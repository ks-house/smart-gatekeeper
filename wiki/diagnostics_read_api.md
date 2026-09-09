# Local-PC diagnostic read API

Status: Backend `a105539273f9eb2aeaf0362d17bcc967336d85a7` deployed via PR #393
at 00:16 KST on September 9. Incident/health history, standalone access history
and existing report reads are verified using the same PC token activated on September 7.
This is separate from administrator cookie authentication and from door control.

The reliability extension is **deployed and independently read back** with schema
016. Existing NAS digest/token/wrapper remain unchanged. New native phone capture
and signed sensor summaries additionally require the independently published app
and Target firmware to be installed; Backend deployment alone does not enable them.

## Agent triage: use this API before requesting NAS access

When the owner asks to inspect Backend-held diagnostic history, first use the
existing local token with the deployed routes below. Also query standalone
access events for the requested
period even if the latest mobile report is old. Do not reinterpret that request
as exclusively Docker stdout logs and prematurely require SSH or manual exports.
Only distinguish unavailable runtime logs after actually checking available
reports and correlated Target events.

On September 8 around 13:00 KST, authenticated list/detail reads succeeded using
the preexisting token. Temporary client-only resolution to the known NAS LAN
address preserved the original HTTPS hostname, certificate checks and redirect
refusal; no system DNS or credentials were changed. Latest stored row remained
141, received **September 7 15:50:48.856 KST**, app 44201. Its latest session and
correlated event were September 7 12:21:38 and 12:22:00.862 respectively; all 34
returned Target events were historical, with truncation false. No new September 8
report was returned. This is a diagnostic evidence gap, not proof of no access
attempts, no Target events outside the report's sessions, or failed ingestion.

Historical source `3c08e6b` hosted upload orchestration in
`SmartKeyHomeScreen`: initialization/resume, a resumed-only 30-second retry timer,
and health-change/marker/settings callbacks. Upload is consent-gated, suppresses
unchanged bundle references and stops with the screen lifecycle. There is no
independent durable background uploader in that older app path. Missing reports may
involve lifecycle, unchanged contents, consent or network/auth errors; this API
alone cannot select a cause. A stored `healthy=true` is not current liveness.

## Scope

The dedicated token can perform only these reads:

| Route | Result |
| --- | --- |
| `GET /api/v1/diagnostics/bundles?limit=20&before_id=…` | Most recently stored opted-in reports, receipt/export times, database row IDs and pagination cursor |
| `GET /api/v1/diagnostics/bundles/{id}` | Validated report including sessions/wakes/optional scan lifecycle, plus up to 500 matching integrity-verified Target events |
| `GET /api/v1/diagnostics/access-events` | Independent verified access history, receipt-time window and Target/session/boot/event filters, paginated by row ID; deployed September 8 |
| `GET /api/v1/diagnostics/health-history` | Sampled verified state/boot history, separate unsigned advisory fields; deployed September 8 |
| `GET /api/v1/diagnostics/incidents` | Bounded Target sessions, independent mobile failure/skip observations and signed sensor summaries, explicit missing/stale evidence; deployed September 8 |

`id` is the decimal row ID returned by the list, not `bundle_ref`. Different
phones can have identical content references, so the latter is not an exact
database identity. IDs/timestamps are strings where needed to preserve integer
precision. Target event truncation is explicit; absent events do not prove that
no physical action occurred. A successful mobile session still does not prove
door movement.

This capability reads all opted-in mobile bundles in this single-owner Backend,
not only one phone. The September 8 owner-authorized extension also reads all
integrity-verified Target access events independently of mobile upload consent
or support-bundle availability. It does not enable new collection. The bundle
list excludes tenant/credential IDs and names; the detail
revalidates the closed support schema and excludes arbitrary DB columns. It is
not a tenant-scoped commercial support credential. It cannot create admin
sessions, read general admin routes, change settings, enroll devices, trigger
OTA or open doors. There is no POST/PUT/DELETE route or command publisher here.

## Independent access history (September 8 extension)

### Reliability release extension (Backend deployed; device installation separate)

