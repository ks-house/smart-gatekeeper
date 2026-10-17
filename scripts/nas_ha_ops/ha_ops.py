#!/usr/bin/python3 -I
"""Fixed HA operations over a dedicated forced key; never a general shell."""
from pathlib import Path
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import uuid

ROOT = Path("/usr/local/lib/smart-gatekeeper-ha-ops")
STATE = ROOT/"state"
BROKER_LOG = Path("/volume1/docker/mosquitto/log/mosquitto.log")
COMMANDS = ("status", "diagnose", "refresh-logging", "adopt", "verify", "rollback")
MUTATIONS = set(COMMANDS)-{"status"}
FILES = {"ha_ops.py": "bin/ha_ops.py", "ssh_dispatch.sh": "bin/ssh_dispatch.sh",
         "activate.py": "lib/activate.py", "ha_mqtt_adoption.py": "lib/ha_mqtt_adoption.py"}


def read(path, limit=4*1024*1024):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("root-owned regular control file required")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError("control file bound")
    return raw


def atomic(path, value):
    fd, name = tempfile.mkstemp(prefix=".ha-ops-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def library():
    for path in (ROOT.parent.parent, ROOT.parent, ROOT, ROOT/"bin", ROOT/"lib", STATE):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("protected gateway directory required")
    config = json.loads(read(ROOT/"config.json", 16384))
    if set(config) != {"schema_version", "owner", "plan", "source_hashes",
                       "ha_image", "ha_container_id", "broker_image"} or config["schema_version"] != 1:
        raise ValueError("closed HA gateway configuration required")
    if set(config["source_hashes"]) != set(FILES):
        raise ValueError("exact captured source inventory required")
    for name, relative in FILES.items():
        if hashlib.sha256(read(ROOT/relative, 262144)).hexdigest() != config["source_hashes"][name]:
            raise ValueError("HA operation source drift")
    modules = {}
    for name in ("activate", "ha_mqtt_adoption"):
        spec = importlib.util.spec_from_file_location(name, ROOT/"lib"/(name+".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules[name] = module
        if name == "activate":
            package = types.ModuleType("scripts");package.__path__ = []
            child = types.ModuleType("scripts.nas_broker_ops");child.__path__ = []
            child.activate = module;package.nas_broker_ops = child
            sys.modules.update({"scripts": package, "scripts.nas_broker_ops": child,
                                "scripts.nas_broker_ops.activate": module})
    return config, modules["ha_mqtt_adoption"]


def bindings(config, m):
    ha = m.container()
    broker = m.docker.inspect("mosquitto")
    if (ha["Id"] != config["ha_container_id"] or ha["Image"] != config["ha_image"]
            or broker["Image"] != config["broker_image"]):
        raise ValueError("installed HA/broker identity changed")
    pieces = [m.regular(m.docker.INCOMING/name) for name in
              ("inventory.json", "credentials-new.json", "acl.candidate", "expected.json")]
    if m.digest(b"\0".join(pieces)) != config["plan"]["expected_input_sha256"]:
        raise ValueError("authorized staged identity changed")
    profile, passwords = json.loads(pieces[0]), json.loads(pieces[1])
    identity = {"username": profile["ha_username"], "password": passwords[profile["ha_username"]]}
    return ha, broker, identity


def session():
    path = STATE/"session.json"
    value = json.loads(read(path, 16384)) if path.exists() else None
    if value and not value.get("work") and value.get("started_epoch"):
        private = Path("/volume1/smart-gatekeeper-broker-private")
        candidates = [p for p in private.glob("ha-adopt-*")
                      if (p/"container.json").exists()
                      and (p/"container.json").stat().st_ctime >= value["started_epoch"]]
        if len(candidates) == 1:
            value["work"] = str(candidates[0])
            atomic(path, value)
    return value


def journal(m, value):
    work = Path(value["work"])
    if work.parent != m.PRIVATE or not work.name.startswith("ha-adopt-"):
        raise ValueError("fixed root adoption journal required")
    m.private_directory(work)
    return json.loads(m.regular(work/"journal.json"))


def live_worker(pid, identifier):
    if type(pid) is not int or pid <= 1:
        return False
    try:
        raw = (Path("/proc")/str(pid)/"cmdline").read_bytes()
        return identifier.encode() in raw and b"--worker" in raw and str(ROOT).encode() in raw
    except OSError:
        return False


def status(config, m):
    ha, broker, identity = bindings(config, m)
    raw = m.regular(m.CONFIG)
    entry = m.mqtt_entry(json.loads(raw))
    named = all(entry["data"].get(key) == value for key, value in
                (("username", identity["username"]), ("password", identity["password"]),
                 ("client_id", m.CLIENT_ID)))
    named = named and not any(k in entry["options"] for k in (*m.MANAGED, "broker", "port"))
    result = {"schema_version": 1, "commands": list(COMMANDS), "general_shell": False,
              "ha_running": ha["State"]["Running"], "ha_container_id": ha["Id"],
              "ha_image": ha["Image"], "broker_container_id": broker["Id"],
              "configuration_sha256": m.digest(raw), "staged_ha_identity_installed": named,
              "storage_private": stat.S_IMODE(m.CONFIG.parent.stat().st_mode) == 0o700,
              "configuration_private": stat.S_IMODE(m.CONFIG.stat().st_mode) == 0o600}
    value = session()
    if value and value.get("work"):
        saved = journal(m, value)
        original_entry = m.mqtt_entry(json.loads(m.regular(Path(value["work"])/"original.json")))
        named = named and all(entry["data"].get(k) == original_entry["data"].get(k)
                              for k in ("broker", "port"))
        result["staged_ha_identity_installed"] = named
        result["adoption"] = {"phase": saved.get("phase"),
                              "completed": saved.get("adoption_completed", False),
                              "rollback_confirmed": saved.get("rollback_confirmed", False),
                              "observer_alive": live_worker(value.get("pid"), value["job_id"])}
    for key, filename in (("job", "job.json"), ("verification", "verification.json"),
                          ("diagnostic", "last-diagnostic.json")):
        path = STATE/filename
        if path.exists():
            result[key] = json.loads(read(path, 131072))
    verified = result.get("verification", {})
    policy_ok = False
    current_path = m.docker.STATE/"current.json"
    if current_path.exists():
        current = json.loads(m.regular(current_path))
        evidence = json.loads(m.regular(m.docker.STATE/"stage-evidence.json"))
        active = m.regular(Path(current["active_config_file"]), owner=evidence["broker_uid"])
        policy_ok = (m.digest(active) == verified.get("broker_config_sha256")
                     and current.get("authenticated_policy_installed") is True
                     and re.findall(r"(?m)^\s*allow_anonymous\s+(\w+)", active.decode()) == ["false", "false"])
    result["authenticated_reconnect_verified"] = (
        verified.get("verified") is True and verified.get("broker_id") == broker["Id"]
        and verified.get("broker_started_at") == broker["State"]["StartedAt"] and named
        and policy_ok and result["storage_private"] and result["configuration_private"]
        and ha["State"]["Running"] and broker["State"]["Running"])
    return result


def sanitize(text, identity):
    text = text.replace(identity["password"], "[credential redacted]")
    text = re.sub(r"https?://[^\s]+", "[url redacted]", text)
    text = re.sub(r"gatekeeper/v1/ha-bridge/[^/\s]+", "gatekeeper/v1/ha-bridge/[target]", text)
    return text[:1000]


def diagnose(config, m):
    ha, broker, identity = bindings(config, m)
    result = {"diagnostic_only": True, "settings_changed": False, "containers": {}}
    for name, item in (("homeassistant", ha), ("mosquitto", broker)):
        conn = m.docker.DockerHTTP("localhost", timeout=10)
        try:
            conn.request("GET", "/containers/"+item["Id"]+
                         "/logs?stdout=1&stderr=1&timestamps=1&tail=3000")
            response = conn.getresponse();raw = response.read(4*1024*1024+1)
            if response.status != 200 or len(raw) > 4*1024*1024:
                raise RuntimeError("bounded diagnostic logs unavailable")
        finally:
            conn.close()
        lines = m.docker_log_text(raw).splitlines()
        info = {"running": item["State"]["Running"], "id": item["Id"],
                "started_at": item["State"]["StartedAt"],
                "logging": item["HostConfig"].get("LogConfig"),
                "last_lines": [sanitize(x, identity) for x in lines[-8:]]}
        if name == "mosquitto":
            cmdline = (Path("/proc")/str(item["State"]["Pid"])/"cmdline").read_bytes().split(b"\0")
            info["quiet_argument"] = b"-q" in cmdline or b"--quiet" in cmdline
            info["notice_records"] = sum("New client connected" in x for x in lines)
            info["ha_client_records"] = [sanitize(x, identity) for x in lines if m.CLIENT_ID in x][-6:]
        result["containers"][name] = info
    atomic(STATE/"last-diagnostic.json", result)
    return result


def ensure_broker_log(text, broker, uid, gid):
    destinations = re.findall(r"(?m)^\s*log_dest\s+file\s+(\S+)\s*$", text)
    if not destinations:
        return {"required": False, "created": False}
    if destinations != ["/mosquitto/log/mosquitto.log"]:
        raise ValueError("fixed broker log destination required")
    mounts = [x for x in broker["Mounts"] if x["Destination"] == "/mosquitto/log"]
    if (len(mounts) != 1 or mounts[0]["Source"] != str(BROKER_LOG.parent)
            or not mounts[0].get("RW") or type(uid) is not int or type(gid) is not int
            or uid <= 0 or gid <= 0):
        raise ValueError("bound broker log mount and non-root identity required")
    directory = os.open(str(BROKER_LOG.parent), os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_mode & 0o022:
            raise ValueError("protected broker log directory required")
        created = False
        try:
            descriptor = os.open(BROKER_LOG.name, os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW,
                                 dir_fd=directory)
        except FileNotFoundError:
            descriptor = os.open(BROKER_LOG.name,
                os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600, dir_fd=directory)
            created = True
        try:
            if created:
                os.fchown(descriptor, uid, gid);os.fchmod(descriptor, 0o600);os.fsync(descriptor)
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != uid
                    or info.st_gid != gid or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError("private broker-owned regular log required")
        finally:
            os.close(descriptor)
        return {"required": True, "created": created, "uid": uid, "gid": gid, "mode": "0o600"}
    finally:
        os.close(directory)


def refresh_logging(config, m):
    ha, broker, identity = bindings(config, m)
    plan = dict(config["plan"])
    _, _, binding, _ = m.preflight(plan, prove_observation=False)
    evidence = json.loads(m.regular(m.docker.STATE/"stage-evidence.json"))
    files = {"mosquitto.conf": m.BROKER_CONFIG}
    files.update({name: m.BROKER_CONFIG.parent/name for name in ("cert.pem", "chain.pem", "privkey.pem")})
    captured = {}
    for name, path in files.items():
        saved = evidence["originals"][str(path)]
        raw = m.regular(path, owner=saved["uid"])
        if m.digest(raw) != saved["sha256"]:
            raise ValueError("authorized broker/TLS file changed")
        m.require_container_view(broker["Id"], "/mosquitto/config/"+name, raw, saved["uid"])
        captured[name] = raw
    text = captured["mosquitto.conf"].decode()
    if (re.findall(r"(?m)^\s*allow_anonymous\s+(\w+)", text) != ["true", "true"]
            or re.search(r"(?m)^\s*(password_file|acl_file|include_dir|plugin|auth_plugin)\s", text)):
        raise ValueError("legacy non-auth policy required for logging recovery")
    work = Path(tempfile.mkdtemp(prefix="log-validation-", dir=str(STATE)))
    os.chmod(work, 0o750);os.chown(work, evidence["broker_uid"], evidence["broker_gid"])
    for name, raw in captured.items():
        m.atomic(work/name, raw, uid=evidence["broker_uid"], gid=evidence["broker_gid"])
    command = [m.docker.DOCKER, "run", "--rm", "--read-only", "--network", "none",
               "--user", str(evidence["broker_uid"])+":"+str(evidence["broker_gid"]),
               "-v", str(work)+":/mosquitto/config:ro", "--tmpfs",
               "/mosquitto/log:rw,nosuid,nodev,noexec,uid="+str(evidence["broker_uid"])+
               ",gid="+str(evidence["broker_gid"])+",mode=0700",
               "--entrypoint", "/usr/sbin/mosquitto", broker["Image"],
               "--test-config", "-c", "/mosquitto/config/mosquitto.conf"]
    checked = subprocess.run(command, capture_output=True, timeout=30)
    if checked.returncode:
        raise ValueError("isolated current broker configuration did not validate")
    # A read-only log directory prevents Mosquitto from creating an absent file.
    # Its failed log initialization suppresses connection notices even on stdout.
    # Precreate only the fixed service-owned private file; preserve directory mode.
    log_file = ensure_broker_log(text, broker, evidence["broker_uid"], evidence["broker_gid"])
    # Only reread the already pinned configuration. No config/account/image write.
    m.docker.api("POST", "/containers/"+broker["Id"]+"/kill?signal=HUP")
    time.sleep(1)
    current = m.docker.inspect("mosquitto")
    if (not current["State"]["Running"] or current["Id"] != broker["Id"]
            or current["State"]["StartedAt"] != broker["State"]["StartedAt"]):
        raise RuntimeError("broker did not preserve its running identity after HUP")
    for name, path in files.items():
        if path.read_bytes() != captured[name]:
            raise RuntimeError("broker/TLS bytes changed during bounded reload")
    m.verify_observation(binding)
    return {"broker_hup_sent": True, "same_container_and_start": True,
            "configuration_bytes_changed": False, "credentials_changed": False,
            "fresh_log_notice_verified": True, "ha_stopped": False, "log_file": log_file}


def adopt(config, m, identifier):
    ha, broker, identity = bindings(config, m)
    previous = session()
    if previous and previous.get("work"):
        saved = journal(m, previous)
        if saved.get("adoption_completed") and not saved.get("rollback_confirmed"):
            return {"already_adopted": True, "no_restart": True}
        if live_worker(previous.get("pid"), previous["job_id"]):
            raise ValueError("HA adoption observer is still active")
    plan = dict(config["plan"]);plan["report_key"] = "ha-mqtt-adopt-auto-"+identifier[:12]
    before = set(m.PRIVATE.glob("ha-adopt-*"))
    initial = {"job_id": identifier, "report_key": plan["report_key"],
               "original_broker_id": broker["Id"],
               "expected_input_sha256": plan["expected_input_sha256"],
               "started_epoch": time.time(), "work": None, "pid": None}
    atomic(STATE/"session.json", initial)
    value = m.start_session(plan, apply=True)
    created = set(m.PRIVATE.glob("ha-adopt-*"))-before
    if len(created) != 1:
        raise RuntimeError("one root adoption journal required")
    work = created.pop();m.private_directory(work)
    atomic(STATE/"session.json", {"work": str(work), "report_key": plan["report_key"],
                                 "pid": value["pid"], "job_id": identifier,
                                 "original_broker_id": broker["Id"],
                                 "expected_input_sha256": plan["expected_input_sha256"],
                                 "started_epoch": initial["started_epoch"]})
    return value


def verify(config, m):
    ha, broker, identity = bindings(config, m)
    value = session()
    if not value or not journal(m, value).get("adoption_completed"):
        raise ValueError("root-journaled HA adoption required")
    original = json.loads(m.regular(Path(value["work"])/"container.json"))
    m.same_container(original)
    m.private_directory(m.CONFIG.parent)
    if stat.S_IMODE(m.CONFIG.stat().st_mode) != 0o600:
        raise ValueError("private HA credential file required")
    entry = m.mqtt_entry(json.loads(m.regular(m.CONFIG)))
    previous = m.mqtt_entry(json.loads(m.regular(Path(value["work"])/"original.json")))
    if (any(k in entry["options"] for k in (*m.MANAGED, "broker", "port"))
            or any(entry["data"].get(k) != previous["data"].get(k) for k in ("broker", "port"))
            or entry["data"].get("password") != identity["password"]
            or entry["data"].get("username") != identity["username"]
            or entry["data"].get("client_id") != m.CLIENT_ID):
        raise ValueError("managed HA identity changed")
    current = json.loads(m.regular(m.docker.STATE/"current.json"))
    evidence = json.loads(m.regular(m.docker.STATE/"stage-evidence.json"))
    raw = m.regular(Path(current["active_config_file"]), owner=evidence["broker_uid"])
    binding = m.log_binding(raw.decode(), broker)
    proof = {"original_broker_id": value["original_broker_id"],
             "expected_input_sha256": value["expected_input_sha256"],
             "ha_origin": config["plan"]["ha_origin"]}
    until = time.monotonic()+120
    while time.monotonic() < until:
        if m.verify_cutover(proof, binding, identity):
            result = {"verified": True, "broker_id": broker["Id"],
                      "broker_started_at": broker["State"]["StartedAt"],
                      "broker_config_sha256": m.digest(raw),
                      "verified_at_utc": datetime.now(timezone.utc).isoformat()}
            atomic(STATE/"verification.json", result)
            return result
        time.sleep(1)
    raise RuntimeError("bounded fresh authenticated HA reconnect deadline")


def rollback(config, m):
    ha, broker, identity = bindings(config, m)
    if (m.docker.STATE/"current.json").exists():
        raise ValueError("roll back the authenticated broker before removing the HA account")
    value = session()
    if not value:
        raise ValueError("no root-journaled HA adoption to restore")
    saved = journal(m, value)
    if saved.get("rollback_confirmed"):
        return {"already_rolled_back": True}
    if not saved.get("adoption_completed"):
        raise ValueError("initial adoption is controlled by its existing watchdog")
    original = json.loads(m.regular(Path(value["work"])/"container.json"))
    return m.restore(Path(value["work"]), original, identity)


def busy():
    path = STATE/"job.json"
    if not path.exists():
        return False
    value = json.loads(read(path, 131072))
    return value.get("state") in ("queued", "running") and live_worker(value.get("pid"), value["id"])


def perform(operation, identifier, config, m):
    if operation == "diagnose":
        return diagnose(config, m)
    if operation == "refresh-logging":
        return refresh_logging(config, m)
    if operation == "adopt":
        return adopt(config, m, identifier)
    if operation == "verify":
        return verify(config, m)
    if operation == "rollback":
        return rollback(config, m)
    raise ValueError("unsupported fixed HA action")


def worker(operation, identifier, config, m):
    # Release the queue lock before HA's existing helper forks its own observer.
    with (STATE/"maintenance.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        atomic(STATE/"job.json", {"id": identifier, "operation": operation,
                                 "pid": os.getpid(), "state": "running"})
    try:
        signal.signal(signal.SIGALRM, lambda *args: (_ for _ in ()).throw(
            TimeoutError("bounded HA maintenance deadline")))
        signal.alarm(210)
        result = perform(operation, identifier, config, m)
        signal.alarm(0)
        value = {"id": identifier, "operation": operation, "state": "success", "result": result}
    except Exception as error:
        signal.alarm(0)
        value = {"id": identifier, "operation": operation, "state": "failed",
                 "error_type": type(error).__name__, "message": str(error)}
        atomic(STATE/"last-error.json", value)
    atomic(STATE/"job.json", value)


def main():
    if os.geteuid() != 0:
        raise SystemExit("root HA gateway required")
    config, m = library()
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        operation, identifier = sys.argv[2:]
        if operation not in MUTATIONS or re.fullmatch(r"[a-f0-9]{32}", identifier) is None:
            raise SystemExit("invalid internal HA worker")
        worker(operation, identifier, config, m)
        return
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit("unsupported HA operation")
    operation = sys.argv[1]
    if operation == "status":
        value = status(config, m)
    else:
        with (STATE/"maintenance.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if busy():
                raise RuntimeError("HA operation already running")
            identifier = uuid.uuid4().hex
            fd = os.open(str(STATE/("worker-"+identifier+".log")),
                         os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
            try:
                process = subprocess.Popen([sys.executable, "-I", str(ROOT/"bin/ha_ops.py"),
                    "--worker", operation, identifier], stdin=subprocess.DEVNULL,
                    stdout=fd, stderr=fd, start_new_session=True, close_fds=True)
            finally:
                os.close(fd)
            value = {"id": identifier, "operation": operation, "state": "queued", "pid": process.pid}
            atomic(STATE/"job.json", value)
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__, "message": str(error)}))
        raise SystemExit(1)
