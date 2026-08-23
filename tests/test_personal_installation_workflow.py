import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "personal_installation_firmware.yml"


class PersonalInstallationWorkflowTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.raw = WORKFLOW.read_text(encoding="utf-8")
    cls.data = yaml.safe_load(cls.raw)
    cls.job = cls.data["jobs"]["build"]

  def test_dispatch_is_main_only_and_environment_protected(self):
    self.assertEqual(self.job["environment"], "production")
    self.assertEqual(self.job["if"], "github.ref == 'refs/heads/main'")
    self.assertEqual(self.data["permissions"], {"contents": "read"})

  def test_actual_connectivity_and_recovery_secrets_are_required(self):
    job_text = str(self.job)
    for name in (
        "SECRET_WIFI_SSID", "SECRET_WIFI_PASSWORD", "SECRET_MQTT_HOST",
        "SECRET_MQTT_USER", "SECRET_MQTT_PASSWORD",
        "SECRET_TARGET_TENANT_ID", "SECRET_TARGET_DOOR_ID",
        "SECRET_COMMAND_SIGNER_PUBLIC_KEY_HEX", "SECRET_OTA_VERSION_URL",
        "SECRET_OTA_FIRMWARE_URL", "SECRET_LOCAL_RECOVERY_AP_PASSWORD",
        "SECRET_LOCAL_RECOVERY_USER", "SECRET_LOCAL_RECOVERY_PASSWORD",
        "SECRET_OTA_CONTENT_KEY_HEX", "SECRET_OTA_CONTENT_KEY_ID",
    ):
      self.assertIn(name, job_text)
    self.assertIn('test "$SECRET_WIFI_SSID" != "YOUR_WIFI_SSID"', self.raw)
    self.assertNotIn('SECRET_MQTT_USER" =~', self.raw)

  def test_only_encrypted_one_day_bundle_is_uploaded(self):
    upload = next(
        step for step in self.job["steps"]
        if step.get("name") == "Upload encrypted one-day bundle"
    )
    self.assertEqual(upload["with"]["path"], "delivery/*.7z")
    self.assertEqual(upload["with"]["retention-days"], 1)
    self.assertIn('-mhe=on -p"$INSTALL_BUNDLE_PASSWORD"', self.raw)

  def test_encrypted_bundle_contains_recoverable_provisioned_header(self):
    self.assertIn("cp include/secrets.h dist/provisioned-secrets.h", self.raw)
    self.assertIn(
        "firmware.factory.bin provisioned-secrets.h > SHA256SUMS", self.raw
    )

  def test_commercial_release_evidence_is_not_modified_or_claimed(self):
    self.assertNotIn("release-evidence.json", self.raw)
    self.assertNotIn("Deploy to Synology NAS", self.raw)
    self.assertIn("production-signed OTA manifest", self.raw)
    self.assertIn("target-content-encrypt", self.raw)
    self.assertIn("gatekeeper-firmware.sgkenc", self.raw)
    self.assertIn("--plaintext-artifact dist/gatekeeper-firmware.bin", self.raw)
    self.assertIn("--expected-encryption-key-id", self.raw)


if __name__ == "__main__":
  unittest.main()
