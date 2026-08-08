# Issue #54 field checklists

## Universal preflight

1. Record the exact candidate Git SHA and firmware/mobile artifact SHA-256
   values before the first trial. Do not reuse a record across candidates.
2. Confirm the test door is isolated, the relay is safe to exercise, a manual
   stop method is available, and the prior bootable Target slot and prior signed
   APK are available.
3. Before execution, record an offset-bearing start timestamp and a named
   executor identity. Allocate immutable content-addressed capture locations
   and unique capture IDs; each required category must retain its capture time,
   named capturing identity, SHA-256 digest, and matching `urn:sha256:` locator.
   A missing or generic capture is a failed/incomplete trial, not a verbal
   substitute.
4. After execution, record the end timestamp and obtain review from a named
   identity independent of the executor. Bind the record to the canonical pass
   condition and exact gate role, and timestamp the decision after the end of
   execution. Empty approvals, self-review, and substitute roles are invalid.
5. Keep L0/L1 results separate from the L2 device record, L3 operator record,
   and L4 production record. Never change `not_run` to `passed` for a plan or
   a synthetic fixture.

## Approval roles

| Gate group | Required approval role |
|---|---|
| Samsung/OEM, ESP32-C6, GPIO3, AJ-SR04T, OTA-G1..G3 | `independent_reviewer` |
| RELAY-G0..G2 | `risk_owner` |
| OTA-G4 and operator drills | `operator_risk_owner` |
| Canary stop/rollback | `release_risk_owner` |

The plan's `pass_condition_id` and `required_approval_role` are authoritative.
A `passed` record requires `approved`; a failed execution requires `rejected`;
an aborted execution requires `incomplete`. All three executed states retain
the same timestamps, actor separation, and complete raw-capture obligations.

## Samsung/OEM 100-run wake campaign

Run 20 eligible trials for each fixed scenario: screen off, Activity
swipe-away, ordinary process kill, reboot registration recovery, and OEM
battery-policy recovery. Record device model, Android/OEM build, permissions,
Bluetooth state, app build, Target identity/advertisement settings, start/end
timestamps, one redacted `BLE_WAKE_POC` capture per trial, and latency samples.
Force-stop, Bluetooth-off, permission-revoked, and unsupported OEM settings are
explicitly unsupported cases; do not silently count them as wake successes.

## ESP32-C6, GPIO3 relay, and AJ-SR04T

For the 100-cycle coexistence campaign capture serial/reset reasons and radio
observations while Wi-Fi, BLE/GATT, MQTT, and OTA-safe-state transitions are
exercised. For GPIO3, confirm the actual relay jumper/polarity, capture the
active-low ON and High-Z OFF waveform plus 3.3 V/5 V rail behavior, and stop
immediately on an unsafe rail observation, missed cutoff, unexpected reset, or
advertisement loss. For AJ-SR04T capture the 19/20 cm boundary and ghost-filter
ledger, wiring/level protection, and no-measurement state when ECHO protection
cannot be verified.

## RELAY-G0 through RELAY-G2

`RELAY-G0` requires the reviewed threat model, byte-exact two-proxy transcript,
matching expected/observed wormhole result, and risk-owner approval. `RELAY-G1`
requires the same selected path in the active control and evidence. `RELAY-G2`
requires that selected path, a zero-failure 100-run physical record, and an OTA
rollback regression; a good RSSI, a unit test, or a bare capability flag does
not close any of these gates.

## OTA-G1 through OTA-G4 and power-cut recovery

Use the existing `ota/fault-injection-plan.json`, `ota/recovery-matrix.json`,
and `wiki/ota_operations_runbook.md` as the detailed contract. Capture the
fault boundary, inactive/active slot, bootloader decision, reset reason, health
window, prior-artifact preservation, periodic HTTPS path, authenticated local
recovery path, mobile fallback path, and N/N-1 result. Before a valid mark,
power-cut/crash/reset-loop recovery must demonstrate the previous bootable slot;
after valid mark, use the documented signed rollback path and never erase a
partition as an improvised repair.

## Operator and canary drills

Have a named operator execute install, recovery, incident-stop, and rollback
from the versioned runbook without undocumented privileged workarounds. The
preproduction canary drill must capture install, reboot, health, the stop
decision, halted expansion, prior-artifact rollback, and post-rollback health.
This preparation task does not authorize contacting production, starting a
canary, or approving deployment.
