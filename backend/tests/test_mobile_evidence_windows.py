"""Relational pagination/window regressions without starting a shared service."""

import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import main
from backend.app.diagnostics_read import create_diagnostics_read_router
from backend.app.mobile_diagnostics import MobileDiagnosticBundle, bundle_event_bounds, bundle_evidence_metadata
from backend.tests.test_mobile_diagnostics import bundle


PHONE_A = "mobile-diagnostic-credential_" + "a" * 24
PHONE_B = "mobile-diagnostic-credential_" + "b" * 24
START = "2026-09-13T11:50:00Z"
END = "2026-09-13T12:00:00Z"
CUTOFF = "2026-09-13T13:10:00Z"


def epoch(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def evidence(at="2026-09-13T11:55:00Z", events=True):
    value = bundle()
    value["created_at"] = at
    value["native"]["runtime"] = dict(
        captured_epoch_ms=epoch(at), captured_elapsed_ms=1000, process_ref="c" * 16,
        pending_uploads=0, pending_events=1 if events else 0, dropped_events=0,
        lifecycle=[dict(sequence=1, event="DISPATCH_SKIPPED", reason="TARGET_NOT_READY",
                        at_epoch_ms=epoch(at), elapsed_ms=1000)] if events else [],
    )
    return value


class Cursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args=()):
        self.db.calls.append((sql, args))
        values = tuple(value.isoformat(sep=" ") if isinstance(value, datetime) else value for value in args)
        self.rows = self.db.conn.execute(sql.replace("%s", "?"), values)

    @staticmethod
    def row(raw):
        if raw is None:
            return None
        value = dict(raw)
        if "received_at" in value:
            value["received_at"] = datetime.fromisoformat(value["received_at"])
        return value

    def fetchall(self):
        return [self.row(raw) for raw in self.rows.fetchall()]

    def fetchone(self):
        return self.row(self.rows.fetchone())


class Database:
    """Execute the route's real predicate/order/limit against a local relation."""
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.calls = []
        self.conn.executescript("""
            CREATE TABLE mobile_diagnostic_bundles (
                id INTEGER PRIMARY KEY, bundle_ref TEXT, credential_ref TEXT, created_at_ms INTEGER,
                payload_json TEXT, received_at TEXT, event_first_epoch_ms INTEGER,
                event_last_epoch_ms INTEGER, captured_epoch_ms INTEGER, evidence_index_version INTEGER);
            CREATE TABLE access_event_history (
                id INTEGER PRIMARY KEY, collector_target_id TEXT, source_boot_id TEXT, source_boot_count INTEGER,
                session_id TEXT, event_code TEXT, event_path TEXT, event_outcome TEXT, reason_code TEXT,
                monotonic_ms INTEGER, source_sequence INTEGER, credential_ref TEXT, received_at TEXT, integrity_status TEXT);
            CREATE TABLE target_sensor_session_history (
                id INTEGER, target_id TEXT, source_boot_id TEXT, session_id TEXT, summary_json TEXT, received_at TEXT);
            CREATE TABLE target_health_history (
                id INTEGER, verified_json TEXT, advisory_json TEXT, received_at TEXT, target_id TEXT);
        """)

    def cursor(self):
        return Cursor(self)

    def close(self):
        pass

    def report(self, report_id, payload, phone=PHONE_A, received="2026-09-13 13:00:00", indexed=True):
        first, last = bundle_event_bounds(payload)
        self.conn.execute("INSERT INTO mobile_diagnostic_bundles VALUES (?,?,?,?,?,?,?,?,?,?)", (
            report_id, f"{report_id:032x}", phone, epoch(payload["created_at"]), json.dumps(payload), received,
            first if indexed else None, last if indexed else None,
            payload["native"].get("runtime", {}).get("captured_epoch_ms") if indexed else None,
            1 if indexed else None,
        ))


