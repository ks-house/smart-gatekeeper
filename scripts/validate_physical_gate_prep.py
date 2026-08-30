#!/usr/bin/env python3
"""Validate Issue #54 preparation artifacts without creating physical evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "physical_validation" / "issue54_gate_plan.json"
DEFAULT_TEMPLATE = ROOT / "physical_validation" / "evidence-template.json"
DEFAULT_SCHEMA = ROOT / "physical_validation" / "schemas" / "issue54_evidence.schema.json"
FORGED_FIXTURE = ROOT / "physical_validation" / "fixtures" / "forged-pass-without-evidence.json"
EXPECTED_GATE_CONTRACTS = {
    "SAMSUNG-WAKE-100": ("PC-SAMSUNG-WAKE-100-V1", "independent_reviewer"),
    "ESP32-C6-COEXISTENCE-100": (
        "PC-ESP32-C6-COEXISTENCE-100-V1",
        "independent_reviewer",
    ),
    "GPIO23-RELAY-100": ("PC-GPIO23-RELAY-100-V1", "independent_reviewer"),
    "AJ-SR04T-BOUNDARY-100": (
        "PC-AJ-SR04T-BOUNDARY-100-V1",
        "independent_reviewer",
    ),
    "RELAY-G0": ("PC-RELAY-G0-V1", "risk_owner"),
    "RELAY-G1": ("PC-RELAY-G1-V1", "risk_owner"),
    "RELAY-G2": ("PC-RELAY-G2-V1", "risk_owner"),
    "OTA-G1": ("PC-OTA-G1-V1", "independent_reviewer"),
    "OTA-G2": ("PC-OTA-G2-V1", "independent_reviewer"),
    "OTA-G3": ("PC-OTA-G3-V1", "independent_reviewer"),
    "OTA-G4": ("PC-OTA-G4-V1", "operator_risk_owner"),
    "OPERATOR-DRILLS": ("PC-OPERATOR-DRILLS-V1", "operator_risk_owner"),
    "CANARY-STOP-ROLLBACK": (
        "PC-CANARY-STOP-ROLLBACK-V1",
        "release_risk_owner",
    ),
}
EXPECTED_GATES = tuple(EXPECTED_GATE_CONTRACTS)
ALLOWED_APPROVAL_ROLES = {
    "independent_reviewer",
    "risk_owner",
    "operator_risk_owner",
    "release_risk_owner",
}
STATUS_DECISIONS = {
    "passed": "approved",
    "failed": "rejected",
    "aborted": "incomplete",
}
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CATEGORY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IDENTITY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$")
CAPTURE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")


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


def require_nonblank(value: Any, context: str) -> str:
  if not isinstance(value, str) or not value.strip():
    raise ValidationError(f"{context}: must be a non-empty string")
  return value


def parse_timestamp(value: Any, context: str) -> datetime:
  if not isinstance(value, str):
    raise ValidationError(f"{context}: must be an ISO-8601 timestamp")
  try:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
  except ValueError:
    raise ValidationError(f"{context}: must be an ISO-8601 timestamp") from None
  if parsed.tzinfo is None or parsed.utcoffset() is None:
    raise ValidationError(f"{context}: timestamp must include a UTC offset")
  return parsed


def validate_identity(value: Any, context: str) -> str:
  if not isinstance(value, dict):
    raise ValidationError(f"{context}: identity must be an object")
  require_exact_keys(value, {"name", "identity_id"}, context)
  require_nonblank(value["name"], f"{context} name")
  identity_id = value["identity_id"]
  if not isinstance(identity_id, str) or not IDENTITY_ID_RE.fullmatch(identity_id):
    raise ValidationError(f"{context}: identity_id is invalid")
  return identity_id


def validate_plan(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
  require_exact_keys(plan, {"plan_version", "issue", "purpose", "gates"}, "plan")
  if plan["plan_version"] != "issue54-physical-gate-plan/v2" or plan["issue"] != 54:
    raise ValidationError("plan: unexpected identity")
  require_nonblank(plan["purpose"], "plan purpose")
  gates = plan["gates"]
  if not isinstance(gates, list):
    raise ValidationError("plan: gates must be a list")
  by_id: dict[str, dict[str, Any]] = {}
  for gate in gates:
    if not isinstance(gate, dict):
      raise ValidationError("plan: every gate must be an object")
    require_exact_keys(
        gate,
        {
            "id",
            "evidence_level",
            "minimum_trials",
            "matrix",
            "required_raw_evidence",
            "pass_condition_id",
            "required_approval_role",
            "pass_condition",
        },
        "plan gate",
    )
    gate_id = gate["id"]
    if (
        not isinstance(gate_id, str)
        or gate_id not in EXPECTED_GATE_CONTRACTS
        or gate_id in by_id
    ):
      raise ValidationError(f"plan: duplicate or invalid gate id {gate_id!r}")
    expected_condition, expected_role = EXPECTED_GATE_CONTRACTS[gate_id]
    if gate["pass_condition_id"] != expected_condition:
      raise ValidationError(f"plan: {gate_id} pass_condition_id is not authoritative")
    if gate["required_approval_role"] != expected_role:
      raise ValidationError(f"plan: {gate_id} required approval role is not authoritative")
    if expected_role not in ALLOWED_APPROVAL_ROLES:
      raise ValidationError(f"plan: {gate_id} has an unsupported approval role")
    require_nonblank(gate["pass_condition"], f"plan: {gate_id} pass condition")
    if gate["evidence_level"] not in {"L2", "L3", "L4"}:
      raise ValidationError(f"plan: {gate_id} has invalid evidence level")
    if not isinstance(gate["minimum_trials"], int) or gate["minimum_trials"] < 1:
      raise ValidationError(f"plan: {gate_id} has invalid minimum_trials")
    matrix = gate["matrix"]
    if not isinstance(matrix, list) or not matrix:
      raise ValidationError(f"plan: {gate_id} has no deterministic matrix")
    if not all(
        isinstance(item, dict) and set(item) == {"scenario", "trials"}
        for item in matrix
    ):
      raise ValidationError(f"plan: {gate_id} has an invalid matrix entry")
    if not all(
        isinstance(item["scenario"], str) and item["scenario"].strip()
        for item in matrix
    ):
      raise ValidationError(f"plan: {gate_id} has an unnamed scenario")
    if not all(isinstance(item["trials"], int) and item["trials"] > 0 for item in matrix):
      raise ValidationError(f"plan: {gate_id} has invalid scenario trials")
    planned_trials = sum(item["trials"] for item in matrix)
    if planned_trials != gate["minimum_trials"]:
      raise ValidationError(f"plan: {gate_id} matrix count does not equal minimum_trials")
    required_categories = gate["required_raw_evidence"]
    if (
        not isinstance(required_categories, list)
        or not required_categories
        or not all(
            isinstance(category, str) and CATEGORY_RE.fullmatch(category)
            for category in required_categories
        )
        or len(set(required_categories)) != len(required_categories)
    ):
      raise ValidationError(f"plan: {gate_id} has invalid raw-evidence requirements")
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
  if schema.get("$id") != "https://smart-gatekeeper.local/schemas/issue54-evidence-v2.json":
    raise ValidationError("schema: unexpected identity")
  definitions = schema.get("$defs", {})
  required_definitions = {"record", "identity", "execution", "raw_evidence_entry", "approval"}
  if not isinstance(definitions, dict) or not required_definitions.issubset(definitions):
    raise ValidationError("schema: accountable evidence definitions are missing")


def validate_candidate(candidate: Any, completed: bool) -> None:
  if not isinstance(candidate, dict):
    raise ValidationError("evidence: candidate must be an object")
  require_exact_keys(
      candidate,
      {"git_sha", "firmware_artifact_sha256", "mobile_artifact_sha256"},
      "evidence candidate",
  )
  values = (
      candidate["git_sha"],
      candidate["firmware_artifact_sha256"],
      candidate["mobile_artifact_sha256"],
  )
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


def validate_execution(value: Any, gate_id: str) -> tuple[datetime, datetime, str]:
  if not isinstance(value, dict):
    raise ValidationError(f"evidence: {gate_id} executed record requires execution metadata")
  require_exact_keys(value, {"started_at", "ended_at", "executor"}, f"evidence: {gate_id} execution")
  started_at = parse_timestamp(value["started_at"], f"evidence: {gate_id} started_at")
  ended_at = parse_timestamp(value["ended_at"], f"evidence: {gate_id} ended_at")
  if ended_at <= started_at:
    raise ValidationError(f"evidence: {gate_id} ended_at must be after started_at")
  executor_id = validate_identity(value["executor"], f"evidence: {gate_id} executor")
  return started_at, ended_at, executor_id


def validate_raw_evidence(
    value: Any,
    gate: dict[str, Any],
    started_at: datetime,
    ended_at: datetime,
) -> None:
  gate_id = gate["id"]
  if not isinstance(value, list):
    raise ValidationError(f"evidence: {gate_id} raw_evidence must be a list")
  required_categories = set(gate["required_raw_evidence"])
  if not all(isinstance(entry, dict) for entry in value):
    raise ValidationError(f"evidence: {gate_id} raw evidence entries must be structured objects")
  categories = [entry.get("category") for entry in value]
  if (
      not all(isinstance(category, str) for category in categories)
      or len(categories) != len(set(categories))
      or set(categories) != required_categories
  ):
    raise ValidationError(
        f"evidence: {gate_id} raw-evidence categories must exactly match "
        f"{sorted(required_categories)}"
    )
  capture_ids: set[str] = set()
  for entry in value:
    category = entry["category"]
    context = f"evidence: {gate_id} raw_evidence[{category}]"
    require_exact_keys(
        entry,
        {
            "category",
            "immutable_locator",
            "capture_id",
            "captured_at",
            "captured_by",
            "sha256",
        },
        context,
    )
    digest = entry["sha256"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
      raise ValidationError(f"{context}: sha256 is invalid")
    if entry["immutable_locator"] != f"urn:sha256:{digest}":
      raise ValidationError(f"{context}: immutable_locator must be content-addressed by sha256")
    capture_id = entry["capture_id"]
    if (
        not isinstance(capture_id, str)
        or not CAPTURE_ID_RE.fullmatch(capture_id)
        or capture_id in capture_ids
    ):
      raise ValidationError(f"{context}: capture_id is invalid or duplicated")
    capture_ids.add(capture_id)
    captured_at = parse_timestamp(entry["captured_at"], f"{context} captured_at")
    if captured_at < started_at or captured_at > ended_at:
      raise ValidationError(f"{context}: captured_at must fall within the execution window")
    validate_identity(entry["captured_by"], f"{context} captured_by")


def validate_approval(
    value: Any,
    gate: dict[str, Any],
    executor_id: str,
    ended_at: datetime,
    status: str,
) -> None:
  gate_id = gate["id"]
  if not isinstance(value, dict):
    raise ValidationError(f"evidence: {gate_id} executed record requires approval")
  require_exact_keys(
      value,
      {"role", "reviewer", "timestamp", "decision"},
      f"evidence: {gate_id} approval",
  )
  expected_role = gate["required_approval_role"]
  if value["role"] != expected_role:
    raise ValidationError(
        f"evidence: {gate_id} approval role must be {expected_role!r}, got {value['role']!r}"
    )
  reviewer_id = validate_identity(value["reviewer"], f"evidence: {gate_id} reviewer")
  if reviewer_id == executor_id:
    raise ValidationError(f"evidence: {gate_id} reviewer must be independent of executor")
  timestamp = parse_timestamp(value["timestamp"], f"evidence: {gate_id} approval timestamp")
  if timestamp <= ended_at:
    raise ValidationError(f"evidence: {gate_id} approval timestamp must follow execution end")
  expected_decision = STATUS_DECISIONS[status]
  if value["decision"] != expected_decision:
    raise ValidationError(
        f"evidence: {gate_id} {status} record requires {expected_decision!r} approval decision"
    )


def validate_evidence(
    evidence: dict[str, Any], plan_by_id: dict[str, dict[str, Any]], require_pending: bool
) -> None:
  require_exact_keys(
      evidence,
      {"schema_version", "plan_version", "candidate", "records"},
      "evidence",
  )
  if evidence["schema_version"] != "issue54-physical-evidence/v2":
    raise ValidationError("evidence: unexpected schema_version")
  if evidence["plan_version"] != "issue54-physical-gate-plan/v2":
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
        {
            "gate_id",
            "status",
            "pass_condition_id",
            "execution",
            "executed_trials",
            "passed_trials",
            "failed_trials",
            "raw_evidence",
            "approval",
            "notes",
        },
        "evidence record",
    )
    gate_id = record["gate_id"]
    if gate_id not in plan_by_id or gate_id in by_id:
      raise ValidationError(f"evidence: unknown or duplicate gate {gate_id!r}")
    gate = plan_by_id[gate_id]
    status = record["status"]
    if status not in {"not_run", "passed", "failed", "aborted"}:
      raise ValidationError(f"evidence: {gate_id} has invalid status")
    counts = (
        record["executed_trials"],
        record["passed_trials"],
        record["failed_trials"],
    )
    if not all(isinstance(count, int) and count >= 0 for count in counts):
      raise ValidationError(f"evidence: {gate_id} has invalid trial counts")
    if record["passed_trials"] + record["failed_trials"] != record["executed_trials"]:
      raise ValidationError(f"evidence: {gate_id} trial counts do not add up")
    require_nonblank(record["notes"], f"evidence: {gate_id} notes")
    if status == "not_run":
      if (
          any(counts)
          or record["pass_condition_id"] is not None
          or record["execution"] is not None
          or record["raw_evidence"] != []
          or record["approval"] is not None
      ):
        raise ValidationError(f"evidence: {gate_id} not_run record must contain no execution or approval")
    else:
      if record["pass_condition_id"] != gate["pass_condition_id"]:
        raise ValidationError(
            f"evidence: {gate_id} pass_condition_id must bind {gate['pass_condition_id']!r}"
        )
      started_at, ended_at, executor_id = validate_execution(record["execution"], gate_id)
      validate_raw_evidence(record["raw_evidence"], gate, started_at, ended_at)
      validate_approval(record["approval"], gate, executor_id, ended_at, status)
      if status == "passed":
        if record["executed_trials"] < gate["minimum_trials"] or record["failed_trials"] != 0:
          raise ValidationError(
              f"evidence: {gate_id} passed record does not meet its full trial requirement"
          )
      elif status == "failed" and record["failed_trials"] == 0:
        raise ValidationError(f"evidence: {gate_id} failed record must contain a failed trial")
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
    if "requires execution metadata" not in str(exc):
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
