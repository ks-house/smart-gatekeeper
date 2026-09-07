import hashlib
import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.diagnostics_read import create_diagnostics_read_router
from backend.app import main
from backend.tests.test_mobile_diagnostics import bundle


class DiagnosticsReadTest(unittest.TestCase):
    def setUp(self):
        self.token = "x" * 43
        self.headers = {"Authorization": "Bearer " + self.token}
        self.db = MagicMock()
        self.cur = self.db.return_value.cursor.return_value.__enter__.return_value
        self.cur.fetchall.return_value = []
        self.cur.fetchone.return_value = None
        self.app = FastAPI()
        self.app.include_router(create_diagnostics_read_router(
            self.db, hashlib.sha256(self.token.encode()).hexdigest(),
        ))
        self.client = TestClient(self.app)

    def test_no_token_invalid_token_or_cookie_never_queries_db(self):
        for headers in ({}, {"Authorization": "Bearer " + "z" * 43},
                        {"Cookie": "sgk_admin_session=" + self.token},
                        {"X-API-KEY": self.token}):
            self.assertEqual(401, self.client.get("/api/v1/diagnostics/bundles", headers=headers).status_code)
        self.db.assert_not_called()

    def test_unconfigured_does_not_allow_anonymous_read(self):
        for digest in ("", "not-a-digest"):
            app = FastAPI()
            app.include_router(create_diagnostics_read_router(self.db, digest))
            self.assertEqual(503, TestClient(app).get("/api/v1/diagnostics/bundles", headers=self.headers).status_code)
        self.db.assert_not_called()

    def test_only_get_and_no_admin_authority(self):
        self.assertEqual(405, self.client.post("/api/v1/diagnostics/bundles", headers=self.headers).status_code)
        self.db.assert_not_called()
        client = TestClient(main.app)
        self.assertEqual(401, client.get("/api/v1/admin/access-events", headers=self.headers).status_code)
        self.assertEqual(401, client.post("/api/v1/admin/sessions/rotate", headers=self.headers).status_code)

    def test_list_is_bounded_parameterized_and_private(self):
        self.cur.fetchall.return_value = [dict(id=i, bundle_ref="a" * 32, created_at_ms=100,
                                              received_at=datetime(2026, 9, 7)) for i in (3, 2)]
        response = self.client.get("/api/v1/diagnostics/bundles?limit=1&before_id=4", headers=self.headers)
        self.assertEqual(200, response.status_code)
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual("3", response.json()["next_before_id"])
        self.assertEqual(1, len(response.json()["bundles"]))
        self.assertEqual((4, 2), self.cur.execute.call_args.args[1])
        self.assertNotIn("credential", response.text)
        self.db.return_value.close.assert_called_once()
        self.assertEqual(422, self.client.get("/api/v1/diagnostics/bundles?limit=101", headers=self.headers).status_code)

    def test_detail_returns_strict_bundle_and_verified_correlation_only(self):
        payload = bundle()
        session = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        payload["sessions"] = [{"state": "SUCCEEDED", "target_session_id": session}]
        self.cur.fetchone.return_value = dict(id=1, payload_json=json.dumps(payload), received_at=datetime(2026, 9, 7))
        self.cur.fetchall.return_value = [dict(session_id=session, event_code="ACCESS_ARMED",
                                             reason_code=None, received_at=datetime(2026, 9, 7))]
        response = self.client.get("/api/v1/diagnostics/bundles/1", headers=self.headers)
        self.assertEqual(200, response.status_code)
        self.assertEqual(session, response.json()["bundle"]["sessions"][0]["target_session_id"])
        self.assertEqual("ACCESS_ARMED", response.json()["target_events"][0]["event_code"])
        self.assertIn("integrity_status='verified'", self.cur.execute.call_args.args[0])
        self.assertFalse(response.json()["target_events_truncated"])
        self.assertNotIn("tenant_id", response.text)

    def test_not_found_corrupt_storage_and_database_error_are_safe(self):
        self.assertEqual(404, self.client.get("/api/v1/diagnostics/bundles/1", headers=self.headers).status_code)
        payload = bundle()
        payload["private_key"] = "must-not-escape"
        self.cur.fetchone.return_value = dict(id=1, payload_json=json.dumps(payload), received_at=datetime(2026, 9, 7))
        response = self.client.get("/api/v1/diagnostics/bundles/1", headers=self.headers)
        self.assertEqual(503, response.status_code)
        self.assertNotIn("must-not-escape", response.text)
        self.db.side_effect = RuntimeError("secret database detail")
        response = self.client.get("/api/v1/diagnostics/bundles", headers=self.headers)
        self.assertEqual(503, response.status_code)
        self.assertNotIn("secret", response.text)

    def test_bounded_rate_limit(self):
        for _ in range(60):
            self.client.get("/api/v1/diagnostics/bundles")
        response = self.client.get("/api/v1/diagnostics/bundles", headers=self.headers)
        self.assertEqual(429, response.status_code)
        self.assertIn("retry-after", response.headers)
        self.db.assert_not_called()
