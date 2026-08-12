import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("personal_production_gate", ROOT / "scripts" / "personal_production_gate.py")
gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gate)

def passing_evidence():
  return {
      "profile": "personal-single-installation-v1",
      "release_blocked": False,
      "commercial_scope": False,
      "approved_by": "repository-owner",
      "approved_at": "2026-08-12T12:00:00+09:00",
      "installation": {"current_installation_is_canary": True, "legacy_access_path_retained": True, "hardwareless_rc_enabled": False},
      "checks": {name: {"required_trials": minimum, "passed_trials": minimum} for name, minimum in gate.REQUIRED_CHECKS.items()},
      "required_safeguards": {name: True for name in gate.REQUIRED_SAFEGUARDS},
  }

class PersonalProductionGateTest(unittest.TestCase):
  def test_reduced_owner_profile_passes(self):
    gate.validate(passing_evidence())

  def test_template_remains_blocked(self):
    evidence = gate.load_evidence(ROOT / "ota" / "personal-release-evidence.template.json")
    with self.assertRaises(gate.PersonalGateError):
      gate.validate(evidence)

  def test_cannot_enable_unvalidated_hardwareless_path(self):
    evidence = passing_evidence()
    evidence["installation"]["hardwareless_rc_enabled"] = True
    with self.assertRaisesRegex(gate.PersonalGateError, "hardwareless RC"):
      gate.validate(evidence)

  def test_each_physical_minimum_is_enforced(self):
    for name, minimum in gate.REQUIRED_CHECKS.items():
      with self.subTest(name=name):
        evidence = copy.deepcopy(passing_evidence())
        evidence["checks"][name]["passed_trials"] = minimum - 1
        with self.assertRaisesRegex(gate.PersonalGateError, name):
          gate.validate(evidence)

  def test_commercial_scope_is_never_authorized(self):
    evidence = passing_evidence()
    evidence["commercial_scope"] = True
    with self.assertRaisesRegex(gate.PersonalGateError, "commercial"):
      gate.validate(evidence)

if __name__ == "__main__":
  unittest.main()
