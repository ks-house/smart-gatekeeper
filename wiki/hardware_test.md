# hardware_test.md — 테스트 증거와 현재 검증 상태
> Last updated: 2026-09-04 (GATT v2 fast-path source/build evidence recorded; installation and physical latency pending)

## 1. 판정 원칙

과거 VL53L0X/ESP32 BLE scanner 아키텍처의 PASS는 변경 이력으로 보존하지만, 현재 **iBeacon → Android → FastAPI → MQTT → AJ-SR04T → Relay** 경로의 합격 근거로 간주하지 않습니다. 소프트웨어 빌드 통과와 실기기 E2E 통과도 분리합니다.

## 2026-09-04 GATT v2 fast-path 후보

| 항목 | 관찰 결과 | 판정 |
|---|---|---|
| Target protocol/adapter host coverage | v2 single Fast-TX subscription, fresh `SGKCHAL2`, `FAST_PROOF`, `SGKPRF02` verifier input, FSM action commit, `FAST_RESULT`를 포함한 focused contract 16 tests 통과 | PASS (host source) |
| Personal-production firmware compile | ESP32-C6 pioarduino `esp32c6_personal_production` compile/link/factory image 성공; RAM 75,912/327,680 bytes, application flash 1,768,106/7,340,032 bytes | PASS (example-provisioned build only) |
| Android JVM suite | 기존 Flutter builder, repository 지정 Gradle 9.1과 persistent package cache로 `:app:testDebugUnitTest` 실행; app/main 및 unit-test Kotlin compile, 19 suites/75 tests, 0 failures/errors/skips | PASS (container/JVM) |
| Installed Target/mobile latency | OTA/APK 설치, reboot health, `protocolMode=FAST_V2`, 동일 휴대폰의 presence→ARMED 반복 측정 미수행 | PENDING (physical/runtime) |

예제 `secrets.h` 연결은 compile 동안만 사용하고 제거했다. 이 표는 실제 Target identity, ACL, Wi-Fi,
MQTT, OTA artifact 또는 설치 결과를 증명하지 않는다.

전체 Android dependency 모듈의 unscoped `testDebugUnitTest`는 SDK 36이 Java 21을 요구하는
`url_launcher_android` Robolectric 외부 플러그인 시험 한 건에서 실패했다. 저장소 앱 범위
`:app:testDebugUnitTest`는 위와 같이 통과했으며, release 재현성의 최종 판정은 고정된 hosted lane에
맡긴다.

## 2026-08-30 wall Target manual-open transport split

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Direct MQTT open | Owner observed the installed door open through the MQTT command path after restoring AJ-SR04T GPIO10/11 and relay GPIO23 firmware | PASS for the installed Target MQTTS/relay/door path in that observation; this does not authenticate the mobile app |
| Mobile Local GATT button | Advanced diagnostics showed stale Target detection at RSSI -97 dBm, native worker `UNHEALTHY`, `GATT_DISCONNECTED`, 10,014 ms latency and all connect/hello/challenge/sign/proof/result phases at zero | FAIL before credential proof or relay command; no door effect |
| Backend-button production deployment | The normal Home, advanced-control and hosted-shell button paths create a fresh AndroidKeyStore credential proof and call Backend `/api/v1/door/open`; Backend verifies active tenant/credential/exact door grant, durable nonce and P-256 signature before per-Target signed MQTTS publication. Run `33309298877` deployed source `07b3543a...36d7eb`, migration `up 008` with backup, and passed internal/public readiness | PASS for protected CI-to-NAS deployment and exact runtime readiness. Connected trials now prove request arrival but HTTP 401/403 denial before publication; Target execution and physical door result do not follow from this path |
| Final mobile/Target OTA publication and mobile install | Final main `f403e10c...113d3bc` mobile run `33309381350` and Target run `33309381357` both completed signed atomic personal OTA publication and HTTPS byte readback. Connected Windows ADB then verified the installed app as exact `1.0.0-gf403e10` / 33401 with the original 2026-07-29 first-install time preserved | PASS for publication and replacement-installed mobile identity. Target publication still does not prove Target install/reboot/health or physical behavior |
| Connected mobile remote-button diagnosis | The refreshed Home remained `스마트키 사용 가능`, user `이승환 401호`, one registered door and ACL 594. The bounded Activity timeline independently showed three remote attempts at 21:00:58, 21:02:00 and 21:09:19, all `REMOTE_CONTROL_DENIED`; no additional door request was triggered during diagnosis | FAIL at Backend credential authorization (HTTP 401/403 mapping), before MQTT publication. Current evidence narrows the remaining causes to command-vs-personal tenant/door scope, exact active grant, or P-256 proof verification; network/MQTT/Target/relay are not the leading boundary |
| Read-only NAS authorization-scope split | Owner-executed aggregate query returned `tenant_scope_match=NO`, `door_scope_match=NO`, zero command-scope active credentials/grants, and all personal-to-command set comparisons `NO` | ROOT CAUSE CONFIRMED: deployed v3 incorrectly queried the independent `COMMAND_*` scope for a credential enrolled under `ACL_PERSONAL_*`; this deterministically produces 403 before signature/MQTT. No runtime ID, credential, grant or database mutation was made |
| Personal-scope correction deployment | Backend v3 now checks credential tenant and exact door grant against `ACL_PERSONAL_TENANT_ID`/`ACL_PERSONAL_DOOR_ID`, while retaining `COMMAND_*` only for the subsequent signed MQTTS publisher. Startup additionally rejects a personal scope bound to any Target other than `COMMAND_TARGET_ID`. PR #290 merge `6c12f169...01081` passed protected run `33311924158`; the Tailscale NAS deploy reported `status=deployed`, loopback/public readiness passed, and independent strict-TLS `/live` and `/ready` returned HTTP 200 for that exact build with every readiness check true | PASS for source, protected CI, immutable-image NAS deployment and runtime readiness. No post-fix mobile request has been sent; one owner-triggered button trial plus Target/relay/physical-door observation remains the final Gate |
| Post-fix mobile physical trial | Owner pressed the installed `1.0.0-gf403e10` normal `문 열기` button after exact Backend `6c12f169...01081` deployment and observed the physical door open | PASS for one mobile credential → Backend → signed MQTTS → installed Target → relay → physical-door observation. Repetition, another-user enrollment and OEM/SLO Gates remain separate |
| Fresh family-member onboarding | Connected fresh-install A24 (Android 16) had Bluetooth/location/notification permissions granted, exact app `1.0.0-gf403e10` / 33401, zero doors and a generated provisional AndroidKeyStore key, but Home initially rendered Backend unavailable without the registration action. PR #295 corrected status and deployed exact main `bf435bf4...a9bf5` in run `33312971831`; the unchanged A24 then rendered the registration form, but the owner's first submission displayed `신청 접수에 실패했습니다`. Root cause was the request/API/storage mismatch: fresh IDs are `GK-*` UUIDs, the request allowed only `DEV-*`, and the legacy column is 17 characters. Policy PR #296 and feature PR #297 passed protected checks; PR #297 merged as exact main `f03acdf...6d084`, and Backend run `33314043691` deployed the consistent bounded locator across request, status and credential bootstrap. Canonical and independent strict-TLS readiness passed for that exact build. The owner's later submission and administrator approval produced the expected connected ADB `이 휴대폰 등록` state. One owner enrollment tap then failed and stayed `readyToEnroll`; the support report showed native healthy, no blocking reason and zero ACL/doors. A production-shaped local reproduction returned exact HTTP 409 `personal tenant is already mapped to another legacy device` because the first owner's legacy row already owns the shared personal tenant mapping. Policy PR #299 and feature PR #300 passed protected checks; #300 merged as exact main `38b90e5f...35d3`. Backend run `33315099974` deployed it with `status=deployed`, canonical loopback/public readiness, and independent strict-TLS exact-build `/live` and `/ready` HTTP 200 with every check true. The owner's one post-deploy retry changed Home to `스마트키 사용 가능`, one registered door and ACL 608; Activity records phone registration at 22:53:15. Because access-ready requires the exact latest signed snapshot ACK, this also proves Target ACL synchronization. Activity later records Backend MQTT-broker delivery for one remote open at 22:53:40 | PASS for request, approval, credential enrollment, exact door grant, signed ACL Target ACK and access-ready UI on the second family phone. Broker delivery is not physical-door proof; the second phone's relay/door observation and repeated/OEM background behavior remain pending |
| Concurrent HA remote-open control | Owner reports HA MQTT remote open successfully opened the door while the updated mobile button still failed | PASS for the current HA/Backend signed-MQTT/Target/relay/door route; this isolates the mobile failure ahead of, or specifically at, the mobile credential authorization/request path and does not prove the Android request was published |

This evidence supports the transport decision: the visible manual button should
use the already working Backend-to-MQTTS control plane, while pocket approach
remains Local GATT action 1. Broker acknowledgement is not itself physical-door
confirmation, and the client never automatically retries an unknown outcome.

## 2026-08-23 N16 USB 설치 및 최초 부팅 확인

| 항목 | 관찰 결과 | 판정 |
|---|---|---|
| 칩/플래시 식별 | ESP32-C6 rev 0.2, JEDEC flash 16 MB | PASS |
| bootloader/partition | bootloader header 16 MB, dual OTA `0x700000` x2, 모든 write hash verified | PASS |
| application 크기 | 1,696,896 bytes / 7,340,032-byte slot = 23.12%, headroom 5,643,136 bytes | PASS |
| NVS 보존 설치 | `erase_flash` 없이 0x0/0x8000/0xe000/0x10000 이미지 기록 | PASS |
| 부팅 안정성 | 16 KiB loop stack 적용 후 stack panic/boot loop 없음; 마지막 45초 오류 출력 없음 | PASS (관찰창) |
| Wi-Fi 최초 연결 | disconnect reason 201 (`NO_AP_FOUND`) 반복 후 AP+STA fallback; DHCP/IP 성공 미관찰 | FAIL/PENDING (AP/RF) |
| MQTTS | production transport/verifier/command provisioning 거부 로그는 제거됐으나 Wi-Fi 부재로 broker online 미관찰 | PENDING |
| OTA | 런타임 크기/SHA/image/slot 검사와 CI 80% size gate 확인; 실제 download→install→reboot→health 미수행 | PENDING |

이 표는 연결된 개발대의 USB 관찰이다. Wi-Fi/MQTTS/OTA의 PASS나 최종 벽 매립 승인을 의미하지 않는다.

## 2026-08-23 Home Assistant secure discovery migration 검증

| 항목 | 관찰 결과 | 판정 |
|---|---|---|
| 기존 entity identity | historical discovery의 device identifier와 read-only unique ID 15개를 고정하고, runtime Target ID는 인자로만 주입 | PASS (software) |
| secure state namespace | read-only 15개 모두 per-Target 10초 `/status`와 30초 만료를 사용; boot-only non-retained `/availability`와 `/config-state`는 discovery에서 참조하지 않음 | PASS (software) |
| legacy write control 제거 | button 3개와 number 4개는 read-only 갱신보다 먼저 빈 retained payload로 삭제하며 새 config에 `command_topic`/`payload_press` 없음 | PASS (software) |
| publish semantics | fake broker client 경계에서 총 22건 모두 QoS 1, retain=true와 ACK 대기 경로 확인 | PASS (host test) |
| credential 경계 | 기본 dry-run은 network-free; username/password 직접 CLI 옵션 없음, env/file 값 출력 없음, credentialed apply는 TLS 필수 | PASS (host test) |
| live broker/HA registry | 실제 broker retained read-back 및 Home Assistant entity registry 확인은 수행하지 않음 | PENDING |

이 검증은 discovery payload 생성과 publish 경계의 host 증거다. live broker의 retained 수락,
Home Assistant registry의 in-place migration 및 stale control 제거를 증명하지 않으며, Target Wi-Fi/MQTTS,
문 열기, signed command bridge 또는 OTA 동작 증거로 승격하지 않는다.

### 같은 날 live Home Assistant 관찰

| 항목 | 관찰 결과 | 판정 |
|---|---|---|
| secure discovery live publish | 운영 internal broker에 15개 read-only retained config를 적용하고 기존 device identity에서 UI 갱신 확인 | PASS (live) |
| 주기 status | Target `c0feffe6ebac`의 `/status`로 firmware `2.1.0-gd06519e`, IDLE, IP `192.168.35.19`, distance 9990 mm, RSSI를 HA에서 확인 | PASS (live) |
| config-state | 현 Target가 boot 시 발행한 값을 관찰한 뒤 동일 값을 1회 non-retained로 seed하여 4개 설정 sensor 표시 확인 | PASS (live, seeded) |
| legacy controls | retained tombstone 7개를 live broker에 적용하고 retained read-back에서 button/number 0개 확인; current signed command bridge는 별도 미구현 | PASS removal / PENDING bridge |
| public MQTTS TLS | Mosquitto restart 뒤 `tworimpa.synology.me:4883`이 RSA SHA-256 `f2c90a2b4a8b3181bb0ae6863618a0101139593ff55105518726a10c78a94e23`, SAN hostname, public chain, TLS 1.3과 2026-10-19 만료를 검증 client에 제공 | PASS (live renewal; expiry monitoring still required) |

이 live 관찰은 read-only 상태 가시성 복구 증거다. 문 열기, reboot, OTA, 설정 변경은 backend signed
command bridge 없이 동작한다고 간주하지 않으며, live migration에서는 legacy control tombstone을 아직
적용했으며 retained read-back에서 legacy control config가 남지 않은 것을 확인했다. 새 write control은
만들지 않았고 실제 문 열기나 설정 변경도 수행하지 않았다.

## 2. 현재 코드 기준 검증표

| 영역 | 마지막 증거 | 판정 | 비고 |
|---|---|---|---|
| Flutter format/analyze/unit test | 2026-07-30 Docker, 5 tests | 🟢 PASS | Flutter 3.44.8 / Dart 3.12.2 |
| Android release APK build | 2026-07-30 Docker | 🟢 PASS | 당시 APK SHA-256은 `wiki/log.md` 기록 참조 |
| Backend syntax/Compose config | 2026-07-30 | 🟢 PASS | 실 broker/DB E2E와는 별개 |
| ESP32 v2.1 diagnostics build | Actions `30566577543` | 🟢 PASS | `2.1.0-g93cee8d`, NAS SFTP와 metadata 검증 성공 |
| iBeacon raw UUID/interval | 실측 없음 | 🔴 REQUIRED | nRF Connect/btmon으로 manufacturer payload 확인 |
| 화면 OFF·앱 swipe-away 접근 | 실기기 없음 | 🔴 REQUIRED | force-stop은 지원 불가 |
| Backend MQTT QoS1 PUBACK fail-closed | 코드/단위 정적 확인 | 🟡 DEVICE/BROKER TEST | 성공 200, 실패 503 확인 |
| Target MQTTS heartbeat/reset | 2026-07-31 remote, `g8eb7cac` | 🔴 RESET REPRODUCED | 세 번째 reset 직접 포착: uptime 919→7, gap 8.288초; 직전 heap 200,648 B/RSSI -58 |
| MQTT reset command correlation | 12분 read-only subscribe | 🟡 MQTT PATH EXCLUDED | 세 번째 reset 전 cmd/arm/force/config 입력 0; retained는 config state뿐 |
| AJ-SR04T 거리·ghost filter | 과거 현장 로그 존재 | 🟡 RE-TEST | 현재 전체 경로에서 20–50 cm 재검증 |
| 릴레이 High-Z OFF/노이즈 내성 | freeze 이력 있음 | 🔴 REQUIRED | 전원 재인가 없이 반복 동작 확인 |
| Wi-Fi/BLE coexistence | watchdog 수정됨 | 🔴 REQUIRED | 장기 soak test 필요 |
| v2.1 OTA 설치/재부팅 | 2026-07-31 remote MQTT/status | 🟢 PASS | `g8eb7cac` → `g93cee8d`, target/boot/reset telemetry 확인 |
| retained flash coredump | v2.1 boot payload | 🔴 PANIC CONFIRMED | loopTask `udp_new_ip_type` core-lock assertion, 11,044 B valid coredump |
| Target OTA rollback/16 MB partition | 과거 OTA 성공 기록 | 🔴 P0 BLOCKER | #23: 양 slot, health mark, 실패 자동 rollback, power-loss 검증 필요 |
| 모바일 APK update 비회귀 | 과거 NAS APK 다운로드 기록 | 🔴 P0 BLOCKER | #23: scanner 독립 update, hash/signing identity, fallback, N/N-1 검증 필요 |
| OTA artifact/schema/semantic negative vectors | 2026-08-01 host unit test 18건 | 🟢 CONTRACT PASS | 실제 artifact size/SHA-256·APK certificate binding과 invariant/recovery fail-closed 검증; 물리 install/boot/rollback 증거 아님 |
| OTA-G1~G4 physical matrix | 실측 없음 | 🔴 RELEASE BLOCKED | periodic HTTPS/local AP, Android fallback, N/N-1, power-loss/rollback 실기기 필요 |
| Epic #13 implementation authorization | 2026-08-02 사용자 승인 + machine-readable contract | 🟢 G0-SW ONLY | #17~#22 software 구현/리뷰/merge 허용; production·물리 완료 증거 아님 |
| #18 core/adapter host tests and builds | 2026-08-02, 87 repository tests + default-OFF/feature-ON ESP32-C6 builds | 🟢 SOFTWARE PASS | connection generation, second peer, reconnect race, overflow ordering, indication ACK/error/timeout, provisioned/cross-door binding, WAIT_SAFE_STATE contract; no radio/GPIO/relay/OTA physical evidence |
| Epic #13 production authorization | 실측 없음 | 🔴 G0-HW BLOCKED | Samsung/OEM, ESP32-C6 real BLE, relay/sensor, bootloader, OTA-G1~G4, RELAY-G0~G2 필요 |

## 3. 현재 E2E 인수 절차

1. 보드 부팅 후 Wi-Fi, MQTT TLS, iBeacon 광고를 동시에 확인합니다.
2. 광고 payload의 `4C 00 02 15` 뒤 UUID 16바이트와 100 ms interval을 캡처합니다.
3. 승인/미승인 Android 기기로 화면 ON, 화면 OFF, task swipe-away를 각각 시험합니다.
4. 승인 요청 성공 시 서버가 QoS 1 PUBACK을 받은 경우에만 HTTP 200과 `mqtt_published=true`를 반환하는지 확인합니다.
5. ARMED 동안 20 cm 미만은 무시되고 20–50 cm 접근은 릴레이를 정확히 1초 구동하는지 확인합니다.
6. 기본 3초 cooldown, 60초 arm expiry, 중복 요청 억제를 검증합니다.
7. MQTT 단절, NAS 단절, 잘못된 API key에서 문이 열리지 않고 앱이 진단 가능한 오류를 표시하는지 확인합니다.
8. 최소 100회 릴레이 반복과 24시간 Wi-Fi/BLE soak 동안 freeze/reset/광고 중단 여부를 기록합니다.

## 4. 과거 검증 이력

| 날짜 | 당시 아키텍처 | 결과 | 현재 적용 범위 |
|---|---|---|---|
| 2026-07-24 | VL53L0X + relay Local PoC | PASS | 릴레이/보드 초기 PoC 이력만 인정 |
| 2026-07-24 | ESP32 → NAS HTTPS → relay | PASS | 현재 역할 반전 흐름과 다름 |
| 2026-07-24 | MQTTS/HA/OTA 통합 | PASS | 인프라 선행 증거, current regression 필요 |
| 2026-07-28 이후 | AJ-SR04T 필터·모바일 beacon 수정 | 코드 변경 다수 | 최신 통합 실기기 재검증 필요 |
| 2026-07-31 | 공인 MQTTS → Target status 관측 | PARTIAL | certificate/hostname·CONNACK·SUBACK 확인; 분리된 20초+30초 안정성만 증명하며 reset 원인은 미확인 |
| 2026-07-31 | 12분 status/control 연속 감시 | FAIL/DIAG | status 678건 뒤 uptime 919→7 reset; 정상 RSSI/heap, MQTT command 없음 |
| 2026-07-31 | retained config/command wildcard 감사 | PASS | `gatekeeper/config/state`만 retained, destructive/config command 없음 |
| 2026-07-31 | v2.1 CI → NAS → MQTT OTA | PASS | run `30566577543`, status의 firmware/reset/boot identity로 설치 확인 |
| 2026-07-31 | OTA 후 retained coredump 회수 | FAIL/ROOT CAUSE | 이전 firmware의 loopTask lwIP UDP core-lock assertion 확인 |

새 하드웨어 결과는 날짜, firmware commit, 앱 build, 환경, 반복 횟수, 원시 로그/캡처 위치와 함께 이 표에 추가합니다.
## 2026-08-09 Target command/OTA security evidence

