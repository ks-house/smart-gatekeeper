# Issue #54 physical-gate preparation

This directory is a deterministic preparation package for Issue #54. It does
not contain measurements, acceptance, operator approval, production contact,
deployment authorization, or a release decision. The committed evidence file
is intentionally an all-`not_run` template.

## Contents

- `issue54_gate_plan.json` is the canonical fixed gate matrix and minimum trial
  counts. It covers the Samsung/OEM 100-run wake campaign, ESP32-C6
  coexistence, GPIO3 relay, AJ-SR04T, `RELAY-G0` through `RELAY-G2`,
  `OTA-G1` through `OTA-G4`, operator drills, and the canary stop/rollback
  drill.
- `schemas/issue54_evidence.schema.json` is the portable JSON Schema for an
  evidence record. The companion validator supplies the cross-field checks
  that JSON Schema alone cannot express.
- `evidence-template.json` is the only record committed for this task. It has
  zero trials, no candidate/artifact identities, no raw evidence, and no
  approvals.
- `fixtures/forged-pass-without-evidence.json` is a synthetic negative fixture
  that must be rejected. It is not a result.
- `checklists.md` defines the field sequence, evidence capture, stop rules,
  and authority boundaries.

## Hardwareless validation

Run the following from the repository root:

```powershell
python scripts/validate_physical_gate_prep.py --require-pending
python scripts/validate_physical_gate_prep.py --self-test
python -m unittest tests/test_physical_gate_prep.py
```

The first command makes this branch fail closed if any committed record claims
completion. The self-test proves that a 100/100 `passed` Samsung record without
raw evidence is rejected. These are L0 checks only; they cannot establish L2
physical, L3 operator, or L4 production evidence.

## Recording a later campaign

Create a separate evidence bundle outside this planning commit, bind it to the
exact candidate Git SHA and both artifact SHA-256 values, and preserve the raw
captures named by each gate. Validate it without `--require-pending`; a passed
record still requires all minimum trials, zero failed trials, raw-evidence
references, and the required operator/risk-owner approval. A validator pass is
format/consistency evidence only: the designated reviewer must inspect the raw
device, operator, and canary records before any gate or deployment decision.

The `raw_evidence` values are references to externally retained captures; do
not put field captures into this repository's immutable `raw/` directory.
