"""Isolated production-producer/DB/receipt integration for issue #426.

Only platform, persistent-byte storage and network delivery are simulated.
The deployed sink, serializer, MACs, DB writer and receipt consumer execute.
"""
import json
import os
from pathlib import Path
import socket
import select
import subprocess
import tempfile
import time
import uuid
from unittest.mock import patch

import pymysql

from backend.app import main
from backend.app.reliability_diagnostics import (
    build_access_receipt, build_sensor_receipt, record_sensor_summary,
    verified_sensor_summary,
)

ROOT = Path(__file__).resolve().parents[1]
KEY = bytes(range(1, 33))
TARGET = "test-target"
DOOR = "01" + "00" * 15


def between(source, start, end):
    """Fail visibly if a production seam moves; never substitute a copy."""
    return source.split(start, 1)[1].split(end, 1)[0]


def build_firmware(directory):
    headers = os.environ.get("SGK_ARDUINOJSON_INCLUDE")
    if not headers:
        candidates = sorted((ROOT / ".pio/libdeps").glob("*/ArduinoJson/src/ArduinoJson.h"))
        if not candidates:
            raise RuntimeError("ArduinoJson headers required for cross-layer integration")
        headers = str(candidates[0].parent)
    mqtt = (ROOT / "src/MqttManager.cpp").read_text()
    sink = (ROOT / "src/GattServer.cpp").read_text()
    fixture = (ROOT / "tests/gatt_evidence_delivery_test.cpp").read_text()
    fixture = fixture.replace("// PRODUCTION_SINK", "class CanonicalMqttEventSink" +
        between(sink, "class CanonicalMqttEventSink", "CanonicalMqttEventSink production_event_sink;"))
    fixture = fixture.replace("  static bool fail;", """  static bool publishCanonicalEvent(const char*);
  static bool publishPacket(const char*, const char*, bool, size_t, const char*);
  static bool fail;""", 1)
    fixture = fixture.replace("int main() {", "void produce() {", 1)
    fixture = fixture.replace('  std::puts("production sink retry identity and sensor terminal passed");', "")
    suffix = (ROOT / "tests/access_evidence_commit_test.cpp").read_text()
    helpers = "\n".join(
        start + between(mqtt, start, end)
        for start, end in [
            ("bool parseLowerHex16(", "bool parseLowerUuid4("),
            ("void bytesToLowerHex(", "bool actorEventCodeAllowsCredentialRef("),
            ("bool actorEventCodeAllowsCredentialRef(", "bool enqueueEventWithDurableSpill("),
            ("bool isSignedCommandTerminalCode(", "bool isAccessTerminalCheckpointCode("),
        ]
    )
    suffix = suffix.replace("// MQTT_HELPERS", helpers)
    suffix = suffix.replace("// RECEIPT_CONSUMER", "bool copyReceiptString(" +
        between(mqtt, "bool copyReceiptString(", "class NvsCommandReplayStorage"))
    suffix = suffix.replace("// EVENT_SERIALIZER", "auto publishEventRecord =" +
        between(mqtt, "auto publishEventRecord =", "// Bound each update pass"))
    suffix = suffix.replace("// SENSOR_SERIALIZER", "const auto* sensorRecord =" +
        between(mqtt, "const auto* sensorRecord =", 'doc["gatt_last_stage_ms"]'))
    harness = Path(directory) / "cross-layer.cpp"
    harness.write_text(fixture + "\n" + suffix)
    binary = Path(directory) / "cross-layer"
    result = subprocess.run([
        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
        "-I" + headers, str(harness), "src/GattProtocol.cpp",
        "src/OfflineEventQueue.cpp", "src/SensorSessionDiagnostics.cpp",
        "src/AccessEventReceipt.cpp", "-o", str(binary),
    ], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError(result.stderr)
    return binary


class Firmware:
    def __init__(self, binary):
        self.pending = b""
        self.process = subprocess.Popen(
            [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0)
        try:
            self.events = [self.read_json() for _ in range(6)]
            self.initial = self.read_json()
        except Exception:
            self.process.kill()
            self.close()
            raise

    def read_json(self):
        deadline = time.monotonic() + 10
        while b"\n" not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select(
                    [self.process.stdout], [], [], max(0, remaining))[0]:
                raise AssertionError("firmware response deadline")
            block = os.read(self.process.stdout.fileno(), 4096)
            if not block:
                raise AssertionError("firmware fixture exited before its response")
            self.pending += block
            if len(self.pending) > 32768:
                raise AssertionError("firmware response bound")
        line, self.pending = self.pending.split(b"\n", 1)
        return json.loads(line)

    def exchange(self, value):
        line = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
        self.process.stdin.write((line + "\n").encode())
        return self.read_json()

    def close(self):
        self.process.stdin.close()
        try:
            code = self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            raise
        finally:
            error = self.process.stderr.read()
            self.process.stdout.close()
            self.process.stderr.close()
        if code:
            raise AssertionError(error.decode(errors="replace"))


def exercise(test):
    """Run real isolated MariaDB plus the production C++ host seam."""
    name = "sgk-evidence-commit-" + uuid.uuid4().hex[:10]
    password = "isolated-test-only"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    def docker(*args, input_text=None, check=True):
        return subprocess.run(["docker", *args], input=input_text, text=True,
                              capture_output=True, check=check, timeout=60)

    image = (ROOT / "backend/db/Dockerfile").read_text().splitlines()[0].split(" ", 1)[1]
    with tempfile.TemporaryDirectory() as directory:
        binary = build_firmware(directory)
        firmware = conn = worker = None
        try:
            result = docker("run", "--rm", "-d", "--name", name,
                            "-e", "MARIADB_ROOT_PASSWORD=" + password,
                            "-p", f"127.0.0.1:{port}:3306", image, check=False)
            test.assertEqual(0, result.returncode, result.stderr)
            def connect():
                return pymysql.connect(
                    host="127.0.0.1", port=port, user="root", password=password,
                    cursorclass=pymysql.cursors.DictCursor, autocommit=True,
                    connect_timeout=1)
            for _ in range(100):
                try:
                    conn = connect()
                    break
                except pymysql.MySQLError:
                    time.sleep(0.2)
            test.assertIsNotNone(conn, "isolated MariaDB did not become ready")
            migrations = ROOT / "backend/db/migrations"
            sql = "CREATE DATABASE smart_gatekeeper;\n" + "\n".join(
                (migrations / f).read_text() for f in [
                    "011_access_event_history_up.sql", "012_access_event_actor_ref_up.sql",
                    "013_ha_access_event_outbox_up.sql", "015_mobile_diagnostics_up.sql",
                    "016_reliability_history_up.sql", "017_access_event_conflicts_up.sql",
                ])
            docker("exec", "-i", name, "mariadb", "-uroot", "-p" + password, input_text=sql)
            conn.select_db("smart_gatekeeper")
            firmware = Firmware(binary)
            events, initial = firmware.events, firmware.initial
            test.assertEqual(6, initial["events_pending"])
            test.assertEqual(1, initial["sensor_pending"])
            test.assertEqual(events[0], json.loads(initial["head_wire"]))
            test.assertEqual("ACCESS_SESSION_COMPLETED", events[-1]["event_code"])
            test.assertEqual(1, len({e["session_id"] for e in events}))
            for previous, following in zip(events, events[1:]):
                test.assertEqual(previous["event_id"], following["causation_event_id"])

            faults = {"commit": True, "receipt": False}
            receipts = []

            class ConnectionFault:
                def __init__(self, connection):
                    self.connection = connection
                def __getattr__(self, key):
                    return getattr(self.connection, key)
                def commit(self):
                    if faults["commit"]:
                        raise pymysql.err.OperationalError(2013, "isolated pre-commit loss")
                    return self.connection.commit()

            def database():
                value = connect()
                value.select_db("smart_gatekeeper")
                return ConnectionFault(value)

            def committed(event):
                receipt = build_access_receipt(event, {"a1": KEY})
                receipts.append(receipt)
                if faults["receipt"]:
                    raise RuntimeError("isolated ACK delivery loss")

            def deliver(event, retained=False):
                start = len(receipts)
                test.assertTrue(worker.request(
                    main._canonical_target_event_topic(TARGET),
                    json.dumps(event, separators=(",", ":")).encode(), retained))
                deadline = time.monotonic() + 5
                while worker._queue.unfinished_tasks and time.monotonic() < deadline:
                    time.sleep(0.01)
                test.assertEqual(0, worker._queue.unfinished_tasks, "writer deadline")
                return receipts[start:]

            with patch.multiple(main, COMMAND_TARGET_ID=TARGET, COMMAND_DOOR_ID=DOOR,
                    ACCESS_EVENT_REF_KEYS={"a1": KEY}, _acl_target_credentials={},
                    _ops_hmac_key=b"k" * 32), patch.object(main, "get_db", side_effect=database):
                worker = main._CanonicalAccessEventWorker(on_commit=committed)
                # Real INSERT transaction rolls back; no callback/receipt may escape.
                test.assertEqual([], deliver(events[0]))
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS n FROM access_event_history")
                    test.assertEqual(0, cur.fetchone()["n"])
                test.assertEqual(initial, firmware.exchange("restart"))
                faults["commit"] = False
                test.assertEqual([], deliver(events[0], retained=True))
                tampered = {**events[0], "reason_code": "REPLAY_DETECTED"}
                test.assertEqual([], deliver(tampered))
                faults["receipt"] = True
                lost = deliver(events[0])[0]
                test.assertEqual(initial, firmware.exchange("peek"))
                worker.stop()
                worker = main._CanonicalAccessEventWorker(on_commit=committed)
                faults["receipt"] = False
                # Backend restart + ACK-loss replay must reissue exact receipt.
                replayed = deliver(events[0])[0]
                test.assertEqual(lost, replayed)
                test.assertEqual(initial, firmware.exchange("restart"))
                # Commit a later source record first; its valid ACK cannot retire head.
                later = json.loads(deliver(events[1])[0])
                state = firmware.exchange(later)
                test.assertEqual(6, state["events_pending"])
                forged = {**json.loads(replayed), "tag": "00" * 16}
                test.assertEqual(6, firmware.exchange(forged)["events_pending"])
                firmware.exchange("fail_storage")
                test.assertEqual(6, firmware.exchange(json.loads(replayed))["events_pending"])
                firmware.exchange("restore_storage")
                state = firmware.exchange(json.loads(replayed))
                test.assertEqual(5, state["events_pending"])
                test.assertEqual(events[1], json.loads(state["head_wire"]))
                for index, event in enumerate(events[1:], start=1):
                    receipt = json.loads(deliver(event)[0])
                    before = firmware.exchange("restart")
                    test.assertEqual(event, json.loads(before["head_wire"]))
                    state = firmware.exchange(receipt)
                    test.assertEqual(5 - index, state["events_pending"])
                test.assertEqual(0, state["events_pending"])
                test.assertEqual(6, state["accepted"])

            summary_doc = {k: initial[k] for k in ("sensor_session_summary", "sensor_summary_auth")}
            summary = summary_doc["sensor_session_summary"]
            status = dict(target_id=TARGET, source_boot_id=events[-1]["source_boot_id"],
                          source_boot_count=events[-1]["target"]["boot_count"], **summary_doc)
            test.assertEqual(summary, verified_sensor_summary(summary_doc, status, {"a1": KEY}))
            test.assertEqual(events[-1]["session_id"], summary["session_id"])
            test.assertEqual(str(events[-1]["sequence"]), summary["terminal_sequence"])
            test.assertEqual(str(events[-1]["clock"]["monotonic_ms"]), summary["ended_monotonic_ms"])
            # Summary commit failure, exact replay and duplicate storage use real SQL.
            conn.begin()
            with conn.cursor() as cur:
                record_sensor_summary(cur, status)
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM target_sensor_session_history")
                test.assertEqual(0, cur.fetchone()["n"])
            for _ in range(2):
                conn.begin()
                with conn.cursor() as cur:
                    record_sensor_summary(cur, status)
                conn.commit()
            sensor_receipt = json.loads(build_sensor_receipt(status, {"a1": KEY}))
            # Access and summary domains cannot retire one another.
            test.assertEqual(1, firmware.exchange(json.loads(replayed))["sensor_pending"])
            test.assertEqual(1, firmware.exchange({**sensor_receipt, "tag": "00" * 16})["sensor_pending"])
            firmware.exchange("fail_storage")
            test.assertEqual(1, firmware.exchange(sensor_receipt)["sensor_pending"])
            firmware.exchange("restore_storage")
            test.assertEqual(1, firmware.exchange("restart")["sensor_pending"])
            test.assertEqual(0, firmware.exchange(sensor_receipt)["sensor_pending"])
            test.assertEqual(0, firmware.exchange("restart")["sensor_pending"])
            with conn.cursor() as cur:
                for table, expected in [("access_event_history", 6),
                                        ("ha_access_event_outbox", 1),
                                        ("target_sensor_session_history", 1)]:
                    cur.execute("SELECT COUNT(*) AS n FROM " + table)
                    test.assertEqual(expected, cur.fetchone()["n"], table)
                cur.execute("SELECT event_id,source_sequence,causation_event_id,integrity_status "
                            "FROM access_event_history ORDER BY source_sequence")
                rows = cur.fetchall()
                test.assertEqual([e["event_id"] for e in events], [row["event_id"] for row in rows])
                test.assertTrue(all(row["integrity_status"] == "verified" for row in rows))
        finally:
            try:
                if worker is not None:
                    worker.stop()
                if firmware is not None:
                    firmware.close()
            finally:
                try:
                    if conn is not None:
                        conn.close()
                finally:
                    docker("rm", "-f", name, check=False)
