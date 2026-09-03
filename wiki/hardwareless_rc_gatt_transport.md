# ESP32-C6 connectable GATT transport (Issue #18)

> Updated: 2026-09-04
> Status: **personal production action-1/action-2 has connected board-level evidence; issue #175 defers actionable BLE until the post-boot signed ACL is active, while the disconnected phone and absent sensor/contact fixture keep final physical acceptance open**
> Tracking: GitHub [#18](https://github.com/ks-house/smart-gatekeeper/issues/18), Epic [#13](https://github.com/ks-house/smart-gatekeeper/issues/13)

## 1. Scope boundary

Issue #18 supplies the bounded BLE transport and authentication-session adapter needed by #20. It does not implement signed ACL storage, credential authorization, the Target-owned access FSM, or relay activation. The production/default `FailClosedProofVerifier` returns `ACL_UNAVAILABLE`; only native host tests inject a clearly test-only deterministic verifier.

Local GATT accepts action `1` (hands-free sensor ARM) and action `2` (explicit immediate local open). In both cases a successful cryptographic proof is insufficient by itself: Result OK is queued only after the Target control gate commits the requested transition into the actual FSM.

## 2. Feature gate

- `ENABLE_HARDWARELESS_RC` still defaults to `0` in the common developer profile. `esp32c6_production` also remains compile-OFF and has a compile-time guard against accidentally enabling Hardwareless in the commercial image.
- The explicit `esp32c6_personal_production` profile is the only production image that sets `SGK_PERSONAL_INSTALLATION_BUILD=1` and `ENABLE_HARDWARELESS_RC=1`. It is used by both personal Target CI lanes and does not authorize a commercial deployment.
- `sgk::effectiveFeatureEnabled()` makes compile OFF dominate any stale NVS `hwless_rc=true` value. An OFF build does not create the service, clears the one-time personal migration epoch and forces runtime OFF.
- A personal image requests runtime ON exactly once, and only after the Hardwareless door ID, ACL signer public key and signer key ID all validate. The migration marker is written after the ON value; after that marker exists, an operator-persisted `hwless_rc=false` remains an authoritative kill switch across reboot and rebuild.
- Runtime disable disconnects peers, removes/stops the service, clears queued writes, and resets session state. A feature-ON image still requires an exact, nonzero/non-`ff` 16-byte `door_id` provisioned through `secrets.h` or NVS; it also requires a valid P-256 ACL signer and nonzero signing key ID. Absent/invalid identity or trust material disables auth fail-closed, and no sample door ID or signer ships.
- `SECRET_HARDWARELESS_DOOR_ID_HEX`, `SECRET_ACL_SIGNER_PUBLIC_KEY_HEX`, and `SECRET_ACL_SIGNING_KEY_ID` are required personal CI inputs. They are real identity/trust values, not fields that accept arbitrary placeholders.
- A reboot intentionally leaves a stored ACL inactive until a fresh signed ACL is received because the Target has no trusted wall clock. In the personal Hardwareless image, iBeacon/connectable GATT therefore stays off until `hasActiveAcl()` becomes true after MQTT refresh. The BLE stack then starts exactly once. Non-Hardwareless builds retain immediate beacon startup.
- Personal source enablement does not retire legacy recovery or close G0-HW, RELAY-G0..G2, OTA-G1..G4, OEM or operator gates.

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
| Fast RX | `9f4d1005-7d9e-4fb1-9c54-6f4d53474b31` | write, user description |
| Fast TX | `9f4d1006-7d9e-4fb1-9c54-6f4d53474b31` | indicate, user description, CCCD |

The Arduino-ESP32 supported BLE stack creates the server, callbacks, characteristics, and CCCDs. The adapter disconnects every rejected handle, binds each accepted handle to a monotonically increasing connection generation, and retains both values on queued writes and outputs. NimBLE writes from rejected/stale owners are ignored, and `ble_gatts_indicate_custom()` targets only the accepted peer after that peer subscribes to the relevant characteristic. `onStatus` records the ACK/error state only; the next MTU-sized fragment is drained by the Arduino loop task. Timeout/error aborts the output and core session. Disconnect restarts advertising.

## 4. Production core and framing

`src/GattProtocol.cpp` is a platform-independent C++17 core used unchanged by `src/GattServer.cpp` and the native host executable. BLE callbacks only copy bounded ATT writes plus the writer connection token into a four-entry queue; the main loop invokes the parser/session core under a critical section. Queue overflow clears/preempts all queued proof work before any verifier call. Authentication control effects are separated from telemetry: ProofRequested/ProofVerified update the FSM synchronously on the 16 KB loop task before Result output, while callback-originated abort and advertising restart are coalesced and drained by that loop. Canonical audit events use a separate bounded 16-entry queue, so telemetry overflow is explicit but cannot turn an `OK` Result into an unarmed Target. JSON/MQTTS publication also runs from the loop task. This keeps the 2.7 KB output-drain and 3.2 KB event-publication frames off NimBLE's 5 KB host stack.

Framing is the frozen 10-byte `SG` v1 header with one 2,048-byte reassembly buffer, one message ID per connection, exact header consistency, sequential fragments, idempotent identical duplicate handling, changed-duplicate rejection, and a rollover-safe 2,000 ms assembly deadline. Hello, Target Hello, Challenge, Proof, and Result payloads are exactly 16, 20, 138, 103, and 32 bytes.

Protocol v2 retains that strict framing and the 138/103/32-byte authenticated payload sizes, but removes normal-operation negotiation traffic. Enabling the one Fast TX CCCD schedules a fresh Target challenge on the Arduino loop; `FAST_CHALLENGE(0x20) → FAST_PROOF(0x21) → FAST_RESULT(0x22)` then completes on the two fast characteristics. The Target requests a 15 ms BLE connection interval as a non-authoritative hint, while Android requests high priority before service discovery. Correctness does not depend on either request being accepted.

The v1 characteristics remain isolated only for the OTA N/N-1 transition window. Android selects v1 only when both fast characteristics are absent; a partial Fast RX/TX service fails closed. A v2-selected connection never falls back to v1 after an error. The fast session still generates fresh CSPRNG material, uses `SGKCHAL2`/`SGKPRF02` domain separation, verifies the current signed ACL, consumes proof once, and binds OK to the FSM commit. It does not cache an Android private key or reusable authorization on Target.

Unsupported protocol/framing/range hello input returns unsupported negotiation without creating session, nonce, or challenge material. A valid hello creates a 16-byte session ID and 32-byte nonce from the hardware CSPRNG. A separate nonzero 16-byte boot ID is generated once per boot. Each session/nonce draw rejects all-zero and its immediately previous value for at most four attempts; exhausting those conservative guards disables authentication fail-closed. This is not a claim that arbitrary non-adjacent repeats are detected.

The challenge lifetime is 5,000 ms and comparisons are safe across `millis()` rollover. Proof consumes the session before verifier invocation. Replay, timeout, malformed frames, connection mismatch, a second concurrent connection, OTA busy, and rate/backoff conditions clear bounded state and return a fixed public reason.

## 5. OTA and observability integration

`OtaManager::checkAndUpdate()` first asserts GATT OTA-busy. An active auth session queues a protocol/session-bound `BUSY` result before its secrets reset. `WAIT_SAFE_STATE` then reads the real Target FSM, `is_armed`, and relay state, allows an already-authorized legacy or authenticated `manual_remote` one-shot plus cooldown to finish, and times out before starting HTTP/TLS/download/flash if `IDLE`/relay-OFF is not reached. An RAII guard clears busy on every return; the successful restart path clears it explicitly before reboot. Existing dual-slot/rollback, periodic HTTPS, authenticated local recovery, and updater-independence contracts are not replaced by this software arbitration.

Production now installs a deferred canonical MQTT event sink for the GATT segment. It preserves authentication lifecycle ordering before the corresponding Result output, then emits schema-v1 catalog code/reason pairs with a UUIDv4 event/session representation, HMAC-derived opaque Target reference, 16-byte boot binding, uint64 monotonic/sequence fields, and direct causation IDs from the main loop. This is only a bounded best-effort emitter for the local GATT segment: it does not supply durable offline queue/delivery proof, cross-layer success evidence, or complete production telemetry. No radio coexistence, heap retention, or latency evidence is claimed.

## 6. Executable evidence and remaining gates

Native host tests compile `src/GattProtocol.cpp` directly and cover canonical SHA/framing/challenge vectors, N/N-1, strict lengths/ranges, malformed and deterministic fuzz inputs, maximum-size bounds, fragment sequence/duplicates/consistency, 2-second timeout, replay, second-peer rejection, disconnect/reconnect generation races, overflow-before-proof, ACK/error/timeout indication transitions, provisioned door fail-closed, same-core cross-door replay, canonical uint64/session/boot/sequence/causation fields, disable/reset, stale NVS under compile OFF, OTA busy, rollover, rate limiting, null/capacity outputs, fail-closed verifier, test-only allow/deny verifier, v2 single-subscription challenge/proof/result and advertisement/filter constants.

The feature-ON `esp32c6_personal_production` path first exposed a repeatable `nimble_host` stack-protection reset and then an Android mixed Challenge read/indication race. Exact main `db37bc2390efbf94bf1a9fca261834c3728606b5` included both corrections. Run `32777471683` published and HA OTA installed Target `2.1.262+main.gdb37bc2`; run `32777471718` produced the matching production Android APK and it was replacement-installed on SM-F966N. One foreground action-1 session completed with worker health `HEALTHY`, no failure/Target denial and 4,599 ms latency. HA independently recorded `AUTH_PENDING` at 06:27:33, `ARMED` at 06:27:36 and `IDLE` at 06:28:35, without a Target reset.

That historical session proves exact-main foreground transport/proof/result and action-1 FSM ARM only. Issue #133 subsequently introduced action 2 for immediate local relay and explicit Result-to-FSM coupling; issue #134 changed bounded pocket dispatch. Current exact-main `a9b68222` Target `2.1.266+main.ga9b6822` is signed-OTA installed, but the matching `1.0.0-ga9b6822` / 19801 APK is only NAS-published because no phone was connected. No current action-2 phone session, repeated Samsung screen-off/process-killed run, relay/sensor trial, heap/soak test, power-loss/bootloader test, complete OTA-G1..G4, or RELAY-G0..G2 evidence is claimed. Issue #18 and Epic #13 remain open.

Exact main `3cf6eaa925e5ef38ee7d538a6d7a1cf8720ad219` was installed as Target `2.1.282+main.g3cf6eaa` and Android `1.0.0-g3cf6eaa` / 21701. With the ACL already active, the main action-2 button reached Target relay-command ON/OFF and terminal UI success in 4,636 ms; a separate foreground action-1 reached `ARMED` in 4,688 ms. These pass only the authenticated board/FSM/GPIO command boundaries.

A controlled Home + Dozing + secure-keyguard first match immediately after Target boot then reproduced a narrower race: Android received `screen_interactive=false` at RSSI -51 and connected before the retained signed ACL had been reactivated; the worker failed after about 3.4 seconds and Target never entered `ARMED`. Runtime order and `TargetAclManager::begin()` confirmed that BLE advertising preceded the post-boot MQTT ACL refresh.

Issue #175 added the one-shot ACL-gated startup policy and merged through PR #176. Final main `577533186ba5b40ca13fc47aadf51747e2057b73` was CI/NAS-published and connected-OTA installed as `2.1.285+main.g5775331`. The exact boot trace showed BLE waiting, MQTTS recovery, signed ACL v203 application, and only then GATT/iBeacon start. A following periodic check was already current. This accepts the Target-side startup order, but the phone is now disconnected so the post-fix screen-off action-1 repetition is still pending. AJ-SR04T, relay contact/load, door movement and bootloader rollback were not proven.

## 7. Hardware contract

- ESP32-C6-DevKitC-1, RISC-V, pioarduino.
- Relay input is authoritative GPIO23, active-low assumption, boot OFF safety retained.
- AJ-SR04T remains GPIO10/11 in the current firmware.
- Physical relay polarity, electrical safety, and GPIO23 behavior remain unverified after the source restoration.
