from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import pymysql
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.acl_management import DeterministicP256Signer


COMMAND_TENANT = "11" * 16
COMMAND_DOOR = "22" * 16
PERSONAL_TENANT = "66" * 16
PERSONAL_DOOR = "77" * 16
CREDENTIAL = "33" * 16


class MobileRemoteControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app, base_url="https://testserver")
        self.signer = DeterministicP256Signer(18, signing_key_id=0)

    def _request(
        self,
        *,
        signature: str | None = None,
        grant: bool = True,
        replay: bool = False,
    ):
        nonce = "44" * 32
        idempotency = "55" * 24
        expires_at = int(time.time()) + 60
        canonical = main.build_mobile_manual_open_input(
            CREDENTIAL,
            nonce,
            expires_at,
            "mobile_manual_button",
            idempotency,
        )
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            {
                "credential_id": CREDENTIAL,
                "tenant_id": PERSONAL_TENANT,
                "public_key_sec1": self.signer.public_key_sec1.hex(),
                "status": "ACTIVE",
                "expires_at": None,
                "tenant_status": "ACTIVE",
            },
            {"permissions": 1} if grant else None,
        ]
        if replay:
            def execute(sql, *_args):
                if "INSERT INTO mobile_credential_control_nonces" in sql:
                    raise pymysql.err.IntegrityError(1062, "duplicate")
                return None

            cursor.execute.side_effect = execute
        payload = {
            "credential_id": CREDENTIAL,
            "reason": "mobile_manual_button",
            "nonce": nonce,
            "expires_at": expires_at,
            "signature_raw64": signature or self.signer.sign(canonical).hex(),
        }
        with (
            patch.object(main, "_acl_runtime_ready", True),
            patch.object(main, "COMMAND_TENANT_ID", COMMAND_TENANT),
            patch.object(main, "COMMAND_DOOR_ID", COMMAND_DOOR),
            patch.object(main, "ACL_PERSONAL_TENANT_ID", PERSONAL_TENANT),
            patch.object(main, "ACL_PERSONAL_DOOR_ID", PERSONAL_DOOR),
            patch.object(main, "get_db", return_value=connection),
            patch.object(main, "publish_force_open_to_mqtt", return_value=True) as publish,
        ):
            response = self.client.post(
                "/api/v1/door/open",
                json=payload,
                headers={"Idempotency-Key": idempotency},
            )
        return response, connection, cursor, publish

    def test_keystore_credential_proof_is_consumed_before_broker_publish(self) -> None:
        response, connection, cursor, publish = self._request()

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("credential-signature-v3", response.json()["auth"])
        self.assertEqual("broker-ack-only", response.json()["delivery"])
        self.assertEqual(1, publish.call_count)
        self.assertTrue(connection.commit.called)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("mobile_credential_control_nonces" in sql for sql in statements))
        grant_query = next(
            call
            for call in cursor.execute.call_args_list
            if "credential_door_grants" in call.args[0]
        )
        self.assertEqual(
            (PERSONAL_TENANT, PERSONAL_DOOR, CREDENTIAL),
            grant_query.args[1],
        )
        self.assertNotIn("X-API-KEY", response.request.headers)

    def test_personal_acl_scope_is_independent_from_legacy_command_scope(self) -> None:
        self.assertNotEqual(PERSONAL_TENANT, COMMAND_TENANT)
        self.assertNotEqual(PERSONAL_DOOR, COMMAND_DOOR)

        response, _, _, publish = self._request()

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(1, publish.call_count)

    def test_invalid_signature_and_missing_grant_never_publish(self) -> None:
        invalid, _, _, invalid_publish = self._request(signature="00" * 64)
        self.assertEqual(403, invalid.status_code, invalid.text)
        self.assertFalse(invalid_publish.called)

        missing, _, _, missing_publish = self._request(grant=False)
        self.assertEqual(403, missing.status_code, missing.text)
        self.assertFalse(missing_publish.called)

    def test_replayed_nonce_is_conflict_and_never_publishes(self) -> None:
        response, connection, _, publish = self._request(replay=True)

        self.assertEqual(409, response.status_code, response.text)
        self.assertTrue(connection.rollback.called)
        self.assertFalse(connection.commit.called)
        self.assertFalse(publish.called)

    def test_legacy_device_id_without_v2_proof_remains_upgrade_required(self) -> None:
        response = self.client.post(
            "/api/v1/door/open",
            json={"device_id": "DEV-STOLEN", "reason": "manual_click"},
        )
        self.assertEqual(426, response.status_code)

    def test_canonical_contract_is_fixed_width_and_field_bound(self) -> None:
        canonical = main.build_mobile_manual_open_input(
            CREDENTIAL,
            "44" * 32,
            1_900_000_000,
            "mobile_manual_button",
            "55" * 24,
        )
        self.assertEqual(128, len(canonical))
        self.assertEqual(b"SGKRMO01", canonical[:8])
        self.assertNotEqual(
            canonical,
            main.build_mobile_manual_open_input(
                CREDENTIAL,
                "44" * 32,
                1_900_000_001,
                "mobile_manual_button",
                "55" * 24,
            ),
        )

    def test_signed_logout_revokes_before_account_cleanup(self) -> None:
        nonce = "88" * 32
        idempotency = "99" * 24
        expires_at = int(time.time()) + 60
        canonical = main.build_mobile_account_logout_input(
            CREDENTIAL, nonce, expires_at, idempotency
        )
        verification = MagicMock()
        verification_cursor = verification.cursor.return_value.__enter__.return_value
        verification_cursor.fetchone.return_value = {
            "credential_id": CREDENTIAL,
            "tenant_id": PERSONAL_TENANT,
            "public_key_sec1": self.signer.public_key_sec1.hex(),
            "status": "ACTIVE",
            "tenant_status": "ACTIVE",
            "legacy_tenant_id": 7,
        }
        cleanup = MagicMock()
        cleanup_cursor = cleanup.cursor.return_value.__enter__.return_value
        cleanup_cursor.fetchone.return_value = {
            "tenant_uuid": None,
            "credential_id": CREDENTIAL,
        }
        cleanup_cursor.rowcount = 1
        service = MagicMock()
        with (
            patch.object(main, "_acl_runtime_ready", True),
            patch.object(main, "_acl_service", service, create=True),
            patch.object(main, "ACL_PERSONAL_TENANT_ID", PERSONAL_TENANT),
            patch.object(main, "get_db", side_effect=[verification, cleanup]),
        ):
            response = self.client.post(
                "/api/v1/mobile/account/logout",
                headers={"Idempotency-Key": idempotency},
                json={
                    "credential_id": CREDENTIAL,
                    "nonce": nonce,
                    "expires_at": expires_at,
                    "signature_raw64": self.signer.sign(canonical).hex(),
                },
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertTrue(response.json()["local_clear_authorized"])
        service.revoke_credential.assert_called_once()
        self.assertTrue(verification.commit.called)
        self.assertTrue(cleanup.commit.called)
        statements = [call.args[0] for call in cleanup_cursor.execute.call_args_list]
        self.assertTrue(any("DELETE FROM tenants" in sql for sql in statements))

    def test_logout_canonical_is_separate_and_fixed_width(self) -> None:
        canonical = main.build_mobile_account_logout_input(
            CREDENTIAL, "88" * 32, 1_900_000_000, "99" * 24
        )
        self.assertEqual(96, len(canonical))
        self.assertEqual(b"SGKOUT01", canonical[:8])
        self.assertNotEqual(
            canonical,
            main.build_mobile_account_logout_input(
                CREDENTIAL, "88" * 32, 1_900_000_001, "99" * 24
            ),
        )


if __name__ == "__main__":
    unittest.main()