class EvidenceWindowsTest(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.addCleanup(self.db.conn.close)
        app = FastAPI()
        app.include_router(create_diagnostics_read_router(lambda: self.db, hashlib.sha256(b"x" * 43).hexdigest()))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def get(self, route="incidents", **params):
        response = self.client.get("/api/v1/diagnostics/" + route, params=params,
                                   headers={"Authorization": "Bearer " + "x" * 43})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("no-store", response.headers["cache-control"])
        return response.json()

    def test_late_evidence_in_same_incident_without_changing_receipt_default(self):
        self.db.report(1, evidence())
        old = self.get(since=START, until=END)
        self.assertEqual([], old["mobile_observations"])
        late = self.get(since=START, until=END, evidence_received_until=CUTOFF)
        self.assertEqual([], late["incidents"])
        self.assertEqual("1", late["mobile_incidents"][0]["report_id"])
        report = late["mobile_observations"][0]
        self.assertEqual("STALE_REPORT", report["freshness"])
        self.assertEqual("EVENTS_OBSERVED", report["evidence_status"])
        self.assertEqual(3900000, report["capture_to_receipt_ms"])
        self.assertFalse(report["receipt_is_current_health"])
        self.assertEqual(END, late["until"])
        self.assertEqual(CUTOFF, late["evidence_received_until"])

    def test_independent_cursor_reaches_more_than_twenty_and_filters_family(self):
        self.db.report(1, evidence(), phone=PHONE_B)
        for report_id in range(2, 27):
            self.db.report(report_id, evidence(), phone=PHONE_A)
        args = dict(occurred_since=START, occurred_until=END, evidence_received_until=CUTOFF)
        first = self.get(**args)
        self.assertIsNone(first["next_before_id"])
        self.assertEqual("7", first["next_mobile_before_id"])
        self.assertTrue(first["coverage"]["mobile_reports_truncated"])
        second = self.get(**args, mobile_before_id=7, before_id=999)
        self.assertEqual("1", second["mobile_observations"][-1]["id"])
        self.assertIsNone(second["next_mobile_before_id"])
        family = self.get(**args, mobile_ref=PHONE_B)
        self.assertEqual(["1"], [row["id"] for row in family["mobile_observations"]])
        listed = self.get("bundles", **args, mobile_ref=PHONE_B)
        self.assertEqual(PHONE_B, listed["bundles"][0]["mobile_ref"])

    def test_new_snapshot_and_empty_report_keep_event_gap_visible(self):
        self.db.report(1, evidence(events=False))
        late = self.get(occurred_since=START, occurred_until=END, evidence_received_until=CUTOFF)
        report = late["mobile_observations"][0]
        self.assertEqual("NO_EVENTS_IN_WINDOW", report["evidence_status"])
        self.assertIsNone(report["event_first_epoch_ms"])
        self.assertEqual([], late["mobile_incidents"])
        self.assertEqual("NO_ARRIVAL_OR_WAKE_INFERENCE", report["silence_classification"])

    def test_new_capture_does_not_move_old_failure_into_incident(self):
        payload = evidence("2026-09-13T10:00:00Z")
        payload["created_at"] = "2026-09-13T11:55:00Z"
        payload["native"]["runtime"]["captured_epoch_ms"] = epoch(payload["created_at"])
        self.db.report(1, payload)
        data = self.get(occurred_since=START, occurred_until=END, evidence_received_until=CUTOFF)
        self.assertEqual([], data["mobile_incidents"])
        self.assertEqual("NO_EVENTS_IN_WINDOW", data["mobile_observations"][0]["evidence_status"])
        self.assertEqual(str(epoch("2026-09-13T10:00:00Z")), data["mobile_observations"][0]["event_first_epoch_ms"])

    def test_legacy_unindexed_report_remains_pageable_and_clock_skew_explicit(self):
        payload = evidence()
        payload["native"]["runtime"]["captured_epoch_ms"] = epoch("2026-09-13T15:00:00Z")
        self.db.report(1, payload, indexed=False)
        data = self.get(occurred_since=START, occurred_until=END, evidence_received_until=CUTOFF)
        self.assertEqual("CLOCK_UNCERTAIN", data["mobile_observations"][0]["freshness"])
        self.assertIsNone(data["mobile_observations"][0]["scan"])
        self.assertEqual("LEGACY_UNKNOWN_USE_DETAIL", self.get("bundles")["bundles"][0]["event_range_index"])

    def test_window_exclusive_cutoff_and_duplicate_event_use_newest_report(self):
        for report_id in (1, 2):
            self.db.report(report_id, evidence())
        self.db.report(3, evidence(), received="2026-09-13 13:10:00")
        data = self.get(occurred_since=START, occurred_until=END, evidence_received_until=CUTOFF)
        self.assertEqual(["2", "1"], [row["id"] for row in data["mobile_observations"]])
        self.assertEqual(1, len(data["mobile_incidents"]))
        self.assertEqual("2", data["mobile_incidents"][0]["report_id"])

    def test_scan_and_wake_without_target_or_session_are_visible(self):
        payload = evidence(events=False)
        payload["wake_events"] = [dict(success=True, screen_interactive=False, received_epoch_ms=epoch(START))]
        payload["native"]["scan"] = dict(observation="RECENT_PACKET", last_packet_at_epoch_ms=epoch(START),
            lifecycle=[dict(event="REGISTER_ACCEPTED", at_epoch_ms=epoch(START))], callback_count=2, fresh_match_count=1)
        self.db.report(1, payload)
        data = self.get(occurred_since=START, occurred_until=END, evidence_received_until=CUTOFF)
        report = data["mobile_observations"][0]
        self.assertEqual(1, len(report["wake_events_in_window"]))
        self.assertEqual(1, len(report["scan_lifecycle_in_window"]))
        self.assertTrue(report["scan_is_historical"])
        self.assertEqual(2, report["scan_snapshot"]["callback_count"])

    def test_manual_open_context_is_not_automatic_failure_or_family_success(self):
        self.db.conn.execute("INSERT INTO access_event_history VALUES (1,'target','boot',901,?,'ACCESS_SIGNED_MANUAL_COMPLETED',"
            "'signed_manual','SUCCEEDED','ACCESS_GRANTED',1000,1,NULL,'2026-09-13 11:56:00','verified')",
            ("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",))
        payload = evidence()
        payload["native"]["runtime"]["lifecycle"][0]["event"] = "MANUAL_OPEN_CONTEXT"
        self.db.report(1, payload, phone=PHONE_A)
        args = dict(occurred_since=START, occurred_until=END, evidence_received_until=CUTOFF)
        data = self.get(**args, mobile_ref=PHONE_A)
        incident = data["incidents"][0]
        self.assertFalse(incident["automatic_failure_inferred"])
        self.assertEqual([], incident["mobile_report_matches"])
        self.assertEqual(["1"], incident["manual_context_report_candidates"])
        self.assertEqual("MANUAL_OPEN_CONTEXT", data["mobile_incidents"][0]["classification"])
        other = self.get(**args, mobile_ref=PHONE_B)
        self.assertEqual("DIAGNOSTIC_EVIDENCE_NOT_RECEIVED", other["incidents"][0]["mobile_evidence_status"])

    def test_validation_rejects_unbounded_or_partial_query_before_sql(self):
        for params in (dict(occurred_since=START), dict(mobile_ref="private-name"),
                       dict(since=START, until=END, evidence_received_until=START),
                       dict(since=START, until=END, evidence_received_until="2027-01-01T00:00:00Z"),
                       dict(mobile_limit=101), dict(mobile_before_id=0)):
            with self.subTest(params=params):
                response = self.client.get("/api/v1/diagnostics/incidents", params=params,
                    headers={"Authorization": "Bearer " + "x" * 43})
                self.assertEqual(422, response.status_code)
        self.assertEqual([], self.db.calls)

    def test_bundles_accept_a_historical_receipt_cutoff_without_occurrence_filter(self):
        self.db.report(1, evidence())
        data = self.get("bundles", evidence_received_until=CUTOFF)
        self.assertEqual("1", data["bundles"][0]["id"])


class EvidenceSchemaTest(unittest.TestCase):
    def test_runtime_extensions_are_optional_and_strict(self):
        old = bundle()
        self.assertEqual(old, MobileDiagnosticBundle.model_validate(old).model_dump(by_alias=True, exclude_unset=True))
        value = evidence()
        runtime = value["native"]["runtime"]
        runtime.update(event_first_epoch_ms=1, event_last_epoch_ms=2, upload_state="RETRY_WAIT",
            last_enqueue_epoch_ms=1, last_worker_start_epoch_ms=1, last_worker_stop_epoch_ms=2,
            last_upload_attempt_epoch_ms=1, next_attempt_epoch_ms=2, upload_attempt=1,
            journal_dropped=1, ring_dropped=2, export_trimmed=3, quarantined_dropped=1,
            quarantined_count=4, generation=2, latest_snapshot=True, incident_ref="a" * 16,
            ring_drop_first_epoch_ms=1, ring_drop_last_epoch_ms=2)
        self.assertEqual("RETRY_WAIT", MobileDiagnosticBundle.model_validate(value).native.runtime.upload_state)
        for change in (dict(pending_events=257), dict(pending_uploads=2), dict(quarantined_count=5),
                       dict(upload_attempt=True), dict(generation="1"), dict(latest_snapshot=1),
                       dict(upload_state="private URL"), dict(incident_ref="secret"),
                       dict(event_first_epoch_ms=-1), dict(quarantined_dropped=-1)):
            bad = copy.deepcopy(value)
            bad["native"]["runtime"].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                MobileDiagnosticBundle.model_validate(bad)

    def test_wall_clock_rollback_is_accepted_and_marked_uncertain_not_quarantined(self):
        value = evidence()
        value["native"]["runtime"].update(event_first_epoch_ms=200, event_last_epoch_ms=100)
        MobileDiagnosticBundle.model_validate(value)
        data = bundle_evidence_metadata(value, epoch(value["created_at"]), datetime(2026, 9, 13, 13), as_of_ms=epoch(CUTOFF))
        self.assertEqual("CLOCK_UNCERTAIN", data["freshness"])
        for invalid in (-1, True, "1"):
            bad = copy.deepcopy(value)
            bad["native"]["runtime"]["lifecycle"][0]["sequence"] = invalid
            with self.assertRaises(ValidationError):
                MobileDiagnosticBundle.model_validate(bad)

    def test_scan_extensions_preserve_closed_projection(self):
        payload = evidence()
        counters = ("callback_count", "empty_callback_count", "result_count", "filter_match_count", "fresh_match_count",
                    "stale_match_count", "missing_ready_hint_count", "malformed_ready_hint_count", "target_not_ready_count",
                    "callback_error_count", "dispatch_attempt_count", "dispatch_enqueued_count", "dispatch_skipped_count",
                    "owner_wait_count", "enqueue_failure_count")
        scan = dict(observation="NO_RECENT_PACKET", last_packet_at_epoch_ms=None, lifecycle=[],
                    **{key: 1 for key in counters})
        scan.update(last_callback_at_epoch_ms=1, last_error_at_epoch_ms=2, last_error_code=6,
            last_dispatch_at_epoch_ms=1, last_dispatch_reason="OWNER_WAIT", recovery_started_at_epoch_ms=1,
            recovery_deadline_at_epoch_ms=3, recovery_finished_at_epoch_ms=2,
            recovery_reason="FOREGROUND", recovery_outcome="NO_MATCHING_PACKET")
        payload["native"]["scan"] = scan
        self.assertEqual(1, MobileDiagnosticBundle.model_validate(payload).native.scan.owner_wait_count)
        nullable = copy.deepcopy(payload)
        nullable["native"]["scan"].update({key: None for key in scan if key not in ("observation", "lifecycle")})
        MobileDiagnosticBundle.model_validate(nullable)
        for key, value in (("callback_count", True), ("last_error_code", 65536), ("recovery_outcome", "https://secret"), ("raw_payload", "secret")):
            bad = copy.deepcopy(payload)
            bad["native"]["scan"][key] = value
            with self.assertRaises(ValidationError):
                MobileDiagnosticBundle.model_validate(bad)

    def test_storage_indexes_event_times_without_changing_immutable_payload(self):
        payload = evidence()
        conn = MagicMock()
        with patch.object(main, "get_db", return_value=conn), patch.object(main, "_ops_hmac_key", b"o" * 32):
            main._store_mobile_diagnostics("a" * 32, "1" * 32, payload)
        sql, args = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
        self.assertIn("event_first_epoch_ms", sql)
        self.assertEqual((epoch(payload["created_at"]), epoch(payload["created_at"]), epoch(payload["created_at"]), 1), args[-4:])
        self.assertEqual(payload, json.loads(args[4]))
        self.assertEqual(hashlib.sha256(args[4].encode()).hexdigest(), args[5])

    def test_loss_and_old_ack_do_not_declare_current_upload_complete(self):
        value = evidence()
        value["native"]["runtime"].update(last_upload_success_epoch_ms=1, dropped_events=5,
                                         pending_uploads=0, pending_events=2, upload_state="RETRY_WAIT")
        data = bundle_evidence_metadata(value, epoch(value["created_at"]), datetime(2026, 9, 13, 13), as_of_ms=epoch(CUTOFF))
        self.assertEqual("STALE_REPORT", data["freshness"])
        self.assertIn("PENDING_AT_CAPTURE", data["gaps"])
        self.assertIn("COLLECTION_LOSS_REPORTED", data["gaps"])
        self.assertEqual("RETRY_WAIT", data["upload"]["state"])
        self.assertTrue(data["upload"]["values_are_capture_snapshot"])

    def test_migration_packages_additive_nullable_indexes_and_preserves_rollback(self):
        root = Path(__file__).resolve().parents[2]
        up = root / "backend/db/migrations/018_mobile_evidence_window_up.sql"
        text = up.read_text()
        for field in ("event_first_epoch_ms", "event_last_epoch_ms", "captured_epoch_ms", "evidence_index_version"):
            self.assertIn("ADD COLUMN IF NOT EXISTS " + field, text)
        self.assertNotIn("UPDATE mobile_diagnostic_bundles", text)
        self.assertNotIn("DROP TRIGGER", text)
        self.assertIn("(credential_ref, id)", text)
        manifest = (root / "backend/db/schema.env").read_text()
        self.assertIn("SCHEMA_VERSION=018", manifest)
        self.assertIn(hashlib.sha256(up.read_bytes()).hexdigest(), manifest)
        dockerfile = (root / "backend/db/Dockerfile").read_text()
        self.assertIn("018_mobile_evidence_window_up.sql", dockerfile)
        down = (root / "backend/db/migrations/018_mobile_evidence_window_down.sql").read_text()
        self.assertNotIn("DROP TABLE", down)
        self.assertNotIn("DELETE", down)
