# Backend public-key enrollment and signed ACL management

> Status: Issue #19 core plus personal public-key bootstrap deployed; first owner physical remote-open passed and approved additional-family-phone enrollment correction is in review
> Protocol: [security_protocol.md](security_protocol.md)
> OTA parent contract: [ota_reliability_contract.md](ota_reliability_contract.md)

## 1. Scope and trust boundary

The Backend now manages Android public credentials and signed door ACL snapshots instead of
being required in the real-time local unlock path. The management plane accepts only a P-256
SEC1 public key and proof-of-possession signature. It has no API or column for a mobile private
key or common per-device unlock secret.

`ACL_MANAGEMENT_ENABLED=false` is the default. Existing `device_id`/`ble_device_mac` behavior,
legacy Pre-arm and the authenticated explicit `POST /api/v1/door/open` `manual_remote` path stay
separate. A legacy device ID may be stored only as a keyed HMAC migration reference and never
becomes an ACL authorization credential. `ACL_LEGACY_REF_HMAC_KEY` is an independent random
server-only key; no static production default exists.

The personal seam adds another independent flag, `ACL_PERSONAL_ENROLLMENT_ENABLED=false`, and exact
`ACL_PERSONAL_TENANT_ID`/`ACL_PERSONAL_DOOR_ID` scope. Enabling general ACL management does not
implicitly enable personal enrollment. The app API key authenticates this narrow bootstrap request,
but an existing approved legacy device row is still required; the raw device ID is used for that
locked lookup and is not promoted into a GATT credential.

## 2. Expand → migrate → contract

1. Apply `backend/db/migrations/002_acl_management_expand_up.sql`. It adds nullable
   `tenants.tenant_uuid`, `credential_mode=legacy`, and an `acl_tenants.status` authority plus new
   credential/ACL/ACK/audit/OTA tables;
   it does not remove or reinterpret `ble_device_mac`, `auth_key`, `is_active`, or `access_logs`.
2. Keep the flag OFF. Register canonical 16-byte tenant IDs through the authenticated admin API,
   then enroll P-256 public credentials. Keep old Backend N-1 and new Backend N operating against
   the expanded schema.
3. This RC does not expose a tenant-wide dual-mode or legacy-retirement transition. Those remain
   blocked until an authenticated expected-Target inventory exists and every required Target on
   every tenant door has ACKed the exact current version/digest, in addition to physical evidence.
4. During rollback, disable the flag first. `002_acl_management_expand_down.sql` may be run only
   while the legacy application/schema are still deployed; it removes additive state but leaves
   legacy tenant/access rows readable.
5. Contract/removal of legacy columns and `device_id` authorization is a later PR after the
   G0-HW/production, N/N-1, OTA and rollback windows. This Hardwareless RC does not authorize it.

Fresh MariaDB volumes execute the expand migration as `02_acl_management_expand.sql` through
Compose. Existing volumes must apply the migration explicitly; MariaDB does not rerun
`docker-entrypoint-initdb.d` on an initialized data directory.

## 3. Authenticated APIs

All management endpoints fail closed if their independent server credential is absent or wrong.
`X-Tenant-ID` must equal the body tenant scope.

| Actor | Authentication | API |
|---|---|---|
| logged-in enrollment bridge | identity-bound `X-Enrollment-Actor-ID`, `X-Enrollment-Key`, `X-Tenant-ID` | challenge and proof-of-possession enrollment |
| admin | `X-Admin-Key`, `X-Tenant-ID` | tenant registration/disable, credential approve/disable/revoke, per-door grant/remove, snapshot publish, fleet status, OTA metadata |
| Target | identity-bound `X-Target-ID`, `X-Target-Key`, `X-Tenant-ID` | periodic ACL pull, idempotent apply ACK, OTA metadata/health confirmation |

### 3.1 Personal installed-phone bootstrap

`POST /api/v1/acl/personal/enroll` is a narrow migration endpoint for the one configured personal
tenant/door. It requires the normal nonempty `X-API-KEY`, an approved legacy `device_id`, an exact
nonzero 16-byte `credential_id`, an uncompressed on-curve P-256 SEC1 public key, and protocol v1.
There is no private-key, shared unlock-secret, caller-selected tenant, caller-selected door, status,
grant or signer field.