| Date | Test | Result | Evidence boundary |
|---|---|---|---|
| 2026-08-09 | Signed command mutation, replay, crash, and storage-fault host tests | PASS (software) | Target/tenant/door/boot/freshness/signature mutations rejected; completed and uncertain duplicates do not repeat effects |
| 2026-08-09 | OTA contract/state/fault and insecure-path host tests | PASS (software) | Verifier/state/static seams exercised without a physical ESP32-C6 or deployed NAS broker |
| 2026-08-09 | #50 independent-review remediation mutations | PASS (software) | Delayed first command stays clock-untrusted; STA-preserving bounded recovery AP seam covers DNS/Backend outage; transient health resets; late recovery rolls back; prerelease/equal-precedence/reboot storage replays reject |
| 2026-08-09 | `pio run -e esp32c6 -j 4` | PASS (software build) | RAM 53,728/327,680; flash 1,600,194/7,340,032; no upload or device execution |
| 2026-08-09 | Authenticated current-boot registry and strict command parser | PASS (software) | Root 102 tests and backend 49 tests (one opt-in MariaDB skip); WSL/Linux production-core seam passed; final ESP32-C6 build used 53,888/327,680 RAM and 1,606,490/7,340,032 flash; no broker or device execution |
| 2026-08-09 | Exact-head duplicate/deadline review mutations | PASS (software) | Every signed-command field rejects same/different duplicate raw JSON members before DOM parsing; health tests cover deadline-1, exact equality, deadline+1, and stalled samples; ESP32-C6 build used 53,888/327,680 RAM and 1,606,546/7,340,032 flash |
| Pending | Physical Target OTA and hardening | OPEN | ESP32-C6 inactive-slot boot, health-valid, power-loss, rollback, periodic HTTPS, local recovery, eFuses/debug locks, radio/relay, N/N-1, operator soak, and production authorization remain unproven |

## 2026-08-23 Recovery portal scan and production connectivity evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Candidate identity | `main` `21107958` plus the unmerged recovery-scan fix, version `2.1.0-g2110795-scanfix`; app-only write at `0x10000`, NVS preserved, flash write hash verified | PASS for field candidate; exact merged-main reinstall still required |
| Recovery scan driver | The previous field image returned `-2` while stale STA authentication retried. The candidate returned 11, 13, 12, 13 and 9 visible AP records in repeated authenticated scans | PASS |
| Recovery portal UI | The phone rendered the explicit network list, selected `SK_WiFiGIGAA947`, and Target logged the matching credential-save request without logging the password | PASS |
| Wi-Fi association | After reboot the AP+STA recovery path obtained DHCP address `192.168.35.19` and logged `provisioning AP station recovery succeeded` | PASS for association and DHCP; long soak pending |
| MQTTS | Target connected to the provisioned TLS broker, subscribed to exact per-Target topics, and published retained boot diagnostics/config state | PASS for current boot; WAN/broker failure soak pending |
| Runtime reconnect | One later beacon timeout (`reason 200`) closed the stale TLS socket; Target regained `192.168.35.19`, reconnected MQTTS, resubscribed and republished boot/config diagnostics without a reboot | PASS for one automatic recovery; repeated/long soak pending |
| OTA capacity | Candidate app 1,699,616 bytes in each 7,340,032-byte slot, 23.16% usage and 5,640,416-byte headroom | PASS for capacity only; periodic HTTPS install, reboot health, rollback and power-loss tests remain pending |

This evidence supersedes the earlier same-day `NO_AP_FOUND` first-boot attempt only
for recovery scan, Wi-Fi association, DHCP and MQTTS. It does not promote the
candidate to production release approval or close the physical OTA/relay/soak gates.

## 2026-08-23 Target OTA rollback and download safety host evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Failed-floor quarantine | Native C++ version-policy tests reject the exact persisted failed floor after a lower slot boots, retain equal-precedence identity-conflict rejection, and accept a strictly newer recovery version | PASS (host software) |
| Bounded remote download | Static Target contract confirms 30-second no-progress and five-minute total deadlines, inactive-write abort, explicit timeout reason and 15-minute retry scheduling | PASS (host/static software) |
| WAIT_SAFE_STATE failure | Static Target contract confirms failure status, reason, retry scheduling and immediate return before any network request | PASS (existing behavior, regression guarded) |
| ESP32-C6 build/capacity | Default N16 build succeeded; app image 1,662,160 bytes in a 7,340,032-byte slot, 22.65% usage and 5,677,872-byte headroom | PASS (compile/capacity only) |
| Physical install/rollback | No firmware was uploaded by this change; inactive-slot install, timeout injection, bootloader rollback and failed-version quarantine remain unobserved on ESP32-C6 | PENDING physical evidence |

## 2026-08-23 Public MQTTS certificate recovery evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Export validation | The selected RSA leaf covered `tworimpa.synology.me` and `*.tworimpa.synology.me`, matched its private key, verified against the exported two-certificate chain, and expires 2026-10-19 | PASS (offline material validation) |
| NAS replacement | The audited Mosquitto `certfile`, `cafile`, and `keyfile` were backed up and replaced; replacement readback matched the approved certificate/key/chain before restart | PASS (on-disk recovery) |
| Live TLS after restart | A default-trust client completed hostname and public-chain validation on port 4883, observed TLS 1.3 and the approved replacement certificate fingerprint | PASS (live endpoint) |
| Authenticated MQTT | The provisioned broker principal received CONNACK success and SUBACK for the exact Target status topic over verified TLS | PASS (live transport/authentication) |
| Target reconnection | A fresh periodic status from Target `c0feffe6ebac` reported boot ID `c2f1ce127f0d5a3a296bb781319dc904`, state IDLE and IP `192.168.35.19` after the broker restart | PASS for current reconnect; outage soak remains pending |

This recovery proves the current public TLS endpoint and one authenticated Target
reconnection. It does not prove automatic certificate renewal, expiry alerting,
long broker/WAN outage recovery, Target OTA installation, reboot health, rollback,
relay safety or final wall-install acceptance.

## 2026-08-24 exact-main encrypted Target USB bootstrap

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact release identity | GitHub Actions Target run `32655789147` published exact main `9e9114b7ddc93e54adab1230341a3bc520b1aa68` as `2.1.233+main.g9e9114b`; signed manifest, encrypted artifact, public HTTPS exact-byte readback and local authenticated decryption all passed | PASS for CI/NAS artifact identity |
| N16 capacity | Plaintext application was 1,703,392 bytes in a 7,340,032-byte slot (23.21%); headroom 5,636,640 bytes. ESP32-C6 image checksum and appended hash were valid and the image declared 16 MB, 80 MHz, DIO | PASS |
| Pre-write preservation | Read-only backup captured the 16 MB partition table, 20 KiB NVS, 8 KiB OTA data and both valid application headers. `app0` was selected and `app1` remained a bootable fallback | PASS |
| USB write | Wrote only the exact application to `app0` at `0x10000`; no erase, bootloader, partition-table, NVS, OTA-data, SPIFFS or `app1` write occurred. esptool verified the written-data hash and hard-reset the Target | PASS for NVS-preserving bootstrap |
| First boot Wi-Fi | Serial identified `2.1.233+main.g9e9114b`, restored the saved SSID from NVS, associated and received `192.168.35.19` | PASS for one boot; three-cycle and outage soak remain pending |
| MQTTS | The Target completed verified TLS broker authentication, subscribed to both exact per-Target command/ACL topics and published boot diagnostics plus current config state | PASS for one boot/session; broker/WAN soak remains pending |
| Authenticated recovery UI and scan | A connected Android device on the same Wi-Fi received HTTP 200 for the authenticated controller page. The page included the explicit list renderer and automatic `/scan`; `/scan` returned a JSON array with 13 visible networks including the active SSID, and serial logged the same count | PASS for STA-local portal/scan; AP-only upload recovery remains pending |
| Home Assistant convergence | After refresh, the existing Smart Gatekeeper device showed `2.1.233+main.g9e9114b`, `192.168.35.19`, `IDLE`, closed door and current distance, RSSI, heap, uptime and four config values | PASS for read-only live telemetry |
| Legacy Home Assistant controls | Seven historical button/number registry entries were still visible even though their retained discovery configs had been tombstoned. They were not invoked; the authenticated backend signed-command bridge remains absent | PENDING registry cleanup / signed bridge |
| Inactive-slot OTA and health | This installation was a direct app-only USB bootstrap into the already selected slot, not a periodic HTTPS write to inactive `app1`; bootloader pending-verify, 30-second health-valid mark and rollback were not exercised | PENDING second exact-main physical OTA |

Immediately after this observation the Target content-encryption key was rotated
without recording its value. GitHub `personal-auto-ota`, GitHub `production` and
the ignored local headers share the policy-pinned key ID
`personal-target-content-20260824-1`. The key material changed while this label
remained fixed because the exact workflow contract rejected a different ID; the
label alone therefore does not identify the material epoch. Exact firmware
commit and manifest binding are required when auditing this emergency rotation.

## 2026-08-24 rotated-key H4 Target USB bootstrap and recovery

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact release identity | GitHub Actions Target run `32657300554`, attempt 2, published exact main `3927a978a8727eac086e88d20bfaa2d414908dbc` as `2.1.234+main.g3927a97`; signed manifest, encrypted artifact and public HTTPS exact-byte readback passed | PASS for CI/NAS artifact identity |
| Artifact binding and capacity | The encrypted artifact was 1,703,428 bytes with SHA-256 `45ff37d858d5fb38a4f2aa397e5809e66be7b42be9cc1b10d97fe32acd18da7f`; authenticated local decryption produced a 1,703,392-byte ESP32-C6 N16 image with SHA-256 `8910bc7cfeef47713c5be57fbc4ab72d379b7435f84949ec49181a4e769dfbcb`, using 23.21% of one 7,340,032-byte OTA slot | PASS |
| Rotated-key bootstrap | Wrote only the exact H4 application to selected `app0` at `0x10000`; NVS, OTA data, partition table, bootloader and `app1` were not erased or overwritten | PASS for the one required NVS-preserving USB bootstrap |
| AP+STA automatic recovery | The initial saved-credential STA attempt timed out and opened `SmartGatekeeper-Recovery`. Without credential entry or physical intervention, AP+STA retry obtained `192.168.35.19` about 54 seconds after the first attempt, then closed the recovery condition | PASS for one boot-failure recovery path; repeated power/AP outage soak remains pending |
| MQTTS after late Wi-Fi | About five seconds after DHCP recovery, the Target completed verified MQTTS authentication, subscribed to both exact per-Target topics and published boot diagnostics/config | PASS for late-Wi-Fi MQTT initialization and one recovered session |
| Home Assistant convergence | Live read-only entities reported `2.1.234+main.g3927a97`, `192.168.35.19`, IDLE/closed, RSSI about -84 dBm and current diagnostics/config. The HA device-card metadata header still showed an older static discovery version | PASS for live sensor convergence; discovery metadata and seven stale legacy controls remain cleanup work |
| Inactive-slot OTA and health | H4 was intentionally the USB bootstrap carrying the rotated key material. The strictly newer main release created by this documentation change is the first eligible encrypted periodic HTTPS update to inactive `app1` | PENDING physical H5 install/reboot/health-valid proof |

## 2026-08-24 H5 encrypted OTA manifest rejection

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact H5 publication | Target run `32658670039` published exact main `6517caa957dcf1c42ece49d15e38a428c81262e5` as `2.1.235+main.g6517caa`. NAS immutable artifact/pointer publication and exact HTTPS readback completed | PASS for CI/NAS transport only |
| Offline cryptographic binding | The 1,703,428-byte envelope SHA-256 `5e09d67e1c0798a87e2fc319f7f249d64346702504d1f9d2602bfa27cf2d9a16` passed Ed25519 manifest verification and AES-256-GCM authentication locally. The decrypted 1,703,392-byte image SHA-256 `67d037c0b824b628e52f16e8b41a559f86a46e4a5b3b4298ff2e319a8a9388e8` matched the manifest and passed ESP32-C6 N16 image/checksum/hash inspection | PASS for exact offline bytes; not Target runtime evidence |
| Periodic HTTPS attempt | H4 remained online with Wi-Fi, MQTTS and Home Assistant status continuing, but did not reboot to H5 after the periodic check window | FAIL for H5 install |
| Authenticated local recovery attempt | An authenticated same-LAN recovery request enabled the bounded recovery window, but posting the exact H5 manifest returned HTTP 400 before artifact upload/download | FAIL at Target manifest validation |
| Slot preservation | No firmware payload was uploaded and no write to inactive `app1` occurred. H4 remained the running image, so the active slot, NVS and existing fallback were not displaced | PASS for fail-closed preservation |
| Root cause | H4 called PSA PureEdDSA, but the actual ESP32-C6 Arduino/ESP-IDF Mbed TLS configuration did not provide that Ed25519 algorithm at runtime even though the PSA constant was present in headers. The exact manifest was therefore rejected before artifact processing | ROOT CAUSE CONFIRMED |
| H6 candidate correction | Manifest verification now uses the bundled Espressif libsodium `sodium_init()` and `crypto_sign_verify_detached()` path, retains exact 32-byte public-key/64-byte signature contracts and fails closed on provider or signature failure | PASS for source/build/host tests only; physical H6 pending |

H5 publication, readback and offline cryptographic verification are not OTA
completion evidence. H4 cannot authenticate a corrective signed image with its
unavailable provider, so exact merged-main H6 must first be installed app-only
over USB while preserving NVS, OTA data and the fallback slot. A strictly newer
H7 must then prove signed manifest acceptance, inactive-slot write, planned
reboot, new version and boot ID, continuous health-window completion and valid
mark. Rollback and power-loss injection remain separate pending tests.

## 2026-08-24 H6 bootstrap and H7 encrypted-stream failure evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact H6 USB bootstrap | Exact main `02090c31b6813d6d1691262809dfc86330283a9d`, version `2.1.237+main.g02090c3`, was written app-only to selected `app0`; no full-chip erase or NVS erase was used | PASS for corrective USB bootstrap; not OTA |
| H6 Wi-Fi/MQTTS | After reboot H6 restored the saved SSID, acquired `192.168.35.19`, authenticated MQTTS, subscribed to exact per-Target topics and published diagnostics/config | PASS for one current boot/session; soak remains pending |
| Exact H7 CI/NAS | Run `32662983244` published exact main `e00ebe84dbd7a4c9323b21e393429c9d44f4cdb3` as `2.1.238+main.ge00ebe8`; latest and immutable manifests were byte-identical and Ed25519/AES-256-GCM/ciphertext/plaintext/image verification passed | PASS for CI/NAS bytes |
| H7 capacity | Plaintext was 1,795,248 bytes, SHA-256 `fc939b690f0418a917172393abb35ba769910b8e5b540c93884053df5e9b9b4e`; encrypted artifact was 1,795,284 bytes. Each 7,340,032-byte slot retained 5,544,784 bytes headroom | PASS; 24.46% slot usage |
| Target manifest/download | H6 accepted the exact H7 signed manifest and began the full encrypted download on three fresh boots | PASS for embedded Ed25519 verifier and HTTPS reachability |
| Inactive-slot completion | All three attempts ended with `[OTA-ERROR] image write/hash`; boot partition was never changed and active H6 plus NVS remained usable | FAIL for H7 install; fail-closed active-slot preservation PASS |
| Failed `app1` readback | First full readback SHA-256 was `ffa311011453f871bca9e85468416c890b337e7acc5f37a1f1a4416f842ccfeb`. Two attempts matched expected plaintext through offset 3804 and first differed at offset 3805 (`0xEDD`, `mod 16 = 13`) | ROOT CAUSE BOUNDARY CONFIRMED |
| GCM implementation root cause | Pinned Arduino 3.3.9 / ESP-IDF libs 5.5.4 GCM ALT resets multipart CTR residual and zero-pads partial GHASH per call. The exact `3841 + 437×4096 + 1491` transport sequence reproduced every failed-slot byte | ROOT CAUSE CONFIRMED; not RF/HTTPS corruption |
| Correction candidate | Runtime now carries 0..15 ciphertext bytes across calls, feeds only 16-byte multiples to non-final GCM updates, validates final carry modulo, and emits stage-specific safe error counters | PASS for source/host contract; production build and USB→next-OTA physical proof required |

The H7 failure deliberately invalidated only inactive `app1`; H6 remained the
active bootable slot and MQTTS recovered after each abort. Repeating H7 would
only rewrite the same inactive slot, so the Target was left in the USB stub
bootloader without flash mutation while the corrected image is built. The
current authenticated local upload path shares the same pre-fix GCM engine and
is not a valid workaround.

## 2026-08-24 exact H7 Android installation and Home Assistant observation

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Signed APK identity | GitHub run `32662983256` produced package `com.kshouse.gatekeeper_app`, version `1.0.0-ge00ebe8`, build `16001`; manifest Ed25519, APK v2/v3 signatures and expected certificate SHA-256 passed | PASS |
| Connected-device install | `adb install -r` on SM-F966N/Android 16 succeeded, the cold-started `MainActivity` became `topResumedActivity`, process remained alive and filtered fatal logs were empty | PASS for install/launch; OEM background access remains separate |
| Installed-byte identity | Pulling installed `base.apk` returned 55,770,265 bytes and SHA-256 `1e60e0cb878aab7f176807de2fb7284b653fd704cbef8c49e9dbcf71a281beae`, exactly matching the signed Actions artifact | PASS for exact installed APK |
| HA telemetry vs legacy controls | Live HA state showed 15 current read-only Target entities and six restored/unavailable historical control entities. Target firmware no longer publishes those unsigned command/config discovery records | PARTIAL: telemetry usable; stale registry cleanup pending |

The Android result proves exact H7 installation and one foreground launch, not
the NAS updater's end-user install flow, background scan reliability or mobile
rollback. The six HA controls must be removed from retained discovery/registry;
they must not be re-enabled without the separately reviewed signed backend
command bridge.

## 2026-08-24 H9-H11 Target OTA, RF isolation and HA migration

| Test | Observed result | Verdict / boundary |
|---|---|---|
| H9 NVS-preserving bootstrap | Exact-main H9 was written only to app0; pre/post readback verified bootloader, partition table, NVS, OTA data and app1 prefix were unchanged before first application boot | PASS for app-only bootstrap |
| H10 CI/NAS identity | Run `32667129968` published `2.1.241+main.g3311ad6`; the 1,796,080-byte plaintext and 1,796,116-byte encrypted artifact passed signature, GCM, digest and ESP32-C6 N16 checks with 5,543,952 bytes slot headroom | PASS for exact bytes/capacity |
| H9 → H10 periodic HTTPS | On a nearby 2.4 GHz AP the Target accepted the signed H10 manifest, downloaded the full encrypted artifact, verified the inactive image and rebooted to the exact H10 banner | PASS for signed encrypted install/reboot |
| H11 CI/NAS identity | Run `32668550147` published exact main `7a55a667b9d30f7929176997010d7ab71abaf833` as `2.1.242+main.g7a55a66`; manifest SHA-256 `280db36e2fe1b4a42e92a3a06c591887f95436d28cca114539d3263f5922647f`, encrypted SHA-256 `bd6274253224720e9c655bcf9e25609255516a5da8d7786973f6825789a155ef`, plaintext SHA-256 `ec5e24684f806c25f547be0f768932e419d6d5e4c4a0815f4a2b7b1d8faf0a6`; N16 headroom remained 5,543,952 bytes | PASS for exact CI/NAS bytes/capacity |
| H11 runtime | H11 booted, obtained `10.71.25.196` from the nearby AP, completed verified MQTTS, subscribed to exact Target topics, published diagnostics/config and reported `already current` for H11 | PASS for one live Wi-Fi/MQTT/current session |
| Intended home AP | Target scan observed the relevant 2.4 GHz signals around `-80~-82 dBm`; repeated reason 2/4/201 prevented stable association. Android freshly authenticated to the same SSID, while the Target connected immediately to the nearby AP around `-42 dBm` | FAIL for wall RF margin; credential/firmware path independently PASS |
| Recovery portal save | Android joined the authenticated recovery AP over USB-controlled Wi-Fi, sent `/save` with local auth and received HTTP 200; Target rebooted with the new NVS credential and later recovered station/MQTT service | PASS; no credential value logged |
| Home Assistant discovery | Applied 15 retained read-only discovery configs and seven legacy tombstones; an independent subscriber saw exactly 15 valid retained configs. With H11 online, HA showed firmware, IP, RSSI, IDLE/door state and config values live | PASS for read-only telemetry migration |
| Legacy HA controls | Historical button/number entities remain `restored/unavailable` in the HA registry after retained tombstones. They were not invoked or revived because no signed-command bridge exists | PENDING registry cleanup; fail-closed |
| OTA health/rollback | No `pending image health window started` or `running image marked VALID` log was observed on the retained bootloader/OTA-data path | PENDING; install/reboot/current does not prove health-valid or rollback |

The weak-link STA profile added after this observation must be tested on the
same hardware and position. Passing at `-81 dBm` would still not authorize wall
installation; section 5 of the connectivity policy requires RF improvement and
repeated outage/boot evidence.

