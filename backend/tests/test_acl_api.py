from __future__ import annotations

import sqlite3
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.acl_api import AclApiConfig, create_acl_router
from backend.app.acl_management import (
    AclManagementService,
    AclStore,
    DeterministicP256Signer,
    RecordingPublisher,
    build_enrollment_input,
    initialize_sqlite_test_schema,
)


TENANT_A = "11111111111111111111111111111111"
TENANT_B = "22222222222222222222222222222222"
DOOR = "00112233445566778899aabbccddeeff"


class AclApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        initialize_sqlite_test_schema(self.conn)
        self.store = AclStore(lambda: self.conn, dialect="sqlite", close_connections=False)
        self.store.create_tenant(TENANT_A, "A")
        self.store.create_tenant(TENANT_B, "B")
        self.service = AclManagementService(
            self.store,
            DeterministicP256Signer(2, signing_key_id=7),
            RecordingPublisher(),
            clock=lambda: 1_785_542_400,
            legacy_hmac_key=b"personal-api-test-hmac-key",
        )
        app = FastAPI()
        app.include_router(
            create_acl_router(
                self.service,
                AclApiConfig(
                    enabled=True,
                    enrollment_credentials={
                        "actor-a": {"tenant_id": TENANT_A, "key": "enroll-secret-a"},
                        "actor-a-peer": {
                            "tenant_id": TENANT_A,
                            "key": "enroll-secret-a-peer",
                        },
                        "actor-b": {"tenant_id": TENANT_B, "key": "enroll-secret-b"},
                    },
                    admin_key="admin-secret",
                    target_credentials={
                        "target-a": {
                            "tenant_id": TENANT_A,
                            "door_id": DOOR,
                            "key": "target-secret-a",
                        },
                        "target-b": {
                            "tenant_id": TENANT_B,
                            "door_id": "f" * 32,
                            "key": "target-secret-b",
                        },
                    },
                    personal_enabled=True,
                    personal_api_key="personal-api-key",
                    personal_tenant_id=TENANT_A,
                    personal_door_id=DOOR,
                ),
            )
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.conn.close()

    def test_authentication_and_tenant_boundary(self) -> None:
        denied = self.client.post(
            "/api/v1/acl/enrollment/challenge", json={"tenant_id": TENANT_A}
        )
        self.assertEqual(401, denied.status_code)
        cross_tenant = self.client.post(
            "/api/v1/acl/enrollment/challenge",
            json={"tenant_id": TENANT_A},
            headers={
                "X-Enrollment-Key": "enroll-secret-a",
                "X-Enrollment-Actor-ID": "actor-a",
                "X-Tenant-ID": TENANT_B,
            },
        )
        self.assertEqual(403, cross_tenant.status_code)

    def test_personal_enrollment_contract_is_authenticated_and_idempotent(self) -> None:
        device_id = "DEV-PERSONAL-API"
        self.conn.execute(
            "INSERT INTO tenants "
            "(name, unit_number, ble_device_mac, is_active, tenant_uuid) "
            "VALUES (?, ?, ?, 1, ?)",
            ("personal", "home", device_id, TENANT_A),
        )
        self.conn.commit()
        device = DeterministicP256Signer(15, signing_key_id=0)
        body = {
            "device_id": device_id,
            "credential_id": "12" * 16,
            "public_key_sec1": device.public_key_sec1.hex(),
            "min_protocol": 1,
            "max_protocol": 1,
        }
        self.assertEqual(
            401,
            self.client.post("/api/v1/acl/personal/enroll", json=body).status_code,
        )
        wrong = self.client.post(
            "/api/v1/acl/personal/enroll",
            json=body,
            headers={"X-API-KEY": "wrong"},
        )
        self.assertEqual(401, wrong.status_code)

        first = self.client.post(
            "/api/v1/acl/personal/enroll",
            json=body,
            headers={"X-API-KEY": "personal-api-key"},
        )
        second = self.client.post(
            "/api/v1/acl/personal/enroll",
            json=body,
            headers={"X-API-KEY": "personal-api-key"},
        )
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(
            {
                "accepted": True,
                "credential_id": body["credential_id"],
                "acl_version": 1,
            },
            first.json(),
        )

        mismatch = dict(
            body,
            public_key_sec1=DeterministicP256Signer(
                16, signing_key_id=0
            ).public_key_sec1.hex(),
        )
        conflict = self.client.post(
            "/api/v1/acl/personal/enroll",
            json=mismatch,
            headers={"X-API-KEY": "personal-api-key"},
        )
        self.assertEqual(409, conflict.status_code)

        extra_private_material = dict(body, private_key="must-never-be-accepted")
        rejected = self.client.post(
            "/api/v1/acl/personal/enroll",
            json=extra_private_material,
            headers={"X-API-KEY": "personal-api-key"},
        )
        self.assertEqual(422, rejected.status_code)

    def test_personal_enrollment_bootstraps_unmapped_approved_legacy_row(self) -> None:
        self.conn.execute("DELETE FROM acl_tenants WHERE tenant_id=?", (TENANT_A,))
        self.conn.execute(
            "INSERT INTO tenants "
            "(name, unit_number, ble_device_mac, is_active, tenant_uuid) "
            "VALUES (?, ?, ?, 1, NULL)",
            ("personal", "home", "DEV-FIRST-BOOTSTRAP"),
        )
        self.conn.commit()
        device = DeterministicP256Signer(21, signing_key_id=0)
        response = self.client.post(
            "/api/v1/acl/personal/enroll",
            json={
                "device_id": "DEV-FIRST-BOOTSTRAP",
                "credential_id": "bc" * 16,
                "public_key_sec1": device.public_key_sec1.hex(),
                "min_protocol": 1,
                "max_protocol": 1,
            },
            headers={"X-API-KEY": "personal-api-key"},
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertTrue(response.json()["accepted"])
        mapping = self.conn.execute(
            "SELECT tenant_uuid, credential_mode FROM tenants "
            "WHERE ble_device_mac='DEV-FIRST-BOOTSTRAP'"
        ).fetchone()
        self.assertEqual(TENANT_A, mapping["tenant_uuid"])
        self.assertEqual("dual", mapping["credential_mode"])

    def test_personal_enrollment_unapproved_device_is_forbidden(self) -> None:
        device = DeterministicP256Signer(17, signing_key_id=0)
        response = self.client.post(
            "/api/v1/acl/personal/enroll",
            json={
                "device_id": "DEV-NOT-APPROVED",
                "credential_id": "34" * 16,
                "public_key_sec1": device.public_key_sec1.hex(),
                "min_protocol": 1,
                "max_protocol": 1,
            },
            headers={"X-API-KEY": "personal-api-key"},
        )
        self.assertEqual(403, response.status_code, response.text)

    def test_personal_enrollment_never_accepts_before_acl_delivery(self) -> None:
        device_id = "DEV-PERSONAL-DELIVERY"
        self.conn.execute(
            "INSERT INTO tenants "
            "(name, unit_number, ble_device_mac, is_active, tenant_uuid) "
            "VALUES (?, ?, ?, 1, ?)",
            ("personal", "home", device_id, TENANT_A),
        )
        self.conn.commit()
        device = DeterministicP256Signer(18, signing_key_id=0)
        body = {
            "device_id": device_id,
            "credential_id": "56" * 16,
            "public_key_sec1": device.public_key_sec1.hex(),
            "min_protocol": 1,
            "max_protocol": 1,
        }

        class FailingPublisher:
            def publish(self, _topic: str, _envelope: dict) -> bool:
                return False

        self.service.publisher = FailingPublisher()
        failed = self.client.post(
            "/api/v1/acl/personal/enroll",
            json=body,
            headers={"X-API-KEY": "personal-api-key"},
        )
        self.assertEqual(503, failed.status_code, failed.text)
        self.assertNotEqual(True, failed.json().get("accepted"))
        pending = self.store.snapshot_job(TENANT_A, DOOR)
        failed_version = int(pending["generated_version"])

        recovered = RecordingPublisher()
        self.service.publisher = recovered
        accepted = self.client.post(
            "/api/v1/acl/personal/enroll",
            json=body,
            headers={"X-API-KEY": "personal-api-key"},
        )
        self.assertEqual(200, accepted.status_code, accepted.text)
        self.assertTrue(accepted.json()["accepted"])
        self.assertEqual(failed_version, accepted.json()["acl_version"])
        self.assertEqual(
            failed_version,
            recovered.messages[0][1]["fields"]["acl_version"],
        )

    def test_enrollment_approval_snapshot_pull_ack_api(self) -> None:
        user_headers = {
            "X-Enrollment-Key": "enroll-secret-a",
            "X-Enrollment-Actor-ID": "actor-a",
            "X-Tenant-ID": TENANT_A,
        }
        challenge = self.client.post(
            "/api/v1/acl/enrollment/challenge",
            json={"tenant_id": TENANT_A},
            headers=user_headers,
        ).json()
        device = DeterministicP256Signer(1, signing_key_id=0)
        payload = build_enrollment_input(
            TENANT_A,
            challenge["enrollment_id"],
            challenge["nonce"],
            device.public_key_sec1.hex(),
        )
        enrolled_response = self.client.post(
            "/api/v1/acl/enrollment/submit",
            json={
                "tenant_id": TENANT_A,
                "enrollment_id": challenge["enrollment_id"],
                "nonce": challenge["nonce"],
                "public_key_sec1": device.public_key_sec1.hex(),
                "signature_raw64": device.sign(payload).hex(),
                "expires_at": 1_785_546_000,
                "min_protocol": 1,
                "max_protocol": 2,
            },
            headers=user_headers,
        )
        self.assertEqual(200, enrolled_response.status_code, enrolled_response.text)
        credential_id = enrolled_response.json()["credential_id"]

        admin_headers = {"X-Admin-Key": "admin-secret", "X-Tenant-ID": TENANT_A}
        self.assertEqual(
            200,
            self.client.post(
                "/api/v1/admin/acl/credentials/approve",
                json={"tenant_id": TENANT_A, "credential_id": credential_id},
                headers=admin_headers,
            ).status_code,
        )
        self.assertEqual(
            200,
            self.client.post(
                "/api/v1/admin/acl/grants/grant",
                json={
                    "tenant_id": TENANT_A,
                    "credential_id": credential_id,
                    "door_id": DOOR,
                },
                headers=admin_headers,
            ).status_code,
        )
        published = self.client.post(
            f"/api/v1/admin/acl/snapshots/{DOOR}",
            json={"tenant_id": TENANT_A, "min_protocol": 1, "max_protocol": 2},
            headers=admin_headers,
        )
        self.assertEqual(200, published.status_code, published.text)
        envelope = published.json()

        target_headers = {
            "X-Target-Key": "target-secret-a",
            "X-Target-ID": "target-a",
            "X-Tenant-ID": TENANT_A,
        }
        pulled = self.client.get(
            f"/api/v1/acl/snapshots/{DOOR}", headers=target_headers
        )
        self.assertEqual(envelope["sha256"], pulled.json()["sha256"])
        other_door_pull = self.client.get(
            f"/api/v1/acl/snapshots/{'f' * 32}", headers=target_headers
        )
        self.assertEqual(403, other_door_pull.status_code)
        acked = self.client.post(
            "/api/v1/acl/acks",
            json={
                "tenant_id": TENANT_A,
                "target_id": "target-a",
                "door_id": DOOR,
                "acl_version": 1,
                "sha256": envelope["sha256"],
                "status": "APPLIED",
            },
            headers=target_headers,
        )
        self.assertEqual(200, acked.status_code, acked.text)
        forged = self.client.post(
            "/api/v1/acl/acks",
            json={
                "tenant_id": TENANT_A,
                "target_id": "target-b",
                "door_id": DOOR,
                "acl_version": 1,
                "sha256": envelope["sha256"],
                "status": "APPLIED",
            },
            headers=target_headers,
        )
        self.assertEqual(403, forged.status_code)
        fleet = self.client.get(
            f"/api/v1/admin/acl/fleet/{DOOR}", headers=admin_headers
        )
        self.assertEqual(1, fleet.json()["synced_targets"])

        wrong_tenant_actor = self.client.post(
            "/api/v1/admin/acl/tenants/disable",
            json={"tenant_id": TENANT_A},
            headers={"X-Admin-Key": "admin-secret", "X-Tenant-ID": TENANT_B},
        )
        self.assertEqual(403, wrong_tenant_actor.status_code)
        disabled = self.client.post(
            "/api/v1/admin/acl/tenants/disable",
            json={"tenant_id": TENANT_A},
            headers=admin_headers,
        )
        self.assertEqual(200, disabled.status_code, disabled.text)
        self.assertFalse(disabled.json()["already_disabled"])
        replacement = self.client.get(
            f"/api/v1/acl/snapshots/{DOOR}", headers=target_headers
        ).json()
        self.assertEqual(2, replacement["fields"]["acl_version"])
        self.assertEqual([], replacement["fields"]["entries"])
        repeated = self.client.post(
            "/api/v1/admin/acl/tenants/disable",
            json={"tenant_id": TENANT_A},
            headers=admin_headers,
        )
        self.assertEqual(200, repeated.status_code, repeated.text)
        self.assertTrue(repeated.json()["already_disabled"])
        self.assertEqual([], repeated.json()["replacement_snapshots"])
        challenge_after_disable = self.client.post(
            "/api/v1/acl/enrollment/challenge",
            json={"tenant_id": TENANT_A},
            headers=user_headers,
        )
        self.assertEqual(403, challenge_after_disable.status_code)
        self.assertEqual(
            1,
            sum(
                row["action"] == "TENANT_DISABLED"
                for row in self.store.list_audit(TENANT_A)
            ),
        )

    def test_enrollment_submit_rejects_different_authenticated_actor(self) -> None:
        actor_a_headers = {
            "X-Enrollment-Key": "enroll-secret-a",
            "X-Enrollment-Actor-ID": "actor-a",
            "X-Tenant-ID": TENANT_A,
        }
        challenge = self.client.post(
            "/api/v1/acl/enrollment/challenge",
            json={"tenant_id": TENANT_A},
            headers=actor_a_headers,
        ).json()
        device = DeterministicP256Signer(5, signing_key_id=0)
        payload = build_enrollment_input(
            TENANT_A,
            challenge["enrollment_id"],
            challenge["nonce"],
            device.public_key_sec1.hex(),
        )
        body = {
            "tenant_id": TENANT_A,
            "enrollment_id": challenge["enrollment_id"],
            "nonce": challenge["nonce"],
            "public_key_sec1": device.public_key_sec1.hex(),
            "signature_raw64": device.sign(payload).hex(),
        }
        same_tenant_peer = self.client.post(
            "/api/v1/acl/enrollment/submit",
            json=body,
            headers={
                "X-Enrollment-Key": "enroll-secret-a-peer",
                "X-Enrollment-Actor-ID": "actor-a-peer",
                "X-Tenant-ID": TENANT_A,
            },
        )
        self.assertEqual(403, same_tenant_peer.status_code)
        self.assertIn("actor boundary", same_tenant_peer.json()["detail"])

        cross_tenant_actor = self.client.post(
            "/api/v1/acl/enrollment/submit",
            json=body,
            headers={
                "X-Enrollment-Key": "enroll-secret-b",
                "X-Enrollment-Actor-ID": "actor-b",
                "X-Tenant-ID": TENANT_B,
            },
        )
        self.assertEqual(403, cross_tenant_actor.status_code)

        original_actor = self.client.post(
            "/api/v1/acl/enrollment/submit", json=body, headers=actor_a_headers
        )
        self.assertEqual(200, original_actor.status_code, original_actor.text)

    def test_feature_flag_is_fail_closed(self) -> None:
        app = FastAPI()
        app.include_router(
            create_acl_router(
                self.service,
                AclApiConfig(
                    enabled=False,
                    enrollment_credentials={
                        "actor-a": {"tenant_id": TENANT_A, "key": "enroll-secret-a"}
                    },
                    admin_key="admin-secret",
                    target_credentials={
                        "target-a": {"tenant_id": TENANT_A, "key": "target-secret-a"}
                    },
                ),
            )
        )
        response = TestClient(app).post(
            "/api/v1/acl/enrollment/challenge",
            json={"tenant_id": TENANT_A},
            headers={
                "X-Enrollment-Key": "enroll-secret-a",
                "X-Enrollment-Actor-ID": "actor-a",
                "X-Tenant-ID": TENANT_A,
            },
        )
        self.assertEqual(503, response.status_code)


if __name__ == "__main__":
    unittest.main()
