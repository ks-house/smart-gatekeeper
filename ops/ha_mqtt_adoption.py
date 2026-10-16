#!/usr/bin/env python3
"""Bounded HA MQTT adoption; existing image/key/broker policy are preserved."""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import signal
import ssl
import stat
import tempfile
import time
import urllib.parse
import urllib.request
try:
    from scripts.nas_broker_ops import activate as docker
except ImportError:
    import activate as docker

HA = "homeassistant"
CONFIG = Path("/volume1/docker/homeassistant/.storage/core.config_entries")
PRIVATE = Path("/volume1/smart-gatekeeper-broker-private")
REPORTS = Path("/var/run/sgk-broker-audit")
BROKER_CONFIG = Path("/volume1/docker/mosquitto/config/mosquitto.conf")
CLIENT_ID = "homeassistant-sgk-20261016"
MANAGED = ("username", "password", "client_id")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path, limit=4*1024*1024):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise ValueError("root-owned regular configuration required")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError("configuration byte bound")
    return raw


def private_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("root-private directory required")


def atomic(path, raw, mode=0o600, uid=0, gid=0):
    fd, name = tempfile.mkstemp(prefix=".ha-adopt-", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def mqtt_entry(document):
    entries = document.get("data", {}).get("entries", [])
    matches = [x for x in entries if x.get("domain") == "mqtt"]
    if len(matches) != 1:
        raise ValueError("one existing MQTT entry required")
    entry = matches[0]
    if (entry.get("disabled_by") is not None or entry.get("version") != 2
            or entry.get("minor_version") != 1):
        raise ValueError("enabled reviewed MQTT schema2.1 required")
    if not isinstance(entry.get("data"), dict) or not isinstance(entry.get("options"), dict):
        raise ValueError("reviewed MQTT entry structure required")
    return entry


def candidate(raw, identity):
    document = json.loads(raw)
    entry = mqtt_entry(document)
    if any(entry["data"].get(k) is not None or k in entry["options"] for k in MANAGED):
        raise ValueError("existing managed MQTT settings require separate review")
    if entry["data"].get("port") != 1883 or not entry["data"].get("broker"):
        raise ValueError("existing LAN listener required")
    entry["data"].update(username=identity["username"], password=identity["password"],
                         client_id=CLIENT_ID)
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()


def rollback_content(current, original, proposed):
    before = json.loads(original)
    expected = json.loads(proposed)
    now = json.loads(current)
    if now == before:
        return original
    current_entry = mqtt_entry(now)
    wanted = mqtt_entry(expected)
    previous = mqtt_entry(before)
    if current_entry["entry_id"] != previous["entry_id"]:
        raise ValueError("MQTT entry identity changed")
    if any(current_entry["data"].get(k) != wanted["data"].get(k)
           or k in current_entry["options"] for k in MANAGED):
        raise ValueError("concurrent MQTT identity prevents rollback")
    if now == expected:
        return original
    # Preserve unrelated HA changes instead of replacing their full storage file.
    for key in MANAGED:
        if key in previous["data"]:
            current_entry["data"][key] = previous["data"][key]
        else:
            current_entry["data"].pop(key, None)
    return json.dumps(now, ensure_ascii=False, separators=(",", ":")).encode()


def container():
    value = docker.inspect(HA)
    mounts = [m for m in value["Mounts"] if m["Destination"] == "/config"]
    if (value["Name"] != "/"+HA or len(mounts) != 1
            or Path(mounts[0]["Source"]).resolve() != CONFIG.parent.parent.resolve()
            or not mounts[0].get("RW") or value["HostConfig"]["NetworkMode"] != "host"
            or value["HostConfig"].get("AutoRemove") is not False
            or value["Config"].get("User", "") not in ("", "0", "0:0", "root")):
        raise ValueError("reviewed existing root HA container required")
    return value


def same_container(original):
    value = container()
    if value["Id"] != original["Id"] or value["Image"] != original["Image"]:
        raise ValueError("HA container/image changed")
    return value


def stopped(original):
    value = same_container(original)
    if value["State"]["Running"]:
        docker.api("POST", "/containers/"+original["Id"]+"/stop?t=30")
    if same_container(original)["State"]["Running"]:
        raise RuntimeError("HA did not stop")


def started(original):
    value = same_container(original)
    if not value["State"]["Running"]:
        docker.api("POST", "/containers/"+original["Id"]+"/start")


def http_ready(origin):
    context = ssl.create_default_context()
    with urllib.request.urlopen(origin, timeout=8, context=context) as response:
        return response.status == 200


def log_binding(configuration, broker):
    if re.search(r"(?m)^\s*connection_messages\s+false\s*$", configuration):
        raise ValueError("broker connection observation disabled")
    files = re.findall(r"(?m)^\s*log_dest\s+file\s+(\S+)\s*$", configuration)
    if len(files) > 1:
        raise ValueError("one bounded broker log required")
    if not files:
        return {"docker": True}
    target = Path(files[0])
    if not target.is_absolute() or ".." in target.parts:
        raise ValueError("absolute fixed broker log required")
    mounts = [m for m in broker["Mounts"] if target == Path(m["Destination"])
              or Path(m["Destination"]) in target.parents]
    if len(mounts) != 1:
        raise ValueError("broker log mount is ambiguous")
    mount = mounts[0]
    path = Path(mount["Source"])/target.relative_to(mount["Destination"])
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular broker log required")
    return {"path": str(path.resolve()), "offset": path.stat().st_size,
            "inode": path.stat().st_ino}


def docker_log_text(raw):
    if raw[:4] not in (b"\x01\x00\x00\x00", b"\x02\x00\x00\x00"):
        return raw.decode("utf-8", "replace")
    parts = []
    while raw:
        if len(raw) < 8 or raw[:4] not in (b"\x01\x00\x00\x00", b"\x02\x00\x00\x00"):
            raise ValueError("invalid Docker log frame")
        length = int.from_bytes(raw[4:8], "big")
        if length > len(raw)-8:
            raise ValueError("truncated Docker log frame")
        parts.append(raw[8:8+length])
        raw = raw[8+length:]
    return b"".join(parts).decode("utf-8", "replace")


def log_data(binding, since):
    if "path" in binding:
        path = Path(binding["path"])
        info = path.stat()
        offset = binding["offset"] if info.st_ino == binding["inode"] else 0
        with path.open("rb") as stream:
            stream.seek(max(offset if offset <= info.st_size else 0, info.st_size-262144))
            return stream.read(262144).decode("utf-8", "replace")
    conn = docker.DockerHTTP("localhost", timeout=10)
    try:
        conn.request("GET", "/containers/mosquitto/logs?stdout=1&stderr=1&tail=200&since="+str(int(since)))
        response = conn.getresponse()
        raw = response.read(262145)
        if response.status != 200 or len(raw) > 262144:
            raise RuntimeError("bounded broker log query failed")
        return docker_log_text(raw)
    finally:
        conn.close()


def named_connection(text, username, since):
    pattern = (r"(?m)(?:^|[\x00-\x1f])([0-9]{9,12}): New client connected from "
               r"[^\r\n]* as "+re.escape(CLIENT_ID)+r" \([^\r\n]*u'"
               +re.escape(username)+r"'\)\.")
    return any(int(match.group(1)) >= int(since) for match in re.finditer(pattern, text))


def preflight(plan):
    fields = {"expected_config_sha256", "expected_input_sha256",
              "expected_broker_config_sha256", "report_key", "report_owner", "ha_origin"}
    if os.geteuid() != 0 or not isinstance(plan, dict) or set(plan) != fields:
        raise ValueError("root and exact captured HA plan required")
    if any(re.fullmatch(r"[a-f0-9]{64}", plan[k]) is None for k in fields if k.startswith("expected_")):
        raise ValueError("captured digest required")
    if re.fullmatch(r"ha-mqtt-adopt-[a-z0-9-]{8,40}", plan["report_key"]) is None:
        raise ValueError("fixed HA report key required")
    parsed = urllib.parse.urlsplit(plan["ha_origin"])
    if (parsed.scheme != "https" or parsed.port != 4123 or parsed.path != "/"
            or parsed.query or parsed.fragment or parsed.username is not None):
        raise ValueError("fixed HTTPS HA route required")
    private_directory(PRIVATE)
    storage = CONFIG.parent.lstat()
    mounted = CONFIG.parent.parent.lstat()
    # Synology's mounted share belongs to its operator. Only the credential
    # storage must belong to root; the exact parent bind is checked below.
    if (not stat.S_ISDIR(storage.st_mode) or storage.st_uid != 0
            or not stat.S_ISDIR(mounted.st_mode)):
        raise ValueError("root-owned real HA storage and real mounted directory required")
    raw = regular(CONFIG)
    if digest(raw) != plan["expected_config_sha256"]:
        raise ValueError("HA configuration drift")
    incoming = docker.INCOMING
    pieces = [regular(incoming/name) for name in
              ("inventory.json", "credentials-new.json", "acl.candidate", "expected.json")]
    if digest(b"\0".join(pieces)) != plan["expected_input_sha256"]:
        raise ValueError("staged input drift")
    evidence = json.loads(regular(docker.STATE/"stage-evidence.json"))
    if (evidence["input_sha256"] != plan["expected_input_sha256"]
            or evidence["validation"]["isolated_auth_cases"] != 16):
        raise ValueError("matching isolated authentication candidate required")
    profile = json.loads(pieces[0]);values = json.loads(pieces[1])
    identity = {"username": profile["ha_username"], "password": values[profile["ha_username"]]}
    if (re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity["username"]) is None
            or re.fullmatch(r"[a-f0-9]{64}", identity["password"]) is None):
        raise ValueError("staged distinct HA identity required")
    settings = json.loads(regular(docker.OPS/"config.json"))
    ready_host = urllib.parse.urlsplit(settings["readiness_url"]).hostname
    if parsed.hostname != ready_host or settings["owner"] != plan["report_owner"]:
        raise ValueError("reviewed NAS origin/owner required")
    live = BROKER_CONFIG
    if (docker.STATE/"current.json").exists():
        live = Path(json.loads(regular(docker.STATE/"current.json"))["active_config_file"])
    config = regular(live)
    if digest(config) != plan["expected_broker_config_sha256"]:
        raise ValueError("broker configuration drift")
    original = container()
    if not original["State"]["Running"]:
        raise ValueError("existing HA must already be running")
    top = docker.api("GET", "/containers/"+original["Id"]+"/top?ps_args=-eo%20uid,comm")
    python_rows = [row for row in top["Processes"] if row[-1] in ("python", "python3")]
    if not python_rows or any(row[0] != "0" for row in python_rows):
        raise ValueError("actual HA Python root identity required for private storage")
    candidate(raw, identity)
    binding = log_binding(config.decode(), docker.inspect("mosquitto"))
    return original, identity, binding, raw


