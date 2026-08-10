import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup_ota_signing_secrets.ps1"


class SetupOtaSigningSecretsContractTest(unittest.TestCase):
  def test_script_generates_exact_raw_ed25519_material(self):
    source = SCRIPT.read_text(encoding="utf-8")
    for fragment in (
        "Ed25519PrivateKey.generate()",
        "serialization.Encoding.Raw",
        "serialization.PrivateFormat.Raw",
        "serialization.PublicFormat.Raw",
        '"^[0-9a-f]{64}$"',
        "hashlib.sha256(public_key).hexdigest()",
    ):
      self.assertIn(fragment, source)

  def test_secret_values_use_stdin_and_are_never_persisted_as_windows_env(self):
    source = SCRIPT.read_text(encoding="utf-8")
    for secret_name in (
        "OTA_SIGNING_PRIVATE_KEY_HEX",
        "OTA_SIGNING_PUBLIC_KEY_HEX",
        "OTA_SIGNING_KEY_ID",
    ):
      self.assertIn(secret_name, source)
      for workflow in ("deploy.yml", "build_app.yml"):
        workflow_source = (
            ROOT / ".github" / "workflows" / workflow
        ).read_text(encoding="utf-8")
        self.assertIn(f"secrets.{secret_name}", workflow_source)

    self.assertIn("RedirectStandardInput", source)
    self.assertIn("StandardInput.Write($StandardInput)", source)
    self.assertNotIn("--body", source)
    self.assertNotIn("SetEnvironmentVariable", source)
    self.assertNotRegex(
        source,
        r"Write-(?:Host|Output).*(?:privateSeed|private_seed_hex)",
    )

  def test_actual_registration_is_fail_closed(self):
    source = SCRIPT.read_text(encoding="utf-8")
    for fragment in (
        'if ($env:OS -ne "Windows_NT")',
        'if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN))',
        '"auth status --hostname github.com"',
        '"secret list --env $Environment --repo $Repository --json name"',
        "Refusing to overwrite existing Environment Secrets",
        "EncryptedBackupPath must be outside the repository",
        "EncryptedBackupPath already exists",
        "EncryptedBackupPath parent directory must already exist",
        "ConvertFrom-SecureString",
        'protection = "windows-dpapi-current-user"',
        "UTF8Encoding]::new($false)",
        "$PSCmdlet.ShouldProcess",
        "ConvertFrom-GitHubSecretListJson",
        'ConvertFrom-GitHubSecretListJson -Json "[]"',
        "foreach ($item in @($parsed))",
        'Properties["name"]',
    ):
      self.assertIn(fragment, source)

  def test_validate_only_generates_public_identity_without_github_or_backup(self):
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
      self.skipTest("PowerShell is unavailable")

    environment = os.environ.copy()
    environment.pop("GITHUB_TOKEN", None)
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-KeyId",
            "ota-contract-test-v1",
            "-ValidateOnly",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("OTA signing key generation validation passed.", result.stdout)
    self.assertNotIn("parser compatibility validation failed", result.stdout)
    self.assertIn("No GitHub secret or backup file was created.", result.stdout)
    self.assertRegex(result.stdout, r"Public key: [0-9a-f]{64}\n")
    self.assertRegex(result.stdout, r"Public key SHA-256: [0-9a-f]{64}\n")
    self.assertNotRegex(result.stdout, r"Private|private|seed")

  def test_script_is_strict_utf8_lf_without_bom(self):
    data = SCRIPT.read_bytes()
    self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
    self.assertNotIn(b"\r\n", data)
    data.decode("utf-8", errors="strict")


if __name__ == "__main__":
  unittest.main()