The same read token adds `--incidents` and `--health-history` to the PC client.
The new routes preserve the time-window, no-store, rate-limit and read-only
boundaries. Incident responses are not atomic snapshots and report their coverage;
Target events, mobile reports and sensor-only observations have independent
pagination/coverage limits. A stale phone report is not evidence that the phone
woke now. Backend receipt windows are not physical arrival windows.

Schema 016 adds append-only sampled Target health and independently authenticated
terminal sensor summaries. The old schema rollback preserves these evidence
tables. Signed status core and unsigned advisory counters are returned separately;
an ESP32 self-reported advertising flag does not prove RF reception, and commanded
relay state does not prove actual door movement. Sensor summaries carry their own
MAC and original boot/session/terminal position, including retransmission after a
later boot. Exact duplicates can be acknowledged without refreshing core liveness.

Mobile runtime observations are opt-in and now originate from a native durable
outbox, independent of the Flutter screen. Only an exact server bundle receipt
retires the pending immutable report. Clear, consent withdrawal, credential or
upload-authority change invalidate the pending generation. No MAC address, keys,
raw advertisement or exception text are added to the report. A phone that the OS
does not run cannot be diagnosed as healthy merely because scheduling was registered.

Target access and sensor receipts use existing command transport with distinct
HMAC domains and exact original-record identity. They acknowledge DB commit only;
they have no relay, authentication, OTA or replay-ledger authority. No NAS wrapper
or token registration change is required for these routes.

`GET /api/v1/diagnostics/access-events` uses the same Bearer token and shared
60/minute rate limit. No administrator cookie or new token registration is
needed. Only `integrity_status='verified'` rows are returned; unsigned legacy
events are intentionally excluded, including when no filter is supplied.

- `since` / `until`: timezone-aware ISO 8601, inclusive start/exclusive end;
  default end is request time and default start is 24 hours before end. Maximum
  positive interval is 31 days. `Z` and `+09:00` are accepted; naive local times
  are rejected. Invalid dates, ranges or filters return 422 without querying DB.
- `target_id`, `session_id`, `boot_count`, `event_code`: optional exact filters.
  `boot_count` should normally be paired with Target ID. Event code is the stored
  uppercase code, e.g. `ACCESS_ARMED`; no filter returns all verified event kinds,
  including failures and termination, not only successful entry.
- `limit`: 1–100, API default 100 (PC client default 20).
- `before_id`: exclusive descending database ID cursor. The response contains
  `events`, `next_before_id` (null at the end), normalized UTC `since`/`until`,
  `time_basis: received_at`, `order: id_desc`, `integrity_status: verified`.
  Reuse the returned interval and all filters with each next cursor. Distinct
  events with equal timestamps remain pageable. This is not an atomic snapshot
  across concurrent requests; rerun a window to include late-ingested events.

Each event exposes session/event IDs, Target ID, boot ID/count, source sequence,
attempt, event code/stage/outcome/reason, access path/transport, distance,
duration, relay hold, device monotonic time, clock quality, pseudonymous
`credential_ref`, integrity status and Backend receipt time. Database ID, boot
count, source sequence and monotonic milliseconds are decimal strings to avoid
64-bit precision loss. No resident names/room numbers, raw payloads, integrity
tags, signing keys or general administrator data are returned.

**Time semantics:** filtering and ordering represent Backend ingestion, not
necessarily physical sensor occurrence. Queued MQTT delivery can arrive later.
Compare boot ID/count, monotonic time and sequence within the same boot to
analyze ordering; never compare monotonic values across boots as wall time.
An empty interval means no matching verified rows were returned, not proof of
no physical entry, no firmware activity or a healthy collector. This endpoint
does not expose Docker logs or a complete Wi-Fi/power/reset timeline.

Query on this WSL PC with its existing token:

```bash
python3 scripts/read_diagnostics.py --access-events --limit 100
python3 scripts/read_diagnostics.py --access-events \
  --since '2026-09-08T00:00:00+09:00' \
  --until '2026-09-09T00:00:00+09:00' --limit 100
```

