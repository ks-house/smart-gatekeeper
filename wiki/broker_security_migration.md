# Broker principal isolation and staged migration — issue #328

## Current evidence and scope

Source remediation is merged: PR434/bcc79f8 after the separate one-file workflow-trigger admission PR435/8e6932d. Operating authentication/ACL activation is still pending under #328.

Owner-authenticated read-only audits on2026-10-16 identify the live broker as Mosquitto2.1.2, with the same immutable image digest used by the isolated regression. Both enabled listeners still permit anonymous access and have no password/ACL policy. Original active config and TLS references were copied to root-private durable storage, restricted to0700 directories/0600 files and independently hash-verified. Configuration hash was unchanged on later readback. This is a completed snapshot, not a tested rollback or a production cutover.

Pinned DSM SSH works over Tailscale on the configured port. The owner entered login/sudo passwords directly into an interactive terminal; no password was collected in chat or printed by the audit. The existing forced Backend deploy key remains restricted to its original commands. No account, SSH/sudo policy, broker configuration, credentials or service was changed.

The Backend has a distinct configured MQTT username and a nonempty password secret on its TLS route. Local Target provisioning differs from the operating Target ID and Backend identity/password; it has not been bound to the installed firmware's actual credentials. Do not treat the local file as proof that the installed Target will authenticate after cutover. The bounded recent connection-log query produced no matching connection records, so current client identities remain unproved by that path.

The running Telegraf configuration subscribes anonymously over the plaintext listener to a separate legacy SmartBox telemetry/event topic family. Stored Home Assistant MQTT configuration also has no credentials, but HA is absent from the running NAS container inventory and its local upstream port is closed. This establishes stored configuration and a running dependent service, not current HA use of this broker. Before global anonymous refusal, include all legacy producers/consumers in the authorized migration scope or choose a separate authenticated Smart Gatekeeper broker route; do not silently break unrelated telemetry.


The old repository ACL used global %u patterns. In pinned isolated Mosquitto2.1.2, Home Assistant, Backend and a read-only diagnostic password principal could each publish a canonical-event to the pseudo Target namespace named after that principal. Application MAC/Target validation is a separate boundary; this is not evidence of a successful door command.

