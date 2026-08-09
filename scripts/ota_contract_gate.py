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
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
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


ALLOWED_BUILD_ACTIONS = {
    "actions/checkout@v4",
    "actions/setup-python@v5",
    "actions/setup-java@v4",
    "subosito/flutter-action@v2",
    "actions/upload-artifact@v4",
}

CANONICAL_RELEASE_STEPS = {
    ".github/workflows/deploy.yml": [
        {
            "name": "Checkout exact main source",
            "uses": "actions/checkout@v4",
            "with": {
                "ref": "${{ github.sha }}",
                "persist-credentials": False,
            },
        },
        {
            "name": "Set up Python",
            "uses": "actions/setup-python@v5",
            "with": {"python-version": "3.10"},
        },
        {
            "name": "Install PlatformIO and OTA release gate dependencies",
            "run": (
                "python -m pip install --upgrade pip\n"
                "pip install platformio -r ota/requirements.txt\n"
            ),
        },
        {
            "name": "Verify exact protected main release source",
            "main_source_verification": True,
        },
        {
            "name": "Create production firmware build secrets",
            "target_build_secrets": True,
            "env": {
                "SECRET_ROOT_CA_CERT": "${{ secrets.SECRET_ROOT_CA_CERT }}",
                "SECRET_WIFI_SSID": "${{ secrets.SECRET_WIFI_SSID }}",
                "SECRET_WIFI_PASSWORD": "${{ secrets.SECRET_WIFI_PASSWORD }}",
                "SECRET_API_URL": "${{ secrets.SECRET_API_URL }}",
                "SECRET_API_KEY": "${{ secrets.SECRET_API_KEY }}",
                "SECRET_MQTT_HOST": "${{ secrets.SECRET_MQTT_HOST }}",
                "SECRET_MQTT_PORT": "${{ secrets.SECRET_MQTT_PORT }}",
                "SECRET_MQTT_USER": "${{ secrets.SECRET_MQTT_USER }}",
                "SECRET_MQTT_PASSWORD": "${{ secrets.SECRET_MQTT_PASSWORD }}",
                "SECRET_TARGET_TENANT_ID": "${{ secrets.SECRET_TARGET_TENANT_ID }}",
                "SECRET_TARGET_DOOR_ID": "${{ secrets.SECRET_TARGET_DOOR_ID }}",
                "SECRET_COMMAND_SIGNER_PUBLIC_KEY_HEX": "${{ secrets.SECRET_COMMAND_SIGNER_PUBLIC_KEY_HEX }}",
                "SECRET_COMMAND_SIGNING_KEY_ID": "${{ secrets.SECRET_COMMAND_SIGNING_KEY_ID }}",
                "SECRET_ACL_SIGNER_PUBLIC_KEY_HEX": "${{ secrets.SECRET_ACL_SIGNER_PUBLIC_KEY_HEX }}",
                "SECRET_ACL_SIGNING_KEY_ID": "${{ secrets.SECRET_ACL_SIGNING_KEY_ID }}",
                "SECRET_OTA_VERSION_URL": "${{ secrets.SECRET_OTA_VERSION_URL }}",
                "SECRET_OTA_FIRMWARE_URL": "${{ secrets.SECRET_OTA_FIRMWARE_URL }}",
                "SECRET_OTA_SIGNER_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
                "SECRET_OTA_SIGNING_KEY_ID": "${{ secrets.OTA_SIGNING_KEY_ID }}",
                "SECRET_LOCAL_RECOVERY_AP_PASSWORD": "${{ secrets.SECRET_LOCAL_RECOVERY_AP_PASSWORD }}",
                "SECRET_LOCAL_RECOVERY_USER": "${{ secrets.SECRET_LOCAL_RECOVERY_USER }}",
                "SECRET_LOCAL_RECOVERY_PASSWORD": "${{ secrets.SECRET_LOCAL_RECOVERY_PASSWORD }}",
            },
        },
        {
            "name": "Build exact production firmware",
            "target_production_build": True,
        },
        {
            "name": "Create production signed Target manifest",
            "target_manifest_producer": True,
            "env": {
                "TARGET_ARTIFACT_URL": "${{ secrets.SECRET_OTA_FIRMWARE_URL }}",
                "TARGET_PRIVATE_KEY_HEX": "${{ secrets.OTA_SIGNING_PRIVATE_KEY_HEX }}",
                "TARGET_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
                "TARGET_SIGNING_KEY_ID": "${{ secrets.OTA_SIGNING_KEY_ID }}",
            },
        },
        {
            "name": "Enforce OTA production release evidence",
            "env": {"OTA_SIGNING_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}"},
            "run_prefix": "python scripts/ota_contract_gate.py release",
            "artifact": "dist/gatekeeper-firmware.bin",
        },
        {
            "name": "Deploy to Synology NAS via SFTP",
            "uses": "wlixcc/SFTP-Deploy-Action@v1.2.4",
            "with": {
                "server": "${{ secrets.NAS_HOST }}",
                "username": "${{ secrets.NAS_USER }}",
                "password": "${{ secrets.NAS_PASSWORD }}",
                "port": "${{ secrets.NAS_PORT || 22 }}",
                "local_path": "./dist/*",
                "remote_path": "${{ secrets.NAS_TARGET_DIR || '/docker/smart-gatekeeper-ota/' }}",
                "sftp_only": True,
            },
        },
    ],
    ".github/workflows/build_app.yml": [
        {
            "name": "Checkout exact main source",
            "uses": "actions/checkout@v4",
            "with": {
                "ref": "${{ github.sha }}",
                "persist-credentials": False,
            },
        },
        {
            "name": "Set up Java JDK 17 for trusted APK inspection",
            "uses": "actions/setup-java@v4",
            "with": {"distribution": "temurin", "java-version": "17"},
        },
        {
            "name": "Set up Python for OTA release gate",
            "uses": "actions/setup-python@v5",
            "with": {
                "python-version": "3.12",
                "cache": "pip",
                "cache-dependency-path": "ota/requirements.txt",
            },
        },
        {
            "name": "Set up Flutter SDK for exact main release",
            "uses": "subosito/flutter-action@v2",
            "with": {"channel": "stable", "cache": True},
        },
        {
            "name": "Install exact main release dependencies",
            "run": (
                "python -m pip install -r ota/requirements.txt\n"
                "cd gatekeeper_app\n"
                "flutter pub get\n"
            ),
        },
        {
            "name": "Verify exact protected main release source",
            "main_source_verification": True,
        },
        {
            "name": "Restore production Android keystore",
            "android_keystore": True,
            "env": {
                "KEYSTORE_BASE64": "${{ secrets.ANDROID_KEYSTORE_BASE64 }}",
            },
        },
        {
            "name": "Create production Android signing properties",
            "android_signing_properties": True,
            "env": {
                "KEYSTORE_PASSWORD": "${{ secrets.ANDROID_KEYSTORE_PASSWORD }}",
                "KEY_ALIAS": "${{ secrets.ANDROID_KEY_ALIAS }}",
            },
        },
        {
            "name": "Build exact production Android APK",
            "android_production_build": True,
            "env": {
                "APK_VERSION_URL": "${{ secrets.SECRET_APK_VERSION_URL }}",
                "APK_FALLBACK_VERSION_URL": "${{ secrets.SECRET_APK_FALLBACK_VERSION_URL }}",
                "UPDATE_SIGNING_KEY_ID": "${{ secrets.OTA_SIGNING_KEY_ID }}",
                "OTA_SIGNING_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
                "GATEKEEPER_API_KEY": "${{ secrets.GATEKEEPER_API_KEY }}",
            },
        },
        {
            "name": "Create production signed mobile manifest",
            "mobile_manifest_producer": True,
            "env": {
                "APK_DOWNLOAD_URL": "${{ secrets.SECRET_APK_DOWNLOAD_URL }}",
                "APK_FALLBACK_DOWNLOAD_URL": "${{ secrets.SECRET_APK_FALLBACK_DOWNLOAD_URL }}",
                "APK_RELEASE_NOTES_URL": "${{ secrets.SECRET_APK_RELEASE_NOTES_URL }}",
                "MOBILE_PRIVATE_KEY_HEX": "${{ secrets.OTA_SIGNING_PRIVATE_KEY_HEX }}",
                "MOBILE_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
                "MOBILE_SIGNING_KEY_ID": "${{ secrets.OTA_SIGNING_KEY_ID }}",
            },
        },
        {
            "name": "Enforce OTA production release evidence",
            "env": {"OTA_SIGNING_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}"},
            "run_prefix": "python scripts/ota_contract_gate.py release",
            "artifact": "dist/ks-house-gatekeeper.apk",
            "apksigner": True,
        },
        {
            "name": "Deploy APK to Synology NAS via SFTP",
            "uses": "wlixcc/SFTP-Deploy-Action@v1.2.4",
            "with": {
                "server": "${{ secrets.NAS_HOST }}",
                "username": "${{ secrets.NAS_USER }}",
                "password": "${{ secrets.NAS_PASSWORD }}",
                "port": "${{ secrets.NAS_PORT || 22 }}",
                "local_path": "./dist/*",
                "remote_path": "${{ secrets.NAS_APK_TARGET_DIR || '/docker/smartbox_ota/gatekeeper_apk/' }}",
                "sftp_only": True,
            },
        },
    ],
}


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
      "inputs.release_target == 'production' && "
      "github.ref == 'refs/heads/main'"
  )

  for path, binding in WORKFLOW_ARTIFACT_BINDINGS.items():
    content = workflows.get(path, "")
    parsed = load_workflow_yaml(path, content)

    # 1. Top-level keys allowlist
    allowed_top_keys = {"name", "on", "permissions", "jobs"}
    extra_top_keys = set(parsed.keys()) - allowed_top_keys
    if extra_top_keys:
      raise GateError(f"{path}: top-level contains unallowed keys: {sorted(extra_top_keys)}")

    # 2. Permissions allowlist
    permissions = parsed.get("permissions")
    if permissions != {"contents": "read"}:
      raise GateError(f"{path}: top-level permissions must be exact mapping {{'contents': 'read'}}")

    # 3. Triggers allowlist
    triggers = parsed.get("on")
    if not isinstance(triggers, dict):
      raise GateError(f"{path}: workflow triggers ('on') must be a mapping")

    allowed_triggers = {"pull_request", "push", "workflow_dispatch"}
    extra_triggers = set(triggers.keys()) - allowed_triggers
    if extra_triggers:
      raise GateError(f"{path}: workflow contains unallowed triggers: {sorted(extra_triggers)}")

    if "pull_request" not in triggers or "push" not in triggers or "workflow_dispatch" not in triggers:
      raise GateError(f"{path}: workflow missing required triggers (pull_request, push, workflow_dispatch)")

    dispatch_input = (
        triggers.get("workflow_dispatch", {})
        .get("inputs", {})
        .get("release_target", {})
    )
    if not isinstance(dispatch_input, dict) or dispatch_input.get("type") != "choice":
      raise GateError(f"{path}: explicit production release trigger missing release_target choice input")
    options = dispatch_input.get("options", [])
    if options != ["canary", "production"]:
      raise GateError(f"{path}: release_target options must include canary and production")

    # 4. Jobs allowlist
    all_jobs = parsed.get("jobs")
    if not isinstance(all_jobs, dict):
      raise GateError(f"{path}: workflow missing jobs mapping")

    build_job_name = binding["build_job"]
    release_job_name = binding["release_job"]
    allowed_jobs = {build_job_name, release_job_name}
    extra_jobs = set(all_jobs.keys()) - allowed_jobs
    if extra_jobs:
      raise GateError(f"{path}: unexpected job in workflow: {sorted(extra_jobs)}")

    build_job = all_jobs.get(build_job_name)
    release_job = all_jobs.get(release_job_name)

    # 5. Build Job Allowlist Check
    allowed_build_job_keys = {"name", "runs-on", "steps"}
    extra_build_job_keys = set(build_job.keys()) - allowed_build_job_keys
    if extra_build_job_keys:
      if "environment" in extra_build_job_keys:
        raise GateError(f"{path}: build job must not use production environment or specify environment (string or object)")
      raise GateError(f"{path}: build job contains unallowed keys: {sorted(extra_build_job_keys)}")

    if build_job.get("runs-on") != "ubuntu-latest":
      raise GateError(f"{path}: build job runs-on must be ubuntu-latest")

    build_steps = build_job.get("steps")
    if not isinstance(build_steps, list):
      raise GateError(f"{path}: build job steps must be a list")

    has_contract_step = False
    has_test_step = False
    has_canary_upload_step = False

    if "${{ secrets." in json.dumps(build_job, sort_keys=True):
      raise GateError(
          f"{path}: PR/branch-dispatch-reachable build job must contain zero production secret references"
      )

    for idx, step in enumerate(build_steps):
      if not isinstance(step, dict):
        raise GateError(f"{path}: step {idx} in build job must be a mapping")
      allowed_step_keys = {"name", "uses", "run", "with", "env", "if"}
      extra_step_keys = set(step.keys()) - allowed_step_keys
      if extra_step_keys:
        raise GateError(f"{path}: step {idx} in build job contains unallowed keys: {sorted(extra_step_keys)}")

      uses_action = str(step.get("uses", ""))
      run_cmd = str(step.get("run", ""))

      if uses_action:
        action_base = uses_action.strip()
        if action_base not in ALLOWED_BUILD_ACTIONS:
          raise GateError(f"{path}: ordinary push or PR build contains production or SFTP deployment capability: unallowed action {action_base}")

      if run_cmd:
        if "ota_contract_gate.py release" in run_cmd or "wlixcc/SFTP-Deploy-Action" in run_cmd:
          raise GateError(f"{path}: ordinary push or PR build contains production or SFTP deployment capability")
        if re.search(r'\b(sftp|scp|rsync|ssh)\b|curl\s+.*(-T|--upload-file)', run_cmd):
          raise GateError(f"{path}: ordinary push or PR build contains production or SFTP deployment capability")

        if "python scripts/ota_contract_gate.py contract" in run_cmd:
          has_contract_step = True
        if "python -m unittest discover" in run_cmd or "pytest" in run_cmd:
          has_test_step = True

      if uses_action and "actions/upload-artifact" in uses_action:
        step_with = step.get("with", {})
        if isinstance(step_with, dict) and step_with.get("name") == binding["canary_name"]:
          has_canary_upload_step = True

    if not has_contract_step or not has_test_step or not has_canary_upload_step:
      missing = []
      if not has_contract_step: missing.append("ota_contract_gate.py contract")
      if not has_test_step: missing.append("unittest discover")
      if not has_canary_upload_step: missing.append(f"upload-artifact {binding['canary_name']}")
      raise GateError(f"{path}: ordinary build/test contract missing: {missing}")

    # 6. Release Job Allowlist Check
    allowed_release_job_keys = {"name", "needs", "if", "environment", "runs-on", "steps"}
    extra_release_job_keys = set(release_job.keys()) - allowed_release_job_keys
    if extra_release_job_keys:
      raise GateError(f"{path}: release job contains unallowed keys: {sorted(extra_release_job_keys)}")

    needs = release_job.get("needs")
    if needs != build_job_name and needs != [build_job_name]:
      raise GateError(f"{path}: release job needs must include {build_job_name}")

    rel_env = release_job.get("environment")
    if not isinstance(rel_env, str) or rel_env != "production":
      raise GateError(f"{path}: release job environment must be exact string 'production'")

    release_if = release_job.get("if")
    if not release_if:
      raise GateError(f"{path}: production job lacks authorized production trigger")

    normalized_release_if = " ".join(str(release_if).split())
    if normalized_release_if != expected_authorized_condition:
      raise GateError(
          f"{path}: production job lacks authorized production trigger: "
          f"release job condition is extended or modified; must be exact production condition (got: '{normalized_release_if}')"
      )

    if release_job.get("runs-on") != "ubuntu-latest":
      raise GateError(f"{path}: release job runs-on must be ubuntu-latest")

    release_steps = release_job.get("steps")
    if not isinstance(release_steps, list):
      raise GateError(f"{path}: release job steps must be a list")

    canonical_steps = CANONICAL_RELEASE_STEPS.get(path, [])
    if len(release_steps) != len(canonical_steps):
      raise GateError(
          f"{path}: immutable release steps order violated: release job step count must be exactly {len(canonical_steps)} "
          f"(exactly one SFTP deploy step allowed, no steps allowed after SFTP deploy step)"
      )

    verification_index = next(
        index
        for index, item in enumerate(canonical_steps)
        if item["name"] == "Verify exact protected main release source"
    )
    for idx, (step, canonical) in enumerate(zip(release_steps, canonical_steps)):
      if not isinstance(step, dict):
        raise GateError(f"{path}: release step {idx} must be a mapping")

      if step.get("name") != canonical["name"]:
        raise GateError(f"{path}: immutable release steps order violated: release step {idx} name mismatch (expected '{canonical['name']}')")

      if "continue-on-error" in step:
        raise GateError(f"{path}: evidence step cannot specify continue-on-error")
      if "if" in step:
        raise GateError(f"{path}: evidence step cannot be conditionally disabled or bypassed")

      if idx < verification_index and "${{ secrets." in json.dumps(step, sort_keys=True):
        raise GateError(
            f"{path}: production secrets must be injected only after exact protected main verification"
        )

      expected_step_keys = {"name"}
      if "uses" in canonical:
        expected_step_keys.add("uses")
        if "with" in canonical:
          expected_step_keys.add("with")
      if "run" in canonical:
        expected_step_keys.add("run")
      if any(
          canonical.get(marker)
          for marker in (
              "main_source_verification",
              "target_build_secrets",
              "target_production_build",
              "target_manifest_producer",
              "android_keystore",
              "android_signing_properties",
              "android_production_build",
              "mobile_manifest_producer",
              "run_prefix",
          )
      ):
        expected_step_keys.add("run")
      if "env" in canonical:
        expected_step_keys.add("env")
      if set(step) != expected_step_keys:
        raise GateError(
            f"{path}: release step {idx} keys must be exact {sorted(expected_step_keys)}"
        )

      if "uses" in canonical:
        if step.get("uses") != canonical["uses"]:
          raise GateError(f"{path}: release step {idx} uses mismatch: expected '{canonical['uses']}'")
        if "with" in canonical:
          if step.get("with") != canonical["with"]:
            raise GateError(f"{path}: SFTP deploy local_path must be strictly './dist/*' and parameters must match canonical schema")

      if "run" in canonical:
        if step.get("run") != canonical["run"]:
          raise GateError(f"{path}: release step {idx} run command mismatch")

      if canonical.get("main_source_verification"):
        run_cmd = str(step.get("run", ""))
        for fragment in (
            'test "$GITHUB_REF" = "refs/heads/main"',
            'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
            "python scripts/ota_contract_gate.py contract",
            "python -m unittest discover -s tests -p 'test_*.py' -v",
        ):
          if run_cmd.count(fragment) != 1:
            raise GateError(
                f"{path}: exact protected main verification is incomplete: {fragment}"
            )
        if "${{ secrets." in run_cmd or "||" in run_cmd or "set +e" in run_cmd:
          raise GateError(
              f"{path}: exact protected main verification must be secret-free and fail closed"
          )

      if canonical.get("target_build_secrets"):
        if step.get("env") != canonical["env"]:
          raise GateError(
              f"{path}: production firmware inputs must come from exact production environment secrets"
          )
        run_cmd = str(step.get("run", ""))
        for fragment in (
            "test -n \"${!name}\"",
            "cat <<EOF > include/secrets.h",
            '#define SECRET_OTA_VERSION_URL "${SECRET_OTA_VERSION_URL}"',
            '#define SECRET_OTA_FIRMWARE_URL "${SECRET_OTA_FIRMWARE_URL}"',
            '#define SECRET_OTA_SIGNER_PUBLIC_KEY_HEX "${SECRET_OTA_SIGNER_PUBLIC_KEY_HEX}"',
            '#define SECRET_OTA_SIGNING_KEY_ID "${SECRET_OTA_SIGNING_KEY_ID}"',
        ):
          if fragment not in run_cmd:
            raise GateError(
                f"{path}: production firmware secret materialization is incomplete: {fragment}"
            )
        if re.search(r"\b(pio|python|curl|wget|sftp|scp|ssh)\b", run_cmd):
          raise GateError(
              f"{path}: production firmware secret step must not execute candidate-controlled tooling"
          )

      if canonical.get("target_production_build"):
        run_cmd = str(step.get("run", ""))
        for fragment in (
            "pio run -e esp32c6",
            "cp .pio/build/esp32c6/firmware.bin dist/gatekeeper-firmware.bin",
            "test -s dist/gatekeeper-firmware.bin",
        ):
          if fragment not in run_cmd:
            raise GateError(f"{path}: exact production firmware build is incomplete")
        if "${{ secrets." in run_cmd:
          raise GateError(f"{path}: production firmware build must consume only materialized inputs")

      if canonical.get("target_manifest_producer"):
        if step.get("env") != canonical["env"]:
          raise GateError(
              f"{path}: production Target manifest secrets must come from exact production environment inputs"
          )
        run_cmd = str(step.get("run", ""))
        required_fragments = (
            "python scripts/ota_contract_gate.py target-manifest-create",
            "python scripts/ota_contract_gate.py target-manifest-verify",
            "--artifact dist/gatekeeper-firmware.bin",
            "--output dist/version.json",
            '--commit "${{ github.sha }}"',
            '--build-id "${{ github.run_id }}"',
            '--private-key-env TARGET_PRIVATE_KEY_HEX',
            '--expected-public-key-hex "$TARGET_PUBLIC_KEY_HEX"',
        )
        for fragment in required_fragments:
          if fragment not in run_cmd:
            raise GateError(
                f"{path}: production Target manifest binding missing: {fragment}"
            )
        if run_cmd.count("target-manifest-create") != 1 or run_cmd.count(
            "target-manifest-verify"
        ) != 1:
          raise GateError(
              f"{path}: production Target manifest create/verify must each run exactly once"
          )
        if "secrets." in run_cmd or "||" in run_cmd or "set +e" in run_cmd:
          raise GateError(
              f"{path}: production Target manifest producer must use protected gate and fail closed"
          )

      if canonical.get("android_keystore"):
        if step.get("env") != canonical["env"]:
          raise GateError(f"{path}: Android keystore provenance must be exact")
        run_cmd = str(step.get("run", ""))
        for fragment in (
            'test -n "$KEYSTORE_BASE64"',
            "base64 --decode > gatekeeper_app/android/app/upload-keystore.jks",
            "test -s gatekeeper_app/android/app/upload-keystore.jks",
        ):
          if fragment not in run_cmd:
            raise GateError(f"{path}: Android keystore materialization is incomplete")
        if re.search(r"\b(gradle|flutter|python|curl|wget|sftp|scp|ssh)\b", run_cmd):
          raise GateError(
              f"{path}: keystore materialization step must not execute candidate-controlled tooling"
          )

      if canonical.get("android_signing_properties"):
        if step.get("env") != canonical["env"]:
          raise GateError(f"{path}: Android signing property provenance must be exact")
        run_cmd = str(step.get("run", ""))
        for fragment in (
            'test -n "$KEYSTORE_PASSWORD"',
            'test -n "$KEY_ALIAS"',
            "cat <<EOF > gatekeeper_app/android/key.properties",
        ):
          if fragment not in run_cmd:
            raise GateError(f"{path}: Android signing properties are incomplete")
        if re.search(r"\b(gradle|flutter|python|curl|wget|sftp|scp|ssh)\b", run_cmd):
          raise GateError(
              f"{path}: signing property step must not execute candidate-controlled tooling"
          )

      if canonical.get("android_production_build"):
        if step.get("env") != canonical["env"]:
          raise GateError(f"{path}: production Android runtime inputs must be exact")
        run_cmd = str(step.get("run", ""))
        for fragment in (
            "flutter build apk --release",
            "printf '%s\\n' '${{ github.sha }}' > gatekeeper_app/assets/source_commit.txt",
            '--dart-define=APK_VERSION_URL="$APK_VERSION_URL"',
            '--dart-define=APK_FALLBACK_VERSION_URL="$APK_FALLBACK_VERSION_URL"',
            '--dart-define=UPDATE_SIGNING_KEY_ID="$UPDATE_SIGNING_KEY_ID"',
            '--dart-define=UPDATE_SIGNING_PUBLIC_KEY_B64="$UPDATE_SIGNING_PUBLIC_KEY_B64"',
            "cp gatekeeper_app/build/app/outputs/flutter-apk/app-release.apk dist/ks-house-gatekeeper.apk",
        ):
          if fragment not in run_cmd:
            raise GateError(f"{path}: exact production Android build is incomplete: {fragment}")

      if canonical.get("mobile_manifest_producer"):
        if set(step) != {"name", "env", "run"}:
          raise GateError(
              f"{path}: production mobile manifest step keys must be exact"
          )
        if step.get("env") != canonical["env"]:
          raise GateError(
              f"{path}: production mobile manifest secrets must come only from exact production environment inputs"
          )
        run_cmd = str(step.get("run", ""))
        required_fragments = (
            "python scripts/ota_contract_gate.py mobile-manifest-create",
            "python scripts/ota_contract_gate.py mobile-manifest-verify",
            "--artifact dist/ks-house-gatekeeper.apk",
            "--output dist/version.json",
            '--commit "${{ github.sha }}"',
            '--expected-package-name "com.kshouse.gatekeeper_app"',
            '--apkanalyzer "$APKANALYZER"',
            '--apksigner "$APKSIGNER"',
            '--private-key-env MOBILE_PRIVATE_KEY_HEX',
            '--expected-public-key-hex "$MOBILE_PUBLIC_KEY_HEX"',
        )
        for fragment in required_fragments:
          if fragment not in run_cmd:
            raise GateError(
                f"{path}: production manifest producer identity binding missing: {fragment}"
            )
        if run_cmd.count("mobile-manifest-create") != 1 or run_cmd.count(
            "mobile-manifest-verify"
        ) != 1:
          raise GateError(
              f"{path}: production manifest create/verify must each run exactly once"
          )
        for repeated_fragment in (
            '--expected-package-name "com.kshouse.gatekeeper_app"',
            '--apkanalyzer "$APKANALYZER"',
            '--apksigner "$APKSIGNER"',
        ):
          if run_cmd.count(repeated_fragment) != 2:
            raise GateError(
                f"{path}: production manifest producer identity binding missing: {repeated_fragment}"
            )
        if "secrets." in run_cmd or "sign_mobile_manifest.py" in run_cmd:
          raise GateError(
              f"{path}: production manifest producer must use protected gate and step env only"
          )
        if "||" in run_cmd or "set +e" in run_cmd or "continue-on-error" in run_cmd:
          raise GateError(
              f"{path}: production manifest producer must fail closed"
          )

      if "run_prefix" in canonical:
        run_cmd = str(step.get("run", ""))
        step_env = step.get("env")
        if step_env != canonical["env"]:
          raise GateError(f"{path}: production signing secret provenance invalid; release evidence step env must equal {canonical['env']}")

        if "&&" in run_cmd or "||" in run_cmd or ";" in run_cmd or "set +e" in run_cmd or "|| true" in run_cmd or "|| exit" in run_cmd:
          raise GateError(f"{path}: evidence step release command must not swallow errors, suppress exit code, or chain commands with && or ;")


        if re.search(r'\b(printf\s+-v|read\b|export\b|OTA_SIGNING_PUBLIC_KEY_HEX\s*=)', run_cmd):
          raise GateError(f"{path}: signing key must come exactly from step env secret, cannot be redefined in run script")

        if f"--artifact {canonical['artifact']}" not in run_cmd or '--public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"' not in run_cmd or "--evidence ota/release-evidence.json" not in run_cmd or "--manifest dist/version.json" not in run_cmd:
          raise GateError(f"{path}: production release isolation violation: release evidence validation step missing required flags for {canonical['artifact']}")

        if canonical.get("apksigner") and '--apksigner "$APKSIGNER"' not in run_cmd:
          raise GateError(f"{path}: release evidence validation step missing required flags (--apksigner)")

        if run_cmd.count("python scripts/ota_contract_gate.py release") != 1:
          raise GateError(f"{path}: release evidence validation step missing or duplicate in release job")

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


