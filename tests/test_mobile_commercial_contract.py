from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MobileCommercialContractTest(unittest.TestCase):
    def test_web_shell_does_not_send_device_id_only_control_or_enrolment(self) -> None:
        page = (ROOT / "backend" / "app" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("fetch('/api/v1/door/open'", page)
        self.assertNotIn("fetch('/api/v1/user/request'", page)
        self.assertNotIn("fetch(`/api/v1/user/me?device_id=", page)
        self.assertIn("보유 증명 자격증명이 배포되기 전에는 원격 문 열기를 사용할 수 없습니다", page)
        self.assertIn('document.getElementById(\'btnOpen\').disabled = true', page)

    def test_updater_rejects_unsigned_download_paths(self) -> None:
        updater = (ROOT / "gatekeeper_app" / "lib" / "services" / "update_checker.dart").read_text(
            encoding="utf-8"
        )
        self.assertIn("NO_VERIFIED_MANIFEST", updater)
        self.assertIn("UNSIGNED_DOWNLOAD_URL", updater)
        self.assertNotIn("downloadUrlFromEnv", updater)
        self.assertIn("SignedUpdateManifest.fromJsonString(response.body)", updater)


if __name__ == "__main__":
    unittest.main()