## 2026-08-24 quiet recovery-AP arbitration candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Host timing/transitions | Native C++ policy tests cover the initial 30-second quiet interval, client/auth/operation blockers, one 10-second attempt, failure-to-quiet, request interruption, idle-client 10-minute expiry/deauth action, persistent reassociation before and throughout a forced bounded attempt, authenticated interruption, station success, `millis()` wrap and the timed-window zero-sentinel edge | PASS for deterministic policy logic |
| Firmware integration contracts | Focused connectivity/security tests verify one WebServer service call per loop, authenticated attempt pause, scan/save/local-OTA leases, no immediate post-scan reconnect, idle-client release, active-operation deadline deferral before AP close, AP-exit auto-reconnect restoration and unchanged MQTTS/OTA health gates | PASS for source integration; not radio runtime |
| ESP32-C6 compile/capacity | Default `esp32c6` compile with non-secret compile-only placeholders succeeded on Arduino 3.3.9 / ESP-IDF libs 5.5.4. `firmware.bin` is 1,786,336 bytes, leaving 5,553,696 bytes in either 7,340,032-byte OTA slot; the temporary ignored header was removed after the build | PASS for build and capacity; not a production-secret artifact |
| Boot recovery AP visibility | No physical Target was flashed from this candidate in this task | PENDING: verify at least 30 seconds of uninterrupted SSID discovery and association |
| Portal scan/list/save | No Android AP-only request/response or NVS-preserving reboot was exercised from this candidate | PENDING: authenticate, render list, select/manual fallback, save, reboot and read back without logging credentials |
| STA/MQTTS/OTA recovery | No physical late-STA association, MQTTS reconnect, periodic HTTPS OTA, signed local OTA, health-valid or rollback sequence was exercised | PENDING; wall installation Gate remains open |

The build proves that `esp_wifi_deauth_sta(0)` and the policy adapter compile for
ESP32-C6. It does not prove beacon continuity or coexistence behavior. Physical
testing must also leave a phone associated but idle through the bounded hold,
confirm that active authenticated upload is not interrupted, and verify that
normal pure-STA auto-reconnect, MQTTS, and signed OTA resume after AP exit.

## 2026-08-24 exact-main Target connectivity and recovery-path evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact runtime identity | The ESP32-C6 serial banner reported exact main `af779e1e61cd6c5c25b9b11e9aab9d1197ca094d` as `2.1.251+main.gaf779e1` | PASS for the observed running image |
| NVS Wi-Fi recovery | The Target restored the saved Fold7 hotspot profile from NVS, recovered from one transient authentication failure and obtained `10.71.25.196`; the SSID is intentionally omitted | PASS for this boot and reconnect only |
| Relay boot state | Serial reported the relay OFF before and after application initialization | PASS for logged software state; no physical relay actuation or electrical measurement |
| MQTTS | The Target authenticated, subscribed to the exact per-Target topics and successfully published retained boot diagnostics and config state | PASS for this live session |
| Periodic signed OTA | The periodic signed manifest check completed with an already-current result for the running exact release | PASS for manifest reachability/validation/current-version handling; no inactive-slot write or reboot |
| Authenticated local recovery | The same-LAN recovery path returned HTTP 401 without authentication, HTTP 200 with authentication and HTTP 202 for authenticated `enable-ap` | PASS for authentication enforcement and bounded AP enable request |
| AP+STA service continuity | During the recovery AP+STA window, Home Assistant kept all 15 read-only entities available while Target uptime advanced from 234 to 302 seconds | PASS for the observed 68-second coexistence interval |
| Post-reset convergence | After the final reset, Home Assistant again showed all 15 read-only entities available while uptime advanced from 51 to 101 seconds | PASS for one reset/reconnect interval |
| Default-disabled security state | NVS had no ACL signer or hardwareless-door override; the Target logged ACL verification fail-closed and Hardwareless GATT disabled | PASS for default-disabled behavior; provisioning/functionality was not exercised |

This run does not prove a real inactive-slot OTA installation, the continuous
health-valid mark, bootloader rollback, power-loss recovery, physical relay
operation/electrical safety, AJ-SR04T behavior or final wall-install acceptance.

## 2026-08-25 exact-main Android artifact pre-install verification

| Test | Observed result | Verdict / boundary |
|---|---|---|
| CI artifact identity | GitHub Actions run `32747024524`, artifact `personal-mobile-ota-7c2764a1a16492ec1620079c8211b47287b1b3fd-attempt-1`, supplied a 55,786,649-byte APK with SHA-256 `afb0cdc5eb95d8c0dd8c34597b180ddb803b6d8b35b9b1e130da7db13f054f42` | PASS for downloaded CI bytes |
| APK manifest | `aapt` reported package `com.kshouse.gatekeeper_app`, `versionCode=18201`, `versionName=1.0.0-g7c2764a` | PASS |
| APK signing continuity | `apksigner verify --verbose --print-certs` passed and reported signing-certificate SHA-256 `8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0` | PASS for APK signature and expected production signer |
| Embedded source identity | `assets/flutter_assets/assets/source_commit.txt` contained exact source commit `7c2764a1a16492ec1620079c8211b47287b1b3fd` | PASS |
| Connected-device installation | The APK was intentionally not installed during this verification-only step | PENDING: preserve the installed app and use same-signature `adb install -r` in the controlled device step |

This proves that the downloaded CI APK is internally consistent and eligible
for the same-signature replacement check. It does not prove Android package
installation, first launch, credential preservation, enrollment, native GATT,
background behavior or rollback.

## 2026-08-25 personal GATT and signed Home Assistant live baseline

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Android replacement install | The run `32747024524` production-signed APK was installed with `adb install -r`; package data remained present and the app reported `1.0.0-g7c2764a` / build 18201 | PASS for same-signature install and launch; uninstall/data clear was not used |
| Android native state | Bluetooth/location permissions, background location, Bluetooth ON, battery allowlist, local consent, Keystore credential and native GATT ownership were all present; the prior `NATIVE_GATT_DISABLED` reason disappeared | PASS for enablement prerequisites |
| Target exact-main OTA | Run `32749448224` published `2.1.256+main.g7c2764a`; the 1,844,800-byte image fit either 7,340,032-byte N16 OTA slot with 5,495,232 bytes headroom. Target installed/rebooted, obtained `192.168.35.19`, connected MQTTS, provisioned the production ACL signer, applied ACL v3 and started connectable GATT | PASS for this install, boot and transport state; rollback/power-loss remains pending |
| NAS Backend and HA bridge | Recreated the live Backend after correcting the paho MQTTv5 callback. Readiness passed, bridge retained availability became online, and Home Assistant rendered reboot/open/OTA/config controls enabled | PASS for discovery/availability; no HA command or relay was invoked |
| Android exact wake | The OS PendingIntent exact iBeacon scan was registered but reported zero filtered results; unfiltered Bluetooth state still saw `SmartGatekeeper`, and manual local retry returned `TARGET_UNAVAILABLE` because no locator existed | FAIL at advertisement matching, before GATT connection |
| Root cause | Pinned pioarduino swaps the `BLEBeacon` manufacturer setter argument. Target `0x004C` emitted company bytes `00 4C`, while Android correctly filters Apple `0x004C` as standard on-air `4C 00` | ROOT CAUSE CONFIRMED |
| Correction candidate | Target now passes `0x4C00`; source regression passed 9/9 and personal-production compile produced 1,779,430 bytes with 5,560,602 bytes slot headroom | PASS for source/build only; CI/NAS OTA and physical Android/GATT result pending |

The two feature planes are enabled, but this baseline does not yet claim local
door authorization: the corrected Target must advertise on air, Android must
record a locator, and the exact challenge/proof/result must reach the Target
FSM. Physical relay actuation and electrical safety remain separate Gates.

## 2026-08-25 exact wake, HA OTA and GATT callback-stack investigation

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact-main Target publication/install | GitHub Actions run `32768108034` published `2.1.259+main.gbc9bb5d`; the live HA OTA button delivered the signed command, after which Target downloaded, verified, installed and rebooted into that exact version | PASS for HA control → signed Target OTA → install/reboot/current-version; rollback and power-loss remain pending |
| Exact-main Android replacement | Run `32768108110` published production-signed `1.0.0-gbc9bb5d` / `versionCode=18501`; its manifest/artifact identity and APK signature verified, and `adb install -r` preserved package data and the enrolled credential | PASS for exact APK identity, same-signature replacement and state preservation |
| Android exact iBeacon delivery | Corrected company bytes produced ten OS PendingIntent exact-filter results with callback latency 6–20 ms and observed RSSI about -46 to -50 dBm | PASS for this connected, screen-on observation; background/OEM repetition remains pending |
| Exact-main GATT connection | Android connected, Target emitted Target Hello and ACK-gated multi-fragment Challenge, then exact-main `2.1.259` repeatedly reset with a stack-protection fault in task `nimble_host` | FAIL for exact-main local authentication; no proof/result/FSM/relay success |
| Root cause | ELF frames were about 2,736 bytes for output draining and 3,216 bytes for canonical JSON/MQTTS emission while the prebuilt NimBLE host task stack is 5,120 bytes. Both could execute from BLE callbacks | ROOT CAUSE CONFIRMED for the observed reset path |
| Stack-safe Target candidate | App-only USB flash of `2.1.260-test.g163610d` preserved bootloader, partitions, NVS, OTA data and fallback slot. It booted with Wi-Fi `192.168.35.19`, MQTTS, current ACL and GATT enabled; the same phone reached Target Hello/Challenge without a reset | PASS for the observed connection and reset non-recurrence; candidate is not exact-main signed OTA evidence |
| Candidate capacity | The candidate binary was 1,845,616 bytes and PlatformIO reported 1,780,006 bytes used in a 7,340,032-byte OTA slot (24.3%) | PASS with 5,560,026 bytes slot headroom |
| Android challenge stream | The installed bc9 APK subscribed to Challenge indications and also read the same characteristic. A single-frame read could interleave with indicated fragments sharing a message ID; the strict reassembler returned `MALFORMED_PROOF` | FAIL at Android transport framing, before proof/FSM/relay |
| Android correction candidate | Source now consumes Target Hello and Challenge only from the already-subscribed ordered indication mailbox and forbids a simultaneous Challenge read; focused source regression passed 11/11 and the focused JDK17 Android build/JUnit run completed 209 Gradle tasks successfully | PASS for local source/JVM coverage; hosted exact-toolchain CI, signed APK installation and physical proof/result remain pending |
| Hardened Target source build | Authentication control was separated from best-effort telemetry, callback-originated abort/advertising restart was moved to loopTask, and `esp32c6_personal_production` compiled with 1,780,268/7,340,032 bytes flash and 67,088/327,680 bytes RAM; `firmware.bin` was 1,845,984 bytes | PASS for local build/capacity only; these additional bytes were not yet installed |
| Home Assistant controls | Bridge availability remained online and reboot/open/OTA/config controls rendered enabled. OTA was exercised successfully; remote open was not invoked | PASS for availability and one OTA command; relay/open remains untested |

The physical target is currently running the USB stack-safe candidate so that
the deterministic reset can be tested without erasing Wi-Fi, ACL or OTA state.
The release Gate remains open until the same Target bytes and the corrected
Android transport are merged, CI-built, NAS-published, installed from exact
main, and one authenticated proof/result completes without a reboot. No relay
actuation or wall-install acceptance is claimed by this section.

## 2026-08-25 exact-main db37bc2 foreground evidence recovered from PR #132

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact source/artifacts | Runs `32777471683` and `32777471718` built and published exact main `db37bc2390efbf94bf1a9fca261834c3728606b5` as Target `2.1.262+main.gdb37bc2` and Android `1.0.0-gdb37bc2` / 19001 | PASS for exact historical identities |
| Target OTA/runtime | HA signed OTA installed/rebooted the Target; Wi-Fi `192.168.35.19`, MQTTS, current ACL and GATT returned | PASS for install/reboot/runtime; rollback and power loss not exercised |
| Android replacement | Production-signed APK was installed with `adb install -r` on SM-F966N, preserving package data, consent and AndroidKeyStore credential | PASS for same-signature replacement |
| Foreground local GATT | One foreground action-1 request completed service/indication/framed proof/result exchange; fresh health was `HEALTHY`, no failure/Target denial, 4,599 ms. HA independently recorded `AUTH_PENDING` 06:27:33, `ARMED` 06:27:36 and `IDLE` 06:28:35; Target did not reset | PASS for this historical foreground authenticated proof/result and FSM ARM |
| Physical boundary | No AJ-SR04T threshold, GPIO3 relay/contact, electrical, screen-off/OEM, rollback or power-loss measurement was captured | PENDING; no physical-open or wall-install claim |

Issue #133 later split the mobile manual button into action 2 immediate relay
and bound successful Result to the actual FSM transition. Consequently this
historical action-1 ARM evidence is not evidence for the current action-2 button
or pocket/background behavior.

## 2026-08-26 current a9 deployment boundary

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Target CI/NAS/install | Run `32872303874` published exact main `a9b68222f8c7d47a1ed36f4395c636f959bfb15d` as `2.1.266+main.ga9b6822`; 1,846,624-byte plaintext and 1,846,660-byte encrypted artifact fit a 7,340,032-byte slot at 25.16%, leaving 5,493,408 bytes. Signed OTA installed/rebooted it and Wi-Fi/MQTTS/ACL v147/GATT returned | PASS for exact Target publication and connected runtime |
| Android CI/NAS | Run `32872303799` published production-signed `1.0.0-ga9b6822` / 19801, 55,786,649 bytes, to primary/fallback NAS paths with HTTPS readback | PASS for artifact publication only; no phone installation |
| Current access E2E | Phone, AJ-SR04T and relay were not connected | PENDING action-2 manual button, pocket action-1, sensor and contact evidence |

## 2026-08-26 issue #133 manual local-open software candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Target action contract | Native host tests accept action 1 and 2, reject unsupported actions, and verify `RESULT OK` is not emitted when the application control gate rejects the transition | PASS for deterministic host logic |
| Target FSM | action 1 reaches `ARMED` with relay OFF; action 2 reaches `RELAY_HOLD` and invokes the relay callback immediately; pending/action rejection returns non-OK and cleanup | PASS for host callback/FSM behavior; no physical GPIO/contact evidence |
| Android action contract | `GattSessionEngine` signs the selected action into canonical byte 56 and proof wire byte 34; background worker passes action 1 and foreground manual executor passes action 2 | PASS for source/unit candidate; hosted Android CI pending |
| Manual UI truthfulness | WebView no longer treats queue acceptance as open success. It calls terminal `triggerLocalGattOpen` and displays success only after Target reason 0; an already enrolled credential has no per-tap backend status GET | PASS for source contract; no connected-phone timing evidence |
| ESP32-C6 build/capacity | `esp32c6_personal_production` compiled with 1,780,836/7,340,032 bytes flash (24.3%) and 67,088/327,680 bytes RAM (20.5%) | PASS for local build and dual-slot capacity headroom |

Phone, AJ-SR04T and physical relay were not connected during this candidate
test. Exact-main CI artifacts, NAS publication, Target OTA/install/reboot and
manual button-to-contact timing remain pending. The hands-free path is tracked
separately in issue #134.

## 2026-08-26 issue #134 pocket-approach software candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Activation wiring | Native GATT enable attempts the exact OS PendingIntent registration in the same control call; disable stops it, and health recomputes current permission/Bluetooth readiness | PASS for deterministic source/control wiring; OS registration survival requires a phone |
| Background dispatch | Android 12+ first presence work is expedited with `RUN_AS_NON_EXPEDITED_WORK_REQUEST` fallback, Android 8~11 retain regular work, no network constraint is added, and the worker signs only `ARM_FOR_SENSOR(1)` | PASS for Android source/unit contract; OEM scheduling latency is pending |
| Stale wake safety | Presence work older than 45 seconds terminates as non-retryable `PRESENCE_EXPIRED` before BLE ownership/proof; process clock rollback does not falsely expire new work | PASS for policy/JVM logic |
| End-to-end observability | Durable redacted state records presence-to-dispatch and presence-to-Target-ARMED separately from GATT session latency | PASS for codec/health/UI source; no connected measurement yet |
| Target sensor interlock | Native host regression holds relay OFF through `AUTH_PENDING -> ARMED`, then permits `RELAY_HOLD` only after a valid ultrasonic trigger; main loop samples only while `ARMED` at 100 ms intervals | PASS for deterministic Target host/source behavior; no AJ-SR04T/GPIO3 timing evidence |
| Focused local suite | Pocket source contract plus Target native host suite: 15/15; implementation/mobile contract suites: 21/21 | PASS for 36 local software tests; hosted Android/Target CI pending |

No phone, AJ-SR04T or physical relay was connected. Screen-off/pocket success
rate, OS delivery delay, presence-to-ARMED distribution, sensor threshold and
GPIO3 contact timing remain pending and must not be inferred from these tests.

## 2026-08-26 exact-main b6 action-2 abort and issue #143 candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact Target OTA | Run `32881540989` published exact main `b6cf6ec1a725e734d67df1ae8729e02f3ade0a9c` as `2.1.267+main.gb6cf6ec`. The connected a9 Target accepted the signed manifest, downloaded the 1,846,660-byte encrypted artifact, verified the inactive slot and rebooted into b6; Wi-Fi `192.168.35.19`, MQTTS, GATT and ACL v159 returned | PASS for signed install/reboot/current runtime; the retained OTA-data path again emitted no pending-health/valid-mark log, so rollback remains pending |
| Exact Android replacement | Run `32881541103` supplied a 55,786,649-byte production-signed APK. SHA-256 was `d0d3ae4b193b5a42e1003197019d865841d1f461ebf012bffab77ceff91e62f7`, signer SHA-256 matched the installed app, and embedded source was exact b6. `adb install -r` produced `1.0.0-gb6cf6ec` / 19901 while preserving first-install time, app data and AndroidKeyStore | PASS for exact identity and same-signature replacement |
| Main `문 열기` action 2 | Android connected, discovered the service and enabled Hello/Challenge/Result indications. Proof processing then reset the Target before any `RELAY_HOLD`, relay ON/OFF or successful Result; Android reported `PROOF_OUTCOME_UNCERTAIN` | FAIL; issue #143 release blocker |
| Crash decode | Physical trace reported `abort()` at `0x40801c75`; production-equivalent ELF mapped the call chain through `TargetAccessFsm::handleLocalManualOpen`, `ProtocolCore::processProof` and the relay callback. `relayOn()` reached `LOGF` while `GattServer::update()` still held the `core_mux` FreeRTOS critical section, and newlib aborted while acquiring its recursive stdout lock | ROOT CAUSE CONFIRMED |
| Issue #143 source candidate | The protocol/adapter serialization lock is a task-context `std::recursive_mutex`, so the synchronous Result-to-FSM action commit may safely reach GPIO, failsafe timer, diagnostics and logging while remaining serialized with NimBLE callbacks. Focused Hardwareless/pocket tests passed 16/16 | PASS for source/host regression only |
| ESP32-C6 candidate capacity | `esp32c6_personal_production` compiled successfully with 1,781,874/7,340,032 bytes flash (24.3%) and 67,088/327,680 bytes RAM (20.5%) | PASS for local build/capacity; exact CI/NAS publication, install and connected action-2 repetition remain pending |

The board-only setup proves the commanded GPIO/FSM path only when the serial
trace reaches it; it does not prove a relay contact or electrical load. Issue
#143 cannot close until the exact merged signed image completes terminal action
2 without reset and logs one relay command ON/OFF sequence. Physical contact,
sensor threshold and power behavior remain separate #54 Gates.

## 2026-08-26 exact-main 848 action-2 acceptance and pocket NVS blocker

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact Target release | Run `32888032443` signed/encrypted and NAS-published exact main `848bbf16`; periodic inactive-slot OTA installed `2.1.270+main.g848bbf1`, then Wi-Fi `192.168.35.19`, MQTTS, GATT and ACL returned | PASS for publication, install, reboot and connected runtime; no pending-health/valid-mark trace, rollback still pending |
| Exact Android release | Run `32888032174` published the production-signed 55,786,649-byte APK, SHA-256 `016e62c5d0fe834f42a06e6651442860a62e06f3798fcaaff4781a8a92c379d4`; same-signature `adb install -r` produced `1.0.0-g848bbf1` / 20201 with data and AndroidKeyStore preserved | PASS for exact identity and replacement install |
| Main action-2 button | Four connected attempts across the prior and exact 848 APKs completed authenticated GATT, Target relay-command ON/OFF and terminal UI success without reset; UI completion was about 4.5--5.2 seconds | PASS for board/FSM/GPIO command path; contact voltage, actuator and actual door remain unmeasured |
| Screen-off first match | Android registered OS BLE wake, moved to background with the display dozing and its WorkManager job completed; Target accepted one GATT connection but never logged `ARMED` or relay | INCONCLUSIVE/FAIL for core pocket acceptance; WorkManager completion is not Target success |
| NVS fault | The same attempt emitted `ledger_b NOT_ENOUGH_SPACE`; prior retained ACL delivery emitted `slot_0 NOT_ENOUGH_SPACE` and rejection | ROOT CAUSE CANDIDATE for action-1 fail-closed storage rejection; issue #149 |
| Issue #149 local candidate | Original 20 KiB NVS and both 7 MiB OTA slot offsets remain fixed. ACL/replay/queue writes use the unused 1.875 MiB region, legacy reads fall back, automatic erase is forbidden. 105 focused tests passed; personal-production build used 1,782,274/7,340,032 bytes flash (24.3%) and 67,088/327,680 bytes RAM (20.5%) | PASS for local source/build/capacity; hosted CI, merge, signed OTA and connected action-1 retry pending |

