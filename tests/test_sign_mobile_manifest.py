import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ota_contract_gate as gate  # noqa: E402
import sign_mobile_manifest as signer  # noqa: E402


TEST_PRIVATE_KEY_HEX = (
    "9d61b19deffd5a60ba844af492ec2cc4"
    "4449c5697b326919703bac031cae7f60"
)


class MobileManifestSignerTest(unittest.TestCase):
  def _create_args(self, directory: Path) -> argparse.Namespace:
    artifact = directory / "app.apk"
    artifact.write_bytes(b"exact signed APK bytes")
    return argparse.Namespace(
        artifact=artifact,
        output=directory / "version.json",
        version="1.2.3-test",
        build_number=42,
        commit="1234567890abcdef1234567890abcdef12345678",
        apk_url="https://updates.example.test/mobile/app.apk",
        fallback_url="https://fallback.example.test/mobile/app.apk",
        release_notes_url="https://updates.example.test/mobile/notes",
        published_at="2026-08-09T00:00:00Z",
        mandatory_after=None,
        certificate_sha256="ab" * 32,
        signing_key_id="rfc8032-test-key-1",
        private_key_env="TEST_MOBILE_SIGNING_SEED",
        expected_public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
        protocol_min=1,
        protocol_max=2,
        min_android_sdk=23,
    )

  def test_create_emits_exact_signed_schema_and_artifact_binding(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      with mock.patch.dict(
          os.environ,
          {"TEST_MOBILE_SIGNING_SEED": TEST_PRIVATE_KEY_HEX},
          clear=False,
      ):
        signer.create_manifest(args)

      manifest = json.loads(args.output.read_text(encoding="utf-8"))
      gate.validate_manifest(
          manifest,
          "mobile-manifest.schema.json",
          gate.TEST_PUBLIC_KEY_HEX,
      )
      self.assertEqual(set(manifest), set(gate.load_json(
          gate.OTA / "test-vectors" / "mobile-valid.json"
      )))
      signer.verify_manifest(argparse.Namespace(
          manifest=args.output,
          artifact=args.artifact,
          public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
          certificate_sha256="ab" * 32,
      ))

  def test_verify_rejects_tampered_artifact_and_certificate(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      with mock.patch.dict(
          os.environ,
          {"TEST_MOBILE_SIGNING_SEED": TEST_PRIVATE_KEY_HEX},
          clear=False,
      ):
        signer.create_manifest(args)
      args.artifact.write_bytes(b"tampered")
      with self.assertRaisesRegex(gate.GateError, "exact APK bytes"):
        signer.verify_manifest(argparse.Namespace(
            manifest=args.output,
            artifact=args.artifact,
            public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
            certificate_sha256="ab" * 32,
        ))

      args.artifact.write_bytes(b"exact signed APK bytes")
      with self.assertRaisesRegex(gate.GateError, "certificate digest"):
        signer.verify_manifest(argparse.Namespace(
            manifest=args.output,
            artifact=args.artifact,
            public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
            certificate_sha256="cd" * 32,
        ))

  def test_create_rejects_private_key_that_does_not_match_pinned_public_key(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      args.expected_public_key_hex = "00" * 32
      with mock.patch.dict(
          os.environ,
          {"TEST_MOBILE_SIGNING_SEED": TEST_PRIVATE_KEY_HEX},
          clear=False,
      ):
        with self.assertRaisesRegex(gate.GateError, "does not match"):
          signer.create_manifest(args)

  def test_create_rejects_unzoned_or_reversed_time_policy(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
      args = self._create_args(Path(temp))
      args.mandatory_after = "2026-08-08T23:59:59Z"
      with mock.patch.dict(
          os.environ,
          {"TEST_MOBILE_SIGNING_SEED": TEST_PRIVATE_KEY_HEX},
          clear=False,
      ):
        with self.assertRaisesRegex(gate.GateError, "cannot precede"):
          signer.create_manifest(args)
        args.mandatory_after = None
        args.published_at = "2026-08-09T00:00:00"
        with self.assertRaisesRegex(gate.GateError, "timezone"):
          signer.create_manifest(args)


if __name__ == "__main__":
  unittest.main()
