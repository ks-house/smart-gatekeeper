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

The completed PR #85 rotation historically contained exactly one authorization for the then-current 57-file
set. The version-3 migration expands that same persistent authorization model to the current 62-file set and
keeps the existing source commit as the ancestry anchor.
`current-main-baseline` is a `persistent-baseline` for repository `ks-house/smart-gatekeeper` at exact merged
main commit `2d6b046b62d53381181d5c4bd8c25a9e781e42d1`. The temporary `temporary-pr85-d754f23` and transition
`future-pr85-persistent-baseline` identities are removed. A current candidate must retain every protected byte,
match both exact namespace inventories, and prove that it descends from this exact source through GitHub
Compare. Because some newly protected paths were introduced after that historical source, the source remains
an ancestry anchor rather than a claim that its old tree itself satisfies the expanded version-3 inventory.

The original 57 `utf8-lf-v1` digests were recomputed from the exact PR #85 Git object bytes. The five newly
protected existing files, including `ota/requirements.lock`, were independently normalized and hashed from the
current migration tree. Eight
historical protected files differed
from the current baseline: `ops/backend_trusted_bundle_paths.json`, `backend/.env.example`,
`backend/app/admin_security.py`, `backend/app/main.py`, `backend/app/static/admin.html`,
`backend/app/static/index.html`, `backend/docker-compose.yml`, and
`backend/tests/test_admin_security.py`. The final baseline map is byte-identical to both transition identities;
this authorization boundary is not production, physical, release, NAS, or deployment evidence.

Regression tests pin the exact repository, source ancestry anchor, sole-bundle count and mode, ordered 62-path
set, exact workflow/action inventories, and every digest. They reject an extra bundle, fork, retired or altered
commit, unproven/diverged history, case/path variant, old five-path partial set, missing or reordered path,
swapped/mixed/per-file digest mutation, truncated/malformed Git trees, workflow/action additions, removals,
renames, executable blobs, symlinks and gitlinks. No temporary identity, branch, wildcard, partial set, mixed set,
candidate-derived digest, transition identity, or second baseline is approved.

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
main; later protected bundles completed the same bounded sequence. PR #86 authorized PR #85's whole protected
bundle, and PR #85 integrated that policy once before merging as exact main
`2d6b046b62d53381181d5c4bd8c25a9e781e42d1`. This final rotation changes only policy data, regression tests,
this guide, and the append-only log. It does not modify the validator or trusted workflow. Its hosted check
executes the trusted-base transition policy, which admits this descendant because all 57 protected bytes remain
unchanged. A green Hosted Trusted check is required before admin merge; no branch-protection change is authorized.
That historical green check is not evidence that the version-3 self-policy/status-context residual is closed.

## 4. Rotation procedure

The PR #28 transition used two steps: first merge the independently reviewed protected bytes through the
temporary approval, then rotate the policy in this separate policy-only change to the actual merged-main
commit. Future protected-file changes must follow the same separation: independently review an exact full
bundle, merge only through trusted-base authorization, then use a separate policy-only PR to remove any
temporary approval and pin one current-main baseline. Never add a wildcard, branch name, partial-file
exception, mixed bundle, or candidate-derived digest.

For PR #85, the transition policy was merged separately as PR #86, PR #85 integrated that exact main once
without rewriting history, retained the complete authorized 57-file map, received fresh hosted checks, and then
merged as exact main `2d6b046b62d53381181d5c4bd8c25a9e781e42d1`. GitHub Compare proved the required
candidate ancestry throughout that sequence.

This separate final policy-only rotation removes both PR #85 transition identities and pins the sole
`persistent-baseline` named `current-main-baseline` to that actual merged-main 57-file bundle. The trusted-main
transition baseline admits this final rotation only when GitHub Compare proves ancestry and every protected byte
is unchanged. After merge, verify current-main policy selection and main CI. Any path, digest, repository, or
reviewed source-commit change requires a fresh whole-bundle review; never prolong the transition window or reuse
a retired transition identity.

Issue #23 remains open and OTA-G1 through OTA-G4 physical/operator evidence remains pending throughout any
policy rotation.

## 5. Scope and OTA status

This policy expands a repository authorization boundary only. It does not itself modify any protected workflow,
backend/product/runtime file, dispatch a workflow, or write to a NAS. It does not change the authenticated mobile
`manual_remote` door-open path, firmware/app runtime code, dual OTA partitions, health/rollback, periodic
HTTPS, authenticated local recovery, mobile updater independence, N/N-1 compatibility, signing trust, or
artifact verification. No physical OTA evidence is claimed.