The connected board currently has no AJ-SR04T/relay load acceptance fixture.
After issue #149 merges and installs, the release Gate requires serial evidence
for durable partition readiness, replay write success, `AUTH_PENDING -> ARMED`,
a valid ultrasonic threshold event and relay-command ON/OFF. Only the first
three can be evaluated without the physical sensor and contact fixture.

## 2026-08-26 final-main 493 post-merge connected validation

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Artifact identity | Live signed NAS manifest selected commit `493591bb`, version `2.1.273+main.g493591b`; immutable ciphertext and authenticated plaintext matched `1,849,044` / `31480801...684e4d8a` and `1,849,008` / `b734ee43...1228a9a8` | PASS for exact CI/NAS artifact identity before recovery install |
| Recovery install | The old full replay ledger rejected the HA OTA effect, so COM5 wrote the standard bootloader/partition/OTA-select offsets plus exact CI app without erasing Wi-Fi/config NVS | PASS for bounded serial recovery and exact boot; this is not a signed inactive-slot OTA install |
| Durable NVS | Exact 493 boot reported `sgkstate used=0 free=60480 total=60480`; ACL v169, v170 and v171 all applied with no `NOT_ENOUGH_SPACE` | PASS for connected durable partition and ACL writes |
| Replay persistence | Signed HA reboot succeeded twice; next boot usage persisted and advanced `179 -> 195` | PASS for signed command replay persistence across reboot |
| HA OTA control | Enabled HA OTA button produced Target `[OTA] forced update check started` and `already current: 2.1.273+main.g493591b` | PASS for HA bridge -> signed command -> Target OTA-check effect; no install was needed because current |
| HA remote open | Enabled HA remote-open button produced relay-command ON then timer-bound OFF without reset | PASS for HA/backend/Target board-FSM/GPIO command path; physical contact and door unmeasured |
| Screen-off attempt 1 | OS first-match at RSSI -50 with `screen_interactive=false`; native worker completed and Target accepted GATT, but no `ARMED` | FAIL/UNCLASSIFIED for hands-free acceptance; app durable reason pending unlock |
| Screen-off attempt 2 | OS first-match at RSSI -52; Android connected, discovered services, enabled indications and wrote the complete framed request/proof sequence; Target accepted GATT, but no `ARMED` | FAIL/UNCLASSIFIED for hands-free acceptance; importantly no NVS/ACL/replay error recurred |
| Screen-off attempt 3 | Target was held in the ROM bootloader without a flash write, phone logcat was cleared, then Target was hard-reset. The OS first match arrived with `screen_interactive=false`; service discovery, indications and all proof fragments completed before the later periodic OTA check, but no `ARMED` followed | FAIL for action-1 acceptance and excludes OTA-busy collision; issue #156, exact durable app reason pending unlock |
| Physical sensor/contact | No AJ-SR04T echo or relay contact/load fixture is attached | PENDING; threshold-to-relay, electrical timing and actual door remain unclaimed |

Issue #149's storage acceptance is complete and the issue is closed. At this
point the missing action-1 terminal result was tracked separately by issue #156;
the later exact-main Android acceptance section below supersedes that failure
and closes #156. It does not reopen the storage design.

## 2026-08-26 exact-main Android connected acceptance and OTA TLS failure

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Android artifact/install | Run `32903378187` production-signed exact source `1e3dfcf32c7b3ef88121fb824c35d81d2f6d40a7` as `1.0.0-g1e3dfcf` / 21001. APK SHA-256 `cbf8497c...9243a5b`, embedded source and production signer matched; `adb install -r` preserved first-install time and KeyStore state | PASS for exact APK identity, same-signature replacement and credential preservation |
| Native health | Dashboard reported `HEALTHY`, `BLE Owner: native_gatt`, `Hands-free: READY` and `local_keystore_authenticated` | PASS for the observed installed state |
| Main `문 열기` action 2 | Tap at 07:14:18 led to HA `AUTH_PENDING` 07:14:20, Target relay ON and HA `RELAY_HOLD`/door-open 07:14:23, OFF/`COOLDOWN` 07:14:24 and `IDLE` 07:14:29 without reset | PASS for mobile -> GATT -> Target FSM/GPIO command and timer cutoff; physical relay contact/door absent |
| Bounded BLE-owner recovery | Observed Flutter owner-exclusion attempts at 07:14:46, 07:15:17, 07:15:47 and 07:16:17 rather than the prior immediate subscription/notification loop | PASS for connected bounded retry; issue #158 closed |
| Screen-off action 1 | App was on Home and phone remained `Dozing`; after one authenticated Target reboot, native WorkManager completed `SUCCESS`, Target accepted GATT and HA recorded `AUTH_PENDING` 07:17:33 -> `ARMED` 07:17:36 | PASS for one real screen-off first-match through terminal action-1 ARM; issue #156 closed |
| Signed exact-main Target OTA | Runs `32903378312` and `32907218154` published `2.1.275+main.g1e3dfcf` and `2.1.278+main.gc5d79eb`. Target accepted both signed manifests; even after #161 released the first client, the artifact's second TLS handshake still failed `-9984`, returning HTTP/size code -1 | FAIL before inactive-slot write; issues #160/#166, installed Target remains 493. The next candidate must reuse the authenticated HTTP/1.1 keep-alive connection and pass a connected retry |
| Physical sensor/contact | AJ-SR04T and relay/contact/load are not attached | PENDING: `ARMED -> threshold -> relay`, electrical timing and actual door remain unclaimed |

The action-1 and action-2 software/control requirements now pass their connected
board-level boundaries. This does not convert the absent sensor, relay contact,
OTA health-valid/rollback or wall-install checks into evidence.

## 2026-08-26 exact-main 281 OTA acceptance and screen-off repetition

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Pre-fix reproduction | Running 493 accepted signed `2.1.281+main.g082e431`, then failed the artifact's second TLS handshake with Mbed TLS `-9984`; no inactive write began | FAIL reproduced at the exact historical boundary |
| NVS-preserving bootstrap | COM5 wrote `bootloader.bin`, reviewed 16 MiB `partitions.bin`, `boot_app0.bin` and exact-source 082 `firmware.bin` at `0x0/0x8000/0xe000/0x10000`. No erase/factory image was used; every written region passed esptool digest readback | PASS for bounded bootstrap and written-region integrity; local build did not carry CI release-version injection |
| Periodic signed OTA | Corrected downloader accepted the signed manifest, started the exact 1,849,444-byte encrypted artifact, verified the inactive image and rebooted | PASS for CA/hostname-verified keep-alive download, decrypt/hash/image verification, inactive write and boot selection |
| Exact runtime recovery | Boot banner reported `2.1.281+main.g082e431`; saved Wi-Fi returned at `192.168.35.19`, exact per-Target MQTTS subscribed, ACL v188 applied and GATT was enabled. A later periodic check reported already current | PASS for exact CI runtime identity and connected service recovery |
| Pending health/valid mark | Neither first OTA boot nor the following 30-second healthy interval logged `PENDING_VERIFY` health start or valid mark | FAIL/PENDING; issue #172. Install/reboot/current version is not rollback proof |
| Exact 281 screen-off action 1 | OS first match at RSSI -53 and `screen_interactive=false`; Android connected, discovered services and enabled Hello/Challenge/Result indications, then WorkManager returned `FAILURE` after about 3.4 seconds. Target accepted GATT but never entered `ARMED` | FAIL for current repetition. Secure keyguard prevents reading the redacted durable reason until user unlock; earlier 493 success does not supersede this result |
| Current manual action 2 | Phone is connected but secure PIN keyguard prevents the user-visible button from being exercised | BLOCKED on user unlock; prior 493 relay-command ON/OFF remains historical evidence only |
| Physical sensor/contact | AJ-SR04T and relay/contact/load are not attached | PENDING; threshold-to-relay, contact voltage/timing and actual door remain unclaimed |

## 2026-08-26 exact-main 282 controls and issue #175 ACL-gated BLE candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact artifacts | Target `2.1.282+main.g3cf6eaa` and production-signed Android `1.0.0-g3cf6eaa` / 21701 both identify exact source `3cf6eaa925e5ef38ee7d538a6d7a1cf8720ad219`; APK hash, embedded source and signer matched before replacement install | PASS for exact installed software identity |
| Main action-2 button | Authenticated GATT reached Target relay-command ON, timer-bound OFF and terminal UI success in 4,636 ms | PASS for mobile -> GATT -> Target FSM/GPIO command; physical contact/load and actual door absent |
| Stable foreground action-1 | With the signed ACL active, the explicit action-1 diagnostic reached Target `ARMED`; UI recorded `Presence -> ARMED` in 4,688 ms | PASS for authenticated transport/result and sensor-arm FSM only; no ultrasonic trigger followed |
| Screen-off boot-first-match | Home + Dozing + secure keyguard; Target absent 15 seconds then booted. Callback was `screen_interactive=false`, RSSI -51 and 5.37 ms, but worker failed after about 3.4 seconds and Target never reached `ARMED` | FAIL for current pocket repetition |
| Root cause | Stored ACL validates at boot but remains intentionally inactive without trusted wall time. BLE advertising began before MQTT applied the fresh signed ACL, so the phone consumed its first match during the fail-closed interval | CONFIRMED runtime/source ordering; issue #175 |
| Issue #175 local candidate | Personal Hardwareless BLE waits for `hasActiveAcl()`, then initializes exactly once; non-Hardwareless startup remains immediate. Focused startup, pocket and Hardwareless tests passed 18/18; expanded security/trusted suite passed 68/68 | PASS for local source/host behavior; hosted CI, merge and exact-main boot trace pending |
| ESP32-C6 N16 capacity | `esp32c6_personal_production` built successfully at 1,782,948/7,340,032 bytes flash (24.3%) and 67,096/327,680 bytes RAM (20.5%); total image size was 1,849,780 bytes | PASS for local production build/capacity and dual 7 MiB-slot fit |
| First hosted CI | Both OTA-contract and Target canary jobs stopped before compilation because the privileged exact-build inventory correctly detected the new header. The candidate now pins the normalized digests of `BleStartupPolicy.h` and changed `main.cpp`, and raises the exact tracked-input count from 41 to 42 | EXPECTED fail-closed inventory result; fresh CI and trusted policy authorization required |
| Current physical boundary | Android phone has been disconnected; AJ-SR04T and relay/contact/load are absent | PENDING screen-off repetition, ultrasonic threshold, contact/electrical timing and door movement |

The failed boot-first-match is not replaced by the stable foreground action-1
success. Final pocket acceptance requires the merged exact-main Target to log
signed ACL application before iBeacon/GATT readiness and a reconnected phone to
reach terminal `ARMED`. Sensor-to-relay acceptance remains a separate physical
fixture Gate.

## 2026-08-26 exact-main 285 post-merge ACL-before-BLE acceptance

| Test | Observed result | Verdict / boundary |
|---|---|---|
| CI/NAS identity | Run `32916682601` built, production-signed, encrypted, atomically published and HTTPS-read-back final main `577533186ba5b40ca13fc47aadf51747e2057b73` as `2.1.285+main.g5775331` | PASS for exact production artifact publication |
| Connected OTA | Running 282 accepted the signed manifest, downloaded 1,849,860 encrypted bytes, verified the inactive image and rebooted into exact 285 | PASS for signed download, inactive verification, boot selection and exact runtime identity |
| Service recovery | Saved Wi-Fi restored at `192.168.35.19`; MQTTS subscribed, retained diagnostics/config returned and signed ACL v203 applied | PASS for one connected reboot recovery |
| Corrected BLE order | Boot logged `waiting for an active signed ACL`; after MQTT connected and ACL v203 applied it logged `active signed ACL ready`, then initialized enabled GATT and iBeacon | PASS for issue #175 Target startup-order acceptance |
| Stable/current interval | No reset occurred over the following 30 seconds; periodic HTTPS OTA reported already current at exact 285 | PASS for bounded connected stability/current-version check |
| Boot health/rollback | No `PENDING_VERIFY` health-window or running-image valid-mark trace appeared | PENDING/FAIL to prove rollback; issue #172 remains open |
| Mobile and physical boundary | Android is disconnected; AJ-SR04T and relay contact/load are absent | PENDING post-fix screen-off action-1, ultrasonic threshold, contact/electrical timing and actual door movement |

The startup-order result closes only the Target-side race. It does not replace a
phone-delivered terminal action-1 result or any sensor/contact evidence.

## 2026-08-28 WSL USB personal-production upload and serial observation

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Source and profile | Synchronized source `21e71d1c8faf469d101a477207276a80297873c8` built locally as `esp32c6_personal_production` with the ignored provisioned `include/secrets.h`; the local banner remained generic `v2.1.0` because no CI release-version override was injected | PASS for exact local source/profile build; not signed CI/NAS release identity |
| N16 capacity | Pinned pioarduino `cbc3349` reported 16 MB flash, 67,096/327,680 bytes RAM and 1,783,028/7,340,032 bytes application flash. Bootloader image-info reported ESP32-C6, 16 MB, DIO, valid checksum/hash | PASS for local build/capacity and dual-slot layout |
| WSL USB identity | `usbipd-win` BUSID `2-4` remained attached as `1a86:55d3`, serial `5C37195343`, and WSL/PlatformIO selected `/dev/ttyACM0` | PASS for the exact Windows-to-WSL serial bridge |
| USB write | PlatformIO/esptool wrote bootloader, `partitions_16MB_ota.csv`, framework `boot_app0` and the local application at `0x0/0x8000/0xe000/0x10000`; each write passed esptool hash verification and the chip hard-reset through RTS. No whole-chip/NVS erase command was used | PASS for these written regions; not inactive-slot OTA/rollback evidence |
| 115200 serial path | A bounded 30-second monitor after one RTS reset received 3,531 bytes including ESP32-C6 ROM boot, application banner and runtime logs | PASS for WSL serial receive/monitor path |
| NVS and network recovery | Boot restored saved tuning and Wi-Fi, obtained `192.168.35.18`, started the Target WebServer, authenticated MQTTS, subscribed exact per-Target topics and published retained diagnostics/config | PASS for this observed boot/session; no outage soak or WAN recovery claim |
| Security/BLE recovery | Boot reported missing optional `hwless_door`, persisted ACL signer and `next_restart` values, then provisioned the configured signer, applied signed ACL v299, started GATT and iBeacon, and accepted one GATT connection | PASS for bounded fail-closed-to-active startup; missing-key diagnostics remain observable and no authenticated proof/result was exercised |
| Monitor-close/network boundary | A final 20-second reset/monitor disabled `HUPCL`, left DTR/RTS idle and repeated Wi-Fi/MQTTS/ACL v301/GATT startup before close. Windows was on `192.168.55.72/24` while Target used `192.168.35.18`; subsequent host ping/HTTP had no route and timed out | Serial startup remains accepted; post-close LAN reachability is unproven rather than failed Target health |
| Relay/sensor boundary | Boot logged software relay OFF and initialized AJ-SR04T GPIO10/11, but no echo threshold, GPIO3 contact/load, actuator or door movement was measured | PENDING physical sensor/contact/electrical acceptance |

This direct USB install overwrote the selected boot/application regions and is
not evidence for periodic signed OTA, inactive-slot verification, health-valid
marking or rollback. The successful serial boot also does not by itself prove
mobile action-1/action-2 completion or physical door operation.
Because the locally flashed banner is generic `v2.1.0`, a later periodic signed
OTA check can replace it with a newer authorized release. This session did not
wait for or block that recovery path.

## 2026-08-28 Windows-hosted ADB connection from WSL

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Windows USB identity | `usbipd-win` listed the Z Fold7 as BUSID `4-1`, VID:PID `04e8:6860`, state `Not shared`; Windows PnP exposed Samsung composite, MTP, modem and Android ADB interfaces | PASS for Windows enumeration; phone was not transferred to WSL USB/IP |
| ADB authorization | Windows SDK `adb.exe` started its server and listed serial `R3CY707DL7L` as `device`, product `q7qksx`, model `SM_F966N` | PASS for authorized Windows-hosted ADB transport invoked from WSL Bash |
| Read-only shell | `get-state` returned `device`; properties reported Samsung `SM-F966N`, Android 16/API 36 and `arm64-v8a` | PASS for bounded ADB shell access |
| Installed app identity | Package `com.kshouse.gatekeeper_app` was present as `versionName=1.0.0-g3cf6eaa`, `versionCode=21701`, `minSdk=24`, `targetSdk=36` | PASS for installed package metadata only |
| Runtime boundary | No APK install/update, app launch, permission change, logcat capture, BLE/GATT action, screen-off trial or package-data access was performed | PENDING all mobile behavior and current-source replacement evidence |

The phone remains Windows-owned while the CH343 Target remains WSL-attached.
This accepts a practical ADB control path from the WSL shell, not native Linux
ADB visibility inside WSL or the Docker Flutter builder.

## 2026-08-28 current Fold7 main action-2 core-use-case check

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Connected preflight | Target local source `21e71d1` booted through the WSL CH343 path, restored saved Wi-Fi `192.168.35.18`, connected MQTTS, applied signed ACL v303 and started enabled GATT/iBeacon. Fold7 ADB remained authorized and the app was foreground-visible | PASS for this bounded transport/runtime precondition; local generic `v2.1.0` is not exact CI/signed OTA identity |
| App state | Installed `1.0.0-g3cf6eaa` / 21701 showed backend `승인됨`, enabled main `문 열기`, native worker `HEALTHY`, BLE owner `native_gatt`, and `local_keystore_authenticated` | PASS for visible preflight state; outer Flutter beacon scan was owner-excluded by the native worker as designed |
| Dashboard retry distinction | The local-control-screen `1-Tap 수동 로컬 개방` returned queue acceptance, but exact installed source maps it to `triggerLocalGattRetry()` / action-1 WorkManager rather than terminal action 2. It stayed `Target Result: NONE`, latency 0 during observation | NOT action-2 evidence; the misleading label must not be treated as an opened door |
| Main action-2 execution | One exact main-WebView `문 열기` tap connected at about 22:36:37, completed service discovery, and enabled Hello/Challenge/Result indications. Android closed the GATT session about 1.8 seconds later and displayed `수동 출입 실패: PROTOCOL_INCOMPATIBLE` | FAIL before authenticated proof/result; unchanged non-retryable attempt was not repeated |
| Target-side effect | Serial recorded the GATT connection as accepted but no proof-verification evidence, `AUTH_PENDING`, `RELAY_HOLD`, relay ON/OFF, cooldown or successful Result. Later periodic OTA check rejected a downgrade and kept the running image | PASS for fail-closed/no-actuation behavior; FAIL for the requested core manual-open outcome |
| Compatibility diagnosis boundary | Installed commit and current HEAD both declare protocol/framing v1, and the core Android/Target protocol files have no diff between `3cf6eaa` and `21e71d1`. Android also maps rejected Target Hello or an unexpected message type into the same public reason | Exact wire cause unresolved; `PROTOCOL_INCOMPATIBLE` does not by itself prove a numeric version mismatch |
| Physical boundary | No relay contact voltage/current, actuator movement, door movement, AJ-SR04T threshold, repeated timing or rollback was measured | PENDING physical acceptance; software fail-closed evidence only |

The current connected core use case is not accepted. The phone reached the
Target over BLE, but no authenticated action reached the Target FSM or relay.
Historical exact-282 action-2 success remains historical and does not override
this current local-Target repetition.

## 2026-08-29 production-app action-2 connected recovery

| Test | Observed result | Verdict / boundary |
|---|---|---|
| APK identity and preservation | NAS production APK `1.0.0-g40852b7` / 22401 matched 55,786,649 bytes, SHA-256 `2790c2844c62881a9fc3e27c1632514fb2ba82080deb12d2ff3775373b63468d` and signer-certificate SHA-256 `8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0`; `adb install -r` retained approved user/native credential state | PASS for production-signed mobile replacement and state preservation |
| Main action-2 | One enabled WebView `문 열기` tap completed terminal UI `문이 열렸습니다 (4585ms)`; native health stayed `HEALTHY`, last latency became 4585 ms, and Android recorded successful writes/indications followed by local disconnect | PASS for authenticated mobile -> Target action-2 terminal software/FSM outcome; stale-app `PROTOCOL_INCOMPATIBLE` not reproduced |
| Target publication | Exact-main run `33199155599` published signed encrypted `2.1.291+main.g89e047c` and the public manifest readback matched commit `89e047c` | PASS for CI/NAS publication only; connected Target install, reboot and health are not observed |
| Physical boundary | No relay contact voltage/current, attached actuator, actual door motion, AJ-SR04T threshold, repetition distribution or rollback was measured | PENDING physical acceptance; terminal protocol success is not contact/door proof |

