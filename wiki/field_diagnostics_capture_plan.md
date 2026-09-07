---
title: Field diagnostics capture plan
type: reference
project: smart-gatekeeper
status: implemented-source
updated: 2026-09-05
source_of_truth: true
applies_to:
  - gatekeeper_app
  - target
  - backend
  - administrator-ui
---

# Field diagnostics capture plan

## 1. Problem and outcome

The physical approach-test loop is long and a failed trial often leaves only a
phone screenshot plus the Target's latest retained status. The next iteration
must preserve enough bounded evidence before, during and after every attempt to
identify the first missing stage without reproducing the failure immediately.

The desired operator outcome is:

1. The owner reports a time or short test reference after one trial.
2. The administrator view groups mobile, Target and Backend evidence for that
   attempt.
3. The view names the last proven stage and first missing stage within five
   minutes, while retaining explicit uncertainty where no component could
   observe the radio or physical door leaf.

The D0-D2 software path is now implemented in source. This page does not claim
a NAS deployment, APK installation, Target OTA, RF reception or physical door
movement. The implementation does not alter access authorization and adds no
synchronous network work to the BLE/sensor/relay critical path.

## 2. Design-time foundation and gaps addressed

| Layer | Already implemented | Gap that extends the diagnosis cycle |
|---|---|---|
| Android | Redacted durable GATT ledger keeps 50 sessions; wake registration, latest detection, Target reason, transport status, presence-to-dispatch/ARMED and GATT phase timings exist | Flutter projects only the latest session/detection; support report v1 is a current snapshot and omits the rolling attempt history and several timing fields |
| Target | Per-session canonical events, asynchronous RAM/NVS/RTC outbox, signed terminal summary, boot/reset breadcrumb, MQTT/Wi-Fi/ACL/BLE-advertising status exist | A trial with no GATT session has no session event; retained status lacks bounded high-water counters/timestamps for accepted connection, challenge, proof and result stages |
| Backend | Append-only Target event history, signed terminal summary fallback, actor projection and administrator history exist | It does not ingest Android attempt evidence or present a cross-layer session completeness view; absent stages appear as blank history rather than an explicit classification |
| HA | Latest state, availability and selected diagnostics are projected | HA is an operator summary, not the forensic store; high-cardinality attempt traces must not be added as entities |
| Physical door | Sensor and relay FSM events exist | Without an independent door-contact input, relay completion cannot prove that the door leaf opened |

Repository source contains a Support Report and Advanced Diagnostics surface,
but installation on each family phone is a separate fact to verify. The plan
extends those surfaces instead of creating an unrelated diagnostic application.

## 3. Correlation contract

Use two identifiers and do not force a protocol change solely for logging:

- `mobile_attempt_id`: Android-generated UUIDv4 at an eligible OS wake. It is
  stored only in the redacted mobile ledger and is uploaded as a purpose-scoped
  opaque reference.
- `target_session_id`: Target-generated canonical GATT session UUID learned from
  the v2 challenge. Once known, the mobile record stores both values and the
  Backend joins them to Target canonical events.
- `field_test_ref`: optional short reference created when the user taps
  `현장 테스트 표시`. It snapshots preconditions and groups attempts in a bounded
  time window. Normal automatic access remains unchanged when no marker exists.

If no phone wake occurs, there is intentionally no fabricated access session.
The marker, mobile registration heartbeat and Target controller snapshot can
show that an attempt was intended, but cannot prove over-air advertisement
reception.

## 4. Bounded evidence to retain

### 4.1 Android rolling journal

Keep the existing maximum of 50 redacted sessions and add a bounded wake journal
instead of a raw log stream. Each attempt records fixed fields only:

- app version/build, Android SDK and process/service boot reference;
- field-test reference when present;
- wake registration requested/reconciled/enabled and current blocking code;
- OS callback source/time, callback latency, screen interactive state, result
  count, scan error and bounded RSSI sample;
- WorkManager enqueue/start times, expedited/fallback decision, BLE-owner wait;
- existing connect, service/CCCD, challenge, signing, proof-write and result-wait
  timings;
