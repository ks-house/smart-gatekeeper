# Target Local ACL Verification and Access Session FSM (Issue #20)

> Last updated: 2026-08-02
> Status: **software core implemented and host/build verified; production default-OFF and physical/operator gates pending**
> Tracking: GitHub [#20](https://github.com/ks-house/smart-gatekeeper/issues/20), Epic [#13](https://github.com/ks-house/smart-gatekeeper/issues/13)

---

## 1. Scope & Ownership

Target (ESP32-C6) is the sole authoritative owner of local ACL verification, access sessions, relay activation, hold timing, and cooldown.

- **`TargetAclManager`**: Parses, validates, stores (dual-slot NVS), and enforces signed ACL snapshots (72B header + 106B entries + 64B SEC1 P-256 raw64 signature) with anti-rollback high-watermark versioning.
- **`TargetProofVerifier`**: Verifies 103-byte GATT proof signatures against the active signed ACL entries with strict low-S (`s <= half_n`) constraints and credential permission checks.
- **`TargetAccessFsm`**: Owns the access state machine (`IDLE` -> `ARMED` -> `RELAY_HOLD` -> `COOLDOWN`).
- **`OfflineEventQueue`**: Bounded FIFO queue (capacity 32) for caching access and system events during network offline periods.

---

## 2. Access FSM State Machine

```
   [ IDLE ] ──(handleAuthSuccess / handleManualRemoteOpen)──> [ RELAY_HOLD ] ──(hold_ms)──> [ COOLDOWN ] ──(cooldown_ms)──> [ IDLE ]
      │                                                           ▲
      └──(handlePreArm)──> [ ARMED ] ──(sensor trigger)───────────┘
                             │
                             └──(timeout)─────────────────────────────────────────────────────────────────────────────> [ IDLE ]
```

### State Definitions

| State | Description | Relay State | OTA Safe State |
|-------|-------------|-------------|----------------|
| `IDLE` | Idle state, ready for access or pre-arm | `OFF` | `SAFE` |
| `ARMED` | Pre-armed via legacy MQTT, sensor active | `OFF` | `ACCESS_SESSION_ACTIVE` |
| `RELAY_HOLD` | Access granted, relay active (`RELAY_HOLD_MS`) | `ON` | `RELAY_ACTIVE` |
| `COOLDOWN` | Relay deactivated, cooling down before next access | `OFF` | `ACCESS_SESSION_ACTIVE` |

### Interlock Rules

- **Relay Interlock**: Relay activation (`RELAY_HOLD`) is only permitted when the FSM is in `IDLE` (or `ARMED` with relay `OFF`). Double-activation while in `RELAY_HOLD` or `COOLDOWN` is rejected fail-closed.
- **Manual Remote Path**: Authenticated explicit-button `manual_remote` (`triggerManualDoorOpen()`) via MQTT is independent of hands-free GATT local auth proof. It requires Target `IDLE` state and emits `relay_on_manual` or `manual_open_rejected_not_idle`.
- **Cleanup**: `cleanupToIdle()` immediately turns relay `OFF` and resets state to `IDLE`.

---

## 3. Signed ACL & Proof Verification

### Signed ACL Snapshot Contract

- **Header (72B)**: `SGKACL01`, schema version 1, 16B `door_id`, uint64 `acl_version`, timestamps, `lease_duration_s` (900s default, max 3600s), protocol bounds, `entry_count`.
- **Entries (106B each)**: `credential_id` (16B, sorted ascending), 65B SEC1 uncompressed P-256 public key (`0x04...`), status (`1=ACTIVE`), permissions bitmask (`0x01=OPEN`), protocol bounds.
- **Signature (64B)**: P-256 raw64 (`r||s`), checked for `1 <= r < n` and low-S `1 <= s <= half_n`.
- **Anti-Rollback**: High-watermark version floor persisted in NVS generation records. Any snapshot with `acl_version < high_watermark` is rejected.
- **Dual-Slot NVS Storage**: Alternating NVS slots (`slot_0`, `slot_1`) with generation records (`gen_0`, `gen_1`) and CRC32 protection for atomic dual-slot recovery across power cuts.

---

## 4. Verification Evidence & Test Coverage

Host unit tests (`python -m unittest tests/test_hardwareless_rc.py` running native C++ `tests/gatt_protocol_test.cpp`) verify:
- Canonical test vectors and framing (challenge SHA-256 `7cebae...`).
- Signed ACL parsing, signature verification, dual-slot storage, anti-rollback floor, and lease expiry.
- Proof verification with strict low-S, invalid action rejection, and unknown credential denial.
- Target FSM transitions, relay interlock, and dedicated `manual_remote` regression.
- Bounded offline event queue push, pop, and overflow eviction (capacity 32).
- Default-OFF and feature-ON PlatformIO builds for `esp32c6`.

---

## 5. Physical Gate Notice

This documentation and C++ core implementation cover software-only host and build evidence. Physical hardware evidence (ESP32-C6 radio capture, GPIO3 relay timing, sensor integration, power-loss/bootloader recovery, `RELAY-G0..G2`, `OTA-G1..G4`) remains pending.