Use the actual date and optionally add `--target-id`, `--session-id`,
`--boot-count` or `--event-code`. To continue a result, add `--before-id` with
its returned `next_before_id` and preserve the exact returned `since`/`until`.
The client URL-encodes timezone offsets so `+09:00` is not treated as whitespace.
Do not combine `--access-events` with bundle detail or token initialization;
event filters without `--access-events` are rejected rather than silently ignored.
Output is inspection JSON, not public telemetry; keep any saved reports private.

## Server configuration and rollout

Set `DIAGNOSTICS_READ_TOKEN_SHA256` to the lowercase SHA-256 hex digest of the
client's randomly generated token. Both Compose profiles pass this optional
value. Empty/malformed configuration disables only these reads (503), not
normal access/readiness/OTA. No DB migration is required.

The current NAS wrapper rejects unknown runtime keys. **First review/admit and
install the updated wrapper** that permits this optional digest, keeping every
other exact-key check. Only then add the single digest assignment to the existing
root-controlled `runtime.env`; do not replace that file with the one-line snippet. Deploy the
Backend containing these routes and recreate its API container through the
normal deployment path. Do not send the raw token to CI, firmware, HA or mobile.
Server restart keeps the capability when the configured digest is unchanged.
To revoke it, remove/change the digest and recreate the API container. This
single-owner token has no built-in expiry, so revoke it if the PC/file is lost
or compromised. It is not the mobile API key or administrator password.

The server compares digests in constant time, limits reads/failed requests to
60 per minute per peer per process, returns `Cache-Control: no-store` for data,
and keeps query sizes bounded. A shared reverse-proxy peer shares that quota.
TLS is required on the public endpoint. Tokens must never be sent in a query
string. Do not enable request-header/body logging for this endpoint.

## Local PC (WSL Bash)

### Owner activation order for the existing PC token

This is a NAS runtime setting, not a GitHub Secret, mobile setting or HA key.
The existing PC token remains local; transfer only the approved
`backend/deploy/sgk_backend_deploy.sh` and the hash-only
`/home/sh-cat-lee/.config/smart-gatekeeper/diagnostics-read.server.env` snippet.
Use the owner's SSH account on port 8822. If SCP reports an unavailable SFTP
subsystem, the client's `scp -O -P 8822` uses the legacy SCP transport without
disabling SSH host-key checks.

Install the reviewed wrapper root-owned, mode 0755, at
`/volume1/docker/smart-gatekeeper-backend/bin/sgk_backend_deploy.sh` **before**
editing `/volume1/docker/smart-gatekeeper-backend/runtime.env`. Keep a backup of
the existing wrapper first. Copy only the `DIAGNOSTICS_READ_TOKEN_SHA256=...`
line from the snippet into that existing runtime file, replacing that key if
already present and preserving all other keys and its root-only permissions.
Never replace the full runtime file with the snippet.

Saving the runtime file does not activate the running API. A plain Docker
restart reuses its old environment; request normal Backend deployment/container
recreation, then run the PC client with `--limit 1`. HTTP 200 with a list (even
an empty one) proves read authorization; an empty list is not successful upload
evidence. Local `--check-token` alone proves neither NAS activation nor upload.
These are owner instructions, not a claim that remote settings were changed.

One-time generation, without displaying the token:

```bash
python3 scripts/read_diagnostics.py --init-token
```

This creates `~/.config/smart-gatekeeper/diagnostics-read.token` with mode 0600,
refuses an existing destination, and prints only the file location and server
digest assignment. It was already run on the current owner's WSL PC during this
implementation; **do not rerun it to retry a failed read**. A separate local
`diagnostics-read.server.env` snippet contains only the digest for NAS setup.

The client automatically uses that default token file. Alternatively provide
exactly one of `SGK_DIAGNOSTICS_READ_TOKEN` or
`SGK_DIAGNOSTICS_READ_TOKEN_FILE` in the actual client process environment:

```bash
export SGK_DIAGNOSTICS_READ_TOKEN_FILE="$HOME/.config/smart-gatekeeper/diagnostics-read.token"
python3 scripts/read_diagnostics.py --check-token
python3 scripts/read_diagnostics.py --limit 20
python3 scripts/read_diagnostics.py --bundle-id 123
```