- Target session ID after challenge, active ACL version, Target wire reason,
  Android transport reason/status and terminal state.

Do not retain Bluetooth address, tenant/unit/device identifiers, credential ID,
challenge, nonce, proof, signature, key material, raw exception, URL or payload.
Support Report v2 previews the recent bounded journal before copying. Background
upload is a separate opt-in decision for each phone; without consent the journal
remains local and can still be copied explicitly.

### 4.2 Target checkpoint telemetry

Add boot-local monotonic high-water counters and last-stage times to the existing
retained diagnostic status:

- advertising health checks and restart results;
- accepted GATT connections and disconnects;
- v2 challenge issued, proof received, Result queued/sent;
- proof accepted/rejected and active ACL version;
- ARMED entry, sensor sample/threshold, relay ON/OFF and terminal completion;
- last active/terminal session reference and current FSM state.

The access callback updates RAM only. Existing deferred canonical-event and
status publication drains later from the main loop. Extend the RTC crash
breadcrumb with only last stage and opaque/canonical session reference so a
reset during the attempt is visible on the next boot. Avoid per-stage NVS writes
and preserve the current OTA/rollback partition and event queue formats unless a
versioned migration is proven.

Controller `advertising_active=true` proves the ESP BLE controller state, not
that an external phone received an RF packet. The administrator UI must label
this boundary.

### 4.3 Backend and administrator view

Add an authenticated, idempotent mobile diagnostic ingest endpoint and an
append-only, privacy-safe attempt table only after the per-phone diagnostic
upload decision is approved. Validate a fixed schema and reject unknown or
secret-bearing fields. Do not accept arbitrary text logs.

The administrator view groups by `target_session_id` when known and otherwise
shows field-test/mobile-attempt evidence by bounded time window. One row expands
into aligned lanes:

`phone wake → worker → GATT → proof → ACL/ARMED → sensor → relay → Backend ingest`

For every lane show `observed`, `failed`, `missing`, or `not observable`, plus
source boot/app version and received delay. Provide a redacted JSON export with
the same fields and existing administrator audit/consent controls. HA receives
only low-cardinality health summaries, never the full attempt journal.

Retention duration for uploaded mobile diagnostics is an owner/privacy decision;
the software must not invent a legal default. Local ring limits and Backend
deletion/export mechanisms remain explicit and independently testable.

## 5. First-missing-stage classification

| Last evidence | First missing evidence | Classification shown to operator |
|---|---|---|
| field marker/precondition only | phone wake callback | `PHONE_WAKE_NOT_OBSERVED`; Target controller status cannot exclude RF propagation failure |
| phone wake | WorkManager dispatch | `ANDROID_DISPATCH_NOT_OBSERVED` |
| worker dispatch | Target accepted connection | `GATT_CONNECT_NOT_OBSERVED` |
| Target connection | challenge/proof | `GATT_PROTOCOL_INCOMPLETE` with exact transport stage |
| proof received | verified ACL decision | Target wire reason or `TARGET_RESULT_NOT_OBSERVED` |
| ACL accepted | ARMED | `TARGET_FSM_ARM_NOT_OBSERVED` |
| ARMED | sensor threshold | `SENSOR_TRIGGER_NOT_OBSERVED` |
| sensor threshold | relay ON/OFF | `RELAY_TRANSITION_NOT_OBSERVED` |
| relay OFF/terminal | Backend canonical ingest | `BACKEND_INGEST_NOT_OBSERVED` while preserving Target success |
| Backend completion | physical door contact | `DOOR_MOVEMENT_UNCONFIRMED`; not a software failure classification |

The classifier is deterministic from fixed codes and stage presence. It does
not infer a root cause from timestamps alone and never changes an authorization
or physical-success result.

## 6. Delivery order

### Phase D0 — contract and fixtures

1. Define Support Report v2 and mobile-attempt schemas, allowed fields, size
   limits and redaction tests.
