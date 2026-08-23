# Trusted workflow policy bootstrap

## 1. Trust boundary

`.github/workflows/trusted_workflow_policy.yml` uses `pull_request_target` without `paths` or `paths-ignore` filters to prevent required-check deadlocks, ensuring `Verify protected files against trusted base policy` runs on all pull requests targeting `main` (including docs-only PRs). It never checks out or executes pull-request code. The workflow checks out only the trusted `base.sha` with credentials disabled and sparse paths limited to the base validator and policy. Candidate protected files are downloaded from the candidate repository and commit through the GitHub Contents API, decoded as inert bytes, normalized, and hashed. The same immutable candidate SHA is also read through GitHub's recursive Git Trees API so path inventory, Git object type, and mode are checked without checking out candidate code; a missing or truncated tree fails closed.

The job has only `contents: read`. Pull-request titles, branches, file contents, and other attacker-controlled values are never interpolated into an executable command. The actual head repository and immutable lowercase 40-hex head SHA are passed as separate quoted environment variables. The production decision validates both values, selects only bundles whose explicit source mode authorizes that identity, and only then downloads candidate bytes.

## 2. Protected bundle decision

The machine-readable policy is `.github/workflow-policy/trusted_workflow_policy.json`; the base validator is
`scripts/verify_trusted_workflow_policy.py`. Policy format version 3 protects 62 files as one indivisible
bundle. It includes every current workflow plus the validator itself. Its exact namespace inventories are:

- `.github/workflows/`: the seven current workflow files; additions, removals, renames, case variants,
  symlinks, executable blobs, gitlinks, or any other non-`100644 blob` entry fail closed.
- `.github/actions/`: empty; adding any repository-local Action file fails closed until a separately reviewed
  whole-policy rotation explicitly inventories and protects it.

The ordered protected set retains the existing release-control five:

- `.github/workflows/deploy.yml`
- `.github/workflows/build_app.yml`
- `.github/workflows/ota_contract.yml`
- `scripts/ota_contract_gate.py`
- `ota/requirements.txt`

The publisher-installed, fully hashed `ota/requirements.lock` is also a direct protected input. The policy does
not rely only on a workflow/gate assertion about that lock file: removal or any normalized byte change fails the
same complete-bundle digest decision before a secret-bearing publisher can run.

It also includes `personal_installation_firmware.yml`, `protocol.yml`,
`trusted_workflow_policy.yml`, and `scripts/verify_trusted_workflow_policy.py`, followed by the exact 52
backend and operations inputs authorized for PR #67: the backend-security
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

Policy format version 3 retains the two version-2 authorization modes and adds exact protected namespace
inventories; there is no implicit fallback:

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

PR #102 completed the previous rotation, and later documentation-only descendants retained its protected
bytes through H5 main `6517caa957dcf1c42ece49d15e38a428c81262e5`. The exact OTA runtime-fix candidate
`d4a3da40b4b6772bb1edcd4583eeb59951d6e7f6` replaced the ESP32-C6 manifest verifier's unavailable PSA
Ed25519 provider with the linked runtime provider, exposed bounded OTA rejection diagnostics, and updated the
authenticated recovery response. The protected `deploy.yml` pins those production-build inputs and has
normalized digest `f8bb1ce2bd89ef8a81d7062aeda843dee2376c19546db0b2e9cb80f0df172bb1`.

PR #106 separately authorized that exact feature commit plus later same-byte descendants and was merge-commit
merged as main `1088dcfb9afcc13d6a8408b5c1a5e6ff373072ff`. The feature branch then merged trusted
main into the reviewed commit without rebasing or squashing, producing policy-connected head
`81a42cf0b57e1830f27a5e88b5d2d15c8d33f451`. PR #105 retained both parents, received fresh green
checks, and was merge-commit merged as main `02090c31b6813d6d1691262809dfc86330283a9d`.

This final rotation removes both `d4a3da4` transition identities and pins the sole
`current-main-baseline` persistent identity to that actual merged-main commit. The reviewed feature and
policy-connected head are both ancestors of the merge. All 62 protected Git objects are unchanged from the
reviewed feature through merged main; the ordered digest map, seven-workflow inventory, and empty local-Action
inventory therefore remain exact.

