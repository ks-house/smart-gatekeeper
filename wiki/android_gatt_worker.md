# Android native BLE GATT credential worker

> Hardwareless RC for issue #17. This page describes software evidence only; Samsung/OEM screen-off delivery and ESP32-C6 radio interoperability remain G0-HW gates.

## 1. Scope and safety boundary

The Android path is an OS-managed `PendingIntent` scan receiver followed by a native WorkManager job. It does not require a Flutter engine, Activity, foreground scanner, WebView, backend network, or MQTT connection. Production ownership is disabled by default and remains on the legacy scanner unless every remote flag condition is valid.

This RC does not change either of these independent paths:

- `manual_remote`: the authenticated, explicit Flutter button door-open path remains distinct from hands-free BLE authentication.
- OTA: the mobile update manager remains reachable through its existing UI and storage path regardless of the BLE flag, worker state, or worker crash. Target dual-slot update, rollback, periodic HTTPS pull, and authenticated local recovery are unchanged.

## 2. Wake-to-worker flow

```text
BluetoothLeScanner PendingIntent
  -> BleWakeScanReceiver (strongest matching result, no Flutter engine)
  -> BleWakeNativeEntrypoint (existing redacted wake journal)
  -> unique WorkManager request, ExistingWorkPolicy.KEEP
  -> durable duplicate coalescer and session ledger
  -> AndroidBleGattTransport
  -> challenge read -> canonical proof sign -> proof write -> result indication
```

The receiver never persists the peer address in its JSON diagnostic journal. The address is passed only in the private WorkManager input needed for the connection attempt. A `SecurityException` at scan delivery is converted to the fixed `PERMISSION_DENIED` reason instead of crashing the receiver.

WorkManager uses a unique work name with `KEEP`, three total attempts, exponential backoff beginning at 10 seconds, and a bounded 15-second GATT session timeout. The session ledger is app-private durable storage, so a process restart resumes or classifies an existing session rather than creating a second door attempt.

## 3. Feature flag and BLE ownership

The native worker owns BLE only when all of the following are true:

1. the remote flag is present;
2. its payload has been authenticated and validated by the remote-config control plane;
3. `enabled=true`;
4. the flag has not expired.

Missing, malformed, unauthenticated, disabled, or stale state always resolves to `legacy`. When native ownership is active, the vendored legacy beacon plugin rejects initialization with `BLE_OWNER_EXCLUDED`; when native ownership is not active, the worker exits without opening GATT. This makes legacy and native ownership mutually exclusive at both entry points.

The RC intentionally exposes no Flutter mutation method for the feature flag or credential. Remote configuration and enrollment are future authenticated native control-plane inputs. The only Flutter bridge added here is read-only health inspection.

## 4. Credential and protocol contract

`BleGattTransport` is the testable boundary between the state machine and Android Bluetooth APIs. The production transport performs service discovery, enables the result CCCD, writes client hello, reads the challenge, writes proof, and awaits a result indication. Protocol messages use the UUIDs, lengths, field ordering, unsigned integer encoding, SHA-256 inputs, ATT fragmentation, and reassembly rules in `security_protocol.md` and `protocol/test_vectors/v1.json`.

`AndroidKeystoreCredentialSigner` uses an AndroidKeyStore P-256 key configured for ECDSA/SHA-256. Signing converts ASN.1 DER output to exact 64-byte P1363 `r || low-S(s)` form. A missing credential is `CREDENTIAL_INACTIVE`; authentication never creates a new identity implicitly. Key creation is an enrollment-only operation, and neither private-key bytes nor raw challenges, proofs, peer addresses, tokens, or key material are returned to Flutter or written to logs.

The JVM fake signer is deterministic and holds test-only material. It verifies canonical compatibility without invoking AndroidKeyStore.

## 5. Durable coalescing and diagnostics

A duplicate fingerprint is an HMAC over the private wake inputs, so diagnostics never use the raw address as their correlation key. The app-private ledger retains the address only while it is needed to reconnect after a worker restart; it is excluded from the wake journal, health bridge, and logs. Repeated wake delivery for an active event coalesces into the original durable session. Terminal completion followed by a distinct event creates a new session. The health projection exposes only bounded, crash-safe fields: state, stable reason, attempt count, update time, and latency.

