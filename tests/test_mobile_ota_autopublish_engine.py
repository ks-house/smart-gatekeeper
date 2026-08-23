import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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


class _CorruptFirstPromotedApkReadbackSftp(FakeSftp):
  def __init__(self):
    super().__init__()
    self._inject_corrupt_readback = False
    self._injected = False

  def posix_rename(self, source: str, target: str):
    super().posix_rename(source, target)
    if target.endswith("/ks-house-gatekeeper.apk") and not self._injected:
      self._inject_corrupt_readback = True
      self._injected = True

  def open(self, path: str, mode: str):
    if (
        mode == "rb"
        and path.endswith("/ks-house-gatekeeper.apk")
        and self._inject_corrupt_readback
    ):
      self._inject_corrupt_readback = False
      return io.BytesIO(b"injected-corrupt-readback")
    return super().open(path, mode)


class _PrefetchReader(io.BytesIO):
  def __init__(self, value: bytes):
    super().__init__(value)
    self.prefetch_calls: list[tuple[int, int]] = []
    self.read_sizes: list[int] = []

  def prefetch(self, file_size: int, max_concurrent_requests: int) -> None:
    self.prefetch_calls.append((file_size, max_concurrent_requests))

  def read(self, size: int = -1) -> bytes:
    self.read_sizes.append(size)
    return super().read(size)


class _PrefetchSftp:
  def __init__(self, value: bytes):
    self.value = value
    self.reader: _PrefetchReader | None = None
    self.open_calls = 0

  def stat(self, _path: str):
    return SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_size=len(self.value))

  def open(self, _path: str, mode: str):
    if mode != "rb":
      raise AssertionError(mode)
    self.open_calls += 1
    self.reader = _PrefetchReader(self.value)
    return self.reader


class _ReadCountingSftp(FakeSftp):
  def __init__(self):
    super().__init__()
    self.reads: dict[str, int] = {}
    self.writes: dict[str, int] = {}

  def open(self, path: str, mode: str):
    if mode == "rb":
      self.reads[path] = self.reads.get(path, 0) + 1
    elif mode == "wb":
      self.writes[path] = self.writes.get(path, 0) + 1
    return super().open(path, mode)


