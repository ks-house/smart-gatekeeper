from __future__ import annotations

import hashlib
import time
from unittest.mock import MagicMock, patch
import unittest

from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app import main
from backend.app.admin_security import AdminSecurity


FINGERPRINT_ADMIN = "d" * 64
FINGERPRINT_AUDITOR = "e" * 64


class OperationsApiTest(unittest.TestCase):
    def setUp(self):
        security = AdminSecurity(
            {
                FINGERPRINT_ADMIN: {
                    "subject": "privacy-admin",
                    "roles": ["TENANT_ADMIN"],
                    "tenants": ["legacy:1"],
                },
                FINGERPRINT_AUDITOR: {
                    "subject": "privacy-auditor",
                    "roles": ["AUDITOR"],
                    "tenants": ["legacy:1"],
                },
            },
            session_seconds=60,
            trusted_proxy_ips={"testclient"},
        )
        self.patch = patch.object(main, "admin_security", security)
        self.patch.start()
        self.client = TestClient(main.app, base_url="https://testserver")

    def tearDown(self):
        self.patch.stop()

    @staticmethod
    def mtls(fingerprint):
        return {
            "X-SSL-Client-Verify": "SUCCESS",
            "X-SSL-Client-SHA256": fingerprint,
        }

    def session(self, fingerprint):
        response = self.client.post("/api/v1/admin/sessions", headers=self.mtls(fingerprint))
        self.assertEqual(200, response.status_code, response.text)
        return response.json()["csrf_token"]

    def test_liveness_is_not_dependency_readiness(self):
        response = self.client.get("/live")
        self.assertEqual(200, response.status_code)
        self.assertEqual("process_liveness_only", response.json()["scope"])
        self.assertNotIn("database", response.json())

    @staticmethod
    def request_from(peer: str, forwarded: str) -> Request:
        return Request({
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/verify",
            "raw_path": b"/api/v1/auth/verify",
            "query_string": b"",
            "headers": [(b"x-forwarded-for", forwarded.encode("ascii"))],
            "client": (peer, 12345),
            "server": ("testserver", 443),
            "scheme": "https",
        })

    def test_rate_limit_identity_only_trusts_single_hop_from_known_proxy(self):
        trusted_a = main._rate_limit_identity(self.request_from("testclient", "203.0.113.8"))
        trusted_b = main._rate_limit_identity(self.request_from("testclient", "203.0.113.9"))
        self.assertNotEqual(trusted_a, trusted_b)

        untrusted_a = main._rate_limit_identity(self.request_from("198.51.100.5", "203.0.113.8"))
        untrusted_b = main._rate_limit_identity(self.request_from("198.51.100.5", "203.0.113.9"))
        self.assertEqual(untrusted_a, untrusted_b)

        chained = main._rate_limit_identity(
            self.request_from("testclient", "203.0.113.8, 198.51.100.5")
        )
        self.assertNotEqual(trusted_a, chained)

    def test_readiness_fails_closed_and_can_report_all_dependencies(self):
        failed = self.client.get("/ready")
        self.assertEqual(503, failed.status_code)
        for required in (
            "control_api_auth", "acl_management",
            "legacy_prearm_retired",
        ):
            self.assertFalse(failed.json()["checks"][required], required)
        with patch.object(main, "admin_security", AdminSecurity()):
            self.assertFalse(self.client.get("/ready").json()["checks"]["admin_auth"])
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            {"ready": 1},
            {"script_sha256": "f" * 64},
        ]
        publisher = MagicMock()
        publisher.probe.return_value = True
        with patch.object(main, "get_db", return_value=connection), patch.object(
            main, "_command_provisioning_error", return_value=None
        ), patch.object(main, "_persistent_publisher", return_value=publisher), patch.object(
            main, "BUILD_SHA", "a" * 40
        ), patch.object(main, "OPS_HMAC_KEY", b"k" * 32), patch.object(
            main, "DB_PASSWORD", "isolated-test-password"
        ), patch.object(main, "GATEKEEPER_API_KEY", "g" * 32), patch.object(
            main, "ACL_MANAGEMENT_ENABLED", True
        ), patch.object(main, "_acl_runtime_ready", True), patch.object(
            main, "ACL_LEGACY_DEVICE_LOOKUP_ENABLED", False
        ), patch.object(
            main, "ACCESS_EVENT_REF_KEYS", {"k1": b"r" * 32}
        ), patch.object(
            main, "ACL_PERSONAL_DOOR_ID", "1" * 32
        ), patch.object(main, "EXPECTED_DB_SCHEMA_VERSION", "008"), patch.object(
            main, "EXPECTED_DB_SCHEMA_SHA256", "f" * 64
        ), patch.object(
            main._canonical_access_collector_health, "ready", return_value=True
        ), patch.object(
            main._authenticated_status_collector_health,
            "ready",
            return_value=True,
        ):
            ready = self.client.get("/ready")
        self.assertEqual(200, ready.status_code, ready.text)
        self.assertTrue(all(ready.json()["checks"].values()))

    def test_readiness_rejects_missing_or_wrong_schema_ledger(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            {"ready": 1}, {"script_sha256": "0" * 64},
        ]
        with patch.object(main, "get_db", return_value=connection), patch.object(
            main, "EXPECTED_DB_SCHEMA_VERSION", "008"
        ), patch.object(main, "EXPECTED_DB_SCHEMA_SHA256", "f" * 64):
            ready, checks = main._readiness_snapshot()
        self.assertFalse(ready)
        self.assertTrue(checks["database"])
        self.assertFalse(checks["database_schema"])

    def test_support_export_is_mtls_scoped_consent_bound_and_redacted(self):
        self.assertEqual(
            401,
            self.client.get(
                "/api/v1/admin/privacy/support-export",
                headers={"X-Tenant-ID": "legacy:1", "X-Support-Consent": "consent_" + "a" * 32},
            ).status_code,
        )
        self.session(FINGERPRINT_AUDITOR)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "tenant_scope": "legacy:1",
            "purpose": "support-diagnostics",
            "expires_at": int(time.time()) + 300,
            "revoked_at": None,
        }
        cursor.fetchall.return_value = [{
            "auth_method": "BLE_BEACON",
            "is_success": False,
            "distance_mm": 500,
            "failure_reason": "token=secret123 AA:BB:CC:DD:EE:FF",
            "created_at": "2026-08-09T00:00:00Z",
        }]
        with patch.object(main, "get_db", return_value=connection):
            response = self.client.get(
                "/api/v1/admin/privacy/support-export",
                headers={"X-Tenant-ID": "legacy:1", "X-Support-Consent": "consent_" + "a" * 32},
            )
        self.assertEqual(200, response.status_code, response.text)
        rendered = response.text
        self.assertNotIn("secret123", rendered)
        self.assertNotIn("AA:BB", rendered)
        self.assertRegex(response.json()["consent_ref"], r"^consent_[a-f0-9]{24}$")
        self.assertNotIn("consent_" + "a" * 32, rendered)
        self.assertRegex(response.json()["sha256"], r"^[a-f0-9]{64}$")
        connection.commit.assert_called_once()

    def test_support_export_rejects_invalid_consent_lifecycle(self):
        self.session(FINGERPRINT_AUDITOR)
        invalid_rows = (
            None,
            {"tenant_scope": "legacy:1", "purpose": "support-diagnostics", "expires_at": 1, "revoked_at": None},
            {"tenant_scope": "legacy:1", "purpose": "support-diagnostics", "expires_at": int(time.time()) + 300, "revoked_at": 2},
            {"tenant_scope": "legacy:2", "purpose": "support-diagnostics", "expires_at": int(time.time()) + 300, "revoked_at": None},
        )
        for consent in invalid_rows:
            with self.subTest(consent=consent):
                connection = MagicMock()
                cursor = connection.cursor.return_value.__enter__.return_value
                cursor.fetchone.return_value = consent
                with patch.object(main, "get_db", return_value=connection):
                    response = self.client.get(
                        "/api/v1/admin/privacy/support-export",
                        headers={
                            "X-Tenant-ID": "legacy:1",
                            "X-Support-Consent": "consent_" + "f" * 32,
                        },
                    )
                self.assertEqual(403, response.status_code, response.text)
                connection.rollback.assert_called_once()

    def test_retention_delete_requires_admin_csrf_reauth_and_is_idempotent(self):
        csrf = self.session(FINGERPRINT_ADMIN)
        base = {
            **self.mtls(FINGERPRINT_ADMIN),
            "X-Tenant-ID": "legacy:1",
            "X-Admin-Reauthenticate": "mtls",
            "Idempotency-Key": "privacy-delete-1",
        }
        denied = self.client.post(
            "/api/v1/admin/privacy/delete",
            headers=base,
            json={"policy_version": "sgk-retention-v1", "before_days": 365},
        )
        self.assertEqual(403, denied.status_code)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        request_hash = hashlib.sha256(
            b'{"actor_subject":"privacy-admin","before_days":365,"policy_version":"sgk-retention-v1","tenant_scope":"legacy:1"}'
        ).hexdigest()
        cursor.fetchone.return_value = {
            "actor_subject": "privacy-admin",
            "request_hash": request_hash,
            "state": "PENDING",
            "deleted_count": None,
        }

        def execute(query, _params=None):
            if query.startswith("DELETE FROM access_logs"):
                cursor.rowcount = 3
            elif query.startswith("UPDATE privacy_deletion_jobs"):
                cursor.rowcount = 1

        cursor.execute.side_effect = execute
        with patch.object(main, "get_db", return_value=connection):
            deleted = self.client.post(
                "/api/v1/admin/privacy/delete",
                headers={**base, "X-CSRF-Token": csrf},
                json={"policy_version": "sgk-retention-v1", "before_days": 365},
            )
        self.assertEqual(200, deleted.status_code, deleted.text)
        self.assertEqual({"status": "completed", "deleted_count": 3}, deleted.json())
        connection.commit.assert_called_once()

    def test_retention_delete_rejects_idempotency_payload_or_actor_mismatch(self):
        csrf = self.session(FINGERPRINT_ADMIN)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "actor_subject": "different-admin",
            "request_hash": "f" * 64,
            "state": "COMPLETED",
            "deleted_count": 9,
        }
        with patch.object(main, "get_db", return_value=connection):
            response = self.client.post(
                "/api/v1/admin/privacy/delete",
                headers={
                    **self.mtls(FINGERPRINT_ADMIN),
                    "X-Tenant-ID": "legacy:1",
                    "X-Admin-Reauthenticate": "mtls",
                    "Idempotency-Key": "privacy-delete-conflict",
                    "X-CSRF-Token": csrf,
                },
                json={"policy_version": "sgk-retention-v1", "before_days": 730},
            )
        self.assertEqual(409, response.status_code, response.text)
        connection.rollback.assert_called_once()

    def test_mqtt_failure_log_never_contains_tenant_name_or_unit(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "id": 1,
            "name": "Private Resident",
            "unit_number": "Secret-101",
            "is_active": True,
        }
        request = main.PrearmRequestSchema(
            beacon_uuid="beacon", device_id="AA:BB:CC:DD:EE:FF"
        )
        with patch.object(main, "ACL_LEGACY_DEVICE_LOOKUP_ENABLED", True), patch.object(
            main, "get_db", return_value=connection
        ), patch.object(
            main, "publish_arm_to_mqtt", return_value=False
        ), self.assertLogs(main.log, level="ERROR") as captured:
            response = main.door_prearm(request, _auth=None)
        self.assertEqual(503, response.status_code)
        rendered = "\n".join(captured.output)
        self.assertNotIn("Private Resident", rendered)
        self.assertNotIn("Secret-101", rendered)

    def test_production_legacy_prearm_is_retired_before_raw_device_lookup(self):
        request = main.PrearmRequestSchema(
            beacon_uuid="beacon", device_id="AA:BB:CC:DD:EE:FF"
        )
        with patch.object(
            main, "ACL_LEGACY_DEVICE_LOOKUP_ENABLED", False
        ), patch.object(main, "get_db") as database, patch.object(
            main, "publish_arm_to_mqtt"
        ) as publish:
            response = main.door_prearm(request, _auth=None)
        self.assertEqual(410, response.status_code)
        database.assert_not_called()
        publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
