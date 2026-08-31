# Trusted workflow policy bootstrap

## 1. Trust boundary

`.github/workflows/trusted_workflow_policy.yml` uses `pull_request_target` without `paths` or `paths-ignore` filters to prevent required-check deadlocks, ensuring `Verify protected files against trusted base policy` runs on all pull requests targeting `main` (including docs-only PRs). It never checks out or executes pull-request code. The workflow checks out only the trusted `base.sha` with credentials disabled and sparse paths limited to the base validator and policy. Candidate protected files are downloaded from the candidate repository and commit through the GitHub Contents API, decoded as inert bytes, normalized, and hashed. The same immutable candidate SHA is also read through GitHub's recursive Git Trees API so path inventory, Git object type, and mode are checked without checking out candidate code; a missing or truncated tree fails closed.

The job has only `contents: read`. Pull-request titles, branches, file contents, and other attacker-controlled values are never interpolated into an executable command. The actual head repository and immutable lowercase 40-hex head SHA are passed as separate quoted environment variables. The production decision validates both values, selects only bundles whose explicit source mode authorizes that identity, and only then downloads candidate bytes.

## 2. Protected bundle decision

The machine-readable policy is `.github/workflow-policy/trusted_workflow_policy.json`; the base validator is
`scripts/verify_trusted_workflow_policy.py`. The current backend-NAS authorization candidate expands policy
format version 3 from 69 to 82 files as one indivisible
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
`trusted_workflow_policy.yml`, and `scripts/verify_trusted_workflow_policy.py`, followed by the exact 72
backend and operations inputs in `ops/backend_trusted_bundle_paths.json`: the backend-security
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

PR #127 merged the bounded authorization as policy main `a1f8e4dc`. That policy
main was merge-connected to the reviewed feature as `b590c410`, preserving both
parents and the exact reviewed 69-file map. After all fresh Hosted Trusted, OTA,
Backend and ESP32-C6 checks passed, PR #126 was merge-commit merged as actual
main `900f22179db54b50aba03fba519ac80266519c2d`. The immediate final rotation
removes both `4538fcb` transition identities and pins that actual merge as the
sole `current-main-baseline`; all 69 protected normalized objects remain exact.

Reviewed GATT stack candidate `df2ac4869f4ee15c567f4a5ce1e0a99fab08e269`
moves authentication control and heavy telemetry work out of the constrained
NimBLE callback context and serializes Android Challenge delivery. Relative to
exact main `bc9bb5dae2d1ca49ef38c8c2d89122084d4b6909`, only the protected
`.github/workflows/deploy.yml` blob changes, to normalized digest
`26d9fc567b7465fc3fcb42c84a85db531b3fb9a227d4fa5432799aba0d86b478`;
the other 68 protected objects and both exact inventories remain unchanged.
The bounded transition uses `temporary-gatt-stack-df2ac48` and
`future-gatt-stack-df2ac48-persistent-baseline`, with the same complete ordered
69-file map and exact source commit. After this policy-only authorization
merges, policy main must be merge-connected into that reviewed feature without
rebasing or squashing. A separate final rotation must then replace both
transition identities with the sole baseline pinned to the actual feature
merge commit.

PR #130 merged the bounded authorization as policy main `813a849f`. That
policy main was merge-connected to the reviewed feature as `4baa3fa8`, retaining
both parents and the reviewed 69-file map. Fresh Hosted Trusted, OTA, protocol,
Android and ESP32-C6 checks then passed before PR #129 was merge-commit merged
as actual main `a9d4bd0de7cf5393cba47b8be1fa6c17c0b6759e`. This immediate
final rotation removes both `df2ac48` transition identities and pins that actual
merge as the sole `current-main-baseline`; all 69 protected normalized objects,
the seven-workflow inventory and the empty local-Action inventory remain exact.

Issue #23 remains open and OTA-G1 through OTA-G4 physical/operator evidence remains pending throughout any
policy rotation.

The per-phone resident identity candidate `d23933d7780f0100b99ddcf38fcfa426b17e9b06`
changes exactly two protected Backend blobs:
`backend/app/acl_management.py` (`681c2d83...a49266`) and
`backend/tests/test_acl_api.py` (`c89a7be1...d356`). The complete 88-path
bundle is authorized only for that exact reviewed commit and its proven
same-repository descendants with identical protected bytes. This does not
weaken request authentication, ACL signatures, OTA, deployment health, backup,
rollback, host-key or NAS access controls, and it is not deployment or
installed-phone evidence.

Issue #265 / PR #266 reviewed feature commit
`c80933a411990022bf14b075b18260a127cb590c` adds the credential-bound
personal mobile status/activity contract and native user Home. Relative to the
current baseline, exactly four protected Backend blobs change:
`backend/app/acl_api.py` (`a262c8f6...`),
`backend/app/acl_management.py` (`4c703860...`),
`backend/app/static/index.html` (`4423c3e0...`) and
`backend/tests/test_acl_api.py` (`c478d95f...`). The other 79 protected blobs
and both namespace inventories remain exact. This policy-only authorization
uses `future-mobile-ux-p0-c80933a-persistent-baseline`; after it merges, policy
main must be merge-connected into PR #266 without rebasing or squashing and all
fresh checks must pass. A final policy-only rotation must then pin the actual
feature merge as the sole `current-main-baseline`.

This authorization changes no NAS runtime, deploys no Backend, publishes or
installs no APK/firmware and claims no connected or physical result.

Reviewed issue #133 candidate `91858585f8db6fb1b8b50ca0182526fdb653f0bf`
adds the authenticated action-2 manual local-open path and updates the
privileged Target source inventory. Relative to exact main
`db37bc2390efbf94bf1a9fca261834c3728606b5`, only the protected
`.github/workflows/deploy.yml` blob changes, to normalized digest
`e46ba83350633b13fd13ad5f5fdee2024481d2eab4857bca3f231a2ad003d409`;
the other 68 protected blobs, seven-workflow inventory and empty local-Action
inventory remain exact. The bounded transition uses
`temporary-manual-open-9185858` and
`future-manual-open-9185858-persistent-baseline` with the same complete map.
After this policy-only PR merges, its main commit must be merge-connected into
PR #135 without rebasing or squashing; a separate rotation then pins the actual
feature merge as the sole baseline.

PR #137 merged the bounded authorization as policy main `26bed3df`. That
policy main was merge-connected to the reviewed feature in `bba7bf4d`, retaining
both parents and the reviewed 69-file map. Fresh Hosted Trusted, OTA, protocol,
Android and ESP32-C6 checks then passed before PR #135 was merge-commit merged
as actual main `737d3243af04d18e0c3f5c5b8e2c8435d177ac2c`. The immediate
issue #138 rotation removes both `9185858` transition identities and pins this
actual merge as the sole `current-main-baseline`; all 69 normalized protected
objects and both exact inventories remain unchanged from the reviewed feature.

Reviewed issue #143 / PR #144 candidate
`9565f67cf16d78342ac7ebbb9035a5517bd5cdb2` moves authenticated GATT
action effects out of the ESP32-C6 FreeRTOS critical-section spinlock and binds
the changed `src/GattServer.cpp` normalized digest into the privileged Target
build inventory. Relative to exact main
`b6cf6ec1a725e734d67df1ae8729e02f3ade0a9c`, only protected
`.github/workflows/deploy.yml` changes, to normalized digest
`76325aac1a37b982f3efd2f317a4ed85af6939c3120a616468e15b7a33320b7f`;
the other 68 protected blobs and both inventories remain exact. Issue #145
authorizes this bounded candidate through
`temporary-gatt-action2-9565f67` and
`future-gatt-action2-9565f67-persistent-baseline`, each with the same complete
ordered map. After this policy-only PR merges, its main merge commit must be
merge-connected into PR #144 without rebasing or squashing. A separate final
rotation must then pin the actual feature merge as the sole baseline.

PR #146 merged the bounded authorization as policy main `fcb6731f`. That
policy main was merge-connected to the reviewed feature as `22c73bf4`, retaining
both parents and the reviewed 69-file map. Fresh Hosted Trusted, OTA contract
and ESP32-C6 canary checks passed before PR #144 was merge-commit merged as
actual main `ff3535a34df004aca296cabd5f4b69ecb698f2a3`. Issue #147 now
removes both `9565f67` transition identities and pins that actual merge as the
sole `current-main-baseline`; the normalized protected map and inventories do
not change from the reviewed feature.

## 5. Scope and OTA status