The store locks the approved legacy device and exact credential binding, then atomically creates or
reuses the ACTIVE credential, exact-door OPEN grant and durable snapshot job. A different public key
for an existing credential ID, a disabled/revoked credential, an unapproved device, another tenant or
door, malformed point or invalid protocol fails closed; a retry of the identical binding is
idempotent. The Backend signs canonical ACL bytes with its protected ACL signer, publishes the
Target-compatible signed envelope to the exact Target ACL topic, and waits for that configured
Target's non-retained `APPLIED` ACK for the same version. Artifact generation or MQTT PUBACK alone
does not satisfy the endpoint. Only after exact apply does the response return
`accepted=true`, the exact credential ID and a positive `acl_version`; otherwise the app leaves native
GATT OFF.

The Target's ACL lease remains bounded (900 seconds by default, maximum 3,600). Backend startup and
Target boot/status observation schedule signed snapshot delivery, and a periodic renewal loop
refreshes it before expiry; retained or malformed ACKs never count. This is an availability mechanism,
not a relaxation of signature, door, version/high-watermark, trusted-time or reboot checks. Source
tests do not prove the live NAS scheduler, broker delivery or long-outage behavior.

Enrollment auth maps each login-bridge actor to its tenant and key; Target auth maps each Target ID
to its tenant, authorized door and management key. A caller cannot select another tenant, cross a door, forge another audit
actor, or claim another Target in an ACK/health body. Audit stores a one-way actor reference, not
the configured actor ID or key. The admin key is intentionally a global
operator role, but every mutation still carries an explicit tenant scope and repository query.

Enrollment challenges expire after five minutes and are single-use. The DB stores a stable one-way
authenticated actor reference plus only the SHA-256 nonce digest. Submit must present the same
authenticated actor and tenant that issued the challenge; the actor check, challenge consumption,
and public-credential insertion commit in one transaction, so a cross-actor attempt or insertion
failure leaves the challenge unused. Public keys must be valid P-256 points and the
enrollment signature must be strict low-S raw64 over `SGKENR01` canonical bytes. A credential
begins `PENDING`; only explicit admin approval makes it `ACTIVE`.

`POST /api/v1/admin/acl/tenants/disable` requires the admin credential and exact matching header/body
tenant scope. The first request changes `acl_tenants.status` from `ACTIVE` to `DISABLED`, records one
`TENANT_DISABLED` audit meaning, and queues every known grant/state/job door in the same transaction.
An exact retry does not create another state transition, audit row, job revision, or ACL version; it
only retries jobs that remain durable after signer or MQTT failure. Enrollment, approval and new grants
fail closed for a disabled tenant. This RC intentionally exposes no tenant re-enable endpoint, and
tenant registration/upsert cannot change `DISABLED` back to `ACTIVE`.

Legacy compatibility is explicit and one-way. Registration maps an already inactive legacy
`tenants.is_active` row to `acl_tenants.status=DISABLED`; the authenticated ACL disable transaction
also writes the mapped legacy row inactive. If an N-1 legacy path or operator later changes
`is_active=false`, the next enrollment-sensitive operation, authoritative publish, or periodic Target
pull atomically reconciles it to the same durable ACL disable transition. A later legacy
`is_active=true` change never re-enables public credentials. Operators must not use the unauthenticated
legacy approve/reject endpoints as the public-ACL lifecycle API; re-enable remains unsupported and
requires a future authenticated design with replacement snapshots and explicit authorization review.

## 4. ACL artifact and synchronization

The Backend uses the exact canonical encoder and deterministic fixture from
`protocol/test_vectors/v1.json`. Entries are sorted by raw credential ID, duplicate-free, and only
unexpired `ACTIVE` credentials with an active grant for that exact door and an `ACTIVE` ACL tenant are
included. `AclStore.list_granted_credentials` joins the authoritative tenant state, so a disabled
tenant cannot leak active public credentials into a newly signed artifact. Approval
alone grants no door. A grant cannot authorize another door; disable/revoke or explicit grant
removal excludes the credential from the next authoritative snapshot.

Because the frozen 72-byte ACL canonical header signs `door_id` but not `tenant_id`, door IDs are
globally unique in `acl_door_state`. Once a door has published for one tenant, a second tenant
cannot reuse that door ID even if administrative configuration is wrong.

Each publish atomically allocates a monotonically increasing per-door version, signs the canonical bytes, stores
the envelope for periodic pull, and pushes that same envelope to
`gatekeeper/acl/v1/{tenant_id}/{door_id}`. A Target must perform authenticated pull at least every
60 seconds as recovery/source-of-truth; MQTT is not the only trigger.