2. Add success, no-wake, dispatch-delay, GATT-disconnect, proof-denial,
   sensor-timeout, Target-reset and Backend-ingest-gap fixtures.
3. Add the deterministic first-missing-stage classifier and tests before UI.

Exit: synthetic fixtures classify the expected boundary and secret/PII fixtures
fail closed. No production behavior changes.

### Phase D1 — local capture without Backend dependency

1. Expose the recent 50 Android sessions and bounded wake journal through the
   existing MethodChannel.
2. Extend Support Report v2 and add the optional `현장 테스트 표시` action.
3. Add Target boot-local checkpoint counters and retained status fields using
   deferred publication only.
4. Extend the crash breadcrumb and verify reset/power-loss compatibility.

Exit: after an offline phone/Target test, one copied report plus retained Target
status identifies the first missing stage. Authentication latency regression is
within measurement noise and no synchronous MQTT call appears in callbacks.

### Phase D2 — automatic cross-layer correlation

1. Add consented authenticated mobile diagnostic upload with idempotency and a
   strict allow-list.
2. Store and join mobile attempts with Target events; keep unmatched attempts.
3. Add the administrator attempt timeline, missing-stage label and redacted
   export.

Exit: one marked and one unmarked trial on each approved phone appear in the
administrator view within five minutes and preserve exact app/Target boot,
firmware, ACL and stage evidence.

### Phase D3 — physical and soak evidence

1. Run repeated screen-off/pocket tests across owner, wife and daughter phones.
2. Force only approved safe fault cases: Bluetooth off, permission blocked,
   broker interruption after GATT, Target restart before proof and sensor
   timeout. Do not force relay/power faults on the installed door without a
   field procedure.
3. Measure p50/p95 presence-to-dispatch, GATT phase and presence-to-ARMED latency,
   evidence loss, duplicate rate and classification accuracy.
4. Treat actual door travel as pending until an approved contact sensor or
   direct operator observation is correlated.

Exit: every trial has one terminal or explicit missing-stage classification;
reboot/offline delivery is idempotent, no secret appears, and OTA install,
rollback and recovery remain independently usable.

## 7. Non-negotiable acceptance gates

- No raw credential, address, signature, payload, tenant/unit or secret leaves
  its current security boundary.
- Logging never blocks BLE callbacks, sensor sampling, relay control or OTA.
- A missing event never authorizes retry, door opening or success inference.
- Target event replay is idempotent and original event/boot/sequence identity is
  preserved.
- App update and Target dual-slot OTA/rollback are regression-tested.
- The UI distinguishes controller advertising, phone reception, authenticated
  Target FSM completion, relay command completion and physical door movement.
- Uploaded-mobile retention and consent are decided before D2 deployment.

## 8. Implemented source and remaining evidence

| Phase | Implemented source | Current evidence boundary |
|---|---|---|
| D0 | Strict `sgk-mobile-support-v2` Pydantic schema, 64 KiB request ceiling, fixed 50-session/100-wake bounds, secret-field rejection and deterministic first-missing-stage classifier | Synthetic contract tests only; field classification accuracy is not yet measured |
| D1 Android | MethodChannel exposes recent redacted sessions/wakes, app/SDK and opaque process reference; Support Report v2 includes phase timings; `현장 테스트 표시` creates a random 10-minute reference | Phone installation and screen-off/pocket capture remain pending |
| D1 Target | Boot-local GATT/proof/ARMED/sensor/relay/terminal counters and last stage/session are copied into deferred retained status; a separate version-1 RTC access breadcrumb survives warm reset | Compile/contract proof only; Target OTA and reset readback remain pending |
| D2 upload | Per-phone setting defaults OFF, discloses the fields and absent automatic-retention period, uploads only the strict redacted bundle using the established credential/public-key identity, and deduplicates by stable bundle digest | Owner reports enabling upload; the September 6 contract rejection is corrected in section 12. A real accepted phone bundle/admin-row readback is still unconfirmed |
| D2 Backend/admin | Schema 015 append-only idempotent storage, actor resolution, verified canonical-event join, fresh controller/previous-reset correlation and admin timeline are implemented; HA stays low-cardinality | NAS deployment and readiness are confirmed below; rendered real-phone admin-row readback remains separate |
| D3 | No physical test was automated or claimed | Owner/wife/daughter marked trials, fault cases, latency percentiles and door observation remain pending |