[Official Mosquitto ACL documentation](https://mosquitto.org/man/mosquitto-conf-5.html) states that pattern rules apply to every user. The new reference contains only named-user topic rules. scripts/render_broker_acl.py expands a private exact inventory into a new candidate; it rejects role collisions, topic/name injection, duplicate Targets, extra/password fields and global pattern directives. The example reference ACL must never be copied directly over a live configuration.

## Private inventory and generated candidate

Use a private0600 inventory, containing no passwords:

~~~json
{
  "schema_version": 1,
  "targets": ["target-a", "target-b"],
  "backend_username": "gatekeeper-backend",
  "ha_username": "homeassistant",
  "diagnostic_usernames": ["gatekeeper-read"],
  "discovery_device_id": "smart_gatekeeper_01"
}
~~~

These names are synthetic. Inventory every actual client first, including both Backend publisher and receive/commit collectors. Each Target broker username must equal its exact Target ID; all Backend/HA/diagnostic roles must be distinct from Target IDs and each other. Maximum64 Targets,8 diagnostic identities and64KiB inventory. Do not guess existing username/password compatibility or silently change installed Target provisioning.

~~~sh
/home/sh-cat-lee/workspaces/smart-gatekeeper/.venv/bin/python scripts/render_broker_acl.py \
  --inventory /private/broker/inventory.json \
  --output /private/broker/target-acl.candidate
~~~

The output is a new0600 file; existing files are never overwritten. Stdout contains only candidate digest/counts and production_installed=false. Names/Target IDs remain in the private inventory/candidate and are not console output.

| Principal | Read | Write |
|---|---|---|
| Target | Own command and ACL | Own status/availability/event/canonical-event/sensor/boot/config-state and ACKs |
| Backend | Listed Target ACK/boot/status/availability/canonical-event; listed HA request/access-event | Listed Target command/ACL; listed HA state/result/diagnostics/access-event and configured discovery |
| HA | Discovery/status and listed Target status/HA results | HA birth/status and listed Backend bridge requests |
| Diagnostic | Listed Target status/availability/boot and bridge verified-status/availability/connectivity | None |

Unknown topics, other Targets, role-name pseudo Target namespaces and diagnostic writes receive no grant. No global Target pattern can leak into another principal. The example template's role wildcards are expanded to the inventory's exact Target list before deployment.

## Real-broker regression

~~~sh
RUN_MQTT_ACL_INTEGRATION=1 /path/to/project/.venv/bin/python \
  -m unittest tests.test_broker_acl_renderer tests.test_broker_acl_integration \
  tests.test_target_security_ota -v
~~~

The integration runs immutable image eclipse-mosquitto@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797 (local verified version2.1.2), bound only to loopback with synthetic names/passwords. It tests actual message delivery and ordered barriers rather than treating SUBACK/PUBACK alone as authorization. A test-only observer and fixture/barrier namespace never appear in generated production ACLs. Temporary containers/files are removed. The existing Backend security CI Target-security entry point also runs the actual13-test renderer/broker matrix in a child process (the Backend dependency tier or explicit local opt-in); it does not require a privileged workflow change.

Anonymous/wrong-password refusal, own Target writes/reads, cross-Target denial, Backend canonical collection/command/ACL, HA bridge/retained discovery for late subscribers, diagnostic read-only behavior and absence of inherited role-name Target writes pass. The later owner-authenticated audit matches the live image/version to this2.1.2 fixture. The synthetic matrix does not prove live TLS configuration/client compatibility or complete a live cutover.

## Required operating sequence and rollback

1. Obtain an authorized NAS administrator session. Record the live container's exact image ID/digest/version and mounts without dumping environment variables. Privately back up all active/include config, password/ACL files, ownership/modes, certificate references and restart procedure. Do not print bridge passwords or secret file contents. The actual deployment unit may differ from the repository reference.
2. Inventory every listener and client. If LAN plaintext1883 is unnecessary, remove it; otherwise document an explicit authenticated policy for each required listener. Do not disable1883 before HA/other legitimate clients have a verified TLS/auth route.
3. Prove current Target credential uniqueness and username-to-ID agreement. If provisioning must change, use the existing signed dual-slot/periodic-HTTPS OTA and rollback path, confirm install→reboot→VALID separately, then proceed. No broker cutover may strand an unprepared Target or weaken OTA recovery.
4. Provision Backend, each Target, HA and optional diagnostic passwords through permission-restricted secret paths. Use the live-compatible mosquitto_passwd interactively; never put real passwords in argv, logs, inventory, source or tickets. Use -c only for a new private candidate, never an existing live password file. Confirm every legitimate client is already using its named credentials before anonymous access is removed.
5. Render a candidate and validate it with the exact live broker version, a separate loopback listener/config and the real client topic inventory. Keep preserved TLS certificate/CA references and verify hostname/chain/version. The pinned synthetic regression is additional evidence, not a replacement for this compatibility check.
6. Prepare a bounded restore of the exact old image/config/password/ACL/ownership before activation. Validate configuration and reader permissions for the actual broker UID. Preserve last-known-good files; do not delete them during cutover.
7. Activate in a bounded operational window with a restart or explicit old-session eviction so pre-change anonymous connections cannot survive. Do not claim SIGHUP alone closes that gate. Verify legitimate Backend collector SUBACK AND fresh verified status/storage, Target reconnect/status/ACK, HA discovery/state and private/public readiness. Do not publish synthetic Target command/ACL/canonical events to the production namespace to test denials.
8. On failed recovery, restore the exact preserved operating configuration/image/permissions and restart once according to the prepared procedure; independently verify reconnect/readiness after rollback. Audit retained messages, exposure and credential-rotation decisions, then capture non-effecting allow/deny evidence (anonymous CONNECT rejection and legitimate status read) plus natural application ACK/receipt evidence.

## Completion boundaries

Source policy, renderer and isolated broker regression are completed separately from production installation. Live #328 acceptance remains open until the authorized inventory/backup, compatible named credentials, every enabled listener, old-session eviction, legitimate reconnect/rollback, retained audit and independent public/private readback are verified. No NAS/broker/HA/Target state or credential was changed by this work. Physical door behavior remains a separate #54 gate.

## 2026-10-16 Tailscale authentication and CI follow-up

The user confirms DSM SSH port8822. Tailscale reports the NAS online, the pinned private OpenSSH transport works, and the existing forced Backend key returns valid deployment status. Port22 refuses connections. [Tailscale's Synology documentation](https://tailscale.com/docs/integrations/synology) distinguishes access over Tailscale from its separate Tailscale SSH server feature, which does not run on Synology; DSM SSH still requires its own allowed credentials. Do not broaden the forced Backend key or disable host-key checks to obtain broker authority.

The first Backend hosted check executed the actual12-case broker matrix successfully. The separate OTA-only lane lacked MQTT dependencies, so real integration now runs only when GITHUB_WORKFLOW identifies the Backend security lane or local opt-in is explicit; a regression covers the tier selection. The OTA/manual walkthrough stays reproducible without pulling in Backend-only packages. Docker assigns fixture ports atomically and verifies loopback mapping, replacing a bind/close/start window; bounded Docker error details are retained on startup failure.

## 2026-10-16 CI input-trigger admission

A later renderer/test-only PR must still start its owning security workflow. Both pull-request and main-push path filters now include the renderer and its two direct regression files. The routing test derives those input paths from the imported implementation and test modules; it fails against the previous filters and passes after the additions.

This changes only path triggers in one of the23 protected files. Permissions, jobs, dependencies, image publication/deployment conditions, signing gates and the22 other protected bytes stay identical. The reviewed feature SHA and complete23-file map must be admitted in a separate policy-only PR before this feature merges. The feature must preserve ancestry (merge-connect main, then merge-commit; no squash/rebase) under the persistent-baseline contract.

## 2026-10-16 merged validation and remaining operating work

Final connected feature fba753a passed the local474-test root suite (one environment skip), OTA contract and exact-head hosted Backend/OTA/trusted checks. The hosted Backend child ran all13 renderer/broker cases rather than skipping them. Main OTA38762364009 succeeded. The redundant main Backend run38762364029 passed security, attestation and operations verification but failed later while pulling the upstream DockerHub Buildx image with HTTP502; deploy was skipped. No Backend or broker deployment followed that run.

The live image/config snapshot is verified, while the combined operating rollback task remains unchecked because restore/config activation has not been exercised. All eight operating acceptance tasks in #328 stay open. The owner explicitly selected a combined SmartBox and Smart Gatekeeper migration. Next are exact Target/SmartBox provisioning, named-client/TLS readiness, private candidate/restore validation and bounded activation/reconnect/independent readback. No Target reboot, OTA trigger, door action or physical acceptance occurred.

## Shared SmartBox policy candidate (inventory schema2)

The owner authorizes a combined migration. The renderer accepts the existing exact schema1 unchanged, or schema2 with one additional smartbox object containing exactly device_username and telemetry_username. Those names must be distinct from every Target, Backend, HA and diagnostic principal; passwords remain forbidden inventory fields.

The currently supported SmartBox is the single-controller namespace implemented in ks-house/smartbox source632f004. This does not provide per-device isolation for multiple SmartBox units sharing that namespace.

| Principal | Additional permitted path |
|---|---|
| SmartBox device | Read smartbox/command; write its exact status/config/log, two telemetry and four event topics; write exactly20 existing smartbox_01 discovery configs |
| Telegraf collector | Read only the two telemetry and four known event topics; no command, state/log/discovery or write access |
| HA | Read SmartBox telemetry/state/log; write smartbox/command, retaining the existing SmartBox control authority |
| Backend/Target/diagnostic | No new SmartBox permissions |

Schema2 example additions (keep all existing schema1 fields and set schema_version to2):

~~~json
"smartbox": {
  "device_username": "smartbox-device",
  "telemetry_username": "smartbox-telemetry"
}
~~~

The extra isolated-broker matrix verifies all six collector deliveries, write denials, HA command/device read delivery, non-command readers, exact20 discovery paths, other-device discovery denial and absence of inherited Target namespaces. Fixture commands target only synthetic loopback brokers; no production actuator command is sent.

Operating rollout must also protect the SmartBox firmware download route before publishing any fresh credential-bearing image. A strict-TLS anonymous HEAD currently obtains its firmware artifact; the existing SmartBox updater does not establish encrypted-artifact support. Authenticated MQTT alone cannot make a credential-bearing public artifact private. Verify current client download routing and a compatible protected origin before credential rotation/publication; preserve the installed updater's recovery route.

## 2026-10-16 authenticated automation preparation

The owner requests a dedicated maintenance route to remove repeated sudo handoffs.
The [broker automation runbook](nas_broker_automation.md) describes the restricted
key and six exact root-owned operations. Existing Backend deployment authority
is preserved. The private stage failed before live changes because Synology Docker
top requires a PID column; the installed helper includes it and preserves errors.
One-time key/sudo registration and actual isolated TLS staging are pending.

Separately, SmartBox origin protection is installed: native nginx whole-config
validation/28 HTTP cases and local strict-TLS paths pass. Independent external
GitHub probe38776457429 succeeds for anonymous HEAD/GET refusal, with publication
skipped. Fresh MQTT credentials have not been published. Shared policy PR437
merged acf6982 after exact-head Backend/OTA/trusted checks and reserved-discovery
collision RED/GREEN correction. Redundant main Backend38778457186 cancellation
was requested before any deployment; read final state before claiming cancelled.


## 2026-10-16 installed client rollout checkpoint

Dedicated restricted NAS access and isolated16-case authentication/TLS staging
are verified. Eight build-provisioning secret entries were registered without
logging values, covering Target repo/personal-auto-ota/production and SmartBox.
Target signed/encrypted publication38823340730 passed, independent artifact
signature/hash/provisioning readback passed, and one signed-bridge OTA check
yielded2.1.525/boot911. Fresh verified Backend state is IDLE/OFF; accompanying
firmware/VALID advisory is consistent, with pending0/gapfalse and all12 ready checks.

SmartBoxPR6 merged5e5e334 and publication38823428021 passed, but the device remains
on0.1.0-g632f004 after one bounded request. Command reception and installed CA/current
URL are verified. Owner confirms the same network as Target; reported LAN is outside
the initial private-origin allowlist. SmartBox issue7 tracks protected route
compatibility, remote OTA diagnostics and actual install health. A pinned private
LAN-only updater is being validated; actual NAS application remains pending.

Both operating listeners still allow anonymous clients and the collector is
unchanged. Do not bind the old SmartBox version to authorize a premature cutover.
After installed health: supply exact prepared versions, restage16 cases, then
activate/verify bounded rollback, legitimate reconnect and independent refusal.
HA remains absent; no HA reconnect, physical access or whole328 completion claim.


## 2026-10-16 HA private credential adoption

SmartBox0.1.0-ge0323a0 is installed with fresh reconnect/IDLE and an authenticated remote version check after early bootstrap closure. Independent pre/post outside authentication and cleanup pass. Current Target525 and SmartBoxe0323a0 bind a newly staged16-case candidate. HA is running and reachable again, but its MQTT entry has no account; parent328 remains open.

[HA adoption helper](../ops/ha_mqtt_adoption.py) is a separate administrator invocation; it does not expand the permanent six-command SSH key. It uses the existing root-private staged credentials and exact input/config hashes, requires the existing running root HA/container binding, and retains the installed image and restart policy. Existing storage is root-owned0777/file0644: the helper stops HA, backs up its final snapshot, protects the directory0700, writes root0600 account data, and restarts that same container.

Acceptance requires a fresh exact MQTT client/username connection record and HTTPS HA readiness. On initial failure, restore managed settings and modes only after credential removal; preserve unrelated HA changes and refuse concurrent identity overwrite. An independent300s watchdog recovers interrupted adoption. Successful adoption leaves named credentials/private storage installed and observes up to600s for a later authenticated-broker reconnect. That later audit requires a changed broker container, two anonymous=false directives, current file hash/stage bindings and a new HA connection since broker start. It does not itself apply broker settings.

Pre-cutover username transmission on an anonymous broker is not authentication proof. No physical commands are sent. HA restart policy/stop-cause issue441 remains separate; user-only administrator authentication is required for this helper because the dedicated key has no HA editing authority.


### HA mount ownership preflight repair

The initial administrator invocation refused before changes because it assumed the mounted Synology share was root-owned. Actual storage/config remain root-owned, but the share belongs to the NAS operator. Preserve that parent ownership; require a real directory and exact existing Docker bind, while the credential-bearing child/file still require root ownership and private modes during adoption. A full root filesystem preflight fixture with this ownership split passes and rejects a changed child owner or symlink. Initial HA config hash and HTTP availability are unchanged.