The Flutter MethodChannel `com.kshouse.gatekeeper_app/ble_gatt_worker_health` accepts only `getHealth` and returns:

- effective owner and flag reason;
- healthy/unhealthy state;
- last stable session reason;
- last latency in milliseconds;
- last update time.

It has no enable, enrollment, signing, connection, retry, or door-open method.

## 6. Stable reasons

Worker outcomes are mapped to the observability access reason vocabulary where a matching code exists. Android lifecycle blockers that are not access decisions remain explicit diagnostic states and never masquerade as authorization success.

| Native reason | Observability mapping / meaning |
|---|---|
| `PERMISSION_DENIED` | exact schema code `PERMISSION_DENIED` |
| `BLUETOOTH_DISABLED` | exact schema code `BLUETOOTH_DISABLED` |
| `FORCE_STOPPED` | exact schema code `FORCE_STOPPED`; OS will not deliver PendingIntent work until user launch |
| `BATTERY_RESTRICTED` | exact schema code `BATTERY_RESTRICTED` |
| `GATT_CONNECT_FAILED` | exact schema code `GATT_CONNECT_FAILED` |
| `GATT_TIMEOUT` | exact schema code `GATT_TIMEOUT` |
| `GATT_DISCONNECTED` | exact schema code `GATT_DISCONNECTED` |
| `SIGNATURE_INVALID` | exact schema code `SIGNATURE_INVALID` |
| `PROOF_EXPIRED` | exact schema code `PROOF_EXPIRED` |
| `NONCE_REPLAYED` | exact schema code `NONCE_REPLAYED` |
| `MALFORMED_PROOF` | exact schema code `MALFORMED_PROOF`, including malformed challenge/result framing |
| `PROTOCOL_INCOMPATIBLE` | exact schema code `PROTOCOL_INCOMPATIBLE` |
| `ACL_NOT_FOUND` | exact schema code `ACL_NOT_FOUND` |
| `CREDENTIAL_INACTIVE` | exact schema code `CREDENTIAL_INACTIVE` |
| `TARGET_BUSY` | exact schema code `TARGET_BUSY` |
| `INTERNAL_ERROR` | `INTERNAL_ERROR` |

Network-off is not a blocker: the worker has no WorkManager network constraint and its GATT session test succeeds with network unavailable. OTA/update ownership is reported separately as `updateManagerIndependent=true` and `updateManagerOwnedByWorker=false`; the worker does not emit a fabricated access reason for an updater it does not own.

## 7. Hardwareless evidence (2026-08-02)

- Forced targeted Android run: `:app:testDebugUnitTest --tests 'com.kshouse.gatekeeper_app.gattworker.*' --rerun-tasks`; 208 tasks executed.
- JUnit XML: 3 suites, 12 tests, 0 failures, 0 errors, 0 skipped.
- Full Android JVM suite: 18 tests passed.
- Flutter: 6 tests passed.
- Targeted Dart analysis of the two changed files: no issues. Full analysis retains 17 pre-existing info-level findings in vendored `flutter_beacon_local`.
- Debug APK: `gatekeeper_app/build/app/outputs/flutter-apk/app-debug.apk` built successfully.
- Protocol, observability, repository gates, and diff/link/immutability checks are recorded in the append-only log.

The JVM coverage includes canonical vector compatibility, ATT fragments, deterministic signing conversion, complete GATT exchange, network-off operation, target retry classification, timeout, malformed result, duplicate delivery, process restart, default-safe flag behavior and ownership exclusion, diagnostic redaction, and OTA independence.

## 8. Pending physical gates

No Samsung screen-off, Activity-terminated, process-killed, reboot-registration, OEM battery-policy, real BLE radio, ESP32-C6 GATT, latency percentile, relay, sensor, or bootloader evidence is claimed. Production enablement, legacy retirement, issue closure, and Epic closure remain blocked by the applicable G0-HW, RELAY-G0 through G2, OTA-G1 through G4, and issue #14/#23 device/operator evidence.
