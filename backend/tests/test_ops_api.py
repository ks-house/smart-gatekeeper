from __future__ import annotations

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
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"ready": 1}
        publisher = MagicMock()
        publisher.probe.return_value = True
        with patch.object(main, "get_db", return_value=connection), patch.object(
            main, "_command_provisioning_error", return_value=None
        ), patch.object(main, "_persistent_publisher", return_value=publisher), patch.object(
            main, "BUILD_SHA", "a" * 40
        ), patch.object(main, "OPS_HMAC_KEY", b"k" * 32), patch.object(
            main, "DB_PASSWORD", "isolated-test-password"
        ):
            ready = self.client.get("/ready")
        self.assertEqual(200, ready.status_code, ready.text)
        self.assertTrue(all(ready.json()["checks"].values()))

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
        self.assertRegex(response.json()["sha256"], r"^[a-f0-9]{64}$")
        connection.commit.assert_called_once()

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
        cursor.fetchone.return_value = None
        cursor.rowcount = 3
        with patch.object(main, "get_db", return_value=connection):
            deleted = self.client.post(
                "/api/v1/admin/privacy/delete",
                headers={**base, "X-CSRF-Token": csrf},
                json={"policy_version": "sgk-retention-v1", "before_days": 365},
            )
        self.assertEqual(200, deleted.status_code, deleted.text)
        self.assertEqual({"status": "completed", "deleted_count": 3}, deleted.json())
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
