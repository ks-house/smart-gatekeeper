import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_trusted_workflow_policy as trusted  # noqa: E402


CURRENT_MAIN_COMMIT = "cc977e42770e6d88822459436a770295632c6e45"
CURRENT_MAIN_DIGESTS = {
    ".github/workflows/deploy.yml": (
        "9bdf5a593907fa8225ebec54b9d305177836b9ace8376bced3914800c3ad5820"
    ),
    ".github/workflows/build_app.yml": (
        "7816856a7ec1f465d016d54e8d50773f9f9e8b9f9b14a81a353852b6f5ab6494"
    ),
    ".github/workflows/ota_contract.yml": (
        "8e2c1479a64336d172a0f13b50a52fcef122e955a56d8866e58a73281ee0c001"
    ),
    "scripts/ota_contract_gate.py": (
        "064c8848d914949383981376ab7ad4f23699b4b118a394793ad66cac9954a66f"
    ),
    "ota/requirements.txt": (
        "d2dc1631f87992338c4779d89db7ac6c049abd79ce14de9e6e8e1b113f7f2ca4"
    ),
}
RETIRED_BUNDLES = {
    "origin-main-bootstrap": "8c36ead9f40e46959af721bbfffaeb00fcb2b2c1",
    "pr-28-preapproved": "7bae62f6921ece5aabb08e994f7527391b7db746",
}
RETIRED_ORIGIN_MAIN_DIGESTS = {
    ".github/workflows/deploy.yml": (
        "d899c4c48412477d5496ac120fe2a9025662fe33763e5b4ab302e8374ffa64ad"
    ),
    ".github/workflows/build_app.yml": (
        "0e3876199ef47652e4d8e9931cd29f5f5ab19bc8aa26249180ef96adb0c12ca4"
    ),
    ".github/workflows/ota_contract.yml": (
        "8e2c1479a64336d172a0f13b50a52fcef122e955a56d8866e58a73281ee0c001"
    ),
    "scripts/ota_contract_gate.py": (
        "82edf10415a653b6ad64c7dd1be29e7eefe2e3df406fdbf73455fb5bbd245f66"
    ),
    "ota/requirements.txt": (
        "ec9f21f0bffe9f3e4d6682cf164f15ae21d2cd5e2994beaaa53281da5f04a6d2"
    ),
}


def _digest(content: bytes) -> str:
  return trusted.normalized_sha256(content)


class TrustedWorkflowPolicyTest(unittest.TestCase):
  def setUp(self):
    self.main_files = {
        "workflow.yml": b"name: main\r\n",
        "gate.py": b"print('main')\n",
    }
    self.alternate_files = {
        "workflow.yml": b"name: alternate\n",
        "gate.py": b"print('alternate')\n",
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
                "id": "alternate",
                "source": {
                    "repository": "owner/repository",
                    "commit": "2" * 40,
                },
                "files": {
                    path: _digest(content)
                    for path, content in self.alternate_files.items()
                },
            },
        ],
    }

  def test_exact_main_bundle_is_approved(self):
    bundle = trusted.verify_candidate(self.policy, self.main_files.__getitem__)
    self.assertEqual(bundle["id"], "main")

  def test_exact_alternate_bundle_is_approved(self):
    bundle = trusted.verify_candidate(self.policy, self.alternate_files.__getitem__)
    self.assertEqual(bundle["id"], "alternate")

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
        "gate.py": self.alternate_files["gate.py"],
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
    self.assertEqual(bundle["id"], "current-main-baseline")

  def test_rotated_policy_has_only_current_main_baseline(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    self.assertEqual(len(policy["approved_bundles"]), 1)
    bundle = policy["approved_bundles"][0]
    self.assertEqual(bundle["id"], "current-main-baseline")
    self.assertEqual(
        bundle["source"],
        {
            "repository": "ks-house/smart-gatekeeper",
            "commit": CURRENT_MAIN_COMMIT,
        },
    )
    self.assertEqual(bundle["files"], CURRENT_MAIN_DIGESTS)
    self.assertNotEqual(bundle["files"], RETIRED_ORIGIN_MAIN_DIGESTS)
    self.assertTrue(RETIRED_BUNDLES.keys().isdisjoint({bundle["id"]}))
    self.assertTrue(
        set(RETIRED_BUNDLES.values()).isdisjoint({bundle["source"]["commit"]})
    )

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


class TrustedWorkflowStructureTest(unittest.TestCase):
  def setUp(self):
    self.workflow_path = ROOT / ".github/workflows/trusted_workflow_policy.yml"
    self.workflow_text = self.workflow_path.read_text(encoding="utf-8")
    self.workflow_data = yaml.safe_load(self.workflow_text)

  def test_no_paths_or_paths_ignore_suppression(self):
    on_block = self.workflow_data.get("on") or self.workflow_data.get(True)
    self.assertIsNotNone(on_block, "Workflow must have an 'on' trigger block")
    pr_target = on_block.get("pull_request_target")
    self.assertIsNotNone(pr_target, "Workflow must trigger on pull_request_target")
    self.assertNotIn(
        "paths", pr_target, "pull_request_target must not have a paths filter"
    )
    self.assertNotIn(
        "paths-ignore",
        pr_target,
        "pull_request_target must not have a paths-ignore filter",
    )
    self.assertNotIn("paths", on_block, "on block must not have a paths filter")
    self.assertNotIn(
        "paths-ignore", on_block, "on block must not have a paths-ignore filter"
    )
    self.assertEqual(pr_target.get("branches"), ["main"])
    self.assertEqual(
        sorted(pr_target.get("types", [])),
        ["opened", "reopened", "synchronize"],
    )

  def test_trust_boundary_guards_and_permissions(self):
    self.assertEqual(
        self.workflow_data.get("permissions"), {"contents": "read"}
    )
    jobs = self.workflow_data.get("jobs", {})
    verify_job = jobs.get("verify", {})
    self.assertEqual(
        verify_job.get("name"),
        "Verify protected files against trusted base policy",
    )

    job_if = verify_job.get("if", "")
    self.assertIn(
        "github.event.pull_request.base.repo.full_name == github.repository",
        job_if,
    )
    self.assertIn(
        "github.event.pull_request.base.ref =="
        " github.event.repository.default_branch",
        job_if,
    )

    steps = verify_job.get("steps", [])
    self.assertGreaterEqual(len(steps), 2)

    checkout_step = steps[0]
    self.assertEqual(
        checkout_step.get("with", {}).get("ref"),
        "${{ github.event.pull_request.base.sha }}",
    )
    self.assertFalse(checkout_step.get("with", {}).get("persist-credentials"))

    verify_step = steps[1]
    env = verify_step.get("env", {})
    self.assertEqual(
        env.get("CANDIDATE_REPOSITORY"),
        "${{ github.event.pull_request.head.repo.full_name }}",
    )
    self.assertEqual(
        env.get("CANDIDATE_SHA"),
        "${{ github.event.pull_request.head.sha }}",
    )


if __name__ == "__main__":
  unittest.main()
