---
title: smart-gatekeeper current project status
type: reference
project: smart-gatekeeper
status: active
updated: 2026-09-05
source_of_truth: true
applies_to:
  - firmware
  - android
  - backend
  - operations
---

# 현재 프로젝트 상태

> 관측 기준: 모바일 remote authorization 교정은 PR #290과 Backend run `33311924158`로 NAS 배포된 뒤 owner의 한 번의 모바일 버튼→Backend→signed MQTTS→Target→relay→실제 문 열림 관찰을 통과했다. Fresh A24 onboarding은 PR #295 배포 후 등록 폼까지 복구됐고 PR #297/Backend run `33314043691`이 `GK-*` 신청 저장 불일치를 교정·배포했다. 이후 owner의 접수와 관리자 승인은 완료됐지만 첫 `이 휴대폰 등록`은 단일-user compatibility mapping 때문에 HTTP 409로 실패했다. 승인된 추가 가족 행을 같은 personal tenant의 별도 public credential/door grant로 수용하는 PR #300이 exact main `38b90e5febc525c96a4013b737850fd6a90235d3`으로 병합됐고 Backend run `33315099974`가 NAS `status=deployed`, canonical loopback/public readiness와 독립 strict-TLS exact-build HTTP 200/all-checks-true를 통과했다. 이후 한 번의 owner retry로 A24가 `스마트키 사용 가능`, 등록 출입문 1, ACL 608이 됐으며 Activity가 credential 등록을 기록했다. Access-ready 계약상 exact signed ACL의 matching APPLIED Target ACK도 통과했다. 뒤이은 원격 개방은 MQTT broker 전달까지만 확인됐고 딸아이 휴대폰에서 실제 문이 열린 물리 관찰은 별도 Gate다. Target 공개 manifest 게시도 설치·재부팅·health confirmation은 아니므로 현재 Target runtime version과 별도 물리 동작은 계속 별도 Gate다.
>
> 이 문서는 **저장소 최신 구현**, **검증 증거**, **현장 배포 상태**를 분리해 보여 주는 시작점이다. 세부 계약은 링크된 문서와 코드를 따른다.

## 2026-09-05 field diagnostics D0-D2 merged source

- Android now preserves and exports at most 50 redacted GATT sessions and 100
  wake callbacks with app/SDK, opaque process reference, scheduler/GATT phase
  times and fixed reason codes. A random 10-minute field marker can capture a
  no-wake trial; automatic upload is independently OFF by default and requires
  the phone owner to enable the disclosed setting.
- Target source adds boot-local connection/challenge/proof/result/ARMED/sensor/
  relay/terminal high-water counters plus last stage/session to the existing
  deferred retained status. A separate RTC access breadcrumb preserves the last
  stage across warm reset without changing the existing `GKDX` layout or doing
  MQTT/NVS work from BLE, sensor or relay callbacks.
- Backend schema 015 strictly validates and idempotently stores consented mobile
  bundles, resolves the current actor, joins verified Target canonical events
  and a fresh Target controller/reset breadcrumb, and renders the last proven
  and first missing stage in the administrator page. HA remains a low-cardinality
  operational summary and receives no attempt journal.
- Local Python, Flutter/Kotlin and ESP32-C6 build evidence is recorded in
  `hardware_test.md`. Policy PR #366 authorizes immutable feature
  `cdcc757b856bc503e9d85b874d67adc425c74a49` with the complete 108-path
  digest map, and feature PR #367 merged as actual main
  `c9aa85c31b0b7b1d04ea71970c720cf358805acc`. This is not yet NAS schema
  migration, APK installation, Target OTA or a physical owner/family trial.
  Uploaded-record automatic retention duration is also still an owner/privacy
  policy Gate and is disclosed in-app rather than silently invented.

## 2026-09-04 23:13 KST Target restart and OTA status readback

- Owner restarted the previously silent Target and reported that manual open works. A strict-TLS,
  exact-topic read-only MQTTS sample then received three consecutive live status messages from
  Target `c0feffe6ebac`. Current runtime is `2.1.442+main.g9ef6b82`, boot count 715, boot ID
  `b3e6ca04ca2346cfc42d6e5377074993`, uptime 1,230 seconds, RSSI -55 dBm and `IDLE`; relay command
  is false and the active-low relay pin is high/OFF.
- The current boot reports MQTT attempts/count 1/1, failures 0, volatile event outbox depth 0 and
  overflow 0. Backend verified-status followed the same boot at revision 1200 while Target advanced
  to 1201, and live bridge availability was `online`. Public `/live` and `/ready` returned HTTP 200
  for Backend `6aa8d188` with every readiness check true.
- The public signed Target manifest is still exactly `2.1.442+main.g9ef6b82`, build ID
  `main-442-9ef6b82b060d0a2e0ac7f3018ee3ae93db0536e2`, and `origin/main` is the same commit. Therefore
  a new OTA request on this runtime selects `UP_TO_DATE` and does not reinstall the same image. The
  powered-but-silent recovery candidate remains uncommitted/unpublished and is not installed.
- Runtime version equality, more than 30 seconds of safe IDLE uptime and working Wi-Fi/MQTT are
  strong evidence that the installed 442 image is operable and would have passed its pending-image
  health window if this boot entered one. They do not prove that the owner's latest OTA action
  downloaded an image or directly expose the running partition's ESP-IDF `VALID` state.
- The current reset reason is `BROWNOUT`, not a planned OTA/software restart. Because installed 442
  does not retain boot diagnostics, the previous boot 714, planned-restart marker, coredump and exact
  cause of the earlier silence cannot be recovered after the fact. The current boot also has no
  last-terminal summary; if the reported manual open occurred after boot 715, its Activity evidence
  remains unproven on the installed release.
- The probes connected and subscribed only. They sent no command, OTA trigger, Target restart,
  relay action, broker/HA mutation or configuration change.

## 2026-09-04 GATT v2 fast-path source candidate

- 최신 Android/Target 정상 경로를 `Fast TX CCCD 1회 → fresh challenge → signed proof → FSM-bound result`로 축소했다. 기존 v1 대비 CCCD 두 번과 Client/Target Hello 왕복을 제거한다.
- v2 선택 뒤에는 v1으로 재시도하지 않는다. v1은 모바일과 Target 독립 OTA를 위한 한 release N/N-1 전환 shim으로만 남으며 fast characteristic이 모두 없는 구 Target에서만 새 앱이 선택한다. Fast RX/TX 중 하나만 보이는 부분 서비스는 fail-closed한다.
- Android private key는 계속 AndroidKeyStore 안에 있고 Target은 signed ACL public credential만 보유한다. v2도 session/nonce를 매번 새로 생성하며 `SGKCHAL2`/`SGKPRF02` domain separation, 5초 deadline, single-use proof와 actual FSM commit-before-OK를 유지한다.
- Native/contract 16 tests, Android `:app:testDebugUnitTest` 19 suite/75 tests와 ESP32-C6 personal-production compile이 통과했다. 해당 Target 빌드는 예제 secrets를 사용한 source compile proof일 뿐이다. CI, signed artifacts, Target OTA install/reboot/health, APK 설치와 동일 휴대폰 반복 latency 측정은 아직 수행하지 않았다.

## 2026-09-04 GATT v2 trusted-policy authorization candidate

- Immutable feature `b5afa8f5660c53517e9bfabf18b5560ac874372d` is bound to a complete 102-path persistent policy bundle. The sole protected-byte change is `.github/workflows/deploy.yml`, whose exact Target build-input hashes cover the five changed firmware inputs.
- This policy-only branch authorizes no artifact or runtime action. Hosted policy review/merge, feature merge-connection and fresh CI, final actual-main policy rotation, signed Target/mobile publication, installation and physical latency evidence remain separate Gates.

## 2026-09-04 GATT v2 merged source and final policy rotation

- Policy PR #352 and feature PR #353 were merge-committed normally. Actual feature main is `3bcac6e7ee66d0f7a9a60be1233e6d5bb63bf957` and contains immutable feature `b5afa8f5660c53517e9bfabf18b5560ac874372d` in its ancestry.
- Feature PR hosted gates passed: Android build/unit/native GATT, firmware canary, OTA P0, canonical protocol vectors and trusted workflow policy. These prove source/build contracts, not signed personal publication or physical runtime.
- The final policy candidate retires the feature transition identity and pins one `current-main-baseline` to actual feature main with all 102 protected bytes unchanged. Its local 42-policy and full 344-test suites passed with one declared environment skip, and the live verifier approved all 102 GitHub objects. Final-policy hosted review/merge and subsequent exact-main personal Android/Target publication remain pending.

## 2026-09-04 live GATT v2 MQTT diagnosis

- At 13:21–13:23 KST, a bounded read-only client received live Target status from
  `gatekeeper/v1/targets/c0feffe6ebac/status`. The installed Target identified itself as
  `2.1.442+main.g9ef6b82`, boot count 713, IP `192.168.0.190`, RSSI -55 dBm and `IDLE`.
  Status revision advanced from 213 to 249; MQTT connect attempts/count were 1/1, failures 0,
  volatile RAM outbox depth 0 and overflow count 0. The status does not expose the separate
  durable NVS queue depth, so it does not by itself prove that no older canonical event is pending.
- The same revision 249 immediately appeared on the Backend-owned
  `gatekeeper/v1/ha-bridge/c0feffe6ebac/verified-status`, while retained bridge availability
  was `online`. Public Backend `/live` and `/ready` were HTTP 200 at deployed Backend
  `6aa8d188`; every reported check, including MQTT, collector and evidence integrity, was true.
  This proves the current Target → broker → Backend HMAC verification → HA bridge MQTT path is
  communicating. It does not prove the Home Assistant frontend rendered the entity because its
  authenticated API/browser session was unavailable to this WSL task.
- GATT v2 did not change `MqttManager`, `OfflineEventQueue`, the main-loop network scheduler or
  Backend MQTT/HA code. MQTT deliberately retains the `gatekeeper/v1/...` namespace; the `v2`
  label applies to the local BLE authentication exchange, not to MQTT topics.
- The existing access-critical deferral predates GATT v2. During GATT authentication, ARMED,
  relay hold and cooldown, status snapshots are coalesced in memory and socket work resumes only
  after the safe IDLE state. Therefore HA may show only IDLE even though revision advances, and
  Activity appears only after the terminal event drains. At the observation point the current
  boot reported no last terminal event. If a door cycle had already completed after boot 713,
  the remaining incident is terminal-event production/drain rather than an MQTT connection loss.
- The diagnostic client authenticated with no broker username or password and was allowed to
  read the exact Target and HA-bridge status topics. This independently confirms transport but
  also leaves a production confidentiality/ACL hardening issue; no broker configuration was
  changed during this diagnosis.

## 2026-09-04 19:49 KST Target heartbeat outage follow-up

> 아래 항목은 고장 관찰 당시 설치본과 source gap의 진단 snapshot이다. 같은 날의
> `Target self-recovery and HA Activity source candidate`가 source-level gap을 대체하지만,
> 새 firmware 설치와 현장 recovery 결과는 아직 확인하지 않았다.

- The owner-provided Home Assistant device page showed the shared controls disabled and every raw
  firmware/uptime/heap/RSSI/config entity unavailable. Bounded read-only MQTTS observations from
  19:51 through 19:57 KST repeatedly connected to the public broker with CONNACK 0 but received
  only retained `gatekeeper/v1/ha-bridge/c0feffe6ebac/availability=offline`; no live Target
  `/status` and no Backend `/verified-status` arrived. Public Backend `/live` and `/ready` remained
  HTTP 200 with database, MQTT subscriber, collector and evidence-integrity checks true. This is a
  real Target status-path outage, not only a Home Assistant rendering or stale-discovery problem.
- The earlier 13:21--13:23 sample proves installed firmware `2.1.442+main.g9ef6b82` and MQTT were
  working on boot 713 before the outage. The current observations cannot distinguish loss of Target
  power, a panic/hard hang followed by failed recovery, Wi-Fi association/recovery failure, or
  Target-side MQTTS reconnect/provisioning failure. A crash that rebooted and successfully rejoined
  would expose a boot count of at least 714, but no such status or boot message was observed.
- Home Assistant raw diagnostics use a 30-second expiry. Backend deliberately publishes the shared
  bridge availability retained `offline` when HMAC-verified status is absent for 90.25 seconds.
  One normal v2 GATT/access critical section is bounded below that window, so it cannot by itself
  explain this persistent condition; chained sessions or a wedged GATT/FSM state remain distinct
  possibilities.
- Recovery handling is partial: normal GATT/FSM deadlines, relay independent cutoff, a 15-second
  Wi-Fi auto-reconnect watch, TLS socket cleanup and five-second MQTT retry are implemented. The
  loop task is not explicitly enrolled in or fed to a task watchdog, MQTT TLS connect remains
  synchronous with the pinned client's 30-second TCP and 120-second handshake defaults, and all
  Wi-Fi/MQTT/OTA maintenance is skipped while `accessCritical` remains true. These gaps permit a
  powered-but-silent state that the Backend can detect but cannot remotely recover or classify.
- Target LWT, online availability and boot diagnostics are passed to PubSubClient with
  `retain=false`, despite source log text and older wiki statements describing retained boot
  evidence. A late observer therefore cannot recover the last reset reason or coredump evidence.
  Backend `/ready` also does not require fresh Target status by default, so its green result is not
  Target-online proof.
- The least destructive discriminator is to preserve the current state and check, at the Target
  site, for the BLE advertisement, `SmartGatekeeper-Recovery` SSID and the router DHCP association.
  If a power cycle becomes necessary, an exact-topic live subscriber must already be running so the
  first new boot count, reset reason, planned-restart value and coredump summary are captured. No
  command, publish, Target restart, relay/door operation, broker change or HA change was performed.

## 2026-09-04 Target self-recovery and HA Activity source candidate

- The powered-but-silent firmware gaps are implemented locally: generation-bound asynchronous DNS
  expires at five seconds, while TCP 4 seconds, TLS 8 seconds and MQTT read 3 seconds run in one
  bounded worker that exclusively owns the secure client/PubSubClient. Loop and worker use the
  45-second task WDT. Loop adopts only a matching request/Wi-Fi generation and rejects a late or
  cancelled result as stale; reconnect continues indefinitely with capped 5--30 second backoff.
- Continuous Wi-Fi outage observation, 30-second authenticated recovery-AP escalation and TLS
  invalidation by outage generation remain outside access control. Recovery-initiated
  `ASSOC_LEAVE` events no longer overwrite the last unplanned disconnect reason.
- Fast-v2 GATT connection/start/write/overflow state is rechecked before each network owner.
  A signed MQTT arm/manual callback discards stale pre-command telemetry and forces the main loop to
  recompute the access guard before OTA. Forced OTA commands are queued rather than running HTTP in
  the MQTT callback. Periodic/forced/local OTA refuses to start another TLS client while the MQTT
  worker is active, and access/link-generation changes cancel or stale-reject that worker.
- Unverified GATT ingress has one shared 10-second lease. Expiry disconnects only that transport,
  cleans to IDLE and resumes network work without rebooting. Short quiet gaps do not renew the
  epoch; 30 continuous quiet seconds are required before rearm, preventing reconnect churn from
  starving MQTT/OTA. A verified action generation instead receives its own 85-second physical
  lease. Only a wedge in that verified phase performs relay-OFF cleanup, GATT/signed-MQTT
  `INTERNAL_ERROR`, an `access_critical_timeout` breadcrumb, evidence checkpoint and controlled
  restart. Internal failure is no longer mislabeled as proof expiry.
- Canonical terminal checkpointing first appends older volatile records behind NVS. If NVS cannot
  accept the reserved terminal, the exact remaining FIFO including that terminal must commit to a
  checksum-bound generation of an RTC_NOINIT A/B journal. Replacement writes the inactive slot and
  commits magic last, so a torn update restores the prior generation. Restored records remain
  journaled until each front record publishes or migrates to NVS; repeated software reset may
  replay but must not silently lose the terminal. RTC remains a cold-power-loss limitation.
- `evidence_persistence_failed` carries across repeated software resets. Successful retained boot
  diagnostics acknowledge only a previous-boot failure; a new same-boot failure remains latched for
  the next reset. Signed reboot also waits beyond the inbound PUBACK boundary for main to block new
  GATT auth, drain callbacks, abort only unverified ingress, recheck the physical state and
  checkpoint evidence before restart.
- Raw pre-session disconnect/malformed/overflow traffic has no canonical session ID and therefore
  cannot create a zero-session terminal that blocks the queue. A duplicate frame after an action is
  already committed returns only a replay transport result; it cannot execute twice, synthesize a
  failure terminal or clear the verified lifecycle actor.
- Target retained availability is explicitly transport-only because PubSubClient cannot expose
  SUBACK refusal. Backend/HA authority stays on fresh HMAC-signed status. Backend readiness can
  require that freshness and reports it from one consistent snapshot.
- The missing strict broker ACL rules for Backend HA Activity publication/readback, Home Assistant
  Activity read and event discovery were added to repository policy. The schema-013 worker now marks
  a row delivered only after local QoS 1 completion **and** the exact non-retained event is routed
  back by the broker; retained/wrong-topic/wrong-payload echoes are rejected. This closes the Paho
  1.6.1 negative-PUBACK false-success gap in source, but the NAS ACL must be installed and read back
  separately.
- Local tests and a clean ESP32-C6 personal-production build prove source/build compatibility only.
  Trusted protected-byte authorization, GitHub publication, Backend/NAS ACL deployment, Target OTA
  install/reboot/health and physical recovery/latency evidence remain separate Gates. Per the owner's
  direction, no live Target, relay, door, broker or HA state was changed in this work.

## 2026-09-03 crash-durable access Activity candidate

> 이 절의 NVS-only/PUBACK-only 설명은 2026-09-03 당시 후보 기록이다. 현재 source 계약은 위
> 2026-09-04 절의 ordered NVS + RTC A/B journal과 exact broker-routed receipt로 대체됐다.

- 첫 post-install manual terminal과 HA entity-specific Activity가 실제로 갱신됐고, owner가 이번에도
  `[Gatekeeper] 최근 출입 결과` 변경을 확인했다. 이는 signed status→Backend→HA latest-result 경로의
  양성 runtime 증거지만 연속 모든 event의 무손실이나 관리자 이력까지 단독으로 증명하지 않는다.
- 기존 후속 후보의 signed MQTT canonical terminal은 volatile outbox에 먼저 들어가므로 relay 완료와
  NVS spill 사이 reset에서 잃을 수 있었다. 이제 terminal callback은 MQTT/TLS를 호출하지 않은 채
  exact HMAC record를 8-entry NVS queue에 먼저 commit하고, NVS 실패 때만 16-entry RAM outbox를 쓴다.
- Backend schema 013은 canonical access history와 HA projection outbox를 한 transaction으로 commit한다.
  독립 worker가 oldest pending row를 QoS 1/non-retained로 전송하고 PUBACK 뒤 완료 표시하므로 API/broker
  restart 후에도 미완료 projection을 재시도한다. PUBACK 뒤 DB mark 전 crash의 중복 가능성을 허용하는
  at-least-once이며, stable marker로 동일 event를 식별한다.
