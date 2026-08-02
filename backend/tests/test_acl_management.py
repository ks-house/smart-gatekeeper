from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from backend.app.acl_management import (
    AclManagementService,
    AclStore,
    DeterministicP256Signer,
    RecordingPublisher,
    acl_snapshot_is_usable,
    build_enrollment_input,
    initialize_sqlite_test_schema,
    verify_snapshot_envelope,
)


ROOT = Path(__file__).resolve().parents[2]
VECTOR = json.loads((ROOT / "protocol" / "test_vectors" / "v1.json").read_text(encoding="utf-8"))
TENANT_A = "11111111111111111111111111111111"
TENANT_B = "22222222222222222222222222222222"
DOOR_A = VECTOR["acl"]["fields"]["door_id"]
TARGET_A = "target-a"
NOW = 1_785_542_400


class MutableClock:
    def __init__(self, value: int = NOW):
        self.value = value

    def __call__(self) -> int:
        return self.value


class AclManagementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        initialize_sqlite_test_schema(self.conn)
        self.clock = MutableClock()
        self.publisher = RecordingPublisher()
        self.signer = DeterministicP256Signer(2, signing_key_id=7)
        self.store = AclStore(lambda: self.conn, dialect="sqlite", close_connections=False)
        self.service = AclManagementService(
            self.store,
            self.signer,
            self.publisher,
            clock=self.clock,
            lease_seconds=900,
            legacy_hmac_key=b"explicit-test-only-key",
        )
        self.store.create_tenant(TENANT_A, "A")
        self.store.create_tenant(TENANT_B, "B")

    def tearDown(self) -> None:
        self.conn.close()

    def enroll(
        self,
        tenant_id: str = TENANT_A,
        private_scalar: int = 1,
        max_protocol: int = 1,
    ) -> str:
        device_signer = DeterministicP256Signer(private_scalar, signing_key_id=0)
        challenge = self.service.issue_enrollment_challenge(tenant_id, actor_ref="user:a")
        enrollment_input = build_enrollment_input(
            tenant_id,
            challenge["enrollment_id"],
            challenge["nonce"],
            device_signer.public_key_sec1.hex(),
        )
        signature = device_signer.sign(enrollment_input).hex()
        result = self.service.submit_enrollment(
            tenant_id=tenant_id,
            enrollment_id=challenge["enrollment_id"],
            nonce_hex=challenge["nonce"],
            public_key_hex=device_signer.public_key_sec1.hex(),
            signature_hex=signature,
            actor_ref="user:a",
            legacy_device_id="DEV-DO-NOT-STORE-RAW",
            expires_at=NOW + 3600,
            max_protocol=max_protocol,
        )
        return result["credential_id"]

    def test_enrollment_is_proof_of_possession_single_use_and_tenant_scoped(self) -> None:
        credential_id = self.enroll()
        row = self.store.get_credential(TENANT_A, credential_id)
        self.assertEqual("PENDING", row["status"])
        self.assertIsNone(self.store.get_credential(TENANT_B, credential_id))

        challenge = self.service.issue_enrollment_challenge(TENANT_A, actor_ref="user:a")
        signer = DeterministicP256Signer(3, signing_key_id=0)
        payload = build_enrollment_input(
            TENANT_A, challenge["enrollment_id"], challenge["nonce"], signer.public_key_sec1.hex()
        )
        signature = signer.sign(payload).hex()
        self.service.submit_enrollment(
            TENANT_A,
            challenge["enrollment_id"],
            challenge["nonce"],
            signer.public_key_sec1.hex(),
            signature,
            actor_ref="user:a",
        )
        with self.assertRaisesRegex(ValueError, "used"):
            self.service.submit_enrollment(
                TENANT_A,
                challenge["enrollment_id"],
                challenge["nonce"],
                signer.public_key_sec1.hex(),
                signature,
                actor_ref="user:a",
            )
        with self.assertRaisesRegex(PermissionError, "tenant"):
            self.service.issue_enrollment_challenge(TENANT_A, actor_ref="user:b", actor_tenant_id=TENANT_B)

    def test_enrollment_rejects_invalid_signature(self) -> None:
        challenge = self.service.issue_enrollment_challenge(TENANT_A, actor_ref="user:a")
        signer = DeterministicP256Signer(1, signing_key_id=0)
        with self.assertRaisesRegex(ValueError, "signature"):
            self.service.submit_enrollment(
                TENANT_A,
                challenge["enrollment_id"],
                challenge["nonce"],
                signer.public_key_sec1.hex(),
                "00" * 64,
                actor_ref="user:a",
            )

    def test_enrollment_insert_failure_does_not_consume_challenge(self) -> None:
        self.enroll(private_scalar=1)
        signer = DeterministicP256Signer(1, signing_key_id=0)
        challenge = self.service.issue_enrollment_challenge(TENANT_A, actor_ref="user:a")
        payload = build_enrollment_input(
            TENANT_A,
            challenge["enrollment_id"],
            challenge["nonce"],
            signer.public_key_sec1.hex(),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.submit_enrollment(
                TENANT_A,
                challenge["enrollment_id"],
                challenge["nonce"],
                signer.public_key_sec1.hex(),
                signer.sign(payload).hex(),
                actor_ref="user:a",
            )
        persisted = self.store.get_challenge(TENANT_A, challenge["enrollment_id"])
        self.assertIsNone(persisted["used_at"])

    def test_approval_disable_revoke_lifecycle_is_audited_and_isolated(self) -> None:
        credential_id = self.enroll()
        with self.assertRaisesRegex(LookupError, "credential"):
            self.service.approve_credential(TENANT_B, credential_id, actor_ref="admin:b")
        self.service.approve_credential(TENANT_A, credential_id, actor_ref="admin:a")
        self.assertEqual("ACTIVE", self.store.get_credential(TENANT_A, credential_id)["status"])
        self.service.disable_credential(TENANT_A, credential_id, actor_ref="admin:a")
        self.assertEqual("DISABLED", self.store.get_credential(TENANT_A, credential_id)["status"])
        self.service.revoke_credential(TENANT_A, credential_id, actor_ref="admin:a")
        self.assertEqual("REVOKED", self.store.get_credential(TENANT_A, credential_id)["status"])
        actions = [row["action"] for row in self.store.list_audit(TENANT_A)]
        self.assertEqual(
            ["ENROLLMENT_CHALLENGE_ISSUED", "CREDENTIAL_ENROLLED", "CREDENTIAL_APPROVED", "CREDENTIAL_DISABLED", "CREDENTIAL_REVOKED"],
            actions,
        )

    def test_snapshot_is_deterministically_sorted_monotonic_and_revocation_removes_entry(self) -> None:
        second = self.enroll(private_scalar=3)
        first = self.enroll(private_scalar=1)
        self.service.approve_credential(TENANT_A, second, actor_ref="admin:a")
        self.service.approve_credential(TENANT_A, first, actor_ref="admin:a")
        self.service.grant_credential_to_door(TENANT_A, DOOR_A, second, actor_ref="admin:a")
        self.service.grant_credential_to_door(TENANT_A, DOOR_A, first, actor_ref="admin:a")
        snap1 = self.service.publish_snapshot(TENANT_A, DOOR_A, actor_ref="admin:a")
        self.assertEqual(1, snap1["fields"]["acl_version"])
        ids = [entry["credential_id"] for entry in snap1["fields"]["entries"]]
        self.assertEqual(sorted(ids), ids)
        self.assertEqual(snap1, self.publisher.messages[-1][1])

        revoke_result = self.service.revoke_credential(
            TENANT_A, first, actor_ref="admin:a"
        )
        snap2 = self.service.pull_snapshot(TENANT_A, DOOR_A)
        self.assertEqual(2, snap2["fields"]["acl_version"])
        self.assertEqual(2, revoke_result["replacement_snapshots"][0]["fields"]["acl_version"])
        self.assertNotIn(first, [entry["credential_id"] for entry in snap2["fields"]["entries"]])
        self.assertEqual(snap2, self.publisher.messages[-1][1])

    def test_revocation_keeps_periodic_pull_current_when_mqtt_push_fails(self) -> None:
        credential_id = self.enroll()
        self.service.approve_credential(TENANT_A, credential_id, actor_ref="admin:a")
        self.service.grant_credential_to_door(
            TENANT_A, DOOR_A, credential_id, actor_ref="admin:a"
        )
        self.service.publish_snapshot(TENANT_A, DOOR_A, actor_ref="admin:a")

        class FailingPublisher:
            def publish(self, topic: str, envelope: dict) -> bool:
                return False

        self.service.publisher = FailingPublisher()
        with self.assertRaisesRegex(RuntimeError, "pull is current"):
            self.service.revoke_credential(
                TENANT_A, credential_id, actor_ref="admin:a"
            )
        replacement = self.service.pull_snapshot(TENANT_A, DOOR_A)
        self.assertEqual(2, replacement["fields"]["acl_version"])
        self.assertEqual([], replacement["fields"]["entries"])
        self.assertIsNotNone(self.store.snapshot_job(TENANT_A, DOOR_A))

        recovered_publisher = RecordingPublisher()
        self.service.publisher = recovered_publisher
        retried = self.service.pull_snapshot(TENANT_A, DOOR_A)
        self.assertEqual(2, retried["fields"]["acl_version"])
        self.assertIsNone(self.store.snapshot_job(TENANT_A, DOOR_A))
        self.assertEqual(retried, recovered_publisher.messages[0][1])

    def test_revocation_job_survives_snapshot_generation_failure(self) -> None:
        credential_id = self.enroll()
        self.service.approve_credential(TENANT_A, credential_id, actor_ref="admin:a")
        self.service.grant_credential_to_door(
            TENANT_A, DOOR_A, credential_id, actor_ref="admin:a"
        )
        self.service.publish_snapshot(TENANT_A, DOOR_A, actor_ref="admin:a")
        working_signer = self.service.signer

        class FailingSigner:
            signing_key_id = working_signer.signing_key_id
            public_key_sec1 = working_signer.public_key_sec1

            def sign(self, payload: bytes) -> bytes:
                raise RuntimeError("isolated signer unavailable")

        self.service.signer = FailingSigner()
        with self.assertRaisesRegex(RuntimeError, "signer unavailable"):
            self.service.revoke_credential(
                TENANT_A, credential_id, actor_ref="admin:a"
            )
        job = self.store.snapshot_job(TENANT_A, DOOR_A)
        self.assertIsNotNone(job)
        self.assertIsNone(job["generated_version"])

        self.service.signer = working_signer
        replacement = self.service.pull_snapshot(TENANT_A, DOOR_A)
        self.assertGreaterEqual(replacement["fields"]["acl_version"], 2)
        self.assertEqual([], replacement["fields"]["entries"])
        self.assertIsNone(self.store.snapshot_job(TENANT_A, DOOR_A))

    def test_canonical_acl_matches_shared_vector(self) -> None:
        envelope = self.service.sign_explicit_snapshot(VECTOR["acl"]["fields"])
        expected = VECTOR["acl"]["expected"]
        self.assertEqual(expected["canonical_hex"], envelope["canonical_hex"])
        self.assertEqual(expected["sha256"], envelope["sha256"])
        self.assertEqual(expected["signature_raw64"], envelope["signature_raw64"])
        self.assertEqual(expected["signing_public_key_sec1"], envelope["signing_public_key_sec1"])

    def test_target_rejects_stale_downgrade_and_invalid_signature(self) -> None:
        envelope = self.service.sign_explicit_snapshot(VECTOR["acl"]["fields"])
        fields = envelope["fields"]
        verify_args = {
            "trusted_signing_keys": {7: self.signer.public_key_sec1},
            "expected_door_id": fields["door_id"],
            "target_min_protocol": 1,
            "target_max_protocol": 1,
            "trusted_now_epoch_s": fields["not_before_epoch_s"],
            "current_boot_id": "boot-a",
            "receipt_boot_id": "boot-a",
            "current_digest": "00" * 32,
        }
        self.assertEqual(
            "activate",
            verify_snapshot_envelope(
                envelope, effective_high_watermark=41, **verify_args
            ),
        )
        self.assertEqual(
            "reject_stale",
            verify_snapshot_envelope(
                envelope, effective_high_watermark=43, **verify_args
            ),
        )
        conflicting = dict(envelope)
        conflicting["signature_raw64"] = "00" * 64
        conflicting["signatures"] = []
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_snapshot_envelope(
                conflicting, effective_high_watermark=41, **verify_args
            )
        downgraded = json.loads(json.dumps(envelope))
        downgraded["fields"]["min_protocol"] = 0
        with self.assertRaises(ValueError):
            verify_snapshot_envelope(
                downgraded, effective_high_watermark=41, **verify_args
            )
        for changed, message in (
            ({"expected_door_id": "00" * 16}, "door"),
            ({"target_min_protocol": 2, "target_max_protocol": 2}, "protocol"),
            ({"trusted_now_epoch_s": fields["expires_at_epoch_s"]}, "time"),
            ({"current_boot_id": "boot-b"}, "boot"),
            (
                {
                    "trusted_signing_keys": {
                        8: DeterministicP256Signer(8, 8).public_key_sec1
                    }
                },
                "signing key",
            ),
        ):
            with self.assertRaisesRegex(ValueError, message):
                verify_snapshot_envelope(
                    envelope,
                    effective_high_watermark=41,
                    **dict(verify_args, **changed),
                )

    def test_duplicate_ack_is_idempotent_and_fleet_status_tracks_latest(self) -> None:
        credential_id = self.enroll()
        self.service.approve_credential(TENANT_A, credential_id, actor_ref="admin:a")
        self.service.grant_credential_to_door(
            TENANT_A, DOOR_A, credential_id, actor_ref="admin:a"
        )
        snapshot = self.service.publish_snapshot(TENANT_A, DOOR_A, actor_ref="admin:a")
        ack1 = self.service.ack_snapshot(
            TENANT_A, TARGET_A, DOOR_A, snapshot["fields"]["acl_version"], snapshot["sha256"], "APPLIED"
        )
        ack2 = self.service.ack_snapshot(
            TENANT_A, TARGET_A, DOOR_A, snapshot["fields"]["acl_version"], snapshot["sha256"], "APPLIED"
        )
        self.assertEqual(ack1["ack_id"], ack2["ack_id"])
        self.assertTrue(ack2["duplicate"])
        with self.assertRaisesRegex(ValueError, "conflicting ACK status"):
            self.service.ack_snapshot(
                TENANT_A,
                TARGET_A,
                DOOR_A,
                snapshot["fields"]["acl_version"],
                snapshot["sha256"],
                "REJECTED",
            )
        status = self.service.fleet_status(TENANT_A, DOOR_A)
        self.assertEqual(1, status["synced_targets"])
        self.assertEqual(1, status["latest_acl_version"])
        with self.assertRaisesRegex(ValueError, "published"):
            self.service.ack_snapshot(TENANT_A, TARGET_A, DOOR_A, 999, "00" * 32, "APPLIED")

    def test_unexpired_local_lease_survives_backend_outage(self) -> None:
        same_boot = {
            "received_monotonic_s": 10,
            "lease_seconds": 900,
            "receipt_boot_id": "boot-a",
            "current_boot_id": "boot-a",
            "not_before_epoch_s": NOW,
            "expires_at_epoch_s": NOW + 3600,
            "received_epoch_s": NOW,
            "trusted_now_epoch_s": None,
        }
        self.assertTrue(acl_snapshot_is_usable(now_monotonic_s=909, **same_boot))
        self.assertFalse(acl_snapshot_is_usable(now_monotonic_s=910, **same_boot))
        self.assertFalse(
            acl_snapshot_is_usable(
                now_monotonic_s=1,
                **dict(same_boot, current_boot_id="boot-b"),
            )
        )
        self.assertTrue(
            acl_snapshot_is_usable(
                now_monotonic_s=1,
                **dict(
                    same_boot,
                    current_boot_id="boot-b",
                    trusted_now_epoch_s=NOW + 10,
                ),
            )
        )
        self.assertFalse(
            acl_snapshot_is_usable(
                now_monotonic_s=1,
                **dict(
                    same_boot,
                    current_boot_id="boot-b",
                    trusted_now_epoch_s=NOW + 900,
                ),
            )
        )

    def test_audit_redacts_nonce_signature_public_key_and_legacy_device_id(self) -> None:
        self.enroll()
        rendered = json.dumps([dict(row) for row in self.store.list_audit(TENANT_A)], sort_keys=True)
        self.assertNotIn("DEV-DO-NOT-STORE-RAW", rendered)
        self.assertNotIn(VECTOR["proof"]["expected"]["public_key_sec1"], rendered)
        self.assertNotIn(VECTOR["proof"]["expected"]["signature_raw64"], rendered)
        self.assertNotIn(VECTOR["challenge"]["fields"]["nonce"], rendered)
        self.assertIn("legacy_device_ref", rendered)

    def test_legacy_lookup_is_feature_flagged_and_never_authorizes_acl(self) -> None:
        credential_id = self.enroll()
        self.assertIsNone(self.service.lookup_legacy_device(TENANT_A, "DEV-DO-NOT-STORE-RAW"))
        enabled_service = AclManagementService(
            self.store,
            self.signer,
            self.publisher,
            clock=self.clock,
            legacy_lookup_enabled=True,
            legacy_hmac_key=b"explicit-test-only-key",
        )
        self.assertEqual(
            credential_id,
            enabled_service.lookup_legacy_device(TENANT_A, "DEV-DO-NOT-STORE-RAW"),
        )
        snapshot = self.service.publish_snapshot(TENANT_A, DOOR_A, actor_ref="admin:a")
        self.assertEqual([], snapshot["fields"]["entries"])
        with self.assertRaisesRegex(ValueError, "legacy HMAC"):
            AclManagementService(
                self.store,
                self.signer,
                self.publisher,
                clock=self.clock,
                legacy_lookup_enabled=True,
            )

    def test_n_and_n_minus_1_protocol_entries_remain_compatible(self) -> None:
        credential_id = self.enroll(max_protocol=2)
        self.service.approve_credential(TENANT_A, credential_id, actor_ref="admin:a")
        self.service.grant_credential_to_door(
            TENANT_A, DOOR_A, credential_id, actor_ref="admin:a"
        )
        snapshot = self.service.publish_snapshot(TENANT_A, DOOR_A, actor_ref="admin:a", min_protocol=1, max_protocol=2)
        entry = snapshot["fields"]["entries"][0]
        self.assertEqual((1, 2), (entry["min_protocol"], entry["max_protocol"]))
        self.assertEqual(
            "activate",
            verify_snapshot_envelope(
                snapshot,
                trusted_signing_keys={7: self.signer.public_key_sec1},
                expected_door_id=DOOR_A,
                target_min_protocol=1,
                target_max_protocol=1,
                trusted_now_epoch_s=NOW,
                current_boot_id="boot-a",
                receipt_boot_id="boot-a",
                effective_high_watermark=0,
                current_digest="00" * 32,
            ),
        )

    def test_rotation_snapshot_validates_with_primary_and_transition_signers(self) -> None:
        next_signer = DeterministicP256Signer(8, signing_key_id=8)
        service = AclManagementService(
            self.store,
            self.signer,
            self.publisher,
            clock=self.clock,
            transition_signers=(next_signer,),
        )
        envelope = service.sign_explicit_snapshot(VECTOR["acl"]["fields"])
        common = {
            "envelope": envelope,
            "expected_door_id": DOOR_A,
            "target_min_protocol": 1,
            "target_max_protocol": 1,
            "trusted_now_epoch_s": envelope["fields"]["not_before_epoch_s"],
            "current_boot_id": "boot-a",
            "receipt_boot_id": "boot-a",
            "effective_high_watermark": 0,
            "current_digest": "00" * 32,
        }
        for signer in (self.signer, next_signer):
            self.assertEqual(
                "activate",
                verify_snapshot_envelope(
                    trusted_signing_keys={
                        signer.signing_key_id: signer.public_key_sec1
                    },
                    **common,
                ),
            )
        with self.assertRaisesRegex(ValueError, "N-1 signer must remain primary"):
            AclManagementService(
                self.store,
                next_signer,
                self.publisher,
                clock=self.clock,
                transition_signers=(self.signer,),
            )

    def test_door_grants_do_not_authorize_other_tenant_doors(self) -> None:
        credential_id = self.enroll()
        other_door = "0123456789abcdef0123456789abcdef"
        self.service.approve_credential(TENANT_A, credential_id, actor_ref="admin:a")
        self.service.grant_credential_to_door(
            TENANT_A, DOOR_A, credential_id, actor_ref="admin:a"
        )
        allowed = self.service.publish_snapshot(TENANT_A, DOOR_A, actor_ref="admin:a")
        denied = self.service.publish_snapshot(TENANT_A, other_door, actor_ref="admin:a")
        self.assertEqual([credential_id], [item["credential_id"] for item in allowed["fields"]["entries"]])
        self.assertEqual([], denied["fields"]["entries"])

        tenant_b_credential = self.enroll(TENANT_B, private_scalar=4)
        self.service.approve_credential(
            TENANT_B, tenant_b_credential, actor_ref="admin:b"
        )
        self.service.grant_credential_to_door(
            TENANT_B, DOOR_A, tenant_b_credential, actor_ref="admin:b"
        )
        with self.assertRaisesRegex(PermissionError, "another tenant"):
            self.service.publish_snapshot(TENANT_B, DOOR_A, actor_ref="admin:b")

    def test_ota_metadata_and_health_are_independent_of_acl_credential_state(self) -> None:
        metadata = {
            "component": "target",
            "version": "2.2.0",
            "primary_url": "https://primary.example/fw.bin",
            "fallback_url": "https://fallback.example/fw.bin",
            "sha256": "ab" * 32,
            "signature": "cd" * 64,
            "protocol_min": 1,
            "protocol_max": 2,
        }
        self.service.put_ota_metadata(TENANT_A, metadata, actor_ref="release:a")
        self.assertEqual(metadata, self.service.get_ota_metadata(TENANT_A, "target"))
        health = self.service.confirm_ota_health(
            TENANT_A,
            TARGET_A,
            component="target",
            version="2.2.0",
            boot_id="boot-new",
            artifact_sha256="ab" * 32,
            healthy=True,
        )
        self.assertEqual("HEALTH_CONFIRMED", health["status"])
        self.assertEqual([], self.store.list_credentials(TENANT_A, statuses=("ACTIVE",)))


if __name__ == "__main__":
    unittest.main()
