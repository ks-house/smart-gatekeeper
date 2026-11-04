# Mobile Background Recovery Implementation Plan

> For agentic workers: use test-driven task execution with independent ownership and a final branch review.

**Goal:** Screen-off/task-swipe access remains independent of Flutter UI; fresh radio evidence can recover a restored worker without stale proofs.
**Architecture:** Preserve existing filtered PendingIntent/native GATT, add bounded lifecycle reconciliation and pre-lease RF waiting, separate Home checking from unavailable.
**Tech Stack:** Existing Kotlin/WorkManager2.9.1/coroutines/Flutter; no new dependencies.
**Spec:** wiki/mobile_background_access_analysis_2026_11_04.md section8, approved by owner with proceed instruction.

## Global constraints
- Never dispatch an open/reboot/OTA from diagnosis or verification.
- Preserve credential binding, fresh RF5s, dispatch age45s, Target ACL/proof, sensor interlock and PROOF_UNCERTAIN no-replay.
- Preserve independent mobile/Target OTA, rollback, N/N-1 and signing. No firmware or Backend runtime change.
- Do not copy diagnostic JSON into the repository. Report aggregates only.
- Runtime phase event codes must fit existing strict Backend schema; no new unadmitted fields.

## Review focus
- Cancel while waiting or before/after proof: no retry generated from cancellation; uncertain proof stays durable.
- Stale or another Target's packet never authorizes waiting worker.
- Disable/logout/radio-off/update and active proof prevent lifecycle recovery effects.
- Rapid Activity changes/callbacks and old async API responses never duplicate registration/auth or replace newer UI state.
- Bounded wait/recovery reaches a terminal result without infinite polling or RF loops.

## Task1: Fresh native dispatch (root)
- [x] Add failing coroutine tests for restored empty RF tracker followed by fresh packet, timeout/deadline, disabled, cancellation, unrelated/stale packet.
- [x] Add failing policy tests for exactly one fast pre-proof freshness recovery; uncertain/authorization denial/missing-hint cooldown remain blocked.
- [x] Wait at most10s and within45s dispatch age before cancelling alternative discovery/acquiring BLE lease; keep5s proof check.
- [x] Add existing-schema diagnostic phases for wait/resume/expiry; zero credential bytes on every exit.
- [x] Ensure external coroutine cancellation propagates through GattSessionEngine without retry; test before and after proof.
- [x] Run native suite and source/OTA contracts.

## Task2: Lifecycle registration recovery (native agent)
- [x] Add failing policy/lifecycle tests for background/SCREEN_OFF, cooldown, active proof, disable and queued work.
- [x] Schedule one bounded unique native reconciliation on background lifecycle; durable cooldown60s and no extra scanner.
- [x] Keep exact filtering, exclusive BLE owner, existing periodic watchdog and OTA/disable cancellation.
- [x] Verify native suite; report limitations honestly.

## Task3: Home state (Flutter agent)
- [x] Add failing widget regressions for checking/unavailable, slow activity, stale responses and dispose.
- [x] Reflect status before activity completes; guard generations; preserve native and manual authorization.
- [x] Run Flutter tests/analyzer/format.

## Task4: Integration and review (root)
- [x] Run complete root/native/Flutter suites and OTA gate; build Android debug APK in WSL Docker.
- [x] Independent code review, fix findings with regression tests.
- [x] Update wiki status/index/log and verification evidence; keep physical/OEM qualification separate.
- [ ] Prepare source commit/PR after publication authorization and authentication. Automatic review rejected the credential/publication step because the current authorization covers implementation/testing. No staging/commit/push performed.

## Progress
- Isolated worktree created from main6126342; baseline12 source/native-host checks PASS.
- Docker Desktop was stopped; started for WSL development without settings changes.

- Final independent review found no new critical/important defect. Parent-timeout RED was fixed with own-timeout-only classification; cancellation propagates.
- Ruling: OTA preserves existing independent UI/installer and filtered native wake; no new durable OTA suppression flag is introduced. Foreground alternative discovery still cancels on update.
- Wait/radio/credential behavior has coroutine/engine/policy tests and source review. Actual worker+Keystore/device/OEM integration and physical passage remain field gates.
- Debug APK build PASS (local verification only, not an installation update). Preserve the worktree pending publication approval.

- Owner explicitly authorizes GitHub publication and signed mobile update delivery on2026-11-04. GitHub auth status succeeds; credential is available without printing raw material. Publication proceeds, with installed/physical acceptance tracked separately.
