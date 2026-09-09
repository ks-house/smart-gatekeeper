import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import unittest
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pymysql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import main
from backend.app.acl_api import AclApiConfig, create_acl_router
from backend.app.diagnostics_read import create_diagnostics_read_router
from backend.app.mobile_diagnostics import MobileDiagnosticBundle
from backend.app.reliability_diagnostics import (
    BootAdvisoryCache, advisory_projection, boot_observation_projection,
    build_access_receipt, build_sensor_receipt, classify_incident, sensor_mac_input,
    verified_sensor_summary, record_verified_health, record_sensor_summary,
)
from backend.tests.test_mobile_diagnostics import FakeService, bundle

ROOT = Path(__file__).resolve().parents[2]
KEY = bytes(range(1, 33))
TARGET = "test-target"
BOOT = "00112233445566778899aabbccddeeff"
SESSION = "00000000-0000-4000-8000-000000000001"


def status_value():
    return dict(target_id=TARGET, source_boot_id=BOOT, source_boot_count=782, status_revision=1,
                state="IDLE", last_terminal_session_id=SESSION, last_terminal_event_sequence=8,
                last_terminal_event_code="ACCESS_SESSION_TERMINATED", last_terminal_reason_code="ARM_TIMEOUT",
                last_terminal_credential_ref=None, last_terminal_phase_mask=3,
                relay_commanded_on=False, relay_pin_level=1)


def sensor_value():
    return dict(schema_version=1, source_boot_id=BOOT, source_boot_count="782", session_id=SESSION,
                terminal_sequence="8", started_monotonic_ms="1000", ended_monotonic_ms="61013",
                threshold_mm=500, samples=10, valid_samples=4, timeouts=5, invalid_samples=1,
                in_range_samples=2, blocked_samples=4, clear_samples=2,
                min_raw_mm=250, max_raw_mm=800, last_raw_mm=None, last_median_mm=450,
                blocked_at_start=True, blocked_at_end=True, clearance_state="UNKNOWN")


def sensor_document(summary=None):
    summary = summary or sensor_value()
    return dict(sensor_session_summary=summary, sensor_summary_auth=dict(version=1, key_id="a1",
                tag=hmac.new(KEY, sensor_mac_input(summary, "a1", TARGET), hashlib.sha256).digest()[:16].hex()))