PR #150 passed fresh Hosted Trusted, OTA contract, ESP32-C6 and Android canary
checks after policy main `9ec55ed8` was merge-connected, then merged as actual
main `b637b046ca94f0be6e874029818d253c3d1b9978`. Issue #153 removes both
bounded `0427181` transition identities and pins that actual merge as the sole
`current-main-baseline`. The complete 69-file normalized protected map and both
inventories remain byte-for-byte identical to the reviewed feature bundle.
This rotation changes no runtime/workflow protected byte and does not claim
production OTA or connected action-1 acceptance.

Issue #151 authorizes immutable issue #149 / PR #150 feature commit
`042718180e3943e8dd6e135a140e59763a602f8c`. The reviewed feature changes two
protected objects: `.github/workflows/deploy.yml` has normalized SHA-256
`61ce60093ce84b65c2a973f58ae903f7f115b1692a38cba8a88ccd3ba52f17e9`,
and `scripts/ota_contract_gate.py` has normalized SHA-256
`89be924d2293bad15d7e4386ee62d5427d69edbfab9e994e1150e12869e035c3`.
The other 67 protected objects, seven-workflow inventory and empty local-Action
inventory remain exact. The transition uses `temporary-nvs-0427181` and
`future-nvs-0427181-persistent-baseline` with the same complete ordered map.
After this policy-only PR merges, its main merge commit must be merge-connected
into PR #150 without rebasing or squashing. Fresh hosted CI must pass before
the feature merges, after which a separate rotation pins the actual feature
merge as the sole current baseline.

This authorization does not initialize or erase either NVS partition, build or
publish firmware, install a Target image, dispatch production secrets, or claim
screen-off action-1, ultrasonic, relay contact, health-valid or rollback
evidence.

Issue #162 authorizes immutable issue #160 / PR #161 feature commit
`748c2681a866c1330d8bfcfd8ecee11c75fbbea3`. The connected Target accepted the
signed exact-main manifest but failed the second TLS connection before artifact
download while the first manifest TLS client remained alive. The candidate
ends that client scope before allocating the artifact client and keeps CA
verification enabled. Relative to authorized main, only protected
`.github/workflows/deploy.yml` changes, to normalized SHA-256
`1b8bf00d885297ad5e4e90c3ae3fc712c91026eaed628a0023e913a1ec8a5582`;
the other 68 protected objects and both inventories remain exact.

The transition uses `temporary-ota-tls-748c268` and
`future-ota-tls-748c268-persistent-baseline` with the same complete ordered
map. After the policy-only PR merges, its main merge commit must be
merge-connected into PR #161. Fresh hosted checks must pass before the feature
merges, after which a separate policy rotation must pin the actual feature
merge as the sole current baseline. This authorization does not publish or
install firmware and does not claim OTA install/reboot/health, ultrasonic, or
physical relay-contact evidence.

PR #161 head `d994a7f0` passed fresh Hosted Trusted, OTA-contract and ESP32-C6
canary checks, then merge-commit merged as actual main
`17793de56289a9fe4f740b8b539aef97fb9182b2`. Issue #164 removes both bounded
`748c268` transition identities and pins that actual merge as the sole
`current-main-baseline`; the complete 69-file protected map and both
inventories remain unchanged from the reviewed candidate. This policy rotation
does not publish or install firmware. Issue #160 remains open until the
connected Target installs the exact-main artifact, reboots and restores
Wi-Fi/MQTTS/GATT/health.

This policy expands a repository authorization boundary only. It does not itself modify any protected workflow,
backend/product/runtime file, dispatch a workflow, or write to a NAS. It does not change the authenticated mobile
`manual_remote` door-open path, firmware/app runtime code, dual OTA partitions, health/rollback, periodic
HTTPS, authenticated local recovery, mobile updater independence, N/N-1 compatibility, signing trust, or
artifact verification. No physical OTA evidence is claimed.

Issue #168 authorizes immutable issue #166 / PR #167 feature commit
`db8d1fe861aeb8815badc7cbf03dd148a815f0d2`. Relative to current main, only
protected `.github/workflows/deploy.yml` changes, to normalized SHA-256
`bd1f5c0c2368bcc1b027c9b7823bda15112f281f7b9652f9b4b3b8082cb6e630`,
binding reviewed `src/OtaManager.cpp` digest `6b1d39f1...`. The other 68
protected objects and both inventories remain exact. The transition uses
`temporary-ota-keepalive-db8d1fe` and
`future-ota-keepalive-db8d1fe-persistent-baseline` with the same complete map.
This policy-only authorization does not publish or install firmware; policy
merge-connection, fresh feature CI, feature merge, final rotation and connected
OTA install/reboot/health recovery remain required.

PR #167 head `c6d2b85` passed fresh Hosted Trusted, OTA-contract and ESP32-C6
canary checks, then merge-commit merged as actual main
`c23793cbee1ba7cde4e03add4b1c944d8bf39032`. Issue #170 removes both bounded
`db8d1fe` transition identities and pins that actual merge as the sole
`current-main-baseline`; the reviewed 69-file map and both inventories are
unchanged. This policy-only rotation does not publish or install firmware, and
issues #160/#166 remain open until connected OTA install/reboot/health recovery.

Issue #177 authorizes immutable issue #175 / PR #176 feature commit
`388dcac079bbe3ddb04f35f7677b4692790f150b`. Relative to the current baseline,
only protected `.github/workflows/deploy.yml` changes, to normalized SHA-256
`17bd1df446bce0cbbf3f8d96f9c21979478d241ab29f25c1b02027e16698894f`.
The reviewed workflow pins the new `include/BleStartupPolicy.h` normalized
digest, the changed `src/main.cpp` digest and the complete sorted 42-file Target
build-input inventory before production secrets are reachable. The other 68
protected objects and both inventories remain exact.

The transition uses `temporary-ble-acl-388dcac` and
`future-ble-acl-388dcac-persistent-baseline` with the same complete ordered
map. After this policy-only PR merges, its main merge commit must be
merge-connected into PR #176 without rebasing or squashing. Fresh Hosted
Trusted, OTA-contract and ESP32-C6 checks must pass before the feature merges,
after which a separate policy rotation must pin the actual feature merge as the
sole current baseline. This authorization does not build, publish or install
firmware, access production secrets or NAS objects, or claim screen-off,
sensor, relay-contact, rollback or door evidence.

PR #176 head `902b53c` passed fresh Hosted Trusted, OTA-contract and ESP32-C6
canary checks, then merge-commit merged as actual main
`ed9ed2bb8d15d40db18db377ec72ba77f1b0de41`. Issue #180 removes both bounded
`388dcac` transition identities and pins that actual merge as the sole
`current-main-baseline`. The complete ordered 69-file protected map and both
inventories remain unchanged from the reviewed candidate. This rotation does
not build, publish or install firmware; exact-main NAS publication, Target OTA,
boot-order evidence, mobile repetition and physical sensor/contact checks stay
separate.

## 5. Backend Synology CI transition candidate

The final backend-NAS/OIDC feature commit is
`25562d1e1ae57bb52a8a0317de8d07a9a1365bef` on repository
`ks-house/smart-gatekeeper`. Bridge PR #187 first merge-connected the previously
approved 82-path bundle as main `087e918b7ed86b71c3c1a13908f94b1dc832251e`.
Relative to that bridged main, the final candidate changes exactly seven
protected objects. The
complete 82-file normalized map is duplicated exactly in two bounded
authorizations:

- `temporary-backend-nas-oidc-25562d1` admits only that exact repository and commit.
- `future-backend-nas-oidc-25562d1-persistent-baseline` admits only proven
  same-repository descendants retaining all 82 exact protected bytes.

The newly protected surface contains `backend/compose.synology.yml`, all eleven
`backend/deploy/` operational inputs and
`backend/tests/test_nas_backend_deploy.py`. The other changed protected objects
were admitted by the bridge. The final seven-path delta is the backend workflow,
commercial gate, deployment README, bootstrap, root wrapper, read-only verifier
and direct deployment test. It includes the manual exact-main status-only
Tailscale OIDC preflight with no signing, image publication or `apply` path.
Regression tests pin the ordered 82-path set, both source identities, all
normalized digests, exact workflow/action inventories and the seven-path delta.
The earlier `2cda04b` identities are retired.

This policy-only candidate must pass the hosted trusted check and merge first.
Its main merge commit must then be merge-connected into the immutable feature
branch without rebasing or squashing. Fresh feature CI must pass before any
feature merge. A final policy-only rotation must remove both transition
identities and pin the actual feature merge commit as the sole
`current-main-baseline`.

This authorization does not create or read GitHub Environment values,
materialize a secret, exchange an OIDC token, publish a GHCR image, open an SSH
session, migrate MariaDB, replace the legacy containers, change
router/NAS/Tailscale state or prove production readiness. Those remain
separately observed deployment Gates.

