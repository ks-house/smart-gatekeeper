---
title: Continuous presence and delayed reauthentication
type: incident
project: smart-gatekeeper
status: active
updated: 2026-09-06
source_of_truth: true
applies_to: [android, target, backend]
---

# Continuous presence and delayed reauthentication

## Evidence boundary

The owner remained at the entrance and reported a long delay between access
termination and the next authentication. The supplied activity screenshot shows:

| Displayed time on September 6 | Displayed event |
|---|---|
| 12:35:06 | Local authentication succeeded / access ready |
| 12:35:07 | Target sensor-wait projection |
| 12:36:07 | Access terminated without completion |
| 12:38:20 | Next Target authentication running |
| 12:38:22 | Local authentication succeeded / access ready |
| 12:38:23 | Target sensor-wait projection |
| 12:38:35 | Access completed / next authentication available |

The visible termination-to-next-start gap is 133 seconds. The second running-to-
ready interval is approximately two seconds. The screenshot contains no later
authentication and cannot measure the delay after 12:38:35. Backend-projected
activity timestamps use event receipt time when available, whereas native
authentication uses mobile time; these are not a synchronized radio trace.

This analysis inspected main `1f3997089adea0923c955d4508ba1d61c0d52f21`.
Its Target, Android and Backend application sources have no diff from
`6701f32b95116514698d7a66672738b31062b736`, the prior rollout's source reference.
No live phone journal, uploaded incident bundle, Target status or installed app
version was retrieved in this turn. Prior installation evidence is not a fresh
runtime check. The owner's sustained presence is accepted; excessive proximity
or a brief dwell is not assumed.

## Source-confirmed current sequence

