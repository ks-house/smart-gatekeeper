# Personal production profile

> Status: reduced physical checks owner-attested on 2026-08-12; release remains fail-closed pending exact-main signed artifact deployment and post-deploy version/boot/health evidence.

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

The reduced screen-off, Activity-terminated, Target reboot, network reconnect, relay boot fail-safe and previous-version recovery checks were owner-attested on 2026-08-12. They do not satisfy the remaining exact-main artifact identity and post-deploy health requirements.

The validator passing is readiness evidence for the reduced personal profile. It is not commercial release evidence and does not alter `ota/release-evidence.json`.

## Automatic exact-main mobile OTA lane

For this owner's single installed Android device, `build_app.yml` contains a
separate `publish_personal_mobile_ota` job. Every push to exact `main`, plus an
exact-main manual dispatch whose `release_target` is `canary`, first
passes the public APK build/test job, then builds a release APK with the
repository-scoped mobile signing values. The job intentionally has no GitHub
Environment so the Target OTA values in the `production` Environment cannot
shadow the mobile trust root already embedded in the installed app.

The personal publisher fails before upload unless the mobile Ed25519 key ID and
public-key digest match the installed-app trust anchor, the APK package is
`com.kshouse.gatekeeper_app`, and the Android signing certificate matches the
currently installed package. It signs and verifies `version.json`, stages the
APK and manifest to both primary and fallback NAS directories, reads every
staged object back, preserves immutable candidates and the previous valid pair,
and uses SFTP `posix_rename` to replace APKs before manifests. Runs are
serialized without cancelling an active two-file promotion. The publisher
double-reads each final pair, restores the previous valid pair if APK or manifest
promotion/readback fails, and finally requires both HTTPS update origins to
return the exact bytes. Every rerun receives a bounded higher version code and
attempt-specific retained CI artifact name. A repository-pinned
`NAS_KNOWN_HOSTS` value is mandatory; password-authenticated automatic delivery
never trusts an unauthenticated runtime keyscan.

This automatic lane only keeps the owner's existing mobile updater supplied
with exact-main artifacts. The explicit `release_to_production` job,
`production` Environment approval, `ota/release-evidence.json`, commercial
OTA-G1..G4 decisions, and default-OFF Hardwareless RC policy remain unchanged.
