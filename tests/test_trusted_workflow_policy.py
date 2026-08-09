import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
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
TEMPORARY_PR59_COMMIT = "e468e0f0a77e5e9b5e1a5ac7c4cdf22c4de951ad"
TEMPORARY_PR59_DIGESTS = {
    ".github/workflows/deploy.yml": (
        "4bf77e4c48b0033aedb0c0b4a45565d9a090538b3a8b2c8eacfc73de349903f7"
    ),
    ".github/workflows/build_app.yml": (
        "f3f66873ba5e207ae2c966e7928ce521af009e9d110f2d2e7967037b4541b077"
    ),
    ".github/workflows/ota_contract.yml": (
        "8e2c1479a64336d172a0f13b50a52fcef122e955a56d8866e58a73281ee0c001"
    ),
    "scripts/ota_contract_gate.py": (
        "751e18ce79f17ec7d0280c31ac6fff314aa3d244af56cf25b410f1db8263fea7"
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


def validate_trusted_workflow_structure(
    workflow_data: Any, raw_text: str | None = None
) -> None:
  if raw_text is not None:
    for index, char in enumerate(raw_text):
      code = ord(char)
      if (code < 32 and code not in (10, 13)) or code == 127:
        raise ValueError(
            f"Raw workflow text contains invalid C0 control character 0x{code:02x} at offset {index}"
        )

  if not isinstance(workflow_data, dict):
    raise ValueError("Workflow data must be a dictionary")

  # 1. Strict key type checking (reject boolean keys / YAML key collisions)
  def _check_keys_strict_strings(obj: Any, path: str = "root") -> None:
    if isinstance(obj, dict):
      for key, val in obj.items():
        if not isinstance(key, str):
          raise ValueError(
              f"YAML key collision / non-string key detected at {path}: key {key!r} (type {type(key).__name__}) is not a string"
          )
        _check_keys_strict_strings(val, f"{path}.{key}")
    elif isinstance(obj, list):
      for idx, item in enumerate(obj):
        _check_keys_strict_strings(item, f"{path}[{idx}]")

  _check_keys_strict_strings(workflow_data)

  expected_top_keys = {"name", "on", "permissions", "jobs"}
  actual_top_keys = set(workflow_data.keys())
  if actual_top_keys != expected_top_keys:
    raise ValueError(
        f"Top-level keys must be exactly {sorted(expected_top_keys)}; got {sorted(actual_top_keys)}"
    )

  if workflow_data.get("name") != "Trusted Workflow Policy":
    raise ValueError("Workflow name mismatch")

  # 2. Permissions check
  if workflow_data.get("permissions") != {"contents": "read"}:
    raise ValueError("Permissions must be exactly {'contents': 'read'}")

  # 3. Trigger ('on') block check
  on_block = workflow_data.get("on")
  if not isinstance(on_block, dict):
    raise ValueError("'on' block must be a dictionary")
  if set(on_block.keys()) != {"pull_request_target"}:
    raise ValueError("'on' block keys must be exactly {'pull_request_target'}")

  pr_target = on_block.get("pull_request_target")
  if not isinstance(pr_target, dict):
    raise ValueError("'pull_request_target' must be a dictionary")
  if set(pr_target.keys()) != {"branches", "types"}:
    raise ValueError(
        "'pull_request_target' keys must be exactly {'branches', 'types'} (no paths or paths-ignore)"
    )

  if pr_target.get("branches") != ["main"]:
    raise ValueError("pull_request_target branches must be ['main']")
  if pr_target.get("types") != ["opened", "synchronize", "reopened"]:
    raise ValueError("pull_request_target types mismatch")

  if (
      "paths" in pr_target
      or "paths-ignore" in pr_target
      or "paths" in on_block
      or "paths-ignore" in on_block
  ):
    raise ValueError(
        "pull_request_target must not contain paths or paths-ignore filters"
    )

  # 4. Jobs check
  jobs = workflow_data.get("jobs")
  if not isinstance(jobs, dict) or set(jobs.keys()) != {"verify"}:
    raise ValueError("jobs block must contain exactly one job named 'verify'")

  verify_job = jobs.get("verify")
  if not isinstance(verify_job, dict):
    raise ValueError("'verify' job must be a dictionary")

  expected_verify_keys = {"name", "if", "runs-on", "steps"}
  if set(verify_job.keys()) != expected_verify_keys:
    raise ValueError(
        f"'verify' job keys must be exactly {sorted(expected_verify_keys)}; got {sorted(verify_job.keys())}"
    )

  if (
      verify_job.get("name")
      != "Verify protected files against trusted base policy"
  ):
    raise ValueError("Job name mismatch")

  expected_if = (
      "github.event.pull_request.base.repo.full_name == github.repository && "
      "github.event.pull_request.base.ref =="
      " github.event.repository.default_branch"
  )
  if verify_job.get("if") != expected_if:
    raise ValueError("Job 'if' condition mismatch")

  if verify_job.get("runs-on") != "ubuntu-latest":
    raise ValueError("Job 'runs-on' must be 'ubuntu-latest'")

  steps = verify_job.get("steps")
  if not isinstance(steps, list) or len(steps) != 2:
    raise ValueError(
        f"Job steps must be exactly 2 ordered steps; got {len(steps) if isinstance(steps, list) else type(steps)}"
    )

  step1, step2 = steps[0], steps[1]
  if not isinstance(step1, dict) or not isinstance(step2, dict):
    raise ValueError("Steps must be dictionaries")

  # Step 1 (Checkout) check
  if set(step1.keys()) != {"name", "uses", "with"}:
    raise ValueError(
        f"Step 1 keys must be exactly {{'name', 'uses', 'with'}}; got {set(step1.keys())}"
    )
  if step1.get("name") != "Checkout trusted policy from the PR base SHA":
    raise ValueError("Step 1 name mismatch")

  expected_uses = "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
  if step1.get("uses") != expected_uses:
    raise ValueError(f"Step 1 uses must be pinned action SHA {expected_uses!r}")

  with1 = step1.get("with")
  if not isinstance(with1, dict):
    raise ValueError("Step 1 'with' block must be a dictionary")

  expected_with1_keys = {
      "ref",
      "persist-credentials",
      "sparse-checkout",
      "sparse-checkout-cone-mode",
  }
  if set(with1.keys()) != expected_with1_keys:
    raise ValueError(
        f"Step 1 'with' keys must be exactly {sorted(expected_with1_keys)}; got {sorted(with1.keys())}"
    )

  if with1.get("ref") != "${{ github.event.pull_request.base.sha }}":
    raise ValueError(
        "Step 1 ref must be exact base SHA"
        " '${{ github.event.pull_request.base.sha }}'"
    )
  if with1.get("persist-credentials") is not False:
    raise ValueError("Step 1 persist-credentials must be False")
  if with1.get("sparse-checkout-cone-mode") is not False:
    raise ValueError("Step 1 sparse-checkout-cone-mode must be False")

  sparse_raw = str(with1.get("sparse-checkout", ""))
  sparse_lines = [
      line.strip() for line in sparse_raw.strip().splitlines() if line.strip()
  ]
  expected_sparse = [
      ".github/workflow-policy/trusted_workflow_policy.json",
      "scripts/verify_trusted_workflow_policy.py",
  ]
  if sparse_lines != expected_sparse:
    raise ValueError(
        f"Step 1 sparse-checkout paths must be exactly {expected_sparse}; got {sparse_lines}"
    )

  # Step 2 (Verifier) check
  if set(step2.keys()) != {"name", "env", "run"}:
    raise ValueError(
        f"Step 2 keys must be exactly {{'name', 'env', 'run'}}; got {set(step2.keys())}"
    )
  if step2.get("name") != "Verify candidate files as inert GitHub API bytes":
    raise ValueError("Step 2 name mismatch")

  env2 = step2.get("env")
  if not isinstance(env2, dict):
    raise ValueError("Step 2 'env' block must be a dictionary")

  expected_env_keys = {
      "GITHUB_TOKEN",
      "GITHUB_API_URL",
      "CANDIDATE_REPOSITORY",
      "CANDIDATE_SHA",
  }
  if set(env2.keys()) != expected_env_keys:
    raise ValueError(
        f"Step 2 env keys must be exactly {sorted(expected_env_keys)}; got {sorted(env2.keys())}"
    )

  if env2.get("GITHUB_TOKEN") != "${{ github.token }}":
    raise ValueError("Step 2 GITHUB_TOKEN mismatch")
  if env2.get("GITHUB_API_URL") != "${{ github.api_url }}":
    raise ValueError("Step 2 GITHUB_API_URL mismatch")
  if (
      env2.get("CANDIDATE_REPOSITORY")
      != "${{ github.event.pull_request.head.repo.full_name }}"
  ):
    raise ValueError("Step 2 CANDIDATE_REPOSITORY mismatch")
  if env2.get("CANDIDATE_SHA") != "${{ github.event.pull_request.head.sha }}":
    raise ValueError("Step 2 CANDIDATE_SHA mismatch")

  # --- EXACT NON-LOSSY PARSED RUN VALIDATION WITH CR/LF/TAB/SPACE REJECTION ---
  run_cmd = step2.get("run")
  if not isinstance(run_cmd, str):
    raise ValueError("Step 2 run must be a string")

  if "\r" in run_cmd:
    raise ValueError("Step 2 run command contains bare CR or CRLF newline")
  if "\n" in run_cmd:
    raise ValueError("Step 2 run command contains LF newline")
  if "\t" in run_cmd:
    raise ValueError("Step 2 run command contains tab character")
  if "  " in run_cmd:
    raise ValueError("Step 2 run command contains multiple consecutive spaces")
  if "${{" in run_cmd or "github.event.pull_request" in run_cmd:
    raise ValueError(
        "Step 2 run command contains unquoted expression or PR-title execution"
    )

  expected_run_cmd = (
      "python scripts/verify_trusted_workflow_policy.py "
      "--policy .github/workflow-policy/trusted_workflow_policy.json "
      '--candidate-repository "$CANDIDATE_REPOSITORY" '
      '--candidate-ref "$CANDIDATE_SHA" '
      '--api-url "$GITHUB_API_URL"'
  )
  if run_cmd != expected_run_cmd:
    raise ValueError(
        f"Step 2 run command mismatch: expected {expected_run_cmd!r}, got {run_cmd!r}"
    )


class TrustedWorkflowPolicyTest(unittest.TestCase):
  def assert_current_main_baseline_is_exact(self, policy):
    bundles_by_id = {
        bundle["id"]: bundle for bundle in policy["approved_bundles"]
    }
    self.assertIn("current-main-baseline", bundles_by_id)
    baseline = bundles_by_id["current-main-baseline"]
    self.assertEqual(
        baseline["source"],
        {
            "repository": "ks-house/smart-gatekeeper",
            "commit": CURRENT_MAIN_COMMIT,
        },
    )
    self.assertEqual(baseline["files"], CURRENT_MAIN_DIGESTS)
    self.assertEqual(list(baseline["files"]), policy["protected_paths"])

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
    self.assertIn(
        bundle["id"],
        {approved["id"] for approved in policy["approved_bundles"]},
    )
    self.assertEqual(list(bundle["files"]), policy["protected_paths"])
    self.assertEqual(
        bundle["files"],
        {path: _digest(current[path]) for path in policy["protected_paths"]},
    )

  def test_temporary_policy_has_current_main_and_exact_pr59_bundle(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    self.assertEqual(policy["protected_paths"], list(CURRENT_MAIN_DIGESTS))
    self.assertEqual(len(policy["approved_bundles"]), 2)
    main_bundle, temporary_bundle = policy["approved_bundles"]
    self.assert_current_main_baseline_is_exact(policy)
    self.assertEqual(main_bundle["id"], "current-main-baseline")
    self.assertEqual(
        main_bundle["source"],
        {
            "repository": "ks-house/smart-gatekeeper",
            "commit": CURRENT_MAIN_COMMIT,
        },
    )
    self.assertEqual(main_bundle["files"], CURRENT_MAIN_DIGESTS)
    self.assertNotEqual(main_bundle["files"], RETIRED_ORIGIN_MAIN_DIGESTS)
    self.assertEqual(temporary_bundle["id"], "temporary-pr59-e468e0f")
    self.assertEqual(
        temporary_bundle["source"],
        {
            "repository": "ks-house/smart-gatekeeper",
            "commit": TEMPORARY_PR59_COMMIT,
        },
    )
    self.assertEqual(temporary_bundle["files"], TEMPORARY_PR59_DIGESTS)
    self.assertTrue(
        RETIRED_BUNDLES.keys().isdisjoint(
            {main_bundle["id"], temporary_bundle["id"]}
        )
    )
    self.assertTrue(
        set(RETIRED_BUNDLES.values()).isdisjoint(
            {main_bundle["source"]["commit"], temporary_bundle["source"]["commit"]}
        )
    )

  def test_current_main_baseline_source_mismatches_are_rejected(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    self.assert_current_main_baseline_is_exact(policy)

    for field, value in (
        ("repository", "attacker/fork"),
        ("commit", "f" * 40),
    ):
      with self.subTest(field=field):
        mutated = copy.deepcopy(policy)
        mutated["approved_bundles"][0]["source"][field] = value
        trusted.validate_policy(mutated)
        with self.assertRaises(AssertionError):
          self.assert_current_main_baseline_is_exact(mutated)

  def test_temporary_pr59_bundle_is_exact_and_adversarial_variants_fail(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )

    def verify_digest_map(digests):
      with mock.patch.object(
          trusted,
          "normalized_sha256",
          side_effect=lambda content: content.decode("ascii"),
      ):
        return trusted.verify_candidate(
            policy, lambda path: digests[path].encode("ascii")
        )

    bundle = verify_digest_map(TEMPORARY_PR59_DIGESTS)
    self.assertEqual(bundle["id"], "temporary-pr59-e468e0f")

    reordered = dict(TEMPORARY_PR59_DIGESTS)
    deploy_path = ".github/workflows/deploy.yml"
    build_path = ".github/workflows/build_app.yml"
    reordered[deploy_path], reordered[build_path] = (
        reordered[build_path],
        reordered[deploy_path],
    )
    with self.assertRaises(trusted.PolicyError):
      verify_digest_map(reordered)

    mixed = dict(CURRENT_MAIN_DIGESTS)
    mixed[build_path] = TEMPORARY_PR59_DIGESTS[build_path]
    mixed["scripts/ota_contract_gate.py"] = TEMPORARY_PR59_DIGESTS[
        "scripts/ota_contract_gate.py"
    ]
    with self.assertRaisesRegex(trusted.PolicyError, "mix approved bundles"):
      verify_digest_map(mixed)

    missing = copy.deepcopy(policy)
    del missing["approved_bundles"][1]["files"][deploy_path]
    with self.assertRaisesRegex(trusted.PolicyError, "protected_paths exactly"):
      trusted.validate_policy(missing)

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

  def test_current_workflow_matches_strict_policy(self):
    validate_trusted_workflow_structure(self.workflow_data, self.workflow_text)

  def test_no_paths_or_paths_ignore_suppression(self):
    on_block = self.workflow_data.get("on")
    self.assertIsNotNone(on_block, "Workflow must have an 'on' trigger block")
    pr_target = on_block.get("pull_request_target")
    self.assertIsNotNone(
        pr_target, "Workflow must trigger on pull_request_target"
    )
    self.assertNotIn(
        "paths", pr_target, "pull_request_target must not have a paths filter"
    )
    self.assertNotIn(
        "paths-ignore",
        pr_target,
        "pull_request_target must not have a paths-ignore filter",
    )

  def test_rejects_lf_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python scripts/verify_trusted_workflow_policy.py\n--policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "LF newline"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_crlf_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python scripts/verify_trusted_workflow_policy.py\r\n--policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "bare CR or CRLF"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_bare_cr_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python scripts/verify_trusted_workflow_policy.py\r--policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "bare CR or CRLF"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_tab_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python\tscripts/verify_trusted_workflow_policy.py --policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "tab character"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_multiple_spaces_in_run_command(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "python  scripts/verify_trusted_workflow_policy.py --policy"
        " .github/workflow-policy/trusted_workflow_policy.json"
        ' --candidate-repository "$CANDIDATE_REPOSITORY" --candidate-ref'
        ' "$CANDIDATE_SHA" --api-url "$GITHUB_API_URL"'
    )
    with self.assertRaisesRegex(ValueError, "multiple consecutive spaces"):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_sparse_checkout_mutation_dot(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][0]["with"]["sparse-checkout"] = "."
    with self.assertRaisesRegex(
        ValueError, "Step 1 sparse-checkout paths must be exactly"
    ):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_pr_title_execution(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"][1]["run"] = (
        "echo ${{ github.event.pull_request.title }}"
    )
    with self.assertRaisesRegex(
        ValueError, "unquoted expression or PR-title execution"
    ):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_extra_checkout_or_execution_steps(self):
    mutated = copy.deepcopy(self.workflow_data)
    mutated["jobs"]["verify"]["steps"].append({
        "name": "Candidate execution step",
        "run": "python candidate.py",
    })
    with self.assertRaisesRegex(
        ValueError, "Job steps must be exactly 2 ordered steps"
    ):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_yaml_boolean_string_key_collision(self):
    mutated = {
        True: {
            "pull_request_target": {
                "branches": ["main"],
                "types": ["opened", "synchronize", "reopened"],
            }
        },
        "name": "Trusted Workflow Policy",
        "permissions": {"contents": "read"},
        "jobs": self.workflow_data["jobs"],
    }
    with self.assertRaisesRegex(
        ValueError, "YAML key collision / non-string key detected"
    ):
      validate_trusted_workflow_structure(mutated)

  def test_rejects_unsafe_yaml_tags(self):
    unsafe_yaml = """
name: Trusted Workflow Policy
'on':
  pull_request_target:
    branches: [main]
    types: [opened, synchronize, reopened]
permissions:
  contents: read
jobs:
  verify: !!python/object/apply:os.system ["echo hack"]
"""
    with self.assertRaises((yaml.YAMLError, ValueError)):
      parsed = yaml.safe_load(unsafe_yaml)
      validate_trusted_workflow_structure(parsed, unsafe_yaml)

  def test_rejects_unexpected_jobs_steps_env_permissions(self):
    mutated1 = copy.deepcopy(self.workflow_data)
    mutated1["permissions"] = {"contents": "write"}
    with self.assertRaisesRegex(ValueError, "Permissions must be exactly"):
      validate_trusted_workflow_structure(mutated1)

    mutated2 = copy.deepcopy(self.workflow_data)
    mutated2["jobs"]["extra_job"] = {}
    with self.assertRaisesRegex(
        ValueError, "jobs block must contain exactly one job named 'verify'"
    ):
      validate_trusted_workflow_structure(mutated2)

    mutated3 = copy.deepcopy(self.workflow_data)
    mutated3["jobs"]["verify"]["steps"][1]["env"]["UNEXPECTED_ENV"] = "BAD"
    with self.assertRaisesRegex(ValueError, "Step 2 env keys must be exactly"):
      validate_trusted_workflow_structure(mutated3)

    mutated4 = copy.deepcopy(self.workflow_data)
    mutated4["jobs"]["verify"]["steps"][0]["extra_key"] = "bad"
    with self.assertRaisesRegex(ValueError, "Step 1 keys must be exactly"):
      validate_trusted_workflow_structure(mutated4)

  def test_c0_control_regression_wiki_log(self):
    log_path = ROOT / "wiki/log.md"
    log_bytes = log_path.read_bytes()

    try:
      log_bytes.decode("utf-8")
    except UnicodeDecodeError as err:
      self.fail(f"wiki/log.md is not valid UTF-8: {err}")

    c0_bad = [
        (idx, byte)
        for idx, byte in enumerate(log_bytes)
        if (byte < 32 and byte not in (9, 10, 13)) or byte == 127
    ]
    self.assertEqual(
        c0_bad,
        [],
        f"wiki/log.md contains C0 control character regressions: {c0_bad}",
    )


if __name__ == "__main__":
  unittest.main()
