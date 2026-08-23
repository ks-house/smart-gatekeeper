import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/setup_ota_content_key.ps1"


class SetupOtaContentKeyTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.source = SCRIPT.read_text(encoding="utf-8")

  def test_requires_windows_dpapi_and_process_github_token(self):
    self.assertIn('$env:OS -ne "Windows_NT"', self.source)
    self.assertIn('$env:GITHUB_TOKEN', self.source)
    self.assertIn('gh" `\n    -Arguments "auth status --hostname github.com"', self.source)
    self.assertIn('ConvertFrom-SecureString -SecureString $secureContentKey', self.source)

  def test_refuses_overwrite_and_repository_local_backup(self):
    self.assertIn("EncryptedBackupPath must be outside the repository.", self.source)
    self.assertIn("EncryptedBackupPath already exists; overwrite is refused.", self.source)
    self.assertIn("Refusing to overwrite existing secrets", self.source)
    self.assertIn('Split-Path -Leaf $resolved) -ne "secrets.h"', self.source)

  def test_generates_dedicated_key_and_never_derives_from_mqtt(self):
    self.assertIn("RandomNumberGenerator", self.source)
    self.assertIn("New-Object byte[] 32", self.source)
    self.assertIn("SECRET_OTA_CONTENT_KEY_HEX", self.source)
    self.assertIn("SECRET_OTA_CONTENT_KEY_ID", self.source)
    self.assertNotIn("MQTT_PASSWORD", self.source)

  def test_secret_values_use_stdin_and_are_not_reported(self):
    self.assertIn('-StandardInput $Value', self.source)
    self.assertNotIn('Write-Output $contentKeyHex', self.source)
    self.assertNotIn('Write-Host $contentKeyHex', self.source)
    self.assertNotIn('Write-Verbose $contentKeyHex', self.source)

  def test_cli_identifiers_are_strictly_validated(self):
    self.assertIn('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$', self.source)
    self.assertIn('^[A-Za-z0-9._-]{1,255}$', self.source)
    self.assertIn('^[A-Za-z0-9._-]{1,64}$', self.source)


if __name__ == "__main__":
  unittest.main()
