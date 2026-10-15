# Broker principal isolation and staged migration — issue #328

## Current evidence and scope

A fresh read-only strict-TLS connection on2026-10-15 confirms anonymous CONNECT is still accepted on the public MQTTS listener. No subscribe, publish, LWT, broker change or Target command was sent. Private NAS SSH is reachable and its server public key matches the existing pin, but the local owner key is not authorized. The separate restricted Backend deploy key authenticates successfully over the configured Tailscale SSH port8822 and its forced status command confirms deployed5053a3a with loopback/public readiness passed. That key is not a broker administration channel. Live image/config/password/ACL snapshots and operating client credentials have not been read or changed.

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

The integration runs immutable image eclipse-mosquitto@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797 (local verified version2.1.2), bound only to loopback with synthetic names/passwords. It tests actual message delivery and ordered barriers rather than treating SUBACK/PUBACK alone as authorization. A test-only observer and fixture/barrier namespace never appear in generated production ACLs. Temporary containers/files are removed. The existing Backend security CI Target-security entry point also runs the actual12-test renderer/broker matrix in a child process (the Backend dependency tier or explicit local opt-in); it does not require a privileged workflow change.

Anonymous/wrong-password refusal, own Target writes/reads, cross-Target denial, Backend canonical collection/command/ACL, HA bridge/retained discovery for late subscribers, diagnostic read-only behavior and absence of inherited role-name Target writes pass. This validates the candidate policy on2.1.2; it does not identify the live NAS image/version, prove its TLS configuration/client compatibility or complete a live cutover.

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
