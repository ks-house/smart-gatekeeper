# Private OTA publisher transport - issue460

## Current state and rollout boundary

The owner's2026-10-17 instruction defers backup work461. Work now prioritizes
GitHub-to-NAS OTA publication over Tailscale before external SSH is blocked.
The prior SSH candidate remains inactive; current publication and NAS settings
are unchanged by this source candidate. No device command or install is required.

Personal Target and mobile publishers gain an opt-in transport selector:

- Unset/empty OTA_PUBLISH_TRANSPORT selects the existing public host/port/pins.
- tailscale requires a literal IPv4 in100.64.0.0/10, a valid port, and configured
  TS_OIDC_CLIENT_ID/TS_OIDC_AUDIENCE in personal-auto-ota.
- The private known_hosts record is derived only from the original public
  endpoint's matching pinned server keys. Address/port rebinding preserves the
  cryptographic server identity. No keyscan or new implicit trust is introduced.
- Malformed configuration, missing pin/identity, join or SFTP failure stops the
  job. There is no automatic public fallback after tailscale is selected.
- The same account, directories, signed manifest/artifact checks, atomic rename,
  previous valid pair and HTTPS readback remain. No Target partition, client
  download URL, signing key or native app behavior changes.

Only the two exact-main personal publisher jobs receive contents:read and
id-token:write. Their main-only personal-auto-ota environment and non-cancelling
concurrency remain. The pinned Tailscale action, client version/hash and deploy
tag match the existing Backend integration. An exact selector body, environment
map, conditional join and routing consumers are validated before the legacy
signing/publication contracts are checked; unexpected extensions still fail.

## Read-only operating preflight

The existing exact-main Backend manual status job keeps its production
environment approval and ephemeral Tailscale identity. A new explicit input,
verify_ota_sftp (defaultfalse), optionally checks the existing publisher password
identity over the already pinned private NAS endpoint.

The SFTP batch contains only cd/pwd for the Target and APK directories. It does
not upload, download, rename, remove, publish, deploy or command a device.
Raw client diagnostics remain in a private runner file; the retained receipt
contains only private_sftp_readonly_ok=true after success.

This preflight proves private authentication/directory traversal, not writer
permission, atomic promotion or device install. Full private publication and
HTTPS readback remain separate gates.

## Activation order

1. Review the source and separately admit the five changed protected inputs:
   backend_security.yml, build_app.yml, deploy.yml, ota_contract.yml and
   scripts/ota_contract_gate.py. Keep the exact23-path policy inventory.
2. On tested main, dispatch Backend security and MariaDB with
   verify_ota_sftp=true; approve only the normal existing protected environment
   job. Keep public publishing and the current firewall state during this test.
3. Confirm the existing Tailscale workload identity can authenticate the
   personal-auto-ota subject for this exact repository/deploy tag. If it does
   not already permit that subject, obtain explicit owner authorization for the
   narrow identity addition. Do not weaken production approval or mint a broad
   persistent credential.
4. Configure the personal-auto-ota TS_OIDC_CLIENT_ID/TS_OIDC_AUDIENCE and
   NAS_OTA_TAILNET_HOST/NAS_OTA_TAILNET_PORT. Set OTA_PUBLISH_TRANSPORT=tailscale
   only after private preflight succeeds and the identity is ready.
5. Verify both actual signed publication/readback paths. Retain public access
   until publication has passed; a successful HTTPS download alone is insufficient.
6. Reapply the reviewed SSH boundary and independently verify management,
   required services, off-LAN refusal and later restart persistence.

Rollback of transport selection is an explicit operator choice of public,
performed before public SSH is blocked. It is never a hidden retry path.
Do not call a CI/source pass a completed network cutover.

## Local validation

-149 focused selector/publication/manifest/OTA tests PASS, including actual
 embedded selector execution, wrong host/pin/port rejection, no-fallback cases,
 conditional pinned join, permissions and mutation rejection.
-29 Backend operations/NAS deployment contracts PASS using the existing private
 Linux Docker CLI/Compose paths for config rendering only; no daemon change.
-OTA contract command PASS. The trusted policy correctly refuses five changed
 protected digests until the separate admission; it is not bypassed.
