# OTA contract assets

This directory is the machine-readable companion to
`wiki/ota_reliability_contract.md`.

- `schemas/`: Target and Android manifest JSON Schemas.
- `test-vectors/`: deterministic Ed25519 positive and tampered vectors. The
  private key is the public RFC 8032 test key seed and is never a production
  trust root.
- `state-machines.json`: required state names and failure-preservation rules.
- `recovery-matrix.json`: required fallback behavior per injected failure.
- `fault-injection-plan.json`: automated and physical test inventory.
- `release-evidence.json`: current Gate status. Pending evidence deliberately
  blocks production distribution.

Validate contract-only assets:

```bash
python -m pip install -r ota/requirements.txt
python scripts/ota_contract_gate.py contract
python -m unittest discover -s tests -p 'test_*.py' -v
```

Enforce a production decision:

```bash
python scripts/ota_contract_gate.py release \
  --evidence ota/release-evidence.json \
  --manifest dist/version.json \
  --public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"
```

The release command must fail until OTA-G0 through OTA-G4, physical tests, and
operator approval are recorded as passed and every release manifest verifies
under the pinned production public key. A green contract check proves only
the contract artifacts and negative signature vectors; it does not prove an
ESP32 bootloader rollback or an Android install.

## Signature serialization

Manifest v1 uses `sgk-json-v1`: remove only the top-level `signature` field,
reject nested values and floating-point numbers, serialize UTF-8 JSON with keys
sorted by Unicode code point, no insignificant whitespace, and no ASCII
escaping, then sign those bytes with Ed25519. Production public keys are pinned
in the consumers by `signing_key_id`; the test key in the validator is not
accepted by production code.
