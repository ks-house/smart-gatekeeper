"""Contract tests for the single-owner main-push mobile OTA publisher."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build_app.yml"
AUTO_JOB = "publish_personal_mobile_ota"


class PersonalMobileAutoDeployTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.source = WORKFLOW.read_text(encoding="utf-8")
    cls.workflow = yaml.load(cls.source, Loader=yaml.BaseLoader)
    cls.jobs = cls.workflow["jobs"]
    cls.auto_job = cls.jobs[AUTO_JOB]
    cls.auto_source = cls.source.split(f"  {AUTO_JOB}:\n", 1)[1]

  def test_every_main_push_runs_the_personal_publisher(self) -> None:
    push = self.workflow["on"]["push"]
    self.assertEqual(push["branches"], ["main"])
    self.assertNotIn("paths", push)
    self.assertEqual(self.auto_job["needs"], "build_apk")
    self.assertEqual(
        self.auto_job["if"],
        "github.event_name == 'push' && github.ref == 'refs/heads/main'",
    )
    self.assertEqual(
        self.auto_job["concurrency"],
        {
            "group": "smart-gatekeeper-personal-mobile-ota-main",
            "cancel-in-progress": "false",
        },
    )
    self.assertNotIn("environment", self.auto_job)

  def test_repository_mobile_keys_cannot_be_shadowed_by_target_environment(self) -> None:
    self.assertNotIn("environment:", self.auto_source)
    for secret in (
        "OTA_SIGNING_PRIVATE_KEY_HEX",
        "OTA_SIGNING_PUBLIC_KEY_HEX",
        "OTA_SIGNING_KEY_ID",
        "ANDROID_KEYSTORE_BASE64",
        "ANDROID_KEYSTORE_PASSWORD",
        "ANDROID_KEY_ALIAS",
    ):
      self.assertIn(f"secrets.{secret}", self.auto_source)
    self.assertIn("personal-legacy-target-20260812-1", self.auto_source)
    self.assertIn(
        "87d8b43a994f1021feca0d7079658f02bee2eb2f5711e67b12d450f841af08c5",
        self.auto_source,
    )

  def test_android_update_identity_is_pinned_before_manifest_creation(self) -> None:
    self.assertIn(
        "8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0",
        self.auto_source,
    )
    self.assertIn('PACKAGE_NAME" = "com.kshouse.gatekeeper_app', self.auto_source)
    self.assertIn("((10#$GITHUB_RUN_NUMBER > 141))", self.auto_source)
    self.assertIn("flutter build apk --release", self.auto_source)
    self.assertIn("--build-number=\"$GITHUB_RUN_NUMBER\"", self.auto_source)

  def test_signed_manifest_is_bound_to_exact_main_artifact(self) -> None:
    for fragment in (
        'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
        "mobile-manifest-create",
        "mobile-manifest-verify",
        '--artifact dist/ks-house-gatekeeper.apk',
        '--output dist/version.json',
        '--commit "$GITHUB_SHA"',
        '--private-key-env MOBILE_UPDATE_PRIVATE_KEY_HEX',
        '--expected-package-name "com.kshouse.gatekeeper_app"',
    ):
      self.assertIn(fragment, self.auto_source)
    self.assertNotIn('echo "$MOBILE_UPDATE_PRIVATE_KEY_HEX"', self.auto_source)
    self.assertNotIn('echo "$KEYSTORE_BASE64"', self.auto_source)

  def test_primary_and_fallback_use_the_shared_atomic_publisher(self) -> None:
    for fragment in (
        "Prepare strict NAS host identity for personal mobile OTA",
        "OTA_NAS_KNOWN_HOSTS_FILE",
        "OTA_NAS_HOST_KEY_MODE",
        "repository-secret-pinned",
        "runtime-keyscan-unpinned",
        "mobile-sftp-publish",
        "MOBILE_PUBLIC_KEY_HEX",
        "NAS_APK_TARGET_DIR",
        "NAS_APK_FALLBACK_TARGET_DIR",
        '--artifact dist/ks-house-gatekeeper.apk',
        '--manifest dist/version.json',
        '--expected-version "$FULL_VERSION"',
        '--expected-commit "$GITHUB_SHA"',
        '--expected-build-number "$GITHUB_RUN_NUMBER"',
        '--expected-package-name "com.kshouse.gatekeeper_app"',
        '--run-attempt "$GITHUB_RUN_ATTEMPT"',
        "evidence/personal-mobile-ota-publication.json",
        '--apkanalyzer "$APKANALYZER"',
        '--apksigner "$APKSIGNER"',
    ):
      self.assertIn(fragment, self.auto_source)
    self.assertNotIn("sshpass", self.auto_source)
    self.assertNotIn("sftp ", self.auto_source)

  def test_publication_evidence_is_preserved_without_secret_material(self) -> None:
    self.assertIn(
        "personal-mobile-ota-evidence-${{ github.sha }}",
        self.auto_source,
    )
    self.assertIn("retention-days: 30", self.auto_source)
    self.assertNotIn('echo "$NAS_PASSWORD"', self.auto_source)
    self.assertNotIn('echo "$MOBILE_PUBLIC_KEY_HEX"', self.auto_source)

  def test_public_endpoints_must_serve_both_exact_copies(self) -> None:
    for fragment in (
        'fetch_exact "$APK_VERSION_URL"',
        'fetch_exact "$APK_FALLBACK_VERSION_URL"',
        'fetch_exact "$APK_DOWNLOAD_URL"',
        'fetch_exact "$APK_FALLBACK_DOWNLOAD_URL"',
        'cmp "$expected" "$destination"',
    ):
      self.assertIn(fragment, self.auto_source)

  def test_commercial_release_gate_remains_separate_and_fail_closed(self) -> None:
    commercial = self.jobs["release_to_production"]
    self.assertEqual(commercial["environment"], "production")
    self.assertEqual(
        commercial["if"].replace("\n", " ").split(),
        (
            "github.event_name == 'workflow_dispatch' && "
            "inputs.release_target == 'production' && "
            "github.ref == 'refs/heads/main'"
        ).split(),
    )
    commercial_steps = "\n".join(
        str(step.get("name", "")) for step in commercial["steps"]
    )
    self.assertIn("Enforce OTA production release evidence", commercial_steps)
    self.assertIn("ota/release-evidence.json", self.source)


if __name__ == "__main__":
  unittest.main()
