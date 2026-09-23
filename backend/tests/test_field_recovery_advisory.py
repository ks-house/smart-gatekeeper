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
from backend.app.reliability_diagnostics import CORE_FIELDS, advisory_projection, interpret_sensor_observation, record_verified_health
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
        ble_advertisement=dict(schema=1, primary_applied=True, response_applied=False,
            payload_generation=2, applied_generation=1, refresh_count=1, last_apply_age_ms=5000,
            primary_apply_failures=0, response_apply_failures=1, primary_length=30,
            response_length=29, refresh_interval_ms=30000, last_error="RESPONSE_APPLY_FAILED"),
    )


class FieldRecoveryAdvisoryTest(unittest.TestCase):
    def test_rearm_history_is_bounded_optional_and_survives_projection(self):
        value = observations()
        history = dict(schema=1, sequence=5, overwritten=1, last_clear_ms=0,
                       edges=["4294967295,2,2,1", "0,3,5,3", "1,1,1,0", "8,2,4,2"])
        value["passage_rearm"]["history"] = history
        self.assertEqual(value, advisory_projection(value))
        self.assertEqual(value, advisory_projection(advisory_projection(value)))
        self.assertEqual(value, advisory_projection(json.loads(json.dumps(value))))
        for change in (dict(schema=True), dict(schema=2), dict(sequence=True),
                       dict(sequence=2**32), dict(overwritten=0), dict(last_clear_ms=-1),
                       dict(last_clear_ms=True), dict(edges=history["edges"] * 2),
                       dict(edges=["0,1,1,0"] * 3), dict(edges=["0,3,2,3"] * 4),
                       dict(edges=["0,2,2,0"] * 4), dict(edges=["secret"] * 4),
                       dict(edges=["4294967296,1,1,0"] * 4), dict(edges=["00,1,1,0"] * 4),
                       dict(edges=["9" * 1000] * 4)):
            value["passage_rearm"]["history"] = dict(history, **change)
            with self.subTest(change=change):
                self.assertEqual(observations(), advisory_projection(value))
        value["passage_rearm"]["history"] = dict(schema=1, sequence=0, overwritten=0, last_clear_ms=None, edges=[])
        self.assertEqual(value, advisory_projection(value))

    def test_approach_wait_is_not_sensor_latency(self):
        value = observations()
        timing = dict(timing_schema=1, first_valid_after_ms=100,
                      first_near_after_ms=12000, near_streak_started_after_ms=12300,
                      first_candidate_after_ms=12500, trigger_after_ms=12500)
        value["sensor_observation"]["qualification"].update(timing, triggers=1)
        projected = advisory_projection(value)
        self.assertEqual(value, projected)
        meaning = interpret_sensor_observation(projected)
        self.assertEqual(12000, meaning["arm_to_first_near_ms"])
        self.assertEqual(500, meaning["first_near_to_trigger_ms"])
        self.assertEqual(200, meaning["triggering_streak_to_trigger_ms"])
        self.assertEqual("TRIGGER_OBSERVED", meaning["arm_window"])
        self.assertEqual("UNDETERMINED", meaning["hardware_fault"])
        self.assertEqual("NOT_OBSERVED", meaning["physical_arrival"])

    def test_legacy_and_invalid_timing_do_not_invent_latency_or_erase_evidence(self):
        value = observations()
        q = value["sensor_observation"]["qualification"]
        legacy = copy.deepcopy(q)
        timing = dict(timing_schema=1, first_valid_after_ms=0, first_near_after_ms=10,
                      near_streak_started_after_ms=10, first_candidate_after_ms=20, trigger_after_ms=30)
        for key, invalid in (("timing_schema", True), ("timing_schema", 2),
                             ("first_valid_after_ms", True), ("first_near_after_ms", -1),
                             ("trigger_after_ms", 2**32), ("trigger_after_ms", 5)):
            q.clear()
            q.update(legacy, **timing)
            q[key] = invalid
            projected = advisory_projection(value)
            self.assertEqual(legacy, projected["sensor_observation"]["qualification"])
            self.assertFalse(interpret_sensor_observation(projected)["timing_available"])
        q.clear()
        q.update(legacy, timing_schema=1, **{key: None for key in timing if key != "timing_schema"})
        meaning = interpret_sensor_observation(advisory_projection(value))
        self.assertIsNone(meaning["first_near_to_trigger_ms"])
        self.assertEqual("ENDED_WITHOUT_TRIGGER", meaning["arm_window"])
        self.assertEqual("UNDETERMINED", meaning["hardware_fault"])

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
                                   ("ble_presence", "applied_age_ms", True), ("ble_presence", "restart_reason", "https://secret"),
                                   ("ble_advertisement", "schema", True), ("ble_advertisement", "schema", 2),
                                   ("ble_advertisement", "primary_length", 32), ("ble_advertisement", "last_error", "secret"),
                                   ("ble_advertisement", "refresh_count", 2**32), ("ble_advertisement", "response_applied", 1)):
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

    def test_checked_refresh_and_inactive_controller_codes_survive_projection(self):
        value = observations()
        value["ble_presence"].update(status="INACTIVE_AFTER_START",
                                     last_result="INACTIVE_AFTER_START", restart_reason="CHECKED_REFRESH")
        value["ble_advertisement"]["last_error"] = "INACTIVE_AFTER_START"
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
        value = observations()
        value["passage_rearm"]["history"] = dict(schema=1, sequence=1, overwritten=0,
                                               last_clear_ms=None, edges=["1000,1,1,0"])
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.rowcount = 0
        record_verified_health(cur, dict(status_value(), advisory_diagnostics=value))
        self.assertEqual(value, json.loads(cur.execute.call_args.args[1][8]))
        self.assertNotIn("passage_rearm", json.loads(cur.execute.call_args.args[1][7]))
        cur.fetchall.return_value = [dict(id=1, received_at=datetime(2026, 9, 13, 12),
            verified_json=json.dumps(status_value()), advisory_json=json.dumps(value))]
        app = FastAPI()
        app.include_router(create_diagnostics_read_router(lambda: conn, hashlib.sha256(b"x" * 43).hexdigest()))
        with TestClient(app) as client:
            response = client.get("/api/v1/diagnostics/health-history", headers={"Authorization": "Bearer " + "x" * 43})
        self.assertEqual(200, response.status_code, response.text)
        sample = response.json()["history"][0]
        self.assertEqual(value, sample["unsigned_advisory"])
        self.assertEqual("UNSIGNED_NOT_USED_FOR_CLASSIFICATION", sample["advisory_integrity"])
        self.assertNotIn("passage_rearm", sample["verified"])
        self.assertEqual("UNDETERMINED", sample["observation_interpretation"]["hardware_fault"])
        self.assertIsNone(sample["observation_interpretation"]["first_near_to_trigger_ms"])
        cur.fetchall.side_effect = [[dict(credential_ref="opaque", bundle_ref="a" * 32,
            created_at_ms=100, payload_json=bundle(), received_at=datetime(2026, 9, 13, 12))], []]
        with patch.object(main, "get_db", return_value=conn), patch.object(main, "_admin_principal"), \
             patch.object(main._target_gate_states, "live_evidence", return_value={"advisory_diagnostics": value}):
            attempt = main.get_diagnostic_attempts_admin(MagicMock(), limit=20)["attempts"][0]
        self.assertEqual(value, attempt["target_unsigned_advisory"])
        self.assertEqual("UNSIGNED_NOT_USED_FOR_CLASSIFICATION", attempt["target_advisory_integrity"])
