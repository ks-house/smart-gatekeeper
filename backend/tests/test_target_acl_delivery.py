from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app import main
from backend.app.target_acl_delivery import (
    TargetAclDeliveryTracker,
    build_target_acl_wire_payload,
    parse_target_acl_ack,
    target_acl_ack_topic,
)


TARGET = "target-a"
TENANT = "1" * 32
ROOT = Path(__file__).resolve().parents[2]
ACL_VECTOR = json.loads(
    (ROOT / "protocol" / "test_vectors" / "v1.json").read_text(encoding="utf-8")
)["acl"]
DOOR = ACL_VECTOR["fields"]["door_id"]


def target_vector_envelope() -> dict:
    expected = ACL_VECTOR["expected"]
    return {
        "fields": ACL_VECTOR["fields"],
        "canonical_hex": expected["canonical_hex"],
        "sha256": expected["sha256"],
        "signature_raw64": expected["signature_raw64"],
    }


class TargetAclDeliveryTest(unittest.TestCase):
    def test_ack_parser_accepts_only_exact_nonretained_applied_schema(self) -> None:
        payload = json.dumps(
            {"status": "applied", "acl_version": 7, "high_watermark": 7}
        ).encode()
        ack = parse_target_acl_ack(target_acl_ack_topic(TARGET), payload)
        self.assertEqual(TARGET, ack.target_id)
        self.assertEqual(7, ack.acl_version)
        self.assertIsNone(
            parse_target_acl_ack(
                target_acl_ack_topic(TARGET), payload, retained=True
            )
        )
        for invalid in (
            {"status": "rejected", "acl_version": 7, "high_watermark": 7},
            {"status": "applied", "acl_version": True, "high_watermark": 7},
            {"status": "applied", "acl_version": 7, "high_watermark": 6},
            {"status": "applied", "acl_version": 7, "high_watermark": 8},
            {
                "status": "applied",
                "acl_version": 7,
                "high_watermark": 7,
                "extra": "field",
            },
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(
                    parse_target_acl_ack(
                        target_acl_ack_topic(TARGET), json.dumps(invalid).encode()
                    )
                )

    def test_production_acl_publish_requires_exact_target_apply_ack(self) -> None:
        credentials = {
            TARGET: {"tenant_id": TENANT, "door_id": DOOR, "key": "unused"}
        }
        envelope = target_vector_envelope()
        calls = []

        def publish(topic: str, payload: bytes, label: str) -> bool:
            calls.append((topic, payload, label))
            return True

        missing = TargetAclDeliveryTracker()
        self.assertFalse(
            main._publish_acl_to_targets(
                f"gatekeeper/acl/v1/{TENANT}/{DOOR}",
                envelope,
                credentials,
                publish_message=publish,
                delivery_tracker=missing,
                ack_timeout_seconds=0.01,
            )
        )
        self.assertEqual(
            f"gatekeeper/v1/targets/{TARGET}/acl", calls[0][0]
        )

        applied = TargetAclDeliveryTracker()

        def publish_and_apply(topic: str, payload: bytes, label: str) -> bool:
            calls.append((topic, payload, label))
            applied.mark_applied(TARGET, 42)
            return True

        self.assertTrue(
            main._publish_acl_to_targets(
                f"gatekeeper/acl/v1/{TENANT}/{DOOR}",
                envelope,
                credentials,
                publish_message=publish_and_apply,
                delivery_tracker=applied,
                ack_timeout_seconds=0.01,
            )
        )

    def test_broker_publish_failure_never_becomes_delivery_success(self) -> None:
        tracker = TargetAclDeliveryTracker()
        tracker.mark_applied(TARGET, 42)
        self.assertFalse(
            main._publish_acl_to_targets(
                f"gatekeeper/acl/v1/{TENANT}/{DOOR}",
                target_vector_envelope(),
                {
                    TARGET: {
                        "tenant_id": TENANT,
                        "door_id": DOOR,
                        "key": "unused",
                    }
                },
                publish_message=lambda *_args: False,
                delivery_tracker=tracker,
                ack_timeout_seconds=0.01,
            )
        )

    def test_wire_payload_matches_shared_target_parser_vector(self) -> None:
        envelope = target_vector_envelope()
        payload = build_target_acl_wire_payload(envelope)
        expected = ACL_VECTOR["expected"]
        self.assertEqual(
            bytes.fromhex(expected["canonical_hex"] + expected["signature_raw64"]),
            payload,
        )
        self.assertEqual(b"SGKACL01", payload[:8])
        self.assertEqual(72 + 106 + 64, len(payload))
        # The firmware host test applies this shared 242-byte vector through the
        # production TargetAclManager parser and signature verifier.
        target_test = (ROOT / "tests" / "gatt_protocol_test.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("acl_manager.applySignedAcl(acl_payload.data()", target_test)

    def test_tracker_rejects_prepublication_and_cross_transport_observations(self) -> None:
        tracker = TargetAclDeliveryTracker()
        tracker.mark_applied(TARGET, 42)
        self.assertTrue(tracker.begin_delivery([TARGET], 42))
        self.assertFalse(tracker.wait_for([TARGET], 42, timeout_seconds=0.01))
        tracker.mark_applied(TARGET, 42)
        tracker.reset_transport()
        self.assertFalse(tracker.wait_for([TARGET], 42, timeout_seconds=0.01))


if __name__ == "__main__":
    unittest.main()
