# Trusted workflow policy bootstrap

## 1. Trust boundary

`.github/workflows/trusted_workflow_policy.yml` uses `pull_request_target` without `paths` or `paths-ignore` filters to prevent required-check deadlocks, ensuring `Verify protected files against trusted base policy` runs on all pull requests targeting `main` (including docs-only PRs). It never checks out or executes pull-request code. The workflow checks out only the trusted `base.sha` with credentials disabled and sparse paths limited to the base validator and policy. Candidate protected files are downloaded from the candidate repository and commit through the GitHub Contents API, decoded as inert bytes, normalized, and hashed. The same immutable candidate SHA is also read through GitHub's recursive Git Trees API so path inventory, Git object type, and mode are checked without checking out candidate code; a missing or truncated tree fails closed.

The job has only `contents: read`. Pull-request titles, branches, file contents, and other attacker-controlled values are never interpolated into an executable command. The actual head repository and immutable lowercase 40-hex head SHA are passed as separate quoted environment variables. The production decision validates both values, selects only bundles whose explicit source mode authorizes that identity, and only then downloads candidate bytes.

## 2. Protected bundle decision

The machine-readable policy is `.github/workflow-policy/trusted_workflow_policy.json`; the base validator is
`scripts/verify_trusted_workflow_policy.py`. Policy format version 3 protects 69 files as one indivisible
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
`trusted_workflow_policy.yml`, and `scripts/verify_trusted_workflow_policy.py`, followed by the exact 59
backend and operations inputs authorized for PR #67: the backend-security
workflow, Orca setup input, commercial-operations gate, evidence/SLO fixtures and policies, backend runtime,
locked dependencies, static admin surfaces, production Compose and database migration inputs, SBOM/supply
chain policy, backend tests, and canonical protocol vectors. The JSON policy contains the authoritative
complete ordered path set. The six feature inputs are the ACL refresh, Home Assistant bridge and Target
ACL-delivery modules plus their three direct tests. The final rotation also protects
`backend/app/static/admin_login.html`, which handles the personal administrator credential and had been the
only path missing from the policy's backend/operations suffix. Regression tests now require that suffix to
equal `ops/backend_trusted_bundle_paths.json` exactly, including order.

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

The completed weak-link transition and its final policy rotation were connected into main
`380d013e819cd013c17253161d664cc69c6e7402`. Reviewed PR #115 feature commit
`23a3f3ed8fac513f1b7f88962e561cfd376f7ea2` stabilizes the ESP32-C6 recovery AP with bounded quiet,
station-attempt, authenticated-request and local-upload radio ownership while preserving dual-slot OTA,
MQTTS and authenticated local recovery. Relative to that base, only one protected path changed:

- `.github/workflows/deploy.yml` becomes normalized SHA-256
  `5d7a72e774b1c2df0b08c1feea9156568d4f057902d6a74c7f0055b40df36eb3`. Its production build tree adds
  reviewed LF `include/RecoveryRadioPolicy.h` at SHA-256
  `3e25df300a313b8081e0c1bbba8b43e04aa5d8d439226c303d560d24e801ff79` and updates
  `src/WifiManager.cpp` to SHA-256
  `9f71191acdb9d068503f02feddf27d40b12f4fcbcf83b86a5df2e88c1439f1c3`.

PR #116 separately authorized that exact feature commit plus later same-byte descendants and was merge-commit
merged as main `5198b8aca401dc73c01137a4ab8efda3ae590dac`. The feature branch then merged trusted main into the
reviewed commit without rebasing or squashing, producing policy-connected head
`aa9fe818482e5a2f7aaaee7471d3e5248624287b`. PR #115 retained both parents and was merge-commit merged as
main `539844ecead1576afd54518bb8db63eb3ec72422`.

