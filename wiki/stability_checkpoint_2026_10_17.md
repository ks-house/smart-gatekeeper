# Personal environment stability checkpoint -2026-10-17

Scope: stabilize this owner's installed system before new features. Follow the
[personal profile](personal_production_profile.md); commercial100-cycle/multi-OEM
and24h release gates are separate and are not silently imposed on personal use.

## Live checkpoint

| Component | Observed result |
|---|---|
| Backend |64b5c2f8b8f854441fdda90df63ae1f78e2c0991 readiness passes; restart0 |
| Database |Running, restart0, no published host database port |
| Broker |Named authentication retained; both anonymous listeners disabled; restart0 |
| HA |Same running container/image, HTTP200, verified TLS WebSocket101/auth-required |
| HA observer |Active, failures0, pending alerts0 |
| SmartBox |Prior deployed diagnostic acceptance preserved; no new update/control |
| Target |Latest sampled verified health20:31:19KST, boot911, IDLE |
| Evidence queue |Unsigned advisory deferred0, invalid0, overflow0, stalledfalse/gapfalse |
| Phone sample |Latest received report20:30:37KST still reports build45701 |
| Gmail |Direct NAS test reached owner INBOX19:52:22KST; owner screenshot confirms |
| GitHub |Initial audit: Gatekeeper9 open issues, SmartBox0; both repos0 open PRs |

Health receipt time, unsigned firmware/queue advisory and physical observations
remain different evidence. The phone report is one reported app snapshot, not an
inventory of every family phone. Installed46101 remains unconfirmed.

## NAS SSH candidate verified, then restored for OTA preservation

Track [460](https://github.com/ks-house/smart-gatekeeper/issues/460).
Before: SSH listens on4222/8822 and DSM firewall is disabled. The public-name4222
banner was reachable from the management PC, but same-LAN NAT hairpin is possible.
Existing failed external-login alerts motivated narrowing management access.

During a bounded candidate test, after root-private export/backup and a300s connection-preservation watchdog,
DSM profile rules preserve the two existing disabled rules and add, in order:

1. Allow TCP4222/8822 from Tailscale IPv4100.64.0.0/10.
2. Preserve existing LAN access from192.168.0.0/16, covering both measured NAS LANs.
3. Drop TCP4222/8822 from remaining sources.
4. Return other traffic to its prior behavior.

Actual IPv4/IPv6 kernel dumps confirm INPUT/FORWARD hooks, loopback/established
acceptance and SSH DROP before the final RETURN. IPv6 new non-loopback SSH is
denied; the verified maintenance route is IPv4 Tailscale. Fresh signed SSH and
Backend/HA/MQTT checks pass before disarming the watchdog. No external-refusal
success marker is fabricated. The private before-export and signed-job source
remain recoverable. Existing SSH keys/accounts/passwords and service configuration
are preserved; there is no NAS/service/device restart.

**Current operating state: firewall is restored to its original disabled state.**
A later source audit confirms personal Target/mobile publishers still use
NAS_HOST/NAS_PORT public SFTP and do not join Tailscale. Keeping the candidate
enabled could break future OTA publication even though existing HTTPS downloads
and current service checks pass. Signed job22de427d restores the original enabled
flag before any new publication; no publication failure is induced. The four new
rules remain inactive for later reviewed activation. The agent should have checked
publisher ingress before the candidate activation.

Required order: validate the CI SFTP route over Tailscale with the same publisher
account and pinned host identity, migrate both publishers with explicit fallback
and acceptance, then reapply the SSH boundary. An enabled firewall candidate is
not reported as a completed production hardening.

The external TCP-check service command was rejected by automatic approval review
with no specific reason. An independent off-LAN TCP check and persistence after
a later authorized/natural NAS restart remain open. Same-LAN public-name reachability
cannot settle that external gate.

## Prioritized remaining work

**Owner update2026-10-17: recurring backup461 is temporarily deferred.** Existing backups/keys and normal deployment backup hooks are preserved. No new dump, encryption, copy, restore or schedule is performed for this deferred item. Current work prioritizes private OTA publication460.

1. [461](https://github.com/ks-house/smart-gatekeeper/issues/461):
   verify recurring encrypted off-NAS backup and restore a recent snapshot.
   The newest observed migration SQL is2.37GB;115 regular files total8.79GB.
   An August28 WSL restore is historical evidence, not current recovery proof.
   A fresh SHA256 read of the2,370,900,079-byte dump matches its sidecar; owner/root-only permissions pass. Read-only DB metadata reports29 tables and approximately2.42GB data/index bytes, dominated by mobile reports and Target health history. This is file-integrity/size preflight, not a recent restore or recurring-copy result. No existing backup is deleted.
2. [430](https://github.com/ks-house/smart-gatekeeper/issues/430):
   confirm46101 installation on the reporting phone and post-install collection.
   The20:30KST report still advertises45701; publication alone is insufficient.
3. [426](https://github.com/ks-house/smart-gatekeeper/issues/426),
   [179](https://github.com/ks-house/smart-gatekeeper/issues/179):
   same-phone causation, screen-off/offline/process-death replay, Bluetooth ON
   wake recovery and reduced personal field observations. No unobserved physical
   opening, electronic fault or phone-setting cause is inferred.
4. [50](https://github.com/ks-house/smart-gatekeeper/issues/50),
   [51](https://github.com/ks-house/smart-gatekeeper/issues/51),
   [52](https://github.com/ks-house/smart-gatekeeper/issues/52),
   [53](https://github.com/ks-house/smart-gatekeeper/issues/53),
   [54](https://github.com/ks-house/smart-gatekeeper/issues/54):
   retain independent physical/operational/manual gates under epic48. Already
   fixed broker328, HA441/447 and Gmail458 are not reopened as current failures.

For the current owner-directed sequence, new-feature readiness first addresses private publication, fresh health/evidence, the intended app actually installed and the personal acceptance record. The recurring-backup project is deferred rather than claimed complete; existing backup-first migration safeguards remain.
This checkpoint does not declare the whole environment or commercial release
complete. Additional general NAS settings authority is dated2026-10-17 only.

Policy references: [Synology firewall rules](https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/connection_security_firewall).


### Private OTA connection accepted; firewall still pending

Owner approves the exact personal-main-only tag/grant/OIDC addition.
PR467/468 are merged after checks; actual private SFTP preflight39034675586
passes all three publisher directories. Future personal publication now selects
Tailscale4222. No new firmware/APK publication or device install was attempted.
Keep460 open until actual private atomic publication plus HTTPS readback and
the later external SSH denial are verified. Firewall remains at its restored
disabled baseline, existing services remain healthy, and461 stays deferred.
