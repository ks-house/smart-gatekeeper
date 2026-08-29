# Commercial operations, privacy, recovery, and supply-chain contract

> Scope: repository and hardwareless software implementation for Issue #52.
> Production state: **OFF**. No item in this page authorizes a live deployment,
> closes a Samsung/ESP32-C6/relay/OTA Gate, or substitutes for an independent
> restore, 24-hour soak, operator review, privacy/legal approval, or user
> physical acceptance.

## 1. Implemented repository boundary

| Area | Implemented contract | Evidence boundary |
|---|---|---|
| privacy-safe logging | root logging filter removes MAC, bearer/secret assignments and URL queries; sensitive producer logs no longer emit tenant name, unit, device, broker topic, path, reason, or exception text | deterministic unit/adversarial tests; DLP is defense-in-depth, so producers must still use fixed codes and opaque references |
| support export | mTLS admin/auditor, tenant scope, SHA-256 lookup of a current DB consent bound to `support-diagnostics`, tenant, expiry and one-way revocation; 1–168-hour window, at most 500 records, recursive redaction, opaque response/audit reference and canonical SHA-256 | fabricated, expired, revoked and cross-tenant mutations fail; lawful consent capture UX, ticket closure deletion and privacy-owner approval remain pending |
| retention deletion | mTLS tenant admin, CSRF, fresh mTLS, idempotency key bound to canonical tenant/actor/policy/window request, exact `sgk-retention-v1`, 30–3650 days, tenant-only deletion and immutable completed evidence | mismatch returns `409`; concurrent MariaDB callers produce one completed row; the actual retention period requires legal/privacy-owner approval |
| resilience | one persistent MQTTS publisher, end-to-end DNS/TCP/TLS plus PUBACK deadline, maximum 16 in-flight effects, non-blocking backpressure, three-failure circuit breaker, one half-open probe and cancellation/socket-close on deadline | blocked-connect mutation is bounded and cannot fan out connection threads; real broker/DNS/certificate/storage recovery and Target receipt remain pending |
| API protection | bounded opaque-peer rate limits for authentication/control/privacy; unsafe admin routes retain session, role, tenant, CSRF and re-authentication checks | host API bypass tests; reverse-proxy and live network policy pending |
| health and metrics | process-only `/live`; `/ready` requires DB plus exact migration ledger, bounded broker probe, runtime secrets, 32-byte control API key, enabled admin mTLS/proxy, initialized ACL management, retired legacy pre-arm authority and exact build SHA | production Compose admits on `/ready`, not `/live`; production scrape, alert delivery and on-call acknowledgement pending |
| production Compose | repository and 64-hex digest are structurally separate required variables for both API and DB; seed-free baseline and every up/down migration are baked into the pinned DB artifact; a backup-first one-shot migration must finish before API admission; external secrets, one routable bridge with no DB publication, no base host port/live SQL bind, read-only non-root API and resource limits | The single bridge avoids an indeterminate DSM Engine 24 multi-network default route. The Synology overlay maps the unchanged broker certificate hostname to Docker `host-gateway`, bypassing public-IP hairpin while retaining TLS SNI/hostname validation; API publication remains loopback-only and immutable images still require provenance |
| supply chain | hash lock, digest-pinned image bases/service, Python `3.12.13`, exact action commits, full workflow path triggers, deterministic SBOM and vulnerability/license Gates | `ops/backend_trusted_bundle_paths.json` defines the whole executable/input set; a separate trusted-base policy rotation must approve the exact candidate without reading candidate policy before merge |
| backup/recovery | HMAC-authenticated manifest binds dump bytes, release migration identity and per-table schema hash, primary key, PK-ordered row count/content hash; isolated restore compares the entire source/target inventory | actual disposable MariaDB logical dump/separate-schema restore and monotonic RTO pass locally; independent operator restore from production-like encrypted storage remains pending |
| SLO/evidence | strict fixed-ID evidence v2 binds checked-out commit, future zoned expiry, authoritative merged PR/reviewer, and an ID-specific producer/job/environment/artifact/claim/predicate contract | only `ops-contract` and `hosted-sbom-attestation` currently have admitted producers; restore, physical soak and production remain fail-closed; cross-ID, same-SBOM, duplicate subject/payload and caller-environment mutations fail |

