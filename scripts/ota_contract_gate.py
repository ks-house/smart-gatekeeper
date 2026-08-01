#!/usr/bin/env python3
"""Validate OTA contracts and block releases without complete P0 evidence."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import sys
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
OTA = ROOT / "ota"
TEST_PUBLIC_KEY_HEX = (
    "d75a980182b10ab7d54bfed3c964073a"
    "0ee172f3daa62325af021a68f707511a"
)


class GateError(RuntimeError):
  """A release-contract violation."""


def load_json(path: Path) -> dict[str, Any]:
  with path.open(encoding="utf-8") as handle:
    value = json.load(handle)
  if not isinstance(value, dict):
    raise GateError(f"{path}: top-level JSON value must be an object")
  return value


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
  schema = load_json(OTA / "schemas" / schema_name)
  errors = sorted(
      Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
          manifest
      ),
      key=lambda error: list(error.path),
  )
  if errors:
    detail = "; ".join(error.message for error in errors)
    raise GateError(f"{schema_name}: schema validation failed: {detail}")

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


def validate_state_machines() -> None:
  document = load_json(OTA / "state-machines.json")
  required = {
      "target": {
          "IDLE", "WAIT_SAFE_STATE", "VERIFY_MANIFEST", "DOWNLOAD_INACTIVE_SLOT",
          "SET_PENDING_BOOT", "BOOT_HEALTH_WINDOW", "MARK_VALID",
          "ROLLBACK_PREVIOUS_SLOT",
      },
      "mobile": {
          "IDLE", "CHECK_METADATA", "VERIFY_METADATA", "DOWNLOAD_TEMP",
          "VERIFY_APK", "REQUEST_PACKAGE_INSTALL", "NEW_APP_FIRST_RUN_HEALTH",
      },
  }
  for component, states in required.items():
    actual = set(document.get(component, {}).get("states", []))
    missing = states - actual
    if missing:
      raise GateError(f"{component} state machine missing: {sorted(missing)}")


def validate_recovery_and_faults() -> None:
  recovery = load_json(OTA / "recovery-matrix.json")
  ids = {row.get("id") for row in recovery.get("rows", [])}
  required = {
      "primary-endpoint-down", "mqtt-down", "download-interrupted",
      "hash-signature-invalid", "power-loss", "new-version-crash",
      "n-minus-one", "storage-full",
  }
  if missing := required - ids:
    raise GateError(f"recovery matrix missing: {sorted(missing)}")

  plan = load_json(OTA / "fault-injection-plan.json")
  tests = plan.get("tests", [])
  if len(tests) < 10 or not any(test.get("physical_gate") for test in tests):
    raise GateError("fault plan must include at least ten tests and physical gates")


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


def validate_contract() -> None:
  validate_partitions()
  validate_state_machines()
  validate_recovery_and_faults()
  validate_vectors()


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


def validate_release_manifests(paths: list[Path], public_key_hex: str) -> None:
  if len(public_key_hex) != 64:
    raise GateError("production Ed25519 public key must be 32-byte lowercase hex")
  schemas = {
      "target-firmware": "target-manifest.schema.json",
      "android-apk": "mobile-manifest.schema.json",
  }
  for path in paths:
    manifest = load_json(path)
    artifact_type = manifest.get("artifact_type")
    if artifact_type not in schemas:
      raise GateError(f"{path}: unsupported or missing artifact_type")
    validate_manifest(manifest, schemas[artifact_type], public_key_hex)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  subparsers = parser.add_subparsers(dest="command", required=True)
  subparsers.add_parser("contract", help="validate schemas, vectors and invariants")
  release = subparsers.add_parser("release", help="enforce all production gates")
  release.add_argument(
      "--evidence", type=Path, default=OTA / "release-evidence.json"
  )
  release.add_argument("--manifest", action="append", type=Path, required=True)
  release.add_argument("--public-key-hex", required=True)
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  try:
    validate_contract()
    if args.command == "release":
      validate_release_evidence(args.evidence)
      validate_release_manifests(args.manifest, args.public_key_hex)
  except (GateError, OSError, json.JSONDecodeError) as exc:
    print(f"[OTA-GATE] FAIL: {exc}", file=sys.stderr)
    return 1
  print(f"[OTA-GATE] PASS: {args.command}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