The earlier failure remains valid for stale installed APK `g3cf6eaa`; the
current production-app repetition supersedes it for the connected action-2
software outcome only.

## 2026-08-28 backend CI to Synology deployment host verification

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Signed release bundle | P-256 descriptor signing produced exactly `release.env`, detached signature and the two Compose files; public-key verification passed and a descriptor mutation failed verification | PASS for host cryptographic contract; production key and GitHub execution untested |
| Synology Compose overlay | Compose v2 rendered exact API/DB digest references, API host bind `127.0.0.1:8000`, NAS file secrets and four explicitly named external volumes; production base exposes no DB/API host port | PASS for local render/static boundary; exact DSM render and start untested |
| Restricted NAS command | Bash syntax passed; arbitrary command input was rejected; source checks require signature/hashes/fixed repos/schema, root-controlled config, existing volumes/secrets, first-adoption holder rejection, migration, exact running-image identity, loopback/public readiness and sanitized evidence | PASS for six focused host unit tests and shell/static contract; no NAS sudo/SSH invocation |
| Backend commercial contract | `scripts/ops_commercial_gate.py contract` passed all 34 repository-only checks after the new backend/deploy inputs were added to the trusted bundle inventory | PASS for repository completeness; protected trusted-policy rotation remains required before merge |
| Full backend regression | The hash-locked backend environment completed 126 tests successfully; two explicit real-MariaDB integration cases remained skipped because `RUN_MARIADB_INTEGRATION=1` was not enabled in this host run | PASS for unit/host regression; CI real-MariaDB jobs and live NAS DB remain separate |
| Live deployment | The owner successfully ran the no-cutover bootstrap: existing containers remained running, NAS-local secret/state files and three external bind-backed volumes were prepared, and copied target config retained SHA-256 `c5668365bd130ec42c7f49aafc53491b1a6ad3a3eb4858f3215b83de3505ece9` | PASS for layout preparation only; no GHCR package, GitHub Environment/Tailscale deploy identity, DB migration, new Compose project, traffic cutover, readiness or rollback rehearsal |
| Legacy container identity | Owner output identified `gatekeeper-api` using local `smart_gatekeeper-api` and publishing `8000` on wildcard IPv4/IPv6; `gatekeeper-db` uses mutable `mariadb:10.11` and publishes no DB host port | PASS for container/port identity only; exact mounts, image bytes/schema and backup remain unknown |
| Legacy persistent mounts | `gatekeeper-db` mounts named volume `smart_gatekeeper_mariadb_data` at `/var/lib/mysql`; API bind-mounts live source at `/app`, APKs from `/volume1/docker/smartbox_ota/gatekeeper_apk`, and one MQTT CA file, with no `/var/lib/smart-gatekeeper` state mount | PASS for DB/APK source identity; target config, runtime user/secrets and backup remain pending |
| Legacy runtime identity/state | API readback reported database `smart_gatekeeper`, user `gatekeeper_user`, and root-owned mode-`0555` `/app/target_config.json` at 135 bytes with SHA-256 `c5668365bd130ec42c7f49aafc53491b1a6ad3a3eb4858f3215b83de3505ece9` | PASS for non-secret identity and source-byte fingerprint; state-volume copy/readback pending |

These results prove the candidate's source and host contracts only. They do not
prove a running NAS backend, and they do not imply mobile, Target, BLE, relay,
sensor or physical-door success.

## 2026-08-29 legacy NAS bootstrap and personal-admin preservation

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Secret semantics | Owner-side checks reported the API/DB runtime passwords match, required primary secrets are set, active command/ACL P-256 scalars have valid shape, the personal administrator password has valid length, and the transition signer pair is disabled | PASS for non-secret semantic state only; no secret value/hash was recorded or independently read by this workspace |
| Personal admin file secret | `AdminSecurity.from_environment()` accepts only one of direct value or `PERSONAL_ADMIN_PASSWORD_FILE`; file success enables the personal session while conflicts and unreadable paths fail closed | PASS in host tests; live NAS Compose/admin login remains untested |
| No-cutover bootstrap | Exact-layout script checked legacy container/project/mount identities, password equality, signing-scalar shape and target-config hash/size; owner execution staged root-only secrets/state and three bind-backed volumes while both legacy containers remained running | PASS for observed layout preparation; no database migration, new Compose startup or cutover occurred |
| Backend regression | 129 backend tests passed in the local hash-locked environment; two opt-in isolated real-MariaDB integration tests were skipped | PASS for host regression; GitHub CI, live MariaDB restore and first deployment remain pending |
| Repository contract | The backend commercial repository contract passed all 34 checks and Compose rendered with the personal-admin file secret | PASS for repository scope; trusted-base rotation is required before merge |
| NAS layout/ACL readback | Owner read-only verifier passed 14 secret-file contracts, exact runtime keys, three external volumes and unchanged legacy containers; DB ledger is `002`-`007`, active credential/grant counts are 1/1, and latest snapshot/applied ACK both equal 313 | PASS for aggregate layout and ACL freshness; exact identity correlation, off-NAS restore, migration and cutover remain separate |
| NAS exact ACL identity correlation | Boolean-only owner rerun matched feature flags, Target auth, dual/public tenant mapping, active ACL tenant, active credential/grant, door state, latest snapshot and applied Target ACK; snapshot/ACK advanced together to 314 | PASS for the technical non-legacy authorization path; owner legacy-lookup-disable decision, off-NAS restore and live cutover remain pending |
| DB size and restore harness | Owner readback reports 2,686,976 database bytes across 20 tables and a 1,638,400-byte largest table; NAS before/dump/after inventory gating, WSL authenticated encryption and exact-digest localhost restore code passed eleven focused tests and the full 133-test backend run (two real-MariaDB opt-in skips) | PASS for capacity and repository software; live NAS backup, encrypted-copy readback and restore are recorded separately below |
| Consistent NAS logical backup | Owner run created a 792,678-byte dump in backup `pre-cutover-20260828T155308Z-9349` for deployed source `7c2764a1a16492ec1620079c8211b47287b1b3fd`; bundle SHA-256 is `d2321993a1858ec053c614bf6aecb212012f2dd25db59ff2fd49ed42056f418d` and legacy containers remained running | PASS for NAS-local consistent backup and temporary plaintext owner export; transfer/encryption/restore results are recorded separately below, recurring backup remains pending |
| WSL encrypted copy readback | Authenticated SSH stream matched the bundle sidecar; AES-256 GPG output and all three local keys are owner-only mode `0600`, and streamed decrypt reproduced SHA-256 `d2321993a1858ec053c614bf6aecb212012f2dd25db59ff2fd49ed42056f418d` without another plaintext file | PASS for this WSL encrypted copy and key readability; keys remain on the same host and recurring/off-site retention is pending |
| WSL isolated MariaDB restore | Pinned MariaDB digest `be981e4113326ada8d6004174dd09eeaefc03094037f811182a52d4f2e737350` restored the 792,678-byte dump on `127.0.0.1:56889`; exact source/target schema and content inventories passed with measured RTO 1.680 seconds | PASS for one isolated restore of source `7c2764a1a16492ec1620079c8211b47287b1b3fd`; NAS production DB was unchanged, disposable lab cleanup and recurring backup remain pending |
| Restore-lab cleanup | After explicit owner authorization, both localhost lab containers and their named volumes were removed and verified absent; WSL plaintext tar/sidecar/SQL/inventory/work files were unlinked, then interactive SSH removed and verified absence of the two exact NAS owner-home export files | PASS for temporary plaintext cleanup; recovery remains possible from the mode-0600 encrypted bundle/keys or retained NAS root-only copy |
| CPU-field-free NAS attempt | Protected run `33245672804` at feature main `b6cab838` started the exact DB, passed migration `up 007` with a retained backup, created the API, then failed loopback `/ready`; cleanup removed the partial project without volumes or DB rollback, and owner recovery restored legacy `/live` HTTP 200 | PASS for CPU compatibility, migration and cleanup boundaries; FAIL for new API readiness and no production deployment claim |
| Compose file-secret access audit | Immutable API `USER 10001:10001` was paired with all local NAS `file:` secret sources at `root:root 0600`; local Compose bind mounts preserve source ownership/mode, making startup reads unavailable to the API. Candidate contract keeps the host directory `0700`, DB-root secret `root:root 0600`, and API files `root:10001 0640` | PASS for source/root-cause contract and focused tests; exact NAS metadata and live API readiness pending |
| Personal administrator secret metadata | Owner readback reports `personal_admin_password` as `-rw-r-----`, owner `root`, group `10001`, 13 bytes | PASS for the required `root:10001 0640` file-access contract only; the password value was not read or recorded |
| MQTT-port-corrected deployment preflight | Owner rerun passed bootstrap plus the read-only verifier with 14 secret contracts, exact runtime keys including retained TLS port 4883, three external volumes, migrations `002`-`007`, exact identity booleans and ACL snapshot/applied ACK `439`/`439`. Installed wrapper/dispatcher hashes are `62181892...`/`6e80dedc...`; status was `not-deployed` and both legacy containers remained running | PASS for exact NAS admission state before the separately recorded live attempt; not deployment proof |
| MQTT-port-corrected live attempt | Owner stopped exactly the retained legacy pair; run `33249202719` pulled API `a82a2b73...` and DB `2e35e1ad...`, passed migration `up 007`, and exact build `146fd7f` returned `/live` 200. `/ready` stayed 503 solely with `mqtt=false`; the wrapper retained diagnostics, removed the partial project/networks without volumes and skipped DB rollback. Owner restart restored legacy `/live` 200 with legacy MQTT true | PASS for exact build startup, migration, bounded cleanup and legacy recovery; FAIL for new MQTT/readiness. Retained root-only API-log diagnosis is required before any retry |
| DSM 24 multi-network MQTT diagnosis | Retained API logs show successful MQTTS provisioning validation followed by a synchronous subscriber `TimeoutError`, with no TLS/certificate/auth rejection. The production API is multi-homed while the working legacy API uses one ordinary bridge; DSM Docker 24/Compose 2.20 predates deterministic `gw_priority` | First internal-bridge hypothesis was incomplete: making both bridges routable did not close the Gate. Multi-homing/default-route ambiguity itself remains the bounded cause consistent with both exact failures |
| DSM route-corrected live attempt | Owner output proved exactly the retained legacy API/DB stopped, then run `33250299026` alone was approved for feature main `aebad8ef`. It pulled API `58f83948...` and DB `5ba469cf...`, passed DB health and migration `up 007`, and started the API, but loopback `/ready` timed out with the same MQTTS subscriber `TimeoutError` and bounded ACL failures. The wrapper retained root-only diagnostics, removed only the partial containers/networks without volumes and did not attempt DB rollback | PASS for exact approval, immutable pull, migration and bounded cleanup; FAIL for readiness/deployment. Owner restart restored legacy and external readback proves `/live=200`, MQTT true, with only expected `legacy_prearm_retired=false` keeping legacy `/ready=503` |
| Current connected-device inventory after retry | usbipd reports CH343 `1a86:55d3` attached and WSL exposes `/dev/ttyACM0`; a fresh nested WSL login can open it but bounded probes received zero bytes. Windows ADB now reports authorized `SM-F966N` serial `R3CY707DL7L`; installed app `1.0.0-gd9ecc87` versionCode `24401` is running and reports native GATT BLE ownership | PASS for Target USB transport and mobile ADB/app readiness only; no current Target runtime identity or backend-included `ARMED`/`OPENED`/relay evidence |
| Deterministic single-bridge candidate | Production API, DB and one-shot migrator now share exactly one routable `data` bridge; the API has no second `edge` attachment. DB port 3306 remains unpublished, the base Compose still publishes no API port, and the Synology overlay publishes API 8000 only on host loopback | Source candidate only. Focused tests, trusted policy authorization, hosted CI and live `/ready` MQTT true are required before deployment evidence |
| Exact single-bridge live attempt | Owner stopped exactly the retained legacy API/DB, then run `33251769358` deployed feature main `dbafe9d4` with immutable API `e947786a...` and DB `365d7c3f...`. The run created only the `data` bridge, passed DB health and migration `up 007`, and started the API, but loopback `/ready` timed out. Root-only runtime/API logs were retained and cleanup removed the partial project without deleting volumes or attempting DB rollback; external `/live` and `/ready` are currently 502 | PASS for exact approval, immutable pull, DB/migration/API-start and bounded cleanup; FAIL for readiness/deployment. Legacy recovery and retained-log classification are mandatory before another retry |
| Single-bridge retained diagnosis and recovery | Root-only evidence shows healthy DB, running API, and the same subscriber `TimeoutError` 5.417 seconds after startup, followed by bounded ACL publish failures; readiness requests reached the API through bridge gateway peer `192.168.0.1`. Owner restarted the exact retained legacy pair; external `/live=200` and legacy `/ready=503` again report MQTT true with only expected `legacy_prearm_retired=false` | Confirms the remaining failure is pre-CONNACK network connect, not DB/API process health. Synology host-gateway hostname override is a source candidate; no new readiness pass yet |
| Host-gateway live attempt | Owner stopped exactly the retained legacy pair, then exact run `33252726976` for feature main `7be8768` pulled API `91a22d34...` and DB `ca89ea4c...`, passed migration `up 007`, started the API and passed loopback `/ready`. The following NAS-local request to the public DSM `:4442/ready` origin exhausted its bounded retries; diagnostics were retained and the partial project was removed without volumes or DB rollback | PASS for the new stack's full internal readiness including MQTTS; FAIL for deployment because the wrapper's NAS-to-public-origin path still depended on public-IP NAT hairpin. A TLS-hostname-preserving loopback DSM-ingress probe is source-only until reviewed, deployed and externally rechecked |
| DSM loopback-ingress wrapper and transport preflight | Staged validation passed and owner readback shows exact feature-main wrapper SHA-256 `3e0fdd660316817493a5cc29e972fdcbfc90833621fb440a75bccc7875381bb5` installed as `root:root 0755`, 23,210 bytes, with status `not-deployed`. NAS-local `curl --resolve tworimpa.synology.me:4442:127.0.0.1` returned recovered legacy build `7c2764a1...`, `mqtt=true`, only expected `legacy_prearm_retired=false`, and HTTP 503 without TLS/timeout error | PASS for installed script identity and TLS-hostname-preserving DSM loopback ingress transport. Maintenance stop, exact run approval, new deployment/readiness and backend-included device E2E remain pending |
| Exact DSM-loopback deployment | Owner stopped only retained `gatekeeper-api`/`gatekeeper-db`; run `33253911475` pulled API `85040373...` and DB `96bb7aad...`, passed migration `up 007`, loopback readiness and DSM public readiness, and wrote deployed source `db37772d`. External `/live` and `/ready` are HTTP 200 with exact build and every check true. Read-only run `33254703582` artifacted the same canonical nine-line status | PASS for exact backend deployment and internal/external readiness. The original run is red only because operational apply stdout preceded the canonical record and failed a post-success byte comparison; stdout-isolation is a source candidate. Backend-included mobile/Target and physical relay evidence remain pending |
| Canonical-evidence managed redeployment | Owner installed exact wrapper `30364e7a...` with a recoverable root-only prior-wrapper backup. Run `33255038063` deployed source `d50b98f`, API `dff4fda6...`, DB `bc348186...`, passed migration `up 007`, loopback/public readiness, canonical apply/status byte equality and two-file evidence upload. Independent external `/live` and `/ready` returned HTTP 200 for `d50b98f` with every check true | PASS for the complete protected CI-to-NAS deployment system and its post-deploy evidence contract. This does not add a new physical Target actuation observation |
| Mobile remote-open exact-main deployment attempt | PR #285 merged as `a78ec0c25e0e498eb1f9f83189279cccba236236`; exact-main Hosted checks and immutable image publication passed, and the approved deployment joined Tailscale. The installed root wrapper then returned `unexpected schema version` before Compose/migration/cutover because it still admits schema 007 while the signed descriptor is 008. Source audit found the 008 readiness digest still referenced migration 007 and corrected it to actual migration-008 SHA-256 `f95e752d...e7219a8` with a cross-file regression test | PASS for fail-closed transport/signature admission and root-cause localization only; FAIL for deployment. No DB migration, new runtime readiness, mobile install or door action is claimed. Exact corrected source review/policy, root wrapper replacement and protected retry remain required |
| Mobile remote-open schema-008 deployment retry | Owner readback confirmed corrected wrapper SHA-256 `6baba70facb90eeab50fd16e9261dd5e18af6b675738d7130fbc30a659b16758` as `root:root 0755`. Protected run `33309298877` deployed exact source `07b3543a1846a1b7220c09874fb89b9e7836d7eb`, API `6f4158bb...6f512`, DB `3eeec166...be269`, migration `up 008` and its pre-migration backup. Canonical status, loopback and public readiness passed; independent strict-TLS `/live` and `/ready` returned HTTP 200 with every check true and the exact build SHA | PASS for corrected wrapper, DB migration, immutable runtime and readiness. It does not prove mobile request delivery, Target receipt, relay actuation or physical door motion |

## 2026-08-29 exact-main 293 install and framework auto-validation root cause

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact publication | Main run `33200199481` built, encrypted, signed, atomically published and HTTPS-read-back commit `c0ac5ed8b9f6cf5860a50f48e760b0cb4df78634` as `2.1.293+main.gc0ac5ed`; encrypted size/SHA-256 were `1,849,860` / `d736d9fe...b910138` | PASS for CI/NAS publication; not installation by itself |
| Starting Target | A bounded RTS reset booted installed `2.1.288+main.g40852b7`, asserted relay OFF, restored saved Wi-Fi `192.168.35.18`, MQTTS, ACL v336 and GATT | PASS for exact pre-update identity and one fail-safe service recovery |
| Signed periodic OTA | The 60-second periodic path accepted exact 293, downloaded all `1,849,860` encrypted bytes, verified the inactive image and software-rebooted | PASS for signed manifest, encrypted transport, inactive validation and boot selection |
| Exact post-update runtime | The next banner was `2.1.293+main.gc0ac5ed`; relay remained OFF and Wi-Fi, MQTTS, ACL v337, GATT/iBeacon and the later `already current` check all returned | PASS for install, reboot, exact identity and bounded runtime recovery |
| OTA state readback | Read-only `0xe000..0xffff` flash readback showed both selection records already `VALID`; no application health-window/valid-mark trace occurred | FAIL for application-gated health acceptance; successful boot did not exercise `OtaHealthPolicy` |
| Bootloader identity | The installed 20,976-byte bootloader SHA-256 `646f5c63...b3a5b92f` was byte-identical to the pinned local pioarduino production bootloader, whose ESP32-C6 sdkconfig enables bootloader/app rollback | PASS for exact bootloader identity; disproves a missing rollback-enabled bootloader byte |
| Root cause | pioarduino `initArduino()` runs before `setup()` and its weak defaults `verifyRollbackLater() == false`, `verifyOta() == true` immediately mark `PENDING_VERIFY` valid | CONFIRMED source/runtime explanation for #172; app health policy is bypassed |
| Candidate fix | `OtaManager.cpp` now defines a strong C-linkage `verifyRollbackLater()` returning true and compile-fails without `CONFIG_APP_ROLLBACK_ENABLE`; local ELF exposes strong `T verifyRollbackLater` and the production N16 build passes | PASS for local source/build only; a newer merged signed OTA must prove health-window start and explicit valid mark |

No flash write occurred during bootloader/OTA-data readback. The two read-only
esptool sessions reset the board, so they are runtime perturbations rather than
passive telemetry. Automatic rollback fault injection, relay contacts/load,
actual door motion and AJ-SR04T threshold remain unproven.

## 2026-08-29 exact-main 295 pending boot and connected rollback

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact publication | Run `33203136822` published actual feature main `a2f7ae2fc4bd1f4fa19839e1021d18cce85ad4fc` as signed/encrypted `2.1.295+main.ga2f7ae2`; public metadata and sanitized evidence agree on 1,849,876 bytes and SHA-256 `fe88c23a...f7df5809` | PASS for exact-main CI/NAS publication and HTTPS readback |
| Pending application boot | Installed 293 accepted 295, verified the inactive image and booted exact 295 with `[OTA] pending image health window started`; relay stayed OFF and Wi-Fi, MQTTS, ACL v342 and GATT/iBeacon returned | PASS for deferred application health ownership and bounded service recovery |
| Automatic rollback injection | Closing the bounded USB observer changed the serial line state and reset the Target before application VALID marking; the rollback-enabled bootloader selected previous VALID `2.1.293+main.gc0ac5ed` and relay-OFF, Wi-Fi, MQTTS, ACL and GATT/iBeacon recovered | PASS for connected pre-VALID reset and automatic previous-slot rollback; not a power-removal test |
| Anti-replay after rollback | The next periodic check rejected the same signed 295 manifest as `downgrade`, consistent with the durable highest-seen-version contract | PASS for same-version replay refusal; normal VALID proof requires a strictly newer artifact |

