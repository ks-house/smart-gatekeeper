# Trusted workflow policy bootstrap

## 1. Trust boundary

`.github/workflows/trusted_workflow_policy.yml` uses `pull_request_target` without `paths` or `paths-ignore` filters to prevent required-check deadlocks, ensuring `Verify protected files against trusted base policy` runs on all pull requests targeting `main` (including docs-only PRs). It never checks out or executes pull-request code. The workflow checks out only the trusted `base.sha` with credentials disabled and sparse paths limited to the base validator and policy. Candidate protected files are downloaded from the candidate repository and commit through the GitHub Contents API, decoded as inert bytes, normalized, and hashed.

The job has only `contents: read`. Pull-request titles, branches, file contents, and other attacker-controlled values are never interpolated into an executable command. The candidate repository and 40-hex commit are passed as quoted environment variables and validated again by the base script.

## 2. Protected bundle decision

The machine-readable policy is `.github/workflow-policy/trusted_workflow_policy.json`; the base validator is
`scripts/verify_trusted_workflow_policy.py`. The policy protects 57 files as one indivisible bundle. The
ordered set starts with the existing release-control five:

- `.github/workflows/deploy.yml`
- `.github/workflows/build_app.yml`
- `.github/workflows/ota_contract.yml`
- `scripts/ota_contract_gate.py`
- `ota/requirements.txt`

It then includes the exact 52 backend and operations inputs authorized for PR #67: the backend-security
workflow, Orca setup input, commercial-operations gate, evidence/SLO fixtures and policies, backend runtime,
locked dependencies, static admin surfaces, production Compose and database migration inputs, SBOM/supply
chain policy, backend tests, and canonical protocol vectors. The JSON policy contains the authoritative
complete ordered path set; it is identical to the existing five followed by
`ops/backend_trusted_bundle_paths.json@2bb223629c848f298177fc16ec3cac1fa40b8e0f`.

`utf8-lf-v1` means strict UTF-8 decoding followed only by CRLF/CR-to-LF conversion. No whitespace, comments,
keys, steps, action versions, commands, or trailing newlines are otherwise ignored. The normalized bytes use
SHA-256. A candidate passes only when every protected path exactly matches one complete approved bundle;
mixing individually approved files from different bundles is rejected.

The transition policy contains exactly one bundle, `temporary-pr67-2bb2236`, whose review provenance is
repository `ks-house/smart-gatekeeper` at exact commit
`2bb223629c848f298177fc16ec3cac1fa40b8e0f`. Independent exact-head COMMENTED review `4890584574`
authorized only those 57 normalized digests as one complete set. Regression tests separately pin the exact
repository, commit, ordered path set, and every digest; they reject the old five-path set, missing/reordered
paths, swapped or mixed digests, retired commits, extra bundles, and candidate policy/validator self-use.

The previous five-file `current-main-baseline@ed19f3256ac8857367f1f490eb1f5f717e20ca03` cannot coexist in
this transition policy because the expanded path set includes files not present on pre-PR67 `main`. Keeping
it as a partial bundle would weaken the whole-bundle invariant, so it is intentionally removed. This makes
the transition narrow: after this policy merges, only the complete reviewed PR #67 bytes pass until PR #67
is merged and a separate final policy-only rotation pins the resulting merged-main 57-file baseline. No
branch, wildcard, partial set, mixed set, or candidate-derived digest is approved.

## 3. Why PR self-modification does not authorize itself

A PR may show edits to the policy, validator, or workflow, but the running `pull_request_target` job comes
from the default branch and explicitly loads the policy and validator from the trusted base SHA. The base
validator fetches only the protected path list from that base policy. Candidate copies of the policy or
validator are never imported, parsed, or executed, so changing them cannot change the decision for that PR.

Changes to these trust-control files still require an explicit security review before merge because their
effect begins only after they become default-branch code.

## 4. Rotation procedure

The PR #28 transition used two steps: first merge the independently reviewed protected bytes through the
temporary approval, then rotate the policy in this separate policy-only change to the actual merged-main
commit. Future protected-file changes must follow the same separation: independently review an exact full
bundle, merge only through trusted-base authorization, then use a separate policy-only PR to remove any
temporary approval and pin one current-main baseline. Never add a wildcard, branch name, partial-file
exception, mixed bundle, or candidate-derived digest.

For PR #67, merge this policy-only temporary authorization first through normal protection. Then re-run the
trusted check on exact PR #67 head `2bb223629c848f298177fc16ec3cac1fa40b8e0f` and merge that reviewed
candidate without rewriting it. Immediately follow with a separate policy-only rotation that removes
`temporary-pr67-2bb2236` and pins one 57-file `current-main-baseline` to the actual PR #67 merged-main commit.
Any path, digest, repository, or reviewed source-commit change requires a fresh independent whole-bundle
review; do not prolong the temporary single-candidate window or merge unrelated PRs through a bypass.

Issue #23 remains open and OTA-G1 through OTA-G4 physical/operator evidence remains pending throughout any
policy rotation.

## 5. Scope and OTA status

This policy expands a repository authorization boundary only. It does not modify any protected workflow,
backend/product/runtime file, or the authenticated mobile
`manual_remote` door-open path, firmware/app runtime code, dual OTA partitions, health/rollback, periodic
HTTPS, authenticated local recovery, mobile updater independence, N/N-1 compatibility, signing trust, or
artifact verification. No physical OTA evidence is claimed.
