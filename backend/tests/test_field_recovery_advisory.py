import copy
import hashlib
import hmac
import json
from datetime import datetime
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.diagnostics_read import create_diagnostics_read_router
from backend.app.reliability_diagnostics import CORE_FIELDS, advisory_projection
from backend.tests.test_mobile_diagnostics import bundle
from backend.tests.test_reliability_diagnostics import KEY, TARGET, BOOT, status_value


def observations():
    return dict(
        passage_rearm=dict(auth_ready=True, pulse_ready=False, auth_reason="READY",
            pulse_reason="SENSOR_CLEARANCE_UNCONFIRMED", blocked=True, blocked_since_ms=1000,
            blocked_age_ms=3000, pulse_source="REMOTE_MANUAL", last_pulse_ms=1000, clear_samples=0, retry_after_ms=0),
        sensor_observation=dict(kind="NO_ECHO", phase="IDLE", valid=False,
            sampled_ms=4000, sample_age_ms=0, echo_us=0, raw_mm=None,
            last_valid_mm=440, last_valid_age_ms=3100, idle_samples=5, armed_samples=2,
            cooldown_samples=1, no_echo=5, out_of_range=1, valid_samples=2, invalid_streak=4,
            qualification=dict(active=False, started_ms=100, ended_ms=800, median_mm=None,
                median_age_ms=3200, samples=2, valid_streak=0, max_valid_streak=1,
                near_streak=0, max_near_streak=1, median_rejects=1, candidates=1,
                rearm_rejects=1, fsm_rejects=0, triggers=0)),
        ble_presence=dict(requested_ready=True, requested_epoch=5, applied_ready=False,
            applied_epoch=4, applied_valid=False, pending=True, status="RETRY_WAIT", last_result="APPLY_FAILED",
            attempts=2, failures=1, retries=1, stops=0, last_attempt_ms=4000,
            applied_age_ms=None, gap_count=1, gap_ms=20, last_gap_ms=10, restart_reason="PRESENCE_APPLY"),
    )


class FieldRecoveryAdvisoryTest(unittest.TestCase):
    def test_exact_nested_shapes_round_trip_without_auth_or_pulse_conflation(self):
        value = observations()
        self.assertEqual(value, advisory_projection(value))
        noisy = copy.deepcopy(value)
        for group in noisy.values():
            group["private_key"] = "must-not-escape"
        noisy["sensor_observation"]["qualification"]["raw_payload"] = "must-not-escape"
        projected = advisory_projection(noisy)
        self.assertEqual(value, projected)
        self.assertTrue(projected["passage_rearm"]["auth_ready"])
        self.assertFalse(projected["passage_rearm"]["pulse_ready"])
        self.assertIsNone(projected["sensor_observation"]["raw_mm"])
        self.assertEqual("NO_ECHO", projected["sensor_observation"]["kind"])

    def test_strict_uint32_nullable_ages_and_closed_codes(self):
        for group, key, invalid in (("passage_rearm", "auth_ready", 1), ("passage_rearm", "auth_reason", "SECRET"),
                                   ("passage_rearm", "blocked_age_ms", -1), ("sensor_observation", "idle_samples", 2**32),
                                   ("sensor_observation", "raw_mm", 65535), ("sensor_observation", "kind", "BROKEN_HARDWARE"),
                                   ("ble_presence", "applied_age_ms", True), ("ble_presence", "restart_reason", "https://secret")):
            value = observations()
            value[group][key] = invalid
            with self.subTest(group=group, key=key):
                self.assertNotIn(group, advisory_projection(value))
        value = observations()
        value["sensor_observation"]["qualification"]["fsm_rejects"] = "1"
        self.assertNotIn("sensor_observation", advisory_projection(value))
        value = observations()
        value["passage_rearm"].update(blocked=False, blocked_since_ms=None, last_pulse_ms=None)
        value["ble_presence"].update(last_attempt_ms=None, applied_age_ms=None)
        self.assertEqual(value, advisory_projection(value))

    def test_actual_signed_parser_keeps_advisory_outside_mac_and_classification(self):
        doc = dict(target_id=TARGET, boot_id=BOOT, boot_count=901, access_status_revision=1, state="IDLE",
            last_terminal_session_id=None, last_terminal_event_sequence=None, last_terminal_event_code=None,
            last_terminal_reason_code=None, last_terminal_credential_ref=None, last_terminal_phase_mask=0,
            relay_commanded_on=False, relay_pin_level=1)
        wire = main.build_access_status_mac_input(key_id="a1", topic_target_id=TARGET, door_id="a" * 32,
            source_boot_id=BOOT, source_boot_count=901, access_revision=1, state="IDLE",
            last_terminal_session_id=None, last_terminal_event_sequence=None, last_terminal_event_code=None,
            last_terminal_credential_ref=None, last_terminal_reason_code=None, last_terminal_phase_mask=0,
            relay_commanded_on=False, relay_pin_level=1)
        doc["access_auth"] = dict(version=1, key_id="a1", tag=hmac.new(KEY, wire, hashlib.sha256).digest()[:16].hex())
        with patch.object(main, "_configured_target_door_id", return_value="a" * 32), patch.object(main, "ACCESS_EVENT_REF_KEYS", {"a1": KEY}):
            original = main._parse_authenticated_target_status(TARGET, json.dumps(doc).encode())
            doc.update(observations())
            projected = main._parse_authenticated_target_status(TARGET, json.dumps(doc).encode())
            self.assertIsNotNone(projected)
            self.assertEqual(observations(), projected["advisory_diagnostics"])
            self.assertEqual({key: original[key] for key in CORE_FIELDS}, {key: projected[key] for key in CORE_FIELDS})
            doc["passage_rearm"]["auth_ready"] = "private"
            malformed = main._parse_authenticated_target_status(TARGET, json.dumps(doc).encode())
            self.assertIsNotNone(malformed)
            self.assertNotIn("passage_rearm", malformed["advisory_diagnostics"])

    def test_health_read_and_admin_keep_unsigned_label_and_nullable_distances(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [dict(id=1, received_at=datetime(2026, 9, 13, 12),
            verified_json=json.dumps(status_value()), advisory_json=json.dumps(observations()))]
        app = FastAPI()
        app.include_router(create_diagnostics_read_router(lambda: conn, hashlib.sha256(b"x" * 43).hexdigest()))
        with TestClient(app) as client:
            response = client.get("/api/v1/diagnostics/health-history", headers={"Authorization": "Bearer " + "x" * 43})
        self.assertEqual(200, response.status_code, response.text)
        sample = response.json()["history"][0]
        self.assertEqual(observations(), sample["unsigned_advisory"])
        self.assertEqual("UNSIGNED_NOT_USED_FOR_CLASSIFICATION", sample["advisory_integrity"])
        self.assertNotIn("passage_rearm", sample["verified"])
        cur.fetchall.side_effect = [[dict(credential_ref="opaque", bundle_ref="a" * 32,
            created_at_ms=100, payload_json=bundle(), received_at=datetime(2026, 9, 13, 12))], []]
        with patch.object(main, "get_db", return_value=conn), patch.object(main, "_admin_principal"), \
             patch.object(main._target_gate_states, "live_evidence", return_value={"advisory_diagnostics": observations()}):
            attempt = main.get_diagnostic_attempts_admin(MagicMock(), limit=20)["attempts"][0]
        self.assertEqual(observations(), attempt["target_unsigned_advisory"])
        self.assertEqual("UNSIGNED_NOT_USED_FOR_CLASSIFICATION", attempt["target_advisory_integrity"])
