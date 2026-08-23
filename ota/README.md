# OTA contract assets

This directory is the machine-readable companion to
`wiki/ota_reliability_contract.md`.

- `schemas/`: Target and Android manifest JSON Schemas.
- `test-vectors/`: deterministic Ed25519 positive and tampered vectors. The
  private key is the public RFC 8032 test key seed and is never a production
  trust root.
- `state-machines.json`: required state names and failure-preservation rules.
- `recovery-matrix.json`: enum-constrained outcomes, actions, and safe state
  transitions for every required failure.
- `fault-injection-plan.json`: exact automated and physical test inventory with
  allowlisted expected outcomes.
- `release-evidence.json`: current Gate status. Pending evidence deliberately
  blocks production distribution.
- `hardwareless-implementation-gates.json`: separates the authorized G0-SW
  Hardwareless RC implementation scope from the still-pending G0-HW production
  scope. It never upgrades synthetic, host, or virtual evidence to physical
  completion.

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
  --artifact dist/gatekeeper-firmware.bin \
  --public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"
```

The release command must fail until OTA-G0 through OTA-G4, physical tests, and
operator approval are recorded as passed and every release manifest verifies
under the pinned production public key. Each repeated `--manifest` is paired by
position with exactly one repeated `--artifact`; the gate reads those artifact
bytes and compares their actual size and SHA-256 with the signed manifest.
Android releases additionally require `--apksigner <path>` (or a discoverable
Android SDK `apksigner`) and must match the signed certificate digest. The same
artifact path passed to the gate must be the file uploaded by the workflow.
A green contract check proves only the contract assets and adversarial negative
vectors; it does not prove an ESP32 bootloader rollback or an Android install.
The repository test suite also validates that G0-SW permits only feature-flagged
implementation/review/merge while G0-HW, legacy retirement, and Epic closure
remain blocked by physical evidence.

An ordinary `main` push still produces a public canary, then the exact
`publish_personal_target_ota` job may use the `production` Environment to build
the single-owner Target profile, create a production-signed manifest and publish
it to the configured NAS OTA directory. This personal-installation publication
is deliberately not `release` authorization: its sanitized evidence keeps
`production_authorized: false` and `release_evidence: false`, and it never edits
`ota/release-evidence.json`.

The automatic Target version is deterministic and increasing along protected
main, `2.1.1-main.<first-parent-count>+g<short-sha>`. Firmware and manifest are
uploaded under immutable commit filenames, read back byte-for-byte, and only
then is `version.json` replaced with the SFTP server's OpenSSH `posix-rename`
extension. A server without atomic replacement support fails while the previous
pointer and immutable artifacts remain available. `NAS_KNOWN_HOSTS` is preferred;
the bounded runtime-keyscan fallback pins only the connection following that
scan and cannot authenticate the first scan.

The commercial `release_to_production` job remains a separate authorized manual
dispatch and still runs the release command above before its deployment. Static
tests reject either lane if exact-main/secret provenance, signed byte binding,
staged readback, atomic metadata swap, release evidence, or explicit commercial
trigger boundaries are weakened.

## Signature serialization

Manifest v1 uses `sgk-json-v1`: remove only the top-level `signature` field,
reject nested values and floating-point numbers, serialize UTF-8 JSON with keys
sorted by Unicode code point, no insignificant whitespace, and no ASCII
escaping, then sign those bytes with Ed25519. Production public keys are pinned
in the consumers by `signing_key_id`; the test key in the validator is not
accepted by production code.