- Target publish는 여전히 PubSubClient QoS 0이고 queue는 유한하다. 따라서 이 후보는 reset과
  Backend commit/publish crash gap을 닫지만, 무한 broker outage나 Target→broker 단절을 포함한 절대
  exactly-once는 아니다. Application-level Backend ACK 및 overflow soak는 열린 강화 Gate다.
- Focused Backend 38 tests, full Backend 203 tests, 실제 MariaDB migration 17 tests와 personal-production
  ESP32-C6 build가 통과했다. trusted-policy rotation, normal merge,
  Backend schema 013 배포, Target OTA/install/reboot/health와 연속 live admin/HA readback은 아직 남아 있다.

## 2026-09-03 crash-durable access Activity policy candidate

- Immutable feature `ca2977638c535aa8ba7bc4ddbeb07342051d1f50` persists each signed MQTT
  terminal to the bounded Target NVS queue before returning and commits Backend canonical history plus
  schema 013 HA projection outbox atomically. MQTT remains deferred to the single safe-state owner.
- The trusted inventory expands from 100 to 102 paths for the schema 013 up/down migrations. The sole
  `crash-durable-access-ca29776-persistent-baseline` binds all 102 normalized digests; 16 feature paths
  differ and the remaining 86 retain trusted-main bytes. Seven workflows and the empty local-Action
  inventory are unchanged.
- This is policy/source authorization only. It does not publish, migrate NAS, deploy Backend, install
  Target firmware, operate the relay or prove a physical access. Home Assistant delivery is durable
  at-least-once, while Target QoS 0, finite queue overflow and live repeated correlation remain open Gates.
  The 42 focused policy tests and all 343 repository tests passed locally with one declared
  environment-only skip.

## 2026-09-03 signed MQTT terminal-history correction candidate

- 첨부 관리자 화면은 01:31:26 `MOBILE_REMOTE`를 이승환·401호의 legacy
  `서버 전송 접수`로만 표시했고, 첨부 HA Activity에는 같은 시각의
  `[Gatekeeper] 최근 출입 결과` 행이 없었다. 문이 열린 owner 관찰과 함께 보면
  Backend command 접수와 물리 릴레이 동작은 있었지만 signed terminal summary가 갱신되지 않았다.
- 원인은 배포된 terminal summary producer가 verified Local GATT lifecycle에만 묶여 있고,
  signed MQTT `arm`/`manual_remote` command session은 relay/session terminal까지 추적하지 않은
  것이었다. 따라서 Backend-only HA marker 배포만으로 이 경로를 고칠 수 없었다.
- Source candidate는 command callback에서 session/mode만 RAM tracker에 시작하고 FSM callback에서
  phase를 메모리로만 기록한다. MQTT/TLS publish는 계속 IDLE safe-state의 단일 owner가 수행한다.
  Signed arm 성공 `0x1e`, signed manual 성공 `0x18` terminal이 HMAC status로 전송되고 Backend/HA는
  기존 Local GATT `0x1f`/`0x19`와 함께 성공으로 해석한다.
- 관리자 화면은 signed terminal을 `모바일 수동 문열기` 또는 `모바일 출입 준비`로 구분하고,
  HA는 새 boot/sequence marker로 세션당 한 번 Activity를 전진시킨다. Native C++ core와 focused
  Backend/HA/admin 73 tests, 추가 UI/SQL 3 tests, `esp32c6_personal_production` build가 통과했다.
- 아직 source/build 후보이며 protected-policy rotation, hosted merge, Backend 배포, Target signed OTA
  install→reboot→health, 새 실제 출입 1회의 관리자 terminal row와 HA Activity 행은 남아 있다.

## 2026-09-03 asynchronous MQTT access-history visibility deployed

- The owner repeated a manual local open at about 01:00 KST and observed the
  physical door open, while Home Assistant added no Activity timestamp. The
  deployed state entity renders only `value_json.state`; access-critical MQTT
  deferral can collapse relay/cooldown snapshots into a final `IDLE`, so a new
  `IDLE -> IDLE` access is invisible to that entity.
- The deployed correction keeps all MQTT socket work outside authentication,
  sensor, relay and cooldown. Backend projects only the HMAC-covered terminal
  boot count/sequence into a privacy-safe unique marker plus success/terminated,
  and new `[Gatekeeper] 최근 출입 결과` discovery uses that changing value.
  Repeated periodic status for the same terminal does not create duplicate HA
  Activity rows.
- Focused Backend, discovery-migration and Target network-deferral tests passed
  59/59, and the full Backend suite passed 194 tests with two declared skips.
  After trusted-policy rotation, repository discovery passed all 342 tests with
  one declared environment-only skip. Policy PR #340, feature PR #341 and final
  policy PR #342 passed hosted checks and merged normally; exact feature main is
  `a87ef21dc9f66b227831066f45fab8cf0176a0e7`.
- Owner-approved Backend run `33654112042` published immutable images and
  deployed that exact feature main. Deployment evidence reports
  `status=deployed`, matching `source_sha`, loopback readiness and public
  readiness passed. Independent strict-TLS `/live` and `/ready` returned HTTP
  200 for the same SHA, with MQTT and the access-event collector true along
  with every other readiness check.
- Backend startup republishes all retained discovery including the new
  `[Gatekeeper] 최근 출입 결과` entity by source contract. A credentialed
  broker readback and one new owner-observed access/HA Activity row remain the
  final runtime UI Gate; deployment/readiness alone does not claim that row.
  No Target or mobile OTA is required by this Backend/HA-only correction.

## 2026-09-02 transient mobile access-ready notification correction

- The observed morning-stale `출입 준비 완료` notification is explained by
  the current native result notifier using only Android `autoCancel`, which
  removes a notification after a user tap but supplies no lifecycle timeout or
  session/region cancellation.
- The source candidate bounds this transient ARMED notice to 65 seconds,
  enables OS `FIRST_MATCH | MATCH_LOST`, dismisses on a valid match-lost exit
  without dispatching access, and dismisses when exact-session Backend polling
  finishes normally, terminally or at its bounded deadline. Scan errors do not
  infer exit, and exit projects to mobile waiting rather than failure.
- This changes no Target proof, ACL, relay, sensor, Backend, HA or OTA recovery
  contract. Local Flutter analysis and 97 tests, targeted Android JVM 60/60,
  repository contracts 342/342 with one declared skip, and diff checks passed.
  Protected merge, signed mobile OTA publication, replacement installation on
  each phone and screen-off area-exit/normal-door observation remain separate
  Gates.

## 2026-09-02 HA verified access-state availability deployed

- Policy PR #335, feature PR #336 and final-policy PR #337 passed their
  required checks and were merge-committed normally. Exact feature main is
  `993c1b6097992bce9fc4f7791a3033f9a34c7f9e`; final policy main is
  `6530d5ca7facf0faee82d4b2944e7ddd65986047` with the sole
  `current-main-baseline`. All 100 protected normalized blobs match the exact
  feature main.
- Owner-approved Backend run `33642436897` passed Backend security, MariaDB,
  evidence verification, exact image publication and NAS deployment. Public
  `/live` and `/ready` returned HTTP 200 for exact build `993c1b6`, with every
  reported database, schema, MQTT, access-event collector, runtime-secret,
  authentication, ACL, actor-reference, evidence-integrity, legacy-retirement
  and build-identity check true.
- Strict-TLS MQTTS readback received the retained Home Assistant discovery for
  verified `state`, `door_binary` and `pre_armed`; all three now omit the old
  30-second `expire_after` and consume the Backend `verified-status` topic. The
  dedicated connectivity discovery also has no expiry and consumes retained
  bridge availability, which read back as `online`.
- A fresh non-retained verified projection reported Target boot count 695,
  status revision 29189, `IDLE`, unarmed and relay OFF/pin level 1. This proves
  the corrected discovery is live against a healthy signed Target projection;
  it does not replace a rendered Home Assistant UI observation or a fresh
  physical access cycle longer than 30 seconds.
- Signed access-event collection and actor projection remain ready. Historical
  events that were never collected before Backend N cannot be reconstructed
  from unsigned Home Assistant state history. One new family-phone access is
  still required to confirm the resulting administrator row/name and mobile
  completion rendering end to end.

## 2026-09-02 authenticated actor/result final-main publication and rollout

- Policy PR #332, feature PR #333 and final-policy PR #334 were each merged
  normally without an administrator bypass, squash, rebase or force update.
  Final `main` is `10d7a1f2e38ed467143db05d5662ae24d575eda5` with the sole
  `current-main-baseline`; all 100 protected runtime blobs remain identical to
  immutable feature `23e28e14cf79e618070d0ea3543bf92910ca9558`.
- Target run `33555893409` built and atomically published exact-main personal
  firmware `2.1.422+main.g10d7a1f`, build ID
  `main-422-10d7a1f2e38ed467143db05d5662ae24d575eda5`. NAS stage/readback,
  signed schema-v2 metadata, immutable encrypted artifact, public HTTPS
  pointer and previous-valid preservation all passed. Independent readback
  verified the Ed25519 signature, AES-GCM envelope and plaintext hash.
- Mobile run `33555893523` built, production-signed and atomically published
  exact-main personal mobile OTA `1.0.0-g10d7a1f` / `38501` to both primary
  and fallback roots with HTTPS readback and previous-valid preservation.
  Publication is not phone installation; neither the owner's nor wife's phone
  has been observed running this APK in this rollout.
- Immediately before local Target recovery, a fresh non-retained status showed
  installed `2.1.419+main.g7981498`, boot count 690, `IDLE`, unarmed and relay
  OFF at pin level 1. The first authenticated station-local
  `/recovery/enable-ap` attempt could not establish TCP port 80 from either WSL
  or Windows. It produced no HTTP response; no manifest or firmware bytes were
  sent and no retry was made. A later status confirmed the same firmware, boot
  and safe state. The periodic signed HTTPS path subsequently installed exact
  `2.1.422+main.g10d7a1f`: at 2026-09-02 22:35 KST two fresh non-retained
  samples from boot count 695 showed a new boot ID, uptime already above
  26,042 seconds and increasing, `IDLE`, unarmed, relay command OFF/pin level 1,
  signed access-status revision and access key ID `a1`. This passes exact image,
  reboot and long post-boot safe-state observation; it does not measure relay
  contacts or physical door travel.
- The owner then reported successful access from both the wife's and daughter's
  phones. This is owner-observed multi-phone functional evidence supporting the
  asynchronous access-path correction, but it is not an instrumented latency,
  GPIO, contact or door-leaf measurement and does not prove which mobile APK
  version each phone was running.
- Backend N is not deployed in this evidence point. Public `/live` on
  2026-09-02 still reported old build
  `e62b681fe9f4ce52e5e5bdb1a795ef6a3ac532d0`; `/ready` returned HTTP 503 with
  `access_event_collector=false` while database, schema and MQTT checks remained
  true. The owner's HA history showed `IDLE -> unavailable -> IDLE` intervals
  of about 31 seconds during access. That is consistent with the old bridge's
  30-second entity expiry while the new Target deliberately defers MQTT during
  the access-critical phase. The source correction now removes that legacy
  expiry from verified state/relay/pre-arm entities and delegates staleness to
  the retained 90.25-second bridge availability watchdog; raw diagnostics keep
  their 30-second expiry. Backend N also consumes signed deferred events, but
  neither correction is live until a new reviewed Backend is safely deployed
  and retained discovery is republished.
- The root-owned NAS
  `access_event_ref_keys.json` and exact runtime keys must be provisioned before
  the restricted deployment can safely run. The live broker's anonymous-read
  drift and HA principal ACL installation/readback also remain open. Therefore
  the admin actor display, mobile exact-session completion and verified HA
  projection are published source artifacts, not live end-to-end behavior yet.
- An owner-approved rerun of Backend run `33555467447` passed all hosted tests,
  evidence verification and exact-image publication, then migrated the database
  to schema 012. API creation failed because the root-owned
  `/volume1/docker/smart-gatekeeper-backend/secrets/access_event_ref_keys.json`
  bind source did not exist. The wrapper removed the partial stack without
  deleting volumes and retained a pre-migration backup, but the public service
  returned 502 until an emergency rerun of the last verified `e62b681` deploy
  job restored it. Post-rollback public `/live` and `/ready` both returned 200,
  exact build `e62b681fe9f4ce52e5e5bdb1a795ef6a3ac532d0`, and readiness again showed
  `access_event_collector=true`. Do not retry Backend N until the root-owned
  evidence key file and exact runtime contract are provisioned and verified.
- The owner subsequently provisioned the root keyring/runtime contract and
  installed the reviewed root deployment wrapper. A final owner-approved rerun
  of `33555467447` deployed exact feature-main build
  `b29cb2497c4adf151b3d60eeab31acb525555340`. Public `/live` and `/ready`
  returned HTTP 200 for that exact identity, with database/schema/MQTT/event
  collector/runtime secrets/admin/ACL/access actor reference/access evidence
  integrity/build checks all true. MQTT readback received retained bridge
  `online` and a fresh non-retained `verified-status` for Target boot 695,
  revision 27868, IDLE and relay OFF/pin 1. Because the Backend publishes that
  projection only after verifying the Target HMAC with its configured door
  scope, this proves the NAS `a1` key matches the installed Target key without
  exposing either value.
- Retained HA state discovery from the deployed build still contains
  `expire_after: 30`. Therefore signed history/actor ingestion and verified
  projection are live, but the reported false unavailable interval remains
  reproducible during a longer access-critical MQTT deferral. The tested local
  correction that removes expiry from verified state/relay/pre-arm entities is
  not part of deployed `b29cb249`; it still requires protected publication,
  Backend redeployment and retained discovery readback.
- No agent-controlled sensor approach, GPIO voltage, relay contact, actuator
  travel or door-leaf measurement was exercised. The owner's access observation
  is recorded separately from those still-open physical acceptance Gates.

## 2026-09-02 authenticated actor and post-ARM completion source candidate

- The source candidate gives each successfully verified Local GATT session a
  door/session/credential-bound HMAC actor reference. Target schema 1.1 events
  and access status are HMAC authenticated; raw credential IDs, resident names,
  proofs and secrets do not enter MQTT or immutable access history. The admin
  read-side shows a name/unit only when the ref has one exact current
  credential match. Unsigned legacy Target rows remain visibly unverified.
- Signed status adds stable Target boot/count and revision high-water, latest
  terminal session/code/reason/actor and phase bits for proof, armed, sensor,
  relay ON/OFF and failsafe. A normal completed summary requires all five normal
  bits and no failsafe. Exact replay does not renew freshness, and stale boot,
  revision rollback or payload conflict fails closed.
- The mobile app carries the exact UUIDv4 session returned by native action 1,
  signs a fresh 80-byte AndroidKeyStore read proof, and polls one session every
  four seconds for at most two minutes. It separates sensor waiting, relay
  active, cooldown and `next authentication ready`; the last state requires a
  matching signed terminal plus fresh `IDLE`, relay OFF and the configured OFF
  pin level. Each proof nonce is durably consumed after verification. It does
  not automatically restart scanning or issue another access authentication.
- Target MQTT/TLS emission remains outside the access-critical GATT/sensor/relay
  phase through the bounded outbox and single PubSubClient owner. Backend MQTT
  callbacks likewise enqueue for event/status DB workers. Home Assistant access
  state consumes a MAC-verified allow-list projection, while raw IP/RSSI/
  distance/config diagnostics remain a broker-ACL-protected, non-authoritative
  display path. NVS/config access timings are clamped to 60 seconds ARMED plus
  one second relay hold, 250 ms true-failsafe grace and at most ten seconds
  cooldown. Once one verified session is ARMED, every new ClientHello is
  rejected as busy through sensor wait, relay hold and cooldown; authentication
  resumes only at fresh IDLE with relay OFF. An unverified second phone cannot
  change the original actor, deadline, phase, causation or sensor/relay path.
  The runtime lifecycle has one five-second auth window; the compile-time
  bound retains an additional five-second safety margin and remains below 90
  seconds. A 120-second MQTT keepalive and 90.25-second HA connectivity
  watchdog therefore outlive it
  without weakening the 15-second HA command freshness check.
- Because Target MQTT is intentionally deferred through the access-critical
  phase, mobile intermediate states are best-effort observations, not a live
  stream. The UI may move directly from sensor wait to final next-auth-ready
  once signed terminal plus fresh IDLE arrive.
- The Home Assistant relay binary sensor keeps its historical `door_binary`
  object/unique ID so existing entity-registry references migrate in place, but
  is named `[Gatekeeper] 릴레이 구동 상태` and has no door device class. Its ON
  state means only verified Target `RELAY_HOLD`, not contact, actuator or door-
  leaf confirmation.
- The latest terminal summary is same-boot RAM best-effort. Power loss before
  its signed status reaches Backend can leave the result unconfirmed; neither
  DB nor mobile reconstructs success. No door-contact sensor exists, so signed
  sensor/relay completion is not physical door-leaf confirmation.
- Safe N/N-1 rollout provisions one reviewed key/key ID to both Target release
  environments and the NAS keyring, installs and health-confirms Target N first,
  then deploys Backend N and mobile N. Target N-1 rollback preserves existing
  access/OTA but makes the new actor/terminal evidence unavailable instead of
  fabricating `complete`.
- After the explicit signed-status readiness cutover, Backend requires one
  persisted HMAC-verified Target status on each current MQTT connection. An
  old-generation in-flight result cannot satisfy a reconnect, and invalid MAC
  traffic is ignored without poisoning health; a Target/NAS key mismatch then
  remains unready. The default cutover-off mode preserves Backend N / Target
  N-1 deployment and rollback until Target N health plus matching status is
  observed. Broker ACL installation plus Backend publish/HA readback remains a
  distinct live Gate.
- Native adversarial coverage holds verified session A in `ARMED` while B sends
  ClientHello, no proof and an invalid proof. B receives busy before challenge,
  while A keeps its original deadline, actor, phase and causal parent and still
  completes the sensor/relay/cooldown path. The focused GATT/FSM source suite
  passed 25/25, and the personal-production ESP32-C6 build passed at
  75,848/327,680 bytes RAM (23.1%) and 1,798,862/7,340,032 bytes application
  flash (24.5%). The one extended OTA failure is the intentionally unrotated
  protected-source digest, not a firmware compile/runtime failure.
- This is source-contract status only. The new release-environment key exists,
  but the matching root-owned NAS keyring file is not asserted installed; the
  live broker's previously observed anonymous/ACL drift is not asserted fixed,
  and no Backend/HA/mobile/Target deployment or new physical access cycle is
  claimed here.

## 2026-09-02 access-critical MQTT deferral candidate

- Administrator canonical history showed local GATT `ARMED` at about 00:12:09
  and `SENSOR` about seven seconds later. A separate Home Assistant state history
  showed `ARMED` 00:12:10, `RELAY_HOLD` 00:12:17, `COOLDOWN` 00:12:18 and `IDLE`
  00:12:23. The owner excluded different approach behavior, blind-zone position
  and insufficient dwell through repeated same-method comparison and more than
  one second continuously in range.
- Source tracing found canonical QoS-0 MQTT/TLS writes inside GATT event draining
  before ultrasonic polling. The candidate replaces those direct access-path
  writes with a bounded 16-entry volatile FIFO, oldest-first durable NVS spill,
  one-event recovery flushing and latest-state telemetry coalescing. GATT,
  ultrasonic and relay/FSM work now precede all network work, which is forbidden
  through AUTH_PENDING, ARMED, RELAY_HOLD and COOLDOWN.