def report(path, owner, value):
    atomic(path, json.dumps(value, sort_keys=True).encode(), uid=owner.pw_uid, gid=owner.pw_gid)


def journal(work, value):
    atomic(work/"journal.json", json.dumps(value, sort_keys=True).encode())


def restore(work, original, identity):
    saved = json.loads(regular(work/"journal.json"))
    stopped(original)
    try:
        previous = regular(work/"original.json")
        current = regular(CONFIG)
        proposed_path = work/"candidate.json"
        if proposed_path.exists():
            restored = rollback_content(current, previous, regular(proposed_path))
            atomic(CONFIG, restored, saved["file_mode"], saved["file_uid"], saved["file_gid"])
            # Restore broad original access only after the new credential is removed.
            os.chmod(CONFIG.parent, saved["directory_mode"])
    finally:
        started(original)
    if not same_container(original)["State"]["Running"]:
        raise RuntimeError("restored HA container did not remain running")
    saved.update(rollback_confirmed=True)
    journal(work, saved)
    return {"rollback_confirmed": True, "original_container_running": True}


def adopt(work, original, identity, binding, origin, notify):
    if digest(regular(CONFIG)) != digest(regular(work/"original.json")):
        raise ValueError("HA configuration changed before stop")
    saved = json.loads(regular(work/"journal.json"))
    try:
        stopped(original)
        # HA may flush unrelated entries on stop. Preserve that exact final snapshot.
        raw = regular(CONFIG)
        proposed = candidate(raw, identity)
        atomic(work/"original.json", raw)
        atomic(work/"candidate.json", proposed)
        saved.update(phase="stopped")
        journal(work, saved)
        os.chmod(CONFIG.parent, 0o700)
        atomic(CONFIG, proposed)
        saved.update(phase="identity_installed")
        journal(work, saved)
        start_epoch = time.time()
        started(original)
        deadline = time.monotonic()+150
        while time.monotonic() < deadline:
            live = same_container(original)
            if (live["State"]["Running"]
                    and named_connection(log_data(binding, start_epoch), identity["username"], start_epoch)):
                try:
                    if http_ready(origin):
                        current_entry = mqtt_entry(json.loads(regular(CONFIG)))
                        wanted = mqtt_entry(json.loads(proposed))
                        if (any(current_entry["data"].get(k) != wanted["data"].get(k)
                                or k in current_entry["options"] for k in MANAGED)
                                or any(current_entry["data"].get(k) != wanted["data"].get(k)
                                       for k in ("broker", "port"))):
                            raise ValueError("HA rewrote managed connection settings")
                        os.chmod(CONFIG, 0o600)
                        private_directory(CONFIG.parent)
                        saved.update(phase="adoption_complete", adoption_completed=True)
                        journal(work, saved)
                        return {"ha_named_connection_observed": True, "ha_http_ready": True,
                                "private_storage_verified": True, "same_container_and_image": True,
                                "broker_authentication_proven": False}
                except (OSError, TimeoutError):
                    pass
            time.sleep(1)
        raise RuntimeError("bounded HA named reconnect/readiness deadline")
    except BaseException:
        result = restore(work, original, identity)
        notify({"state": "rolled_back", **result})
        raise


