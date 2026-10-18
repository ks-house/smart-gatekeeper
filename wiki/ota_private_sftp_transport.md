# Private OTA publisher transport - issue460

## Current state and rollout boundary

The owner's2026-10-17 instruction defers backup work461. Work now prioritizes
GitHub-to-NAS OTA publication over Tailscale before external SSH is blocked.
The prior SSH firewall candidate remains inactive. Reviewed main79ecb000 now
supports the private route; owner-approved tag/grant/OIDC are installed and
main-only personal-auto-ota selects tailscale:4222 for future publication.
Actual private SFTP authentication and three-directory reads pass in39034675586.
No artifact publication, device command/install or firewall cutover is claimed.

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
concurrency remain. The pinned Tailscale action and client version/hash match the existing Backend
integration; a separate tag:sgk-github-ota is proposed for NAS SFTP TCP4222 only.
The existing Backend tag:sgk-github-deploy and management SSH8822 stay unchanged. An exact selector body, environment
map, conditional join and routing consumers are validated before the legacy
signing/publication contracts are checked; unexpected extensions still fail.

## Read-only operating preflight

The exact-main Backend manual status job keeps its production environment,
management SSH8822 and existing ephemeral Tailscale role. It runs when
verify_ota_sftp=false (the default). A separate exact-main job runs only when
verify_ota_sftp=true, under personal-auto-ota with the publisher account,
separate tag:sgk-github-ota and SFTP4222. It never receives Backend SSH keys.

The new job forces private selection and reuses the exact tested publisher
selector/pinned join. Its batch contains only cd/pwd for Target, primary APK
and fallback APK directories. It cannot upload, download, rename, remove,
publish, deploy or command a device. Raw client diagnostics stay private;
the always-retained receipt contains a start marker and, only after success,
private_sftp_readonly_ok=true. Failures retain only a closed category/exit code.

This preflight proves private authentication/directory traversal, not writer
permission, atomic promotion or device install. Full private publication and
HTTPS readback remain separate gates.

## Activation order

1. Review and separately admit the four changed protected inputs:
   backend_security.yml, build_app.yml, deploy.yml and scripts/ota_contract_gate.py.
   Keep the exact23-path policy inventory and the existing signing/readback gates.
2. Obtain action-time owner approval for the new tag/network grant and OIDC
   identity. Proposed grant: tag:sgk-github-ota -> sgk-nas-deploy TCP4222 only.
   Proposed subject: repo:ks-house/smart-gatekeeper:environment:personal-auto-ota;
   require repository_id1281428181 and ref refs/heads/main. Scope auth_keys only,
   no devices/policy/user administration. Leave the production identity unchanged.
3. Configure personal-auto-ota TS_OIDC_CLIENT_ID/TS_OIDC_AUDIENCE and
   NAS_OTA_TAILNET_HOST/NAS_OTA_TAILNET_PORT4222, then dispatch
   verify_ota_sftp=true on reviewed main. Keep current public publishing/firewall
   state during this read-only authentication and directory test.
4. Set OTA_PUBLISH_TRANSPORT=tailscale only after the private preflight succeeds.
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


## Read-only preflight option-order follow-up

The first actual private job39031524098 passed the existing signed status
connection but failed at SFTP, with no publication or device action.
A real local OpenSSH sftp transport stub plus ssh -G reproduces the option-order
defect: putting -b before -o BatchMode=no forwards batchmodeyes first and
suppresses password prompts. Put the explicit BatchMode=no option before -b.
This is a protocol/client reproduction, not just a fake SFTP success.

Failure now retains only a closed category and exit code in the existing
sanitized status receipt. The raw client text stays private on the runner.
An always-run artifact step retains this receipt even when SFTP fails; failures
never gain a success marker.19 focused selector/preflight/real-client/error
tests and29 Backend/NAS contracts PASS. Live retry remains separate acceptance.


## Actual NAS service and role boundary

The corrected-option live run39032386499 still failed (sanitized exit255) at
management SSH8822. Signed read-only NAS configuration confirms separate
ssh_port8822 and sftpPort4222. The publisher session is non-admin with nologin;
the management account is admin. Do not add administrator membership, grant a
shell, change sshd/PAM, or broaden the existing management tag to solve this.

The current source separates service and role, defaults private publication to
SFTP4222, and restores diagnostics to a private log with sftp -N. The owner approved the exact new tag/grant/OIDC scope on2026-10-17, and they are
now created and independently read back. Production federation is preserved.
The earlier source/CI passes are not proof of private operating publication.
Backup461 remains deferred, and the NAS firewall remains at its restored
original disabled state until private publication and HTTPS readback pass.


## Owner-approved operating connection acceptance

PR467 merged as79ecb000dd5e830f3519f60b6558e08da287b11c after all five required
checks passed; policy468 is also merged. Source-only main39034588220/221 and
39034588301 were cancelled before publisher/deploy steps ran, preventing
redundant versions or service churn.

The saved Tailscale configuration has exactly one new tag:sgk-github-ota and a
grant to the existing NAS host definition on tcp:4222. Existing member and
production deploy8822 rules remain unchanged. New OIDC scope is auth_keys only;
persisted subject is the personal-auto-ota environment with ref refs/heads/main
and repository_id1281428181. No devices:core, policy editing, management shell or
new NAS account/password permission was granted.

GitHub personal-auto-ota retains its main-only branch restriction. Only the two
public OIDC metadata items and private NAS host/port were configured there;
production federation was preserved. Run39034675586 joins using this exact
new identity and completes Target/primary APK/fallback APK cd/pwd successfully.
The downloaded receipt is exactly start=true and readonly_ok=true; no raw
connection logs or credentials enter the retained artifact.

OTA_PUBLISH_TRANSPORT=tailscale is now independently read back, so future
personal releases use SFTP4222 and do not silently fall back to public.
This does not trigger publication by itself. Actual private atomic publication
and HTTPS artifact/readback acceptance are still required before reactivating
the external SSH firewall restriction. Keep460 open; current NAS firewall stays
disabled and existing download/rollback paths remain available. Backup461 is
still owner-deferred; no new dump/copy/restore/schedule was run.


## 2026-10-18 actual private Target publication

[Release39111255559](https://github.com/ks-house/smart-gatekeeper/actions/runs/39111255559)
publishes exact-main3edc4b42 firmware2.1.552+main.g3edc4b4 through the dedicated
private publisher network. The sanitized receipt confirms atomic metadata
swap, retained previous valid artifact and immutable HTTPS readback; encrypted
artifact size is1942500 bytes. Installation is separately verified by new-boot
VALID health. This is personal-lane proof, not commercial production approval.

This closes the Target publication evidence gap only. Mobile private atomic
publication and subsequent external SSH refusal remain pending in460. Keep
the firewall disabled baseline and owner-deferred461 backup unchanged.
