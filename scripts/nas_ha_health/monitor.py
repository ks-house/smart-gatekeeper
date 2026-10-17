"""Bounded HA ingress/lifecycle observation and owner-only DSM alerts.

No repair, service stop, device command, credential read or Docker log query.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import tempfile
import time
import urllib.parse
import uuid

ROOT = Path("/usr/local/lib/smart-gatekeeper-ha-health")
STATE = Path("/volume1/smart-gatekeeper-operations-private/ha-health")
SOCKET = "/var/run/docker.sock"
NOTIFIER = "/usr/syno/bin/synodsmnotify"
ORIGIN = "https://tworimpa.synology.me:4123/"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def private_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("private directory binding")


def regular(path, limit=262144):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > limit:
        raise ValueError("private regular file binding")
    return path.read_bytes()


def atomic(path, value):
    private_directory(path.parent)
    descriptor, name = tempfile.mkstemp(prefix=".health-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def journal(directory, record):
    private_directory(directory)
    path = directory / "observations.jsonl"
    if path.exists() or path.is_symlink():
        regular(path, 1048576)
        if path.stat().st_size > 1000000:
            for index in range(5, 0, -1):
                older = directory / ("observations.jsonl." + str(index))
                if older.exists() or older.is_symlink():
                    regular(older, 1048576)
                    if index == 5:
                        older.unlink()
                    else:
                        os.replace(older, directory / ("observations.jsonl." + str(index + 1)))
            os.replace(path, directory / "observations.jsonl.1")
    raw = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode()
    if len(raw) > 32768:
        raise ValueError("observation bound")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "ab") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def validate_config(value):
    if set(value) != {"schema_version", "container_id", "image", "origin", "owner", "interval_seconds"}:
        raise ValueError("configuration inventory")
    if value["schema_version"] != 1 or value["origin"] != ORIGIN or value["owner"] != "noty00":
        raise ValueError("origin or owner binding")
    if not re.fullmatch(r"[0-9a-f]{64}", value["container_id"]) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["image"]):
        raise ValueError("container binding")
    if type(value["interval_seconds"]) is not int or not 15 <= value["interval_seconds"] <= 60:
        raise ValueError("observation interval")
    return value


class DockerHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def docker_read(path, limit=262144):
    connection = DockerHTTP("localhost", timeout=3)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        raw = response.read(limit + 1)
        if response.status != 200 or len(raw) > limit:
            raise ValueError("bounded Docker observation")
        return raw
    finally:
        connection.close()


def container_observation(config):
    value = json.loads(docker_read("/containers/" + config["container_id"] + "/json"))
    state = value["State"]
    return {
        "id": value["Id"], "image": value["Image"],
        "running": state["Running"], "started_at": state["StartedAt"],
        "finished_at": state["FinishedAt"], "exit_code": state["ExitCode"],
        "oom_killed": state["OOMKilled"], "restart_count": value["RestartCount"],
        "restart_policy": value["HostConfig"]["RestartPolicy"]["Name"],
    }


def lifecycle_events(config, since, until):
    if until < since:
        return []
    filters = {"type": ["container"], "container": [config["container_id"]],
               "event": ["die", "kill", "oom", "stop", "start", "restart", "destroy", "update"]}
    query = urllib.parse.urlencode({"since": int(since), "until": int(until), "filters": json.dumps(filters)})
    raw = docker_read("/events?" + query)
    records = []
    for line in raw.splitlines():
        value = json.loads(line)
        if value.get("id", value.get("Actor", {}).get("ID")) != config["container_id"]:
            raise ValueError("foreign lifecycle event")
        attributes = value.get("Actor", {}).get("Attributes", {})
        records.append({"action": value.get("Action", value.get("status")),
                        "time_ns": value.get("timeNano"), "time": value.get("time"),
                        "exit_code": attributes.get("exitCode"), "signal": attributes.get("signal")})
        if len(records) > 256:
            raise ValueError("lifecycle count bound")
    return records


def tls_context(context):
    context = context or ssl.create_default_context()
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("TLS verification is mandatory")
    return context


def websocket_probe(origin, connect_host=None, context=None, timeout=3):
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("HTTPS origin required")
    context = tls_context(context)
    host = parsed.hostname
    port = parsed.port or 443
    key = base64.b64encode(os.urandom(16)).decode()
    target = parsed.path.rstrip("/") + "/api/websocket"
    authority = host + (":" + str(port) if port != 443 else "")
    with socket.create_connection((connect_host or host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as stream:
            stream.settimeout(timeout)
            request = ("GET " + target + " HTTP/1.1\r\nHost: " + authority +
                       "\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " + key +
                       "\r\nSec-WebSocket-Version: 13\r\nOrigin: " + origin.rstrip("/") + "\r\n\r\n")
            stream.sendall(request.encode("ascii"))
            buffer = bytearray()
            deadline = time.monotonic() + timeout * 2
            while b"\r\n\r\n" not in buffer:
                if time.monotonic() > deadline or len(buffer) > 16384:
                    raise ValueError("WebSocket header bound")
                part = stream.recv(4096)
                if not part:
                    raise ValueError("WebSocket closed before handshake")
                buffer.extend(part)
            header, trailing = bytes(buffer).split(b"\r\n\r\n", 1)
            lines = header.decode("ascii").split("\r\n")
            if lines[0].split()[:2] != ["HTTP/1.1", "101"]:
                raise ValueError("WebSocket status")
            headers = {}
            for line in lines[1:]:
                name, value = line.split(":", 1)
                name = name.lower()
                if name in headers:
                    raise ValueError("duplicate WebSocket header")
                headers[name] = value.strip()
            expected = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
            if (headers.get("sec-websocket-accept") != expected or
                headers.get("upgrade", "").lower() != "websocket" or
                "upgrade" not in {token.strip().lower() for token in headers.get("connection", "").split(",")}):
                raise ValueError("WebSocket handshake identity")
            pending = bytearray(trailing)
            def exact(count):
                while len(pending) < count:
                    if time.monotonic() > deadline:
                        raise TimeoutError("WebSocket frame deadline")
                    stream.settimeout(min(timeout, max(0.01, deadline - time.monotonic())))
                    part = stream.recv(min(4096, count - len(pending)))
                    if not part:
                        raise ValueError("WebSocket frame closed")
                    pending.extend(part)
                result = bytes(pending[:count])
                del pending[:count]
                return result
            first, length = exact(2)
            if first != 0x81 or length & 0x80:
                raise ValueError("unexpected WebSocket frame")
            if length == 126:
                length = int.from_bytes(exact(2), "big")
            elif length == 127:
                length = int.from_bytes(exact(8), "big")
            if length > 16384:
                raise ValueError("WebSocket payload bound")
            message = json.loads(exact(length))
            if not isinstance(message, dict) or message.get("type") != "auth_required":
                raise ValueError("HA protocol not ready")
            return {"status": 101, "auth_required": True}


class LocalHTTPS(http.client.HTTPSConnection):
    def connect(self):
        self.sock = socket.create_connection(("127.0.0.1", self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def ingress_observation(origin, local=False, context=None):
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("HTTPS origin required")
    context = tls_context(context)
    result = {"http_status": None, "websocket_status": None, "auth_required": False, "errors": []}
    connection = (LocalHTTPS if local else http.client.HTTPSConnection)(
        parsed.hostname, parsed.port or 443, timeout=3, context=context)
    try:
        connection.request("GET", parsed.path or "/")
        response = connection.getresponse()
        result["http_status"] = response.status
        response.read(4096)
    except Exception as error:
        result["errors"].append({"check": "http", "type": type(error).__name__})
    finally:
        connection.close()
    try:
        value = websocket_probe(origin, "127.0.0.1" if local else None, context)
        result.update(websocket_status=value["status"], auth_required=value["auth_required"])
    except Exception as error:
        result["errors"].append({"check": "websocket", "type": type(error).__name__})
    return result


def reasons(config, container, ingress):
    result = []
    if container is None:
        result.append("container_observation_unavailable")
    else:
        if not container["running"]:
            result.append("container_not_running")
        if container["id"] != config["container_id"] or container["image"] != config["image"]:
            result.append("container_identity_changed")
        if container["restart_policy"] != "unless-stopped":
            result.append("restart_policy_changed")
    if ingress.get("http_status") != 200:
        result.append("http_unavailable")
    if ingress.get("websocket_status") != 101 or not ingress.get("auth_required"):
        result.append("websocket_unavailable")
    return result


def advance(previous, failures, now, identifier=None):
    value = dict(previous)
    value["failures"] = previous.get("failures", 0) + 1 if failures else 0
    value["successes"] = previous.get("successes", 0) + 1 if not failures else 0
    value["pending"] = list(previous.get("pending", []))
    notice = None
    if value["failures"] >= 2 and not previous.get("alert_open", False):
        incident = identifier or uuid.uuid4().hex[:16]
        value.update(alert_open=True, incident=incident)
        notice = {"phase": "failure", "incident": incident, "at": now, "reasons": failures}
    elif value["successes"] >= 2 and previous.get("alert_open", False):
        value["alert_open"] = False
        notice = {"phase": "recovered", "incident": previous["incident"], "at": now, "reasons": []}
    if notice is not None:
        if len(value["pending"]) >= 16:
            value["notification_overflow"] = value.get("notification_overflow", 0) + 1
        else:
            value["pending"].append(notice)
    value["observed_at"] = now
    return value, notice


def notify_owner(notice, test=False):
    if notice["phase"] not in {"failure", "recovered"} or not re.fullmatch(r"[0-9a-f]{16}", notice["incident"]):
        raise ValueError("notification binding")
    title = ("[진단 시험] " if test else "") + "Smart Gatekeeper Home Assistant"
    message = ("연결 점검에 실패했습니다. NAS에서 HTTP·WebSocket과 컨테이너 종료 기록을 확인하세요."
               if notice["phase"] == "failure" else "HTTP·WebSocket 연결이 정상으로 복구됐습니다.")
    if test:
        message = "운영 서비스를 중단하지 않은 경보 경로 시험입니다. " + message
    tag = "sgk-ha-health-" + notice["incident"] + "-" + notice["phase"]
    result = subprocess.run([NOTIFIER, "-t", tag, "-l", "warn" if notice["phase"] == "failure" else "info",
                             "noty00", title, message], capture_output=True, timeout=5)
    return result.returncode == 0


def run_cycle(config, directory=STATE, observe=None, ingress=None, events=None, notifier=notify_owner, now=None):
    now = int(time.time()) if now is None else now
    state_file = directory / "state.json"
    previous = json.loads(regular(state_file)) if state_file.exists() else {}
    errors = []
    try:
        container = (observe or container_observation)(config)
    except Exception as error:
        container = None
        errors.append({"check": "container", "type": type(error).__name__})
    try:
        health = (ingress or (lambda origin: ingress_observation(origin, local=True)))(config["origin"])
    except Exception as error:
        health = {}
        errors.append({"check": "ingress", "type": type(error).__name__})
    until = now - 1
    since = max(0, previous.get("events_until", until - 120) - 2)
    try:
        changes = (events or lifecycle_events)(config, since, until)
        event_until = until
    except Exception as error:
        changes = []
        event_until = previous.get("events_until", until - 120)
        errors.append({"check": "lifecycle", "type": type(error).__name__})
    failures = reasons(config, container, health)
    if any(error["check"] == "lifecycle" for error in errors):
        failures.append("lifecycle_observation_unavailable")
    value, notice = advance(previous, failures, now)
    value["events_until"] = event_until
    atomic(state_file, value)
    journal(directory, {"at": now, "container": container, "ingress": health, "lifecycle": changes,
                        "errors": errors, "transition": notice, "alert_open": value.get("alert_open", False)})
    if value["pending"]:
        try:
            delivered = notifier(value["pending"][0])
        except Exception:
            delivered = False
        if delivered:
            value["pending"].pop(0)
            value["last_notification_accepted_at"] = now
            atomic(state_file, value)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("root-owned observer required")
    private_directory(ROOT)
    private_directory(STATE)
    config = validate_config(json.loads(regular(ROOT / "config.json")))
    descriptor = os.open(STATE / "observer.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            result = run_cycle(config)
            if args.once:
                print(json.dumps({"observed": True, "alert_open": result.get("alert_open", False),
                                  "pending_notifications": len(result["pending"])}))
                break
            time.sleep(config["interval_seconds"])
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    main()