An expired field marker produces one final snapshot so `PHONE_WAKE_NOT_OBSERVED`
can be distinguished from an still-open test window. It is cleared locally only
after the Backend accepts that final bundle. While the app is foreground, a new
wake/session timestamp triggers a non-blocking upload; BLE callbacks themselves
only update the bounded local journal.

Uploaded records currently have no automatic deletion schedule. They are
append-only security/support evidence and the app says so before opt-in. A
privacy owner must select and execute the existing retention workflow before a
production policy promises automatic deletion; the code does not invent a
duration. This unresolved legal/operations policy does not weaken the default-
OFF consent gate, but it remains a release disclosure and production Gate.

## 9. Report UX and history reset (2026-09-06)

- Support Report pins consent, copy and reset actions in a bottom SafeArea,
  separate from scrolling JSON. A long report no longer requires scrolling
  through all records to reach Copy, and Android navigation padding is reserved.
- Manual copy defaults to the latest **10 sessions and 20 wake events**, sorted
  newest first. An explicit full-history switch retains the previous 50/100
  bounds. Consented automatic upload keeps its existing full bounded schema;
  the Backend wire contract and upload consent are unchanged.
- Refresh rebuilds the report and reads current native health when available,
  falling back to the caller's snapshot on bridge failure. Changing the report
  resets copy consent; load/copy/reset failures surface a retryable UI message.
- Clear requires an in-app confirmation. It persists a report cutoff timestamp
  and clears the local field-test marker. Reports omit older session updates and
  wake events; new updates appear automatically, including a session that was
  already running when Clear was pressed. Full-history mode honors the cutoff.
- This is **diagnostic-view reset, not a security-ledger purge**. Credentials,
  enrollment/ACL, upload consent, current health, active work, deduplication,
  unresolved-proof state and server-uploaded records are preserved. The native
  bounded ledger remains available to the worker; old versions can ignore the
  new view preference without compromising access/OTA rollback.
- No live phone records were cleared while implementing this feature. Tests use
  mocked local preferences, fake native reports and a 360×640 viewport with a
  48-pixel Android navigation inset; installation/rendering on the owner's phone
  remains a separate check.

Android's continuous callback early-return paths additionally journal fixed
`BLE_SCAN_NO_READY_HINT`, `BLE_SCAN_NO_ADDRESS` and `BLE_SCAN_STALE` codes, bounded
to one per reason per ten seconds. A missing ready hint can now be distinguished
from an absent exported callback without recording raw advertisement data.

## 10. Operator explanation: report, upload and test marker

### September 7 scan observation implementation (local, not deployed)

#### Local-PC read authentication boundary

Existing GET routes `/api/v1/admin/diagnostic-attempts` (summary) and
`/api/v1/admin/access-events` (Target history) accept the `sgk_admin_session`
cookie, not an arbitrary Bearer admin token. A local client may obtain that
cookie through the existing personal-password login or use an already valid
session. A proposed local variable such as `SGK_ADMIN_SESSION_COOKIE` is a
client-side naming convention only: code must read it and send the cookie;
setting it does not configure new Backend authorization. Sessions are held in
server memory, expire according to server policy (default 900 seconds) and are
lost on process restart. The environment must actually be visible to the tool
process; exporting in an unrelated terminal does not update an existing process.

Detailed stored mobile session/wake/lifecycle arrays still have no dedicated
administrator read/export route. The scan-observation implementation above
extends capture/ingest only. A durable diagnostics-only read token and detailed
read route remain separate implementation work; existing administrator sessions
have broader authority and must never be described as read-only tokens. Do not
paste secrets into chat, print them or commit them.

