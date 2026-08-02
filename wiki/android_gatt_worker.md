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
  -> Keystore-HMAC wake identity + unique WorkManager request
  -> durable duplicate coalescer, including terminal/redelivered wakes
  -> cross-process exclusive native BLE lease
  -> AndroidBleGattTransport
  -> challenge read -> canonical proof sign
  -> durable PROOF_UNCERTAIN commit + encrypted-locator deletion
  -> proof write -> result indication -> terminal commit
```

The receiver never persists the peer address in its JSON diagnostic journal or WorkManager input. The OS scan timestamp/callback identity and address are reduced to a Keystore-HMAC fingerprint; the raw address and credential ID are held only in an AES-GCM record under `noBackupFilesDir` with a non-exportable AndroidKeyStore key. A `SecurityException` at scan delivery is converted to the fixed `PERMISSION_DENIED` reason instead of crashing the receiver.

Initial WorkManager dispatch uses a unique work name with `KEEP`; retry work uses `APPEND_OR_REPLACE` with the exact bounded delay selected from local exponential backoff and Target `retry_after_ms` (hard cap 30 seconds). The ledger stores both the selected delay and its durable scheduling epoch, so a process restart or redelivered WorkManager item re-enqueues the remaining delay instead of retrying early. Three total attempts and a bounded 15-second GATT session timeout remain fail-closed. Before the first proof byte can be written, the ledger durably enters `PROOF_UNCERTAIN` and deletes the locator ciphertext. A restart from that state never reconnects or signs again. Only an explicit Target failure result resolves uncertainty and may schedule a new Target session; a crash after proof write, after result receipt, or before the final ledger commit cannot repeat proof/ARM for that wake.

## 3. Feature flag and BLE ownership

The native worker owns BLE only when all of the following are true:

1. the remote envelope is signed by the APK-pinned P-256 rollout authority and matches its issuer/key ID;
2. its revision is positive and strictly greater than the accepted revision;
3. its issued/expiry window is current, bounded to seven days, and within the clock-skew contract;
4. it is bound to both the enrolled 16-byte credential ID and the SHA-256 of the exact AndroidKeyStore public key;
5. that non-exportable credential key is present;
6. `enabled=true`.

The authority is supplied only by signed APK manifest metadata (`GATT_FLAG_AUTHORITY_ISSUER`, `GATT_FLAG_AUTHORITY_KEY_ID`, and `GATT_FLAG_AUTHORITY_P256_SEC1_HEX`). Authenticated state and its accepted revision are committed atomically under a cross-process update lock in `noBackupFilesDir`; the old caller-validated SharedPreferences records are cleared and never imported. This draft intentionally configures no production authority, so production remains default-OFF. Missing, malformed, signature-invalid, replayed, disabled, stale, restored-without-key, or key-mismatched state resolves to `legacy`.

Ownership is not inferred from cross-process SharedPreferences. A no-backup requested-owner marker plus an exclusive kernel file lease serializes the vendored legacy scanner and native worker across processes. OFF→ON first publishes the native request and sends a package-scoped stop signal; every legacy initialize/ranging/monitoring/bind entry point also reacquires the same legacy lease. Native GATT cannot start until legacy releases it. Expiry or authenticated rollback clears the marker, native work exits before proof, and legacy can reacquire only after the native lease closes. Process death releases the kernel lease automatically.

The RC intentionally exposes no Flutter mutation method for the feature flag or credential. Remote configuration and enrollment are future authenticated native control-plane inputs. The only Flutter bridge added here is read-only health inspection.

## 4. Credential and protocol contract

`BleGattTransport` is the testable boundary between the state machine and Android Bluetooth APIs. The production transport performs service discovery, enables the result CCCD, writes client hello, reads the challenge, writes proof, and awaits a result indication. Protocol messages use the UUIDs, lengths, field ordering, unsigned integer encoding, SHA-256 inputs, ATT fragmentation, and reassembly rules in `security_protocol.md` and `protocol/test_vectors/v1.json`.

`AndroidKeystoreCredentialSigner` uses an AndroidKeyStore P-256 key configured for ECDSA/SHA-256. Signing converts ASN.1 DER output to exact 64-byte P1363 `r || low-S(s)` form. A missing credential is `CREDENTIAL_INACTIVE`; authentication never creates a new identity implicitly. Key creation is an enrollment-only operation, and neither private-key bytes nor raw challenges, proofs, peer addresses, tokens, or key material are returned to Flutter or written to logs.

The JVM fake signer is deterministic and holds test-only material. It verifies canonical compatibility without invoking AndroidKeyStore.

## 5. Durable coalescing, migration, and diagnostics

A duplicate fingerprint is an HMAC over the private address plus stable OS wake identity. Its HMAC key is non-exportable AndroidKeyStore material, not a SharedPreferences byte string. Repeated delivery of the same wake coalesces into the original durable session even after terminal completion; a distinct advertisement timestamp creates a separate session.

The redacted `sessions_v2` ledger never serializes raw address or credential ID. On first read, legacy `sessions_v1` is decoded, sensitive fields are discarded, the redacted record is durably written, and the old preference is removed; corrupt legacy data is removed rather than retained. The credential ID and temporary locator moved to AES-GCM/no-backup storage, the old plaintext credential and HMAC preferences are deleted, and the old raw-ID Keystore alias is deleted with authenticated re-enrollment required because a non-exportable key cannot be renamed safely. Terminal and uncertain states delete the locator record immediately. Logs, health, WorkManager data, wake JSON, and filenames contain no raw locator.

The health projection exposes only bounded fields: state, stable observability reason, exact Target reason code/name, exact transport failure/status, raw and scheduled bounded retry delays, attempt count, update time, and latency.

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
| `TARGET_BUSY` | observability mapping for exact Target `BUSY(8)` or `RATE_LIMITED(9)`; exact wire code/name remains separately durable and visible |
| `INTERNAL_ERROR` | `INTERNAL_ERROR` |

The frozen Target wire reasons are retained exactly as `UNSUPPORTED_VERSION(1)`, `MALFORMED(2)`, `SESSION_INVALID(3)`, `EXPIRED_OR_REPLAY(4)`, `ACL_UNAVAILABLE(5)`, `CREDENTIAL_DENIED(6)`, `PROOF_INVALID(7)`, `BUSY(8)`, `RATE_LIMITED(9)`, and `INTERNAL_FAIL_CLOSED(10)`. Their observability mapping never replaces the wire identity. Callback transport failures likewise remain distinct as `DISCONNECTED`, `READ_FAILED`, `WRITE_FAILED`, `DESCRIPTOR_WRITE_FAILED`, `SERVICE_DISCOVERY_FAILED`, `MALFORMED_FRAME`, or `UNEXPECTED_MESSAGE_TYPE`, with Android GATT status retained where present.

Network-off is not a blocker: the worker has no WorkManager network constraint and its GATT session test succeeds with network unavailable. OTA/update ownership is reported separately as `updateManagerIndependent=true` and `updateManagerOwnedByWorker=false`; the worker does not emit a fabricated access reason for an updater it does not own.

## 7. Hardwareless evidence (2026-08-02)

- Forced targeted Android run: `:app:testDebugUnitTest --tests 'com.kshouse.gatekeeper_app.gattworker.*' --rerun-tasks`; 208 tasks executed.
- Final JUnit XML: 6 targeted suites, 23 tests, 0 failures, 0 errors, 0 skipped.
- Full Android JVM suite: 8 suites and 28 tests passed with 0 failures, 0 errors, and 0 skips.
- Flutter: 6 tests passed.
- Targeted Dart analysis of the two changed files: no issues. Full analysis retains 17 pre-existing info-level findings in vendored `flutter_beacon_local`.
- Debug APK: `gatekeeper_app/build/app/outputs/flutter-apk/app-debug.apk` built successfully.
- Protocol, observability, repository gates, and diff/link/immutability checks are recorded in the append-only log.

The JVM coverage includes signed flag tamper/expiry/replay/key-binding negatives, two-process ownership transitions, canonical vector compatibility, ATT fragments, deterministic signing conversion, complete GATT exchange, every frozen Target reason, exact disconnect/read/malformed callback failures, bounded Target retry delay, process death after proof write/result receipt, duplicate delivery across restart/terminal state, plaintext-ledger migration and redaction, network-off operation, OTA independence, and default-safe legacy fallback.

## 8. Pending physical gates

No Samsung screen-off, Activity-terminated, process-killed, reboot-registration, OEM battery-policy, real BLE radio, ESP32-C6 GATT, latency percentile, relay, sensor, or bootloader evidence is claimed. Production enablement, legacy retirement, issue closure, and Epic closure remain blocked by the applicable G0-HW, RELAY-G0 through G2, OTA-G1 through G4, and issue #14/#23 device/operator evidence.
