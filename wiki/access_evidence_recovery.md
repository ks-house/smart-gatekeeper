# Access evidence recovery — issue #426

- Status: implemented candidate; PR review/publication/installation and field acceptance remain open.
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

The optional access_evidence object is schema1 and explicitly unsigned. It is appended after existing signed status, sensor summary and OTA fields only when both ArduinoJson pool and wire capacity permit. Absence means unobserved, including older firmware or insufficient payload space.

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

This candidate does not reconstruct lost historical events. Remaining issue #426 work includes exact-head hosted checks/review, authorized Backend/Target release, installed-image health/rollback checks, natural access evidence through actual DB commit ACK, offline/screen-off/process-death retransmission acceptance, and physical sensor/door proof under #54. P1 physical diagnosis and P2 latency optimization remain separate. Do not close #426 based only on this PR or CI success.
