# Android native BLE GATT credential worker

> Hardwareless RC for issues #17 and #133. The personal local-bootstrap, background action-1 worker and foreground action-2 manual-open paths are implemented and software-tested; current phone/relay physical evidence remains pending.

## 1. Scope and safety boundary

The Android execution path is an OS-managed `PendingIntent` scan receiver followed by a native WorkManager job. Once enrolled and enabled, a GATT proof does not require a Flutter engine, Activity, foreground scanner, WebView, backend network, or MQTT connection. The explicit personal bootstrap does require authenticated HTTPS once to enroll or reconcile the public credential and confirm exact Target ACL application before native ownership is enabled. A fresh APK install alone remains OFF.

This RC does not change either of these independent paths:

- `manual_local_gatt`: the app's button runs signed `OPEN_IMMEDIATELY(2)` directly in a foreground coroutine, waits for the terminal Target Result, and never sends a plaintext Target command.
- `background_local_gatt`: PendingIntent/WorkManager presence always signs `ARM_FOR_SENSOR(1)`; it can arm the Target but cannot bypass the ultrasonic trigger.
- `manual_remote`: the authenticated Backend/MQTT command remains a separate remote-control path; Home Assistant can expose it only through the signed backend bridge's independent opt-in.
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
  -> ACK-gated challenge indication -> canonical proof sign
  -> durable PROOF_UNCERTAIN commit + encrypted-locator deletion
  -> proof write -> result indication -> terminal commit