Tenant disable, credential disable/revoke, and door-grant removal synchronously publish monotonically
newer replacement snapshots for every affected door. The state/grant mutation and durable replacement
job are committed in one transaction. A signer failure leaves an ungenerated job; MQTT failure leaves
the exact persisted generated version. Periodic pull or an idempotent disable retry signs only pending
work or republishes the exact queued artifact, so retries neither regress/increment an already generated
version nor duplicate the disable audit meaning.
The lease defaults to 900 seconds and is bounded to 3,600 seconds. Before activation the shared
Target verifier checks canonical bytes/digest/signature, trusted signer ID, exact door, Target
protocol overlap, trusted UTC validity, receipt boot identity and persisted version/digest
high-watermark. Equal-version replay never refreshes a lease. A cached ACL is rejected after reboot
without trusted UTC; with trusted UTC it remains usable only until the earlier of the signed expiry
or the persisted trusted receipt time plus `lease_duration_s`.

Signer rotation uses an optional transition signer. Keep the N-1 signer as the primary/top-level
signature while Targets learn the transition public key; new Targets validate either entry in the
`signatures` set. Configure both `ACL_TRANSITION_SIGNING_PRIVATE_SCALAR_HEX` and
`ACL_TRANSITION_SIGNING_KEY_ID` together. Promote the transition key to primary only after every
required Target trusts it and the N-1 rollback trust window closes. Configuration rejects an older
transition key behind a newer primary because an N-1 parser reads only the top-level signature.

An ACK must identify an actually published `(tenant, door, version, digest)`. Exact retries return
the original ACK ID; an `APPLIED`/`REJECTED` conflict for the same identity is rejected rather than
being ordered by timestamp. Fleet status counts a Target synced only when its latest `APPLIED` ACK
matches the latest version and digest.

Backend/MQTT outage does not revoke an already verified, unexpired local Target lease. It only
prevents a newer snapshot from arriving. After expiry the Target fails closed according to the
security protocol.

The authenticated boot registry distinguishes a physically advanced boot from the same
`(boot_count, boot_id)` being replayed by a normal MQTT reconnect. Either the non-retained boot
event or fresh periodic status may establish the advance, but the first one to commit queues the
`TARGET_BOOT_REFRESH` path and allocates `N+1` exactly once. The second observation is unchanged
and does not republish. The worker's immediate startup pass still restores a valid lease after a
Backend restart. This prevents missed boot events from delaying local recovery while routine
broker reconnects cannot create unbounded ACL versions or unnecessary Target NVS writes.

## 5. OTA and manual path independence