def validate_firmware_build_workflow(
    workflows: dict[str, str] | None = None,
) -> None:
  """Keep every PR/branch-dispatch firmware canary public and non-production."""
  path = ".github/workflows/deploy.yml"
  content = (
      workflows[path]
      if workflows is not None
      else (ROOT / path).read_text(encoding="utf-8")
  )
  parsed = load_workflow_yaml(path, content)
  build_job = parsed.get("jobs", {}).get("test_and_build", {})
  steps = build_job.get("steps", [])
  if "${{ secrets." in json.dumps(build_job, sort_keys=True):
    raise GateError(
        f"{path}: PR/branch-dispatch firmware job must contain zero production secret references"
    )
  by_name = {step.get("name"): step for step in steps if isinstance(step, dict)}
  for name in (
      "Create compile-only public canary secrets",
      "Build ESP32-C6 firmware public canary",
      "Prepare signed public firmware canary",
      "Upload unsigned canary artifacts for physical Gate validation",
  ):
    if sum(
        1 for step in steps if isinstance(step, dict) and step.get("name") == name
    ) != 1:
      raise GateError(f"{path}: firmware build contract requires exactly one '{name}' step")
  prepare = by_name["Prepare signed public firmware canary"]
  if prepare.get("if") is not None or prepare.get("env"):
    raise GateError(f"{path}: public firmware metadata producer must be unconditional and secret-free")
  run_cmd = str(prepare.get("run", ""))
  for fragment in (
      "python scripts/ota_contract_gate.py target-manifest-create",
      "python scripts/ota_contract_gate.py target-manifest-verify",
      "--artifact dist/gatekeeper-firmware.bin",
      "--output dist/version.json",
      '--commit "${{ github.sha }}"',
      "https://target-canary.invalid/",
      '"2026-08-01T00:00:00Z"',
      "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
      "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
      "rfc8032-test-key-1",
  ):
    if fragment not in run_cmd:
      raise GateError(f"{path}: public firmware manifest binding is missing: {fragment}")
  if run_cmd.count("target-manifest-create") != 1 or run_cmd.count(
      "target-manifest-verify"
  ) != 1:
    raise GateError(f"{path}: public Target manifest create/verify must each run exactly once")
  if "secrets." in run_cmd or "SECRET_OTA_FIRMWARE_URL" in run_cmd:
    raise GateError(f"{path}: public firmware artifact producer exposes a production secret")
  upload = by_name["Upload unsigned canary artifacts for physical Gate validation"]
  if upload.get("with", {}).get("path") != "dist/":
    raise GateError(f"{path}: firmware canary upload must preserve exact dist artifact binding")


