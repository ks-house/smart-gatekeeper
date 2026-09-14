#!/usr/bin/env python3
"""Bounded local MQTT observation; subscribe-only, TLS required, no raw bodies.

Use a new --output-dir. Credentials use SGK_MQTT_USERNAME/PASSWORD (or their
_FILE variables), as in the HA migration tool. Host/port use SGK_MQTT_HOST/PORT
with MQTT_HOST/PORT fallback. SGK_MQTT_CA_FILE selects a CA; default is system
trust. This observes one exact Target and its Backend HA state topics only.
All MQTT evidence is labelled unverified by this observer, including bridge
assertions. A retained snapshot, reconnect gap or silence proves no new boot,
arrival, radio failure or door movement. API cursor flags preserve the separate
read API checkpoint; this process never advances those cursors or calls the API.
Target availability accepts a strict boot-labelled mqtt_transport JSON document
or legacy online/offline bytes with no boot claim. Bridge availability remains
plain online/offline; its connectivity diagnostic is a historical assertion.
"""

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import ssl
import sys
import threading
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.reliability_diagnostics import advisory_projection  # noqa: E402


MAX_PAYLOAD = 65536
MAX_AVAILABILITY_PAYLOAD = 512
U64 = (1 << 64) - 1
STATES = {"BOOTING", "IDLE", "AUTH_PENDING", "ARMED", "RELAY_HOLD", "RELAY_ON", "COOLDOWN"}
CHANNELS = {"target_status", "target_availability", "target_boot", "bridge_status",
            "bridge_availability", "bridge_connectivity"}
CONNECTIVITY_REASONS = {"WAITING_FOR_SIGNED_STATUS", "SIGNED_STATUS_FRESH", "SIGNED_STATUS_STALE"}