This final rotation removes both `23a3f3ed` transition identities and pins the sole `current-main-baseline`
persistent identity to that actual merged-main commit. The reviewed feature and policy-connected head are both
ancestors of the merge. All 62 protected Git objects are unchanged from the reviewed feature through merged
main; the ordered digest map, seven-workflow inventory and empty local-Action inventory therefore remain exact.

The recovery-AP final policy was then merge-commit merged as main
`5444ced107cdacbaf47bad1aca683f0e4694285c`. Exact-main Target runs `32679358174` and `32679992103`
passed the secret-free canary but failed closed before Secret materialization because the new
`RecoveryRadioPolicy.h` inventory row did not match `git ls-files` byte order. Reviewed PR #118 commit
`7021150d57aa6ceffec6a69e12cdf12cc88c548f` swaps only the two existing inventory rows and adds an
unprotected order/membership regression. Relative to current main, the only protected byte change is:

- `.github/workflows/deploy.yml` becomes normalized SHA-256
  `7f26fe2b5250927304cf2f4be5a6c5fa3e110429602f870c05ae991410fa4b1e`.

PR #119 separately authorized that exact feature commit plus later same-byte descendants and was merge-commit
merged as main `b23a13a1e17d6c4c7028fc6995999fcc54e5e464`. The feature branch then merged trusted main into the
reviewed commit without rebasing or squashing, producing policy-connected head
`cd625503ce1382704cecd0a715334c98ed18d85e`. PR #118 retained both parents and was merge-commit merged as
main `6ca977f71f19a9b2017bc51922b5fc808a8e5d2c`.

This final rotation removes both `7021150d` transition identities and pins the sole `current-main-baseline`
persistent identity to that actual merged-main commit. The reviewed feature and policy-connected head are both
ancestors of the merge. All 62 protected Git objects are unchanged from the reviewed feature through merged
main; the ordered digest map, seven-workflow inventory and empty local-Action inventory therefore remain exact.

Reviewed feature PR #123 commit `47f7e111ed3c8f625dad09597af3426f8204930d` enables the personal-production
Hardwareless GATT and signed Backend-owned Home Assistant control paths. Relative to the predecessor baseline,
23 protected files were changed or newly protected, including the six new module/test paths above. PR #124
authorized that exact commit plus later same-byte descendants and was merge-commit merged as policy main
`fdf9d695c1c3462b044063a083aa70f4a662b085`. The feature then merged trusted main without rebasing or
squashing as policy-connected head `5eb8b2154671d50e5f03dfcb723e0c13c48376c2`; all required checks passed,
and PR #123 was merge-commit merged as main `374043426b560108b30cb954fc15d658a56631a2`.

This final rotation removes both `47f7e111` transition identities and pins the sole
`current-main-baseline` persistent identity to actual merged main `37404342`. It expands the indivisible set
from 68 to 69 by protecting the previously omitted administrator-login surface; the other 68 protected Git
objects are unchanged from the reviewed feature through merged main. Regression tests pin the exact repository,
merged-main SHA, sole baseline ID and mode, ordered 69-path set, complete map, exact backend/operations suffix
and exact workflow/action inventories. They require explicit ancestry for later descendants and reject every
retired source commit. They also reject an extra bundle, fork, altered commit,
unproven/diverged history, case/path variant, old five-path partial set, missing or reordered path,
swapped/mixed/per-file digest mutation, truncated/malformed Git trees, workflow/action additions, removals,
renames, executable blobs, symlinks and gitlinks. No branch, wildcard, partial set, mixed set, or
candidate-derived digest is approved. This authorization boundary is not production, physical, release, NAS,
deployment, install, reboot-health, or rollback evidence.

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
main; later protected bundles completed the same sequence, including PR #86/#85, PR #100/#101,
PR #106/#105 and PR #113/#112. PR #116/#115/#117 completed the recovery-AP rollout, PR #119/#118 completed the
Target build-order correction, and PR #124/#123 completed the personal GATT and signed HA feature merge. This
final rotation starts from exact merged main `374043426b560108b30cb954fc15d658a56631a2` and changes only policy
data, regression tests, this guide and the append-only log. It does not modify the validator, trusted workflow
or any of the 68 paths protected by the base policy. Its hosted check executes merged main's `47f7e111`
transition policy and can admit this policy-only descendant because all 68 predecessor-protected bytes are
unchanged. The new 69th path is independently pinned to the exact merged-main Git object and cross-checked
against the trusted backend inventory. A green Hosted Trusted check is required before merge; no
branch-protection change is authorized. That green check does not close the version-3 self-policy or
same-status-context producer residual.