PR #188 merge-commit merged the final authorization as policy main `29cf3d0`.
That policy main was merge-connected into the immutable feature without
rebasing or squashing as `f5e2ed9`; after fresh hosted trusted, OTA and backend
checks passed, PR #186 merge-commit merged as actual main
`89e047c2416de6924ee4b7aff4daf4250d55f907`. This immediate final rotation
removes both `25562d1` transition identities and pins that actual merge as the
sole `current-main-baseline`. All 82 protected normalized objects and both
inventories remain exact. The separate status-only run `33199183911` passed,
but policy rotation and status reachability do not prove a release `apply`,
database migration, container cutover, readiness, rollback or physical access.

## 6. Target deferred OTA health transition candidate

Reviewed feature commit `2d3221ee54b9277bc3783811f17e12658fb93901`
prevents the Arduino core from auto-validating a newly booted OTA slot before
the application health policy can run. The protected surface expands from 82
to 83 paths by adding `src/OtaManager.cpp`; relative to the current main
baseline, only that source and `.github/workflows/deploy.yml` differ. Their
normalized SHA-256 values are respectively
`36f1db079f0ea65feb175c7fcf5d079b1e9952ad40e98607036874f252f3cea7`
and `649ff762b2baa9a57d3b8893b346f32abd094b77b77e16f216bd1b2ebf92284a`.

The transition duplicates the complete ordered 83-path map in exactly two
bounded identities: `temporary-target-ota-health-2d3221e` for the immutable
feature commit, and
`future-target-ota-health-2d3221e-persistent-baseline` for proven descendants
that retain every protected byte. After this policy-only PR merges, its exact
main merge commit must be merge-connected into PR #192 without rebase or
squash. Fresh Hosted Trusted, OTA-contract and ESP32-C6 checks are required
before merge. A separate policy-only rotation must then remove both transition
identities and pin the actual feature merge commit as the sole baseline.

This authorization is source and CI trust evidence only. It does not publish
or install firmware and does not prove the 30-second health window, VALID mark,
rollback, relay contact, sensor threshold or door movement; those remain
separate connected-device Gates.

PR #193 merge-commit merged the bounded authorization as policy main
`482f127e388318d53a0da7627036fde55f84114b`. That commit was merge-connected
into the immutable feature without rebase or squash as `b251218`; fresh Hosted
Trusted, OTA-contract and ESP32-C6 checks passed, then PR #192 merge-commit
produced actual main `a2f7ae2fc4bd1f4fa19839e1021d18cce85ad4fc`.
This immediate final rotation removes both `2d3221e` transition identities and
pins that actual merge as the sole `current-main-baseline`. The complete
ordered 83-path map, including newly protected `src/OtaManager.cpp`, and both
exact inventories remain unchanged.

The subsequent exact-main publication and connected rollback are operational
evidence, not policy authority. Rotation itself does not prove application
VALID, hard power-loss, relay contact, sensor threshold or door movement.

## 7. Action-2 ARMED replacement transition candidate

Reviewed immutable feature commit `828820da348afc509bc21ebd0b13f1c023563415`
for PR #198. It lets a fresh authenticated GATT session replace only a
sensor-waiting action-1 `ARMED` window so foreground action 2 can proceed,
while `RELAY_HOLD` and `COOLDOWN` stay fail-closed. Android also classifies
Target Hello status 2 as retryable `TARGET_BUSY`. Relative to current policy
main, the sole protected delta is `.github/workflows/deploy.yml`, normalized
SHA-256 `88cdf941157c778e626ace7977c2bdb2e860b50f5e21a3871b9b9cb2cd7dffea`;
it pins the matching `TargetAccessFsm` header/source build-input digests.

The complete ordered 83-path protected map is duplicated in exactly two
bounded identities: `temporary-action2-armed-828820d` for the immutable
feature commit and `future-action2-armed-828820d-persistent-baseline` for
proven descendants retaining every protected byte. After this policy-only PR
merges, its exact main merge commit must be merge-connected into PR #198
without rebase or squash. Fresh Hosted Trusted, OTA, Android and ESP32-C6
checks are required before feature merge, followed by an immediate final
policy rotation to the actual feature merge commit.

This authorization changes no runtime, artifact, Target, phone, NAS, database
or router state. It does not prove signed publication, installation, relay
command ON/OFF, physical relay contact/load, sensor threshold or door motion.

PR #200 passed hosted Trusted verification and merge-commit merged the bounded
authorization as policy main `2d18d694d28d548f1be4d383dd9c1550c3581932`.
That exact main was merge-connected into PR #198 without changing the reviewed
feature bytes. Fresh Trusted, OTA, Android and ESP32-C6 checks passed, then PR
#198 merge-commit produced actual main
`618220e106b0bc2eee5faba6485a54dd66a8b7c6`. This final rotation removes both
`828820d` transition identities and pins that actual merge as the sole
`current-main-baseline`; the ordered 83-path map and both inventories are
unchanged.

Policy completion remains authority evidence only. Signed exact-main Target
and Android publication/install plus connected action-1-followed-by-action-2
relay-command evidence are still required.

## 8. NAS first-adoption documentation transition candidate

Reviewed immutable PR #206 feature commit
`43c775969b082397ceb063e7ef929307a72d4b74`. It records the owner's
maintenance-window stop of only the two legacy containers and the exact-main
status preflight run `33234620284`; the change deliberately causes the
backend-main workflow to run after merge. Relative to current policy main, the
sole protected delta is `backend/deploy/README.md`, normalized SHA-256
`9940c34e4a6dc57b2fa27411fee4c5def1e24aaede8b7c1e4480a3d19770b33b`.
No executable backend, workflow, image, migration or deploy-wrapper byte is
changed.

The complete ordered 83-path protected map is duplicated in exactly two
bounded identities: `temporary-nas-first-adoption-43c7759` for the immutable
feature commit and
`future-nas-first-adoption-43c7759-persistent-baseline` for proven descendants
retaining every protected byte. After this policy-only PR merges, its exact
main merge commit must be merge-connected into PR #206 without rebase or
squash. Fresh Hosted Trusted, OTA and Backend checks are required before the
feature merge, followed by an immediate final policy rotation to the actual
feature merge commit.

This authorization changes no NAS runtime or database state and does not
approve the protected `production` environment. Deployment success still
requires the post-merge job to return `status=deployed`, exact `source_sha`,
matching status readback and HTTP readiness. Failure recovery remains starting
the untouched legacy `gatekeeper-db` and `gatekeeper-api` containers.

## 9. Synology Compose Docker-path correction candidate

Reviewed immutable PR #208 feature commit
`750a5456fae988c2595098dcec01f410c8941d4b`. It corrects the exact failure
observed in main deploy run `33235108484`: `compose_for_release` passed the
non-exportable shell function name `docker` to `env`, which could not resolve
an executable even though the wrapper had already selected Synology's absolute
Container Manager CLI. The feature invokes `"$DOCKER_BIN" compose` and adds a
source regression rejecting the bare form.

Relative to current policy main, exactly two protected normalized blobs change:

- `backend/deploy/sgk_backend_deploy.sh` becomes
  `5f108cc233fdab5194c4522b06fb9daa8436aef337a49136e838bcfd5177df8e`.
- `backend/tests/test_nas_backend_deploy.py` becomes
  `97fcdbcd25be718528f0241e6490ef11771535e856a8d7aacf6290456d1a5b18`.

The complete ordered 83-path map is duplicated in
`temporary-synology-docker-path-750a545` and
`future-synology-docker-path-750a545-persistent-baseline`. After this
policy-only PR merges, its main must be merge-connected into PR #208 without
rebase or squash, followed by fresh Trusted/OTA/Backend checks and an immediate
final baseline rotation after feature merge.

Policy authority and source correction do not update the root-owned installed
NAS wrapper. The owner must install exact corrected bytes before retrying the
protected deployment. Only `status=deployed`, exact `source_sha`, matching
status readback and loopback/public readiness can close the deployment Gate.

## 10. Synology Compose Docker-path final baseline

Policy PR #209 passed Hosted Trusted verification and merge-commit produced
policy main `095cb6ed317bea49957af9f8d8c36b8a35060a69`. That main was
merge-connected into PR #208 as `779ef1225842b4756173cf3fb673318cd553542c`,
preserving reviewed feature `750a5456fae988c2595098dcec01f410c8941d4b` as
the first parent. Fresh Trusted, OTA and Backend checks passed before PR #208
merge-commit produced actual main
`21a0124f6e4b5dfc300b205073e1b464066355e8`.

