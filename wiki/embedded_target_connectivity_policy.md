# 벽 매립형 Target 상시 연결·원격 복구 지침

> 적용 범위: 사용자가 도구 없이 꺼내거나 USB/serial로 복구하기 어려운 현관 ESP32-C6 Target
>
> 목적: 출입 기능과 별개로 Wi-Fi, MQTTS, HTTPS OTA의 원격 복구 가능성을 계속 보장한다.

## 1. 최상위 원칙

1. 매립형 Target은 전원이 켜진 동안 **Wi-Fi STA와 per-Target MQTTS 세션을 항상 유지하려고 시도**해야 한다.
2. 공유기 재부팅, WAN 단절, DHCP 갱신, broker 재시작 뒤에는 사람의 물리 조작 없이 자동 복구해야 한다.
3. MQTT는 즉시 명령 경로이고 HTTPS periodic pull은 독립 OTA 복구 경로다. 둘 중 하나만 존재하는 firmware를 새로 매립하지 않는다.
4. BLE beacon이 보인다는 사실은 Wi-Fi 또는 MQTT online 증거가 아니다.
5. MQTT QoS 1 PUBACK은 broker 수신 증거일 뿐 Target 실행 또는 OTA 성공 증거가 아니다.
6. 100% 무중단 네트워크를 가정하지 않는다. 단절을 빠르게 탐지하고 자동 재접속하며 원격 복구 불가 상태를 경보한다.
7. 네트워크 복구 로직은 `IDLE -> ARMED -> RELAY_HOLD -> COOLDOWN -> IDLE` Target FSM과 독립이어야 하며 relay fail-safe를 지연시키면 안 된다.

## 2. 필수 연결 계약

### 2.1 Target firmware