def validate_mobile_build_workflow(
    workflows: dict[str, str] | None = None,
) -> None:
  """Bind updater trust, PR secret isolation, APK identity, and metadata."""
  path = ".github/workflows/build_app.yml"
  content = (
      workflows[path]
      if workflows is not None
      else (ROOT / path).read_text(encoding="utf-8")
  )
  parsed = load_workflow_yaml(path, content)
  steps = parsed.get("jobs", {}).get("build_apk", {}).get("steps", [])
  names = [step.get("name") for step in steps if isinstance(step, dict)]
  required_names = [
      "Check Dart formatting",
      "Analyze Flutter code",
      "Run Flutter unit tests",
      "Run targeted native GATT unit tests before APK build",
      "Build Android debug APK for public canary",
      "Prepare public mobile canary metadata",
      "Upload artifact-bound canary for separate Gate validation",
  ]
  for name in required_names:
    if names.count(name) != 1:
      raise GateError(f"{path}: mobile build contract requires exactly one '{name}' step")
  position = {name: names.index(name) for name in required_names}
  first_build = position["Build Android debug APK for public canary"]
  if not (
      position["Check Dart formatting"]
      < position["Analyze Flutter code"]
      < position["Run Flutter unit tests"]
      < first_build
      and position["Run targeted native GATT unit tests before APK build"] < first_build
      and position["Prepare public mobile canary metadata"] > first_build
  ):
    raise GateError(f"{path}: Flutter/native tests must precede APK build and signing")

  by_name = {step.get("name"): step for step in steps if isinstance(step, dict)}
  for step in steps:
    if not isinstance(step, dict):
      raise GateError(f"{path}: mobile build steps must be mappings")
    condition = " ".join(str(step.get("if", "")).split())
    pr_reachable = condition != "github.event_name != 'pull_request'"
    serialized = json.dumps(step, sort_keys=True)
    if pr_reachable and "${{ secrets." in serialized:
      raise GateError(
          f"{path}: PR-reachable step '{step.get('name')}' references a production secret"
      )
  if "scripts/sign_mobile_manifest.py" in content:
    raise GateError(
        f"{path}: mobile manifest execution must remain inside protected ota_contract_gate.py"
    )
  format_run = str(by_name["Check Dart formatting"].get("run", ""))
  if "dart format --output=none --set-exit-if-changed lib test" not in format_run:
    raise GateError(f"{path}: hosted Dart formatting check is missing or mutable")
  native_run = str(
      by_name["Run targeted native GATT unit tests before APK build"].get("run", "")
  )
  for fragment in (
      "--no-daemon --rerun-tasks :app:testDebugUnitTest",
      "wrapper --gradle-version 9.1.0 --distribution-type all",
      "com.kshouse.gatekeeper_app.gattworker.*",
      "com.kshouse.gatekeeper_app.UpdatePackageIdentityPolicyTest",
      "com.kshouse.gatekeeper_app.BatteryOptimizationRequestPolicyTest",
      "Targeted native GATT JUnit",
  ):
    if fragment not in native_run:
      raise GateError(f"{path}: targeted native test evidence is incomplete: {fragment}")

  debug_step = by_name["Build Android debug APK for public canary"]
  if debug_step.get("if") is not None or debug_step.get("env"):
    raise GateError(f"{path}: public debug APK step must be unconditional and secret-free")
  debug_run = str(debug_step.get("run", ""))
  for fragment in (
      "--dart-define=APK_VERSION_URL=\"https://pr-canary.invalid/",
      "--dart-define=APK_FALLBACK_VERSION_URL=\"https://pr-fallback.invalid/",
      "--dart-define=UPDATE_SIGNING_KEY_ID=\"rfc8032-test-key-1\"",
      "--dart-define=UPDATE_SIGNING_PUBLIC_KEY_B64=\"11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=\"",
  ):
    if fragment not in debug_run:
      raise GateError(f"{path}: PR canary trust input is missing or installable: {fragment}")
  if "printf '%s\\n' '${{ github.sha }}' > gatekeeper_app/assets/source_commit.txt" not in debug_run:
    raise GateError(f"{path}: PR APK does not embed exact source commit identity")

  prepare_step = by_name["Prepare public mobile canary metadata"]
  if prepare_step.get("if") is not None:
    raise GateError(f"{path}: public canary metadata step must be unconditional")
  if prepare_step.get("env"):
    raise GateError(f"{path}: public PR metadata step must not define an env mapping")
  prepare_run = str(prepare_step.get("run", ""))
  for fragment in (
      "python scripts/ota_contract_gate.py mobile-manifest-create",
      "python scripts/ota_contract_gate.py mobile-manifest-verify",
      "--artifact dist/ks-house-gatekeeper.apk",
      "--output dist/version.json",
      '--commit "${{ github.sha }}"',
      '--expected-package-name "com.kshouse.gatekeeper_app"',
      '--apkanalyzer "$APKANALYZER"',
      '--apksigner "$APKSIGNER"',
      "https://pr-canary.invalid/",
      "https://pr-fallback.invalid/",
      "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
      "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
      'rfc8032-test-key-1',
  ):
    if fragment not in prepare_run:
      raise GateError(f"{path}: public PR metadata binding is missing: {fragment}")
  if prepare_run.count("mobile-manifest-create") != 1 or prepare_run.count(
      "mobile-manifest-verify"
  ) != 1:
    raise GateError(f"{path}: PR manifest create/verify must each run exactly once")
  for repeated_fragment in (
      '--expected-package-name "com.kshouse.gatekeeper_app"',
      '--apkanalyzer "$APKANALYZER"',
      '--apksigner "$APKSIGNER"',
  ):
    if prepare_run.count(repeated_fragment) != 2:
      raise GateError(f"{path}: PR metadata binding is missing: {repeated_fragment}")
  if "secrets." in prepare_run or "SECRET_" in prepare_run or "OTA_SIGNING_" in prepare_run:
    raise GateError(f"{path}: public PR metadata step exposes a production secret input")
  if "cat <<EOF > dist/version.json" in prepare_run or '"updated_at"' in prepare_run:
    raise GateError(f"{path}: legacy unsigned version.json generation is forbidden")

  if "app-release.apk" in json.dumps(steps, sort_keys=True):
    raise GateError(
        f"{path}: PR/branch-dispatch build job must never materialize a production APK"
    )


