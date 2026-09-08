import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
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

    def event(self, row_id=3):
        return dict(
            id=row_id, event_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            session_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            source_boot_id="boot-1", source_boot_count=9007199254740993,
            source_sequence=9007199254740994, event_attempt=1,
            event_code="ACCESS_ARMED", event_stage="AUTH", event_outcome="SUCCESS",
            reason_code=None, event_path="LOCAL", event_transport="BLE",
            distance_mm=None, duration_ms=250, relay_hold_ms=None, monotonic_ms=9007199254740996,
            clock_quality="UNSYNCED", collector_target_id="gatekeeper",
            credential_ref="a" * 32, integrity_status="verified",
            received_at=datetime(2026, 9, 7, 4, 8, 9, 123000),
            actor_name="must-not-escape", integrity_tag="must-not-escape",
        )

    def test_events_share_token_but_never_allow_writes(self):
        route = "/api/v1/diagnostics/access-events"
        for headers in ({}, {"Authorization": "Bearer " + "z" * 43},
                        {"Cookie": "sgk_admin_session=" + self.token},
                        {"X-API-KEY": self.token}):
            self.assertEqual(401, self.client.get(route, headers=headers).status_code)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(405, self.client.request(method, route, headers=self.headers).status_code)
        self.db.assert_not_called()
        self.assertEqual(200, self.client.get(route, headers=self.headers).status_code)
        app = FastAPI()
        app.include_router(create_diagnostics_read_router(self.db, ""))
        self.db.reset_mock()
        self.assertEqual(503, TestClient(app).get(route, headers=self.headers).status_code)
        self.db.assert_not_called()

    def test_events_default_window_empty_result_does_not_query_bundles(self):
        before = datetime.now(timezone.utc)
        response = self.client.get("/api/v1/diagnostics/access-events", headers=self.headers)
        after = datetime.now(timezone.utc)
        self.assertEqual(200, response.status_code)
        self.assertEqual("no-store", response.headers["cache-control"])
        data = response.json()
        start = datetime.fromisoformat(data["since"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(data["until"].replace("Z", "+00:00"))
        self.assertLessEqual(before, end)
        self.assertLessEqual(end, after)
        self.assertEqual(timedelta(hours=24), end - start)
        self.assertEqual([], data["events"])
        self.assertIsNone(data["next_before_id"])
        self.assertEqual("received_at", data["time_basis"])
        sql, args = self.cur.execute.call_args.args
        self.assertIn("integrity_status='verified'", sql)
        self.assertNotIn("mobile_diagnostic_bundles", sql)
        self.assertIn("received_at >= %s AND received_at < %s", sql)
        self.assertEqual((start.replace(tzinfo=None), end.replace(tzinfo=None), 101), args)

    def test_events_filters_are_parameterized_and_projection_is_closed(self):
        self.cur.fetchall.return_value = [self.event(9007199254740995), self.event(9007199254740994)]
        params = dict(since="2026-09-07T00:00:00+09:00", until="2026-09-08T00:00:00+09:00",
                      limit=1, before_id=9007199254740996, target_id="gatekeeper",
                      session_id=self.event()["session_id"], boot_count=9007199254740993,
                      event_code="ACCESS_ARMED")
        response = self.client.get("/api/v1/diagnostics/access-events", params=params, headers=self.headers)
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("2026-09-06T15:00:00Z", data["since"])
        self.assertEqual("2026-09-07T15:00:00Z", data["until"])
        self.assertEqual("9007199254740995", data["next_before_id"])
        self.assertEqual(1, len(data["events"]))
        event = data["events"][0]
        self.assertEqual("9007199254740993", event["source_boot_count"])
        self.assertEqual("9007199254740994", event["source_sequence"])
        self.assertEqual("9007199254740996", event["monotonic_ms"])
        self.assertEqual("gatekeeper", event["target_id"])
        self.assertEqual("2026-09-07T04:08:09.123000Z", event["received_at"])
        self.assertNotIn("collector_target_id", event)
        self.assertNotIn("must-not-escape", response.text)
        sql, args = self.cur.execute.call_args.args
        self.assertIn("ORDER BY id DESC LIMIT %s", sql)
        self.assertNotIn("gatekeeper", sql)
        self.assertNotIn("integrity_tag", sql)
        self.assertEqual((datetime(2026, 9, 6, 15), datetime(2026, 9, 7, 15),
                          "gatekeeper", self.event()["session_id"], 9007199254740993,
                          "ACCESS_ARMED", 9007199254740996, 2), args)
        self.db.return_value.close.assert_called_once()
        # Same receipt timestamp still pages by unique ID without an offset.
        params.update(since=data["since"], until=data["until"], before_id=data["next_before_id"])
        self.cur.fetchall.return_value = [self.event(9007199254740994)]
        page2 = self.client.get("/api/v1/diagnostics/access-events", params=params, headers=self.headers).json()
        self.assertIsNone(page2["next_before_id"])
        self.assertNotEqual(event["id"], page2["events"][0]["id"])
        self.assertEqual(9007199254740995, self.cur.execute.call_args.args[1][-2])

    def test_events_invalid_windows_and_filters_never_query_db(self):
        window = dict(since="2026-09-07T00:00:00Z", until="2026-09-08T00:00:00Z")
        for invalid in (
            {"since": "2026-09-07T00:00:00"}, {"since": "not-a-date"},
            {"since": "2026-09-08T00:00:00Z"}, {"since": "2026-09-09T00:00:00Z"},
            {"since": "2026-08-01T00:00:00Z"}, {"since": "0001-01-01T00:00:00+09:00"},
            {"until": "9999-12-31T00:00:00Z"}, {"limit": 0}, {"limit": 101},
            {"before_id": 0}, {"before_id": 18446744073709551616},
            {"boot_count": -1}, {"target_id": "x' OR 1=1 --"},
            {"session_id": "not-a-uuid"}, {"event_code": "x' OR 1=1 --"},
            {"since": "z" * 65},
        ):
            with self.subTest(invalid=invalid):
                response = self.client.get("/api/v1/diagnostics/access-events",
                                           params={**window, **invalid}, headers=self.headers)
                self.assertEqual(422, response.status_code)
        self.db.assert_not_called()
        response = self.client.get("/api/v1/diagnostics/access-events", headers=self.headers,
                                   params={**window, "since": "2026-08-08T00:00:00Z"})
        self.assertEqual(200, response.status_code)  # Exactly 31 days is allowed.

    def test_events_storage_error_is_generic_and_closes_connection(self):
        self.cur.execute.side_effect = RuntimeError("secret SQL detail")
        response = self.client.get("/api/v1/diagnostics/access-events", headers=self.headers)
        self.assertEqual(503, response.status_code)
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertNotIn("secret", response.text)
        self.db.return_value.close.assert_called_once()

    def test_events_share_bundle_rate_limit(self):
        for _ in range(60):
            self.client.get("/api/v1/diagnostics/bundles")
        response = self.client.get("/api/v1/diagnostics/access-events", headers=self.headers)
        self.assertEqual(429, response.status_code)
        self.db.assert_not_called()