class ReliabilityContractTest(unittest.TestCase):
    def test_ota_projection_is_bounded_unsigned_and_revalidated(self):
        ota = dict(schema=1, attempt=2, boot_count=809, updated_uptime_ms=3600000,
                   stage=12, failed_stage=3, error=5, http_code=-1, transport_code=-9984,
                   bytes=0, total=0, heap_before=63000, heap_after=120000, largest_after=60000,
                   target_version="", persisted=True, restored=False, request_pending=False,
                   runtime_status=11, rejection=0, flash_code=0)
        result = advisory_projection(dict(ota={**ota, "secret": "discard"}))
        self.assertEqual(result, dict(ota=ota))
        self.assertEqual(result, advisory_projection(result))
        for key, bad in (("schema", True), ("stage", 16), ("error", 20),
                         ("http_code", True), ("transport_code", 2**31), ("bytes", 1),
                         ("target_version", "https://private"), ("persisted", "true")):
            self.assertEqual({}, advisory_projection(dict(ota={**ota, key: bad})))

    def test_audit_health_projection_is_closed_unsigned(self):
        value = dict(mqtt_audit_durable_depth=2, mqtt_audit_pending_depth=3,
                     mqtt_audit_head_wait_ms=16000, mqtt_audit_head_publish_attempts=8,
                     mqtt_audit_head_boot_count=808, mqtt_audit_stalled=True)
        self.assertEqual(value, advisory_projection({**value, "private_key": "not exported"}))
        self.assertEqual({}, advisory_projection(dict(mqtt_audit_stalled="true",
                         mqtt_audit_durable_depth=-1, mqtt_audit_head_wait_ms=2**32)))

    def test_boot_cache_retained_exact_match_and_closed_redaction(self):
        cache = BootAdvisoryCache(clock=lambda: 123)
        doc = dict(target_id=TARGET, boot_id=BOOT, boot_count=782, firmware="2.1.469+main.g6a45aec",
            planned_restart="ota_pending_verify", previous_action="restart:ota_pending_verify",
            reset_reason="BROWNOUT", previous_valid=True, previous_state="ARMED", previous_access_stage="CHALLENGE_ISSUED",
            previous_access_session_id=SESSION, largest_free_block=16000, mqtt_last_error=-2,
            sensor_clearance_state="OCCUPIED", gatt_proofs_verified=3,
            ip="private", wifi_bssid="private", coredump_panic_reason="private", private_key="private",
            boot_observation={"provenance": "forged"})
        self.assertTrue(cache.observe(f"gatekeeper/v1/targets/{TARGET}/boot", json.dumps(doc).encode(),
                                     retained=True, configured_targets={TARGET}))
        value = cache.match_verified(status_value())
        self.assertEqual("UNSIGNED", value["integrity_status"])
        self.assertEqual("MQTT_BOOT_ADVISORY", value["provenance"])
        self.assertEqual("123000", value["received_epoch_ms"])
        self.assertTrue(value["retained"])
        self.assertEqual("NOT_OBSERVED", value["generation_time"])
        self.assertEqual("ota_pending_verify", value["fields"]["planned_restart"])
        self.assertEqual("restart:ota_pending_verify", value["fields"]["previous_action"])
        self.assertEqual(SESSION, value["fields"]["previous_access_session_id"])
        self.assertEqual(-2, value["fields"]["mqtt_last_error"])
        self.assertNotIn("private", json.dumps(value))
        self.assertNotIn("boot_observation", value["fields"])
        for mismatch in ({"source_boot_count": 783}, {"source_boot_id": "f"*32}, {"target_id": "other"}):
            self.assertIsNone(cache.match_verified({**status_value(), **mismatch}))
        value["fields"]["planned_restart"] = "mutated"
        self.assertEqual("ota_pending_verify", cache.match_verified(status_value())["fields"]["planned_restart"])

    def test_boot_cache_rejects_malformed_exact_topics_and_is_bounded(self):
        cache = BootAdvisoryCache(max_entries=2)
        doc = dict(target_id=TARGET, boot_id=BOOT, boot_count=782)
        topic = f"gatekeeper/v1/targets/{TARGET}/boot"
        for candidate, payload, allowed in ((topic+"/extra", json.dumps(doc).encode(), {TARGET}),
                (topic, json.dumps(doc).encode(), {"other"}),
                (topic, b" "*4097, {TARGET}), (topic, b'{"target_id":"a","target_id":"b"}', {TARGET}),
                (topic, json.dumps({**doc, "boot_count": True}).encode(), {TARGET}),
                (topic, json.dumps({**doc, "target_id": "other"}).encode(), {TARGET}),
                (topic, json.dumps({**doc, "boot_id": "f"*64}).encode(), {TARGET}),
                (topic, b'{"boot_count":NaN}', {TARGET})):
            self.assertFalse(cache.observe(candidate, payload, retained=True, configured_targets=allowed))
        for count in (782, 783, 784):
            self.assertTrue(cache.observe(topic, json.dumps({**doc, "boot_count": count}).encode(),
                                          retained=False, configured_targets={TARGET}))
        self.assertIsNone(cache.match_verified(status_value()))
        self.assertIsNotNone(cache.match_verified({**status_value(), "source_boot_count": 784}))
        self.assertEqual({}, advisory_projection(dict(previous_action="PRIVATE_TOKEN", previous_access_stage="PRIVATE_TOKEN",
             planned_restart="PRIVATE_TOKEN", reset_reason="PRIVATE_TOKEN", gatt_proofs_verified=True,
             previous_access_session_id="PRIVATE_TOKEN", largest_free_block=-1)))

    def test_boot_advisory_attaches_only_after_verified_accepted_status(self):
        cache = BootAdvisoryCache(clock=lambda: 123)
        doc = dict(target_id=TARGET, boot_id=BOOT, boot_count=782, planned_restart="ota_health_heap_timeout")
        cache.observe(f"gatekeeper/v1/targets/{TARGET}/boot", json.dumps(doc).encode(),
                      retained=True, configured_targets={TARGET})
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        status = {**status_value(), "integrity_key_id": "a1", "integrity_tag": bytes(16)}
        for key in ("last_terminal_session_id", "last_terminal_event_sequence", "last_terminal_event_code",
                    "last_terminal_reason_code", "last_terminal_credential_ref"):
            status[key] = None
        status["last_terminal_phase_mask"] = 0
        with patch.object(main, "_boot_advisories", cache), patch.object(main, "get_db", return_value=conn), \
             patch.object(main, "_parse_authenticated_target_status", return_value=None):
            self.assertIsNone(main._persist_authenticated_target_status(TARGET, b"unsigned", retained=False))
        conn.begin.assert_not_called()
        with patch.object(main, "_boot_advisories", cache), patch.object(main, "get_db", return_value=conn), \
             patch.object(main, "_parse_authenticated_target_status", return_value=status):
            result = main._persist_authenticated_target_status(TARGET, b"verified", retained=False)
        self.assertTrue(result["advanced"])
        conn.commit.assert_called_once()
        insert = next(c for c in cur.execute.call_args_list if "INSERT INTO target_health_history" in c.args[0])
        self.assertNotIn("boot_observation", json.loads(insert.args[1][7]))
        stored = json.loads(insert.args[1][8])["boot_observation"]
        self.assertEqual("UNSIGNED", stored["integrity_status"])
        self.assertEqual("ota_health_heap_timeout", stored["fields"]["planned_restart"])
        self.assertEqual([], classify_incident([])["explicit_reasons"])

    def test_native_producer_report_accepted_by_authenticated_api(self):
        result_xml = ROOT / "gatekeeper_app/build/app/test-results/testDebugUnitTest/TEST-com.kshouse.gatekeeper_app.gattworker.NativeDiagnosticsTest.xml"
        if not result_xml.exists():
            self.skipTest("run NativeDiagnosticsTest first for cross-language producer integration")
        output = ET.parse(result_xml).getroot().findtext("system-out", "")
        if "NATIVE_DIAGNOSTIC_FIXTURE=" not in output:
            self.skipTest("native producer fixture not emitted by this build")
        payload = json.loads(output.split("NATIVE_DIAGNOSTIC_FIXTURE=", 1)[1].splitlines()[0])
        captured = []
        app = FastAPI()
        app.include_router(create_acl_router(FakeService(), AclApiConfig(
            enabled=True, enrollment_credentials={}, admin_key="unused", target_credentials={},
            personal_enabled=True, personal_api_key="mobile-key", personal_tenant_id="a"*32,
            personal_door_id="b"*32, personal_diagnostics_ingest=lambda tenant, credential, value:
                captured.append((tenant, credential, value)) or
                dict(accepted=True, bundle_ref=value["bundle_ref"], deduplicated=False))))
        client = TestClient(app)
        body = dict(device_id="DEV-TEST-1234", credential_id="1"*32,
                    public_key_sec1="04" + "2"*128, bundle=payload)
        self.assertEqual(401, client.post("/api/v1/acl/personal/diagnostics", json=body).status_code)
        self.assertFalse(captured)
        response = client.post("/api/v1/acl/personal/diagnostics", json=body,
                               headers={"X-API-KEY": "mobile-key"})
        self.assertEqual(200, response.status_code, response.text)
        self.assertIs(True, response.json()["accepted"])
        self.assertEqual(payload["bundle_ref"], response.json()["bundle_ref"])
        self.assertEqual(MobileDiagnosticBundle.model_validate(payload).native.runtime.model_dump(),
                         captured[0][2]["native"]["runtime"])

    def test_access_receipt_cross_language_vector_and_domain_separation(self):
        event = dict(collector_target_id=TARGET, event_id=SESSION, source_boot_id=BOOT,
                     source_boot_count=782, source_sequence=9007199254740993,
                     integrity_tag="a0a1a2a3a4a5a6a7a8a9aaabacadaeaf", integrity_key_id="a1",
                     integrity_status="verified")
        receipt = json.loads(build_access_receipt(event, {"a1": KEY}))
        self.assertEqual("e965e03f7c5ab76921e0668bdd17a377", receipt["tag"])
        self.assertEqual("9007199254740993", receipt["source_sequence"])
        self.assertEqual("access_event_receipt", receipt["type"])
        self.assertNotIn("command", receipt)
        for values in ({"integrity_status": "legacy_unsigned"}, {"source_sequence": True},
                       {"source_boot_count": 0}, {"event_id": "not-a-uuid"}):
            with self.assertRaises(ValueError):
                build_access_receipt({**event, **values}, {"a1": KEY})
        stored = status_value()
        stored.update(sensor_document())
        sensor = json.loads(build_sensor_receipt(stored, {"a1": KEY}))
        self.assertEqual("sensor_session_receipt", sensor["type"])
        self.assertEqual(SESSION, sensor["session_id"])
        self.assertNotIn("event_id", sensor)
        self.assertNotEqual(receipt["tag"], sensor["tag"])
        for key in (KEY[:16], bytes(32), KEY + b"x"):
            with self.assertRaises(ValueError):
                build_access_receipt(event, {"a1": key})

    def test_sensor_exact_firmware_vector_and_millis_wrap(self):
        summary = dict(schema_version=1, source_boot_id=BOOT, source_boot_count="782",
            session_id="00000000-0000-4000-8000-000000000002", terminal_sequence="9",
            started_monotonic_ms="1000", ended_monotonic_ms="61000", threshold_mm=500,
            samples=4, valid_samples=2, timeouts=1, invalid_samples=1, in_range_samples=1,
            blocked_samples=3, clear_samples=1, min_raw_mm=300, max_raw_mm=900,
            last_raw_mm=900, last_median_mm=700, blocked_at_start=True, blocked_at_end=False,
            clearance_state="CLEAR")
        fields = ["SGK-SENSOR-SESSION-MAC-V1", "a1", "target-1", BOOT, "782", summary["session_id"],
            "9", "1000", "61000", "500", "4", "2", "1", "1", "1", "3", "1", "300", "900", "900", "700", "1", "0", "CLEAR"]
        self.assertEqual("\n".join(fields).encode(), sensor_mac_input(summary, "a1", "target-1"))
        wrapped = {**summary, "started_monotonic_ms": "4294967290", "ended_monotonic_ms": "10"}
        self.assertTrue(sensor_mac_input(wrapped, "a1", "target-1"))

    def test_sensor_summary_authentication_prior_boot_and_closed_schema(self):
        document = sensor_document()
        self.assertEqual(sensor_value(), verified_sensor_summary(document, status_value(), {"a1": KEY}))
        # An older durable summary may be carried by a new boot without pretending
        # it belongs to the newest terminal. Its separate MAC preserves identity.
        later = {**status_value(), "source_boot_count": 783, "source_boot_id": "f" * 32,
                 "last_terminal_session_id": None, "last_terminal_event_sequence": None}
        self.assertEqual(sensor_value(), verified_sensor_summary(document, later, {"a1": KEY}))
        self.assertIsNone(verified_sensor_summary(document, {**later, "source_boot_count": 782}, {"a1": KEY}))
        self.assertIsNone(verified_sensor_summary(document, status_value(), {"a1": b"z" * 32}))
        for values in ({"samples": 11}, {"source_boot_count": "0782"}, {"terminal_sequence": 8},
                       {"blocked_at_start": 1}, {"private_key": "secret"}, {"min_raw_mm": None},
                       {"clear_samples": 5}, {"last_raw_mm": 10001}):
            bad = {**sensor_value(), **values}
            with self.assertRaises(ValueError):
                sensor_mac_input(bad, "a1", TARGET)
        tampered = {**document, "sensor_session_summary": {**sensor_value(), "threshold_mm": 600}}
        self.assertIsNone(verified_sensor_summary(tampered, status_value(), {"a1": KEY}))

    def test_runtime_is_optional_strict_bounded_and_legacy_bytes_unchanged(self):
        value = bundle()
        self.assertNotIn("runtime", MobileDiagnosticBundle.model_validate(value).model_dump(exclude_unset=True)["native"])
        value["native"]["runtime"] = dict(captured_epoch_ms=1, captured_elapsed_ms=1, process_ref="a"*16,
            pending_uploads=1, oldest_pending_epoch_ms=1, last_upload_success_epoch_ms=None,
            last_upload_code=None, dropped_events=0,
            lifecycle=[dict(event="DISPATCH_SKIPPED", at_epoch_ms=1, elapsed_ms=1,
                            reason="TARGET_NOT_READY", session_ref=None, ready=False, ready_epoch=1, status=None)])
        self.assertEqual(1, MobileDiagnosticBundle.model_validate(value).native.runtime.pending_uploads)
        for change in ({"pending_uploads": 2}, {"captured_elapsed_ms": True},
                       {"lifecycle": value["native"]["runtime"]["lifecycle"] * 65}, {"raw_payload": "secret"}):
            bad = json.loads(json.dumps(value))
            bad["native"]["runtime"].update(change)
            with self.assertRaises(ValidationError):
                MobileDiagnosticBundle.model_validate(bad)

    def test_classifier_separates_positive_reason_from_failure_and_sensor_evidence(self):
        events = [dict(event_code="ACCESS_GATT_CONNECTED", reason_code="GATT_CONNECTED", event_outcome="SUCCEEDED", monotonic_ms=1000),
                  dict(event_code="ACCESS_PROOF_VERIFIED", reason_code="PROOF_VALID", event_outcome="SUCCEEDED", monotonic_ms=1400),
                  dict(event_code="ACCESS_ARMED", reason_code="ARM_ACCEPTED", event_outcome="SUCCEEDED", monotonic_ms=1500)]
        result = classify_incident(events)
        self.assertEqual([], result["explicit_reasons"])
        self.assertEqual("CHALLENGE", result["first_missing_stage"])
        events.append(dict(event_code="ACCESS_SESSION_TERMINATED", event_outcome="TIMED_OUT",
                           reason_code="ARM_TIMEOUT", monotonic_ms=61513))
        result = classify_incident(events, sensor_value())
        self.assertEqual("EXPLICIT_FAILURE", result["classification"])
        self.assertEqual("SENSOR_REARM_BLOCK_OBSERVED", result["sensor_boundary"])
        self.assertEqual(60513, result["source_span_ms"])
        self.assertEqual("UNRESOLVED", result["owner_attribution"])
        self.assertEqual("NOT_OBSERVABLE", result["physical_door"])

    def test_manual_flow_does_not_require_gatt_and_event_millis_wrap_is_bounded(self):
        events = [dict(event_code=code, event_path="mqtt_manual_remote", event_outcome="SUCCEEDED",
                       reason_code="ACCESS_GRANTED", monotonic_ms=when)
                  for code, when in (("ACCESS_MANUAL_OPEN_RECEIVED", 4294967290),
                                     ("ACCESS_RELAY_ON", 4294967294), ("ACCESS_RELAY_OFF", 9),
                                     ("ACCESS_SIGNED_MANUAL_COMPLETED", 10))]
        result = classify_incident(events)
        self.assertEqual("FLOW_REPORTED_COMPLETE", result["classification"])
        self.assertEqual("DOOR_CONTACT", result["first_missing_stage"])
        self.assertNotIn("GATT", result["observed_stages"])
        self.assertEqual(16, result["source_span_ms"])

    def test_worker_receipts_only_for_committed_event_and_survives_receipt_failure(self):
        event = dict(event_id=SESSION)
        receipt = MagicMock(side_effect=RuntimeError("offline"))
        worker = main._CanonicalAccessEventWorker(persist=MagicMock(side_effect=[
            None, False, {"inserted": True, "event": event}, {"inserted": False, "event": event},
        ]), on_commit=receipt)
        for _ in range(4):
            worker.request("topic", b"bytes", False)
        worker._queue.join()
        self.assertEqual(2, receipt.call_count)
        self.assertTrue(worker.healthy)
        worker.stop()

    def test_duplicate_status_receipt_does_not_refresh_live_registry(self):
        stored = {**status_value(), **sensor_document(), "advanced": False}
        registry, receipt = MagicMock(), MagicMock()
        worker = main._AuthenticatedTargetStatusWorker(persist=MagicMock(return_value=stored),
                    registry=registry, on_commit=receipt)
        worker.connect_transport()
        worker.request(TARGET, b"bytes", False)
        worker._queue.join()
        worker.stop()
        receipt.assert_called_once_with(TARGET, stored)
        registry.note_verified.assert_not_called()