def validate_mobile_release_signing_config(content: str | None = None) -> None:
  path = "gatekeeper_app/android/app/build.gradle.kts"
  source = content if content is not None else (ROOT / path).read_text(encoding="utf-8")
  for fragment in (
      'it.contains("release", ignoreCase = true)',
      "releaseKey == null || !releaseKey.exists()",
      'keystoreProperties.getProperty("storePassword").isNullOrBlank()',
      'keystoreProperties.getProperty("keyAlias").isNullOrBlank()',
      'keystoreProperties.getProperty("keyPassword").isNullOrBlank()',
      "Release signing is fail-closed",
      'signingConfig = signingConfigs.getByName("release")',
  ):
    if fragment not in source:
      raise GateError(f"{path}: release-signing fail-closed seam missing: {fragment}")
  if 'signingConfigs.getByName("debug")' in source:
    raise GateError(f"{path}: debug signing fallback is forbidden for release")






def validate_contract() -> None:
  validate_partitions()
  state_machines = validate_state_machines()
  validate_recovery_and_faults(state_machines=state_machines)
  validate_vectors()
  validate_workflow_artifact_bindings()
  validate_firmware_build_workflow()
  validate_mobile_build_workflow()
  validate_mobile_release_signing_config()
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
  matches = re.findall(
          r"certificate SHA-256 digest:\s*([0-9a-fA-F]{64})",
          result.stdout + result.stderr,
      )
  if len(matches) != 1:
    raise GateError("APK must contain exactly one signing certificate")
  return {matches[0].lower()}


