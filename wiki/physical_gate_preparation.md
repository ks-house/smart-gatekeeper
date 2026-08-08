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

## 2. Deterministic gate matrix

The canonical [Issue #54 plan](../physical_validation/issue54_gate_plan.json)
fixes the gate IDs, scenario matrices, minimum trial counts, required capture
categories, and pass conditions:

| Group | Planned Gate |
|---|---|
| Samsung/OEM mobile wake | `SAMSUNG-WAKE-100`: five fixed 20-trial scenarios, totaling 100 eligible trials |
| Target physical behavior | `ESP32-C6-COEXISTENCE-100`, `GPIO3-RELAY-100`, `AJ-SR04T-BOUNDARY-100` |
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
adds cross-field rules that prevent a completion claim without all required
trials, zero failed trials, raw-evidence references, and the required
operator/risk-owner approval.

```powershell
python scripts/validate_physical_gate_prep.py --require-pending
python scripts/validate_physical_gate_prep.py --self-test
python -m unittest tests/test_physical_gate_prep.py
```

`--require-pending` is required for this preparation branch and rejects any
claimed completion. The self-test rejects the synthetic
[`forged-pass-without-evidence.json`](../physical_validation/fixtures/forged-pass-without-evidence.json)
fixture. These commands do not validate a physical measurement.

## 4. Field execution and stop rules

The detailed [field checklists](../physical_validation/checklists.md) preserve
the required evidence split and reference the existing [Android wake ADR](android_ble_wake_adr.md),
[relay security contract](security_protocol.md), [OTA contract](ota_reliability_contract.md),
and [OTA operations runbook](ota_operations_runbook.md). The operator must
capture raw ledgers/logs/waveforms/boot records in the later evidence bundle,
stop on unsafe relay/rail/reset/radio observations, and leave the relevant gate
incomplete when capture or prerequisite access is missing.

`raw_evidence` means an external immutable-capture reference, not a file to add
under this repository's immutable `raw/` source directory.

No result may be promoted from this package to `hardware_test.md` as PASS until
the raw L2 evidence is independently reviewed. L3 operator and L4 canary
records remain separate; the plan explicitly does not authorize a production
contact, canary start, deployment, or production approval.
