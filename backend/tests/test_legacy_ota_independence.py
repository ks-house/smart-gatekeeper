from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app import main


class LegacyAndOtaIndependenceTest(unittest.TestCase):
    def test_authenticated_mobile_button_manual_remote_is_independent_of_relay_gates(self) -> None:
        paths = {route.path for route in main.app.routes}
        self.assertIn("/api/v1/door/open", paths)
        self.assertNotIn("/api/v1/acl/enrollment/challenge", paths)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "name": "Mobile User",
            "unit_number": "101",
            "is_active": True,
        }
        with patch.object(main, "get_db", return_value=connection), patch.object(
            main, "publish_force_open_to_mqtt", return_value=True
        ) as publish, patch.object(
            main, "publish_arm_to_mqtt", side_effect=AssertionError("hands-free path used")
        ) as publish_arm, patch.object(
            main, "_api_key_matches", side_effect=AssertionError("admin path used")
        ):
            response = TestClient(main.app).post(
                "/api/v1/door/open",
                json={"reason": "manual_click", "device_id": "mobile-device-01"},
            )
        body = response.json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("force_opened", body["result"])
        self.assertTrue(body["mqtt_published"])
        publish.assert_called_once_with("Mobile User(101)")
        publish_arm.assert_not_called()
        cursor.execute.assert_called_once()
        self.assertEqual(("MOBILE-DEVICE-01",), cursor.execute.call_args.args[1])
        connection.close.assert_called_once()

    def test_ota_health_config_and_download_routes_do_not_depend_on_acl_feature(self) -> None:
        paths = {route.path for route in main.app.routes}
        self.assertIn("/health", paths)
        self.assertIn("/api/v1/config", paths)
        self.assertIn("/api/v1/download/apk", paths)
        health = json.loads(main.health_check().body)
        config = json.loads(main.get_remote_config().body)
        self.assertEqual("healthy", health["status"])
        self.assertIn("apk_version_url", config)
        self.assertIn("apk_download_url", config)

    @staticmethod
    def _manual_remote_assertion_script() -> str:
        return (
            "import json,sys;"
            "sys.stdout.reconfigure(encoding='utf-8');"
            "sys.stderr.reconfigure(encoding='utf-8');"
            "from backend.app import main;"
            "C=type('C',(),{'__enter__':lambda s:s,'__exit__':lambda s,*a:None,"
            "'execute':lambda s,q,p:None,'fetchone':lambda s:{'name':'Mobile User','unit_number':'101','is_active':True}});"
            "D=type('D',(),{'cursor':lambda s:C(),'close':lambda s:None});"
            "main.get_db=lambda:D();"
            "calls=[];"
            "main.publish_force_open_to_mqtt=lambda label:calls.append(label) or True;"
            "main.publish_arm_to_mqtt=lambda *a:(_ for _ in ()).throw(AssertionError('hands-free path used'));"
            "response=main.door_force_open(main.ForceOpenRequestSchema(reason='manual_click',device_id='mobile-device-01'),x_api_key=None);"
            "body=json.loads(response.body);"
            "assert body['result']=='force_opened';"
            "assert calls==['Mobile User(101)'];"
            "assert any(r.path=='/api/v1/download/apk' for r in main.app.routes)"
        )

    def test_disabled_acl_invalid_integer_config_cannot_take_down_mobile_manual_remote(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "ACL_MANAGEMENT_ENABLED": "false",
                "ACL_SIGNING_KEY_ID": "not-an-integer",
                "ACL_LEASE_SECONDS": "not-an-integer",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                self._manual_remote_assertion_script(),
            ],
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_malformed_signer_input_is_not_reflected_in_logs(self) -> None:
        marker = "DO_NOT_LOG_THIS_SIGNER_VALUE"
        environment = os.environ.copy()
        environment.update(
            {
                "ACL_MANAGEMENT_ENABLED": "true",
                "ACL_LEGACY_REF_HMAC_KEY": "test-hmac",
                "ACL_ENROLLMENT_AUTH_JSON": '{"actor-a":{"tenant_id":"11111111111111111111111111111111","key":"e"}}',
                "ACL_ADMIN_API_KEY": "a",
                "ACL_TARGET_AUTH_JSON": '{"target-a":{"tenant_id":"11111111111111111111111111111111","door_id":"00112233445566778899aabbccddeeff","key":"t"}}',
                "ACL_SIGNING_PRIVATE_SCALAR_HEX": marker,
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                self._manual_remote_assertion_script(),
            ],
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(marker, result.stdout + result.stderr)

    def test_cross_tenant_duplicate_target_door_config_fails_closed(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "ACL_MANAGEMENT_ENABLED": "true",
                "ACL_LEGACY_REF_HMAC_KEY": "test-hmac",
                "ACL_ENROLLMENT_AUTH_JSON": '{"actor-a":{"tenant_id":"11111111111111111111111111111111","key":"e"}}',
                "ACL_ADMIN_API_KEY": "a",
                "ACL_TARGET_AUTH_JSON": (
                    '{"target-a":{"tenant_id":"11111111111111111111111111111111",'
                    '"door_id":"00112233445566778899aabbccddeeff","key":"ta"},'
                    '"target-b":{"tenant_id":"22222222222222222222222222222222",'
                    '"door_id":"00112233445566778899aabbccddeeff","key":"tb"}}'
                ),
                "ACL_SIGNING_PRIVATE_SCALAR_HEX": "2",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from backend.app import main; paths={r.path for r in main.app.routes}; "
                "assert '/api/v1/door/open' in paths; "
                "assert '/api/v1/acl/enrollment/challenge' not in paths",
            ],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
