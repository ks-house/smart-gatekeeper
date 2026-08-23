"""Contract tests for the single-owner exact-main mobile OTA publisher."""

from pathlib import Path
import re
import unittest

import yaml

from scripts import ota_contract_gate as gate


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build_app.yml"
UNSIGNED_JOB = "build_personal_mobile_ota_unsigned"
AUTO_JOB = "publish_personal_mobile_ota"


class PersonalMobileAutoDeployTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.source = WORKFLOW.read_text(encoding="utf-8")
    cls.workflow = yaml.load(cls.source, Loader=yaml.BaseLoader)
    cls.jobs = cls.workflow["jobs"]
    cls.unsigned_job = cls.jobs[UNSIGNED_JOB]
    cls.auto_job = cls.jobs[AUTO_JOB]
    unsigned_tail = cls.source.split(f"  {UNSIGNED_JOB}:\n", 1)[1]
    cls.unsigned_source, cls.auto_source = unsigned_tail.split(f"  {AUTO_JOB}:\n", 1)

  def test_every_main_push_and_canary_dispatch_run_the_personal_publisher(self) -> None:
    push = self.workflow["on"]["push"]
    self.assertEqual(push["branches"], ["main"])
    self.assertNotIn("paths", push)
    self.assertEqual(self.unsigned_job["needs"], "build_apk")
    self.assertEqual(self.auto_job["needs"], UNSIGNED_JOB)
    self.assertEqual(
        " ".join(self.auto_job["if"].split()),
        "github.ref == 'refs/heads/main' && (github.event_name == 'push' || "
        "(github.event_name == 'workflow_dispatch' && inputs.release_target == 'canary'))",
    )
    self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.auto_source)
    self.assertEqual(
        self.auto_job["concurrency"],
        {
            "group": "smart-gatekeeper-personal-mobile-ota-main",
            "cancel-in-progress": "false",
        },
    )
    self.assertEqual(self.auto_job["environment"], "personal-auto-ota")
    self.assertNotIn("environment", self.unsigned_job)

  def test_repository_mobile_keys_cannot_be_shadowed_by_target_environment(self) -> None:
    self.assertIn("environment: personal-auto-ota", self.auto_source)
    for secret in (
        "MOBILE_OTA_SIGNING_PRIVATE_KEY_HEX",
        "MOBILE_OTA_SIGNING_PUBLIC_KEY_HEX",
        "MOBILE_OTA_SIGNING_KEY_ID",
        "ANDROID_KEYSTORE_BASE64",
        "ANDROID_KEYSTORE_PASSWORD",
        "ANDROID_KEY_ALIAS",
    ):
      self.assertIn(f"secrets.{secret}", self.auto_source)
    self.assertNotIn("${{ secrets.OTA_SIGNING_", self.auto_source)
    self.assertIn("personal-legacy-target-20260812-1", self.auto_source)
    self.assertIn(
        "87d8b43a994f1021feca0d7079658f02bee2eb2f5711e67b12d450f841af08c5",
        self.auto_source,
    )

  def test_unsigned_producer_receives_only_apk_embedded_inputs(self) -> None:
    expected = {
        "SECRET_APK_VERSION_URL",
        "SECRET_APK_FALLBACK_VERSION_URL",
        "OTA_SIGNING_KEY_ID",
        "OTA_SIGNING_PUBLIC_KEY_HEX",
        "GATEKEEPER_API_KEY",
    }
    self.assertEqual(
        set(re.findall(r"secrets\.([A-Z0-9_]+)", self.unsigned_source)),
        expected,
    )
    for forbidden in (
        "ANDROID_KEYSTORE_BASE64",
        "ANDROID_KEYSTORE_PASSWORD",
        "OTA_SIGNING_PRIVATE_KEY_HEX",
        "NAS_PASSWORD",
        "NAS_KNOWN_HOSTS",
        "mobile-manifest-create",
        "mobile-sftp-publish",
        "apksigner",
        "key.properties",
    ):
      self.assertNotIn(forbidden, self.unsigned_source)
    self.assertIn("SGK_UNSIGNED_CI_RELEASE=1", self.unsigned_source)

  def test_privileged_publisher_is_sparse_and_never_executes_candidate_build_code(self) -> None:
    self.assertIn("sparse-checkout:", self.auto_source)
    for path in (
        "scripts/ota_contract_gate.py",
        "ota/requirements.lock",
        "ota/schemas/mobile-manifest.schema.json",
    ):
      self.assertIn(path, self.auto_source)
    setup_prefix = self.auto_source.split(
        "Align and sign exact personal mobile APK", 1
    )[0]
    for forbidden in ("flutter", "gradle", "unittest", "pytest", "ota_contract_gate.py contract"):
      self.assertNotIn(forbidden, setup_prefix.lower())
    self.assertIn(
        "python -I -m pip install --no-cache-dir --require-hashes",
        self.auto_source,
    )
    self.assertNotIn("cache: pip", self.auto_source)
    self.assertNotIn("${{ secrets.", setup_prefix)

  def test_unsigned_artifact_and_toolchain_are_verified_before_any_secret(self) -> None:
    sign_offset = self.auto_source.index("Align and sign exact personal mobile APK")
    secret_free_prefix = self.auto_source[:sign_offset]
    for fragment in (
        "find unsigned-dist -mindepth 1 -maxdepth 1 -print0",
        'test "${#DOWNLOADED_ENTRIES[@]}" -eq 1',
        "UNSIGNED_APK_SIZE >= 1048576",
        "UNSIGNED_APK_SIZE <= 209715200",
        'UNSIGNED_APK_SHA256="$(sha256sum',
        "Install verified personal mobile signing toolchain",
    ):
      self.assertIn(fragment, secret_free_prefix)
    self.assertNotIn("${{ secrets.", secret_free_prefix)
    self.assertNotIn("-type f", secret_free_prefix)

  def test_personal_mobile_toolchain_uses_exact_verified_archives(self) -> None:
    pinned = {
        "OpenJDK17U-jdk_x64_linux_hotspot_17.0.16_8.tar.gz": (
            "192062472",
            "166774efcf0f722f2ee18eba0039de2d685b350ee14d7b69e6f83437dafd2af1",
        ),
        "build-tools_r36_linux.zip": (
            "63737259",
            "5d9ac77fb6ff43d9da518a337b4fcf8f9097113df531d99ccefe80ef7ce8250b",
        ),
        "commandlinetools-linux-11076708_latest.zip": (
            "153607504",
            "2d2d50857e4eb553af5a6dc3ad507a17adf43d115264b1afc116f95c92e5e258",
        ),
    }
    for archive, (size, digest) in pinned.items():
      self.assertIn(archive, self.auto_source)
      self.assertIn(size, self.auto_source)
      self.assertIn(digest, self.auto_source)
    self.assertIn("1100545", self.auto_source)
    self.assertIn(
        "3716d9311e55d2b0918a2fd9d54ba9e406c5f6abeea700b287f11259bc163dec",
        self.auto_source,
    )
    self.assertIn("sha256sum --check --strict", self.auto_source)
    self.assertIn("reject_unsafe_entry", self.auto_source)
    self.assertIn('"$JAVA_BIN" -jar "$APKSIGNER_JAR" sign', self.auto_source)
    self.assertNotIn("Set up Java JDK 17 for personal mobile OTA", self.auto_source)
    self.assertNotIn("actions/setup-java", self.auto_source)

  def test_each_secret_bearing_step_has_only_its_required_scope(self) -> None:
    steps = {step["name"]: step for step in self.auto_job["steps"]}
    self.assertEqual(
        set(steps["Align and sign exact personal mobile APK"]["env"]),
        {"KEYSTORE_BASE64", "ANDROID_KEYSTORE_PASSWORD", "ANDROID_KEY_ALIAS"},
    )
    self.assertEqual(
        set(steps["Create and verify personal signed mobile manifest"]["env"]),
        {
            "APK_DOWNLOAD_URL",
            "APK_FALLBACK_DOWNLOAD_URL",
            "APK_RELEASE_NOTES_URL",
            "MOBILE_UPDATE_PRIVATE_KEY_HEX",
            "MOBILE_UPDATE_PUBLIC_KEY_HEX",
            "MOBILE_UPDATE_KEY_ID",
        },
    )
    self.assertEqual(
        set(steps["Prepare strict NAS host identity for personal mobile OTA"]["env"]),
        {"NAS_HOST", "NAS_PORT", "NAS_KNOWN_HOSTS"},
    )
    self.assertEqual(
        steps[
            "Atomically publish and read back primary and fallback mobile OTA"
        ]["env"]["NAS_APK_FALLBACK_TARGET_DIR"],
        "${{ secrets.NAS_APK_FALLBACK_TARGET_DIR || "
        "'/docker/smartbox_ota/gatekeeper_apk_fallback' }}",
    )

  def test_android_update_identity_is_pinned_before_manifest_creation(self) -> None:
    self.assertIn(
        "8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0",
        self.auto_source,
    )
    self.assertIn('PACKAGE_NAME" = "com.kshouse.gatekeeper_app', self.auto_source)
    self.assertIn(
        "MOBILE_BUILD_NUMBER=$((RUN_NUMBER_DEC * 100 + RUN_ATTEMPT_DEC))",
        self.auto_source,
    )
    self.assertIn(
        "((MOBILE_BUILD_NUMBER > 141 && MOBILE_BUILD_NUMBER <= 2100000000))",
        self.auto_source,
    )
    self.assertIn("flutter build apk --release", self.unsigned_source)
    self.assertIn("--build-number=\"$MOBILE_BUILD_NUMBER\"", self.unsigned_source)
    self.assertIn('test "$VERSION_CODE" = "$MOBILE_BUILD_NUMBER"', self.auto_source)
    self.assertIn('test "$VERSION_NAME" = "$FULL_VERSION"', self.auto_source)
    self.assertIn('test "$SOURCE_COMMIT" = "$GITHUB_SHA"', self.auto_source)

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
    self.assertIn(
        'PUBLISHED_AT="$(git show -s --format=%cI "$GITHUB_SHA")"',
        self.auto_source,
    )
    self.assertNotIn("PUBLISHED_AT=\"$(date", self.auto_source)

  def test_primary_and_fallback_use_the_shared_atomic_publisher(self) -> None:
    for fragment in (
        "Prepare strict NAS host identity for personal mobile OTA",
        "OTA_NAS_KNOWN_HOSTS_FILE",
        "OTA_NAS_HOST_KEY_MODE",
        "repository-secret-pinned",
        'test -n "$NAS_KNOWN_HOSTS"',
        "mobile-sftp-publish",
        "MOBILE_PUBLIC_KEY_HEX",
        "NAS_APK_TARGET_DIR",
        "NAS_APK_FALLBACK_TARGET_DIR",
        '--artifact dist/ks-house-gatekeeper.apk',
        '--manifest dist/version.json',
        '--expected-version "$FULL_VERSION"',
        '--expected-commit "$GITHUB_SHA"',
        '--expected-build-number "$MOBILE_BUILD_NUMBER"',
        '--expected-package-name "com.kshouse.gatekeeper_app"',
        '--run-attempt "$GITHUB_RUN_ATTEMPT"',
        "evidence/personal-mobile-ota-publication.json",
        '--apkanalyzer "$APKANALYZER"',
        '--apksigner "$APKSIGNER_JAR"',
    ):
      self.assertIn(fragment, self.auto_source)
    self.assertNotIn("sshpass", self.auto_source)
    self.assertNotIn("sftp ", self.auto_source)
    self.assertNotIn("ssh-keyscan", self.auto_source)
    self.assertNotIn("runtime-keyscan-unpinned", self.auto_source)

  def test_publication_evidence_is_preserved_without_secret_material(self) -> None:
    self.assertIn(
        "personal-mobile-ota-evidence-${{ github.sha }}",
        self.auto_source,
    )
    self.assertIn("attempt-${{ github.run_attempt }}", self.auto_source)
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
    self.assertIn(
        "MOBILE_BUILD_NUMBER=$((RUN_NUMBER_DEC * 100 + RUN_ATTEMPT_DEC))",
        str(commercial),
    )

  def test_protected_contract_rejects_personal_mobile_publish_bypasses(self) -> None:
    deploy_path = ".github/workflows/deploy.yml"
    mobile_path = ".github/workflows/build_app.yml"
    deploy = (ROOT / deploy_path).read_text(encoding="utf-8")
    mutations = (
        (
            "    environment: personal-auto-ota\n    concurrency:",
            "    environment: production\n    concurrency:",
        ),
        (
            "inputs.release_target == 'canary'",
            "inputs.release_target == 'production'",
        ),
        ("cancel-in-progress: false", "cancel-in-progress: true"),
        (
            'PUBLISHED_AT="$(git show -s --format=%cI "$GITHUB_SHA")"',
            'PUBLISHED_AT="$(date -u +%FT%TZ)"',
        ),
        (
            "python -I scripts/ota_contract_gate.py mobile-sftp-publish",
            "python attacker.py",
        ),
        (
            "166774efcf0f722f2ee18eba0039de2d685b350ee14d7b69e6f83437dafd2af1",
            "0" * 64,
        ),
        (
            "((UNSIGNED_APK_SIZE >= 1048576 && UNSIGNED_APK_SIZE <= 209715200))",
            "test -s \"$UNSIGNED_APK\"",
        ),
        (
            '--apksigner "$APKSIGNER_JAR"',
            '--apksigner "$ANDROID_HOME/build-tools/36.0.0/apksigner"',
        ),
        (
            "secrets.MOBILE_OTA_SIGNING_PRIVATE_KEY_HEX",
            "secrets.OTA_SIGNING_PRIVATE_KEY_HEX",
        ),
        (
            'fetch_verified "$JDK_URL" "$JDK_ARCHIVE" "$JDK_SIZE" "$JDK_SHA256"',
            "echo skipped-jdk-fetch",
        ),
        (
            'JAVA_BIN="${JAVA_HOME}/bin/java"',
            'JAVA_BIN="/usr/bin/java"',
        ),
        (
            "      - name: Install verified personal mobile signing toolchain\n"
            "        run: |\n"
            "          set -euo pipefail",
            "      - name: Install verified personal mobile signing toolchain\n"
            "        run: |\n"
            "          set +e",
        ),
        (
            "      - name: Verify pinned Android signer and package identity\n"
            "        run: |\n"
            "          set -euo pipefail",
            "      - name: Verify pinned Android signer and package identity\n"
            "        run: |\n"
            "          set -euo pipefail\n"
            '          echo "${{ secrets.NAS_PASSWORD }}"',
        ),
        (
            'fetch_exact "$APK_FALLBACK_DOWNLOAD_URL" http-readback/fallback.apk dist/ks-house-gatekeeper.apk',
            "echo skipped-fallback-apk",
        ),
    )
    for before, after in mutations:
      with self.subTest(before=before):
        self.assertIn(before, self.source)
        workflows = {
            deploy_path: deploy,
            mobile_path: self.source.replace(before, after, 1),
        }
        with self.assertRaises(gate.GateError):
          gate.validate_workflow_release_triggers(workflows)


if __name__ == "__main__":
  unittest.main()
