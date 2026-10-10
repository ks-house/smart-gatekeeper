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


## 2026-10-10 isolated commit/receipt acceptance

A new opt-in integration compiles the actual CanonicalMqttEventSink, MQTT event/sensor serializers, receipt parser, MAC implementation and durable queue implementations. Platform, persistent-byte storage and delivery are host seams; no production secret, broker, GPIO or installed Target is used. Source extraction fails visibly if its anchors move.

The real isolated MariaDB writer is exercised through a pre-commit failure (rollback and no ACK), lost ACK, Backend worker restart, exact replay/deduplication, out-of-order and forged receipts, and local storage-write failure. Six causally linked signed events, one terminal outbox item and one matching signed sensor summary remain in SQL exactly once; verified receipts retire only the exact persisted heads. Sensor SQL rollback/replay and MAC/receipt validation execute directly; this does not exercise the full authenticated MQTT status worker or an actual NVS power failure.

Run from a WSL checkout with the project Python environment, Docker, g++, Backend dependencies and ArduinoJson headers installed:

~~~sh
RUN_MARIADB_INTEGRATION=1 SGK_ARDUINOJSON_INCLUDE=/path/to/ArduinoJson/src /path/to/.venv/bin/python -m unittest backend.tests.test_reliability_diagnostics.ReliabilityMariaDbTest.test_production_sink_to_commit_receipt_after_failure_and_replay -v
~~~

SGK_ARDUINOJSON_INCLUDE can be omitted when headers are present under .pio/libdeps. The test uses an isolated container bound only to loopback and removes it afterward. This opt-in test was run locally; hosted default suites may skip it and do not constitute a hosted MariaDB integration result.

- Related local suite: 51 tests, 1 expected environment skip, no failures. Includes real MariaDB reliability/conflict tests, mobile late-evidence query regression and firmware sink/receipt fixtures. OTA source contract also passes.
- Browser rendering: unchanged deployed Admin HTML with synthetic local responses displays absent, idle, pending, stalled and evidence-gap states, including the unsigned/server-storage/physical-proof boundary. No production Admin login or control action was performed.
- Finite post-install readback: 47 verified health rows, exhausted cursor, same installed boot, latest IDLE/relay OFF and unsigned queue depth/retry/loss/gap zero. The fixed approximately24-minute window has zero access events and an exhausted access cursor. This is an absence of a natural-session validation sample, not proof of physical failure or successful delivery.

Natural same-session packet-to-terminal commit ACK, real Android screen-off/offline/process-death retransmission and independent physical acceptance under #54 remain open. Local late-query and storage reconstruction tests cannot close those field gates. No APK, runtime policy, firmware artifact or production service was changed by this follow-up.
