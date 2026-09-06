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