def _resolve_apkanalyzer(explicit_path: Path) -> Path:
  if explicit_path.is_file():
    return explicit_path
  raise GateError(f"apkanalyzer is missing or not a file: {explicit_path}")


def read_apk_manifest_identity(
    artifact_path: Path, apkanalyzer_path: Path
) -> tuple[str, int, str]:
  executable = _resolve_apkanalyzer(apkanalyzer_path)

  def read(verb: str) -> str:
    result = subprocess.run(
        [str(executable), "manifest", verb, str(artifact_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value or "\n" in value or "\r" in value:
      raise GateError(f"apkanalyzer could not read APK manifest {verb}")
    return value

  package_name = read("application-id")
  version_name = read("version-name")
  version_code_text = read("version-code")
  if not re.fullmatch(r"[1-9][0-9]*", version_code_text):
    raise GateError("APK manifest version-code must be a positive integer")
  return package_name, int(version_code_text), version_name


def read_apk_embedded_source_commit(artifact_path: Path) -> str:
  entry = "assets/flutter_assets/assets/source_commit.txt"
  try:
    with zipfile.ZipFile(artifact_path) as archive:
      matches = [item for item in archive.infolist() if item.filename == entry]
      if len(matches) != 1:
        raise GateError("APK must contain exactly one embedded source commit identity")
      value = archive.read(matches[0]).decode("ascii").strip()
  except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
    raise GateError("APK embedded source commit identity cannot be read") from exc
  if not re.fullmatch(r"[0-9a-f]{40}", value):
    raise GateError("APK embedded source commit identity must be exact lowercase 40-hex")
  return value


def _validate_mobile_apk_identity(
    artifact_path: Path,
    apkanalyzer_path: Path,
    expected_package_name: str,
    expected_version: str,
    expected_build_number: int,
    expected_commit: str,
) -> None:
  package_name, version_code, version_name = read_apk_manifest_identity(
      artifact_path, apkanalyzer_path
  )
  if package_name != expected_package_name:
    raise GateError("APK application ID does not match the expected package")
  if version_code != expected_build_number:
    raise GateError("APK version code does not match the signed build number")
  if version_name != expected_version:
    raise GateError("APK version name does not match the signed version")
  if read_apk_embedded_source_commit(artifact_path) != expected_commit:
    raise GateError("APK embedded source commit does not match signed metadata")


def _mobile_private_key_from_env(variable: str) -> Ed25519PrivateKey:
  value = os.environ.get(variable, "")
  if not re.fullmatch(r"[0-9a-f]{64}", value):
    raise GateError(f"{variable} must contain an exact 32-byte lowercase hex seed")
  return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(value))


def _mobile_public_hex(private_key: Ed25519PrivateKey) -> str:
  return private_key.public_key().public_bytes(
      encoding=serialization.Encoding.Raw,
      format=serialization.PublicFormat.Raw,
  ).hex()


def _mobile_timestamp(value: str, label: str) -> datetime:
  if not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value):
    raise GateError(f"{label} must be an RFC3339 timestamp with a timezone")
  try:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
  except ValueError as exc:
    raise GateError(f"{label} must be a valid RFC3339 timestamp") from exc


def create_target_manifest(args: argparse.Namespace) -> None:
  if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
    raise GateError("commit must be the exact lowercase 40-hex source identity")
  private_key = _mobile_private_key_from_env(args.private_key_env)
  public_hex = _mobile_public_hex(private_key)
  if public_hex != args.expected_public_key_hex:
    raise GateError("signing private key does not match the pinned Target OTA public key")
  size, sha256 = _artifact_size_and_sha256(args.artifact)
  if size < 1:
    raise GateError("Target firmware artifact must not be empty")
  publication = _mobile_timestamp(args.published_at, "published_at")
  if args.mandatory_after is not None and _mobile_timestamp(
      args.mandatory_after, "mandatory_after"
  ) < publication:
    raise GateError("mandatory_after cannot precede published_at")
  manifest: dict[str, object] = {
      "schema_version": 1,
      "artifact_type": "target-firmware",
      "version": args.version,
      "firmware_version": args.version,
      "protocol_min": args.protocol_min,
      "protocol_max": args.protocol_max,
      "board": "esp32-c6-devkitc-1",
      "flash_layout": "dual-ota-16mb-v1",
      "artifact_url": args.artifact_url,
      "artifact_size": size,
      "sha256": sha256,
      "signature_algorithm": "Ed25519",
      "signing_key_id": args.signing_key_id,
      "signature": "",
      "mandatory_after": args.mandatory_after,
      "published_at": args.published_at,
      "build_id": args.build_id,
      "commit": args.commit,
  }
  manifest["signature"] = base64.b64encode(
      private_key.sign(canonical_signed_bytes(manifest))
  ).decode("ascii")
  validate_manifest(manifest, "target-manifest.schema.json", public_hex)
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(
      json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
  )
  print(f"[TARGET-MANIFEST] created and verified: {args.output}")


def verify_target_manifest(args: argparse.Namespace) -> None:
  manifest = load_json(args.manifest)
  validate_manifest(manifest, "target-manifest.schema.json", args.public_key_hex)
  if manifest["version"] != args.expected_version:
    raise GateError("Target manifest version does not match the expected build")
  if manifest["commit"] != args.expected_commit:
    raise GateError("Target manifest commit does not match the expected source identity")
  if manifest["build_id"] != args.expected_build_id:
    raise GateError("Target manifest build ID does not match the expected workflow run")
  actual_size, actual_sha256 = _artifact_size_and_sha256(args.artifact)
  if (
      manifest["artifact_size"] != actual_size
      or manifest["sha256"] != actual_sha256
  ):
    raise GateError("Target manifest is not bound to the exact firmware bytes")
  print(f"[TARGET-MANIFEST] artifact binding verified: {args.manifest}")


def create_mobile_manifest(args: argparse.Namespace) -> None:
  if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
    raise GateError("commit must be the exact lowercase 40-hex source identity")
  _validate_mobile_apk_identity(
      args.artifact,
      args.apkanalyzer,
      args.expected_package_name,
      args.version,
      args.build_number,
      args.commit,
  )
  certificates = read_apk_signing_certificate_digests(
      args.artifact, args.apksigner
  )
  certificate_sha256 = next(iter(certificates))
  private_key = _mobile_private_key_from_env(args.private_key_env)
  public_hex = _mobile_public_hex(private_key)
  if public_hex != args.expected_public_key_hex:
    raise GateError("signing private key does not match the pinned updater public key")
  size, sha256 = _artifact_size_and_sha256(args.artifact)
  if size < 1:
    raise GateError("mobile artifact must not be empty")
  publication = _mobile_timestamp(args.published_at, "published_at")
  if args.mandatory_after is not None and _mobile_timestamp(
      args.mandatory_after, "mandatory_after"
  ) < publication:
    raise GateError("mandatory_after cannot precede published_at")
  manifest: dict[str, object] = {
      "schema_version": 1,
      "artifact_type": "android-apk",
      "version": args.version,
      "version_name": args.version,
      "build_number": args.build_number,
      "version_code": args.build_number,
      "protocol_min": args.protocol_min,
      "protocol_max": args.protocol_max,
      "min_android_sdk": args.min_android_sdk,
      "apk_url": args.apk_url,
      "fallback_url": args.fallback_url,
      "apk_size": size,
      "sha256": sha256,
      "signing_certificate_digest": certificate_sha256,
      "signature_algorithm": "Ed25519",
      "signing_key_id": args.signing_key_id,
      "signature": "",
      "mandatory_after": args.mandatory_after,
      "release_notes_url": args.release_notes_url,
      "published_at": args.published_at,
      "commit": args.commit,
  }
  manifest["signature"] = base64.b64encode(
      private_key.sign(canonical_signed_bytes(manifest))
  ).decode("ascii")
  validate_manifest(manifest, "mobile-manifest.schema.json", public_hex)
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(
      json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
  )
  print(f"[MOBILE-MANIFEST] created and verified: {args.output}")


def verify_mobile_manifest(args: argparse.Namespace) -> None:
  manifest = load_json(args.manifest)
  validate_manifest(manifest, "mobile-manifest.schema.json", args.public_key_hex)
  _validate_mobile_apk_identity(
      args.artifact,
      args.apkanalyzer,
      args.expected_package_name,
      str(manifest["version_name"]),
      int(manifest["version_code"]),
      str(manifest["commit"]),
  )
  actual_size, actual_sha256 = _artifact_size_and_sha256(args.artifact)
  if manifest["apk_size"] != actual_size or manifest["sha256"] != actual_sha256:
    raise GateError("mobile manifest is not bound to the exact APK bytes")
  certificates = read_apk_signing_certificate_digests(
      args.artifact, args.apksigner
  )
  if certificates != {manifest["signing_certificate_digest"]}:
    raise GateError("mobile manifest certificate digest does not match apksigner")
  print(f"[MOBILE-MANIFEST] artifact binding verified: {args.manifest}")


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
  target_create = subparsers.add_parser(
      "target-manifest-create",
      help="create exact signed Target metadata inside the protected OTA gate",
  )
  target_create.add_argument("--artifact", type=Path, required=True)
  target_create.add_argument("--output", type=Path, required=True)
  target_create.add_argument("--version", required=True)
  target_create.add_argument("--commit", required=True)
  target_create.add_argument("--build-id", required=True)
  target_create.add_argument("--artifact-url", required=True)
  target_create.add_argument("--published-at", required=True)
  target_create.add_argument("--mandatory-after")
  target_create.add_argument("--signing-key-id", required=True)
  target_create.add_argument("--private-key-env", required=True)
  target_create.add_argument("--expected-public-key-hex", required=True)
  target_create.add_argument("--protocol-min", type=int, default=1)
  target_create.add_argument("--protocol-max", type=int, default=2)
  target_verify = subparsers.add_parser(
      "target-manifest-verify",
      help="verify Target metadata and exact firmware bytes inside the protected gate",
  )
  target_verify.add_argument("--manifest", type=Path, required=True)
  target_verify.add_argument("--artifact", type=Path, required=True)
  target_verify.add_argument("--public-key-hex", required=True)
  target_verify.add_argument("--expected-version", required=True)
  target_verify.add_argument("--expected-commit", required=True)
  target_verify.add_argument("--expected-build-id", required=True)
  mobile_create = subparsers.add_parser(
      "mobile-manifest-create",
      help="create exact signed mobile metadata inside the protected OTA gate",
  )
  mobile_create.add_argument("--artifact", type=Path, required=True)
  mobile_create.add_argument("--output", type=Path, required=True)
  mobile_create.add_argument("--version", required=True)
  mobile_create.add_argument("--build-number", type=int, required=True)
  mobile_create.add_argument("--commit", required=True)
  mobile_create.add_argument("--apk-url", required=True)
  mobile_create.add_argument("--fallback-url", required=True)
  mobile_create.add_argument("--release-notes-url", required=True)
  mobile_create.add_argument("--published-at", required=True)
  mobile_create.add_argument("--mandatory-after")
  mobile_create.add_argument("--signing-key-id", required=True)
  mobile_create.add_argument("--private-key-env", required=True)
  mobile_create.add_argument("--expected-public-key-hex", required=True)
  mobile_create.add_argument("--expected-package-name", required=True)
  mobile_create.add_argument("--apkanalyzer", type=Path, required=True)
  mobile_create.add_argument("--apksigner", type=Path, required=True)
  mobile_create.add_argument("--protocol-min", type=int, default=1)
  mobile_create.add_argument("--protocol-max", type=int, default=2)
  mobile_create.add_argument("--min-android-sdk", type=int, default=23)
  mobile_verify = subparsers.add_parser(
      "mobile-manifest-verify",
      help="verify mobile metadata and APK-internal identity inside the protected gate",
  )
  mobile_verify.add_argument("--manifest", type=Path, required=True)
  mobile_verify.add_argument("--artifact", type=Path, required=True)
  mobile_verify.add_argument("--public-key-hex", required=True)
  mobile_verify.add_argument("--expected-package-name", required=True)
  mobile_verify.add_argument("--apkanalyzer", type=Path, required=True)
  mobile_verify.add_argument("--apksigner", type=Path, required=True)
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
    elif args.command == "target-manifest-create":
      create_target_manifest(args)
    elif args.command == "target-manifest-verify":
      verify_target_manifest(args)
    elif args.command == "mobile-manifest-create":
      create_mobile_manifest(args)
    elif args.command == "mobile-manifest-verify":
      verify_mobile_manifest(args)
  except (GateError, OSError, json.JSONDecodeError) as exc:
    print(f"[OTA-GATE] FAIL: {exc}", file=sys.stderr)
    return 1
  print(f"[OTA-GATE] PASS: {args.command}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
