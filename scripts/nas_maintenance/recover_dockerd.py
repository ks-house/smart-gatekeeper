#!/usr/bin/python3
"""Prepare or apply a pinned Docker log-driver recovery with live restore."""
from pathlib import Path
import base64
import hashlib
import importlib.util
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time

UNIT = "pkg-ContainerManager-dockerd.service"
BINARY = "/var/packages/ContainerManager/target/usr/bin/dockerd"
CONFIG = Path("/var/packages/ContainerManager/etc/dockerd.json")
STATE = Path("/usr/local/lib/smart-gatekeeper-maintenance/state/dockerd-recovery")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, raw, mode=0o600, uid=0, gid=0):
    fd, name = tempfile.mkstemp(prefix=".docker-recovery-", dir=str(path.parent))
    try:
        os.fchmod(fd, mode);os.fchown(fd, uid, gid)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def trusted(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("root-owned regular recovery control required")
    raw = path.read_bytes()
    if len(raw) > 262144:
        raise ValueError("recovery control bound")
    return raw


def same_containers(before, after):
    if set(before) != set(after) or not before:
        raise ValueError("running container inventory changed")
    for identifier in before:
        if before[identifier] != after[identifier]:
            raise ValueError("container process, start or image changed")


def plan(runtime):
    raw, metadata = runtime.configuration()
    data = json.loads(raw)
    if not isinstance(data, dict) or "live-restore" in data and type(data["live-restore"]) is not bool:
        raise ValueError("reviewed daemon configuration required")
    service = runtime.service()
    if (service["KillMode"] != "process" or service["Restart"] != "always"
            or service["ActiveState"] != "active" or service.get("ExecStop")
            or BINARY not in service["ExecStart"]):
        raise ValueError("isolated daemon unit with process-only termination required")
    info = runtime.info()
    if info["ServerVersion"] != "24.0.2" or info.get("Swarm", {}).get("LocalNodeState") != "inactive":
        raise ValueError("reviewed standalone Docker24.0.2 required")
    proposed = dict(data);proposed["live-restore"] = True
    candidate = json.dumps(proposed, sort_keys=True, indent=2).encode()+b"\n"
    runtime.validate(candidate)
    containers = runtime.containers()
    if info["ContainersRunning"] != len(containers) or len(containers) != 8:
        raise ValueError("reviewed eight-container maintenance scope required")
    return {"schema_version": 1, "unit": UNIT, "daemon_pid": int(service["MainPID"]),
            "daemon_identity": runtime.daemon_identity(),
            "metadata": metadata, "original": base64.b64encode(raw).decode(),
            "original_sha256": digest(raw), "candidate": base64.b64encode(candidate).decode(),
            "candidate_sha256": digest(candidate), "containers": containers}


def recover(runtime, prepared, notify):
    raw, metadata = runtime.configuration()
    if digest(raw) != prepared["original_sha256"] or metadata != prepared["metadata"]:
        raise ValueError("daemon configuration drift")
    if int(runtime.service()["MainPID"]) != prepared["daemon_pid"]:
        raise ValueError("daemon process changed; prepare a fresh plan")
    same_containers(prepared["containers"], runtime.containers())
    candidate = base64.b64decode(prepared["candidate"], validate=True)
    if digest(candidate) != prepared["candidate_sha256"]:
        raise ValueError("prepared candidate drift")
    expected = json.loads(raw);expected["live-restore"] = True
    if json.loads(candidate) != expected:
        raise ValueError("only live-restore may change")
    runtime.validate(candidate)
    notify({"phase": "validated", "daemon_restart_requested": False})
    try:
        runtime.install(candidate)
        runtime.reload()
        until = runtime.monotonic()+20
        while not runtime.info()["LiveRestoreEnabled"]:
            if runtime.monotonic() >= until:
                raise ValueError("live restore did not activate; daemon restart refused")
            runtime.sleep(.25)
        same_containers(prepared["containers"], runtime.containers())
    except BaseException:
        runtime.install(raw)
        runtime.reload()
        notify({"phase": "pre_restart_failed", "configuration_rollback_attempted": True,
                "daemon_restart_requested": False})
        raise
    notify({"phase": "live_restore_verified", "daemon_restart_requested": False})
    # Do not stop the ContainerManager package or any container.
    notify({"phase": "restart_requested", "daemon_restart_requested": True})
    runtime.restart()
    grace = runtime.monotonic()+30
    forced = False
    until = runtime.monotonic()+180
    while True:
        try:
            current_pid = int(runtime.service()["MainPID"])
            info = runtime.info()
            if current_pid != prepared["daemon_pid"] and current_pid > 1 and info["LiveRestoreEnabled"]:
                break
        except (OSError, ValueError, RuntimeError):
            pass
        if not forced and runtime.monotonic() >= grace and runtime.old_daemon_stopping(prepared):
            runtime.force_stopping_daemon(prepared)
            forced = True
            notify({"phase": "stopping_daemon_forced", "daemon_restart_requested": True,
                    "old_daemon_only_killed": True})
        if runtime.monotonic() >= until:
            raise TimeoutError("same daemon recovery remains unverified; do not retry automatically")
        runtime.sleep(1)
    same_containers(prepared["containers"], runtime.containers())
    services = runtime.services()
    runtime.fresh_notice()
    result = {"phase": "verified", "daemon_restart_requested": True,
              "daemon_pid_before": prepared["daemon_pid"], "daemon_pid_after": current_pid,
              "live_restore_enabled": True, "old_daemon_force_required": forced, "preserved_container_count": len(prepared["containers"]),
              "container_processes_and_starts_preserved": True, "services": services,
              "fresh_connect_only_notice_verified": True}
    notify(result)
    return result


class Runtime:
    def __init__(self):
        root = Path("/usr/local/lib/smart-gatekeeper-ha-ops")
        spec = importlib.util.spec_from_file_location("installed_ha_ops", root/"bin/ha_ops.py")
        gateway = importlib.util.module_from_spec(spec);spec.loader.exec_module(gateway)
        self.gateway = gateway
        self.control, self.helper = gateway.library()
        self.path = CONFIG.resolve(strict=True)

    def configuration(self):
        raw = trusted(self.path);info = self.path.stat()
        return raw, {"path": str(self.path), "mode": stat.S_IMODE(info.st_mode),
                     "uid": info.st_uid, "gid": info.st_gid}

    def command(self, args, timeout=20):
        result = subprocess.run(args, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError("fixed Docker recovery command failed")
        return result.stdout

    def service(self):
        raw = self.command(["/bin/systemctl", "show", UNIT,
            "--property=MainPID,ExecStart,ExecStop,KillMode,Restart,ActiveState,SubState"]).decode()
        return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)

    def info(self):
        return self.helper.docker.api("GET", "/info")

    def daemon_identity(self):
        pid = int(self.service()["MainPID"])
        path = Path("/proc")/str(pid)
        if (path/"comm").read_text().strip() != "dockerd":
            raise ValueError("bound Docker daemon process required")
        return {"pid": pid, "start_ticks": (path/"stat").read_text().rsplit(")", 1)[1].split()[19],
                "executable": os.readlink(str(path/"exe"))}

    def old_daemon_stopping(self, prepared):
        service = self.service()
        return (service["ActiveState"] == "deactivating"
                and int(service["MainPID"]) == prepared["daemon_pid"])

    def force_stopping_daemon(self, prepared):
        if self.daemon_identity() != prepared["daemon_identity"] or not self.old_daemon_stopping(prepared):
            raise ValueError("original stopping daemon identity changed")
        # The unit has infinite TimeoutStopUSec. Never signal container processes.
        # Live restore was verified before restart; recheck every container PID/tick.
        for value in prepared["containers"].values():
            path = Path("/proc")/str(value["pid"])/"stat"
            ticks = path.read_text().rsplit(")", 1)[1].split()[19]
            if ticks != value["process_start_ticks"]:
                raise ValueError("container process changed during daemon stop")
        os.kill(prepared["daemon_pid"], signal.SIGKILL)

    def containers(self):
        found = {}
        for item in self.helper.docker.api("GET", "/containers/json"):
            value = self.helper.docker.inspect(item["Id"])
            pid = value["State"]["Pid"]
            # Linux process start tick prevents PID reuse from qualifying.
            ticks = (Path("/proc")/str(pid)/"stat").read_text().rsplit(")", 1)[1].split()[19]
            found[value["Id"]] = {"name": value["Name"], "pid": pid,
                "started_at": value["State"]["StartedAt"], "process_start_ticks": ticks,
                "image": value["Image"]}
        return found

    def validate(self, raw):
        path = STATE/"candidate.validate.json";write(path, raw)
        self.command([BINARY, "--validate", "--config-file", str(path)])

    def install(self, raw):
        _, metadata = self.configuration()
        write(self.path, raw, metadata["mode"], metadata["uid"], metadata["gid"])

    def reload(self):
        self.command(["/bin/systemctl", "reload", UNIT])

    def restart(self):
        self.command(["/bin/systemctl", "--no-block", "restart", UNIT])

    def monotonic(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)

    def services(self):
        if not self.helper.http_ready(self.control["plan"]["ha_origin"]):
            raise ValueError("HA HTTP readiness failed")
        health = self.helper.docker.ready()
        return {"ha_http_200": True, "backend_readiness": health["readiness_passed"]}

    def fresh_notice(self):
        raw = self.helper.regular(self.helper.CONFIG)
        host = self.helper.mqtt_entry(json.loads(raw))["data"]["broker"]
        broker = self.helper.docker.inspect("mosquitto")
        text = self.helper.regular(self.helper.BROKER_CONFIG,
                                   owner=self.helper.BROKER_CONFIG.stat().st_uid).decode()
        binding = self.helper.log_binding(text, broker);binding["probe_host"] = host
        self.helper.verify_observation(binding)


def main():
    if os.geteuid() != 0:
        raise ValueError("privileged signed recovery required")
    if STATE.is_symlink():
        raise ValueError("protected recovery directory required")
    STATE.mkdir(mode=0o700, exist_ok=True)
    info = STATE.stat()
    if info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("root-private recovery directory required")
    runtime = Runtime()
    if sys.argv[1:] == ["prepare"]:
        if (STATE/"journal.json").exists():
            raise ValueError("existing recovery journal requires inspection")
        value = plan(runtime)
        raw = json.dumps(value, sort_keys=True).encode()
        write(STATE/"plan.json", raw)
        print(json.dumps({"prepared": True, "plan_sha256": digest(raw),
            "container_count": len(value["containers"]), "live_restore_currently_enabled": runtime.info()["LiveRestoreEnabled"],
            "daemon_restart_requested": False, "operating_configuration_changed": False}))
    elif len(sys.argv) == 3 and sys.argv[1] == "apply":
        raw = trusted(STATE/"plan.json")
        if digest(raw) != sys.argv[2] or (STATE/"journal.json").exists():
            raise ValueError("exact prepared plan and no prior recovery attempt required")
        def notify(value):
            write(STATE/"journal.json", json.dumps(value, sort_keys=True).encode())
        print(json.dumps(recover(runtime, json.loads(raw), notify)))
    else:
        raise ValueError("exact prepare or approved plan hash required")


if __name__ == "__main__":
    main()
