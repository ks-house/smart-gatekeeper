# Trusted workflow policy bootstrap

## 1. Trust boundary

`.github/workflows/trusted_workflow_policy.yml` uses `pull_request_target` without `paths` or `paths-ignore` filters to prevent required-check deadlocks, ensuring `Verify protected files against trusted base policy` runs on all pull requests targeting `main` (including docs-only PRs). It never checks out or executes pull-request code. The workflow checks out only the trusted `base.sha` with credentials disabled and sparse paths limited to the base validator and policy. Candidate protected files are downloaded from the candidate repository and commit through the GitHub Contents API, decoded as inert bytes, normalized, and hashed.

The job has only `contents: read`. Pull-request titles, branches, file contents, and other attacker-controlled values are never interpolated into an executable command. The actual head repository and immutable lowercase 40-hex head SHA are passed as separate quoted environment variables. The production decision validates both values, selects only bundles whose explicit source mode authorizes that identity, and only then downloads candidate bytes.

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
`ops/backend_trusted_bundle_paths.json@22ddc7237f15758a0c77c72902b51ff25d31e483`.

`utf8-lf-v1` means strict UTF-8 decoding followed only by CRLF/CR-to-LF conversion. No whitespace, comments,
keys, steps, action versions, commands, or trailing newlines are otherwise ignored. The normalized bytes use
SHA-256. A candidate passes only when every protected path exactly matches one complete approved bundle and
the actual repository/SHA satisfies that bundle's source mode. Mixing individually approved files is rejected.
Protected paths use canonical case-sensitive repository-relative POSIX syntax; dot segments, backslashes,
empty segments, absolute paths, and case-folding duplicates are rejected.

Policy format version 2 defines two authorization modes and no implicit fallback:

- `temporary-exact` requires actual candidate repository and immutable SHA to equal the bundle's exact
  `source.repository` and `source.commit`. Equivalent bytes from a fork, old commit, case variant, branch,
  tag, or another ref are rejected.
- `persistent-baseline` requires actual candidate repository to equal the trusted source repository and the
  candidate SHA to equal or descend from the reviewed `source.commit`. The trusted validator proves ancestry
  with GitHub's compare API: a distinct candidate must report `ahead` with both the exact source as the base
  commit and merge base. Only then may identical protected bytes pass. Old ancestors, diverged commits, forks,
  branches, tags, and unproven ancestry fail closed.

Missing or duplicated CLI identity options, malformed repository paths, mutable refs, uppercase or short
SHAs, duplicate authorization identities, more than one persistent baseline per repository, and unknown modes
fail closed. When an exact temporary identity and a persistent baseline both cover the same reviewed bytes,
the exact temporary match takes precedence without invoking ancestry; later descendants use only the one
persistent baseline.

The final policy contains exactly one authorization: `current-main-baseline`, a `persistent-baseline` sourced
from repository `ks-house/smart-gatekeeper` at the exact PR #67 merged-main commit
`22ddc7237f15758a0c77c72902b51ff25d31e483`. All 57 `utf8-lf-v1` digests were recomputed from GitHub Contents
API bytes at that immutable commit, independently matched against the local Git tree, and remain byte-identical
to the previously reviewed PR #67 bundle. Both transition identities, `temporary-pr67-4f14ec6` and
`future-pr67-persistent-baseline`, are removed.

Regression tests pin the exact repository, merged-main commit, mode, sole-bundle count, ordered path set, and
every digest. The real decision path rejects forks, retired or altered commits, unproven/diverged histories,
case/path variants, the old five-path partial set, missing or reordered paths, swapped/mixed/per-file digest
mutations, extra bundles, and candidate policy/validator self-use. No branch, wildcard, partial set, mixed set,
or candidate-derived digest is approved.

## 3. Why PR self-modification does not authorize itself

A PR may show edits to the policy, validator, or workflow, but the running `pull_request_target` job comes
from the default branch and explicitly loads the policy and validator from the trusted base SHA. The base
validator fetches only the protected path list from that base policy. Candidate copies of the policy or
validator are never imported, parsed, or executed, so changing them cannot change the decision for that PR.

Changes to these trust-control files still require an explicit security review before merge because their
effect begins only after they become default-branch code.

PR #68 established the identity-bound validator and schema version 2 on trusted main. This follow-up strengthens
the validator so persistent authorization requires proven source ancestry, enforces one persistent baseline per
repository, and gives an exact temporary candidate deterministic precedence. Its own hosted check still executes
the old trusted-base policy and validator, so this PR cannot authorize itself and is expected to fail the current
source-identity Gate. The validator, two-bundle transition, tests, guide, and append-only log therefore require
fresh independent exact-head review and one explicitly authorized governance exception before becoming trusted.

## 4. Rotation procedure

The PR #28 transition used two steps: first merge the independently reviewed protected bytes through the
temporary approval, then rotate the policy in this separate policy-only change to the actual merged-main
commit. Future protected-file changes must follow the same separation: independently review an exact full
bundle, merge only through trusted-base authorization, then use a separate policy-only PR to remove any
temporary approval and pin one current-main baseline. Never add a wildcard, branch name, partial-file
exception, mixed bundle, or candidate-derived digest.

PR #67 completed the transition and merged normally as exact main
`22ddc7237f15758a0c77c72902b51ff25d31e483` after hosted checks and independent exact-head review. This separate
policy-only rotation must contain only the policy, its adversarial tests, this guide, and one append-only log
entry. It removes both transition bundles and pins the sole 57-file `current-main-baseline` to that merged-main
repository and commit. The trusted base admits the rotation normally because its head is a proven descendant of
the prior reviewed source and every protected byte is unchanged.

After the final rotation merges normally, verify branch protection, current-main policy selection, and main CI.
Any later path, digest, repository, or source-commit change requires a fresh independent whole-bundle review and
the same temporary-then-persistent separation; never reuse a retired transition identity or governance exception.

Issue #23 remains open and OTA-G1 through OTA-G4 physical/operator evidence remains pending throughout any
policy rotation.

## 5. Scope and OTA status

This policy expands a repository authorization boundary only. It does not modify any protected workflow,
backend/product/runtime file, or the authenticated mobile
`manual_remote` door-open path, firmware/app runtime code, dual OTA partitions, health/rollback, periodic
HTTPS, authenticated local recovery, mobile updater independence, N/N-1 compatibility, signing trust, or
artifact verification. No physical OTA evidence is claimed.
