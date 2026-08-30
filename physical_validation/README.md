# Issue #54 physical-gate preparation

This directory is a deterministic preparation package for Issue #54. It does
not contain measurements, acceptance, operator approval, production contact,
deployment authorization, or a release decision. The committed evidence file
is intentionally an all-`not_run` template.

## Contents

- `issue54_gate_plan.json` is the canonical fixed gate matrix and minimum trial
  counts. It covers the Samsung/OEM 100-run wake campaign, ESP32-C6
  coexistence, GPIO23 relay, AJ-SR04T, `RELAY-G0` through `RELAY-G2`,
  `OTA-G1` through `OTA-G4`, operator drills, and the canary stop/rollback
  drill.
- `schemas/issue54_evidence.schema.json` is the portable JSON Schema for an
  evidence record. Version 2 requires accountable execution windows, actor
  identities, structured content-addressed captures, pass-condition binding,
  and a role-bound independent review. The companion validator supplies the
  cross-field checks that JSON Schema alone cannot express.
- `evidence-template.json` is the only record committed for this task. It has
  zero trials, no candidate/artifact identities, no raw evidence, and no
  approvals.
- `fixtures/forged-pass-without-evidence.json` is a synthetic negative fixture
  that claims a pass with no execution metadata, a generic capture category,
  and an empty approval; it must be rejected and is not a result.
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
completion. The self-test and unit mutations prove that a nominal `passed`
record cannot omit its execution window/actors, substitute generic or partial
capture categories, omit content identity/digests, use an empty or wrong-role
approval, or detach itself from the canonical pass condition. These are L0
checks only; they cannot establish L2 physical, L3 operator, or L4 production
evidence.

## Recording a later campaign

Create a separate evidence bundle outside this planning commit, bind it to the
exact candidate Git SHA and both artifact SHA-256 values, and preserve the raw
captures named by each gate. Every non-`not_run` record must include an
offset-bearing start/end time, a named executor, the gate's exact
`pass_condition_id`, one structured entry for every `required_raw_evidence`
category, and a named reviewer whose identity differs from the executor. Each
capture entry binds its category and capture ID to an in-window capture time,
capturing identity, SHA-256 digest, and matching `urn:sha256:` immutable
locator. The review decision must occur after execution and use the plan's
exact role: `independent_reviewer`, `risk_owner`, `operator_risk_owner`, or
`release_risk_owner` as assigned to that gate.

Validate a later bundle without `--require-pending`; a passed record still
requires all minimum trials, zero failed trials, exact evidence-category
coverage, and an `approved` role-bound review. Failed and aborted executions
remain accountable records and require `rejected` and `incomplete` review
decisions respectively. A validator pass is format/consistency evidence only:
the designated reviewer must inspect the raw device, operator, and canary
records before any gate or deployment decision.

The `raw_evidence` objects describe externally retained, content-addressed
captures; do not put field captures into this repository's immutable `raw/`
source directory.
