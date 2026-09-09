import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

import pymysql

from backend.app import main
from backend.app.access_event_conflicts import preserve_conflict
from backend.app.access_actor_ref import build_access_event_mac_input, access_evidence_mac
from backend.tests.test_target_boot_registry import (
    TARGET, ACCESS_DOOR_ID, ACCESS_REF_KEY, signed_canonical_event_payload,
)

ROOT = Path(__file__).resolve().parents[2]


def sign_event(document):
    canonical = build_access_event_mac_input(
        key_id="k1", topic_target_id=TARGET, door_id=ACCESS_DOOR_ID,
        source_instance_id=document["source_instance_id"], source_boot_id=document["source_boot_id"],
        source_boot_count=document["target"]["boot_count"], event_id=document["event_id"],
        session_id=document["session_id"], sequence=document["sequence"], attempt=document["attempt"],
        event_code=document["event_code"], stage=document["stage"], outcome=document["outcome"],
        reason_code=document["reason_code"], causation_event_id=document["causation_event_id"],
        monotonic_ms=document["clock"]["monotonic_ms"],
        credential_ref=document["attributes"].get("credential_ref"),
        distance_mm=None, duration_ms=None, relay_hold_ms=None)
    document["auth"]["tag"] = access_evidence_mac(ACCESS_REF_KEY, canonical)
    return json.dumps(document).encode()


class ConflictCustodyTest(unittest.TestCase):
    def setUp(self):
        self.payload = signed_canonical_event_payload()
        self.topic = main._canonical_target_event_topic(TARGET)
        self.config = patch.multiple(main, COMMAND_TARGET_ID=TARGET,
            COMMAND_DOOR_ID=ACCESS_DOOR_ID, ACCESS_EVENT_REF_KEYS={"k1": ACCESS_REF_KEY},
            _acl_target_credentials={}, _ops_hmac_key=b"k" * 32)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.conn = MagicMock()
        self.cur = self.conn.cursor.return_value.__enter__.return_value
        self.cur.fetchone.return_value = None
        self.cur.fetchall.return_value = [{"event_id": "different"}]
        # Canonical INSERT conflicts; custody SELECT and INSERT succeed.
        self.cur.execute.side_effect = [pymysql.err.IntegrityError(1062, "duplicate"), None, None, None]

    def persist(self, payload=None, retained=False):
        with patch.object(main, "get_db", return_value=self.conn):
            return main._persist_canonical_target_access_event(
                self.topic, payload or self.payload, retained=retained)

    def test_conflict_is_preserved_before_exact_receipt_not_projected_as_success(self):
        stored = self.persist()
        self.assertTrue(stored["quarantined"])
        self.assertFalse(stored["inserted"])
        self.conn.commit.assert_called_once()
        sql, args = self.cur.execute.call_args.args
        self.assertIn("INSERT INTO access_event_conflicts", sql)
        preserved = json.loads(args[-1])
        self.assertEqual(stored["event"]["event_id"], preserved["event_id"])
        self.assertEqual(stored["event"]["integrity_tag"], preserved["integrity_tag"])
        self.assertEqual(hashlib.sha256(args[-1].encode()).hexdigest(), args[-2])
        self.assertNotIn("ha_access_event_outbox", str(self.cur.execute.call_args_list))
        receipt = json.loads(main.build_access_receipt(stored["event"], {"k1": ACCESS_REF_KEY}))
        self.assertEqual(preserved["event_id"], receipt["event_id"])
        self.assertEqual(preserved["integrity_tag"], receipt["event_tag"])

    def test_replay_rechecks_exact_custody_and_never_inserts_again(self):
        stored = self.persist()
        preserved = self.cur.execute.call_args.args[1][-1]
        self.cur.execute.side_effect = None
        self.cur.execute.reset_mock()
        self.cur.fetchone.return_value = {"payload_json": preserved}
        again = preserve_conflict(self.conn, stored["event"])
        self.assertTrue(again["quarantined"])
        self.cur.execute.assert_called_once()
        self.assertIn("SELECT payload_json", self.cur.execute.call_args.args[0])
        self.cur.fetchone.return_value = {"payload_json": "{}"}
        with self.assertRaises(ValueError):
            preserve_conflict(self.conn, stored["event"])

    def test_missing_table_write_failure_or_uncertain_commit_never_acknowledges(self):
        for fault in ("read", "write", "commit"):
            with self.subTest(fault=fault):
                error = pymysql.err.OperationalError(2013, "isolated failure")
                self.cur.execute.side_effect = [pymysql.err.IntegrityError(1062, "duplicate"),
                    None, error if fault == "read" else None,
                    error if fault == "write" else None]
                self.conn.commit.side_effect = error if fault == "commit" else None
                self.assertIsNone(self.persist())
                self.conn.rollback.assert_called()

    def test_retained_or_forged_event_cannot_fill_quarantine(self):
        with patch.object(main, "get_db") as db:
            self.assertIsNone(main._persist_canonical_target_access_event(
                self.topic, self.payload, retained=True))
            with patch.object(main, "_authenticate_canonical_target_access_event", return_value=False):
                self.assertIsNone(main._persist_canonical_target_access_event(
                    self.topic, self.payload, retained=False))
            db.assert_not_called()

    def test_worker_receipts_custody_without_normal_insert_callback(self):
        event = {"event_id": "preserved"}
        on_insert, on_commit = MagicMock(), MagicMock()
        worker = main._CanonicalAccessEventWorker(persist=MagicMock(return_value={
            "inserted": False, "quarantined": True, "event": event}),
            on_insert=on_insert, on_commit=on_commit)
        try:
            self.assertTrue(worker.request(self.topic, self.payload, False))
            worker._queue.join()
            on_insert.assert_not_called()
            on_commit.assert_called_once_with(event)
        finally:
            worker.stop()


