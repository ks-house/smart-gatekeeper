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

The automatic Target version and build identity are deterministic along
protected main: `2.1.<first-parent-count>+main.g<short-sha>` and
`main-<first-parent-count>-<full-sha>`. Firmware and manifest are
created with pinned PlatformIO/pioarduino inputs and a commit-derived
`SOURCE_DATE_EPOCH`; two clean builds must be byte-identical before signing.
The exact generated version must also be present in the firmware bytes before
the manifest can be signed.
The protected OTA contract binds the normalized full `platformio.ini` bytes, so
a pull request cannot silently swap the platform, library, flags or production
environment while retaining a green auto-publication job.
All Actions artifacts include `github.run_attempt`, so rerunning the original
workflow can safely retry publication without colliding with immutable
`upload-artifact@v4` names. An exact-main manual dispatch with the default
`release_target=canary` also enters the personal publisher; physical-test and
commercial dispatch choices remain separate and cannot enter it.
They are uploaded under immutable commit filenames, read back byte-for-byte, and only
then is `version.json` replaced with the SFTP server's OpenSSH `posix-rename`
extension. A server without atomic replacement support fails while the previous
pointer and immutable artifacts remain available. `NAS_KNOWN_HOSTS` is required
for both automatic password-authenticated publishers; an absent or changed NAS
trust anchor fails before credentials are sent. After SFTP promotion, the Target
lane requires the configured HTTPS `version.json` and immutable firmware URL to
return the exact signed bytes through the same provisioned Target root CA, so a
wrong TLS chain, HTTPS downgrade, reverse-proxy/path error or 404 cannot pass CI.
If a commercial `2.2.0` or newer line is deployed, the automatic major/minor
base must be explicitly advanced before the next personal publish. Until then,
the publisher treats the signed newer NAS pointer as stale-run protection and
fails closed instead of silently overwriting it.
Only a genuinely missing `version.json` may bootstrap automatically. If metadata
exists but its schema or signature cannot be verified with the current Target
key, publication fails closed and requires an explicit migration decision.

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