class ReliabilityReadTest(unittest.TestCase):
    def setUp(self):
        self.db, self.token = MagicMock(), "x" * 43
        self.cur = self.db.return_value.cursor.return_value.__enter__.return_value
        self.cur.fetchall.return_value = []
        app = FastAPI()
        app.include_router(create_diagnostics_read_router(self.db, hashlib.sha256(self.token.encode()).hexdigest()))
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer " + self.token}

    def test_read_routes_are_no_store_read_only_and_auth_first(self):
        for route in ("health-history", "incidents"):
            path = "/api/v1/diagnostics/" + route
            self.assertEqual(401, self.client.get(path).status_code)
            for method in ("POST", "DELETE", "PUT"):
                self.assertEqual(405, self.client.request(method, path, headers=self.headers).status_code)
        self.db.assert_not_called()
        for route in ("health-history", "incidents"):
            response = self.client.get("/api/v1/diagnostics/" + route, headers=self.headers)
            self.assertEqual(200, response.status_code)
            self.assertEqual("no-store", response.headers["cache-control"])
        self.assertTrue(response.json()["coverage"]["absence_is_not_success"])

    def test_health_boot_advisory_reprojection_rejects_mismatch_and_private_fields(self):
        cache = BootAdvisoryCache(clock=lambda: 123)
        cache.observe(f"gatekeeper/v1/targets/{TARGET}/boot", json.dumps(dict(target_id=TARGET,
            boot_id=BOOT, boot_count=782, planned_restart="ota_pending_verify")).encode(),
            retained=True, configured_targets={TARGET})
        boot = cache.match_verified(status_value())
        boot["fields"].update(private_key="must-not-escape", previous_action="PRIVATE_TOKEN",
                              previous_access_stage="PRIVATE_TOKEN")
        for mismatch in (False, True):
            item = json.loads(json.dumps(boot))
            if mismatch:
                item["source_boot_count"] = "781"
            self.cur.fetchall.return_value = [dict(id=1, verified_json=json.dumps(status_value()),
                advisory_json=json.dumps(dict(boot_observation=item)), received_at=datetime(2026, 9, 8))]
            response = self.client.get("/api/v1/diagnostics/health-history", headers=self.headers)
            self.assertEqual(200, response.status_code, response.text)
            row = response.json()["history"][0]
            self.assertNotIn("boot_observation", row["verified"])
            self.assertNotIn("must-not-escape", response.text)
            self.assertNotIn("PRIVATE_TOKEN", response.text)
            if mismatch:
                self.assertNotIn("boot_observation", row["unsigned_advisory"])
            else:
                self.assertEqual("UNSIGNED", row["unsigned_advisory"]["boot_observation"]["integrity_status"])
                self.assertTrue(row["unsigned_advisory"]["boot_observation"]["retained"])

    def test_health_projection_and_filters_do_not_promote_unsigned_fields(self):
        self.cur.fetchall.return_value = [dict(id=2, verified_json=json.dumps(status_value()),
            advisory_json=json.dumps(dict(firmware="test", reset_reason="BROWNOUT", private_key="must-not-escape",
                mqtt_status_worker_published=3, mqtt_audit_receipts_accepted=4, sensor_summary_capture_pending=1)),
            received_at=datetime(2026, 9, 8, 12)), dict(id=1)]
        response = self.client.get("/api/v1/diagnostics/health-history", headers=self.headers,
            params=dict(since="2026-09-08T00:00:00+09:00", until="2026-09-09T00:00:00+09:00",
                        target_id=TARGET, boot_count=782, limit=1, before_id=3))
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("2", data["next_before_id"])
        self.assertEqual("782", data["history"][0]["verified"]["source_boot_count"])
        self.assertEqual("BROWNOUT", data["history"][0]["unsigned_advisory"]["reset_reason"])
        self.assertEqual(3, data["history"][0]["unsigned_advisory"]["mqtt_status_worker_published"])
        self.assertEqual(4, data["history"][0]["unsigned_advisory"]["mqtt_audit_receipts_accepted"])
        self.assertEqual(1, data["history"][0]["unsigned_advisory"]["sensor_summary_capture_pending"])
        self.assertNotIn("must-not-escape", response.text)
        self.assertEqual((datetime(2026, 9, 7, 15), datetime(2026, 9, 8, 15), TARGET, 782, 3, 2),
                         self.cur.execute.call_args.args[1])

    def test_incident_stale_mobile_is_not_owner_wake_and_batched_events_keep_span(self):
        group = dict(collector_target_id=TARGET, source_boot_id=BOOT, session_id=SESSION, latest_id=9)
        events = [dict(id=8, collector_target_id=TARGET, source_boot_id=BOOT, source_boot_count=782,
                       session_id=SESSION, event_code="ACCESS_ARMED", event_outcome="SUCCEEDED", reason_code="ARM_ACCEPTED",
                       monotonic_ms=1000, source_sequence=8, credential_ref=None, received_at=datetime(2026, 9, 8, 12, 57, 44)),
                  dict(id=9, collector_target_id=TARGET, source_boot_id=BOOT, source_boot_count=782,
                       session_id=SESSION, event_code="ACCESS_SESSION_TERMINATED", event_outcome="TIMED_OUT", reason_code="ARM_TIMEOUT",
                       monotonic_ms=61013, source_sequence=9, credential_ref=None, received_at=datetime(2026, 9, 8, 12, 57, 45))]
        mobile = dict(id=1, credential_ref="mobile-diagnostic-credential_" + "a"*24,
                      created_at_ms=1, payload_json=json.dumps(bundle()), received_at=datetime(2026, 9, 7))
        self.cur.fetchall.side_effect = [[group], events, [], [mobile], []]
        response = self.client.get("/api/v1/diagnostics/incidents", headers=self.headers,
                  params=dict(since="2026-09-08T12:30:00Z", until="2026-09-08T13:30:00Z", target_id=TARGET))
        self.assertEqual(200, response.status_code, response.text)
        data = response.json()
        self.assertEqual(60013, data["incidents"][0]["source_span_ms"])
        self.assertEqual("EXPLICIT_FAILURE", data["incidents"][0]["classification"])
        self.assertEqual([], data["incidents"][0]["mobile_report_matches"])
        self.assertEqual("STALE_REPORT", data["mobile_observations"][0]["freshness"])
        self.assertIsNone(data["mobile_observations"][0]["scan"])
        self.assertFalse(data["snapshot_atomic"])

    def test_invalid_window_and_storage_failure_are_safe(self):
        for route in ("incidents", "health-history"):
            self.assertEqual(422, self.client.get("/api/v1/diagnostics/" + route,
                headers=self.headers, params={"since": "not-a-date"}).status_code)
        self.db.assert_not_called()
        self.cur.execute.side_effect = RuntimeError("secret detail")
        response = self.client.get("/api/v1/diagnostics/incidents", headers=self.headers)
        self.assertEqual(503, response.status_code)
        self.assertNotIn("secret", response.text)
        self.db.return_value.close.assert_called_once()

    def test_mobile_only_skip_and_failed_session_are_incidents_without_target_events(self):
        payload = bundle()
        epoch = int(datetime(2026, 9, 8, 12, 55, tzinfo=timezone.utc).timestamp()*1000)
        payload["native"]["runtime"] = dict(captured_epoch_ms=epoch, captured_elapsed_ms=123,
            process_ref="a"*16, pending_uploads=0, dropped_events=0,
            lifecycle=[dict(event="DISPATCH_SKIPPED", reason="TARGET_NOT_READY",
                            at_epoch_ms=epoch, elapsed_ms=123)])
        payload["sessions"] = [dict(state="FAILED", reason_code="GATT_DISCONNECTED", updated_epoch_ms=epoch)]
        mobile = dict(id=1, credential_ref="mobile-diagnostic-credential_" + "a"*24,
                      created_at_ms=epoch, payload_json=json.dumps(payload), received_at=datetime(2026, 9, 8, 12, 56))
        self.cur.fetchall.side_effect = [[], [], [mobile], []]
        response = self.client.get("/api/v1/diagnostics/incidents", headers=self.headers,
            params=dict(since="2026-09-08T12:30:00Z", until="2026-09-08T12:57:00Z"))
        self.assertEqual(200, response.status_code, response.text)
        data = response.json()
        self.assertEqual([], data["incidents"])
        self.assertEqual(2, len(data["mobile_incidents"]))
        self.assertEqual("TARGET_NOT_READY", data["mobile_incidents"][0]["event"]["reason"])
        self.assertEqual("RECENT_REPORT", data["mobile_observations"][0]["freshness"])

    def test_sensor_summary_without_surviving_event_chain_remains_visible(self):
        row = dict(id=1, target_id=TARGET, source_boot_id=BOOT, session_id=SESSION,
                   summary_json=json.dumps(sensor_value()), received_at=datetime(2026, 9, 8, 12, 57))
        self.cur.fetchall.side_effect = [[], [row], [], []]
        response = self.client.get("/api/v1/diagnostics/incidents", headers=self.headers)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(1, len(response.json()["sensor_observations"]))
        self.assertEqual([], response.json()["incidents"])


