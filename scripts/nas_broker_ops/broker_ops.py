#!/usr/bin/python3 -I
"""Root-owned, fixed-command NAS broker gateway. No shell or arbitrary file API."""
from pathlib import Path
import hashlib
import fcntl
import signal
import time
import uuid
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path("/usr/local/lib/smart-gatekeeper-broker-ops")
INCOMING = ROOT/"incoming"
STATE = ROOT/"state"
DOCKER = "/usr/local/bin/docker"
CONFIG = Path("/volume1/docker/mosquitto/config/mosquitto.conf")
RUNTIME = Path("/volume1/docker/smart-gatekeeper-backend/runtime.env")
COMMANDS = {"status", "receive", "stage", "apply", "rollback", "diagnose"}
MAX_INPUT = 131072


def load_module(name):
    path = ROOT/"lib"/(name+".py")
    info = path.stat()
    if info.st_uid != 0 or info.st_mode & 0o022 or path.is_symlink():
        raise RuntimeError("unsafe maintenance module")
    spec = importlib.util.spec_from_file_location("sgk_"+name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def atomic(path, content, mode=0o600):
    descriptor, name = tempfile.mkstemp(prefix=".incoming-", dir=str(path.parent))
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def receive(raw):
    if len(raw) > MAX_INPUT:
        raise ValueError("input byte bound")
    data = json.loads(raw)
    if (not isinstance(data, dict) or set(data) !=
            {"schema_version", "inventory", "credentials", "expected_versions"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1):
        raise ValueError("exact maintenance input required")
    renderer = load_module("render_broker_acl")
    rendered = renderer.render_acl(data["inventory"])
    profile = data["inventory"]
    if len(profile["targets"]) != 1 or len(profile["diagnostic_usernames"]) != 1:
        raise ValueError("installed personal gateway requires one Target and one diagnostic identity")
    if profile["schema_version"] != 2:
        raise ValueError("this installed gateway requires shared schema2")
    runtime = {}
    for line in RUNTIME.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            runtime[key] = value
    if (profile["backend_username"] != runtime.get("MQTT_USER") or
            runtime.get("COMMAND_TARGET_ID") not in profile["targets"]):
        raise ValueError("operating Backend/Target identity must be preserved")
    names = {*profile["targets"], profile["ha_username"], *profile["diagnostic_usernames"],
             *profile["smartbox"].values()}
    values = data["credentials"]
    if (not isinstance(values, dict) or set(values) != names or
            any(not isinstance(v, str) or re.fullmatch(r"[a-f0-9]{64}", v) is None
                for v in values.values())):
        raise ValueError("exact bounded new credentials required")
    active = STATE/"current.json"
    if active.exists():
        current = json.loads(active.read_text())
        old_policy = Path(current["stage_root"])/"policy"
        old_profile = json.loads((old_policy/"inventory.json").read_text())
        old_values = json.loads((old_policy/"credentials.json").read_text())
        device_names = [*profile["targets"], profile["smartbox"]["device_username"]]
        if (profile["smartbox"]["device_username"] != old_profile["smartbox"]["device_username"] or
                any(values.get(key) != old_values.get(key) for key in device_names)):
            raise ValueError("device credential rotation needs a separate compatible rollback plan")
    versions = data["expected_versions"]
    if versions is not None and (
            not isinstance(versions, dict) or set(versions) != {"target", "smartbox"} or
            any(not isinstance(v, str) or re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", v) is None
                for v in versions.values())):
        raise ValueError("exact installed-version expectations required")
    old = hashlib.sha256(b"").hexdigest()
    if (INCOMING/"inventory.json").exists() and (INCOMING/"credentials-new.json").exists():
        old = input_hash()
    bundles = INCOMING.parent/"bundles"
    bundles.mkdir(mode=0o700,exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="input-",dir=str(bundles)))
    contents = {"inventory.json":json.dumps(profile,sort_keys=True),
                "credentials-new.json":json.dumps(values,sort_keys=True),
                "acl.candidate":rendered,
                "expected.json":json.dumps(versions,sort_keys=True)}
    for name,content in contents.items():
        atomic(destination/name,content)
    pointer = INCOMING.parent/(".input-pointer-"+uuid.uuid4().hex)
    try:
        os.symlink(str(destination),str(pointer))
        os.replace(str(pointer),str(INCOMING))
    finally:
        if pointer.is_symlink():pointer.unlink()
    new = input_hash()
    if old != new and (STATE/"stage-evidence.json").exists():
        (STATE/"stage-evidence.json").unlink()
    return {"received": True, "input_sha256": new, "credentials_printed": False,
            "operating_broker_changed": False}


def input_hash():
    return hashlib.sha256(b"\0".join((INCOMING/name).read_bytes() for name in
                          ("inventory.json","credentials-new.json","acl.candidate","expected.json"))).hexdigest()


def docker(*arguments):
    result = subprocess.run([DOCKER, *arguments], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30)
    if result.returncode:
        raise RuntimeError("bounded Docker metadata query failed")
    return result.stdout.decode("utf-8")


def status():
    live = CONFIG
    if (STATE/"current.json").exists():
        live = Path(json.loads((STATE/"current.json").read_text())["active_config_file"])
    configuration = live.read_text()
    states = {}
    for name in ("mosquitto", "telegraf", "smart-gatekeeper-production-api-1"):
        states[name] = json.loads(docker("inspect", "--format",
            '{"state":{{json .State.Status}},"image":{{json .Image}}}', name))
    result = {"schema_version": 1, "commands": sorted(COMMANDS),
              "containers": states, "broker_config_sha256":
                  hashlib.sha256(live.read_bytes()).hexdigest(),
              "anonymous_directives": re.findall(r"(?m)^\s*allow_anonymous\s+(\w+)", configuration),
              "password_policy": bool(re.search(r"(?m)^\s*password_file\s+", configuration)),
              "acl_policy": bool(re.search(r"(?m)^\s*acl_file\s+", configuration))}
    for field, filename in (("stage", "stage-evidence.json"), ("current", "current.json"),
                            ("last_error", "last-error.json"), ("job", "job.json"), ("setup", "setup.json")):
        path = STATE/filename
        if path.exists():
            result[field] = json.loads(path.read_text())
    return result



def alive(pid):
    if type(pid) is not int or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def busy():
    path = STATE/"job.json"
    if not path.exists():
        return False
    job = json.loads(path.read_text())
    if job.get("state") not in ("queued", "running") or not alive(job.get("pid", -1)):
        return False
    try:
        command = Path("/proc")/str(job["pid"])/"cmdline"
        return job.get("id", "").encode() in command.read_bytes() and b"--worker" in command.read_bytes()
    except OSError:
        return False


def perform(command):
    if command == "stage":
        path = STATE/"stage-evidence.json"
        if path.exists():
            path.unlink()
        module = load_module("stage")
        try:
            module.main()
        except Exception:
            if module.LAST_ERROR:
                atomic(STATE/"last-query-error.json", json.dumps(module.LAST_ERROR))
            raise
        return {"private_candidate_staged": True,
                "validation": json.loads(path.read_text())["validation"]}
    module = load_module("activate")
    return module.activate() if command == "apply" else module.rollback()


def worker(command, identifier):
    with (STATE/"maintenance.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        atomic(STATE/"job.json", json.dumps(
            {"id": identifier, "operation": command, "pid": os.getpid(), "state": "running"}))
        try:
            signal.signal(signal.SIGALRM, lambda *args: (_ for _ in ()).throw(
                TimeoutError("bounded maintenance deadline")))
            signal.alarm(300)
            result = perform(command)
            signal.alarm(0)
            job = {"id": identifier, "operation": command, "state": "success", "result": result}
        except Exception as error:
            signal.alarm(0)
            message = {"operation": command, "error_type": type(error).__name__, "message": str(error)}
            atomic(STATE/"last-error.json", json.dumps(message))
            job = {"id": identifier, "operation": command, "state": "failed", **message}
        atomic(STATE/"job.json", json.dumps(job))
        return job