Replace `123` with a returned ID. `--check-token` validates local availability
only, never Backend activation. The default origin is the owner's HTTPS backend;
`--base-url` accepts another HTTPS origin without credentials/path/query. TLS
certificate verification is never disabled. Redirects are refused so a response
cannot forward the Authorization header elsewhere. Tokens are not CLI arguments
or output, and error output does not echo response bodies or headers. Successful
report JSON is intentionally printed for local inspection; do not publish it.

HTTP 404 can mean the old deployment lacks the route (or a detail row is absent),
503 can mean the capability is disabled or storage unavailable, 401 means the
token does not match, and 429 means wait for the limit to reset. Do not retry by
generating another token or changing the administrator password.

## Validation and evidence boundary

September 8 extension: 21 focused API/client tests pass (13 Backend, 8 PC),
covering independent history, unchanged token authorization, parameterized
filters, UTC/KST receipt windows, 31-day/page bounds, equal-time ID pagination,
64-bit precision, closed projection, safe storage failures and shared rate
limits. Full Backend suite: 239 tests, no failures, two existing real-MariaDB
skips. Root suite: 382 tests, no failures, one PowerShell-availability skip.
OTA contract passes. These are local automated results, not NAS route/readback
or physical-entry evidence. Deployment and real stored-event query were
subsequently verified below; existing mobile/Target ingestion paths are unchanged.

The following results and rollout evidence describe the original September 7
report API release, not deployment of the September 8 extension.

Tests cover disabled/wrong credentials without DB calls, read-only methods and
no administrator authority, list bounds/cursor, exact row retrieval, verified
event correlation, malformed stored-report rejection, safe errors, rate limits,
private non-overwriting token creation, env/file exclusivity, HTTPS and redirect
guards. Existing administrator/mobile/OTA routes retain their own authorization.
Live NAS activation and real uploaded-report list/detail readback are now
verified; see the September 7 activation evidence below.

Local results: 233 Backend tests complete with two existing real-MariaDB skips,
four PC-client tests pass, and the OTA contract passes. The new API/client tests
account for seven/four tests respectively. Existing route inventory assertions
now use OpenAPI paths rather than assuming every FastAPI router node has `.path`.

The following deployment-input changes were separately admitted by policy
PR #388 before merge-connecting that main into PR #387. Local policy tests and
the hosted trusted-base check pass; all 23 protected paths remain enforced:

| Protected candidate | SHA-256 |
| --- | --- |
| `backend/compose.production.yml` | `709f70c7683636a0eb34a9822212b4369d5e5b906bbdeae81c3e2307236f953a` |
| `backend/deploy/sgk_backend_deploy.sh` | `c368931822e5bf6c2cb50b9d12f7b0fe372f61f47f03eb98245b9c0e48118003` |
| `ops/backend_trusted_bundle_paths.json` | `b4512474c0bda2901b978b038f7dd47dd5b401066bb9521f2e4f8d4b7086db65` |

The unauthenticated live list-route probe returned 404 on September 7. The local
token file exists with mode 0600 and `--check-token` succeeds, but neither proves
NAS activation. Do not generate another token to resolve that 404.

After deployment run `34086666204`, external `/ready` returns that exact source
and all checks pass (DB, MQTT, collector, authentication and evidence integrity).
API image digest is `9c56cdb92797158dbfd31fef40f327336a26a3a59c79f64ab0c6fa60a86a6439`.
The dedicated PC token now receives 503, consistent with the deliberately
disabled capability until NAS digest configuration. This is not an empty report
list and does not establish real report readback.

The current GitHub production variable identifies NAS SSH port **8822**.
Port 22 refuses connections; port 8822 is reachable but this PC's available
noninteractive authentication is rejected. CI's forced `apply`/`status` key
does not authorize editing the root wrapper or runtime configuration. Owner
setup must use the existing NAS administrative path and the previously created
digest snippet; do not regenerate the PC token or loosen the forced key.

## September 7 owner-confirmed activation