This final policy-only rotation removes both `750a545` transition identities
and pins the sole `current-main-baseline` to actual feature main `21a0124f`.
The complete ordered 83-path map, workflow/action inventories and the two
reviewed corrected wrapper/test digests remain unchanged.

Final rotation is authority evidence, not NAS installation or deployment
evidence. Exact-main run `33235596047` is retained at protected `production`
approval pending owner readback of the installed wrapper digest and the legacy
maintenance stop. Deployment and connected access Gates remain open.

## 11. Ephemeral GHCR pull-auth transition candidate

Reviewed immutable PR #211 feature commit
`7b549978239455f12620429ffc06a553a1a0dd41`. Exact-main run
`33235596047` proved the corrected Synology Docker path but failed closed on
the first private GHCR image pull with `unauthorized`; Compose and migration did
not run, and the retained legacy API/DB were restarted successfully.

The candidate grants only `packages: read` to the protected deployment job,
streams its short-lived `github.token` in a versioned stdin envelope, and keeps
Docker auth solely in the root-only per-attempt directory removed by the common
cleanup trap. It does not store a long-lived PAT on the NAS or include any
credential in the signed bundle artifact or deployment evidence.

Relative to the current protected baseline, exactly four normalized blobs
change as one indivisible candidate:

- `.github/workflows/backend_security.yml` becomes
  `ba723b29efd4e00f2849173bcd7ce43a8203eb3a6bd3fd3e060f997cce9d5bbb`.
- `backend/deploy/README.md` becomes
  `2a1a9277ec8b797ac2cc1776982f6a4a4a6711c1afaca7b83b4bd726e817af7d`.
- `backend/deploy/sgk_backend_deploy.sh` becomes
  `afda60b403988653ed92b0714fa25dc97980d1103c5709d0090fb49e9889ab7e`.
- `backend/tests/test_nas_backend_deploy.py` becomes
  `aba8b7803c4c94cbb2f7fafd15f84cd7f7ad7a3bcf0ba4d791740b02239ae594`.

The complete ordered 83-path map is duplicated in
`temporary-ephemeral-ghcr-auth-7b54997` and
`future-ephemeral-ghcr-auth-7b54997-persistent-baseline`. After this
policy-only PR merges, its main must be merge-connected into PR #211 without
rebase or squash, followed by fresh Trusted/OTA/Backend checks and an immediate
final baseline rotation after feature merge.

This policy change grants no production approval and changes no NAS file,
container, database, phone or Target state. Wrapper installation, a new owner
maintenance stop, protected deployment, exact source/status evidence,
loopback/public readiness and backend-included access E2E remain separate
Gates.

## 12. Ephemeral GHCR pull-auth final baseline

The corrected policy PR #213 merge-committed as
`c926a71dab78934719c3123fa68ad16b0edd5d9d` after an owner-approved one-time
administrator recovery. Only `enforce_admins` was temporarily disabled; it was
immediately restored with strict checking and the same required status context.
That main was merge-connected into immutable feature
`7b549978239455f12620429ffc06a553a1a0dd41` as PR #211 head
`35410f0b8f00c7a033f8952bcfd6d8d007199072`. Fresh Trusted, OTA and Backend
checks passed before feature merge-main
`42b754d75863072e4ad0af32f2667ff54ceb050c`.

This final rotation removes both `7b549978` transition identities and pins the
sole `current-main-baseline` to actual feature main `42b754d7`. The complete
ordered 83-path digest map, exact workflow/action inventories and reviewed
four-file GHCR-auth bundle remain unchanged.

Final policy authority is not NAS installation or deployment evidence. The
root-owned NAS wrapper must match `afda60b403988653ed92b0714fa25dc97980d1103c5709d0090fb49e9889ab7e`
before a new maintenance stop and protected apply. Only exact source/status and
loopback/public readiness can close the backend deployment Gate.

## 13. DSM backend compatibility transition

The first authenticated feature-main deployment failed before migration after
starting the new DB because the DS423+ DSM kernel rejects Docker's nonzero
`NanoCPUs` field. Immutable feature commit
`e787786f2514c641e02dd5608d0fe21c4476eca4` corrects that host compatibility,
partial-project cleanup and the Tailscale action checksum input.

Relative to the current protected baseline, exactly five normalized blobs
change as one indivisible candidate:

- `.github/workflows/backend_security.yml` becomes
  `f48e242ba34d1ccdfe58faf95859e9d6b18af4ad947a9e9319317d187a054efb`.
- `backend/compose.synology.yml` becomes
  `fa0f88acdfd0c6de87b6fde278804c673f18f07a099e5844d2b21ac10be451a2`.
- `backend/deploy/README.md` becomes
  `a7dad4437568d8c76a1ffe96dac9011565a1952fdc4f4bc0f29b9b1fc709293e`.
- `backend/deploy/sgk_backend_deploy.sh` becomes
  `6a29bf87f1e5b91050cc37c5bcff260564e95abd41dd8749d37a8f63514cf805`.
- `backend/tests/test_nas_backend_deploy.py` becomes
  `f79ba51e87045e1731542602a588c6f2f63aebcc1dad64497b1f39a0714f64bd`.

The complete ordered 83-path map is duplicated in
`temporary-dsm-backend-compat-e787786` and
`future-dsm-backend-compat-e787786-persistent-baseline`. After this policy-only
PR merges, its exact main must be merge-connected into feature PR #215 without
rebase or squash. Fresh Trusted, OTA and Backend checks remain mandatory, and
the policy must rotate again to the actual feature merge-main.

This transition changes no NAS file, container, volume or database and grants
no production approval. Legacy recovery, root-owned wrapper installation, a
new maintenance stop, protected deploy, exact source/status/readiness and the
backend-included access E2E remain separate Gates.

## 14. DSM backend compatibility final baseline

Policy-connected feature PR #215 head
`a581e370fc0895041792cdc7c975a83aa6bf19e3` passed fresh Hosted Trusted, OTA P0
and Backend checks. Merge commit
`6b1f1da3359dcca95c8434b73970ba992ef9d41d` is the actual feature main.

This final rotation removes both bounded `e787786` transition identities and
pins the sole `current-main-baseline` to actual feature main `6b1f1da3`. The
complete ordered 83-path map, workflow/action inventories and five reviewed
DSM compatibility digests remain unchanged.

Final policy authority is still source/CI evidence only. It does not recover
legacy containers, install the root-owned wrapper, approve production, migrate
the DB, prove readiness or complete the backend-included access E2E.

## 15. DSM NanoCPUs field-removal transition

Protected run `33241850366` disproved the earlier assumption that Synology
Compose v2.20.1 treats `cpus: 0` as field deletion. DSM preserved it as a
Docker `NanoCPUs` request and failed before migration, although the installed
wrapper then removed the partial production stack without deleting volumes.

Immutable feature commit
`5a32570a8ec08a2433601dd29ff6ff9c4b31d44d` removes `cpus` from both signed
Compose inputs. Relative to the current protected baseline, exactly four
normalized blobs change as one indivisible candidate:

- `backend/compose.production.yml` becomes
  `8d094aeef780db18d0b97e14ee845dc05eec8bdb8b2df00fa077a3fbc40b6702`.
- `backend/compose.synology.yml` becomes
  `1d93e3bf87a950d6e7a38e8412c79d7f1dada7dce76da89f5a4678656003e1a4`.
- `backend/deploy/README.md` becomes
  `9ffd1f09bd60b2adbd6814dabf35b797d9ecacdaaf78758c99f40583e78a0125`.
- `backend/tests/test_nas_backend_deploy.py` becomes
  `9701fb18f0f5a51374f97a74d47e45c80a3d585adcef741fb949bad5fb026687`.

The complete ordered 83-path map is duplicated in
`temporary-dsm-nanocpus-removal-5a32570` and
`future-dsm-nanocpus-removal-5a32570-persistent-baseline`. After this
policy-only PR merges, its exact main must be merge-connected into feature PR
#220 without rebase or squash. Fresh Trusted, OTA and Backend checks remain
mandatory, and the policy must rotate again to the actual feature merge-main.
This authority changes no NAS runtime and is not deployment/readiness evidence.

## 16. DSM NanoCPUs field-removal final baseline

Policy-connected feature PR #220 head
`719564f159205cdbabb769037f7783f5e0aaabad` passed fresh Hosted Trusted, OTA P0
and Backend checks. Merge commit
`b6cab8384efe7b5e046841ff84681b74d0cae113` is the actual feature main.

This final rotation removes both bounded `5a32570` transition identities and
pins the sole `current-main-baseline` to actual feature main `b6cab83`. The
complete ordered 83-path map, workflow/action inventories and four reviewed
CPU-field-removal digests remain unchanged.