def verify_cutover(state, binding, identity):
    current = json.loads(regular(docker.STATE/"current.json"))
    config = regular(Path(current["active_config_file"])).decode()
    if (current.get("authenticated_policy_installed") is not True
            or re.findall(r"(?m)^\s*allow_anonymous\s+(\w+)", config) != ["false", "false"]):
        raise ValueError("operating authenticated broker required")
    if digest(config.encode()) != current["current_config_sha256"]:
        raise ValueError("operating broker hash changed")
    evidence = json.loads(regular(docker.STATE/"stage-evidence.json"))
    if (current["stage_root"] != evidence["stage_root"]
            or evidence["input_sha256"] != state["expected_input_sha256"]):
        raise ValueError("authenticated broker stage binding changed")
    broker = docker.inspect("mosquitto")
    if broker["Id"] == state["original_broker_id"]:
        raise ValueError("new broker session eviction not observed")
    started_at = datetime.fromisoformat(broker["State"]["StartedAt"][:26]+"+00:00").timestamp()
    if not named_connection(log_data(binding, started_at), identity["username"], started_at):
        return False
    return http_ready(state["ha_origin"])


def watchdog_recover(work, original, identity, worker, response, owner, state):
    saved = json.loads(regular(work/"journal.json"))
    if saved.get("adoption_completed") or saved.get("rollback_confirmed"):
        return False
    try:os.kill(worker, signal.SIGKILL)
    except ProcessLookupError:pass
    result = restore(work, original, identity)
    report(response, owner, {**state, "state": "watchdog_rollback", **result})
    return True