The mobile and Target OTA paths remain independent. These changes do not alter
the signed mobile manifest, Target dual-slot state machine, periodic HTTPS,
authenticated local recovery, N/N-1 protocol window, or rollback semantics.

## 2. Health, readiness, and metrics

### 2.1 Endpoints

| Endpoint | Authentication | Meaning |
|---|---|---|
| `GET /live` | reverse-proxy network boundary | Python process is responsive; never means DB, MQTT, Target or production healthy |
| `GET /health` | same | compatibility alias; response explicitly says `scope=process_liveness_only` |
| `GET /ready` | deployment network boundary | `200` only when DB, exact `007` script ledger, bounded broker session, runtime/control secrets, admin mTLS/proxy, ACL runtime, legacy pre-arm retirement and exact build identity all pass; otherwise `503` |
| `GET /api/v1/admin/metrics` | current mTLS admin/auditor session and tenant `*` | low-cardinality request, MQTT and breaker metrics; no tenant/device/MAC labels |

Production sets `ACL_LEGACY_DEVICE_LOOKUP_ENABLED=false`. Under that same
authority boundary, legacy `POST /api/v1/door/prearm` returns fixed `410` before
reading a raw `device_id`, database row or MQTT state. Control admission must use
the signed per-device credential plane. Mobile update and Target OTA/manual
recovery remain separate paths and are not weakened by this retirement.

The reverse proxy must remove inbound certificate headers, establish mTLS,
then set verified headers only for an allow-listed proxy IP. The API service has
no host port in `backend/compose.production.yml`; publishing it directly breaks
the administrator security model.

### 2.2 Initial SLO policy

`ops/slo_policy.json` is the executable **candidate** policy:

- at least 20 samples;
- p95 API stage latency at most 250 ms;
- error rate at most 1%;
- bounded queue depth at most 12;
- reconnect at most 5 seconds;
- heap floor at least 131,072 bytes.

The nominal fixture proves evaluator behavior only. Production acceptance needs
a 24-hour load/soak with real timestamps, battery, heap, queue, reconnect,
broker/API/DB fault windows and artifact identity. An alert is accepted only
after its notification is received and acknowledged through the incident
route; a metrics value alone is not alert evidence.

## 3. Privacy operations

### 3.1 Consented support export

```http
GET /api/v1/admin/privacy/support-export?hours=24&limit=200
X-Tenant-ID: legacy:<tenant-number>
X-Support-Consent: consent_<32 lowercase hex>
```

The operator first records informed consent in `support_export_consents` through
the approved subject-consent workflow. The stored row is keyed by the SHA-256
of the presented reference and binds `legacy:<tenant>`, purpose
`support-diagnostics`, `expires_at`, `created_at`, `granted_by` and nullable
`revoked_at`. Revocation is one-way; fabricated, expired, revoked or
cross-tenant references fail with `403`. The response contains only an HMAC
opaque consent reference, fixed operational fields, redacted
records and a canonical digest. It must be transferred only to the approved
ticket, access must be audited, and the export must be deleted at ticket close.
Never attach raw logs, database dumps, MQTT payloads or screenshots containing
identifiers as a substitute.

### 3.2 Retention deletion

```http
POST /api/v1/admin/privacy/delete
X-Tenant-ID: legacy:<tenant-number>
Idempotency-Key: <unique bounded value>
X-CSRF-Token: <current session token>
X-Admin-Reauthenticate: mtls
Content-Type: application/json

{"policy_version":"sgk-retention-v1","before_days":365}
```

`before_days` is a mechanism bound (30–3650), not a legal default. A privacy
owner must approve the jurisdictional retention schedule before execution.
Deletion affects only the tenant's legacy access records. The reservation binds
the key to a canonical SHA-256 of tenant, actor, policy and days. A different
payload or actor returns `409`; concurrent identical requests serialize on the
unique DB row and return the single completed result.

## 4. Backup and isolated restore procedure

1. Record exact application image digest, `BUILD_SHA`, schema/migration set and
   backup start time. Stop schema changes during the snapshot window.
2. Use the database platform's secret-file authentication and consistent
   transaction snapshot to create a dump in encrypted, access-controlled
   storage. Never place a password on a command line or in the manifest.