- 저장된 Wi-Fi 자격 증명이 있으면 STA 연결을 무기한 재시도한다.
- 부팅 시 첫 STA 연결이 실패해 recovery AP가 열리더라도 STA 재시도를 중단하지 않는다. recovery AP는 시간 제한과 인증을 가져야 하며 영구 AP trap이 되어서는 안 된다.
- Wi-Fi disconnect/lost-IP/got-IP callback은 edge와 link generation만 기록한다. Safe loop phase가 generation 변경을 관찰해 기존 TLS socket을 무효화하고, got-IP 뒤 단일-owner worker로 새 MQTTS session을 만든다.
- Wi-Fi 상태는 매 loop에서 radio 변경 없이 관찰한다. 정상 STA 단절이 30초 동안 자동 복구되지 않으면 안전한 IDLE 구간에서 인증된 recovery AP로 승격하고, 실패한 AP 승격은 60초 뒤 재시도한다.
- MQTTS가 끊긴 동안에도 재접속을 계속한다. 현재 구현 기준 재시도는 5초에서 시작해 30초까지 지수 backoff하며 keepalive는 120초다.
- DNS는 lwIP callback과 generation token을 사용해 loop를 막지 않고 5초에 만료한다. TCP 4초, TLS handshake 8초, MQTT protocol read 3초 단계는 secure client와 PubSubClient를 단독 소유하는 bounded connect worker 하나에서만 실행한다. Loop task와 worker는 모두 45초 task watchdog 보호를 받으며, worker는 각 bounded 단계 사이에 feed하고 모든 종료 경로에서 watchdog 등록을 해제한 뒤 결과를 넘긴다.
- Connect 결과는 request ID와 Wi-Fi link generation이 모두 현재값일 때만 loop task가 채택한다. Access 진입이나 link generation 변경은 worker 취소를 요청하고, 늦게 끝난 성공·실패는 stale로 폐기한 뒤 transport를 닫는다. Worker가 객체를 소유하는 동안 loop task는 TLS/PubSubClient를 읽거나 쓰지 않는다.
- GATT 연결, fast-v2 start/write, 인증, ranging, relay hold/cooldown 동안 MQTT/HTTPS socket 작업을 보류한다. 미인증 ingress는 10초 lease를 초과하면 해당 transport만 끊고 네트워크를 즉시 재개하며 Target을 재부팅하지 않는다. 짧은 connect/disconnect 반복은 lease를 갱신하지 않고, 30초 연속 quiet 뒤에만 새 미인증 epoch를 연다. 실제 verified action generation은 별도의 85초 physical lease를 시작한다.
- 각 blocking 단계 직전에 callback-visible ingress를 다시 확인하고 MQTT command가 access를 시작한 같은 loop에서는 stale IDLE/status flush와 OTA를 중단한다. OTA periodic/local TLS는 MQTT connect worker가 끝난 뒤에만 시작하므로 두 handshake가 겹치지 않는다.
- 고유 Target client ID, hostname 검증 TLS, per-Target credential, signed command namespace를 유지한다.
- retained availability LWT/online은 `scope=mqtt_transport`만 의미한다. PubSubClient 2.8은 SUBACK reason을 노출하지 않으므로 broker의 command 구독 승인은 fresh HMAC-signed status와 실제 command/ACK로 별도 판정한다. Retained boot/config와 1초 non-retained status heartbeat를 발행한다.
- MQTT와 무관하게 signed manifest 기반 HTTPS OTA를 부팅 후와 주기적으로 확인하고, 실패 시 bounded retry를 계속한다.
- OTA는 inactive slot, health window, valid mark, 자동 rollback 계약을 유지한다.
- Periodic HTTPS와 authenticated local recovery는 production Target에서 실제 제공되는 동일한 서명 provider를 사용한다. Provider 초기화나 manifest 검증 실패는 artifact 전송과 slot write 전에 중단하고 단계별 원인을 기록한다.
- Signed reboot command는 MQTT callback에서 직접 재부팅하지 않는다. Inbound QoS 1 처리/PUBACK 경계 뒤 main이 새 GATT 인증을 차단하고 callback을 drain한 뒤 verified physical session이 없음을 다시 확인하며, pending access evidence를 checkpoint한 다음에만 재부팅한다.
- Controlled restart 전에는 기존 volatile FIFO를 oldest-first NVS 뒤에 append한다. NVS가 terminal을 수용하지 못하면 reserved RAM tail의 terminal을 포함한 남은 FIFO 전체를 checksum-bound generation의 RTC A/B journal에 보존한다. Inactive slot을 magic-last로 commit하므로 교체 도중 reset되면 직전 valid generation을 복원한다. 이 journal은 cold power-loss 내구성이 아니라 반복 software reset을 위한 degraded recovery다.

### 2.2 NAS, broker, backend

- Mosquitto MQTTS listener, 인증 DB, CA chain, per-Target ACL과 시스템 시간을 상시 유지한다.
- backend는 boot 토픽뿐 아니라 per-Target `availability`와 `status`를 구독해 마지막 수신 시각, boot ID, firmware version, RSSI와 reconnect 상태를 저장해야 한다.
- 동일 client ID를 진단 도구가 사용하지 못하게 한다. 진단 client ID에는 별도 접두사와 read-only ACL을 사용한다.
- offline command를 retained로 남기지 않는다. OTA/door command는 online 확인 후 1회 발행하고 command ACK와 후속 boot/health로 완료를 판정한다.
- `/health` 성공을 Target online으로 표시하지 않는다. API, broker, Target 연결 상태를 별도 상태로 노출한다.

## 3. 운영 SLO와 경보 기준

다음 기준은 개인 PROD의 최소값이다. 더 엄격하게 운영할 수 있지만 완화하려면 근거와 현장 시험을 기록한다.

| 상태 | 판정 | 운영 동작 |
|---|---|---|
| 정상 | 최근 status가 15초 이내이고 boot ID가 현재값과 일치 | 정상 표시 |
| 경고 | status가 15초 초과 90초 이내 없음 | 자동 재접속 관찰, NAS/broker/WAN 상태 확인 |
| 위험 | status가 90초 초과 없음 또는 LWT offline 수신 | 즉시 알림, OTA/원격 개방 명령 중지, 원인 분리 진단 |
| 복구 | 위험 뒤 같은 Target의 새 online/status 수신 | boot ID/reset reason/IP/RSSI/firmware 비교 후 해제 |
| 원격 복구 불가 | BLE만 보이고 10분 동안 Wi-Fi/MQTT가 복구되지 않음 | 현장 조치 incident로 승격; 정상으로 표시 금지 |