- The design deliberately keeps PubSubClient on the existing single loopTask
  rather than adding a concurrent MQTT task whose callbacks would race FSM, ACL
  and OTA state. Outbox depth/overflow are observable in boot/status telemetry.
- Seven direct source contracts, eleven related HA migration contracts, the
  18-test Target autopublish contract and all 78 OTA invariants passed. The
  personal-production ESP32-C6 build succeeded at 74,536/327,680 bytes RAM
  (22.7%) and 1,788,526/7,340,032 bytes application flash (24.4%). Full policy,
  review, exact-main signed publication and Target install/reboot/health remain
  separate Gates at this point; no physical latency improvement is claimed yet.

## 2026-08-31 Local GATT ultrasonic session isolation

- After the owner excluded manual remote open and asked to assume intact wiring
  and sensor hardware, source/timeline correlation identified a deterministic
  session-boundary defect: Local GATT action-1 retained the five-slot ultrasonic
  median from an earlier passage, while MQTT pre-arm already cleared it. Three
  retained valid samples could therefore satisfy a later session before three
  fresh measurements existed. This is high-confidence source/timeline
  correlation rather than canonical per-session event proof.
- The candidate resets ultrasonic history only after Local GATT action-1 is
  successfully accepted. Five invalid sentinels then require at least three
  fresh current-session valid samples before the 20-50 cm relay predicate can
  succeed. Rejected arms and action-2 are unchanged; ACL/proof, nonce/replay,
  relay interlocks, signed OTA, health and rollback boundaries remain intact.
- New session-isolation plus pocket-path regressions passed 8/8. The complete
  Hardwareless RC host suite passed 13/13, including its C++ protocol/FSM build
  and run. A combined session-isolation, pocket, Target OTA-autopublish and
  Hardwareless RC invocation passed 39/39. The `esp32c6` PlatformIO build
  succeeded at 59,200/327,680 bytes RAM (18.1%) and 1,745,602/7,340,032 bytes
  application flash (23.8%). The separate `esp32c6_personal_production` profile
  also succeeded at 67,096/327,680 bytes RAM (20.5%) and
  1,783,164/7,340,032 bytes application flash (24.3%).
- Full Python discovery ran 324 tests: 322 passed, one skipped, and only the
  expected fail-closed trusted-workflow-policy test failed because the
  protected `deploy.yml` digest rotation is still pending. Protected policy,
  reviewed CI, merge, exact-main signed Target publication and physical Target
  installation/reboot/health are separate Gates.
- No firmware was installed and no sensor, relay contact or physical door was
  exercised by this change. A fresh on-wall hands-free trial after exact-main
  OTA installation remains required; no deployed or physical success is claimed.

## 2026-08-31 off-site BLE ownership notification incident

- The owner reports the latest installed mobile app raised `BLE 비콘 스캔
  초기화 실패` with exact code `BLE_OWNER_EXCLUDED` while at work with no
  Gatekeeper Target present. This is not evidence of a Bluetooth, location or
  permission failure; no Target is a normal native-wake idle condition.
- Source tracing shows that enabled native GATT persists the native-request
  marker, while the Flutter foreground scanner still attempts mutually
  excluded legacy initialization. The existing direct-exception suppression
  and notification cleanup are insufficient for the observed runtime path.
- The planned correction separates native-wake idle from an active GATT lease,
  skips legacy scanner initialization when native wake is authoritative, and
  explicitly replaces stale failure UI without weakening cross-process BLE
  exclusion. The source candidate now implements the privacy-safe plugin state,
  explicit `nativeWake` scanner mode, cross-isolate error clear, neutral forced
  notification replacement and single-flight transition recovery.
- PR #318 passed Hosted Trusted, OTA P0, Flutter format/analyze/unit, targeted
  native GATT tests and Android canary build, then merged normally as exact main
  `d9100240c8c9c07faacd2b0c293b46e01462d3ad`. Mobile run `33380064991`
  built and pinned the exact source, verified the production Android signer and
  published signed `1.0.0-gd910024` / `36801` to both NAS OTA roots.
- Independent strict-TLS readback matched both public manifests byte-for-byte
  at SHA-256 `1ce61bf0...b4ace5` and both 55,119,001-byte APKs at SHA-256
  `0f183867...c8654f5`. Publication is not installation: the latest package is
  not yet confirmed on a phone, and the off-site no-Target soak plus subsequent
  real-Target native-wake/authentication recovery remain open physical Gates.

## 2026-08-30 administrator account-management deployment

- PR #303 passed Hosted Trusted, Backend/MariaDB and the complete 317-test
  OTA/schema Gate, then merged as exact main
  `05a58dc3785ca36924c062181a6a3bc114c68281`.
- The first protected deployment failed closed before Compose or migration
  because the root-owned NAS wrapper admitted schema 008 while the signed
  bundle required schema 009. The owner installed the reviewed wrapper at
  exact SHA-256 `8b0e230f...352f2a8`, preserving the preceding wrapper as a
  root-only backup; read-only status still showed the healthy prior release.
- Backend run `33316931652` attempt 2 then completed the owner-approved
  restricted-Tailscale deployment. Canonical evidence reported
  `status=deployed`, the exact source, and passed loopback/public readiness.
  Independent strict-TLS `/live` and `/ready` returned HTTP 200 for the exact
  build with database, schema, MQTT, runtime secrets, control/admin auth, ACL,
  legacy retirement and build identity all true.
- Name/unit editing, fail-closed user deletion, global recent access history
  and the 900-second personal reauthentication default are therefore deployed.
  Administrator browser rendering and one bounded edit/delete/history
  acceptance trial remain separate operator Gates; no user account was edited
  or deleted during deployment verification.

## 2026-08-31 mobile account lifecycle and schema-010 deployment

- PR #309 passed Hosted Trusted, Backend/MariaDB, OTA/schema and Android
  canary checks and merge-committed normally as exact feature main
  `1b701df93194029fb7be733a372f7ddb68f57e97`. Final policy PR #311 then
  passed Hosted Trusted and restored the protected actual-main baseline with
  administrator enforcement and strict required checks retained.
- Exact-main Backend run `33323849258` published immutable API/DB images. Its
  first NAS attempt failed closed before migration because the installed root
  wrapper admitted only the preceding schema generation. The owner installed
  the reviewed stable wrapper at exact SHA-256
  `66507318ad2b5b7fff6e4bdc6b3f2bd8994a97877be6500df9f218619ac0223e`;
  read-only status still showed the preceding deployed release ready.
- Attempt 2 then completed the restricted-Tailscale deployment, created a
  pre-migration backup, and applied the contiguous migration target `010`.
  Canonical evidence reports `status=deployed`, exact source `1b701df...`, and
  passed loopback/public readiness. Independent strict-TLS `/live` and `/ready`
  returned HTTP 200 for the exact build with every readiness check true.
- Native registration-only onboarding, server-first signed logout, reduced
  ordinary-user settings and console-assigned `TENANT_ADMIN` projection are
  therefore merged and backed by the deployed API/schema. Exact-main Target
  run `33323849255` also completed signed personal OTA publication for
  `2.1.399+main.g1b701df`. These are
  source, deployment and publication results. Exact-main mobile run
  `33323849352` also signed, atomically published and HTTPS-read-back personal
  OTA `1.0.0-g1b701df` / `35801`; independent primary/fallback manifest
  readback matched commit and APK SHA-256
  `bc4d24fdeacda655a1f1465f466abf15192c3287117965308abe1329cdc9faf3`.
  The subsequent policy-only actual main `4d906aee...` preserved the same
  feature blobs and completed its own exact-main publications. Current public
  pointers independently read back as mobile `1.0.0-g4d906ae` / `35901` with
  APK SHA-256
  `a5d3e9b332a36a85ea9ab1b7f06dd89dc318ab15b9abf693c00ece67d373667a`
  and Target `2.1.400+main.g4d906ae`; both manifests name exact commit
  `4d906aeeaab972e9abe07325fe3c8ba43febff8a`.
  Phone installation, visible logout/registration/admin acceptance and Target
  install/reboot/health remain separately recorded Gates.

## 2026-08-31 account deletion and fresh re-enrollment correction

- A current mobile build reproduced a user-visible failure after account
  deletion, fresh registration request and administrator approval. Source-level
  tracing and a failing regression identified the exact conflict: immutable
  `REVOKED` credential history for the same keyed phone locator was being treated
  as if it were a live credential during personal bootstrap.
- The candidate now admits a new AndroidKeyStore credential only when every
  different prior credential for that locator is terminal (`REVOKED`, `DISABLED`
  or `EXPIRED`). `ACTIVE`/`PENDING` conflicts, public-key uniqueness, explicit
  approval, exact tenant/door scope, ACL signing and Target apply gates remain
  unchanged. The old credential remains revoked and is excluded from the new
  signed ACL.
- Store-level and HTTP API regressions cover logout/account-row deletion,
  reapproval and fresh credential bootstrap. The complete Backend suite passed
  165 tests with two expected environment-only skips. The 317-test OTA and
  operations suite has only the three expected pre-authorization protected
  digest failures for the changed implementation and regression files.
  Protected policy/CI/NAS deployment are separate Gates; no phone, account,
  credential or live database mutation was performed during diagnosis.
- Policy PR #314 and feature PR #315 passed their protected checks and merged
  normally. Exact-main Backend run `33326079617` published digest-pinned API/DB
  images and deployed source `b0e1339c186bde81e2f4602ff426251b88e57db6`
  through the reviewed Tailscale/restricted-SSH path. Canonical evidence reports
  `status=deployed`, `loopback_ready=passed` and `public_ready=passed`.
- Independent strict-TLS requests returned HTTP 200 from `/live` and `/ready`;
  both named exact build `b0e1339c...`, and readiness reported database, schema,
  MQTT, runtime secrets, control/admin auth, ACL management, legacy retirement
  and build identity all true. This closes source/CI/deployment readiness.
- The owner subsequently confirmed that the freshly approved account completed
  `이 휴대폰 등록` and that a door-open request from that newly enrolled phone
  physically opened the installed door. This closes the exact post-deletion
  re-enrollment, replacement credential, Target ACL apply and one
  user-initiated physical door-cycle acceptance Gate for the observed trial.
  It does not establish repeated reliability, OEM background proximity,
  another resident phone, ultrasonic/sensor actuation, outage recovery or OTA
  install/reboot/health.

## 2026-08-30 credential-signed remote Home button rollout

- The owner-observed direct MQTT command opened the installed door. The mobile
  button failed separately at `GATT_DISCONNECTED` before every GATT protocol
  phase, so the Target MQTT/relay result is not evidence that the old mobile
  Local GATT button worked.
- The normal Home, advanced-control and hosted-shell button paths now request a
  Backend remote open. Native Android signs a fresh fixed-width request with the
  already-enrolled non-exportable AndroidKeyStore P-256 key; no shared API key or
  legacy tenant HMAC is placed in the control request.
- Backend v3 verifies the active credential, active tenant, exact active door
  grant, expiry and signature, consumes a durable database nonce, then reuses
  the existing per-Target signed MQTTS command path. Legacy HMAC v2 remains for
  N-1, and device-ID-only calls remain HTTP 426/no-effect.
- PR #285 merged as exact main `a78ec0c25e0e498eb1f9f83189279cccba236236`
  after Hosted Trusted, OTA/schema, Backend and Android canary checks passed.
  Its protected Backend run published immutable images and joined the NAS
  tailnet, but the installed root-owned schema-007 wrapper rejected the signed
  schema-008 descriptor before Compose, migration or cutover. No deployment
  success is inferred from this fail-closed result.
- The owner installed the corrected root wrapper at exact SHA-256
  `6baba70f...b16758`. Protected run `33309298877` then deployed exact source
  `07b3543a...36d7eb`, migrated the production database to schema 008 with a
  pre-migration backup, and passed canonical loopback/public readiness evidence.
- Independent strict-TLS `/live` and `/ready` requests returned HTTP 200 for
  `07b3543a...36d7eb`; every readiness check was `true`. Final policy main
  `f403e10c...113d3bc` mobile run `33309381350` and Target run `33309381357`
  signed, atomically published and HTTPS-read-back their personal OTA artifacts.
  Connected ADB subsequently verified exact installed mobile
  `1.0.0-gf403e10` / 33401 with the original first-install time preserved. The
  refreshed Home still reported access ready and ACL 594, but the Activity
  timeline classified all three owner attempts as `REMOTE_CONTROL_DENIED`.
  They were rejected at Backend credential authorization before MQTT publish;
  no retry was issued during diagnosis. Target install/reboot/health and the
  mobile authorization defect remain open.
- The owner-run aggregate NAS query then confirmed both tenant and door scopes
  differ and that the legacy command scope has zero active mobile credentials
  or grants. This is a code-scope defect, not missing production data: v3 now
  authorizes the AndroidKeyStore credential and exact grant in `ACL_PERSONAL_*`
  while leaving the already-working `COMMAND_*` signed MQTTS publisher intact.
  A regression with deliberately different scopes, a cross-Target rejection
  check and all 149 backend tests
  passed locally; review, protected CI, NAS deployment and a single bounded
  owner-triggered button trial remain open.
- Root discovery also passed every method outside the trusted protected-byte
  Gate; the policy test rejected the four expected changed protected blobs.
  This is the required separate policy-authorization boundary, not a reason to
  weaken workflow/digest enforcement.
- Policy PR #291 subsequently passed Hosted Trusted and merged as main
  `41d89fb`; that exact policy main was merge-connected without rebase or
  squash as `a5671be`. The reviewed protected bytes are unchanged and fresh
  feature CI is now the next Gate.

## 2026-08-30 fresh family-member registration rollout

- PR #295 restored the fresh-install registration projection and form, but the
  owner's first A24 submission failed before persistence. New installs use a
  UUID-shaped `GK-*` credential ID, while the request admitted only `DEV-*`
  and the legacy MariaDB locator is limited to 17 characters.
- The correction accepts the reviewed `DEV-*`/`GK-*` forms and derives one
  deterministic 17-character internal locator for longer values. Registration,
  status and credential bootstrap use the same mapping; existing fitting IDs
  are preserved and the raw high-entropy device ID is not stored in the legacy
  tenant row.
- Policy PR #296 passed Hosted Trusted and merged as `44f8879`; feature PR #297
  passed Hosted Trusted, Backend and OTA/schema checks and merged as exact main
  `f03acdfaad4fa2fad61439f58f318ddbc756d084`. Backend run `33314043691`
  completed the restricted Tailscale NAS deployment. Canonical loopback/public
  readiness and independent strict-TLS `/live` and `/ready` passed for that
  exact build with every check true.
- No registration was automatically retried. The owner's later submit and
  administrator approval reached the expected connected ADB projection:
  `스마트키 등록 준비 완료` and `이 휴대폰 등록`. This is the separate
  AndroidKeyStore enrollment step, not another tenant request. One owner tap,
  credential result, signed ACL Target ACK and daughter-device access remain
  unclaimed.
- The owner's one enrollment tap failed and the A24 remained
  `readyToEnroll`. Its bounded support report showed native healthy, no native
  blocking reason, zero doors and no ACL version. A production-shaped local
  reproduction returned HTTP 409 because the first owner's legacy row already
  holds the configured personal tenant's unique compatibility mapping.
- The source correction leaves that first mapping intact and keeps each newly
  approved family row unmapped while creating a distinct active public
  credential and exact shared-personal-door grant. Idempotency and the existing
  unapproved/cross-tenant/conflict denials are retained. Focused and complete
  Backend tests pass. Policy PR #299 and feature PR #300 passed protected
  checks; #300 merged as exact main
  `38b90e5febc525c96a4013b737850fd6a90235d3`. Backend run `33315099974`
  deployed it over the restricted Tailscale path with canonical loopback/public
  readiness. Independent strict-TLS `/live` and `/ready` returned HTTP 200 for
  that exact build with every check true. The owner's single post-deploy retry
  then produced `스마트키 사용 가능`, one registered door and ACL 608; the
  Activity timeline records phone credential registration at 22:53:15. Since
  access-ready requires an exact current snapshot ACK, credential enrollment,
  door grant and Target ACL synchronization pass. A later 22:53:40 remote-open
  entry proves Backend broker delivery only; physical door movement remains an
  owner-observation Gate.

## 2026-08-29 foreground Target detection dashboard candidate

- The Smart Key control screen now polls native GATT health once per second and
  renders a dedicated Target card for waiting, detected, authenticating,
  ARMED, failed, and disabled states. It displays latest event time/age,
  strongest callback RSSI, screen ON/OFF, durable session state, and
  presence-to-ARMED latency.
- The native bridge returns only a redacted latest-event summary. BLE address,
  credential ID and all authentication/key material remain outside Flutter.
  Events older than the native 45-second presence window return the card to
  waiting; the RSSI value is one `FIRST_MATCH` sample, not continuous distance.
- Focused and complete Flutter tests (43 total), targeted analysis, and two
  native redaction/projection tests pass locally. Production-signed APK
  publication, phone installation, and a visible real Target transition are
  still required before calling the user-facing behavior deployed or
  physically verified.

## 2026-08-30 GATT latency optimization candidate

- Issue #260 tracks the observed foreground baseline: presence-to-dispatch
  61 ms, native GATT session 4,801 ms and presence-to-ARMED 5,765 ms. This
  localizes the current delay after dispatch, but one run is not an accepted
  latency SLO.
- Android now requests high connection priority and ATT MTU 247, with a bounded
  750 ms negotiation wait and automatic MTU-23 fallback. The wire protocol,
  authentication proof, crash-safe no-replay boundary, feature kill switch and
  mobile/Target OTA paths are unchanged.
- Durable redacted phase timing and negotiated-link diagnostics are projected
  to the foreground Native Worker card. Android `gattworker.*`, targeted Flutter
  analysis, all 45 Flutter tests and all 317 repository contract tests pass
  locally with one expected skip. Production signed APK publication, phone
  installation and repeated connected before/after evidence remain required
  before accepting the candidate `<2.5 s` objective.

## 2026-08-30 authoritative mobile credential status candidate

- Issue #262 replaces the `Key & Tenant` card's legacy SharedPreferences
  projection. That old projection defaulted to `UNREGISTERED` and its submit
  button only stored name, room and `pending` locally; it did not submit a
  Backend tenant approval request.
- The candidate reads Android native `credentialProvisioned` and
  `localConsentValid` for key registration and displays a Target ACL version
  only when the latest authenticated GATT session returned a positive
  `activeAclVersion`. A native bridge failure is `상태 확인 불가`, not
  `미등록`.
- Tenant authorization remains Backend-owned and is not inferred in Flutter.
  This corrects operator visibility only; it does not create, approve, revoke
  or migrate any credential, tenant, ACL, Backend row or Target state.

## 2026-08-28 external Synology backend CI deployment candidate

### 2026-08-29 canonical CI deployment completion

- Owner validation installed wrapper SHA-256
  `30364e7a3442a6631d1a49adf7e129469838aeb9ee8bd8af3b894ef049b9abb7`
  as `root:root 0755` and retained the prior wrapper as a root-only recoverable
  backup. Read-only status before approval still reported the healthy deployed
  `db37772d` release.