Regression tests pin the exact repository, final merged-main SHA, sole baseline ID and mode, ordered 62-path
set, exact workflow/action inventories, and every digest. They require explicit ancestry for later descendants
and reject the retired feature source. They also reject an extra bundle, fork,
retired or altered commit, unproven/diverged history, case/path variant, old five-path partial set, missing or
reordered path, swapped/mixed/per-file digest mutation, truncated/malformed Git trees, workflow/action
additions, removals, renames, executable blobs, symlinks and gitlinks. No branch, wildcard, partial set, mixed
set, candidate-derived digest, or transition identity is approved. This authorization boundary is not production,
physical, release, NAS, deployment, install, reboot-health, or rollback evidence.

## 3. Why PR self-modification does not authorize itself

A PR may show edits to the policy, validator, or workflow, but the running `pull_request_target` job comes
from the default branch and explicitly loads the policy and validator from the trusted base SHA. The base
validator fetches only paths and inventories declared by that base policy. Candidate copies of the policy or
validator are never imported, parsed, or executed. The candidate validator is additionally a protected byte
input, so modifying it requires an explicitly approved complete bundle rather than silently changing future
verification behavior.

The policy JSON remains a self-policy boundary: its candidate copy is not used for the current decision, but a
merged change governs later PRs. It therefore still requires an independently reviewed, bounded transition and
an immediate final baseline rotation. There is also a status-context boundary: this repository-local policy
cannot by itself prove that branch protection accepted this exact workflow/event rather than another producer
of the same required-check context. Closing that residual circularity requires an externally controlled or
separately app-pinned status identity and repository policy outside the mutable workflow namespace.

PR #68 and PR #69 established the identity-bound schema version 2 validator and bounded transition on trusted
main; later protected bundles completed the same sequence, including PR #86/#85 and PR #100/#101. PR #106 was
the bounded policy-only authorization for this rollout, and PR #105 integrated that trusted main without
rewriting history. The final rotation changes only policy data, regression tests, this guide, and the
append-only log. It does not modify the validator, trusted workflow, or any other protected byte. Its hosted
check executes M2's transition policy from the trusted base and can admit this policy-only descendant only
because `d4a3da4` remains an ancestor and all 62 protected bytes are unchanged. A green Hosted Trusted check is
required before merge; no branch-protection change is authorized. That green check does not close the
version-3 self-policy or same-status-context producer residual.

## 4. Rotation procedure

The PR #28 transition used two steps: first merge the independently reviewed protected bytes through the
temporary approval, then rotate the policy in this separate policy-only change to the actual merged-main
commit. Future protected-file changes must follow the same separation: independently review an exact full
bundle, merge only through trusted-base authorization, then use a separate policy-only PR to remove any
temporary approval and pin one current-main baseline. Never add a wildcard, branch name, partial-file
exception, mixed bundle, or candidate-derived digest.

The OTA Ed25519 runtime-fix sequence was: H5 base `6517caa`, reviewed feature `d4a3da4`, PR #106 authorization
merge `1088dcf`, policy-connected feature head `81a42cf`, and PR #105 merge commit `02090c3`. The protected
objects and both inventories were rechecked after the ancestry connection, and the feature was never rebased
or squashed.

This separate final policy-only rotation starts from that actual merged main, removes both transition
identities, and pins one `persistent-baseline` named `current-main-baseline` to `02090c3` with the same 62-file
map. The transition persistent baseline admits this rotation only when GitHub Compare proves ancestry and every
protected byte is unchanged. After merge, verify final-main policy selection and both OTA publishers. Any path,
digest, repository, or reviewed source-commit change requires a fresh whole-bundle review; never prolong the
transition window or reuse a retired transition identity.

Issue #23 remains open and OTA-G1 through OTA-G4 physical/operator evidence remains pending throughout any
policy rotation.

## 5. Scope and OTA status

This policy expands a repository authorization boundary only. It does not itself modify any protected workflow,
backend/product/runtime file, dispatch a workflow, or write to a NAS. It does not change the authenticated mobile
`manual_remote` door-open path, firmware/app runtime code, dual OTA partitions, health/rollback, periodic
HTTPS, authenticated local recovery, mobile updater independence, N/N-1 compatibility, signing trust, or
artifact verification. No physical OTA evidence is claimed.
