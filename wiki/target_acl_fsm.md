# Target Local ACL Verification and Access Session FSM (Issue #20)

> Last updated: 2026-08-26
> Status: **software core implemented and host/build verified; personal production profile enabled, commercial/default profiles OFF, and physical/operator gates pending**
> Tracking: GitHub [#20](https://github.com/ks-house/smart-gatekeeper/issues/20), Epic [#13](https://github.com/ks-house/smart-gatekeeper/issues/13)

---

## 1. Scope & Ownership

Target (ESP32-C6) is the sole authoritative owner of local ACL verification, access sessions, relay activation, hold timing, and cooldown.

- **`TargetAclManager`**: Parses, validates, stores (dual-slot NVS), and enforces signed ACL snapshots (72B header + 106B entries + 64B SEC1 P-256 raw64 signature) with anti-rollback high-watermark versioning.
- **`TargetProofVerifier`**: Verifies 103-byte GATT proof signatures against the active signed ACL entries with strict low-S (`s <= half_n`) constraints and credential permission checks.
- **`TargetAccessFsm`**: Owns the access state machine (`IDLE` -> `ARMED` -> `RELAY_HOLD` -> `COOLDOWN`).
- **`OfflineEventQueue`**: Bounded FIFO queue (capacity 8) for caching access and system events during network offline periods.

---

## 2. Access FSM State Machine

```
   [ IDLE ] ──(handleAuthPending)──> [ AUTH_PENDING ] ──(action 1)──> [ ARMED ] ──(sensor trigger)──> [ RELAY_HOLD ] ──(hold_ms)──> [ COOLDOWN ] ──(cooldown_ms)──> [ IDLE ]
                                             └────────(action 2)───────────────────────────────> [ RELAY_HOLD ]
      │                                    │                                                                      ▲
      │                                    └──(disconnect/abort)───────────> [ IDLE ]                             │
      │                                                                                                           │
      └──(handlePreArm)───────────────────────────────────────────────────────────────────────────────────────────┘
```

### State Definitions

| State | Description | Relay State | OTA Safe State |
|-------|-------------|-------------|----------------|
| `IDLE` | Idle state, ready for access or pre-arm | `OFF` | `SAFE` |
| `AUTH_PENDING` | Local GATT auth proof verification in progress | `OFF` | `ACCESS_SESSION_ACTIVE` |
| `ARMED` | Verified or pre-armed, awaiting passage sensor trigger | `OFF` | `ACCESS_SESSION_ACTIVE` |
| `RELAY_HOLD` | Access granted, relay active (`RELAY_HOLD_MS`) | `ON` | `RELAY_ACTIVE` |
| `COOLDOWN` | Relay deactivated, cooling down before next access | `OFF` | `ACCESS_SESSION_ACTIVE` |

### Interlock Rules

- **Single FSM Ownership**: `g_access_fsm` is the single authoritative owner for state transitions, relay interlock, and OTA safe state classification.
- **Hands-free Local GATT Flow**: action 1 follows `IDLE -> AUTH_PENDING -> ARMED (relay OFF) -> passage sensor trigger -> RELAY_HOLD (relay ON) -> COOLDOWN -> IDLE`.
- **Manual Local GATT Flow**: action 2 follows `IDLE -> AUTH_PENDING -> RELAY_HOLD (relay ON immediately) -> COOLDOWN -> IDLE`; it does not wait for the ultrasonic sensor.
- **Result/FSM Binding**: `AuthControlGate` begins `AUTH_PENDING` before challenge delivery and commits the signed action after proof verification. `RESULT OK` is queued only after the corresponding FSM transition returns true. Missing callbacks or rejected transitions fail closed and abort pending state.
- **Auth Abort / Disconnect**: `handleAuthAbort` transitions `AUTH_PENDING` to `IDLE` upon disconnect or proof rejection, but does not abort an already verified `ARMED` passage nor an active `RELAY_HOLD`.
- **Relay Interlock**: Relay activation (`RELAY_HOLD`) is permitted from `ARMED` after a sensor trigger, from `AUTH_PENDING` for signed local action 2, or from `IDLE` for signed MQTT manual remote. Double-activation while in `RELAY_HOLD` or `COOLDOWN` is rejected fail-closed.
- **Manual Remote Path**: Authenticated explicit-button `manual_remote` (`triggerManualDoorOpen()`) via MQTT is independent of hands-free GATT local auth proof. It requires Target `IDLE` state and transitions directly to `RELAY_HOLD`.
- **Boot Validation**: `TargetAclManager::begin()` validates stored slot semantics, ECDSA signature, door ID binding, generation CRC, and high-watermark floor on boot before marking active.
- **Relay Failsafe**: Independent esp_timer / hardware failsafe timeout transitions FSM to `COOLDOWN`.

### Canonical Local-GATT Lifecycle Bridge

- `LocalGattLifecycleBridge`는 `ACCESS_PROOF_VERIFIED`를 받은 검증 완료 local-GATT session만
  추적한다. MQTT pre-arm과 authenticated explicit `manual_remote`는 이 bridge를 활성화하지 않는다.
- 성공 chain은 동일 `session_id`/`source_boot_id`에서 strictly increasing sequence와 바로 앞
  event의 causation을 사용해 `ACCESS_PROOF_VERIFIED -> ACCESS_ARMED ->
  ACCESS_SENSOR_DETECTED -> ACCESS_RELAY_ON -> ACCESS_RELAY_OFF ->
  ACCESS_SESSION_COMPLETED`를 생성한다. terminal emit 후 bridge state를 지운다.
- proof 결과 indication 후 정상 BLE disconnect는 검증 완료 `ARMED` chain을 취소하지 않는다.
  arm timeout은 catalog-valid `ACCESS_SESSION_TERMINATED`/`ARM_TIMEOUT`으로 끝난다.
- `handleRelayFailsafeOff()`는 `RELAY_HOLD && relay_on`에서만 한 번 작동한다. timer와 loop의 두
  failsafe 경로가 겹쳐도 relay-off와 terminal event는 중복되지 않는다.

---

## 3. Signed ACL & Proof Verification

### Signed ACL Snapshot Contract

- **Header (72B)**: `SGKACL01`, schema version 1, 16B `door_id`, uint64 `acl_version`, timestamps, `lease_duration_s` (900s default, max 3600s), protocol bounds, `entry_count`.
- **Entries (106B each)**: `credential_id` (16B, sorted ascending), 65B SEC1 uncompressed P-256 public key (`0x04...`), status (`1=ACTIVE`), permissions bitmask (`0x01=OPEN`), protocol bounds.
- **Signature (64B)**: P-256 raw64 (`r||s`), checked for `1 <= r < n` and low-S `1 <= s <= half_n`.
- **Anti-Rollback**: High-watermark version floor persisted in NVS generation records. Any snapshot with `acl_version < high_watermark` is rejected.
- **Dual-Slot Durable NVS Storage**: Alternating NVS slots (`slot_0`, `slot_1`) with generation records (`gen_0`, `gen_1`) and CRC32 protection for atomic dual-slot recovery across power cuts. Issue #149 moves these records out of the original 20 KiB default NVS into the fixed 1.875 MiB durable-state region while retaining read fallback to the old partition for application-only OTA migration. Wi-Fi/config remains in the default NVS, and migration never erases it.
- **Connected #149 validation**: Exact `2.1.273+main.g493591b` reported
  `sgkstate used=0 free=60480 total=60480`, then applied ACL v169--v171 and
  retained signed-command replay writes across two HA-triggered reboots without
  another `NOT_ENOUGH_SPACE`. Three later screen-off action-1 transports still
  stopped before `ARMED`, but did so without an ACL/replay storage error. The
  third completed before the later periodic OTA check, excluding OTA-busy
  collision. Issue #149 is closed; issue #156 owns the separate terminal
  mobile/Target result classification.

---

## 4. Verification Evidence & Test Coverage

Host unit tests (`python -m unittest tests/test_hardwareless_rc.py` running native C++ `tests/gatt_protocol_test.cpp`) verify:
- Canonical test vectors and framing (challenge SHA-256 `7cebae...`).
- Signed ACL parsing, signature verification, dual-slot storage, anti-rollback floor, and lease expiry.
- Proof verification with strict low-S, explicit action 1/2 acceptance, invalid action rejection, and unknown credential denial.
- Target FSM transitions, action 1 relay-OFF arming, action 2 immediate relay, fail-closed Result/control binding, and dedicated `manual_remote` regression.
- Issue #134 pocket-approach regression fixes the exact action-1 order as `AUTH_PENDING -> ARMED` with both software and relay callback OFF, then permits `RELAY_HOLD` only after the ultrasonic trigger; the main loop samples only while `ARMED` at a 100 ms polling interval.
- Bounded offline event queue push, pop, and overflow eviction (capacity 8).
- Default-OFF and feature-ON PlatformIO builds for `esp32c6`.

---

## 5. Physical Gate Notice

This documentation and C++ core implementation cover software-only host and build evidence. Physical hardware evidence (ESP32-C6 radio capture, GPIO3 relay timing, sensor integration, power-loss/bootloader recovery, `RELAY-G0..G2`, `OTA-G1..G4`) remains pending.

The first connected exact-main action-2 trial on 2026-08-26 exposed issue #143:
`ProtocolCore::processProof()` synchronously committed the authenticated action
while `GattServer::update()` still held a FreeRTOS critical-section spinlock.
`TargetAccessFsm::handleLocalManualOpen()` then reached the relay callback and
newlib aborted when `LOGF` attempted to acquire its recursive stdout lock. The
issue #143 candidate replaces that adapter/core spinlock with a recursive
task-context mutex; this preserves serialized Result-to-FSM binding without
executing GPIO, timer, diagnostics or logging inside a critical section. Host
and build evidence does not close the Gate: the exact merged signed image must
complete action 2, terminal Result and one commanded relay ON/OFF sequence on
the connected Target without a reset.
