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
| D2 upload | Per-phone setting defaults OFF, discloses the fields and absent automatic-retention period, uploads only the strict redacted bundle using the established credential/public-key identity, and deduplicates by stable bundle digest | Enabling the switch is the phone-owner consent action; no phone has enabled or uploaded it yet |
| D2 Backend/admin | Schema 015 append-only idempotent storage, actor resolution, verified canonical-event join, fresh controller/previous-reset correlation and admin timeline are implemented; HA stays low-cardinality | Trusted-policy review, NAS migration/deployment and rendered admin readback remain pending |
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
