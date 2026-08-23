#!/usr/bin/env python3
"""Validate OTA contracts and block releases without complete P0 evidence."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[1]
OTA = ROOT / "ota"
UBUNTU_RUNNER = "ubuntu-24.04"
CHECKOUT_ACTION = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
SETUP_PYTHON_ACTION = (
    "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
SETUP_JAVA_ACTION = (
    "actions/setup-java@cf277c60eb25467037889841efdb72551f06f6c3"
)
FLUTTER_ACTION = (
    "subosito/flutter-action@1a449444c387b1966244ae4d4f8c696479add0b2"
)
UPLOAD_ARTIFACT_ACTION = (
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
)
DOWNLOAD_ARTIFACT_ACTION = (
    "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093"
)
SFTP_DEPLOY_ACTION = (
    "wlixcc/SFTP-Deploy-Action@da88a4dbe95286266bbac3c0b2b8284048d20c8f"
)
TARGET_PYTHON_VERSION = "3.10.20"
MOBILE_PYTHON_VERSION = "3.12.13"
JAVA_VERSION = "17.0.16+8"
FLUTTER_VERSION = "3.44.8"
TARGET_AUTO_SIGNING_KEY_ID = "personal-target-auto-20260823-1"
TARGET_AUTO_PUBLIC_KEY_SHA256 = (
    "65154566393ecfb249c8aceb637e3258e349eb36e4dbca0dd52d61a6e55cb61b"
)
TARGET_HANDOFF_KEY_ID = "personal-target-handoff-20260824-1"
TARGET_HANDOFF_PUBLIC_KEY_HEX = (
    "c29829f8f801e887bcb56f1349c02ca0bd8403d2a11b16703121ae3418b6976a"
)
TARGET_HANDOFF_PUBLIC_KEY_SHA256 = (
    "b46f35bed26b7542c9103c1006ff90816e2e8758ebfc1fd9c53cab4561ec829f"
)
TARGET_CONTENT_KEY_ID = "personal-target-content-20260824-1"
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
        "canary_name": "target-canary-attempt-${{ github.run_attempt }}",
        "artifact": "dist/gatekeeper-firmware.bin",
        "build_copy": (
            "cp .pio/build/esp32c6/firmware.bin "
            "dist/gatekeeper-firmware.bin"
        ),
    },
    ".github/workflows/build_app.yml": {
        "build_job": "build_apk",
        "release_job": "release_to_production",
        "canary_name": "smart-key-app-canary-attempt-${{ github.run_attempt }}",
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
    artifact_url = urlparse(str(manifest["artifact_url"]))
    if artifact_url.username is not None or artifact_url.password is not None:
      raise GateError("Target artifact URL must not contain credentials")
    schema_version = manifest["schema_version"]
    if schema_version == 2:
      if Path(artifact_url.path).suffix != ".sgkenc":
        raise GateError("encrypted Target manifest must reference a .sgkenc artifact")
      if manifest["artifact_size"] != (
          manifest["plaintext_size"] + len(TARGET_CONTENT_MAGIC)
          + TARGET_CONTENT_NONCE_SIZE + TARGET_CONTENT_TAG_SIZE
      ):
        raise GateError("encrypted Target envelope size is inconsistent")
    elif Path(artifact_url.path).suffix != ".bin":
      raise GateError("legacy Target manifest must reference a .bin artifact")
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
    CHECKOUT_ACTION,
    SETUP_PYTHON_ACTION,
    SETUP_JAVA_ACTION,
    FLUTTER_ACTION,
    UPLOAD_ARTIFACT_ACTION,
}

PHYSICAL_TEST_PUBLIC_CONDITION = (
    "github.event_name == 'workflow_dispatch' && "
    "inputs.release_target == 'physical-test-canary' && "
    "github.ref == 'refs/heads/main'"
)
PHYSICAL_TEST_CONNECTED_CONDITION = (
    "github.event_name == 'workflow_dispatch' && "
    "inputs.release_target == 'physical-test-connected' && "
    "github.ref == 'refs/heads/main'"
)
PHYSICAL_TEST_NAS_ENV = {
    "NAS_HOST": "${{ secrets.NAS_HOST }}",
    "NAS_USER": "${{ secrets.NAS_USER }}",
    "NAS_PASSWORD": "${{ secrets.NAS_PASSWORD }}",
    "NAS_PORT": "${{ secrets.NAS_PORT || 22 }}",
    "NAS_KNOWN_HOSTS": "${{ secrets.NAS_KNOWN_HOSTS }}",
}
PHYSICAL_TEST_CONNECTED_SECRET_NAMES = {
    ".github/workflows/deploy.yml": (
        "PHYSICAL_TEST_ROOT_CA_CERT",
        "PHYSICAL_TEST_WIFI_SSID",
        "PHYSICAL_TEST_WIFI_PASSWORD",
        "PHYSICAL_TEST_API_URL",
        "PHYSICAL_TEST_API_KEY",
        "PHYSICAL_TEST_MQTT_HOST",
        "PHYSICAL_TEST_MQTT_PORT",
        "PHYSICAL_TEST_MQTT_USER",
        "PHYSICAL_TEST_MQTT_PASSWORD",
        "PHYSICAL_TEST_TARGET_TENANT_ID",
        "PHYSICAL_TEST_TARGET_DOOR_ID",
        "PHYSICAL_TEST_COMMAND_SIGNER_PUBLIC_KEY_HEX",
        "PHYSICAL_TEST_COMMAND_SIGNING_KEY_ID",
        "PHYSICAL_TEST_ACL_SIGNER_PUBLIC_KEY_HEX",
        "PHYSICAL_TEST_ACL_SIGNING_KEY_ID",
        "PHYSICAL_TEST_OTA_VERSION_URL",
        "PHYSICAL_TEST_OTA_FIRMWARE_URL",
        "PHYSICAL_TEST_OTA_SIGNING_PRIVATE_KEY_HEX",
        "PHYSICAL_TEST_OTA_SIGNING_PUBLIC_KEY_HEX",
        "PHYSICAL_TEST_OTA_SIGNING_KEY_ID",
        "PHYSICAL_TEST_LOCAL_RECOVERY_AP_PASSWORD",
        "PHYSICAL_TEST_LOCAL_RECOVERY_USER",
        "PHYSICAL_TEST_LOCAL_RECOVERY_PASSWORD",
    ),
    ".github/workflows/build_app.yml": (
        "PHYSICAL_TEST_ANDROID_KEYSTORE_BASE64",
        "PHYSICAL_TEST_ANDROID_KEYSTORE_PASSWORD",
        "PHYSICAL_TEST_ANDROID_KEY_ALIAS",
        "PHYSICAL_TEST_UPDATE_SIGNING_PRIVATE_KEY_HEX",
        "PHYSICAL_TEST_UPDATE_SIGNING_PUBLIC_KEY_HEX",
        "PHYSICAL_TEST_UPDATE_SIGNING_KEY_ID",
        "PHYSICAL_TEST_APK_VERSION_URL",
        "PHYSICAL_TEST_APK_DOWNLOAD_URL",
        "PHYSICAL_TEST_APK_FALLBACK_DOWNLOAD_URL",
        "PHYSICAL_TEST_APK_RELEASE_NOTES_URL",
        "PHYSICAL_TEST_API_KEY",
    ),
}


def _validate_physical_test_jobs(
    path: str, binding: dict[str, Any], all_jobs: dict[str, Any]
) -> None:
  public_job = all_jobs.get("deploy_physical_test_canary")
  connected_job = all_jobs.get("validate_connected_physical_test_prerequisites")
  if not isinstance(public_job, dict) or not isinstance(connected_job, dict):
    raise GateError(f"{path}: both physical-test jobs are required")

  if set(public_job) != {"name", "needs", "if", "runs-on", "steps"}:
    raise GateError(f"{path}: physical-test canary job keys are not exact")
  if public_job.get("needs") != binding["build_job"]:
    raise GateError(f"{path}: physical-test canary must consume the exact build job")
  if " ".join(str(public_job.get("if", "")).split()) != PHYSICAL_TEST_PUBLIC_CONDITION:
    raise GateError(f"{path}: physical-test canary trigger must be exact main dispatch")
  if public_job.get("runs-on") != UBUNTU_RUNNER:
    raise GateError(f"{path}: physical-test canary runner must be {UBUNTU_RUNNER}")
  public_steps = public_job.get("steps")
  if not isinstance(public_steps, list):
    raise GateError(f"{path}: physical-test canary steps must be a list")
  expected_names = (
      [
          "Checkout exact main physical-test verifier",
          "Download exact-run firmware canary",
          "Set up Python for physical-test verification",
          "Install physical-test verification dependencies",
          "Verify exact public firmware canary before NAS contact",
          "Install SFTP client",
          "Stage, read back, verify and publish isolated firmware canary",
          "Upload sanitized firmware physical-test evidence",
      ]
      if path.endswith("deploy.yml")
      else [
          "Checkout exact main physical-test verifier",
          "Download exact-run mobile canary",
          "Set up Java JDK 17 for APK inspection",
          "Set up Python for physical-test verification",
          "Install physical-test verification dependencies",
          "Verify exact public mobile canary before NAS contact",
          "Install SFTP client",
          "Stage, read back, verify and publish isolated mobile canary",
          "Upload sanitized mobile physical-test evidence",
      ]
  )
  if [step.get("name") for step in public_steps] != expected_names:
    raise GateError(f"{path}: physical-test canary step order is not exact")
  if any(not isinstance(step, dict) for step in public_steps):
    raise GateError(f"{path}: physical-test canary step must be a mapping")
  for step in public_steps:
    if set(step) - {"name", "uses", "with", "run", "env"}:
      raise GateError(f"{path}: physical-test canary step contains an unsafe key")
    if "continue-on-error" in step or "if" in step:
      raise GateError(f"{path}: physical-test canary step cannot bypass failure")

  checkout_step = public_steps[0]
  if checkout_step != {
      "name": "Checkout exact main physical-test verifier",
      "uses": CHECKOUT_ACTION,
      "with": {"ref": "${{ github.sha }}", "persist-credentials": False},
  }:
    raise GateError(f"{path}: physical-test verifier checkout must be exact main SHA")
  download_step = public_steps[1]
  if download_step.get("uses") != DOWNLOAD_ARTIFACT_ACTION:
    raise GateError(f"{path}: physical-test must download an exact-run Actions artifact")
  if download_step.get("with") != {"name": binding["canary_name"], "path": "dist"}:
    raise GateError(f"{path}: physical-test download artifact identity is not exact")
  upload_step = public_steps[-1]
  if upload_step.get("uses") != UPLOAD_ARTIFACT_ACTION:
    raise GateError(f"{path}: physical-test sanitized evidence upload is required")
  upload_with = upload_step.get("with", {})
  if (
      not isinstance(upload_with, dict)
      or upload_with.get("if-no-files-found") != "error"
      or upload_with.get("retention-days") != 30
      or upload_with.get("path") not in {
          "evidence/firmware-physical-test-evidence.json",
          "evidence/mobile-physical-test-evidence.json",
      }
  ):
    raise GateError(f"{path}: physical-test evidence upload contract is incomplete")

  network_step = public_steps[-2]
  if network_step.get("env") != PHYSICAL_TEST_NAS_ENV:
    raise GateError(f"{path}: physical-test NAS credentials must use the exact transport secret set")
  network_run = str(network_step.get("run", ""))
  expected_root = (
      "/docker/smart-gatekeeper-physical-test/firmware-public-canary"
      if path.endswith("deploy.yml")
      else "/docker/smart-gatekeeper-physical-test/mobile-public-canary"
  )
  expected_artifact = (
      "gatekeeper-firmware.bin"
      if path.endswith("deploy.yml")
      else "ks-house-gatekeeper.apk"
  )
  expected_evidence = (
      "firmware-physical-test-evidence.json"
      if path.endswith("deploy.yml")
      else "mobile-physical-test-evidence.json"
  )
  exact_sftp = (
      'sshpass -e sftp "${SSH_OPTIONS[@]}" -P "$NAS_PORT" '
      '-b - "$SSH_TARGET" <<EOF'
  )
  required_fragments = (
      "set -euo pipefail",
      f'REMOTE_ROOT="{expected_root}"',
      "StrictHostKeyChecking=yes",
      "repository-secret-pinned",
      "runtime-keyscan-unpinned",
      "for name in NAS_HOST NAS_USER NAS_PASSWORD NAS_PORT",
      'if [[ -n "${NAS_KNOWN_HOSTS:-}" ]]; then',
      'test "${{ inputs.allow_unpinned_host_key }}" = "true"',
      "for attempt in 1 2 3; do",
      '[[ "$NAS_USER" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$ ]]',
      '[[ "$NAS_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ ]]',
      '[[ "$NAS_PORT" =~ ^[0-9]{1,5}$ ]]',
      "((10#$NAS_PORT >= 1 && 10#$NAS_PORT <= 65535))",
      '[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]',
      '[[ "$GITHUB_RUN_ID" =~ ^[1-9][0-9]*$ ]]',
      '[[ "$GITHUB_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]]',
      'ssh-keygen -l -E sha256 -f "$KNOWN_HOSTS_FILE" >/dev/null',
      'timeout 10s ssh-keyscan -T 5 -p "$NAS_PORT" -- "$NAS_HOST" > "${KNOWN_HOSTS_FILE}.scan" 2>/dev/null',
      "::warning::NAS_KNOWN_HOSTS is not configured; using runtime ssh-keyscan",
      "-mkdir /docker",
      "-mkdir /docker/smart-gatekeeper-physical-test",
      "-mkdir $REMOTE_ROOT",
      "-mkdir $REMOTE_PARENT",
      "mkdir $REMOTE_STAGE",
      f"put dist/{expected_artifact} $REMOTE_STAGE/{expected_artifact}",
      f"get $REMOTE_STAGE/{expected_artifact} readback/{expected_artifact}",
      "physical-test-evidence-create",
      "--readback-manifest readback/version.json",
      f"put evidence/{expected_evidence} $REMOTE_STAGE/evidence.json",
      "get $REMOTE_STAGE/evidence.json readback/evidence.json",
      "cmp evidence/",
      "rename $REMOTE_STAGE $REMOTE_FINAL",
  )
  for fragment in required_fragments:
    if fragment not in network_run:
      raise GateError(f"{path}: physical-test stage/readback contract missing: {fragment}")
  for exact_once in (
      "for attempt in 1 2 3; do",
      'timeout 10s ssh-keyscan -T 5 -p "$NAS_PORT" -- "$NAS_HOST" > "${KNOWN_HOSTS_FILE}.scan" 2>/dev/null',
  ):
    if network_run.count(exact_once) != 1:
      raise GateError(
          f"{path}: physical-test fallback and SFTP publish sequence must be exact"
      )
  stripped_lines = [line.strip() for line in network_run.splitlines()]
  for exact_sftp_command in (
      "-mkdir /docker",
      "-mkdir /docker/smart-gatekeeper-physical-test",
      "-mkdir $REMOTE_ROOT",
      "-mkdir $REMOTE_PARENT",
      "mkdir $REMOTE_STAGE",
      "rename $REMOTE_STAGE $REMOTE_FINAL",
  ):
    if stripped_lines.count(exact_sftp_command) != 1:
      raise GateError(
          f"{path}: physical-test fallback and SFTP publish sequence must be exact"
      )
  expected_sftp_lines = [
      f"timeout 300s {exact_sftp}",
      f"timeout 300s {exact_sftp}",
      f"timeout 120s {exact_sftp}",
      f"timeout 30s {exact_sftp}",
  ]
  sshpass_lines = [
      line.strip() for line in network_run.splitlines() if "sshpass" in line
  ]
  if sshpass_lines != expected_sftp_lines:
    raise GateError(
        f"{path}: physical-test transport must use exactly four bounded SFTP-only batches"
    )
  if re.search(
      r"(?m)^\s*(?:(?:timeout\s+\d+s|command)\s+)?(?:sshpass\s+-e\s+)?ssh(?:\s|$)",
      network_run,
  ):
    raise GateError(f"{path}: physical-test SFTP-only lane forbids remote shell invocation")
  ordered_fragments = (
      "-mkdir /docker",
      "-mkdir /docker/smart-gatekeeper-physical-test",
      "-mkdir $REMOTE_ROOT",
      "-mkdir $REMOTE_PARENT",
      "mkdir $REMOTE_STAGE",
      f"put dist/{expected_artifact} $REMOTE_STAGE/{expected_artifact}",
      f"get $REMOTE_STAGE/{expected_artifact} readback/{expected_artifact}",
      "physical-test-evidence-create",
      f"put evidence/{expected_evidence} $REMOTE_STAGE/evidence.json",
      "get $REMOTE_STAGE/evidence.json readback/evidence.json",
      "cmp evidence/",
      "rename $REMOTE_STAGE $REMOTE_FINAL",
  )
  positions = [network_run.index(fragment) for fragment in ordered_fragments]
  if positions != sorted(positions):
    raise GateError(f"{path}: physical-test SFTP stage/readback/rename order is not exact")
  forbidden_fragments = (
      "${{ secrets.NAS_TARGET_DIR",
      "${{ secrets.NAS_APK_TARGET_DIR",
      "/docker/smart-gatekeeper-ota/",
      "/docker/smartbox_ota/gatekeeper_apk/",
      "ota_contract_gate.py release",
      "|| true",
      "set +e",
      "while true",
      "while :",
      "for name in NAS_HOST NAS_USER NAS_PASSWORD NAS_PORT NAS_KNOWN_HOSTS",
      "StrictHostKeyChecking=no",
      "StrictHostKeyChecking=accept-new",
      "sshpass -e ssh",
      "mv '$REMOTE_STAGE' '$REMOTE_FINAL'",
      "-mkdir $REMOTE_STAGE",
      "-rename $REMOTE_STAGE $REMOTE_FINAL",
      "\n!",
  )
  if any(fragment in network_run for fragment in forbidden_fragments):
    raise GateError(f"{path}: physical-test lane reaches a production or bypass surface")
  serialized_public = json.dumps(public_job, sort_keys=True)
  secret_refs = set(re.findall(r"\$\{\{ secrets\.([A-Z0-9_]+)", serialized_public))
  if secret_refs != set(PHYSICAL_TEST_NAS_ENV):
    raise GateError(f"{path}: public physical-test lane may use only NAS transport secrets")

  if set(connected_job) != {"name", "needs", "if", "environment", "runs-on", "steps"}:
    raise GateError(f"{path}: connected physical-test prerequisite job keys are not exact")
  if connected_job.get("needs") != binding["build_job"]:
    raise GateError(f"{path}: connected physical-test prerequisites require exact build")
  if " ".join(str(connected_job.get("if", "")).split()) != PHYSICAL_TEST_CONNECTED_CONDITION:
    raise GateError(f"{path}: connected physical-test trigger must be exact main dispatch")
  if connected_job.get("environment") != "physical-test":
    raise GateError(f"{path}: connected physical-test requires the physical-test environment")
  if connected_job.get("runs-on") != UBUNTU_RUNNER:
    raise GateError(f"{path}: connected physical-test runner must be {UBUNTU_RUNNER}")
  connected_steps = connected_job.get("steps")
  if not isinstance(connected_steps, list) or len(connected_steps) != 1:
    raise GateError(f"{path}: connected physical-test must remain one fail-closed prerequisite step")
  connected_step = connected_steps[0]
  if set(connected_step) != {"name", "env", "run"}:
    raise GateError(f"{path}: connected physical-test prerequisite step keys are not exact")
  expected_names_set = set(PHYSICAL_TEST_CONNECTED_SECRET_NAMES[path])
  expected_env = {name: f"${{{{ secrets.{name} }}}}" for name in expected_names_set}
  if connected_step.get("env") != expected_env:
    raise GateError(f"{path}: connected physical-test secret contract is not exact")
  connected_run = str(connected_step.get("run", ""))
  for name in expected_names_set:
    if connected_run.count(name) != 1:
      raise GateError(f"{path}: connected physical-test missing secret precondition {name}")
  if connected_run.count("exit 1") != 2 or "separately reviewed implementation" not in connected_run:
    raise GateError(f"{path}: connected physical-test must remain fail closed")
  if re.search(r"\b(sftp|scp|rsync|ssh|curl|wget|pio|flutter|gradle)\b", connected_run):
    raise GateError(f"{path}: connected prerequisite job must not build, sign or contact a network")

PERSONAL_TARGET_SECRET_ENV = {
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
    "SECRET_OTA_VERSION_URL": "${{ secrets.SECRET_OTA_VERSION_URL }}",
    "SECRET_OTA_FIRMWARE_URL": "${{ secrets.SECRET_OTA_FIRMWARE_URL }}",
    "SECRET_OTA_SIGNER_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
    "SECRET_OTA_SIGNING_KEY_ID": "${{ secrets.OTA_SIGNING_KEY_ID }}",
    "SECRET_OTA_CONTENT_KEY_HEX": "${{ secrets.SECRET_OTA_CONTENT_KEY_HEX }}",
    "SECRET_OTA_CONTENT_KEY_ID": "${{ secrets.SECRET_OTA_CONTENT_KEY_ID }}",
    "SECRET_LOCAL_RECOVERY_AP_PASSWORD": "${{ secrets.SECRET_LOCAL_RECOVERY_AP_PASSWORD }}",
    "SECRET_LOCAL_RECOVERY_USER": "${{ secrets.SECRET_LOCAL_RECOVERY_USER }}",
    "SECRET_LOCAL_RECOVERY_PASSWORD": "${{ secrets.SECRET_LOCAL_RECOVERY_PASSWORD }}",
}

PINNED_TARGET_BUILD_INPUTS = {
    "platformio.ini": "cd4ade51f2e8934470ec0027c9e204e2f344853c8b05f610616b700f63869de1",
}
PINNED_OTA_PYTHON_INPUTS = {
    "ota/requirements.txt": (
        "21f985255f11f89d00cd6061a3817c860b6da951424121040e82358053cf90c7"
    ),
    "ota/requirements.lock": (
        "5b8c5859426a7febd6bd9d9b0482bf78f8f4854c2d83d0ce53ba49c14c5cea12"
    ),
}

PERSONAL_TARGET_MANIFEST_ENV = {
    "TARGET_ARTIFACT_URL": "${{ secrets.SECRET_OTA_FIRMWARE_URL }}",
    "TARGET_PRIVATE_KEY_HEX": "${{ secrets.OTA_SIGNING_PRIVATE_KEY_HEX }}",
    "TARGET_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
    "TARGET_SIGNING_KEY_ID": "${{ secrets.OTA_SIGNING_KEY_ID }}",
    "TARGET_CONTENT_KEY_ID": "${{ secrets.SECRET_OTA_CONTENT_KEY_ID }}",
}

PERSONAL_TARGET_PUBLISH_ENV = {
    "NAS_HOST": "${{ secrets.NAS_HOST }}",
    "NAS_USER": "${{ secrets.NAS_USER }}",
    "NAS_PASSWORD": "${{ secrets.NAS_PASSWORD }}",
    "NAS_PORT": "${{ secrets.NAS_PORT || 22 }}",
    "NAS_TARGET_DIR": "${{ secrets.NAS_TARGET_DIR || '/docker/smartbox_ota/firmware/' }}",
    "NAS_KNOWN_HOSTS": "${{ secrets.NAS_KNOWN_HOSTS }}",
    "TARGET_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
}

PERSONAL_TARGET_HTTPS_ENV = {
    "TARGET_VERSION_URL": "${{ secrets.SECRET_OTA_VERSION_URL }}",
    "TARGET_FIRMWARE_URL": "${{ secrets.SECRET_OTA_FIRMWARE_URL }}",
    "TARGET_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
    "TARGET_ROOT_CA_CERT": "${{ secrets.SECRET_ROOT_CA_CERT }}",
    "TARGET_CONTENT_KEY_ID": "${{ secrets.SECRET_OTA_CONTENT_KEY_ID }}",
}


def _validate_personal_target_ota_job(
    path: str,
    build_job_name: str,
    jobs: dict[str, Any],
) -> None:
  if path != ".github/workflows/deploy.yml":
    if any(name in jobs for name in (
        PERSONAL_TARGET_BUILD_JOB, PERSONAL_TARGET_PUBLISH_JOB
    )):
      raise GateError(f"{path}: Target OTA auto-publish job belongs only in deploy.yml")
    return
  compile_job = jobs.get(PERSONAL_TARGET_BUILD_JOB)
  if not isinstance(compile_job, dict):
    raise GateError(f"{path}: exact-main personal Target compile job is required")
  job = jobs.get(PERSONAL_TARGET_PUBLISH_JOB)
  if not isinstance(job, dict):
    raise GateError(f"{path}: exact-main personal Target OTA job is required")
  if set(compile_job) != {"name", "needs", "if", "environment", "runs-on", "steps"}:
    raise GateError(f"{path}: personal Target compile job keys must be exact")
  if compile_job.get("name") != "Build exact-main personal Target firmware with runtime inputs":
    raise GateError(f"{path}: personal Target compile job name is not exact")
  if compile_job.get("needs") not in (build_job_name, [build_job_name]):
    raise GateError(f"{path}: personal Target compile must need public test/build")
  if " ".join(str(compile_job.get("if", "")).split()) != PERSONAL_TARGET_AUTO_CONDITION:
    raise GateError(f"{path}: personal Target compile trigger must be exact")
  if compile_job.get("environment") != "personal-auto-ota":
    raise GateError(f"{path}: personal Target compile must use the main-only environment")
  if compile_job.get("runs-on") != UBUNTU_RUNNER:
    raise GateError(f"{path}: personal Target compile runner must be {UBUNTU_RUNNER}")
  if set(job) != {
      "name", "needs", "if", "environment", "concurrency", "runs-on", "steps"
  }:
    raise GateError(f"{path}: personal Target OTA job keys must be exact")
  if job.get("name") != "Sign and atomically publish exact-main personal Target OTA":
    raise GateError(f"{path}: personal Target OTA job name is not exact")
  if job.get("needs") not in (PERSONAL_TARGET_BUILD_JOB, [PERSONAL_TARGET_BUILD_JOB]):
    raise GateError(f"{path}: personal Target publisher must need only the compile job")
  if " ".join(str(job.get("if", "")).split()) != PERSONAL_TARGET_AUTO_CONDITION:
    raise GateError(f"{path}: personal Target OTA trigger must be exact main push/canary dispatch")
  if job.get("environment") != "personal-auto-ota":
    raise GateError(
        f"{path}: personal Target OTA must use the main-only automatic environment"
    )
  if job.get("concurrency") != {
      "group": "smart-gatekeeper-personal-target-ota-main",
      "cancel-in-progress": False,
  }:
    raise GateError(f"{path}: personal Target OTA concurrency contract is not exact")
  if job.get("runs-on") != UBUNTU_RUNNER:
    raise GateError(f"{path}: personal Target OTA runner must be {UBUNTU_RUNNER}")
  steps = compile_job.get("steps")
  expected_names = [
      "Checkout exact main OTA source",
      "Set up Python for exact-main OTA",
      "Install exact-main OTA dependencies",
      "Verify exact protected main before production secrets",
      "Materialize personal Target production inputs",
      "Build exact monotonic N16 production firmware",
      "Encrypt sensitive Target firmware handoff",
      "Upload short-lived encrypted Target firmware handoff",
  ]
  if not isinstance(steps, list) or [step.get("name") for step in steps] != expected_names:
    raise GateError(f"{path}: personal Target OTA step order must be exact")
  expected_keys = [
      {"name", "uses", "with"},
      {"name", "uses", "with"},
      {"name", "run"},
      {"name", "run"},
      {"name", "env", "run"},
      {"name", "run"},
      {"name", "env", "run"},
      {"name", "uses", "with"},
  ]
  for index, (step, keys) in enumerate(zip(steps, expected_keys)):
    if not isinstance(step, dict) or set(step) != keys:
      raise GateError(f"{path}: personal Target OTA step {index} keys are not exact")
    if "continue-on-error" in step or "if" in step:
      raise GateError(f"{path}: personal Target OTA steps cannot suppress or skip failures")

  (
      checkout, setup, install, verify, materialize, build, handoff_encrypt,
      handoff_upload,
  ) = steps
  if checkout.get("uses") != CHECKOUT_ACTION or checkout.get("with") != {
      "ref": "${{ github.sha }}",
      "fetch-depth": 0,
      "persist-credentials": False,
  }:
    raise GateError(f"{path}: personal Target OTA checkout identity/history is not exact")
  if setup.get("uses") != SETUP_PYTHON_ACTION or setup.get("with") != {
      "python-version": TARGET_PYTHON_VERSION
  }:
    raise GateError(f"{path}: personal Target OTA Python setup is not exact")
  if install.get("run") != (
      "python -I -m pip install --require-hashes -r ota/requirements.lock"
  ):
    raise GateError(f"{path}: personal Target OTA dependency install is not exact")
  verify_run = str(verify.get("run", ""))
  for fragment in (
      'test "$GITHUB_EVENT_NAME" = "push"',
      'test "$GITHUB_REF" = "refs/heads/main"',
      'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
      'test "$(git rev-parse --is-shallow-repository)" = "false"',
      'if [[ "$GITHUB_EVENT_NAME" == "workflow_dispatch" ]]; then',
      'test "${{ inputs.release_target }}" = "canary"',
      'EXPECTED_BUILD_TREE="$(cat <<\'EOF\'',
      'test ! -e .pio',
      "git ls-files --others --exclude-standard --",
      "src include lib boards variants sitecustomize.py usercustomize.py",
      'test -z "$UNEXPECTED_BUILD_INPUTS"',
      "git ls-files --stage -- src include lib boards variants",
      "sitecustomize.py usercustomize.py platformio_override.ini platformio.ini",
      "partitions_16MB_ota.csv ota/requirements.lock |",
      "100644 5b8c5859426a7febd6bd9d9b0482bf78f8f4854c2d83d0ce53ba49c14c5cea12 ota/requirements.lock",
      "100644 6a43bf72346adc028df3ee46734c856373a79216ad15e7e9461681a128a96d04 partitions_16MB_ota.csv",
      "100644 cd4ade51f2e8934470ec0027c9e204e2f344853c8b05f610616b700f63869de1 platformio.ini",
      'while read -r mode object stage path; do',
      'test "$mode" = "100644"',
      'test -f "$path"',
      'test ! -L "$path"',
      'test "$(stat -c \'%a\' -- "$path")" = "644"',
      'digest="$(sha256sum -- "$path" | cut -d\' \' -f1)"',
      'printf \'%s %s %s\\n\' "$mode" "$digest" "$path"',
      'test "$ACTUAL_BUILD_TREE" = "$EXPECTED_BUILD_TREE"',
  ):
    if verify_run.count(fragment) != 1:
      raise GateError(f"{path}: personal Target exact-main verification is incomplete")
  if re.search(r"(?m)^\s*(?:python|pio|pytest)\b|python\s+-m\s+unittest", verify_run):
    raise GateError(f"{path}: privileged Target verification must not execute candidate code")
  if "${{ secrets." in json.dumps(steps[:4], sort_keys=True):
    raise GateError(f"{path}: personal Target secrets appear before exact-main verification")

  if materialize.get("env") != PERSONAL_TARGET_SECRET_ENV:
    raise GateError(f"{path}: personal Target input provenance is not exact")
  materialize_run = str(materialize.get("run", ""))
  for fragment in (
      "require_cpp_string",
      "cat <<EOF > include/secrets.h",
      '#define SECRET_HARDWARELESS_DOOR_ID_HEX ""',
      '#define SECRET_ACL_SIGNER_PUBLIC_KEY_HEX ""',
      '#define SECRET_OTA_VERSION_URL "${SECRET_OTA_VERSION_URL}"',
      '#define SECRET_OTA_FIRMWARE_URL "${SECRET_OTA_FIRMWARE_URL}"',
      '#define SECRET_OTA_SIGNER_PUBLIC_KEY_HEX "${SECRET_OTA_SIGNER_PUBLIC_KEY_HEX}"',
      '#define SECRET_OTA_CONTENT_KEY_HEX "${SECRET_OTA_CONTENT_KEY_HEX}"',
      '#define SECRET_OTA_CONTENT_KEY_ID "${SECRET_OTA_CONTENT_KEY_ID}"',
      '#define SECRET_LOCAL_RECOVERY_AP_PASSWORD "${SECRET_LOCAL_RECOVERY_AP_PASSWORD}"',
      f'test "$SECRET_OTA_SIGNING_KEY_ID" = "{TARGET_AUTO_SIGNING_KEY_ID}"',
      f'test "$OTA_PUBLIC_KEY_SHA256" = "{TARGET_AUTO_PUBLIC_KEY_SHA256}"',
      '[[ "$SECRET_OTA_CONTENT_KEY_HEX" =~ ^[0-9a-f]{64}$ ]]',
      f'test "$SECRET_OTA_CONTENT_KEY_ID" = "{TARGET_CONTENT_KEY_ID}"',
      "xxd -r -p | sha256sum",
  ):
    if fragment not in materialize_run:
      raise GateError(f"{path}: personal Target secret materialization is incomplete")
  if re.search(r"\b(pio|python|curl|wget|sftp|scp|ssh)\b", materialize_run):
    raise GateError(f"{path}: Target secret step must not execute candidate tooling")

  build_run = str(build.get("run", ""))
  for fragment in (
      "git rev-list --count --first-parent HEAD",
      'FULL_VERSION="2.1.${COMMIT_SEQUENCE}+main.g${SHORT_SHA}"',
      'TARGET_BUILD_ID="main-${COMMIT_SEQUENCE}-${GITHUB_SHA}"',
      'echo "TARGET_BUILD_ID=${TARGET_BUILD_ID}" >> "$GITHUB_ENV"',
      'SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$GITHUB_SHA")"',
      "export SOURCE_DATE_EPOCH",
      "python -I -m platformio run -e esp32c6_production",
      "cp .pio/build/esp32c6_production/firmware.bin dist/gatekeeper-firmware-first.bin",
      "python -I -m platformio run -e esp32c6_production -t clean",
      "cmp dist/gatekeeper-firmware-first.bin .pio/build/esp32c6_production/firmware.bin",
      'version = os.environ["FULL_VERSION"].encode("ascii")',
      "if version not in firmware:",
      'raise SystemExit("exact Target version is absent from firmware bytes")',
      "python -I scripts/verify_target_flash_layout.py",
      "--partitions partitions_16MB_ota.csv",
      "--flash-size 0x1000000",
      "--max-slot-usage-percent 80",
      "cp .pio/build/esp32c6_production/firmware.bin dist/gatekeeper-firmware.bin",
  ):
    if fragment not in build_run:
      raise GateError(f"{path}: monotonic N16 Target production build is incomplete")
  if "${{ secrets." in build_run:
    raise GateError(f"{path}: Target build must consume only materialized inputs")

  if handoff_encrypt.get("env") != {
      "TARGET_HANDOFF_PUBLIC_KEY_HEX": "${{ secrets.TARGET_HANDOFF_PUBLIC_KEY_HEX }}",
      "TARGET_HANDOFF_KEY_ID": "${{ secrets.TARGET_HANDOFF_KEY_ID }}",
  }:
    raise GateError(f"{path}: Target handoff encryption public-key provenance is not exact")
  handoff_encrypt_run = str(handoff_encrypt.get("run", ""))
  for fragment in (
      f'test "$TARGET_HANDOFF_KEY_ID" = "{TARGET_HANDOFF_KEY_ID}"',
      f'test "$HANDOFF_PUBLIC_SHA256" = "{TARGET_HANDOFF_PUBLIC_KEY_SHA256}"',
      "python -I scripts/ota_contract_gate.py target-handoff-encrypt",
      "--artifact dist/gatekeeper-firmware.bin",
      "--output dist/gatekeeper-firmware.sgkenc",
      '--recipient-public-key-hex "$TARGET_HANDOFF_PUBLIC_KEY_HEX"',
      '--commit "$GITHUB_SHA"',
      '--run-attempt "$GITHUB_RUN_ATTEMPT"',
      "rm -f dist/gatekeeper-firmware.bin dist/gatekeeper-firmware-first.bin",
      "test ! -e dist/gatekeeper-firmware.bin",
  ):
    if fragment not in handoff_encrypt_run:
      raise GateError(f"{path}: sensitive Target firmware handoff encryption is incomplete")
  if handoff_upload.get("uses") != UPLOAD_ARTIFACT_ACTION or handoff_upload.get(
      "with"
  ) != {
      "name": (
          "personal-target-firmware-${{ github.sha }}-attempt-"
          "${{ github.run_attempt }}"
      ),
      "path": "dist/gatekeeper-firmware.sgkenc",
      "if-no-files-found": "error",
      "retention-days": 1,
  }:
    raise GateError(f"{path}: encrypted Target firmware handoff upload is not exact")
  compile_serialized = json.dumps(compile_job, sort_keys=True)
  for forbidden in (
      "OTA_SIGNING_PRIVATE_KEY_HEX", "TARGET_PRIVATE_KEY_HEX", "NAS_HOST",
      "NAS_USER", "NAS_PASSWORD", "NAS_KNOWN_HOSTS", "NAS_TARGET_DIR",
      "TARGET_HANDOFF_PRIVATE_KEY_HEX", "target-sftp-publish",
      "target-manifest-create",
  ):
    if forbidden in compile_serialized:
      raise GateError(f"{path}: Target compiler gained signing or NAS authority")
  expected_compile_secret_refs = set(PERSONAL_TARGET_SECRET_ENV.values()) | {
      "${{ secrets.TARGET_HANDOFF_PUBLIC_KEY_HEX }}",
      "${{ secrets.TARGET_HANDOFF_KEY_ID }}",
  }
  actual_compile_secret_refs = set(re.findall(
      r"\$\{\{ secrets\.[^}]+\}\}", compile_serialized
  ))
  if actual_compile_secret_refs != expected_compile_secret_refs:
    raise GateError(f"{path}: Target compiler secret allowlist is not exact")

  publisher_steps = job.get("steps")
  publisher_expected_names = [
      "Checkout exact protected Target publisher inputs",
      "Set up Python for isolated Target publisher",
      "Verify exact main and install isolated Target publisher dependencies",
      "Download exact sensitive Target firmware handoff",
      "Validate encrypted Target handoff inventory",
      "Decrypt authenticated Target firmware handoff",
      "Validate Target firmware before signing secrets",
      "Encrypt Target OTA content for public NAS delivery",
      "Create exact production-signed immutable Target manifest",
      "Stage read back and atomically publish Target OTA",
      "Verify exact Target OTA pointer and immutable artifact over HTTPS",
      "Upload sanitized Target OTA publication evidence",
  ]
  if (
      not isinstance(publisher_steps, list)
      or [step.get("name") for step in publisher_steps] != publisher_expected_names
  ):
    raise GateError(f"{path}: personal Target publisher step order must be exact")
  publisher_expected_keys = [
      {"name", "uses", "with"},
      {"name", "uses", "with"},
      {"name", "run"},
      {"name", "uses", "with"},
      {"name", "run"},
      {"name", "env", "run"},
      {"name", "run"},
      {"name", "env", "run"},
      {"name", "env", "run"},
      {"name", "env", "run"},
      {"name", "env", "run"},
      {"name", "uses", "with"},
  ]
  for index, (step, keys) in enumerate(zip(
      publisher_steps, publisher_expected_keys
  )):
    if not isinstance(step, dict) or set(step) != keys:
      raise GateError(f"{path}: Target publisher step {index} keys are not exact")
    if "continue-on-error" in step or "if" in step:
      raise GateError(f"{path}: Target publisher steps cannot suppress failures")
  (
      publisher_checkout, publisher_setup, publisher_verify, handoff_download,
      handoff_inventory, handoff_decrypt, firmware_validate, content_encrypt,
      manifest, publish, https_readback, evidence,
  ) = publisher_steps
  if publisher_checkout.get("uses") != CHECKOUT_ACTION or publisher_checkout.get(
      "with"
  ) != {
      "ref": "${{ github.sha }}",
      "fetch-depth": 0,
      "persist-credentials": False,
      "sparse-checkout": (
          "scripts/ota_contract_gate.py\n"
          "scripts/verify_target_flash_layout.py\n"
          "ota/requirements.lock\n"
          "ota/schemas/target-manifest.schema.json\n"
          "partitions_16MB_ota.csv\n"
      ),
      "sparse-checkout-cone-mode": False,
  }:
    raise GateError(f"{path}: isolated Target publisher sparse checkout is not exact")
  if publisher_setup.get("uses") != SETUP_PYTHON_ACTION or publisher_setup.get(
      "with"
  ) != {"python-version": TARGET_PYTHON_VERSION}:
    raise GateError(f"{path}: isolated Target publisher Python setup is not exact")
  publisher_verify_run = str(publisher_verify.get("run", ""))
  for fragment in (
      'test "$GITHUB_REF" = "refs/heads/main"',
      'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
      'test "$(git rev-parse --is-shallow-repository)" = "false"',
      'if [[ "$GITHUB_EVENT_NAME" == "workflow_dispatch" ]]; then',
      'test "${{ inputs.release_target }}" = "canary"',
      'test "$GITHUB_EVENT_NAME" = "push"',
      "python -I -m pip install --no-cache-dir --require-hashes -r ota/requirements.lock",
  ):
    if publisher_verify_run.count(fragment) != 1:
      raise GateError(f"{path}: isolated Target publisher verification is incomplete")
  if "${{ secrets." in json.dumps(publisher_steps[:5], sort_keys=True):
    raise GateError(f"{path}: Target publisher secrets appear before handoff inventory")
  if handoff_download.get("uses") != DOWNLOAD_ARTIFACT_ACTION or handoff_download.get(
      "with"
  ) != {
      "name": (
          "personal-target-firmware-${{ github.sha }}-attempt-"
          "${{ github.run_attempt }}"
      ),
      "path": "sensitive-handoff",
  }:
    raise GateError(f"{path}: exact encrypted Target handoff download is not exact")
  inventory_run = str(handoff_inventory.get("run", ""))
  for fragment in (
      "find sensitive-handoff -mindepth 1 -maxdepth 1 -printf '%y %p\\n'",
      'test "${#HANDOFF_ENTRIES[@]}" -eq 1',
      'test "${HANDOFF_ENTRIES[0]}" = "f sensitive-handoff/gatekeeper-firmware.sgkenc"',
      "test ! -L sensitive-handoff/gatekeeper-firmware.sgkenc",
      "test -s sensitive-handoff/gatekeeper-firmware.sgkenc",
  ):
    if fragment not in inventory_run:
      raise GateError(f"{path}: encrypted Target handoff inventory is incomplete")
  if handoff_decrypt.get("env") != {
      "TARGET_HANDOFF_PRIVATE_KEY_HEX": "${{ secrets.TARGET_HANDOFF_PRIVATE_KEY_HEX }}",
      "TARGET_HANDOFF_PUBLIC_KEY_HEX": "${{ secrets.TARGET_HANDOFF_PUBLIC_KEY_HEX }}",
      "TARGET_HANDOFF_KEY_ID": "${{ secrets.TARGET_HANDOFF_KEY_ID }}",
  }:
    raise GateError(f"{path}: Target handoff decryption secret provenance is not exact")
  decrypt_run = str(handoff_decrypt.get("run", ""))
  for fragment in (
      f'test "$TARGET_HANDOFF_KEY_ID" = "{TARGET_HANDOFF_KEY_ID}"',
      f'test "$HANDOFF_PUBLIC_SHA256" = "{TARGET_HANDOFF_PUBLIC_KEY_SHA256}"',
      "python -I scripts/ota_contract_gate.py target-handoff-decrypt",
      "--input sensitive-handoff/gatekeeper-firmware.sgkenc",
      "--output dist/gatekeeper-firmware.bin",
      "--private-key-env TARGET_HANDOFF_PRIVATE_KEY_HEX",
      '--recipient-public-key-hex "$TARGET_HANDOFF_PUBLIC_KEY_HEX"',
      '--commit "$GITHUB_SHA"',
      '--run-attempt "$GITHUB_RUN_ATTEMPT"',
      "rm -f sensitive-handoff/gatekeeper-firmware.sgkenc",
  ):
    if fragment not in decrypt_run:
      raise GateError(f"{path}: authenticated Target handoff decryption is incomplete")
  if any(fragment in decrypt_run for fragment in (
      "OTA_SIGNING_PRIVATE_KEY_HEX", "NAS_PASSWORD", "target-manifest-create",
      "target-sftp-publish",
  )):
    raise GateError(f"{path}: Target handoff decryption gained signing or NAS authority")
  firmware_validate_run = str(firmware_validate.get("run", ""))
  for fragment in (
      'FULL_VERSION="2.1.${COMMIT_SEQUENCE}+main.g${SHORT_SHA}"',
      'TARGET_BUILD_ID="main-${COMMIT_SEQUENCE}-${GITHUB_SHA}"',
      "export FULL_VERSION TARGET_BUILD_ID",
      'version = os.environ["FULL_VERSION"].encode("ascii")',
      'if len(firmware) > 0x700000:',
      "python -I scripts/verify_target_flash_layout.py",
      "--partitions partitions_16MB_ota.csv",
      "--max-slot-usage-percent 80",
  ):
    if fragment not in firmware_validate_run:
      raise GateError(f"{path}: Target firmware pre-sign verification is incomplete")
  if content_encrypt.get("env") != PERSONAL_TARGET_CONTENT_ENV:
    raise GateError(f"{path}: Target NAS content encryption provenance is not exact")
  content_encrypt_run = str(content_encrypt.get("run", ""))
  for fragment in (
      '[[ "$TARGET_CONTENT_KEY_HEX" =~ ^[0-9a-f]{64}$ ]]',
      f'test "$TARGET_CONTENT_KEY_ID" = "{TARGET_CONTENT_KEY_ID}"',
      "python -I scripts/ota_contract_gate.py target-content-encrypt",
      "--artifact dist/gatekeeper-firmware.bin",
      "--output dist/gatekeeper-firmware.sgkenc",
      "--key-env TARGET_CONTENT_KEY_HEX",
      '--key-id "$TARGET_CONTENT_KEY_ID"',
      "python -I scripts/ota_contract_gate.py target-content-decrypt",
      '--output "$ROUNDTRIP"',
      'cmp dist/gatekeeper-firmware.bin "$ROUNDTRIP"',
      'rm -f "$ROUNDTRIP"',
      "test -s dist/gatekeeper-firmware.sgkenc",
      "test -s dist/gatekeeper-firmware.bin",
      '--commit "$GITHUB_SHA"',
  ):
    if fragment not in content_encrypt_run:
      raise GateError(f"{path}: Target NAS content encryption is incomplete")
  if any(fragment in content_encrypt_run for fragment in (
      "OTA_SIGNING_PRIVATE_KEY_HEX", "NAS_PASSWORD", "target-manifest-create",
      "target-sftp-publish",
  )):
    raise GateError(
        f"{path}: Target content encryption gained signing or NAS authority"
    )
  publisher_serialized = json.dumps(job, sort_keys=True)
  for forbidden in (
      "platformio", "flutter", "gradle", "unittest", "pytest", "src/", "include/",
      "gatekeeper-firmware-first.bin", "secrets.h",
  ):
    if forbidden in publisher_serialized:
      raise GateError(f"{path}: isolated Target publisher executes candidate build code")

  if manifest.get("env") != PERSONAL_TARGET_MANIFEST_ENV:
    raise GateError(f"{path}: personal Target signing provenance is not exact")
  manifest_run = str(manifest.get("run", ""))
  for fragment in (
      'IMMUTABLE_ARTIFACT_URL="${TARGET_ARTIFACT_URL%/*}/gatekeeper-firmware-${GITHUB_SHA}.sgkenc"',
      'PUBLISHED_AT="$(git show -s --format=%cI "$GITHUB_SHA")"',
      "python -I scripts/ota_contract_gate.py target-manifest-create",
      "python -I scripts/ota_contract_gate.py target-manifest-verify",
      '--version "$FULL_VERSION"',
      '--commit "$GITHUB_SHA"',
      '--build-id "$TARGET_BUILD_ID"',
      '--artifact-url "$IMMUTABLE_ARTIFACT_URL"',
      "--plaintext-artifact dist/gatekeeper-firmware.bin",
      '--encryption-key-id "$TARGET_CONTENT_KEY_ID"',
      '--private-key-env TARGET_PRIVATE_KEY_HEX',
      "--artifact dist/gatekeeper-firmware.sgkenc",
      '--expected-encryption-key-id "$TARGET_CONTENT_KEY_ID"',
      "rm -f dist/gatekeeper-firmware.bin",
      "test ! -e dist/gatekeeper-firmware.bin",
  ):
    if fragment not in manifest_run:
      raise GateError(f"{path}: personal Target signed immutable manifest is incomplete")
  if manifest_run.count("target-manifest-create") != 1 or manifest_run.count(
      "target-manifest-verify"
  ) != 1:
    raise GateError(f"{path}: personal Target manifest create/verify count is not exact")

  if publish.get("env") != PERSONAL_TARGET_PUBLISH_ENV:
    raise GateError(f"{path}: personal Target NAS/signing input provenance is not exact")
  publish_run = str(publish.get("run", ""))
  for fragment in (
      'test -n "$NAS_KNOWN_HOSTS"',
      'printf \'%s\\n\' "$NAS_KNOWN_HOSTS" > "$KNOWN_HOSTS_FILE"',
      "repository-secret-pinned",
      "ssh-keygen -l -E sha256",
      "python -I scripts/ota_contract_gate.py target-sftp-publish",
      "--artifact dist/gatekeeper-firmware.sgkenc",
      '--expected-version "$FULL_VERSION"',
      '--expected-commit "$GITHUB_SHA"',
      '--expected-build-id "$TARGET_BUILD_ID"',
      '--run-attempt "$GITHUB_RUN_ATTEMPT"',
      "dist/target-ota-publish-evidence.json",
  ):
    if fragment not in publish_run:
      raise GateError(f"{path}: staged/readback/atomic Target NAS publish is incomplete")
  if any(fragment in publish_run for fragment in (
      "StrictHostKeyChecking=no", "set +e", "continue-on-error",
      "ssh-keyscan", "runtime-keyscan-unpinned",
      "ota_contract_gate.py release", "production_authorized: true",
  )):
    raise GateError(f"{path}: personal Target OTA publication adds a release bypass")

  if https_readback.get("env") != PERSONAL_TARGET_HTTPS_ENV:
    raise GateError(f"{path}: personal Target HTTPS readback provenance is not exact")
  https_run = str(https_readback.get("run", ""))
  for fragment in (
      'IMMUTABLE_ARTIFACT_URL="${TARGET_FIRMWARE_URL%/*}/gatekeeper-firmware-${GITHUB_SHA}.sgkenc"',
      'test -n "$TARGET_ROOT_CA_CERT"',
      f'test "$TARGET_CONTENT_KEY_ID" = "{TARGET_CONTENT_KEY_ID}"',
      'printf \'%s\\n\' "$TARGET_ROOT_CA_CERT" > "$CA_FILE"',
      'chmod 600 "$CA_FILE"',
      'trap \'rm -f "$CA_FILE"\' EXIT',
      'fetch_exact "$TARGET_VERSION_URL" https-readback/version.json dist/version.json',
      'fetch_exact "$IMMUTABLE_ARTIFACT_URL" https-readback/gatekeeper-firmware.sgkenc dist/gatekeeper-firmware.sgkenc',
      'cmp "$expected" "$destination"',
      "curl --fail --silent --show-error --location",
      "--proto '=https' --proto-redir '=https' --cacert \"$CA_FILE\"",
      "python -I scripts/ota_contract_gate.py target-manifest-verify",
      "--manifest https-readback/version.json",
      "--artifact https-readback/gatekeeper-firmware.sgkenc",
      '--expected-version "$FULL_VERSION"',
      '--expected-commit "$GITHUB_SHA"',
      '--expected-build-id "$TARGET_BUILD_ID"',
      '--expected-encryption-key-id "$TARGET_CONTENT_KEY_ID"',
  ):
    if fragment not in https_run:
      raise GateError(f"{path}: exact Target OTA HTTPS readback is incomplete")

  if evidence.get("uses") != UPLOAD_ARTIFACT_ACTION or evidence.get("with") != {
      "name": (
          "target-ota-publish-evidence-${{ github.sha }}-attempt-"
          "${{ github.run_attempt }}"
      ),
      "path": "dist/target-ota-publish-evidence.json",
      "if-no-files-found": "error",
      "retention-days": 30,
  }:
    raise GateError(f"{path}: sanitized Target OTA evidence upload is not exact")


PERSONAL_MOBILE_EMBEDDED_BUILD_ENV = {
    "APK_VERSION_URL": "${{ secrets.SECRET_APK_VERSION_URL }}",
    "APK_FALLBACK_VERSION_URL": "${{ secrets.SECRET_APK_FALLBACK_VERSION_URL }}",
    "MOBILE_UPDATE_KEY_ID": "${{ secrets.OTA_SIGNING_KEY_ID }}",
    "MOBILE_UPDATE_PUBLIC_KEY_HEX": "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
    "GATEKEEPER_API_KEY": "${{ secrets.GATEKEEPER_API_KEY }}",
}

PERSONAL_TARGET_CONTENT_ENV = {
    "TARGET_CONTENT_KEY_HEX": "${{ secrets.SECRET_OTA_CONTENT_KEY_HEX }}",
    "TARGET_CONTENT_KEY_ID": "${{ secrets.SECRET_OTA_CONTENT_KEY_ID }}",
}

PERSONAL_TARGET_BUILD_JOB = "build_personal_target_ota_firmware"
PERSONAL_TARGET_PUBLISH_JOB = "publish_personal_target_ota"
PERSONAL_TARGET_AUTO_CONDITION = (
    "github.ref == 'refs/heads/main' && (github.event_name == 'push' || "
    "(github.event_name == 'workflow_dispatch' && inputs.release_target == 'canary'))"
)

PERSONAL_MOBILE_UNSIGNED_JOB = "build_personal_mobile_ota_unsigned"
PERSONAL_MOBILE_PUBLISH_JOB = "publish_personal_mobile_ota"
PERSONAL_MOBILE_AUTO_CONDITION = (
    "github.ref == 'refs/heads/main' && (github.event_name == 'push' || "
    "(github.event_name == 'workflow_dispatch' && inputs.release_target == 'canary'))"
)

PERSONAL_MOBILE_ENVIRONMENT = "personal-auto-ota"
PERSONAL_MOBILE_UNSIGNED_MIN_BYTES = 1048576
PERSONAL_MOBILE_UNSIGNED_MAX_BYTES = 209715200
PERSONAL_MOBILE_TOOLCHAIN = {
    "jdk_url": (
        "https://github.com/adoptium/temurin17-binaries/releases/download/"
        "jdk-17.0.16%2B8/OpenJDK17U-jdk_x64_linux_hotspot_17.0.16_8.tar.gz"
    ),
    "jdk_size": "192062472",
    "jdk_sha256": (
        "166774efcf0f722f2ee18eba0039de2d685b350ee14d7b69e6f83437dafd2af1"
    ),
    "build_tools_url": (
        "https://dl.google.com/android/repository/build-tools_r36_linux.zip"
    ),
    "build_tools_size": "63737259",
    "build_tools_sha256": (
        "5d9ac77fb6ff43d9da518a337b4fcf8f9097113df531d99ccefe80ef7ce8250b"
    ),
    "cmdline_tools_url": (
        "https://dl.google.com/android/repository/"
        "commandlinetools-linux-11076708_latest.zip"
    ),
    "cmdline_tools_size": "153607504",
    "cmdline_tools_sha256": (
        "2d2d50857e4eb553af5a6dc3ad507a17adf43d115264b1afc116f95c92e5e258"
    ),
    "apksigner_jar_size": "1100545",
    "apksigner_jar_sha256": (
        "3716d9311e55d2b0918a2fd9d54ba9e406c5f6abeea700b287f11259bc163dec"
    ),
}

PERSONAL_MOBILE_MANIFEST_ENV = {
    "APK_DOWNLOAD_URL": "${{ secrets.SECRET_APK_DOWNLOAD_URL }}",
    "APK_FALLBACK_DOWNLOAD_URL": "${{ secrets.SECRET_APK_FALLBACK_DOWNLOAD_URL }}",
    "APK_RELEASE_NOTES_URL": "${{ secrets.SECRET_APK_RELEASE_NOTES_URL }}",
    "MOBILE_UPDATE_PRIVATE_KEY_HEX": (
        "${{ secrets.MOBILE_OTA_SIGNING_PRIVATE_KEY_HEX }}"
    ),
    "MOBILE_UPDATE_PUBLIC_KEY_HEX": (
        "${{ secrets.MOBILE_OTA_SIGNING_PUBLIC_KEY_HEX }}"
    ),
    "MOBILE_UPDATE_KEY_ID": "${{ secrets.MOBILE_OTA_SIGNING_KEY_ID }}",
}

PERSONAL_MOBILE_PUBLISH_ENV = {
    "MOBILE_PUBLIC_KEY_HEX": (
        "${{ secrets.MOBILE_OTA_SIGNING_PUBLIC_KEY_HEX }}"
    ),
    "NAS_HOST": "${{ secrets.NAS_HOST }}",
    "NAS_USER": "${{ secrets.NAS_USER }}",
    "NAS_PASSWORD": "${{ secrets.NAS_PASSWORD }}",
    "NAS_PORT": "${{ secrets.NAS_PORT || 22 }}",
    "NAS_APK_TARGET_DIR": "${{ secrets.NAS_APK_TARGET_DIR }}",
    "NAS_APK_FALLBACK_TARGET_DIR": (
        "${{ secrets.NAS_APK_FALLBACK_TARGET_DIR || "
        "'/docker/smartbox_ota/gatekeeper_apk_fallback' }}"
    ),
}

PERSONAL_MOBILE_HTTPS_ENV = {
    "APK_VERSION_URL": "${{ secrets.SECRET_APK_VERSION_URL }}",
    "APK_FALLBACK_VERSION_URL": "${{ secrets.SECRET_APK_FALLBACK_VERSION_URL }}",
    "APK_DOWNLOAD_URL": "${{ secrets.SECRET_APK_DOWNLOAD_URL }}",
    "APK_FALLBACK_DOWNLOAD_URL": "${{ secrets.SECRET_APK_FALLBACK_DOWNLOAD_URL }}",
}


def _validate_personal_mobile_ota_job(
    path: str,
    build_job_name: str,
    jobs: dict[str, Any],
) -> None:
  if path != ".github/workflows/build_app.yml":
    if any(name in jobs for name in (
        PERSONAL_MOBILE_UNSIGNED_JOB, PERSONAL_MOBILE_PUBLISH_JOB
    )):
      raise GateError(f"{path}: mobile OTA auto-publish belongs only in build_app.yml")
    return
  unsigned_job = jobs.get(PERSONAL_MOBILE_UNSIGNED_JOB)
  if not isinstance(unsigned_job, dict):
    raise GateError(f"{path}: exact-main unsigned personal mobile OTA job is required")
  job = jobs.get(PERSONAL_MOBILE_PUBLISH_JOB)
  if not isinstance(job, dict):
    raise GateError(f"{path}: exact-main personal mobile OTA job is required")
  if set(unsigned_job) != {"name", "needs", "if", "runs-on", "steps"}:
    raise GateError(f"{path}: unsigned personal mobile OTA job keys must be exact")
  if unsigned_job.get("name") != (
      "Build exact-main unsigned personal mobile OTA with APK-embedded inputs"
  ):
    raise GateError(f"{path}: unsigned personal mobile OTA job name is not exact")
  if unsigned_job.get("needs") not in (build_job_name, [build_job_name]):
    raise GateError(f"{path}: unsigned personal mobile OTA must need public build/test")
  if " ".join(str(unsigned_job.get("if", "")).split()) != PERSONAL_MOBILE_AUTO_CONDITION:
    raise GateError(f"{path}: unsigned personal mobile trigger must be exact")
  if unsigned_job.get("runs-on") != UBUNTU_RUNNER:
    raise GateError(f"{path}: unsigned personal mobile runner must be {UBUNTU_RUNNER}")
  if "environment" in unsigned_job or "concurrency" in unsigned_job:
    raise GateError(f"{path}: unsigned mobile build cannot gain an environment or deployment lock")
  if set(job) != {
      "name", "needs", "if", "environment", "concurrency", "runs-on", "steps"
  }:
    raise GateError(f"{path}: personal mobile OTA job keys must be exact")
  if job.get("name") != "Sign and atomically publish personal mobile OTA":
    raise GateError(f"{path}: personal mobile OTA job name is not exact")
  if job.get("needs") not in (
      PERSONAL_MOBILE_UNSIGNED_JOB, [PERSONAL_MOBILE_UNSIGNED_JOB]
  ):
    raise GateError(f"{path}: mobile publisher must need only the unsigned producer")
  if " ".join(str(job.get("if", "")).split()) != PERSONAL_MOBILE_AUTO_CONDITION:
    raise GateError(f"{path}: personal mobile OTA trigger must be exact main push/canary dispatch")
  if job.get("environment") != PERSONAL_MOBILE_ENVIRONMENT:
    raise GateError(f"{path}: personal mobile OTA requires the main-only environment")
  if job.get("concurrency") != {
      "group": "smart-gatekeeper-personal-mobile-ota-main",
      "cancel-in-progress": False,
  }:
    raise GateError(f"{path}: personal mobile OTA concurrency contract is not exact")
  if job.get("runs-on") != UBUNTU_RUNNER:
    raise GateError(f"{path}: personal mobile OTA runner must be {UBUNTU_RUNNER}")

  unsigned_steps = unsigned_job.get("steps")
  unsigned_expected_names = [
      "Checkout exact main mobile source without credentials",
      "Set up Java JDK 17 for unsigned mobile build",
      "Set up Flutter SDK for unsigned mobile build",
      "Verify exact main and resolve unsigned mobile dependencies",
      "Build unsigned exact personal mobile release",
      "Upload exact unsigned personal mobile artifact",
  ]
  if (
      not isinstance(unsigned_steps, list)
      or [step.get("name") for step in unsigned_steps] != unsigned_expected_names
  ):
    raise GateError(f"{path}: unsigned personal mobile step order must be exact")
  unsigned_expected_keys = [
      {"name", "uses", "with"},
      {"name", "uses", "with"},
      {"name", "uses", "with"},
      {"name", "run"},
      {"name", "env", "run"},
      {"name", "uses", "with"},
  ]
  for index, (step, keys) in enumerate(zip(unsigned_steps, unsigned_expected_keys)):
    if not isinstance(step, dict) or set(step) != keys:
      raise GateError(f"{path}: unsigned personal mobile step {index} keys are not exact")
    if "continue-on-error" in step or "if" in step:
      raise GateError(f"{path}: unsigned personal mobile steps cannot suppress failures")
  (
      unsigned_checkout, unsigned_java, unsigned_flutter, unsigned_verify,
      unsigned_build, unsigned_upload,
  ) = unsigned_steps
  if unsigned_checkout.get("uses") != CHECKOUT_ACTION or unsigned_checkout.get(
      "with"
  ) != {"ref": "${{ github.sha }}", "persist-credentials": False}:
    raise GateError(f"{path}: unsigned mobile checkout identity is not exact")
  if unsigned_java.get("uses") != SETUP_JAVA_ACTION or unsigned_java.get("with") != {
      "distribution": "temurin", "java-version": JAVA_VERSION
  }:
    raise GateError(f"{path}: unsigned mobile Java setup is not exact")
  if unsigned_flutter.get("uses") != FLUTTER_ACTION or unsigned_flutter.get(
      "with"
  ) != {"flutter-version": FLUTTER_VERSION, "channel": "stable", "cache": True}:
    raise GateError(f"{path}: unsigned mobile Flutter setup is not exact")
  unsigned_verify_run = str(unsigned_verify.get("run", ""))
  for fragment in (
      'test "$GITHUB_REF" = "refs/heads/main"',
      'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
      'if [[ "$GITHUB_EVENT_NAME" == "workflow_dispatch" ]]; then',
      'test "${{ inputs.release_target }}" = "canary"',
      'test "$GITHUB_EVENT_NAME" = "push"',
      "cd gatekeeper_app",
      "flutter pub get",
  ):
    if unsigned_verify_run.count(fragment) != 1:
      raise GateError(f"{path}: unsigned mobile exact-main verification is incomplete")
  if "${{ secrets." in json.dumps(unsigned_steps[:4], sort_keys=True):
    raise GateError(f"{path}: APK-embedded inputs appear before exact-main verification")
  if unsigned_build.get("env") != PERSONAL_MOBILE_EMBEDDED_BUILD_ENV:
    raise GateError(f"{path}: unsigned mobile APK-embedded input provenance is not exact")
  unsigned_build_run = str(unsigned_build.get("run", ""))
  for fragment in (
      'test "$MOBILE_UPDATE_KEY_ID" = "personal-legacy-target-20260812-1"',
      'test "$MOBILE_PUBLIC_KEY_SHA256" = "87d8b43a994f1021feca0d7079658f02bee2eb2f5711e67b12d450f841af08c5"',
      '[[ "$GITHUB_RUN_NUMBER" =~ ^[1-9][0-9]*$ ]]',
      '[[ "$GITHUB_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]]',
      "MOBILE_BUILD_NUMBER=$((RUN_NUMBER_DEC * 100 + RUN_ATTEMPT_DEC))",
      "((MOBILE_BUILD_NUMBER > 141 && MOBILE_BUILD_NUMBER <= 2100000000))",
      'FULL_VERSION="1.0.0-g$(git rev-parse --short HEAD)"',
      "printf '%s\\n' \"$GITHUB_SHA\" > gatekeeper_app/assets/source_commit.txt",
      "export SGK_UNSIGNED_CI_RELEASE=1",
      "flutter build apk --release",
      '--build-name="$FULL_VERSION"',
      '--build-number="$MOBILE_BUILD_NUMBER"',
      '--dart-define=UPDATE_SIGNING_KEY_ID="$MOBILE_UPDATE_KEY_ID"',
      '--dart-define=UPDATE_SIGNING_PUBLIC_KEY_B64="$MOBILE_UPDATE_PUBLIC_KEY_B64"',
      "find gatekeeper_app/build/app/outputs/flutter-apk",
      "test \"${#APK_CANDIDATES[@]}\" -eq 1",
      "unsigned-dist/ks-house-gatekeeper-unsigned.apk",
  ):
    if fragment not in unsigned_build_run:
      raise GateError(f"{path}: exact unsigned personal mobile build is incomplete")
  if unsigned_build_run.count("SGK_UNSIGNED_CI_RELEASE") != 1:
    raise GateError(f"{path}: unsigned release escape hatch must occur once in its exact job")
  unsigned_serialized = json.dumps(unsigned_job, sort_keys=True)
  forbidden_unsigned = (
      "ANDROID_KEYSTORE", "OTA_SIGNING_PRIVATE_KEY_HEX", "MOBILE_UPDATE_PRIVATE_KEY_HEX",
      "NAS_PASSWORD", "NAS_KNOWN_HOSTS", "mobile-manifest-create",
      "mobile-sftp-publish", "apksigner", "key.properties", "upload-keystore.jks",
      "environment:", "production_authorized: true",
  )
  if any(fragment in unsigned_serialized for fragment in forbidden_unsigned):
    raise GateError(f"{path}: unsigned mobile build gained a private signing or deployment surface")
  expected_public_secret_refs = {
      "${{ secrets.SECRET_APK_VERSION_URL }}",
      "${{ secrets.SECRET_APK_FALLBACK_VERSION_URL }}",
      "${{ secrets.OTA_SIGNING_KEY_ID }}",
      "${{ secrets.OTA_SIGNING_PUBLIC_KEY_HEX }}",
      "${{ secrets.GATEKEEPER_API_KEY }}",
  }
  actual_public_secret_refs = set(re.findall(r"\$\{\{ secrets\.[^}]+\}\}", unsigned_serialized))
  if actual_public_secret_refs != expected_public_secret_refs:
    raise GateError(f"{path}: unsigned mobile job may receive only exact APK-embedded inputs")
  if unsigned_upload.get("uses") != UPLOAD_ARTIFACT_ACTION or unsigned_upload.get(
      "with"
  ) != {
      "name": (
          "personal-mobile-unsigned-${{ github.sha }}-attempt-"
          "${{ github.run_attempt }}"
      ),
      "path": "unsigned-dist/ks-house-gatekeeper-unsigned.apk",
      "if-no-files-found": "error",
      "retention-days": 1,
  }:
    raise GateError(f"{path}: exact unsigned mobile artifact handoff is not exact")

  steps = job.get("steps")
  expected_names = [
      "Checkout exact main source for personal mobile OTA",
      "Set up Python for personal mobile OTA",
      "Verify exact main and install isolated publisher dependencies",
      "Download exact unsigned personal mobile artifact",
      "Verify exact unsigned artifact inventory",
      "Install verified personal mobile signing toolchain",
      "Calculate exact personal mobile identity",
      "Align and sign exact personal mobile APK",
      "Verify pinned Android signer and package identity",
      "Create and verify personal signed mobile manifest",
      "Preserve exact personal mobile OTA artifact",
      "Prepare strict NAS host identity for personal mobile OTA",
      "Atomically publish and read back primary and fallback mobile OTA",
      "Preserve sanitized personal mobile publication evidence",
      "Verify primary and fallback OTA over HTTPS",
  ]
  if not isinstance(steps, list) or [step.get("name") for step in steps] != expected_names:
    raise GateError(f"{path}: personal mobile OTA step order must be exact")
  expected_keys = [
      {"name", "uses", "with"},
      {"name", "uses", "with"},
      {"name", "run"},
      {"name", "uses", "with"},
      {"name", "run"},
      {"name", "run"},
      {"name", "run"},
      {"name", "env", "run"},
      {"name", "run"},
      {"name", "env", "run"},
      {"name", "uses", "with"},
      {"name", "env", "run"},
      {"name", "env", "run"},
      {"name", "uses", "with"},
      {"name", "env", "run"},
  ]
  for index, (step, keys) in enumerate(zip(steps, expected_keys)):
    if not isinstance(step, dict) or set(step) != keys:
      raise GateError(f"{path}: personal mobile OTA step {index} keys are not exact")
    if "continue-on-error" in step or "if" in step:
      raise GateError(f"{path}: personal mobile OTA steps cannot suppress failures")
    non_env_step = {key: value for key, value in step.items() if key != "env"}
    if "${{ secrets." in json.dumps(non_env_step, sort_keys=True):
      raise GateError(
          f"{path}: personal mobile secrets are allowed only through exact step env"
      )

  (
      checkout, python, verify, unsigned_download, unsigned_inventory,
      toolchain, calculate_identity, sign, identity, manifest,
      artifact_upload, host_identity, publish, evidence_upload, https_readback,
  ) = steps
  if checkout.get("uses") != CHECKOUT_ACTION or checkout.get("with") != {
      "ref": "${{ github.sha }}",
      "persist-credentials": False,
      "sparse-checkout": (
          "scripts/ota_contract_gate.py\nota/requirements.lock\n"
          "ota/schemas/mobile-manifest.schema.json\n"
      ),
      "sparse-checkout-cone-mode": False,
  }:
    raise GateError(f"{path}: personal mobile OTA checkout identity is not exact")
  if python.get("uses") != SETUP_PYTHON_ACTION or python.get("with") != {
      "python-version": MOBILE_PYTHON_VERSION,
  }:
    raise GateError(f"{path}: personal mobile OTA Python setup is not exact")
  verify_run = str(verify.get("run", ""))
  for fragment in (
      'test "$GITHUB_REF" = "refs/heads/main"',
      'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
      'if [[ "$GITHUB_EVENT_NAME" == "workflow_dispatch" ]]; then',
      'test "${{ inputs.release_target }}" = "canary"',
      'test "$GITHUB_EVENT_NAME" = "push"',
      "python -I -m pip install --no-cache-dir --require-hashes -r ota/requirements.lock",
  ):
    if verify_run.count(fragment) != 1:
      raise GateError(f"{path}: personal mobile exact-main verification is incomplete")
  if any(fragment in verify_run for fragment in ("set +e", "|| true")):
    raise GateError(f"{path}: personal mobile exact-main verification must fail closed")

  if unsigned_download.get("uses") != DOWNLOAD_ARTIFACT_ACTION or unsigned_download.get(
      "with"
  ) != {
      "name": (
          "personal-mobile-unsigned-${{ github.sha }}-attempt-"
          "${{ github.run_attempt }}"
      ),
      "path": "unsigned-dist",
  }:
    raise GateError(f"{path}: exact unsigned mobile artifact download is not exact")
  unsigned_inventory_run = str(unsigned_inventory.get("run", ""))
  for fragment in (
      "find unsigned-dist -mindepth 1 -maxdepth 1 -print0",
      'test "${#DOWNLOADED_ENTRIES[@]}" -eq 1',
      'UNSIGNED_APK="unsigned-dist/ks-house-gatekeeper-unsigned.apk"',
      'test "${DOWNLOADED_ENTRIES[0]}" = "$UNSIGNED_APK"',
      'test -f "$UNSIGNED_APK"',
      'test ! -L "$UNSIGNED_APK"',
      'UNSIGNED_APK_SIZE="$(stat -c%s "$UNSIGNED_APK")"',
      (
          f"((UNSIGNED_APK_SIZE >= {PERSONAL_MOBILE_UNSIGNED_MIN_BYTES} && "
          f"UNSIGNED_APK_SIZE <= {PERSONAL_MOBILE_UNSIGNED_MAX_BYTES}))"
      ),
      'UNSIGNED_APK_SHA256="$(sha256sum "$UNSIGNED_APK" | cut -d\' \' -f1)"',
      'echo "UNSIGNED_APK_SIZE=${UNSIGNED_APK_SIZE}" >> "$GITHUB_ENV"',
      'echo "UNSIGNED_APK_SHA256=${UNSIGNED_APK_SHA256}" >> "$GITHUB_ENV"',
  ):
    if fragment not in unsigned_inventory_run:
      raise GateError(f"{path}: unsigned mobile artifact inventory is incomplete")
  if "-type f" in unsigned_inventory_run:
    raise GateError(f"{path}: unsigned mobile inventory must reject non-file extras")

  toolchain_run = str(toolchain.get("run", ""))
  for value in PERSONAL_MOBILE_TOOLCHAIN.values():
    if toolchain_run.count(value) != 1:
      raise GateError(f"{path}: personal mobile toolchain bytes are not exactly pinned")
  for fragment in (
      'curl --fail --silent --show-error --location',
      "--proto '=https' --proto-redir '=https'",
      'test "$(stat -c%s "$output")" = "$expected_size"',
      'sha256sum --check --strict',
      'reject_unsafe_entry "$entry"',
      'tar -tzf "$JDK_ARCHIVE"',
      'unzip -Z1 "$BUILD_TOOLS_ARCHIVE"',
      'unzip -Z1 "$CMDLINE_TOOLS_ARCHIVE"',
      'JAVA_HOME="${TOOLCHAIN_ROOT}/jdk-17.0.16+8"',
      'JAVA_BIN="${JAVA_HOME}/bin/java"',
      'ZIPALIGN="${TOOLCHAIN_ROOT}/build-tools/36.0.0/zipalign"',
      'APKSIGNER_JAR="${TOOLCHAIN_ROOT}/build-tools/36.0.0/lib/apksigner.jar"',
      'APKANALYZER="${TOOLCHAIN_ROOT}/cmdline-tools/12.0/bin/apkanalyzer"',
      "grep -Fx 'Pkg.Revision=36.0.0'",
      "grep -Fx 'Pkg.Revision=12.0'",
      'test "$(stat -c%s "$APKSIGNER_JAR")" = "$APKSIGNER_JAR_SIZE"',
      '"$JAVA_BIN" -version 2>&1 | grep -F \'openjdk version "17.0.16"\'',
      '"$JAVA_BIN" -version 2>&1 | grep -F \'Temurin-17.0.16+8\'',
      '"$JAVA_BIN" -jar "$APKSIGNER_JAR" version',
      'echo "JAVA_HOME=${JAVA_HOME}" >> "$GITHUB_ENV"',
      'echo "SGK_APKSIGNER_JAVA=${JAVA_BIN}" >> "$GITHUB_ENV"',
  ):
    if fragment not in toolchain_run:
      raise GateError(f"{path}: verified personal mobile toolchain setup is incomplete")
  if any(fragment in toolchain_run for fragment in (
      "setup-java", "sdkmanager", "ANDROID_SDK_ROOT", "ANDROID_HOME", "|| true",
      "set +e", "/usr/bin/java", "command -v java", "which java",
  )):
    raise GateError(f"{path}: personal mobile toolchain uses a mutable source")
  exact_fetches = (
      'fetch_verified "$JDK_URL" "$JDK_ARCHIVE" "$JDK_SIZE" "$JDK_SHA256"',
      'fetch_verified "$BUILD_TOOLS_URL" "$BUILD_TOOLS_ARCHIVE"',
      'fetch_verified "$CMDLINE_TOOLS_URL" "$CMDLINE_TOOLS_ARCHIVE"',
  )
  if any(toolchain_run.count(fragment) != 1 for fragment in exact_fetches):
    raise GateError(f"{path}: personal mobile toolchain fetch set is not exact")
  ordered_fragments = (
      'curl --fail --silent --show-error --location',
      'test "$(stat -c%s "$output")" = "$expected_size"',
      'printf \'%s  %s\\n\' "$expected_sha256" "$output"',
      exact_fetches[0],
      exact_fetches[1],
      exact_fetches[2],
      'tar -tzf "$JDK_ARCHIVE"',
      'unzip -Z1 "$BUILD_TOOLS_ARCHIVE"',
      'unzip -Z1 "$CMDLINE_TOOLS_ARCHIVE"',
      'tar -xzf "$JDK_ARCHIVE" -C "$TOOLCHAIN_ROOT"',
      'unzip -q "$BUILD_TOOLS_ARCHIVE" -d "$TOOLCHAIN_ROOT/build-tools"',
      'unzip -q "$CMDLINE_TOOLS_ARCHIVE" -d "$TOOLCHAIN_ROOT/cmdline-tools"',
  )
  ordered_positions = [toolchain_run.find(fragment) for fragment in ordered_fragments]
  if any(position < 0 for position in ordered_positions) or ordered_positions != sorted(
      ordered_positions
  ):
    raise GateError(
        f"{path}: personal mobile toolchain download/verify/extract order is not exact"
    )
  expected_tool_exports = {
      'echo "JAVA_HOME=${JAVA_HOME}" >> "$GITHUB_ENV"',
      'echo "JAVA_BIN=${JAVA_BIN}" >> "$GITHUB_ENV"',
      'echo "ZIPALIGN=${ZIPALIGN}" >> "$GITHUB_ENV"',
      'echo "APKSIGNER_JAR=${APKSIGNER_JAR}" >> "$GITHUB_ENV"',
      'echo "APKANALYZER=${APKANALYZER}" >> "$GITHUB_ENV"',
      'echo "SGK_APKSIGNER_JAVA=${JAVA_BIN}" >> "$GITHUB_ENV"',
  }
  actual_tool_exports = {
      line.strip() for line in toolchain_run.splitlines()
      if '>> "$GITHUB_ENV"' in line
  }
  if actual_tool_exports != expected_tool_exports:
    raise GateError(f"{path}: personal mobile toolchain environment export is not exact")
  for variable in (
      "JAVA_HOME", "JAVA_BIN", "ZIPALIGN", "APKSIGNER_JAR", "APKANALYZER"
  ):
    if len(re.findall(rf"(?m)^\s*{variable}=", toolchain_run)) != 1:
      raise GateError(f"{path}: personal mobile toolchain variable binding is not exact")

  secret_free_prefix = json.dumps(steps[:7], sort_keys=True)
  if "${{ secrets." in secret_free_prefix:
    raise GateError(
        f"{path}: personal mobile secrets appear before artifact and toolchain verification"
    )
  if any(fragment in secret_free_prefix for fragment in (
      "flutter", "gradle", "unittest", "pytest", "ota_contract_gate.py contract",
      "gatekeeper_app", "src/", "include/",
  )):
    raise GateError(f"{path}: privileged mobile publisher executes candidate build/test code")
  protected_tool_variables = (
      "JAVA_HOME", "JAVA_BIN", "ZIPALIGN", "APKSIGNER_JAR", "APKANALYZER",
      "SGK_APKSIGNER_JAVA",
  )
  for protected_step in steps[6:]:
    protected_run = str(protected_step.get("run", ""))
    if any(re.search(
        rf"(?m)^\s*(?:export\s+)?{variable}=", protected_run
    ) for variable in protected_tool_variables):
      raise GateError(f"{path}: verified personal mobile tool binding was replaced")
    if any(
        f'echo "{variable}=' in protected_run
        for variable in protected_tool_variables
    ):
      raise GateError(f"{path}: verified personal mobile tool environment was replaced")

  calculate_run = str(calculate_identity.get("run", ""))
  for fragment in (
      'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
      '[[ "$GITHUB_RUN_NUMBER" =~ ^[1-9][0-9]*$ ]]',
      '[[ "$GITHUB_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]]',
      "MOBILE_BUILD_NUMBER=$((RUN_NUMBER_DEC * 100 + RUN_ATTEMPT_DEC))",
      "((MOBILE_BUILD_NUMBER > 141 && MOBILE_BUILD_NUMBER <= 2100000000))",
      'FULL_VERSION="1.0.0-g$(git rev-parse --short HEAD)"',
      'echo "FULL_VERSION=${FULL_VERSION}" >> "$GITHUB_ENV"',
      'echo "MOBILE_BUILD_NUMBER=${MOBILE_BUILD_NUMBER}" >> "$GITHUB_ENV"',
  ):
    if fragment not in calculate_run:
      raise GateError(f"{path}: exact personal mobile identity calculation is incomplete")

  if sign.get("env") != {
      "KEYSTORE_BASE64": "${{ secrets.ANDROID_KEYSTORE_BASE64 }}",
      "ANDROID_KEYSTORE_PASSWORD": "${{ secrets.ANDROID_KEYSTORE_PASSWORD }}",
      "ANDROID_KEY_ALIAS": "${{ secrets.ANDROID_KEY_ALIAS }}",
  }:
    raise GateError(f"{path}: personal Android signing secret provenance is not exact")
  sign_run = str(sign.get("run", ""))
  for fragment in (
      '[[ "$ANDROID_KEY_ALIAS" =~ ^[A-Za-z0-9._-]{1,128}$ ]]',
      'test -x "$JAVA_BIN"',
      'test -x "$ZIPALIGN"',
      'test -f "$APKSIGNER_JAR"',
      'test -x "$APKANALYZER"',
      'UNSIGNED_APK="unsigned-dist/ks-house-gatekeeper-unsigned.apk"',
      'test "$(stat -c%s "$UNSIGNED_APK")" = "$UNSIGNED_APK_SIZE"',
      'printf \'%s  %s\\n\' "$UNSIGNED_APK_SHA256" "$UNSIGNED_APK"',
      '"$JAVA_BIN" -jar "$APKSIGNER_JAR" verify "$UNSIGNED_APK"',
      'KEYSTORE_PATH="${RUNNER_TEMP}/personal-mobile-release.jks"',
      'ALIGNED_APK="${RUNNER_TEMP}/ks-house-gatekeeper-aligned.apk"',
      "trap 'rm -f \"$KEYSTORE_PATH\" \"$ALIGNED_APK\"' EXIT",
      'printf \'%s\' "$KEYSTORE_BASE64" | base64 --decode > "$KEYSTORE_PATH"',
      'chmod 600 "$KEYSTORE_PATH"',
      '"$ZIPALIGN" -p -f 4 "$UNSIGNED_APK" "$ALIGNED_APK"',
      '"$ZIPALIGN" -c -p 4 "$ALIGNED_APK"',
      '"$JAVA_BIN" -jar "$APKSIGNER_JAR" sign',
      '--ks-pass env:ANDROID_KEYSTORE_PASSWORD',
      '--key-pass env:ANDROID_KEYSTORE_PASSWORD',
      '--out dist/ks-house-gatekeeper.apk',
      '"$JAVA_BIN" -jar "$APKSIGNER_JAR" verify --verbose',
  ):
    if fragment not in sign_run:
      raise GateError(f"{path}: isolated personal Android signing is incomplete")
  if any(fragment in sign_run for fragment in (
      "flutter", "gradle", "key.properties", "ota_contract_gate.py", "python ",
  )):
    raise GateError(f"{path}: private Android signing step executes candidate code")

  identity_run = str(identity.get("run", ""))
  for fragment in (
      'test -x "$JAVA_BIN"',
      'test -f "$APKSIGNER_JAR"',
      'test -x "$APKANALYZER"',
      '"$JAVA_BIN" -jar "$APKSIGNER_JAR" verify',
      '--print-certs dist/ks-house-gatekeeper.apk',
      'test "$CERTIFICATE_SHA256" = "8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0"',
      'test "$PACKAGE_NAME" = "com.kshouse.gatekeeper_app"',
      'VERSION_CODE="$("$APKANALYZER" manifest version-code dist/ks-house-gatekeeper.apk)"',
      'VERSION_NAME="$("$APKANALYZER" manifest version-name dist/ks-house-gatekeeper.apk)"',
      'test "$VERSION_CODE" = "$MOBILE_BUILD_NUMBER"',
      'test "$VERSION_NAME" = "$FULL_VERSION"',
      'SOURCE_ENTRY="assets/flutter_assets/assets/source_commit.txt"',
      'test "$SOURCE_ENTRY_COUNT" -eq 1',
      'test "$SOURCE_COMMIT" = "$GITHUB_SHA"',
  ):
    if fragment not in identity_run:
      raise GateError(f"{path}: personal Android signer/package verification is incomplete")

  if manifest.get("env") != PERSONAL_MOBILE_MANIFEST_ENV:
    raise GateError(f"{path}: personal mobile manifest signing provenance is not exact")
  manifest_run = str(manifest.get("run", ""))
  for fragment in (
      'for name in APK_DOWNLOAD_URL APK_FALLBACK_DOWNLOAD_URL',
      'test "$MOBILE_UPDATE_KEY_ID" = "personal-legacy-target-20260812-1"',
      '[[ "$MOBILE_UPDATE_PRIVATE_KEY_HEX" =~ ^[0-9a-f]{64}$ ]]',
      '[[ "$MOBILE_UPDATE_PUBLIC_KEY_HEX" =~ ^[0-9a-f]{64}$ ]]',
      'test "$MOBILE_PUBLIC_KEY_SHA256" = "87d8b43a994f1021feca0d7079658f02bee2eb2f5711e67b12d450f841af08c5"',
      'parsed.scheme != "https"',
      "personal mobile primary and fallback APK URLs must be distinct",
      'PUBLISHED_AT="$(git show -s --format=%cI "$GITHUB_SHA")"',
      "python -I scripts/ota_contract_gate.py mobile-manifest-create",
      "python -I scripts/ota_contract_gate.py mobile-manifest-verify",
      "--artifact dist/ks-house-gatekeeper.apk",
      "--output dist/version.json",
      '--version "$FULL_VERSION"',
      '--build-number "$MOBILE_BUILD_NUMBER"',
      '--commit "$GITHUB_SHA"',
      "--private-key-env MOBILE_UPDATE_PRIVATE_KEY_HEX",
      '--expected-package-name "com.kshouse.gatekeeper_app"',
      '--apkanalyzer "$APKANALYZER"',
      '--apksigner "$APKSIGNER_JAR"',
  ):
    if fragment not in manifest_run:
      raise GateError(f"{path}: exact personal signed mobile manifest is incomplete")
  if manifest_run.count("mobile-manifest-create") != 1 or manifest_run.count(
      "mobile-manifest-verify"
  ) != 1:
    raise GateError(f"{path}: personal mobile manifest create/verify count is not exact")
  if manifest_run.count('--apkanalyzer "$APKANALYZER"') != 2 or manifest_run.count(
      '--apksigner "$APKSIGNER_JAR"'
  ) != 2:
    raise GateError(f"{path}: personal mobile manifest tool binding count is not exact")

  if artifact_upload.get("uses") != UPLOAD_ARTIFACT_ACTION or artifact_upload.get(
      "with"
  ) != {
      "name": (
          "personal-mobile-ota-${{ github.sha }}-attempt-"
          "${{ github.run_attempt }}"
      ),
      "path": "dist/ks-house-gatekeeper.apk\ndist/version.json\n",
      "if-no-files-found": "error",
      "retention-days": 14,
  }:
    raise GateError(f"{path}: exact personal mobile artifact retention is not exact")

  if host_identity.get("env") != {
      "NAS_HOST": "${{ secrets.NAS_HOST }}",
      "NAS_PORT": "${{ secrets.NAS_PORT || 22 }}",
      "NAS_KNOWN_HOSTS": "${{ secrets.NAS_KNOWN_HOSTS }}",
  }:
    raise GateError(f"{path}: personal mobile NAS host input provenance is not exact")
  host_run = str(host_identity.get("run", ""))
  for fragment in (
      'test -n "$NAS_KNOWN_HOSTS"',
      'printf \'%s\\n\' "$NAS_KNOWN_HOSTS" > "$KNOWN_HOSTS_FILE"',
      "repository-secret-pinned",
      'ssh-keygen -l -E sha256 -f "$KNOWN_HOSTS_FILE" >/dev/null',
      'echo "OTA_NAS_KNOWN_HOSTS_FILE=${KNOWN_HOSTS_FILE}" >> "$GITHUB_ENV"',
      'echo "OTA_NAS_HOST_KEY_MODE=${HOST_KEY_MODE}" >> "$GITHUB_ENV"',
  ):
    if fragment not in host_run:
      raise GateError(f"{path}: strict personal mobile NAS host identity is incomplete")
  if any(fragment in host_run for fragment in (
      "StrictHostKeyChecking=no", "set +e", "ssh-keyscan",
      "runtime-keyscan-unpinned",
  )):
    raise GateError(f"{path}: personal mobile NAS host identity is fail-open")

  if publish.get("env") != PERSONAL_MOBILE_PUBLISH_ENV:
    raise GateError(f"{path}: personal mobile NAS publish provenance is not exact")
  publish_run = str(publish.get("run", ""))
  for fragment in (
      'for name in MOBILE_PUBLIC_KEY_HEX NAS_HOST NAS_USER NAS_PASSWORD',
      '[[ "$MOBILE_PUBLIC_KEY_HEX" =~ ^[0-9a-f]{64}$ ]]',
      'test "$MOBILE_PUBLIC_KEY_SHA256" = "87d8b43a994f1021feca0d7079658f02bee2eb2f5711e67b12d450f841af08c5"',
      '[[ "$NAS_USER" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$ ]]',
      "python -I scripts/ota_contract_gate.py mobile-sftp-publish",
      "--artifact dist/ks-house-gatekeeper.apk",
      "--manifest dist/version.json",
      '--expected-version "$FULL_VERSION"',
      '--expected-commit "$GITHUB_SHA"',
      '--expected-build-number "$MOBILE_BUILD_NUMBER"',
      '--expected-package-name "com.kshouse.gatekeeper_app"',
      '--run-attempt "$GITHUB_RUN_ATTEMPT"',
      "--evidence-output evidence/personal-mobile-ota-publication.json",
      '--apkanalyzer "$APKANALYZER"',
      '--apksigner "$APKSIGNER_JAR"',
  ):
    if fragment not in publish_run:
      raise GateError(f"{path}: staged/readback/atomic mobile NAS publish is incomplete")
  if any(fragment in publish_run for fragment in (
      "sshpass", "StrictHostKeyChecking=no", "set +e", "ota_contract_gate.py release",
      "production_authorized: true",
  )):
    raise GateError(f"{path}: personal mobile OTA publication adds a release bypass")

  if evidence_upload.get("uses") != UPLOAD_ARTIFACT_ACTION or evidence_upload.get(
      "with"
  ) != {
      "name": (
          "personal-mobile-ota-evidence-${{ github.sha }}-attempt-"
          "${{ github.run_attempt }}"
      ),
      "path": "evidence/personal-mobile-ota-publication.json",
      "if-no-files-found": "error",
      "retention-days": 30,
  }:
    raise GateError(f"{path}: sanitized personal mobile evidence upload is not exact")

  if https_readback.get("env") != PERSONAL_MOBILE_HTTPS_ENV:
    raise GateError(f"{path}: personal mobile HTTPS readback provenance is not exact")
  https_run = str(https_readback.get("run", ""))
  for fragment in (
      "for name in APK_VERSION_URL APK_FALLBACK_VERSION_URL",
      '[[ "${!name}" == https://* ]]',
      'test "$APK_VERSION_URL" != "$APK_FALLBACK_VERSION_URL"',
      'test "$APK_DOWNLOAD_URL" != "$APK_FALLBACK_DOWNLOAD_URL"',
      'fetch_exact "$APK_VERSION_URL" http-readback/primary-version.json dist/version.json',
      'fetch_exact "$APK_FALLBACK_VERSION_URL" http-readback/fallback-version.json dist/version.json',
      'fetch_exact "$APK_DOWNLOAD_URL" http-readback/primary.apk dist/ks-house-gatekeeper.apk',
      'fetch_exact "$APK_FALLBACK_DOWNLOAD_URL" http-readback/fallback.apk dist/ks-house-gatekeeper.apk',
      'cmp "$expected" "$destination"',
      "curl --fail --silent --show-error --location",
      "--proto '=https' --proto-redir '=https'",
  ):
    if fragment not in https_run:
      raise GateError(f"{path}: primary/fallback HTTPS exact-byte readback is incomplete")
  serialized_job = json.dumps(job, sort_keys=True)
  if "ota_contract_gate.py release" in serialized_job or "production_authorized: true" in serialized_job:
    raise GateError(f"{path}: personal mobile OTA cannot self-attest release evidence")
  if "${{ secrets.OTA_SIGNING_" in serialized_job:
    raise GateError(f"{path}: Target OTA environment secrets must not shadow mobile trust")


CANONICAL_RELEASE_STEPS = {
    ".github/workflows/deploy.yml": [
        {
            "name": "Checkout exact main source",
            "uses": CHECKOUT_ACTION,
            "with": {
                "ref": "${{ github.sha }}",
                "persist-credentials": False,
            },
        },
        {
            "name": "Set up Python",
            "uses": SETUP_PYTHON_ACTION,
            "with": {"python-version": TARGET_PYTHON_VERSION},
        },
        {
            "name": "Install PlatformIO and OTA release gate dependencies",
            "run": (
                "python -m pip install --require-hashes -r "
                "ota/requirements.lock"
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
            "uses": SFTP_DEPLOY_ACTION,
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
            "uses": CHECKOUT_ACTION,
            "with": {
                "ref": "${{ github.sha }}",
                "persist-credentials": False,
            },
        },
        {
            "name": "Set up Java JDK 17 for trusted APK inspection",
            "uses": SETUP_JAVA_ACTION,
            "with": {"distribution": "temurin", "java-version": JAVA_VERSION},
        },
        {
            "name": "Set up Python for OTA release gate",
            "uses": SETUP_PYTHON_ACTION,
            "with": {
                "python-version": MOBILE_PYTHON_VERSION,
                "cache": "pip",
                "cache-dependency-path": "ota/requirements.lock",
            },
        },
        {
            "name": "Set up Flutter SDK for exact main release",
            "uses": FLUTTER_ACTION,
            "with": {
                "flutter-version": FLUTTER_VERSION,
                "channel": "stable",
                "cache": True,
            },
        },
        {
            "name": "Install exact main release dependencies",
            "run": (
                "python -m pip install --require-hashes -r ota/requirements.lock\n"
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
            "uses": SFTP_DEPLOY_ACTION,
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

    physical_test_contract_path = "tests/test_nas_physical_test_delivery.py"
    pull_request = triggers.get("pull_request")
    if (
        not isinstance(pull_request, dict)
        or physical_test_contract_path not in pull_request.get("paths", [])
    ):
      raise GateError(
          f"{path}: pull_request paths must include the NAS physical-test contract"
      )
    if path.endswith("build_app.yml"):
      push = triggers.get("push")
      if push != {"branches": ["main"]}:
        raise GateError(
            f"{path}: every main push must run the personal mobile OTA workflow"
        )

    dispatch_inputs = triggers.get("workflow_dispatch", {}).get("inputs", {})
    if set(dispatch_inputs) != {"release_target", "allow_unpinned_host_key"}:
      raise GateError(f"{path}: workflow dispatch inputs must be exact")
    dispatch_input = dispatch_inputs.get("release_target", {})
    if not isinstance(dispatch_input, dict) or dispatch_input.get("type") != "choice":
      raise GateError(f"{path}: explicit production release trigger missing release_target choice input")
    options = dispatch_input.get("options", [])
    if options != [
        "canary", "physical-test-canary", "physical-test-connected", "production"
    ]:
      raise GateError(
          f"{path}: release_target options must exactly separate canary, "
          "physical-test-canary, physical-test-connected and production"
      )
    unpinned_input = dispatch_inputs.get("allow_unpinned_host_key")
    if unpinned_input != {
        "description": (
            "Acknowledge MITM risk when NAS_KNOWN_HOSTS is absent for "
            "physical-test-canary"
        ),
        "required": True,
        "type": "boolean",
        "default": False,
    }:
      raise GateError(f"{path}: unpinned host-key acknowledgement input is not exact")

    # 4. Jobs allowlist
    all_jobs = parsed.get("jobs")
    if not isinstance(all_jobs, dict):
      raise GateError(f"{path}: workflow missing jobs mapping")

    build_job_name = binding["build_job"]
    release_job_name = binding["release_job"]
    allowed_jobs = {
        build_job_name,
        release_job_name,
        "deploy_physical_test_canary",
        "validate_connected_physical_test_prerequisites",
    }
    if path == ".github/workflows/deploy.yml":
      allowed_jobs.update({
          PERSONAL_TARGET_BUILD_JOB,
          PERSONAL_TARGET_PUBLISH_JOB,
      })
    if path == ".github/workflows/build_app.yml":
      allowed_jobs.update({
          PERSONAL_MOBILE_UNSIGNED_JOB,
          PERSONAL_MOBILE_PUBLISH_JOB,
      })
    extra_jobs = set(all_jobs.keys()) - allowed_jobs
    if extra_jobs:
      raise GateError(f"{path}: unexpected job in workflow: {sorted(extra_jobs)}")

    for job_name, workflow_job in all_jobs.items():
      if not isinstance(workflow_job, dict):
        raise GateError(f"{path}: job {job_name} must be a mapping")
      for step in workflow_job.get("steps", []):
        if not isinstance(step, dict):
          continue
        if step.get("uses") == UPLOAD_ARTIFACT_ACTION:
          artifact_name = str(step.get("with", {}).get("name", ""))
          if "${{ github.run_attempt }}" not in artifact_name:
            raise GateError(
                f"{path}: upload-artifact v4 names must include github.run_attempt"
            )

    build_job = all_jobs.get(build_job_name)
    release_job = all_jobs.get(release_job_name)

    # 5. Build Job Allowlist Check
    allowed_build_job_keys = {"name", "runs-on", "steps"}
    extra_build_job_keys = set(build_job.keys()) - allowed_build_job_keys
    if extra_build_job_keys:
      if "environment" in extra_build_job_keys:
        raise GateError(f"{path}: build job must not use production environment or specify environment (string or object)")
      raise GateError(f"{path}: build job contains unallowed keys: {sorted(extra_build_job_keys)}")

    if build_job.get("runs-on") != UBUNTU_RUNNER:
      raise GateError(f"{path}: build job runs-on must be {UBUNTU_RUNNER}")

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
    path_release_condition = expected_authorized_condition
    if path == ".github/workflows/deploy.yml":
      # The legacy commercial Target lane still emits a plaintext schema-v1
      # artifact. It must remain impossible to execute until it is migrated to
      # the encrypted-v2 atomic publisher. The personal exact-main lane below
      # is the only currently authorized Target deployment path.
      path_release_condition = f"false && {expected_authorized_condition}"
    if normalized_release_if != path_release_condition:
      raise GateError(
          f"{path}: production job lacks authorized production trigger: "
          f"release job condition is extended or modified; must be exact production condition (got: '{normalized_release_if}')"
      )

    if release_job.get("runs-on") != UBUNTU_RUNNER:
      raise GateError(f"{path}: release job runs-on must be {UBUNTU_RUNNER}")

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
            '[[ "$GITHUB_RUN_NUMBER" =~ ^[1-9][0-9]*$ ]]',
            '[[ "$GITHUB_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]]',
            "MOBILE_BUILD_NUMBER=$((RUN_NUMBER_DEC * 100 + RUN_ATTEMPT_DEC))",
            "((MOBILE_BUILD_NUMBER <= 2100000000))",
            'echo "MOBILE_BUILD_NUMBER=${MOBILE_BUILD_NUMBER}" >> "$GITHUB_ENV"',
            "flutter build apk --release",
            '--build-number="$MOBILE_BUILD_NUMBER"',
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
            '--build-number "$MOBILE_BUILD_NUMBER"',
            'PUBLISHED_AT="$(git show -s --format=%cI "$GITHUB_SHA")"',
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

    _validate_physical_test_jobs(path, binding, all_jobs)
    _validate_personal_target_ota_job(path, build_job_name, all_jobs)
    _validate_personal_mobile_ota_job(path, build_job_name, all_jobs)


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
      "Install exact Android canary inspection tools",
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
      position["Install exact Android canary inspection tools"]
      < position["Check Dart formatting"]
      < position["Analyze Flutter code"]
      < position["Run Flutter unit tests"]
      < first_build
      and position["Run targeted native GATT unit tests before APK build"] < first_build
      and position["Prepare public mobile canary metadata"] > first_build
  ):
    raise GateError(f"{path}: Flutter/native tests must precede APK build and signing")
  if (
      'find "$ANDROID_SDK/build-tools"' in content
      or 'find "$ANDROID_SDK/cmdline-tools"' in content
  ):
    raise GateError(f"{path}: Android inspection tools must not use mutable discovery")
  if content.count(
      'APKSIGNER="$ANDROID_SDK/build-tools/36.0.0/apksigner"'
  ) != 5 or content.count(
      'APKANALYZER="$ANDROID_SDK/cmdline-tools/12.0/bin/apkanalyzer"'
  ) != 4 or content.count(
      'ZIPALIGN="$ANDROID_SDK/build-tools/36.0.0/zipalign"'
  ) != 0:
    raise GateError(f"{path}: exact Android inspection tool versions are incomplete")

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
  canary_tools = by_name["Install exact Android canary inspection tools"]
  if canary_tools.get("if") is not None or canary_tools.get("env"):
    raise GateError(f"{path}: public canary Android tool setup must be unconditional")
  canary_tools_run = str(canary_tools.get("run", ""))
  for fragment in (
      'SDKMANAGER="$ANDROID_SDK/cmdline-tools/latest/bin/sdkmanager"',
      '"$SDKMANAGER" --install "build-tools;36.0.0" "cmdline-tools;12.0"',
      'test -x "$ANDROID_SDK/build-tools/36.0.0/apksigner"',
      'test -x "$ANDROID_SDK/cmdline-tools/12.0/bin/apkanalyzer"',
  ):
    if fragment not in canary_tools_run:
      raise GateError(f"{path}: exact public canary Android tools are incomplete")
  if "secrets." in canary_tools_run:
    raise GateError(f"{path}: public canary Android tool setup must remain secret-free")
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
      'val unsignedCiRelease = System.getenv("SGK_UNSIGNED_CI_RELEASE") == "1"',
      'it.contains("release", ignoreCase = true)',
      "releaseRequested && !unsignedCiRelease",
      "releaseKey == null || !releaseKey.exists()",
      'keystoreProperties.getProperty("storePassword").isNullOrBlank()',
      'keystoreProperties.getProperty("keyAlias").isNullOrBlank()',
      'keystoreProperties.getProperty("keyPassword").isNullOrBlank()',
      "Release signing is fail-closed",
      "if (!unsignedCiRelease)",
      'signingConfig = signingConfigs.getByName("release")',
  ):
    if fragment not in source:
      raise GateError(f"{path}: release-signing fail-closed seam missing: {fragment}")
  if 'signingConfigs.getByName("debug")' in source:
    raise GateError(f"{path}: debug signing fallback is forbidden for release")
  if source.count("SGK_UNSIGNED_CI_RELEASE") != 1:
    raise GateError(f"{path}: unsigned CI release escape hatch must have one exact declaration")
  if not (
      source.index("plugins {")
      < source.index('val unsignedCiRelease = System.getenv("SGK_UNSIGNED_CI_RELEASE") == "1"')
      < source.index("android {")
  ):
    raise GateError(f"{path}: Kotlin plugins block must precede the unsigned CI declaration")


def validate_mobile_gradle_wrapper_pins(
    contents: dict[str, str] | None = None,
) -> None:
  expected = {
      "gatekeeper_app/android/gradle/wrapper/gradle-wrapper.properties": (
          "https\\://services.gradle.org/distributions/gradle-9.1.0-all.zip",
          "b84e04fa845fecba48551f425957641074fcc00a88a84d2aae5808743b35fc85",
      ),
      (
          "gatekeeper_app/android/app/libs/flutter_beacon_local/android/"
          "gradle/wrapper/gradle-wrapper.properties"
      ): (
          "https\\://services.gradle.org/distributions/gradle-5.4.1-all.zip",
          "14cd15fc8cc8705bd69dcfa3c8fefb27eb7027f5de4b47a8b279218f76895a91",
      ),
  }
  for path, (distribution_url, distribution_sha256) in expected.items():
    source = (
        contents[path]
        if contents is not None
        else (ROOT / path).read_text(encoding="utf-8")
    )
    properties = {}
    for line in source.splitlines():
      if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
      key, value = line.split("=", 1)
      properties[key] = value
    if properties.get("distributionUrl") != distribution_url:
      raise GateError(f"{path}: Gradle distribution URL is not the reviewed exact pin")
    if properties.get("distributionSha256Sum") != distribution_sha256:
      raise GateError(f"{path}: Gradle distribution SHA-256 is missing or changed")


def validate_target_build_inputs(content: bytes | None = None) -> None:
  """Bind automatic production firmware to reviewed, immutable build inputs."""
  path = "platformio.ini"
  value = content if content is not None else (ROOT / path).read_bytes()
  try:
    value.decode("utf-8")
  except UnicodeDecodeError as exc:
    raise GateError(f"{path}: target build input must be strict UTF-8") from exc
  normalized = value.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
  actual = hashlib.sha256(normalized).hexdigest()
  expected = PINNED_TARGET_BUILD_INPUTS[path]
  if actual != expected:
    raise GateError(
        f"{path}: production Target build inputs differ from the reviewed exact pin"
    )


def validate_ota_python_dependency_inputs(
    contents: dict[str, bytes] | None = None,
) -> None:
  for path, expected in PINNED_OTA_PYTHON_INPUTS.items():
    value = contents[path] if contents is not None else (ROOT / path).read_bytes()
    try:
      value.decode("utf-8")
    except UnicodeDecodeError as exc:
      raise GateError(f"{path}: dependency input must be strict UTF-8") from exc
    normalized = value.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if hashlib.sha256(normalized).hexdigest() != expected:
      raise GateError(f"{path}: dependency input differs from the reviewed hash lock")






def validate_contract() -> None:
  validate_partitions()
  state_machines = validate_state_machines()
  validate_recovery_and_faults(state_machines=state_machines)
  validate_vectors()
  validate_workflow_artifact_bindings()
  validate_firmware_build_workflow()
  validate_mobile_build_workflow()
  validate_mobile_release_signing_config()
  validate_mobile_gradle_wrapper_pins()
  validate_target_build_inputs()
  validate_ota_python_dependency_inputs()
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


def _apksigner_command(apksigner_path: Path | None) -> list[str]:
  executable = _resolve_apksigner(apksigner_path)
  if executable.suffix.lower() != ".jar":
    return [str(executable)]
  java_value = os.environ.get("SGK_APKSIGNER_JAVA", "")
  java_path = Path(java_value)
  if not java_value or not java_path.is_absolute() or not java_path.is_file():
    raise GateError(
        "direct apksigner.jar validation requires absolute SGK_APKSIGNER_JAVA"
    )
  return [str(java_path), "-jar", str(executable)]


def read_apk_signing_certificate_digests(
    artifact_path: Path, apksigner_path: Path | None = None
) -> set[str]:
  result = subprocess.run(
      _apksigner_command(apksigner_path)
      + ["verify", "--print-certs", str(artifact_path)],
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


def _validated_target_artifact_url(value: str, commit: str) -> str:
  expected_names = {
      f"gatekeeper-firmware-{commit}.bin",
      f"gatekeeper-firmware-{commit}.sgkenc",
  }
  parsed = urlparse(value)
  if parsed.username is not None or parsed.password is not None:
    raise GateError("signed Target artifact URL must not contain credentials")
  if (
      parsed.scheme != "https"
      or not parsed.hostname
      or parsed.query
      or parsed.fragment
      or Path(parsed.path).name not in expected_names
      or "//" in parsed.path
  ):
    raise GateError("signed Target artifact URL is not bound to the immutable SHA filename")
  return value


TARGET_HANDOFF_MAGIC = b"SGKTHO1\x00"
TARGET_HANDOFF_INFO = b"smart-gatekeeper-target-handoff-v1"
TARGET_HANDOFF_MAX_PLAINTEXT = 0x700000
TARGET_CONTENT_MAGIC = b"SGKOTA2\x00"
TARGET_CONTENT_AAD_PREFIX = b"smart-gatekeeper-target-content-v1\n"
TARGET_CONTENT_NONCE_INFO = b"smart-gatekeeper-target-content-nonce-v1"
TARGET_CONTENT_NONCE_SIZE = 12
TARGET_CONTENT_TAG_SIZE = 16


def _target_handoff_aad(commit: str, run_attempt: str) -> bytes:
  if not re.fullmatch(r"[0-9a-f]{40}", commit):
    raise GateError("Target handoff commit must be exact lowercase 40-hex")
  if not re.fullmatch(r"[1-9][0-9]*", run_attempt):
    raise GateError("Target handoff run attempt must be a positive integer")
  return f"{commit}\n{run_attempt}\n".encode("ascii")


def _target_handoff_key(shared_secret: bytes, aad: bytes) -> bytes:
  return HKDF(
      algorithm=hashes.SHA256(),
      length=32,
      salt=hashlib.sha256(aad).digest(),
      info=TARGET_HANDOFF_INFO,
  ).derive(shared_secret)


def encrypt_target_handoff(args: argparse.Namespace) -> None:
  aad = _target_handoff_aad(args.commit, args.run_attempt)
  if not re.fullmatch(r"[0-9a-f]{64}", args.recipient_public_key_hex):
    raise GateError("Target handoff recipient public key must be lowercase 32-byte hex")
  plaintext = args.artifact.read_bytes()
  if not 1 <= len(plaintext) <= TARGET_HANDOFF_MAX_PLAINTEXT:
    raise GateError("Target handoff plaintext size is outside the N16 OTA slot")
  recipient = X25519PublicKey.from_public_bytes(
      bytes.fromhex(args.recipient_public_key_hex)
  )
  ephemeral = X25519PrivateKey.generate()
  ephemeral_public = ephemeral.public_key().public_bytes(
      encoding=serialization.Encoding.Raw,
      format=serialization.PublicFormat.Raw,
  )
  nonce = os.urandom(12)
  key = _target_handoff_key(ephemeral.exchange(recipient), aad)
  ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_bytes(TARGET_HANDOFF_MAGIC + ephemeral_public + nonce + ciphertext)
  print(f"[TARGET-HANDOFF] encrypted sensitive firmware: {args.output}")


def decrypt_target_handoff(args: argparse.Namespace) -> None:
  aad = _target_handoff_aad(args.commit, args.run_attempt)
  private_hex = os.environ.get(args.private_key_env, "")
  if not re.fullmatch(r"[0-9a-f]{64}", private_hex):
    raise GateError(f"{args.private_key_env} must be lowercase 32-byte hex")
  private_key = X25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
  actual_public_hex = private_key.public_key().public_bytes(
      encoding=serialization.Encoding.Raw,
      format=serialization.PublicFormat.Raw,
  ).hex()
  if actual_public_hex != args.recipient_public_key_hex:
    raise GateError("Target handoff private key does not match pinned recipient public key")
  payload = args.input.read_bytes()
  minimum_size = len(TARGET_HANDOFF_MAGIC) + 32 + 12 + 16 + 1
  maximum_size = len(TARGET_HANDOFF_MAGIC) + 32 + 12 + 16 + TARGET_HANDOFF_MAX_PLAINTEXT
  if not minimum_size <= len(payload) <= maximum_size:
    raise GateError("Target handoff ciphertext size is invalid")
  if not payload.startswith(TARGET_HANDOFF_MAGIC):
    raise GateError("Target handoff envelope magic is invalid")
  offset = len(TARGET_HANDOFF_MAGIC)
  ephemeral_public = X25519PublicKey.from_public_bytes(payload[offset:offset + 32])
  nonce = payload[offset + 32:offset + 44]
  ciphertext = payload[offset + 44:]
  key = _target_handoff_key(private_key.exchange(ephemeral_public), aad)
  try:
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
  except InvalidTag as exc:
    raise GateError("Target handoff authentication failed") from exc
  if not 1 <= len(plaintext) <= TARGET_HANDOFF_MAX_PLAINTEXT:
    raise GateError("Target handoff decrypted size is outside the N16 OTA slot")
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_bytes(plaintext)
  print(f"[TARGET-HANDOFF] authenticated firmware recovered: {args.output}")


def _target_content_key_from_env(variable: str) -> bytes:
  value = os.environ.get(variable, "")
  if not re.fullmatch(r"[0-9a-f]{64}", value):
    raise GateError(f"{variable} must contain exact lowercase 32-byte hex")
  return bytes.fromhex(value)


def _target_content_aad(commit: str, key_id: str) -> bytes:
  if not re.fullmatch(r"[0-9a-f]{40}", commit):
    raise GateError("Target content commit must be exact lowercase 40-hex")
  if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", key_id):
    raise GateError("Target content key ID is invalid")
  return (
      TARGET_CONTENT_AAD_PREFIX + commit.encode("ascii") + b"\n"
      + key_id.encode("ascii") + b"\n"
  )


def _target_content_nonce(key: bytes, aad: bytes, plaintext: bytes) -> bytes:
  # The immutable NAS object is keyed by source commit. A random nonce would
  # make an otherwise identical workflow rerun produce different bytes and
  # collide with that immutable path. Derive a separate nonce key, then bind
  # the nonce to both release identity and plaintext identity. Identical input
  # intentionally reproduces identical ciphertext; any plaintext/commit/key-id
  # change gets an independently derived 96-bit nonce.
  nonce_key = HKDF(
      algorithm=hashes.SHA256(),
      length=32,
      salt=hashlib.sha256(aad).digest(),
      info=TARGET_CONTENT_NONCE_INFO,
  ).derive(key)
  plaintext_sha256 = hashlib.sha256(plaintext).digest()
  return hmac.new(nonce_key, aad + plaintext_sha256, hashlib.sha256).digest()[
      :TARGET_CONTENT_NONCE_SIZE
  ]


def encrypt_target_content(args: argparse.Namespace) -> None:
  plaintext = args.artifact.read_bytes()
  if not 1 <= len(plaintext) <= TARGET_HANDOFF_MAX_PLAINTEXT:
    raise GateError("Target content plaintext size is outside the N16 OTA slot")
  key = _target_content_key_from_env(args.key_env)
  aad = _target_content_aad(args.commit, args.key_id)
  nonce = _target_content_nonce(key, aad, plaintext)
  ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_bytes(TARGET_CONTENT_MAGIC + nonce + ciphertext)
  print(f"[TARGET-CONTENT] encrypted NAS firmware artifact: {args.output}")


def decrypt_target_content(args: argparse.Namespace) -> None:
  payload = args.input.read_bytes()
  minimum_size = (
      len(TARGET_CONTENT_MAGIC) + TARGET_CONTENT_NONCE_SIZE
      + TARGET_CONTENT_TAG_SIZE + 1
  )
  maximum_size = minimum_size - 1 + TARGET_HANDOFF_MAX_PLAINTEXT
  if not minimum_size <= len(payload) <= maximum_size:
    raise GateError("Target content envelope size is invalid")
  if not payload.startswith(TARGET_CONTENT_MAGIC):
    raise GateError("Target content envelope magic is invalid")
  offset = len(TARGET_CONTENT_MAGIC)
  nonce = payload[offset:offset + TARGET_CONTENT_NONCE_SIZE]
  ciphertext = payload[offset + TARGET_CONTENT_NONCE_SIZE:]
  key = _target_content_key_from_env(args.key_env)
  aad = _target_content_aad(args.commit, args.key_id)
  try:
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
  except InvalidTag as exc:
    raise GateError("Target content authentication failed") from exc
  if not 1 <= len(plaintext) <= TARGET_HANDOFF_MAX_PLAINTEXT:
    raise GateError("Target content decrypted size is outside the N16 OTA slot")
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_bytes(plaintext)
  print(f"[TARGET-CONTENT] authenticated firmware recovered: {args.output}")


def create_target_manifest(args: argparse.Namespace) -> None:
  if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
    raise GateError("commit must be the exact lowercase 40-hex source identity")
  _validated_target_artifact_url(args.artifact_url, args.commit)
  private_key = _mobile_private_key_from_env(args.private_key_env)
  public_hex = _mobile_public_hex(private_key)
  if public_hex != args.expected_public_key_hex:
    raise GateError("signing private key does not match the pinned Target OTA public key")
  size, sha256 = _artifact_size_and_sha256(args.artifact)
  if size < 1:
    raise GateError("Target firmware artifact must not be empty")
  plaintext_artifact = getattr(args, "plaintext_artifact", None)
  encryption_key_id = getattr(args, "encryption_key_id", None)
  encrypted = plaintext_artifact is not None or encryption_key_id is not None
  if encrypted and (plaintext_artifact is None or encryption_key_id is None):
    raise GateError(
        "encrypted Target manifest requires plaintext artifact and encryption key ID"
    )
  if encrypted:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", encryption_key_id):
      raise GateError("Target encryption key ID is invalid")
    plaintext_size, plaintext_sha256 = _artifact_size_and_sha256(
        plaintext_artifact
    )
    envelope_overhead = (
        len(TARGET_CONTENT_MAGIC) + TARGET_CONTENT_NONCE_SIZE
        + TARGET_CONTENT_TAG_SIZE
    )
    if not 1 <= plaintext_size <= TARGET_HANDOFF_MAX_PLAINTEXT:
      raise GateError("Target plaintext size is outside the N16 OTA slot")
    if size != plaintext_size + envelope_overhead:
      raise GateError("Target encrypted envelope length is not exact")
    if not args.artifact.read_bytes().startswith(TARGET_CONTENT_MAGIC):
      raise GateError("Target encrypted artifact magic is invalid")
    if Path(urlparse(args.artifact_url).path).suffix != ".sgkenc":
      raise GateError("encrypted Target artifact URL must end in .sgkenc")
  else:
    plaintext_size = 0
    plaintext_sha256 = ""
  publication = _mobile_timestamp(args.published_at, "published_at")
  if args.mandatory_after is not None and _mobile_timestamp(
      args.mandatory_after, "mandatory_after"
  ) < publication:
    raise GateError("mandatory_after cannot precede published_at")
  manifest: dict[str, object] = {
      "schema_version": 2 if encrypted else 1,
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
  if encrypted:
    manifest.update({
        "encryption_algorithm": "AES-256-GCM",
        "encryption_key_id": encryption_key_id,
        "plaintext_size": plaintext_size,
        "plaintext_sha256": plaintext_sha256,
    })
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
  expected_encryption_key_id = getattr(
      args, "expected_encryption_key_id", None
  )
  if expected_encryption_key_id is not None and (
      manifest.get("schema_version") != 2
      or manifest.get("encryption_algorithm") != "AES-256-GCM"
      or manifest.get("encryption_key_id") != expected_encryption_key_id
  ):
    raise GateError("Target manifest encryption identity does not match")
  _validated_target_artifact_url(
      str(manifest["artifact_url"]), args.expected_commit
  )
  actual_size, actual_sha256 = _artifact_size_and_sha256(args.artifact)
  if (
      manifest["artifact_size"] != actual_size
      or manifest["sha256"] != actual_sha256
  ):
    raise GateError("Target manifest is not bound to the exact firmware bytes")
  print(f"[TARGET-MANIFEST] artifact binding verified: {args.manifest}")


AUTO_TARGET_VERSION = re.compile(
    r"^2\.1\.([1-9][0-9]*)\+main\.g([0-9a-f]{7,40})$"
)
AUTO_TARGET_BUILD_ID = re.compile(r"^main-([1-9][0-9]*)-([0-9a-f]{40})$")
REMOTE_TARGET_ROOT = re.compile(r"^/docker/[A-Za-z0-9._/-]+$")


def _validated_target_remote_root(value: str) -> str:
  root = value.rstrip("/")
  if (
      not REMOTE_TARGET_ROOT.fullmatch(root)
      or "//" in root
      or any(segment in ("", ".", "..") for segment in root.split("/")[1:])
  ):
    raise GateError("NAS_TARGET_DIR must be a canonical /docker path")
  return root


def _read_sftp_bytes(sftp: Any, path: str) -> bytes:
  with sftp.open(path, "rb") as stream:
    value = stream.read()
  if not isinstance(value, bytes):
    raise GateError("SFTP readback did not return bytes")
  return value


def _read_optional_sftp_bytes(sftp: Any, path: str) -> bytes | None:
  try:
    return _read_sftp_bytes(sftp, path)
  except OSError as exc:
    if getattr(exc, "errno", None) == 2 or "no such file" in str(exc).lower():
      return None
    raise


def _write_sftp_bytes(sftp: Any, path: str, value: bytes) -> None:
  with sftp.open(path, "wb") as stream:
    written = stream.write(value)
    if written is not None and written != len(value):
      raise GateError("SFTP staged write was incomplete")
    stream.flush()


def _manifest_from_bytes(value: bytes) -> dict[str, Any]:
  try:
    parsed = json.loads(value.decode("utf-8"))
  except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise GateError("NAS current Target manifest is not valid UTF-8 JSON") from exc
  if not isinstance(parsed, dict):
    raise GateError("NAS current Target manifest must be an object")
  return parsed


def _target_pointer_decision(
    existing_bytes: bytes | None,
    candidate: dict[str, Any],
    public_key_hex: str,
) -> tuple[str, dict[str, Any] | None]:
  if existing_bytes is None:
    return "publish-new", None
  try:
    existing = _manifest_from_bytes(existing_bytes)
    validate_manifest(existing, "target-manifest.schema.json", public_key_hex)
  except GateError as exc:
    raise GateError(
        "NAS current Target manifest is present but unverifiable; "
        "automatic replacement is refused"
    ) from exc

  if (
      existing["commit"] == candidate["commit"]
      and existing["version"] == candidate["version"]
      and existing["sha256"] == candidate["sha256"]
      and existing["artifact_url"] == candidate["artifact_url"]
  ):
    return "idempotent", existing

  candidate_match = AUTO_TARGET_VERSION.fullmatch(str(candidate["version"]))
  if candidate_match is None:
    raise GateError("automatic Target OTA version is not the monotonic main format")
  candidate_sequence = int(candidate_match.group(1))
  candidate_core = (2, 1, candidate_sequence)
  existing_version = str(existing["version"])
  existing_core_match = re.match(r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:[-+]|$)", existing_version)
  if existing_core_match is None:
    raise GateError("NAS current signed Target version cannot be ordered safely")
  existing_core = tuple(int(value) for value in existing_core_match.groups())
  if existing_core > candidate_core:
    raise GateError("stale Target OTA publish refused: NAS version core is newer")
  if existing_core < candidate_core:
    return "publish-upgrade", existing
  existing_match = AUTO_TARGET_VERSION.fullmatch(existing_version)
  if existing_match is None:
    raise GateError("stale Target OTA publish refused: equal-core NAS version is not ordered")
  existing_sequence = int(existing_match.group(1))
  if existing_sequence >= candidate_sequence:
    raise GateError("stale or conflicting Target OTA publish refused")
  return "publish-upgrade", existing


def _place_immutable_sftp_bytes(
    sftp: Any,
    staged_path: str,
    final_path: str,
    expected: bytes,
) -> None:
  current = _read_optional_sftp_bytes(sftp, final_path)
  if current is None:
    sftp.rename(staged_path, final_path)
  elif current == expected:
    sftp.remove(staged_path)
  else:
    raise GateError("immutable NAS OTA history path already contains different bytes")
  if _read_sftp_bytes(sftp, final_path) != expected:
    raise GateError("immutable NAS OTA readback differs after publish")


def _publish_target_sftp_bytes(
    sftp: Any,
    remote_root: str,
    artifact_path: Path,
    manifest_path: Path,
    candidate: dict[str, Any],
    public_key_hex: str,
    run_attempt: str,
) -> dict[str, Any]:
  commit = str(candidate["commit"])
  if not re.fullmatch(r"[0-9a-f]{40}", commit):
    raise GateError("automatic Target OTA commit identity is invalid")
  version_match = AUTO_TARGET_VERSION.fullmatch(str(candidate["version"]))
  build_id = str(candidate["build_id"])
  build_match = AUTO_TARGET_BUILD_ID.fullmatch(build_id)
  if (
      version_match is None
      or build_match is None
      or build_match.group(1) != version_match.group(1)
      or build_match.group(2) != commit
  ):
    raise GateError("automatic Target OTA deterministic build identity is invalid")
  if not re.fullmatch(r"[1-9][0-9]*", run_attempt):
    raise GateError("automatic Target OTA run attempt is invalid")
  validated_artifact_url = _validated_target_artifact_url(
      str(candidate["artifact_url"]), commit
  )
  immutable_artifact_name = Path(urlparse(validated_artifact_url).path).name
  immutable_manifest_name = f"version-{commit}.json"

  artifact_bytes = artifact_path.read_bytes()
  manifest_bytes = manifest_path.read_bytes()
  if not artifact_bytes or not manifest_bytes:
    raise GateError("automatic Target OTA local artifact or manifest is empty")
  remote_stat = sftp.stat(remote_root)
  if not stat.S_ISDIR(remote_stat.st_mode):
    raise GateError("NAS_TARGET_DIR does not identify an existing directory")

  pointer_path = f"{remote_root}/version.json"
  initial_pointer = _read_optional_sftp_bytes(sftp, pointer_path)
  initial_decision, initial_valid_manifest = _target_pointer_decision(
      initial_pointer, candidate, public_key_hex
  )
  if initial_decision == "idempotent" and initial_pointer != manifest_bytes:
    raise GateError("equal Target OTA identity has conflicting signed manifest bytes")
  previous_valid_artifact = False
  if initial_valid_manifest is not None:
    previous_name = Path(
        urlparse(str(initial_valid_manifest["artifact_url"])).path
    ).name
    previous_bytes = _read_optional_sftp_bytes(
        sftp, f"{remote_root}/{previous_name}"
    )
    previous_valid_artifact = bool(
        previous_bytes is not None
        and len(previous_bytes) == int(initial_valid_manifest["artifact_size"])
        and hashlib.sha256(previous_bytes).hexdigest()
        == str(initial_valid_manifest["sha256"])
    )
  stage = (
      f"{remote_root}/.staging-{commit}-"
      f"{build_id}-{run_attempt}"
  )
  sftp.mkdir(stage)
  staged_artifact = f"{stage}/{immutable_artifact_name}"
  staged_manifest = f"{stage}/{immutable_manifest_name}"
  staged_pointer = f"{stage}/version.json"
  sftp.put(str(artifact_path), staged_artifact, confirm=True)
  sftp.put(str(manifest_path), staged_manifest, confirm=True)
  sftp.put(str(manifest_path), staged_pointer, confirm=True)
  if _read_sftp_bytes(sftp, staged_artifact) != artifact_bytes:
    raise GateError("NAS staged Target artifact readback differs")
  if (
      _read_sftp_bytes(sftp, staged_manifest) != manifest_bytes
      or _read_sftp_bytes(sftp, staged_pointer) != manifest_bytes
  ):
    raise GateError("NAS staged Target manifest readback differs")

  final_artifact = f"{remote_root}/{immutable_artifact_name}"
  _place_immutable_sftp_bytes(
      sftp, staged_artifact, final_artifact, artifact_bytes
  )

  if initial_decision == "idempotent":
    sftp.remove(staged_manifest)
    sftp.remove(staged_pointer)
    sftp.rmdir(stage)
    return {
        "result": "idempotent",
        "previous_valid_manifest": True,
        "previous_valid_artifact": True,
        "immutable_artifact": immutable_artifact_name,
        "immutable_manifest": immutable_manifest_name,
    }

  final_manifest = f"{remote_root}/{immutable_manifest_name}"
  _place_immutable_sftp_bytes(
      sftp, staged_manifest, final_manifest, manifest_bytes
  )

  if initial_valid_manifest is not None and initial_pointer is not None:
    previous_commit = str(initial_valid_manifest["commit"])
    previous_history = f"{remote_root}/version-{previous_commit}.json"
    previous_staged = f"{stage}/previous-{previous_commit}.json"
    _write_sftp_bytes(sftp, previous_staged, initial_pointer)
    if _read_sftp_bytes(sftp, previous_staged) != initial_pointer:
      raise GateError("previous valid Target manifest staging readback differs")
    _place_immutable_sftp_bytes(
        sftp, previous_staged, previous_history, initial_pointer
    )

  # Re-read immediately before the pointer swap. A changed/newer pointer is a
  # stale-run conflict and must not be overwritten by this run.
  current_pointer = _read_optional_sftp_bytes(sftp, pointer_path)
  if current_pointer != initial_pointer:
    current_decision, _ = _target_pointer_decision(
        current_pointer, candidate, public_key_hex
    )
    if current_decision == "idempotent":
      if current_pointer != manifest_bytes:
        raise GateError(
            "equal Target OTA race identity has conflicting signed manifest bytes"
        )
      sftp.remove(staged_pointer)
      sftp.rmdir(stage)
      return {
          "result": "idempotent-race-winner",
          "previous_valid_manifest": True,
          "previous_valid_artifact": True,
          "immutable_artifact": immutable_artifact_name,
          "immutable_manifest": immutable_manifest_name,
      }
    raise GateError("NAS Target pointer changed during staged publication")

  # OpenSSH posix-rename is the commit point: replacing version.json is one
  # atomic filesystem operation. Unsupported servers fail while the old pointer
  # and every previously valid immutable artifact remain untouched.
  sftp.posix_rename(staged_pointer, pointer_path)
  if _read_sftp_bytes(sftp, pointer_path) != manifest_bytes:
    raise GateError("atomic NAS Target manifest pointer readback differs")
  sftp.rmdir(stage)
  return {
      "result": initial_decision,
      "previous_valid_manifest": initial_valid_manifest is not None,
      "previous_valid_artifact": previous_valid_artifact,
      "immutable_artifact": immutable_artifact_name,
      "immutable_manifest": immutable_manifest_name,
  }


def publish_target_sftp(args: argparse.Namespace) -> None:
  public_key_hex = os.environ.get("TARGET_PUBLIC_KEY_HEX", "")
  if not re.fullmatch(r"[0-9a-f]{64}", public_key_hex):
    raise GateError("TARGET_PUBLIC_KEY_HEX must be exact lowercase 32-byte hex")
  verify_target_manifest(argparse.Namespace(
      manifest=args.manifest,
      artifact=args.artifact,
      public_key_hex=public_key_hex,
      expected_version=args.expected_version,
      expected_commit=args.expected_commit,
      expected_build_id=args.expected_build_id,
  ))
  candidate = load_json(args.manifest)
  _validated_target_artifact_url(
      str(candidate.get("artifact_url", "")), args.expected_commit
  )
  if AUTO_TARGET_VERSION.fullmatch(args.expected_version) is None:
    raise GateError("automatic Target OTA version is not monotonic main format")
  host = os.environ.get("NAS_HOST", "")
  user = os.environ.get("NAS_USER", "")
  password = os.environ.get("NAS_PASSWORD", "")
  port_text = os.environ.get("NAS_PORT", "")
  known_hosts_path = Path(os.environ.get("OTA_NAS_KNOWN_HOSTS_FILE", ""))
  host_key_mode = os.environ.get("OTA_NAS_HOST_KEY_MODE", "")
  if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
    raise GateError("NAS_HOST format is invalid")
  if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}", user):
    raise GateError("NAS_USER format is invalid")
  if not password:
    raise GateError("NAS_PASSWORD is empty")
  if not re.fullmatch(r"[0-9]{1,5}", port_text) or not 1 <= int(port_text) <= 65535:
    raise GateError("NAS_PORT format or range is invalid")
  if not known_hosts_path.is_file() or known_hosts_path.stat().st_size < 1:
    raise GateError("strict NAS known-hosts file is missing")
  if host_key_mode != "repository-secret-pinned":
    raise GateError("automatic Target OTA requires repository-pinned NAS host keys")
  remote_root = _validated_target_remote_root(
      os.environ.get("NAS_TARGET_DIR", "")
  )

  try:
    import paramiko
  except ImportError as exc:
    raise GateError("Paramiko is required for atomic Target OTA publication") from exc
  client = paramiko.SSHClient()
  try:
    client.load_host_keys(str(known_hosts_path))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        hostname=host,
        port=int(port_text),
        username=user,
        password=password,
        allow_agent=False,
        look_for_keys=False,
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    with client.open_sftp() as sftp:
      result = _publish_target_sftp_bytes(
          sftp,
          remote_root,
          args.artifact,
          args.manifest,
          candidate,
          public_key_hex,
          args.run_attempt,
      )
  except GateError:
    raise
  except Exception as exc:
    raise GateError(
        "Target OTA SFTP publication failed before atomic readback confirmation"
    ) from exc
  finally:
    client.close()

  artifact_size, artifact_sha256 = _artifact_size_and_sha256(args.artifact)
  _, manifest_sha256 = _artifact_size_and_sha256(args.manifest)
  evidence = {
      "schema_version": 1,
      "kind": "personal-target-ota-publication",
      "production_authorized": False,
      "release_evidence": False,
      "commit": args.expected_commit,
      "version": args.expected_version,
      "build_id": args.expected_build_id,
      "artifact_size": artifact_size,
      "artifact_sha256": artifact_sha256,
      "manifest_sha256": manifest_sha256,
      "immutable_artifact": result["immutable_artifact"],
      "immutable_manifest": result["immutable_manifest"],
      "atomic_metadata_swap": True,
      "previous_valid_artifact_retained": result["previous_valid_artifact"],
      "previous_valid_manifest": result["previous_valid_manifest"],
      "host_key_mode": host_key_mode,
      "result": result["result"],
  }
  args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
  args.evidence_output.write_text(
      json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
  )


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


MOBILE_REMOTE_ROOT = re.compile(
    r"^/docker/smartbox_ota/[A-Za-z0-9._/-]+$"
)


def _validated_mobile_remote_root(value: str) -> str:
  root = value.rstrip("/")
  if (
      not MOBILE_REMOTE_ROOT.fullmatch(root)
      or "//" in root
      or any(segment in ("", ".", "..") for segment in root.split("/")[1:])
  ):
    raise GateError("mobile NAS directory must be a canonical /docker/smartbox_ota path")
  return root


def _ensure_sftp_directory(sftp: Any, root: str) -> None:
  current = ""
  for segment in root.split("/")[1:]:
    current += f"/{segment}"
    try:
      remote_stat = sftp.stat(current)
    except OSError as exc:
      if getattr(exc, "errno", None) != 2 and "no such file" not in str(exc).lower():
        raise
      sftp.mkdir(current)
      remote_stat = sftp.stat(current)
    if not stat.S_ISDIR(remote_stat.st_mode):
      raise GateError("mobile NAS path component is not a directory")


def _validate_remote_mobile_pair(
    manifest_bytes: bytes | None,
    apk_bytes: bytes | None,
    public_key_hex: str,
    apkanalyzer: Path,
    apksigner: Path,
) -> dict[str, Any] | None:
  if manifest_bytes is None or apk_bytes is None:
    return None
  try:
    manifest = _manifest_from_bytes(manifest_bytes)
    validate_manifest(manifest, "mobile-manifest.schema.json", public_key_hex)
    if (
        manifest.get("apk_size") != len(apk_bytes)
        or manifest.get("sha256") != hashlib.sha256(apk_bytes).hexdigest()
    ):
      return None
    with tempfile.TemporaryDirectory() as directory_name:
      previous_apk = Path(directory_name) / "previous.apk"
      previous_apk.write_bytes(apk_bytes)
      _validate_mobile_apk_identity(
          previous_apk,
          apkanalyzer,
          "com.kshouse.gatekeeper_app",
          str(manifest["version_name"]),
          int(manifest["version_code"]),
          str(manifest["commit"]),
      )
      if read_apk_signing_certificate_digests(previous_apk, apksigner) != {
          manifest["signing_certificate_digest"]
      }:
        return None
    return manifest
  except (GateError, OSError):
    return None


def _validate_remote_mobile_manifest(
    manifest_bytes: bytes | None,
    public_key_hex: str,
) -> dict[str, Any] | None:
  if manifest_bytes is None:
    return None
  try:
    manifest = _manifest_from_bytes(manifest_bytes)
    validate_manifest(manifest, "mobile-manifest.schema.json", public_key_hex)
    return manifest
  except GateError as exc:
    raise GateError(
        "existing mobile OTA manifest is present but unverifiable"
    ) from exc


def _mobile_pair_decision(
    existing_manifest: dict[str, Any] | None,
    existing_pair_valid: bool,
    candidate: dict[str, Any],
) -> str:
  if existing_manifest is None:
    return "publish-bootstrap"
  if (
      existing_manifest["commit"] == candidate["commit"]
      and existing_manifest["build_number"] == candidate["build_number"]
      and existing_manifest["sha256"] == candidate["sha256"]
      and existing_manifest["apk_url"] == candidate["apk_url"]
      and existing_manifest["fallback_url"] == candidate["fallback_url"]
  ):
    if not existing_pair_valid:
      raise GateError(
          "current signed mobile OTA floor requires a strictly newer candidate"
      )
    return "idempotent"
  if int(existing_manifest["build_number"]) >= int(candidate["build_number"]):
    raise GateError("stale or conflicting mobile OTA publish refused")
  if existing_pair_valid:
    return "publish-upgrade"
  return "publish-upgrade-replacing-invalid-pair"


def _read_mobile_sftp_root_state(
    sftp: Any,
    remote_root: str,
    public_key_hex: str,
    apkanalyzer: Path,
    apksigner: Path,
) -> dict[str, Any]:
  fixed_apk = f"{remote_root}/ks-house-gatekeeper.apk"
  fixed_manifest = f"{remote_root}/version.json"
  apk_bytes = _read_optional_sftp_bytes(sftp, fixed_apk)
  manifest_bytes = _read_optional_sftp_bytes(sftp, fixed_manifest)
  if manifest_bytes is None and apk_bytes is not None:
    raise GateError("mobile OTA APK exists without a signed manifest")
  manifest = _validate_remote_mobile_manifest(manifest_bytes, public_key_hex)
  valid_pair = _validate_remote_mobile_pair(
      manifest_bytes,
      apk_bytes,
      public_key_hex,
      apkanalyzer,
      apksigner,
  )
  return {
      "apk_bytes": apk_bytes,
      "manifest_bytes": manifest_bytes,
      "manifest": manifest,
      "valid_pair": valid_pair,
  }


def _preflight_mobile_sftp_roots(
    sftp: Any,
    remote_roots: tuple[str, ...],
    candidate: dict[str, Any],
    public_key_hex: str,
    apkanalyzer: Path,
    apksigner: Path,
) -> None:
  if len(remote_roots) < 2 or len(set(remote_roots)) != len(remote_roots):
    raise GateError("mobile OTA preflight requires distinct primary and fallback roots")
  for remote_root in remote_roots:
    state = _read_mobile_sftp_root_state(
        sftp,
        remote_root,
        public_key_hex,
        apkanalyzer,
        apksigner,
    )
    _mobile_pair_decision(
        state["manifest"],
        state["valid_pair"] is not None,
        candidate,
    )


def _publish_mobile_sftp_root(
    sftp: Any,
    remote_root: str,
    artifact_path: Path,
    manifest_path: Path,
    candidate: dict[str, Any],
    public_key_hex: str,
    apkanalyzer: Path,
    apksigner: Path,
    run_attempt: str,
) -> dict[str, Any]:
  _ensure_sftp_directory(sftp, remote_root)
  commit = str(candidate["commit"])
  build_number = int(candidate["build_number"])
  if not re.fullmatch(r"[0-9a-f]{40}", commit) or build_number < 1:
    raise GateError("mobile OTA identity is invalid")
  if not re.fullmatch(r"[1-9][0-9]*", run_attempt):
    raise GateError("mobile OTA run attempt is invalid")
  artifact_bytes = artifact_path.read_bytes()
  manifest_bytes = manifest_path.read_bytes()
  fixed_apk = f"{remote_root}/ks-house-gatekeeper.apk"
  fixed_manifest = f"{remote_root}/version.json"
  initial_state = _read_mobile_sftp_root_state(
      sftp,
      remote_root,
      public_key_hex,
      apkanalyzer,
      apksigner,
  )
  initial_apk = initial_state["apk_bytes"]
  initial_manifest_bytes = initial_state["manifest_bytes"]
  initial_manifest = initial_state["manifest"]
  initial_valid = initial_state["valid_pair"]
  decision = _mobile_pair_decision(
      initial_manifest,
      initial_valid is not None,
      candidate,
  )
  if decision == "idempotent" and (
      initial_apk != artifact_bytes or initial_manifest_bytes != manifest_bytes
  ):
    raise GateError("equal mobile OTA identity has conflicting signed bytes")
  immutable_apk_name = (
      f"ks-house-gatekeeper-{commit}-{build_number}.apk"
  )
  immutable_manifest_name = f"version-{commit}-{build_number}.json"
  stage = (
      f"{remote_root}/.staging-{commit}-{build_number}-{run_attempt}"
  )
  sftp.mkdir(stage)
  staged_fixed_apk = f"{stage}/ks-house-gatekeeper.apk"
  staged_fixed_manifest = f"{stage}/version.json"
  staged_immutable_apk = f"{stage}/{immutable_apk_name}"
  staged_immutable_manifest = f"{stage}/{immutable_manifest_name}"
  for local_path, remote_path in (
      (artifact_path, staged_fixed_apk),
      (manifest_path, staged_fixed_manifest),
      (artifact_path, staged_immutable_apk),
      (manifest_path, staged_immutable_manifest),
  ):
    sftp.put(str(local_path), remote_path, confirm=True)
  if (
      _read_sftp_bytes(sftp, staged_fixed_apk) != artifact_bytes
      or _read_sftp_bytes(sftp, staged_immutable_apk) != artifact_bytes
      or _read_sftp_bytes(sftp, staged_fixed_manifest) != manifest_bytes
      or _read_sftp_bytes(sftp, staged_immutable_manifest) != manifest_bytes
  ):
    raise GateError("mobile NAS staged readback differs")

  _place_immutable_sftp_bytes(
      sftp,
      staged_immutable_apk,
      f"{remote_root}/{immutable_apk_name}",
      artifact_bytes,
  )
  _place_immutable_sftp_bytes(
      sftp,
      staged_immutable_manifest,
      f"{remote_root}/{immutable_manifest_name}",
      manifest_bytes,
  )

  if (
      initial_valid is not None
      and initial_apk is not None
      and initial_manifest_bytes is not None
  ):
    previous_commit = str(initial_valid["commit"])
    previous_build = int(initial_valid["build_number"])
    previous_apk_stage = (
        f"{stage}/previous-{previous_commit}-{previous_build}.apk"
    )
    previous_manifest_stage = (
        f"{stage}/previous-{previous_commit}-{previous_build}.json"
    )
    _write_sftp_bytes(sftp, previous_apk_stage, initial_apk)
    _write_sftp_bytes(sftp, previous_manifest_stage, initial_manifest_bytes)
    if (
        _read_sftp_bytes(sftp, previous_apk_stage) != initial_apk
        or _read_sftp_bytes(sftp, previous_manifest_stage)
        != initial_manifest_bytes
    ):
      raise GateError("previous valid mobile OTA history readback differs")
    _place_immutable_sftp_bytes(
        sftp,
        previous_apk_stage,
        (
            f"{remote_root}/ks-house-gatekeeper-"
            f"{previous_commit}-{previous_build}.apk"
        ),
        initial_apk,
    )
    _place_immutable_sftp_bytes(
        sftp,
        previous_manifest_stage,
        f"{remote_root}/version-{previous_commit}-{previous_build}.json",
        initial_manifest_bytes,
    )

  if decision == "idempotent":
    sftp.remove(staged_fixed_apk)
    sftp.remove(staged_fixed_manifest)
    sftp.rmdir(stage)
    return {
        "result": "idempotent",
        "previous_valid_pair": True,
        "immutable_artifact": immutable_apk_name,
        "immutable_manifest": immutable_manifest_name,
    }

  current_apk = _read_optional_sftp_bytes(sftp, fixed_apk)
  current_manifest_bytes = _read_optional_sftp_bytes(sftp, fixed_manifest)
  if current_apk != initial_apk or current_manifest_bytes != initial_manifest_bytes:
    if current_manifest_bytes is None and current_apk is not None:
      raise GateError("mobile NAS current APK lost its signed manifest")
    current_manifest = _validate_remote_mobile_manifest(
        current_manifest_bytes,
        public_key_hex,
    )
    current_valid = _validate_remote_mobile_pair(
        current_manifest_bytes,
        current_apk,
        public_key_hex,
        apkanalyzer,
        apksigner,
    )
    current_decision = _mobile_pair_decision(
        current_manifest,
        current_valid is not None,
        candidate,
    )
    if current_decision == "idempotent":
      if current_apk != artifact_bytes or current_manifest_bytes != manifest_bytes:
        raise GateError("equal mobile OTA race identity has conflicting signed bytes")
      sftp.remove(staged_fixed_apk)
      sftp.remove(staged_fixed_manifest)
      sftp.rmdir(stage)
      return {
          "result": "idempotent-race-winner",
          "previous_valid_pair": True,
          "immutable_artifact": immutable_apk_name,
          "immutable_manifest": immutable_manifest_name,
      }
    raise GateError("mobile NAS current pair changed during staged publication")

  # The fixed APK changes first. During the short interval before the signed
  # metadata swap, an old manifest can only reject the new bytes by exact hash.
  # Both promotions and both readbacks remain inside the rollback boundary.
  try:
    sftp.posix_rename(staged_fixed_apk, fixed_apk)
    if _read_sftp_bytes(sftp, fixed_apk) != artifact_bytes:
      raise GateError("atomic mobile APK readback differs")
    sftp.posix_rename(staged_fixed_manifest, fixed_manifest)
    if _read_sftp_bytes(sftp, fixed_manifest) != manifest_bytes:
      raise GateError("atomic mobile manifest readback differs")
  except Exception as promotion_error:
    if (
        initial_valid is None
        or initial_apk is None
        or initial_manifest_bytes is None
    ):
      raise
    rollback_apk = f"{stage}/rollback-previous.apk"
    rollback_manifest = f"{stage}/rollback-previous-version.json"
    try:
      _write_sftp_bytes(sftp, rollback_apk, initial_apk)
      _write_sftp_bytes(sftp, rollback_manifest, initial_manifest_bytes)
      if (
          _read_sftp_bytes(sftp, rollback_apk) != initial_apk
          or _read_sftp_bytes(sftp, rollback_manifest)
          != initial_manifest_bytes
      ):
        raise GateError("mobile OTA rollback staging readback differs")
      sftp.posix_rename(rollback_apk, fixed_apk)
      sftp.posix_rename(rollback_manifest, fixed_manifest)
      if (
          _read_sftp_bytes(sftp, fixed_apk) != initial_apk
          or _read_sftp_bytes(sftp, fixed_manifest)
          != initial_manifest_bytes
      ):
        raise GateError("mobile OTA previous-pair rollback readback differs")
    except Exception as rollback_error:
      raise GateError(
          "mobile manifest promotion and previous-pair rollback both failed"
      ) from rollback_error
    raise GateError(
        "mobile manifest promotion failed; previous valid pair was restored"
    ) from promotion_error
  sftp.rmdir(stage)
  return {
      "result": decision,
      "previous_valid_pair": initial_valid is not None,
      "immutable_artifact": immutable_apk_name,
      "immutable_manifest": immutable_manifest_name,
  }


def publish_mobile_sftp(args: argparse.Namespace) -> None:
  public_key_hex = os.environ.get("MOBILE_PUBLIC_KEY_HEX", "")
  if not re.fullmatch(r"[0-9a-f]{64}", public_key_hex):
    raise GateError("MOBILE_PUBLIC_KEY_HEX must be exact lowercase 32-byte hex")
  verify_mobile_manifest(argparse.Namespace(
      manifest=args.manifest,
      artifact=args.artifact,
      public_key_hex=public_key_hex,
      expected_package_name=args.expected_package_name,
      apkanalyzer=args.apkanalyzer,
      apksigner=args.apksigner,
  ))
  candidate = load_json(args.manifest)
  if (
      candidate.get("version") != args.expected_version
      or candidate.get("commit") != args.expected_commit
      or candidate.get("build_number") != args.expected_build_number
  ):
    raise GateError("mobile manifest does not match the expected exact-main identity")
  host = os.environ.get("NAS_HOST", "")
  user = os.environ.get("NAS_USER", "")
  password = os.environ.get("NAS_PASSWORD", "")
  port_text = os.environ.get("NAS_PORT", "")
  known_hosts_path = Path(os.environ.get("OTA_NAS_KNOWN_HOSTS_FILE", ""))
  host_key_mode = os.environ.get("OTA_NAS_HOST_KEY_MODE", "")
  if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
    raise GateError("NAS_HOST format is invalid")
  if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}", user):
    raise GateError("NAS_USER format is invalid")
  if not password:
    raise GateError("NAS_PASSWORD is empty")
  if not re.fullmatch(r"[0-9]{1,5}", port_text) or not 1 <= int(port_text) <= 65535:
    raise GateError("NAS_PORT format or range is invalid")
  if not known_hosts_path.is_file() or known_hosts_path.stat().st_size < 1:
    raise GateError("strict NAS known-hosts file is missing")
  if host_key_mode != "repository-secret-pinned":
    raise GateError("automatic mobile OTA requires repository-pinned NAS host keys")
  primary_root = _validated_mobile_remote_root(
      os.environ.get("NAS_APK_TARGET_DIR", "")
      or "/docker/smartbox_ota/gatekeeper_apk"
  )
  fallback_root = _validated_mobile_remote_root(
      os.environ.get("NAS_APK_FALLBACK_TARGET_DIR", "")
      or "/docker/smartbox_ota/gatekeeper_apk_fallback"
  )
  if primary_root == fallback_root:
    raise GateError("mobile primary and fallback NAS directories must differ")
  try:
    import paramiko
  except ImportError as exc:
    raise GateError("Paramiko is required for atomic mobile OTA publication") from exc
  client = paramiko.SSHClient()
  try:
    client.load_host_keys(str(known_hosts_path))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        hostname=host,
        port=int(port_text),
        username=user,
        password=password,
        allow_agent=False,
        look_for_keys=False,
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    with client.open_sftp() as sftp:
      _preflight_mobile_sftp_roots(
          sftp,
          (primary_root, fallback_root),
          candidate,
          public_key_hex,
          args.apkanalyzer,
          args.apksigner,
      )
      # Fallback first: if primary promotion later fails, both endpoints still
      # serve independently signed and hash-bound old/new pairs.
      fallback_result = _publish_mobile_sftp_root(
          sftp,
          fallback_root,
          args.artifact,
          args.manifest,
          candidate,
          public_key_hex,
          args.apkanalyzer,
          args.apksigner,
          args.run_attempt,
      )
      primary_result = _publish_mobile_sftp_root(
          sftp,
          primary_root,
          args.artifact,
          args.manifest,
          candidate,
          public_key_hex,
          args.apkanalyzer,
          args.apksigner,
          args.run_attempt,
      )
  except GateError:
    raise
  except Exception as exc:
    raise GateError(
        "mobile OTA SFTP publication failed before all atomic readbacks"
    ) from exc
  finally:
    client.close()

  artifact_size, artifact_sha256 = _artifact_size_and_sha256(args.artifact)
  _, manifest_sha256 = _artifact_size_and_sha256(args.manifest)
  previous_valid_artifact_retained = bool(
      primary_result["previous_valid_pair"]
      and fallback_result["previous_valid_pair"]
  )
  evidence = {
      "schema_version": 1,
      "kind": "personal-mobile-ota-publication",
      "production_authorized": False,
      "release_evidence": False,
      "commit": args.expected_commit,
      "version": args.expected_version,
      "build_number": args.expected_build_number,
      "artifact_size": artifact_size,
      "artifact_sha256": artifact_sha256,
      "manifest_sha256": manifest_sha256,
      "primary": primary_result,
      "fallback": fallback_result,
      "atomic_fixed_apk_swap": True,
      "atomic_metadata_swap": True,
      "previous_valid_artifact_retained": previous_valid_artifact_retained,
      "host_key_mode": host_key_mode,
  }
  args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
  args.evidence_output.write_text(
      json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
  )


def verify_physical_test_canary(args: argparse.Namespace) -> dict[str, Any]:
  """Verify an exact public/test-signed canary without granting release status."""
  if not re.fullmatch(r"[0-9a-f]{40}", args.expected_commit):
    raise GateError("physical-test expected commit must be a lowercase 40-byte SHA")
  manifest = load_json(args.manifest)
  if manifest.get("commit") != args.expected_commit:
    raise GateError("physical-test manifest is not bound to the dispatched main SHA")
  if manifest.get("signing_key_id") != "rfc8032-test-key-1":
    raise GateError("physical-test public canary must use the fixed RFC8032 test key")

  version_prefix = "2.1.0-g" if args.kind == "target" else "1.0.0-g"
  expected_version = manifest.get("version")
  short_commit = (
      expected_version[len(version_prefix):]
      if isinstance(expected_version, str) and expected_version.startswith(version_prefix)
      else ""
  )
  if (
      not re.fullmatch(r"[0-9a-f]{7,40}", short_commit)
      or not args.expected_commit.startswith(short_commit)
  ):
    raise GateError("physical-test canary version is not derived from the exact commit")

  if args.kind == "target":
    if manifest.get("artifact_type") != "target-firmware":
      raise GateError("physical-test target lane requires a Target manifest")
    if manifest.get("build_id") != f"public-canary-{args.expected_commit}":
      raise GateError("physical-test Target build ID is not exact-run public canary")
    if manifest.get("artifact_url") != (
        f"https://target-canary.invalid/smart-gatekeeper/"
        f"gatekeeper-firmware-{args.expected_commit}.bin"
    ):
      raise GateError("physical-test Target public manifest must remain non-connected")
    verify_target_manifest(
        argparse.Namespace(
            manifest=args.manifest,
            artifact=args.artifact,
            public_key_hex=TEST_PUBLIC_KEY_HEX,
            expected_version=expected_version,
            expected_commit=args.expected_commit,
            expected_build_id=f"public-canary-{args.expected_commit}",
        )
    )
  elif args.kind == "mobile":
    if manifest.get("artifact_type") != "android-apk":
      raise GateError("physical-test mobile lane requires an Android manifest")
    expected_urls = {
        "apk_url": (
            f"https://pr-canary.invalid/smart-gatekeeper/"
            f"{args.expected_commit}/app.apk"
        ),
        "fallback_url": (
            f"https://pr-fallback.invalid/smart-gatekeeper/"
            f"{args.expected_commit}/app.apk"
        ),
        "release_notes_url": (
            f"https://pr-canary.invalid/smart-gatekeeper/"
            f"{args.expected_commit}/notes"
        ),
    }
    if any(manifest.get(field) != value for field, value in expected_urls.items()):
      raise GateError("physical-test mobile public manifest must remain non-connected")
    if args.apkanalyzer is None or args.apksigner is None:
      raise GateError("physical-test mobile verification requires APK tools")
    verify_mobile_manifest(
        argparse.Namespace(
            manifest=args.manifest,
            artifact=args.artifact,
            public_key_hex=TEST_PUBLIC_KEY_HEX,
            expected_package_name="com.kshouse.gatekeeper_app",
            apkanalyzer=args.apkanalyzer,
            apksigner=args.apksigner,
        )
    )
  else:
    raise GateError("physical-test kind must be target or mobile")
  return manifest


def create_physical_test_evidence(args: argparse.Namespace) -> None:
  """Bind local and NAS-readback bytes to a sanitized, non-release claim."""
  manifest = verify_physical_test_canary(args)
  readback_args = argparse.Namespace(
      kind=args.kind,
      manifest=args.readback_manifest,
      artifact=args.readback_artifact,
      expected_commit=args.expected_commit,
      apkanalyzer=args.apkanalyzer,
      apksigner=args.apksigner,
  )
  verify_physical_test_canary(readback_args)
  if args.manifest.read_bytes() != args.readback_manifest.read_bytes():
    raise GateError("physical-test NAS manifest readback differs from staged bytes")
  if args.artifact.read_bytes() != args.readback_artifact.read_bytes():
    raise GateError("physical-test NAS artifact readback differs from staged bytes")

  if args.host_key_mode not in {
      "repository-secret-pinned",
      "runtime-keyscan-unpinned",
  }:
    raise GateError("physical-test host-key mode is invalid")
  remote_component = (
      "firmware-public-canary" if args.kind == "target" else "mobile-public-canary"
  )
  remote_pattern = re.compile(
      rf"^/docker/smart-gatekeeper-physical-test/{remote_component}/"
      rf"{args.expected_commit}/run-[1-9][0-9]*-[1-9][0-9]*$"
  )
  if not remote_pattern.fullmatch(args.remote_path):
    raise GateError("physical-test remote path is outside the isolated canary root")

  _, artifact_sha256 = _artifact_size_and_sha256(args.artifact)
  _, manifest_sha256 = _artifact_size_and_sha256(args.manifest)
  evidence = {
      "schema_version": 1,
      "claim": "nas-physical-test-canary-staged-readback-verified",
      "tier": "public-test-signed-non-connected",
      "kind": args.kind,
      "source_commit": args.expected_commit,
      "artifact_name": args.artifact.name,
      "artifact_sha256": artifact_sha256,
      "manifest_sha256": manifest_sha256,
      "manifest_signing_key_id": manifest["signing_key_id"],
      "host_key_mode": args.host_key_mode,
      "remote_path": args.remote_path,
      "nas_upload_verified": True,
      "physical_validation_status": "pending",
      "production_authorized": False,
      "release_evidence": False,
  }
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(
      json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
      encoding="utf-8",
  )
  print(f"[PHYSICAL-TEST] sanitized evidence created: {args.output}")


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
  target_encrypt = subparsers.add_parser(
      "target-handoff-encrypt",
      help="encrypt a sensitive production firmware handoff for the publisher",
  )
  target_encrypt.add_argument("--artifact", type=Path, required=True)
  target_encrypt.add_argument("--output", type=Path, required=True)
  target_encrypt.add_argument("--recipient-public-key-hex", required=True)
  target_encrypt.add_argument("--commit", required=True)
  target_encrypt.add_argument("--run-attempt", required=True)
  target_decrypt = subparsers.add_parser(
      "target-handoff-decrypt",
      help="authenticate and decrypt a sensitive production firmware handoff",
  )
  target_decrypt.add_argument("--input", type=Path, required=True)
  target_decrypt.add_argument("--output", type=Path, required=True)
  target_decrypt.add_argument("--private-key-env", required=True)
  target_decrypt.add_argument("--recipient-public-key-hex", required=True)
  target_decrypt.add_argument("--commit", required=True)
  target_decrypt.add_argument("--run-attempt", required=True)
  target_content_encrypt = subparsers.add_parser(
      "target-content-encrypt",
      help="encrypt exact Target firmware bytes for public NAS delivery",
  )
  target_content_encrypt.add_argument("--artifact", type=Path, required=True)
  target_content_encrypt.add_argument("--output", type=Path, required=True)
  target_content_encrypt.add_argument("--key-env", required=True)
  target_content_encrypt.add_argument("--key-id", required=True)
  target_content_encrypt.add_argument("--commit", required=True)
  target_content_decrypt = subparsers.add_parser(
      "target-content-decrypt",
      help="authenticate and decrypt a Target NAS delivery envelope",
  )
  target_content_decrypt.add_argument("--input", type=Path, required=True)
  target_content_decrypt.add_argument("--output", type=Path, required=True)
  target_content_decrypt.add_argument("--key-env", required=True)
  target_content_decrypt.add_argument("--key-id", required=True)
  target_content_decrypt.add_argument("--commit", required=True)
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
  target_create.add_argument("--plaintext-artifact", type=Path)
  target_create.add_argument("--encryption-key-id")
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
  target_verify.add_argument("--expected-encryption-key-id")
  target_publish = subparsers.add_parser(
      "target-sftp-publish",
      help=(
          "stage/read back immutable Target OTA bytes and atomically replace "
          "the NAS version pointer"
      ),
  )
  target_publish.add_argument("--artifact", type=Path, required=True)
  target_publish.add_argument("--manifest", type=Path, required=True)
  target_publish.add_argument("--expected-version", required=True)
  target_publish.add_argument("--expected-commit", required=True)
  target_publish.add_argument("--expected-build-id", required=True)
  target_publish.add_argument("--run-attempt", required=True)
  target_publish.add_argument("--evidence-output", type=Path, required=True)
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
  mobile_publish = subparsers.add_parser(
      "mobile-sftp-publish",
      help=(
          "stage/read back immutable mobile OTA bytes and atomically replace "
          "the NAS fixed APK and signed metadata pair"
      ),
  )
  mobile_publish.add_argument("--artifact", type=Path, required=True)
  mobile_publish.add_argument("--manifest", type=Path, required=True)
  mobile_publish.add_argument("--expected-version", required=True)
  mobile_publish.add_argument("--expected-commit", required=True)
  mobile_publish.add_argument("--expected-build-number", type=int, required=True)
  mobile_publish.add_argument("--expected-package-name", required=True)
  mobile_publish.add_argument("--run-attempt", required=True)
  mobile_publish.add_argument("--evidence-output", type=Path, required=True)
  mobile_publish.add_argument("--apkanalyzer", type=Path, required=True)
  mobile_publish.add_argument("--apksigner", type=Path, required=True)
  physical_verify = subparsers.add_parser(
      "physical-test-canary-verify",
      help="verify an exact public/test-signed non-release physical-test canary",
  )
  physical_verify.add_argument("--kind", choices=("target", "mobile"), required=True)
  physical_verify.add_argument("--manifest", type=Path, required=True)
  physical_verify.add_argument("--artifact", type=Path, required=True)
  physical_verify.add_argument("--expected-commit", required=True)
  physical_verify.add_argument("--apkanalyzer", type=Path)
  physical_verify.add_argument("--apksigner", type=Path)
  physical_evidence = subparsers.add_parser(
      "physical-test-evidence-create",
      help="verify NAS readback and create a sanitized non-release evidence record",
  )
  physical_evidence.add_argument("--kind", choices=("target", "mobile"), required=True)
  physical_evidence.add_argument("--manifest", type=Path, required=True)
  physical_evidence.add_argument("--artifact", type=Path, required=True)
  physical_evidence.add_argument("--readback-manifest", type=Path, required=True)
  physical_evidence.add_argument("--readback-artifact", type=Path, required=True)
  physical_evidence.add_argument("--expected-commit", required=True)
  physical_evidence.add_argument("--host-key-mode", required=True)
  physical_evidence.add_argument("--remote-path", required=True)
  physical_evidence.add_argument("--output", type=Path, required=True)
  physical_evidence.add_argument("--apkanalyzer", type=Path)
  physical_evidence.add_argument("--apksigner", type=Path)
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  try:
    if args.command in {
        "contract", "release", "physical-test-canary-verify",
        "physical-test-evidence-create",
    }:
      validate_contract()
    if args.command == "release":
      validate_release_evidence(args.evidence)
      validate_release_manifests(
          args.manifest, args.artifact, args.public_key_hex, args.apksigner
      )
    elif args.command == "target-handoff-encrypt":
      encrypt_target_handoff(args)
    elif args.command == "target-handoff-decrypt":
      decrypt_target_handoff(args)
    elif args.command == "target-content-encrypt":
      encrypt_target_content(args)
    elif args.command == "target-content-decrypt":
      decrypt_target_content(args)
    elif args.command == "target-manifest-create":
      create_target_manifest(args)
    elif args.command == "target-manifest-verify":
      verify_target_manifest(args)
    elif args.command == "target-sftp-publish":
      publish_target_sftp(args)
    elif args.command == "mobile-manifest-create":
      create_mobile_manifest(args)
    elif args.command == "mobile-manifest-verify":
      verify_mobile_manifest(args)
    elif args.command == "mobile-sftp-publish":
      publish_mobile_sftp(args)
    elif args.command == "physical-test-canary-verify":
      verify_physical_test_canary(args)
    elif args.command == "physical-test-evidence-create":
      create_physical_test_evidence(args)
  except (GateError, OSError, json.JSONDecodeError) as exc:
    print(f"[OTA-GATE] FAIL: {exc}", file=sys.stderr)
    return 1
  print(f"[OTA-GATE] PASS: {args.command}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
