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
- Wi-Fi disconnect/lost-IP/got-IP를 수명주기 사건으로 처리한다. lost-IP 때 기존 TLS socket을 닫고 got-IP 뒤 새 MQTTS session을 만든다.
- Wi-Fi 상태 확인과 재접속은 비차단 방식으로 수행한다. 현재 구현 기준 확인 주기는 15초다.
- MQTTS가 끊긴 동안에도 재접속을 계속한다. 현재 구현 기준 재시도 gate는 약 5초, keepalive는 30초다.
- TLS/CONNACK 시도는 제한된 timeout과 backoff를 사용하며 relay/FSM loop를 장시간 막지 않는다.
- 고유 Target client ID, hostname 검증 TLS, per-Target credential, signed command namespace를 유지한다.
- availability LWT와 online, boot, status heartbeat를 발행한다. status는 현재 구현 기준 1초 주기다.
- MQTT와 무관하게 signed manifest 기반 HTTPS OTA를 부팅 후와 주기적으로 확인하고, 실패 시 bounded retry를 계속한다.
- OTA는 inactive slot, health window, valid mark, 자동 rollback 계약을 유지한다.

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

The current firmware no longer stops STA attempts after the initial ten-second
boot window. A failed boot association opens the authenticated recovery AP in
`WIFI_AP_STA` mode while retrying the stored/compiled STA credentials every 15
seconds. Successful association closes the indefinite provisioning AP and
returns to pure STA mode. Failed attempts do not erase the NVS credentials.
The AP identity is single-sourced by `kRecoveryApSsid` as
`SmartGatekeeper-Recovery`; the same constant is used for the broadcast SSID,
serial ready log and HTTP Basic authentication realm.
An authenticated `/scan` request temporarily pauses a disconnected STA's
credential retry, performs one bounded synchronous scan with one bounded retry,
then restores STA auto-reconnect without stopping the SoftAP or clearing NVS.
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