1. [BleWakeRegistrar](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/blewake/BleWakeRegistrar.kt)
   registers LOW_POWER scanning with FIRST_MATCH and MATCH_LOST. FIRST_MATCH
   reports initial discovery, not periodic continued presence. Android documents
   these semantics in [ScanSettings](https://developer.android.com/reference/android/bluetooth/le/ScanSettings).
2. [BleWakeNativeEntrypoint](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/blewake/BleWakeNativeEntrypoint.kt)
   dispatches a presence event to WorkManager. MATCH_LOST only records exit and
   dismisses the ready notice. Registration recovery is not a continuous-presence
   reauthentication scheduler.
3. [BleGattCredentialWorker](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/BleGattCredentialWorker.kt)
   performs local v2 action-1, records SUCCEEDED at ARMED, deletes its temporary
   locator, posts the notice, and ends. It schedules retries only for eligible
   failures, not after successful sensor arming. Identical OS wake redelivery is
   coalesced and a completed durable session is not replayed.
4. [TargetAccessFsm](../src/TargetAccessFsm.cpp) admits authentication only from
   IDLE with relay OFF. ARMED expires at the configured duration (default/max
   60 seconds), or a sensor trigger causes one-second relay hold and configured
   cooldown (default three seconds, range one to ten). No authenticated presence
   renewal or queued next authentication exists during ARMED/hold/cooldown.
5. [main.cpp](../src/main.cpp) samples the ultrasonic sensor only in ARMED, with
   a 100 ms loop delay plus processing time. Authentication resets the five-sample
   median history, requiring at least three fresh qualifying readings. Outside
   ARMED the sensor cannot initiate a new phone authentication.
6. [smart_key_home_screen.dart](../gatekeeper_app/lib/screens/smart_key_home_screen.dart)
   polls exact-session Backend evidence every four seconds while mounted, with
   a maximum 120-second window. Completion closes polling and dismisses the
   notice; it never schedules the next native authentication.

Consequently, `next_auth_ready` means the Backend observed eligible Target state,
not that the phone has queued an authentication. Continuous presence may produce
no fresh FIRST_MATCH until the OS detects a loss/new match or registration changes.
There is no fixed 133-second retry timer in the inspected successful-session path.
The 120-second UI polling window does not itself gate native authentication.

## Reproduced Target lease defect

[AccessCriticalLeasePolicy](../include/AccessCriticalLeasePolicy.h) retains a
shared epoch until 30 seconds of continuous noncritical time or a new verified
action generation. [main.cpp](../src/main.cpp) evaluates that epoch against an
85-second limit during physical access and a ten-second limit before proof.
Successful physical-session termination does not retire the epoch. A subsequent
AUTH_PENDING still has the old generation until proof succeeds.

The following host reproduction uses the real FSM and lease class:

| Simulated time | Call / result |
|---|---|
| 0 ms | Begin authentication; generation 0, ten-second lease |
| 2,000 ms | Grant ARMED; generation 1 starts physical lease |
| 62,000 ms | Arm expires; FSM enters IDLE and quiet timer starts |
| 63,000 ms | New authentication accepted by FSM; old epoch immediately exceeds ten-second pre-proof limit |
| 63,001–93,001 ms | Continuous quiet window retires epoch |
| 93,002 ms | New authentication receives a fresh lease |

A second case grants at 2,000 ms, detects the sensor at 12,000 ms, finishes relay
at 13,000 ms and cooldown at 16,000 ms. Authentication at 17,000 ms is likewise
classified as expired. The main-loop enforcement path aborts unverified GATT
ingress and cleans the FSM to IDLE when this predicate is true.

Both cases reproduced using C++17 with warnings as errors. The existing recovery
policy executable also passed all 105 checks: its coverage includes unverified
reconnect abuse, quiet reset and verified grant, but omits the verified-terminal-
to-next-auth transition. The reproduction is host policy evidence, not proof
that this exact defect occurred during the screenshot's 133-second gap. Timing
relative to proof completion matters; the behavior is not an unconditional
30-second delay after every opening. Repeated ingress can also restart the
continuous-quiet observation.

## Sensor wait and diagnostic limitations

The approximately 60-second sensor-wait-to-termination display interval is
consistent with arm expiry; the screenshot does not expose the terminal reason.
If the owner remained in position throughout that interval, the absence of a
qualifying sensor trigger deserves independent investigation.

Current Target counters retain accepted sensor detections, not per-session raw
sample counts, invalid/timeout counts, minimum/maximum readings or rejection
causes. Latest distance telemetry is overwritten while network publication is
deferred during critical access, and an IDLE iteration resets its local distance
to the sentinel. It cannot reconstruct every sample of an expired ARMED window.
The earlier diagnostics plan's desired sample/threshold evidence is therefore
not fully implemented. MQTT receipt and UI polling can also hide intermediate
sensor/relay stages; missing activity rows alone do not prove missing actuation.

## Recommended implementation order (not implemented by this analysis)

1. Retire the completed verified physical lease and grant a bounded budget for
   the next pre-proof attempt. Preserve the separate aggregate bound against
   repeated unauthenticated reconnects. Add both reproduced transition cases.
2. Introduce a native, bounded continuous-presence coordinator with fresh BLE
   evidence and local Target lifecycle feedback. After expiry or cooldown, it
   should obtain a fresh challenge without depending on another FIRST_MATCH,
   a foreground screen, or Backend polling. A new proof is distinct from replaying
   an uncertain earlier proof. Initially target a measured one-to-three-second
   terminal-to-next-start interval; this is a proposed acceptance target.
3. Keep authentication readiness separate from relay retrigger eligibility.
   After one passage, require a short sensor-clear/new-approach cycle for another
   automatic pulse, without requiring the phone to leave BLE range. Blindly
   rearming while the sensor remains occupied would otherwise pulse the relay
   after each cooldown. ARMED expiry without a pulse needs its own renewal rule.
4. Capture bounded per-session sensor and rearm diagnostics: sample/valid/timeout
   counts, distance bounds, expiry reason, lease rejection, fresh-presence age,
   last terminal and next dispatch times. Verify continuous presence, expiry,
   successful repeated approach, leave-before-renewal and multiple resident phones.

Continuous renewal must give network/OTA service bounded opportunities: current
critical-access scheduling defers them throughout ARMED/hold/cooldown. Extending
ARMED indefinitely would conflict with that architecture. Keep each physical
session bounded and evaluate a dedicated presence lease separately.

The initial analysis changed documentation only and performed no door action.

## Implemented correction and rollout status

The owner subsequently authorized implementation and deployment. The candidate:

- Retires the verified physical lease on its transition to IDLE, before new
  GATT ingress. Unverified disconnects keep their original bounded budget.
- Advertises six advisory bytes in 128-bit service data (version, ready flag,
  boot-seeded epoch), with a 29-byte scan-response payload. One second of IDLE
  precedes a new ready epoch so network/OTA servicing can run.
- Keeps the original FIRST_MATCH/MATCH_LOST registration and adds LOW_POWER
  ALL_MATCHES delivery under the same native owner. The app coalesces one ready
  epoch, throttles dispatch/journaling, and checks radio evidence no older than
  five seconds immediately before a continuous-presence proof. It never resolves
  PROOF_UNCERTAIN from an unsigned advertisement. Older Targets without the hint
  retain the original FIRST_MATCH flow; older apps retain v2 proof compatibility.
  A known terminal failure may create a fresh attempt after 60 seconds even if
  the ready epoch is unchanged; successful epochs remain coalesced. This avoids
  turning temporary failures into an indefinite wait for a new radio match.
- Separates the next authentication from another relay pulse. After any pulse,
  three consecutive valid readings beyond threshold plus 10 cm clear the
  automatic-passage latch. Invalid/no-echo samples do not clear it. Sampling for
  clearance also runs in IDLE and relay-OFF COOLDOWN so an exit during cooldown
  is not missed before the next person's approach; a fresh ARMED session uses fresh median
  history. Manual authenticated opening keeps its explicit semantics.
- Retains the last ARMED window's sample, valid, timeout and invalid counts and
  distance bounds in deferred telemetry. The admin diagnostic table displays
  them as latest reference values, not historical per-attempt or physical proof.
- Removes the leftover hardcoded 45-file runtime hash list in the personal
  Target compiler. The compiler now verifies checkout/index/file contents
  against the tested exact main commit, retaining file modes, no-symlink and
  untracked-input checks. Privileged workflow and signing inputs still require
  the separate 23-path trusted-policy authorization.

Source validation: the dedicated host transition/interlock test passes; Android
native unit tests pass. Live Target installation and phone update evidence are
recorded separately after publication. No fixed Android discovery latency is
claimed; one-to-three seconds remains the intended field measurement target.

## Production evidence on September 6

PR #381 merged as `6a45aecbdcadf1a50b020b2a9b67c0b3ae45d3a5`, after the
independent policy authorization in PR #380. All final-main host tests pass
(374 tests, one expected skip). Backend run `34012322823` deployed that exact
source with strict readiness checks passing. Target run `34012322944` published
`2.1.469+main.g6a45aec`; one OTA request advanced boot 739 to 740, with the new
image observed through uptime 151 seconds without rollback, relay ON or MQTT/
BLE failure. See [hardware evidence](hardware_test.md#2026-09-06-continuous-presence-rollout).

An older Backend release had remained approval-waiting since September 5 and
held the shared NAS deployment slot. Its source was an ancestor of this release
and its deployment had not executed. It was cancelled, then the current exact
release was approved under the owner's deployment authorization. No deployment
protection was disabled. Future rollout preflight should inspect both waiting
and pending runs, not only running jobs; never approve a superseded release to
clear the queue.

Before any new Target publication/install, the previous image reported another
unplanned BROWNOUT reset (boot 738→739). Supply/wiring diagnosis is still a
separate field gate. The new software does not establish electrical stability.
Android run `34012322829` subsequently published `1.0.0-g6a45aec` / 43501.
Publisher signature checks and independent primary/fallback source/metadata/APK
hash verification passed. Final Target readback at uptime 453 seconds retained
boot 740, the new version, MQTT/BLE and relay-OFF state. Owner mobile installation
and physical testing remain separate evidence; no fixed discovery latency or
electrical stability is claimed.

## Owner-reported authentication failure after rollout

The next owner screenshot shows native attempts at 15:28:22, 15:28:23 and
15:28:26, ending in `GATT_DISCONNECTED` at 15:28:29 on September 6. A separate
remote-open broker-delivery row is displayed at 15:30:02. This is a transport
failure display, not a displayed signature/ACL denial; it does not identify the
connection phase or Android GATT status number.

Read-only observation around 15:30–15:31 found the exact installed `2.1.469`
image, boot 743 / `bcd600b1b20b12fde3dfbc7ae9ae6914`, IDLE, relay commanded OFF,
MQTT failures zero, advertising expected/active, and active ACL 1468 with v2/v2.
Accepted GATT connections, disconnects, challenges, proofs, results and ARMED
entries were all zero; the last GATT checkpoint was BOOTING. These counters
cover accepted adapter connections, not every controller-level connection or
rejected ingress, and advertising-active does not establish phone RF reception.

Boot count increased from the rollout's 740 to 743. The latest retained reset
reason is BROWNOUT with no planned restart and previous action
`mqtt_connect_worker_adopted`. Uptime places that latest boot around 15:04,
before the displayed 15:28 failure, so a reset during this specific attempt is
not established. The other intervening reset reasons are not recovered here.
Backend strict readiness still reports the deployed source and all checks true.

The installed phone build and redacted Support Report are requested to determine
connect/discovery/proof stage, native transport status and dispatch history.
No root cause is assigned from the screenshot alone. No reboot, BLE setting,
credential reset, door command, firmware change or repeat OTA was issued during
this diagnosis.

### Support report correlation, 15:35 KST

The owner-supplied `sgk-mobile-support-v2` report confirms app
`1.0.0-g6a45aec` / 43501, Android SDK 36, approved enrollment, one door and
synchronized ACL 1468 at export. This establishes the installed app at export,
not the app/Target versions of every historical session retained in the report.

- At 15:28:22.363, a FIRST_MATCH wake callback received a beacon (RSSI -94).
  The session was created at 15:28:22.410, 47 ms later. This is session creation,
  not proof that the first worker had already dispatched.
- The final, third attempt dispatched at 15:28:26.939 and failed at
  15:28:29.272 with `DISCONNECTED`, Android status 133. Reported attempt latency
  is 2329 ms; session creation to terminal update is 6862 ms. The 4529 ms
  presence-to-dispatch field includes earlier attempts/backoff; it must not be
  reported as a 4.5-second initial wake/WorkManager delay.
- MTU remains the default 23 / NOT_REQUESTED; connection setup, challenge,
  signing, proof and result timings are null. This is a pre-proof connection
  setup failure, not a Target signature/ACL rejection or a sensor-trigger delay.
  High-priority-request false supports an early connection failure but is not
  independently proof that STATE_CONNECTED never happened: the request can
  return false or throw a handled SecurityException.
- A subsequent read-only sample retains boot 743 at uptime 2093 seconds,
  advertising active, no accepted GATT/challenge/proof counters and IDLE/relay
  OFF. ACL has advanced to 1469 since export; this is not evidence that the
  failed attempt was rejected for ACL mismatch. No reset coincident with the
  attempt is established. Phone-side beacon reception does not by itself bind
  an unauthenticated advertised identity to this exact physical Target.

[AOSP status definitions](https://android.googlesource.com/platform/packages/modules/Bluetooth/+/9afa02435692ca52952fe7158fcc162e05cff0fc/system/stack/include/gatt_api.h)
identify 133 / 0x85 as generic GATT_ERROR and 147 / 0x93 as connection timeout.
Neither identifies the root cause of this owner's current link failure.
The status-147 session is from 13:50:05 and the preceding successful session
from 13:49:28, before this rollout; they cannot validate the newly installed
continuous-presence path. Historical successful sessions show substantial
connection-setup cost while signing is only a few milliseconds.

Two source-confirmed gaps must be separated from the unconfirmed cause of 133:

1. **Early v2 result misclassification.** `ProtocolCore::beginFastSession`
   can send FAST_RESULT before FAST_CHALLENGE for BUSY, RATE_LIMITED or
   INTERNAL_FAIL_CLOSED. Android `readChallenge` waits only for FAST_CHALLENGE;
   `GattCallbackMailbox.awaitMessage` throws UNEXPECTED_MESSAGE_TYPE and places
   the received message type into the transport-status field. Thus the reported
   historical `PROTOCOL_INCOMPATIBLE / 34` means SGK FAST_RESULT (0x22), not
   Android connection status 34. Its actual result reason/retry interval is lost.
   BUSY is a supported source path, not a recovered reason for those particular
   historical frames. Correct early-result parsing must validate framing/version
   and negative reason without accepting pre-proof success as authorization.
2. **Continuous-presence observability gap.** All exported wake events are
   FIRST_MATCH/MATCH_LOST, with no ALL_MATCHES. However the native entrypoint
   returns before journaling an ALL_MATCHES callback lacking a ready hint (also
   for missing address or stale timing). Absence from the report therefore does
   not prove an unregistered/dead scanner. Add bounded counters for received,
   hint-valid/missing, stale and dispatch-suppressed callbacks; expose Target
   GATT service enable/init state and rejected connection reasons separately
   from advertising-active and accepted-session counters.

The immediate diagnostic boundary is Android-to-Target BLE setup. Distinguishing
radio/controller failure, Target service availability or pre-accept rejection
requires those missing connection-level observations. Do not infer user standing
position, reset credentials, or declare continuous reauthentication operational
from registration flags alone. This turn changes documentation only; runtime
fixes, publication and physical recovery actions have not been performed.

### Follow-up implementation: early rejection and bounded recovery

The subsequent owner request authorizes defect/UX fixes plus report-button
layout and Clear support. Android now recognizes pre-challenge FAST_RESULT
only for v2 negative reasons BUSY, RATE_LIMITED and INTERNAL_FAIL_CLOSED. It
validates the full result shape/version/reason/ACL range, preserves the Target
reason and retry interval and never signs or writes proof on that path. An
early success, post-proof-only reason, wrong version or malformed packet is
still rejected. Normal post-proof results retain exact challenge-session binding.

After an ordinary failed session with a transient link/BUSY reason, a fresh
ready hint permits one recovery session after five seconds (or the longer
Target-requested delay). If the recovery session also fails, the existing
60-second quiet/backoff applies, leaving room for Target's 30-second unverified
lease recovery. A backward-compatible `failure_recovery` ledger flag separates
that recovery from an ordinary fresh-radio session and survives process restart.
PROOF_UNCERTAIN, active work, same-epoch success coalescing, credential denials
and the fresh-radio-before-proof requirement are unchanged. There is no timer
that opens the door or dispatches without a new eligible radio observation.

Skipped continuous callbacks now leave a bounded, privacy-safe source code for
missing address, stale/invalid timing or missing ready hint, at most once per
reason per ten seconds. Raw payloads/addresses are not logged. This closes the
silent mobile early-return gap, but does not add Target controller rejection or
GATT initialization telemetry. Android error 133's field root cause remains
unconfirmed, and the latter Target diagnostics remain a follow-up gap.

Report UX, local history reset and validation are described in
[field diagnostics](field_diagnostics_capture_plan.md#9-report-ux-and-history-reset-2026-09-06).
These changes are local implementation/test evidence, not a new published APK,
Target OTA or a successful physical re-entry trial.

### Mobile-only publication completed

PR #383 merged the follow-up as main `80569b1961edad512827a20829d73539c7de89dd`.
Android run `34018358565` completed successfully at 16:25:53 KST on September 6,
publishing **1.0.0-g80569b1 / 43701**. The personal publisher verified signing
identity and the signed manifest; independent strict-HTTPS readback found the
same exact-source manifest on primary/fallback and both 55,594,137-byte APKs
matching SHA-256 `b053454696acd0e8a7739aa83acdd7822ae5087818f6b5a2bf0b954ac1aea8e1`.

The owner can install through app Settings/update, reset report history and
perform the next access trial. Publication is complete; owner installation and
physical authentication/re-entry remain pending. Target/Backend were not
republished, no Target reboot/OTA/door command was sent, and error 133's physical
root cause remains unconfirmed.

### September 7, 13:08 approach: read-only incident observation

The owner's screenshot shows manual remote-command delivery at **13:08:09 KST**,
after the last visible automatic authentication at 12:21:38, sensor-wait messages
at 12:21:40–41 and flow completion at 12:22:00. The owner confirms manual opening
worked. The screenshot alone does not establish whether the phone received a
fresh advertisement or failed before recording an authentication attempt.

Read-only production observation at **13:23:35–46 KST** found:

- Backend `/ready` reports exact deployed source `0c965d99632449d2d5a9b7e4c76f4c79d49b7644`,
  all readiness checks true and fresh verified Target status. This is current
  health evidence, not historical proof for 13:08.
- Twelve seconds of MQTT observation found Target `2.1.469+main.g6a45aec`, boot
  count 760, boot ID `ba9a88fa6d08cbde44ba1d8e8ce51426`, uptime 6213–6224 seconds,
  IDLE, relay commanded off, advertising expected/active and zero active BLE
  connections. Advertising restart attempts/failures were 3/0.
- Accepted connections/disconnects were 3/3; challenges/proofs verified were
  2/2, rejected proofs 0; ARMED entries/sensor detections were 2/2. The last
  diagnostic stage remained COMPLETED at uptime 2507499 ms, approximately
  **12:21:50 KST** using observation time minus uptime. That is consistent with
  the earlier access window, but screenshot receipt time is not Target event
  time and exact session correlation has not been obtained.
- Reset reason was BROWNOUT, with the current boot estimated around **11:40 KST**,
  before the successful automatic session. It is a separate power-stability
  observation, not evidence of a crash at 13:08.
- Sensor totals were 60 samples, 5 valid, 55 timeouts and 0 invalid; passage
  rearm was not blocked. These aggregate measurements include clearance polling
  and have no 13:08 attribution. They warrant follow-up but do not establish
  that this approach failed at the ultrasonic stage.

The primary sensor trigger is read only while ARMED; IDLE clearance polling does
not authorize opening. Prior completed authentication therefore cannot open on
a later approach without a fresh authorized session. Current accepted-connection
and stage evidence points first to the path **before new authentication/ARMED**,
not a proven sensor failure. Rejected controller connections and failures before
Target acceptance are not counted, so a stopped phone scanner, missing ready
hint, suppressed dispatch and early GATT failure cannot yet be distinguished.
The relevant Target source files are unchanged between `6a45aec` and current HEAD.

Administrator diagnostic readback returned 401 (administrator session required),
and the existing NAS SSH endpoint refused connection. No authentication bypass,
credential change, device reboot, OTA, door command or synthetic report upload
was attempted. Preserve the phone's report history and obtain a fresh support
report, including installed app version, wake events and sessions around 13:08,
before choosing a runtime fix. This incident update is documentation only.

#### Owner report received at 13:34:05 KST

Bundle `f862b8acc3eca9e8fb86885ad32c7705` identifies installed Android
`1.0.0-g80569b1` / **43701**, not the published diagnostic-upload follow-up
43901. It contains the exact Target session
`fab94c3a-74ef-45d2-8392-e7cffdbb337a`: creation 12:21:38.219 and successful
authentication 12:21:40.515 KST (2296 ms presence-to-armed). This now correlates
the prior live Target's last-session identifier with the phone's last success.

The newest packet callback is 12:21:55.773; the newest lifecycle callback is
MATCH_LOST (`BLE_SCAN_EXIT`, type 4, error 0) at 12:22:05.772. The independent
registration last-callback timestamp is 12:22:05.767. No newer authentication or
recorded receiver callback appears through the 13:34 export. The report is the
recent view (10 sessions/20 wake records), sorted newest first; ordinary truncation
would discard older, not later, observations. Missing journal entries alone are
not full radio evidence, but the separately maintained callback timestamp also
remains old. Receiver registration evidence is updated before ready-hint/dispatch
filtering, with continuous callbacks throttled to at most one write per two seconds.

Registration attempted/reconciled timestamps are **13:34:01.560/.586**, after the
incident, and only establish accepted registration at that later time. They do
not prove continuous scanner operation at 13:08. Source inspection confirms
`healthy` only excludes FAILED/PROOF_UNCERTAIN as the last durable session state;
`handsFreeReady` checks configuration/registration/current blocking reasons, not
recent successful radio reception. Therefore both true flags and the exported
2296 ms latency must not be read as evidence of a successful 13:08 approach.
The inspected native receiver/registrar/health source is unchanged from 80569b1.

The incident is now localized first to **fresh BLE observation delivery before
authentication dispatch**, not a recorded proof denial or sensor-wait timeout.
An Android scan/delivery lifecycle problem versus absent/mismatched Target radio
at the actual approach remains unresolved; later advertising-active telemetry
does not establish over-air reception at 13:08. MATCH_LOST is an observation,
not proof of a scan error, user movement or scanner termination. No claim is
made that installing 43901 fixes this path; that release fixes upload/reporting.
Next diagnostic improvements should separate configuration health, last packet
age and authenticated-session outcome, and preserve bounded registration/stop/
error/recovery lifecycle history. Absence of advertisements alone cannot prove
a dead scanner when a phone may legitimately be out of range.

The follow-up owner-authorized implementation now adds separate scan packet
evidence, bounded lifecycle capture and truthful home/settings projections;
see [field diagnostics](field_diagnostics_capture_plan.md#september-7-scan-observation-implementation-local-not-deployed).
It does not claim a repaired 13:08 radio path or publish a release.