@unittest.skipUnless(os.getenv("RUN_MARIADB_INTEGRATION") == "1", "set RUN_MARIADB_INTEGRATION=1")
class ReliabilityMariaDbTest(unittest.TestCase):
    def test_real_migration_sampling_immutability_retention_and_sensor_replay(self):
        name = "sgk-reliability-test-" + uuid.uuid4().hex[:10]
        password = "isolated-test-only"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        def docker(*args, input_text=None, check=True):
            return subprocess.run(["docker", *args], input=input_text, text=True, capture_output=True, check=check)
        image = (ROOT / "backend/db/Dockerfile").read_text().splitlines()[0].split(" ", 1)[1]
        docker("run", "--rm", "-d", "--name", name, "-e", "MARIADB_ROOT_PASSWORD=" + password,
               "-p", f"127.0.0.1:{port}:3306", image)
        conn = None
        try:
            for _ in range(50):
                try:
                    conn = pymysql.connect(host="127.0.0.1", port=port, user="root", password=password,
                        cursorclass=pymysql.cursors.DictCursor, autocommit=False, connect_timeout=1)
                    break
                except pymysql.MySQLError:
                    time.sleep(0.2)
            self.assertIsNotNone(conn, "isolated MariaDB did not become ready")
            up = (ROOT / "backend/db/migrations/016_reliability_history_up.sql").read_text()
            prerequisites = "\n".join((ROOT / "backend/db/migrations" / path).read_text() for path in (
                "011_access_event_history_up.sql", "012_access_event_actor_ref_up.sql", "015_mobile_diagnostics_up.sql"))
            docker("exec", "-i", name, "mariadb", "-uroot", "-p" + password,
                   input_text="CREATE DATABASE smart_gatekeeper;\n" + prerequisites + "\n" + up + "\n" + up)
            conn.select_db("smart_gatekeeper")
            with conn.cursor() as cur:
                record_verified_health(cur, status_value())
                conn.commit()
                record_verified_health(cur, {**status_value(), "status_revision": 2})
                conn.commit()
                cur.execute("SELECT COUNT(*) AS n FROM target_health_history")
                self.assertEqual(1, cur.fetchone()["n"])
                record_verified_health(cur, {**status_value(), "status_revision": 3, "state": "ARMED"})
                conn.commit()
                cur.execute("SELECT COUNT(*) AS n FROM target_health_history")
                self.assertEqual(2, cur.fetchone()["n"])
                for sql in ("UPDATE target_health_history SET gate_state='IDLE'", "DELETE FROM target_health_history"):
                    with self.assertRaises(pymysql.MySQLError):
                        cur.execute(sql)
                    conn.rollback()
                stored = {**status_value(), **sensor_document()}
                record_sensor_summary(cur, stored)
                conn.commit()
                record_sensor_summary(cur, stored)
                conn.commit()
                cur.execute("SELECT COUNT(*) AS n FROM target_sensor_session_history")
                self.assertEqual(1, cur.fetchone()["n"])
                conflicting = {**stored, "sensor_session_summary": {**sensor_value(), "threshold_mm": 600}}
                with self.assertRaises(ValueError):
                    record_sensor_summary(cur, conflicting)
                conn.rollback()
                cur.execute("INSERT INTO target_health_history (target_id,source_boot_id,source_boot_count,status_revision,"
                            "gate_state,terminal_session_id,relay_commanded_on,verified_json,received_at) "
                            "SELECT target_id,source_boot_id,source_boot_count,100,gate_state,terminal_session_id,"
                            "relay_commanded_on,verified_json,UTC_TIMESTAMP(3)-INTERVAL 32 DAY FROM target_health_history LIMIT 1")
                conn.commit()
                record_verified_health(cur, {**status_value(), "status_revision": 4, "state": "COOLDOWN"})
                conn.commit()
                cur.execute("SELECT COUNT(*) AS n FROM target_health_history WHERE status_revision=100")
                self.assertEqual(0, cur.fetchone()["n"])
                # Execute the API grouping/HAVING/tuple-IN queries against the
                # actual schema, not only a mocked cursor with preselected rows.
                for seq, code, outcome, reason, monotonic in (
                    (7, "ACCESS_ARMED", "SUCCEEDED", "ARM_ACCEPTED", 1000),
                    (8, "ACCESS_SESSION_TERMINATED", "TIMED_OUT", "ARM_TIMEOUT", 61013)):
                    cur.execute("INSERT INTO access_event_history (event_id,session_id,source_component,"
                        "source_instance_id,source_boot_id,source_boot_count,source_sequence,event_attempt,"
                        "event_code,event_stage,event_outcome,reason_code,target_ref,event_path,event_transport,"
                        "monotonic_ms,clock_quality,collector_target_ref,collector_target_id,integrity_status) "
                        "VALUES (%s,%s,'target','target',%s,782,%s,1,%s,'COMPLETE',%s,%s,'opaque-target',"
                        "'local_gatt','ble_gatt',%s,'UNSYNCED','opaque-target',%s,'verified')",
                        (str(uuid.uuid4()), SESSION, BOOT, seq, code, outcome, reason, monotonic, TARGET))
                encoded = json.dumps(bundle(), separators=(",", ":"))
                cur.execute("INSERT INTO mobile_diagnostic_bundles (tenant_id,credential_ref,bundle_ref,"
                            "created_at_ms,payload_json,payload_sha256) VALUES (%s,%s,%s,1,%s,%s)",
                            ("a"*32, "mobile-diagnostic-credential_" + "b"*24, "c"*32,
                             encoded, hashlib.sha256(encoded.encode()).hexdigest()))
                conn.commit()
            def connection_factory():
                return pymysql.connect(host="127.0.0.1", port=port, user="root", password=password,
                    database="smart_gatekeeper", cursorclass=pymysql.cursors.DictCursor, autocommit=False)
            token = "x"*43
            app = FastAPI()
            app.include_router(create_diagnostics_read_router(connection_factory, hashlib.sha256(token.encode()).hexdigest()))
            client = TestClient(app)
            headers = {"Authorization": "Bearer " + token}
            response = client.get("/api/v1/diagnostics/incidents", headers=headers,
                                  params={"target_id": TARGET, "before_id": 100, "limit": 1})
            self.assertEqual(200, response.status_code, response.text)
            incident = response.json()["incidents"][0]
            self.assertEqual(60013, incident["source_span_ms"])
            self.assertEqual("SENSOR_REARM_BLOCK_OBSERVED", incident["sensor_boundary"])
            self.assertEqual("STALE_REPORT", response.json()["mobile_observations"][0]["freshness"])
            response = client.get("/api/v1/diagnostics/health-history", headers=headers,
                                  params={"target_id": TARGET, "boot_count": 782, "limit": 1})
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual("COOLDOWN", response.json()["history"][0]["verified"]["state"])
            self.assertIsNotNone(response.json()["next_before_id"])
            down = (ROOT / "backend/db/migrations/016_reliability_history_down.sql").read_text()
            docker("exec", "-i", name, "mariadb", "-uroot", "-p" + password, input_text=down)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM target_sensor_session_history")
                self.assertEqual(1, cur.fetchone()["n"])
        finally:
            if conn is not None:
                conn.close()
            docker("rm", "-f", name, check=False)