After the owner confirmed wrapper replacement and digest registration, only the
NAS deployment job of verified run `34086666204` was rerun (attempt 2). The
existing signed-source image was retained: newer main differed only in wiki
documentation. No rebuild, APK publication, Target command or authorization
policy change was needed. Deployment completed at `2026-09-07T07:08:15Z`.

External `/ready` returns source `00bee34343827181cbaa449244dbfe96044a6e94` with
all checks true. The preexisting PC token reads both list and detail successfully.
Latest inspected stored report was received at 15:50:48 KST, from app build
44201, with 12 sessions, 100 wake events, 11 scan lifecycle entries and 34
correlated verified Target events. This proves an uploaded report is available
for remote inspection, not that a particular physical approach succeeded.

Missing/wrong diagnostic tokens and use of the diagnostic token on the existing
administrator-summary route each return 401. The raw PC token was not printed,
regenerated or sent to GitHub. Future uploaded reports can be inspected through
the existing client; upload consent and actual last-success time still matter.

## September 8 independent history rollout

PR #390 merged the tested feature to exact main
`3c08e6b8ce60fd693103df868715215e8fbfe2f2`. Read-only NAS preflight run
`34211540652` passed before deployment. Main run `34211698089` passed Backend
security and real-MariaDB checks, operations evidence and image publication;
the separate main OTA contract run passed too. Owner-requested production
deployment finished at 18:50 KST, with matching forced apply/status evidence.
API digest: `6955b04f9275f2d20a3594b5376eb9bcf5bbc8b754991d241da1e6bd7a093f47`.

At 18:50–18:51 KST, independent HTTPS `/ready` returned that exact source with
all checks true and fresh authenticated Target status. System DNS resolved
normally for the authenticated PC readback; no TLS bypass or token change.
The same local token retrieved today's verified access history across two
two-row pages with distinct IDs and a fixed receipt-time interval. Combined
Target/session/boot/event filtering also succeeded. Latest inspected row was
received September 8 **16:11:22.784 KST**, code `ACCESS_SESSION_COMPLETED`.
This is a stored event, not independent proof of physical door movement.

Existing bundle reads remained successful. Missing/wrong tokens on the new
route and the diagnostic token on the administrator access-event route each
returned 401. No new data collection, device command, APK publication or Target
OTA was performed. Earlier stale-report evidence does not contradict today's
standalone access rows: the new route no longer requires mobile-session linkage.

## September 8 reliability-history rollout

PR #392 merged to `81fbc6dc9b9286b2d4375afeda9129566789ad2a` after policy
admission PR #391. Backend run `34240363175` deployed schema 016 and the API
between 23:52:33 and 23:54:11 KST. External `/ready` returned the exact source,
all 12 checks true and fresh verified Target status.

Independent authenticated reads observed health rows 1, 2 and 3 at
23:54:06.207, 23:54:36.932 and 23:55:07.631 KST, with the same verified boot
784 and increasing status revisions 4085, 4115 and 4145. Firmware advisory
remained old `2.1.469+main.g6a45aec`, separate from newly published Target
`2.1.480+main.g81fbc6d`; this is not new firmware installation evidence.

The incident API returned the earlier boot-782 `ARM_TIMEOUT` and
`GATT_DISCONNECTED` sessions, explicitly marking missing sensor evidence, stale
pre-window mobile data and `mobile_reports_truncated=true`. Other inspected
coverage flags were false. Existing report list/detail and access-events CLI
reads passed; both new routes returned 401 for missing and wrong tokens. New
report row 143 arrived at 23:41:17 from old APK 44201 and is not native-outbox
execution evidence. No synthetic production report or device command was sent.

Live HTTPS testing found the common middleware overwrote diagnostic `no-store`
with `no-cache`, although router-only tests passed. This additional defect was
corrected by the September 9 hotfix below; the initial deployment did not
satisfy that header contract.

## September 9 operational readback corrections

### September 9 follow-up: audit conflict custody (local implementation, not deployed)