- Exact feature-main run `33255038063` deployed source
  `d50b98f9c1e4e046fb62d1e8698c0ed2407291fe`, API digest
  `dff4fda6298a77a8cc9b712afd25f4849ad3f3aa02908919d3638d1089310738`
  and DB digest
  `bc3481867340ef3134dbddb435998f4438c497ecdf79683074b45abd352a2385`.
  Migration `up 007`, loopback/public readiness, canonical apply/status byte
  comparison and two-file evidence artifact upload all passed. The signed
  bundle SHA-256 is
  `5b12762281b6b6a246aeb3c3df7f065da18fe391b674633cdcebcd200b59eefb`.
- A separate WSL request after CI returned HTTP 200 from both `/live` and
  `/ready` with exact build `d50b98f`; every readiness check was true. Branch
  protection readback remains administrator-enforced and strict with exactly
  `Verify protected files against trusted base policy` required.

### 2026-08-29 live first-adoption boundary

- Exact-main status-only run `33234620284` at `d9ecc87e04fc2b0e57cc892e549b02ddce26184a` used the protected `production`
  Environment, ephemeral Tailscale OIDC identity, pinned private NAS endpoint
  and forced SSH dispatcher. The retained evidence is exactly
  `status=not-deployed`; all image publication and `apply` jobs were skipped.
- Immediately before the maintenance stop, public readback identified legacy API build
  `7c2764a1a16492ec1620079c8211b47287b1b3fd`: `/live` is HTTP 200, while
  `/ready` is HTTP 503 with every reported check true except
  `legacy_prearm_retired=false`. The owner then recorded and stopped exactly
  `gatekeeper-api` and `gatekeeper-db` without removing either container or
  volume. This opens the issue #190 first-adoption window but is not evidence
  of new-stack deployment. Recovery remains starting those same legacy
  containers until `status=deployed`, exact `source_sha` and readiness pass.
- Main run `33235108484` at `a0baab91f2e1a13643a25ce7f82485aca33dc269`
  passed backend/MariaDB contracts, evidence verification, exact API/DB image
  publication, provenance, signed bundle creation, protected approval,
  ephemeral Tailscale and restricted SSH. Its NAS `apply` then failed closed
  before Compose with `env: 'docker': No such file or directory`. The installed
  wrapper had resolved Synology's absolute Docker CLI but `compose_for_release`
  incorrectly asked `env` to execute the non-exportable shell function name
  `docker`. No deployment evidence or database rollback was claimed; legacy
  recovery and an absolute-CLI wrapper correction are required before retry.
- The corrected root-installed wrapper SHA-256 `5f108cc2...` was verified and
  exact-main run `33235596047` at `21a0124f6e4b5dfc300b205073e1b464066355e8`
  was owner-approved. It passed publication, provenance, signed bundle,
  Tailscale and forced SSH, then failed closed on the first exact API image pull
  with GHCR `unauthorized`; the NAS had no registry credential. Compose and
  migration did not run and DB rollback was not attempted. The owner restarted
  both retained legacy containers; their runtime state is `running`, public
  `/live` is HTTP 200 for build `7c2764a1`, and `/ready` is the known HTTP 503
  with only `legacy_prearm_retired=false`. Main
  `42b754d75863072e4ad0af32f2667ff54ceb050c` now streams the
  deployment job's short-lived `github.token` through a versioned envelope and
  confines Docker auth to the wrapper's per-attempt temporary directory. Its
  protected checks passed; at that point the new wrapper was not yet installed
  on the NAS and no deployment/readiness result was inferred from the merge.
- The owner subsequently installed the exact `afda60b4...` wrapper, stopped the
  retained legacy pair and approved feature-main run `33240731351`. Signed
  bundle verification, attestation, Tailscale OIDC, forced SSH, ephemeral GHCR
  authentication and both exact image pulls passed. Compose created the
  production networks and started the new DB, then DSM rejected the next
  container with `NanoCPUs can not be set` before migration. No DB rollback was
  attempted and no deployment/readiness result exists. The installed wrapper
  did not yet clean the partial project, so recovery must stop that new DB and
  restart the retained legacy pair without deleting the shared volume.
- The first correction used zero-valued Synology overrides for the portable
  base CPU limits. Hosted Compose rendering omitted them, but DSM Compose
  v2.20.1 preserved the zero value as a Docker `NanoCPUs` request. That
  assumption is now rejected; both deployment Compose inputs must omit `cpus`
  entirely while retaining memory/PID/capability/read-only hardening.
- Policy PR #216, policy-connected feature PR #215 and final policy PR #217
  all passed their required Hosted checks and merge-committed through final
  main `bb970bb68c365140b2b1717116fc19eac307cb59`. Exact feature-main backend
  run `33241850366` then passed tests, evidence, provenance and image
  publication and was owner-approved after exact wrapper installation and a
  new maintenance stop. The NAS pulled exact API digest `044a3ab1...` and DB
  digest `8f1baca0...`, recreated and started the production DB, then failed on
  the same `NanoCPUs` incompatibility before migration.
- The corrected wrapper automatically stopped and removed the partial
  production container and both project networks, explicitly without deleting
  volumes, and did not attempt DB rollback. Owner recovery restarted both
  retained legacy containers; external `/live` is HTTP 200 for build
  `7c2764a1`, while `/ready` is the expected legacy HTTP 503 with only
  `legacy_prearm_retired=false`.

- Final policy main `7a09a25ad01e21b7d0e515cbbf96bce2ca5af23a`
  admitted CPU-field-free feature main
  `b6cab8384efe7b5e046841ff84681b74d0cae113`. Protected run `33245672804`
  pulled the exact images, started the DB, and passed migration `up 007` with
  a retained pre-migration backup. The API was created but loopback `/ready`
  failed; cleanup removed the partial project without deleting external
  volumes, and DB rollback was not attempted. The retained legacy pair was
  restarted; public `/live` is HTTP 200 and `/ready` is its expected single
  legacy-boundary 503.
- Protected feature main `3fdc615833da68af22623eefafc876d4c84b86d7`
  fixes the newly isolated startup contract: local
  Compose `file:` secrets retain host bind-mount metadata, while the immutable
  API runs as `10001:10001`. The root-only `secrets/` directory remains
  `0700`; only `db_root_password` stays `root:root 0600`, and API-consumed
  files become `root:10001 0640`. Failure cleanup also preserves root-only API
  logs and non-secret runtime state before removing a partial stack. The
  post-merge bootstrap audit additionally fixed the unchanged `runtime.env`
  install call to pass explicit `root root 600` metadata to the expanded
  helper. PRs #223/#226 and their policy rotations through PR #228 passed;
  final policy main is `ae69332f16d855f39cec99bd46a21736194769b1`.
  Exact feature-main run `33246998513` passed backend/MariaDB tests, evidence,
  provenance and exact API/DB publication, then stopped at protected production
  approval. These remain source/CI results, not a NAS deployed/readiness pass.

- The retained legacy backend is recovered after run `33241850366`; its public
  liveness is restored, but the new exact-digest lane is not deployed
  production.
- The DSM loopback-ingress wrapper from feature main
  `db37772de5a3f18be7bcaa73170933ab18442475` is now installed at
  `/volume1/docker/smart-gatekeeper-backend/bin/sgk_backend_deploy.sh` with
  SHA-256 `3e0fdd660316817493a5cc29e972fdcbfc90833621fb440a75bccc7875381bb5`,
  owner/mode `root:root 0755` and size 23,210 bytes. Its staged validation
  passed and exact status remains `not-deployed`; this changed no container or
  database. The following NAS-local `curl --resolve` probe of DSM `:4442`
  completed without timeout or TLS failure and returned the recovered legacy
  build `7c2764a1...`, MQTT true, only `legacy_prearm_retired=false`, and the
  expected HTTP 503. This closes the transport preflight only; a fresh owner
  maintenance stop is still required before approval of run `33253911475`.
- The existing NAS SFTP-only identity remains suitable for firmware/APK artifact
  delivery but has no remote shell for Compose, migration or readiness work.
- The implementation and acceptance plan are documented in
  [nas_backend_external_deployment_plan.md](nas_backend_external_deployment_plan.md):
  the protected backend workflow now builds DS423+ `linux/amd64` API/DB images,
  publishes exact GHCR digests with provenance, signs a four-file release
  bundle, joins Tailscale with OIDC and invokes only `apply/status` through a
  forced SSH dispatcher. The NAS wrapper verifies signature, descriptor,
  Compose hashes, fixed repositories/digests/schema, existing volumes and local
  secret files before backup-first migration, then requires loopback and public
  `/ready` before recording the current release.
- Host validation currently passes the focused deployment-contract tests, Compose
  rendering, shell syntax, trusted-input completeness and the 35-check backend
  commercial contract. Separate bootstrap work has prepared the NAS wrapper,
  tailnet policy and protected GitHub Environment as recorded below. GHCR image
  publication has occurred, but no successful workflow deployment, database
  migration, Compose cutover or reverse-proxy change has occurred.
- MQTT-port preservation feature main `146fd7f85f14c4da0a5ce17518f876bdb9c1b21b`
  passed fresh Hosted Trusted, OTA P0 and Backend checks; final policy main
  `c9b6419006709f0f3cd19591a7162314fa48fd18` restored the sole persistent
  baseline. Exact feature-main run `33249202719` passed security, evidence and
  immutable image publication before its production deployment attempt.
  Owner readback proves bootstrap/verifier PASS, wrapper SHA-256 `62181892...`,
  dispatcher SHA-256 `6e80dedc...` and `status=not-deployed` while both retained
  legacy containers remain running. The exact live mounts and first off-NAS
  isolated restore are already evidenced below. The only remaining cutover
  precondition is the owner maintenance stop of exactly `gatekeeper-api` and
  `gatekeeper-db`; the wrapper rejects another running project holding the
  MariaDB volume or API port and never attempts a blind DB rollback.
  Owner output then proved that exact maintenance stop and the run was approved.
  It pulled exact API/DB digests, passed migration `up 007`, and exposed exact
  build `146fd7f` at `/live` HTTP 200, but `/ready` remained 503 solely with
  `mqtt=false`. After the loopback deadline the wrapper retained root-only
  runtime/API-log evidence, removed the partial project and networks without
  deleting volumes, and did not attempt DB rollback. The owner restarted the
  retained legacy DB/API; external `/live` is again HTTP 200 for build
  `7c2764a1`, and `/ready` is the known legacy-only HTTP 503 with MQTT true and
  only `legacy_prearm_retired=false`. The retained failure-log diagnosis
  supersedes any immediate deployment retry. Those logs show a synchronous
  subscriber `TimeoutError` after MQTTS configuration validation, with no
  TLS/certificate/authentication rejection. DSM Docker 24/Compose 2.20 cannot
  set deterministic `gw_priority`; a second attempt still timed out after both
  bridges were made routable. The current candidate therefore removes API
  multi-homing and uses one routable `data` bridge for API/DB/migration while
  keeping DB ports unpublished and the Synology API port loopback-only. Trusted
  policy authorization, CI and a fresh live attempt remain required.
- Owner-provided live container inventory now identifies legacy
  `gatekeeper-api` from local image `smart_gatekeeper-api` with wildcard IPv4
  and IPv6 host port `8000`, and `gatekeeper-db` from mutable tag
  `mariadb:10.11` with no published DB host port. This confirms the exact two
  containers that must be stopped during first adoption. Their exact mounts and
  volume identities were subsequently resolved as recorded below; automatic
  deployment is still not authorized until the backup/restore and live-control
  Gates close.
- A subsequent mount inventory fixes the DB data volume as
  `smart_gatekeeper_mariadb_data` and the APK source as the existing bind path
  `/volume1/docker/smartbox_ota/gatekeeper_apk`. The API is a live source bind
  from the NAS repository and has no `/var/lib/smart-gatekeeper` mount; its
  default `target_config.json` therefore lives under `/app` and requires a
  metadata check/copy into the new state volume. Existing DB init-SQL binds are
  not persistent data and will be replaced by the immutable DB image/migration
  runner.
- The candidate no longer assumes a new `gatekeeper_runtime` account. Both DB
  initialization and API connection now require explicit `DB_RUNTIME_USER` so
  the first adoption can retain the exact existing account. Passwords remain
  unprinted and will be migrated to NAS-local secret files.
- Readback now confirms `DB_NAME=smart_gatekeeper` and
  `DB_RUNTIME_USER=gatekeeper_user`. The legacy target config is a root-owned,
  mode `0555`, 135-byte regular file at `/app/target_config.json` with SHA-256
  `c5668365bd130ec42c7f49aafc53491b1a6ad3a3eb4858f3215b83de3505ece9`;
  the successful bootstrap copied those exact bytes into the prepared API
  state volume without changing the running legacy API.
- Secret-semantic readback confirms the API DB password matches the DB account,
  required DB/MQTT/API/operations/ACL values are set, both active P-256 scalars
  have valid shape, and the personal administrator password is active with a
  valid length. Administrator mTLS identities and the ACL transition signer are
  empty, so the transition pair remains disabled. No secret value or secret
  hash was recorded.
- The production API now reads the active personal administrator credential
  from a NAS-local file secret; ambiguous direct-plus-file configuration and an
  unreadable file fail closed. The one-time
  `bootstrap_legacy_synology.sh` candidate validates the exact observed legacy
  containers/mounts, stages existing values without printing them, copies the
  exact target config, and creates bind-backed API/APK/backup volumes without
  stopping the live project. Owner execution now reports successful preparation:
  the legacy containers remained unchanged, all three new external volume names
  were created, and the copied target config retained the expected SHA-256.
  This is NAS layout evidence only; DB migration, new containers and cutover
  have not run.
- Independent read-only verification now passes all 14 secret-file contracts,
  the exact runtime key set, all three external volumes and unchanged running
  legacy containers. The DB ledger contains migrations `002` through `007`;
  one active credential/grant has latest snapshot `313` and an exact applied
  ACK at `313`. The three legacy tenant rows report no `public_key` mode because
  the personal bootstrap intentionally retains its mapped row in `dual` mode.
  Exact tenant/door/Target boolean correlation remains the final lookup-disable
  check before the separate owner decision. Owner execution subsequently passed
  every boolean: feature flags, target-auth scope, dual/public tenant mapping,
  active ACL tenant, exact active credential/grant and snapshot/ACK hash/version
  all match. Latest snapshot and applied ACK advanced together to `314` during
  the live readback. The technical path for disabling legacy lookup is present;
  owner approval and off-NAS restore remain mandatory before cutover.
  The MQTT-port-corrected owner rerun again passed all contracts and exact
  identity booleans with latest ACL snapshot `439` and exact applied ACK `439`;
  this supersedes the older count while preserving the same one active
  credential/grant and three active tenants. The owner lookup-disable decision
  remains separate from the now-proved deployment preflight.
- Owner size readback reports the current `smart_gatekeeper` database at
  2,686,976 bytes over 20 tables, with a 1,638,400-byte largest table. The
  repository now contains a no-cutover NAS dump/inventory helper plus WSL
  digest/authentication/encryption and exact-digest isolated-restore harness.
  Twelve focused deployment tests and the 35-check repository contract pass;
  owner execution subsequently created a consistent 792,678-byte SQL dump and
  bundle SHA-256 `d2321993a1858ec053c614bf6aecb212012f2dd25db59ff2fd49ed42056f418d`
  for deployed source `7c2764a1a16492ec1620079c8211b47287b1b3fd`, while both legacy
  containers stayed running. The root-only NAS copy and temporary owner export
  were transferred with exact sidecar validation. WSL produced a mode-0600
  AES-256 GPG copy whose streamed decrypt hash matched the NAS bundle, then
  restored the dump into pinned MariaDB on IPv4 localhost. Exact schema/content
  inventory passed in 1.680 seconds with 316 ACL snapshots, one credential, one
  target boot-state row and three tenants. This closes the first isolated
  restore Gate only; two disposable labs and plaintext copies await owner
  cleanup, and recurring off-site 3-2-1 backup remains open. Owner subsequently
  authorized cleanup: both WSL containers/volumes and all WSL plaintext
  bundle/work files were removed, while the encrypted bundle, authenticated
  manifest, restore result and keys were retained mode `0600`. NAS owner-home
  export deletion subsequently passed through interactive SSH; all temporary
  plaintext copies are now removed. The NAS root-only backup remains retained
  by design.
- The initial GitHub control-plane readback confirmed `origin/main` equaled local main at
  `21e71d1c8faf469d101a477207276a80297873c8`, the environment token is
  authenticated as repository ADMIN, and `production` already has owner review
  plus a `main`-only branch policy. Backend deploy variables/secrets were absent
  at that snapshot; their later bounded setup is recorded in the 2026-08-29
  section. The trusted workflow policy still requires a separate exact-candidate
  authorization rotation.

## 2026-08-28 current WSL/Fold7 core action-2 check

- WSL-attached CH343 Target booted the local personal-production image, restored
  saved Wi-Fi at `192.168.35.18`, connected exact per-Target MQTTS, applied
  signed ACL v303, and started the enabled GATT/iBeacon service. Windows-hosted
  ADB kept the authorized Fold7 connected independently.
- The installed app's main WebView reported backend status `승인됨` and exposed
  the enabled `문 열기` button. Native health was `HEALTHY`, BLE owner
  `native_gatt`, and local consent `local_keystore_authenticated`.
- One main-screen action-2 tap connected to the Target, discovered the service,
  and enabled Target Hello, Challenge and Result indications. It then closed in
  about 1.8 seconds with UI result `수동 출입 실패: PROTOCOL_INCOMPATIBLE`.
  Target serial recorded only the accepted connection: there was no proof-verification evidence,
  `AUTH_PENDING`, `RELAY_HOLD`, relay ON/OFF or terminal Result OK.
- The installed `3cf6eaa` and current Target source still have protocol/framing
  version 1 and no diff in the core Android/Target GATT protocol files. The
  public error can also represent a rejected Target Hello or unexpected message
  type, so the exact on-wire cause is unresolved and must not be called a simple
  version-range mismatch without packet/transport diagnostics.
- A preceding dashboard `1-Tap 수동 로컬 개방` control was found in the exact
  installed source to enqueue the action-1 WorkManager retry path, not the
  terminal action-2 executor. It remained `Target Result: NONE` during the
  bounded observation and was not used as action-2 success evidence.

Current core manual-open acceptance is therefore **FAIL at the authenticated
protocol boundary**. The non-retryable result was not repeated. This run safely
failed before relay actuation and provides no physical contact or door-motion
evidence.

## 2026-08-29 production-app action-2 recovery

- Windows ADB showed the connected Fold7 still running stale
  `1.0.0-g3cf6eaa` / 21701. The NAS production APK
  `1.0.0-g40852b7` / 22401 was downloaded and independently matched its
  55,786,649-byte length, SHA-256
  `2790c2844c62881a9fc3e27c1632514fb2ba82080deb12d2ff3775373b63468d`
  and signer-certificate SHA-256
  `8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0`.
  `adb install -r` preserved the approved user and native credential state.
