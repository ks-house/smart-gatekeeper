# current_code_audit.md — 최신 코드 기준 문서·구현 재분석
> Audit date: 2026-07-30
> Baseline: branch `work`, HEAD `8da8818`

## 1. 결론

저장소는 초기 문서가 설명하던 “ESP32 BLE scanner + VL53L0X ToF + ESP32 HTTPS 인증”을 이미 벗어났습니다. 최신 구현의 기준선은 **ESP32 iBeacon advertiser + Android foreground scanner + FastAPI/MariaDB 인증 + MQTT QoS1 Pre-arm + AJ-SR04T + GPIO3 relay**입니다.

이번 감사에서 README, architecture, environment, pin map, test matrix, index를 현재 코드에 맞춰 다시 컴파일했습니다. `raw/`와 append-only log의 과거 항목은 역사적 근거이므로 변경하지 않았습니다.

## 2. 코드에서 확인한 현재 계약

| 계약 | 현재 값/동작 | 근거 코드 |
|---|---|---|
| Target board/build | ESP32-C6, pioarduino, `esp32c6`, 16 MB OTA | `platformio.ini` |
| Sensor | AJ-SR04T, GPIO10/11, 20 cm min, 50 cm default | `include/config.h`, `src/UltrasonicSensor.cpp` |
| Relay | GPIO3 Active-LOW, ON push-pull LOW, OFF INPUT High-Z; physical validation pending | `include/config.h`, `src/RelayController.cpp` |
| Beacon | fixed UUID, 100 ms, +9 dBm default | `include/config.h`, `src/main.cpp` |
| Target FSM | IDLE/ARMED/RELAY_HOLD/COOLDOWN | `src/main.cpp` |
| Pre-arm | `gatekeeper/arm`, default 60 s | `include/config.h`, `src/MqttManager.cpp` |
| App scan | service-isolate owner, monitor→range, EMA/hysteresis | `gatekeeper_app/lib/services/ble_scanner.dart` |
| App request | `/door/prearm`, optional API key, 4 s timeout | same |
| Backend delivery | approved device + QoS1 PUBACK; failure 503 | `backend/app/main.py` |
| Deployment | firmware on every main push; APK main app changes/manual | `.github/workflows/*.yml` |

## 3. 기존 문서에서 제거한 잘못된 현재형 설명

- ESP32가 스마트폰 BLE 광고를 스캔한다.
- VL53L0X가 현재 출입 센서이며 GPIO6/7 I²C를 사용한다.
- ESP32가 NAS `/auth/verify`를 직접 호출한다.
- ToF 전용/relay 전용 PlatformIO 환경과 Pololu dependency가 현재 존재한다.
- 과거 ToF E2E PASS가 현재 Android/초음파 흐름도 증명한다.
- Target cooldown이 고정 10초다. 현재 기본은 3초이며 NVS/MQTT로 조정됩니다.

## 4. 코드상 주요 잔존 위험

### P0 — 실기기 합격을 막는 미검증

1. **iBeacon UUID byte order/stack 불일치**: `BLEDevice`/Bluedroid 설명과 NimBLE 형태 native field가 혼재합니다. raw advertisement 캡처 전에는 앱 filter 매칭을 보장할 수 없습니다.
2. **릴레이/5V 전기 경계**: High-Z OFF는 현재 모듈 호환을 위한 우회이며, ECHO 5V 직결과 릴레이 역전류는 ESP32 latch-up 위험입니다.
3. **Android 종료 정책**: 화면 OFF 경로는 강화됐지만 force-stop/OEM kill은 복구할 수 없습니다. 실제 Samsung/Xiaomi 등에서 확인해야 합니다.

### P1 — 보안·운영 부채

1. **MQTT TLS fail-open**: Target은 TLS 실패 3회 후 `setInsecure()`를 사용해 broker 신원 검증을 포기합니다.
2. **관리자 무인증**: `/admin` 및 admin API는 앱 레벨 인증이 없으며 승인 우회와 개인정보 노출 위험이 있습니다.
3. **고정 beacon UUID**: 근접 신호는 복제 가능하고 보안 자격 증명이 아닙니다. 실제 권한은 device approval/API/MQTT ACL에 의존합니다.
4. **문서 push의 운영 펌웨어 배포**: firmware workflow가 main의 path filter 없이 실행됩니다.

### P2 — 정리 대상

1. 현재 I²C 센서가 없는데 `clearI2CBus(6, 7)`가 부팅마다 실행됩니다.
2. source/header 주석에 Bluedroid/NimBLE, ToF/ultrasonic 용어가 혼재합니다.
3. `ConfigManager.h` 스타일과 일부 로그 prefix가 프로젝트 컨벤션과 다릅니다.
4. `url_launcher`가 앱 dependency에 남아 있으나 최근 다운로드 경로는 Dio/open_filex로 전환됐습니다.
5. 현재 릴레이 계약은 `AGENTS.md`, `schema.md`, `include/config.h`와 동일한 authoritative GPIO3입니다. 과거 GPIO23 현장 관측은 append-only 이력으로만 유지하며 현재 지침으로 사용하지 않습니다.

## 5. 다음 우선순위

1. current HEAD PlatformIO build 및 Android/backend 정적 검증을 다시 실행합니다.
2. nRF Connect raw payload와 interval을 캡처해 BLE stack/UUID 처리를 확정합니다.
3. ECHO 레벨 시프터, optocoupler/flyback, 반복 relay 시험으로 전기적 안전을 먼저 닫습니다.
4. 화면 OFF/task swipe-away/OEM battery policy별 실제 접근 시험을 수행합니다.
5. MQTT broker 차단·잘못된 CA·PUBACK timeout 시험 후 insecure fallback 제거 정책을 결정합니다.
6. admin authentication과 workflow path filter를 별도 보안 변경으로 처리합니다.

## 6. 문서 신뢰도 규칙

- 현재 동작: 이 문서, `architecture.md`, 실제 코드가 기준입니다.
- 테스트 합격: `hardware_test.md`에서 current architecture로 명시된 행만 인정합니다.
- 과거 사실: `wiki/log.md`는 append-only 이력이므로 당시 사실과 현재 사실을 구분합니다.
- 부품 원본: `raw/`는 초기 BOM/사양 보존용이며 현재 장착 부품 목록으로 해석하지 않습니다.

## 7. 테스트 실행 위치 구분

이 문서 현행화 작업에서 직접 실행한 Markdown 링크 검사, `py_compile`, `git diff --check`, PlatformIO 빌드 시도는 **GitHub Actions가 아니라 에이전트 작업 컨테이너**의 `/workspace/smart-gatekeeper`에서 수행했습니다. 이 컨테이너에는 Docker CLI가 없었고, PlatformIO는 pioarduino 의존성 다운로드 중 로컬 실행 환경의 TLS 인증서 체인 오류로 중단됐습니다.

`wiki/log.md`의 2026-07-30 Flutter format/analyze/test/APK PASS는 `gatekeeper_app-flutter-builder` Docker 컨테이너에서 얻은 별도 선행 증거입니다. 저장소 기록만으로는 그 Docker daemon의 물리 호스트가 개발자 PC인지 클라우드 VM인지 확정할 수 없으므로 “GitHub Actions에서 통과”로 확대 해석하지 않습니다. GitHub Actions 실행은 workflow/run 번호가 명시된 기록만 CI 증거로 취급합니다.
