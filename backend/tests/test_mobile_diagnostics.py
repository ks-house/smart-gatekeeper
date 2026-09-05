from __future__ import annotations

import unittest
import hashlib
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pymysql

from backend.app.acl_api import AclApiConfig, create_acl_router
from backend.app import main
from backend.app.mobile_diagnostics import MobileDiagnosticBundle, classify_bundle


def bundle() -> dict:
    return {
        "schema": "sgk-mobile-support-v2",
        "bundle_ref": "a" * 32,
        "created_at": "2026-09-05T11:00:00Z",
        "app": {"version": "2.1.0", "build": "451"},
        "identity": {
            "enrollment_state": "approved",
            "access_ready": True,
            "door_count": 1,
            "target_synced": True,
            "acl_version": 1340,
        },
        "native": {"healthy": True, "stage": "WAITING"},
        "field_test": None,
        "sessions": [],
        "wake_events": [],
    }


class FakeService:
    def personal_mobile_activity(self, tenant_id, credential_id, public_key):
        if credential_id != "1" * 32 or public_key != "04" + "2" * 128:
            raise PermissionError("credential identity mismatch")
        return {"events": []}


class MobileDiagnosticsTest(unittest.TestCase):
    def test_strict_contract_rejects_unknown_and_secret_fields(self) -> None:
        value = bundle()
        value["token"] = "must-not-be-accepted"
        with self.assertRaises(ValidationError):
            MobileDiagnosticBundle.model_validate(value)

    def test_classifier_names_first_unobserved_stage(self) -> None:
        self.assertEqual(
            "PHONE_WAKE_NOT_OBSERVED",
            classify_bundle(bundle(), [])["first_missing"],
        )
        value = bundle()
        value["wake_events"] = [{"success": True}]
        value["sessions"] = [
            {
                "state": "SUCCEEDED",
                "target_session_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            }
        ]
        self.assertEqual(
            "BACKEND_INGEST_NOT_OBSERVED",
            classify_bundle(value, [])["first_missing"],
        )
        events = [
            {
                "session_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                "event_code": "ACCESS_SESSION_COMPLETED",
            }
        ]
        self.assertEqual(
            "DOOR_MOVEMENT_UNCONFIRMED",
            classify_bundle(value, events)["first_missing"],
        )

    def test_classifier_covers_each_cross_layer_boundary(self) -> None:
        value = bundle()
        value["wake_events"] = [{"success": True}]
        self.assertEqual(
            "ANDROID_DISPATCH_NOT_OBSERVED",
            classify_bundle(value, [])["first_missing"],
        )
        value["sessions"] = [{"state": "FAILED", "reason_code": "GATT_DISCONNECTED"}]
        self.assertEqual(
            "GATT_DISCONNECTED",
            classify_bundle(value, [])["first_missing"],
        )
        session_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        value["sessions"] = [{"state": "SUCCEEDED", "target_session_id": session_id}]
        expected = [
            ("ACCESS_PROOF_REQUESTED", "TARGET_RESULT_NOT_OBSERVED"),
            ("ACCESS_PROOF_VERIFIED", "TARGET_FSM_ARM_NOT_OBSERVED"),
            ("ACCESS_ARMED", "SENSOR_TRIGGER_NOT_OBSERVED"),
            ("ACCESS_SENSOR_DETECTED", "RELAY_TRANSITION_NOT_OBSERVED"),
            ("ACCESS_RELAY_OFF", "TARGET_TERMINAL_NOT_OBSERVED"),
        ]
        events = []
        for event_code, first_missing in expected:
            events.append({"session_id": session_id, "event_code": event_code})
            self.assertEqual(
                first_missing,
                classify_bundle(value, events)["first_missing"],
            )

    def test_classifier_uses_live_or_previous_target_breadcrumb_without_inference(self) -> None:
        value = bundle()
        value["wake_events"] = [{"success": True}]
        session_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        value["sessions"] = [{"state": "SUCCEEDED", "target_session_id": session_id}]
        current = {
            "gatt_last_session_id": session_id,
            "gatt_last_stage": "RESULT_INDICATED",
            "previous_access_valid": False,
        }
        self.assertEqual(
            {
                "last_stage": "RESULT_INDICATED",
                "first_missing": "BACKEND_INGEST_NOT_OBSERVED",
            },
            classify_bundle(value, [], target_controller=current),
        )
        previous = {
            "gatt_last_session_id": None,
            "gatt_last_stage": "BOOTING",
            "previous_access_valid": True,
            "previous_access_session_id": session_id,
        }
        self.assertEqual(
            "TARGET_RESET_BREADCRUMB",
            classify_bundle(value, [], target_controller=previous)["last_stage"],
        )

    def test_active_marker_waits_until_window_closes_before_no_wake(self) -> None:
        value = bundle()
        value["field_test"] = {
            "ref": "1" * 16,
            "created_at": "2026-09-05T11:00:00Z",
            "expires_at": "2026-09-05T11:10:00Z",
            "active": True,
        }
        self.assertEqual(
            "FIELD_WINDOW_OPEN",
            classify_bundle(value, [], now_ms=1788606300000)["first_missing"],
        )
        self.assertEqual(
            "PHONE_WAKE_NOT_OBSERVED",
            classify_bundle(value, [], now_ms=1788606700000)["first_missing"],
        )

    def test_personal_upload_is_authenticated_and_idempotency_is_delegated(self) -> None:
        captured = []
        app = FastAPI()
        app.include_router(
            create_acl_router(
                FakeService(),
                AclApiConfig(
                    enabled=True,
                    enrollment_credentials={},
                    admin_key="unused",
                    target_credentials={},
                    personal_enabled=True,
                    personal_api_key="mobile-key",
                    personal_tenant_id="a" * 32,
                    personal_door_id="b" * 32,
                    personal_diagnostics_ingest=lambda tenant, credential, payload: (
                        captured.append((tenant, credential, payload))
                        or {
                            "accepted": True,
                            "bundle_ref": payload["bundle_ref"],
                            "deduplicated": False,
                        }
                    ),
                ),
            )
        )
        request = {
            "device_id": "DEV-TEST-1234",
            "credential_id": "1" * 32,
            "public_key_sec1": "04" + "2" * 128,
            "bundle": bundle(),
        }
        client = TestClient(app)
        self.assertEqual(
            401,
            client.post("/api/v1/acl/personal/diagnostics", json=request).status_code,
        )
        response = client.post(
            "/api/v1/acl/personal/diagnostics",
            json=request,
            headers={"X-API-KEY": "mobile-key"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("a" * 32, response.json()["bundle_ref"])
        self.assertEqual(1, len(captured))

    def test_admin_projection_keeps_physical_result_explicitly_unconfirmed(self) -> None:
        value = bundle()
        session_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        value["wake_events"] = [{"success": True}]
        value["sessions"] = [
            {"state": "SUCCEEDED", "target_session_id": session_id}
        ]
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [
                {
                    "credential_ref": "opaque-credential",
                    "bundle_ref": "a" * 32,
                    "created_at_ms": 1788606000000,
                    "payload_json": value,
                    "received_at": datetime(2026, 9, 5, 11),
                }
            ],
            [],
            [
                {
                    "session_id": session_id,
                    "event_code": "ACCESS_SESSION_COMPLETED",
                    "reason_code": "ACCESS_GRANTED",
                }
            ],
        ]
        with (
            patch.object(main, "_admin_principal"),
            patch.object(main, "get_db", return_value=connection),
            patch.object(
                main._target_gate_states, "live_evidence", return_value=None
            ),
        ):
            response = main.get_diagnostic_attempts_admin(MagicMock(), limit=30)
        attempt = response["attempts"][0]
        self.assertEqual(
            "DOOR_MOVEMENT_UNCONFIRMED",
            attempt["classification"]["first_missing"],
        )
        self.assertEqual({"fresh": False}, attempt["target_controller"])

    def test_storage_accepts_only_byte_identical_duplicate_bundle(self) -> None:
        value = bundle()
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        connection = MagicMock()
        insert_context = MagicMock()
        insert_cursor = insert_context.__enter__.return_value
        insert_cursor.execute.side_effect = pymysql.err.IntegrityError(
            1062, "duplicate"
        )
        lookup_context = MagicMock()
        lookup_cursor = lookup_context.__enter__.return_value
        lookup_cursor.fetchone.return_value = {"payload_sha256": digest}
        connection.cursor.side_effect = [insert_context, lookup_context]
        with (
            patch.object(main, "get_db", return_value=connection),
            patch.object(main, "_ops_hmac_key", b"o" * 32),
        ):
            result = main._store_mobile_diagnostics(
                "a" * 32, "1" * 32, value
            )
        self.assertTrue(result["accepted"])
        self.assertTrue(result["deduplicated"])
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
        self.assertNotIn("INSERT IGNORE", insert_cursor.execute.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
