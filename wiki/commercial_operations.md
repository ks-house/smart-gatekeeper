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
| support export | mTLS admin/auditor, tenant scope, opaque `consent_<32hex>`, 1–168-hour window, at most 500 records, recursive redaction, canonical SHA-256, immutable admin audit | local API tests only; consent UX, ticket closure deletion, and privacy-owner approval pending |
| retention deletion | mTLS tenant admin, CSRF, fresh mTLS, idempotency key, exact `sgk-retention-v1`, 30–3650 days, tenant-only `access_logs` deletion, immutable deletion/audit evidence | software and migration tests only; the actual number of days requires legal/privacy-owner approval |
| resilience | one persistent MQTTS publisher, QoS 1 confirmation, maximum 16 in-flight effects, non-blocking backpressure, three-failure circuit breaker, 15-second half-open probe, session discard/reconnect after failure | fake-client fault tests; real broker/DNS/certificate/storage recovery and Target receipt remain pending |
| API protection | bounded opaque-peer rate limits for authentication/control/privacy; unsafe admin routes retain session, role, tenant, CSRF and re-authentication checks | host API bypass tests; reverse-proxy and live network policy pending |
| health and metrics | process-only `/live` (legacy `/health` alias), dependency `/ready`, fixed-label Prometheus metrics behind admin mTLS | local tests; production scrape, alert delivery and on-call acknowledgement pending |
| production Compose | digest-pinned MariaDB, immutable digest-supplied API, external secrets, internal data network, no host port, no source bind mount, read-only API root, non-root UID, capability drop and resource limits | Compose rendering and image build; NAS/proxy/volume/secrets deployment pending |
| supply chain | fully resolved hash lock, digest-pinned Python/MariaDB, exact action commits, deterministic CycloneDX SBOM, license allow-list, high/critical vulnerability Gate, main-only GitHub provenance attestation | repository and hosted-CI contract; attestation exists only after a successful exact-main run |
| backup/recovery | dump manifest binds exact source commit, bytes, SHA-256, completion time and required tables; verify enforces RPO age; isolated restore check measures RTO and tenant/ACL/audit integrity | disposable MariaDB logical dump/separate-schema restore passes locally; independent operator restore from a production-like encrypted backup remains pending |
| SLO/evidence | fixed synthetic load evaluator plus generated fail-closed evidence register requiring commit, artifact digest, reviewer and expiry for any `passed` entry | nominal fixture is not a load/soak result; 24-hour device/broker/API/DB run remains pending |

The mobile and Target OTA paths remain independent. These changes do not alter
the signed mobile manifest, Target dual-slot state machine, periodic HTTPS,
authenticated local recovery, N/N-1 protocol window, or rollback semantics.

## 2. Health, readiness, and metrics

### 2.1 Endpoints

| Endpoint | Authentication | Meaning |
|---|---|---|
| `GET /live` | reverse-proxy network boundary | Python process is responsive; never means DB, MQTT, Target or production healthy |
| `GET /health` | same | compatibility alias; response explicitly says `scope=process_liveness_only` |
| `GET /ready` | deployment network boundary | `200` only when DB `SELECT 1`, broker TLS/MQTT session, secret prerequisites and exact 40-hex `BUILD_SHA` all pass; otherwise `503` with per-component booleans |
| `GET /api/v1/admin/metrics` | current mTLS admin/auditor session and tenant `*` | low-cardinality request, MQTT and breaker metrics; no tenant/device/MAC labels |

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

The operator first records informed consent in the support system and uses only
its opaque reference. The response contains fixed operational fields, redacted
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
Deletion affects only the tenant's legacy access records; immutable admin audit
and deletion evidence are preserved. A duplicate idempotency key returns the
existing result and never repeats the deletion.

## 4. Backup and isolated restore procedure

1. Record exact application image digest, `BUILD_SHA`, schema/migration set and
   backup start time. Stop schema changes during the snapshot window.
2. Use the database platform's secret-file authentication and consistent
   transaction snapshot to create a dump in encrypted, access-controlled
   storage. Never place a password on a command line or in the manifest.
3. Bind the dump to source and required tables:

```powershell
python scripts/ops_commercial_gate.py backup-manifest `
  --dump <encrypted-staging-dump.sql> `
  --output <backup-manifest.json> `
  --source-commit <40-hex-commit> `
  --completed-at <UTC-RFC3339>

python scripts/ops_commercial_gate.py verify-backup `
  --dump <encrypted-staging-dump.sql> `
  --manifest <backup-manifest.json> `
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
  --restore-started-at <UTC-RFC3339> --now <UTC-RFC3339> `
  --max-rto-seconds 1800
```

6. Require all tenant/access, ACL credential/snapshot, immutable admin audit and
   privacy deletion invariants to pass. Compare expected aggregate counts from
   the approved backup record. Destroy the isolated restore and temporary
   secret using the approved recoverable lifecycle procedure.

The candidate objectives are RPO ≤15 minutes and RTO ≤30 minutes. They remain
unproven until an independent operator performs the full restore using a
production-like encrypted backup and records timestamps and artifact digests.

## 5. Supply-chain and deployment Gate

Run locally from the repository root:

```powershell
python scripts/ops_commercial_gate.py contract
python scripts/ops_commercial_gate.py sbom --output build/backend-sbom.cdx.json
python scripts/ops_commercial_gate.py slo --samples ops/fixtures/load_nominal.jsonl --policy ops/slo_policy.json
python -m unittest discover -s backend/tests -p "test_*.py" -v
docker compose -f backend/docker-compose.yml config --quiet
```

The hosted backend workflow installs `requirements.lock` with
`--require-hashes`, runs the full security suite, policy/SBOM/SLO Gates,
high/critical vulnerability audit and MariaDB migration test. On exact main it
attests the generated SBOM with GitHub's identity. An SBOM upload without a
successful attestation does not satisfy provenance.

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

The generator rejects any `passed` record without artifact SHA-256, reviewer
and expiry. Local, hosted, independent restore, physical/live-like soak and
production scopes stay separate. Regeneration after an expired artifact does
not renew evidence; a new test and review are required.

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