def main():
    if os.geteuid() != 0:
        raise SystemExit("root gateway required")
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        command, identifier = sys.argv[2:]
        if command not in {"stage", "apply", "rollback"} or re.fullmatch(r"[a-f0-9]{32}", identifier) is None:
            raise SystemExit("invalid internal worker")
        worker(command, identifier)
        return
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit("unsupported maintenance command")
    command = sys.argv[1]
    try:
        if command == "status":
            result = status()
        elif command == "diagnose":
            result = {}
            for filename in ("last-error.json", "last-query-error.json",
                             "last-observe-error.json", "stage-error.json",
                             "last-activation-diagnostic.json", "last-activation-diagnostic-error.json"):
                path = STATE/filename
                if path.exists():
                    result[filename] = json.loads(path.read_text())
        else:
            with (STATE/"maintenance.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if busy():
                    raise RuntimeError("maintenance operation already running")
                if command == "receive":
                    signal.signal(signal.SIGALRM, lambda *args: (_ for _ in ()).throw(
                        TimeoutError("maintenance input deadline")))
                    signal.alarm(15)
                    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
                    signal.alarm(0)
                    result = receive(raw)
                else:
                    identifier = uuid.uuid4().hex
                    output = STATE/("worker-" + identifier + ".log")
                    descriptor = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as stream:
                        process = subprocess.Popen(
                            ["/usr/bin/python3", "-I", str(Path(__file__).resolve()),
                             "--worker", command, identifier],
                            stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                            start_new_session=True, close_fds=True)
                    atomic(STATE/"job.json", json.dumps(
                        {"id": identifier, "operation": command, "pid": process.pid, "state": "queued"}))
                    result = {"job_started": identifier, "operation": command,
                              "detached_from_ssh": True}
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        atomic(STATE/"last-error.json", json.dumps(
            {"operation": command, "error_type": type(error).__name__, "message": str(error)}))
        print(json.dumps({"operation_failed": command, "private_diagnostics_available": True}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
