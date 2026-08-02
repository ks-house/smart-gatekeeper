# ESP32-C6 connectable GATT transport (Issue #18)

> Updated: 2026-08-02
> Status: **software transport implemented and host-tested; production remains OFF and physical gates remain pending**
> Tracking: GitHub [#18](https://github.com/ks-house/smart-gatekeeper/issues/18), Epic [#13](https://github.com/ks-house/smart-gatekeeper/issues/13)

## 1. Scope boundary

Issue #18 supplies the bounded BLE transport and authentication-session adapter needed by #20. It does not implement signed ACL storage, credential authorization, the Target-owned access FSM, or relay activation. The production/default `FailClosedProofVerifier` returns `ACL_UNAVAILABLE`; only native host tests inject a clearly test-only deterministic verifier.

Local GATT accepts only protocol action `1` (hands-free/local open intent). Action `2` is rejected because authenticated `manual_remote` remains the independent explicit app button → Backend authorization → MQTT Target receipt path. No file in the GATT core or adapter calls relay code.

## 2. Feature gate

- `ENABLE_HARDWARELESS_RC` defaults to `0`.
- `sgk::effectiveFeatureEnabled()` makes compile OFF dominate any stale NVS `hwless_rc=true` value.
- An OFF build does not create the service. Runtime disable disconnects peers, removes/stops the service, clears queued writes, and resets session state.
- Production enable, legacy retirement, and Epic closure remain prohibited by the G0-HW, RELAY-G0..G2, OTA-G1..G4, and OEM/physical gates.

## 3. Stable BLE contract

The legacy advertising filter bytes remain:

```text
company id: 0x004c
manufacturer prefix: 02 15 a1 b2 c3 d4 e5 f6 78 90 ab cd ef 12 34 56 78 90
AD flags: 0x1a
```

The Android `BleWakeContract` and production C++ `kIBeaconFilterPrefix` use those exact bytes. Hardwareless mode adds the stable service UUID only to the scan response.

| GATT object | UUID | properties/descriptors |
|---|---|---|
| Primary auth service | `9f4d1000-7d9e-4fb1-9c54-6f4d53474b31` | primary |
| Hello/control | `9f4d1001-7d9e-4fb1-9c54-6f4d53474b31` | write, indicate, user description, CCCD |
| Challenge | `9f4d1002-7d9e-4fb1-9c54-6f4d53474b31` | read, indicate, user description, CCCD |
| Proof | `9f4d1003-7d9e-4fb1-9c54-6f4d53474b31` | write, user description |
| Result | `9f4d1004-7d9e-4fb1-9c54-6f4d53474b31` | indicate, user description, CCCD |

The Arduino-ESP32 supported BLE stack creates the server, callbacks, characteristics, and CCCDs. Indications are emitted one MTU-sized frame at a time; the stack waits for indication confirmation before the next frame. Disconnect restarts advertising.

## 4. Production core and framing

`src/GattProtocol.cpp` is a platform-independent C++17 core used unchanged by `src/GattServer.cpp` and the native host executable. BLE callbacks only copy bounded ATT writes into a four-entry queue; the main loop invokes the parser/session core under a critical section.

Framing is the frozen 10-byte `SG` v1 header with one 2,048-byte reassembly buffer, one message ID per connection, exact header consistency, sequential fragments, idempotent identical duplicate handling, changed-duplicate rejection, and a rollover-safe 2,000 ms assembly deadline. Hello, Target Hello, Challenge, Proof, and Result payloads are exactly 16, 20, 138, 103, and 32 bytes.

Unsupported protocol/framing/range hello input returns unsupported negotiation without creating session, nonce, or challenge material. A valid hello creates a 16-byte session ID and 32-byte nonce from the hardware CSPRNG. A separate nonzero 16-byte boot ID is generated once per boot; all-zero or repeated RNG output disables authentication fail-closed.

The challenge lifetime is 5,000 ms and comparisons are safe across `millis()` rollover. Proof consumes the session before verifier invocation. Replay, timeout, malformed frames, connection mismatch, a second concurrent connection, OTA busy, and rate/backoff conditions clear bounded state and return a fixed public reason.

## 5. OTA and observability integration

`OtaManager::checkAndUpdate()` asserts GATT OTA-busy before the first blocking HTTP/TLS operation and an RAII guard clears it on every return; the successful restart path clears it explicitly before reboot. Busy resets active auth state and subsequent writes fail with `BUSY`. Existing dual-slot/rollback, periodic HTTPS, authenticated local recovery, and updater-independence contracts are not replaced by this coupling.

The core exposes a bounded `EventSink` using canonical catalog enums for `ACCESS_GATT_CONNECTED`/`ACCESS_GATT_FAILED`, `ACCESS_PROOF_REQUESTED`/`ACCESS_PROOF_VERIFIED`/`ACCESS_PROOF_REJECTED`, and `ACCESS_SESSION_TERMINATED`, together with fixed catalog reason enums. #20 must wrap these hooks in the complete v1 envelope and causal access chain. This change does not claim production telemetry, radio coexistence, heap retention, or latency evidence.

## 6. Executable evidence and remaining gates

Native host tests compile `src/GattProtocol.cpp` directly and cover canonical SHA/framing/challenge vectors, N/N-1, strict lengths/ranges, malformed and deterministic fuzz inputs, maximum-size bounds, fragment sequence/duplicates/consistency, 2-second timeout, replay, connection limit, disable/reset, stale NVS under compile OFF, OTA busy, rollover, rate limiting, null/capacity outputs, fail-closed verifier, test-only allow/deny verifier, action 2 rejection, no relay integration, and advertisement/filter constants.

The feature-ON `esp32c6` PlatformIO build compiles the real BLE server and adapter. These are software checks only. No Samsung/OEM wake run, ESP32-C6 radio capture, GPIO/relay/sensor trial, heap/soak test, power-loss/bootloader test, OTA-G1..G4, or RELAY-G0..G2 evidence is claimed. Issue #18 and Epic #13 remain open.

## 7. Hardware contract

- ESP32-C6-DevKitC-1, RISC-V, pioarduino.
- Relay input is authoritative GPIO3, active-low assumption, boot OFF safety retained.
- AJ-SR04T remains GPIO10/11 in the current firmware.
- Physical relay polarity, electrical safety, and GPIO3 behavior remain unverified.
