#!/usr/bin/env python3
"""Validate OTA contracts and block releases without complete P0 evidence."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[1]
OTA = ROOT / "ota"
TEST_PUBLIC_KEY_HEX = (
    "d75a980182b10ab7d54bfed3c964073a"
    "0ee172f3daa62325af021a68f707511a"
)

STATE_MACHINE_REQUIREMENTS = {
    "target": {
        "initial": "IDLE",
        "terminal_success": "MARK_VALID",
        "states": {
            "IDLE", "WAIT_SAFE_STATE", "VERIFY_MANIFEST",
            "DOWNLOAD_INACTIVE_SLOT", "SET_PENDING_BOOT",
            "BOOT_HEALTH_WINDOW", "MARK_VALID", "ROLLBACK_PREVIOUS_SLOT",
        },
        "failure_preserves": {
            "active_slot", "previous_bootable_slot", "nvs_v_previous",
        },
        "invariants": {
            "relay_off_before_flash", "inactive_slot_only",
            "explicit_valid_mark", "health_timeout_rolls_back",
            "commands_rejected_with_ota_busy",
        },
    },
    "mobile": {
        "initial": "IDLE",
        "terminal_success": "COMPLETE",
        "states": {
            "IDLE", "CHECK_METADATA", "VERIFY_METADATA", "DOWNLOAD_TEMP",
            "VERIFY_APK", "REQUEST_PACKAGE_INSTALL",
            "NEW_APP_FIRST_RUN_HEALTH", "COMPLETE",
        },
        "failure_preserves": {
            "installed_apk", "credentials", "preferences_v_previous",
        },
        "invariants": {
            "scanner_independent", "webview_independent",
            "temporary_download", "sha256_before_installer",
            "signing_identity_before_installer",
        },
    },
}

RECOVERY_REQUIREMENTS = {
    "primary-endpoint-down": {
        "gate": "OTA-G3",
        "mobile": {
            "outcome": "secondary-path-available",
            "action": "use-secondary-https",
            "from_state": "CHECK_METADATA",
            "to_state": "CHECK_METADATA",
        },
        "target": {
            "outcome": "authenticated-recovery-available",
            "action": "retry-periodic-https-then-authenticated-local-ap",
            "from_state": "CHECK_MANIFEST",
            "to_state": "FAILED_RETRYABLE",
        },
    },
    "scanner-gatt-down": {
        "gate": "OTA-G1",
        "mobile": {
            "outcome": "update-control-available",
            "action": "cold-start-resume-settings-manual",
            "from_state": "IDLE",
            "to_state": "CHECK_METADATA",
        },
        "target": {
            "outcome": "ota-engine-available",
            "action": "continue-ota-independent-of-access",
            "from_state": "IDLE",
            "to_state": "IDLE",
        },
    },
    "mqtt-down": {
        "gate": "OTA-G1",
        "mobile": {
            "outcome": "unaffected",
            "action": "none",
            "from_state": "IDLE",
            "to_state": "IDLE",
        },
        "target": {
            "outcome": "authenticated-recovery-available",
            "action": "use-periodic-https-or-authenticated-local-ap",
            "from_state": "IDLE",
            "to_state": "UPDATE_REQUESTED",
        },
    },
    "download-interrupted": {
        "gate": "OTA-G1",
        "mobile": {
            "outcome": "installed-apk-preserved",
            "action": "discard-or-resume-temp",
            "from_state": "DOWNLOAD_TEMP",
            "to_state": "CHECK_METADATA",
        },
        "target": {
            "outcome": "active-slot-preserved",
            "action": "discard-or-resume-inactive-slot",
            "from_state": "DOWNLOAD_INACTIVE_SLOT",
            "to_state": "FAILED_RETRYABLE",
        },
    },
    "hash-signature-invalid": {
        "gate": "OTA-G0",
        "mobile": {
            "outcome": "installer-not-invoked",
            "action": "reject-before-installer",
            "from_state": "VERIFY_APK",
            "to_state": "IDLE",
        },
        "target": {
            "outcome": "image-not-selected",
            "action": "reject-before-boot-selection",
            "from_state": "VERIFY_IMAGE",
            "to_state": "FAILED_RETRYABLE",
        },
    },
    "power-loss": {
        "gate": "OTA-G3",
        "mobile": {
            "outcome": "installed-apk-preserved",
            "action": "retain-installed-apk",
            "from_state": "DOWNLOAD_TEMP",
            "to_state": "IDLE",
        },
        "target": {
            "outcome": "previous-slot-booted",
            "action": "boot-previous-slot",
            "from_state": "SET_PENDING_BOOT",
            "to_state": "ROLLBACK_PREVIOUS_SLOT",
        },
    },
    "new-version-crash": {
        "gate": "OTA-G3",
        "mobile": {
            "outcome": "stable-fallback-available",
            "action": "use-stable-fallback",
            "from_state": "NEW_APP_FIRST_RUN_HEALTH",
            "to_state": "INSTALL_FAILED",
        },
        "target": {
            "outcome": "rollback-completed",
            "action": "rollback-on-health-timeout",
            "from_state": "BOOT_HEALTH_WINDOW",
            "to_state": "ROLLBACK_PREVIOUS_SLOT",
        },
    },
    "n-minus-one": {
        "gate": "OTA-G2",
        "mobile": {
            "outcome": "n-minus-one-compatible",
            "action": "negotiate-legacy",
            "from_state": "COMPARE_COMPATIBILITY",
            "to_state": "CHECK_STORAGE",
        },
        "target": {
            "outcome": "n-minus-one-compatible",
            "action": "retain-ota-and-previous-protocol",
            "from_state": "IDLE",
            "to_state": "UPDATE_REQUESTED",
        },
    },
    "storage-full": {
        "gate": "OTA-G1",
        "mobile": {
            "outcome": "storage-recovery-guidance",
            "action": "show-storage-guidance",
            "from_state": "CHECK_STORAGE",
            "to_state": "IDLE",
        },
        "target": {
            "outcome": "active-slot-and-nvs-preserved",
            "action": "retain-active-slot-and-nvs",
            "from_state": "DOWNLOAD_INACTIVE_SLOT",
            "to_state": "FAILED_RETRYABLE",
        },
    },
}

FAULT_REQUIREMENTS = {
    "FI-01": ("active-artifact-preserved", False),
    "FI-02": ("digest-rejected-before-install-or-boot", False),
    "FI-03": ("metadata-rejected", False),
    "FI-04": ("target-periodic-https-reachable", True),
    "FI-05": ("previous-slot-boots-relay-off", True),
    "FI-06": ("rollback-before-valid-mark", True),
    "FI-07": ("settings-update-path-available", True),
    "FI-08": ("secondary-mobile-path-installs", True),
    "FI-09": ("installer-not-invoked", True),
    "FI-10": ("update-planes-and-access-compatible", True),
}

WORKFLOW_ARTIFACT_BINDINGS = {
    ".github/workflows/deploy.yml": {
        "build_job": "test_and_build",
        "release_job": "release_to_production",
        "canary_name": "target-canary",
        "artifact": "dist/gatekeeper-firmware.bin",
        "build_copy": (
            "cp .pio/build/esp32c6/firmware.bin "
            "dist/gatekeeper-firmware.bin"
        ),
    },
    ".github/workflows/build_app.yml": {
        "build_job": "build_apk",
        "release_job": "release_to_production",
        "canary_name": "smart-key-app-canary",
        "artifact": "dist/ks-house-gatekeeper.apk",
        "build_copy": (
            "cp gatekeeper_app/build/app/outputs/flutter-apk/app-release.apk "
            "dist/ks-house-gatekeeper.apk"
        ),
    },
}


class GateError(RuntimeError):
  """A release-contract violation."""


def load_json(path: Path) -> dict[str, Any]:
  with path.open(encoding="utf-8") as handle:
    value = json.load(handle)
  if not isinstance(value, dict):
    raise GateError(f"{path}: top-level JSON value must be an object")
  return value


def validate_document_schema(
    document: dict[str, Any], schema_name: str, label: str
) -> None:
  schema = load_json(OTA / "schemas" / schema_name)
  errors = sorted(
      Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
          document
      ),
      key=lambda error: list(error.path),
  )
  if errors:
    detail = "; ".join(error.message for error in errors)
    raise GateError(f"{label}: schema validation failed: {detail}")


def canonical_signed_bytes(manifest: dict[str, Any]) -> bytes:
  """Return sgk-json-v1 bytes: scalar manifest fields, sorted, no whitespace."""
  payload = {key: value for key, value in manifest.items() if key != "signature"}
  if any(isinstance(value, (dict, list, float)) for value in payload.values()):
    raise GateError("sgk-json-v1 permits only string, integer, boolean, or null fields")
  return json.dumps(
      payload,
      ensure_ascii=False,
      allow_nan=False,
      sort_keys=True,
      separators=(",", ":"),
  ).encode("utf-8")


def validate_manifest(
    manifest: dict[str, Any], schema_name: str, public_key_hex: str
) -> None:
  validate_document_schema(manifest, schema_name, schema_name)

  if manifest["protocol_min"] > manifest["protocol_max"]:
    raise GateError("protocol_min must not exceed protocol_max")

  if manifest["artifact_type"] == "target-firmware":
    if manifest["version"] != manifest["firmware_version"]:
      raise GateError("target version legacy alias must equal firmware_version")
  elif manifest["artifact_type"] == "android-apk":
    if manifest["version"] != manifest["version_name"]:
      raise GateError("mobile version legacy alias must equal version_name")
    if manifest["build_number"] != manifest["version_code"]:
      raise GateError("mobile build_number legacy alias must equal version_code")
    if manifest["apk_url"] == manifest["fallback_url"]:
      raise GateError("mobile fallback_url must be independent from apk_url")

  try:
    signature = base64.b64decode(manifest["signature"], validate=True)
    public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
    public_key.verify(signature, canonical_signed_bytes(manifest))
  except (InvalidSignature, ValueError) as exc:
    raise GateError("Ed25519 manifest signature verification failed") from exc


def validate_partitions() -> None:
  path = ROOT / "partitions_16MB_ota.csv"
  with path.open(encoding="utf-8", newline="") as handle:
    rows = {
        row[0].strip(): row
        for row in csv.reader(line for line in handle if not line.startswith("#"))
        if row
    }
  required = {"otadata", "app0", "app1"}
  if not required.issubset(rows):
    raise GateError("16MB partition table must contain otadata, app0, and app1")
  if rows["app0"][2].strip() != "ota_0" or rows["app1"][2].strip() != "ota_1":
    raise GateError("app0/app1 must use ota_0/ota_1 subtypes")
  if int(rows["app0"][4], 0) != int(rows["app1"][4], 0):
    raise GateError("dual OTA slots must have equal capacity")


def _validate_exact_string_set(
    actual_value: Any, expected: set[str], label: str
) -> None:
  if not isinstance(actual_value, list) or not all(
      isinstance(value, str) for value in actual_value
  ):
    raise GateError(f"{label} must be a string array")
  actual = set(actual_value)
  missing = expected - actual
  unexpected = actual - expected
  duplicate_count = len(actual_value) - len(actual)
  if missing or unexpected or duplicate_count:
    raise GateError(
        f"{label} must equal the required set; missing={sorted(missing)}, "
        f"unexpected={sorted(unexpected)}, duplicates={duplicate_count}"
    )


def validate_state_machines(
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
  if document is None:
    document = load_json(OTA / "state-machines.json")
  validate_document_schema(
      document, "state-machines.schema.json", "state-machines.json"
  )
  for component, requirements in STATE_MACHINE_REQUIREMENTS.items():
    component_document = document[component]
    actual_states = set(component_document["states"])
    missing = requirements["states"] - actual_states
    if missing:
      raise GateError(f"{component} state machine missing: {sorted(missing)}")
    for scalar in ("initial", "terminal_success"):
      if component_document[scalar] != requirements[scalar]:
        raise GateError(
            f"{component} {scalar} must be {requirements[scalar]}"
        )
      if component_document[scalar] not in actual_states:
        raise GateError(f"{component} {scalar} must name a declared state")
    for collection in ("failure_preserves", "invariants"):
      _validate_exact_string_set(
          component_document[collection],
          requirements[collection],
          f"{component}.{collection}",
      )
  return document


def validate_recovery_and_faults(
    recovery: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    state_machines: dict[str, Any] | None = None,
) -> None:
  if recovery is None:
    recovery = load_json(OTA / "recovery-matrix.json")
  if plan is None:
    plan = load_json(OTA / "fault-injection-plan.json")
  if state_machines is None:
    state_machines = validate_state_machines()

  validate_document_schema(
      recovery, "recovery-matrix.schema.json", "recovery-matrix.json"
  )
  rows = recovery["rows"]
  rows_by_id = {row["id"]: row for row in rows}
  if len(rows_by_id) != len(rows):
    raise GateError("recovery matrix IDs must be unique")
  actual_ids = set(rows_by_id)
  expected_ids = set(RECOVERY_REQUIREMENTS)
  if actual_ids != expected_ids:
    raise GateError(
        "recovery matrix IDs must equal the required set; "
        f"missing={sorted(expected_ids - actual_ids)}, "
        f"unexpected={sorted(actual_ids - expected_ids)}"
    )
  for recovery_id, expected in RECOVERY_REQUIREMENTS.items():
    actual = {key: value for key, value in rows_by_id[recovery_id].items()
              if key != "id"}
    if actual != expected:
      raise GateError(f"recovery {recovery_id} does not match required semantics")
    for component in ("mobile", "target"):
      declared_states = set(state_machines[component]["states"])
      transition = actual[component]
      if transition["from_state"] not in declared_states:
        raise GateError(
            f"recovery {recovery_id} {component} from_state is not declared"
        )
      if transition["to_state"] not in declared_states:
        raise GateError(
            f"recovery {recovery_id} {component} to_state is not declared"
        )

  validate_document_schema(
      plan, "fault-injection-plan.schema.json", "fault-injection-plan.json"
  )
  tests = plan["tests"]
  tests_by_id = {test["id"]: test for test in tests}
  if len(tests_by_id) != len(tests):
    raise GateError("fault plan IDs must be unique")
  actual_fault_ids = set(tests_by_id)
  expected_fault_ids = set(FAULT_REQUIREMENTS)
  if actual_fault_ids != expected_fault_ids:
    raise GateError(
        "fault plan IDs must equal the required set; "
        f"missing={sorted(expected_fault_ids - actual_fault_ids)}, "
        f"unexpected={sorted(actual_fault_ids - expected_fault_ids)}"
    )
  for fault_id, (expected_outcome, physical_gate) in FAULT_REQUIREMENTS.items():
    test = tests_by_id[fault_id]
    if test["expected"] != expected_outcome:
      raise GateError(f"fault {fault_id} expected outcome is not fail-safe")
    if test["physical_gate"] is not physical_gate:
      raise GateError(f"fault {fault_id} physical_gate classification changed")


def validate_vectors() -> None:
  vectors = [
      ("target-valid.json", "target-manifest.schema.json", True),
      ("target-tampered.json", "target-manifest.schema.json", False),
      ("mobile-valid.json", "mobile-manifest.schema.json", True),
      ("mobile-tampered.json", "mobile-manifest.schema.json", False),
  ]
  for filename, schema, should_pass in vectors:
    manifest = load_json(OTA / "test-vectors" / filename)
    try:
      validate_manifest(manifest, schema, TEST_PUBLIC_KEY_HEX)
    except GateError:
      if should_pass:
        raise
    else:
      if not should_pass:
        raise GateError(f"negative test vector unexpectedly passed: {filename}")


def load_workflow_yaml(path: str | Path, content: str | None = None) -> dict[str, Any]:
  if content is None:
    path_obj = Path(path)
    if not path_obj.is_absolute():
      path_obj = ROOT / path_obj
    content = path_obj.read_text(encoding="utf-8")
  parsed = yaml.safe_load(content)
  if not isinstance(parsed, dict):
    raise GateError(f"{path}: workflow YAML must be a top-level mapping")
  if True in parsed and "on" not in parsed:
    parsed["on"] = parsed.pop(True)
  return parsed


def validate_workflow_artifact_bindings(
    workflows: dict[str, str] | None = None,
) -> None:
  if workflows is None:
    workflows = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in WORKFLOW_ARTIFACT_BINDINGS
    }
  for path, binding in WORKFLOW_ARTIFACT_BINDINGS.items():
    content = workflows.get(path, "")
    parsed = load_workflow_yaml(path, content)
    jobs = parsed.get("jobs", {})
    build_job = jobs.get(binding["build_job"], {})
    release_job = jobs.get(binding["release_job"], {})

    build_steps = build_job.get("steps", [])
    copy_found = False
    for step in build_steps:
      run_cmd = str(step.get("run", ""))
      if binding["build_copy"] in run_cmd or binding["artifact"] in run_cmd:
        copy_found = True
        break
    if not copy_found:
      raise GateError(
          f"{path}: release Gate and upload artifact binding missing artifact copy in build job"
      )

    release_steps = release_job.get("steps", [])
    evidence_found = False
    evidence_idx = None
    sftp_idx = None

    for idx, step in enumerate(release_steps):
      run_cmd = str(step.get("run", ""))
      uses_action = str(step.get("uses", ""))

      if "python scripts/ota_contract_gate.py release" in run_cmd:
        if f"--artifact {binding['artifact']}" in run_cmd and "--manifest dist/version.json" in run_cmd:
          evidence_found = True
          evidence_idx = idx
      if "wlixcc/SFTP-Deploy-Action" in uses_action:
        sftp_idx = idx

    if not evidence_found:
      raise GateError(
          f"{path}: release Gate and upload artifact binding missing: artifact binding for {binding['artifact']}"
      )

    if evidence_idx is not None and sftp_idx is not None:
      if sftp_idx != evidence_idx + 1:
        raise GateError(
            f"{path}: immutable release steps order violated between release validation and SFTP deploy"
        )


def validate_workflow_release_triggers(
    workflows: dict[str, str] | None = None,
) -> None:
  """Keep ordinary CI green while production remains explicit and fail-closed."""
  if workflows is None:
    workflows = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in WORKFLOW_ARTIFACT_BINDINGS
    }

  expected_authorized_condition = (
      "github.event_name == 'workflow_dispatch' && "
      "inputs.release_target == 'production'"
  )

  for path, binding in WORKFLOW_ARTIFACT_BINDINGS.items():
    content = workflows.get(path, "")
    parsed = load_workflow_yaml(path, content)

    all_jobs = parsed.get("jobs", {})
    if not isinstance(all_jobs, dict):
      raise GateError(f"{path}: workflow missing jobs mapping")

    sftp_step_count = 0
    for jname, jbody in all_jobs.items():
      if not isinstance(jbody, dict):
        continue
      if jname != binding["release_job"]:
        if "environment" in jbody:
          raise GateError(f"{path}: build job must not use production environment or specify environment (string or object)")

      for st in jbody.get("steps", []):
        if not isinstance(st, dict):
          continue
        u = str(st.get("uses", ""))
        r = str(st.get("run", ""))
        if "wlixcc/SFTP-Deploy-Action" in u:
          sftp_step_count += 1
        if jname != binding["release_job"]:
          if "wlixcc/SFTP-Deploy-Action" in u or "python scripts/ota_contract_gate.py release" in r:
            raise GateError(f"{path}: ordinary push or PR build contains production or SFTP deployment capability")
          if re.search(r'\b(sftp|scp|rsync|ssh)\b|curl\s+.*-T', r):
            raise GateError(f"{path}: ordinary push or PR build contains production or SFTP deployment capability")

    if sftp_step_count != 1:
      raise GateError(f"{path}: workflow must contain exactly one SFTP deploy step")

    triggers = parsed.get("on")
    if not isinstance(triggers, dict):
      raise GateError(f"{path}: workflow triggers ('on') must be a mapping")

    if "pull_request" not in triggers:
      raise GateError(f"{path}: workflow missing pull_request trigger")
    if "push" not in triggers:
      raise GateError(f"{path}: workflow missing push trigger")
    if "workflow_dispatch" not in triggers:
      raise GateError(f"{path}: explicit production release trigger missing: workflow_dispatch")

    dispatch_input = (
        triggers.get("workflow_dispatch", {})
        .get("inputs", {})
        .get("release_target", {})
    )
    if not isinstance(dispatch_input, dict) or dispatch_input.get("type") != "choice":
      raise GateError(f"{path}: explicit production release trigger missing release_target choice input")
    options = dispatch_input.get("options", [])
    if "canary" not in options or "production" not in options:
      raise GateError(f"{path}: release_target options must include canary and production")

    build_job_name = binding["build_job"]
    release_job_name = binding["release_job"]

    if build_job_name not in all_jobs:
      raise GateError(f"{path}: missing workflow job {build_job_name}")
    if release_job_name not in all_jobs:
      raise GateError(f"{path}: missing workflow job {release_job_name}")

    build_job = all_jobs[build_job_name]
    release_job = all_jobs[release_job_name]

    build_steps = build_job.get("steps", [])
    if not isinstance(build_steps, list):
      raise GateError(f"{path}: build job steps must be a list")

    has_contract_step = False
    has_test_step = False
    has_canary_upload_step = False

    for step in build_steps:
      run_cmd = str(step.get("run", ""))
      uses_action = str(step.get("uses", ""))

      if "python scripts/ota_contract_gate.py contract" in run_cmd:
        has_contract_step = True
      if "python -m unittest discover" in run_cmd or "pytest" in run_cmd:
        has_test_step = True
      if "actions/upload-artifact" in uses_action:
        step_with = step.get("with", {})
        if isinstance(step_with, dict) and step_with.get("name") == binding["canary_name"]:
          has_canary_upload_step = True

    if not has_contract_step or not has_test_step or not has_canary_upload_step:
      missing = []
      if not has_contract_step: missing.append("ota_contract_gate.py contract")
      if not has_test_step: missing.append("unittest discover")
      if not has_canary_upload_step: missing.append(f"upload-artifact {binding['canary_name']}")
      raise GateError(f"{path}: ordinary build/test contract missing: {missing}")

    needs = release_job.get("needs")
    if isinstance(needs, list):
      if build_job_name not in needs:
        raise GateError(f"{path}: release job needs must include {build_job_name}")
    elif needs != build_job_name:
      raise GateError(f"{path}: release job needs must include {build_job_name}")

    rel_env = release_job.get("environment")
    if not isinstance(rel_env, str) or rel_env != "production":
      raise GateError(f"{path}: release job environment must be exact string 'production'")

    release_if = release_job.get("if")
    if not release_if:
      raise GateError(f"{path}: production job lacks authorized production trigger")

    normalized_release_if = " ".join(str(release_if).split())
    if "workflow_dispatch" not in normalized_release_if or "release_target" not in normalized_release_if:
      raise GateError(f"{path}: production job lacks authorized production trigger")

    if normalized_release_if != expected_authorized_condition:
      raise GateError(
          f"{path}: release job condition is extended or modified; "
          f"must be exact production condition (got: '{normalized_release_if}')"
      )

    release_steps = release_job.get("steps", [])
    if not isinstance(release_steps, list):
      raise GateError(f"{path}: release job steps must be a list")

    evidence_step_index = None
    sftp_step_index = None

    for idx, step in enumerate(release_steps):
      run_cmd = str(step.get("run", ""))
      uses_action = str(step.get("uses", ""))

      if "python scripts/ota_contract_gate.py release" in run_cmd:
        evidence_step_index = idx

        if "continue-on-error" in step:
          if step["continue-on-error"] is not False and str(step["continue-on-error"]).lower() != "false":
            raise GateError(f"{path}: evidence step cannot specify continue-on-error")

        if "if" in step:
          raise GateError(f"{path}: evidence step cannot be conditionally disabled or bypassed")

        if "|| true" in run_cmd or "; true" in run_cmd or "set +e" in run_cmd or "|| exit" in run_cmd or "|| echo" in run_cmd or "|| :" in run_cmd or "; :" in run_cmd:
          raise GateError(f"{path}: evidence step release command must not swallow errors or suppress non-zero exit code")

        cmd_parts = run_cmd.split("python scripts/ota_contract_gate.py release")
        after_release = cmd_parts[-1]
        lines_after = after_release.splitlines()
        if len(lines_after) > 1:
          prev_continued = True
          for line in lines_after[1:]:
            sline = line.strip()
            if not sline or sline.startswith("#"):
              continue
            if not prev_continued and not sline.startswith("-"):
              raise GateError(f"{path}: immutable artifact identity violated: evidence step run script cannot alter artifacts after validation")
            prev_continued = sline.endswith("\\")

        if re.search(r'\bOTA_SIGNING_PUBLIC_KEY_HEX\s*=', run_cmd):
          raise GateError(f"{path}: signing key must come exactly from step env secret, cannot be redefined in run script")

        step_env = step.get("env", {})
        if not isinstance(step_env, dict) or step_env.get("OTA_SIGNING_PUBLIC_KEY_HEX") != "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}":
          raise GateError(
              f"{path}: production signing secret provenance invalid; "
              f"OTA_SIGNING_PUBLIC_KEY_HEX must come exactly from production signing secret"
          )

        if '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"' not in run_cmd:
          raise GateError(
              f"{path}: production release isolation violation: evidence validation must use pinned secret --public-key-hex \"$OTA_SIGNING_PUBLIC_KEY_HEX\""
          )
        if "--evidence ota/release-evidence.json" not in run_cmd or "--manifest dist/version.json" not in run_cmd:
          raise GateError(f"{path}: release evidence validation step missing required flags")
        if f"--artifact {binding['artifact']}" not in run_cmd:
          raise GateError(f"{path}: release Gate and upload artifact binding missing or mismatched")

      elif "wlixcc/SFTP-Deploy-Action" in uses_action:
        sftp_step_index = idx
        step_with = step.get("with", {})
        if not isinstance(step_with, dict) or step_with.get("local_path") != "./dist/*":
          raise GateError(f"{path}: SFTP deploy local_path must be strictly './dist/*'")

    if evidence_step_index is None:
      raise GateError(f"{path}: release evidence validation step missing in release job")
    if sftp_step_index is None:
      raise GateError(f"{path}: production release isolation missing: SFTP deploy step missing")

    if sftp_step_index != evidence_step_index + 1:
      raise GateError(
          f"{path}: immutable release steps order violated: SFTP deploy step (index {sftp_step_index}) "
          f"must immediately follow release evidence step (index {evidence_step_index}) with no intermediate steps"
      )

    if sftp_step_index != len(release_steps) - 1:
      raise GateError(f"{path}: immutable release steps order violated: no steps allowed after SFTP deploy step")




def validate_contract() -> None:
  validate_partitions()
  state_machines = validate_state_machines()
  validate_recovery_and_faults(state_machines=state_machines)
  validate_vectors()
  validate_workflow_artifact_bindings()
  validate_workflow_release_triggers()


def validate_release_evidence(path: Path) -> None:
  evidence = load_json(path)
  gates = {gate.get("id"): gate for gate in evidence.get("gates", [])}
  required = {f"OTA-G{index}" for index in range(5)}
  if missing := required - set(gates):
    raise GateError(f"release evidence missing gates: {sorted(missing)}")
  incomplete = sorted(
      gate_id for gate_id in required if gates[gate_id].get("status") != "passed"
  )
  if evidence.get("release_blocked") is not False or incomplete:
    raise GateError(f"production OTA release blocked; incomplete gates: {incomplete}")
  if evidence.get("physical_tests") != "passed":
    raise GateError("production OTA release requires passed physical tests")
  if not evidence.get("approved_by") or not evidence.get("approved_at"):
    raise GateError("production OTA release requires dated operator approval")


def _artifact_size_and_sha256(path: Path) -> tuple[int, str]:
  if not path.is_file():
    raise GateError(f"release artifact is missing or not a file: {path}")
  digest = hashlib.sha256()
  size = 0
  with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
      size += len(chunk)
      digest.update(chunk)
  return size, digest.hexdigest()


def _resolve_apksigner(explicit_path: Path | None) -> Path:
  if explicit_path is not None:
    if explicit_path.is_file():
      return explicit_path
    raise GateError(f"apksigner is missing or not a file: {explicit_path}")
  if executable := shutil.which("apksigner"):
    return Path(executable)
  executable_name = "apksigner.bat" if os.name == "nt" else "apksigner"
  for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
    if not (sdk_root := os.environ.get(variable)):
      continue
    candidates = sorted(
        (Path(sdk_root) / "build-tools").glob(f"*/{executable_name}"),
        reverse=True,
    )
    if candidates:
      return candidates[0]
  raise GateError("Android release validation requires apksigner")


def read_apk_signing_certificate_digests(
    artifact_path: Path, apksigner_path: Path | None = None
) -> set[str]:
  executable = _resolve_apksigner(apksigner_path)
  result = subprocess.run(
      [str(executable), "verify", "--print-certs", str(artifact_path)],
      check=False,
      capture_output=True,
      text=True,
      encoding="utf-8",
      errors="replace",
  )
  if result.returncode != 0:
    raise GateError("APK signature verification failed")
  digests = {
      match.lower()
      for match in re.findall(
          r"certificate SHA-256 digest:\s*([0-9a-fA-F]{64})",
          result.stdout + result.stderr,
      )
  }
  if not digests:
    raise GateError("apksigner did not report an APK signing certificate digest")
  return digests


def validate_release_manifests(
    manifest_paths: list[Path],
    artifact_paths: list[Path],
    public_key_hex: str,
    apksigner_path: Path | None = None,
) -> None:
  if not re.fullmatch(r"[0-9a-f]{64}", public_key_hex):
    raise GateError("production Ed25519 public key must be 32-byte lowercase hex")
  if not manifest_paths or len(manifest_paths) != len(artifact_paths):
    raise GateError("each release manifest requires exactly one artifact path")
  schemas = {
      "target-firmware": "target-manifest.schema.json",
      "android-apk": "mobile-manifest.schema.json",
  }
  for manifest_path, artifact_path in zip(manifest_paths, artifact_paths):
    manifest = load_json(manifest_path)
    artifact_type = manifest.get("artifact_type")
    if artifact_type not in schemas:
      raise GateError(f"{manifest_path}: unsupported or missing artifact_type")
    validate_manifest(manifest, schemas[artifact_type], public_key_hex)
    actual_size, actual_sha256 = _artifact_size_and_sha256(artifact_path)
    size_field = "artifact_size" if artifact_type == "target-firmware" else "apk_size"
    if actual_size != manifest[size_field]:
      raise GateError(
          f"{artifact_path}: byte length does not match signed {size_field}"
      )
    if actual_sha256 != manifest["sha256"]:
      raise GateError(f"{artifact_path}: SHA-256 does not match signed manifest")
    if artifact_type == "android-apk":
      actual_certificates = read_apk_signing_certificate_digests(
          artifact_path, apksigner_path
      )
      expected_certificate = manifest["signing_certificate_digest"]
      if actual_certificates != {expected_certificate}:
        raise GateError(
            f"{artifact_path}: APK signing certificate digest mismatch"
        )


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  subparsers = parser.add_subparsers(dest="command", required=True)
  subparsers.add_parser("contract", help="validate schemas, vectors and invariants")
  release = subparsers.add_parser("release", help="enforce all production gates")
  release.add_argument(
      "--evidence", type=Path, default=OTA / "release-evidence.json"
  )
  release.add_argument("--manifest", action="append", type=Path, required=True)
  release.add_argument("--artifact", action="append", type=Path, required=True)
  release.add_argument("--apksigner", type=Path)
  release.add_argument("--public-key-hex", required=True)
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  try:
    validate_contract()
    if args.command == "release":
      validate_release_evidence(args.evidence)
      validate_release_manifests(
          args.manifest, args.artifact, args.public_key_hex, args.apksigner
      )
  except (GateError, OSError, json.JSONDecodeError) as exc:
    print(f"[OTA-GATE] FAIL: {exc}", file=sys.stderr)
    return 1
  print(f"[OTA-GATE] PASS: {args.command}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
