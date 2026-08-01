# Smart Gatekeeper observability contract

This directory contains the executable Wave 0 contract for GitHub issue #15.

- `event_schema_v1.json`: JSON Schema 2020-12 envelope for access and update events.
- `event_codes_v1.json`: authoritative event/reason compatibility catalog.
- `event_parser.py`: dependency-free validation, deduplication, partial ordering, and I7/I9 acceptance checks.
- `fixtures/access_success_v1.jsonl`: scan wake through relay OFF in one access session.
- `fixtures/manual_remote_access_success_v1.jsonl`: authenticated app button request through the distinct manual-open Target command and relay OFF.
- `fixtures/target_ota_success_v1.jsonl`: install, reboot, health, and valid-mark correlation across Target boots.
- `fixtures/target_ota_rollback_success_v1.jsonl`: previous-version install, boot, health, and rollback confirmation on a recovery boot.
- `fixtures/negative_*.jsonl`: fail-closed digest, rollback-evidence, reset-correlation, uint64, and causation-cycle cases.
- `tests/test_event_parser.py`: positive, privacy, replay, offline-ordering, reset, uint64, cycle, and OTA completion tests.

Run the reference checks from the repository root:

```powershell
python observability/event_parser.py validate observability/fixtures/access_success_v1.jsonl observability/fixtures/manual_remote_access_success_v1.jsonl observability/fixtures/target_ota_success_v1.jsonl observability/fixtures/target_ota_rollback_success_v1.jsonl
python observability/event_parser.py evaluate observability/fixtures/access_success_v1.jsonl observability/fixtures/manual_remote_access_success_v1.jsonl observability/fixtures/target_ota_success_v1.jsonl observability/fixtures/target_ota_rollback_success_v1.jsonl
python -m unittest discover -s observability/tests -v
```

The parser deliberately produces only a partial causal order. It never treats upload or
collector arrival time as event time, and it never invents a cross-device order when clocks
are unsynchronised and no `causation_event_id` exists.

Within one update session the first non-null artifact digest is immutable. Manifest,
installed-image, boot/health, rollback, and known-digest failure events must retain it.
Rollback completion additionally requires previous-version install, boot, and health
evidence from one Target recovery boot. The negative fixtures are expected to be rejected
by either per-event validation, stream validation, or acceptance evaluation as named.

Epic #13's authenticated mobile-app button path is a separate `manual_remote` access path,
not a hands-free wake/pre-arm session. Its acceptance chain requires explicit button request,
authorization, and Target command-receipt events and rejects hands-free activation events.

The normative lifecycle, privacy, migration, and acceptance rules are documented in
[`wiki/observability_event_schema.md`](../wiki/observability_event_schema.md).