def topics(target_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", target_id):
        raise ValueError("invalid Target ID")
    target = "gatekeeper/v1/targets/" + target_id
    bridge = "gatekeeper/v1/ha-bridge/" + target_id
    return {target + "/status": "target_status", target + "/availability": "target_availability",
            target + "/boot": "target_boot", bridge + "/verified-status": "bridge_status",
            bridge + "/availability": "bridge_availability",
            bridge + "/connectivity-diagnostic": "bridge_connectivity"}


def _integer(value):
    if type(value) is int and 0 <= value <= U64:
        return value
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", value) and int(value) <= U64:
        return int(value)
    return None


def project_message(channel, payload, *, target_id=None):
    if channel not in CHANNELS:
        raise ValueError("invalid observation channel")
    if target_id is not None:
        topics(target_id)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_PAYLOAD:
        raise ValueError("invalid payload size")
    if channel in ("target_availability", "bridge_availability"):
        if len(payload) > MAX_AVAILABILITY_PAYLOAD:
            raise ValueError("invalid availability size")
        if payload in (b"online", b"offline"):
            result = {"availability": payload.decode("ascii")}
            if channel == "target_availability":
                # N-1 Target compatibility: transport only, with no boot claim.
                result.update(scope="mqtt_transport", payload_format="legacy_plain")
            return result
        if channel == "bridge_availability":
            raise ValueError("invalid availability")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("invalid JSON number")

    doc = json.loads(payload.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(doc, dict):
        raise ValueError("invalid JSON object")
    if "target_id" in doc and (not isinstance(doc["target_id"], str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", doc["target_id"]) is None
            or (target_id is not None and doc["target_id"] != target_id)):
        raise ValueError("mismatched Target identity")
    if channel == "target_availability":
        # MqttManager::startConnectWorker/connectWorkerEntry emit these exact
        # fields for the offline LWT and retained online transport announcement.
        if (target_id is None
                or set(doc) != {"status", "scope", "target_id", "boot_id", "boot_count"}
                or doc["status"] not in ("online", "offline")
                or doc["scope"] != "mqtt_transport"
                or not isinstance(doc["boot_id"], str)
                or re.fullmatch(r"[0-9a-f]{32}", doc["boot_id"]) is None
                or type(doc["boot_count"]) is not int
                or not 1 <= doc["boot_count"] <= (1 << 32) - 1):
            raise ValueError("invalid Target availability")
        return dict(availability=doc["status"], scope="mqtt_transport", target_id=target_id,
                    boot_id=doc["boot_id"], boot_count=str(doc["boot_count"]), payload_format="target_json")
    if channel == "bridge_connectivity":
        # home_assistant_bridge.bridge_connectivity_diagnostic_payload emits a
        # historical Backend observation, not a current online/readiness claim.
        if (set(doc) != {"schema_version", "diagnostic_scope", "last_signed_status_observation"}
                or type(doc["schema_version"]) is not int or doc["schema_version"] != 1
                or doc["diagnostic_scope"] != "last_completed_backend_observation"
                or not isinstance(doc["last_signed_status_observation"], str)
                or doc["last_signed_status_observation"] not in CONNECTIVITY_REASONS):
            raise ValueError("invalid bridge connectivity diagnostic")
        return doc
    if doc.get("scope") == "mqtt_transport" or "diagnostic_scope" in doc:
        raise ValueError("wrong observation channel")
    result = advisory_projection(doc)
    for key in ("source_boot_count", "boot_count", "status_revision", "access_status_revision", "monotonic_ms"):
        value = _integer(doc.get(key))
        if value is not None:
            result[key] = str(value)
    for key in ("source_boot_id", "boot_id"):
        value = doc.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value):
            result[key] = value
    if isinstance(doc.get("state"), str) and doc["state"] in STATES:
        result["state"] = doc["state"]
    for key in ("relay_commanded_on", "is_armed"):
        if type(doc.get(key)) is bool:
            result[key] = doc[key]
    if type(doc.get("relay_pin_level")) is int and doc["relay_pin_level"] in (-1, 0, 1, 2):
        result["relay_pin_level"] = doc["relay_pin_level"]
    if not result:
        raise ValueError("no allowed observation")
    return result


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BoundedJsonl:
    """Only rotate files created by this instance, in a new private directory."""
    def __init__(self, directory, *, max_bytes=1024 * 1024, max_files=4):
        if not 4096 <= max_bytes <= 16 * 1024 * 1024 or not 2 <= max_files <= 16:
            raise ValueError("invalid recording limits")
        self.directory = Path(directory).resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.max_bytes, self.max_files = max_bytes, max_files
        self.sequence, self.segment, self.evicted_through = 0, 0, 0
        self.files = deque()
        self.handle, self.size = None, 0

    def _encode(self, kind, data):
        return (json.dumps({**data, "sequence": self.sequence + 1, "received_at": data.get("received_at", utc_now()), "kind": kind},
                           sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")

    def _append(self, line):
        self.handle.write(line)
        self.handle.flush()
        self.size += len(line)
        self.sequence += 1
        self.files[-1][1] = self.sequence

    def write(self, kind, data, *, snapshot=None):
        line = self._encode(kind, data)
        if len(line) > self.max_bytes // 2:
            line = self._encode("gap", {"reason": "PROJECTED_RECORD_TOO_LARGE", "raw_body_saved": False})
        if self.handle is None or self.size + len(line) > self.max_bytes:
            if self.handle is not None:
                self.handle.flush()
                os.fsync(self.handle.fileno())
                self.handle.close()
            if len(self.files) == self.max_files:
                old, last = self.files.popleft()
                # This exact child was exclusively created by this run.
                if old.parent != self.directory or old.is_symlink():
                    raise ValueError("recording path changed")
                old.unlink()
                self.evicted_through = last
            self.segment += 1
            path = self.directory / f"observation-{self.segment:06d}.jsonl"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            self.handle = os.fdopen(fd, "wb")
            self.files.append([path, self.sequence])
            self.size = 0
            header = self._encode("segment_start", dict(segment=self.segment,
                history_evicted_through_sequence=self.evicted_through, snapshot=snapshot,
                rotation_is_collection_loss=self.evicted_through > 0))
            if len(header) > self.max_bytes // 2:
                header = self._encode("segment_start", dict(segment=self.segment,
                    history_evicted_through_sequence=self.evicted_through,
                    snapshot=None, snapshot_omitted="RECORD_SIZE_LIMIT"))
            self._append(header)
            # The segment header owns its own sequence position.
            body = json.loads(line)
            body.pop("sequence")
            stamp = body.pop("received_at")
            record_kind = body.pop("kind")
            line = self._encode(record_kind, {**body, "received_at": stamp})
        self._append(line)

    def close(self):
        if self.handle is not None:
            self.handle.flush()
            os.fsync(self.handle.fileno())
            self.handle.close()
            self.handle = None


class Observer:
    def __init__(self, writer, target_id, *, cursors=None, monotonic=time.monotonic):
        self.writer, self.channels = writer, topics(target_id)
        self.target_id = target_id
        self.cursors, self.monotonic = cursors or {}, monotonic
        self.state, self.received, self.live_received, self.repeats = {}, {}, {}, {}
        self.connected, self.subscribed, self.connection_count = False, False, 0
        self.subscription_ever_accepted = False
        self.gap_started = self.monotonic()
        self.rejected, self.lock = 0, threading.RLock()
        self.rejected_by_channel = {channel: 0 for channel in self.channels.values()}

    def snapshot(self):
        now = self.monotonic()
        return dict(target_id=self.target_id, connected=self.connected, subscribed=self.subscribed,
                    connection_count=self.connection_count, rejected_messages=self.rejected,
                    rejected_messages_by_channel=dict(self.rejected_by_channel),
                    api_cursors=self.cursors, api_cursors_advanced=False,
                    evidence_integrity="UNVERIFIED_MQTT_OBSERVATION",
                    gap_duration_ms=int((now - self.gap_started) * 1000) if self.gap_started is not None else None,
                    observations={channel: dict(**value, duplicates_suppressed=self.repeats.get(channel, 0),
                        receipt_age_ms=int((now - self.received[channel]) * 1000),
                        # Channel receipt history is separate from this value:
                        # a replay may contain another boot and is never live.
                        live_receipt_age_ms=int((now - self.live_received[channel]) * 1000)
                            if channel in self.live_received else None,
                        freshness="RETAINED_ONLY" if value["retained"] else
                                  "NO_RECENT_MESSAGE" if now - self.live_received[channel] > 90 else "RECENT_MESSAGE")
                        for channel, value in self.state.items()},
                    missing_channels=sorted(set(self.channels.values()) - set(self.state)),
                    physical_door="NOT_OBSERVABLE", silence_is_failure=False)

    def record(self, kind, data):
        self.writer.write(kind, data, snapshot=self.snapshot())

    def start(self):
        with self.lock:
            self.record("collection_start", dict(target_id=self.target_id, target_namespace_exact=True, tls_required=True,
                topic_count=len(self.channels), api_cursors=self.cursors,
                initial_gap="NOT_YET_SUBSCRIBED", retained_is_snapshot=True,
                limits=dict(max_bytes=self.writer.max_bytes, max_files=self.writer.max_files)))

    def connection(self, accepted):
        with self.lock:
            self.connected, self.subscribed = accepted, False
            if accepted:
                self.connection_count += 1
            elif self.gap_started is None:
                self.gap_started = self.monotonic()
            self.record("connection", {"accepted": accepted, "connection_count": self.connection_count})

    def subscription(self, accepted):
        with self.lock:
            self.subscribed = accepted
            gap_ms = int((self.monotonic() - self.gap_started) * 1000) if self.gap_started is not None else None
            self.record("subscription", dict(accepted=accepted, preceding_gap_ms=gap_ms,
                missing_messages="UNKNOWN", replay_recovers_gap=False))
            if accepted:
                self.subscription_ever_accepted = True
                self.gap_started = None

    def disconnect(self):
        with self.lock:
            self.connected = self.subscribed = False
            if self.gap_started is None:
                self.gap_started = self.monotonic()
            self.record("gap", {"reason": "MQTT_DISCONNECTED", "missing_messages": "UNKNOWN"})

    def message(self, topic, payload, retained):
        with self.lock:
            channel = self.channels.get(topic)
            if channel is None:
                return False
            try:
                fields = project_message(channel, payload, target_id=self.target_id)
            except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
                self.rejected += 1
                self.rejected_by_channel[channel] += 1
                # Aggregate rejected payloads; never copy payload/exception text.
                return False
            now = self.monotonic()
            value = dict(fields=fields, retained=bool(retained), snapshot_only=bool(retained))
            self.received[channel] = now
            if not retained:
                self.live_received[channel] = now
            if self.state.get(channel) == value:
                self.repeats[channel] = self.repeats.get(channel, 0) + 1
                return True
            self.state[channel] = value
            self.record("observation", dict(channel=channel, **value,
                evidence_integrity="UNVERIFIED_MQTT_OBSERVATION"))
            return True

    def checkpoint(self):
        with self.lock:
            self.record("snapshot", self.snapshot())

    def finish(self, reason):
        with self.lock:
            self.record("collection_end", dict(reason=reason, snapshot=self.snapshot()))
            self.writer.close()


def _secret(name):
    direct, file_name = os.getenv(name), os.getenv(name + "_FILE")
    if direct is not None and file_name:
        raise ValueError("choose secret environment or file")
    if file_name:
        with Path(file_name).open(encoding="utf-8") as source:
            direct = source.read(8193).rstrip("\r\n")
    if direct is not None and (not direct or len(direct) > 8192 or "\x00" in direct):
        raise ValueError("invalid secret source")
    return direct


def _positive(value):
    if not re.fullmatch(r"[1-9][0-9]{0,19}", value) or int(value) > U64:
        raise argparse.ArgumentTypeError("invalid cursor")
    return value


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        raise argparse.ArgumentTypeError("invalid timezone-aware timestamp") from None


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--target-id", required=True)
    result.add_argument("--output-dir", type=Path, required=True, help="new private recording directory; existing paths refused")
    result.add_argument("--host", default=os.getenv("SGK_MQTT_HOST", os.getenv("MQTT_HOST")))
    result.add_argument("--port", type=int, default=os.getenv("SGK_MQTT_PORT", os.getenv("MQTT_PORT", "8883")))
    result.add_argument("--duration-seconds", type=int, default=1800)
    result.add_argument("--snapshot-seconds", type=int, default=30)
    result.add_argument("--max-bytes", type=int, default=1024 * 1024)
    result.add_argument("--max-files", type=int, default=4)
    for key in ("access-before-id", "health-before-id", "incident-before-id", "mobile-before-id"):
        result.add_argument("--" + key, type=_positive)
    for key in ("since", "until", "occurred-since", "occurred-until", "evidence-received-until"):
        result.add_argument("--" + key, type=_timestamp)
    return result


def run(args, mqtt, *, monotonic=time.monotonic, sleep=time.sleep):
    topics(args.target_id)
    if (not args.host or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,253}", args.host)
            or not 1 <= args.port <= 65535 or not 1 <= args.duration_seconds <= 86400
            or not 1 <= args.snapshot_seconds <= 300):
        raise ValueError("invalid connection or observation bounds")
    username, password = _secret("SGK_MQTT_USERNAME"), _secret("SGK_MQTT_PASSWORD")
    if (username is None) != (password is None):
        raise ValueError("both credential sources are required")
    context = ssl.create_default_context(cafile=os.getenv("SGK_MQTT_CA_FILE"))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    kwargs = dict(client_id="sgk-read-observer-" + uuid.uuid4().hex[:12], protocol=mqtt.MQTTv311)
    client = (mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, **kwargs)
              if hasattr(mqtt, "CallbackAPIVersion") else mqtt.Client(**kwargs))
    client.tls_set_context(context)
    if username is not None:
        client.username_pw_set(username, password)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    cursors = {key: value for key, value in vars(args).items() if value is not None and
               (key.endswith("before_id") or key in ("since", "until", "occurred_since", "occurred_until", "evidence_received_until"))}
    writer = BoundedJsonl(args.output_dir, max_bytes=args.max_bytes, max_files=args.max_files)
    observer = Observer(writer, args.target_id, cursors=cursors, monotonic=monotonic)
    fatal = threading.Event()

    def guarded(action):
        def callback(*values):
            try:
                action(*values)
            except Exception:
                fatal.set()
        return callback

    def connected(c, _userdata, _flags, reason, *_rest):
        accepted = reason == 0
        observer.connection(accepted)
        if accepted:
            rc, _mid = c.subscribe([(topic, 1) for topic in observer.channels])
            if rc != mqtt.MQTT_ERR_SUCCESS:
                observer.subscription(False)

    def subscribed(_c, _userdata, _mid, codes, *_rest):
        observer.subscription(len(codes) == len(observer.channels) and all(code == 0 or code == 1 for code in codes))

    client.on_connect = guarded(connected)
    client.on_connect_fail = guarded(lambda *_: observer.connection(False))
    client.on_disconnect = guarded(lambda *_: observer.disconnect())
    client.on_subscribe = guarded(subscribed)
    client.on_message = guarded(lambda _c, _u, msg: observer.message(msg.topic, msg.payload, msg.retain))
    reason, started = "DURATION_COMPLETE", False
    try:
        observer.start()
        client.connect_async(args.host, args.port, keepalive=30)
        if client.loop_start() not in (None, mqtt.MQTT_ERR_SUCCESS):
            raise RuntimeError("observer network loop unavailable")
        started = True
        deadline = monotonic() + args.duration_seconds
        checkpoint = monotonic() + args.snapshot_seconds
        while monotonic() < deadline:
            if fatal.is_set():
                raise RuntimeError("observer recording unavailable")
            if monotonic() >= checkpoint:
                observer.checkpoint()
                checkpoint = monotonic() + args.snapshot_seconds
            sleep(min(1, max(0, deadline - monotonic())))
        if fatal.is_set():
            raise RuntimeError("observer recording unavailable")
    except KeyboardInterrupt:
        reason = "OPERATOR_STOP"
    except Exception:
        reason = "OBSERVER_ERROR"
        raise
    finally:
        if started:
            # Stop callbacks before the terminal snapshot closes its files.
            client.on_disconnect = None
            client.disconnect()
            client.loop_stop()
        observer.finish(reason)
    return {"recording_complete": True, "end_reason": reason, "segment_count": writer.segment,
            "history_evicted_through_sequence": writer.evicted_through,
            "subscribed": observer.subscribed, "observed_channels": len(observer.state),
            "subscription_ever_accepted": observer.subscription_ever_accepted,
            "rejected_messages": observer.rejected,
            "rejected_messages_by_channel": dict(observer.rejected_by_channel),
            "observation_status": "MESSAGES_OBSERVED" if observer.state else "NO_MESSAGES_OBSERVED",
            "api_cursors_advanced": False, "evidence_integrity": "UNVERIFIED_MQTT_OBSERVATION"}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        import paho.mqtt.client as mqtt
        result = run(args, mqtt)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["subscription_ever_accepted"] else 1
    except (OSError, ValueError, RuntimeError, ImportError):
        # Never log exception strings, endpoints, credentials or broker payloads.
        print("MQTT observation failed; check TLS, configuration and a new writable recording directory.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
