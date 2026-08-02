# hardware_test.md — 테스트 증거와 현재 검증 상태
> Last updated: 2026-08-02 (G0-SW hardwareless와 G0-HW production Gate 분리)

## 1. 판정 원칙

과거 VL53L0X/ESP32 BLE scanner 아키텍처의 PASS는 변경 이력으로 보존하지만, 현재 **iBeacon → Android → FastAPI → MQTT → AJ-SR04T → Relay** 경로의 합격 근거로 간주하지 않습니다. 소프트웨어 빌드 통과와 실기기 E2E 통과도 분리합니다.

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
| #18 production-core host tests | 2026-08-02 native C++ build/run | 🟢 SOFTWARE PASS | production `GattProtocol.cpp` direct compile/run; canonical framing/session/parser/fail-closed tests; no radio/GPIO/relay evidence |
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
