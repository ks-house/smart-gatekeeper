# Target network recovery — 2026-11-05

## Incident and scope

The owner requests prevention of the [ACL wait incident](acl_wait_incident_2026_11_05.md). Installed552 retried DNS/MQTT while its last applied15-minute ACL expired. Signed status was absent82m38s; recovery retained boot912. The initiating fault and precise natural recovery trigger remain unproved.

The change bounds no-progress recovery and exposes stale status. Hardware/power/router/WAN availability is not guaranteed. Source validation, signed publication, installed boot health and physical entry are separate evidence.

## Recovery policy

- Keep the5-second DNS deadline. Count one terminal failure per actual generation; late/invalidated callbacks cannot revive it. Consume synchronous errors in the same attempt.
- Three actual same-link DNS failures spanning60s or six transport failures spanning180s qualify repair. Authorization/resource failure clears qualification. A new link clears old evidence while preserving stage and global action budget.
- First repair asynchronously disconnects/reassociates STA. Repeated qualifying failure recreates only STA and restores its existing profile/credentials. No credential erase, DNS/IP replacement, TLS relaxation or automatic chip reboot.
- Accepted actions are120s apart, at most two in any rolling15min. Brief success retains budget;60s stable adopted MQTT resets only the episode/stage. Continuing failures can retry after budget expiry.
- A2s disconnect observation and15s adapter lease bound pending ownership. API acceptance is not proof of restored connectivity.

## Safety and evidence

Atomic idle-radio admission excludes GATT connection/ingress/output, ARM/relay/cooldown and OTA. All MQTT socket workers must relinquish ownership. No GATT mutex is held across radio/socket I/O. Local recovery/AP and OTA take precedence; busy access defers repair.

A connect worker that loses watchdog coverage stops before further I/O and returns ownership for monitored main cleanup. Existing TLS, principal, proof, signed ACL/replay and dual-slot OTA/rollback contracts remain.

Optional unsigned network_recovery counters fit within existing status pool/wire budgets or are omitted. They cannot grant authority. Fresh signed health, adopted MQTT and exact ACL APPLIED ACK establish recovery.

Home consumes optional identity/door-scoped fresh/stale/unknown availability. A persisted observation cannot make a cold registry/replay fresh. Cached freshness expires from the server age; permission and updater rules remain.

## Validation and delivery

Actual production-function host fixtures cover failure/race guards. Fake-clock policy/controller tests, ArduinoJson budget tests, Backend/widgets and enabled/default C6 builds cover software boundaries. Results and delivery state are in [hardware_test](hardware_test.md), [project_status](project_status.md) and [log](log.md).

No unattended door command or live failure injection is used. Target557 is installed as boot913 after one safe-state-gated OTA request. Health accepts the image at00:29:28 KST on11/06; later same-boot reports stay VALID/IDLE/relay OFF/BLE ready. The previous bootable slot and previous valid published artifacts remain. Its own post-install HTTPS current-version check passes. Backend2dfe93a is independently ready12/12 with fresh verified status. Phone installation, physical entry and power/router fault acceptance remain open.

### Operating evidence and remaining limits

PR478 merges as2dfe93a after all hosted checks; separate policy479 changes only the certifi lock digest. Actual Target557 private publication includes clean repeat/cmp, Ed25519, encrypted full-artifact hashes, atomic swap and HTTPS verification. Independent verification uses the preexisting provisioned public macro whose SHA matches the protected production pin; no private signer or plaintext firmware is retrieved.

Source tests cover bounded repair faults and ownership, while field validation confirms install/boot health and normal communication. No live DNS/router outage is injected, and zero recovery counters do not demonstrate actual staged repair in the wall unit. The post-install read API does not expose latest desired ACL/APPLIED ACK; unavailable browser transport prevented a separate read-only DB check. BLE ready is not substituted for that exact ACK. No physical-door success is claimed.

### Mobile delivery

Signed mobile `1.0.0-g2dfe93a / 47401` is published through42052375603. Both primary/fallback APKs and manifests independently match complete CI bytes over strict HTTPS; APK signer, embedded source and Ed25519 verification pass, with previous valid pairs retained. Phone installation is not observed. Backend availability changes become visible when the updated app is installed; the deployed Target remains N/N-1 compatible with the existing app.
