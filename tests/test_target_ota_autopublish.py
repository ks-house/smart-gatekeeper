import argparse
import hashlib
import io
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from scripts import ota_contract_gate as gate


ROOT = Path(__file__).resolve().parents[1]
TEST_SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
TEST_PUBLIC = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
REMOTE_ROOT = "/docker/smartbox_ota/firmware"


class _FakeAttr:
  def __init__(self, mode: int, size: int = 0):
    self.st_mode = mode
    self.st_size = size


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
      return _FakeAttr(stat.S_IFREG | 0o644, len(self.files[path]))
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
    artifact_url: str | None = None,
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
        artifact_url=artifact_url or (
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
  def test_sensitive_handoff_is_bound_to_recipient_commit_and_attempt(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      artifact = directory / "firmware.bin"
      envelope = directory / "firmware.sgkenc"
      recovered = directory / "recovered.bin"
      artifact.write_bytes(b"exact secret-bearing firmware")
      recipient = X25519PrivateKey.generate()
      recipient_private_hex = recipient.private_bytes(
          serialization.Encoding.Raw,
          serialization.PrivateFormat.Raw,
          serialization.NoEncryption(),
      ).hex()
      recipient_public_hex = recipient.public_key().public_bytes(
          serialization.Encoding.Raw,
          serialization.PublicFormat.Raw,
      ).hex()
      commit = "a" * 40
      gate.encrypt_target_handoff(argparse.Namespace(
          artifact=artifact,
          output=envelope,
          recipient_public_key_hex=recipient_public_hex,
          commit=commit,
          run_attempt="2",
      ))
      with mock.patch.dict(
          os.environ, {"TEST_HANDOFF_PRIVATE": recipient_private_hex}, clear=False
      ):
        gate.decrypt_target_handoff(argparse.Namespace(
            input=envelope,
            output=recovered,
            private_key_env="TEST_HANDOFF_PRIVATE",
            recipient_public_key_hex=recipient_public_hex,
            commit=commit,
            run_attempt="2",
        ))
        self.assertEqual(recovered.read_bytes(), artifact.read_bytes())
        for wrong_commit, wrong_attempt in (("b" * 40, "2"), (commit, "3")):
          with self.subTest(commit=wrong_commit, attempt=wrong_attempt):
            with self.assertRaisesRegex(gate.GateError, "authentication failed"):
              gate.decrypt_target_handoff(argparse.Namespace(
                  input=envelope,
                  output=recovered,
                  private_key_env="TEST_HANDOFF_PRIVATE",
                  recipient_public_key_hex=recipient_public_hex,
                  commit=wrong_commit,
                  run_attempt=wrong_attempt,
              ))
        tampered = bytearray(envelope.read_bytes())
        tampered[-1] ^= 0x01
        envelope.write_bytes(tampered)
        with self.assertRaisesRegex(gate.GateError, "authentication failed"):
          gate.decrypt_target_handoff(argparse.Namespace(
              input=envelope,
              output=recovered,
              private_key_env="TEST_HANDOFF_PRIVATE",
              recipient_public_key_hex=recipient_public_hex,
              commit=commit,
              run_attempt="2",
          ))

  def test_sensitive_handoff_rejects_wrong_key_and_oversize_plaintext(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      artifact = directory / "firmware.bin"
      envelope = directory / "firmware.sgkenc"
      recipient = X25519PrivateKey.generate()
      other = X25519PrivateKey.generate()
      recipient_public_hex = recipient.public_key().public_bytes(
          serialization.Encoding.Raw,
          serialization.PublicFormat.Raw,
      ).hex()
      other_private_hex = other.private_bytes(
          serialization.Encoding.Raw,
          serialization.PrivateFormat.Raw,
          serialization.NoEncryption(),
      ).hex()
      artifact.write_bytes(b"firmware")
      gate.encrypt_target_handoff(argparse.Namespace(
          artifact=artifact,
          output=envelope,
          recipient_public_key_hex=recipient_public_hex,
          commit="c" * 40,
          run_attempt="1",
      ))
      with mock.patch.dict(
          os.environ, {"TEST_HANDOFF_PRIVATE": other_private_hex}, clear=False
      ):
        with self.assertRaisesRegex(gate.GateError, "does not match"):
          gate.decrypt_target_handoff(argparse.Namespace(
              input=envelope,
              output=directory / "recovered.bin",
              private_key_env="TEST_HANDOFF_PRIVATE",
              recipient_public_key_hex=recipient_public_hex,
              commit="c" * 40,
              run_attempt="1",
          ))
      artifact.write_bytes(b"x" * (gate.TARGET_HANDOFF_MAX_PLAINTEXT + 1))
      with self.assertRaisesRegex(gate.GateError, "outside the N16 OTA slot"):
        gate.encrypt_target_handoff(argparse.Namespace(
            artifact=artifact,
            output=envelope,
            recipient_public_key_hex=recipient_public_hex,
            commit="c" * 40,
            run_attempt="1",
        ))

  def test_public_nas_content_envelope_roundtrip_and_tamper_rejection(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      artifact = directory / "firmware.bin"
      envelope = directory / "firmware.sgkenc"
      recovered = directory / "recovered.bin"
      artifact.write_bytes(b"credential-bearing-target-firmware")
      common = {
          "key_env": "TEST_TARGET_CONTENT_KEY",
          "key_id": "test-target-content-1",
          "commit": "d" * 40,
      }
      with mock.patch.dict(
          os.environ,
          {"TEST_TARGET_CONTENT_KEY": "12" * 32},
          clear=False,
      ):
        gate.encrypt_target_content(argparse.Namespace(
            artifact=artifact, output=envelope, **common
        ))
        self.assertTrue(envelope.read_bytes().startswith(gate.TARGET_CONTENT_MAGIC))
        self.assertNotIn(artifact.read_bytes(), envelope.read_bytes())
        gate.decrypt_target_content(argparse.Namespace(
            input=envelope, output=recovered, **common
        ))
        self.assertEqual(recovered.read_bytes(), artifact.read_bytes())
        with self.assertRaisesRegex(gate.GateError, "authentication failed"):
          gate.decrypt_target_content(argparse.Namespace(
              input=envelope,
              output=recovered,
              key_env=common["key_env"],
              key_id=common["key_id"],
              commit="e" * 40,
          ))
        tampered = bytearray(envelope.read_bytes())
        tampered[-1] ^= 0x80
        envelope.write_bytes(tampered)
        with self.assertRaisesRegex(gate.GateError, "authentication failed"):
          gate.decrypt_target_content(argparse.Namespace(
              input=envelope, output=recovered, **common
          ))

  def test_public_nas_content_envelope_is_safe_and_deterministic_for_reruns(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      artifact = directory / "firmware.bin"
      first = directory / "first.sgkenc"
      rerun = directory / "rerun.sgkenc"
      changed = directory / "changed.sgkenc"
      artifact.write_bytes(b"deterministic exact-main firmware")
      common = {
          "artifact": artifact,
          "key_env": "TEST_TARGET_CONTENT_KEY",
          "key_id": "test-target-content-1",
          "commit": "a" * 40,
      }
      with mock.patch.dict(
          os.environ,
          {"TEST_TARGET_CONTENT_KEY": "ab" * 32},
          clear=False,
      ):
        gate.encrypt_target_content(argparse.Namespace(output=first, **common))
        gate.encrypt_target_content(argparse.Namespace(output=rerun, **common))
        self.assertEqual(first.read_bytes(), rerun.read_bytes())

        artifact.write_bytes(b"different deterministic exact-main firmware")
        gate.encrypt_target_content(argparse.Namespace(output=changed, **common))

      nonce_start = len(gate.TARGET_CONTENT_MAGIC)
      nonce_end = nonce_start + gate.TARGET_CONTENT_NONCE_SIZE
      self.assertNotEqual(
          first.read_bytes()[nonce_start:nonce_end],
          changed.read_bytes()[nonce_start:nonce_end],
      )
      self.assertNotEqual(first.read_bytes(), changed.read_bytes())

  def test_public_nas_content_envelope_rejects_wrong_key_and_oversize(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      artifact = directory / "firmware.bin"
      envelope = directory / "firmware.sgkenc"
      commit = "f" * 40
      artifact.write_bytes(b"firmware")
      with mock.patch.dict(
          os.environ, {"CONTENT_KEY": "34" * 32}, clear=False
      ):
        gate.encrypt_target_content(argparse.Namespace(
            artifact=artifact,
            output=envelope,
            key_env="CONTENT_KEY",
            key_id="test-target-content-1",
            commit=commit,
        ))
      with mock.patch.dict(
          os.environ, {"CONTENT_KEY": "56" * 32}, clear=False
      ):
        with self.assertRaisesRegex(gate.GateError, "authentication failed"):
          gate.decrypt_target_content(argparse.Namespace(
              input=envelope,
              output=directory / "recovered.bin",
              key_env="CONTENT_KEY",
              key_id="test-target-content-1",
              commit=commit,
          ))
      artifact.write_bytes(b"x" * (gate.TARGET_HANDOFF_MAX_PLAINTEXT + 1))
      with mock.patch.dict(
          os.environ, {"CONTENT_KEY": "34" * 32}, clear=False
      ):
        with self.assertRaisesRegex(gate.GateError, "outside the N16 OTA slot"):
          gate.encrypt_target_content(argparse.Namespace(
              artifact=artifact,
              output=envelope,
              key_env="CONTENT_KEY",
              key_id="test-target-content-1",
              commit=commit,
          ))

  def test_encrypted_target_manifest_binds_ciphertext_and_plaintext_identity(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      plaintext = directory / "firmware.bin"
      encrypted = directory / "firmware.sgkenc"
      manifest = directory / "version.json"
      plaintext.write_bytes(b"exact firmware plaintext")
      commit = "7" * 40
      key_id = "test-target-content-1"
      with mock.patch.dict(
          os.environ,
          {
              "CONTENT_KEY": "78" * 32,
              "TEST_TARGET_SIGNING_SEED": TEST_SEED,
          },
          clear=False,
      ):
        gate.encrypt_target_content(argparse.Namespace(
            artifact=plaintext,
            output=encrypted,
            key_env="CONTENT_KEY",
            key_id=key_id,
            commit=commit,
        ))
        gate.create_target_manifest(argparse.Namespace(
            artifact=encrypted,
            plaintext_artifact=plaintext,
            encryption_key_id=key_id,
            output=manifest,
            version="2.1.207+main.g7777777",
            commit=commit,
            build_id=f"main-207-{commit}",
            artifact_url=(
                "https://updates.example.test/firmware/"
                f"gatekeeper-firmware-{commit}.sgkenc"
            ),
            published_at="2026-08-24T00:00:00Z",
            mandatory_after=None,
            signing_key_id="rfc8032-test-key-1",
            private_key_env="TEST_TARGET_SIGNING_SEED",
            expected_public_key_hex=TEST_PUBLIC,
            protocol_min=1,
            protocol_max=2,
        ))
      document = gate.load_json(manifest)
      self.assertEqual(document["schema_version"], 2)
      self.assertEqual(document["encryption_algorithm"], "AES-256-GCM")
      self.assertEqual(document["encryption_key_id"], key_id)
      self.assertEqual(document["plaintext_size"], len(plaintext.read_bytes()))
      self.assertEqual(
          document["plaintext_sha256"],
          hashlib.sha256(plaintext.read_bytes()).hexdigest(),
      )
      gate.verify_target_manifest(argparse.Namespace(
          manifest=manifest,
          artifact=encrypted,
          public_key_hex=TEST_PUBLIC,
          expected_version="2.1.207+main.g7777777",
          expected_commit=commit,
          expected_build_id=f"main-207-{commit}",
          expected_encryption_key_id=key_id,
      ))

  def test_target_artifact_url_rejects_embedded_credentials(self):
    with tempfile.TemporaryDirectory() as directory_name:
      directory = Path(directory_name)
      commit = "a" * 40
      with self.assertRaisesRegex(gate.GateError, "must not contain credentials"):
        _create_manifest(
            directory,
            "credentialed",
            "2.1.210+main.gaaaaaaa",
            commit,
            f"main-210-{commit}",
            b"firmware",
            artifact_url=(
                "https://user:password@updates.example.test/firmware/"
                f"gatekeeper-firmware-{commit}.bin"
            ),
        )

  def test_main_job_is_exact_and_commercial_gate_remains_separate(self):
    source = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    workflow = gate.load_workflow_yaml(".github/workflows/deploy.yml", source)
    compiler = workflow["jobs"]["build_personal_target_ota_firmware"]
    auto = workflow["jobs"]["publish_personal_target_ota"]
    commercial = workflow["jobs"]["release_to_production"]
    self.assertEqual(
        " ".join(str(auto["if"]).split()),
        "github.ref == 'refs/heads/main' && (github.event_name == 'push' || "
        "(github.event_name == 'workflow_dispatch' && inputs.release_target == 'canary'))",
    )
    self.assertEqual(auto["environment"], "personal-auto-ota")
    self.assertEqual(compiler["environment"], "personal-auto-ota")
    self.assertEqual(auto["needs"], "build_personal_target_ota_firmware")
    self.assertIn("git rev-list --count --first-parent HEAD", source)
    self.assertIn("2.1.${COMMIT_SEQUENCE}+main.g${SHORT_SHA}", source)
    self.assertIn('TARGET_BUILD_ID="main-${COMMIT_SEQUENCE}-${GITHUB_SHA}"', source)
    self.assertIn('SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$GITHUB_SHA")"', source)
    self.assertIn(
        "python -I -m pip install --require-hashes -r ota/requirements.lock",
        source,
    )
    self.assertIn(
        "python -I -m platformio run -e esp32c6_personal_production -t clean",
        source,
    )
    self.assertIn(
        "cmp dist/gatekeeper-firmware-first.bin "
        ".pio/build/esp32c6_personal_production/firmware.bin",
        source,
    )
    self.assertIn('version = os.environ["FULL_VERSION"].encode("ascii")', source)
    self.assertIn("if version not in firmware:", source)
    self.assertIn('PUBLISHED_AT="$(git show -s --format=%cI "$GITHUB_SHA")"', source)
    self.assertIn(
        "python -I -m platformio run -e esp32c6_personal_production", source
    )
    privileged_verify = next(
        step["run"] for step in compiler["steps"]
        if step["name"] == "Verify exact protected main before production secrets"
    )
    expected_build_rows = []
    for line in privileged_verify.splitlines():
      parts = line.strip().split()
      if (
          len(parts) == 3
          and parts[0] == "100644"
          and len(parts[1]) == 64
          and all(char in "0123456789abcdef" for char in parts[1])
      ):
        self.assertEqual(line, line.strip(), parts[2])
        expected_build_rows.append(parts)
    expected_build_paths = [row[2] for row in expected_build_rows]
    tracked_build_paths = subprocess.run(
        [
            "git", "ls-files", "--", "src", "include", "lib", "boards",
            "variants", "sitecustomize.py", "usercustomize.py",
            "platformio_override.ini", "platformio.ini",
            "partitions_16MB_ota.csv", "ota/requirements.lock",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    self.assertEqual(len(expected_build_rows), 45)
    self.assertEqual(expected_build_paths, sorted(expected_build_paths))
    self.assertEqual(expected_build_paths, tracked_build_paths)
    for _mode, expected_digest, path in expected_build_rows:
      normalized = (ROOT / path).read_bytes().replace(b"\r\n", b"\n").replace(
          b"\r", b"\n"
      )
      self.assertEqual(
          expected_digest,
          hashlib.sha256(normalized).hexdigest(),
          path,
      )
    self.assertNotIn("unittest", privileged_verify)
    self.assertNotIn("ota_contract_gate.py contract", privileged_verify)
    self.assertIn(
        "git ls-files --stage -- src include lib boards variants",
        privileged_verify,
    )
    self.assertIn(
        "sitecustomize.py usercustomize.py platformio_override.ini platformio.ini",
        privileged_verify,
    )
    self.assertIn(
        "partitions_16MB_ota.csv ota/requirements.lock |",
        privileged_verify,
    )
    self.assertIn("ota/requirements.lock |", privileged_verify)
    self.assertIn("git ls-files --others --exclude-standard", privileged_verify)
    self.assertIn('test -z "$UNEXPECTED_BUILD_INPUTS"', privileged_verify)
    self.assertIn("test ! -e .pio", privileged_verify)
    self.assertIn('test ! -L "$path"', privileged_verify)
    self.assertIn('stat -c \'%a\' -- "$path"', privileged_verify)
    self.assertIn('sha256sum -- "$path"', privileged_verify)
    self.assertNotIn('git show "$GITHUB_SHA:$path"', privileged_verify)
    self.assertIn(
        "5b8c5859426a7febd6bd9d9b0482bf78f8f4854c2d83d0ce53ba49c14c5cea12 ota/requirements.lock",
        privileged_verify,
    )
    self.assertIn(
        "20eb6e06d094abfa4436abf741fe21652e4b92ec076d24dbc0eac8e7d2ed88b4 partitions_16MB_ota.csv",
        privileged_verify,
    )
    self.assertIn(
        "a10ccb9f2216d8b46ab3869a20d228c4c39aa7630b5c672f01be97f8ce7ce839 platformio.ini",
        privileged_verify,
    )
    self.assertIn("src/OtaManager.cpp", privileged_verify)
    self.assertIn(
        "ce133f5fa6748fa7e6edd863e899c8e21d6a0da64563f353975e4800fb0e6c9b",
        privileged_verify,
    )
    self.assertIn("src/WifiManager.cpp", privileged_verify)
    self.assertIn(
        "d47d4462d071e51afad98c1bff32476ca67f5345314eb2975f857b5b0cea2b91",
        privileged_verify,
    )
    self.assertIn("include/RecoveryRadioPolicy.h", privileged_verify)
    self.assertIn(
        "8c0be800233019cf2edad1ffcec7d3d9eef9d1c85d0097f8ec78fdd62ee6a92d",
        privileged_verify,
    )
    self.assertIn("sitecustomize.py usercustomize.py", privileged_verify)
    materialize = next(
        step for step in compiler["steps"]
        if step["name"] == "Materialize personal Target production inputs"
    )
    materialize_text = str(materialize)
    for secret_name in (
        "SECRET_HARDWARELESS_DOOR_ID_HEX",
        "SECRET_ACCESS_EVENT_REF_KEY_HEX",
        "SECRET_ACCESS_EVENT_REF_KEY_ID",
        "SECRET_ACL_SIGNER_PUBLIC_KEY_HEX",
        "SECRET_ACL_SIGNING_KEY_ID",
    ):
      self.assertIn(secret_name, materialize_text)
    self.assertIn("^04[0-9a-f]{128}$", materialize_text)
    self.assertIn("^[0-9a-f]{32}$", materialize_text)
    self.assertIn("^[0-9a-f]{64}$", materialize_text)
    self.assertIn("^[a-z0-9]{1,4}$", materialize_text)
    self.assertIn("10#$SECRET_ACL_SIGNING_KEY_ID <= 4294967295", materialize_text)
    self.assertIn("esp32c6_personal_production", str(compiler))
    self.assertIn("esp32c6_personal_production", str(commercial))
    self.assertIn("personal-target-auto-20260823-1", str(compiler))
    self.assertIn(
        "65154566393ecfb249c8aceb637e3258e349eb36e4dbca0dd52d61a6e55cb61b",
        str(compiler),
    )
    self.assertEqual(auto["concurrency"]["cancel-in-progress"], False)
    self.assertNotIn("runtime-keyscan-unpinned", str(auto))
    self.assertIn("Verify exact Target OTA pointer and immutable artifact over HTTPS", source)
    self.assertIn("TARGET_ROOT_CA_CERT", source)
    self.assertIn("--cacert \"$CA_FILE\"", source)
    self.assertIn("--proto '=https' --proto-redir '=https'", source)
    self.assertNotIn("ota_contract_gate.py release", str(auto))
    self.assertIn("ota_contract_gate.py release", str(commercial))
    self.assertEqual(
        " ".join(str(commercial["if"]).split()),
        "false && github.event_name == 'workflow_dispatch' && "
        "inputs.release_target == 'production' && "
        "github.ref == 'refs/heads/main'",
    )
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
            "python -I scripts/ota_contract_gate.py target-sftp-publish",
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
        (
            'test "$ACTUAL_BUILD_TREE" = "$EXPECTED_BUILD_TREE"',
            "python -m unittest discover -s tests -p 'test_*.py' -v",
        ),
        (
            "personal-target-auto-20260823-1",
            "personal-legacy-target-20260812-1",
        ),
        (
            "65154566393ecfb249c8aceb637e3258e349eb36e4dbca0dd52d61a6e55cb61b",
            "87d8b43a994f1021feca0d7079658f02bee2eb2f5711e67b12d450f841af08c5",
        ),
        (
            "python -I -m platformio run -e "
            "esp32c6_personal_production -t clean",
            "python -I -m platformio run -e esp32c6_production -t clean",
        ),
        (
            '#define SECRET_HARDWARELESS_DOOR_ID_HEX '
            '"${SECRET_HARDWARELESS_DOOR_ID_HEX}"',
            '#define SECRET_HARDWARELESS_DOOR_ID_HEX ""',
        ),
        (
            '[[ "$SECRET_ACL_SIGNER_PUBLIC_KEY_HEX" =~ '
            '^04[0-9a-f]{128}$ ]]',
            "true # ACL signer format bypassed",
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