월간 연결 가용성 목표는 99.5% 이상으로 두되 계획된 공유기/NAS 유지보수는 별도 기록한다. 단일 10분 초과 원격 복구 불가 사건은 월간 수치와 무관하게 개선 항목으로 남긴다.

## 4. 설치 전 네트워크 기준

- 전용 또는 신뢰 가능한 2.4 GHz SSID를 사용하고 Target 위치에서 반복 RSSI를 측정한다.
- 권장 RSSI는 `-67 dBm` 이상이다. `-75 dBm` 이하는 매립 전 AP 위치, 채널 또는 안테나를 개선한다.
- Target MAC에 DHCP reservation을 설정하고 lease 변경 이력을 확인할 수 있게 한다.
- client isolation, captive portal, 주기적인 강제 재인증, MQTTS/HTTPS 차단 정책이 없는지 확인한다.
- NAS 도메인의 MQTTS와 HTTPS 인증서 만료를 감시한다.
- 공유기, AP, NAS와 broker 재부팅 뒤 자동 복구 시험을 각각 수행한다.
- 전원 공급의 brownout 여유와 relay 노이즈 대책을 확인한다. 네트워크 장애처럼 보이는 reset을 분리할 수 있도록 reset reason과 boot count를 보존한다.

## 5. 매립 승인 Gate

아래 증거가 없으면 Target을 벽에 최종 매립하거나 “원격 유지보수 가능”으로 판정하지 않는다.

1. 전원 재인가 3회 모두 2분 안에 Wi-Fi, MQTTS online, status heartbeat가 확인된다.
2. 공유기/AP 5분 단절 후 물리 조작 없이 2분 안에 online/status가 복구된다.
3. NAS broker 5분 중단 후 물리 조작 없이 2분 안에 재구독과 status가 복구된다.
4. WAN 5분 단절 뒤 MQTTS와 HTTPS OTA check가 모두 자동 복구된다.
5. 잘못된 retained command가 없고 진단 client ID 충돌이 없다.
6. signed OTA 명령 또는 periodic HTTPS pull로 N+1 설치가 완료되고 새 version, boot ID, health valid가 확인된다.
7. 실패 image가 자동 rollback되어 N 버전의 online/status가 다시 확인된다.
8. admin 화면이나 운영 dashboard에서 정상·경고·위험·마지막 수신 시각을 확인할 수 있다.

## 6. 현재 구현 감사와 release blocker

2026-08-12 `main` 기준으로 다음은 구현되어 있다.

- STA 상태 15초 확인과 Arduino core auto-reconnect 감시
- MQTTS 약 5초 재시도, 30초 keepalive, TLS socket reset
- per-Target availability LWT/online, retained boot 진단, 1초 status
- signed per-Target command와 periodic HTTPS OTA
- inactive-slot health/rollback

다음 공백은 **다음 현장 매립 또는 “언제든 원격 OTA 가능” 선언 전 P0 release blocker**다.

- 부팅 STA 실패 후 recovery AP 상태에서도 STA 재시도를 계속한다는 구현·시험 증거
- Wi-Fi lost-IP/got-IP에 맞춘 명시적 TLS socket 폐기·재생성 시험
- backend의 availability/status 구독, last-seen 저장, 15초/90초 경보와 admin 표시
- 공유기, broker, WAN 단절 후 자동 복구 physical evidence

과거 벽 매립본 `2.1.0-g75b946a`는 더 이상 현재 Target 상태가 아니다. 2026-08-24 연결된 Target은 exact-main `2.1.234+main.g3927a97`로 NVS 보존 USB bootstrap 되었고, 첫 STA timeout 뒤 recovery AP+STA가 저장 credential로 DHCP와 exact per-Target MQTTS를 자동 복구하는 것을 실기기에서 확인했다. 이는 회전된 content-key material을 포함한 첫 이미지와 한 번의 복구 세션 증거이며 periodic HTTPS inactive-slot install, health-valid, rollback, 세 번의 power cycle과 장기 outage soak는 아직 닫지 않는다. 이 문서 변경을 포함하는 다음 main을 OTA로 검증한다.

