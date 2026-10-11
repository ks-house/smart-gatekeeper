# Access evidence recovery — issue #426

- Status: PR #427 merged; Backend deployed and Target 514 installed with persisted VALID health on 2026-10-10. Natural access/ACK, retransmission and physical acceptance remain open.
- Tracking: [#426](https://github.com/ks-house/smart-gatekeeper/issues/426).
- Baseline: main 3426298; existing dirty field-recovery checkout is preserved.
- Scope: P0 producer/deferred-queue recovery and visibility. No opening-policy, pin, radio scanning, signed wire ABI, durable journal, or OTA partition change.

## Confirmed code failure and repair

ProtocolCore::abortTransport() could emit a terminal after a rejection reset, or before a session was allocated. Its zero session was permanently rejected by the canonical sink, while the deferred FIFO retained that head forever. This is a reproduced software failure path; it does not alone establish the cause of every historical missing field event.

The core now suppresses sessionless canonical emissions while retaining authentication cleanup. The adapter separately counts transport aborts, including indication failure/timeout, without inventing an access session. Verified actions still survive RESULT transport failure and complete through the independent Target FSM.

DeferredAccessQueue retains the same 16-event bound. A transient downstream failure retains its exact head, source timestamp, credential bytes and FIFO order. The production encoder retains its generated event ID until enqueue succeeds; causal state, phase projection and terminal correlation advance only after acceptance. The host fixture compiles the actual production sink class and verifies byte-identical signed canonical records over failed retries and subsequent acceptance.

Permanently invalid session/sequence/catalog/encoded records enter a four-slot volatile metadata quarantine. Only sequence, quarantine uptime, event code and reason are retained; credential/session identities are not retained there. Aggregate invalid and overflow counters saturate, latch an evidence gap, and permit following valid records to drain. Quarantine overwrite is bounded; it is not a forensic archive or recovery of lost history. No local dequeue fabricates a Backend commit receipt. Controlled restart persistence still fails closed while a gap or pending record exists.

The catalog mapping is extracted unchanged into AccessEventCatalog.h; a matrix of event/reason combinations is checked against the production Backend validator. Unsupported proof rejection reasons remain invalid rather than acquiring new authority.

## Sensor capture policy

Captures still correlate only on the exact terminal monotonic timestamp, never on the next available session. A capture older than five minutes can expire only when the deferred FIFO is empty, so backpressured terminal records retain their matching capture. Expiry is counted separately as capture_orphaned, latches the advisory gap and never becomes a successful terminal or summary. The four-capture/full/drop policy, durable sensor journal and MAC remain unchanged. Capture age is a boot-local uint32 elapsed duration, not wall-clock occurrence time.

## Diagnostics contract

The optional access_evidence object is schema 1 and explicitly unsigned. It is appended after existing signed status, sensor summary and OTA fields only when both ArduinoJson pool and wire capacity permit. Absence means unobserved, including older firmware or insufficient payload space.

| Field | Meaning |
|---|---|
| transport_aborts | Observed adapter transport aborts, independent of canonical session emission |
| deferred_depth | Volatile callback FIFO depth, separate from the MQTT/NVS outbox |
| head_age_ms | Elapsed time since FIFO enqueue, not event occurrence or server receipt |
| head_retries / retry_count | Failed downstream attempts for the current head / boot aggregate |
| invalid_count / overflow_count | Invalid records quarantined / FIFO overflow loss |
| last_failure | NONE, DOWNSTREAM_RETRY, INVALID_EVENT, QUEUE_FULL; last observed failure can remain after recovery |
| stalled | A retained head with at least one failed attempt and age at least15s |
| evidence_gap | Invalid/overflow loss or expired orphan capture was observed in this boot |
| capture_oldest_age_ms / capture_orphaned | Frozen capture age / explicitly expired orphan captures |

Quiet idle with no retained head does not become stalled solely because the last stored audit is old. The existing authenticated health status describes Target availability separately from unsigned evidence-pipeline health. Backend strict projection, persisted health JSON and read API preserve this distinction; Admin diagnostics show queue status, failures and gaps. Existing canonical source monotonic time and API server receipt remain separate; the new head age is not substituted for either.

## Validation and remaining acceptance

Local validation results are recorded in [hardware_test.md](hardware_test.md) and [log.md](log.md). Host execution verifies pre-session abort, rejection then transport loss, disconnect, retained verified action, bounded quarantine/overflow, FIFO duplicate/reorder preservation, transient signed-record identity, terminal-to-capture matching, orphan expiry and real ArduinoJson admission. Backend tests cover catalog compatibility, strict unsigned redaction, health-history roundtrip and the existing DB-commit-only receipt behavior.

This change does not reconstruct lost historical events. Remaining issue #426 work includes natural access evidence through actual DB commit ACK, offline/screen-off/process-death retransmission acceptance, and physical sensor/door proof under #54. P1 physical diagnosis and P2 latency optimization remain separate. Do not close #426 based only on deployment or idle queue health.

## 2026-10-10 authorized deployment

[PR #427](https://github.com/ks-house/smart-gatekeeper/pull/427) passed its exact-head checks and merged as release bf6100c440af3a1e8f9b8a20d9bb74870fe910d8. The owner explicitly requested deployment. Existing protected workflows and the production approval were used without policy changes.

- [Backend run 38039839789](https://github.com/ks-house/smart-gatekeeper/actions/runs/38039839789): SUCCESS; exact-source NAS deployment and status receipts match, loopback/public readiness pass. Independent public readiness confirms the exact release, all 12 checks and fresh authenticated Target status.
- [Target run 38039839795](https://github.com/ks-house/smart-gatekeeper/actions/runs/38039839795): SUCCESS; personal signed/encrypted publication of 2.1.514+main.gbf6100c, build main-514-bf6100c440af3a1e8f9b8a20d9bb74870fe910d8. Independent HTTPS readback verifies the provisioned Ed25519 key, schema-v2 encryption identity and exact file binding. Encrypted artifact1,937,108 bytes / SHA256 10de4813c27465c8a935a218403b54f6de6edcd3835282c59dc1ca74d7733091; manifest SHA256 c509aee08897240fd1b684cccfb52dd024cc842a88b91f2005817d107a1f8b56. Publisher receipt confirms the previous valid pair is retained. The personal publication receipt explicitly is not commercial production authorization.
- [OTA P0 run 38039839806](https://github.com/ks-house/smart-gatekeeper/actions/runs/38039839806): SUCCESS.
- One non-retained authenticated bridge ota_check request followed fresh matching API/live status: IDLE, relay OFF, no ARM/BLE connection or pending OTA. Broker, Backend and Target acceptance were observed without resending. Target 514 booted, entered persisted stage11/VALID with running_image_valid=true, then independently completed periodic HTTPS stage14/CURRENT with HTTP 200/error 0 on the same boot.
- The deployed read API persists and returns unsigned access_evidence schema 1: depth/head age/retries/invalid/overflow/capture-orphaned all0, stalled=false, evidence_gap=false and last_failure=NONE at idle. These are boot-local observations; empty queues after reboot do not reconstruct or prove delivery of historical lost records.

No mobile source or APK release is included. No door command, extra reboot, threshold change or fault injection on the installed Target was used. Natural new-session commit ACK and offline/screen-off/process-death/physical acceptance remain pending under #426/#54.

Final bounded readback confirms the same new boot at uptime 220s, persisted valid image, CURRENT/HTTP 200/error 0, IDLE/relay OFF and fresh authenticated Backend health. The completed subscribe-only observer saw all6 allowlisted channels, one segment, zero rejected messages and zero history eviction. Observation has stopped; this is not an ongoing monitor or power soak.

## 2026-10-11 collector recovery candidate — issue #430

The reported phone remains approved while its exact Target ACL application is unconfirmed. Live receive/commit collector readiness is unavailable although the database and independent MQTT publisher pass. A bounded subscribe-only observation receives increasing Target status revisions; independent verification against the authentic signed released image's provisioned key validates the live status MAC. This does not establish agreement with the deployed Backend keyring. The last database health snapshot is stale and cannot substitute for current Target state. Mobile proof rejection is a separate observed stage, not proof of a sensor or phone-settings cause.

Reproduction injects a database failure into ACL ACK snapshot lookup. The exception escapes the Paho callback, whose default exception handling rethrows; the lookup is now inside the persistence failure boundary. Application acknowledgement is still recorded only after the exact snapshot ACK is durably stored.

Canonical and authenticated-status workers now survive unexpected persistence exceptions, leave failed writes unacknowledged and mark writer health failed. A subsequent successful write can recover health; status effects still require the current transport generation and an advanced authenticated status. Post-commit projection failure no longer suppresses the committed canonical receipt or stops later events. The Target's retained journal and exact replay remain the recovery source.

The readiness response adds aggregate collector metadata: connection, expected/accepted subscription counts, subscription failure, writer failure/liveness and verified-evidence barriers. It includes no Target IDs, topic names, credentials or payloads. Existing readiness requirements are unchanged.

Local Backend tests pass (351 tests, five expected environment skips), including lookup failure then exact retry, worker failure with no false receipt/freshness, subsequent recovery and projection failure. OTA contract passes. Hosted CI, deployment, runtime collector recovery, natural phone proof and physical access are separate acceptance steps. Track [#430](https://github.com/ks-house/smart-gatekeeper/issues/430); #426/#54 remain open.

### Expired queued ACL retry

A second reproduction advances the clock to the exact expiry of a generated ACL whose MQTT application ACK was not received. Previously, lease refresh replayed the expired signed version indefinitely. Retry now preserves a still-valid envelope byte-for-byte, but conditionally retires an expired generated version and builds a higher signed version from current authoritative grants. A revision/version compare-and-swap preserves a newer revocation job. Failed delivery of the replacement retains its new exact retry identity; lease duration, signature, high-watermark and ACK rules are unchanged.

## 2026-10-11 authorized recovery rollout

[PR #431](https://github.com/ks-house/smart-gatekeeper/pull/431) passed all four final-head checks and merged as 5053a3a32fcd78e216f8c34d8dacacf5f2ebc674. The final local Backend suite has353 tests (five environment skips); hosted security/MariaDB, Flutter/native/APK, OTA P0 and protected-policy checks passed on c790424. The owner authorized the update and deployment; existing release protections remain unchanged.

- [Backend run38147664233](https://github.com/ks-house/smart-gatekeeper/actions/runs/38147664233): SUCCESS; exact-source NAS deployment/status receipts match, loopback/public readiness pass. Independent public API confirms release5053a3a, all12 checks, connected/subscribed/live writers and fresh authenticated status. Same Target boot910/firmware514 remains IDLE/OFF, auth READY, pending audit0 and12 cumulative receipts.
- [Mobile run38147664244](https://github.com/ks-house/smart-gatekeeper/actions/runs/38147664244): SUCCESS; signed personal APK1.0.0-g5053a3a/build46101 is published on both updater origins. Independent strict-HTTPS readback verifies identical signed metadata, Ed25519 signature, APK size/hash, actual Android signature/certificate continuity, package/version/build and embedded exact source. APK55,692,441B / SHA2569044a27751fc046f6529782874785072f45837d55b364ffef88856939faef09c; manifest SHA256576c719cfb1d4d1765858aa160a88be36f739636d9fa51877545003f5df235f3. Publisher receipt matches and retains the previous valid artifact.
- [OTA run38147664247](https://github.com/ks-house/smart-gatekeeper/actions/runs/38147664247): SUCCESS; exact-main contract check.
- Target firmware remains514 on the existing boot; no Target OTA request/restart or door command is included. Phone installation and same-phone proof/physical access remain unverified.

The reporting owner explicitly confirms that status refresh now shows **Smart Key ready** on the existing phone app. This closes the reported home-readiness symptom; it does not establish installation of46101, a fresh same-phone GATT success or physical passage. No connected ADB device was available. Install46101 through Settings → App update; #430 remains open for installation/field acceptance, with #426/#54 tracking independent replay and physical evidence.

The old bf6100c Backend had already recovered collectors and12 natural backlog receipts before5053a3a was deployed. Those receipts are not attributed retroactively to this release or treated as a new successful access session. This release fixes reproduced exception/retry defects; the original field collector failure cause is not conclusively identified.
