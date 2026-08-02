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
        store = AclStore(lambda: self.conn, dialect="sqlite", close_connections=False)
        store.create_tenant(TENANT_A, "A")
        store.create_tenant(TENANT_B, "B")
        self.service = AclManagementService(
            store,
            DeterministicP256Signer(2, signing_key_id=7),
            RecordingPublisher(),
            clock=lambda: 1_785_542_400,
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
