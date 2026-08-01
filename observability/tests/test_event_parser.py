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
        cls.ota = load_jsonl(FIXTURE_DIR / "target_ota_success_v1.jsonl")

    def test_contract_artifacts_are_valid_json(self) -> None:
        for filename in ("event_schema_v1.json", "event_codes_v1.json"):
            with (BASE_DIR / filename).open("r", encoding="utf-8") as stream:
                self.assertIsInstance(json.load(stream), dict)

    def test_successful_access_fixture_passes_i7_contract(self) -> None:
        result = evaluate_access_session(self.access)
        self.assertTrue(result["passed"])
        self.assertEqual(result["terminal_reason_code"], "ACCESS_GRANTED")

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

    def test_every_session_has_exactly_one_terminal_event(self) -> None:
        missing_terminal = self.access[:-1]
        with self.assertRaisesRegex(EventValidationError, "exactly one terminal"):
            validate_stream(missing_terminal)


if __name__ == "__main__":
    unittest.main()