ACL routes are mounted only when the feature and all prerequisites are valid. Initialization
failure leaves legacy `manual_remote`, APK/version download, health and config routes active.
The authenticated remote contract `POST /api/v1/door/open` remains available as
`manual_remote`; it is distinct from hands-free `manual_local_gatt` action 1.
The current mobile v3 path proves possession of the enrolled AndroidKeyStore
credential, requires an ACTIVE tenant and the exact ACTIVE credential-to-door
grant in `ACL_PERSONAL_TENANT_ID`/`ACL_PERSONAL_DOOR_ID`, then consumes a durable
replay nonce before publishing a signed command. Credential authorization must
not be looked up in the independent legacy `COMMAND_TENANT_ID`/`COMMAND_DOOR_ID`
scope; those identifiers remain the signed MQTTS command-envelope scope after
authorization succeeds. Startup fails closed unless the personal ACL scope is
the exact tenant/door authorization registered for `COMMAND_TARGET_ID`, so a
credential approved for another configured Target cannot bridge into this
command publisher.
PR #290 deployed this scope correction as exact main
`6c12f169bd2d8733352beb3415159a6e60c01081` in Backend run `33311924158`.
Canonical Tailscale deployment evidence and an independent strict-TLS readback
both passed loopback/public readiness with every check true. This is runtime
authorization/readiness evidence only; a post-fix mobile request, Target receipt,
relay actuation and physical door movement remain separate observations.
On a fresh install Android prepares a valid non-exportable key before its first
status request. If that credential ID does not yet exist, status projects only
the same supervised legacy registration state used before key creation so Home
can offer `request_registration`, `wait_for_approval` or `enroll_credential`.
If the credential ID exists but its public key differs, status still fails
closed; an unknown key never inherits an existing credential's authorization.
PR #295 deployed this onboarding correction as exact main
`bf435bf4c9681c3ef5e926ecc23f8f7619da9bf5`. Run `33312971831` passed
canonical loopback/public readiness, independent strict-TLS readback returned
HTTP 200 with all checks true, and the connected fresh A24 displayed the
registration action and form. The owner's subsequent submission failed before
persistence because the legacy request schema accepted only `DEV-*`, while a
fresh install generates a random UUID-shaped `GK-*` ID. PR #297 deployed the
correction as exact main `f03acdfaad4fa2fad61439f58f318ddbc756d084` in
Backend run `33314043691`: it accepts both bounded formats, preserves
identifiers that already fit, and maps longer values such as the high-entropy
`GK-*` UUID to a deterministic 17-character locator for the existing legacy
MariaDB column. Status and credential bootstrap use the same mapping, while
credentials keep their separate keyed legacy reference. Canonical loopback and
public readiness passed; independent strict-TLS `/live` and `/ready` returned
HTTP 200 for the exact build with every readiness check true. No registration
was retried automatically. The owner's later submission and administrator
approval reached the expected `enroll_credential` projection; connected ADB
rendered `이 휴대폰 등록` with the instruction to link this phone's security
key to the approved account. This is the intended next step, not another tenant
request. The owner then pressed the key-enrollment action once, but it failed
and remained `ready_to_enroll`. Connected diagnostics showed healthy native key
material and no Bluetooth/permission failure. A production-shaped local
reproduction returned HTTP 409 because the configured personal tenant was
already compatibility-mapped to the first owner's legacy row. The correction
keeps that unique compatibility owner while allowing each separately approved
additional family row to remain unmapped and receive its own public credential,
door grant and shared-tenant signed ACL entry. Unapproved, inactive,
cross-tenant, conflicting and revoked identities remain fail-closed. Source
regressions and all 152 Backend tests pass with two expected Docker-only skips;
policy authorization, protected CI, NAS deployment, one owner retry, signed ACL
Target ACK and access remain pending.
It fails closed while ACL management is unavailable. The older HMAC v2 envelope
remains N-1 compatible, while device-ID-only calls are upgrade-required and
cause no control effect. Home Assistant
may reach `manual_remote` only through its separate signed bridge opt-in, never by publishing a
plaintext Target command.
Management OTA metadata requires distinct primary/fallback HTTPS URLs, artifact digest,
signature and N/N-1 protocol range. Target health confirmation must match the published version
and digest; metadata upload or MQTT publication alone is not OTA success.

This is management-plane support plus the narrow personal bootstrap described above. Periodic Target HTTPS, authenticated local recovery,
dual-slot health/rollback, mobile fallback and physical install/boot evidence remain pending in
issue #23. No Samsung, ESP32-C6 radio, relay, sensor, bootloader or physical OTA evidence is
claimed here.

The personal enrollment API is a supervised commissioning seam, not a permanent ownership
credential: the shared mobile API key is extractable from the personal APK. Enable enrollment
only while the owner is commissioning the connected phone, require the exact Target ACL ACK,
then disable the endpoint and restart the Backend. A future multi-user/commercial flow requires
one-time owner pairing or explicit administrator approval instead of this exception.

## 6. Verification

```bash
python -m unittest discover -s backend/tests -v
RUN_MARIADB_INTEGRATION=1 python -m unittest backend.tests.test_migrations -v
python protocol/tools/verify_vectors.py
python -m unittest discover -s protocol/tests -v
python -m unittest discover -s observability/tests -v
python scripts/ota_contract_gate.py contract
```

The MariaDB integration test creates an isolated disposable MariaDB 10.11 container, applies the
legacy schema and expand migration, performs both N-1 legacy and N credential writes, exercises
multi-door tenant disable through signer and MQTT outages, exact retry, no-grant legacy reconciliation,
and fail-closed re-enable, then rolls down and confirms the legacy row remains readable. It passes SQL
to Docker and captures output with
explicit UTF-8 plus a MariaDB `utf8mb4` client charset, so Windows does not require
`PYTHONUTF8` or `PYTHONIOENCODING` overrides. The only additional prerequisite is a running Docker
engine able to bind an ephemeral localhost port.

Windows PowerShell invocation:

```powershell
$env:RUN_MARIADB_INTEGRATION = "1"
python -m unittest backend.tests.test_migrations -v
Remove-Item Env:RUN_MARIADB_INTEGRATION
```
