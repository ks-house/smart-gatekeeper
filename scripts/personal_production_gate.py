#!/usr/bin/env python3
"""Validate the reduced, single-owner personal-production evidence profile."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

EXPECTED_PROFILE = "personal-single-installation-v1"
REQUIRED_CHECKS = {
    "screen_off_access": 3,
    "activity_terminated_access": 3,
    "target_reboot_recovery": 1,
    "network_reconnect": 1,
    "relay_boot_fail_safe": 1,
    "ota_previous_version_recovery": 1,
}
REQUIRED_SAFEGUARDS = {
    "exact_main_commit",
    "signed_manifest_and_artifact",
    "post_deploy_version_boot_health_check",
}

class PersonalGateError(RuntimeError):
  pass

def load_evidence(path: Path) -> dict:
  with path.open(encoding="utf-8") as handle:
    value = json.load(handle)
  if not isinstance(value, dict):
    raise PersonalGateError("evidence must be a JSON object")
  return value

def validate(evidence: dict) -> None:
  if evidence.get("profile") != EXPECTED_PROFILE:
    raise PersonalGateError("unexpected personal-production profile")
  if evidence.get("commercial_scope") is not False:
    raise PersonalGateError("personal profile cannot authorize commercial deployment")
  installation = evidence.get("installation", {})
  if installation.get("current_installation_is_canary") is not True:
    raise PersonalGateError("the installed owner system must be the declared canary")
  if installation.get("legacy_access_path_retained") is not True:
    raise PersonalGateError("personal release must retain the currently validated legacy access path")
  if installation.get("hardwareless_rc_enabled") is not False:
    raise PersonalGateError("hardwareless RC must remain disabled for this personal profile")
  checks = evidence.get("checks", {})
  for name, minimum in REQUIRED_CHECKS.items():
    check = checks.get(name)
    if not isinstance(check, dict):
      raise PersonalGateError(f"missing check: {name}")
    if check.get("required_trials") != minimum:
      raise PersonalGateError(f"{name}: required_trials must be exactly {minimum}")
    passed = check.get("passed_trials")
    if not isinstance(passed, int) or isinstance(passed, bool) or passed < minimum:
      raise PersonalGateError(f"{name}: requires at least {minimum} observed passes")
  safeguards = evidence.get("required_safeguards", {})
  missing = sorted(name for name in REQUIRED_SAFEGUARDS if safeguards.get(name) is not True)
  if missing:
    raise PersonalGateError(f"required safeguards not confirmed: {missing}")
  if evidence.get("release_blocked") is not False:
    raise PersonalGateError("release_blocked must remain true until every reduced check is complete")
  if not evidence.get("approved_by"):
    raise PersonalGateError("owner approval identity is required")
  approved_at = evidence.get("approved_at")
  if not isinstance(approved_at, str) or not approved_at:
    raise PersonalGateError("dated owner approval is required")
  try:
    parsed = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
  except ValueError as exc:
    raise PersonalGateError("approved_at must be ISO-8601") from exc
  if parsed.tzinfo is None:
    raise PersonalGateError("approved_at must include a timezone")

def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--evidence", type=Path, required=True)
  args = parser.parse_args()
  try:
    validate(load_evidence(args.evidence))
  except (OSError, json.JSONDecodeError, PersonalGateError) as exc:
    print(f"[PERSONAL-PROD] FAIL: {exc}", file=sys.stderr)
    return 1
  print("[PERSONAL-PROD] PASS: reduced owner-device release evidence is complete")
  return 0

if __name__ == "__main__":
  raise SystemExit(main())