3. Capture the source inventory with a read-only account. Store the manifest
   authentication key only in the approved secret store; it must be at least
   32 bytes and must never be placed in the dump or manifest:

```powershell
python scripts/ops_commercial_gate.py inventory `
  --host <source-host> --port 3306 --database smart_gatekeeper `
  --user <backup-auditor> --password-file <source-password-file> `
  --output <source-inventory.json>

python scripts/ops_commercial_gate.py backup-manifest `
  --dump <encrypted-staging-dump.sql> `
  --output <backup-manifest.json> `
  --inventory <source-inventory.json> `
  --manifest-key-file <manifest-auth-key-file> `
  --source-commit <40-hex-commit> `
  --completed-at <UTC-RFC3339>

python scripts/ops_commercial_gate.py verify-backup `
  --dump <encrypted-staging-dump.sql> `
  --manifest <backup-manifest.json> `
  --manifest-key-file <manifest-auth-key-file> `
  --max-age-seconds 900 `
  --now <UTC-RFC3339>
```

4. Restore into a newly created isolated MariaDB instance with no production
   routes, broker credentials or Target access. Apply no repair query before
   the first integrity result.
5. Run the read-only integrity and RTO check with a secret file:

```powershell
python scripts/ops_commercial_gate.py restore-check `
  --host 127.0.0.1 --port <isolated-port> `
  --database smart_gatekeeper --user <restore-auditor> `
  --password-file <temporary-secret-file> `
  --dump <verified-staging-dump.sql> `
  --manifest <backup-manifest.json> `
  --manifest-key-file <manifest-auth-key-file> `
  --max-rto-seconds 1800
```

6. The restore command rejects a non-empty target, starts its own monotonic clock
   before invoking the real MariaDB client, and stops only after authenticated
   inventory verification; it exposes no caller-supplied measured-RTO field.
   Require every fixed table
   to match the authenticated source schema hash, primary key, row count and
   PK-ordered content hash, in addition to tenant/access/ACL orphan invariants.
   Destroy the isolated restore and temporary
   secret using the approved recoverable lifecycle procedure.

The candidate objectives are RPO ≤15 minutes and RTO ≤30 minutes. They remain
unproven until an independent operator performs the full restore using a
production-like encrypted backup and records timestamps and artifact digests.

## 5. Supply-chain and deployment Gate

Run locally from the repository root:

```powershell
python scripts/ops_commercial_gate.py contract
python scripts/ops_commercial_gate.py production-compose `
  --api-image <repository@sha256:64hex> `
  --db-image <repository@sha256:64hex>
