# Mobile background recovery implementation - 2026-11-04

> LOCAL IMPLEMENTATION/VERIFICATION COMPLETE. Owner explicitly authorized GitHub publication and signed mobile update delivery on 2026-11-04. Publication is in progress; installation and screen-off/task-swipe physical acceptance remain pending.
> Branch: codex/mobile-background-recovery-20261104. Base: 612634206f8228500241789390cdd339f1d35a97. Primary dirty NAS checkout preserved.

## Resulting behavior

- Application-level Activity-stop/SCREEN_OFF lifecycle schedules one immediate native filtered-registration check. It does not claim that Activity stop proves task swipe.
- Durable monotonic60s throttle, cancellation generation and actual WorkManager unique-chain inspection bound recovery to one running plus one pending pass. Existing15-minute watchdog remains.
- Queued registration work rechecks current feature authority. Disabled intent cannot be re-enabled by old work; live RF/active session/proof uncertainty retain their guards.
- A restored hands-free worker with no volatile RF evidence waits at most10s and within its remaining45s dispatch budget, before BLE ownership or foreground-discovery cleanup. It needs a real fresh packet for the same Target.
- After suspension it rechecks native enablement, session execution state and credential binding. After BLE ownership it rechecks5s RF, and it preserves the existing5s check before proof.
- Explicit pre-proof FRESH_PACKET_REQUIRED failure permits exactly one5s fast recovery on new RF. The45s expiry, authorization denials, missing-hint60s cooldown, Target retry-after and PROOF_UNCERTAIN no-replay remain.
- Coroutine cancellation is propagated. Only the engine's own timeout becomes GATT_TIMEOUT; parent cancellation/timeouts do not create retry outcomes. The durable pre-proof boundary remains authoritative after a possibly executed proof.
- Added bounded PRESENCE_WAIT_STARTED/RESUMED/EXPIRED event codes using the existing Backend schema. No new unadmitted JSON fields, RF payloads or addresses are exported.
- Home starts with checking information, displays status without waiting for activity history, and rejects stale asynchronous results after newer refresh/disposal. Native authorization is unchanged.

## Verification

| Check | Result |
|---|---|
| Root repository unittest suite |490 collected,0 failures,16 explicit environment skips |
| Native Android whole suite |167 tests,0 failures/errors/skips; final JUnit XML independently parsed |
| Flutter whole suite |133 PASS |
| Dart formatting/analyzer |60 files,0 changes; no issues |
| OTA independent recovery contract |PASS |
| APK compilation |Debug APK built successfully with Flutter3.44.8/Dart3.12.2 in WSL Docker |
| Independent source review |No new critical/important defect; final timeout/lease/lifecycle deltas reviewed |

The new recovery policy test is under the existing hosted gattworker selector; protected workflows/dependency locks were not changed. Generated desktop plugin output was restored after Flutter build.
Local Java is17.0.19; hosted pinned Java17.0.16+8 remains a separate CI verification step.

Debug APK SHA256: f8083bc5ae75002aec1308313305e0d6781f2d0a38b30c4f4a0de6c4b9d73958

This debug artifact is compile evidence only. It is not the signed update for the installed release app and was not installed or published.

## Evidence and boundaries

Local logs: /tmp/sgk-root-final-20261104.log, /tmp/sgk-flutter-final-20261104.log, /tmp/sgk-flutter-analyze-20261104.log.
Container sgk-mobile-bg-20261104 retains /tmp/sgk-native-all-final-20261104.log, /tmp/sgk-apk-final-20261104.log and the RED/earlier integration logs.
Initial RED reproduced explicit freshness recovery, before/after-proof cancellation and queued disabled-feature registration. An added parent-timeout test also failed before its fix. Fresh-wait tests cover same/other Target, deadline, disable and cancellation.

No real access command, reboot, Target OTA, NAS setting or phone setting was issued. No firmware/Backend runtime/signing/partition change.
Actual worker+Keystore wait-time credential rotation/radio-off/cancellation integration and Android/OEM/physical passage are not established by these local tests. Installation of the signed APK and same-phone screen-off/task-swipe acceptance remain necessary.

## Publication authorization

Automatic approval review rejected the GitHub credential/publication-preparation action: it interpreted the owner's proceed as implementation/testing authorization, not publishing authorization. No credential retrieval, staging, commit, push, PR or deployment followed that rejection.
The owner subsequently explicitly approved GitHub publication and signed mobile update delivery on 2026-11-04. Auth status and credential availability were verified without exposing the token. Publication now proceeds through normal review, CI, merge and signed delivery; installation is separate.

## Related

- [Analysis](mobile_background_access_analysis_2026_11_04.md)
- [Implementation plan](../docs/superpowers/plans/2026-11-04-mobile-background-recovery.md)
- [Scan lifecycle](mobile_app_scan_lifecycle.md)
- [Native GATT worker](android_gatt_worker.md)
- [OTA reliability contract](ota_reliability_contract.md)
