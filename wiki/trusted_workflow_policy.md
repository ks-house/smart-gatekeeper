# Trusted workflow policy bootstrap

## 1. Trust boundary

`.github/workflows/trusted_workflow_policy.yml` uses `pull_request_target`, but it never checks out or
executes pull-request code. The workflow checks out only the trusted `base.sha` with credentials disabled
and sparse paths limited to the base validator and policy. Candidate protected files are downloaded from
the candidate repository and commit through the GitHub Contents API, decoded as inert bytes, normalized,
and hashed.

The job has only `contents: read`. Pull-request titles, branches, file contents, and other attacker-controlled
values are never interpolated into an executable command. The candidate repository and 40-hex commit are
passed as quoted environment variables and validated again by the base script.

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

The bootstrap contains two bundles: `origin/main` at `8c36ead` and the pre-reviewed PR #28 head `7bae62f`.
This permits ordinary PRs to keep the current main bytes while allowing PR #28's complete protected bundle
during the transition. It does not approve later PR #28 heads or arbitrary edits.

## 3. Why PR self-modification does not authorize itself

A PR may show edits to the policy, validator, or workflow, but the running `pull_request_target` job comes
from the default branch and explicitly loads the policy and validator from the trusted base SHA. The base
validator fetches only the protected path list from that base policy. Candidate copies of the policy or
validator are never imported, parsed, or executed, so changing them cannot change the decision for that PR.

Changes to these trust-control files still require an explicit security review before merge because their
effect begins only after they become default-branch code.

## 4. Two-step rotation after PR #28

1. Merge PR #28 only after the trusted check identifies the exact `pr-28-preapproved` bundle and the
   independent review accepts the remaining OTA contract behavior. Keep issue #23 open and all OTA-G1
   through OTA-G4 physical/operator evidence pending.
2. From the resulting `main`, open a separate policy-only rotation PR. Replace the bootstrap's old-main and
   temporary PR #28 entries with a single bundle pinned to the actual merged `main` commit, update the
   source-evidence tests, obtain independent review, and merge the rotation. Do not combine operational
   workflow edits with this trust-anchor rotation.

If PR #28 changes after `7bae62f`, first review the new exact bytes and rotate the trusted base policy in a
separate PR. Never add a wildcard, branch name, partial-file exception, or candidate-derived digest.

## 5. Scope and OTA status

This policy adds a repository authorization boundary only. It does not change the authenticated mobile
`manual_remote` door-open path, firmware/app runtime code, dual OTA partitions, health/rollback, periodic
HTTPS, authenticated local recovery, mobile updater independence, N/N-1 compatibility, signing trust, or
artifact verification. No physical OTA evidence is claimed.