- One main-WebView `문 열기` action-2 completed with terminal UI
  `문이 열렸습니다 (4585ms)`. Native health remained `HEALTHY` with last
  latency 4585 ms; Android recorded successful characteristic writes,
  indications and a normal local GATT disconnect. The prior
  `PROTOCOL_INCOMPATIBLE` was not reproduced.
- This closes the currently connected authenticated mobile-to-Target action-2
  software/FSM outcome. It does not prove physical relay contacts/load, actual
  door motion, AJ-SR04T threshold, repeated latency, screen-off action-1 or OTA
  rollback.
- Exact-main run `33199155599` separately published signed encrypted Target
  `2.1.291+main.g89e047c`. Publication is not installation: current Target
  install, reboot and health remain unconfirmed because this shell's group list
  has not refreshed `dialout` access to `/dev/ttyACM0`.

## 2026-08-29 dashboard action-2 binding correction

- The connected Fold7 was replacement-updated to the signed exact-main
  `1.0.0-gf3f4121` / 23301 APK after its 55,786,649-byte size, artifact
  SHA-256 and production signing-certificate SHA-256 matched the NAS manifest.
  The original installation time and AndroidKeyStore-backed native status were
  retained.
- On that installed build, the dashboard control labelled `1-Tap 수동 로컬
  개방` only returned `durable queue에 등록`; Android executed the action-1
  WorkManager GATT path and Target serial never recorded proof or relay ON/OFF.
  This reconfirms the historical source mismatch above and is not an access
  success.
- The source correction binds that dashboard control to
  `triggerLocalGattOpen`, requires exact native terminal reason `OPENED`, and
  reports the returned latency. Source contracts reject a return to
  `triggerLocalGattRetry` or queue-acceptance success text. This remains a
  candidate until hosted build, signed publication, replacement install and
  connected Target action-2 relay ON/OFF evidence pass.

## 2026-08-29 backend NAS GitHub CI policy connection

- Backend-NAS feature PR #186 passed fresh hosted trusted, OTA and backend
  MariaDB checks at merge-connected head `732e672`, then merge-commit merged as
  exact main `89e047c2416de6924ee4b7aff4daf4250d55f907`.
- Bridge PR #187 and final admission PR #188 connected and authorized the exact
  82-path feature bundle without rebasing or squashing. This immediate final
  rotation removes both `25562d1` transition identities and pins only
  `current-main-baseline` to actual merged main `89e047c`.
- The GitHub `production` Environment has owner review and a `main`-only branch
  rule. Exact NAS variables, pinned SSH host key/private key, release signer and
  both Tailscale OIDC secret names are present; secret values were never read
  back. The narrow tailnet grant is saved, and a WSL user-owned source passed
  private forced `status` plus arbitrary-command rejection.
- Manual exact-main run `33199183911` then exercised the ephemeral
  `tag:sgk-github-deploy` runner through Tailscale and the pinned forced SSH
  endpoint. Its retained evidence is exactly `status=not-deployed`; all
  publication and `apply` jobs were skipped.
- The private CI transport Gate is therefore closed, but the new stack is not
  deployed. Database migration, legacy-container cutover, API readiness,
  rollback and external service evidence remain separate production Gates.

## 2026-08-26 issue #179 Bluetooth-state recovery candidate

- Android's modern implicit-broadcast limits make a manifest-only
  `ACTION_STATE_CHANGED` receiver unreliable. The candidate registers a native
  process-lifetime receiver from `GatekeeperApplication`, independently of the
  Flutter UI/isolate, while the existing foreground service keeps the process
  resident.
- Persistent registration intent survives a Bluetooth-OFF registration attempt;
  disable intent is committed before best-effort platform stop. The first
  observed `STATE_ON` reconciles one exact PendingIntent scan by stop-then-start.
  OFF/TURNING/repeated-ON and disabled states do not dispatch work, and the state
  receiver never invokes action 1 directly.
- Seven focused Python source/pocket contracts, an expanded 174-test mobile/
  OTA/trusted suite and the Android Gradle `:app:testDebugUnitTest` build
  (209 tasks) passed locally. The phone remains disconnected, so OFF→ON
  broadcast delivery, OS first match and terminal action-1 `ARMED` are
  explicitly pending connected acceptance.

## 2026-08-26 exact-main 285 ACL-before-BLE connected acceptance

- PR #176 and both trusted-policy PRs merged; final source/policy main is
  `577533186ba5b40ca13fc47aadf51747e2057b73`. Run `32916682601` built,
  production-signed, encrypted and atomically NAS-published it as
  `2.1.285+main.g5775331`.
- The connected 282 Target accepted the signed manifest, downloaded the exact
  1,849,860-byte encrypted artifact, verified the inactive image and rebooted
  into exact 285. Saved Wi-Fi returned at `192.168.35.19`; exact per-Target
  MQTTS, retained diagnostics/config and signed ACL delivery recovered.
- The corrected boot order was observed directly: `BLE waiting for active ACL`
  appeared before MQTT connection; signed ACL v203 applied; only then did the
  Target start GATT, iBeacon and the enabled Hardwareless transport. This closes
  the Target-side startup-order acceptance for issue #175.
- A following 30-second connected interval remained stable and periodic HTTPS
  OTA reported `already current: 2.1.285+main.g5775331`. No pending-image
  health-window/valid-mark trace appeared, so issue #172 remains open and this
  is not rollback proof.
- Android is disconnected, so the fixed Target has not yet received a new
  Samsung screen-off first match. AJ-SR04T and relay contact/load are absent;
  ultrasonic threshold, electrical contact and actual door movement remain
  unclaimed. Android Bluetooth OFF->ON re-registration is tracked separately by
  issue #179.

## 2026-08-26 exact-main 282 connected controls and boot ACL race

- Target and production-signed Android were aligned to exact main
  `3cf6eaa925e5ef38ee7d538a6d7a1cf8720ad219`: Target
  `2.1.282+main.g3cf6eaa`, Android `1.0.0-g3cf6eaa` / 21701. The APK hash,
  embedded source and production signer matched before replacement install.
- The actual main-screen action-2 completed authenticated GATT, Target relay
  command ON then timer-bound OFF, and terminal UI success in 4,636 ms. A
  separate foreground action-1 completed `Presence -> ARMED` in 4,688 ms once
  the Target ACL was active. These are board/FSM/GPIO command results, not
  relay-contact voltage, actuator or actual-door evidence.
- A controlled Home + Dozing + secure-keyguard attempt held the Target absent
  for 15 seconds and then booted it. Android received the first match with
  `screen_interactive=false`, RSSI -51 and 5.37 ms callback latency, connected
  and configured GATT, but failed after about 3.4 seconds without `ARMED`.
- Source and runtime order identify the race: `TargetAclManager::begin()` must
  leave a stored ACL inactive without trusted wall time, while setup advertised
  iBeacon/GATT before MQTT delivered the fresh signed ACL. Issue #175 defers
  personal Hardwareless BLE until `hasActiveAcl()` becomes true, starts it once,
  and leaves non-Hardwareless immediate beacon startup unchanged.
- Android has now been disconnected. Hosted CI, merge, exact-main Target boot
  order verification and a new physical screen-off repetition remain pending.
  AJ-SR04T and relay/contact/load are absent, and issue #172 still owns
  pending-image valid-mark/rollback proof.

## 2026-08-26 exact-main 281 OTA acceptance and current mobile boundary

- Runs and atomic NAS evidence published exact main
  `082e431b50cd569ab0f557d463305e3b48ad27cc` as
  `2.1.281+main.g082e431`. The encrypted artifact is 1,849,444 bytes with
  SHA-256 `ea17493b...ab5566`; the signed manifest SHA-256 is
  `d936f157...b92eda9`.
- The installed pre-fix 493 image accepted that manifest but reproduced the
  second-handshake Mbed TLS `-9984` failure before any inactive write. A bounded
  COM5 bootstrap then wrote bootloader, the reviewed 16 MiB partition table,
  `boot_app0` and exact-source 082 firmware at the documented offsets. It did
  not run `erase_flash` or write `firmware.factory.bin`; every region passed
  esptool readback verification and saved Wi-Fi/security NVS remained present.
- From that corrected downloader, the independent periodic HTTPS path accepted
  the signed 281 manifest, started the exact 1,849,444-byte encrypted download,
  verified the inactive image and rebooted. Exact CI identity
  `2.1.281+main.g082e431` then restored `192.168.35.19`, exact per-Target MQTTS,
  ACL v188 and enabled GATT. A later periodic check reported already current.
  This closes the #166 TLS reuse defect; #160 is closed as superseded.
- The OTA boot never logged `pending image health window started` or `running
  image marked VALID`, including after a full 30-second healthy interval. Issue
  #172 owns the distinct production N16 bootloader pending-verify/rollback Gate.
- On the exact 281 Target, a new Samsung screen-off first match arrived at RSSI
  -53 with `screen_interactive=false`. Android connected, discovered services
  and enabled all three indications, but WorkManager returned `FAILURE` after
  about 3.4 seconds and Target never entered `ARMED`. The secure keyguard blocks
  the redacted native health screen and current manual-open retest until the
  user unlocks the phone. The earlier 493 action-1/action-2 successes remain
  valid historical connected evidence but do not override this failed current
  repetition.
- AJ-SR04T and relay/contact/load remain physically absent. Sensor threshold,
  relay voltage/contact timing, actual door movement, automatic rollback and
  final wall-install acceptance are not claimed.

## 2026-08-26 exact-main Android action acceptance and Target OTA TLS blocker

- Main run `32903378187` built, production-signed and atomically published exact
  source `1e3dfcf32c7b3ef88121fb824c35d81d2f6d40a7` as Android
  `1.0.0-g1e3dfcf` / `versionCode=21001`. Downloaded APK SHA-256
  `cbf8497c...9243a5b` matched its signed manifest, embedded the exact source
  SHA and retained production signer SHA-256 `8bdbcf86...e1d7ba0`.
  `adb install -r` preserved the original first-install timestamp, app data and
  AndroidKeyStore-authenticated native state.
- The actual main-screen `문 열기` action reached HA `AUTH_PENDING` at 07:14:20,
  Target relay-command ON and HA `RELAY_HOLD`/door-open at 07:14:23, timer-bound
  OFF/`COOLDOWN` at 07:14:24 and `IDLE` at 07:14:29 without a Target reset.
  This passes the connected action-2 board/GPIO command path; no physical relay
  contact or door mechanics were attached.
- With the app on Home and the Samsung phone still `Dozing`, one authenticated
  Target reboot created a fresh beacon. Native WorkManager completed successfully
  and HA independently observed `AUTH_PENDING` at 07:17:33 then `ARMED` at
  07:17:36. The bounded Flutter owner-exclusion path produced one ranging attempt
  about every 30 seconds rather than the earlier immediate retry storm. Issues
  #156 and #158 are closed by this connected evidence.
- Target run `32903378312` published signed exact-main firmware
  `2.1.275+main.g1e3dfcf`, but the installed 493 Target accepted the manifest and
  then failed the immediately following artifact TLS handshake with Mbed TLS
  `-9984`; it did not write or boot the new slot. The NAS serves a valid longer
  Let's Encrypt chain rooted at the provisioned ISRG Root X1. PR #161 changed
  the two clients to sequential lifetime, and run `32907218154` then published
  `2.1.278+main.gc5d79eb`; the connected Target again accepted the signed
  manifest and failed the second artifact handshake with the same `-9984`.
  That disproves client destruction alone. Issue #166 instead requires the
  signed artifact to use the exact manifest HTTPS authority and reuses the
  already CA/hostname-verified HTTP/1.1 keep-alive connection; no certificate
  bypass or insecure fallback is allowed.
- AJ-SR04T and a physical relay/contact fixture are still absent. Therefore
  `ARMED -> distance <= 80 cm -> RELAY_HOLD`, electrical contact timing,
  pending-image valid marking, rollback and final wall-install acceptance remain
  open evidence Gates.

## 2026-08-26 final-main 493 durable-NVS and connected control validation

- Final push run `32895175240` built and published exact main `493591bb` as
  `2.1.273+main.g493591b`. Before recovery installation, the live NAS manifest,
  immutable encrypted artifact and authenticated plaintext were checked at
  `1,849,044` bytes / SHA-256 `31480801...684e4d8a` and `1,849,008` bytes /
  SHA-256 `b734ee43...1228a9a8`, respectively.
- The old 848 command ledger was already full, so even the signed HA OTA
  request failed before reaching the OTA effect. COM5 was therefore used as a
  bounded recovery path: bootloader, the reviewed 16 MiB partition table,
  `boot_app0` and the exact authenticated CI application were written at their
  standard offsets without erasing the Wi-Fi/config NVS.
- The recovered Target booted exact 493, restored Wi-Fi `192.168.35.19`, MQTTS
  and GATT, and initialized `sgkstate` with `used=0 free=60480 total=60480`.
  Signed retained ACLs v169--v171 then wrote successfully with no further
  `NOT_ENOUGH_SPACE` error.
- Two signed HA reboots succeeded. Durable usage survived the first reboot and
  advanced from 179 to 195 entries by the second, proving that signed-command
  replay writes now persist instead of failing at `ledger_b`. A signed HA OTA
  request also reached `[OTA] forced update check started` and returned
  `already current: 2.1.273+main.g493591b`. HA remote open produced one
  relay-command ON/OFF sequence without reset.
- Three Samsung screen-off first-match trials were delivered with
  `screen_interactive=false`, RSSI -50/-52. Native WorkManager connected,
  discovered services, enabled the three indication characteristics and wrote
  all framed proof chunks, then disconnected. Target accepted all three BLE links,
  but no action-1 `ARMED` trace followed. No NVS/ACL/replay error accompanied
  these attempts. The third trial completed before the later periodic OTA check,
  excluding OTA-busy collision. Issue #149 storage acceptance is complete and
  closed; issue #156 then tracked the missing terminal action-1 result. The later
  exact-main Android `1e3dfcf` trial documented above reached terminal `ARMED`
  and closed #156, superseding this earlier failure classification.
- There is no AJ-SR04T/contact fixture in the current board-only setup.
  Ultrasonic threshold-to-relay, electrical contact, pending-image valid mark,
  rollback and wall-install acceptance remain open evidence Gates.

## 2026-08-26 exact-main 848 connected acceptance and issue #149

- Target run `32888032443` built, signed, encrypted and NAS-published exact
  main `848bbf16`; periodic signed HTTPS OTA installed
  `2.1.270+main.g848bbf1`. Wi-Fi `192.168.35.19`, per-Target MQTTS,
  connectable GATT and ACL delivery returned after reboot. The retained OTA
  path did not expose a `PENDING_VERIFY`/valid-mark trace, so rollback health
  remains a separate open Gate.
- Android run `32888032174` published the production-signed exact-main APK.
  SHA-256 was `016e62c5d0fe834f42a06e6651442860a62e06f3798fcaaff4781a8a92c379d4`;
  `adb install -r` installed `1.0.0-g848bbf1` / 20201 while preserving app
  data, first-install identity and AndroidKeyStore state.
- The main mobile open button completed action 2 four times across the prior
  and exact 848 APKs. Each Target trace reached authenticated GATT acceptance,
  relay-command ON, timer-bound OFF and terminal mobile success without reset;
  observed UI completion was about 4.5--5.2 seconds. This is a board/GPIO
  command result, not relay contact voltage or door mechanics evidence.
- A true screen-off first-match attempt reached the Android background worker
  and Target GATT connection, but no action-1 `ARMED` result followed. Target
  serial emitted `ledger_b NOT_ENOUGH_SPACE`; earlier ACL writes had also
  emitted `slot_0 NOT_ENOUGH_SPACE`. Issue #149 therefore blocks the pocket
  acceptance test until durable ACL/replay writes are restored and the exact
  merged image is redeployed.
- The issue #149 candidate leaves both 7 MiB OTA slots and offsets unchanged,
  keeps Wi-Fi/config in the original 20 KiB NVS, and moves ACL snapshots,
  command replay ledgers and the offline event queue to the unused 1.875 MiB
  data region. Existing application-only OTA installations discover the legacy
  `spiffs` label; new full flashes declare the same region as `sgkstate` NVS.
  Reads fall back to legacy NVS and no automatic erase is allowed.

## 2026-08-26 connected b6 acceptance와 issue #143

- runs `32881540989` / `32881541103`의 exact b6 Target/APK를 각각 signed
  periodic HTTPS OTA와 same-signature `adb install -r`로 설치했다. Target은
  Wi-Fi `192.168.35.19`, MQTTS, GATT와 ACL v159를 복원했고 Android 앱 데이터와
  AndroidKeyStore credential은 보존됐다.
- 메인 `문 열기` action 2는 GATT 연결·service discovery·indication enable까지 진행했지만
  proof 처리 중 Target이 `abort()`로 재부팅했다. `RELAY_HOLD`, relay ON/OFF와 terminal
  Result OK는 발생하지 않았고 앱은 `PROOF_OUTCOME_UNCERTAIN`을 표시했다. 요구사항 1은
  현재 FAIL이며 issue #143이 release blocker다.
- production-equivalent ELF는 `GattServer::update()`가 `core_mux` critical section 안에서
  `ProtocolCore::processProof()`를 실행하고, 동기 Result-to-FSM commit이
  `TargetAccessFsm::handleLocalManualOpen()` → relay callback → `LOGF`에 도달하면서
  newlib stdout recursive-lock assert를 일으킨 경로를 가리켰다.
- issue #143 후보는 adapter/core 직렬화를 recursive task mutex로 바꿔 GPIO, failsafe timer,
  diagnostics와 logging을 critical section 밖 task context에서 실행한다. focused 16/16과
  personal-production ESP32-C6 build(1,781,874/7,340,032 bytes)는 통과했다. 아직 merge,
  exact CI/NAS 재게시, Target OTA와 action-2 재시험 전이므로 수정 완료로 판정하지 않는다.

## 2026-08-26 PR #132 증거 복구와 현재 경계

- PR #132에만 남아 있던 2026-08-25 실기기 증거를 issue #141에서 역사적 사실로 복구했다.
  exact main `db37bc2`의 Target `2.1.262+main.gdb37bc2`와 Android
  `1.0.0-gdb37bc2` / 19001은 각각 runs `32777471683`, `32777471718`에서
  빌드·게시·설치됐다. 한 foreground local GATT 세션은 `HEALTHY`, failure/Target denial 없음,
  4,599 ms를 기록했고 HA는 `AUTH_PENDING` 06:27:33 → `ARMED` 06:27:36 →
  `IDLE` 06:28:35를 독립 관측했다. Target reset은 없었다.
- 이 세션은 당시 action 1의 authenticated proof/result와 FSM ARM 증거다. 이후 issue #133에서
  수동 버튼을 action 2 즉시 relay 경로로 분리하고 Result를 실제 FSM 전이에 결합했으므로,
  과거 성공을 현재 수동 버튼-to-relay 성공으로 해석하지 않는다.
- 현재 exact main `a9b68222`의 firmware는 signed OTA로 Target에 설치되어 Wi-Fi
  `192.168.35.19`, MQTTS, ACL v147과 GATT를 복원했고 이후 OTA 확인에서 current로 판정됐다.
  같은 main의 APK는 NAS에 게시됐지만 phone이 연결되지 않아 설치하지 않았다. 따라서 현재
  action 2 버튼, screen-off/pocket action 1, AJ-SR04T와 당시 GPIO3 접점 결과는 여전히 미검증이다.

