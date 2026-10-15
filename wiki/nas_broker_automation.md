# Dedicated NAS broker maintenance access

The owner explicitly requests unattended broker maintenance after repeated
interactive sudo handoffs. This is an additional dedicated SSH identity.
The existing forced Backend deploy key, account groups and SSH server policy
are preserved.

## Scope and installation

scripts/nas_broker_ops/bootstrap.py is a one-time operator-authenticated installer.
It captures bounded package bytes once, verifies the pinned manifest/payload
hashes and installs those exact immutable captured bytes. Trusted bootstrap code
is passed from the local client through an isolated interpreter command rather
than executed from a mutable NAS staging file. It compiles server/embedded SDK code,
checks typed initial inputs and confirms the operator cannot write the root
program or parent directories. Root-owned code lives outside the shared Docker
configuration directory. Operator name, host, new passwords and private key are
private setup data and are absent from repository examples.

The added public key accepts tailnet source addresses and exact IPv4 loopback
127.0.0.1, disallows PTY/forwarding/user startup files and forces one dispatcher.
The installed Synology Tailscale daemon uses userspace networking: its NAS SSH
connection has both endpoints 127.0.0.1. Restricting the key to 100.64.0.0/10
therefore rejects a valid tailnet connection. The loopback exception also permits
NAS-local connections possessing the dedicated private key; it does not grant
direct LAN/public source access. The private key remains on the WSL client.
Installation receipts now enumerate accepted source ranges; the initial live
receipt's legacy tailnet_only flag predates this correction and must not be
treated as proof of excluding NAS-local peers. SSH original-command strings must
exactly equal status, receive, stage, apply, rollback or diagnose. The sudo rule
names the root-owned program plus these exact arguments. A command-specific
no-TTY setting permits unattended use. The actual complete NAS sudo policy
parser and a detached operator status call validate the rule before key
registration; failed registration restores the previous policy/key bytes.

Gateway updates require a fresh authorized installer action. The dedicated key
cannot replace privileged code or run arbitrary Docker, shell or filesystem
commands. Routine data/validation/activation/rollback uses the fixed gateway.

## Local client

Use the project Python with scripts/nas_broker_ops/client.py. The setup also
places a persistent client, pinned known_hosts, private connection metadata and
the dedicated key under ~/.config/smart-gatekeeper-broker, directory0700 and
private files0600. The client forces public-key authentication, disables master
reuse/password fallback/forwarding and verifies the existing server pin.

~~~sh
.venv/bin/python scripts/nas_broker_ops/client.py status
.venv/bin/python scripts/nas_broker_ops/client.py receive --input-file /private/input.json
.venv/bin/python scripts/nas_broker_ops/client.py stage
.venv/bin/python scripts/nas_broker_ops/client.py diagnose
~~~

Receive accepts only a bounded exact typed inventory, five64-hex new passwords
and optional installed-version expectations. It preserves the operating Backend
identity/password and registered Target. This installed personal profile handles
one Target, one diagnostic identity, HA, one SmartBox and one collector. Future
device-password rotation after authenticated activation requires a separate
compatible rollback plan; it cannot silently reuse this initial anonymous
rollback assumption.

Stage/apply/rollback run under an exclusive lock in detached, time-bounded
workers, surviving SSH disconnect. Status is read-only and exposes selected
metadata, validation results and private error summaries. Each receive writes a complete versioned root-private bundle, then atomically
publishes one pointer. A digest binds inventory, credentials, ACL and expected
versions together. Every bundle change, including version-only updates,
invalidates the previous stage; restaging is unattended.

## Staging and activation contract

Stage snapshots current config/TLS/client files privately, preserves the Backend
password, creates a candidate with the actual broker password utility and tests
16 named/anonymous/wrong-password handshakes across both loopback listeners.
TLS uses the real hostname/certificate/CA. The Synology Docker top query includes
the PID column required by its daemon. No live broker/client file is edited.

Apply requires matching staged input, successful authentication matrix, protected
origin hashes and fresh matching installed Target/SmartBox versions. Subscribe-only
preflight also requires both FSMs idle and Target relay commanded OFF. The gateway
does not publish commands or trigger firmware updates.

It creates private config/auth files and replaces only the broker and collector
with the exact installed images/configuration, preserving mounts, ports, networks
and other environment fields. Broker runtime UID remains its measured unprivileged
UID, avoiding root-entrypoint chown against a read-only configuration overlay.
The collector credential-bearing file stays in root-private storage. Original
shared configuration files are preserved. Both operating broker listeners receive
the same explicit authentication/ACL policy; the collector retains its existing
LAN listener route with named read-only credentials.

The old containers are retained stopped with restart disabled, and their original
restart policies are saved. A failed verification restores their names, exact
images/configurations/mounts and restart policies. Explicit rollback supports a
recorded interrupted transaction. This is bounded software rollback, not an
installed power-loss/availability Gate. Static container IPAM changes are rejected
rather than silently reallocating them.

Fresh Target status/SmartBox telemetry, matching versions, collector process
stability and independent Backend readiness are required after replacement.
Anonymous/cross-principal and external readback are separate operating evidence.
HA is currently absent from running NAS inventory; its actual reconnect is not
asserted or silently started. The corresponding #328 acceptance remains open.

## Validation and current boundary

- Local full488 cases/1environment skip and OTA contract PASS before the final
  embedded-worker compile regression; final focused9 cases PASS.
- Actual Docker replacement test proves private mount delivery, exact image and
  environment preservation, disabled backup restart and restore of the previous
  mount/restart policy. Fixtures have no production names or published ports.
- Forced-command injection, unrecognized input/identity/password/path fields,
  byte bounds, protected mounts and version-only versus credential-stage
  invalidation are verified.
- Owner completed NAS installation. Fresh key-only status succeeds after narrowly
  correcting the dedicated authorized-key source range; existing keys are byte
  preserved and general command id returns126. Installed executable hashes match
  the pinned package. Six exact sudo commands work without password prompts.
- Actual NAS stage succeeded at 2026-10-16 08:09 KST: all16 named,
  anonymous and wrong-password cases passed across both isolated listeners;
  real TLS hostname/chain verified. Runtime broker UID/GID1883 measured.
  Operating broker config hash remains unchanged and new_credentials_installed
  is false. No new MQTT credential was published and no broker/collector
  replacement or physical command occurred. Coordinated device publication,
  installed-version/health proof, restaging and live cutover remain pending.

See [broker migration](broker_security_migration.md) for the operating gates and
[OTA contract](ota_reliability_contract.md) for independent device recovery.