```

The receiver never persists the peer address in its JSON diagnostic journal or WorkManager input. The OS scan timestamp/callback identity and address are reduced to a Keystore-HMAC fingerprint; the raw address and credential ID are held only in an AES-GCM record under `noBackupFilesDir` with a non-exportable AndroidKeyStore key. A `SecurityException` at scan delivery is converted to the fixed `PERMISSION_DENIED` reason instead of crashing the receiver.

Initial WorkManager dispatch uses a unique work name with `KEEP`; retry work uses `APPEND_OR_REPLACE` with the exact bounded delay selected from local exponential backoff and Target `retry_after_ms` (hard cap 30 seconds). The ledger stores both the selected delay and its durable scheduling epoch, so a process restart or redelivered WorkManager item re-enqueues the remaining delay instead of retrying early. Three total attempts and a bounded 15-second GATT session timeout remain fail-closed. Before the first proof byte can be written, the ledger durably enters `PROOF_UNCERTAIN` and deletes the locator ciphertext. A restart from that state never reconnects or signs again. Only an explicit Target failure result resolves uncertainty and may schedule a new Target session; a crash after proof write, after result receipt, or before the final ledger commit cannot repeat proof/ARM for that wake.

## 3. Feature flag and BLE ownership

The signed remote rollout path continues to let the native worker own BLE only when all of the following are true:

1. the remote envelope is signed by the APK-pinned P-256 rollout authority and matches its issuer/key ID;
2. its revision is positive and strictly greater than the accepted revision;
3. its issued/expiry window is current, bounded to seven days, and within the clock-skew contract;
4. it is bound to both the enrolled 16-byte credential ID and the SHA-256 of the exact AndroidKeyStore public key;
5. that non-exportable credential key is present;
6. `enabled=true`.

The remote authority is supplied only by signed APK manifest metadata (`GATT_FLAG_AUTHORITY_ISSUER`, `GATT_FLAG_AUTHORITY_KEY_ID`, and `GATT_FLAG_AUTHORITY_P256_SEC1_HEX`). Authenticated state and its accepted revision are committed atomically under a cross-process update lock in `noBackupFilesDir`; the old caller-validated SharedPreferences records are cleared and never imported. Missing, malformed, signature-invalid, replayed, disabled, stale, restored-without-key, or key-mismatched remote state resolves to `legacy`. A present remote snapshot has precedence and cannot be bypassed by the personal bootstrap.

When no remote snapshot exists, the personal-build-only `GATT_LOCAL_MANUAL_BOOTSTRAP` policy permits a narrower path. Gradle defaults its manifest placeholder to `false`; only the exact-main personal mobile OTA producer sets `SGK_PERSONAL_GATT_BOOTSTRAP=1`, while debug and commercial production builds remain OFF. It remains OFF until an explicit UI action prepares the AndroidKeyStore credential, the backend confirms exact Target ACL application, and native code commits an AES-GCM protected consent record bound to hashes of the credential ID and public key. The obsolete Flutter `ENABLE_HARDWARELESS_RC` preference is removed; native health and consent state are authoritative. A missing key, invalid binding, corrupt consent, explicit OFF, legacy-prearm selection, or kill switch returns ownership to `legacy`.

Ownership is not inferred from cross-process SharedPreferences. A no-backup requested-owner marker plus an exclusive kernel file lease serializes the vendored legacy scanner and native worker across processes. OFF→ON first publishes the native request and sends a package-scoped stop signal; every legacy initialize/ranging/monitoring/bind entry point also reacquires the same legacy lease. Native GATT cannot start until legacy releases it. Expiry or authenticated rollback clears the marker, native work exits before proof, and legacy can reacquire only after the native lease closes. Process death releases the kernel lease automatically.

The Flutter bridge exposes bounded operations for health, public enrollment material, explicit local consent ON/OFF, diagnostic background retry, and terminal manual open. `triggerLocalGattOpen` returns only redacted success/reason/session/latency fields after the Target result; it never returns a private key, signature proof, challenge, raw peer locator, or secret. The UI first calls `POST /api/v1/acl/personal/enroll` over HTTPS only when local enrollment is absent or invalid; an already valid local credential starts manual GATT without a per-tap backend status round trip. Enrollment accepts only an echoed exact credential and positive ACL version after the backend observed exact Target ACL applied ACK. Native ON happens after that response, never before it. Once action 1 is verified and `ARMED`, Target rejects every new ClientHello before proof through sensor wait, relay hold and cooldown. Foreground action 2 therefore cannot replace that actor/session; Target Hello status 2 is surfaced as retryable `TARGET_BUSY`, not `PROTOCOL_INCOMPATIBLE`, and a new attempt waits for exact-session next-auth-ready evidence (fresh `IDLE`, relay OFF).

## 4. Credential and protocol contract

`BleGattTransport` is the testable boundary between the state machine and Android Bluetooth APIs. The production transport performs service discovery, enables the hello/challenge/result CCCDs, writes client hello, receives Target Hello and Challenge as ACK-gated indications through one ordered mailbox, writes proof, and awaits a result indication. It must not issue a simultaneous Challenge characteristic read: the readable single-frame representation and fragmented indication representation can share a message ID and interleave in Android callbacks, which the strict reassembler correctly rejects as malformed. Protocol messages use the UUIDs, lengths, field ordering, unsigned integer encoding, SHA-256 inputs, ATT fragmentation, and reassembly rules in `security_protocol.md` and `protocol/test_vectors/v1.json`.

`GattSessionEngine.run(..., action)` signs the action into both canonical proof bytes and the wire payload. Background `BleGattCredentialWorker` passes action 1 explicitly. `BleGattManualOpenExecutor` acquires the same exclusive native BLE lease and passes action 2 explicitly; before proof write it durably records `PROOF_UNCERTAIN`, and it reports success only for Target reason 0. This separation prevents the manual button from merely arming the sensor path and prevents background presence from directly opening the relay.

Every `connectGatt` call now owns a monotonic transport generation and a callback object captured for that generation. The first callback and the returned `BluetoothGatt` must identify the same connection owner; callbacks from an older generation, a different GATT object, or a terminal connection are ignored. Characteristic and CCCD writes use operation-scoped single-consumer latches keyed by operation kind and characteristic UUID instead of buffered result channels. A disconnect atomically completes connection, service-discovery, message, characteristic-write, and descriptor-write waiters exactly once with `DISCONNECTED` and the original Android GATT status. Late or duplicate callbacks cannot be buffered for a later operation, and reconnect creates a clean generation, so an in-flight disconnect is never allowed to drift into the outer 15-second `GATT_TIMEOUT` classification.

`AndroidKeystoreCredentialSigner` uses an AndroidKeyStore P-256 key configured for ECDSA/SHA-256. Signing converts ASN.1 DER output to exact 64-byte P1363 `r || low-S(s)` form. A missing credential is `CREDENTIAL_INACTIVE`; a background authentication attempt never creates a new identity implicitly. Key creation occurs only during the explicit enrollment/bootstrap operation, uses a CSPRNG-generated nonzero 16-byte credential ID, and never replaces an existing identity whose key disappeared. Neither private-key bytes nor raw challenges, proofs, peer addresses, tokens, or key material are returned to Flutter or written to logs.

The JVM fake signer is deterministic and holds test-only material. It verifies canonical compatibility without invoking AndroidKeyStore.

## 5. Durable coalescing, migration, and diagnostics

A duplicate fingerprint is an HMAC over the private address plus stable OS wake identity. Its HMAC key is non-exportable AndroidKeyStore material, not a SharedPreferences byte string. Repeated delivery of the same wake coalesces into the original durable session even after terminal completion; a distinct advertisement timestamp creates a separate session.

The redacted `sessions_v2` ledger never serializes raw address or credential ID. On first read, legacy `sessions_v1` is decoded, sensitive fields are discarded, the redacted record is durably written, and the old preference is removed; corrupt legacy data is removed rather than retained. The credential ID and temporary locator moved to AES-GCM/no-backup storage, the old plaintext credential and HMAC preferences are deleted, and the old raw-ID Keystore alias is deleted with authenticated re-enrollment required because a non-exportable key cannot be renamed safely. Terminal and uncertain states delete the locator record immediately. Logs, health, WorkManager data, wake JSON, and filenames contain no raw locator.

The health projection exposes only bounded fields: state, stable observability reason, exact Target reason code/name, exact transport failure/status, raw and scheduled bounded retry delays, attempt count, update time, latency, and the latest privacy-safe BLE wake summary. That summary contains only source, success, receive time, callback latency, strongest RSSI, screen-interactive state, result count, and scan error code. It never contains a raw peer address, credential ID, challenge, proof, token, or private key.

The Flutter MethodChannel `com.kshouse.gatekeeper_app/ble_gatt_worker_health` `getHealth` response returns:

- effective owner and flag reason;
- healthy/unhealthy state;
- last stable session reason;
- last latency in milliseconds;
- last update time;
- latest redacted Target-detection summary and presence-to-dispatch/ARMED timing.

The same bounded channel also owns the explicit local-consent toggle, enrollment material, diagnostic retry, and terminal manual action-2 operation described in section 3. None of those methods exports signing material or a raw peer locator.

While the Smart Key control screen is mounted, Flutter polls this projection once per second and renders `waiting`, `detected`, `authenticating`, `armed`, `failed`, or `disabled`. The card shows the latest receive time and age, one advertisement RSSI sample, screen ON/OFF state, durable session state, and presence-to-ARMED latency. A detection older than the native `maxPresenceAgeMs` contract (currently 45 seconds) is rendered as waiting, so an old journal entry cannot masquerade as current presence. This is a latest-event/status projection, not continuous BLE ranging and not a distance measurement.

## 6. Stable reasons

Worker outcomes are mapped to the observability access reason vocabulary where a matching code exists. Android lifecycle blockers that are not access decisions remain explicit diagnostic states and never masquerade as authorization success.

| Native reason | Observability mapping / meaning |
|---|---|
| `PERMISSION_DENIED` | exact schema code `PERMISSION_DENIED` |
| `BLUETOOTH_DISABLED` | exact schema code `BLUETOOTH_DISABLED` |
| `FORCE_STOPPED` | exact schema code `FORCE_STOPPED`; OS will not deliver PendingIntent work until user launch |
| `BATTERY_RESTRICTED` | exact schema code `BATTERY_RESTRICTED` |
| `PRESENCE_EXPIRED` | a delayed/retried wake exceeded the 45-second presence execution window and is terminally discarded before GATT proof |
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
- Final JUnit XML: 6 targeted GATT worker suites, 30 tests, 0 failures, 0 errors, 0 skipped.
- Full Android JVM suite: 8 suites and 36 tests passed with 0 failures, 0 errors, and 0 skips; all 208 Gradle tasks were freshly executed with `--rerun-tasks`.
- Flutter: 6 tests passed.
- Targeted Dart analysis of the two changed files: no issues. Full analysis retains 17 pre-existing info-level findings in vendored `flutter_beacon_local`.
- Debug APK: `gatekeeper_app/build/app/outputs/flutter-apk/app-debug.apk` built successfully.
- Protocol, observability, repository gates, and diff/link/immutability checks are recorded in the append-only log.

The JVM coverage includes signed flag tamper/expiry/replay/key-binding negatives, two-process ownership transitions, canonical vector compatibility, ATT fragments, deterministic signing conversion, complete GATT exchange, every frozen Target reason, disconnect during client-hello/proof characteristic writes and CCCD writes, exact status preservation without timeout misclassification, simultaneous waiter fan-out, ordered Target-Hello/challenge indication delivery, late/duplicate callbacks, reconnect generation isolation, malformed callback failures, bounded Target retry delay, process death after proof write/result receipt, duplicate delivery across restart/terminal state, plaintext-ledger migration and redaction, network-off operation, OTA independence, and default-safe legacy fallback.

## 8. Historical physical evidence and pending gates

On 2026-08-25 the production-signed `1.0.0-gbc9bb5d` APK (`versionCode=18501`) was installed with `adb install -r`; package data, local consent and the AndroidKeyStore credential were preserved. Corrected iBeacon bytes produced exact-filter PendingIntent deliveries and native GATT connected to the ESP32-C6. After the Target callback-stack fix stopped its reset, that installed app reached Target Hello/challenge but returned `MALFORMED_PROOF`. The physical trace and source path identified the simultaneous Challenge indication/read stream race described above.

The matching exact-main correction was subsequently deployed: runs `32777471683` and `32777471718` produced Target `2.1.262+main.gdb37bc2` and production-signed Android `1.0.0-gdb37bc2` (`versionCode=19001`). The APK was replacement-installed on SM-F966N with its data and AndroidKeyStore credential preserved. One foreground action-1 request connected, discovered services, enabled Hello/Challenge/Result indications, exchanged framed messages, disconnected cleanly and completed with health `HEALTHY`, no failure or Target denial, and 4,599 ms latency. HA independently observed `AUTH_PENDING` at 06:27:33, `ARMED` at 06:27:36 and `IDLE` at 06:28:35; no Target reset recurred.

This establishes same-signature installation, native ownership and one historical foreground authenticated action-1 proof/result through Target FSM ARM. Issue #133 later split the manual button into action 2 and bound success to actual Target transition; issue #134 changed pocket dispatch. The current `1.0.0-ga9b6822` / 19801 APK from run `32872303799` is NAS-published but was not installed because no phone was connected. Therefore the historical action-1 success does not establish current action-2 relay opening, screen-off/pocket repetition, Activity/process-killed or reboot registration behavior, OEM battery-policy survival, latency percentile, relay, sensor, health-valid or bootloader rollback. Personal enablement does not retire the legacy rollback path, and issue/Epic closure remains blocked by the remaining applicable G0-HW, RELAY-G0 through G2, OTA-G1 through G4, and issue #14/#23 device/operator evidence.

## 9. Issue #134 fast pocket-approach dispatch

Enabling the personal native GATT control now immediately attempts the exact OS
`PendingIntent` wake registration, while disabling it stops that registration.
The health projection reports the live permission/Bluetooth registration status
and exposes `handsFreeReady`; local manual action 2 remains usable when enrolled
even if wake registration is blocked, but the UI must not call that state
hands-free ready.

On Android 12+, the first WorkManager request for one exact presence is expedited with
`RUN_AS_NON_EXPEDITED_WORK_REQUEST` as the quota fallback. Delayed retries keep
their requested delay and are not expedited. Android 8 through 11 retain the
non-expedited request rather than introducing a new foreground-service contract.
A wake older than 45 seconds is
terminally recorded as `PRESENCE_EXPIRED` and discarded before acquiring the
BLE owner or signing a proof, preventing a stale approach from arming the door
later. Successful action-1 Result is already bound to the Target's real
`AUTH_PENDING -> ARMED` transition, so the ledger records both
`presenceToDispatchMs` and `presenceToArmedMs`; session-only GATT latency remains
a separate field.

These bounds improve Android-side dispatch and make latency measurable. They do
not guarantee OS radio discovery time or Samsung background scheduling. A phone
was not connected for this change, and AJ-SR04T/GPIO3 were not wired, so pocket,
screen-off, sensor and physical relay timing remain field gates.

## 10. Final-main 493 screen-off observations

The installed Samsung APK remains production-signed
`1.0.0-g848bbf1` / 20201; final main 493 changed Target durable storage and
trusted policy, not this Android runtime. After exact 493 recovered on the
Target, three true screen-off first-match callbacks arrived at RSSI -50/-52
with `screen_interactive=false`. Each expedited native worker connected to the
Target, discovered the Hardwareless service, enabled Hello/Challenge/Result
indications, wrote the framed request/proof chunks and closed cleanly in about
4.6--5.8 seconds. Target serial independently recorded all accepted GATT
connections. The third trial held the Target in its ROM bootloader before a
hard reset and did not write flash; the worker completed before the later
periodic OTA check started, excluding the earlier OTA-busy collision hypothesis.

No attempt produced Target action-1 `AUTH_PENDING -> ARMED`. Unlike the
earlier 848 trial, none was accompanied by `ledger_b`, `slot_0`, ACL or
replay storage failure. WorkManager `SUCCESS`, Android ATT write success and a
Target connection are transport evidence only; they do not establish an
authenticated terminal Result or FSM ARM. Issue #156 owns this distinct mobile
terminal-result defect; the durable worker reason/Target reason must still be
read after one user unlock before selecting the smallest corrective layer.
Issue #149 is closed because its durable-storage acceptance is complete.
AJ-SR04T threshold and physical relay/contact evidence remain pending.

The same third trial exposed a separate Flutter ownership-recovery defect:
while native GATT held the BLE lease, `BLE_OWNER_EXCLUDED` caused immediate
ranging subscription recreation and a high-volume error loop. Issue #158 owns
the bounded cancel-before-retry correction. That defect is connected evidence,
but it is not assumed to be the Target denial cause tracked by issue #156.

## 11. Exact-main 281 screen-off repetition boundary

The connected phone still runs production-signed `1.0.0-g1e3dfcf` / 21001 and
preserves its AndroidKeyStore enrollment. After the Target reached exact CI
`2.1.281+main.g082e431`, the phone was placed behind the secure keyguard with
the display `Dozing`. A signed HA reboot created a fresh beacon. Android logged
one OS first-match callback at RSSI -53 with `screen_interactive=false`, then
connected to the Target, discovered the service and enabled the
Hello/Challenge/Result indications.

That worker returned `FAILURE` after about 3.4 seconds; Target serial recorded
the accepted GATT connection but no action-1 `AUTH_PENDING -> ARMED`. This is a
failed current repetition, even though one earlier 493 attempt with the same
APK reached terminal `ARMED`. The phone's secure PIN keyguard prevents reading
the redacted native health screen or exercising the current main manual-open
button until the user unlocks it. No failure reason is guessed from ATT setup
alone. AJ-SR04T threshold, GPIO3 contact timing and actual door motion remain
separate physical Gates.
