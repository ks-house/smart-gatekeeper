#!/usr/bin/python3 -I
"""Signed privileged maintenance. The signer authorizes root Python code."""
from pathlib import Path
import base64
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path("/usr/local/lib/smart-gatekeeper-maintenance")
STATE = ROOT/"state"
COMMANDS = ("status", "submit", "result")
FILES = {"gateway.py": "bin/gateway.py", "ssh_dispatch.sh": "bin/ssh_dispatch.sh",
         "signer-public.pem": "security/signer-public.pem"}
MAX_ENVELOPE = 524288
MAX_SCRIPT = 262144
MAX_OUTPUT = 65536


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def control(path, limit=MAX_ENVELOPE):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("root-owned regular maintenance control required")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError("maintenance control bound")
    return raw


def atomic(path, raw):
    fd, name = tempfile.mkstemp(prefix=".maintenance-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(path, value):
    atomic(path, json.dumps(value, sort_keys=True).encode())


def configuration():
    for path in (ROOT.parent.parent, ROOT.parent, ROOT, ROOT/"bin", ROOT/"security", STATE):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("protected maintenance directory required")
    value = json.loads(control(ROOT/"config.json", 16384))
    if (set(value) != {"schema_version", "owner", "source_hashes", "openssl_path"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or set(value["source_hashes"]) != set(FILES)):
        raise ValueError("closed maintenance configuration required")
    for name, path in FILES.items():
        if digest(control(ROOT/path)) != value["source_hashes"][name]:
            raise ValueError("maintenance source or signer drift")
    binary = Path(value["openssl_path"])
    info = binary.lstat()
    if (not binary.is_absolute() or not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022 or not os.access(str(binary), os.X_OK)):
        raise ValueError("trusted OpenSSL binary required")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def validate(raw, config, now=None):
    if len(raw) > MAX_ENVELOPE:
        raise ValueError("signed maintenance input bound")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"manifest", "script", "signature"}:
        raise ValueError("closed signed maintenance envelope required")
    manifest = value["manifest"]
    fields = {"schema_version", "request_id", "operation", "script_sha256",
              "issued_at", "expires_at", "timeout_seconds"}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        raise ValueError("closed signed maintenance manifest required")
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or re.fullmatch(r"[a-f0-9]{32}", manifest["request_id"]) is None
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", manifest["operation"]) is None
            or re.fullmatch(r"[a-f0-9]{64}", manifest["script_sha256"]) is None):
        raise ValueError("bounded signed operation identity required")
    for name in ("issued_at", "expires_at", "timeout_seconds"):
        if type(manifest[name]) is not int:
            raise ValueError("integer maintenance time bounds required")
    epoch = int(time.time()) if now is None else now
    if (not 0 < manifest["expires_at"]-manifest["issued_at"] <= 900
            or manifest["issued_at"] > epoch+60 or epoch > manifest["expires_at"]
            or not 1 <= manifest["timeout_seconds"] <= 900):
        raise ValueError("maintenance authorization expired or outside bounds")
    script = base64.b64decode(value["script"], validate=True)
    signature = base64.b64decode(value["signature"], validate=True)
    if (not script or len(script) > MAX_SCRIPT or len(signature) != 384
            or digest(script) != manifest["script_sha256"]):
        raise ValueError("signed maintenance content mismatch")
    with tempfile.TemporaryDirectory(prefix="signature-", dir=str(STATE)) as tmp:
        directory = Path(tmp)
        atomic(directory/"manifest.json", canonical(manifest))
        atomic(directory/"signature.bin", signature)
        result = subprocess.run([config["openssl_path"], "dgst", "-sha256", "-verify",
            str(ROOT/"security/signer-public.pem"), "-signature", str(directory/"signature.bin"),
            str(directory/"manifest.json")], capture_output=True, timeout=10, env={"PATH": "/usr/bin:/bin", "LANG": "C"})
    if result.returncode:
        raise ValueError("maintenance signature rejected")
    compile(script, "<signed-maintenance>", "exec")
    return manifest, script


def job_path(identifier):
    if re.fullmatch(r"[a-f0-9]{32}", identifier) is None:
        raise ValueError("fixed maintenance request identity required")
    return STATE/"requests"/identifier


def live(value):
    if value.get("state") not in ("queued", "running") or type(value.get("pid")) is not int:
        return False
    try:
        raw = (Path("/proc")/str(value["pid"])/"cmdline").read_bytes()
        return (str(ROOT/"bin/gateway.py").encode() in raw
                and b"--worker" in raw and value["id"].encode() in raw)
    except OSError:
        return False


def latest():
    path = STATE/"latest.json"
    if not path.exists():
        return None
    pointer = json.loads(control(path, 4096))
    return json.loads(control(job_path(pointer["id"])/"job.json", 8192))