## 7. 장애 대응 순서

1. command를 재발행하기 전에 last-seen, availability, status, boot ID와 firmware version을 read-only로 조회한다.
2. API health, broker listener, Target MQTTS를 서로 분리해 확인한다.
3. 공유기 DHCP lease에서 Target MAC과 IP를 확인하고 2.4 GHz association/RSSI를 확인한다.
4. BLE만 감지되고 Wi-Fi lease가 없으면 STA/AP trap 또는 credential/RF 문제로 분류한다.
5. Wi-Fi lease는 있으나 status가 없으면 TLS, ACL, client-ID 충돌, broker log를 확인한다.
6. online이 복구되면 OTA 명령을 retain=false로 한 번만 발행하고 command ACK 뒤 새 boot/health를 기다린다.
7. 10분 안에 원격 복구되지 않으면 반복 명령을 중단하고 현장 incident로 승격한다.

## 8. 2026-08-23 software recovery closure

The current firmware no longer stops STA recovery after the initial boot
window, but it also does not run an unbounded reconnect loop beside the
recovery AP. A failed boot association opens the authenticated recovery AP in
`WIFI_AP_STA`, disables STA auto-reconnect, and provides at least 30 seconds of
quiet AP discovery before a policy-controlled attempt. A successful
association closes the indefinite provisioning AP and returns to pure STA
mode. Failed attempts do not erase the NVS credentials.
The AP identity is single-sourced by `kRecoveryApSsid` as
`SmartGatekeeper-Recovery`; the same constant is used for the broadcast SSID,
serial ready log and HTTP Basic authentication realm.
An authenticated `/scan` request temporarily pauses a disconnected STA
attempt, performs one bounded synchronous scan with one bounded retry, and
returns to a fresh quiet-AP interval without stopping the SoftAP, immediately
restarting STA, or clearing NVS.
The portal renders the returned SSIDs and RSSI values as an explicit scrollable
list while retaining a manual SSID field as a fallback.

MQTTS provisioning is initialized regardless of whether Wi-Fi is available at
boot. On Wi-Fi loss the stale TLS socket is closed; on Wi-Fi recovery a fresh
TLS/MQTT session is attempted immediately and the normal five-second retry loop
continues after failures. Periodic signed HTTPS OTA remains independently gated
on `WifiManager::isConnected()` and therefore resumes after the same STA
recovery.

These changes close the two identified software gaps: AP-mode STA retry and
late-Wi-Fi MQTT initialization/socket recreation. They are build/static-test
evidence only until the installed Target demonstrates association, DHCP,
MQTTS online/status, periodic HTTPS OTA check, reboot health and outage recovery.

An OTA pending image is marked valid only after both Wi-Fi STA and MQTTS remain
healthy during the stability window. A recovery AP by itself no longer counts
as network health, so a firmware that cannot restore required communications
rolls back instead of becoming the accepted slot.

## 9. 2026-08-23 physical Target recovery attempt

The connected Target was positively identified as ESP32-C6 revision 0.2 with
16 MB flash. The generic 8 MB board default had produced an invalid bootloader
header for the existing 16 MB partition table; the explicit N16 profile fixed
that mismatch. A production build then booted without the earlier loop-task
stack-protection panic after raising the stack to 16 KiB.

Initial STA association still timed out with disconnect reason 201
(`NO_AP_FOUND`); authentication was not reached. Two software
races were removed: repeated `WiFi.begin()` rewrote STA configuration while a
connection was active, and periodic `WiFi.reconnect()` raced the Arduino core's
own auto-reconnect. AP+STA fallback now initiates recovery once and lets the core
retry reconnectable reasons while the 15-second watchdog records state only.
Disconnect reason codes are logged without credential values so an unavailable
AP can be distinguished from authentication and handshake failures.
The broker principal is also accepted as an opaque non-empty credential instead
of being required to equal the MAC-derived Target ID; exact per-Target topics,
TLS and signed-command verification remain required.

