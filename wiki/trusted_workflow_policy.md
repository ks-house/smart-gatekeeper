# Trusted workflow policy bootstrap

## 1. Trust boundary

`.github/workflows/trusted_workflow_policy.yml` uses `pull_request_target` without `paths` or `paths-ignore` filters to prevent required-check deadlocks, ensuring `Verify protected files against trusted base policy` runs on all pull requests targeting `main` (including docs-only PRs). It never checks out or executes pull-request code. The workflow checks out only the trusted `base.sha` with credentials disabled and sparse paths limited to the base validator and policy. Candidate protected files are downloaded from the candidate repository and commit through the GitHub Contents API, decoded as inert bytes, normalized, and hashed.

The job has only `contents: read`. Pull-request titles, branches, file contents, and other attacker-controlled values are never interpolated into an executable command. The candidate repository and 40-hex commit are passed as quoted environment variables and validated again by the base script.

## 2. Protected bundle decision

The machine-readable policy is `.github/workflow-policy/trusted_workflow_policy.json`; the base validator is
`scripts/verify_trusted_workflow_policy.py`. The policy protects these files as one indivisible bundle:

- `.github/workflows/deploy.yml`
- `.github/workflows/build_app.yml`
- `.github/workflows/ota_contract.yml`
- `scripts/ota_contract_gate.py`
- `ota/requirements.txt`

`utf8-lf-v1` means strict UTF-8 decoding followed only by CRLF/CR-to-LF conversion. No whitespace, comments,
keys, steps, action versions, commands, or trailing newlines are otherwise ignored. The normalized bytes use
SHA-256. A candidate passes only when every protected path exactly matches one complete approved bundle;
mixing individually approved files from different bundles is rejected.

The repository regression test follows the same rule and requires the checked-out protected bytes to match
the sole `current-main-baseline` bundle. Separate assertions bind that entry to the exact trusted repository,
merged-main commit, protected-path order, and five normalized digests.

The policy contains exactly one `current-main-baseline` bundle sourced from merged `main` at
`ed19f3256ac8857367f1f490eb1f5f717e20ca03`. Its protected bytes are the exact PR #59 bundle authorized by
independent exact-head COMMENTED review `4890233068` and then merged normally. The transition-only
`temporary-pr59-e468e0f@e468e0f0a77e5e9b5e1a5ac7c4cdf22c4de951ad` entry has been removed. The earlier
`current-main-baseline@4e628baf043721d0e0ae86290915886cee7e3d5c`,
`origin-main-bootstrap@8c36ead`, and `pr-28-preapproved@7bae62f` identities remain retired. No branch,
wildcard, partial set, mixed set, or candidate-derived digest is approved.

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

For PR #59, the temporary approval and protected-file merge are complete. This separate policy-only
rotation removes `temporary-pr59-e468e0f` and pins the sole baseline to exact merged-main commit
`ed19f3256ac8857367f1f490eb1f5f717e20ca03`. Future rotations must repeat the same independent full-bundle
review, temporary trusted-base authorization, protected merge, and final policy-only retirement sequence.

Issue #23 remains open and OTA-G1 through OTA-G4 physical/operator evidence remains pending throughout any
policy rotation.

## 5. Scope and OTA status

This policy adds a repository authorization boundary only. It does not change the authenticated mobile
`manual_remote` door-open path, firmware/app runtime code, dual OTA partitions, health/rollback, periodic
HTTPS, authenticated local recovery, mobile updater independence, N/N-1 compatibility, signing trust, or
artifact verification. No physical OTA evidence is claimed.