Schema017 adds immutable `access_event_conflicts`, separately from normal access
history. MAC-verified conflicting envelopes are durably preserved before the
existing exact-event receipt may retire the Target head. This receipt means DB
custody, not a successful canonical-history insert or physical entry. Quarantined
events do not drive the HA success outbox. Commit failure never emits a receipt;
replay checks the exact stored content. Application rollback preserves the table.

The same read-only token can query `GET /api/v1/diagnostics/audit-conflicts`, or:

```bash
.venv/bin/python scripts/read_diagnostics.py --audit-conflicts --target-id c0feffe6ebac --boot-count 808
```

It returns `conflicts` and `next_before_id`, with `disposition=QUARANTINED` and
`reason_code=IDENTITY_CONFLICT`. It accepts the same since/until/limit/before_id/
target_id/session_id/boot_count/event_code filters as access history. Dates use
server receipt time (default24h, maximum31d), not physical event time. No raw
envelope, MAC or key material is exposed. Normal `--access-events` stays separate.

New Target periodic status exposes durable/total pending audit depth, head wait,
publish attempts, original head boot count and a15-second pending advisory flag.
These appear under health-history `unsigned_advisory`, never the signed status
core or the access verdict. Head wait is time observed **in the current boot**,
not the old event's age. A healthy status stream alone is not audit progress.
This extension needs Backend/schema017 deployment and a new Target for the added
counters. The token and NAS wrapper registration do not change.

### Previously deployed schema016 corrections

The full-app middleware now preserves diagnostic `Cache-Control: no-store` on
success, authentication/validation/routing errors, rate limit, handled storage
failures and generic unexpected failures. The regression runs through actual
`main.app`, not an isolated router. No exception detail is returned.

The old Target already emits retained `/boot` diagnostic fields, but the old
subscriber discarded them. A bounded cache now accepts only configured exact
Target topics, payloads up to 4 KiB and closed projected fields, retaining at
most 32 boot identities. It does not update the boot registry, liveness or
command authority. A subsequent MAC-verified, high-water-accepted status can
attach only the exact matching Target/boot ID/boot count observation to the
existing health history. A replayed status does not create new health history.

`unsigned_advisory.boot_observation` explicitly records `MQTT_BOOT_ADVISORY`,
`UNSIGNED`, whether the message was retained, its server receipt time and
`generation_time=NOT_OBSERVED`. Its reset/planned restart/previous action, heap,
network and access breadcrumb fields remain advisory, not signed crash proof.
The API revalidates the nested identity and closed projection. It excludes IP,
BSSID, arbitrary exception/log strings, raw coredump contents and keys.
Periodic status GATT/advertising/network counters and sensor-clearance codes
are also retained instead of being discarded by the earlier projection.

This is a Backend-only correction using schema 016; no additional migration,
token/wrapper change or mobile/Target rebuild is required. Production readback
of these corrections passed as recorded below. OTA in-flight stage and errors not emitted by
the current Target remain unobservable; a retained boot receipt is not its
generation timestamp and does not demonstrate a new reboot.

PR #393 merged to exact `a105539273f9eb2aeaf0362d17bcc967336d85a7`; Backend
run `34243125046` deployed between September 9 00:14:44 and 00:16:16 KST.
Independent `/ready` matches the source, all 12 checks true and Target fresh.
All four diagnostic routes returned exactly `Cache-Control: no-store` for
200, missing-token 401, wrong-token 401 and invalid-query 422 responses.

Historical rows 1 and 36 retain their original receipt/core/advisory data.
New row 46 at 00:17:10.672 KST includes an exact same-boot-784 unsigned boot
observation, retained=true, received at 00:16:07.306 KST. Its fields report
`planned_restart=none`, `previous_action=https_date_clock_trusted`, previous
IDLE/relay OFF and previous uptime 1,977,020 ms. The repeated BROWNOUT code 9
belongs to that same boot and does not prove a new voltage drop at read time.
The current periodic advisory shows old firmware `2.1.469+main.g6a45aec`,
uptime 5,585 seconds, BLE expected/active=true, no current connections and zero
current-boot GATT/auth/sensor/relay counts. These are not independent RF or
physical-door observations. New firmware `2.1.480` installation is still unobserved.
