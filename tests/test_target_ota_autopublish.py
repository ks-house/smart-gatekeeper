import argparse
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path

from scripts import ota_contract_gate as gate


ROOT = Path(__file__).resolve().parents[1]
TEST_SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
TEST_PUBLIC = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
REMOTE_ROOT = "/docker/smartbox_ota/firmware"


class _FakeAttr:
  def __init__(self, mode: int):
    self.st_mode = mode


class _FakeWriter(io.BytesIO):
  def __init__(self, files: dict[str, bytes], path: str):
    super().__init__()
    self._files = files
    self._path = path

  def close(self) -> None:
    if not self.closed:
      self._files[self._path] = self.getvalue()
    super().close()


class FakeSftp:
  def __init__(self):
    self.files: dict[str, bytes] = {}
    self.directories = {REMOTE_ROOT}
    self.operations: list[tuple[str, str, str | None]] = []

  def stat(self, path: str):
    if path in self.directories:
      return _FakeAttr(stat.S_IFDIR | 0o755)
    if path in self.files:
      return _FakeAttr(stat.S_IFREG | 0o644)
    raise FileNotFoundError(2, "No such file", path)

  def open(self, path: str, mode: str):
    if mode == "rb":
      if path not in self.files:
        raise FileNotFoundError(2, "No such file", path)
      return io.BytesIO(self.files[path])
    if mode == "wb":
      return _FakeWriter(self.files, path)
    raise AssertionError(mode)

  def put(self, local: str, remote: str, confirm: bool = True):
    self.operations.append(("put", remote, None))
    self.files[remote] = Path(local).read_bytes()
    return self.stat(remote) if confirm else None

  def mkdir(self, path: str):
    if path in self.directories:
      raise FileExistsError(path)
    self.operations.append(("mkdir", path, None))
    self.directories.add(path)

  def rename(self, source: str, target: str):
    if target in self.files:
      raise FileExistsError(target)
    self.operations.append(("rename", source, target))
    self.files[target] = self.files.pop(source)

  def posix_rename(self, source: str, target: str):
    self.operations.append(("posix_rename", source, target))
    self.files[target] = self.files.pop(source)

  def remove(self, path: str):
    self.operations.append(("remove", path, None))
    del self.files[path]

  def rmdir(self, path: str):
    if any(name.startswith(f"{path}/") for name in self.files):
      raise OSError("directory not empty")
    self.operations.append(("rmdir", path, None))
    self.directories.remove(path)


def _create_manifest(
    directory: Path,
    name: str,
    version: str,
    commit: str,
    build_id: str,
    artifact_bytes: bytes,
    published_at: str = "2026-08-23T12:00:00Z",
) -> tuple[Path, Path, dict]:
  artifact = directory / f"{name}.bin"
  manifest = directory / f"{name}.json"
  artifact.write_bytes(artifact_bytes)
  previous = os.environ.get("TEST_TARGET_SIGNING_SEED")
  os.environ["TEST_TARGET_SIGNING_SEED"] = TEST_SEED
  try:
    gate.create_target_manifest(argparse.Namespace(
        artifact=artifact,
        output=manifest,
        version=version,
        commit=commit,
        build_id=build_id,
        artifact_url=(
            "https://updates.example.test/firmware/"
            f"gatekeeper-firmware-{commit}.bin"
        ),
        published_at=published_at,
        mandatory_after=None,
        signing_key_id="rfc8032-test-key-1",
        private_key_env="TEST_TARGET_SIGNING_SEED",
        expected_public_key_hex=TEST_PUBLIC,
        protocol_min=1,
        protocol_max=2,
    ))
  finally:
    if previous is None:
      os.environ.pop("TEST_TARGET_SIGNING_SEED", None)
    else:
      os.environ["TEST_TARGET_SIGNING_SEED"] = previous
  return artifact, manifest, gate.load_json(manifest)