Final policy authority is still source/CI evidence only. It does not stop the
recovered legacy containers, approve production, migrate the DB, prove
readiness or complete the backend-included access E2E.

## 17. Non-root Compose secret-access transition

Protected run `33245672804` passed DB startup and migration but failed new API
readiness. Immutable feature commit
`2b32fc5fe14b5c90db022ed14deca5f572a68040` corrects the root cause and adds
bounded failure evidence. Relative to the current baseline, exactly five
protected normalized blobs change as one indivisible candidate:

- `backend/deploy/README.md` becomes `17c02dbb...`.
- `backend/deploy/bootstrap_legacy_synology.sh` becomes `8d0eccae...`.
- `backend/deploy/sgk_backend_deploy.sh` becomes `234231e8...`.
- `backend/deploy/verify_legacy_synology.sh` becomes `2b58d125...`.
- `backend/tests/test_nas_backend_deploy.py` becomes `c27affbb...`.

The complete ordered 83-path map is duplicated in
`temporary-compose-secret-access-2b32fc5` and
`future-compose-secret-access-2b32fc5-persistent-baseline`. After this
policy-only PR merges, its exact main must be merge-connected into feature PR
#223 without rebase or squash. Fresh Trusted, OTA and Backend checks remain
mandatory, followed by a final rotation to the actual feature merge-main.
This authority changes no NAS file, secret, container or database state and is
not readiness/deployment evidence.

## 18. Non-root Compose secret-access final baseline

Policy-connected feature PR #223 head
`40556adbb8ed067c43bfd19a73da7098f9f31984` passed fresh Hosted Trusted, OTA
P0 and Backend checks. Merge commit
`5e0aec37282ec0af9846bb6681aee87d89dabfa3` is the actual feature main.

This final rotation removes both bounded `2b32fc5` transition identities and
pins the sole `current-main-baseline` to actual feature main `5e0aec3`. The
complete ordered 83-path map, inventories and five reviewed secret-access
digests remain unchanged. It is source/CI authority only: exact NAS file
metadata, wrapper installation, approved deployment, readiness and
backend-included access remain separate Gates.

## 19. Bootstrap runtime.env argument transition

Post-merge audit found a fail-closed bootstrap arity regression after the
secret metadata helper expanded. Immutable feature commit
`ecc189e8d1ab21ad0c797b3a6009f3f12ac48829` passes explicit
`root root 600` metadata for `runtime.env` and pins the call in its direct test.
Exactly two protected normalized blobs change:

- `backend/deploy/bootstrap_legacy_synology.sh` becomes `1969b5a8...`.
- `backend/tests/test_nas_backend_deploy.py` becomes `ce8b1dff...`.

The complete ordered 83-path map is duplicated in
`temporary-bootstrap-runtime-ecc189e` and
`future-bootstrap-runtime-ecc189e-persistent-baseline`. Policy merge,
merge-connection into PR #226, fresh checks and final rotation remain required.
This authority changes no NAS state and the previous deployment run remains
unapproved.

## 20. Bootstrap runtime.env argument final baseline

Policy-connected feature PR #226 head
`527a671124c87e6a01241ddb55193b71fa1b7af8` passed fresh Hosted Trusted, OTA
P0 and Backend checks. Merge commit
`3fdc615833da68af22623eefafc876d4c84b86d7` is the actual feature main.

This final rotation removes both bounded `ecc189e` transition identities and
pins the sole `current-main-baseline` to actual feature main `3fdc615`. The
complete ordered 83-path map, inventories and the two reviewed bootstrap/test
digests remain unchanged.

Final policy authority is source/CI evidence only. It changes no NAS file,
secret metadata, container or database and proves no deployment/readiness.
Exact bootstrap/verifier/wrapper installation, owner maintenance stop,
protected deployment and backend-included access E2E remain separate Gates.

## 21. DSM noexec-safe operator-guide transition

Owner execution proved a DSM `/tmp` policy can reject direct execution of an
otherwise digest-matched mode-0700 helper. Immutable feature commit
`b2e7d6000fc5096cf3fb8a1ed00761030b1c073a` changes the operator guide to use
the trusted system Bash interpreter without remounting or weakening `/tmp` and
adds a focused regression. Exactly two protected normalized blobs change:

- `backend/deploy/README.md` becomes `da807427...`.
- `backend/tests/test_nas_backend_deploy.py` becomes `d97079ed...`.

The complete ordered 83-path map is duplicated in
`temporary-dsm-noexec-guide-b2e7d60` and
`future-dsm-noexec-guide-b2e7d60-persistent-baseline`. Policy merge,
merge-connection into PR #231, fresh checks and final rotation remain required.
This source authority changes no NAS container, database or deployment state;
the live production run remains an independently monitored Gate.

The complete source identity above supersedes the invalid full SHA originally
recorded by policy PR #232. Hosted ancestry validation must resolve this exact
commit before the feature can pass; no prefix-only identity is accepted.

After policy repair, PR #231 head `e986fd9` passed fresh Hosted Trusted, OTA P0
and Backend checks and merge-committed as actual main
`7236c550c05e8972c7517544d105adea7c957671`. The final rotation removes both
bounded transition identities and pins the sole `current-main-baseline` to
that actual main. The complete ordered 83-path map and two reviewed protected
digests remain unchanged. This rotation changes no NAS state and proves no
deployment or readiness.

## 22. Legacy MQTTS port-preservation transition

Protected deployment run `33246998513` proved the production DB and migration
path but the API remained unready because its MQTT clients attempted the
hard-coded port 8883 while the retained legacy runtime uses authenticated TLS
on port 4883. Immutable merge candidate
`2339f6c9319f973b2b2a3b3062d87b5fb29137dc` preserves that exact runtime port,
validates it, and renders the hosted Backend fixture explicitly. Relative to
the current baseline, exactly eight protected normalized blobs change:

- `.github/workflows/backend_security.yml` becomes `e209b1b2...`.
- `backend/compose.production.yml` becomes `cb0a84db...`.
- `backend/deploy/README.md` becomes `6db1ae72...`.
- `backend/deploy/bootstrap_legacy_synology.sh` becomes `cc0a758d...`.
- `backend/deploy/runtime.env.example` becomes `48a84108...`.
- `backend/deploy/sgk_backend_deploy.sh` becomes `62181892...`.
- `backend/deploy/verify_legacy_synology.sh` becomes `c4ab1fdd...`.
- `backend/tests/test_nas_backend_deploy.py` becomes `4d26c7a5...`.

The complete ordered 83-path map is duplicated in
`temporary-mqtt-port-2339f6c` and
`future-mqtt-port-2339f6c-persistent-baseline`. After this policy-only PR
merges, its exact main must be merge-connected into feature PR #234 without
rebase or squash. Fresh Trusted, OTA and Backend checks remain mandatory,
followed by a final rotation to the actual feature merge-main.

This authority is source/CI evidence only. It does not install corrected NAS
helpers, stop the running legacy pair, approve a production run, migrate the
database, prove API readiness, or complete the mobile/Target access E2E.

Policy PR #236 passed Hosted Trusted and merge-committed as main
`911752dabf45d28b1ed9efac61a08d85046310ea`. That exact policy main was then
merged into PR #234 without rebase or squash as `8ea8de3`, preserving both the
immutable candidate parent `2339f6c` and the policy-main parent. The complete
83-path protected map still matches the reviewed candidate bytes. Fresh
Trusted, OTA and Backend checks on the connected head remain required before
feature merge; no runtime deployment is inferred from this connection.

## 23. Legacy MQTTS port-preservation final baseline

Policy-connected PR #234 head
`33666674ada4c53552fda8b022a3bd0b2bb5fd9e` passed fresh Hosted Trusted, OTA
P0 and Backend checks. Merge commit
`146fd7f85f14c4da0a5ce17518f876bdb9c1b21b` is the actual feature main.

This final rotation removes both bounded `2339f6c` transition identities and
pins the sole `current-main-baseline` to actual feature main `146fd7f`. The
complete ordered 83-path map, inventories and eight reviewed MQTT-port
preservation digests remain unchanged.

Final policy authority is source/CI evidence only. It changes no NAS helper,
runtime file, container or database and proves no deployment/readiness. Exact
NAS installation, bootstrap/verifier preflight, owner maintenance stop,
protected deployment and backend-included mobile/Target access E2E remain
separate Gates.

## 24. DSM 24 MQTT route compatibility transition

Protected deployment run `33249202719` started exact feature main `146fd7f`,
passed DB health and migration, and returned `/live` 200, but `/ready` remained
503 solely with MQTT false. Retained logs showed MQTTS configuration validation
followed by subscriber `TimeoutError`, without TLS, certificate or broker-auth
rejection. The recovered legacy single-bridge API reconnects to the same broker
host and TLS port 4883.