def start_session(plan, apply=False):
    original, identity, binding, raw = preflight(plan)
    if not apply:
        return {"validated": True, "operating_configuration_changed": False}
    owner = pwd.getpwnam(plan["report_owner"])
    info = REPORTS.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("protected receipt directory required")
    response = REPORTS/(plan["report_key"]+".json")
    if response.exists() or response.is_symlink():
        raise ValueError("HA adoption report already exists")
    lock = os.open(str(PRIVATE/"ha-mqtt-adoption.lock"), os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    work = Path(tempfile.mkdtemp(prefix="ha-adopt-", dir=str(PRIVATE)))
    os.chmod(work, 0o700)
    atomic(work/"original.json", raw)
    atomic(work/"container.json", json.dumps(original).encode())
    info = CONFIG.stat()
    journal(work, {"phase": "prepared", "file_uid": info.st_uid, "file_gid": info.st_gid,
                   "file_mode": stat.S_IMODE(info.st_mode),
                   "directory_mode": stat.S_IMODE(CONFIG.parent.stat().st_mode)})
    state = {"state": "prepared", "ha_origin": plan["ha_origin"], "broker_configuration_changed": False,
             "ssh_permissions_changed": False, "expected_input_sha256": plan["expected_input_sha256"],
             "original_broker_id": docker.inspect("mosquitto")["Id"]}
    report(response, owner, state)
    pid = os.fork()
    if pid == 0:
        os.setsid()
        fd = os.open(str(work/"worker.log"), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        os.dup2(fd, 1);os.dup2(fd, 2);os.close(fd)
        fd = os.open("/dev/null", os.O_RDONLY);os.dup2(fd, 0);os.close(fd)
        worker = os.getpid()
        watchdog = os.fork()
        if watchdog == 0:
            try:
                time.sleep(300)
                watchdog_recover(work, original, identity, worker, response, owner, state)
            except BaseException as error:
                report(response, owner, {**state, "state": "watchdog_failed", "error_type": type(error).__name__})
            finally:os._exit(0)
        state.update(pid=worker, watchdog_pid=watchdog)
        def notify(update):
            state.update(update)
            report(response, owner, state)
        try:
            notify({"state": "adopting"})
            result = adopt(work, original, identity, binding, plan["ha_origin"], notify)
            try:os.kill(watchdog, signal.SIGTERM)
            except ProcessLookupError:pass
            notify({"state": "ready_for_broker", **result, "wait_seconds": 600})
            deadline = time.monotonic()+600
            while time.monotonic() < deadline:
                raw = response.read_bytes()[:8193]
                try:command = json.loads(raw) if len(raw)<=8192 else {}
                except ValueError:command = {}
                if isinstance(command, dict) and command.get("verify_cutover") is True:
                    until = time.monotonic()+120
                    while time.monotonic()<until:
                        if verify_cutover(state, binding, identity):
                            notify({"state": "authenticated_ha_reconnect_verified",
                                    "broker_authentication_proven": True})
                            break
                        time.sleep(1)
                    else:raise RuntimeError("fresh authenticated HA reconnect deadline")
                    break
                time.sleep(0.5)
            else:notify({"state": "adopted_observer_expired"})
        except BaseException as error:
            atomic(work/"error.json", json.dumps({"error_type": type(error).__name__,
                                                 "message": str(error)}).encode())
            notify({"state": "failed", "error_type": type(error).__name__})
        finally:
            saved = json.loads(regular(work/"journal.json"))
            if saved.get("adoption_completed") or saved.get("rollback_confirmed"):
                try:os.kill(watchdog, signal.SIGTERM)
                except ProcessLookupError:pass
            os._exit(0)
    return {"ha_adoption_started": True, "pid": pid, "report_key": plan["report_key"],
            "general_shell": False, "broker_configuration_changed": False}