The stable observation window had no panic, reboot or Wi-Fi state-race output.
It did not contain a DHCP success or MQTTS online event, so the wall
installation Gate remains open. The next evidence must be collected with the
configured 2.4 GHz AP available: association/IP, MQTTS online/subscriptions,
periodic HTTPS OTA check, and the three power-cycle/recovery trials in section 5.

## 10. 2026-08-24 exact-main connectivity closure

The exact-main encrypted build `2.1.233+main.g9e9114b` was written only to the
selected `app0` partition with NVS, OTA data and the valid `app1` fallback left
untouched. On its first observed boot it restored the saved SSID, received
`192.168.35.19`, completed MQTTS authentication, subscribed to the exact
per-Target command and ACL topics and published current diagnostics/config.
An authenticated request from an Android device on the same Wi-Fi loaded the
controller UI and returned 13 visible networks from `/scan`, including the
active SSID. Home Assistant converged to the same version, IP, IDLE/closed state
and current diagnostic/config values.

This closes the previously missing association, DHCP and one-session MQTTS
observations. It does not close the three-cycle, broker/WAN outage, RSSI/antenna,
relay, sensor or OTA install/health/rollback gates. The observed RSSI was about
`-84 dBm`, below the preferred `-67 dBm` installation target, so AP placement or
antenna conditions require attention before final wall installation.

## 11. 2026-08-24 rotated-key bootstrap and late-Wi-Fi recovery

Exact main `3927a978a8727eac086e88d20bfaa2d414908dbc` was published by
Target run `32657300554`, attempt 2, as `2.1.234+main.g3927a97` and installed
app-only to `app0`. This was the intentional NVS-preserving bootstrap for the
rotated content-key material. The policy-pinned key ID remained
`personal-target-content-20260824-1`; exact commit and manifest binding, not the
unchanged label alone, distinguish the material epoch.

The first saved-credential STA attempt timed out and entered the authenticated
recovery AP. AP+STA retry then acquired `192.168.35.19` without credential entry
or physical intervention, and MQTTS authenticated about five seconds later,
subscribed to both exact Target topics and published current diagnostics/config.
Home Assistant live sensors converged to H4, while the device-card metadata
header and seven historical controls remained stale registry/discovery state.
The observed RSSI remained about `-84 dBm`, below the installation target.

This closes one physical AP+STA late-Wi-Fi and late-MQTT recovery path. It does
not close repeated power/AP/broker/WAN outage soak, relay/sensor safety,
inactive-slot OTA, health-valid or rollback. The strictly newer main produced by
this evidence-only change is the first image eligible for H4's encrypted
periodic HTTPS install to inactive `app1`.

## 12. 2026-08-24 H5 OTA rejection and H6 recovery candidate

Exact H5 `2.1.235+main.g6517caa` was present on the public NAS and its signed,
encrypted bytes passed independent local signature, authenticated decryption,
digest and ESP32-C6 N16 image validation. The running H4 nevertheless did not
reboot during its periodic check. An authenticated same-LAN recovery attempt
made the failure observable: posting the exact H5 manifest returned HTTP 400
before artifact transfer or inactive `app1` write. H4 stayed online and
continued Wi-Fi/MQTTS/status service.

The network paths were therefore reachable; the failure boundary was H4's
manifest verifier. Its PSA PureEdDSA selection was not provided by the actual
ESP32-C6 Mbed TLS runtime configuration. The H6 candidate uses the bundled
libsodium Ed25519 verifier and keeps initialization/signature errors fail-closed.
This correction currently has source, host-test and build evidence only. Because
H4 cannot authenticate any signed successor with its unavailable provider, the
recovery sequence requires an app-only, NVS-preserving USB bootstrap of exact
merged-main H6 followed by a strictly newer H7 delivered through HTTPS to the
inactive slot. Wall installation still requires that H7 run to show manifest
acceptance, inactive-slot install, reboot, expected version and boot ID,
health-valid marking, plus the repeated outage and rollback trials in section 5.

