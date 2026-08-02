from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from backend.app import main


class LegacyAndOtaIndependenceTest(unittest.TestCase):
    def test_authenticated_manual_remote_master_path_remains_distinct_and_functional(self) -> None:
        paths = {route.path for route in main.app.routes}
        self.assertIn("/api/v1/door/open", paths)
        self.assertNotIn("/api/v1/acl/enrollment/challenge", paths)
        with patch.object(main, "GATEKEEPER_API_KEY", "manual-admin-key"), patch.object(
            main, "publish_force_open_to_mqtt", return_value=True
        ) as publish:
            response = main.door_force_open(
                main.ForceOpenRequestSchema(reason="manual_button", device_id=None),
                x_api_key="manual-admin-key",
            )
        body = json.loads(response.body)
        self.assertEqual("force_opened", body["result"])
        self.assertTrue(body["mqtt_published"])
        publish.assert_called_once_with("마스터개방")

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

    def test_disabled_acl_invalid_integer_config_cannot_take_down_legacy_routes(self) -> None:
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
                "from backend.app import main; assert any(r.path == '/api/v1/door/open' for r in main.app.routes)",
            ],
            text=True,
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
                "from backend.app import main; assert any(r.path == '/api/v1/door/open' for r in main.app.routes)",
            ],
            text=True,
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