## 2026-08-26 issue #134 pocket-approach 후보

- 개인 native GATT enable은 같은 native 호출에서 exact `PendingIntent` wake 등록을 시도하고,
  disable은 등록을 중지한다. live 권한/Bluetooth 상태와 `handsFreeReady`를 별도로 노출한다.
- Android 12+의 첫 presence WorkManager 작업은 expedited이고 quota 부족 시 일반 작업으로 안전하게 강등된다.
  Android 8~11은 새 foreground-service 계약을 요구하지 않도록 기존 일반 작업을 유지한다.
  retry는 설정된 지연을 지키며, 45초를 넘긴 stale presence는 proof 전에
  `PRESENCE_EXPIRED`로 종료한다.
- action 1 성공은 실제 Target `ARMED` 전이 뒤에만 반환되므로 presence→dispatch와
  presence→ARMED 시간을 분리 기록한다. Target은 ARMED 동안 100 ms 간격으로만 초음파를 읽고
  유효 설정 거리 안에서만 relay를 켠다.
- source/native-host 집중 테스트 36개가 통과했다. 현재 phone, AJ-SR04T와 physical relay가
  연결되지 않았으므로 screen-off/pocket 성공률, 실제 sensor-to-contact latency는 미검증이다.

## 2026-08-26 issue #133 merged software path

- 수동 앱 버튼과 background presence가 더 이상 같은 의미를 공유하지 않는다. 수동 버튼은 signed
  local GATT action 2를 foreground에서 즉시 실행하고 Target terminal result를 기다리며, presence
  worker는 action 1을 명시적으로 사용해 `ARMED`까지만 전환한다.
- Target protocol은 `AuthControlGate`로 proof와 FSM을 결합한다. action 1은
  `AUTH_PENDING → ARMED`, action 2는 `AUTH_PENDING → RELAY_HOLD`이며 실제 전이가 성공한 뒤에만
  `RESULT OK`를 생성한다.
- native C++/source suite 11/11과 `esp32c6_personal_production` build가 통과했다. firmware는
  1,780,836/7,340,032 bytes(24.3%), RAM 67,088/327,680 bytes(20.5%)다.
- PR #135는 Android, Target, OTA, protocol과 Trusted CI 통과 후 main `737d3243`으로
  merge됐고, 최종 정책 회전 PR #139도 main `6cad8baa`에 병합됐다. 현재 phone은 연결되어 있지 않고
  sensor/relay가 배선되지 않았으므로 버튼-to-GPIO latency, 실제 접점, 초음파 hands-free 결과를
  주장하지 않는다.

## 1. 한눈에 보기

| 축 | 저장소 최신 구현 | 검증/운영 경계 |
|---|---|---|
| Target | ESP32-C6, AJ-SR04T GPIO10/11, GPIO23 relay, per-Target MQTTS, signed command/ACL, signed dual-slot OTA. 개인 설치 전용 `esp32c6_personal_production`은 valid door/ACL trust 뒤 Hardwareless를 compile/runtime ON하고, default/commercial profile은 OFF를 유지 | GPIO23 source restoration is a new candidate. Its build, exact-main signed OTA install/reboot/health and the GPIO11 electrical/relay-contact/door trials must be recorded separately before physical success is claimed |
| Android | foreground scan, OS-managed BLE wake, native GATT credential worker, AndroidKeyStore public enrollment, native-authoritative consent/ownership, recovery/update UI, bounded NAS APK publisher | run `32872303799`가 production-signed `1.0.0-ga9b6822` / 19801을 NAS primary/fallback에 게시·readback했다. phone 미연결로 설치하지 않았다. 마지막 연결 증거는 `db37bc2` action-1 foreground GATT 성공이며, 현재 action-2 수동 개방과 pocket action-1은 실기기 미검증이다 |
| Backend | FastAPI/MariaDB, enrollment/ACL, personal public-key bootstrap, exact Target ACL apply correlation, signed HA command bridge, admin session/RBAC/CSRF/re-auth, operations APIs | paho-mqtt 1.6.1 MQTTv5 `ReasonCodes` callback correction은 exact main `bc9bb5d`에 포함됐다. NAS live Backend를 rebuild/recreate했고 readiness, Target status, subscriber/discovery와 bridge availability가 정상이다 |
| Access | legacy iBeacon → pre-arm, personal native local GATT, signed Backend/MQTT remote command가 상호 구분됨 | 과거 `db37bc2`에서 action-1 foreground proof/result와 `ARMED`를 실기기로 확인했다. 현재 소스는 action 1 sensor ARM과 action 2 immediate relay를 분리하고 Target FSM 전이 성공에 Result를 결합한다. a9 APK/phone 및 실제 sensor/relay E2E는 미검증이다 |
| OTA | Target periodic HTTPS pull, signed manifest/artifact, inactive slot, health mark/rollback, authenticated local recovery; mobile signed update/recovery 계약 | run `32872303874`의 1,846,624-byte plaintext와 1,846,660-byte encrypted Target artifact가 게시되고 Target에 설치됐다. 7,340,032-byte OTA slot의 25.16%로 5,493,408 bytes가 남는다. run `32872303799`의 55,786,649-byte APK도 NAS에 게시됐으나 미설치다. rollback/power-loss Gate는 열려 있다 |
| Home Assistant | 기존 15개 status-backed read-only entity와 retained bridge availability 기반 `[Gatekeeper] 연결 상태` entity, Backend ingress→fresh boot/status→서명된 per-Target command bridge 기반 reboot/OTA/config control을 구현. 검증 status max-age watchdog은 갱신 중단 시 retained `offline`을 발행한다. `manual_remote`는 별도 opt-in | 기존 live bridge availability와 controls는 enabled다. signed-status/watchdog 변경은 source/test candidate이며 NAS 재배포·retained discovery apply·HA 화면 확인 전이다. remote/manual relay와 sensor actuation은 수행하지 않았다 |

## 2. 저장소 구현과 현장 배포를 혼동하지 않는다

2026-08-12의 구형 매립본은 더 이상 현재 상태가 아니다. 2026-08-24에 GCM block carry를 포함한 exact-main H9를 app-only USB로 설치하면서 bootloader, partition table, NVS, OTA data와 fallback slot을 보존했다. 이후 signed inactive-slot OTA를 반복해 `db37bc2` 실기기 GATT 증거를 얻었고, 현재는 exact main `a9b68222`의 `2.1.266+main.ga9b6822`가 Target에서 실행 중이다. 저장된 Wi-Fi로 `192.168.35.19`를 얻고 exact per-Target MQTTS, production ACL signer/ACL과 connectable GATT service를 복원했다.

연결된 Samsung phone에는 production signer가 일치하는 `1.0.0-gdb37bc2` / 19001을 replacement install해 앱 데이터와 native credential을 보존했다. 이 APK와 matching Target은 callback-stack 및 Challenge stream 수정 뒤 foreground action-1 proof/result와 `ARMED` 전이를 한 번 완료했다. 이후 issue #133/#134가 action 2 즉시 개방과 bounded pocket dispatch를 추가했고 exact a9 APK까지 게시했지만, phone 미연결로 그 APK를 설치·실행하지 않았다. 따라서 과거 action-1 성공은 현재 수동 action-2 relay 또는 pocket/background 성공의 대체 증거가 아니다.

Wi-Fi 자격 증명 자체는 Android가 동일 2.4 GHz SSID에 새로 인증해 검증했다. 그러나 Target이 본 현관 AP 신호는 약 `-80~-82 dBm`이었고 reason 2/4/201이 반복됐다. 같은 H11과 같은 저장 경로가 가까운 hotspot `-42 dBm`에서는 즉시 성공했으므로 현재 지배적 원인은 RF margin이다. 코드 호환 프로파일은 AP 선택과 association 안정성을 개선할 수 있지만 `-81 dBm` link budget을 만들 수는 없다. 최종 매립은 최소 `-75 dBm`, 가능하면 `-67 dBm` 이상을 확보하고 반복 부팅/장애 복구를 통과한 뒤 승인한다.

- 저장소 최신 구현: 이 문서와 [최신 코드 감사](current_code_audit.md)
- 개인 현장 배포: [개인 PROD 사건 기록](personal_prod_incident_2026_08_12.md)
- 상용 출시 Gate: [commercial_release_program.md](commercial_release_program.md)
- 개인 축소 Gate: [personal_production_profile.md](personal_production_profile.md)

## 3. 현재 기준 아키텍처

정상 원격 pre-arm은 다음 경로를 사용한다.

```text
Target iBeacon
  → Android foreground scanner
  → HTTPS /api/v1/door/prearm
  → approved tenant/device lookup
  → boot-bound signed command over per-Target MQTTS
  → Target command verification
  → TargetAccessFsm ARMED
  → AJ-SR04T valid distance
  → GPIO23 relay
```

Hardwareless RC는 AndroidKeyStore 자격과 connectable GATT proof를 사용해 Target-local FSM으로 연결되는 별도 경로다. 기본 개발 및 commercial production 빌드는 `ENABLE_HARDWARELESS_RC=0`을 유지한다. 단일 설치용 `esp32c6_personal_production`만 compile-ON이며, valid Target identity/ACL trust에 따른 일회성 NVS migration과 이후 `false` kill switch를 적용한다. 모바일은 명시적 enrollment가 exact Target ACL applied ACK까지 확인된 뒤에만 native ownership을 ON한다.

## 4. 현재 신뢰 경계

- MQTT 연결은 Root CA, non-1883 port, Target별 principal과 exact topic namespace가 모두 provisioned되지 않으면 command plane을 닫는다.
- Target command는 target/tenant/door/boot/session/nonce/time/key에 묶인 서명을 검증하고 replay를 거부한다.
- 관리자 경로는 구성된 mTLS trusted proxy 또는 개인 관리자 세션을 사용하며, unsafe 요청은 CSRF와 역할/tenant scope, 중요 작업은 fresh re-auth를 요구한다.
- force-open은 상용 경로에서 제안자와 다른 승인자를 요구하고 publication reconciliation 상태를 영속화한다.
- `mqtt_published=true` 또는 QoS 1 PUBACK은 broker 수락 증거이며 Target 실행 증거가 아니다.
- BLE 탐지, API 성공, MQTT 수락, Target command ACK, FSM 상태, sensor, relay 결과는 서로 다른 증거 단계다.

## 5. 열려 있는 주요 Gate

1. Issue #172는 exact 295 pre-VALID 자동 rollback/anti-replay와 strictly newer exact 296의 application health-window→explicit VALID→post-VALID reboot를 모두 연결 Target에서 통과해 닫혔다. OTA-G4의 별도 hard power-removal 시험은 계속 남는다.
2. 약신호 compatibility release를 동일 위치에서 홈 AP와 가까운 AP로 A/B하고, 홈 위치 RSSI를 최소 `-75 dBm` 이상으로 개선한 뒤 Wi-Fi/DHCP/MQTTS와 broker/WAN 장애 자동 복구를 실측한다.
3. GPIO23 Active-LOW relay, High-Z OFF, ECHO 5 V 보호, 전원 강하와 반복 구동을 물리 검증한다.
4. Samsung/OEM 화면 OFF, Activity 종료, OS background 제한을 release artifact로 반복 검증한다.
5. Personal Hardwareless RC의 compile/runtime enable에서 exact-main 301/`gf352a78` 조합은 fresh beacon action 1 `ARMED` 직후 dashboard action 2 relay-command ON/OFF와 terminal UI 성공을 통과했다. Samsung/OEM screen-off·process-killed pocket action 1의 반복/latency 분포, relay contact/load와 실제 문 움직임은 계속 검증한다. Commercial/default compile-OFF와 local kill switch는 보존한다.
6. production NAS 배포, reverse proxy, backup/restore와 operator acceptance는 소프트웨어 계약과 별개의 운영 증거로 남긴다.

## 6. 문서 읽기 순서

| 질문 | 먼저 읽을 문서 |
|---|---|
| 현재 코드가 무엇을 구현했는가 | [current_code_audit.md](current_code_audit.md) |
| 현재 시스템 흐름 | [architecture.md](architecture.md) |
| 실제 매립 Target 상태 | [personal_prod_incident_2026_08_12.md](personal_prod_incident_2026_08_12.md) |
| Target 연결/복구 | [embedded_target_connectivity_policy.md](embedded_target_connectivity_policy.md) |
| OTA 완료 기준 | [ota_reliability_contract.md](ota_reliability_contract.md) |
| 모바일 background 문제 | [mobile_app_background_audit.md](mobile_app_background_audit.md) |
| 핀과 전기 안전 | [pin_mapping.md](pin_mapping.md) |
| 검증 결과 | [hardware_test.md](hardware_test.md) |

## 2026-08-29 exact-main Target 293 connected update and #172 correction

- Main run `33200199481` published exact `c0ac5ed8b9f6cf5860a50f48e760b0cb4df78634`
  as signed/encrypted `2.1.293+main.gc0ac5ed`. The connected Target upgraded
  from exact 288 by periodic HTTPS, verified the inactive image, rebooted into
  exact 293 and restored relay-OFF, Wi-Fi `192.168.35.18`, MQTTS, ACL v337 and
  GATT. A later periodic check was already current.
- This closes exact-main Target install/reboot/service recovery for 293, not
  OTA health-valid or rollback. No application health-window trace appeared,
  and read-only OTA-data evidence showed both slots already `VALID`.
- The installed bootloader exactly matches the rollback-enabled pinned
  pioarduino bootloader. Root cause is Arduino core's pre-`setup()` weak
  auto-validation, which marks a pending slot valid before `OtaManager` can
  apply its 30-second predicates.
- The current candidate supplies strong `verifyRollbackLater()` and a
  compile-time rollback requirement. Local production build and ELF symbol
  verification pass. It must still merge, publish and complete a strictly
  newer connected health-window/valid-mark trial; automatic rollback fault
  injection remains open under #172.

## 2026-08-29 exact-main Target 295 connected rollback

- PR #192 passed Hosted Trusted, OTA-contract and ESP32-C6 canary checks and
  merge-commit produced actual main `a2f7ae2fc4bd1f4fa19839e1021d18cce85ad4fc`.
  Run `33203136822` published it as signed/encrypted exact 295.
- Connected 293 installed 295 and exact 295 emitted `pending image health
  window started` while relay OFF, Wi-Fi, MQTTS, ACL and GATT/iBeacon returned.
- A pre-VALID USB line-state reset caused automatic bootloader rollback to
  previous VALID 293, whose services recovered. Reusing signed 295 was then
  rejected as downgrade by the durable highest-seen-version contract.
- Automatic rollback injection is therefore connected PASS. A strictly newer
  exact-main must still emit the explicit application VALID mark; relay
  contacts/load, sensor threshold, door motion and hard power-loss stay open.

## 2026-08-29 exact-main Target 296 health acceptance

- Final policy PR #194 merge-commit produced exact main
  `21c5d560a82a633831ed40e600cdcf5aad59688f`; run `33204658431` published it
  as signed/encrypted `2.1.296+main.g21c5d56` with matching HTTPS evidence.
- VALID 293 installed exact 296. The new slot logged application health-window
  start, kept relay OFF, restored Wi-Fi, MQTTS, ACL v347 and GATT/iBeacon, then
  explicitly marked the running image VALID.
- A deliberate reboot retained exact 296 without another pending window and
  restored relay OFF, Wi-Fi, MQTTS, ACL v348 and GATT/iBeacon. Together with
  the 295 rollback trial this closes issue #172.
- Hard power-removal, physical relay contacts/load, AJ-SR04T threshold, door
  motion and OEM screen-off repetition remain independent open Gates.

## 2026-08-29 exact-main 301 connected ARMED-preemption acceptance

- PR #198 passed fresh Trusted, OTA, ESP32-C6 and Android checks after its
  merge-connection to the authorized policy main. It merge-commit produced
  feature main `618220e106b0bc2eee5faba6485a54dd66a8b7c6`; final policy rotation
  produced exact main `f352a78db6870339c8e59f75e28fce0e3c327a07`.
- Target run `33212529200` published signed/encrypted
  `2.1.301+main.gf352a78`. Connected exact 298 accepted it, verified the
  inactive image, rebooted, restored relay OFF, Wi-Fi `192.168.35.18`, MQTTS,
  ACL v365 and GATT/iBeacon, then emitted `running image marked VALID after
  health window` and `already current`.
- Mobile run `33212529199` published production-signed
  `1.0.0-gf352a78` / 24101 to primary and fallback. The 55,786,649-byte APK,
  SHA-256 `051a442a485ef4355e2207d0ef977bf929a57f7dff1215f0df4d66753fe03495`,
  embedded exact commit and signing-certificate SHA-256
  `8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0`
  matched before `adb install -r`; the original first-install time remained.
- A fresh OS beacon callback at 06:46:23 completed the action-1 GATT worker at
  06:46:28. Dashboard action 2 began at 06:46:50, within the 60-second ARMED
  window, completed its own authenticated GATT session and returned
  `문이 열렸습니다 (4530ms)`. Target serial recorded relay command ON and the
  timer-bound OFF without reset.
- This closes issue #197's action-1 ARMED replacement incident for the
  connected board/FSM/GPIO-command path. It does not prove contact voltage,
  attached load, actual door movement, AJ-SR04T threshold or repetition SLO.

## 2026-08-30 unified mobile settings source state

- The main WebView AppBar and degraded recovery shell now route to one
  `AppSettingsScreen` rather than exposing separate Smart Key control and
  engineer-debug pages.
- The unified screen keeps user controls and privacy-safe Target status in the
  `Smart Key` tab, and RSSI/scan diagnostics, Target tuning and logs in the
  `진단·튜닝` tab. Manual refresh and independent mobile OTA access remain
  present.
- Focused Flutter analysis, eight navigation/recovery tests, the complete
  44-test Flutter suite and the 316-test repository contract suite pass (one
  platform-specific test skipped). Signed APK publication, install and
  connected on-device visual confirmation remain separate release evidence.

## 2026-08-30 mobile usability planning baseline

- Annotated tag `baseline-mobile-usability-2026-08-30` is pushed and
  dereferences to exact main
  `38fe3b164e6615a9b727910a7776de5d5747eec7`. Its published identities are
  mobile `1.0.0-g38fe3b1` build `30501` and Target
  `2.1.359+main.g38fe3b1`; the disconnected phone means installation and visual
  acceptance remain unclaimed.
- The source-backed plan in `mobile_usability_improvement_plan.md` prioritizes a
  native plain-language Home, credential-bound tenant/door state, truthful
  activity/results and reason-specific recovery before localization,
  accessibility, support and measured latency iteration.
- Current product gaps include the WebView's retired device-ID status authority,
  its non-functional user history call to an administrator-only API, unwired
  `DoorState`/`EnrollmentState` models, no durable user activity notification,
  mixed hard-coded ko/en copy and engineering controls in the normal Smart Key
  tab. No implementation change is included in this planning baseline.

## 2026-08-30 mobile P0 native-home candidate

- Issue #265 source now makes a native Home/Activity/Settings shell the normal
  ready-state entry. It joins native wake/GATT health with an authenticated
  personal Backend status contract and exposes one context-sensitive next
  action; installer timing and feature controls remain under `고급 진단`.