class MobileOtaAutoPublishEngineTests(unittest.TestCase):
  def _publish(
      self,
      sftp: FakeSftp,
      apk: Path,
      manifest: Path,
      candidate: dict,
      valid_by_manifest: dict[bytes, dict],
      initial_state: dict | None = None,
  ) -> dict:
    def validate_manifest(manifest_bytes, *_args):
      if manifest_bytes is None:
        return None
      expected = valid_by_manifest.get(manifest_bytes)
      if expected is None:
        raise gate.GateError(
            "existing mobile OTA manifest is present but unverifiable"
        )
      return expected

    def validate(manifest_bytes, apk_bytes, *_args):
      if manifest_bytes is None or apk_bytes is None:
        return None
      expected = valid_by_manifest.get(manifest_bytes)
      if expected is None:
        return None
      return expected if expected["sha256"] == gate.hashlib.sha256(apk_bytes).hexdigest() else None

    with mock.patch.object(
        gate, "_validate_remote_mobile_manifest", side_effect=validate_manifest
    ), mock.patch.object(
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
          initial_state,
      )

  def _preflight(
      self,
      sftp: FakeSftp,
      candidate: dict,
      valid_by_manifest: dict[bytes, dict],
  ) -> dict[str, dict]:
    def validate_manifest(manifest_bytes, *_args):
      if manifest_bytes is None:
        return None
      expected = valid_by_manifest.get(manifest_bytes)
      if expected is None:
        raise gate.GateError(
            "existing mobile OTA manifest is present but unverifiable"
        )
      return expected

    def validate_pair(manifest_bytes, apk_bytes, *_args):
      if manifest_bytes is None or apk_bytes is None:
        return None
      expected = valid_by_manifest.get(manifest_bytes)
      if expected is None:
        return None
      return (
          expected
          if expected["sha256"] == gate.hashlib.sha256(apk_bytes).hexdigest()
          else None
      )

    with mock.patch.object(
        gate, "_validate_remote_mobile_manifest", side_effect=validate_manifest
    ), mock.patch.object(
        gate, "_validate_remote_mobile_pair", side_effect=validate_pair
    ):
      return gate._preflight_mobile_sftp_roots(
          sftp,
          (REMOTE_ROOT, REMOTE_ROOT + "_fallback"),
          candidate,
          "0" * 64,
          Path("apkanalyzer"),
          Path("apksigner"),
      )

  def test_sftp_readback_uses_bounded_prefetch_and_exact_size(self):
    value = b"apk-readback" * 1024
    sftp = _PrefetchSftp(value)

    self.assertEqual(gate._read_sftp_bytes(sftp, "/bounded.apk"), value)
    self.assertIsNotNone(sftp.reader)
    assert sftp.reader is not None
    self.assertEqual(
        sftp.reader.prefetch_calls,
        [(len(value), gate.SFTP_PREFETCH_REQUESTS)],
    )
    self.assertEqual(sftp.reader.read_sizes, [len(value) + 1])
    self.assertEqual(gate.SFTP_PREFETCH_REQUESTS, 64)

  def test_sftp_readback_refuses_oversized_object_before_open(self):
    sftp = _PrefetchSftp(b"")
    with mock.patch.object(
        sftp,
        "stat",
        return_value=SimpleNamespace(
            st_mode=stat.S_IFREG | 0o644,
            st_size=gate.SFTP_MAX_READBACK_BYTES + 1,
        ),
    ), self.assertRaisesRegex(gate.GateError, "bounded contract"):
      gate._read_sftp_bytes(sftp, "/oversized.apk")
    self.assertEqual(sftp.open_calls, 0)

  def test_preflight_state_is_reused_and_fixed_apk_is_read_only_for_validation_and_promotion(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      old_bytes = b"old-apk-reuse"
      new_bytes = b"new-apk-reuse"
      old = _candidate("1" * 40, 501, old_bytes)
      new = _candidate("2" * 40, 502, new_bytes)
      old_apk, old_manifest = _write_pair(directory, "old", old, old_bytes)
      new_apk, new_manifest = _write_pair(directory, "new", new, new_bytes)
      sftp = _ReadCountingSftp()
      fixed_apk = f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"
      fixed_manifest = f"{REMOTE_ROOT}/version.json"
      sftp.files[fixed_apk] = old_apk.read_bytes()
      sftp.files[fixed_manifest] = old_manifest.read_bytes()
      states = self._preflight(
          sftp,
          new,
          {old_manifest.read_bytes(): old},
      )

      result = self._publish(
          sftp,
          new_apk,
          new_manifest,
          new,
          {old_manifest.read_bytes(): old},
          states[REMOTE_ROOT],
      )

      self.assertEqual(result["result"], "publish-upgrade")
      self.assertEqual(sftp.reads[fixed_apk], 2)
      self.assertEqual(sftp.files[fixed_apk], new_bytes)

  def test_preflight_state_cannot_be_reused_for_a_different_root(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      candidate_bytes = b"root-bound-candidate"
      candidate = _candidate("3" * 40, 503, candidate_bytes)
      apk, manifest = _write_pair(
          directory, "root-bound", candidate, candidate_bytes
      )
      sftp = FakeSftp()
      wrong_state = {
          "remote_root": REMOTE_ROOT + "_fallback",
          "apk_bytes": None,
          "manifest_bytes": None,
          "manifest": None,
          "valid_pair": None,
      }

      with self.assertRaisesRegex(gate.GateError, "not bound"):
        self._publish(sftp, apk, manifest, candidate, {}, wrong_state)
      self.assertFalse(
          any(
              operation[0] in {"mkdir", "put", "rename", "posix_rename", "remove"}
              for operation in sftp.operations
          )
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

  def test_signed_floor_survives_missing_or_corrupt_apk(self):
    for current_apk in (None, b"corrupt-apk"):
      with self.subTest(current_apk=current_apk):
        with tempfile.TemporaryDirectory() as directory_name:
          directory = Path(directory_name)
          signed_apk = b"signed-current-apk"
          candidate_bytes = b"stale-candidate"
          current = _candidate("b" * 40, 300, signed_apk)
          candidate = _candidate("c" * 40, 299, candidate_bytes)
          _, current_manifest = _write_pair(
              directory, "current", current, signed_apk
          )
          candidate_apk, candidate_manifest = _write_pair(
              directory, "candidate", candidate, candidate_bytes
          )
          sftp = FakeSftp()
          if current_apk is not None:
            sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"] = current_apk
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

  def test_signed_invalid_pair_accepts_only_strictly_newer_candidate(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      old_apk = b"old-apk"
      current = _candidate("d" * 40, 301, old_apk)
      same = _candidate("d" * 40, 301, old_apk)
      newer_bytes = b"strictly-newer"
      newer = _candidate("e" * 40, 302, newer_bytes)
      _, current_manifest = _write_pair(directory, "current", current, old_apk)
      same_apk, same_manifest = _write_pair(directory, "same", same, old_apk)
      newer_apk, newer_manifest = _write_pair(
          directory, "newer", newer, newer_bytes
      )

      stale_sftp = FakeSftp()
      stale_sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"] = b"corrupt"
      stale_sftp.files[f"{REMOTE_ROOT}/version.json"] = current_manifest.read_bytes()
      with self.assertRaisesRegex(gate.GateError, "strictly newer"):
        self._publish(
            stale_sftp,
            same_apk,
            same_manifest,
            same,
            {current_manifest.read_bytes(): current},
        )

      upgrade_sftp = FakeSftp()
      upgrade_sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"] = b"corrupt"
      upgrade_sftp.files[f"{REMOTE_ROOT}/version.json"] = current_manifest.read_bytes()
      result = self._publish(
          upgrade_sftp,
          newer_apk,
          newer_manifest,
          newer,
          {current_manifest.read_bytes(): current},
      )
      self.assertEqual(result["result"], "publish-upgrade-replacing-invalid-pair")
      self.assertEqual(
          upgrade_sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"],
          newer_bytes,
      )

  def test_invalid_or_orphaned_existing_metadata_fails_closed(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      candidate_bytes = b"candidate"
      candidate = _candidate("f" * 40, 303, candidate_bytes)
      candidate_apk, candidate_manifest = _write_pair(
          directory, "candidate", candidate, candidate_bytes
      )
      for existing_apk, existing_manifest, error in (
          (b"orphan", None, "without a signed manifest"),
          (None, b"not-a-signed-manifest", "present but unverifiable"),
      ):
        with self.subTest(error=error):
          sftp = FakeSftp()
          if existing_apk is not None:
            sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"] = existing_apk
          if existing_manifest is not None:
            sftp.files[f"{REMOTE_ROOT}/version.json"] = existing_manifest
          with self.assertRaisesRegex(gate.GateError, error):
            self._publish(
                sftp,
                candidate_apk,
                candidate_manifest,
                candidate,
                {},
            )

  def test_two_root_preflight_preserves_the_highest_signed_floor(self):
    primary_root = REMOTE_ROOT
    fallback_root = REMOTE_ROOT + "_fallback"
    primary_bytes = b"primary-newer"
    fallback_bytes = b"fallback-older"
    candidate_bytes = b"candidate-middle"
    primary = _candidate("1" * 40, 401, primary_bytes)
    fallback = _candidate("2" * 40, 399, fallback_bytes)
    candidate = _candidate("3" * 40, 400, candidate_bytes)
    primary_manifest = json.dumps(primary).encode("utf-8")
    fallback_manifest = json.dumps(fallback).encode("utf-8")
    sftp = FakeSftp()
    sftp.files[f"{primary_root}/ks-house-gatekeeper.apk"] = primary_bytes
    sftp.files[f"{primary_root}/version.json"] = primary_manifest
    sftp.files[f"{fallback_root}/ks-house-gatekeeper.apk"] = fallback_bytes
    sftp.files[f"{fallback_root}/version.json"] = fallback_manifest
    before = dict(sftp.files)

    with self.assertRaisesRegex(gate.GateError, "stale or conflicting"):
      self._preflight(
          sftp,
          candidate,
          {
              primary_manifest: primary,
              fallback_manifest: fallback,
          },
      )
    self.assertEqual(sftp.files, before)
    self.assertFalse(
        any(
            operation[0] in {"mkdir", "put", "posix_rename", "remove"}
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

  def test_equal_identity_with_different_signed_manifest_bytes_is_rejected(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      apk_bytes = b"same-apk"
      candidate = _candidate("8" * 40, 204, apk_bytes)
      current = {**candidate, "published_at": "2026-08-23T01:00:00Z"}
      rerun = {**candidate, "published_at": "2026-08-23T02:00:00Z"}
      current_apk, current_manifest = _write_pair(
          directory, "current", current, apk_bytes
      )
      rerun_apk, rerun_manifest = _write_pair(
          directory, "rerun", rerun, apk_bytes
      )
      sftp = FakeSftp()
      sftp.files[f"{REMOTE_ROOT}/ks-house-gatekeeper.apk"] = current_apk.read_bytes()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = current_manifest.read_bytes()
      with self.assertRaisesRegex(gate.GateError, "conflicting signed bytes"):
        self._publish(
            sftp,
            rerun_apk,
            rerun_manifest,
            rerun,
            {current_manifest.read_bytes(): current},
        )
      self.assertFalse(
          any(
              operation[0] == "mkdir" and "/.staging-" in operation[1]
              for operation in sftp.operations
          )
      )

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

  def test_apk_promotion_readback_failure_restores_previous_valid_pair(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      old_bytes = b"old-before-apk-readback"
      new_bytes = b"new-before-apk-readback"
      old = _candidate("9" * 40, 205, old_bytes)
      new = _candidate("a" * 40, 206, new_bytes)
      old_apk, old_manifest = _write_pair(directory, "old", old, old_bytes)
      new_apk, new_manifest = _write_pair(directory, "new", new, new_bytes)
      sftp = _CorruptFirstPromotedApkReadbackSftp()
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
