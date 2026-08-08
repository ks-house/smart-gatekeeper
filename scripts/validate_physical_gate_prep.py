#!/usr/bin/env python3
"""Validate Issue #54 preparation artifacts without creating physical evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "physical_validation" / "issue54_gate_plan.json"
DEFAULT_TEMPLATE = ROOT / "physical_validation" / "evidence-template.json"
DEFAULT_SCHEMA = ROOT / "physical_validation" / "schemas" / "issue54_evidence.schema.json"
FORGED_FIXTURE = ROOT / "physical_validation" / "fixtures" / "forged-pass-without-evidence.json"
EXPECTED_GATES = (
    "SAMSUNG-WAKE-100",
    "ESP32-C6-COEXISTENCE-100",
    "GPIO3-RELAY-100",
    "AJ-SR04T-BOUNDARY-100",
    "RELAY-G0",
    "RELAY-G1",
    "RELAY-G2",
    "OTA-G1",
    "OTA-G2",
    "OTA-G3",
    "OTA-G4",
    "OPERATOR-DRILLS",
    "CANARY-STOP-ROLLBACK",
)
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ValidationError(ValueError):
  """A preparation artifact violates its fail-closed contract."""


def load_json(path: Path) -> dict[str, Any]:
  with path.open(encoding="utf-8") as handle:
    value = json.load(handle)
  if not isinstance(value, dict):
    raise ValidationError(f"{path}: root must be an object")
  return value


def require_exact_keys(value: dict[str, Any], keys: set[str], context: str) -> None:
  actual = set(value)
  if actual != keys:
    raise ValidationError(
        f"{context}: keys must be {sorted(keys)}, got {sorted(actual)}"
    )


def validate_plan(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
  require_exact_keys(plan, {"plan_version", "issue", "purpose", "gates"}, "plan")
  if plan["plan_version"] != "issue54-physical-gate-plan/v1" or plan["issue"] != 54:
    raise ValidationError("plan: unexpected identity")
  gates = plan["gates"]
  if not isinstance(gates, list):
    raise ValidationError("plan: gates must be a list")
  by_id: dict[str, dict[str, Any]] = {}
  for gate in gates:
    if not isinstance(gate, dict):
      raise ValidationError("plan: every gate must be an object")
    require_exact_keys(
        gate,
        {"id", "evidence_level", "minimum_trials", "matrix", "required_raw_evidence", "pass_condition"},
        "plan gate",
    )
    gate_id = gate["id"]
    if not isinstance(gate_id, str) or gate_id in by_id:
      raise ValidationError(f"plan: duplicate or invalid gate id {gate_id!r}")
    if gate["evidence_level"] not in {"L2", "L3", "L4"}:
      raise ValidationError(f"plan: {gate_id} has invalid evidence level")
    if not isinstance(gate["minimum_trials"], int) or gate["minimum_trials"] < 1:
      raise ValidationError(f"plan: {gate_id} has invalid minimum_trials")
    matrix = gate["matrix"]
    if not isinstance(matrix, list) or not matrix:
      raise ValidationError(f"plan: {gate_id} has no deterministic matrix")
    try:
      planned_trials = sum(item["trials"] for item in matrix)
    except (KeyError, TypeError):
      raise ValidationError(f"plan: {gate_id} has an invalid matrix") from None
    if planned_trials != gate["minimum_trials"]:
      raise ValidationError(f"plan: {gate_id} matrix count does not equal minimum_trials")
    if not all(isinstance(item.get("scenario"), str) and item["scenario"] for item in matrix):
      raise ValidationError(f"plan: {gate_id} has an unnamed scenario")
    if not all(isinstance(item.get("trials"), int) and item["trials"] > 0 for item in matrix):
      raise ValidationError(f"plan: {gate_id} has invalid scenario trials")
    if not isinstance(gate["required_raw_evidence"], list) or not gate["required_raw_evidence"]:
      raise ValidationError(f"plan: {gate_id} has no raw-evidence requirement")
    by_id[gate_id] = gate
  if tuple(by_id) != EXPECTED_GATES:
    raise ValidationError(
        "plan: gate coverage/order differs from Issue #54 required set "
        f"({list(EXPECTED_GATES)})"
    )
  return by_id


def validate_schema(schema: dict[str, Any]) -> None:
  if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
    raise ValidationError("schema: must declare JSON Schema draft 2020-12")
  if schema.get("$id") != "https://smart-gatekeeper.local/schemas/issue54-evidence-v1.json":
    raise ValidationError("schema: unexpected identity")
  if "record" not in schema.get("$defs", {}):
    raise ValidationError("schema: record definition is missing")


def validate_candidate(candidate: Any, completed: bool) -> None:
  if not isinstance(candidate, dict):
    raise ValidationError("evidence: candidate must be an object")
  require_exact_keys(
      candidate,
      {"git_sha", "firmware_artifact_sha256", "mobile_artifact_sha256"},
      "evidence candidate",
  )
  values = (candidate["git_sha"], candidate["firmware_artifact_sha256"], candidate["mobile_artifact_sha256"])
  if not completed:
    if any(value is not None for value in values):
      raise ValidationError("pending evidence template must not bind a candidate")
    return
  if not isinstance(values[0], str) or not SHA1_RE.fullmatch(values[0]):
    raise ValidationError("completed evidence requires a lowercase 40-character candidate SHA")
  if not isinstance(values[1], str) or not SHA256_RE.fullmatch(values[1]):
    raise ValidationError("completed evidence requires a firmware SHA-256")
  if not isinstance(values[2], str) or not SHA256_RE.fullmatch(values[2]):
    raise ValidationError("completed evidence requires a mobile SHA-256")


def validate_evidence(
    evidence: dict[str, Any], plan_by_id: dict[str, dict[str, Any]], require_pending: bool
) -> None:
  require_exact_keys(
      evidence,
      {"schema_version", "plan_version", "candidate", "records"},
      "evidence",
  )
  if evidence["schema_version"] != "issue54-physical-evidence/v1":
    raise ValidationError("evidence: unexpected schema_version")
  if evidence["plan_version"] != "issue54-physical-gate-plan/v1":
    raise ValidationError("evidence: unexpected plan_version")
  records = evidence["records"]
  if not isinstance(records, list):
    raise ValidationError("evidence: records must be a list")
  by_id: dict[str, dict[str, Any]] = {}
  for record in records:
    if not isinstance(record, dict):
      raise ValidationError("evidence: every record must be an object")
    require_exact_keys(
        record,
        {"gate_id", "status", "executed_trials", "passed_trials", "failed_trials", "raw_evidence", "operator_approval", "notes"},
        "evidence record",
    )
    gate_id = record["gate_id"]
    if gate_id not in plan_by_id or gate_id in by_id:
      raise ValidationError(f"evidence: unknown or duplicate gate {gate_id!r}")
    status = record["status"]
    if status not in {"not_run", "passed", "failed", "aborted"}:
      raise ValidationError(f"evidence: {gate_id} has invalid status")
    counts = (record["executed_trials"], record["passed_trials"], record["failed_trials"])
    if not all(isinstance(count, int) and count >= 0 for count in counts):
      raise ValidationError(f"evidence: {gate_id} has invalid trial counts")
    if record["passed_trials"] + record["failed_trials"] != record["executed_trials"]:
      raise ValidationError(f"evidence: {gate_id} trial counts do not add up")
    raw_evidence = record["raw_evidence"]
    if not isinstance(raw_evidence, list) or not all(
        isinstance(item, str) and item for item in raw_evidence
    ):
      raise ValidationError(f"evidence: {gate_id} has invalid raw_evidence")
    if not isinstance(record["notes"], str) or not record["notes"]:
      raise ValidationError(f"evidence: {gate_id} requires a note")
    minimum = plan_by_id[gate_id]["minimum_trials"]
    approval_required = plan_by_id[gate_id]["evidence_level"] in {"L3", "L4"} or gate_id == "RELAY-G0"
    if status == "not_run":
      if any(counts) or raw_evidence or record["operator_approval"] is not None:
        raise ValidationError(f"evidence: {gate_id} not_run record must contain no results or approval")
    elif status == "passed":
      if record["executed_trials"] < minimum or record["failed_trials"] != 0:
        raise ValidationError(f"evidence: {gate_id} passed record does not meet its full trial requirement")
      if not raw_evidence:
        raise ValidationError(f"evidence: {gate_id} passed record requires raw evidence")
      if approval_required and not isinstance(record["operator_approval"], dict):
        raise ValidationError(f"evidence: {gate_id} passed record requires operator or risk-owner approval")
    elif record["executed_trials"] and not raw_evidence:
      raise ValidationError(f"evidence: {gate_id} executed record requires raw evidence")
    by_id[gate_id] = record
  if tuple(by_id) != EXPECTED_GATES:
    raise ValidationError("evidence: record coverage/order differs from the deterministic plan")
  all_pending = all(record["status"] == "not_run" for record in records)
  if require_pending and not all_pending:
    raise ValidationError("pending-only validation rejects any claimed physical/operator/canary completion")
  validate_candidate(evidence["candidate"], completed=not all_pending)


def validate_all(evidence_path: Path, require_pending: bool) -> None:
  plan_by_id = validate_plan(load_json(DEFAULT_PLAN))
  validate_schema(load_json(DEFAULT_SCHEMA))
  validate_evidence(load_json(evidence_path), plan_by_id, require_pending=require_pending)


def self_test() -> None:
  validate_all(DEFAULT_TEMPLATE, require_pending=True)
  try:
    validate_all(FORGED_FIXTURE, require_pending=False)
  except ValidationError as exc:
    if "passed record requires raw evidence" not in str(exc):
      raise ValidationError(f"forged-pass fixture failed for an unexpected reason: {exc}") from exc
  else:
    raise ValidationError("forged-pass fixture was accepted")


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--evidence", type=Path, default=DEFAULT_TEMPLATE)
  parser.add_argument(
      "--require-pending",
      action="store_true",
      help="reject every completed gate; use for this preparation branch",
  )
  parser.add_argument("--self-test", action="store_true")
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  try:
    if args.self_test:
      self_test()
      print("[PHYSICAL-GATE-PREP] PASS: pending template plus forged-pass rejection")
    else:
      validate_all(args.evidence, require_pending=args.require_pending)
      print(f"[PHYSICAL-GATE-PREP] PASS: {args.evidence}")
  except (OSError, json.JSONDecodeError, ValidationError) as exc:
    print(f"[PHYSICAL-GATE-PREP] FAIL: {exc}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
