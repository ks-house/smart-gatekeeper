# Dedicated unattended HA operations

The owner requested that NAS diagnosis and migration no longer require repeated password entry. The existing deploy and six-command broker keys remain unchanged. A separate tailnet/loopback-only Ed25519 key reaches six fixed HA operations through a forced SSH command and exact passwordless sudo rules.

Installation requires one administrator invocation. It installs root-owned source/control files and the dedicated public key; it does not alter an HA account, restart policy, broker configuration, Docker group, service image or device. Existing keys and the complete previous sudo policy are preserved; failure during privilege registration restores the previous key/policy bytes. The installer checks that the operator cannot write the root program or its ancestors before registering authority.

| Command | Scope |
|---|---|
| status | Read current HA/broker identity, managed-account/private-mode state and root job receipts; no passwords |
| diagnose | Detached bounded snapshots of the two fixed services, including actual broker quiet flag and recent logs |
| refresh-logging | Before HA adoption, validate the exact staged original broker/TLS files in an isolated same-image container, send HUP to that fixed broker, require same container/start and fresh named notice; no file/account edit |
| adopt | Run the guarded HA operator against root-pinned input/config/image bindings; maintain existing private backup, watchdog and rollback |
| verify | Independently verify a fresh named HA reconnect after actual authenticated broker replacement; keep proof bound to broker ID/start/config and private HA identity |
| rollback | Restore only root-journaled managed HA settings; refuse while authenticated broker state exists or initial adoption is controlled by its watchdog |

Local client after installation:

    /home/sh-cat-lee/workspaces/smart-gatekeeper/.venv/bin/python ~/.config/smart-gatekeeper-ha/client.py status

The private local directory and key have0700/0600 modes. Client connections use pinned known-host data, a dedicated identity, BatchMode, no password fallback and no forwarding. The server dispatcher rejects shell/file/argument requests; root operations accept no user-provided paths, code, plans or MQTT payloads. Runtime modules are checked against captured hashes on every invocation. Long operations are detached with root-owned bounded job receipts.

The preflight connection marker uses the same reviewed broker endpoint as HA, instead of assuming loopback reaches the same listener. It sends CONNECT/DISCONNECT only, with no password, will, subscription, publish or HA client-ID collision. HA stop/write still requires actual mounted-file agreement and a fresh timestamped notice. The logging recovery command rereads the current pinned configuration; it is not broker authentication cutover and does not evict pre-change anonymous sessions.

Broker cutover/rollback remains on the existing broker client. If a failed cutover needs HA account removal, restore the previous broker first, then invoke HA rollback. Source merge and key installation are distinct from successful account migration, authenticated reconnect, OTA or physical access.