## 13. 2026-08-24 H6 connectivity and H7 GCM stream boundary

Exact H6 `2.1.237+main.g02090c3` was installed app-only over USB without erasing
NVS. A subsequent reboot restored the saved SSID, acquired `192.168.35.19` in
about three seconds, established verified MQTTS, subscribed to both exact
per-Target topics and published diagnostics/config. This proves the bundled
libsodium manifest verifier image retained the required Wi-Fi and MQTT paths.

H6 then accepted exact H7 `2.1.238+main.ge00ebe8` and began the encrypted HTTPS
download on three fresh boots. Each attempt reached the shared image write/hash
boundary and failed closed. Two physical `app1` readbacks first differed from
the authenticated H7 plaintext at the identical offset 3805, the first
non-block-aligned ESP32-C6 GCM ALT continuation. Active H6 and saved Wi-Fi
credentials remained intact and MQTTS reconnected after each abort; the
inactive slot is intentionally not bootable after those failed writes.

The correction carries partial ciphertext between transport callbacks and
feeds complete 16-byte blocks to every non-final GCM update. Current H6 cannot
consume that corrective envelope through either periodic HTTPS or local upload
because both use the affected pre-fix engine. One NVS-preserving app-only USB
bootstrap is therefore required, followed by a strictly newer periodic HTTPS
release and continuous Wi-Fi+MQTTS health-valid observation. Until that
sequence completes, the Target must not be returned to the wall even though
Wi-Fi and MQTT recovery themselves passed.

## 14. 2026-08-24 H9-H11 OTA closure and weak-home-AP boundary

The exact H9 production image was installed app-only over USB while preserving
the 16 MB N16 bootloader, partition table, NVS, OTA data and fallback slot. On a
nearby 2.4 GHz AP, H9 obtained an address, established verified per-Target
MQTTS, accepted exact H10's signed manifest, downloaded the complete encrypted
artifact, verified the inactive image and rebooted into H10. Exact H11
`7a55a667b9d30f7929176997010d7ab71abaf833`, version
`2.1.242+main.g7a55a66`, is now the observed running image. It obtained
`10.71.25.196`, subscribed to the exact command/ACL topics, published current
diagnostics/config and reported the H11 OTA pointer as already current.

The same Target could not associate reliably with the intended home AP. Its
scan saw the relevant 2.4 GHz signals at approximately `-80` to `-82 dBm`, and
the serial history was dominated by `AUTH_EXPIRE`, inactivity and intermittent
`NO_AP_FOUND`. A connected Android device separately authenticated to the same
SSID with the saved credential, while the Target connected immediately to the
nearby AP at approximately `-42 dBm`. This isolates the operational boundary to
RF margin/installation conditions rather than a missing credential, MQTTS
principal or OTA implementation.

The STA compatibility profile now performs an all-channel scan and selects the
strongest matching BSSID dynamically, disables modem sleep for the wall-powered
control path, and limits only the STA interface to 802.11b/g/n. It does not pin
a BSSID or channel, add another `WiFi.begin()`, change the authenticated
recovery AP, or weaken MQTT/HTTPS OTA. A configuration failure logs a degraded
profile and continues to the existing AP+STA recovery path.

This profile is a compatibility improvement, not a substitute for link budget.
The Target must not be re-embedded until the intended location measures at least
`-75 dBm` (preferably `-67 dBm` or better) and repeated cold boots, AP outage,
MQTT reconnect and signed OTA health/rollback trials pass. The observed H10/H11
reboots did not emit the expected `PENDING_VERIFY` health-window/valid-mark
sequence, so rollback remains an open Gate even though install and current-image
execution succeeded.

## 15. 2026-08-24 quiet recovery-AP arbitration candidate

The ESP32-C6 has one 2.4 GHz radio, and an associated STA determines the AP+STA
channel. The recovery adapter now applies the following explicit state policy:

1. A boot STA failure opens `SmartGatekeeper-Recovery` with STA auto-reconnect
   disabled and starts a 30-second AP-discovery quiet interval. There is no STA
   reconnect call during that interval.
