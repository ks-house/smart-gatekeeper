import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_trusted_workflow_policy as trusted  # noqa: E402


def _digest(content: bytes) -> str:
  return trusted.normalized_sha256(content)


class TrustedWorkflowPolicyTest(unittest.TestCase):
  def setUp(self):
    self.main_files = {
        "workflow.yml": b"name: main\r\n",
        "gate.py": b"print('main')\n",
    }
    self.pr_files = {
        "workflow.yml": b"name: approved-pr\n",
        "gate.py": b"print('approved-pr')\n",
    }
    self.policy = {
        "format_version": 1,
        "normalization": trusted.NORMALIZATION,
        "protected_paths": list(self.main_files),
        "approved_bundles": [
            {
                "id": "main",
                "source": {
                    "repository": "owner/repository",
                    "commit": "1" * 40,
                },
                "files": {
                    path: _digest(content)
                    for path, content in self.main_files.items()
                },
            },
            {
                "id": "preapproved-pr",
                "source": {
                    "repository": "owner/repository",
                    "commit": "2" * 40,
                },
                "files": {
                    path: _digest(content)
                    for path, content in self.pr_files.items()
                },
            },
        ],
    }

  def test_exact_main_bundle_is_approved(self):
    bundle = trusted.verify_candidate(self.policy, self.main_files.__getitem__)
    self.assertEqual(bundle["id"], "main")

  def test_exact_preapproved_pr_bundle_is_approved(self):
    bundle = trusted.verify_candidate(self.policy, self.pr_files.__getitem__)
    self.assertEqual(bundle["id"], "preapproved-pr")

  def test_line_endings_are_normalized_but_other_bytes_are_exact(self):
    self.assertEqual(_digest(b"a\r\nb\r"), _digest(b"a\nb\n"))
    self.assertNotEqual(_digest(b"a\nb\n"), _digest(b"a\nb\n "))

  def test_arbitrary_byte_change_is_rejected(self):
    changed = dict(self.main_files)
    changed["gate.py"] += b"# attacker\n"
    with self.assertRaisesRegex(trusted.PolicyError, "gate.py"):
      trusted.verify_candidate(self.policy, changed.__getitem__)

  def test_mixed_approved_bundles_are_rejected(self):
    mixed = {
        "workflow.yml": self.main_files["workflow.yml"],
        "gate.py": self.pr_files["gate.py"],
    }
    with self.assertRaisesRegex(trusted.PolicyError, "mix approved bundles"):
      trusted.verify_candidate(self.policy, mixed.__getitem__)

  def test_missing_protected_file_is_rejected(self):
    with self.assertRaises(KeyError):
      trusted.verify_candidate(self.policy, {"workflow.yml": b"x"}.__getitem__)

  def test_pr_side_policy_and_validator_changes_cannot_change_decision(self):
    candidate_tree = dict(self.main_files)
    policy_path = ".github/workflow-policy/trusted_workflow_policy.json"
    validator_path = "scripts/verify_trusted_workflow_policy.py"
    candidate_tree[policy_path] = json.dumps(
        {"approved_bundles": [{"files": {"gate.py": "0" * 64}}]}
    ).encode()
    candidate_tree[validator_path] = (
        b"def verify_candidate(*_): return 'candidate-approved'\n"
    )
    requested_paths = []

    def fetch(path):
      requested_paths.append(path)
      return candidate_tree[path]

    bundle = trusted.verify_candidate(copy.deepcopy(self.policy), fetch)
    self.assertEqual(bundle["id"], "main")
    self.assertEqual(requested_paths, self.policy["protected_paths"])
    self.assertNotIn(policy_path, requested_paths)
    self.assertNotIn(validator_path, requested_paths)

  def test_pr_side_policy_cannot_bless_a_modified_protected_file(self):
    candidate_tree = dict(self.main_files)
    candidate_tree["gate.py"] += b"# attacker\n"
    candidate_tree[".github/workflow-policy/trusted_workflow_policy.json"] = (
        json.dumps(
            {
                "approved_bundles": [
                    {"files": {"gate.py": _digest(candidate_tree["gate.py"])}}
                ]
            }
        ).encode()
    )
    candidate_tree["scripts/verify_trusted_workflow_policy.py"] = (
        b"def verify_candidate(*_): return 'candidate-approved'\n"
    )
    with self.assertRaisesRegex(trusted.PolicyError, "gate.py"):
      trusted.verify_candidate(copy.deepcopy(self.policy), candidate_tree.__getitem__)

  def test_policy_requires_exact_file_set_for_every_bundle(self):
    policy = copy.deepcopy(self.policy)
    del policy["approved_bundles"][0]["files"]["gate.py"]
    with self.assertRaisesRegex(trusted.PolicyError, "protected_paths exactly"):
      trusted.validate_policy(policy)

  def test_policy_rejects_unknown_fields(self):
    policy = copy.deepcopy(self.policy)
    policy["allow_candidate_policy_override"] = True
    with self.assertRaisesRegex(trusted.PolicyError, "keys must be exactly"):
      trusted.validate_policy(policy)

  def test_current_checkout_matches_an_approved_bundle(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    current = {
        path: (ROOT / path).read_bytes() for path in policy["protected_paths"]
    }
    bundle = trusted.verify_candidate(policy, current.__getitem__)
    self.assertIn(bundle["id"], {"origin-main-bootstrap", "pr-28-preapproved"})

  def test_every_real_protected_path_rejects_single_byte_mutation(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    original = {
        path: (ROOT / path).read_bytes()
        for path in policy["protected_paths"]
    }
    for changed_path in policy["protected_paths"]:
      with self.subTest(path=changed_path):
        candidate = dict(original)
        candidate[changed_path] += b"X"
        with self.assertRaises(trusted.PolicyError):
          trusted.verify_candidate(policy, candidate.__getitem__)


if __name__ == "__main__":
  unittest.main()
