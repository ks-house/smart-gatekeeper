from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from observability.event_parser import (
    EventValidationError,
    evaluate_access_session,
    evaluate_update_session,
    load_jsonl,
    order_events,
    validate_event,
    validate_stream,
)


BASE_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = BASE_DIR / "fixtures"


class EventParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.access = load_jsonl(FIXTURE_DIR / "access_success_v1.jsonl")
        cls.manual_access = load_jsonl(
            FIXTURE_DIR / "manual_remote_access_success_v1.jsonl"
        )
        cls.ota = load_jsonl(FIXTURE_DIR / "target_ota_success_v1.jsonl")
        cls.rollback = load_jsonl(
            FIXTURE_DIR / "target_ota_rollback_success_v1.jsonl"
        )
        cls.digest_mismatch = load_jsonl(
            FIXTURE_DIR / "negative_update_digest_mismatch_v1.jsonl"
        )
        cls.rollback_missing_evidence = load_jsonl(
            FIXTURE_DIR / "negative_rollback_missing_evidence_v1.jsonl"
        )
        cls.reset_wrong_prior_boot = load_jsonl(
            FIXTURE_DIR / "negative_access_reset_wrong_prior_boot_v1.jsonl"
        )
        cls.sequence_overflow = load_jsonl(
            FIXTURE_DIR / "negative_sequence_overflow_v1.jsonl"
        )
        cls.causation_cycle = load_jsonl(
            FIXTURE_DIR / "negative_causation_cycle_v1.jsonl"
        )

    def test_contract_artifacts_are_valid_json(self) -> None:
        for filename in ("event_schema_v1.json", "event_codes_v1.json"):
            with (BASE_DIR / filename).open("r", encoding="utf-8") as stream:
                self.assertIsInstance(json.load(stream), dict)

    def test_successful_access_fixture_passes_i7_contract(self) -> None:
        result = evaluate_access_session(self.access)
        self.assertTrue(result["passed"])
        self.assertEqual(result["terminal_reason_code"], "ACCESS_GRANTED")

    def test_authenticated_manual_button_path_is_distinct_from_hands_free(self) -> None:
        result = evaluate_access_session(self.manual_access)
        self.assertTrue(result["passed"])
        self.assertEqual(result["terminal_reason_code"], "ACCESS_GRANTED")

        codes = {event["event_code"] for event in self.manual_access}
        self.assertIn("ACCESS_MANUAL_OPEN_REQUESTED", codes)
        self.assertIn("ACCESS_MANUAL_OPEN_AUTHORIZED", codes)
        self.assertIn("ACCESS_MANUAL_OPEN_RECEIVED", codes)
        self.assertNotIn("ACCESS_WAKE_DETECTED", codes)
        self.assertNotIn("ACCESS_SENSOR_DETECTED", codes)

        blurred = copy.deepcopy(self.manual_access)
        inserted = copy.deepcopy(self.access[8])
        inserted["event_id"] = "e1000008-0000-4000-8000-000000000008"
        inserted["session_id"] = blurred[0]["session_id"]
        inserted["sequence"] = 901
        inserted["clock"]["monotonic_ms"] = 9001
        inserted["causation_event_id"] = blurred[3]["event_id"]
        for event in blurred[4:]:
            event["sequence"] += 1
        blurred[4]["causation_event_id"] = inserted["event_id"]
        with self.assertRaisesRegex(EventValidationError, "distinct from hands-free"):
            evaluate_access_session(blurred[:4] + [inserted] + blurred[4:])

    def test_offline_arrival_is_reordered_by_causation_and_sequence(self) -> None:
        ordered = order_events(reversed(self.access))
        self.assertEqual(ordered[0]["event_code"], "ACCESS_SESSION_STARTED")
        self.assertEqual(ordered[-1]["event_code"], "ACCESS_SESSION_COMPLETED")
        self.assertEqual(
            [event["sequence"] for event in ordered if event["source_component"] == "target"],
            list(range(501, 510)),
        )

    def test_exact_replay_is_idempotently_deduplicated(self) -> None:
        replayed = self.access + [copy.deepcopy(self.access[3])]
        self.assertEqual(len(validate_stream(replayed)), len(self.access))

    def test_sequence_conflict_is_rejected(self) -> None:
        conflict = copy.deepcopy(self.access[4])
        conflict["event_id"] = "c0000001-0000-4000-8000-000000000001"
        conflict["sequence"] = self.access[3]["sequence"]
        with self.assertRaisesRegex(EventValidationError, "sequence conflict"):
            validate_stream(self.access + [conflict])

    def test_unknown_or_mismatched_code_is_rejected(self) -> None:
        unknown = copy.deepcopy(self.access[0])
        unknown["event_code"] = "ACCESS_FREE_TEXT_FAILURE"
        with self.assertRaisesRegex(EventValidationError, "not registered"):
            validate_event(unknown)

        mismatch = copy.deepcopy(self.access[0])
        mismatch["reason_code"] = "INTERNAL_ERROR"
        with self.assertRaisesRegex(EventValidationError, "not allowed"):
            validate_event(mismatch)

    def test_privacy_policy_rejects_raw_proof_and_mac(self) -> None:
        private_event = copy.deepcopy(self.access[0])
        private_event["attributes"]["proof"] = "raw-proof-material"
        with self.assertRaisesRegex(EventValidationError, "forbidden sensitive field"):
            validate_event(private_event)

        mac_event = copy.deepcopy(self.access[0])
        mac_event["attributes"]["credential_ref"] = "AA:BB:CC:DD:EE:FF"
        with self.assertRaisesRegex(EventValidationError, "raw MAC address"):
            validate_event(mac_event)

    def test_target_ota_requires_new_boot_and_health_confirmation(self) -> None:
        result = evaluate_update_session(self.ota)
        self.assertTrue(result["passed"])
        self.assertEqual(result["terminal_reason_code"], "UPDATE_HEALTH_CONFIRMED")

        incomplete = [
            copy.deepcopy(event)
            for event in self.ota
            if event["event_code"] not in {"UPDATE_HEALTH_CONFIRMED", "UPDATE_MARKED_VALID"}
        ]
        incomplete[-1]["causation_event_id"] = "b000000a-0000-4000-8000-00000000000a"
        with self.assertRaisesRegex(EventValidationError, "completed update is missing"):
            evaluate_update_session(incomplete)

    def test_completed_update_requires_artifact_digest(self) -> None:
        missing_digest = copy.deepcopy(self.ota[-1])
        missing_digest["update"]["artifact_sha256"] = None
        with self.assertRaisesRegex(EventValidationError, "requires update.artifact_sha256"):
            validate_event(missing_digest)

    def test_update_session_artifact_digest_is_immutable(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "changes artifact_sha256"):
            validate_stream(self.digest_mismatch)

        dropped_failure_digest = copy.deepcopy(self.ota)
        dropped_failure_digest[-1]["event_code"] = "UPDATE_SESSION_FAILED"
        dropped_failure_digest[-1]["outcome"] = "FAILED"
        dropped_failure_digest[-1]["reason_code"] = "ARTIFACT_HASH_MISMATCH"
        dropped_failure_digest[-1]["update"]["artifact_sha256"] = None
        with self.assertRaisesRegex(EventValidationError, "drops artifact_sha256"):
            validate_stream(dropped_failure_digest)

    def test_rollback_requires_previous_install_boot_and_health_evidence(self) -> None:
        result = evaluate_update_session(self.rollback)
        self.assertTrue(result["passed"])
        self.assertEqual(result["terminal_reason_code"], "ROLLBACK_COMPLETED")

        with self.assertRaisesRegex(EventValidationError, "missing ordered stages"):
            evaluate_update_session(self.rollback_missing_evidence)

    def test_proof_rejection_can_never_open_relay(self) -> None:
        rejected = copy.deepcopy(self.access)
        rejected[5]["event_code"] = "ACCESS_PROOF_REJECTED"
        rejected[5]["outcome"] = "DENIED"
        rejected[5]["reason_code"] = "SIGNATURE_INVALID"
        with self.assertRaisesRegex(EventValidationError, "must never activate relay"):
            evaluate_access_session(rejected)

    def test_target_boot_change_needs_reset_terminal_reason(self) -> None:
        reset_stream = copy.deepcopy(self.access)
        reset_stream[-1]["source_boot_id"] = "9a34bc56de78fa90"
        reset_stream[-1]["target"]["boot_id"] = "9a34bc56de78fa90"
        reset_stream[-1]["sequence"] = 0
        reset_stream[-1]["clock"]["monotonic_ms"] = 10
        with self.assertRaisesRegex(EventValidationError, "RESET_DURING_SESSION"):
            evaluate_access_session(reset_stream)

    def test_reset_requires_actual_prior_boot_and_new_target_emitter(self) -> None:
        with self.assertRaisesRegex(
            EventValidationError, "prior_target_boot_id does not match"
        ):
            evaluate_access_session(self.reset_wrong_prior_boot)

        valid_reset = copy.deepcopy(self.reset_wrong_prior_boot)
        valid_reset[-1]["attributes"]["prior_target_boot_id"] = valid_reset[-2][
            "source_boot_id"
        ]
        result = evaluate_access_session(valid_reset)
        self.assertTrue(result["passed"])
        self.assertEqual(result["terminal_reason_code"], "RESET_DURING_SESSION")

        stale_cause = copy.deepcopy(valid_reset)
        stale_cause[-1]["causation_event_id"] = stale_cause[0]["event_id"]
        with self.assertRaisesRegex(EventValidationError, "last prior target event"):
            evaluate_access_session(stale_cause)

        wrong_emitter = copy.deepcopy(valid_reset)
        wrong_emitter[-1]["source_component"] = "android"
        with self.assertRaisesRegex(EventValidationError, "emitted by the new target boot"):
            evaluate_access_session(wrong_emitter)

    def test_sequence_and_monotonic_clock_are_uint64(self) -> None:
        boundary = copy.deepcopy(self.access[0])
        boundary["sequence"] = (1 << 64) - 1
        boundary["clock"]["monotonic_ms"] = (1 << 64) - 1
        validate_event(boundary)

        with self.assertRaisesRegex(
            EventValidationError, "sequence must be an integer between"
        ):
            validate_event(self.sequence_overflow[0])

        monotonic_overflow = copy.deepcopy(boundary)
        monotonic_overflow["clock"]["monotonic_ms"] = 1 << 64
        with self.assertRaisesRegex(
            EventValidationError, "monotonic_ms must be an integer between"
        ):
            validate_event(monotonic_overflow)

    def test_validate_stream_rejects_causation_cycle(self) -> None:
        with self.assertRaisesRegex(EventValidationError, "contains a cycle"):
            validate_stream(self.causation_cycle)

    def test_every_session_has_exactly_one_terminal_event(self) -> None:
        missing_terminal = self.access[:-1]
        with self.assertRaisesRegex(EventValidationError, "exactly one terminal"):
            validate_stream(missing_terminal)


if __name__ == "__main__":
    unittest.main()
