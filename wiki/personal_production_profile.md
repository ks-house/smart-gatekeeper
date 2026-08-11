# Personal production profile

> Status: configured but fail-closed until the owner records the reduced physical checks.

This profile is for one repository owner, one primary phone, and the ESP32-C6 Target already installed at the owner's entrance. It does not authorize a commercial deployment and does not weaken the commercial `production` workflow.

## What is relaxed

- The installed phone and Target are also the canary devices.
- The repository owner may be operator, reviewer, and risk owner.
- No multi-OEM matrix, independent reviewer, 100-trial campaign, or 24-hour commercial soak is required.
- Screen-off and Activity-terminated access are reduced to three observed passes each.
- Target reboot and network reconnect are reduced to one observed pass each.

## What remains mandatory

- Build and deploy only an exact `main` commit.
- Verify the signed manifest and exact artifact digest.
- Keep the currently validated legacy BLE/API/MQTT access path.
- Keep `ENABLE_HARDWARELESS_RC=0`.
- Confirm relay OFF safety during Target boot.
- Confirm the previous Target version remains recoverable.
- After deployment, record expected version, boot ID, and health.

## Procedure

1. Copy `ota/personal-release-evidence.template.json` to a private working evidence file. Do not add secrets.
2. Perform the listed checks on the owner's phone and installed Target, recording only observed pass counts.
3. Set each safeguard to `true` only after confirming it.
4. Add the owner identity and timezone-qualified approval timestamp.
5. Set `release_blocked` to `false` only when every entry is complete.
6. Run `python scripts/personal_production_gate.py --evidence <private-evidence.json>`.

The validator passing is readiness evidence for the reduced personal profile. It is not commercial release evidence and does not alter `ota/release-evidence.json`.
