from __future__ import annotations

import hashlib
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.admin_security import AdminSecurity


FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64
FINGERPRINT_C = "c" * 64


class AdminSecurityBypassTest(unittest.TestCase):
    def setUp(self) -> None:
        self.security = AdminSecurity(
            {
                FINGERPRINT_A: {
                    "subject": "operator-a",
                    "roles": ["TENANT_ADMIN", "SECURITY_OPERATOR"],
                    "tenants": ["legacy:1"],
                },
                FINGERPRINT_B: {
                    "subject": "approver-b",
                    "roles": ["SECURITY_APPROVER", "AUDITOR"],
                    "tenants": ["legacy:1"],
                },
                FINGERPRINT_C: {
                    "subject": "other-tenant-approver",
                    "roles": ["SECURITY_APPROVER"],
                    "tenants": ["legacy:2"],
                },
            },
            session_seconds=60,
            auth_attempts=2,
            auth_window_seconds=60,
            trusted_proxy_ips={"testclient"},
        )
        self.patch = patch.object(main, "admin_security", self.security)
        self.patch.start()
        self.client = TestClient(main.app, base_url="https://testserver")

    def tearDown(self) -> None:
        self.patch.stop()

    @staticmethod
    def _mtls_headers(fingerprint: str) -> dict[str, str]:
        return {"X-SSL-Client-Verify": "SUCCESS", "X-SSL-Client-SHA256": fingerprint}

    def _session(self, fingerprint: str) -> tuple[dict[str, str], str]:
        response = self.client.post("/api/v1/admin/sessions", headers=self._mtls_headers(fingerprint))
        self.assertEqual(200, response.status_code, response.text)
        return {"X-CSRF-Token": response.json()["csrf_token"]}, response.cookies["sgk_admin_session"]

    def test_anonymous_forged_role_stale_session_and_cross_tenant_are_denied(self) -> None:
        self.assertEqual(401, self.client.get("/api/v1/admin/config").status_code)
        self.assertEqual(
            401,
            self.client.post("/api/v1/admin/sessions", headers={"X-Role": "TENANT_ADMIN"}).status_code,
        )
        headers, token = self._session(FINGERPRINT_A)
        headers["Cookie"] = f"sgk_admin_session={token}"
        headers["X-SSL-Client-Verify"] = "SUCCESS"
        headers["X-SSL-Client-SHA256"] = FINGERPRINT_A
        headers["X-Admin-Reauthenticate"] = "mtls"
        headers["Idempotency-Key"] = "cross-tenant"
        response = self.client.post("/api/v1/admin/tenants/2/approve", headers=headers)
        self.assertEqual(403, response.status_code)
        self.security.rotate_sessions()
        self.assertEqual(401, self.client.get("/api/v1/admin/config", headers={"Cookie": f"sgk_admin_session={token}"}).status_code)

    def test_csrf_stolen_device_id_and_replay_do_not_publish(self) -> None:
        headers, token = self._session(FINGERPRINT_A)
        base = {
            "Cookie": f"sgk_admin_session={token}",
            "X-SSL-Client-Verify": "SUCCESS",
            "X-SSL-Client-SHA256": FINGERPRINT_A,
            "X-Admin-Reauthenticate": "mtls",
            "Idempotency-Key": "proposal-1",
        }
        response = self.client.post(
            "/api/v1/admin/control/force-open",
            headers=base,
            json={"tenant_id": "legacy:1", "reason": "approved emergency access"},
        )
        self.assertEqual(403, response.status_code)  # missing CSRF
        self.assertEqual(
            426,
            self.client.post("/api/v1/door/open", json={"device_id": "stolen-id", "reason": "anything"}).status_code,
        )

        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.return_value = None
        cursor.fetchone.return_value = None
        with patch.object(main, "get_db", return_value=connection), patch.object(main, "publish_force_open_to_mqtt", return_value=True) as publish:
            approved = dict(base, **headers)
            proposal = self.client.post(
                "/api/v1/admin/control/force-open",
                headers=approved,
                json={"tenant_id": "legacy:1", "reason": "approved emergency access"},
            )
            self.assertEqual(202, proposal.status_code, proposal.text)
            proposal_id = proposal.json()["approval_id"]
            self.assertFalse(publish.called)
        self.assertEqual(48, len(proposal_id))

    def test_mtls_authentication_is_rate_limited(self) -> None:
        for _ in range(2):
            self.assertEqual(401, self.client.post("/api/v1/admin/sessions").status_code)
        self.assertEqual(429, self.client.post("/api/v1/admin/sessions").status_code)

    def test_two_person_approval_publishes_exactly_once(self) -> None:
        """Persisted names, not obsolete aliases, authorize the approver path."""
        operator_csrf, _ = self._session(FINGERPRINT_A)
        operator_headers = {
            **operator_csrf,
            **self._mtls_headers(FINGERPRINT_A),
            "X-Admin-Reauthenticate": "mtls",
            "Idempotency-Key": "operator-proposal-1",
        }
        proposal_row = {
            "approval_id": "p" * 48,
            "tenant_scope": "legacy:1",
            "proposer_subject": "operator-a",
            "status": "PENDING",
            "expires_at": 4_102_444_800,
        }
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.rowcount = 1
        cursor.fetchone.side_effect = [None, proposal_row]
        with patch.object(main, "get_db", return_value=connection), patch.object(
            main, "publish_force_open_to_mqtt", return_value=True
        ) as publish:
            proposed = self.client.post(
                "/api/v1/admin/control/force-open",
                headers=operator_headers,
                json={"tenant_id": "legacy:1", "reason": "approved emergency access"},
            )
            self.assertEqual(202, proposed.status_code, proposed.text)

            approver_csrf, _ = self._session(FINGERPRINT_B)
            approved = self.client.post(
                "/api/v1/admin/control/force-open/" + proposal_row["approval_id"] + "/approve",
                headers={
                    **approver_csrf,
                    **self._mtls_headers(FINGERPRINT_B),
                    "X-Admin-Reauthenticate": "mtls",
                    "Idempotency-Key": "approver-publish-1",
                },
            )
        self.assertEqual(200, approved.status_code, approved.text)
        self.assertEqual({"status": "published", "approval_id": proposal_row["approval_id"]}, approved.json())
        publish.assert_called_once_with("authorized-control-plane")

    def test_force_open_self_expired_replay_tenant_and_duplicate_publish_are_denied(self) -> None:
        now = 4_102_444_800
        cases = (
            ("self", FINGERPRINT_A, "PENDING", now + 60, "operator-a", 403),
            ("expired", FINGERPRINT_B, "PENDING", now - 1, "operator-a", 404),
            ("replay", FINGERPRINT_B, "PUBLISHED", now + 60, "operator-a", 404),
            ("tenant", FINGERPRINT_C, "PENDING", now + 60, "operator-a", 403),
            ("duplicate-publish", FINGERPRINT_B, "PUBLISHING", now + 60, "operator-a", 404),
        )
        with patch.object(main.time, "time", return_value=now):
            for name, fingerprint, status, expires_at, proposer, expected in cases:
                with self.subTest(name=name):
                    csrf, _ = self._session(fingerprint)
                    connection = MagicMock()
                    cursor = connection.cursor.return_value.__enter__.return_value
                    cursor.fetchone.return_value = {
                        "approval_id": "q" * 48,
                        "tenant_scope": "legacy:1",
                        "proposer_subject": proposer,
                        "status": status,
                        "expires_at": expires_at,
                    }
                    with patch.object(main, "get_db", return_value=connection), patch.object(
                        main, "publish_force_open_to_mqtt", return_value=True
                    ) as publish:
                        response = self.client.post(
                            "/api/v1/admin/control/force-open/" + ("q" * 48) + "/approve",
                            headers={
                                **csrf,
                                **self._mtls_headers(fingerprint),
                                "X-Admin-Reauthenticate": "mtls",
                                "Idempotency-Key": "negative-" + name,
                            },
                        )
                    self.assertEqual(expected, response.status_code, response.text)
                    publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
