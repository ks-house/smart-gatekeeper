# NAS physical-test delivery

> Status: **public-canary NAS delivery verified** at exact main `85568c18c136ef3c1d104026e033da789867b73e`. Real-device installation and physical validation remain pending.

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

## Latest verified NAS delivery (2026-08-10)

The repository owner dispatched both exact-main `physical-test-canary` workflows
with `allow_unpinned_host_key=true`. Both SFTP-only jobs completed staging,
readback verification, sanitized evidence comparison, and final directory rename.

| Kind | Actions run | Verified NAS path | Artifact SHA-256 | Manifest SHA-256 |
|---|---|---|---|---|
| Firmware public canary | `31323665004` | `/docker/smart-gatekeeper-physical-test/firmware-public-canary/85568c18c136ef3c1d104026e033da789867b73e/run-31323665004-1` | `b76c8e98e569b40b7647db9141fbb84afcfb8bf2d09253893170549b8f7e154a` | `0ee4e933e1d687a1baedbcb3a398698eaaaa0f6e12ae3d5db0593310b5f63314` |
| Mobile debug canary | `31323666311` | `/docker/smart-gatekeeper-physical-test/mobile-public-canary/85568c18c136ef3c1d104026e033da789867b73e/run-31323666311-1` | `8147d4f552df6420aac7d811d2a7d2accd21ce93ee83e3be4ef2efc2b972d3ef` | `4b6d4949fa482a7c8aac27e6212d799837c9284aec076390942bb74d0e123311` |

The downloaded Actions evidence records `nas_upload_verified: true`,
`host_key_mode: runtime-keyscan-unpinned`, `physical_validation_status: pending`,
`production_authorized: false`, and `release_evidence: false` for both artifacts.
This proves NAS transport and readback only. The operator must still recompute the
listed hashes before flashing/installing and then execute the physical checklists.
Because the first host key was discovered at runtime, rotate the NAS password if
the network path was not trusted during these runs.

## Public canary tier available after merge

The repository owner must explicitly dispatch each workflow from `main` with
`release_target=physical-test-canary`. If `NAS_KNOWN_HOSTS` is absent, the owner
must also set `allow_unpinned_host_key=true` on that individual dispatch. A branch dispatch can build a public
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

The physical-test transport is SFTP-only because the restricted NAS account does
not provide an SSH remote shell. It uses four bounded OpenSSH `sftp -b` batches:
artifact upload, artifact readback, evidence upload/readback, and final publish.
The upload batch creates the hierarchy one component at a time. Existing parent
errors are tolerated only for `/docker`, `/docker/smart-gatekeeper-physical-test`,
the fixed canary root and the exact-SHA parent; creation of the unique staging
directory, every `put`/`get`, evidence comparison, and the final atomic SFTP `rename`
remain strict. No `ssh` remote-shell command is issued.

OpenSSH batch mode aborts on a failed strict command, but SFTP servers do not
provide a portable cross-server no-clobber preflight for directory rename. A
pre-existing final run directory is therefore an operator conflict: the direct
rename is expected to fail closed on the supported NAS, and this lane never
deletes or intentionally overwrites it. The SHA/run/attempt path makes such a
collision exceptional; investigate it instead of retrying with destructive
cleanup.

Required repository secrets are `NAS_HOST`, `NAS_USER`, `NAS_PASSWORD`, and
`NAS_PORT` (port defaults to 22). `NAS_KNOWN_HOSTS` is optional. When supplied,
the job parses the independently verified OpenSSH record with `ssh-keygen` and
records `repository-secret-pinned`. When absent, the physical-test lane performs
a bounded runtime `ssh-keyscan`, validates the resulting record, records
`runtime-keyscan-unpinned`, and still connects with `StrictHostKeyChecking=yes`
against that run-local file. This compatibility fallback permits the established
NAS setup to upload without a known-hosts secret, but it does not authenticate
the first key exchange and therefore is weaker against an active network
interceptor. `accept-new` and disabled strict checking remain forbidden. The
sanitized evidence records only the mode, never the host-key value.

The boolean acknowledgement is default-false and does not make the transport
cryptographically authenticated. It only records an explicit owner decision for
this public physical-test upload; use the pinned secret whenever possible and
rotate the NAS password after an unpinned run if the network path was not trusted.

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

At the 2026-08-09 audit, none of the `PHYSICAL_TEST_*` names existed in repository
secrets. The public canary can use the explicitly authorized unpinned keyscan
fallback, while the connected tier remains blocked. Do not copy a production
value into the `PHYSICAL_TEST_*` names. Provision test-scoped endpoints,
identities and signing keys, then implement/review the connected jobs as another
protected workflow bundle.

## Operator handoff after a successful public dispatch

1. Confirm the workflow conclusion is `success` and its checked-out SHA equals
   the intended merged `main` SHA.
2. Download the Actions evidence artifact. Confirm its `remote_path`,
   `source_commit`, artifact/manifest SHA-256 values and host-key mode.
3. Confirm that the exact final run directory did not exist before this run. On
   NAS, select only the exact `remote_path` from that evidence. Recalculate both
   SHA-256 values before copying to the test device. Treat an existing final run
   directory as a conflict; do not delete or overwrite it automatically.
4. Install the debug APK manually and flash the public firmware using the
   documented lab procedure. Do not point an enrolled production device at these
   `.invalid` manifests.
5. Execute `wiki/physical_gate_preparation.md` and the user/installer manuals.
   Record actual install, boot, BLE/GATT, sensor, relay, update, failure and
   rollback observations against the exact SHA and artifact digests.
6. A failed install or hardware test leaves the NAS delivery evidence valid as a
   transport result but keeps the physical gate failed/pending. Preserve the
   previous bootable firmware slot and installed APK for rollback.

The public physical-test jobs, their isolated directories and non-release
evidence semantics remain unchanged. A separate later exact-main personal Target
job may publish production-signed immutable bytes to the configured live OTA
directory after staged readback and an atomic metadata-pointer swap; that path is
documented in [ota_operations_runbook.md](ota_operations_runbook.md). It does not
retroactively promote this public-canary evidence, edit commercial release
evidence or close production authorization. The manual commercial release job
and its fail-closed release-evidence gate remain separate.