Immutable candidate `40ccecc2bd5d0b35e648f7a5c2d0ed4923fc3b61`
adds a DSM-only Compose compatibility override for Docker Engine 24 / Compose
2.20, which cannot express the newer `gw_priority`. Relative to the current
baseline, exactly two protected normalized blobs change:

- `backend/compose.synology.yml` becomes `29d82f97...`.
- `backend/tests/test_nas_backend_deploy.py` becomes `de15e6b7...`.

The complete ordered 83-path map is pinned by
`future-dsm-mqtt-route-40ccecc-persistent-baseline`, whose source is the exact
candidate and whose ancestry check admits only that commit or a merge-connected
descendant with the same complete protected bytes. After policy merge, main
must be merged into the feature branch without rebase or squash; fresh Hosted
Trusted, OTA P0 and Backend checks remain mandatory before feature merge and a
final policy rotation.

This policy transition changes no NAS file, container, database or network. It
does not prove that the route hypothesis is correct, that the new API is ready,
or that the Target/mobile/backend access flow succeeds. Those require a new
approved maintenance window and live evidence after feature merge.

Policy PR #238 passed Hosted Trusted and merge-committed as main
`7fd54c7ca802a25689e246da7caabc5d095aaaad`. That exact policy main was merged
into the immutable feature candidate without rebase or squash as
`df5357ec3685afa33b4ab64b0b58d974a71adde5`; its parents are exactly
`40ccecc2bd5d0b35e648f7a5c2d0ed4923fc3b61` and the policy main. Both reviewed
protected blobs and the complete ordered 83-path map remain unchanged. Fresh
Hosted Trusted, OTA P0 and Backend checks are still required before feature
merge; no NAS runtime result follows from this source-history connection.

## 25. DSM 24 MQTT route final baseline

Policy-connected PR #239 head
`2f0de8aff4f00ca1af22138d66a0f81ff7489710` passed fresh Hosted Trusted, OTA
P0 and Backend checks. Merge commit
`aebad8ef398e7d5a69e192547543424931ed38af` is the actual feature main.

This final rotation removes the transition source identity `40ccecc2` and pins
the sole `current-main-baseline` to actual feature main `aebad8ef`. The complete
ordered 83-path map, inventories and two reviewed DSM route compatibility
digests remain unchanged.

Final policy authority is source/CI evidence only. It changes no NAS network,
container or database and does not prove MQTT readiness. Exact live deployment
and backend-included Target/mobile evidence remain separate Gates.

## 26. Deterministic single-network backend transition

Exact protected run `33250299026` invalidated the narrower DSM internal-bridge
hypothesis: after both API bridges were routable, DB health, migration and API
startup passed, but MQTTS repeated the same subscriber `TimeoutError`. Owner
recovery then restored the legacy single-bridge API with MQTT true.

Immutable candidate `8e2ec16daad6ead3d981ba476ada67936179a72a`
removes API multi-homing. API, DB and the one-shot migrator share one routable
`data` bridge; DB 3306 remains unpublished, base Compose publishes no API port,
and the Synology overlay remains loopback-only. Relative to the current
baseline, exactly four protected normalized blobs change:

- `scripts/ops_commercial_gate.py` becomes `321a6221...`.
- `backend/compose.production.yml` becomes `42f04b42...`.
- `backend/compose.synology.yml` becomes `b5c6542f...`.
- `backend/tests/test_nas_backend_deploy.py` becomes `673467ab...`.

The complete ordered 83-path map is pinned by
`future-dsm-single-network-8e2ec16-persistent-baseline`, whose source is the
exact candidate and whose ancestry check admits only that commit or a
merge-connected descendant with identical protected bytes. The policy PR must
pass against the trusted base and merge first; that exact policy main must then
be merged into the feature branch without rebase or squash. Fresh Hosted
Trusted, OTA P0 and Backend checks remain mandatory before feature merge and a
final policy rotation.

This policy transition changes no NAS file, container, database or network and
grants no deployment approval. Exact live `/ready` with MQTT true and the
backend-included Target/mobile access sequence remain separate physical Gates.

## 27. Deterministic single-network final baseline

Policy-connected PR #243 head
`81968677ef3e18bdc50abcef186c600894c9e687` passed fresh Hosted Trusted, OTA P0
and Backend checks. Merge commit
`dbafe9d4f803938d7570ef18769ef0925c6b0230` is the actual feature main.

This final rotation removes transition source `8e2ec16` and pins the sole
`current-main-baseline` to actual feature main `dbafe9d4`. The complete ordered
83-path map, inventories and four reviewed single-network digests remain
unchanged.

Final policy authority is source/CI evidence only. It changes no NAS network,
container or database and does not prove MQTTS readiness. Exact live deployment
and backend-included Target/mobile evidence remain separate Gates.

## 28. Synology MQTT host-gateway transition

Exact single-bridge run `33251769358` still failed before broker CONNACK: the
API and DB remained running/healthy, while the subscriber raised `TimeoutError`
5.417 seconds after startup and bounded ACL publishes also failed. Owner
recovery restored the retained legacy API with MQTT true. The evidence narrows
the remaining path to the container's public-IP hairpin rather than DB, API
process, TLS provisioning or multi-network gateway selection.

Immutable candidate `1feb4b9d14ee2742e228f298557e3335a2060d09`
keeps `MQTT_HOST` as the Paho connect and certificate verification hostname but
maps it to Docker `host-gateway` only in the Synology API container. The NAS
already publishes verified MQTTS on port 4883, so this bypasses public-IP NAT
hairpin without disabling TLS SNI/hostname validation, adding another network,
publishing DB 3306 or widening the loopback API bind. Relative to feature main
`dbafe9d4`, exactly three protected normalized blobs change:

- `scripts/ops_commercial_gate.py` becomes `8859e089...`.
- `backend/compose.synology.yml` becomes `307d0486...`.
- `backend/tests/test_nas_backend_deploy.py` becomes `e90cec4c...`.

The complete ordered 83-path map is pinned by
`future-nas-mqtt-host-gateway-1feb4b9-persistent-baseline`, sourced from the
exact immutable candidate. The policy PR must pass against trusted main and
merge first; that exact policy main must then be merge-connected into the
feature branch without rebase or squash. Fresh Hosted Trusted, OTA P0 and
Backend checks, final policy rotation, exact live `/ready` with MQTT true, and
backend-included Target/mobile access remain separate Gates.

Policy PR #246 passed the required Trusted check and merge-committed as main
`be8c462d35cd25790cdf45a92bbcb6eb6b95c44e`. That exact policy main was then
merged without rebase or squash into immutable feature candidate `1feb4b9` as
`56029d3f8eeba717fd6f81505b607294d4846d4b`. All three reviewed protected
candidate blobs and the complete 83-path map remain unchanged. Fresh Hosted
Trusted, OTA P0 and Backend checks are required on this connected head before
feature merge.

## 29. Synology MQTT host-gateway final baseline

Policy-connected PR #245 head
`799c65152ba4a3edea16c7c18bcd4ad0a4c05736` passed fresh Hosted Trusted, OTA
P0 and Backend checks. Its merge commit
`7be876804c23d91caf252b92e2b859f81aee168a` is the actual feature main.

This final rotation removes transition source `1feb4b9` and pins the sole
`current-main-baseline` to actual feature main `7be8768`. The complete ordered
83-path map, workflow/action inventories and three reviewed host-gateway
digests remain unchanged. This changes no NAS runtime and proves no MQTTS
readiness; exact deployment and backend-included Target/mobile evidence remain
separate Gates.

## 30. Synology DSM public-ingress hairpin transition

Exact run `33252726976` for feature main `7be8768` passed immutable image
identity, DB health, migration `up 007`, API start and loopback `/ready`. This
closes the MQTTS dependency Gate for that attempt. The following NAS-local curl
to the public `:4442/ready` origin exhausted its bounded retries, so the wrapper
retained diagnostics and removed the partial project without volumes or DB
rollback. External probes then returned 502 because the retained legacy pair
remained stopped.

Immutable candidate `15005944591a43a5437ccf33f9a945ab7b47809f`
changes the NAS-side DSM ingress probe only. Curl resolves the configured HTTPS
hostname transport to `127.0.0.1`, while continuing to send the hostname as TLS
SNI and verify its public certificate. It does not add `--insecure`, widen API
publication, expose MariaDB, change the public mobile origin or claim external
reachability. Relative to feature main `7be8768`, exactly three protected
normalized blobs change:

