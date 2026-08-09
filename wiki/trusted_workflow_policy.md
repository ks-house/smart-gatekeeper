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

The PR #72 transition policy contains exactly two non-ambiguous authorizations for one byte-identical complete
57-file set. `temporary-pr72-03ffba4` is a `temporary-exact` identity for repository
`ks-house/smart-gatekeeper` at exact candidate commit
`03ffba4f5020bb304a4a22cdfd4ff9c4c46a035b`. `future-pr72-persistent-baseline` uses the same repository,
source commit, ordered paths, and 57 digests, but admits only that source or a GitHub Compare-proven descendant.
Exact-match precedence selects the temporary identity at the reviewed head without invoking ancestry; after the
policy lands and PR #72 integrates the new main once, only the persistent identity can admit the resulting
descendant while all protected bytes remain unchanged.

All 57 `utf8-lf-v1` digests were recomputed from immutable GitHub Contents API bytes at the exact PR head. The
three changed values are `.github/workflows/deploy.yml`
`133d31ebb91922ab9e2370e91d8a3ad4215accde1c7adbad28cb2c653aa42251`,
`.github/workflows/build_app.yml`
`1d17741591fde129200c6aa6403644b0d9b590de1831936d65db0e9ea9f17af2`, and
`scripts/ota_contract_gate.py`
`ba3bc9de1eeecc306d1b23b1a2c6ddb124a0d3d4396c54ef137e6cc3a071e1bc`; the other 54 match the prior reviewed
complete baseline. Independent product COMMENTED review `4891310679` is bound by the GitHub API to PR #72 and
that exact commit and reports a nonblocking product-bundle verdict. It is review evidence, not production,
physical, release, or deployment authorization.

Regression tests pin the exact repository, source commit, modes, two-bundle count, ordered path set, and every
digest. They reject an extra bundle, fork, retired or altered commit, unproven/diverged history, case/path
variant, old five-path partial set, missing or reordered path, swapped/mixed/per-file digest mutation, and
candidate policy/validator self-use. The former `current-main-baseline` is intentionally replaced; retaining it
would create a second persistent authorization for the repository and violate the schema. No branch, wildcard,
partial set, mixed set, candidate-derived digest, or third baseline is approved.

## 3. Why PR self-modification does not authorize itself

A PR may show edits to the policy, validator, or workflow, but the running `pull_request_target` job comes
from the default branch and explicitly loads the policy and validator from the trusted base SHA. The base
validator fetches only the protected path list from that base policy. Candidate copies of the policy or
validator are never imported, parsed, or executed, so changing them cannot change the decision for that PR.

Changes to these trust-control files still require an explicit security review before merge because their
effect begins only after they become default-branch code.

PR #68 and PR #69 established the identity-bound schema version 2 validator and bounded transition on trusted
main; PR #67 then completed that transition. This PR #72 authorization changes only policy data, regression
tests, this guide, and the append-only log. It does not modify the validator or trusted workflow. Its own hosted
check executes the old trusted-base policy and validator, which admit the policy PR normally because its head is
a GitHub-proven descendant of the current baseline source and all 57 protected bytes remain unchanged. A green
Hosted Trusted check and fresh independent exact-head review are required before a normal protected merge; no
governance exception or branch-protection change is authorized.

## 4. Rotation procedure

The PR #28 transition used two steps: first merge the independently reviewed protected bytes through the
temporary approval, then rotate the policy in this separate policy-only change to the actual merged-main
commit. Future protected-file changes must follow the same separation: independently review an exact full
bundle, merge only through trusted-base authorization, then use a separate policy-only PR to remove any
temporary approval and pin one current-main baseline. Never add a wildcard, branch name, partial-file
exception, mixed bundle, or candidate-derived digest.

For PR #72, first merge this independently reviewed policy-only PR normally from exact trusted main
`038bc8508fca71e1d4074a3eedca5517d3c2ecfe`. Do not merge or dispatch PR #72 in the same operation. The transition
policy intentionally no longer admits the old protected bytes after it becomes main. PR #72 must then integrate
that exact new main once without rewriting history, preserve the new-main `wiki/log.md` blob as a byte prefix,
retain its prior suffix exactly once, keep all 57 reviewed protected digests and `raw/` unchanged, and receive a
fresh exact-descendant review and hosted checks. GitHub Compare must prove
`03ffba4f5020bb304a4a22cdfd4ff9c4c46a035b` is the exact merge base/ancestor of the new PR head before the
persistent identity may admit it.

After PR #72 merges normally, immediately create a separate final policy-only rotation. It removes both PR #72
transition identities and pins one `persistent-baseline` named `current-main-baseline` to the actual merged-main
57-file bundle. The transition baseline admits that final rotation only when GitHub Compare proves ancestry and
every protected byte is unchanged. Then verify branch protection, current-main policy selection, and main CI.
Any path, digest, repository, or reviewed source-commit change requires a fresh independent whole-bundle review;
never prolong the transition window or reuse a retired transition identity.

Issue #23 remains open and OTA-G1 through OTA-G4 physical/operator evidence remains pending throughout any
policy rotation.

## 5. Scope and OTA status

This policy expands a repository authorization boundary only. It does not itself modify any protected workflow,
backend/product/runtime file, dispatch a workflow, or write to a NAS. It does not change the authenticated mobile
`manual_remote` door-open path, firmware/app runtime code, dual OTA partitions, health/rollback, periodic
HTTPS, authenticated local recovery, mobile updater independence, N/N-1 compatibility, signing trust, or
artifact verification. No physical OTA evidence is claimed.