Follow-up owner approval implemented the separate
[diagnostic read API and PC client](diagnostics_read_api.md). Its token is not an
administrator session and grants only report-list/detail reads. This is local
implementation; the deployed administrator-only service remains unchanged until
Backend publication and NAS digest configuration are completed.

- Native scan diagnostics keep a separate bounded 32-entry registration/stop/
  invalidation/callback-error/recovery timeline. It cannot replace the presence
  journal's latest event or trigger authentication. Repeated identical lifecycle
  events are suppressed within ten seconds. Matching FIRST_MATCH/ALL_MATCHES
  packets update a separate last-packet timestamp, at most once per two seconds;
  MATCH_LOST, empty results and scan errors do not refresh packet evidence.
- Home/settings separate accepted registration from recent packet observation
  (15 seconds), no recent observation, absent evidence and uncertain clock. Old
  successful authentication is no longer presented as proof of current radio
  health. The legacy `healthy` field retains its last-session semantics for
  compatibility; the new optional `native.scan` contains observation, last packet
  timestamp and the closed, bounded lifecycle list. No address, credential,
  arbitrary error text or radio payload is added.
- Report Clear filters lifecycle rows using the same report cutoff; operational
  registration/last-packet facts, consent, credentials and replay/uncertain-proof
  state are not cleared. Recent/full reports both retain at most 32 lifecycle
  rows under the existing total byte budget. Backend accepts this optional
  extension, while omission preserves legacy canonical retry bytes.
- Deploy the Backend schema extension **before** publishing the new APK. The
  previously deployed strict Backend does not accept the added scan field; no
  coordinated production rollout or phone installation is claimed in this entry.
- Recovery still requires existing explicit scanner errors or lifecycle triggers,
  with existing bounded retry/ownership behavior. No radio-silence watchdog,
  periodic scan reset, Target reboot, authorization bypass or door action was
  added. This closes observation gaps, not the unproven field root cause.

September 7 clarification: accepted uploads persist their validated diagnostic
bundle as `mobile_diagnostic_bundles.payload_json`, including the exported
session/wake records. The administrator `diagnostic-attempts` endpoint and table
currently expose summary/classification projections, not the detailed stored
session/wake arrays. Raw-detail retrieval therefore needs an authorized database
read or a separately implemented authenticated detail/export route. A live
unauthenticated read on September 7 returned 401 `administrator session required`;
this says nothing about whether the owner's bundle is stored. Agent access to
Target MQTT does not confer administrator report access. Ask for manual copying
only as a fallback, distinguishing missing read access from missing upload.

- Support Report is the phone-side diagnostic bundle that the owner can inspect
  and explicitly copy/share. Opening or copying it does not itself upload it.
- Automatic field-diagnostic upload is an independent, default-OFF consented
  delivery path for the same kind of bounded diagnostic data to the Backend
  administrator. It is driven by the app screen's refresh/sync lifecycle, not a
  guaranteed always-running background uploader. Reopen the app after testing
  to give queued local observations an opportunity to upload.
- Field Test Marker labels a ten-minute observation window with a reference in
  the report. It does not trigger authentication, open the door, alter scanning,
  or extend access authorization. It also works in manually copied reports when
  automatic upload is disabled.
- For an isolated trial: clear the report view first, start the test marker,
  perform the approach test, then reopen the app and upload or copy the report.
  Clearing after starting the marker would remove that marker. Clearing the
  report view does not remove already uploaded Backend records.

## 11. Upload rejection diagnosis (2026-09-06)

- Owner enabled upload but could not find the earlier support report. Verified
  the production HTTPS OpenAPI schema read-only: diagnostic ingest exists, but
  native `stage` and `wake_registration_status` accept uppercase codes only;
  wake `strongest_rssi` accepts -127 through 20 or null.
- The app report builder emits `detectionStage.name` and registration status
  without uppercase normalization and passes RSSI integers through unchanged.
  The supplied report contains `waiting`, `registered` and RSSI 127. These are
  incompatible with both the current source and deployed schema. The latest
  mobile publication still contains these serialization paths.