This closes issue #172's connected automatic rollback injection path. A newer
exact-main artifact must still remain healthy through the complete application
window and emit the explicit VALID mark. Relay contacts/load, door motion,
AJ-SR04T threshold and hard power-loss remain separate physical Gates.

## 2026-08-29 exact-main 296 health-to-VALID acceptance

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Strictly newer publication | Run `33204658431` published final-policy main `21c5d560a82a633831ed40e600cdcf5aad59688f` as signed/encrypted `2.1.296+main.g21c5d56`; manifest and sanitized evidence agree on 1,849,876 bytes and SHA-256 `007de3ea...bcdeeecf` | PASS for exact-main CI/NAS publication and HTTPS readback |
| Pending health path | VALID 293 accepted 296, verified the inactive image and booted exact 296 with `pending image health window started`; relay stayed OFF and Wi-Fi, MQTTS, ACL v347 and GATT/iBeacon returned | PASS for deferred application health ownership and all configured runtime predicates |
| Explicit acceptance | The uninterrupted observer captured `running image marked VALID after health window` | PASS for application-controlled stable window and OTA VALID marking |
| Post-VALID persistence | A deliberate reboot selected exact 296 without another pending window; relay OFF, Wi-Fi `192.168.35.18`, MQTTS, ACL v348 and GATT/iBeacon recovered | PASS for durable boot selection and one bounded post-acceptance recovery |

Together with the separate 295 pre-VALID rollback trial, issue #172 acceptance
is complete. No factory erase or partition-layout change occurred. Hard power
removal, relay contact/load, actual door motion and AJ-SR04T threshold remain
separate physical Gates.

## 2026-08-29 exact-main 301 action-1 followed by action-2 acceptance

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Target publication/install | Run `33212529200` published exact `f352a78db6870339c8e59f75e28fce0e3c327a07` as signed/encrypted `2.1.301+main.gf352a78`; connected 298 accepted and verified it, booted the pending slot, restored relay OFF/Wi-Fi/MQTTS/ACL v365/GATT and explicitly marked the image VALID | PASS for exact-main production OTA and bounded service recovery |
| Mobile publication/install | Run `33212529199` published matching `1.0.0-gf352a78` / 24101 to both HTTPS paths. Size 55,786,649, SHA-256 `051a442a...fe03495`, embedded commit and signer certificate `8bdbcf86...e1d7ba0` matched before replacement install; first-install time remained 2026-07-29 | PASS for exact artifact identity, signing continuity and state-preserving install |
| Fresh action 1 | Target reboot advertising produced a native OS beacon callback at 06:46:23, authenticated GATT writes/indications and WorkManager success at 06:46:28 | PASS for one foreground-visible native beacon action-1 completion; the Target's 60-second sensor ARMED window is established by the authenticated action contract |
| ARMED replacement by action 2 | Dashboard action 2 started at 06:46:50, 22 seconds after action-1 completion. A separate authenticated GATT session completed and UI returned `문이 열렸습니다 (4530ms)` instead of `PROTOCOL_INCOMPATIBLE` or `TARGET_BUSY` | PASS for the exact incident ordering and terminal mobile result |
| Target relay command | During the action-2 session serial recorded `릴레이 ON 상태로 변경 완료`, then timer-bound `릴레이 OFF 상태로 변경 완료` without reset | PASS for Target FSM/GPIO command and fail-safe timer output; not electrical contact/load proof |
| Physical boundary | No contact voltage/current, attached actuator, actual door movement, AJ-SR04T threshold or repeated latency distribution was measured | PENDING physical and SLO acceptance |

Issue #197 is closed with the exact connected evidence. The software/core
path now passes the ordering that previously failed, while physical actuation
and sensor acceptance remain explicitly separate.

## 2026-08-29 deployed-backend included core-use-case repetition

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Backend production precondition | Exact source `db37772de5a3f18be7bcaa73170933ab18442475` is `status=deployed`; external `/live` and `/ready` returned HTTP 200 with all checks true, and read-only run `33254703582` retained the canonical status artifact | PASS for deployed backend, DB/schema, MQTTS, auth/ACL, legacy retirement and build identity |
| Connected inventory | Windows ADB authorized Fold7 `SM-F966N` serial `R3CY707DL7L`; installed production-signed app is `1.0.0-gd9ecc87` / 24401. CH343 is attached as WSL `/dev/ttyACM0`, and a fresh nested WSL login activated its configured `dialout` membership | PASS for current mobile/serial transport identity |
| Fresh native action 1 | After a bounded app process restart, OS native wake connected to `SmartGatekeeper`, completed authenticated characteristic writes/indications, and WorkManager returned `SUCCESS`. Dashboard showed `HEALTHY`, owner `native_gatt`, hands-free `READY`, and `Presence → dispatch/ARMED` 44 / 4509 ms | PASS for one current action-1 terminal ARM in the deployed-backend test window |
| ARMED replacement by action 2 | About 47 seconds after action-1 completion, the dashboard terminal action-2 button completed a separate GATT session and displayed `문이 열렸습니다 (4909ms)` | PASS for current authenticated action-2 `OPENED` within the 60-second ARMED window |
| Target relay command | Independent serial observation recorded a second accepted GATT connection, `릴레이 ON 상태로 변경 완료`, then timer-bound `릴레이 OFF 상태로 변경 완료` without reset | PASS for Target FSM/GPIO command and fail-safe timer cutoff |
| Physical boundary | No contact voltage/current, attached actuator, actual door motion, AJ-SR04T threshold or repeated latency distribution was measured | PENDING physical actuation, sensor and SLO acceptance; no physical-open claim |

This repetition closes the requested backend-included software/core loop across
the deployed NAS backend, current Fold7 app and connected Target. Local GATT
does not perform a backend request per tap by design; the backend contribution
is the deployed ready control/ACL plane and the approved app state visible in
the same acceptance window. Physical actuation remains a separate owner-observed
Gate.

## 2026-08-30 exact-main mobile/Target connected acceptance without sensors

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Connected identities | Windows ADB authorized Fold7 `SM-F966N` on Android 16/API 36. A fresh WSL login opened CH343 `/dev/ttyACM0`; esptool identified an ESP32-C6 revision 0.2. Target booted `2.1.364+main.g89164ce` and the installed mobile app initially reported `1.0.0-gbd3a27b` / 30301 | PASS for exact device transports and pre-update runtime identities; no sensor/contact evidence |
| Mobile signed replacement | Public metadata named `1.0.0-g89164ce` / 31501 at exact commit `89164ce4eb43f6deba8667bf9db6926fcfedfe46`. The 56,134,809-byte APK matched metadata SHA-256 and its signer certificate matched the installed app before `adb install -r`; replacement returned `Success`, preserved first-install time and app data, and retained required BLE/location/notification permissions | PASS for production-signed same-signer replacement and credential/data preservation |
| Target boot and control plane | Relay fail-safe OFF ran before application start; saved Wi-Fi returned at `192.168.35.18`, exact per-Target MQTTS subscribed, signed ACL v539 applied, and GATT/iBeacon started. Strict-TLS backend `/live` and `/ready` independently returned HTTP 200 at build `8ea9ff1f8177bf49dba524b11d586715af5e1f6b` with every readiness check true | PASS for one bounded Target/backend runtime window |
| Foreground action 1 | The exact app observed Target RSSI -52, completed authenticated GATT, reported `SUCCEEDED · ARMED 1726 ms`, worker `HEALTHY`, MTU 256, and 1669 ms last GATT latency. Activity rendered `출입 준비 완료 · 센서 접근 대기`, not physical-open confirmation | PASS for one mobile-to-Target sensor-arm result; ultrasonic trigger and relay remain unexercised |
| Manual action 2 | `1-Tap 수동 로컬 개방` completed in 1846 ms. Independent CH343 serial recorded a GATT connection, relay-command ON completion and timer-bound OFF completion | PASS for authenticated Target FSM/GPIO command and fail-safe cutoff; the app's `문이 열렸습니다` text is not physical evidence and is misleading while no relay module/door is attached |
| Screen-off automatic detection | With the app backgrounded and display non-interactive, a Target reset/re-advertisement produced a native `FIRST_MATCH` at RSSI -54 with `screen_interactive=false` and 35.65 ms callback latency. The exact app's GATT Worker returned `SUCCESS` about 1.9 seconds later and posted the result notification | PASS for one screen-off/background auto-detect-to-GATT completion on this Fold7 |
| Process-death boundary | Android retained the app PID because its foreground service was active; `am kill` did not reclaim it, and the shell was not authorized to stop the non-exported service. No force-stop was used because that intentionally disables wake registration | PENDING ordinary process-absent cold-wake repetition; screen-off success is not process-death proof |
| OTA failure/rollback | Public Target metadata was newer at `2.1.365+main.g95355c2`. A pending image later logged `health window timed out; rolling back`; boot returned to valid `2.1.364+main.g89164ce` with relay OFF. Saved Wi-Fi initially failed with `AUTH_EXPIRE`/`NO_AP_FOUND`, then the bounded AP+STA recovery restored `192.168.35.18`, MQTTS, ACL v541 and GATT/iBeacon. The periodic check rejected the same manifest as `downgrade`, matching the durable highest-seen-version contract | PASS for prior-slot automatic rollback, relay fail-safe and eventual network/control-plane recovery. The candidate boot identity was not directly captured, and no newer image reached explicit health VALID in this session |
| Missing hardware boundary | AJ-SR04T, ECHO-level protection, relay module/contact/load, actuator and door were not connected | PENDING distance threshold, electrical timing, actual door motion, repeated SLO, hard power-loss and complete wall-install acceptance |

This session accepts the currently installed mobile and Target software path for
foreground action 1, manual action 2 and one screen-off action-1 repetition. It
also directly exercises automatic Target rollback and eventual network recovery.
It does not claim that a pocket approach opens a physical door, because the
distance sensor, relay contact/load and door actuator were absent. The manual
success copy must be treated as a product wording defect until it distinguishes
an authenticated command from independently confirmed physical opening.

## 2026-08-30 GPIO23 relay source-restoration candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Authoritative pin contract | `include/config.h` defines AJ-SR04T TRIG/ECHO as GPIO10/11 and the single Active-Low, High-Z-OFF relay input as GPIO23 | PASS for source contract; this does not measure the installed Target |
| Contract validation | Manual/physical-plan unit tests passed 23/23; the pending evidence template validated and the forged-pass self-test was rejected | PASS for deterministic L0/L1 contract checks only |
| Personal production build | `esp32c6_personal_production` built with pinned pioarduino; 1,783,096/7,340,032 bytes Flash (24.3%) and 67,096/327,680 bytes RAM (20.5%) | PASS for local compile and dual-slot image fit |
| Physical boundary | No GPIO11 ECHO voltage, GPIO23 input/contact/load, AJ-SR04T distance, actuator movement or door opening was measured in this source/build step | PENDING exact-main signed OTA install/health and on-wall physical acceptance |

The source change intentionally retains the existing one-shot FSM, Active-Low
polarity, High-Z OFF behavior, signed OTA verification and rollback contract.
It does not add SmartBox GPIO4/5/6 compatibility or modify the wall wiring.

## 2026-08-31 Local GATT ultrasonic session-isolation candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Session reset contract | An accepted Local GATT action-1 now clears the five-slot ultrasonic median history before the next sensor loop. The reset is not applied to action-2 or a rejected arm request | PASS for source-level session separation; no Target runtime observation |
| Fresh-sample threshold | The reset seeds five invalid sentinels and index zero, so the relay predicate cannot become true until at least three fresh, current-session distance samples are valid | PASS for deterministic host regression; this is not GPIO/echo evidence |
| Focused regressions | New session-isolation regressions plus existing pocket-path tests passed 8/8 | PASS for the targeted source contract |
| Hardwareless RC regressions | The complete Hardwareless RC host suite passed 13/13, including the C++ protocol/FSM build and execution | PASS for host software behavior only |
| Integrated focused suite | `test_ultrasonic_session_isolation`, `test_pocket_approach_contract`, `test_target_ota_autopublish` and `test_hardwareless_rc` passed together 39/39 | PASS for their combined host/source contracts; no OTA publication or device action occurred |
| ESP32-C6 build | `.venv/bin/pio run -e esp32c6` completed successfully. RAM was 59,200/327,680 bytes (18.1%); application flash was 1,745,602/7,340,032 bytes (23.8%) | PASS for local compile, capacity and image fit; not a signed production artifact or installed image |
| Personal-production build | `.venv/bin/pio run -e esp32c6_personal_production` completed successfully. RAM was 67,096/327,680 bytes (20.5%); application flash was 1,783,164/7,340,032 bytes (24.3%) | PASS for the local production-profile compile and dual-slot image fit; not signing, publication or Target installation evidence |
| Repository regression | The full Python discovery ran 324 tests: 322 passed, one skipped, and only the expected trusted-workflow-policy test failed because the changed protected `deploy.yml` digest has not yet been authorized | SOURCE TESTS PASS / POLICY GATE OPEN; the fail-closed result must be resolved by normal policy rotation before merge |
| Field causation boundary | The five-slot stale-median pattern deterministically fits the owner-correlated HA sequence after the owner ruled out manual remote open and requested analysis under the assumption of intact wiring and sensor hardware | HIGH-CONFIDENCE source/timeline correlation, not canonical per-session event proof |
| Release boundary | No protected CI, merge, signed Target OTA publication, Target download/install/reboot/health confirmation, fresh sensor distance, relay contact or physical door cycle was performed by these local tests | PENDING all release and physical acceptance Gates |

The correction is deliberately limited to the start of a successfully accepted
Local GATT action-1 sensor session. It does not weaken signed ACL/proof,
nonce/replay, action-2, relay cooldown, OTA signature, health or rollback
contracts. A signed exact-main artifact must still be installed and observed on
the wall Target, followed by a fresh hands-free approach in which three current
distance samples precede relay activation.

## 2026-09-02 access-critical MQTT deferral exact-main installation

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact merge and publication | Policy PR #329 and feature PR #330 passed normal protection. Exact main `e62b681fe9f4ce52e5e5bdb1a795ef6a3ac532d0` run `33529692563` built, encrypted, signed, atomically published and strict-HTTPS-read-back `2.1.418+main.ge62b681`; encrypted/plaintext sizes were 1,855,492 / 1,855,456 bytes | PASS for reviewed exact-main artifact publication |
| Safe preflight | The installed Target reported `2.1.413+main.ga9f72fa`, boot count 685, boot ID `aee54f1d43fca05ea611cdd1b303296b`, IDLE, unarmed, relay command OFF, pin high and RSSI -56 dBm | PASS for bounded pre-install safe state |
| Signed OTA trigger | The Home Assistant bridge accepted one `trigger_ota` request and Backend published signed boot-bound `ota_check` session `c9da763106b798d919dd42ac1af7724d`. No duplicate request was sent when the synchronous OTA path rebooted before ACK | PASS for one Backend-signed install trigger; ACK absence alone is not install evidence |
| Installed runtime | Target status advanced to exact `2.1.418+main.ge62b681`, boot count 686 and new boot ID `5400d2f178eed725f6f5f3caa252bceb`; it remained IDLE, unarmed, relay OFF/pin high with status age below three seconds for a continuous 30-second verification window | PASS for install, reboot, exact identity and bounded healthy runtime |
| Behavioral boundary | No fresh wife-phone approach, sensor-to-relay latency sample, GPIO voltage/contact measurement or physical door travel was performed in this installation window | PENDING repeated on-wall latency and physical acceptance |

The OTA used the existing inactive-slot signed path and did not erase NVS or
the previous bootable slot. Status evidence establishes the new runtime and
fail-safe output; it does not by itself prove that the reported seven-second
ARMED-to-sensor delay is physically eliminated.

## 2026-09-02 Home Assistant connectivity entity production deployment

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Owner approval and protected deployment | The owner approved the sole pending `production` environment request for run `33529692517`. Exact source `e62b681fe9f4ce52e5e5bdb1a795ef6a3ac532d0` completed Backend security, evidence verification, immutable image publication and `deploy_backend_to_nas` successfully | PASS for approved NAS Backend deployment |
| External runtime identity | Strict public TLS requests to `/live` and `/ready` returned build SHA `e62b681fe9f4ce52e5e5bdb1a795ef6a3ac532d0`; readiness reported database, schema, MQTT, event collector, runtime secrets, control/admin authentication, ACL management, legacy prearm retirement and build identity all true | PASS for exact deployed process and dependency readiness |
| Retained HA discovery | A strict-TLS MQTTS subscriber received retained QoS-1 `homeassistant/binary_sensor/smart_gatekeeper_01/connectivity/config`. It names `[Gatekeeper] 연결 상태`, uses unique ID `smart_gatekeeper_01_connectivity`, `device_class=connectivity`, and maps `online/offline` from `gatekeeper/v1/ha-bridge/c0feffe6ebac/availability` | PASS for live discovery publication and stable HA entity identity |
| Current bridge state | The discovery config deliberately has no self-referential `availability_topic` and no `expire_after`; the referenced bridge availability topic delivered retained QoS-1 payload `online` | PASS for current Backend-to-HA connectivity state and visible offline semantics |
| Display and physical boundary | No Home Assistant frontend screenshot, entity-registry row, dashboard card placement, sensor approach, relay contact or physical door movement was observed in this verification | PENDING only visible dashboard placement and physical behavior; broker evidence proves the HA discovery input, not the rendered card |

The connectivity entity is now available to Home Assistant through its normal
MQTT discovery path and continuously represents the Backend bridge's retained
online/offline state. A browser refresh or MQTT integration entity reload may
be needed before a previously open dashboard view displays the newly discovered
entity.

## 2026-09-02 authenticated actor and post-ARM completion candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Cross-language evidence contract | Target and Backend implement domain-separated fixed binary inputs for credential ref, event MAC and status MAC, with deterministic vectors and strict key/key-ID parsing. Raw credential/name/unit/proof material is excluded from the MQTT evidence envelope | SOURCE CONTRACT PRESENT; this is not live secret provisioning, broker identity or NAS ingestion evidence |
| Target evidence path | Signed schema 1.1 events carry boot count and optional session actor ref; signed status carries monotonic revision, FSM/relay state and latest terminal phase mask. Event/status production uses the existing bounded outbox and safe-state single MQTT owner rather than socket writes in the GATT/sensor/relay critical phase | SOURCE/HOST CONTRACT; a reviewed exact-main build, install, reboot, status readback and outage soak are separate Gates |
| Durable compatibility | The deployed 368-byte offline event ABI is preserved with a v2 overlay marker that an N-1 reader ignores. New readers recover the actor/tag overlay without changing record offsets | N/N-1 SOURCE CONTRACT; an actual N→N-1 rollback with queued authenticated records remains a connected acceptance Gate |
| Durable overflow and wrapped-ring recovery | A full eight-record queue replaces the two oldest records with one noncanonical `queue_overflow` diagnostic plus the incoming record. Host recovery restored all eight records without torn recovery and drained through the following event. A separate full→pop→wrapped-push→reboot→pop→reboot case preserved physical ring indices, did not replay the second event, and drained the wrapped tail exactly once; the gap carries no fabricated access UUID or HMAC | HOST PASS for queue/repeated-reboot logic; sustained connected Target outage, NVS wear and real power interruption remain physical/runtime Gates |
| Backend integrity and actor projection | New live trust requires signed event/status, exact Target/door, boot/revision high-water and unique credential-ref match. Exact replay cannot refresh live age; legacy unsigned rows are separate. Stable Target ID owns security correlation while opaque collector/session refs remain presentation values | SOURCE/DB CONTRACT; the final schema migration and complete Backend/MariaDB regression must pass at the reviewed candidate SHA before deployment |
| Mobile exact-session display | Native code signs the exact Target UUIDv4 session with a 20-second, fixed 80-byte AndroidKeyStore read proof. Flutter polling is bounded to 4-second intervals and 120 seconds, uses typed stop/backoff rules, and renders armed, relay, cooldown, complete/terminated separately | SOURCE/HOST CONTRACT; no matching APK was installed and no wife's-phone post-ARM/next-auth timing was measured in this entry |
| Home Assistant trust split | Access state/door/pre-armed discovery points at Backend `verified-status`, whose payload contains only HMAC-covered allow-listed fields. Raw Target status remains for diagnostics/config and requires the HA broker principal's exact read ACL | SOURCE CONTRACT; repository ACL text is not live Mosquitto installation or HA retained/readback evidence |
| Terminal power-loss boundary | Same-boot RAM terminal summary can preserve a complete phase mask after individual QoS 0 event loss once Backend receives it. Power loss before that signed status can lose the summary and must leave the outcome unconfirmed | EXPECTED BEST-EFFORT BOUNDARY; hard power interruption around terminal publish remains untested |
| Relay completion/failsafe arbitration | The one-second esp-timer cutoff is recorded as normal `door_close` plus successful completion. Only a missed timer/FSM transition beyond an additional 250 ms records `door_close_failsafe` plus `session_terminated_failsafe`; both paths drive relay OFF exactly once and the true failsafe projects as failed rather than sensor-complete | PASS for source order and native host FSM regression; no installed-Target timer latency, GPIO voltage/contact or physical door result |
| Verified-session preemption rejection | With A verified and sensor-waiting in `ARMED`, adversarial B ClientHello is rejected busy before challenge/proof. A subsequent invalid B proof is not verified and cannot change A's original 60-second deadline, actor reference, phase mask or A-scoped causal parent; A still reaches sensor, relay ON/OFF, terminal phase `0x1f`, cooldown and fresh IDLE. New authentication remains rejected in `AUTH_PENDING`, `ARMED`, `RELAY_HOLD` and `COOLDOWN` and is accepted only at fresh IDLE/relay OFF | PASS for integrated native ProtocolCore/FSM/lifecycle regression; no second phone or installed Target was exercised |
| Focused fail-closed regressions | `test_hardwareless_rc` and `test_access_control_network_deferral` passed 25/25. The broader five-module security/personal-install/OTA command ran 57 tests: 56 passed and only the expected protected-source digest assertion failed because the source freeze hash has not yet been rotated | SOURCE TESTS PASS / POLICY ROTATION OPEN; protected workflow policy and exact hash rows were not edited |
| Personal-production build after fail-closed correction | `.venv/bin/pio run -e esp32c6_personal_production` succeeded at 75,848/327,680 bytes RAM (23.1%) and 1,798,862/7,340,032 bytes application flash (24.5%) | PASS for local compile and dual-slot fit; not signed publication, Target install/reboot/health or physical action |
| Physical result boundary | A complete phase mask proves Target proof→ARMED→sensor→relay ON→relay OFF software stages and fresh IDLE can prove next-auth readiness | NO PHYSICAL-DOOR CLAIM: there is no independent door-contact sensor, and this entry measures no GPIO voltage/contact, actuator travel or door leaf movement |