def status(config):
    value = {"schema_version": 1, "installed": True, "commands": list(COMMANDS),
             "interactive_shell": False, "signed_root_code_execution": True,
             "signer_sha256": config["source_hashes"]["signer-public.pem"]}
    current = latest()
    if current:
        value["job"] = current
        value["worker_alive"] = live(current)
    return value


def launch_worker(identifier, descriptor):
    return subprocess.Popen([sys.executable, "-I", str(ROOT/"bin/gateway.py"),
        "--worker", identifier], stdin=subprocess.DEVNULL, stdout=descriptor,
        stderr=descriptor, start_new_session=True, close_fds=True)


def submit(raw, config):
    manifest, script = validate(raw, config)
    identifier = manifest["request_id"];directory = job_path(identifier)
    envelope_sha = digest(raw)
    with (STATE/"queue.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        if directory.exists():
            old = json.loads(control(directory/"job.json", 8192))
            if old["envelope_sha256"] != envelope_sha:
                raise ValueError("maintenance request identity collision")
            return {**old, "idempotent": True}
        current = latest()
        if current and live(current):
            raise RuntimeError("maintenance request already running")
        directory.mkdir(mode=0o700)
        atomic(directory/"envelope.json", raw)
        atomic(directory/"script.py", script)
        value = {"id": identifier, "operation": manifest["operation"], "state": "queued",
                 "script_sha256": manifest["script_sha256"], "envelope_sha256": envelope_sha,
                 "authorized_expires_at": manifest["expires_at"]}
        save(directory/"job.json", value);save(STATE/"latest.json", {"id": identifier})
        descriptor = os.open(str(directory/"worker.log"), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        try:
            process = launch_worker(identifier, descriptor)
        finally:
            os.close(descriptor)
        value["pid"] = process.pid;save(directory/"job.json", value)
    return value


def execute(directory, manifest):
    stdout = directory/"stdout.private";stderr = directory/"stderr.private"
    with stdout.open("wb") as out, stderr.open("wb") as error:
        os.chmod(stdout, 0o600);os.chmod(stderr, 0o600)
        process = subprocess.Popen([sys.executable, "-I", "-B", str(directory/"script.py")],
            stdin=subprocess.DEVNULL, stdout=out, stderr=error, start_new_session=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/syno/bin:/usr/sbin:/sbin",
                 "LANG": "C.UTF-8", "HOME": "/root"})
        timeout = False
        try:
            code = process.wait(timeout=manifest["timeout_seconds"])
        except subprocess.TimeoutExpired:
            timeout = True
            try:os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:pass
            code = process.wait(timeout=10)
    info = {"returncode": code, "timed_out": timeout,
            "stdout_bytes": stdout.stat().st_size, "stderr_bytes": stderr.stat().st_size}
    if not timeout and code == 0 and stdout.stat().st_size <= MAX_OUTPUT:
        try:
            value = json.loads(stdout.read_bytes())
            if not isinstance(value, dict):
                raise ValueError("object receipt required")
            save(directory/"result.json", value);info["json_result_available"] = True
        except ValueError:
            info["json_result_available"] = False
    return info


def worker(identifier, config):
    directory = job_path(identifier)
    with (STATE/"queue.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = json.loads(control(directory/"job.json", 8192))
        value.update(state="running", pid=os.getpid(), started_at=int(time.time()))
        save(directory/"job.json", value)
    try:
        manifest, script = validate(control(directory/"envelope.json"), config)
        if control(directory/"script.py", MAX_SCRIPT) != script:
            raise ValueError("captured maintenance script drift")
        result = execute(directory, manifest)
        value.update(state="success" if result["returncode"] == 0 and not result["timed_out"] else "failed",
                     finished_at=int(time.time()), **result)
    except Exception as error:
        value.update(state="failed", finished_at=int(time.time()), error_type=type(error).__name__)
    save(directory/"job.json", value)


def main():
    if os.geteuid() != 0:
        raise SystemExit("root signed maintenance gateway required")
    config = configuration()
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(sys.argv[2], config);return
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit("unsupported signed maintenance operation")
    if sys.argv[1] == "status":
        value = status(config)
    elif sys.argv[1] == "submit":
        signal.signal(signal.SIGALRM, lambda *args: (_ for _ in ()).throw(TimeoutError()))
        signal.alarm(20)
        value = submit(sys.stdin.buffer.read(MAX_ENVELOPE+1), config)
        signal.alarm(0)
    else:
        current = latest()
        value = {"job": current}
        if current:
            path = job_path(current["id"])/"result.json"
            if path.exists():
                value["result"] = json.loads(control(path, MAX_OUTPUT))
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__}))
        raise SystemExit(1)
