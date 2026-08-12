import copy
import contextlib
import hashlib
import io
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


PR85_COMMIT = "d754f23a1028500248edb6a7025885c256e97c8c"
PR85_DIGEST_LINES = """\
.github/workflows/deploy.yml b73646d4e4196c48763f9e3ab5f21606df145d897c767ec1a90f25e739b7a209
.github/workflows/build_app.yml a38a63f5d31516593d91cd182614198fc538ee325a7e11364e7246e29fc11a9f
.github/workflows/ota_contract.yml 8e2c1479a64336d172a0f13b50a52fcef122e955a56d8866e58a73281ee0c001
scripts/ota_contract_gate.py d41630cb61441c135aec6756d1726d96b18e944eb96ab93f1780306b5ae780fe
ota/requirements.txt d2dc1631f87992338c4779d89db7ac6c049abd79ce14de9e6e8e1b113f7f2ca4
.github/workflows/backend_security.yml d53d6b63c9340c2dfb3ba372f7547598ca5e0bdde6ad757a8df0a169edbe4f6d
.orca/scripts/setup_worktree.ps1 07662269a4ee145547a6d0365764f4ab2d42d4234b64fe452b8a9bac4a6440ab
scripts/ops_commercial_gate.py af48700570b2ba68c910da9850a96995bb96a1647cc0ac9ff72d9261583f1e88
ops/backend_trusted_bundle_paths.json 81384991a57444c459c4b7bff540480caa0b234e32fcbc09b66ba5e68cd0f0e9
ops/evidence_sources.json 49d23f9125f65db4ba0e4398e742bcf7f41b34174b2df3d47aef1efa4fbb951b
ops/fixtures/evidence_adversarial_v1.json c2bbc316b4730a28e873abc3017f533afab2e6d7d45f95e29e228b661f72c04f
ops/fixtures/load_nominal.jsonl c7ae231d1d7321255ce0d5539b3fd18b1aa077c94ae5060fc293624913b8015e
ops/prometheus_rules.yml 8bfea1ed8d82d4bf4ce7c75ee52e5909c4b7af2c0f405d1b942ddf1119012fe9
ops/slo_policy.json e7c734c431d232e6caffa32d0796990e3dc71ff88c557498bd4433479c825e4a
backend/.env.example ae9e7c8e647c4f7544321d55cd3407d40c43b7f0a6b384cd0e8b596c8c25872e
backend/app/Dockerfile ec66fbe0de7f4fe47edf36e594810a0bb1192cf94fa5fc81cc7fced224479573
backend/app/acl_api.py c8ca43b7f6c648645c37aa789128c7e262076f673e79a2560fb5d5cdf6931366
backend/app/acl_management.py 3c9d712c436eb98632c1e4840e4268889253706c162de7ce22a2d9d83ddb1ad7
backend/app/admin_security.py 5b88de305f35159641c176005b5e741bd4b9e1f9b0eb24a521c4fb5dcf774327
backend/app/command_security.py 9b5c058fd8fe4d58c6c20a23548e803ddeb06b493a344f18e29453f599271e1c
backend/app/main.py 9da41f2db0e3a999be1f9ffa9cb67e34a6bb25d4ddb847d9771b06863efe1083
backend/app/ops_runtime.py 1a5d8cb2c08181c9e76d67bb93339da6a9b8d05b3ff8ccf7141a985070f56608
backend/app/requirements.lock 4a1f393a82340ed062e7e2efdc7b57edd8df6d6d59d62a561643c93685a19a71
backend/app/requirements.txt 75bca144713e5c0ac8c09f2963cccb45e077e22b2f5a166a0db1fa28617595f7
backend/app/static/admin.html ca61cf93520cfdd7bab0d5c710ab01a6b7215e94d2be54ee61f4537deb4b141e
backend/app/static/index.html 4218d95905ae238339987cb0887d2fd03e352493dcabfe1133500296ec25f01d
backend/app/target_boot_registry.py c5cd20f2a54baf4746245e7c9dfa62916b7fe1152f9789f532d7f119c86288cf
backend/compose.production.yml 645f08487de733d76a4fe34b427179284d264decb1c55717ccf194677f51d5de
backend/db/Dockerfile 317ad438b9d2ce25325027b5b1170f92d14c45f536ba413bd0d3ca853fd73c2a
backend/db/migrations/002_acl_management_expand_down.sql 19c26782df1ef78755681805839e704f3adaf83cce1dec4b29c4ecdf1c0cf687
backend/db/migrations/002_acl_management_expand_up.sql aa3b07f195c0502434f8ad5ba633b0d46d6b04f7e21fa0ff22215fb136746543
backend/db/migrations/003_admin_security_down.sql 1fb6804703a9fdd4d9ffdb74adb1113cd7f420b914fa572978dcb2e6212f9d71
backend/db/migrations/003_admin_security_up.sql 488f52723e9e4d089c25f46d80bfcd641cf573a0d68d950bfbbf6b6c7c5923e1
backend/db/migrations/004_admin_control_v2_down.sql 5ac8153a9247176f0631f8e621d99913cb010b870cd42e635ae7c6d7f5cc0b78
backend/db/migrations/004_admin_control_v2_up.sql 58cefa03fb7c70a96b819510b80ccd8bd0cc085b0cb981d76bd0c86b78801d49
backend/db/migrations/005_force_open_reconciliation_down.sql c9f0e1c5f85fbc6c462f9fefc8417548f86ae0a3f3d39c4d9b9ab7c6eab2de13
backend/db/migrations/005_force_open_reconciliation_up.sql 36d08998dd633cce71d67ad6124b668e81804911eddf7e9322f9e40c9c14e5e7
backend/db/migrations/006_target_boot_state_down.sql d746fd9fca137863f19f54d461edde52c09d2c4fd64bfc0d2b8610361e3e03ff
backend/db/migrations/006_target_boot_state_up.sql b7beae706b694d3fde5b63bf2d1587ba5ded887aedec060e148b15109f5fcabd
backend/db/migrations/007_ops_privacy_down.sql 2f0c2094f6c5748ad3a067a71c3d31effed310ccc68ebb14c714ec09fe901922
backend/db/migrations/007_ops_privacy_up.sql edde5662c42e65dda82b2e0a9145d64dc4ebfc9fe7a5e5bd44b0b3aae0fe1d79
backend/db/production_schema.sql b9e6910bff05272c1b05f1e23805abf250c6a9e3df9e4a7db966ae6517b555e3
backend/db/run_migrations.sh b408f0b2e6ffe7b58a095430a3ecdbc6d719cef31b8cb7c6a2b62b4ab39d7d3b
backend/db/schema.sql ce22d4e2675490f2e238cd98e9f9168e572cd45d0de8030811b01384226f4d43
backend/docker-compose.yml 4ce83d166d6f90bea175b1ba9c80182b54cc86fcf61db2ff57064e60ffa6095e
backend/sbom.cdx.json 67b78d1a2cb4d5e48dc8b79f9630a58da0cee207d126c469cb0b0bfbd1945fd7
backend/supply_chain_policy.json fef90253f3ec0b065f14dd1e83a2b6702b4dd2ad8dbeefc59b12dc78f3cb15e4
backend/tests/test_acl_api.py 4e276a773d5a7d52e470b5f4922c231a20141d2078db00f925d8aee2a855e72b
backend/tests/test_acl_management.py 63466520512ea0a259b61976417150feb622ebbbd0fb0e287769669e47764566
backend/tests/test_admin_security.py f3ea883b82b45c9141f7b12b098f683da54a510df85cac7f21b5eb9c4ac43a5e
backend/tests/test_legacy_ota_independence.py 5819701b2b2fc5c9c0e2b7bbaf710f23360d6a0df36c1966c345621dc4aceca4
backend/tests/test_migrations.py 2143f4e9a4ca6b9b672f5ed6a9d1de84f45a41db78e1d169d3cc5dde69f22289
backend/tests/test_ops_api.py faf541fdbbf7db438ab2c838767a431ea524f37d11ee963ca7dadea6f6d806ea
backend/tests/test_ops_commercial_gate.py 0bc3396d0705e4d4328092c6d87ac66352c297095108336f19c0db87e7a16d94
backend/tests/test_ops_runtime.py 322d72efa0c1ebf8154992bea6c153ac6904eaf3fe61b2dee7dc779d5c131519
backend/tests/test_target_boot_registry.py d02627f6ef826f5e57c8086c1251d46bbab1fa5346bb87e03015b759791649d5
protocol/test_vectors/v1.json a60dfef0d23b8b3bd016e8f30e690609a82ff009ca90ff2c6aa5525d7539048f
"""
PR85_DIGESTS = dict(
    line.split() for line in PR85_DIGEST_LINES.splitlines()
)
OLD_FIVE_PATHS = list(PR85_DIGESTS)[:5]
RETIRED_MAIN_SAMPLE_DIGESTS = {
    ".github/workflows/backend_security.yml": (
        "5ea77cd7444c7a284485acf65a24e265746bcde4fbb18fa30b1f6220b45053b0"
    ),
    "backend/app/main.py": (
        "af96a303439e77fceb8cb781196f7558e768119ba0c5c03ed6331636fe721e80"
    ),
}
RETIRED_SOURCE_COMMITS = {
    "72fa8610e509de4bff3b20d60d9da19ab312bd3b",
    "44b43411d5156d9a3a08ec0f94b8336c90f6bcb5",
    "0a34796213d5677d9dc77a8b73564004e8e3a2cf",
    "0ec8221e275e36a5917c08a55cde10c36dd0e972",
    "2c676a2f71f33aebcf8b15beec40d868f6e6efd5",
    "f0f8666ab9aa2b68d042207ddb89d47f97ea7146",
    "24b8e4122b6aad37175fc4be3449372abb1eed0d",
    "bbe842a13541386c9e101284cf49ab4df6bca042",
    "2e540d13f1ea31d800a9a6f2f3bca668a23c4013",
    "5f68de9523e6c2ee263452a7c593ad50069a657b",
    "03ffba4f5020bb304a4a22cdfd4ff9c4c46a035b",
    "4db7a975d7af45b96d6f6aaf6beb6f2ca6aa2a34",
    "5389f6a3ab2f28698d423567481ecdc29a260ace",
    "22ddc7237f15758a0c77c72902b51ff25d31e483",
    "e42d1f417a555b17d7476522aa48f7e4d72306b7",
    "4f14ec660bc69fa9afc23ab4f257f52fcc4a7a22",
    "9d33d10ce3b500dfcad818f08de11b324da4bdbb",
    "f5c90bef2c2d4500ff68c014d1385ac37b440f0c",
    "2bb223629c848f298177fc16ec3cac1fa40b8e0f",
    "1ce7f16a52380a6ff1dcd84a4cdca70569cbff75",
    "ed19f3256ac8857367f1f490eb1f5f717e20ca03",
    "e468e0f0a77e5e9b5e1a5ac7c4cdf22c4de951ad",
    "4e628baf043721d0e0ae86290915886cee7e3d5c",
    "cc977e42770e6d88822459436a770295632c6e45",
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
  def assert_pr85_transition_is_exact(self, policy):
    self.assertEqual(policy["format_version"], 2)
    self.assertEqual(policy["protected_paths"], list(PR85_DIGESTS))
    self.assertEqual(len(policy["protected_paths"]), 57)
    self.assertEqual(len(policy["approved_bundles"]), 2)
    temporary, persistent = policy["approved_bundles"]
    self.assertEqual(temporary["id"], "temporary-pr85-d754f23")
    self.assertEqual(temporary["mode"], "temporary-exact")
    self.assertEqual(persistent["id"], "future-pr85-persistent-baseline")
    self.assertEqual(persistent["mode"], "persistent-baseline")
    expected_source = {
        "repository": "ks-house/smart-gatekeeper",
        "commit": PR85_COMMIT,
    }
    self.assertEqual(temporary["source"], expected_source)
    self.assertEqual(persistent["source"], expected_source)
    self.assertEqual(temporary["files"], PR85_DIGESTS)
    self.assertEqual(persistent["files"], PR85_DIGESTS)
    self.assertEqual(temporary["files"], persistent["files"])
    self.assertEqual(list(temporary["files"]), policy["protected_paths"])
    self.assertEqual(list(persistent["files"]), policy["protected_paths"])

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
        "format_version": 2,
        "normalization": trusted.NORMALIZATION,
        "protected_paths": list(self.main_files),
        "approved_bundles": [
            {
                "id": "main",
                "mode": "persistent-baseline",
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
                "mode": "temporary-exact",
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

  def verify(
      self,
      files,
      repository="owner/repository",
      ref="3" * 40,
  ):
    return trusted.verify_candidate(
        self.policy,
        repository,
        ref,
        files.__getitem__,
        lambda ancestor, descendant: (
            ancestor == descendant or descendant in {"3" * 40, "f" * 40}
        ),
    )

  def test_exact_main_bundle_is_approved(self):
    bundle = self.verify(self.main_files)
    self.assertEqual(bundle["id"], "main")

  def test_exact_alternate_bundle_is_approved(self):
    bundle = self.verify(self.alternate_files, ref="2" * 40)
    self.assertEqual(bundle["id"], "alternate")

  def test_exact_temporary_precedes_same_byte_persistent_baseline(self):
    policy = copy.deepcopy(self.policy)
    policy["approved_bundles"][1]["files"] = copy.deepcopy(
        policy["approved_bundles"][0]["files"]
    )
    ancestry = mock.Mock(return_value=True)
    bundle = trusted.verify_candidate(
        policy,
        "owner/repository",
        "2" * 40,
        self.main_files.__getitem__,
        ancestry,
    )
    self.assertEqual(bundle["id"], "alternate")
    ancestry.assert_not_called()

  def test_persistent_baseline_accepts_later_same_repository_commit_only(self):
    for ref in ("1" * 40, "3" * 40, "f" * 40):
      with self.subTest(ref=ref):
        self.assertEqual(self.verify(self.main_files, ref=ref)["id"], "main")
    with self.assertRaisesRegex(trusted.PolicyError, "source repository/ref"):
      self.verify(self.main_files, repository="attacker/fork")

  def test_persistent_baseline_requires_proven_descendant(self):
    with self.assertRaisesRegex(trusted.PolicyError, "ancestry verification"):
      trusted.verify_candidate(
          self.policy,
          "owner/repository",
          "3" * 40,
          self.main_files.__getitem__,
      )
    ancestry = mock.Mock(return_value=False)
    with self.assertRaisesRegex(trusted.PolicyError, "source repository/ref"):
      trusted.verify_candidate(
          self.policy,
          "owner/repository",
          "3" * 40,
          self.main_files.__getitem__,
          ancestry,
      )
    ancestry.assert_called_once_with("1" * 40, "3" * 40)

  def test_github_compare_requires_ahead_status_and_exact_merge_base(self):
    ancestor = "1" * 40
    descendant = "3" * 40
    fetcher = trusted.GitHubContentsFetcher(
        "https://api.github.com", "owner/repository", descendant, "token"
    )
    valid = {
        "status": "ahead",
        "merge_base_commit": {"sha": ancestor},
        "base_commit": {"sha": ancestor},
    }
    cases = (
        (valid, True),
        ({**valid, "status": "behind"}, False),
        ({**valid, "status": "diverged"}, False),
        ({**valid, "merge_base_commit": {"sha": "2" * 40}}, False),
        ({**valid, "base_commit": {"sha": "2" * 40}}, False),
        ({"status": "ahead"}, False),
    )
    for payload, expected in cases:
      response = mock.MagicMock()
      response.__enter__.return_value.read.return_value = json.dumps(
          payload
      ).encode("utf-8")
      with self.subTest(payload=payload), mock.patch.object(
          trusted.urllib.request, "urlopen", return_value=response
      ) as urlopen:
        self.assertEqual(fetcher.is_descendant(ancestor, descendant), expected)
        request = urlopen.call_args.args[0]
        self.assertIn(f"/compare/{ancestor}...{descendant}", request.full_url)

    with mock.patch.object(trusted.urllib.request, "urlopen") as urlopen:
      self.assertTrue(fetcher.is_descendant(ancestor, ancestor))
      urlopen.assert_not_called()

  def test_line_endings_are_normalized_but_other_bytes_are_exact(self):
    self.assertEqual(_digest(b"a\r\nb\r"), _digest(b"a\nb\n"))
    self.assertNotEqual(_digest(b"a\nb\n"), _digest(b"a\nb\n "))

  def test_arbitrary_byte_change_is_rejected(self):
    changed = dict(self.main_files)
    changed["gate.py"] += b"# attacker\n"
    with self.assertRaisesRegex(trusted.PolicyError, "gate.py"):
      self.verify(changed)

  def test_mixed_approved_bundles_are_rejected(self):
    mixed = {
        "workflow.yml": self.main_files["workflow.yml"],
        "gate.py": self.alternate_files["gate.py"],
    }
    with self.assertRaisesRegex(trusted.PolicyError, "not an approved bundle"):
      self.verify(mixed)

  def test_missing_protected_file_is_rejected(self):
    with self.assertRaises(KeyError):
      self.verify({"workflow.yml": b"x"})

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

    bundle = trusted.verify_candidate(
        copy.deepcopy(self.policy),
        "owner/repository",
        "3" * 40,
        fetch,
        lambda _ancestor, _descendant: True,
    )
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
      trusted.verify_candidate(
          copy.deepcopy(self.policy),
          "owner/repository",
          "3" * 40,
          candidate_tree.__getitem__,
          lambda _ancestor, _descendant: True,
      )

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

  def test_policy_rejects_mode_identity_and_path_schema_mutations(self):
    mutations = []

    missing_mode = copy.deepcopy(self.policy)
    del missing_mode["approved_bundles"][0]["mode"]
    mutations.append(missing_mode)

    invalid_mode = copy.deepcopy(self.policy)
    invalid_mode["approved_bundles"][0]["mode"] = "branch-or-wildcard"
    mutations.append(invalid_mode)

    duplicate_identity = copy.deepcopy(self.policy)
    duplicate_identity["approved_bundles"][1]["mode"] = "persistent-baseline"
    duplicate_identity["approved_bundles"][1]["source"] = copy.deepcopy(
        duplicate_identity["approved_bundles"][0]["source"]
    )
    mutations.append(duplicate_identity)

    duplicate_persistent_repository = copy.deepcopy(self.policy)
    duplicate_persistent_repository["approved_bundles"].append(
        copy.deepcopy(duplicate_persistent_repository["approved_bundles"][0])
    )
    duplicate_persistent_repository["approved_bundles"][2]["id"] = "later-main"
    duplicate_persistent_repository["approved_bundles"][2]["source"][
        "commit"
    ] = "4" * 40
    mutations.append(duplicate_persistent_repository)

    for path_variant in (
        "Workflow.yml",
        "workflow.yml/../gate.py",
        "workflow.yml\\gate.py",
        "workflow.yml//gate.py",
        "/workflow.yml",
    ):
      mutated = copy.deepcopy(self.policy)
      if path_variant == "Workflow.yml":
        mutated["protected_paths"].append(path_variant)
        mutated["approved_bundles"][0]["files"][path_variant] = "0" * 64
        mutated["approved_bundles"][1]["files"][path_variant] = "0" * 64
      else:
        old_path = mutated["protected_paths"][0]
        mutated["protected_paths"][0] = path_variant
        for bundle in mutated["approved_bundles"]:
          bundle["files"][path_variant] = bundle["files"].pop(old_path)
      mutations.append(mutated)

    for index, mutated in enumerate(mutations):
      with self.subTest(index=index):
        with self.assertRaises(trusted.PolicyError):
          trusted.validate_policy(mutated)

  def test_runtime_rejects_missing_malformed_case_and_wrong_identity(self):
    fetch = mock.Mock(side_effect=self.main_files.__getitem__)
    invalid = (
        (None, "3" * 40),
        ("owner/repository", None),
        ("Owner/repository", "3" * 40),
        ("owner/repository/extra", "3" * 40),
        ("owner//repository", "3" * 40),
        ("../repository", "3" * 40),
        ("owner/..", "3" * 40),
        ("owner/repository", "3" * 39),
        ("owner/repository", "A" * 40),
        ("owner/repository", "refs/heads/main"),
    )
    for repository, ref in invalid:
      with self.subTest(repository=repository, ref=ref):
        fetch.reset_mock()
        with self.assertRaises(trusted.PolicyError):
          trusted.verify_candidate(self.policy, repository, ref, fetch)
        fetch.assert_not_called()

  def test_cli_rejects_missing_and_duplicate_candidate_identity(self):
    common = ["verify", "--policy", "policy.json"]
    cases = (
        common + ["--candidate-ref", "1" * 40],
        common + ["--candidate-repository", "owner/repository"],
        common + [
            "--candidate-repository", "owner/repository",
            "--candidate-repository", "attacker/fork",
            "--candidate-ref", "1" * 40,
        ],
        common + [
            "--candidate-repository", "owner/repository",
            "--candidate-ref", "1" * 40,
            "--candidate-ref", "2" * 40,
        ],
    )
    for argv in cases:
      with self.subTest(argv=argv), mock.patch.object(sys, "argv", argv):
        with contextlib.redirect_stderr(io.StringIO()):
          with self.assertRaises(SystemExit):
            trusted.parse_args()

  def verify_pr85_digest_map(
      self,
      policy,
      digests,
      repository="ks-house/smart-gatekeeper",
      ref=PR85_COMMIT,
      is_descendant=None,
  ):
    if is_descendant is None:
      is_descendant = lambda ancestor, descendant: (
          ancestor == descendant and descendant == PR85_COMMIT
      )
    with mock.patch.object(
        trusted,
        "normalized_sha256",
        side_effect=lambda content: content.decode("ascii"),
    ):
      return trusted.verify_candidate(
          policy,
          repository,
          ref,
          lambda path: digests[path].encode("ascii"),
          is_descendant,
      )

  def test_transition_policy_has_exact_and_future_pr85_bundles(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    self.assert_pr85_transition_is_exact(policy)
    ancestry = mock.Mock(return_value=True)
    bundle = self.verify_pr85_digest_map(
        policy, PR85_DIGESTS, is_descendant=ancestry
    )
    self.assertEqual(bundle["id"], "temporary-pr85-d754f23")
    ancestry.assert_not_called()
    self.assertNotIn(
        "current-main-baseline",
        {approved["id"] for approved in policy["approved_bundles"]},
    )

  def test_future_pr85_baseline_accepts_only_proven_descendant(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    future_ref = "a" * 40
    ancestry = mock.Mock(
        side_effect=lambda ancestor, descendant: (
            ancestor == PR85_COMMIT and descendant == future_ref
        )
    )
    bundle = self.verify_pr85_digest_map(
        policy,
        PR85_DIGESTS,
        ref=future_ref,
        is_descendant=ancestry,
    )
    self.assertEqual(bundle["id"], "future-pr85-persistent-baseline")
    ancestry.assert_called_once_with(PR85_COMMIT, future_ref)

    with self.assertRaisesRegex(trusted.PolicyError, "source repository/ref"):
      self.verify_pr85_digest_map(
          policy,
          PR85_DIGESTS,
          ref="bbe842a13541386c9e101284cf49ab4df6bca042",
          is_descendant=lambda _ancestor, _descendant: False,
      )

  def test_pr85_source_forks_divergence_and_old_commits_are_rejected(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    self.assert_pr85_transition_is_exact(policy)
    mutations = [("repository", "attacker/fork"), ("commit", "f" * 40)]
    mutations.extend(("commit", commit) for commit in RETIRED_SOURCE_COMMITS)
    for field, value in mutations:
      with self.subTest(field=field, value=value):
        mutated = copy.deepcopy(policy)
        mutated["approved_bundles"][0]["source"][field] = value
        trusted.validate_policy(mutated)
        with self.assertRaises(AssertionError):
          self.assert_pr85_transition_is_exact(mutated)

    runtime_identities = [
        ("attacker/fork", PR85_COMMIT),
        ("KS-HOUSE/smart-gatekeeper", PR85_COMMIT),
        ("ks-house/SMART-GATEKEEPER", PR85_COMMIT),
        ("ks-house/smart-gatekeeper", "f" * 40),
    ]
    runtime_identities.extend(
        ("ks-house/smart-gatekeeper", commit)
        for commit in RETIRED_SOURCE_COMMITS
    )
    for repository, ref in runtime_identities:
      with self.subTest(repository=repository, ref=ref):
        with self.assertRaisesRegex(
            trusted.PolicyError, "source repository/ref"
        ):
          self.verify_pr85_digest_map(
              policy,
              PR85_DIGESTS,
              repository=repository,
              ref=ref,
              is_descendant=lambda _ancestor, _descendant: False,
          )

    with self.assertRaisesRegex(trusted.PolicyError, "source repository/ref"):
      self.verify_pr85_digest_map(
          policy,
          PR85_DIGESTS,
          ref="a" * 40,
          is_descendant=lambda _ancestor, _descendant: False,
      )

  def test_pr85_missing_partial_old_and_reordered_paths_are_rejected(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    deploy_path = policy["protected_paths"][0]

    missing_file = copy.deepcopy(policy)
    del missing_file["approved_bundles"][0]["files"][deploy_path]
    with self.assertRaisesRegex(trusted.PolicyError, "protected_paths exactly"):
      trusted.validate_policy(missing_file)

    partial = copy.deepcopy(policy)
    partial["protected_paths"] = OLD_FIVE_PATHS
    for bundle in partial["approved_bundles"]:
      bundle["files"] = {
          path: PR85_DIGESTS[path] for path in OLD_FIVE_PATHS
      }
    trusted.validate_policy(partial)
    with self.assertRaises(AssertionError):
      self.assert_pr85_transition_is_exact(partial)

    reordered = copy.deepcopy(policy)
    reordered["protected_paths"][5], reordered["protected_paths"][6] = (
        reordered["protected_paths"][6],
        reordered["protected_paths"][5],
    )
    trusted.validate_policy(reordered)
    with self.assertRaises(AssertionError):
      self.assert_pr85_transition_is_exact(reordered)

  def test_pr85_swapped_mixed_partial_and_digest_mutations_are_rejected(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    deploy_path = ".github/workflows/deploy.yml"
    build_path = ".github/workflows/build_app.yml"

    swapped = dict(PR85_DIGESTS)
    swapped[deploy_path], swapped[build_path] = (
        swapped[build_path],
        swapped[deploy_path],
    )
    with self.assertRaises(trusted.PolicyError):
      self.verify_pr85_digest_map(policy, swapped)

    mixed = dict(PR85_DIGESTS)
    mixed.update(RETIRED_MAIN_SAMPLE_DIGESTS)
    with self.assertRaises(trusted.PolicyError):
      self.verify_pr85_digest_map(policy, mixed)

    partial = dict(PR85_DIGESTS)
    del partial["backend/app/main.py"]
    with self.assertRaises(KeyError):
      self.verify_pr85_digest_map(policy, partial)

    for path in policy["protected_paths"]:
      with self.subTest(path=path):
        changed = dict(PR85_DIGESTS)
        changed[path] = "0" * 64
        with self.assertRaises(trusted.PolicyError):
          self.verify_pr85_digest_map(policy, changed)

  def test_pr85_policy_digest_or_extra_bundle_cannot_expand_authorization(self):
    policy = trusted.load_policy(
        ROOT / ".github/workflow-policy/trusted_workflow_policy.json"
    )
    mutated = copy.deepcopy(policy)
    mutated["approved_bundles"][0]["files"]["backend/app/main.py"] = "0" * 64
    trusted.validate_policy(mutated)
    with self.assertRaises(AssertionError):
      self.assert_pr85_transition_is_exact(mutated)
    with self.assertRaises(trusted.PolicyError):
      self.verify_pr85_digest_map(mutated, PR85_DIGESTS)

    extra = copy.deepcopy(policy)
    extra["approved_bundles"].append({
        "id": "unauthorized-second-bundle",
        "mode": "temporary-exact",
        "source": {
            "repository": "ks-house/smart-gatekeeper",
            "commit": "f" * 40,
        },
        "files": dict(PR85_DIGESTS),
    })
    trusted.validate_policy(extra)
    with self.assertRaises(AssertionError):
      self.assert_pr85_transition_is_exact(extra)


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