Safe connected validation is ordered Target N publication/install/reboot/health,
then Backend N schema/runtime and signed status ingestion, then mobile N
replacement install and one exact-session sensor/relay cycle. The same evidence
key/key ID must be present in both Target release environments and the NAS
keyring before Target N is built. Broker anonymous/crossover denial and
legitimate Target/Backend/HA reconnect/readback are release prerequisites, not
an inference from application HMAC tests.

## 2026-09-02 HA verified access-state availability deployment

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Protected merge | PRs #335, #336 and #337 passed their required checks and merged normally. Exact feature main is `993c1b6097992bce9fc4f7791a3033f9a34c7f9e`; final policy main `6530d5ca7facf0faee82d4b2944e7ddd65986047` pins the sole `current-main-baseline` with all 100 protected blobs unchanged from feature main | PASS for reviewed exact source and final policy identity |
| Exact Backend deployment | Owner-approved run `33642436897` passed Backend security/MariaDB, evidence verification, immutable API/DB image publication and NAS deployment. Public `/live` and `/ready` returned HTTP 200 for exact `993c1b6`; every readiness check was true | PASS for exact deployed process and dependency readiness |
| Retained discovery correction | Strict-TLS MQTTS read back retained configs for verified `state`, `door_binary` and `pre_armed`. Each points to `gatekeeper/v1/ha-bridge/c0feffe6ebac/verified-status` and omits `expire_after`; raw diagnostic expiry remains source-tested at 30 seconds | PASS for live retained input that removes the false 30-second HA entity expiry |
| Bridge and Target state | Retained bridge availability was `online`; a fresh non-retained verified projection reported boot 695, revision 29189, `IDLE`, unarmed and relay OFF/pin 1 | PASS for current signed projection and fail-safe output command; no relay-contact/door motion implied |
| Rendered and physical boundary | No authenticated HA frontend entity-registry read, over-30-second UI observation, new administrator history row, sensor passage, GPIO/contact measurement or door-leaf observation was performed after this deployment | PENDING one new family-phone access and rendered UI/physical acceptance |

## 2026-09-02 mobile transient access-ready notification candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Stale-notification diagnosis | Native `출입 준비 완료` used one fixed notification ID and `setAutoCancel(true)` only; no timeout, region-exit cancellation or exact-session terminal cancellation existed | CONFIRMED source cause for a notice surviving until user interaction; not an OEM runtime trace |
| Bounded fallback | The access-ready policy now supplies 65,000 ms to `NotificationCompat.setTimeoutAfter`, covering the Target's 60-second ARMED window plus delivery grace; attention-required failure notices remain unbounded under a separate notification ID | SOURCE CONTRACT; Android/OEM delivery must be observed on replacement APK |
| Area exit | PendingIntent scan requests `FIRST_MATCH | MATCH_LOST`; valid match-lost dismisses the ready notice and does not invoke `BleGattWorkScheduler.onPresence`. Error callbacks do not infer exit | SOURCE CONTRACT; physical exit latency and OEM callback reliability pending |
| Normal/terminal result | Exact-session polling dismissal runs only after the active Target session generation closes, including terminal result and bounded expiry | SOURCE CONTRACT; live Backend/mobile session result observation pending |
| Local regression suites | Flutter analysis reported no issues; Flutter tests passed 97/97; Android targeted JVM tests passed 60/60; repository contracts passed 342/342 with one declared skip; `git diff --check` passed | PASS for local source/unit/contract evidence; hosted exact-head and physical behavior remain pending |
| Safety boundary | No Target, Backend, HA, sensor, relay or door control semantics change | PASS by changed-file scope; signed publication/install and physical behavior remain pending |

## 2026-09-02 authenticated actor/result final-main rollout evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Normal merge and final policy | PRs #332, #333 and #334 were normal merge commits. Final `main` is `10d7a1f2e38ed467143db05d5662ae24d575eda5`; its sole policy bundle is `current-main-baseline`, and all 100 protected runtime blobs match immutable feature `23e28e14cf79e618070d0ea3543bf92910ca9558` | PASS for reviewed source and final policy identity; no deployment implied |
| Exact Target publication | Run `33555893409` built and published `2.1.422+main.g10d7a1f`, build ID `main-422-10d7a1f2e38ed467143db05d5662ae24d575eda5`. CI and independent HTTPS readback verified signed schema v2, immutable 1,867,636-byte ciphertext, Ed25519, AES-GCM and plaintext SHA | PASS for exact artifact publication and cryptographic readback |
| Exact mobile publication | Run `33555893523` signed and atomically published `1.0.0-g10d7a1f` / `38501` to primary and fallback roots with exact HTTPS readback and previous-valid preservation | PASS for OTA publication; no phone replacement install or wife's-phone rendering evidence |
| Target pre-install safety | Fresh status at 05:47 KST showed installed `2.1.419+main.g7981498`, boot 690, `IDLE`, unarmed, relay OFF/pin 1 and cooldown 5000 ms | PASS for safe preflight only; this proves the new firmware was not installed at that time |
| Authenticated local recovery reachability | The first `/recovery/enable-ap` request could not complete a TCP/80 handshake from WSL or Windows. There was no HTTP code, manifest transfer or firmware upload; no retry was sent. Fresh readback kept old firmware/boot and safe relay state | FAIL for station-local recovery reachability, SAFE NO-CHANGE for Target. Periodic signed HTTPS OTA remains the recovery path |
| Periodic OTA install and stability | At 2026-09-02 22:35 KST, two fresh non-retained samples showed installed `2.1.422+main.g10d7a1f`, boot count 695, a new boot ID and uptime above 26,042 seconds and increasing. Both were `IDLE`, unarmed, relay command OFF/pin 1 and carried signed access status with key ID `a1` | PASS for exact Target install, reboot and long post-boot safe runtime; no sensor/relay/door measurement implied |
| Owner multi-phone access observation | The owner reported that both the wife's and daughter's phones could now enter, and assessed the asynchronous change as working | OWNER-OBSERVED FUNCTIONAL PASS; phone APK identities, instrumented timing, GPIO/contact and door-leaf motion were not independently captured |
| Backend and HA runtime diagnosis | Public Backend remained old build `e62b681fe9f4ce52e5e5bdb1a795ef6a3ac532d0`; `/ready` was HTTP 503 solely because `access_event_collector=false`. The supplied HA history alternated `IDLE` and unavailable with about 31-second unavailable windows. The new Target's access-critical MQTT deferral exposed a remaining 30-second `expire_after` on access-state discovery; source now removes it from verified state/relay/pre-arm entities and relies on the retained 90.25-second bridge watchdog. Backend N also contains signed deferred-event collection | FAIL for live access-history/HA projection; reviewed Backend deployment, root-owned evidence keyring/runtime, retained discovery republish, broker ACL and HA readback remain required |
| Backend N attempted deployment and recovery | Owner-approved run `33555467447` passed hosted tests, evidence verification and image publication, migrated to schema 012, then failed API creation because root-owned `secrets/access_event_ref_keys.json` was absent. The partial stack was removed without deleting volumes and a pre-migration backup was retained. Public endpoints returned 502 until the last verified `e62b681` deploy job was rerun; rollback then passed private/public readiness, and `/live` plus `/ready` returned 200 with exact `e62b681` and `access_event_collector=true` | FAIL for Backend N due exact missing root key file; PASS for emergency service recovery. Do not retry N before root provisioning/read-only verification |
| Backend N final deployment | After the owner provisioned the root `a1` keyring/runtime and installed reviewed wrapper SHA-256 `ec7e7eaa...9806`, run `33555467447` deployed exact `b29cb2497c4adf151b3d60eeab31acb525555340`. Public `/live` and `/ready` returned 200 with database, schema, MQTT, event collector, runtime secrets, admin/ACL, actor-ref and evidence-integrity checks all true | PASS for exact Backend N deployment and dependency readiness |
| Signed Target key agreement and HA readback | Read-only MQTTS received retained bridge `online` plus non-retained Backend `verified-status` for Target boot 695/revision 27868, IDLE and relay OFF/pin 1. The projection is emitted only after HMAC verification with the configured door scope, proving NAS and installed Target key agreement for ID `a1`. Retained state discovery pointed at `verified-status` but still carried `expire_after: 30` | PASS for live signed-status ingestion/key agreement and bridge publication; FAIL remains for false 30-second entity expiry until the tested source correction is reviewed/deployed/republished |
| Physical access | No agent-controlled sensor passage, GPIO/contact measurement, actuator travel or door-leaf measurement was performed | PENDING; owner observation is not an instrumented physical acceptance result |

## 2026-09-03 asynchronous MQTT per-access HA Activity candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Repeated physical observation | The owner reports that a manual local open at about 01:00 KST opened the door, while the HA state entity added no new Activity timestamp or row | OWNER-OBSERVED door-cycle pass and CONFIRMED HA visibility defect; no agent-controlled GPIO/contact trace |
| Root cause | Target intentionally defers MQTT throughout the access-critical interval and coalesces status to the newest snapshot. HA rendered only `state`, so the final `IDLE` matched the previous `IDLE` | CONFIRMED by source; the missing HA row is not evidence that the relay failed |
| Asynchronous correction | Backend derives a privacy-safe `<boot_count>-<terminal_sequence>` marker and `SUCCEEDED`/`TERMINATED` from HMAC-verified terminal status. New `[Gatekeeper] 최근 출입 결과` discovery renders that pair as its state | DEPLOYED SOURCE: every terminal session changes HA state once without adding MQTT socket work to authentication/sensor/relay/cooldown |
| Privacy and duplication | Session UUID, credential/actor ref, reason and HMAC tag stay outside HA projection. Repeated periodic snapshots of the same terminal marker render the same state | PASS by focused projection/discovery tests; no personal identifier exposure or periodic Activity spam |
| Focused regression | Home Assistant bridge, authenticated status registry, discovery migration and access-network-deferral suites passed 59/59 | PASS for local source contracts; one new physical Activity observation remains pending |
| Full regression | Backend passed 194 tests with two declared skips. After policy rotation, repository discovery passed 342/342 with one declared environment-only skip | PASS for functional, security, OTA and trusted-policy contracts |
| Release scope | No Target, mobile, GPIO, relay, sensor, ACL, command or OTA code changes | Backend/HA-only candidate; installed Target `2.1.422` remains protocol-compatible |
| Normal merge | Policy PR #340, feature PR #341 and final-policy PR #342 passed hosted checks and merge-committed normally. Exact feature main is `a87ef21dc9f66b227831066f45fab8cf0176a0e7`; final policy pins that main with all 100 protected blobs exact | PASS for reviewed source, merge ancestry and final policy identity |
| Exact Backend deployment | Owner-approved run `33654112042` passed Backend security/MariaDB, evidence verification, immutable image publication and NAS deployment. Deployment evidence records `status=deployed`, the exact feature SHA, loopback readiness and public readiness passed | PASS for exact NAS rollout |
| Independent public readiness | Strict-TLS `/live` and `/ready` returned HTTP 200 with build SHA `a87ef21dc9f66b227831066f45fab8cf0176a0e7`; all checks were true, including MQTT and `access_event_collector` | PASS for deployed process and dependency readiness |
| Discovery and physical boundary | Backend startup republishes the 17-entity retained discovery plan including `last_access_event` by source contract. No credentialed retained broker readback or post-deployment owner access/HA Activity row was observed in this verification | PENDING live retained discovery readback and one new owner-observed HA Activity timestamp; no physical door claim inferred from readiness |

## 2026-09-03 signed MQTT manual/arm terminal completion candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Supplied administrator evidence | At 01:31:26 the only new row was `MOBILE_REMOTE`, actor `이승환 · 401호`, `서버 전송 접수`, `broker accepted; physical result unconfirmed`; no Target terminal row followed | CONFIRMED signed MQTT completion-evidence gap; the owner separately reports the door opened |
| Supplied HA evidence | The Activity panel contained only older IDLE/unavailable state rows and no `[Gatekeeper] 최근 출입 결과` row for the manual request | CONFIRMED deployed Backend-only marker did not cover signed MQTT manual completion |
| Source root cause | Existing `LocalGattLifecycleBridge` created terminal summaries only after verified Local GATT proof. Signed MQTT command callback retained no session lifecycle through relay OFF | CONFIRMED by source inspection |
| Async correction | Signed command callback starts only an in-RAM session/mode tracker; FSM callbacks add phase bits without network I/O; IDLE safe-state MQTT owner later sends the existing HMAC status terminal summary | SOURCE CONTRACT preserves access-critical MQTT deferral |
| Path/result projection | Backend recognizes exact success masks local sensor/manual `0x1f/0x19` and signed arm/manual `0x1e/0x18`; admin labels remote summaries `모바일 출입 준비`/`모바일 수동 문열기` and HA advances on boot/terminal sequence | PASS for focused Backend/UI source tests; no live row yet |
| Native and firmware validation | Native production core plus focused network/backend/HA/admin suites passed 73/73; targeted UI/SQL/HA tests passed 3/3; `esp32c6_personal_production` compiled and linked at 75,896/327,680 RAM and 1,800,410/7,340,032 flash | PASS for host/build evidence only |
| Runtime boundary | No candidate artifact is merged, published or installed; no post-candidate Target boot/status, admin terminal row, HA Activity row, relay contact or door-leaf observation exists | PENDING policy/CI, Backend deployment, Target signed OTA install/reboot/health and one new access observation |

## 2026-09-03 signed MQTT terminal completion rollout

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Reviewed main | PRs #344, #345 and #346 passed required checks and merge-committed normally. Exact feature main is `3be8310d85ad7c37659576a0cda618ab693b9927`; final policy main is `531b15aba56d500078d09a0f3daf5a8b0597c275` and all 100 protected blobs are byte-identical to the immutable feature | PASS for reviewed source and protected main identity |
| Exact Backend deployment | Owner-approved run `33658872347` completed immutable image publication and NAS deployment for exact feature main. Independent strict-TLS `/live` and `/ready` returned HTTP 200 with build SHA `3be8310d...`; all readiness checks were true, including MQTT, `access_event_collector`, schema and access-evidence integrity | PASS for deployed Backend process and dependencies |
| Exact Target publication | Final-main run `33659186723` built, signed and atomically published `2.1.434+main.g531b15a`, build ID `main-434-531b15aba56d500078d09a0f3daf5a8b0597c275`. Sanitized evidence records a 1,869,620-byte artifact, atomic metadata swap and previous-valid retention | PASS for signed publication and HTTPS readback; publication alone is not installation |
| Approved OTA install | One owner-approved HA `trigger_ota` ingress received QoS 1 PUBACK and Backend `broker_accepted`. Fresh MQTTS then advanced the Target from firmware `2.1.422`, boot 695 to exact `2.1.434+main.g531b15a`, boot 696 and boot ID `bc45dc394a658921ce75654d9f2570b7` | PASS for exact Target install and reboot identity |
| Post-boot health | Ten consecutive one-second status samples at uptime 100--109 seconds retained the same boot identity, `IDLE`, unarmed, relay command OFF/pin high; signed status revision advanced 91--100. A later fresh sample remained on the same boot and safe state at uptime 325 seconds, beyond both the 30-second health-valid and 120-second rollback windows | PASS for post-install health, no rollback and safe output state; no GPIO voltage/contact or door motion measured |
| Live HA contract | Retained `state` and `last_access_event` discovery both point at Backend `verified-status` and omit legacy `expire_after`; bridge availability is retained `online`. Fresh verified status reports boot 696/revision 139 and safe IDLE, but no terminal marker exists after the reboot | PASS for live HA discovery/state transport; one new access is still required to prove the new admin terminal row and HA Activity marker |
| Supplied UI comparison | The administrator screenshot contains only the pre-fix 01:31:26 broker-accepted legacy row, and the HA screenshot contains only older IDLE/unavailable transitions | CONSISTENT with the pre-rollout defect; screenshots do not constitute a post-install access result |
| Physical/access boundary | No agent-triggered relay, sensor passage or door movement was performed after installation | PENDING one owner-triggered mobile manual/pre-arm cycle followed by administrator and HA readback |

## 2026-09-03 post-install signed MQTT manual completion

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Owner action | The owner reported completion of one post-install test. The agent did not issue a relay or door-open command | OWNER-TRIGGERED test; physical door movement is owner-observed rather than instrumented |
| Target terminal | Fresh verified-TLS MQTTS on exact firmware `2.1.434+main.g531b15a`, boot 696 reported terminal sequence 1, exact signed-manual success mask `0x18`, event `ACCESS_SESSION_COMPLETED` and reason `ACCESS_GRANTED` | PASS for asynchronous Target relay ON/OFF terminal production without critical-path MQTT I/O |
| Backend verified projection | On the same status revision 426, Backend `verified-status` reported `last_access_result=SUCCEEDED` and marker `696-1`; Target and projection were both fresh IDLE with relay OFF/pin high and bridge availability online | PASS for HMAC verification, persisted status high-water and Backend-to-HA MQTT publication |
| HA retained contract | Live discovery binds `[Gatekeeper] 최근 출입 결과` to the verified-status marker/result without `expire_after`; the new broker payload therefore supplies `SUCCEEDED #696-1` to that entity | PASS for live HA MQTT input contract; authenticated HA state/recorder Activity readback remains pending |
| Administrator UI | Backend persistence is required before verified-status publication by the deployed transaction contract, but the authenticated administrator endpoint could not be read from WSL and Windows Computer Use failed before browser selection because its sandbox cwd was not a Windows local file URI | BACKEND persistence proven; rendered administrator completion row remains pending authenticated readback |

## 2026-09-03 Home Assistant rendered access Activity proof

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Entity identity | The owner identified the older state entity as `sensor.smart_gatekeeper_gatekeeper_geiteukipeo_dongjag_sangtae`; that entity intentionally renders only the FSM state and is not the new access marker entity | EXPLAINS why filtering only the state entity does not show per-access marker changes |
| Recent-access state | The authenticated HA entity page rendered `[Gatekeeper] 최근 출입 결과 = SUCCEEDED #696-1` five minutes after the owner test | PASS for HA MQTT entity state update matching Backend marker |
| Entity Activity | The same page's Activity section recorded `SUCCEEDED #696-1` at 02:25:37, after `NO_EVENT` at 02:18:55 and prior boot marker `SUCCEEDED #695-17` at 01:24:24 | PASS for Home Assistant recorder/history of the post-install access completion |
| Global Activity view | The supplied global Activity screenshot still showed only the older state entity rows because it was inspecting the state entity/device view rather than the separate recent-access entity change | UI selection/cache boundary; does not contradict the entity-specific recorded Activity proof |
| Administrator view | The supplied administrator screenshot still showed only the 01:31:26 broker-accepted legacy row | PENDING a fresh `loadLogs()` readback after the 02:25 terminal event |