- Personal status and lifecycle routes bind the legacy migration context to the
  exact AndroidKeyStore credential ID and public key. `access_ready` additionally
  requires an active tenant, credential, door grant, current signed ACL entry
  and Target ACK; a device-ID-only legacy row can never report ready.
- A bounded on-device timeline and Android terminal notifications distinguish
  `출입 준비 완료` from physical `문 열림`, remove the non-functional admin-log
  history affordance and preserve proof-uncertain no-auto-retry semantics.
- Nine Backend ACL tests, Flutter analysis and all 49 Flutter tests pass. Hosted
  Android Gradle/Trusted/Backend/OTA checks, exact-main signed publication and
  NAS deployment are still pending. The phone remains disconnected, so install,
  visual, notification, background and physical results remain unclaimed.

## 2026-08-30 mobile P0 merge and P1 experience candidate

- PR #266 merged as exact main `8ea9ff1f8177bf49dba524b11d586715af5e1f6b`
  after Backend, Trusted, OTA, Flutter and hosted Android APK checks passed.
- Issue #269 source now generates ko/en resources for the normal Home/Activity/
  Settings shell and uses the system locale, while keeping engineering details
  behind the existing advanced diagnostics route.
- Normal settings projects installed and available app versions, signed update
  progress and replacement first-run health without weakening installer
  confirmation, signature/hash validation, old-app preservation or independent
  recovery access.
- The in-app support report is preview-first and bounded. Copy remains disabled
  until explicit consent; exported data uses an opaque event reference and
  excludes tenant label/name, unit, MAC, token, key and proof values.
- These are source/widget results until PR #269 CI/merge and exact-main signed
  publication complete. The disconnected phone leaves TalkBack, 200% font,
  landscape/foldable, install, notification, Target transition and physical
  door acceptance pending.

## 2026-08-30 mobile P1 merge and final policy rotation candidate

- PR #270 merged as main `2ae453a0206796650ee99da0e0e57b8fb5078598`.
  Hosted Android APK completion, exact-main signed mobile publication and NAS
  backend readiness are still tracked independently.
- Issue #271 rotates the sole persistent trusted bundle from its transitional
  P0 identity to `current-main-baseline` at actual merged mobile UX main. P1
  changed no protected path, so all 83 reviewed protected digests remain exact.
- The policy candidate changes no runtime. Connected phone acceptance and
  physical Target/door evidence remain pending even after CI and NAS succeed.

## 2026-08-30 private Tailscale NAS deployment completion

- Public DSM SSH `4422` remains closed. DSM OpenSSH moved to `8822`, and the
  deployment control plane uses only Tailscale address `100.95.243.92:8822`;
  no router SSH forwarding is required.
- The live private ED25519/ECDSA host fingerprints matched the previously
  accepted DSM keys. GitHub `production` pins the exact private endpoint and
  the `tag:sgk-github-deploy` identity is allowed only to that NAS SSH port.
- Status-only preflight run `33289323225` attempt 2 passed OIDC Tailscale join,
  strict host-key verification, restricted deploy-key authentication and the
  forced dispatcher with `status=deployed`.
- Backend run `33269719228` attempt 2 reran only its failed deploy job and passed
  with canonical `status=deployed`, exact source
  `8ea9ff1f8177bf49dba524b11d586715af5e1f6b`, matching status readback,
  `loopback_ready=passed` and `public_ready=passed`.
- An independent strict-TLS check returned HTTP 200 for public `/live` and
  `/ready`; both reported the exact deployed build and every readiness check was
  `true`. This proves backend deployment/readiness, not phone installation,
  Target OTA transition, notification delivery, sensor/relay operation or
  physical door motion.
- Exact final-main mobile run `33270789676` and Target run `33270789693` remain
  successful at `89164ce4eb43f6deba8667bf9db6926fcfedfe46`, including both signed
  personal OTA publication jobs. The disconnected phone and physical Target
  acceptance Gates remain open.

## 2026-08-30 connected mobile/Target software acceptance and physical boundary

- The connected Fold7 replacement-installed production-signed
  `1.0.0-g89164ce` / 31501 after APK size/hash/package/commit and signer
  continuity checks. First-install time, app data, AndroidKeyStore-backed
  registration and required permissions remained intact.
- The connected ESP32-C6 booted valid `2.1.364+main.g89164ce`, asserted relay
  OFF, restored Wi-Fi/MQTTS, applied signed ACL v539 and enabled GATT/iBeacon.
  Backend `/live` and `/ready` remained HTTP 200 at exact deployed source
  `8ea9ff1f8177bf49dba524b11d586715af5e1f6b` with all readiness checks true.
- One foreground native action 1 completed with `ARMED 1726 ms` and a separate
  manual action 2 completed in 1846 ms; independent Target serial captured the
  latter relay-command ON and timer-bound OFF. One screen-off/background
  `FIRST_MATCH` at RSSI -54 completed the GATT Worker and posted a result
  notification while `screen_interactive=false`.
- Ordinary process-absent cold wake remains pending: Android kept the active
  foreground-service PID alive and the shell could not stop that non-exported
  service. No force-stop was used because it deliberately disables automatic
  wake until the user reopens the app.
- A pending newer Target image failed its health window and automatically
  rolled back to valid 364. After transient `AUTH_EXPIRE`/`NO_AP_FOUND`, the
  bounded recovery loop restored Wi-Fi `192.168.35.18`, MQTTS, ACL v541 and
  GATT/iBeacon. Same-version replay was then rejected as `downgrade`; a strictly
  newer publication is required for the next health-to-VALID installation.
- AJ-SR04T, 5 V ECHO protection, relay module/contact/load, actuator and door
  were absent. Therefore distance-triggered pocket opening, electrical
  actuation, actual door motion, repetition SLO and hard power-loss remain open
  physical Gates. The action-2 UI text `문이 열렸습니다` currently overstates
  the proven command/FSM result and requires truthful wording or independent
  physical confirmation.

## 2026-08-30 GitHub issue hygiene and current open register

- Audited all nine open issues against merged PRs, exact NAS deployment and the
  connected mobile/Target evidence. Issue deletion was not used; completed or
  duplicate tracking was closed with an evidence comment so history remains.
- Closed #262 as completed after its authoritative credential/ACL card was
  replacement-installed and visually confirmed. Closed redesign Epic #13 as
  completed because Wave 0~3 and bounded connected foreground/screen-off GATT
  acceptance are done; remaining commercial Gates are already consolidated in
  #51, #54 and #48 and were not declared complete.
- Updated release Epic #48 to the 2026-08-30 deployed/runtime baseline. Updated
  #50~#53 and #179 with passed evidence and narrowed remaining acceptance; #54
  retains the latest physical trial and stays open. Added area-appropriate
  `bug`, `enhancement` or `documentation` labels.
- Opened #276 for the independently actionable truth defect where manual
  action-2 displays `문이 열렸습니다` after Target command/FSM/GPIO success
  without an authoritative contact/door event.

| Open issue | Current owner boundary |
|---|---|
| #276 | truthful command result versus physical-open confirmation |
| #179 | Bluetooth OFF→ON wake-registration recovery |
| #54 | sensor/relay/door, RF/soak, operator and production canary |
| #53 | independent manual walkthrough and zero product/manual mismatches |
| #52 | alert drills, recurring recovery, RPO/RTO policy and 24-hour SLO |
| #51 | process-death/OEM 100-run, accessibility and repeated mobile SLO |
| #50 | production device hardening, power-loss, RELAY/OTA matrix and soak |
| #48 | aggregate commercial-release approval |

The register contains eight open issues after the cleanup. It intentionally
keeps broad release Gates open while removing only completed or duplicate
tracking.

## 2026-08-30 truthful action-2 result source candidate (#276)

- The mobile projection no longer maps background durable `SUCCEEDED` to
  physical `confirmed`; it maps to `armed`, while queued/running/retry-pending
  remain authorization progress. `confirmed` is reserved for a future
  independent authoritative contact/door event.
- Home, hosted WebView and advanced control now treat native `OPENED` as
  `개방 명령 실행 완료` and explicitly say physical door opening is not
  confirmed. Accepted-but-non-`OPENED` and proof-uncertain results become
  unknown and prohibit automatic retry; non-accepted results remain failures.
- Manual action-2 outcomes are written to the bounded privacy-safe activity
  timeline with command-executed/unknown/failed types, latency where available
  and a normalized bounded reason. Raw Target addresses, credentials, proofs
  and tenant data are not persisted.
- Local Flutter analysis reported no findings, all 57 Flutter tests passed,
  Android `gattworker.*` unit tests rebuilt and passed, and all 317 repository
  contract tests passed with one expected platform-specific skip. PR #278
  merged as exact main `b96afb7de3e13c2cfcf38326ffbf402568fa2838` after all
  required checks passed.
- Exact-main mobile run `33298655135` built, signed and atomically published
  personal OTA `1.0.0-gb96afb7` / 32001. Independent strict-TLS manifest/APK
  readback matched the 56,134,809-byte artifact, SHA-256
  `5ca0b476bf34a638ad92a82b630e9eca6a5ac1169b20cb947e3ac267b693863f`
  and pinned Android signer digest.
- The authorized Fold7 replacement-installed that exact APK with `install -r`:
  version advanced from `1.0.0-g89164ce` / 31501 to
  `1.0.0-gb96afb7` / 32001 while first-install time, native registration,
  tenant label, one-door assignment and ACL 566 remained present. A bounded
  Korean action-2 readback returned Target command execution in 2007 ms and
  rendered the corrected physical-evidence disclaimer.
- App-locale switching exposed a remaining issue-specific gap: the terminal
  Home message was retained as an already-rendered Korean string, and a
  distinct English-mode failure also used a Korean generic error. The current
  implementation preserves the terminal outcome as a semantic message and
  resolves success, unknown, failure and core Home recovery text through the
  active ko/en localization at render time.
- PR #280 passed trusted-policy, OTA/schema, Flutter, native GATT and Android
  canary checks and merged as `6d7ed42c56483ee61ee4f36302428c0c7a7d3db6`.
  Exact-main run `33300474502` passed the isolated unsigned build and signed
  primary/fallback NAS publication. Independent strict-TLS download bound
  `1.0.0-g6d7ed42` / 32301 and its 56,134,809-byte APK SHA-256
  `da629f3c43d56302860cfe506c234f48569e06424a135ed355d014ff8964ae94`
  to the exact commit; embedded source identity, APK v2/v3 signatures and the
  pinned signer digest also matched.
- `adb install -r` advanced the authorized Fold7 from 32001 to 32301 while
  preserving first-install time and the registered identity. The exact app's
  English ready Home was fully localized; one bounded English action-2 ended
  in command-executed at 1834 ms with `Physical door opening is not confirmed`.
  Removing the app-locale override re-rendered the same retained result in
  Korean with the same latency, and final locale state returned to system
  default `ko-KR`. This closes the issue-specific connected ko/en wording Gate.
- The absent sensor/relay/contact/door fixture means distance sensing,
  electrical relay actuation and physical opening remain unverified regardless
  of UI or Target command result.

## 2026-08-30 mobile remote personal-scope production correction

- Owner-side aggregate diagnostics found `tenant_scope_match=NO`,
  `door_scope_match=NO`, zero active credentials/grants in the legacy command
  scope and different personal/command credential and grant sets. This proved
  that deployed mobile v3 was authorizing the AndroidKeyStore credential in the
  wrong scope before MQTT publication.
- PR #290 retained `COMMAND_*` for the signed per-Target MQTTS envelope but moved
  credential and exact-door grant authorization to `ACL_PERSONAL_*`; startup
  also fails closed if the personal scope does not belong to
  `COMMAND_TARGET_ID`. No production ID, credential, grant or database row was
  rewritten to hide the mismatch.
- Exact main `6c12f169bd2d8733352beb3415159a6e60c01081` passed Backend run
  `33311924158`: security/MariaDB, evidence verification, immutable API/DB image
  publication and the owner-approved Tailscale NAS deployment all completed.
  Canonical deployment evidence reported `status=deployed`,
  `loopback_ready=passed` and `public_ready=passed`.
- Independent strict-TLS `/live` and `/ready` returned HTTP 200 for that exact
  build; database, schema, MQTT, secrets, control/admin auth, ACL management,
  legacy retirement and build identity were all true. No post-fix mobile request
  was sent during deployment. One owner-triggered button trial and observed
  Target/relay/physical-door outcome remain pending.

## 2026-08-30 owner remote-open success and fresh-family onboarding defect

- After the personal-scope Backend deployment, the owner used the installed
  `1.0.0-gf403e10` normal `문 열기` button and observed the physical door open.
  This closes one complete mobile credential → Backend → signed MQTTS → Target
  → relay → door observation, while repetition/OEM/SLO remain open.
- A different connected A24 was a true fresh install of the same APK. Android
  16 reported Bluetooth scan/connect, fine/coarse location and notifications
  granted, but Home showed zero doors and Backend unavailable without a
  registration action. No access request or database change was made.
- The app had already generated a provisional AndroidKeyStore credential and
  included it in personal status. Backend treated the not-yet-enrolled valid
  credential ID as a 403, hiding its existing `request_registration` flow.
- Issue #293 source returns the supervised device registration projection only
  when the credential ID is absent from storage. A stored credential ID with a
  different public key still fails closed. Focused 9 and full 149 Backend tests
  pass with the two expected Docker-only skips. Trusted policy main `6a714f8`
  was merge-connected as `79bdf7b`; PR #295 passed fresh checks and merged as
  exact main `bf435bf4c9681c3ef5e926ecc23f8f7619da9bf5`.
- Backend run `33312971831` passed immutable image publication and the
  owner-approved Tailscale NAS deployment. Canonical evidence reported
  `status=deployed` with loopback/public readiness passed; independent
  strict-TLS `/live` and `/ready` returned HTTP 200 for the exact build with all
  checks true.
- The unchanged connected A24 then rendered `스마트키 등록 필요` and
  `등록 요청`; opening it showed the existing name/unit inputs and
  `출입 권한 신청하기`. The owner submitted once and received
  `신청 접수에 실패했습니다`; no successful database mutation is claimed.
- Source comparison established a two-stage contract defect: fresh installs
  generate UUID-shaped `GK-*` IDs, while `/api/v1/user/request` accepted only
  `DEV-*`, and the legacy tenant locator column is fixed at 17 characters. The
  proposed correction accepts the same `DEV|GK` grammar as the personal ACL
  routes, preserves identifiers that already fit, and maps longer values such
  as `GK-*` to a deterministic 17-character digest locator used consistently
  by request, status and bootstrap. Focused flow and
  all 151 Backend tests pass with two expected Docker-only skips. Protected
  policy/CI, NAS deployment, one owner retry, administrator approval,
  credential enrollment, Target ACL publication and daughter-device access
  remain separate Gates.

## 2026-08-31 per-phone resident identity privacy deployment

- PR #306 passed Hosted Trusted, Backend security/MariaDB, OTA/schema, Flutter
  format/analyze/unit, native GATT and Android canary checks and merged normally
  as exact main `4a3067ce45faea01fcc7d1097cf19d2e112dfbc1`.
- Backend run `33318827231` published immutable API/database images and
  completed the owner-authorized restricted-Tailscale NAS deployment. Canonical
  evidence reports `status=deployed`, exact source, and passed loopback/public
  readiness. Independent strict-TLS `/live` and `/ready` both returned HTTP 200
  for the exact build with every readiness check true.
- Mobile run `33318827185` passed the complete Flutter/native suite and signed,
  atomically published and HTTPS-read-back personal OTA
  `1.0.0-g4a3067c` / `35101`. Independent strict-TLS primary and fallback
  manifests both returned HTTP 200 and matched exact commit and APK SHA-256
  `654d1d726b3ab56628d36c560db8cc5e0a5bce6c433c73606a207776bb019ace`.
- Target run `33318827246` also built, signed, atomically published and
  HTTPS-read-back exact-main personal firmware `2.1.395+main.g4a3067c`. The
  application change did not require a Target behavior change, and publication
  alone is not Target install/reboot/health evidence.
- The deployed Backend and published app now project a resident name/unit only
  from the account row bound to that phone's verified AndroidKeyStore
  credential. The app never renders an older shared ACL `tenant_label` as a
  resident identity, so missing/N-1 profile data becomes generic rather than
  exposing the household owner.
- The publication evidence is explicitly personal/non-release evidence. No APK
  was installed during this work. Wife/daughter phone update and visual
  confirmation that each phone shows only its own approved name/unit remain the
  final device acceptance Gate.

## 2026-08-31 mobile account/settings and schema automation implementation

- The owner visually confirmed that family phones now show their own approved
  identity. This closes the per-phone label acceptance Gate for that observation;
  it does not broaden physical door or OEM repetition evidence.
- Native registration now replaces the legacy `/app` onboarding path and cannot
  render door-open or installer controls. Normal Settings no longer navigates to
  GATT/RSSI tuning; a console-assigned, server-projected `TENANT_ADMIN` role alone
  reveals the separate administrator entry, whose unsafe operations still require
  existing console reauthentication.
- Server-first signed logout, migration 010 and a manifest/image-bound automatic
  schema runner are merged. Protected CI passed, the one-time stable wrapper was
  installed, and schema 010 plus exact-build readiness were verified on NAS.
  APK installation and logout/registration/admin UI device acceptance remain
  separate Gates.
- Local validation passed the complete Backend suite (`162`, two environment-only
  skips), MariaDB 10.11 migration integration (`13`), Flutter analyze and unit
  suite (`66`), and targeted Android native JUnit (`49`). The OTA/operations
  contract run exposed only the expected pre-authorization trusted-policy digest
  mismatch after stale recovery-manual assertions were corrected and rerun.

## 2026-09-01 native-wake registration recovery publication

- PR #323 separated durable native-wake intent from current-process
  reconciliation evidence, bounded transient recovery to one native WorkManager
  chain, and serialized native/legacy scanner ownership. Required PR checks
  passed and the change merged normally as exact main
  `e0d809cfb6b31a532840c66eb250ae6feaf82c7b`.
- Exact-main OTA contract run `33457276522` passed. Mobile run `33457276558`
  signed and atomically published personal OTA `1.0.0-ge0d809c` / `37401`;
  Target run `33457276556` signed and atomically published unchanged-source
  personal OTA `2.1.412+main.ge0d809c`.
- Independent strict-TLS readback matched the exact commit and published
  manifests. Mobile primary/fallback were byte-identical 55,200,921-byte APKs
  with SHA-256
  `5964dffaa9f1e5c0978be90388f64d7bf2720a82cd8fff39cc7eee53b6ca4e8a`;
  the 1,850,036-byte encrypted Target artifact matched SHA-256
  `71c845c219efd0b23983efa83215acb00fbc602d02282d7585fe3b58fa6d32da`.
- Publication evidence is explicitly personal and non-release
  (`production_authorized=false`, `release_evidence=false`). No phone install,
  screen-off wake, Target detection/authentication, `ARMED`, sensor/relay,
  Target install/reboot/health or physical door result is inferred. #179 and
  the broader #51 remain open for connected acceptance.

## 2026-09-01 administrator Target access timeline implementation

