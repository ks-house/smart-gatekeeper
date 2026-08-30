# Issue #54 physical gate preparation

> Status: **preparation only; every physical, operator, canary, and production gate remains pending**
>
> Scope: deterministic plans, schemas, checklists, templates, and host-only validation for Issue #54.

## 1. Authority boundary

This page and the linked `physical_validation/` package prepare evidence
collection; they do not record a device measurement, acceptance, risk-owner
approval, production contact, canary, deployment, or release decision. The
committed [evidence template](../physical_validation/evidence-template.json) is
all `not_run` with no candidate or artifact identity. A green validator, unit
test, CI result, uploaded artifact, or worker lifecycle message is L0/L1
evidence only and cannot close L2/L3/L4 gates.

The exact-main NAS handoff in
[`nas_physical_test_delivery.md`](nas_physical_test_delivery.md) may populate a
candidate SHA and artifact digests after a successful manual dispatch. Its
host-key-mode-labelled staging/readback result remains L1 transport evidence: every device
observation in this plan must still be executed and recorded by the operator.

## 2. Deterministic gate matrix

The canonical [Issue #54 plan](../physical_validation/issue54_gate_plan.json)
fixes the gate IDs, scenario matrices, minimum trial counts, required capture
categories, versioned pass-condition IDs, required approval roles, and pass
conditions:

| Group | Planned Gate |
|---|---|
| Samsung/OEM mobile wake | `SAMSUNG-WAKE-100`: five fixed 20-trial scenarios, totaling 100 eligible trials |
| Target physical behavior | `ESP32-C6-COEXISTENCE-100`, `GPIO23-RELAY-100`, `AJ-SR04T-BOUNDARY-100` |
| Hands-free relay security | `RELAY-G0`, `RELAY-G1`, `RELAY-G2` |
| OTA and recovery | `OTA-G1`, `OTA-G2`, `OTA-G3`, `OTA-G4`, including power-cut/recovery evidence |
| Operator and release action | `OPERATOR-DRILLS`, `CANARY-STOP-ROLLBACK` |

The plan is intentionally candidate-neutral. A future executed evidence bundle
must bind the exact candidate Git SHA and both firmware/mobile artifact
SHA-256 values before any trial is counted.

## 3. Evidence format and fail-closed validation

[`issue54_evidence.schema.json`](../physical_validation/schemas/issue54_evidence.schema.json)
defines the portable record structure. The standard-library
[`validate_physical_gate_prep.py`](../scripts/validate_physical_gate_prep.py)
adds cross-field rules that prevent an executed record without offset-bearing
start/end timestamps, a named executor, a different named reviewer/risk owner,
an after-execution role-bound decision, exact pass-condition binding, and
complete structured evidence categories. Each raw entry requires a unique
capture identity, capture time and actor, a SHA-256 digest, and its matching
content-addressed `urn:sha256:` locator.

```powershell
python scripts/validate_physical_gate_prep.py --require-pending
python scripts/validate_physical_gate_prep.py --self-test
python -m unittest tests/test_physical_gate_prep.py
```

`--require-pending` is required for this preparation branch and rejects any
claimed completion. The self-test rejects the synthetic
[`forged-pass-without-evidence.json`](../physical_validation/fixtures/forged-pass-without-evidence.json)
fixture, while unit mutations reject missing times/actors, generic or partial
categories, incomplete capture identity/digest, empty or wrong-role approvals,
self-review, and pass-condition substitution. These commands do not validate a
physical measurement.

## 4. Field execution and stop rules

The detailed [field checklists](../physical_validation/checklists.md) preserve
the required evidence split and reference the existing [Android wake ADR](android_ble_wake_adr.md),
[relay security contract](security_protocol.md), [OTA contract](ota_reliability_contract.md),
and [OTA operations runbook](ota_operations_runbook.md). The operator must
capture raw ledgers/logs/waveforms/boot records in the later evidence bundle,
stop on unsafe relay/rail/reset/radio observations, and leave the relevant gate
incomplete when capture or prerequisite access is missing.

`raw_evidence` means structured metadata for an externally retained immutable
capture, not a file to add under this repository's immutable `raw/` source
directory. An opaque string or a generic evidence category cannot satisfy a
gate's plan-bound category list.

No result may be promoted from this package to `hardware_test.md` as PASS until
the raw L2 evidence is independently reviewed. L3 operator and L4 canary
records remain separate; the plan explicitly does not authorize a production
contact, canary start, deployment, or production approval.

## 5. Wall-first commissioning boundary

The AJ-SR04T and door-side relay wiring can be connected only at the entrance,
so installation may precede their physical trials. This is a **conditional
commissioning installation**, not final concealed-wall acceptance.

Before placing the Target in the wall:

1. Leave a removable service cover or an equivalent non-destructive extraction
   path. Keep Target USB/serial reachable with an external service lead or
   conduit, and keep a separately accessible power-isolation point. Signed OTA
   and rollback reduce service visits but are not the sole recovery mechanism
   until the complete wall-install campaign passes.
2. Route and label sensor, relay-input, dry-contact, ground and power conductors
   separately. Preserve measurement points for GPIO11 ECHO voltage, GPIO23
   relay input and COM/NO/NC contact behavior.
3. Do not connect a 5 V ECHO directly to GPIO11. Install and verify the planned
   divider or level shifter before the first powered sensor trial.
4. Keep the actual lock/door actuator electrically isolated for initial tests.
   First prove sensor distance reporting, GPIO23 active-low ON, High-Z OFF,
   timer cutoff, relay contact behavior and safe power/reset behavior with no
   door load.
5. Measure 2.4 GHz RSSI after the Target is at its real depth and the cover is
   in place. Stop final closure below `-75 dBm`; `-67 dBm` or better remains the
   preferred installation target.

After the mechanical placement, execute the physical sequence in increasing
risk order: boot/relay-OFF and network recovery, raw distance and 19/20 cm
boundary capture, action-1 `ARMED` to sensor-threshold relay command, dry
contact timing, isolated actuator trial, repeated hands-free trials, power/AP/
broker/WAN recovery, and signed OTA install/health/rollback. Stop on direct
5 V ECHO, unexpected relay ON, missed cutoff, reset/brownout, unstable radio or
loss of the service recovery path.

Final wall closure is permitted only after the applicable Issue #54 evidence
and the wall-install connectivity Gates are complete. If the service cover,
USB/serial lead and accessible power isolation cannot be retained, installation
must wait; current OTA and one connected rollback observation do not justify an
irretrievable sealed Target.
