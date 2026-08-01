# Smart Gatekeeper observability contract

This directory contains the executable Wave 0 contract for GitHub issue #15.

- `event_schema_v1.json`: JSON Schema 2020-12 envelope for access and update events.
- `event_codes_v1.json`: authoritative event/reason compatibility catalog.
- `event_parser.py`: dependency-free validation, deduplication, partial ordering, and I7/I9 acceptance checks.
- `fixtures/access_success_v1.jsonl`: scan wake through relay OFF in one access session.
- `fixtures/target_ota_success_v1.jsonl`: install, reboot, health, and valid-mark correlation across Target boots.
- `tests/test_event_parser.py`: positive, privacy, replay, offline-ordering, reset, and OTA completion tests.

Run the reference checks from the repository root:

```powershell
python observability/event_parser.py validate observability/fixtures/access_success_v1.jsonl observability/fixtures/target_ota_success_v1.jsonl
python observability/event_parser.py evaluate observability/fixtures/access_success_v1.jsonl observability/fixtures/target_ota_success_v1.jsonl
python -m unittest discover -s observability/tests -v
```

The parser deliberately produces only a partial causal order. It never treats upload or
collector arrival time as event time, and it never invents a cross-device order when clocks
are unsynchronised and no `causation_event_id` exists.

The normative lifecycle, privacy, migration, and acceptance rules are documented in
[`wiki/observability_event_schema.md`](../wiki/observability_event_schema.md).