## 4. Rotation procedure

The PR #28 transition used two steps: first merge the independently reviewed protected bytes through the
temporary approval, then rotate the policy in this separate policy-only change to the actual merged-main
commit. Future protected-file changes must follow the same separation: independently review an exact full
bundle, merge only through trusted-base authorization, then use a separate policy-only PR to remove any
temporary approval and pin one current-main baseline. Never add a wildcard, branch name, partial-file
exception, mixed bundle, or candidate-derived digest.

The recovery-AP sequence was: base `380d013e`, reviewed feature `23a3f3ed`, PR #116 authorization merge
`5198b8ac`, policy-connected feature head `aa9fe818`, and PR #115 merge commit `539844ec`. The protected
objects and both inventories were rechecked after the ancestry connection, and the feature was never rebased
or squashed.

The recovery-AP final rotation pinned `current-main-baseline` to `539844ec` and was merged as `5444ced1`.
For the build-order correction, PR #119 authorized exact feature `7021150d`; trusted policy main `b23a13a1` was
then merged into that feature as `cd625503`, and fresh Hosted Trusted, OTA contract and ESP32-C6 canary checks
passed before PR #118 merge-commit produced main `6ca977f7`. This rotation immediately replaces both order-fix
transition identities with one `current-main-baseline` pinned to that actual merge. The exact final-main Target
publisher must still pass its privileged inventory check, production build, signed encrypted NAS publication
and public readback. Any path, digest, repository or reviewed source-commit change requires a fresh whole-bundle
review; never prolong the transition window or reuse a retired transition identity.

For PR #123, PR #124 first authorized exact feature `47f7e111`; trusted policy main `fdf9d695` was then merged
into the feature as `5eb8b215`, and fresh Hosted Trusted, OTA, Backend, Android and ESP32-C6 checks passed before
PR #123 merge-commit produced main `37404342`. This rotation replaces both transition identities with one
`current-main-baseline` pinned to that actual merge and closes the administrator-login inventory mismatch as
the 69th protected path. Production Secret materialization, NAS publication and device installation remain
separately observed deployment steps after this policy rotation.

PR #126 reviewed feature commit `4538fcb184d77f92991063f93dc4d875ba1e870f`
corrects the Target's iBeacon company-byte serialization and the Backend's paho
MQTTv5 connect callback. Relative to exact main `7c2764a1`, exactly three of the
69 protected normalized blobs change: `deploy.yml`, `backend/app/main.py` and
`backend/tests/test_target_boot_registry.py`. This bounded authorization uses
one temporary-exact identity and one future persistent identity with identical
complete 69-file maps. After its separate policy PR merges, policy main must be
merge-connected into the exact feature without rebasing or squashing. A final
policy-only rotation must then remove both transition identities and pin the
actual PR #126 merged-main commit as the sole baseline.

Issue #23 remains open and OTA-G1 through OTA-G4 physical/operator evidence remains pending throughout any
policy rotation.

## 5. Scope and OTA status

This policy expands a repository authorization boundary only. It does not itself modify any protected workflow,
backend/product/runtime file, dispatch a workflow, or write to a NAS. It does not change the authenticated mobile
`manual_remote` door-open path, firmware/app runtime code, dual OTA partitions, health/rollback, periodic
HTTPS, authenticated local recovery, mobile updater independence, N/N-1 compatibility, signing trust, or
artifact verification. No physical OTA evidence is claimed.
