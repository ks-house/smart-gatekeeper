> Latest acceptance: [2026-10-17 authenticated cutover](broker_cutover_2026_10_17.md). Earlier pending/failed sections are historical checkpoints.

# Synology Docker log recovery

The running broker's log file was absent in an operator-owned0555 directory.
PR450 precreates only its0600 UID/GID1883 file and rereads the same pinned broker
configuration with HUP. Exact fresh CONNECT notices now reach that file.

A subsequent read-only Docker goroutine snapshot identifies a separate blockage:
a terminated diagnostic HTTP tail-all consumer leaves Synology logdb.tail.func1
blocked on channel send while holding the logdb mutex. The same mutex blocks its
flusher and later tail readers. The broker's25MB SQLite log database is readable
but its newest record remains2026-10-16T23:39:37Z. Do not repeat tail-all queries,
claim that missing EOF alone caused the timeout, or accept old records as fresh.

## Bounded observation

For the exact Synology db logger, read only the latest200 physical log_content
rows through SQLite mode=ro, query_only and a2s deadline. Preserve Docker's
explicit UTC created timestamp and the existing exact client-ID/username/since
matcher. Reject unbound container IDs, wrong data ownership and malformed rows.
Ignore oversized unrelated rows entirely rather than turning truncated text into
a valid notice. Other logger types retain the bounded Docker HTTP path.

No global Docker configuration changes are required for this read-only method.
It prevents new HTTP log-reader deadlocks; an existing writer deadlock still
requires daemon recovery before newly captured notices can pass the gate.

## Prepared daemon recovery

All eight running containers belong to Gatekeeper, Home Assistant or SmartBox.
The exact Docker24.0.2 service has KillMode=process, Restart=always, no ExecStop,
and an infinite stop timeout. Its daemon configuration is root-owned0600.

The signed recovery code changes only live-restore=true, validates the candidate
using the installed dockerd --validate, reloads it and requires actual activation
plus unchanged container IDs/PIDs/start ticks/start times/images before proceeding.
It restarts only pkg-ContainerManager-dockerd.service, never the package or a
container. If the original daemon remains stopping after30s, it may signal only
that exact original dockerd PID/start-tick/executable after verifying all container
processes still exist. The unit restarts the daemon. No container process is
signalled. Repeated recovery attempts are refused by a root-private journal.

Post-checks require a new daemon PID, active live restore, preservation of all
eight container processes, HA HTTP200, backend readiness and an actual fresh
CONNECT-only notice. Failed reload before restart restores exact previous config
bytes. A restart observation timeout is incomplete evidence and never causes an
automatic second restart.

Operating recovery2026-10-17: dockerd now runs as PID22352 with live restore
enabled. A separate read-only observation proves all eight original processes
survived that daemon restart and fresh notices reach the database again. The
original recovery job fails on its NAS self-origin HTTP check and is not reported
as a complete success.

A live-restored database endpoint lost its DNS alias registration. A subsequent
API restart alone did not restore that database alias; network reregistration
failed on staleeth0. A controlled DB restart kept its exact container, image and
persistent data mount and restored the alias. API and DB processes therefore
changed during these explicit follow-ups; the other six remained running.
External HA/backendHTTP200 and all12 backend readiness checks are verified.
Authenticated broker cutover remains pending.

NAS self-origin HTTPS health probes now use the pinned local route while retaining
the original public SNI/Host and normal certificate chain/hostname verification.
Actual candidate probes pass both4123/4442 and operator readiness. Public
MQTT4883 observation already works and is unchanged. Container process survival
alone must never substitute for network/DNS/application readiness.

References: [Docker live restore](https://docs.docker.com/engine/daemon/live-restore/),
[recovery source](../scripts/nas_maintenance/recover_dockerd.py),
[HA operator](../ops/ha_mqtt_adoption.py),
[dedicated maintenance](signed_nas_maintenance.md).