2. After the interval, one `WiFi.reconnect()` may start only when there is no
   associated AP client, no authenticated activity in the preceding 30
   seconds, and no active scan, credential-save, or signed local OTA lease.
3. The STA attempt lasts at most 10 seconds. Failure or interruption explicitly
   disconnects the STA side, keeps credentials/NVS, and begins another full
   quiet interval. A queued authenticated HTTP request is handled before the
   policy update and immediately interrupts an attempt.
4. A merely associated, idle AP client has a bounded 10-minute hold. On expiry,
   provided no authenticated/local operation is active, the Target
   deauthenticates AP clients and starts another 30-second quiet interval.
   Reassociating stale clients are released at a one-second bounded rate. After
   the quiet interval, deauthentication and one bounded STA attempt are paired
   even if the idle phone continues to reassociate; raw idle association alone
   does not interrupt that attempt. Authenticated activity or local work still
   interrupts it immediately. If driver deauthentication fails, the Target
   returns to quiet AP instead of starting an attempt against an associated
   operator.
5. `/scan` leaves STA auto-reconnect disabled after its bounded scan so the JSON
   response and list rendering are not raced by immediate channel hopping.
   Root and scan responses use `Cache-Control: no-store`; the manual SSID field
   remains available. `/save` and local manifest/upload operations hold the
   radio, and each upload chunk renews the bounded lease.
6. Station success closes an indefinite boot provisioning AP and restores pure
   STA plus continuous auto-reconnect. A healthy operator-opened AP+STA window
   has a 10-minute base deadline, then also restores normal STA auto-reconnect.
   If signed local OTA is active at that boundary, each active operation lease
   may defer closure by only 30 seconds; upload chunks renew it, but an idle or
   unauthenticated association cannot. A stalled lease expires and permits AP
   closure. The wrap-safe deadline reserves zero only for an indefinite AP.

This policy does not change MQTTS identity/TLS, periodic HTTPS OTA, signed local
manifest verification, inactive-slot writes, health/rollback, NVS format, or
the authenticated 10-minute operator endpoint. Time/transition host tests and
an ESP32-C6 compile/capacity check pass. Physical evidence is still required
for 30-second continuous AP visibility, Android scan-list rendering, save and
reboot, late STA+MQTTS recovery, local signed OTA, and repeated outage cycles at
the intended installation RF level.

## 16. 2026-08-26 exact-main 281 OTA and connectivity acceptance

The connected pre-fix 493 image accepted the signed 281 manifest and then
reproduced Mbed TLS `-9984` on the second artifact handshake. One bounded COM5
bootstrap installed exact source `082e431` at the documented NVS-preserving
offsets; it did not erase flash or use the padded factory image, and esptool
verified every written region. Saved station and durable-security state
survived.

On the corrected downloader, the independent periodic HTTPS path accepted
`2.1.281+main.g082e431`, downloaded the exact 1,849,444-byte encrypted artifact
over the reused CA/hostname-verified connection, verified the inactive image and
rebooted. Exact CI identity 281 obtained `192.168.35.19`, restored exact
per-Target MQTTS subscriptions, applied ACL v188 and exposed enabled GATT. A
later check reported the manifest already current. Issues #160/#166 are closed
at their TLS/install/connectivity boundary.

No `PENDING_VERIFY` health-window or valid-mark trace appeared. Issue #172 owns
that distinct bootloader/rollback Gate; install/reboot/current identity is not
rollback evidence. Intended-wall RF margin, repeated AP/broker/WAN outage
recovery, AJ-SR04T, relay contact and enclosure acceptance remain open.

## 17. 2026-09-04 powered-but-silent recovery candidate

The source candidate closes the software gaps found after the installed v2
Target stopped producing heartbeat/status. DNS resolution is asynchronous with
a real five-second generation-bound deadline. TCP (4 seconds), TLS (8 seconds)
and MQTT protocol read (3 seconds) run in one bounded FreeRTOS connect worker
that exclusively owns the secure client and PubSubClient until terminal
handoff. The loop and worker are covered by the 45-second task watchdog. A
result is adopted only when both its request ID and Wi-Fi link generation are
current; cancelled or late-generation results are closed as stale. An outage
counter is observed even while access owns the loop, so a disconnect and
recovery that both happen during that interval still invalidate the old TLS
socket before MQTT resumes. Failed reconnects continue indefinitely with the
capped 5-to-30-second backoff.