- Schema 011 adds a separate append-only `access_event_history` projection for privacy-safe Target
  canonical access events. Exact topic binding, strict envelope/catalog validation, bounded worker
  offload and exact replay-versus-conflict checks are implemented without reinterpreting legacy
  `access_logs.is_success`.
- The administrator timeline now distinguishes proof verification/denial, ACL denial, `ARMED`,
  sensor threshold detection, relay ON/OFF and session completion/termination. A legacy manual
  remote success is labelled only as Backend transmission acceptance, not Target or physical-door
  success.
- PR #326 passed Hosted Trusted, Backend/MariaDB and OTA/schema checks and merged normally as exact
  main `3d3e041b9b64ac514b9b05e8ae71aa2221955d33`. Backend run `33516916385`
  published digest-pinned API/DB images and deployed schema 011 through the restricted Tailscale
  forced-dispatch path. Deployment and status evidence matched, with loopback/public readiness
  passed.
- Independent strict-TLS `/live` and `/ready` returned HTTP 200 for that exact build. Every readiness
  check was true, including `database_schema`, `mqtt` and `access_event_collector`. The public
  administrator asset also contains the new `최근 전체 출입 감지 이력 (수신 이벤트)` contract.
- Canonical publication remains Target QoS 0 with a bounded offline queue. Missing events therefore
  remain `unconfirmed`, and the current no-door-contact hardware cannot prove physical door travel.
- Collector readiness now fails closed until every configured canonical subscription receives a
  successful SUBACK and also fails on disconnect, dead writer, queue overflow or persistence failure.
  UTC receive timestamps are explicit and the administrator “today” count uses the KST day boundary.
- A same-day read-only NAS inspection found deployment drift: the running Mosquitto config has no
  `password_file` or `acl_file` and permits anonymous access on both 1883 and 8883. Collection is
  operational under that topology, but broker-principal provenance and topic isolation are not
  production-grade evidence. This confirmed P0 remains tracked in #50 and requires a staged
  credential/ACL migration; it was not hidden or altered by the access-history deployment.
- No natural post-deployment Target access event has yet been correlated in the administrator UI.
  Target relay/session events, when received, remain firmware lifecycle evidence rather than proof
  of physical door travel because no door-contact sensor is present.

## 2026-09-03 durable signed-MQTT terminal candidate

- The deployed `2.1.434` status-summary path proved one signed manual completion in Backend and HA,
  but retained only the newest terminal in boot-local RAM. A second completion before safe-state
  publication or a reboot could therefore hide the earlier terminal from HA/admin history.
- The local candidate emits one separately HMAC-signed canonical terminal for every signed MQTT arm
  or manual session, enqueues it without socket I/O, preserves FIFO through the existing NVS queue,
  and derives its `mqtt_prearm`/`mqtt_manual_remote` route from a MAC-covered event code.
- Backend schema 013 commits an HA projection outbox row with each authenticated DB insert. Its worker
  publishes QoS 1 and waits for PUBACK before completion; an exact replay reuses the same outbox identity.
  A crash after PUBACK but before DB acknowledgement may repeat the stable marker, so this is durable
  at-least-once rather than exactly-once. The existing latest-result sensor
  remains unchanged for Backend N / Target N-1 compatibility.
- Backend 197/197 tests passed with two environment-only skips; repository discovery ran 343 tests
  with 337 passes, one skip and six expected trusted-policy/build-map mismatches before the map was
  refreshed. The personal-production firmware built warning-free at 75,880 bytes RAM and 1,766,442
  bytes application flash. Protected-policy rotation, normal merge, exact Backend/Target deployment
  and a repeated live access test remain open; no installed device changed from this local work.

## 2026-09-03 crash-durable access Activity rollout

- Policy PR #347, feature PR #348 and final-policy PR #349 passed their hosted
  checks and merge-committed normally. Exact feature main is
  `6aa8d188f509f2135c1551abca9284022ef88e2d`; final policy main is
  `f4e22654eca1bce44044b5a461d2185c5982806a`, and all 102 protected blobs
  retain the immutable feature bytes.
- Owner-approved Backend run `33668277642` completed immutable image
  publication, schema 013 migration and restricted NAS deployment. Independent
  strict-TLS `/live` and `/ready` returned HTTP 200 for exact feature main with
  every check true, including database schema, MQTT, access-event collector,
  access-evidence integrity and build identity.
- Target run `33668277535` built, encrypted, signed, atomically published and
  HTTPS-read-back `2.1.436+main.g6aa8d18`, build ID
  `main-436-6aa8d188f509f2135c1551abca9284022ef88e2d`. Publication is complete,
  but no fresh Target boot/version observation proves installation yet.
- The owner reported that the recent-access result changed. This confirms the
  already-deployed latest-status entity advanced; it does not by itself prove
  schema 013 canonical history, the administrator row or one HA event for every
  completion.
- Windows Computer Use failed before browser selection because the WSL cwd was
  not accepted as a Windows-local URI. The Target MQTTS principal correctly
  could not read status or publish to the HA bridge under the reviewed broker
  ACL, and station-local TCP/80 recovery remained unreachable. No duplicate OTA
  request, direct unsigned command, NVS erase, full flash or relay action was
  attempted. One owner press of the HA OTA button and subsequent exact
  version/reboot/health readback remain the installation Gate; repeated live
  administrator/HA correlation remains the delivery Gate.

## 2026-09-04 Target connectivity self-recovery authorization candidate

- Immutable feature `d0e43188449495ed33c860019fc1093b05491700` contains the validated
  asynchronous MQTT/TLS recovery, bounded access leases, staged signed reboot, restart-safe
  access evidence, retained boot diagnostics and exact HA broker-receipt completion changes.
- The trusted-policy candidate binds all 102 protected paths to that immutable feature; nine
  protected blobs change and the other 93 retain current-main bytes.
- This is policy/source evidence only. Hosted policy and feature merges, actual-main rotation,
  Backend/NAS deployment, signed OTA publication, Target install/reboot and post-update health
  remain pending.

## 2026-09-04 Target connectivity self-recovery actual-main merge

- Policy PR #355 and feature PR #356 passed their hosted checks and merge-committed normally.
  Actual feature main is `7774060ba580a64e925727dfbc17c7c045ed58e2`; immutable feature
  `d0e43188449495ed33c860019fc1093b05491700` remains in ancestry.
- The final policy candidate retires the transition identity and pins the sole
  `current-main-baseline` to actual feature main with all 102 protected blobs unchanged.
- Exact Backend/NAS deployment, signed OTA publication and Target install/reboot/health are still
  runtime Gates until their independent evidence is recorded.

## 2026-09-05 GATT v2 ACL contract defect candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Owner failure evidence | Smart Key Activity showed repeated `GATT_DISCONNECTED` plus one `SIGNATURE_INVALID` at 11:59 after the v2 rollout | CONFIRMED production authentication failure; no assumption about sensor dwell or phone handling |
| Live Target separation | Target remained on exact `2.1.445+main.g57bfe10`, boot 720, same boot ID, fresh IDLE status, MQTT connected with zero connection failures | NOT a current Target crash or MQTT outage |
| Source root cause | Android selects fast protocol v2 when Fast RX/TX exist, but personal enrollment and replacement ACL defaults remained `1..1`; `TargetProofVerifier` correctly returned unsupported version and `ProtocolCore` incorrectly exposed it as proof/signature invalid | ROOT CAUSE CONFIRMED across Android, Backend and Target source |
| Corrective contract | Personal enrollment is exact `2..2`; migration 014 upgrades stored credentials and queues active doors; every replacement refresh signs `2..2`; Target preserves unsupported-version as protocol-incompatible | SOURCE FIX IMPLEMENTED; no credential private material or raw device identifier is migrated |
| Host and DB validation | Backend discovery passed 213 tests with two declared skips; Target/common discovery had 355 functional passes and one declared skip, with only 12 expected pre-authorization digest failures; a real MariaDB image passed idempotent 013→014 upgrade of a live `1..1` credential to `2..2` plus replacement-job creation | FUNCTIONAL PASS; protected policy rotation remains required |
| Firmware build | `esp32c6_personal_production` built successfully at 76,968/327,680 RAM and 1,818,664/7,340,032 application flash | PASS for compile/partition fit only; not signed publication or installation |
| Runtime boundary | No corrected Backend, APK or Target artifact has yet been merged, deployed or installed; no post-fix phone access has been attempted | PENDING trusted-policy rotation, CI, Backend schema 014 deployment, mobile/Target publication, installation and owner access confirmation |

## 2026-09-05 GATT v2 ACL protected authorization candidate

- Immutable feature `7edd3aa39bd762c06e791ff2661b1b01f3d3a0c5` contains the
  v2 personal enrollment contract, schema 014 credential upgrade and queued ACL
  replacement, plus truthful Target protocol-mismatch reporting.
- The trusted inventory expands from 102 to 104 paths for migration 014
  up/down. Fourteen protected blobs change or are added; the remaining 90 and
  the workflow/action inventories retain trusted-main bytes.
- Focused policy tests passed 42/42, and the GitHub API verifier approved all
  104 candidate paths under the sole exact persistent bundle.
- This is source authorization only; feature CI/merge, Backend deployment,
  signed APK/Target publication, installation and phone authentication remain
  pending.

## 2026-09-05 GATT v2 ACL merged source and final policy rotation

- Policy PR #358 and feature PR #359 passed their required hosted checks and
  merged normally. Exact feature main is
  `382c4f86a4ef4164acd32eecc29b7a4c6908354c`, containing immutable reviewed
  feature `7edd3aa39bd762c06e791ff2661b1b01f3d3a0c5` in its ancestry.
- Android/native GATT, firmware canary, Backend/MariaDB, OTA/schema, canonical
  vectors and trusted-policy checks all passed on the merge-connected feature.
  These prove source/build contracts, not installed runtime behavior.
- The final policy candidate retires the transitional identity and pins the
  sole `current-main-baseline` to actual feature main with all 104 protected
  bytes unchanged. Backend schema 014 deployment, signed Android/Target
  publication, installation, reboot/health and owner access confirmation remain
  separate pending Gates.

## 2026-09-05 GATT v2 ACL production rollout

- Owner-approved Backend run `33942785068` published immutable API/DB images,
  created a pre-migration backup, applied schema `014`, and deployed exact
  feature main `382c4f86a4ef4164acd32eecc29b7a4c6908354c`. Canonical loopback/public
  readiness passed; independent strict-TLS `/ready` returned that exact SHA
  with every check true, including database schema, MQTT, collector and ACL
  management.
- Final-main Target run `33942948534` signed and atomically published encrypted
  `2.1.448+main.g6d8ab48`. One owner-approved HA `trigger_ota` request received
  QoS 1 PUBACK, Backend `broker_accepted`, Target command ACK result 0 and
  Backend `target_accepted`; no duplicate request was sent.
- The Target advanced from boot 720 / `2.1.445+main.g57bfe10` to boot 721 /
  `2.1.448+main.g6d8ab48`, new boot ID
  `38f688d0768d84ad0b2b1a2b204f0662`, SOFTWARE reset and IDLE. Read-only MQTTS
  held the same version/boot through uptime 126 seconds, beyond the 30-second
  valid-mark and 120-second rollback windows, with MQTT connect 1/1, failures
  0 and Backend verified-status advancing.
- Final-main mobile run `33942948521` signed and atomically published
  `1.0.0-g6d8ab48` / version code 41501 and verified primary/fallback HTTPS
  readback. Phone installation is not claimed.
- The passive post-deploy ACL-ACK subscription began after schema migration and
  received no new ACK in its bounded window, so exact migrated snapshot ACK is
  not reconstructed from that observation. A fresh owner phone authentication
  is still required to close the GATT v2 credential/ACL acceptance and physical
  access Gate; the agent issued no relay or door-open action.
- Final readback later found boot 722, boot ID
  `e8c8d996c89184110d83c011a38a6ba0`, with reset reason `BROWNOUT`. It retained
  exact `2.1.448+main.g6d8ab48`, was online/IDLE at uptime 344 seconds, reported
  MQTT 1/1 with zero failures and continued Backend verified-status. This is a
  separate electrical/reset event after the successful OTA health window, not
  firmware rollback; the repeated brownout cause remains a field power Gate.

## 2026-09-05 post-rollout hands-free no-response incident

- The owner reported that a fresh entrance approach produced no automatic
  reaction and that the authenticated app `문 열기` button was used successfully
  to enter.
- A read-only MQTTS readback at 17:28 KST found the Target online and IDLE on
  boot 723, exact `2.1.448+main.g6d8ab48`, with uptime 9,266 seconds, MQTT
  attempts/connects `1/1`, zero connection failures and an empty volatile event
  outbox. Backend `/ready` returned every check true.
- The retained terminal result was `ACCESS_SESSION_COMPLETED / ACCESS_GRANTED`
  with phase mask 24 (`0x18`), which is the signed MQTT manual-open success
  contract. This confirms the fallback path but is not hands-free GATT evidence.
- No retained Local GATT terminal result followed the incident. Because the
  manual result replaces the single last-terminal slot, the readback cannot say
  whether an earlier phone wake never arrived, failed before a terminal Target
  result, or was overwritten. The current boot uptime rules out a Target reboot
  immediately around this incident, but historical administrator rows or the
  phone Activity entry are still required to split BLE wake absence from GATT
  dispatch/transport failure.
- No access, OTA or configuration command was sent during diagnosis. A source
  change is not attributed to this incident until the same-cycle phone Activity
  or administrator history is correlated.
- The subsequent owner Activity capture closes part of that gap: the most recent
  automatic entries are `RUNNING` at 14:38:57 and
  `PROTOCOL_INCOMPATIBLE` at 14:39:00, while 17:13:07 is only the manual remote
  command. There is no automatic detection/authentication entry around the
  after-17:00 entrance attempt. The 14:39 Target-originated protocol result
  proves that iBeacon/GATT radio was available then, but not that advertising
  restarted or remained active afterwards.
- Source inspection found that the ESP32-C6 calls advertising start at boot and
  after disconnect but discards the return value. It had no controller
  `isAdvertising()` watchdog, recovery counter or MQTT diagnostic, so a silent
  post-disconnect advertising stop can coexist with healthy Wi-Fi/MQTT status.
- Candidate remediation now polls NimBLE advertising state every two seconds
  only when no GATT connection is active, performs a bounded restart when the
  controller reports stopped, and publishes advertising/restart plus active ACL
  version and protocol range diagnostics. HA discovery adds a read-only
  `[Gatekeeper] BLE 광고 상태` entity. This is source/build evidence until
  reviewed, deployed and read back from the installed Target.

## 2026-09-05 BLE advertising self-heal authorization candidate

- The 17:13 manual-open record proves Backend-to-broker delivery, while the last
  automatic Target authentication at 14:39 proves BLE/GATT only at that earlier
  time. No post-17:00 activity entry proves that the Target was still advertising.
- Immutable feature `148d7b6de6be476e9680da4bb98444dfc5a80899` adds a no-client
  advertising watchdog plus Target MQTT diagnostics for advertising state,
  restart counters, physical connection count and the installed ACL protocol range.
- The trusted-policy candidate changes exactly three of 104 protected blobs;
  the other 101 and both workflow inventories retain trusted-main bytes.
- This is source authorization only. Exact-main publication, Backend/NAS
  deployment, Target OTA/reboot/health and an external BLE scan or fresh phone
  access remain separate runtime Gates.

## 2026-09-05 BLE advertising self-heal merge connection

- Policy PR #361 passed and merge-committed as main
  `89225afa162619f7f8448703b7b9b2775eb7b98e`; that exact policy main is
  merged into the feature history with immutable feature `148d7b6d` retained.
- The next evidence Gate is fresh hosted feature CI over the merge-connected
  source. Publication, Backend deployment, Target OTA, controller-state readback
  and over-air emission remain unclaimed.
- Local merge-connected validation passed 42/42 focused policy tests and 368/368
  repository tests with one declared environment skip; hosted feature checks remain
  the merge Gate.

## 2026-09-05 BLE advertising self-heal actual-main merge

- Feature PR #362 passed the hosted firmware, Backend, OTA and trusted-policy
  checks and merge-committed normally as actual main
  `1aacbaf073731c6ed8b3c703254d2e5e12bb9990`.
- The final policy candidate pins the sole `current-main-baseline` to that exact
  merge with all 104 protected bytes unchanged from the reviewed feature.
- Publication/deployment, Target OTA/reboot/health, reported advertising state
  and physical RF/access verification are still independent runtime Gates.

## 2026-09-05 BLE advertising rollout and brownout-safe retry

- Backend run `33956526362` deployed exact feature main `1aacbaf0`; strict-TLS
  `/ready` reported every dependency healthy. Final-main Target run `33956619291`
  published signed `2.1.451+main.ga683832` with HTTPS readback.
- One OTA request was broker- and Target-accepted. The pending candidate booted
  as unobserved boot 724, reset after a 2,094 ms BOOTING breadcrumb with
  `BROWNOUT`, and the bootloader safely restored `2.1.448` as boot 725.
- Boot 725 remained online/IDLE beyond uptime 216 seconds with MQTT 1/1 and zero
  failures. Because `2.1.451` is now rollback-quarantined, this docs-only exact-main
  retry commit intentionally creates one strictly newer signed version; no second
  device request occurs until its publication and stable-current evidence pass.

## 2026-09-05 BLE advertising self-heal installed

- Run `33957358126` published signed exact-main `2.1.452+main.g2bedd83` after
  boot 725 remained stable for 927 seconds. One new-version OTA request advanced
  the Target once to boot 726, exact 452, SOFTWARE reset.
- Boot 726 remained online/IDLE through uptime 139 seconds with MQTT 1/1, zero
  failures and an empty outbox, exceeding both OTA health windows without rollback.
- Target status now reports BLE advertising expected/active `true`, no client
  connection and no restart failure, plus active ACL version 1331 at exact `2..2`.
  HA retained discovery for `[Gatekeeper] BLE 광고 상태` is present with a
  30-second expiry.
- This closes source, Backend deployment, signed publication, Target installation
  and controller-state readback. External RF reception, Android wake/authentication
  and a physical hands-free door opening remain owner field evidence.

## 2026-09-05 field diagnostics deployment and Target rollback

- Backend run `33965557195` deployed exact feature main `c9aa85c3` with schema
  015; strict-TLS `/live` and `/ready` return that SHA and all readiness checks
  true. Final-main Target run `33965654223` published exact signed
  `2.1.456+main.gc1d58b1`.
- One safe-preflight HA OTA request was accepted by Backend and Target. The
  candidate booted as boot 730, restored MQTT and BLE advertising, and stayed
  IDLE with relay OFF through uptime 75 seconds, but then the bootloader restored
  exact `2.1.452` as boot 731. Retained diagnostics classify a controlled
  `ota_health_rollback`, not a matching panic/WDT reset. No retry was sent.
- Source correlation identified a fragile equality: the OTA health sampler
  rejected gaps over 1,000 ms while expanded signed status publication also runs
  every 1,000 ms. The corrective candidate tolerates up to 5,000 ms, still well
  below the 45-second loop watchdog, and persists a specific rollback predicate.
  Focused tests and the production Target build pass; trusted review, a strictly
  newer artifact and one bounded OTA/install-health observation remain required.
