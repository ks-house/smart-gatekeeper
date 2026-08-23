import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import ota_contract_gate as gate
from tests.test_target_ota_autopublish import FakeSftp


REMOTE_ROOT = "/docker/smartbox_ota/gatekeeper_apk"


def _candidate(commit: str, build_number: int, apk_bytes: bytes) -> dict:
  return {
      "commit": commit,
      "version": f"1.0.0-g{commit[:7]}",
      "version_name": f"1.0.0-g{commit[:7]}",
      "build_number": build_number,
      "version_code": build_number,
      "sha256": gate.hashlib.sha256(apk_bytes).hexdigest(),
      "apk_url": "https://updates.example.test/ks-house-gatekeeper.apk",
      "fallback_url": (
          "https://fallback.example.test/ks-house-gatekeeper.apk"
      ),
  }


def _write_pair(
    directory: Path,
    name: str,
    candidate: dict,
    apk_bytes: bytes,
) -> tuple[Path, Path]:
  apk = directory / f"{name}.apk"
  manifest = directory / f"{name}.json"
  apk.write_bytes(apk_bytes)
  manifest.write_text(json.dumps(candidate), encoding="utf-8")
  return apk, manifest


class _FailFirstManifestPromotionSftp(FakeSftp):
  def __init__(self):
    super().__init__()
    self._failed = False

  def posix_rename(self, source: str, target: str):
    if target.endswith("/version.json") and not self._failed:
      self._failed = True
      raise OSError("injected manifest promotion failure")
    super().posix_rename(source, target)


class MobileOtaAutoPublishEngineTests(unittest.TestCase):
  def _publish(
      self,
      sftp: FakeSftp,
      apk: Path,
      manifest: Path,
      candidate: dict,
      valid_by_manifest: dict[bytes, dict],
  ) -> dict:
    def validate(manifest_bytes, apk_bytes, *_args):
      if manifest_bytes is None or apk_bytes is None:
        return None
      expected = valid_by_manifest.get(manifest_bytes)
      if expected is None:
        return None
      return expected if expected["sha256"] == gate.hashlib.sha256(apk_bytes).hexdigest() else None

    with mock.patch.object(
        gate, "_validate_remote_mobile_pair", side_effect=validate
    ):
      return gate._publish_mobile_sftp_root(
          sftp,
          REMOTE_ROOT,
          apk,
          manifest,
          candidate,
          "0" * 64,
          Path("apkanalyzer"),
          Path("apksigner"),
          "1",
      )

  def test_previous_pair_and_candidate_are_immutable_before_fixed_pair_swap(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      old_bytes = b"old-apk"
      new_bytes = b"new-apk"
      old = _candidate("1" * 40, 141, old_bytes)
      new = _candidate("2" * 40, 142, new_bytes)
      old_apk, old_manifest = _write_pair(directory, "old", old, old_bytes)
      new_apk, new_manifest = _write_pair(directory, "new", new, new_bytes)
      sftp = FakeSftp()
      sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"] = old_apk.read_bytes()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = old_manifest.read_bytes()

      result = self._publish(
          sftp,
          new_apk,
          new_manifest,
          new,
          {old_manifest.read_bytes(): old},
      )

      self.assertEqual(result["result"], "publish-upgrade")
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"], new_bytes
      )
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/version.json"], new_manifest.read_bytes()
      )
      for manifest_candidate, apk_bytes in ((old, old_bytes), (new, new_bytes)):
        commit = manifest_candidate["commit"]
        build = manifest_candidate["build_number"]
        self.assertEqual(
            sftp.files[
                f"{REMOTE_ROOT}/ks-house-gatekeeper-{commit}-{build}.apk"
            ],
            apk_bytes,
        )
        self.assertIn(
            f"{REMOTE_ROOT}/version-{commit}-{build}.json", sftp.files
        )
      fixed_swaps = [
          operation
          for operation in sftp.operations
          if operation[0] == "posix_rename"
          and operation[2]
          in {
              f"{REMOTE_ROOT}/ks-house-gatekeeper.apk",
              f"{REMOTE_ROOT}/version.json",
          }
      ]
      self.assertEqual(
          [operation[2] for operation in fixed_swaps],
          [
              f"{REMOTE_ROOT}/ks-house-gatekeeper.apk",
              f"{REMOTE_ROOT}/version.json",
          ],
      )

  def test_newer_valid_pair_refuses_stale_candidate_before_staging(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      current_bytes = b"current"
      candidate_bytes = b"candidate"
      current = _candidate("3" * 40, 200, current_bytes)
      candidate = _candidate("4" * 40, 199, candidate_bytes)
      current_apk, current_manifest = _write_pair(
          directory, "current", current, current_bytes
      )
      candidate_apk, candidate_manifest = _write_pair(
          directory, "candidate", candidate, candidate_bytes
      )
      sftp = FakeSftp()
      sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"] = current_apk.read_bytes()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = current_manifest.read_bytes()
      with self.assertRaisesRegex(gate.GateError, "stale or conflicting"):
        self._publish(
            sftp,
            candidate_apk,
            candidate_manifest,
            candidate,
            {current_manifest.read_bytes(): current},
        )
      self.assertFalse(
          any(
              operation[0] == "mkdir" and "/.staging-" in operation[1]
              for operation in sftp.operations
          )
      )

  def test_equal_valid_pair_is_idempotent_without_fixed_pair_swap(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      apk_bytes = b"same"
      candidate = _candidate("5" * 40, 201, apk_bytes)
      apk, manifest = _write_pair(directory, "same", candidate, apk_bytes)
      sftp = FakeSftp()
      sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"] = apk_bytes
      sftp.files[f"{REMOTE_ROOT}/version.json"] = manifest.read_bytes()
      result = self._publish(
          sftp,
          apk,
          manifest,
          candidate,
          {manifest.read_bytes(): candidate},
      )
      self.assertEqual(result["result"], "idempotent")
      self.assertFalse(any(operation[0] == "posix_rename" for operation in sftp.operations))

  def test_manifest_promotion_failure_restores_previous_valid_pair(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      old_bytes = b"old"
      new_bytes = b"new"
      old = _candidate("6" * 40, 202, old_bytes)
      new = _candidate("7" * 40, 203, new_bytes)
      old_apk, old_manifest = _write_pair(directory, "old", old, old_bytes)
      new_apk, new_manifest = _write_pair(directory, "new", new, new_bytes)
      sftp = _FailFirstManifestPromotionSftp()
      sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"] = old_apk.read_bytes()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = old_manifest.read_bytes()
      with self.assertRaisesRegex(gate.GateError, "previous valid pair was restored"):
        self._publish(
            sftp,
            new_apk,
            new_manifest,
            new,
            {old_manifest.read_bytes(): old},
        )
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"], old_bytes
      )
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/version.json"], old_manifest.read_bytes()
      )

  def test_remote_root_rejects_traversal_and_aliasing(self):
    for invalid in (
        "/docker/smartbox_ota/../secrets",
        "/volume1/docker/smartbox_ota/gatekeeper_apk",
        "/docker//smartbox_ota/gatekeeper_apk",
        "/docker/smartbox_ota/app path",
    ):
      with self.subTest(path=invalid), self.assertRaises(gate.GateError):
        gate._validated_mobile_remote_root(invalid)


if __name__ == "__main__":
  unittest.main()
