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
    def test_force_open_is_admin_dual_control_and_legacy_device_route_is_removed(self) -> None:
        paths = {route.path for route in main.app.routes}
        self.assertIn("/api/v1/admin/control/force-open", paths)
        self.assertIn("/api/v1/admin/control/force-open/{approval_id}/approve", paths)
        self.assertNotIn("/api/v1/door/open", paths)
        self.assertNotIn("/api/v1/acl/enrollment/challenge", paths)
        response = TestClient(main.app).post(
            "/api/v1/door/open", json={"reason": "manual_click", "device_id": "stolen-id"}
        )
        self.assertEqual(404, response.status_code)

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
            "assert '/api/v1/door/open' not in {r.path for r in main.app.routes};"
            "assert '/api/v1/admin/control/force-open' in {r.path for r in main.app.routes};"
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
                "assert '/api/v1/door/open' not in paths; "
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