- A local reproduction through the actual ACL router, with fake identity and
  storage only, returned HTTP 422 for those three field paths and made zero
  storage calls. Uppercase native codes and null for the out-of-range RSSI
  returned HTTP 200 with one fake storage call. This proves the contract defect,
  not observation of an individual live phone HTTP request.
- `_post` discards non-2xx status/detail; `uploadDiagnostics` returns false and
  the settings switch continues to display consent, not delivery success. No
  last-error/last-success UI is exposed. Retry is triggered by subsequent sync
  opportunities, not a durable delivery queue. Admin currently renders summary
  rows, not the full copied-report JSON.
- NAS SSH probes were refused, so production DB rows and phone-request access
  logs were not inspected. No live upload, credential operation, settings
  change, code fix or deployment was performed. Corrective work should align
  producer/consumer codes and unknown RSSI handling, expose upload outcome,
  retain bounded retry, and test real app-shaped reports against Backend ingest.

## 12. Compatible upload correction (2026-09-06)

- Backend normalizes bounded ASCII native stage/registration codes to uppercase
  for already installed v2 clients, and maps only the integer RSSI sentinel 127
  to null. All other field bounds, unknown-field rejection, credential matching
  and consent remain intact. New mobile reports uppercase those native fields
  and export unavailable/out-of-range RSSI as null.
- Settings distinguish consent from delivery with persisted last-success time,
  a safe error code (including HTTP 422), in-progress indication and a retry
  button. Server response bodies and credentials are never retained in status.
- While the screen is active, sync opportunities recur every 30 seconds and on
  app resume. Failures back off at least 30 seconds and honor a longer numeric
  Retry-After; automatic and manual attempts share the cooldown and in-flight
  guard. Consent is rechecked after building the report. This is not an
  always-running background uploader and does not alter BLE/control/OTA work.
- Same-content retries can have a new export timestamp but the same bundle ref.
  Backend now accepts this as a duplicate only when every other canonical byte
  matches, preserving the first stored row. Changed diagnostic evidence under
  the same ref is still rejected. This also supports old clients after a lost
  HTTP acknowledgement without a database migration.
- A shared synthetic report fixture is checked against the real Flutter report
  producer and the authenticated Backend route with fake storage. Legacy
  values, invalid data, changed-evidence conflicts, acknowledgement identity,
  HTTP error handling and status persistence have regression coverage.
- Dense full reports additionally discard oldest exported records until content
  fits 60 KiB, leaving room inside the existing 64 KiB authenticated request
  limit. Local operational history remains untouched. The route measures UTF-8
  canonical JSON bytes consistently with storage, not Python string formatting.
- Runtime implementation and local tests do not prove production deployment or
  a real phone upload. Those outcomes are recorded separately below/in the log.

### Exact Backend activation

- Run `34033139623` deployed source
  `0c965d99632449d2d5a9b7e4c76f4c79d49b7644` at
  `2026-09-06T12:31:59Z` (21:31:59 KST). The NAS evidence says `deployed`,
  loopback/public readiness passed, and independent public `/ready` returns
  the same source with every check true.
- A synthetic, unauthenticated live legacy-shaped request now reaches the
  authentication rejection (401), while invalid RSSI 126 still returns 422.
  No test report is persisted. This verifies deployed parsing and the retained
  authentication barrier, not receipt of the owner's actual phone bundle.

### Signed mobile publication

- Run `34033139669` published the same exact source as
  `1.0.0-g0c965d9` / 43901 at 21:44:39 KST. Publisher signing and NAS atomic
  promotion/readback passed. Independent HTTPS downloads from primary/fallback
  agree on metadata and both 55,594,137-byte APKs match manifest SHA-256
  `b7932838db0eaf516dbcd3128a469367a09d0496e8c188c42663b136217c81c7`.
- Update the phone without clearing report history, keep upload enabled, and
  open the app to allow synchronization. Confirm last-success status and then
  the real Backend admin row. Publication is not phone installation or evidence
  that the owner's original report has already been stored.
