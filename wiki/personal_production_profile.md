# Personal production profile

> Status: the reviewed personal-only Target and Android enablement paths are implemented and software-tested; exact-main CI publication, same-signature phone install, NAS activation, Target install/reboot/health and physical GATT/relay evidence remain pending.

This profile is for one repository owner, one primary phone, and the ESP32-C6 Target already installed at the owner's entrance. It does not authorize a commercial deployment and does not weaken the commercial `production` workflow.

## What is relaxed

- The installed phone and Target are also the canary devices.
- The repository owner may be operator, reviewer, and risk owner.
- No multi-OEM matrix, independent reviewer, 100-trial campaign, or 24-hour commercial soak is required.
- Screen-off and Activity-terminated access are reduced to three observed passes each.
- Target reboot and network reconnect are reduced to one observed pass each.
- Ordinary firmware, Android and Backend runtime changes use one component PR;
  whole-bundle policy rotation is limited to privilege-bearing workflow,
  signing/publisher dependency and NAS deployment inputs.
- Main-push publication is component-scoped. Policy, wiki, test-only and
  unrelated-component changes do not create new Target or Android artifacts.
- The reviewed persistent-baseline source may remain the authorization anchor
  for same-byte descendants; no immediate post-feature policy rotation is
  required in this personal lane.

## What remains mandatory

- Build and deploy only an exact `main` commit.
- Verify the signed manifest and exact artifact digest.
- Keep the currently validated legacy BLE/API/MQTT access path recoverable as the rollback path; native GATT and legacy BLE ownership must never run concurrently.
- Use `esp32c6_personal_production` only for this installed personal Target. It sets `SGK_PRODUCTION_BUILD=1`, `SGK_PERSONAL_INSTALLATION_BUILD=1`, and `ENABLE_HARDWARELESS_RC=1`; the default developer profile and commercial `esp32c6_production` profile remain compile-OFF.
- Provision an exact nonzero/non-`ff` 16-byte Hardwareless door ID, a valid P-256 ACL signer public key, and a nonzero ACL signing key ID. Placeholder or malformed values must fail before CI build and fail closed again on Target initialization.
- Require the app-selected AndroidKeyStore public credential to be present in a signed ACL applied by the exact Target before native ownership is enabled. MQTT PUBACK or ACL artifact generation alone is not Target apply evidence.
- Confirm relay OFF safety during Target boot.
- Confirm the previous Target version remains recoverable.
- After deployment, record expected version, boot ID, and health.
- Protected workflow/signing/deployment changes still pass the inert-byte
  trusted policy check before merge.

## Procedure

1. Copy `ota/personal-release-evidence.template.json` to a private working evidence file. Do not add secrets.
2. Perform the listed checks on the owner's phone and installed Target, recording only observed pass counts.
3. Set each safeguard to `true` only after confirming it.
4. Add the owner identity and timezone-qualified approval timestamp.
5. Set `release_blocked` to `false` only when every entry is complete.
6. Run `python scripts/personal_production_gate.py --evidence <private-evidence.json>`.

The reduced screen-off, Activity-terminated, Target reboot, network reconnect, relay boot fail-safe and previous-version recovery checks were owner-attested on 2026-08-12. They do not satisfy the remaining exact-main artifact identity and post-deploy health requirements.

The validator passing is readiness evidence for the reduced personal profile. It is not commercial release evidence and does not alter `ota/release-evidence.json`.

## Personal Hardwareless enablement boundary

The personal Target profile requests Hardwareless GATT at runtime only after its door identity and ACL signer provisioning validate. On the first transition from a compile-OFF image it writes the runtime enable request and then a one-time migration marker. After that marker exists, a persisted `hwless_rc=false` is an authoritative local kill switch and is not overwritten by reboot or rebuild. Returning to a compile-OFF image clears the migration epoch and forces the transport OFF.

Only the exact-main personal Android build permits an explicit local bootstrap: the Gradle manifest placeholder defaults OFF and is enabled by `SGK_PERSONAL_GATT_BOOTSTRAP=1` only in the personal OTA producer. Installation alone still does not turn native ownership on. The operator's first local-open attempt or explicit ON action creates or loads one non-exportable AndroidKeyStore P-256 credential, sends only its 16-byte credential ID and SEC1 public key over authenticated HTTPS to `POST /api/v1/acl/personal/enroll`, and waits for the backend to confirm the exact signed ACL version was applied by the configured Target. Only then is encrypted, credential-bound local consent committed and the native worker allowed to own BLE. A signed remote rollout snapshot, when present, retains precedence. Disabling local GATT, selecting legacy pre-arm, or using the kill switch returns ownership to the legacy path.

This narrow enablement does not close Samsung screen-off/process-death, ESP32-C6 radio interoperability, ACL lease renewal across reboot/outage, relay electrical, or OTA rollback Gates. Those are physical and operational evidence, not consequences of a successful build.

## Automatic exact-main Target OTA lane

Both the main-push personal Target compiler/publisher in `deploy.yml` and the manual personal-installation workflow build `esp32c6_personal_production`. Before materializing `include/secrets.h`, they require and validate `SECRET_HARDWARELESS_DOOR_ID_HEX`, `SECRET_ACL_SIGNER_PUBLIC_KEY_HEX`, and `SECRET_ACL_SIGNING_KEY_ID` alongside the existing per-Target command, MQTTS, recovery and OTA inputs. The N16 16 MB dual-slot layout, 80% slot ceiling, deterministic rebuild comparison, encrypted handoff/content envelope, signed manifest, immutable NAS candidate and previous-version preservation remain unchanged.

The current source tree built both personal and commercial profiles successfully. The personal image was 1,844,880 bytes in each 7,340,032-byte OTA slot (25.13%, 5,495,152 bytes headroom); Hardwareless tests passed 9/9, personal workflow tests 6/6, physical profile tests 5/5, Target auto-publish tests 18/18, and the OTA gate passed 78/78. These are source/build results only: no new NAS pointer, inactive-slot install, reboot health-valid mark, rollback, or physical GATT session is claimed by this page.

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
with exact-main artifacts. The APK now contains the personal local-bootstrap
policy and enrollment client described above, but publication is not
installation or enrollment evidence. The explicit `release_to_production` job,
`production` Environment approval, `ota/release-evidence.json`, commercial
OTA-G1..G4 decisions, and commercial/default Target Hardwareless compile-OFF
policy remain unchanged.