- `backend/deploy/README.md` becomes `083089b3...`.
- `backend/deploy/sgk_backend_deploy.sh` becomes `3e0fdd66...`.
- `backend/tests/test_nas_backend_deploy.py` becomes `5968e0ce...`.

The complete ordered 83-path map is pinned by
`future-nas-public-ingress-hairpin-1500594-persistent-baseline`, sourced from
the exact immutable candidate. Policy merge, feature merge-connection, fresh
Hosted Trusted/OTA/Backend checks, final policy rotation, exact NAS deployment,
external `/ready`, and backend-included Target/mobile access remain separate
Gates.

Policy PR #248 passed the required Trusted check and merge-committed as main
`36c720aabf5d2b7deb685836b612c1633d8f2e15`. That exact policy main was then
merged without rebase or squash into immutable feature candidate `1500594` as
`6a5c75eec07062f3ec4d5acd50914f669a88f24e`. All three reviewed protected
candidate blobs and the complete 83-path map remain unchanged. Fresh Hosted
Trusted, OTA P0 and Backend checks are required on the connected feature head
before merge.

The merge-connected feature head uses the required single
`current-main-baseline` ID with source `1500594` and the same reviewed 83-path
map. The OTA policy regression fixture is synchronized to that immutable
candidate and its three changed digests; this does not alter any additional
protected file or broaden the source identity.

## 31. Synology DSM public-ingress hairpin final baseline

Corrected PR #249 head `ad7c31331bd671823007d94f7eef609c19cc088c`
passed Hosted Trusted, OTA P0 and Backend checks. Its merge commit
`db37772de5a3f18be7bcaa73170933ab18442475` is the actual feature main.

This final rotation retires source `1500594` and pins the sole
`current-main-baseline` plus its regression fixture to actual feature main
`db37772d`. The complete ordered 83-path map, workflow/action inventories and
three reviewed DSM-ingress digests remain unchanged. This policy change affects
no NAS runtime and proves no deployment; exact NAS apply, external readiness
and backend-included Target/mobile evidence remain separate Gates.

## 32. Credential-bound mobile UX final baseline

Credential-bound mobile P0 PR #266 merged as main `8ea9ff1f`, and the normal
language/update/support P1 PR #270 subsequently merged as main
`2ae453a0206796650ee99da0e0e57b8fb5078598`. P1 changes no protected path; all
83 normalized protected blobs still match the reviewed P0 candidate map.

This rotation removes the transitional
`future-mobile-ux-p0-c80933a-persistent-baseline` identity and pins the sole
`current-main-baseline` plus its regression fixture to actual merged mobile UX
main `2ae453a`. It changes no workflow/action inventory, NAS runtime, container,
database, mobile installation or Target state. Hosted policy validation, NAS
deployment readiness and disconnected-phone physical acceptance remain
separate evidence Gates.

## 33. GPIO23 Target build-input authorization

Reviewed feature candidate `4c16b44352a986417ee679465da1c61f670abde1`
restores only the authoritative relay pin in `include/config.h` from GPIO3 to
the owner-confirmed historical Gatekeeper GPIO23 mapping while retaining
AJ-SR04T GPIO10/11, fail-safe High-Z OFF, signed dual-slot OTA and rollback.
The privileged Target build inventory must therefore change its reviewed
`include/config.h` row, making the only protected-byte change
`.github/workflows/deploy.yml` at LF-normalized SHA-256
`a69c6abfe5006c40f1088f8ac756018d72b5e6d8fd314d5435323b14913d9bc8`.

This policy-only authorization binds one complete 83-file persistent bundle to
that exact candidate and its future merge-connected descendants. After this
policy merges, trusted main must be merge-connected into the feature without
rebasing or squashing, and a separate final policy rotation must replace this
transition with the actual feature merged-main commit. It authorizes no
firmware publication, Target installation, relay actuation or physical door
claim by itself.

## 34. GPIO23 Target final baseline

GPIO23 restoration PR #283 passed Hosted Trusted, OTA-contract and ESP32-C6
canary checks after policy main was merge-connected without rebase or squash.
It merge-committed as actual main
`c96e85410d2e56bf6757f4ec3f30df2133213bd0`.

This final rotation retires the transitional feature identity and pins the
sole `current-main-baseline` to that actual merged main. The complete ordered
83-path map, workflow/action inventories and reviewed deploy-workflow digest
remain unchanged. Signed exact-main publication, Target OTA installation and
physical GPIO23/contact/door evidence remain separate from this policy result.

## 35. Credential-signed mobile remote-open authorization

Reviewed feature candidate
`3073d716b2c7157178a1f06fa5f38c3a9bc6a56d` changes the normal visible
mobile `문 열기` action from direct Local GATT action 2 to Backend
authorization followed by the existing per-Target signed MQTTS command plane.
The Android Keystore credential signs a fixed 128-byte request envelope; the
Backend validates the active credential, tenant and exact door grant, consumes
a durable nonce and returns only broker-ack evidence. The pocket-approach path
remains Local GATT action 1 followed by Target ARMED and sensor confirmation.

The complete protected bundle grows from 83 to 86 paths so both migration 008
directions and the focused remote-control backend test are protected directly.
Fifteen normalized blobs differ from the previous baseline: the three newly
protected paths plus the reviewed Backend endpoint, migration wiring, release
bundle/deploy wrapper, commercial gate and regression-test changes. The sole
`future-mobile-remote-open-3073d71-persistent-baseline` bundle is pinned to the
exact immutable candidate and permits only its merge-connected descendants.

This policy-only authorization neither deploys the Backend nor installs the
mobile APK, publishes a command, actuates GPIO23 or proves a physical door
opening. After this policy merges, trusted main must be merge-connected into
the feature without rebase or squash. Fresh Hosted Trusted, Backend, OTA and
mobile checks, feature merge, exact-main deployment/publication, connected app
installation, bounded button trial and final baseline rotation remain separate
Gates.

## 36. Migration-008 deployment identity correction authorization

Exact feature main `a78ec0c25e0e498eb1f9f83189279cccba236236`
passed its Hosted checks and immutable image publication, but its approved NAS
job failed closed before Compose, migration or cutover because the installed
root wrapper still admits schema 007. Source review then found the schema-008
readiness value was the prior migration-007 hash rather than the actual
migration-008 bytes.

Reviewed correction candidate
`b6aff4c517a54a4242862c7856c388770eb89146` pins the actual migration-008
SHA-256 `f95e752d...e7219a8` in the signed release descriptor, root deploy
wrapper, production Compose and development Compose. A focused regression test
derives the digest from migration 008 and requires every consumer to match.
Exactly these five protected blobs change inside the complete ordered 86-path
map; the sole `future-schema008-b6aff4c-persistent-baseline` bundle binds them
to the immutable candidate and its merge-connected descendants.

This policy-only authorization does not replace the root-owned NAS wrapper,
run migration 008, deploy a Backend, install an APK or issue a door command.
Policy merge, merge-connection, fresh CI, feature merge, owner-authenticated
wrapper replacement, protected retry/readiness and physical observation remain
separate Gates.

## 37. Migration-008 deployment identity final baseline

Correction PR #287 passed Hosted Trusted, OTA/schema and Backend checks after
policy main was merge-connected without rebase or squash. It merge-committed
as actual feature main `07b3543a1846a1b7220c09874fb89b9e7836d7eb`.

This final rotation retires the transitional
`future-schema008-b6aff4c-persistent-baseline` identity and pins the sole
`current-main-baseline` to that actual feature merge. All 86 normalized
protected blobs and both workflow/action inventories remain exactly those
reviewed in the correction bundle. This policy change installs no root-owned
wrapper, deploys no Backend or APK, runs no migration and proves no Target,
relay or physical-door result.

## 38. Mobile remote personal-ACL scope authorization

Connected exact mobile `1.0.0-gf403e10` reached the deployed Backend three
times but received `REMOTE_CONTROL_DENIED`. A privacy-safe owner aggregate
query proved that `ACL_PERSONAL_*` and legacy `COMMAND_*` tenant/door scopes
intentionally differ and that the command scope contains no mobile credential
or grant. Immutable feature candidate
`e14f34c8896854dc50e7f8a0183eb764f205a622` corrects v3 authorization to the
personal ACL scope while preserving the signed MQTTS command-envelope scope.

The candidate also fails closed unless that personal ACL scope belongs to the
configured `COMMAND_TARGET_ID`, preventing a credential for another Target
from bridging into this publisher. Exactly four protected normalized blobs
change: `backend/app/main.py`, the DSM deployment guide validator correction,
and the two focused Backend tests. The complete ordered 86-path bundle is bound
to the immutable candidate and its merge-connected descendants by
`future-mobile-remote-personal-scope-e14f34c-persistent-baseline`.

