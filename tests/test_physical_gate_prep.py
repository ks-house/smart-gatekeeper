"""Host-only regression tests for Issue #54 pending-only artifacts."""

from __future__ import annotations

import copy
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_physical_gate_prep.py"
sys.path.insert(0, str(ROOT / "scripts"))
import validate_physical_gate_prep as validator  # noqa: E402


class PhysicalGatePrepTest(unittest.TestCase):

  @classmethod
  def setUpClass(cls) -> None:
    cls.plan = validator.validate_plan(validator.load_json(validator.DEFAULT_PLAN))

  def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
    )

  def make_valid_synthetic_pass(self, gate_id: str = "SAMSUNG-WAKE-100") -> dict[str, Any]:
    evidence = copy.deepcopy(validator.load_json(validator.DEFAULT_TEMPLATE))
    evidence["candidate"] = {
        "git_sha": "a" * 40,
        "firmware_artifact_sha256": "b" * 64,
        "mobile_artifact_sha256": "c" * 64,
    }
    gate = self.plan[gate_id]
    record = next(item for item in evidence["records"] if item["gate_id"] == gate_id)
    record.update(
        {
            "status": "passed",
            "pass_condition_id": gate["pass_condition_id"],
            "execution": {
                "started_at": "2026-08-09T00:00:00Z",
                "ended_at": "2026-08-09T01:00:00Z",
                "executor": {
                    "name": "Synthetic Executor",
                    "identity_id": "test:executor",
                },
            },
            "executed_trials": gate["minimum_trials"],
            "passed_trials": gate["minimum_trials"],
            "failed_trials": 0,
            "raw_evidence": [
                {
                    "category": category,
                    "immutable_locator": f"urn:sha256:{index:064x}",
                    "capture_id": f"synthetic-{index}-{category}",
                    "captured_at": "2026-08-09T00:30:00Z",
                    "captured_by": {
                        "name": "Synthetic Executor",
                        "identity_id": "test:executor",
                    },
                    "sha256": f"{index:064x}",
                }
                for index, category in enumerate(gate["required_raw_evidence"], start=1)
            ],
            "approval": {
                "role": gate["required_approval_role"],
                "reviewer": {
                    "name": "Synthetic Independent Reviewer",
                    "identity_id": "test:reviewer",
                },
                "timestamp": "2026-08-09T01:01:00Z",
                "decision": "approved",
            },
            "notes": "Synthetic in-memory contract test; not physical evidence.",
        }
    )
    return evidence

  def assert_mutation_rejected(
      self,
      mutation: Callable[[dict[str, Any]], None],
      expected: str,
  ) -> None:
    evidence = self.make_valid_synthetic_pass()
    mutation(evidence)
    with self.assertRaisesRegex(validator.ValidationError, expected):
      validator.validate_evidence(evidence, self.plan, require_pending=False)

  @staticmethod
  def executed_record(evidence: dict[str, Any]) -> dict[str, Any]:
    return evidence["records"][0]

  def test_pending_template_is_valid(self) -> None:
    result = self.run_validator("--require-pending")
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("PASS", result.stdout)

  def test_forged_pass_fixture_is_rejected(self) -> None:
    result = self.run_validator("--self-test")
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("forged-pass rejection", result.stdout)

  def test_complete_accountable_synthetic_contract_is_valid(self) -> None:
    validator.validate_evidence(
        self.make_valid_synthetic_pass(), self.plan, require_pending=False
    )

  def test_missing_execution_times_and_actor_are_rejected(self) -> None:
    mutations = {
        "started_at": lambda evidence: self.executed_record(evidence)["execution"].pop(
            "started_at"
        ),
        "ended_at": lambda evidence: self.executed_record(evidence)["execution"].pop(
            "ended_at"
        ),
        "executor": lambda evidence: self.executed_record(evidence)["execution"].pop(
            "executor"
        ),
    }
    for field, mutation in mutations.items():
      with self.subTest(field=field):
        self.assert_mutation_rejected(mutation, "execution: keys must")

  def test_missing_reviewer_and_nonindependent_reviewer_are_rejected(self) -> None:
    self.assert_mutation_rejected(
        lambda evidence: self.executed_record(evidence)["approval"].pop("reviewer"),
        "approval: keys must",
    )
    self.assert_mutation_rejected(
        lambda evidence: self.executed_record(evidence)["approval"].update(
            {
                "reviewer": {
                    "name": "Synthetic Executor",
                    "identity_id": "test:executor",
                }
            }
        ),
        "reviewer must be independent",
    )

  def test_generic_and_incomplete_evidence_categories_are_rejected(self) -> None:
    self.assert_mutation_rejected(
        lambda evidence: self.executed_record(evidence)["raw_evidence"][0].update(
            {"category": "generic-evidence"}
        ),
        "raw-evidence categories must exactly match",
    )
    self.assert_mutation_rejected(
        lambda evidence: self.executed_record(evidence)["raw_evidence"].pop(),
        "raw-evidence categories must exactly match",
    )

  def test_raw_evidence_requires_immutable_capture_identity_and_digest(self) -> None:
    mutations = {
        "capture_id": lambda evidence: self.executed_record(evidence)["raw_evidence"][
            0
        ].pop("capture_id"),
        "digest": lambda evidence: self.executed_record(evidence)["raw_evidence"][0].update(
            {"sha256": "f" * 64}
        ),
        "captured_by": lambda evidence: self.executed_record(evidence)["raw_evidence"][
            0
        ].pop("captured_by"),
    }
    expected = {
        "capture_id": "keys must",
        "digest": "immutable_locator must be content-addressed",
        "captured_by": "keys must",
    }
    for field, mutation in mutations.items():
      with self.subTest(field=field):
        self.assert_mutation_rejected(mutation, expected[field])

  def test_empty_and_wrong_role_approval_are_rejected(self) -> None:
    self.assert_mutation_rejected(
        lambda evidence: self.executed_record(evidence).update({"approval": {}}),
        "approval: keys must",
    )
    self.assert_mutation_rejected(
        lambda evidence: self.executed_record(evidence)["approval"].update(
            {"role": "risk_owner"}
        ),
        "approval role must be",
    )

  def test_approval_timestamp_and_pass_condition_binding_are_required(self) -> None:
    self.assert_mutation_rejected(
        lambda evidence: self.executed_record(evidence)["approval"].pop("timestamp"),
        "approval: keys must",
    )
    self.assert_mutation_rejected(
        lambda evidence: self.executed_record(evidence).update(
            {"pass_condition_id": "PC-GENERIC-V1"}
        ),
        "pass_condition_id must bind",
    )


if __name__ == "__main__":
  unittest.main()
