# NAS physical-test delivery

> Status: **repository implementation only**. No workflow was dispatched and no NAS byte was written by this change.

## Purpose and evidence boundary

`physical-test-canary` is a manual `workflow_dispatch` lane on exact `main` for
placing the firmware public canary and Android debug APK where an operator can
download them for real-device testing. It is deliberately separate from the
production release job, production directories, production signing keys and
OTA-G1 through OTA-G4 evidence.

Successful CI means only that the exact-run artifact was test-signed, staged in
an isolated NAS directory, downloaded again, byte-compared, and verified against
its manifest. The emitted evidence always records
`physical_validation_status: pending`, `production_authorized: false`, and
`release_evidence: false`. It does not prove installation, boot, BLE/radio,
relay/ToF behavior, update health, rollback, Samsung/OEM behavior or operator
acceptance.

## Public canary tier available after merge

The repository owner must explicitly dispatch each workflow from `main` with
`release_target=physical-test-canary`. A branch dispatch can build a public
canary but cannot contact NAS secrets because the NAS job also requires
`github.ref == 'refs/heads/main'`.

| Workflow | Payload | Isolated remote root |
|---|---|---|
| `.github/workflows/deploy.yml` | `gatekeeper-firmware.bin`, test-signed `version.json`, sanitized `evidence.json` | `/docker/smart-gatekeeper-physical-test/firmware-public-canary/<SHA>/run-<RUN_ID>-<ATTEMPT>` |
| `.github/workflows/build_app.yml` | `ks-house-gatekeeper.apk` debug APK, test-signed `version.json`, sanitized `evidence.json` | `/docker/smart-gatekeeper-physical-test/mobile-public-canary/<SHA>/run-<RUN_ID>-<ATTEMPT>` |

Both jobs consume only the `actions/upload-artifact` object produced in the same
workflow run. They verify the exact 40-character source SHA before network
contact, upload first to a unique `.staging-*` directory, read the artifact and
manifest back, repeat cryptographic and package/firmware identity checks, upload
the sanitized evidence, read that evidence back, and only then atomically rename
the staging directory to its final run directory. Existing production roots
`/docker/smart-gatekeeper-ota/` and
`/docker/smartbox_ota/gatekeeper_apk/` are never selected by this lane.

Required repository secrets are `NAS_HOST`, `NAS_USER`, `NAS_PASSWORD`,
`NAS_PORT` (port defaults to 22), and `NAS_KNOWN_HOSTS`. The latter must contain
the independently verified OpenSSH known-hosts record for the configured NAS;
the job parses it with `ssh-keygen` before any credentialed connection and uses
`StrictHostKeyChecking=yes`. Missing or malformed host-key material fails before
network contact. Runtime `ssh-keyscan`, TOFU, `accept-new`, and disabled strict
checking are forbidden. Sanitized evidence records only
`repository-secret-pinned`, never the host-key value.

Before constructing any OpenSSH destination or remote path, the job also
restricts `NAS_USER` to a non-option portable account name, `NAS_HOST` to a
hostname/IPv4-compatible value that cannot begin with an option marker, and
`NAS_PORT` to the numeric range 1 through 65535. The exact 40-character commit
SHA and positive numeric run ID/attempt are validated before they are used as
path components. IPv6 literals are intentionally unsupported by this lane.

The public artifacts intentionally contain the fixed RFC 8032 test signing key
and `.invalid` updater URLs. The firmware uses compile-only example runtime
secrets and the APK is debug-signed. They are suitable for installation/UI,
local hardware and packaging checks, not a connected or release-signed end-to-end
test.

## Connected/release-signed tier remains fail-closed

`release_target=physical-test-connected` is a visible prerequisite contract,
not a deployment implementation. It runs only on exact `main`, requires the
`physical-test` GitHub Environment, checks the following separate secrets, and
then exits non-zero even when all are present. This prevents accidental use of
production secrets while a connected test implementation is still awaiting its
own security review.

Firmware contract:

- `PHYSICAL_TEST_ROOT_CA_CERT`, `PHYSICAL_TEST_WIFI_SSID`, `PHYSICAL_TEST_WIFI_PASSWORD`
- `PHYSICAL_TEST_API_URL`, `PHYSICAL_TEST_API_KEY`
- `PHYSICAL_TEST_MQTT_HOST`, `PHYSICAL_TEST_MQTT_PORT`, `PHYSICAL_TEST_MQTT_USER`, `PHYSICAL_TEST_MQTT_PASSWORD`
- `PHYSICAL_TEST_TARGET_TENANT_ID`, `PHYSICAL_TEST_TARGET_DOOR_ID`
- `PHYSICAL_TEST_COMMAND_SIGNER_PUBLIC_KEY_HEX`, `PHYSICAL_TEST_COMMAND_SIGNING_KEY_ID`
- `PHYSICAL_TEST_ACL_SIGNER_PUBLIC_KEY_HEX`, `PHYSICAL_TEST_ACL_SIGNING_KEY_ID`
- `PHYSICAL_TEST_OTA_VERSION_URL`, `PHYSICAL_TEST_OTA_FIRMWARE_URL`
- `PHYSICAL_TEST_OTA_SIGNING_PRIVATE_KEY_HEX`, `PHYSICAL_TEST_OTA_SIGNING_PUBLIC_KEY_HEX`, `PHYSICAL_TEST_OTA_SIGNING_KEY_ID`
- `PHYSICAL_TEST_LOCAL_RECOVERY_AP_PASSWORD`, `PHYSICAL_TEST_LOCAL_RECOVERY_USER`, `PHYSICAL_TEST_LOCAL_RECOVERY_PASSWORD`

Mobile contract:

- `PHYSICAL_TEST_ANDROID_KEYSTORE_BASE64`, `PHYSICAL_TEST_ANDROID_KEYSTORE_PASSWORD`, `PHYSICAL_TEST_ANDROID_KEY_ALIAS`
- `PHYSICAL_TEST_UPDATE_SIGNING_PRIVATE_KEY_HEX`, `PHYSICAL_TEST_UPDATE_SIGNING_PUBLIC_KEY_HEX`, `PHYSICAL_TEST_UPDATE_SIGNING_KEY_ID`
- `PHYSICAL_TEST_APK_VERSION_URL`, `PHYSICAL_TEST_APK_DOWNLOAD_URL`, `PHYSICAL_TEST_APK_FALLBACK_DOWNLOAD_URL`, `PHYSICAL_TEST_APK_RELEASE_NOTES_URL`
- `PHYSICAL_TEST_API_KEY`

At the 2026-08-09 audit, none of the `PHYSICAL_TEST_*` names or
`NAS_KNOWN_HOSTS` existed in repository secrets. Consequently even the public
canary dispatch remains blocked until the operator registers an independently
verified NAS host record. Do not copy a production value
into these names. Provision test-scoped endpoints, identities and signing keys,
then implement/review the connected jobs as another protected workflow bundle.

## Operator handoff after a successful public dispatch

1. Confirm the workflow conclusion is `success` and its checked-out SHA equals
   the intended merged `main` SHA.
2. Download the Actions evidence artifact. Confirm its `remote_path`,
   `source_commit`, artifact/manifest SHA-256 values and host-key mode.
3. On NAS, select only the exact `remote_path` from that evidence. Recalculate
   both SHA-256 values before copying to the test device.
4. Install the debug APK manually and flash the public firmware using the
   documented lab procedure. Do not point an enrolled production device at these
   `.invalid` manifests.
5. Execute `wiki/physical_gate_preparation.md` and the user/installer manuals.
   Record actual install, boot, BLE/GATT, sensor, relay, update, failure and
   rollback observations against the exact SHA and artifact digests.
6. A failed install or hardware test leaves the NAS delivery evidence valid as a
   transport result but keeps the physical gate failed/pending. Preserve the
   previous bootable firmware slot and installed APK for rollback.

Production jobs, their conditions, Environment, signing inputs, release evidence
gate and target directories are unchanged. A NAS physical-test upload is not a
production deployment and never closes production authorization.