class TargetOtaAutoPublishContractTests(unittest.TestCase):
  def test_main_job_is_exact_and_commercial_gate_remains_separate(self):
    source = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    workflow = gate.load_workflow_yaml(".github/workflows/deploy.yml", source)
    auto = workflow["jobs"]["publish_personal_target_ota"]
    commercial = workflow["jobs"]["release_to_production"]
    self.assertEqual(
        " ".join(str(auto["if"]).split()),
        "github.ref == 'refs/heads/main' && (github.event_name == 'push' || "
        "(github.event_name == 'workflow_dispatch' && inputs.release_target == 'canary'))",
    )
    self.assertEqual(auto["environment"], "production")
    self.assertIn("git rev-list --count --first-parent HEAD", source)
    self.assertIn("2.1.${COMMIT_SEQUENCE}+main.g${SHORT_SHA}", source)
    self.assertIn('TARGET_BUILD_ID="main-${COMMIT_SEQUENCE}-${GITHUB_SHA}"', source)
    self.assertIn('SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$GITHUB_SHA")"', source)
    self.assertIn("pip install platformio==6.1.19", source)
    self.assertIn("pio run -e esp32c6_production -t clean", source)
    self.assertIn(
        "cmp dist/gatekeeper-firmware-first.bin .pio/build/esp32c6_production/firmware.bin",
        source,
    )
    self.assertIn('version = os.environ["FULL_VERSION"].encode("ascii")', source)
    self.assertIn("if version not in firmware:", source)
    self.assertIn('PUBLISHED_AT="$(git show -s --format=%cI "$GITHUB_SHA")"', source)
    self.assertIn("pio run -e esp32c6_production", source)
    self.assertEqual(auto["concurrency"]["cancel-in-progress"], False)
    self.assertNotIn("runtime-keyscan-unpinned", str(auto))
    self.assertIn("Verify exact Target OTA pointer and immutable artifact over HTTPS", source)
    self.assertIn("TARGET_ROOT_CA_CERT", source)
    self.assertIn("--cacert \"$CA_FILE\"", source)
    self.assertIn("--proto '=https' --proto-redir '=https'", source)
    self.assertNotIn("ota_contract_gate.py release", str(auto))
    self.assertIn("ota_contract_gate.py release", str(commercial))
    gate.validate_workflow_release_triggers()

  def test_auto_job_condition_step_and_host_key_bypasses_are_rejected(self):
    path = ".github/workflows/deploy.yml"
    original = (ROOT / path).read_text(encoding="utf-8")
    app = (ROOT / ".github/workflows/build_app.yml").read_text(encoding="utf-8")
    mutations = (
        (
            "inputs.release_target == 'canary'",
            "inputs.release_target == 'production'",
        ),
        (
            "python scripts/ota_contract_gate.py target-sftp-publish",
            "python attacker.py",
        ),
        (
            "ssh-keygen -l -E sha256 -f \"$KNOWN_HOSTS_FILE\" >/dev/null",
            "true # host key ignored",
        ),
        ("cancel-in-progress: false", "cancel-in-progress: true"),
        ('test -n "$NAS_KNOWN_HOSTS"', "true # missing trust anchor allowed"),
        (
            'fetch_exact "$TARGET_VERSION_URL" https-readback/version.json dist/version.json',
            "echo skipped-target-version-readback",
        ),
        (
            "target-symbol-map-${{ env.FULL_VERSION }}-attempt-${{ github.run_attempt }}",
            "target-symbol-map-${{ env.FULL_VERSION }}",
        ),
    )
    for before, after in mutations:
      with self.subTest(before=before):
        self.assertIn(before, original)
        workflows = {
            path: original.replace(before, after, 1),
            ".github/workflows/build_app.yml": app,
        }
        with self.assertRaises(gate.GateError):
          gate.validate_workflow_release_triggers(workflows)

  def test_staged_readback_atomic_pointer_and_previous_history_are_preserved(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      old_commit = "1" * 40
      new_commit = "2" * 40
      old_artifact, old_manifest, _ = _create_manifest(
          directory, "old", "2.1.0-g1111111", old_commit, "100", b"old-fw"
      )
      new_artifact, new_manifest, candidate = _create_manifest(
          directory,
          "new",
          "2.1.200+main.g2222222",
          new_commit,
          f"main-200-{new_commit}",
          b"new-fw",
      )
      sftp = FakeSftp()
      old_artifact_name = f"gatekeeper-firmware-{old_commit}.bin"
      sftp.files[f"{REMOTE_ROOT}/{old_artifact_name}"] = old_artifact.read_bytes()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = old_manifest.read_bytes()

      result = gate._publish_target_sftp_bytes(
          sftp,
          REMOTE_ROOT,
          new_artifact,
          new_manifest,
          candidate,
          TEST_PUBLIC,
          "1",
      )

      self.assertEqual(result["result"], "publish-upgrade")
      self.assertTrue(result["previous_valid_artifact"])
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/version.json"], new_manifest.read_bytes()
      )
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/version-{old_commit}.json"],
          old_manifest.read_bytes(),
      )
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/{old_artifact_name}"], b"old-fw"
      )
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/gatekeeper-firmware-{new_commit}.bin"],
          b"new-fw",
      )
      self.assertNotIn(
          f"{REMOTE_ROOT}/.staging-{new_commit}-main-200-{new_commit}-1",
          sftp.directories,
      )
      pointer_swaps = [op for op in sftp.operations if op[0] == "posix_rename"]
      self.assertEqual(len(pointer_swaps), 1)
      self.assertEqual(pointer_swaps[0][2], f"{REMOTE_ROOT}/version.json")

  def test_newer_signed_pointer_refuses_stale_publish_before_staging(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      old_artifact, old_manifest, old_candidate = _create_manifest(
          directory,
          "candidate",
          "2.1.200+main.g3333333",
          "3" * 40,
          f"main-200-{'3' * 40}",
          b"candidate",
      )
      _, newer_manifest, _ = _create_manifest(
          directory,
          "newer",
          "2.1.201+main.g4444444",
          "4" * 40,
          f"main-201-{'4' * 40}",
          b"newer",
      )
      sftp = FakeSftp()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = newer_manifest.read_bytes()
      with self.assertRaisesRegex(gate.GateError, "stale"):
        gate._publish_target_sftp_bytes(
            sftp,
            REMOTE_ROOT,
            old_artifact,
            old_manifest,
            old_candidate,
            TEST_PUBLIC,
            "1",
        )
      self.assertFalse(any(op[0] == "mkdir" for op in sftp.operations))
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/version.json"], newer_manifest.read_bytes()
      )

  def test_present_but_unverifiable_pointer_fails_closed_before_staging(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      commit = "d" * 40
      artifact, manifest, candidate = _create_manifest(
          directory,
          "candidate",
          "2.1.205+main.gddddddd",
          commit,
          f"main-205-{commit}",
          b"candidate-after-corrupt-pointer",
      )
      sftp = FakeSftp()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = b'{"unsigned":"legacy"}\n'
      with self.assertRaisesRegex(gate.GateError, "present but unverifiable"):
        gate._publish_target_sftp_bytes(
            sftp,
            REMOTE_ROOT,
            artifact,
            manifest,
            candidate,
            TEST_PUBLIC,
            "1",
        )
      self.assertFalse(
          any(
              op[0] == "mkdir" and "/.staging-" in op[1]
              for op in sftp.operations
          )
      )
      self.assertEqual(
          sftp.files[f"{REMOTE_ROOT}/version.json"], b'{"unsigned":"legacy"}\n'
      )

  def test_newer_commercial_core_requires_explicit_auto_base_bump(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      commit = "b" * 40
      candidate_artifact, candidate_manifest, candidate = _create_manifest(
          directory,
          "candidate",
          "2.1.204+main.gbbbbbbb",
          commit,
          f"main-204-{commit}",
          b"personal-candidate",
      )
      _, commercial_manifest, _ = _create_manifest(
          directory,
          "commercial",
          "2.2.0",
          "c" * 40,
          "commercial-2.2.0",
          b"commercial-current",
      )
      sftp = FakeSftp()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = commercial_manifest.read_bytes()
      with self.assertRaisesRegex(gate.GateError, "version core is newer"):
        gate._publish_target_sftp_bytes(
            sftp,
            REMOTE_ROOT,
            candidate_artifact,
            candidate_manifest,
            candidate,
            TEST_PUBLIC,
            "1",
        )
      self.assertFalse(
          any(
              op[0] == "mkdir" and "/.staging-" in op[1]
              for op in sftp.operations
          )
      )

  def test_equal_signed_pointer_is_idempotent_without_pointer_swap(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      commit = "5" * 40
      artifact, manifest, candidate = _create_manifest(
          directory,
          "same",
          "2.1.202+main.g5555555",
          commit,
          f"main-202-{commit}",
          b"same",
      )
      sftp = FakeSftp()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = manifest.read_bytes()
      sftp.files[f"{REMOTE_ROOT}/gatekeeper-firmware-{commit}.bin"] = b"same"
      result = gate._publish_target_sftp_bytes(
          sftp, REMOTE_ROOT, artifact, manifest, candidate, TEST_PUBLIC, "2"
      )
      self.assertEqual(result["result"], "idempotent")
      self.assertFalse(any(op[0] == "posix_rename" for op in sftp.operations))

  def test_equal_identity_with_different_signed_manifest_bytes_is_rejected(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      commit = "6" * 40
      build_id = f"main-203-{commit}"
      artifact, current_manifest, _ = _create_manifest(
          directory,
          "current",
          "2.1.203+main.g6666666",
          commit,
          build_id,
          b"same-target",
          "2026-08-23T01:00:00Z",
      )
      _, rerun_manifest, rerun = _create_manifest(
          directory,
          "rerun",
          "2.1.203+main.g6666666",
          commit,
          build_id,
          b"same-target",
          "2026-08-23T02:00:00Z",
      )
      sftp = FakeSftp()
      sftp.files[f"{REMOTE_ROOT}/version.json"] = current_manifest.read_bytes()
      with self.assertRaisesRegex(gate.GateError, "conflicting signed manifest bytes"):
        gate._publish_target_sftp_bytes(
            sftp,
            REMOTE_ROOT,
            artifact,
            rerun_manifest,
            rerun,
            TEST_PUBLIC,
            "2",
        )
      self.assertFalse(
          any(
              op[0] == "mkdir" and "/.staging-" in op[1]
              for op in sftp.operations
          )
      )

  def test_remote_root_rejects_traversal(self):
    for invalid in (
        "/docker/smartbox_ota/../secrets",
        "/volume1/docker/smartbox_ota/firmware",
        "/docker//firmware",
        "/docker/firmware path",
    ):
      with self.subTest(path=invalid), self.assertRaises(gate.GateError):
        gate._validated_target_remote_root(invalid)

  def test_paramiko_is_pinned_for_posix_rename_transport(self):
    requirements = (ROOT / "ota/requirements.txt").read_text(encoding="utf-8")
    self.assertIn("paramiko==5.0.0", requirements.splitlines())

  def test_pioarduino_platform_is_pinned_to_exact_release_commit(self):
    platformio_path = ROOT / "platformio.ini"
    platformio = platformio_path.read_text(encoding="utf-8")
    self.assertIn(
        "platform-espressif32.git#"
        "cbc3349061987c28bc1b48d43d473e70c5ae04ed",
        platformio,
    )
    self.assertNotIn("releases/download/stable", platformio)
    self.assertNotIn("#b5ecd92324adf48003a470aeddfeb1f181d6e047", platformio)
    self.assertIn("bblanchon/ArduinoJson @ 6.21.5", platformio)
    self.assertIn("knolleary/PubSubClient @ 2.8", platformio)
    gate.validate_target_build_inputs(platformio_path.read_bytes())
    with self.assertRaisesRegex(gate.GateError, "reviewed exact pin"):
      gate.validate_target_build_inputs(
          platformio.replace("55.03.39", "stable").encode("utf-8")
      )


if __name__ == "__main__":
  unittest.main()
