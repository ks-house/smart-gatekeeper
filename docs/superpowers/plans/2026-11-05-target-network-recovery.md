# Target network self-recovery implementation plan

**Goal:** Prevent unbounded no-progress DNS/MQTT retry loops while preserving access/relay/OTA safety; show stale Target availability honestly.
**Approved scope:** Owner requests recurrence prevention and Target fixes after the11/05 incident. Absolute fault-free operation is not a claim; validate bounded detection/recovery under available infrastructure.
**Spec:** wiki/acl_wait_incident_2026_11_05.md and wiki/embedded_target_connectivity_policy.md; OTA contract remains higher priority.

## Design and constraints
- No credential erasure, hardcoded/public resolver fallback, hostname/CA weakening or automatic chip reboot.
- Count one terminal failure per real DNS generation. Existing5s DNS deadline and stale callback rejection remain.
- Three genuine same-link DNS failures spanning60s request network recovery. Six transport failures spanning180s may request recovery; explicit credential/authorization/resource failures do not trigger radio resets.
- Stage1 asynchronous STA disconnect then reassociate only after disconnect observation. Stage2 may recreate STA interface when another qualifying episode persists. Keep credentials and existing protected AP behavior.
- Minimum120s between actions, maximum2 actions in any rolling15minutes. Preserve this budget across brief successes; reset the failure episode only after60s stable MQTT adoption.
- Use an atomic idle-radio admission reservation. Never mutate radio/socket during GATT ingress/session/output, ARM/relay/cooldown, connect/status/ingress worker ownership, pending signed action, OTA or active local recovery/AP. No waiting under GATT locks.
- Invalidate DNS and stale worker generations; relinquish every owner before socket/radio transition. No MqttManager re-init that would clear evidence.
- Watchdog enrollment/reset failure prevents subsequent connect-worker I/O and returns ownership; main watchdog-protected owner performs cleanup when monitoring is unavailable.
- Add optional bounded unsigned recovery diagnostics, preserving signed-status RAM/wire budgets and N/N-1 parsing.
- Personal status adds optional scoped fresh/stale/unknown availability; permission/ACK rules remain. UI distinguishes Target communication from ACL wait, preserves old Backend behavior, updater/native independence.

## Task1: worker hard-stall prevention
- [x] Compile actual connect worker in fake TLS/MQTT/task fixture; observe RED for enrollment/reset failure and cancellation between subscriptions.
- [x] Stop unmonitored work, classify resource failure, preserve SNI/CA/principal/LWT; GREEN executable tests.

## Task2: bounded network progress recovery
- [x] Add fake-clock RED for DNS/transport thresholds, one-count-per-generation, late callbacks, rate budget, stable reset and wrap.
- [x] Implement allocation-free policy and guarded async STA stages with current driver profile.
- [x] Execute real adapter boundaries with stubs: busy/OTA/AP defer, owner handoff, event loss, false starts, long outage and late completion.
- [x] Add bounded optional advisory fields and parser/budget regressions.

## Task3: availability projection/UI
- [x] RED status/provider/widget tests for stale→fresh/ACL pending→exact APPLIED, unknown/reconnect/cache age and identity/door scope.
- [x] Optional fields and explanatory last verified server time; no freshness authority from persisted/replayed timestamps.
- [x] Backend and Flutter full suite/analyzer/format GREEN.

## Task4: integrate and release
- [x] Whole root/backend/native/Flutter checks, default and effective enabled Target compile, OTA contract and protected-input inventory.
- [x] Independent review and regression fixes; update wiki/index/log/hardware evidence.
- [ ] Reviewed source publication and signed artifacts; install/reboot/health evidence remains separate and no unattended actuator testing.

## Progress
- Existing isolated worktree retained; own incident documentation is preserved.
- Worker RED:4 test methods/21 scenarios,8 expected failures (no compile errors).
- Backend optional availability RED demonstrated by the UI agent; dependencies isolated in this worktree .venv.

- Final local validation: root512/14 explicit environment skips; Backend450/13 explicit opt-in skips; complete-dependency diagnostics33 PASS; Flutter136 PASS; Android167/zero failures-errors-skips in existing XML (Gradle task up-to-date); Dart format/analyzer, default+personal-enabled C6 and OTA contract PASS. Public example-only firmware fixture, no device upload.
- Independent review found old-link failure qualification surviving natural reassociation. Policy+controller+actual-service RED-to-GREEN clears evidence/selection across link change while preserving stage/global budget; no remaining confirmed blocker. Physical RF/door and install gates remain separate.