Normal STA recovery is separated into side-effect-free observation and a safe
radio-mutation phase. A 30-second unresolved outage escalates to the existing
authenticated recovery AP without erasing credentials. Internal recovery
disconnects are explicitly marked and only an associated `ASSOC_LEAVE` event
within the bounded marker window is classified as intentional, preserving the
last genuine driver reason for diagnostics.

Fast-v2 ingress now includes a connection, queued/overflowed write, fast-start
latch and non-IDLE protocol state. The main loop drains and rechecks this
snapshot before Web, MQTT and OTA work, and rechecks again after `client.loop()`.
If a signed MQTT arm/manual callback changes the FSM, the stale pre-command
telemetry is discarded and OTA is skipped. A forced OTA command only queues a
check for the later safe network phase. Periodic and local OTA refuse to begin
while the MQTT connect worker owns its TLS phase, preventing concurrent
handshakes on the shared radio/heap.

A raw or otherwise unverified peer may hold the access-critical gate for at
most 10 seconds. Expiry disconnects only that ingress, cleans the unverified
state and resumes network work without rebooting. Brief quiet gaps resume
network service immediately but do not mint a fresh lease; only 30 continuous
quiet seconds reset the unverified epoch, so reconnect churn cannot starve
MQTT/OTA indefinitely. A verified action generation instead receives its own
85-second physical lease. If that verified phase wedges, relay cleanup is
followed by GATT and signed MQTT `INTERNAL_ERROR` terminal evidence plus an
`access_critical_timeout` breadcrumb before a fail-closed controlled restart.
The GATT transport reason is `INTERNAL_FAIL_CLOSED`, not the misleading
`PROOF_EXPIRED` mapping. Availability LWT/online is retained but explicitly
scoped to MQTT transport because PubSubClient cannot observe SUBACK rejection.

Terminal checkpointing preserves causal FIFO order: older volatile records are
first appended behind existing NVS records, then the terminal is committed. If
NVS is full or unavailable, the terminal uses the reserved RAM tail only when
the complete remaining FIFO, including that terminal, is saved in a
checksum-bound generation of an RTC_NOINIT A/B journal. Replacement writes the
inactive slot and commits its magic last, so a torn replacement leaves the
previous valid generation restorable. The selected generation is kept after
restore until every represented front record has actually published or
migrated to NVS; a later partial drain writes the exact remaining FIFO as the
next generation. Repeated software resets can replay duplicates but cannot
silently discard the terminal. Cold power loss still exceeds this RTC
fallback's durability claim.

The `evidence_persistence_failed` breadcrumb is separately latched across
repeated software resets. A successful retained boot-diagnostics publish may
acknowledge and clear only the failure carried from the previous boot. A new
failure raised in the current boot remains set for the next reset, so publishing
an older warning cannot erase newer degradation evidence.

Signed reboot is also staged rather than executed in the MQTT callback. After
the inbound PUBACK boundary, main blocks new GATT authentication, drains pending
callbacks, aborts only unverified ingress and rechecks that no verified physical
action won the race. It persists the complete pending evidence set before the
restart; a verified action keeps the reboot pending until its terminal state.

A raw link, malformed write or overflow before fast-start has no canonical
session identity, so it may receive a transport failure but cannot enqueue a
zero-session terminal ahead of valid evidence. A trailing duplicate after a
verified action is already committed likewise produces only a replay transport
result; it cannot execute the action again, synthesize a failed terminal or
clear the verified physical actor.

These are source, host-test and ESP32-C6 build results only. The owner deferred
physical Target inspection, so current power state, installed version, boot
reason, Wi-Fi association, broker session, recovery-AP behavior, OTA
install/reboot/health and repeated access latency remain unverified runtime
Gates.
