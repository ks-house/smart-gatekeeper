# 2026-10-17 shared broker authenticated cutover

## Accepted operating state

Final signed root job c1c77a8faac84767a2ddd7e0725b2ad6 succeeds at
2026-10-17T02:56:00Z (11:56 KST). Earlier pending/failed migration checkpoints
are historical and superseded by this acceptance.

| Requirement | Verified operating evidence |
|---|---|
| Loaded broker | ce922207831e, Mosquitto2.1.2/image4725ea7590a5; actual mounted config SHA33946fb57f895149949743a3679fc04210315389f25c095389c16ed1c76fba73 |
| Authentication | Both anonymous=false, password/ACL installed, private service-owned files/UID1883 |
| Session eviction | Actual replacement started2026-10-17T02:11:02.513984769Z |
| HA | Independent verify5b698b50: fresh authenticated named notice bound to current broker ID/start/hash; storage700/file600; HTTPS200 |
| Devices | Fresh nonretained Target2.1.525+main.ga63ca41 and SmartBox0.1.0-ge0323a0 observations |
| Collector | Named telemetry principal; installed imageb11ef7ced0e6; running/RestartCount0 |
| Backend | HTTP200/all12 readiness checks, unchanged deployed build5053a3a32fcd78e216f8c34d8dacacf5f2ebc674 |
| SmartBox storage | Read-only Flux200/latest2026-10-17T02:53:58.326031791Z after Influx recovery |
| Grafana/Influx | Exact configured smartbox_influxdb resolves from Grafana; actual mapped4086/health200/pass |
| Inventory | Eight running services, no startup lab containers; previous broker/collector retained stopped/no-autostart |

The broker role does not independently verify HA: its HA verification field is
false while the separate HA role and joint acceptance are true. Its last_error
retains the earlier failed attempt, not the successful apply8fc8c77a outcome.

## Authentication and ACL evidence

Four local1883/certificate-verified TLS4883 negative connects reject anonymous
and wrong passwords for the actual staged HA identity with CONNACK135.
Independent WSL publicTLS4883 probes verify CA/hostname and reject anonymous/
invalid identities135. Public1883 is TCP-refused from that vantage point.
LAN1883 is retained for the existing local HA integration with password/ACL;
it remains plaintext on LAN. External device clients use TLS4883.

Exact installed schema2 policy derives from the reviewed inventory. PR434 and
SmartBox extension real same-image isolated matrices cover legitimate Target
status/events, Backend command/ACL/canonical reads, HA discovery/status/bridge,
six collector topics and cross-principal delivery denials. Loaded bytes are
hash/container-view bound. Live canary1222540f proves five wrong-principal
PUBACK135 refusals and fresh allowed Target status delivery to HA/diagnostic.
Synthetic foreign namespaces avoid actual command/ACL/OTA destinations.
Mosquitto may grant SUBACK1 and filter delivery; do not call this denied SUBACK.
Full read matrix evidence is isolated, without injecting production events.

Scoped retained audit46 records finds zero effectful retained commands and zero
known credential markers. Legacy log audit counts125087 rows,5233 client notices
and40199 connection lines, covering2026-06-28T13:24:48Z–2026-10-17T02:10:53Z.
Anonymous drift was confirmed2026-09-01 and closed at replacement start above.
These counts do not prove absence of intrusion. Historical received events are
not retroactively authenticated or physical-passage evidence.

Distinct Target/SmartBox/HA/collector/diagnostic secrets were prepared privately;
existing Backend secret was preserved under the compatibility plan. Authenticated
HTTPS SmartBox OTA, approved bounded bootstrap closure and actual installed version
were accepted before cutover. No secret values are recorded here.

## Recovery and NAS settings

First apply failed collector stability and restored exact original IDs/images/
configuration. Same-image isolated reproduction established startup ordering.
PR453 verifies broker connect readiness before collector and keeps RestartCount0.
Rollback restores broker first and retains private failed-container evidence.
Preserve previous stopped broker/collector and private backups for rollback.

Our broad diagnostic tail-all query triggered a Synology Docker db logger mutex
stall, established by goroutine evidence. PR451 uses bounded SQLite mode=ro/
query_only/latest200 reads. Live restore recovered daemon/logging. Stale Docker
DNS then required separate existing API/DB and Influx restarts preserving images/
persistent data. Initial daemon recovery preserved eight starts, but subsequent
targeted restarts did not. Do not claim uninterrupted service for the whole repair.
Influx restart's first check incorrectly probed8086 rather than actual4086.
Independent observation6bb8efe1 and fresh stored data/final joint acceptance prove
recovery; the earlier failed job stays recorded.

HA restart policy no→unless-stopped was read back without stopping HA or changing
its image/config/start. HTTPS200 and TLS WebSocket101/auth_required pass.
Original HA stop cause, alarm delivery and NAS reboot/failure injection remain
unverified under441. Event discovery JSON bug447 remains a separate follow-up.

Dedicated broker/HA keys and signed root maintenance work without interactive
password input; existing deploy keys are preserved. Signed root Python execution
is privileged authority, not a sandbox. Signer private key stays WSL; signature/
expiry/replay/deadline controls and private receipts apply. Additional NAS settings
authorization is only2026-10-17, not a future blanket permission.

## Source, tests and boundaries

PR449–453 merged after exact-head checks. PR453d7739f07 passes
Backend38993254335/OTA38993254331/trusted38993254355, merged a528b82f.
Local71 HA/access/TLS tests,14 broker integration cases including actual rollback,
Backend425/14 explicit skips and OTA12/1 explicit skip pass.
Source-only main38993648688 cancelled with no NAS deployment steps; API stays5053a3a.
Documentation publication requires no API/firmware rollout.

No additional device OTA/reboot or real actuator command was sent by this final
acceptance. Physical door/lid, relay/sensor electrical qualification, OEM background
and failure-injection gates remain separate.