This policy-only authorization changes no NAS runtime ID, credential, grant,
database, container, MQTT command, Target, relay or door state. Policy merge,
merge-connection, fresh feature CI, feature merge, NAS deployment/readiness
and one owner-triggered physical trial remain separate Gates.

Policy PR #291 passed the trusted-base check and merge-committed as main
`41d89fb302ed95310db9585dffe3721797139ee2`. That exact policy main was then
merged without rebase or squash into immutable feature candidate `e14f34c` as
`a5671be`. The four reviewed protected candidate blobs and the complete 86-path
map remain unchanged; fresh feature checks are required before merge.

## 39. Fresh family-member registration onboarding authorization

Connected A24 evidence showed that a fresh app generated valid provisional
AndroidKeyStore material before its first personal status call. Candidate
`9291758c99fd21231ddb30fe029b3f6f11fb1de2` changes only
`backend/app/acl_management.py` and `backend/tests/test_acl_api.py` in the
protected map: an unknown valid credential now receives the supervised legacy
registration projection, while a stored credential ID with a different public
key remains a hard denial. The complete 86-path bundle is pinned as
`future-fresh-registration-onboarding-9291758-persistent-baseline`; it does not
authorize a partial map, wildcard, runtime data mutation or credential
replacement. This policy step changes no runtime data, credential or deployed
image; merge-connection, protected CI, NAS deployment and connected A24 UI
readback remain separate Gates.

## 40. Approved additional family-phone enrollment authorization

After the bounded registration correction was deployed, the approved A24
reached `이 휴대폰 등록` but one explicit enrollment attempt failed. Native
support evidence remained healthy. A production-shaped local reproduction
returned HTTP 409 because the first owner's legacy row already holds the
configured personal tenant's unique compatibility mapping.

Immutable feature candidate
`e2ecc68f9e5f7a15c9ca9319d244c99bc778f371` changes exactly two protected
blobs: `backend/app/acl_management.py` and `backend/tests/test_acl_api.py`.
It retains one unique compatibility owner while a separately approved
additional family row remains unmapped and receives its own active public
credential and exact shared-personal-door grant. Unapproved, inactive,
cross-tenant, conflicting and revoked identities remain fail-closed. The
complete ordered 86-path bundle is bound as
`future-family-phone-enrollment-e2ecc68-persistent-baseline` to this immutable
candidate and its merge-connected descendants.

This policy-only authorization creates no credential or grant, changes no NAS
database/container, publishes no ACL, installs no app or Target image and opens
no door. Policy merge, exact merge-connection, fresh protected CI, feature
merge, owner-approved NAS deployment/readiness, one owner retry, Target ACK and
daughter-device access remain separate Gates.

## 41. Mobile account lifecycle and manifest schema authorization

Immutable feature candidate
`68c9c3172782339a731f01dfb960b1aa8aeabaff` adds exact-phone logout,
native registration-only onboarding, console-assigned mobile administrator
projection and migration 010. It also replaces per-version deployment-script
edits with a signed `schema.env` contract whose version and digest are verified
against the pinned database image before the backup-first migration runs.

The indivisible protected set expands from 88 to 91 by adding migration 010 up
and down files plus `backend/db/schema.env`. Eighteen protected blobs are new or
changed, covering the exact Backend authorization/cleanup path, administrator
role console, schema image/bundle/Compose/wrapper consumers, trusted inventory
and their direct regressions. The sole
`mobile-account-schema-68c9c31-persistent-baseline` is repository, immutable
candidate, ancestry, ordered inventory and normalized-digest bound; it grants no
partial-file, branch, wildcard or caller-selected schema exception.

This policy-only authorization changes no NAS file, database, container,
credential, ACL, mobile installation or Target state. After it merges, that
exact trusted main must be merge-connected into the feature without rebase or
squash. Fresh Hosted Trusted, Backend/MariaDB, OTA/schema, Flutter/native checks,
feature merge, one final root-wrapper installation and exact-main NAS migration
and readiness remain separate Gates.

## 42. Hosted schema-manifest validation correction

Feature PR #309 proved the application, migration and OTA contracts locally,
but its first hosted Backend job failed closed before publication because the
production Compose validation step did not export the reviewed
`backend/db/schema.env`. Immutable corrective candidate
`67f87a1dddccb6630564160a1c38d25926817891` loads that exact two-field manifest
before Compose interpolation and adds a direct ordering regression.

The complete ordered 91-path bundle changes one additional protected runtime
blob relative to the preceding candidate: `.github/workflows/backend_security.yml`.
`backend/tests/test_migrations.py` remains in the feature delta with its new
hosted-validation regression, for 19 changed or new protected paths total and
72 unchanged paths. The sole
`mobile-account-schema-ci-67f87a1-persistent-baseline` remains repository,
immutable-candidate, ancestry, inventory and normalized-digest bound.

This correction relaxes no schema, signature, image, backup, migration,
no-downgrade, readiness, rollback or access-control Gate and performs no NAS or
device mutation. Policy merge, merge-connection, fresh hosted CI, feature merge
and exact-main deployment remain separate Gates.

## 43. Final mobile-account and schema-010 main baseline

Feature PR #309 passed Hosted Trusted, Backend/MariaDB, OTA/schema and Android
canary checks, then merge-committed as exact main
`1b701df93194029fb7be733a372f7ddb68f57e97`. The transitional candidate identity
is retired in favor of the sole `current-main-baseline` pinned to that exact
merge commit.

All 91 ordered protected paths and normalized digests remain byte-identical to
the reviewed corrective candidate. The final rotation changes no runtime or
workflow byte, publishes no artifact, installs no NAS wrapper, migrates no
database and performs no mobile, Target, relay or door action. Hosted policy
merge, owner-authenticated root-wrapper installation, exact-main deployment and
runtime acceptance remain separate Gates.

## 44. Fresh credential after logout candidate

Immutable feature candidate
`d1272a5ec16269e51d852f0fc70854cd00048eb3` corrects a narrow personal
bootstrap conflict after server-first logout or administrator deletion. The
old credential remains terminal audit history, while a newly approved account
may bind a new AndroidKeyStore credential for the same keyed device locator.

The complete ordered 91-path bundle changes exactly three protected blobs:
`backend/app/acl_management.py` and its store/API regressions. The sole
`reenrollment-d1272a5-persistent-baseline` is bound to the exact repository,
immutable candidate SHA, ancestry, protected inventory and normalized digest of
every protected path. The other 88 protected blobs remain byte-identical to the
current baseline.

This authorization does not revive retired credentials, bypass approval, admit
an active or pending duplicate, relax public-key uniqueness, weaken signed ACL
or Target ACK requirements, or mutate NAS/database/device state. Hosted policy
CI and merge, merge-connection into the feature, fresh feature CI, exact-main
merge and NAS deployment remain separate Gates.

## 45. Final re-enrollment correction main baseline

Feature PR #315 passed Hosted Trusted, Backend/MariaDB and OTA/schema checks,
then merge-committed normally as exact main
`b0e1339c186bde81e2f4602ff426251b88e57db6`. The transitional candidate
identity is retired in favor of the sole `current-main-baseline` pinned to that
exact merge commit.

All 91 ordered protected paths and normalized digests remain byte-identical to
the reviewed candidate. This final rotation changes no Backend runtime byte,
publishes no ACL, changes no account or credential, installs no app or Target
image and performs no physical action. Hosted policy CI/merge and the owner's
post-deployment phone retry remain separate Gates.

## 46. Local GATT ultrasonic session-isolation candidate

Immutable feature candidate
`a57ea44e295e6c780f154a005ae111d69b59f669` resets the five-slot ultrasonic
median only after an authenticated Local GATT action-1 has successfully entered
`ARMED`. This prevents valid distance samples retained by an earlier passage
from satisfying a new sensor session before three fresh measurements exist.

The complete ordered 91-path bundle changes exactly one protected blob:
`.github/workflows/deploy.yml`, whose closed personal-Target build inventory now
pins the reviewed `src/main.cpp` digest. The sole
`ultrasonic-session-a57ea44-persistent-baseline` is bound to the exact
repository, immutable candidate SHA, ancestry, protected inventory and
normalized digest of every protected path; the other 90 protected blobs remain
byte-identical to the current baseline.

This authorization does not admit an arbitrary Target source tree or relax
ACL/proof, nonce/replay, action-2, relay/cooldown, OTA signing, health or
rollback requirements. It publishes no firmware, changes no Target state and
performs no physical door action. Policy CI/merge, merge-connection, fresh
feature CI, exact-main merge, signed OTA publication, Target
install/reboot/health and physical acceptance remain separate Gates.