@unittest.skipUnless(os.getenv("RUN_MARIADB_INTEGRATION") == "1", "isolated MariaDB opt-in")
class ConflictMariaDbTest(unittest.TestCase):
    def test_real_collision_replay_following_event_and_rollback_preservation(self):
        name = "sgk-audit-conflict-test-" + uuid.uuid4().hex[:10]
        password = "isolated-test-only"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        def docker(*args, input_text=None):
            return subprocess.run(["docker", *args], input=input_text, text=True,
                                  capture_output=True, check=True)
        image = (ROOT / "backend/db/Dockerfile").read_text().splitlines()[0].split(" ", 1)[1]
        docker("run", "--rm", "-d", "--name", name, "-e", "MARIADB_ROOT_PASSWORD=" + password,
               "-p", f"127.0.0.1:{port}:3306", image)
        def connect():
            return pymysql.connect(host="127.0.0.1", port=port, user="root", password=password,
                cursorclass=pymysql.cursors.DictCursor, autocommit=True, connect_timeout=1)
        conn = None
        try:
            for _ in range(50):
                try:
                    conn = connect()
                    break
                except pymysql.MySQLError:
                    time.sleep(0.2)
            self.assertIsNotNone(conn)
            migrations = ROOT / "backend/db/migrations"
            up = (migrations / "017_access_event_conflicts_up.sql").read_text()
            prerequisites = "\n".join((migrations / file).read_text() for file in (
                "011_access_event_history_up.sql", "012_access_event_actor_ref_up.sql",
                "013_ha_access_event_outbox_up.sql",
                "015_mobile_diagnostics_up.sql"))
            docker("exec", "-i", name, "mariadb", "-uroot", "-p" + password,
                   input_text="CREATE DATABASE smart_gatekeeper;\n" + prerequisites + "\n" + up + "\n" + up)
            conn.select_db("smart_gatekeeper")
            def database():
                result = connect()
                result.select_db("smart_gatekeeper")
                return result
            payload = signed_canonical_event_payload()
            topic = main._canonical_target_event_topic(TARGET)
            with patch.multiple(main, COMMAND_TARGET_ID=TARGET, COMMAND_DOOR_ID=ACCESS_DOOR_ID,
                ACCESS_EVENT_REF_KEYS={"k1": ACCESS_REF_KEY}, _acl_target_credentials={},
                _ops_hmac_key=b"k" * 32), patch.object(main, "get_db", side_effect=database):
                first = main._persist_canonical_target_access_event(topic, payload, retained=False)
                self.assertTrue(first["inserted"])
                next_gatt = json.loads(payload)
                next_gatt["event_id"] = "cccccccc-bbbb-4ccc-8ddd-eeeeeeeeeeee"
                next_gatt["sequence"] += 1
                self.assertTrue(main._persist_canonical_target_access_event(
                    topic, sign_event(next_gatt), retained=False)["inserted"])
                # Different MAC-valid event with the same source position.
                altered = json.loads(payload)
                altered["event_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
                altered["event_code"] = "ACCESS_SIGNED_MANUAL_COMPLETED"
                altered["stage"] = "COMPLETE"
                altered["outcome"] = "SUCCEEDED"
                altered["reason_code"] = "ACCESS_GRANTED"
                altered["attributes"] = {"path": "mqtt_manual_remote", "transport": "signed_mqtt"}
                for event_id in ("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                                 "dddddddd-bbbb-4ccc-8ddd-eeeeeeeeeeee"):
                    altered["event_id"] = event_id
                    conflict = sign_event(altered)
                    for _ in range(3):  # ACK loss / new DB connection after replay.
                        stored = main._persist_canonical_target_access_event(topic, conflict, retained=False)
                        self.assertTrue(stored["quarantined"])
                        self.assertFalse(stored["inserted"])
                    altered["sequence"] += 1
                altered["event_id"] = "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee"
                following = main._persist_canonical_target_access_event(
                    topic, sign_event(altered), retained=False)
                self.assertTrue(following["inserted"])
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM access_event_conflicts")
                self.assertEqual(2, cur.fetchone()["n"])
                cur.execute("SELECT COUNT(*) AS n FROM access_event_history")
                self.assertEqual(3, cur.fetchone()["n"])
                cur.execute("SELECT COUNT(*) AS n FROM ha_access_event_outbox")
                self.assertEqual(1, cur.fetchone()["n"])  # Only the nonconflicting terminal.
                for sql in ("DELETE FROM access_event_conflicts",
                            "UPDATE access_event_conflicts SET reason_code='REPLACED'"):
                    with self.assertRaises(pymysql.MySQLError):
                        cur.execute(sql)
            docker("exec", "-i", name, "mariadb", "-uroot", "-p" + password,
                   input_text=(migrations / "017_access_event_conflicts_down.sql").read_text())
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM access_event_conflicts")
                self.assertEqual(2, cur.fetchone()["n"])
        finally:
            if conn is not None:
                conn.close()
            docker("rm", "-f", name)  # Only this randomly named isolated test DB.