python scripts/ops_commercial_gate.py sbom --output build/backend-sbom.cdx.json
python scripts/ops_commercial_gate.py slo --samples ops/fixtures/load_nominal.jsonl --policy ops/slo_policy.json
python -m unittest discover -s backend/tests -p "test_*.py" -v
docker compose -f backend/docker-compose.yml config --quiet
```

For production Compose, set `API_IMAGE_REPOSITORY`, `API_IMAGE_DIGEST`,
`DB_IMAGE_REPOSITORY` and `DB_IMAGE_DIGEST` separately. Direct `API_IMAGE`
input is intentionally ignored, so `API_IMAGE=nginx:latest` fails interpolation.
Only values already accepted by `production-compose` may be split into those
four variables. The database image is built from `backend/db/Dockerfile`; the
production file contains no repository SQL bind mount or demo tenant/phone/MAC/
credential seed. On a fresh volume only `production_schema.sql` creates the
empty baseline. On every deployment the `migrate` service runs
`sgk-migrate up 007`, takes a logical backup and SHA-256 sidecar before changing
the ledger/schema, admits only exact 40-hex source identity, verifies canonical
migration digests on repeat runs, uses a nanosecond/mode/process backup identity
and fails rather than overwriting any collision, and exposes `down 001` as the explicit
backup-first rollback. The API starts only after this service succeeds and then
requires the exact `007` ledger digest in `/ready`. Backup files belong in the
external `migration_backups` volume and must be copied to approved encrypted
storage before operator rollback or volume replacement.

The hosted backend workflow installs `requirements.lock` with
`--require-hashes`, runs the full security suite, policy/SBOM/SLO Gates,
high/critical vulnerability audit, both actual MariaDB lanes, and both image
builds. On exact main it creates separate typed operations-contract and hosted-
SBOM claim envelopes, uploads them under disjoint names/paths, attests each with
GitHub's identity, then
generates the operations register only after the security and attestation jobs
succeed. An SBOM upload without a successful attestation does not satisfy
provenance.

The backend workflow is not allowed to authorize itself. Before this candidate
can merge, an independent policy-only change based on trusted `main` must add
the exact paths from `ops/backend_trusted_bundle_paths.json` and the final
candidate digests to the base policy. PR #67 must not modify that trusted policy
or validator. Until the policy-only change is reviewed and merged, the backend
bundle Gate remains explicitly blocking even when its ordinary PR job is green.

Before any production deployment, require all of the following:

1. exact reviewed main commit and immutable `repository@sha256` API image;
2. successful hosted tests, vulnerability Gate, SBOM digest and attestation;
3. external Docker secrets and mTLS proxy identity map; no `.env` secret copy;
4. verified backup plus independent restore evidence within approved RPO/RTO;
5. rendered production Compose with no host DB/API exposure or source mount;
6. canary `/live`, `/ready`, fixed-label metrics and alert delivery evidence;
7. mobile/Target OTA and rollback Gates, physical device/relay safety, 24-hour
   soak, operator walkthrough and explicit production authorization.

No automated job in this repository may infer item 7 from green CI.

## 6. Evidence register

`ops/evidence_sources.json` starts every operational claim pending or blocked.
Generate a candidate-bound register with:

```powershell
python scripts/ops_commercial_gate.py evidence `
  --source ops/evidence_sources.json `
  --output build/ops-evidence-register.json `
  --commit <40-hex-candidate>
```

The generator requires `--commit` to equal the checked-out HEAD. A `passed`
record must use one fixed unique ID/scope, exact 64-hex claim/archive/payload
digests, a future timezone-aware ISO expiry, and a reviewer different from the
candidate author. Every ID has a code-owned policy for workflow/ref/event,
producer and attestor jobs/steps, execution environment, artifact name/archive
path, attestation subject path, claim type, payload schema and SLSA predicate.
Only repository `ops-contract` and `hosted-sbom-attestation` producers are
admitted today. `isolated-mariadb-restore`, `24h-load-soak` and
`production-deployment` reject `passed` before network access until separate
trusted producers and environment approval contracts are implemented.

The verifier ignores caller provenance environment strings and queries only
fixed `https://api.github.com`. It binds the authoritative commit author,
completed successful exact-main run and exact producer/attestor job steps,
non-expired uniquely named artifact, downloaded archive path and bytes, typed
claim contents, and GitHub-hosted SLSA repository/ref/workflow/commit/invocation.
It also requires a closed merged PR whose base is this repository's `main`,
whose merge SHA equals the evidence commit, whose head equals the reviewed head,
and whose exact `APPROVED` review and numeric reviewer identity match the
authoritative user API. Same-account `COMMENTED`, unrelated PR, wrong base/head/
merge, cross-ID artifact, same SBOM/payload reuse and duplicate claim digest all
fail. Every redirect hop must remain HTTPS; authorization is removed on any
normalized scheme/host/effective-port origin change, and downgrade redirects are
rejected. The adversarial corpus is
`ops/fixtures/evidence_adversarial_v1.json`. Regeneration never renews evidence.

## 7. Remaining fail-closed Gates

- real DNS, certificate-expiry, broker, API, DB and storage fault injection with
  alert delivery and bounded recovery;
- production-like encrypted backup and independent restore with measured
  tenant/ACL/audit integrity, RPO and RTO;
- 24-hour load/soak including Android battery, ESP32-C6 heap/radio/reconnect,
  queue pressure, relay safety and physical OTA/rollback;
- privacy/legal owner approval of inventory, lawful basis, retention schedule,
  deletion exceptions and consent text;
- NAS reverse proxy, least-privilege broker/DB principals, secret rotation and
  on-call walkthrough;
- Samsung/OEM, real BLE/ESP32-C6/sensor/relay, Target bootloader and OTA-G1–G4,
  RELAY-G0–G2, operator canary, production signing and user physical acceptance.