## 2026-09-03 durable signed-MQTT terminal candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Consecutive terminal persistence | Native queue regression enqueued signed manual sequence 1 and signed arm sequence 2, reconstructed the NVS queue after a simulated reboot and drained both in original FIFO order | PASS for the existing 368-byte durable queue ABI and two-event replay; finite queue overflow remains explicitly gap-reported |
| Backend insert/idempotency | Worker regression delivered two distinct inserted terminal events to HA in order and suppressed the callback for an identical replay. Route relabeling from signed MQTT to Local GATT was rejected | PASS for DB-first HA dispatch, replay dedupe and MAC-covered route semantics |
| Backend regression | Full Backend discovery passed 197 tests with two explicit environment-only skips | PASS for parser, HMAC, DB worker, admin projection, HA discovery/event and N/N-1 latest-status compatibility |
| Repository regression | Initial repository discovery ran 343 tests: 337 passed, one environment-only case skipped and six assertions identified only the expected protected-policy/build-input digest drift. The three exact Target build-input hashes were then refreshed and its focused 18-test contract passed | FUNCTIONAL PASS; trusted policy authorization still pending |
| ESP32-C6 build | `esp32c6_personal_production` compiled and linked without warnings at 75,880/327,680 bytes RAM (23.2%) and 1,766,442/7,340,032 bytes application flash (24.1%) | PASS for local build and OTA partition fit; not a signed artifact, install, reboot or physical door result |
| Deployment boundary | No GitHub push, Backend deployment, Target publication/OTA, relay command or physical access was performed | PENDING protected merge, exact deployment and at least two live consecutive accesses with admin/HA readback |

## 2026-09-03 crash-durable terminal and HA projection candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Owner latest-result observation | The owner reported that the recent-access result changed after the latest test | POSITIVE runtime observation for the latest-status projection only; it does not prove every canonical event, administrator row or failure recovery |
| Target production enqueue contract | Signed MQTT arm/manual terminal writes the exact HMAC canonical record to the 8-entry NVS queue before its callback returns, falling back to the 16-entry RAM outbox only if NVS rejects the write; no `client.publish` occurs in that producer | PASS for reboot-durable bounded enqueue without synchronous MQTT; finite overflow and QoS 0 delivery remain explicit gaps |
| Backend atomicity | Regression commits `access_event_history` and `ha_access_event_outbox` in one transaction and rolls both back when outbox insertion fails | PASS for eliminating DB-row-without-pending-HA-record at commit time |
| HA retry/PUBACK | Worker regression drained two consecutive committed rows in ID order, waited for QoS 1 PUBACK and marked each only afterwards; noncanonical/inconsistent stored payloads were rejected | PASS for restart-recoverable at-least-once HA projection; crash after PUBACK but before DB mark may repeat the same marker |
| Schema migration | Real Docker/MariaDB run passed all 17 migration tests, including idempotent schema 013 up and N-1 rollback preservation of the pending-delivery table | PASS for host migration/rollback contract; live NAS backup/migration/readiness is separate |
| Backend regression | Full Backend discovery passed 203 tests with two declared environment-only skips; the focused registry suite passed 38/38 including retry of the same row after a missing PUBACK | PASS for final local Backend source freeze |
| ESP32-C6 build | `esp32c6_personal_production` compiled warning-free at 75,880/327,680 bytes RAM (23.2%) and 1,766,444/7,340,032 bytes application flash (24.1%) | PASS for local build/partition fit; not signed publication, installation, reboot/health or physical access |
| End-to-end boundary | Target publisher remains QoS 0 with no Backend application ACK and both queues are finite | NOT absolute exactly-once; protected merge/deploy, outage/overflow soak and repeated live admin plus HA Activity correlation remain open |

## 2026-09-03 crash-durable access Activity rollout

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Reviewed main | PRs #347, #348 and #349 passed hosted checks and merge-committed normally. Feature main is `6aa8d188f509f2135c1551abca9284022ef88e2d`; final policy main is `f4e22654eca1bce44044b5a461d2185c5982806a` | PASS for reviewed source and protected identity |
| Backend schema 013 deployment | Run `33668277642` completed production deployment. Strict-TLS `/live` and `/ready` returned exact feature main with every readiness check true | PASS for deployed process, migration and dependencies; no access event is inferred from readiness |
| Target OTA publication | Run `33668277535` published and HTTPS-read-back signed encrypted `2.1.436+main.g6aa8d18`, build ID `main-436-6aa8d188f509f2135c1551abca9284022ef88e2d` | PASS for publication; install/reboot/health remains unproven |
| Latest-result observation | The owner reports that the recent-access result changed | POSITIVE for the existing latest-status projection; not proof of every schema 013 canonical event or HA event outbox delivery |
| Automated install attempt boundary | Windows Computer Use could not initialize from the WSL cwd; the constrained Target MQTT identity could not read state or write HA ingress, and station-local TCP/80 recovery timed out. No OTA request or unsafe fallback was issued | SAFE NO-CHANGE; one HA OTA button press and exact post-reboot readback remain required |
| Delivery acceptance | No two consecutive post-`2.1.436` terminal events have yet been correlated across administrator history and HA Activity | PENDING repeated live test; finite Target queues/QoS 0 and at-least-once duplicate marker boundary remain explicit |

## 2026-09-05 GATT v2 ACL mismatch diagnosis and host validation

- Owner screenshot recorded `SIGNATURE_INVALID` followed by repeated
  `GATT_DISCONNECTED`. Read-only runtime correlation kept the Target on exact
  `2.1.445+main.g57bfe10`, boot 720 and the same boot ID with fresh IDLE/MQTT
  health, separating the failure from a crash or broker outage.
- Source tracing found Android fast v2 proof against a retained Backend ACL
  credential range `1..1`; the Target verifier's unsupported-version result was
  then collapsed to signature-invalid by the public Result mapper.
- Backend 213-test discovery passed with two declared environment skips. Target
  and shared repository discovery produced 355 functional passes with one
  declared skip; the remaining 12 failures were only the expected protected
  digest authorization gate.
- A real Docker/MariaDB image applied schema 013, inserted an active granted
  `1..1` credential, applied schema 014 twice, and verified exact `2:2` plus a
  pending `GATT_V2_CONTRACT` replacement job. The production Target environment
  built successfully at 23.5% RAM and 24.8% application flash.
- These are source/build/database results, not a deployed ACL ACK, phone
  authentication, relay contact or physical door result.

## 2026-09-05 GATT v2 ACL production rollout

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Reviewed main | Policy PR #358, feature PR #359 and final policy PR #360 passed required hosted checks and merged normally; feature main is `382c4f86...54c` and final policy main is `6d8ab481...131` with all 104 protected blobs unchanged | PASS for reviewed source and trusted identity |
| Backend schema 014 deployment | Owner-approved run `33942785068` created the pre-migration backup, passed `up 014`, deployed exact feature main and passed loopback/public readiness; independent `/ready` returned the same SHA and all checks true | PASS for immutable Backend deployment, schema 014 and live dependencies |
| Signed Target publication | Run `33942948534` built, encrypted, signed, atomically published and HTTPS-read-back `2.1.448+main.g6d8ab48`, build ID `main-448-6d8ab481afc7e4fc74636eef8be816f2dadd7131` | PASS for signed publication; not installation by itself |
| Single OTA request | One HA bridge `trigger_ota` request received QoS 1 PUBACK, Backend `broker_accepted`, Target result 0 and Backend `target_accepted`; no duplicate request was sent | PASS for one signed boot-bound install trigger and Target acceptance |
| Exact Target install | Target changed from boot 720 / `2.1.445+main.g57bfe10` to boot 721 / `2.1.448+main.g6d8ab48`, new boot ID `38f688d0768d84ad0b2b1a2b204f0662`, SOFTWARE reset, online and IDLE | PASS for exact installation and reboot identity |
| Post-install health | Same boot/version remained IDLE and online through uptime 126 seconds; MQTT connect attempts/count were 1/1, failures 0, and Backend verified-status advanced with the Target | PASS beyond the 30-second valid-mark and 120-second rollback windows; no rollback observed |
| Later boot readback | Final readback found boot 722 / `e8c8d996c89184110d83c011a38a6ba0`, reset reason `BROWNOUT`, still on exact `2.1.448+main.g6d8ab48`, online/IDLE at uptime 344 seconds with MQTT 1/1 and zero failures | PASS for retaining the validated image through a later power reset; repeated brownout diagnosis remains a separate electrical field Gate |
| Signed mobile publication | Run `33942948521` published `1.0.0-g6d8ab48` / 41501 and verified primary/fallback HTTPS copies | PASS for publication; phone install is pending |
| ACL and physical acceptance | A passive ACL-ACK probe started after migration and observed no new message, so it cannot reconstruct an ACK that may have occurred earlier | PENDING one owner phone authentication plus Activity/result/door observation; no relay action was initiated by the agent |

## 2026-09-05 post-rollout entrance no-response readback

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Owner entrance attempt | Automatic hands-free access produced no visible reaction; the app `문 열기` fallback opened the installed door | FAIL for that hands-free trial; PASS only for the independently authenticated manual remote path |
| Target/Backend health after report | Target boot 723 stayed on exact `2.1.448+main.g6d8ab48`, online/IDLE at uptime 9,266 seconds, MQTT 1/1 with zero failures and outbox depth 0; public `/ready` returned all checks true | No evidence of a current Target crash, broker outage or Backend readiness failure |
| Latest terminal classification | Signed retained status showed `ACCESS_SESSION_COMPLETED`, `ACCESS_GRANTED`, phase mask 24 (`0x18`) | Confirms signed MQTT manual-open completion; does not prove a Local GATT attempt |
| Hands-free failure boundary | The one-slot retained terminal summary was replaced by manual-open success and has no Local GATT terminal marker | UNRESOLVED before/within phone BLE wake and GATT; correlate the same-cycle mobile Activity or administrator history before assigning a code defect |
| Phone Activity correlation | Latest automatic rows were `RUNNING` 14:38:57 then `PROTOCOL_INCOMPATIBLE` 14:39:00; the next visible row was only manual remote at 17:13:07, with no automatic row for the after-17:00 entrance | Confirms radio/GATT response existed at 14:39 and no phone-side automatic session was created around 17:13; does not by itself distinguish stopped Target advertising from a dead Android scan registration |
| Advertising self-heal candidate | ESP32-C6 controller `isAdvertising()` is checked every 2 seconds only with zero active GATT connections; stopped advertising is restarted with attempt/success/failure/watchdog counters, and raw Target status includes active ACL version/protocol range | PASS in focused 38-test run after one expected discovery-count update and production firmware link at 76,992/327,680 RAM, 1,820,028/7,340,032 app flash; connected Target behavior remains pending |
| HA diagnostic candidate | Discovery adds `[Gatekeeper] BLE 광고 상태` from raw Target diagnostic status, with 30-second expiry and bridge availability | SOURCE ONLY; protected authorization, Backend deployment, Target OTA and live entity readback remain pending |

## 2026-09-05 BLE advertising self-heal first OTA rollback

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Reviewed source | Policy PR #361, feature PR #362 and final-policy PR #363 passed required hosted checks; actual feature main is `1aacbaf073731c6ed8b3c703254d2e5e12bb9990` | PASS for reviewed source and trusted bytes |
| Backend deployment | Owner-approved run `33956526362` deployed exact feature main; independent strict-TLS `/ready` returned that SHA and every check true | PASS for Backend and HA discovery code deployment |
| Signed publication | Final-main run `33956619291` published and HTTPS-read-back `2.1.451+main.ga683832` | PASS for artifact publication only |
| Single OTA request | One HA trigger received QoS 1 PUBACK, Backend `broker_accepted`, Target result 0 and `target_accepted`; no duplicate request was sent | PASS for request acceptance, not install health |
| Pending-image boot | Target left boot 723 / `2.1.448`, then returned as boot 725 / `2.1.448`; boot 725 retained a valid previous-boot breadcrumb with state `BOOTING`, action `wifi_sta_profile_enabled` and uptime 2,094 ms | Boot 724 started but did not reach MQTT/health; previous image was restored |
| Reset classification | Boot 725 reports `BROWNOUT`; it remained online/IDLE with MQTT 1/1, zero failures and advancing status beyond uptime 216 seconds | FAIL for first install; evidence indicates supply brownout during pending verification rather than an application panic |
| Retry boundary | Booting the candidate advanced the version floor, so the unchanged `2.1.451` pointer is intentionally quarantined after rollback | A strictly newer exact-main build is required; retry only once after stable-current verification |

## 2026-09-05 BLE advertising self-heal installed health

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Retry publication | Docs-only exact-main `2bedd83cad02aabbd75c27e39655c61d7c9ed5e0` run `33957358126` built, signed, atomically published and HTTPS-read-back `2.1.452+main.g2bedd83` | PASS for a strictly newer artifact containing unchanged reviewed firmware source |
| Pre-retry health | Recovered boot 725 stayed `2.1.448`, online/IDLE through uptime 927 seconds with MQTT 1/1 and zero failures | PASS for stable-current precondition after the first brownout rollback |
| Single retry request | One new-version HA OTA request received PUBACK, Backend broker acceptance, Target result 0 and Target acceptance | PASS; no further request was sent |
| Exact install | Target advanced once to boot 726 / boot ID `b820fcff4cfd60dfcfd56ac4567d47bf`, exact `2.1.452+main.g2bedd83`, SOFTWARE reset and `ota_pending_verify` breadcrumb | PASS for installed candidate identity |
| Health/rollback window | The same boot/version remained online/IDLE through uptime 139 seconds, MQTT 1/1, failures 0 and outbox 0 | PASS beyond the 30-second valid mark and 120-second rollback timeout |
| Advertising controller state | Raw Target status reported expected `true`, active `true`, zero GATT connections and restart attempts/successes/failures/watchdog recoveries all 0 | PASS for ESP32-C6 controller state; not direct proof that an external phone received packets |
| Active ACL | Raw Target status reported active ACL version 1331 with exact protocol range `2..2` | PASS; the earlier 14:39 `PROTOCOL_INCOMPATIBLE` stale-ACL hypothesis is no longer present in installed state |
| HA discovery | Retained config named `[Gatekeeper] BLE 광고 상태`, used raw Target status, device class `running` and 30-second expiry | PASS for discovery contract and MQTT publication; HA UI rendering remains a separate observation |
| Physical acceptance | No external BLE scanner or fresh hands-free phone approach was available in WSL | PENDING over-air reception and automatic Android authentication/door result |

## 2026-09-05 live ACL 1340 reconciliation

| Test | Observed result | Verdict / boundary |
|---|---|---|
| App identity card | Owner screenshot displayed `등록 출입문 1 · ACL 1340`, `스마트키 사용 가능` and the green access-ready mark | Backend personal-status projection is ACL 1340 and access-ready; the UI alone is not physical access proof |
| Live Target readback | Target boot 727 reported exact firmware `2.1.452+main.g2bedd83`, active ACL 1340, protocol range `2..2`, IDLE, BLE advertising expected/active, and MQTT 1/1 with zero failures | MATCH: the app and Target currently agree on ACL 1340; the earlier ACL 1331 observation was the boot-726 post-install snapshot |
| Backend readiness meaning | `access_ready` requires the latest Target ACK to be `APPLIED` for the same ACL version and SHA-256 digest | The green mark is backed by exact version/digest acknowledgement, not merely a phone-local display value |
| Later reset boundary | Boot 727 reported `BROWNOUT` while retaining exact firmware 452 and ACL 1340 | Separate electrical field issue; not evidence of an ACL mismatch |

## 2026-09-05 field diagnostics D0-D2 source verification

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Backend unit and contract suite | 222 tests passed; 2 optional environment tests skipped | PASS for strict bundle validation, authenticated/idempotent storage, first-missing-stage classification, admin projection and schema/deploy contracts |
| Real MariaDB migration | Existing-volume upgrade through schema 015 and up/write/down/legacy-read scenarios both passed | PASS for the tested MariaDB migration and rollback compatibility paths; this is not a NAS deployment |
| Flutter diagnostics | 27 focused tests passed and `dart analyze lib test` reported no issues | PASS for the default-OFF consent setting, bounded redacted report, field marker and non-blocking upload behavior |
| Android native journal | Focused Gradle/JUnit test passed | PASS for newest-first 50-session/100-wake bounds and omission/hashing of phone/process identifiers |
| Target firmware | Production `esp32c6` build passed at RAM 26.9% and flash 24.9%; exact Target OTA input contract passed | PASS for source/build and deferred telemetry contract; no Target OTA or physical access action was performed |
| Evidence ceiling | No deployed phone bundle, installed firmware readback or new hands-free approach trial exists for this candidate | D3 PENDING; source tests do not prove phone RF reception, Target action or physical door movement |

## 2026-09-05 field diagnostics first Target rollout and health rollback

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Backend deployment | Owner-approved run `33965557195` deployed exact feature main `c9aa85c31b0b7b1d04ea71970c720cf358805acc`; independent strict-TLS `/live` and `/ready` returned HTTP 200 for that SHA with every readiness check true | PASS for Backend schema-015 runtime and dependencies |
| Signed Target publication | Final-main run `33965654223` signed, encrypted, atomically published and HTTPS-read-back `2.1.456+main.gc1d58b1` | PASS for exact artifact publication; not installation health |
| Safe preflight and single request | Boot 729 / exact `2.1.452` was IDLE, unarmed, relay OFF, MQTT 1/1 with zero failures and BLE advertising active at uptime 1,195 seconds. One HA request received PUBACK, Backend `target_accepted` and Target ACK result 0 | PASS for one accepted OTA request; no duplicate was sent |
| Candidate boot | Target advanced to boot 730 / exact `2.1.456`, SOFTWARE reset, IDLE and relay OFF; MQTT recovered to 1/1 with zero failures and BLE advertising became active by uptime 8 seconds | PASS for download, inactive-slot boot and initial control-plane recovery |
| Health rollback | The same boot/version remained healthy in external status through uptime 75 seconds, then boot 731 restored exact `2.1.452`. Retained boot diagnostics report `planned_restart=ota_health_rollback`, SOFTWARE reset and no matching panic/WDT coredump | FAIL for candidate valid mark; PASS for automatic rollback and prior-slot service recovery |
| Root-cause candidate | OTA health sampling allowed only a 1,000 ms gap while the main loop also serialized and published the expanded signed status every 1,000 ms. The diagnostic payload increase makes small TLS/scheduler overruns repeatedly reset the required 30-second healthy interval | Strong source/runtime correlation; exact per-sample gap was not retained by the rolled-back image |
| Corrective source | Health sample tolerance is raised to 5,000 ms, still below the 45-second loop watchdog, and rollback breadcrumbs distinguish safe-state, network, heap and sample-gap timeout. Focused 45 tests and the production Target build pass at RAM 26.9%, flash 24.9% | SOURCE PASS; trusted authorization, strictly newer publication and one new OTA remain required |

## 2026-09-05 OTA health gap correction rollout and heap-headroom candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Reviewed correction | Policy PR #369, feature PR #370 and final policy PR #371 passed required checks; final main `987bec7b74519d4800b7d876585af7a45ad2a8c0` published signed `2.1.459+main.g987bec7` | PASS for reviewed source and exact publication |
| Safe retry and candidate boot | Stable boot 732 / `2.1.452` was IDLE, relay OFF, MQTT 1/1 and BLE active at uptime 1,581 seconds. One request received PUBACK, Backend `target_accepted` and Target result 0; boot 733 then ran exact 459 with MQTT and BLE restored | PASS for one accepted request and candidate boot; no duplicate was sent |
| Second controlled rollback | Boot 733 stayed exact 459, IDLE, relay OFF, MQTT 1/1 and BLE active through uptime 61 seconds, but boot 734 restored exact 452 before 120 seconds. New breadcrumb reports generic `ota_health_timeout`; no sample gap exceeded 5 seconds and the final sample predicates were healthy | FAIL for valid mark; sample-gap hypothesis alone is rejected. Automatic rollback and service recovery passed again |
| Heap correlation | Recovered 452 reports steady free heap 80,972 B, largest block 73,716 B and historical minimum 20,768 B. Field diagnostics add static memory and signed MQTT/TLS work can transiently cross the previous 65,536 B instantaneous threshold | Strong remaining predicate candidate; candidate 459 did not retain historical false-predicate identity |
| Headroom correction source | Health retains 30 continuous seconds and the 120-second deadline, but uses 48 KiB aggregate plus 32 KiB contiguous heap thresholds and persists the last predicate that reset the interval. Five-second sampling remains below the 45-second watchdog | Production build PASS at RAM 26.9%, flash 24.9%; focused 45 tests PASS. Trusted review and one strictly newer OTA are pending |
