import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ota_contract_gate as gate  # noqa: E402


TEST_PRIVATE_KEY_HEX = (
    "9d61b19deffd5a60ba844af492ec2cc4"
    "4449c5697b326919703bac031cae7f60"
)
TEST_COMMIT = "1234567890abcdef1234567890abcdef12345678"
TEST_CERTIFICATE = "ab" * 32
APK_COMMIT_ENTRY = "assets/flutter_assets/assets/source_commit.txt"


class MobileManifestSignerTest(unittest.TestCase):
  def _write_apk(self, artifact: Path, commit: str = TEST_COMMIT) -> None:
    with zipfile.ZipFile(artifact, "w") as archive:
      archive.writestr(APK_COMMIT_ENTRY, commit + "\n")
      archive.writestr("classes.dex", b"synthetic exact APK payload")

  def _create_args(self, directory: Path) -> argparse.Namespace:
    artifact = directory / "app.apk"
    self._write_apk(artifact)
    apkanalyzer = directory / "apkanalyzer"
    apksigner = directory / "apksigner"
    apkanalyzer.write_text("test executable", encoding="utf-8")
    apksigner.write_text("test executable", encoding="utf-8")
    return argparse.Namespace(
        artifact=artifact,
        output=directory / "version.json",
        version="1.2.3-test",
        build_number=42,
        commit=TEST_COMMIT,
        apk_url="https://updates.example.test/mobile/app.apk",
        fallback_url="https://fallback.example.test/mobile/app.apk",
        release_notes_url="https://updates.example.test/mobile/notes",
        published_at="2026-08-09T00:00:00Z",
        mandatory_after=None,
        signing_key_id="rfc8032-test-key-1",
        private_key_env="TEST_MOBILE_SIGNING_SEED",
        expected_public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
        expected_package_name="com.kshouse.gatekeeper_app",
        apkanalyzer=apkanalyzer,
        apksigner=apksigner,
        protocol_min=1,
        protocol_max=2,
        min_android_sdk=23,
    )

  def _create(
      self,
      args: argparse.Namespace,
      identity: tuple[str, int, str] = (
          "com.kshouse.gatekeeper_app", 42, "1.2.3-test"
      ),
      certificates: set[str] | None = None,
  ) -> None:
    with mock.patch.dict(
        os.environ,
        {"TEST_MOBILE_SIGNING_SEED": TEST_PRIVATE_KEY_HEX},
        clear=False,
    ), mock.patch.object(
        gate, "read_apk_manifest_identity", return_value=identity
    ), mock.patch.object(
        gate,
        "read_apk_signing_certificate_digests",
        return_value=certificates or {TEST_CERTIFICATE},
    ):
      gate.create_mobile_manifest(args)

  def _verify_args(self, args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        manifest=args.output,
        artifact=args.artifact,
        public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
        expected_package_name="com.kshouse.gatekeeper_app",
        apkanalyzer=args.apkanalyzer,
        apksigner=args.apksigner,
    )

  def _verify(
      self,
      args: argparse.Namespace,
      identity: tuple[str, int, str] = (
          "com.kshouse.gatekeeper_app", 42, "1.2.3-test"
      ),
      certificates: set[str] | None = None,
  ) -> None:
    with mock.patch.object(
        gate, "read_apk_manifest_identity", return_value=identity
    ), mock.patch.object(
        gate,
        "read_apk_signing_certificate_digests",
        return_value=certificates or {TEST_CERTIFICATE},
    ):
      gate.verify_mobile_manifest(self._verify_args(args))

  def test_create_emits_exact_signed_schema_and_artifact_binding(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      self._create(args)

      manifest = json.loads(args.output.read_text(encoding="utf-8"))
      gate.validate_manifest(
          manifest,
          "mobile-manifest.schema.json",
          gate.TEST_PUBLIC_KEY_HEX,
      )
      self.assertEqual(
          set(manifest),
          set(gate.load_json(gate.OTA / "test-vectors" / "mobile-valid.json")),
      )
      self._verify(args)

  def test_verify_rejects_tampered_artifact_and_certificate(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      self._create(args)
      original = args.artifact.read_bytes()
      with zipfile.ZipFile(args.artifact, "a") as archive:
        archive.writestr("tampered.bin", b"tampered")
      with self.assertRaisesRegex(gate.GateError, "exact APK bytes"):
        self._verify(args)

      args.artifact.write_bytes(original)
      with self.assertRaisesRegex(gate.GateError, "certificate digest"):
        self._verify(args, certificates={"cd" * 32})

  def test_create_rejects_private_key_that_does_not_match_pinned_public_key(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      args.expected_public_key_hex = "00" * 32
      with self.assertRaisesRegex(gate.GateError, "does not match"):
        self._create(args)

  def test_create_rejects_unzoned_or_reversed_time_policy(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      args.mandatory_after = "2026-08-08T23:59:59Z"
      with self.assertRaisesRegex(gate.GateError, "cannot precede"):
        self._create(args)
      args.mandatory_after = None
      args.published_at = "2026-08-09T00:00:00"
      with self.assertRaisesRegex(gate.GateError, "timezone"):
        self._create(args)

  def test_create_rejects_apk_internal_identity_and_commit_mismatches(self) -> None:
    mutations = (
        (("com.attacker.repacked", 42, "1.2.3-test"), "application ID"),
        (("com.kshouse.gatekeeper_app", 43, "1.2.3-test"), "version code"),
        (("com.kshouse.gatekeeper_app", 42, "1.2.4"), "version name"),
    )
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      for identity, message in mutations:
        with self.subTest(identity=identity):
          with self.assertRaisesRegex(gate.GateError, message):
            self._create(args, identity)

      self._write_apk(args.artifact, "0" * 40)
      with self.assertRaisesRegex(gate.GateError, "embedded source commit"):
        self._create(args)

      args.commit = "not-a-commit"
      with self.assertRaisesRegex(gate.GateError, "40-hex"):
        self._create(args)

  def test_duplicate_or_missing_embedded_commit_is_rejected(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(args.artifact, "a") as archive:
          archive.writestr(APK_COMMIT_ENTRY, TEST_COMMIT)
      with self.assertRaisesRegex(gate.GateError, "exactly one"):
        gate.read_apk_embedded_source_commit(args.artifact)

      with zipfile.ZipFile(args.artifact, "w") as archive:
        archive.writestr("classes.dex", b"missing identity")
      with self.assertRaisesRegex(gate.GateError, "exactly one"):
        gate.read_apk_embedded_source_commit(args.artifact)

  def test_zero_or_multiple_archive_signers_are_rejected(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      outputs = (
          "",
          "\n".join((
              f"Signer #1 certificate SHA-256 digest: {TEST_CERTIFICATE}",
              f"Signer #2 certificate SHA-256 digest: {'cd' * 32}",
          )),
      )
      for output in outputs:
        with self.subTest(output=output):
          completed = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
          with mock.patch.object(gate.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(gate.GateError, "exactly one"):
              gate.read_apk_signing_certificate_digests(
                  args.artifact, args.apksigner
              )

  def test_direct_apksigner_jar_uses_only_explicit_java_binary(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      apksigner_jar = Path(temp) / "apksigner.jar"
      java_binary = Path(temp) / "jdk-17.0.16+8" / "bin" / "java"
      apksigner_jar.write_bytes(b"pinned apksigner jar")
      java_binary.parent.mkdir(parents=True)
      java_binary.write_bytes(b"pinned java binary")
      completed = subprocess.CompletedProcess(
          [],
          0,
          stdout=(
              f"Signer #1 certificate SHA-256 digest: {TEST_CERTIFICATE}\n"
          ),
          stderr="",
      )
      with mock.patch.dict(
          os.environ,
          {"SGK_APKSIGNER_JAVA": str(java_binary.resolve())},
          clear=False,
      ), mock.patch.object(
          gate.subprocess, "run", return_value=completed
      ) as run:
        self.assertEqual(
            gate.read_apk_signing_certificate_digests(
                args.artifact, apksigner_jar
            ),
            {TEST_CERTIFICATE},
        )
      self.assertEqual(
          run.call_args.args[0],
          [
              str(java_binary.resolve()),
              "-jar",
              str(apksigner_jar),
              "verify",
              "--print-certs",
              str(args.artifact),
          ],
      )

      with mock.patch.dict(os.environ, {}, clear=True):
        with self.assertRaisesRegex(gate.GateError, "SGK_APKSIGNER_JAVA"):
          gate.read_apk_signing_certificate_digests(
              args.artifact, apksigner_jar
          )

  def test_android_tools_are_invoked_for_exact_archive_identity(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      results = [
          subprocess.CompletedProcess([], 0, stdout=value, stderr="")
          for value in (
              "com.kshouse.gatekeeper_app\n",
              "1.2.3-test\n",
              "42\n",
          )
      ]
      with mock.patch.object(
          gate.subprocess, "run", side_effect=results
      ) as run:
        self.assertEqual(
            gate.read_apk_manifest_identity(args.artifact, args.apkanalyzer),
            ("com.kshouse.gatekeeper_app", 42, "1.2.3-test"),
        )
      self.assertEqual(
          [call.args[0][2] for call in run.call_args_list],
          ["application-id", "version-name", "version-code"],
      )
      self.assertTrue(all(
          call.args[0][-1] == str(args.artifact) for call in run.call_args_list
      ))

      invalid_results = [
          subprocess.CompletedProcess([], 0, stdout=value, stderr="")
          for value in ("com.kshouse.gatekeeper_app", "1.2.3-test", "0")
      ]
      with mock.patch.object(
          gate.subprocess, "run", side_effect=invalid_results
      ), self.assertRaisesRegex(gate.GateError, "positive integer"):
        gate.read_apk_manifest_identity(args.artifact, args.apkanalyzer)


if __name__ == "__main__":
  unittest.main()
