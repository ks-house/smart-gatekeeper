# wiki/log.md — Chronological Change Log
> Format: `## [YYYY-MM-DD] <type> | <description>`
> Append only. Never edit past entries.

---

## [2026-06-26] compile | wiki 초기 뼈대 생성 (schema.md, index.md, log.md)

- `schema.md` 생성: 디렉토리 레이아웃, 네이밍 컨벤션, 코드 스타일, 워크플로우 정의
- `wiki/index.md` 생성: 4개 카테고리 + Quick Reference 테이블
- `wiki/log.md` 생성: 본 파일

## [2026-06-26] compile | env_setup.md 생성 — 개발 환경 세팅 가이드

- PlatformIO IDE 기반 워크플로우 확정
- ESP32 Arduino 프레임워크 boilerplate `platformio.ini` 내용 정의
- VL53L0X 라이브러리 선택: `pololu/VL53L0X` (C++ native, no HAL dependency)
- 필수 라이브러리 목록 확정

## [2026-06-26] compile | pin_mapping.md 생성 — I2C 및 릴레이 핀 매핑

- ESP32 기본 I2C 핀 확정: SDA=GPIO21, SCL=GPIO22
- 릴레이 제어 핀: GPIO26 (Active-LOW 가정, 확인 필요)
- 안전 배선 주의사항 기록

## [2026-06-26] code | ToF 센서 드라이버 스켈레톤 생성 (src/ToFSensor.h, .cpp)

## [2026-06-26] code | 릴레이 드라이버 스켈레톤 생성 (src/RelayController.h, .cpp)

## [2026-06-26] code | Step1_ToF_Test.cpp, Step1_Relay_Test.cpp 예제 스케치 생성

## [2026-06-26] ingest | raw/ST_VL53L0X_Specs.md — VL53L0X 데이터시트 핵심 스펙 컴파일

- 소스: STMicroelectronics DS11486 + Pololu Arduino Library GitHub
- 전기 사양, I²C 타이밍, 측정 모드, Pololu API 요약, ESP32 특이사항 포함
- 다중 센서 XSHUT 주소 할당 패턴 기록

## [2026-06-26] fix | ToFSensor.cpp — 데이터시트 기반 3가지 버그 수정

- Bug #1: `Wire.begin(21, 22)` → `Wire.begin(21, 22, 400000UL)` (100kHz→400kHz, 응답 지연 해소)
- Bug #2: `sensor.setTimeout(500)` 누락 추가 (I2C 단선 시 무한 블로킹 방지)
- Bug #3: 반환값 65535 sentinel 미처리 → 명시적 체크 추가 (out-of-range 오류)

## [2026-06-26] lint | 위키 전체 링크 및 일관성 검사

- index.md: raw/ 카테고리 추가, Quick Reference 항목 3개 추가
- 깨진 링크: 없음
- 모순 정보: 없음

## [2026-06-27] ingest | raw/Espressif_ESP32C6_BoardSpec.md — ESP32-C6 보드 사양 컴파일

- 아키텍처 비교 (Xtensa vs RISC-V), GPIO 사용 가능 여부 분류
- 스트래핑 핀(GPIO4/5/8/9/15) 및 예약 핀(GPIO17-20) 사용 금지 목록
- I2C 권장 핀: GPIO6(SDA), GPIO7(SCL)
- pioarduino 플랫폼 필수 이유 기록

## [2026-06-27] fix | ESP32 → ESP32-C6 전면 마이그레이션 (CRITICAL)

- `platformio.ini`: board=esp32dev → esp32-c6-devkitc-1, platform → pioarduino
  `-DARDUINO_USB_CDC_ON_BOOT=1` 및 `-DARDUINO_USB_MODE=1` 빌드 플래그 추가
- `config.h`: I2C SDA 21→6, SCL 22→7 / Relay 26→23
- `pin_mapping.md`: ESP32-C6 GPIO 테이블 전면 개편

## [2026-06-27] fix | RelayController.cpp — Active-LOW optocoupler 스위칭 로직 수정

- 문제: 3.3V GPIO HIGH(3.3V) 시 5V 오토커플러 전압차 1.7V > Vf(1.2V)로 릴레이 상시 ON 유지
- 수정: `relayOff()`에 `pinMode(pin, INPUT)` 고임피던스 트릭 적용하여 통전 완전 차단

## [2026-07-24] test | Test #3 합격 — Step 1 (Local PoC) 최종 완료 🟢

- ToF 센서 500mm 이하 감지 시 릴레이 1초 ON 후 자동 OFF (2초 쿨다운) 비블로킹 상태 머신 정상 작동
- hardware_test.md, index.md 등 문서 업데이트 완료
- Step 1 (하드웨어 단독 및 연동 검증) 최종 성공 완료 처리

## [2026-07-24] code | backend/ 뼈대 파일 생성 — Step 2 시놀로지 NAS 백엔드 구축 시작

- `backend/docker-compose.yml`: MariaDB 및 FastAPI 서비스 구성

## [2026-07-24] test | Step 2 성공 — cURL 기반 NAS HTTPS API 자격 검증 검증 완료 🟢

- 시놀로지 NAS 도커 환경(tworimpa.synology.me:4443)에서 `/api/v1/auth/verify` 통신 성공
- 허용 MAC 요청: `granted: true`, 세입자 `홍길동` 정상 반환 확인
- 거부 MAC 요청: `granted: false`, 출입 거부 정상 반환 확인
- FastAPI 응답 `Content-Type: application/json; charset=utf-8` 명시 보장 반영 완료

## [2026-07-24] code | 3단계 WiFi + HTTPS 연동 펌웨어 구현 진입

- `include/secrets.h.example` 및 `include/secrets.h` 구성 (보안 규정 준수)
- `include/config.h`: Wi-Fi 설정, NAS API_URL, 임계값(500mm), RELAY_HOLD_MS(1000ms) 추가
- `platformio.ini`: `bblanchon/ArduinoJson` 의존성 추가

## [2026-07-24] test | Test #3 합격 — Step 3 엔드-투-엔드 통합 검증 완전 성공 🟢

- ToF 센서 225mm 거리 감지 ➔ 시놀로지 NAS HTTPS POST 요청 (`https://tworimpa.synology.me:4442/api/v1/auth/verify`)
- `ble_mac`: `AA:BB:CC:DD:EE:01` 자격 검증 성공 (`granted: true`, 세입자: `홍길동(101호)`)
- 출입 승인 결과 수신에 따른 릴레이 1000ms ON 구동 (딸깍!) 및 2000ms 쿨다운 비블로킹 FSM 완벽 작동
- Captive Portal AP 설정, NVS ConfigManager, NTP 시간 동기화 모듈 통합 성공
- hardware_test.md, architecture.md, index.md 상태 🟢 완료 업데이트

## [2026-07-24] code | Step 4 — MQTTS, Home Assistant Auto Discovery & GitHub CI/CD OTA 구축

- `OtaManager.h/.cpp`: 시놀로지 NAS `version.json` 무선 펌웨어 수신 및 `HTTPUpdate` 자동 플래싱 모듈 구현
- `MqttManager.h/.cpp`: `WiFiClientSecure` 기반 MQTTS (4883 TLS) Pinning 및 Home Assistant Auto-Discovery 엔티티 5개 자동 등록
- `.github/workflows/deploy.yml`: GitHub Actions 자동 컴파일(`-DFIRMWARE_VERSION_OVERRIDE="1.0.0-g<sha>"`) 및 SFTP NAS 자동 배포 파이프라인
- `secrets.h` & `secrets.h.example`: ISRG Root X1 TLS Root CA Certificate Raw String Literal 주입 적용

## [2026-07-24] fix | MqttManager — PubSubClient 1024바이트 버퍼 확장 및 시각 계산 언더플로우 버그 해결

- Bug #1: `PubSubClient` 기본 버퍼(128B) 초과로 HA Auto-Discovery 전송 누락 ➔ `client.setBufferSize(1024)` 적용
- Bug #2: `loop()` 내 `now` 수신 시점 차이로 인한 Unsigned millis Underflow 발생 ➔ 최신 `millis()` 갱신으로 릴레이 1초 정상 ON 보장

## [2026-07-24] test | Step 3 & Step 4 전체 시스템 통합 테스트 100% 정상 완수 🟢

- ToF 50cm 진입 ➔ NAS 자격 검증 ➔ 릴레이 1초 ON 스위칭 E2E 통과
- HA 원격 명령(`open_gate`) 수신 ➔ 릴레이 1초 ON 스위칭 완벽 가동
- 무선 OTA 배포 파이프라인 성공 (`[OTA-PROGRESS] 87.3%` 수신 및 무선 재부팅 완료)
- hardware_test.md, architecture.md, log.md 최종 통합 완료 기록

## [2026-07-24] code | Step 4 최종 완성 — BLE 5.0 선인증 & 스마트 쿨다운 리셋 FSM 개편 🟢

- `partitions_16MB_ota.csv`: ESP32-C6 N16 모델에 맞춰 App 영역 각 7.0MB 확장 파티션 스킴 작성
- `config.h`: `BLE_RSSI_THRESHOLD` 현장 수신 세기 기준인 `-80 dBm`으로 현실화 최적화
- `src/main.cpp`:
  - BLE 5.0 선-인증 신호 10초 이내 유효할 때만 ToF 50cm 이내 접근 검증 구동
  - 문 주변(BLE & ToF 구역)에 사용자가 머무르는 동안 `COOLDOWN` 타이머 지속 리셋하여 중복 릴레이 연타 및 서버 통신 폭주 차단
  - 문 영역 완전 이탈 후 3초 경과 시 `IDLE` 대기 모드로 복귀
  - `pScan->clearResults()` 매 10초 호출로 RAM 힙 메모리 고갈(Out-Of-Memory) 원천 차단
  - Native USB CDC 시리얼 동기화 대기로 부팅 시 초반 `[OTA]` 버전 체크 로그 유실 방지
- `architecture.md`, `pin_mapping.md`, `hardware_test.md`, `log.md` 지식 베이스 문서 최종 업데이트 완료

## [2026-07-24] feat | MQTT 기반 동적 BLE RSSI 임계값 제어 및 Home Assistant Number 슬라이더 구현

- `ConfigManager.h/.cpp`: `getBleRssiThreshold()`, `setBleRssiThreshold(rssi)` NVS 영구 보관 구현
- `MqttManager.h/.cpp`:
  - MQTT `smart-gatekeeper/cmd` 의 `{"command": "set_rssi", "rssi": -85}` 및 `smart-gatekeeper/rssi/set` 수신 처리
  - Home Assistant MQTT Auto-Discovery에 **`number.ble_rssi_threshold` 슬라이더 엔티티 (-100 dBm ~ -50 dBm)** 6번째 등록
- `src/main.cpp`: 동적 `currentBleRssiThreshold` 적용 및 `updateBleRssiThreshold()` 구현으로 실전 튜닝 편의성 100% 확보

## [2026-07-24] fix | NimBLE Host 태스크 스택 오버플로우로 인한 반복 크래시(Load access fault) 근본 해결

- **근본 원인**: 스택 덤프 태스크 이름 `nimble_host` 확인 및 `MTVAL=0x40880001`(SRAM 경계 1바이트 초과)로 NimBLE Host 태스크 스택 오버플로우 확정
- **NimBLE 기본 스택 4KB(4096)** 환경에서 BLE `onResult` 콜백 내 Arduino `String` 객체 3개 생성 + `BLEUUID` 구조체 + `printf` 버퍼가 스택을 초과
- `platformio.ini`: `-DCONFIG_BT_NIMBLE_TASK_STACK_SIZE=8192` 빌드 플래그 추가 (4KB → 8KB)
- `src/main.cpp`: BLE 콜백 내 모든 `String` 객체를 C 문자열 직접 비교(`strcmp`, `strstr`, `strcasecmp`)로 교체하여 스택 사용량 대폭 축소
- `src/main.cpp`: `len >= 16` 가드 추가로 `memcmp` 루프 언더플로우 방지
- `partitions_16MB_ota.csv`: 64KB coredump 파티션(0xFF0000) 추가로 향후 사후 분석(post-mortem) 지원
- `MqttManager.cpp`: 불필요한 FreeRTOS `mqttMutex` 락 코드 100% 제거 (단일 스레드 환경에서 오히려 TLS 소켓 타이밍 교란 유발)

## [2026-07-25] compile | v2.0 아키텍처 전면 개편 — BLE Beacon Advertiser + MQTT Pre-arm 설계 확정

### 변경 사유

1. **스마트폰 배터리 효율 극대화**
   - 기존(v1.x): ESP32-C6가 BLE 스캐너로서 스마트폰이 항상 BLE 패킷을 광고해야 했음 → 스마트폰 배터리 지속 소모
   - 신규(v2.0): ESP32-C6가 비콘을 상시 발신 → 스마트폰은 비콘 수신 시에만 반응 → 배터리 소모 대폭 절감

2. **외부 진입 전용 동선 최적화**
   - 출입문 외부에 비콘을 발신하여 외부 접근자만 인증 흐름 진입 가능
   - NAS 인증 후 MQTT Pre-arm → ToF 조건부 활성화로 미인증 접근자 완전 차단

3. **보안 강화**
   - 인증 경로: 스마트폰 → NAS HTTPS → MQTT MQTTS → ESP32 (다층 암호화)
   - IDLE 상태에서 ToF 완전 비활성 → 물리적 관찰(ToF 레이저 스캔)에 의한 부정 진입 차단

### v2.0 설계 확정 내역

- **아키텍처**: ESP32-C6 BLE Advertiser (Non-connectable) + MQTT Pre-arm + 조건부 ToF 출입 통제
- **인증 흐름**: 스마트폰 비콘 수신 → NAS FastAPI POST → NAS MQTT Publish(gatekeeper/arm) → ESP32 ToF 활성화 → 50cm 감지 → 릴레이 개방
- **FSM 상태 변경**: `IDLE / VERIFYING / RELAY_HOLD / COOLDOWN` → `IDLE / ARMED / RELAY_HOLD / COOLDOWN`

### 변경 파일 목록

- `wiki/architecture.md`: v2.0 시퀀스 다이어그램 전면 재작성, 실외 ToF 태양광 IR 간섭 주의사항 추가
- `include/config.h`:
  - **삭제**: `BLE_TARGET_UUID`, `BLE_RSSI_THRESHOLD`, `BLE_VALID_MS`
  - **추가**: `GATEKEEPER_BEACON_UUID`, `PRE_ARM_DURATION_MS = 60000`, `MQTT_TOPIC_ARM = "gatekeeper/arm"`, `BLE_ADV_INTERVAL_MS = 100`
  - **버전**: `FIRMWARE_VERSION 1.0.0 → 2.0.0`
- `platformio.ini`: `h2zero/NimBLE-Arduino @ ^1.4.3` 라이브러리 추가
- `include/MqttManager.h`: `publishBleRssi()` 제거, `publishTelemetry()` 시그니처에 `is_armed` 파라미터 추가
- `src/MqttManager.cpp`:
  - `gatekeeper/arm` 토픽 구독 추가 (MQTT 연결 시 자동 subscribe)
  - `callback()`: arm 토픽 수신 시 JSON/단순 문자열 파싱 후 `triggerArm()` extern 호출
  - HA Auto-Discovery: Pre-arm 활성화 Binary Sensor, 잔여 시간 Sensor 엔티티 2개 추가
  - `publishBleRssi()` 완전 제거
- `src/main.cpp`:
  - BLE 스캐너 관련 코드 전체 제거 (`BleScanCallbacks`, `BLEScan*`, `onScanComplete`, `BLEDevice` Bluedroid 포함)
  - `NimBLEDevice` 기반 Beacon Advertiser 초기화 (`initBleAdvertiser()`) 추가
  - Tx Power: `ESP_PWR_LVL_P9` (+9 dBm, 실외 10~15m 도달)
  - Non-connectable 광고 모드 설정 (`BLE_HCI_ADV_TYPE_ADV_NONCONN_IND`)
  - `triggerArm()` 함수 구현 (extern linkage, MqttManager 콜백에서 호출)
  - FSM `ARMED` 상태 도입: `is_armed == true && arm 유효 시간 이내`에서만 ToF 측정 활용
  - `is_armed = false` 초기화: ToF 50cm 감지 즉시 (단발 소비) + PRE_ARM_DURATION_MS 만료 시
  - NAS HTTPS 직접 호출(`requestNASVerification()`) 완전 제거
  - BLE RSSI 관련 변수(`last_ble_detected_time`, `last_target_ble_rssi`, `currentBleRssiThreshold`) 전체 제거

## [2026-07-25] fix | NimBLE-Arduino IDF5 호환성 에러 해결 — 내장 Bluedroid BLE Advertiser로 전환

- **문제**: `h2zero/NimBLE-Arduino @ 1.4.3`이 `framework-arduinoespressif32 3.3.9 (IDF 5.5)` 와 API 충돌
  - `MYNEWT_VAL_BLE_TRANSPORT_ACL_SIZE` 등 IDF5 신규 상수 미선언 에러 다수 발생
  - NimBLE 1.4.x는 IDF 4.x 대상으로 개발되어 IDF 5.x 호환 불가
- **해결**: `NimBLE-Arduino` 의존성 제거 → Arduino-ESP32 3.3.9 내장 **Bluedroid BLE 라이브러리** 사용
  - `#include <BLEDevice.h>`, `<BLEAdvertising.h>`, `<BLEUtils.h>` (추가 라이브러리 불필요)
  - `BLEDevice::init()`, `BLEDevice::setPower(ESP_PWR_LVL_P9, ESP_BLE_PWR_TYPE_ADV)` 사용
  - `ADV_TYPE_NONCONN_IND` enum은 사용자 소스에서 헤더 직접 include 불가 → 리터럴 `0x03`으로 대체
  - `ConfigManager::getBleRssiThreshold()` / `setBleRssiThreshold()` 함수 제거 (config.h에서 `BLE_RSSI_THRESHOLD` 삭제됨)
- **결과**: `[SUCCESS]` ✅ — RAM 14.6% (47,968B / 327,680B), Flash 22.0% (1,613,222B / 7,340,032B)

## [2026-07-25] code | 백엔드 v2.0 업데이트 — MariaDB 실제 연동 + MQTT Pre-arm 발행

### 변경 내용

- `backend/app/main.py`:
  - **더미 로직 완전 제거** → MariaDB `tenants` 테이블 실제 조회로 교체
  - **인증 성공 시 `publish_arm_to_mqtt()` 호출** → MQTT `gatekeeper/arm` 토픽 발행
    - 페이로드: `{"action": "arm", "user": "홍길동", "tenant_id": 1, "issued_at": "..."}`
    - MQTTS (TLS) 지원 (`MQTT_USE_TLS=true`), 시놀로지 NAS 자체 서명 인증서 허용
  - **`_log_access()` 헬퍼**: 모든 출입 시도를 `access_logs` 테이블에 자동 기록
  - **인증 체계**:
    - 미등록 MAC → `granted: false` + 로그 기록
    - 비활성화 세입자 (`is_active=false`) → `granted: false`
    - `auth_key` 불일치 (선택 검증) → `granted: false`
    - 모든 조건 통과 → `granted: true` + MQTT arm 발행
  - `lifespan` 핸들러로 기동/종료 로그 출력
  - `auth_method` DB 기록값: `BLE` → `BLE_BEACON`으로 변경 (v2.0 방식 구분)
  - `arm_published` 필드 응답에 추가 (앱에서 arm 발행 성공 여부 확인 가능)
- `backend/app/requirements.txt`: `paho-mqtt>=2.0.0` 추가
- `backend/docker-compose.yml`: `api` 서비스에 MQTT 환경변수 6개 추가
  - `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`, `MQTT_USE_TLS`, `MQTT_TOPIC_ARM`
- `backend/.env.example`: MQTT 설정 포함 환경변수 템플릿 신규 생성

## [2026-07-25] code | GitHub Actions 백엔드 자동 배포 파이프라인 추가 (SSH → 시놀로지 NAS)

- `.github/workflows/deploy.yml`:
  - **Job 1 (기존 유지)**: 펌웨어 빌드 → SFTP OTA 배포, 버전 `1.0.0` → `2.0.0` 업데이트
  - **Job 2 (신규)**: `backend/` 디렉토리 변경 감지 시에만 실행
    - `webfactory/ssh-agent` 액션으로 SSH 키 로드
    - NAS SSH 접속 → `git pull origin main` → `docker compose up -d --build`
    - `curl` 헬스 체크로 배포 성공 여부 자동 검증 (30초 재시도, HTTP 200 확인)
  - **필요한 신규 GitHub Secrets**:
    - `NAS_SSH_KEY` — NAS 접속용 SSH 개인키 (PEM 형식)
    - `NAS_BACKEND_DIR` — NAS의 backend 경로 (예: `/volume1/docker/smart-gatekeeper/backend`)
    - `BACKEND_HEALTH_URL` — 헬스 체크 URL (예: `https://tworimpa.synology.me:4443/health`)
  - **설계 원칙**: 백엔드 무관 커밋(펌웨어 전용)에서는 Job 2 실행 안 함 (불필요한 재시작 방지)

## [2026-07-25] fix | BLE 비콘 광고 모드를 ADV_TYPE_SCAN_IND (0x02)로 전환하여 nRF Connect 디바이스 이름 노출 🟢

- `src/main.cpp`:
  - 기존 `ADV_TYPE_NONCONN_IND` (`0x03`)는 BLE 규격상 `SCAN_REQ`에 응답하지 않아 Scan Response에 포함된 디바이스 이름(`SmartGatekeeper`)이 스마트폰에 전송되지 않음
  - `ADV_TYPE_SCAN_IND` (`0x02`)로 전환하여 스캔 요청 수신 시 Scan Response로 디바이스 이름(`SmartGatekeeper`) 정상 응답하도록 수정
  - 연결(`CONNECT_REQ`)은 여전히 차단되어 비연결 보안 모드는 유지됨

## [2026-07-25] compile | wiki/mobile_app_scenario.md 생성 — Step 6 모바일 앱(Smart Key) 공식 시나리오 기획서 작성

- **신규 생성**: `wiki/mobile_app_scenario.md` (Step 6 세입자용 모바일 어플리케이션 개발 기획서)
- **핵심 아키텍처**: Entry-Only (외부 진입 전용) 및 Target BLE Beacon Continuous Broadcast (Role Reversal)
- **포함 요소**:
  - 시스템 개요 및 역발상 아키텍처 철학 (스마트폰 배터리 절감, 스푸핑 차단 보안)
  - 컴포넌트별 주요 역할 (App, Synology NAS Backend, ESP32-C6 Target)
  - 5단계 핵심 사용 시나리오 (설치/권한요청 ➔ 권한승인 ➔ Walk-through 자동 개방 ➔ 수동 원격개방 ➔ 권한회수) 및 Sequence Diagram
  - 신규 필요 REST API 명세 (`/api/v1/user/*`, `/api/v1/door/*`) 및 MQTT 토픽 명세 (`gatekeeper/arm`, `gatekeeper/force_open`, `gatekeeper/status`, `gatekeeper/event`)
- **wiki/index.md 업데이트**: Category: Architecture & Planning 카테고리에 신규 기획서 등록

## [2026-07-25] compile | wiki/mobile_app_scenario.md 업데이트 — Flutter 하이브리드 Zero-Update 아키텍처 반영

- **기획서 전면 업데이트**: `wiki/mobile_app_scenario.md`
- **Flutter 하이브리드 아키텍처 (Thin Client + WebView)**:
  - **Native Shell (Flutter)**: 백그라운드 BLE 비콘 스캐닝 Engine, OS 권한 관리, FCM 푸시 수신, `/api/v1/config` 백엔드 동적 설정 조회 (Remote Config)
  - **WebView UI (Hosted on Synology NAS)**: 사용자 화면 전체 (가입 신청, 승인 상태, 수동 '문 열기' 버튼 등). 백엔드 소스 수정으로 앱 업데이트 없는 Zero-Update 구현
- **신규 REST API 명세 확장**: Native Shell 동적 설정 반환용 `GET /api/v1/config` 명세 및 중요성 명시
- **5단계 시나리오 업데이트**: Native Shell ↔ WebView 분리 동작 흐름 및 Sequence Diagram 세분화

## [2026-07-25] code | gatekeeper_app 신규 생성 — Flutter 하이브리드 앱 뼈대 및 권한 세팅 완료

- **프로젝트 생성**: `gatekeeper_app/` (Flutter 프로젝트 구조)
- **`pubspec.yaml` 의존성 패키지 구성**:
  - `flutter_blue_plus` (BLE 비콘 스캔 엔진)
  - `webview_flutter` (NAS 호스팅 웹 화면 렌더링)
  - `permission_handler` (OS 위치, BLE, 푸시 권한 관리)
  - `http` (백엔드 Pre-arm REST API 및 Remote Config 조회)
- **네이티브 권한 세팅**:
  - `android/app/src/main/AndroidManifest.xml`: `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`, `ACCESS_FINE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`, `INTERNET` 추가
  - `ios/Runner/Info.plist`: `NSBluetoothAlwaysUsageDescription`, `NSLocationAlwaysAndWhenInUseUsageDescription` 등 추가
- **핵심 소스코드 구축**:
  - `lib/main.dart`: OS 권한 자동 요청 및 싱글톤 초기화 후 WebView 렌더링 진입점
  - `lib/services/ble_scanner.dart`: `flutter_blue_plus` 기반 백그라운드 비콘 감지, `/config` 동적 설정 로드, 30초 쿨다운 제어 및 `POST /api/v1/door/prearm` API 연동 싱글톤
  - `lib/screens/web_view_screen.dart`: `webview_flutter` 기반 NAS 웹 UI (`https://tworimpa.synology.me:4442/app`) 전면 렌더링 위젯

## [2026-07-25] code | gatekeeper_app Docker 격리 빌드 환경 구축 완료

- **`gatekeeper_app/Dockerfile`**: `ubuntu:22.04` 기반 OpenJDK 17 + Android SDK (API 33, build-tools 33.0.2) + Flutter SDK (stable) 빌드 이미지 구성
- **`gatekeeper_app/docker-compose.yml`**: `flutter-builder` 컨테이너 정의 및 `./:/workspace` 볼륨 마운트
- **`gatekeeper_app/BUILD_GUIDE.md`**: 도커 기동 ➔ 컨테이너 접속 ➔ APK 빌드 명령어 및 생성 가이드 작성

## [2026-07-25] code | GitHub Actions Flutter APK 클라우드 자동 빌드 파이프라인 추가

- **`.github/workflows/build_app.yml` 신규 생성**:
  - `gatekeeper_app/` 소스 변경 감지 시 클라우드(Ubuntu 릴레이 러너)에서 Flutter APK 자동 빌드
  - JDK 17 + Flutter SDK setup + `flutter pub get` + `flutter build apk --release` 실행
  - 빌드 완료된 `app-release.apk` 파일을 GitHub Artifacts로 자동 업로드 (클릭 한 번으로 APK 다운로드 지원)

## [2026-07-25] fix | CI/CD build_app.yml 및 settings.gradle.kts 수정 — GitHub Actions 빌드 실패 예방

- **원인 분석**: `.gitignore`에 등록된 `android/local.properties` 파일이 CI 환경(GitHub Actions Runner)에 존재하지 않아 `settings.gradle.kts`에서 `FileNotFoundException` 발생 및 빌드 중단
- **수정 내용**:
  - `gatekeeper_app/android/settings.gradle.kts`: `local.properties` 존재 여부 안전 검사(`exists()`) 추가 및 `FLUTTER_ROOT` / `FLUTTER_HOME` 환경변수 폴백 연동
  - `.github/workflows/build_app.yml`: Android 라이선스 자동 승인 단계 (`yes | flutter doctor --android-licenses || true`) 추가

## [2026-07-25] code | CI/CD 시놀로지 NAS APK 자동 업로드 및 앱 버전 검사 기능 구축

- **`.github/workflows/build_app.yml` SFTP 연동**:
  - 빌드 완료된 APK 파일명을 `ks-house-gatekeeper.apk`로 변경
  - `dist/version.json` 메타데이터 자동 생성 (`version`, `build_number`, `commit`, `apk_url`, `updated_at`)
  - 시놀로지 NAS 타겟 디렉토리(`docker/smartbox_ota/gatekeeper_apk`)로 SFTP 자동 업로드 배포
  - CI build step에 `--dart-define=APK_VERSION_URL` / `--dart-define=APK_DOWNLOAD_URL` 주입
- **`gatekeeper_app` 동적 업데이트 서비스 구축**:
  - `lib/services/update_checker.dart` 신규 작성 (`package_info_plus`, `url_launcher` 연동)
  - 소스코드 내 raw URL 하드코딩 완전 방지 (`String.fromEnvironment` & 백엔드 `/config` Remote Config 연동)
  - `lib/screens/web_view_screen.dart`: 앱 구동 시 최신 APK 업데이트 안내 배너 및 1-Click 외부 브라우저 다운로드 버튼 탑재

## [2026-07-25] code | CI/CD build_app.yml — App FULL_VERSION 동적 동기화 적용

- **`FULL_VERSION` 동적 계산**: `1.0.0-g${SHORT_SHA}` 포맷으로 커밋 SHA 기반 동적 버전 생성 및 GITHUB_ENV 저장
- **Flutter Build 명시**: `flutter build apk --build-name="${FULL_VERSION}" --build-number=${{ github.run_number }}` 주입
- **`dist/version.json` 업데이트**: `"version": "${{ env.FULL_VERSION }}"` 동기화 적용

## [2026-07-25] code | 백엔드 호스팅 WebView 웹 어플리케이션(index.html) 및 REST API 구현 완료

- **`backend/app/static/index.html` 신규 구축**:
  - 모바일 WebView 전용 리치 웹 어플리케이션 UI (Glassmorphism, Dark Mode, Pulse 릴레이 개방 버튼)
  - 세입자 승인 상태 카드, 원격 문 열기 수동 조작 UI, 가입 신청 폼 및 최근 출입 이력 컴포넌트 포함
- **`backend/app/main.py` 기능 확장**:
  - `GET /app`: WebView 메인 화면 반환 (Static HTML 라우트)
  - `GET /api/v1/config`: Remote Config 제공 (`beacon_uuid`, `cooldown_sec`, `apk_version_url`, `apk_download_url`, `webview_url`)
  - `POST /api/v1/user/request`: 세입자 권한 가입 신청 API
  - `POST /api/v1/door/prearm`: 비콘 감지 사전 승인 MQTT arm 발행 API
  - `POST /api/v1/door/open`: WebView 수동 문 열기 MQTT force_open 발행 API

## [2026-07-25] code | 관리자 콘솔 대시보드(admin.html) 및 관리자 전용 REST API 구축

- **`backend/app/static/admin.html` 신규 구축**:
  - 건물 관리자 전용 웹 대시보드 UI (실시간 통계, 세입자 승인/권한 회수 테이블, 전체 출입 Audit Logs, 마스터 원격 문 열기)
- **`backend/app/main.py` 관리자 라우트 추가**:
  - `GET /admin`: 관리자 콘솔 웹페이지 반환
  - `GET /api/v1/admin/tenants`: 전체 세입자 및 승인 대기 세입자 목록 조회
  - `POST /api/v1/admin/tenants/{id}/approve`: 세입자 출입 권한 즉시 승인 (`is_active = true`)
  - `POST /api/v1/admin/tenants/{id}/reject`: 세입자 출입 권한 회수 (`is_active = false`)

## [2026-07-25] fix | 백엔드 수동 배포 방식으로 변경 (deploy_backend.yml 제거)

- **배포 방식 변경**: NAS 권한 이슈로 인해 `deploy_backend.yml` 워크플로우 제거. 백엔드 및 관리자 UI는 사용자가 NAS 상에서 수동으로 `git pull origin main && docker compose up -d --build api` 실행하여 배포 진행.
- **`backend/docker-compose.yml` 바인드 볼륨 연동**: `api` 서비스에 `./app:/app` 볼륨 마운트를 추가하여, `git pull` 시 이미지 재빌드 없이 소스코드/정적UI(`admin.html`, `index.html`)가 컨테이너에 즉시 동기화되도록 개선.
- **`backend/app/main.py` 예외 처리 보강**: `paho.mqtt` 패키지 구버전 미설치 시 구동 중단 방지를 위한 `try...except ImportError` 예외 처리 추가.

## [2026-07-25] fix | include/secrets.h & deploy.yml 백슬래시 경고(backslash-newline at end of file) 제거

- **원인 분석**: `include/secrets.h` 파일 생성 및 자동 포맷팅 시 `#define SECRET_APK_DOWNLOAD_URL` 구문이 80자 라인 분할 백슬래시(`\`)와 함께 `#endif` 외부 파일 끝으로 밀려나 GCC 컴파일러 경고 발생
- **수정 내용**:
  - `include/secrets.h` 및 `include/secrets.h.example`: 모든 매크로를 단일 라인 단독 선언으로 정렬하고 `#ifndef ... #endif` 가드 내부로 정돈
  - `.github/workflows/deploy.yml`: CI secrets.h 생성 단계에 `SECRET_APK_VERSION_URL` 및 `SECRET_APK_DOWNLOAD_URL` 매크로 추가

## [2026-07-26] fix | 모바일 앱 최초 인증 흐름 구축, 문 열기 API 연동 및 Android 11+ APK 다운로드 패치

- **`gatekeeper_app/android/app/src/main/AndroidManifest.xml`**:
  - Android 11+ (API 30+) 패키지 공개성 제약 해결을 위한 `<queries>` 인텐트 요소(`https`, `http` 외부 스킴) 추가
- **`gatekeeper_app/lib/screens/web_view_screen.dart` & `update_checker.dart`**:
  - WebView 내 `.apk` 다운로드 링크 클릭 시 `onNavigationRequest`에서 감지하여 외부 기본 브라우저로 1-Click 다운로드 전환 실행
  - `url_launcher` 실행 시 `externalApplication` ➔ `inAppBrowserView` ➔ `platformDefault` 순차 다중 Fallback 적용하여 Android APK 다운로드 예외 완전 방어

- **`backend/app/static/index.html` & `main.py`**:
  - 최초 접속 시 디바이스 고유 식별자(`device_id`) 자동 생성 및 세입자 동적 인증 상태 머신 구축
  - 미등록 세입자 ➔ 최초 세입자 출입 신청 폼 제공 (`POST /api/v1/user/request`)
  - 승인 대기 세입자 ➔ `⏳ 승인 대기 중` 안내 및 문 열기 버튼 비활성화
  - 승인 완료 세입자 ➔ 실제 이름/호수 표출 및 `문 열기` 활성화 ➔ `POST /api/v1/door/open` 실행하여 MQTT force_open 메시지 발신

## [2026-07-26] fix | ESP32-C6 MqttManager gatekeeper/force_open 토픽 구독 추가 및 비콘 스캔 UUID 동기화

- **`src/MqttManager.cpp` (ESP32-C6)**:
  - 브로커 연결 시 `client.subscribe("gatekeeper/force_open")` 구독 누락을 수정 ➔ 앱 문열기 버튼 클릭 시 수동 릴레이 개방 반응 완벽 작동
- **`gatekeeper_app/lib/services/ble_scanner.dart` (Flutter)**:
  - 기본 타겟 비콘 UUID를 `a1b2c3d4-e5f6-7890-abcd-ef1234567890` (ESP32-C6 상시 비콘 UUID)로 동기화 ➔ 모바일 비콘 감지 및 자동 Pre-arm 연동 완결
- **`backend/app/main.py` & `backend/docker-compose.yml`**:
  - `MQTT_HOST` 기본값을 빈값(`""`)에서 `tworimpa.synology.me`, 포트를 `4883`(MQTTS 포트)으로 설정하여 `.env` 누락 시에도 `gatekeeper/arm` 메시지 발행이 즉시 동작하도록 보강
  - FastAPI 구동 시 `paho-mqtt` 미설치 감지 시 자동으로 `pip install paho-mqtt==1.6.1`을 수행하는 동적 런타임 자가 치유(Self-healing) 로직 도입
  - MariaDB 컨테이너 `healthcheck` 명령어를 `mariadb-admin ping`으로 교체하고 초반 부팅 타임아웃 지연 완화
  - `POST /api/v1/door/prearm` 라우트 복구 및 MQTT 발행 시 Docker 게이트웨이(`172.17.0.1:1883`) 초고속 우선 접속 ➔ 5.4초 지연 ➔ 0.001초(1ms)로 완벽 개선

- **`src/MqttManager.cpp` (ESP32-C6)**:
  - `MqttManager::callback` 내 `gatekeeper/force_open` 전용 분기 처리 추가 ➔ 수동 원격 개방 메시지 수신 시 `triggerManualDoorOpen()` (릴레이 1초 개방) 확실한 구동 완결

## [2026-07-26] feat | 모바일 앱 안드로이드 포그라운드 상주 서비스(Foreground Service) 구축 (화면 OFF / 주머니 속 자동 출입문 감지 지원)

- **`gatekeeper_app/pubspec.yaml`**: `flutter_foreground_task: ^6.2.0` 의존성 추가
- **`gatekeeper_app/android/app/src/main/AndroidManifest.xml`**:
  - `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_CONNECTED_DEVICE`, `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, `POST_NOTIFICATIONS` 권한 및 Service 컴포넌트 선언
- **`gatekeeper_app/lib/services/foreground_service.dart`**:
  - 화면이 꺼지거나 주머니 속 잠금 상태에서도 안드로이드 Doze Mode를 극복하고 24시간 BLE 비콘 스캐너를 백그라운드에서 지속 유지하는 포그라운드 서비스 및 알림창 헬퍼 구축
- **`backend/app/main.py` & `backend/docker-compose.yml`**:
  - 타사 포트 `4443` 차단 이슈 극복을 위해, 웹뷰가 정상 구동 중인 동일 포트(`4442`)에서 `GET /api/v1/download/apk` 및 `/gatekeeper_apk/ks-house-gatekeeper.apk` 직접 서비스 추가 ➔ 헤더 `application/vnd.android.package-archive` 명시
  - `docker-compose.yml` 내 `/volume1/docker/smartbox_ota/gatekeeper_apk` 시놀로지 NAS 절대 경로 볼륨 바인딩 추가
  - `POST /api/v1/door/prearm` 내 `device_id` 세입자 DB 승인 여부(`is_active=true`) 검증 게이트 추가 ➔ 미승인/미등록 기기 접근 시 `403 Forbidden` (`[PREARM-REJECT]`) 거부 처리로 보안 강화

## [2026-07-26] feat | 모바일 하드웨어 영구 고유 식별자(ANDROID_ID) 도입 (앱 재설치 시 세입자 승인 유지)

- **`gatekeeper_app/lib/services/device_id_service.dart`**:
  - `device_info_plus` 기반 안드로이드/iOS 하드웨어 고유 ID (`ANDROID_ID`) 추출 및 `SharedPreferences` 영구 보존 싱글톤 구축
- **`gatekeeper_app/lib/screens/web_view_screen.dart` & `gatekeeper_app/lib/services/ble_scanner.dart`**:
  - 웹뷰 로드 시 `?device_id=DEV-ANDROID_ID` URL 파라미터 주입 및 `POST /api/v1/door/prearm` 호출 시 `device_id` 전송 ➔ 앱 재설치 시에도 세입자 식별자 100% 동일 유지
- **`gatekeeper_app/pubspec.yaml`**: `shared_preferences: ^2.2.3` 명시적 의존성 선언 추가
- **`gatekeeper_app/lib/services/device_id_service.dart`**: `device_info_plus` 패키지 패스 `.dart` 확장자 누락 오기 정정 ➔ GitHub Actions CI 빌드 정상화 완결

## [2026-07-26] feat | 엔지니어 원격 튜닝(Engineer Remote Calibration & Tuning System) 구축

- **`include/config.h` & `src/main.cpp` & `src/MqttManager.cpp` (Target)**:
  - `gatekeeper/config/tx_power`, `gatekeeper/config/tof_distance`, `gatekeeper/config/duration` MQTT 구독 및 콜백 처리 추가
  - `setTxPower()`, `setTofDistanceCm()`, `setPreArmDurationMs()` 동적 세터 추가하여 실시간 파라미터 적용 지원
- **`backend/app/main.py` (NAS Backend)**:
  - `AdminConfigRequestSchema` 및 `POST /admin/config` REST API 추가하여 원격 튜닝 요청 수신 시 MQTT 토픽 즉시 릴레이 발행
- **`gatekeeper_app` (Flutter Shell App)**:
  - `lib/screens/debug_screen.dart` 신규 생성: 실시간 비콘 RSSI 대형 텍스트 모니터, 동적 RSSI Threshold 슬라이더, 쿨다운 무시 체크박스, Target 원격 튜닝 전송 폼 탑재
- **`smart-gatekeeper Target (ESP32-C6 Firmware)`**:
  - Target 웹 접속 시 주변 Wi-Fi 스캔 및 설정 변경 불능 버그 완전 해결:
    - `WifiManager`: `startWebServer()` 모듈화로 STA 연결 성공 시에도 로컬 IP(192.168.x.x) WebServer(Port 80) 상시 구동 및 개방
    - Wi-Fi 스캔 (`/scan`): `WiFi.scanNetworks(false, false, false, 150)` 채널별 액티브 스캔 적용으로 STA 연결 중에도 주변 AP 실시간 수집 목록(SSID, RSSI) JSON 제공
    - 웹 UI 대시보드 개편: 현재 Wi-Fi 연결 상태(SSID/IP) 뱃지, 주변 AP 실시간 재검색 & 변경 폼, 엔지니어 원격 튜닝 파라미터(Tx Power, ToF 거리, Pre-arm 유효시간) NVS 저장 폼 제공
- **`smart-gatekeeper Target (ESP32-C6 Firmware) & App & NAS Backend`**:
  - Target 릴레이 쿨다운 및 모바일 앱 비콘 쿨다운 수치 단축 및 2-Way 원격 설정 구축:
    - **Target 보드**: 릴레이 쿨다운 기본값 **3초**(3,000ms)로 단축, `g_relay_cooldown_ms` 동적 변수화 및 ESP32 NVS Flash (`relay_cool`) 영구 저장 연동
    - **모바일 앱**: 비콘 API 쿨다운 기본값 **10초**로 단축 (`cooldownSeconds = 10`), 디버그 화면에 앱 쿨다운(1~30초) 및 Target 릴레이 쿨다운(1~10초) 조절 슬라이더 탑재
    - **MQTT 2-Way**: `gatekeeper/config/relay_cooldown` 구독 및 `gatekeeper/config/state` / `gatekeeper/config/set` JSON에 `relay_cooldown` 파라미터 양방향 동기화


- **`gatekeeper_app` (Flutter Shell App) & Web Dashboard**:
  - 앱 하단 "Smart Key APK 최신버전 수동 다운로드" 버튼 동작 불능 해결:
    - **`web_view_screen.dart`**: WebView `onNavigationRequest` 필터에 `/download/apk` 및 `/download/` 경로 감지 로직 추가. 터치 시 internal WebView 인라인 바이너리 렌더링 시도를 차단하고 `LaunchMode.externalApplication` (크롬/기본 브라우저)으로 시그널 전환 하달
    - **`index.html`**: 수동 다운로드 앵커 태그에 `target="_blank" download="ks-house-gatekeeper.apk"` 속성 명시
    - **`main.py`**: `/download/apk` 및 `/api/v1/download/ks-house-gatekeeper.apk` 라우팅 라우트 추가
  - 상단 포그라운드 상주 알림(Notification) 실시간 상태 불일치 버그 완벽 수정:
    - **`ble_scanner.dart`**: `_updateNotification` 헬퍼 메서드 추가. 비콘 신호 끊김(2.5초 타임아웃) 시 `🔴 Target 비콘 연결 안됨 (탐색 중)`으로 즉시 변경, 신호 약함(`🟡`), 쿨다운 중(`⏳`), 승인 완료(`🟢`), 거부됨(`⛔`) 등 모든 상태 변화 시 알림 메시지가 실시간으로 갱신되도록 보장
    - **`foreground_service.dart`**: 기본 서비스 시작 문구를 탐색 중 안내로 초기화
















- **`gatekeeper_app/android/app/upload-keystore.jks` & `.github/workflows/build_app.yml`**:
  - 보안 강화: 바이너리 `.jks` 키스토어 파일의 Git 추적 제외(`git rm --cached`, `.gitignore`) 및 GitHub Secrets(`ANDROID_KEYSTORE_BASE64`) 주입 동적 복원 구조 개편 완료

## [2026-07-26] code | ToF(VL53L0X) 센서 제거 및 AJ-SR04T(JSN-SR04T) 방수 초음파 센서 교체 전면 리팩토링

- **`smart-gatekeeper Target (ESP32-C6 Firmware)`**:
  - 기존 I2C 기반 VL53L0X ToF 센서 관련 라이브러리(`pololu/VL53L0X`), `Wire.begin()`, I2C 핀(GPIO 6, 7, 10) 및 `ToFSensor` 클래스 완전 제거
  - `AJ-SR04T` (JSN-SR04T) 방수 초음파 센서 드라이버 신규 구축 (`include/UltrasonicSensor.h`, `src/UltrasonicSensor.cpp`)
  - 핀 정의: `PIN_TRIG` = GPIO 10 (OUTPUT), `PIN_ECHO` = GPIO 11 (INPUT) — 스트래핑 및 USB 예약 핀 완전 회피
  - **맹점 (Blind Zone) 방어 (0 ~ 20cm)**: 초음파 트랜스듀서 진동 잔향 난반사 구간(0~19.9cm)은 노이즈로 간주하고 무시 (`-1.0f` 반환)
  - `pulseIn(ECHO_PIN, HIGH, 30000UL)` 30ms 비블로킹 타임아웃 적용으로 시스템 무한 멈춤 완전 방지
  - **전력 절감 FSM 연동**: `is_armed == true` (MQTT Pre-arm 사전 승인) 상태에서만 초음파 센서 핑 발사
  - 감지 임계 거리 (`distance_threshold`, 기본값 50cm) 조건 충족 시 릴레이 1초 ON 후 즉시 `is_armed = false` 무장 해제
  - MQTT 토픽 명칭 정리: `gatekeeper/config/tof_distance` ➡️ `gatekeeper/config/distance_threshold` (하위 별칭 호환 유지)
- **`backend/app/main.py` & `gatekeeper_app` & `wiki/pin_mapping.md`**:
  - 백엔드, 모바일 앱 디버그 화면(20~150cm 슬라이더), 핀 매핑 위키 문서 초음파 규격으로 통합 동기화 완료

































## [2026-07-28] code | Real-time ultrasonic sensor monitoring via MQTT

- Updated `src/main.cpp` to continuously read the ultrasonic sensor instead of only reading it during the ARMED state.
- Changed the MQTT telemetry publish interval from 10 seconds to 1 second to support real-time dashboard monitoring.
- Made sure that the valid trigger threshold check still works properly.
## [2026-07-28] fix | Ultrasonic sensor default value and BLE beacon parsing

- **Ultrasonic Sensor 0cm Issue**: Fixed an issue where the ultrasonic sensor returned `0` when no object was detected or the reading timed out. Updated `src/UltrasonicSensor.cpp` to return `999.0f` on timeout or out of bounds (blind zone). Updated `src/main.cpp` telemetry logic to send `9990` mm instead of `0` when `distCm <= 0.0f`.
- **BLE Beacon Payload Truncation**: Fixed an issue in `src/main.cpp` where the iBeacon payload string was inadvertently truncated at the first null byte due to the use of `.c_str()` when constructing `strServiceData`. Replaced `.c_str()` with explicit string length constructor `std::string(beaconData.c_str(), beaconData.length())` to preserve the full raw binary payload.
## [2026-07-28] fix | Ultrasonic sensor distance accuracy and raw info via MQTT

- Adjusted the speed of sound calculation in `UltrasonicSensor.cpp` to `0.0343` (at 20°C) instead of `0.034` for improved accuracy.
- Increased the trigger pulse from 10µs to 20µs for better stability with the AJ-SR04T sensor.
- Modified `UltrasonicSensor::readDistanceCm()` to output the raw duration in microseconds.
- Added `MqttManager::publishSensorInfo()` to send `duration_us` and `distance_cm` to a new `smart-gatekeeper/sensor/ultrasonic` MQTT topic.
- Modified `main.cpp` to call `publishSensorInfo()` and log the raw info during the 1-second interval loop.

## [2026-07-28] fix | AJ-SR04T 501mm (2.9ms Ghost Read) Out-of-Range Timeout Filter

- **Ghost Read Filter**: Fixed AJ-SR04T / JSN-SR04T hardware bug where the module outputs a fixed ~2.92ms (2880~2950µs / ~501mm) pulse when no obstacle is present (Out of Range). Added exception filtering in `UltrasonicSensor.cpp` to return `999.0f` for this specific duration range.
- **MQTT Out-of-Range Handling**: Updated `src/main.cpp` to map distances >= 900cm or `999.0f` to `9990` mm (999 cm) in `smart-gatekeeper/status` MQTT telemetry.

## [2026-07-28] fix | Port 5-point Median Filter & Expand Jitter Guard (440~569mm)

- **Ghost Read Jitter Guard**: Expanded AJ-SR04T / JSN-SR04T hardware out-of-range pulse filter range to 2570~3320µs (~440mm to ~569mm, e.g., 470mm, 500mm, 543mm) in `UltrasonicSensor.cpp`.
- **5-point Median Filter**: Ported the 5-sample bubble-sort median filter pattern from `smartbox` into `UltrasonicSensor::readDistanceCm()` to eliminate noise jitter and guarantee stable `9990` mm (999 cm) output.

## [2026-07-28] code | Comprehensive Target Board Sensor & Config MQTT Auto Discovery (22 Entities)

- **Target Board Sensor & Diagnostic Auto Discovery**: Expanded Home Assistant MQTT Auto Discovery in `src/MqttManager.cpp` to register 9 real-time sensor & diagnostic entities (`distance_mm`, `distance_cm`, `state`, `ip`, `arm_remaining_s`, `wifi_rssi`, `free_heap`, `uptime_s`, `firmware`) and 2 binary sensors (`door_binary`, `pre_armed`).
- **NVS Config Control & Sensor Auto Discovery**: Registered 4 HA `number` control sliders (BLE Tx Power, Distance Threshold, Pre-arm Duration, Relay Cooldown) and 4 configuration state sensors to enable dynamic parameter tuning directly from HA UI.
- **Telemetry & Unit Handling**: Updated `publishTelemetry` to transmit full diagnostic metrics and real-time Pre-arm remaining time. Added unit conversion logic in MQTT callbacks to handle seconds <-> milliseconds for duration and cooldown settings.
- **Documentation**: Updated `wiki/architecture.md` (Section 5.4) and `wiki/log.md`. Verified clean build via `pio run -e esp32c6`.

## [2026-07-28] fix | Resolve iBeacon Null-Byte Payload Truncation & App Isolate Crash

- **Target Board iBeacon Payload Truncation Fix**: Updated `src/main.cpp` `setTxPower()` to use `oAdvertisementData.setManufacturerData(mfgData)` with explicit 25-byte length `std::string(beaconData.c_str(), beaconData.length())`. Eliminated `strlen` truncation at byte 3 (`0x00` in Apple Manufacturer ID `0x004C`), guaranteeing full over-the-air transmission of iBeacon UUID (`a1b2c3d4-e5f6-7890-abcd-ef1234567890`), Major, Minor, and Measured Power.
- **Mobile App Crash Prevention**: Added `onError` exception handler to `flutterBeacon.ranging().listen(...)` in `gatekeeper_app/lib/services/ble_scanner.dart` to catch transient stream errors cleanly. Added try-catch guards around `GatekeeperTaskHandler.onStart()` and `onRepeatEvent()` in `gatekeeper_app/lib/services/foreground_service.dart` to prevent dual background/main isolate native `BeaconManager.bind()` collision crashes.

## [2026-07-28] feat | Implement 2-Phase Low-Power OS iBeacon Monitoring & Wake-Up Architecture

- **OS iBeacon Region Monitoring (`monitoring`)**: Updated `gatekeeper_app/lib/services/ble_scanner.dart` to use `flutterBeacon.monitoring(regions)` for low-power OS-level region detection (`didEnterRegion` / `didExitRegion`). Idle notification displays `💤 Target 비콘 구역 수면 감시 중 (저전력 모드)`, keeping continuous high-frequency BLE scanning OFF when away from target.
- **Dynamic 2-Stage Ranging Transition**: Automatically triggers `_startRangingStream()` upon receiving OS `didEnterRegion` event, transitioning smoothly to `ranging` mode for real-time RSSI measurement and Pre-arm NAS verification (`POST /door/prearm`), returning to `monitoring` mode on region exit or timeout.

## [2026-07-28] fix | Resolve Native AltBeacon Stream Collision & HTTP Prearm Timeout Protection

- **Native AltBeacon Concurrent Modification Fix**: Fixed process crash ("앱 종료 및 상태창 사라짐 후 재시작") in `gatekeeper_app/lib/services/ble_scanner.dart` when approaching target beacon. Added active stream check `if (_streamRanging != null) return;` and `scheduleMicrotask()` in `_startRangingStream()` to prevent duplicate PlatformChannel subscription calls during native `didEnterRegion` callbacks.
- **HTTP Network Timeout & Back-end Guard**: Added 4-second timeout (`.timeout(const Duration(seconds: 4))`) to `http.post('/door/prearm')` in `_sendPrearmRequest()`, preventing network stalls or SSL handshake delays near the door from hanging the scanner.

## [2026-07-28] fix | Remove Ultrasonic Sensor 44~57cm Blackout Zone & Restore Continuous Sensing

- **Ultrasonic 44~57cm Jump to 999cm Bug**: Removed hardcoded duration filter `if (durationUs >= 2570UL && durationUs <= 3320UL) return 999.0f;` in `src/UltrasonicSensor.cpp`. This filter had been forcing valid physical distance readings between 44.0cm and 56.9cm to `999.0f` (999 cm). The existing 5-sample bubble-sort median filter (`history[5]`) handles transient hardware noise automatically while preserving continuous smooth distance measurement from 20cm to 400cm.

## [2026-07-28] fix | Resolve flutter_beacon_local Native NullPointer Crash & Add Native Safety Guards

- **Native NullPointerException Fix**: Added explicit null checks for `beacon.getId1()`, `beacon.getId2()`, and `beacon.getId3()` in `FlutterBeaconUtils.java`. Previously, when any non-iBeacon or malformed BLE packet was range-detected, calling `beacon.getId2().toInt()` caused a native Java `NullPointerException` on the main Looper thread, abruptly killing the Android app process.
- **Native Callback Exception Guard**: Wrapped `didRangeBeaconsInRegion` in `FlutterBeaconScanner.java` with try-catch blocks to catch and log any native AltBeacon exceptions cleanly without crashing the Android app.

## [2026-07-28] feat | Implement In-App Error Capture, Floating Banner & Real-Time Log Console

- **AppErrorLogger Service (`error_logger.dart`)**: Created singleton logger service capturing global `FlutterError.onError`, `PlatformDispatcher.instance.onError`, BLE scanner errors, and network exceptions.
- **In-App Floating Error Banner (`web_view_screen.dart`)**: Displays a real-time red glassmorphic notification banner at the top of the main screen whenever a runtime error or network exception occurs, allowing users/engineers to see the error message immediately on their phone.
- **Live Terminal Log Console (`debug_screen.dart`)**: Integrated a real-time terminal-style log console in the Engineer Debug Screen with copy/clear functions for viewing full system event streams and error tracebacks directly in the app.

## [2026-07-28] fix | Resolve Missing dart:ui Import in main.dart for PlatformDispatcher

- **CI/CD Build Failure Fix**: Added `import 'dart:ui';` to `gatekeeper_app/lib/main.dart` to resolve `undefined_identifier PlatformDispatcher` error during `flutter analyze` step in GitHub Actions run 30373139338.

## [2026-07-28] audit | Comprehensive App-Wide Crash Prevention Hardening

- **Null Guard in `ble_scanner.dart`**: Added `if (beacon.proximityUUID.isEmpty) return;` check in `_processBeacon()` to prevent `NoSuchMethodError` crashes on null/malformed BLE beacon UUIDs.
- **Startup Protection in `main.dart`**: Wrapped `_initializeApp()` in a `try...catch` block to guarantee `setState()` runs even if BLE or foreground service initialization encounters permission or hardware errors during boot.
- **Battery Optimization Guard in `foreground_service.dart`**: Wrapped `requestIgnoreBatteryOptimization()` in `try...catch` to prevent uncaught `PlatformException` crashes on restricted OEM Android ROMs (Xiaomi/Samsung).
- **Mounted Checks in `debug_screen.dart`**: Added `if (!mounted) return;` guards before every `setState()` in async callbacks to prevent `StateError: setState() called after dispose()` crashes.

## [2026-07-28] fix | Explicitly Enforce 100ms iBeacon Advertising Interval in main.cpp

- **BLE Advertising Interval**: Updated `src/main.cpp` `setTxPower()` to explicitly set `pAdv->setMinInterval(160);` and `pAdv->setMaxInterval(160);` (100ms in 0.625ms steps = Apple iBeacon standard interval / 10 times per second), guaranteeing fast BLE responsiveness without relying on default stack values.

## [2026-07-28] fix | Resolve Target Board UUID Byte Reversal & App UUID Normalization

- **Target Board UUID Reversal Fix**: Restored 16-byte byte reversal loop in `src/main.cpp` `setTxPower()`. Arduino-ESP32's `BLEBeacon` structure requires little-endian byte ordering internally to map to Apple's big-endian over-the-air iBeacon layout.
- **Mobile App UUID Normalization**: Updated `gatekeeper_app/lib/services/ble_scanner.dart` to clean and normalize UUID comparison (`replaceAll(RegExp(r'[^a-zA-Z0-9]'), '').toLowerCase()`), eliminating hyphen/case mismatches.
- **Ranging Refresh on `didEnterRegion`**: Updated `_startRangingStream(regions, forceRefresh: true)` and status notification update upon receiving OS `didEnterRegion` events.

## [2026-07-28] feat | Implement Single Persistent Ranging Stream Architecture in ble_scanner.dart

- **Single Persistent Ranging Stream**: Converted `_streamRanging` in `gatekeeper_app/lib/services/ble_scanner.dart` to a single persistent singleton stream initialized once at app startup.
- **Eliminated Native IPC Race Condition**: Completely removed `forceRefresh: true` and stream cancellation inside `didEnterRegion` callbacks, preventing AltBeacon native `BeaconService` race conditions and native Android process crashes while ensuring uninterrupted real-time RSSI tracking.

## [2026-07-29] code | Android 앱 패키지명(com.kshouse.gatekeeper_app) 및 표시 이름(경성하우스 스마트키) 변경

- **`AndroidManifest.xml`**: `package` 속성을 `com.kshouse.gatekeeper_app`으로 변경 및 `android:label`을 `"경성하우스 스마트키"`로 변경.
- **`build.gradle.kts`**: `namespace` 및 `applicationId`를 `com.kshouse.gatekeeper_app`으로 통일.
- **`MainActivity.kt`**: 패키지 경로를 `com/kshouse/gatekeeper_app/MainActivity.kt`로 재배치 및 패키지 선언 수정.

## [2026-07-29] fix | 모바일 앱 비콘 수신 / RSSI 실시간 표시 / 전력 최적화 전면 수정

브랜치 `fix/beacon-rssi-and-power`. 근본 원인 분석은 `issue.md`, 처리 결과는
`IMPLEMENTATION_REPORT.md` 참조.

- **P0-1** `startScanning(forceRestart:)` / `stopScanning()` 이 `_streamRanging` 을
  cancel 후 null 로 비우지 않아 ranging 이 영구히 재구독되지 않던 버그 수정.
  RSSI 를 표시하는 DebugScreen 자신이 이 경로를 호출하고 있었다.
- **P0-2** 화면 OFF 시 Android 가 ScanFilter 없는 스캔 결과를 폐기하는 문제 대응 —
  vendored `flutter_beacon` fork 에 `setBackgroundMode` /
  `setBackground(Between)ScanPeriod` / `setEnableScheduledScanJobs` 노출 후 호출.
  AltBeacon 기본 `backgroundBetweenScanPeriod` 가 5분이어서 반드시 0 으로 낮춰야 한다.
- **P0-3** 플러그인의 채널·BeaconManager 바인딩 소유자를 Activity → FlutterEngine +
  applicationContext 로 이전. Activity 파괴 시 ranging 이 무증상으로 끊기던 구조 제거.
- **P0-5** ranging 상시 ON 구조를 IDLE(monitoring 전용) ↔ ACTIVE(monitoring+ranging)
  2단 전력 모드로 전환. `didDetermineStateForRegion(INSIDE)` 도 승격 트리거로 처리.
- **P1/P2** 신호 소실 판정(6초+4회 연속), 모드 전환 뮤텍스 직렬화, 프리플라이트
  권한/위치서비스 게이트, RSSI EMA 평활+히스테리시스, 알림 갱신 스로틀,
  Pre-arm 실패 시 짧은 재시도, 진단 패널 신규, 매니페스트 `RECEIVE_BOOT_COMPLETED`.
- **P2-13** ESP32 AD Flags `0x04` → `0x1A` (표준 iBeacon). ⚠️ UUID 바이트 순서는
  BLE 스택(Bluedroid/NimBLE) 불명확으로 **실측 전까지 손대지 않음** — 검증 절차는
  `src/main.cpp` 주석 참조.
- **문서** `wiki/mobile_app_scan_lifecycle.md` 신규 — Android 플랫폼 제약,
  상황별 동작 매트릭스, **Activity 파괴 시 스캔 정지라는 잔존 한계**, 신고 대응 순서.

⚠️ 빌드/실기기 검증 미수행 (툴체인 부재). 완료 판정은 IMPLEMENTATION_REPORT.md §5
체크리스트 통과 후에 한다.


## [2026-07-29] fix | Add ProGuard rules for release build crash

- Added android/app/proguard-rules.pro to prevent R8 from obfuscating/shrinking org.altbeacon, com.flutterbeacon, and AsyncTask.
- Updated android/app/build.gradle.kts to enable minifyEnabled and apply the proguard rules.

## [2026-07-30] fix | 모바일 앱 비콘 상태 불일치(State Desync) 및 쿨다운 알림 UI 갱신 버그 해결

- AltBeacon 내부 구역 상태(INSIDE/OUTSIDE)와 앱 내부 상태(ACTIVE/IDLE) 불일치를 막기 위해 ranging 연속 무수신에 의한 커스텀 강제 IDLE 강등 로직 제거
- 네이티브 didExitRegion 발생 시에만 IDLE로 전환되도록 하여 Foreground/Background 모두 자연스러운 연결 보장
- 신호 유실 상태에서도 쿨다운 타이머가 멈추지 않고 매끄럽게 카운트다운 되도록 _startTimeoutCheckTimer 코루틴 내 알림 강제 갱신 로직 추가
- 6초 이상 신호 완전 소실 시 쿨다운 알림을 초기화하여 화면이 특정 상태에 멈춰있는 현상(Stuck) 완전 해결

## [2026-07-30] feat | 모바일 앱 크롬 중복 다운로드 방지를 위한 In-App APK 다운로드 및 자동 설치 로직 구축

- 모바일 크롬 브라우저의 탭 복원 기능으로 인한 APK 중복 다운로드 버그 완벽 해결
- url_launcher 의존성을 제거하고 dio 패키지를 활용한 앱 내부 다운로드(In-App Download) 구현
- 다운로드 진행 상태를 상단 배너에 실시간 프로그레스 바(LinearProgressIndicator)로 표출하여 UX 극대화
- 다운로드 완료 시 open_filex 를 통해 안드로이드 패키지 설치 화면 자동 호출 기능 탑재
- AndroidManifest.xml 에 REQUEST_INSTALL_PACKAGES 권한 추가

## [2026-07-30] fix | CI 빌드 실패 해결: dart:io 미사용 import 제거

- GitHub Actions CI 환경의 flutter analyze 단계에서 unused_import 경고(dart:io)로 인해 빌드가 실패(Exit 1)하는 문제 수정
- update_checker.dart 파일에서 불필요한 import 제거 완료

## [2026-07-30] fix | 안드로이드 백그라운드 스캔 전환 시 ranging 먹통 현상 해결

- 안드로이드 환경에서 구역 모니터링(Monitoring) 도중 동적으로 Ranging 을 시작할 때, 동일한 Region 식별자를 사용하면 OS 수준의 ScanFilter 가 갱신되지 않아 패킷 수신이 완전 차단되는 AltBeacon 고질적 버그 해결
- Ranging 전용 Region 식별자(GatekeeperRangingRegion)를 별도 분리하여 스캐너 충돌 원천 방지
- 초기 패킷 유실(last == null) 상태에서 6초 초과 시 IDLE 로 강제 강등시켜 재시작을 유도하는 복구 로직 추가

## [2026-07-30] fix | Resolve Relay Freeze & I2C Bus Hang Issues (Hardware/Firmware)

- **Relay Freeze (Back EMF / Latch-up)**: Analyzed the relay freeze issue requiring hard power cycles. Identified the root cause as a combination of back EMF from the relay coil lacking flyback diode/optocoupler isolation and a dangerous `pinMode(INPUT)` trick for the 5V relay pin in `src/main.cpp`.
- **Removed Dangerous INPUT Trick**: Replaced the `pinMode(PIN_RELAY, INPUT)` trick with the proper `RelayController` class to ensure safe Push-Pull logic outputs, preventing 5V reverse voltage from latching up the 3.3V-tolerant ESP32-C6 GPIO pins.
- **Added I2C Bus Clear Routine**: Implemented `clearI2CBus()` in `setup()` of `src/main.cpp` to send up to 9 clock pulses on SCL if SDA is stuck LOW. This defensive code prevents the main loop from blocking during soft resets caused by hung I2C slave devices (like VL53L0X) recovering from voltage drops.
- **Troubleshooting Guide**: Authored `wiki/relay_troubleshooting_guide.md` to document hardware improvements (Optocouplers, Flyback Diodes, separate power supplies) and firmware defenses.

## [2026-07-30] fix | Revert Relay OFF logic to High-Impedance (INPUT) mode

- **Root Cause**: The previous commit changed the relay OFF logic to Push-Pull HIGH (3.3V). Since the 5V relay module's optocoupler triggers at LOW and 3.3V is not high enough to completely shut off the 5V circuit (leaving 1.7V forward voltage), the relay remained ON permanently.
- **Fix**: Referenced smartbox and updated RelayController::_applyState() to use pinMode(pin, INPUT) for the OFF state of Active-LOW relays. This High-Impedance state cuts the current completely and correctly turns off the relay.

## [2026-07-30] fix | Correct I2C pins for C6 and tune Wi-Fi watchdog to prevent BLE starvation

- **Root Cause 1**: I2C Bus Clear routine was erroneously using GPIO 21 and 22, which are forbidden (JTAG/MTDI) on ESP32-C6. This could cause the ESP32 to lock up on boot before BLE initialization. Fixed to use proper SDA=6, SCL=7.
- **Root Cause 2**: Wi-Fi Auto-Reconnect watchdog in STA mode was aggressively calling WiFi.begin() every 5 seconds if not connected. The constant reset of the Wi-Fi modem starved the shared 2.4GHz RF PHY, completely blocking BLE advertising and causing the app to show '연결 안됨'.
- **Fix**: Adjusted Wi-Fi watchdog to 15 seconds and replaced disconnect()/begin() with a non-blocking WiFi.reconnect().

## [2026-07-30] compile | Audit mobile screen-off and app-closed beacon-to-prearm path

- Added `wiki/mobile_app_background_audit.md` with a source-level trace of foreground-service isolate startup, filtered iBeacon monitoring/ranging, RSSI gating, REST Pre-arm, MQTT arm, and ultrasonic relay activation.
- Identified P0 risks: ranging timeout can leave the scanner permanently IDLE while the native region remains INSIDE; UI/service Flutter engines can remove each other's global AltBeacon notifiers; background location is not enforced; HTTP 200 is treated as success even when `mqtt_published=false`.
- Recorded operational limits for force-stop, Android 13 Active Apps stop, OEM battery policies, pocket/body RSSI attenuation, and the Target's 20–50 cm ultrasonic valid range.
- Marked the older scan-lifecycle document as partially stale after the scanner was moved into the foreground-service isolate, and linked the new audit from `wiki/index.md`.

## [2026-07-30] fix | Harden screen-off mobile beacon scanning and Pre-arm delivery

- Made the foreground-service isolate the only native BLE scanner owner; removed DebugScreen direct scanning and synchronized full service diagnostics/settings to the UI every 5 seconds.
- Replaced ranging-timeout IDLE demotion with serialized ACTIVE-mode ranging resubscription, including stream-error recovery and a 10-second restart throttle.
- Removed global AltBeacon `removeAllRangeNotifiers()` / `removeAllMonitorNotifiers()` calls so separate FlutterEngine plugin instances cannot erase each other's callbacks.
- Added required-settings onboarding and blocked service/scanning until background location, Bluetooth, GPS, notification, and battery-optimization requirements are met; added Samsung/Xiaomi OEM guidance.
- Changed the default RSSI threshold from -75 dBm to -85 dBm and added backend `APP_RSSI_THRESHOLD` remote configuration with local user override support.
- Replaced new-install Android build-ID identifiers with persisted random UUIDs while preserving existing `DEV-*` identifiers for tenant-registration compatibility.
- Required both `result=armed` and `mqtt_published=true` before the app shows success.

## [2026-07-30] fix | Fail closed when MQTT Pre-arm delivery is not acknowledged

- Backend MQTT publish now starts the network loop, uses QoS 1, waits for PUBACK, and reports success only when `is_published()` is true.
- `/api/v1/door/prearm` now returns HTTP 503 when MQTT arm delivery fails instead of returning a misleading HTTP 200.
- Corrected the MariaDB Docker healthcheck to expand the password inside the container and removed the unconditional `exit 0` that marked an unhealthy database healthy.

## [2026-07-30] test | Verify mobile fixes with Docker Flutter builder

- `gatekeeper_app-flutter-builder`: Dart format completed, `dart analyze lib test` passed with no issues, and 5 Flutter unit tests passed.
- Android release APK build passed with Flutter 3.44.8, Dart 3.12.2, Java 17, compile SDK 36, and NDK 28.2.
- Output: `gatekeeper_app/build/app/outputs/flutter-apk/app-release.apk` (53,291,303 bytes), SHA-256 `82721F441C9B02F90EEC66E7A1F2FBF7439180A081F43BF67D7AF7005B83A9F4`.
- Updated the builder Dockerfile with required Android SDK/NDK/CMake components and a local-only debug signing fallback; Dockerfile check passed with no warnings.
- Backend `py_compile`, Compose config validation, wiki link validation, and `git diff --check` completed successfully.

## [2026-07-31] code | Prepare background beacon reliability fixes for publication

- Confirmed the commit scope covers the mobile foreground-service scanner hardening, Android permission onboarding, AltBeacon notifier isolation, backend MQTT fail-closed handling, Docker build support, regression tests, and synchronized wiki documentation.
- Reconfirmed the verified release APK checksum and prepared the complete related worktree for publication on a dedicated agent branch.

## [2026-07-31] fix | Prevent feature-branch APK deployment to NAS

- Restricted `.github/workflows/build_app.yml` automatic `push` trigger to the `main` branch while retaining explicit `workflow_dispatch` deployment.
- Added a job-level event/ref guard so pull requests and feature-branch pushes cannot execute the production APK build-and-SFTP job even if trigger configuration is changed accidentally.
- Confirmed the unintended feature-branch run `30557645940` was cancelled during the APK build and its NAS artifact preparation, SFTP deployment, and artifact upload steps were skipped.

## [2026-07-30] compile | 최신 코드 기준 핵심 문서 재분석 및 현행화

- 현재 구현을 ESP32 iBeacon Advertiser → Android foreground scanner → FastAPI/MariaDB → MQTT QoS1 Pre-arm → AJ-SR04T → GPIO23 relay 흐름으로 재확정
- `README.md`, `wiki/architecture.md`, `wiki/env_setup.md`, `wiki/pin_mapping.md`, `wiki/hardware_test.md`, `wiki/relay_troubleshooting_guide.md`에서 제거된 VL53L0X/ESP32 scanner/구 PlatformIO 환경 설명을 현재 코드 계약으로 교체
- `wiki/current_code_audit.md`를 추가해 코드 근거, 기존 문서 불일치, 실기기 P0와 보안·운영 P1, 정리 P2를 기록
- 과거 ToF 테스트 PASS와 현재 초음파·Android 통합 검증을 분리하고 iBeacon payload, 전기 안전, OEM 백그라운드, RF soak 재검증을 필수로 지정
- `wiki/index.md` 내비게이션과 Quick Reference를 현재 문서 구조로 동기화

## [2026-07-30] compile | 문서 감사 테스트 실행 위치 명확화

- 최신 문서 현행화의 링크 검사, backend `py_compile`, diff 검사와 PlatformIO 시도는 GitHub Actions가 아닌 `/workspace/smart-gatekeeper` 에이전트 작업 컨테이너에서 수행했음을 명시
- 2026-07-30 Flutter PASS는 `gatekeeper_app-flutter-builder` Docker 선행 증거이며 저장소 기록만으로 Docker 물리 호스트 위치를 확정할 수 없다고 구분
- GitHub Actions workflow/run 번호가 명시된 결과만 클라우드 CI 증거로 판정하도록 문서 신뢰도 기준 보강

## [2026-07-31] compile | Target 반복 통신 단절 근본 원인 감사

- 개발 PC와 1층 Target의 망 분리를 반영해 개발 PC 사설망 scan 결과를 판정에서 제외하고, 공인 MQTTS 접속·Target heartbeat·배포 metadata만 live 증거로 사용
- `wiki/target_connectivity_root_cause.md`에 부팅 10초 실패 후 AP 영구 고착, Wi-Fi 복구 시 stale TLS socket, 120초 동기 handshake block, relay OFF 경로 상실, MQTT ACK/Backend 거짓 성공, OTA 설치 gap을 코드 근거와 함께 기록
- 공인 broker는 감사 시점 접속 가능했지만 8초 동안 예상 1초 Target status heartbeat가 0건이어서 Target이 정상 MQTT loop 상태가 아님을 확인
- ECHO 5V, relay GPIO23 High-Z 역주입·back-EMF·전원 강하는 현장 실측 전까지 유력한 물리 trigger로 분리하고, AP SSID·iBeacon·relay LED·serial에 따른 현장 판별표와 수정 후 합격 기준을 추가

## [2026-07-31] lint | Target 통신 감사 증거 강도와 버전 해석 보정

- 8초 status 0건은 감사 subscriber의 직접 관측으로 한정하고, SUBACK/ACL raw trace가 없어 Target offline 단독 확정 증거가 아니라 정상 loop 이탈을 지지하는 정황으로 보정
- `SmartGatekeeper-Setup` SSID는 AP interface 활성 신호로만 사용하고, 정상 STA 경로도 `WIFI_AP_STA`이며 AP 종료가 없어 SSID 하나로 AP-trap을 확정하지 않도록 현장 판별 기준 수정
- retained `g8eb7cac`과 NAS metadata `g707ca23` 사이 Target source diff가 없음을 확인해 이번 장애 원인에서 제외하고, NAS upload와 실제 Target 설치의 구조적 gap만 유지
- 내부 1883과 공인 4883이 같은 broker의 listener일 가능성, stale TLS cleanup 누락의 사고 기여 미확정, live backend revision 확인 불가를 명시

## [2026-07-31] lint | Target 통신 감사 safety 경로 정밀 보정

- MCU reset 경로와 reset 없는 Wi-Fi 단절/stale socket 경로를 분리하고, 현재 로컬 framework 기준 TCP 30초 + TLS handshake 120초 + MQTT CONNACK 15초의 동기 block 가능성을 deployed version 미상 조건과 함께 기록
- relay OFF 상실은 force-open 뒤 arm 수신 후 센서 재감지가 없거나 기존 arm 만료가 1초 hold 안에 겹칠 때의 조건부 재현임을 명시하고, OTA callback도 동일 loop를 장시간 막을 수 있음을 추가
- 정상 STA 경로의 open provisioning AP 미종료, 무인증 credential 변경·동기 scan 위험과 물리 버튼·제한 시간·인증·pure STA 전환 요구사항을 추가
- 향후 relay ACK는 GPIO command만 증명하며 실제 접점/문 개방에는 별도 feedback sensor가 필요하다고 범위를 구분

## [2026-07-31] test | Verify Target MQTT recovery and fresh boot

- 공인 MQTTS listener에서 certificate/hostname 검증, MQTT 3.1.1 CONNACK 0, `smart-gatekeeper/status` SUBACK granted QoS 1을 확인
- 12초 관측에서 status 11건, 이어진 20초 관측에서 19건과 최대 heartbeat gap 1.134초를 기록해 01:45 KST 현재 Target online을 확인
- live telemetry는 firmware `2.0.0-g8eb7cac`, uptime 277→296초, IDLE/unarmed, free heap 200,568 bytes, Wi-Fi RSSI -82 dBm이었음
- uptime으로 약 01:40:39 KST 새 boot를 추정했으며 감사에서는 reboot/OTA/power 명령을 보내지 않았으므로, 현장 수동 power-cycle 여부와 reset reason 확인이 남음

## [2026-07-31] test | Extend recovered Target heartbeat and RSSI sample

- 추가 30초 구독에서 status 29건, 최대 heartbeat gap 1.118초, 2초 초과 gap 0회, uptime 429→458초와 regression 0회를 확인
- Wi-Fi RSSI는 -85~-78 dBm, 평균 -81.6 dBm으로 낮은 RF margin을 보였으며 짧은 관측창에서는 disconnect가 재현되지 않음
- 현재 online은 확인됐지만 초기 무수신과 약 01:40 새 boot의 원인은 여전히 reset reason/현장 power-cycle 정보가 없어 미확정

## [2026-07-31] compile | Narrow fresh-boot trigger candidates

- project의 의도적 restart 경로를 MQTT reboot command, OTA 성공, 무인증 provisioning `/save` 세 곳으로 한정하고 감사 client가 어떤 command도 publish하지 않았음을 기록
- 현재 로컬 Arduino-ESP32 3.3.9는 loop task watchdog을 disabled로 시작하며 project가 `enableLoopWDT()`를 호출하지 않아, 동기 TLS block은 무응답 원인이지만 그 자체의 watchdog reboot 증거는 없다고 구분
- 현장 power-cycle, 다른 MQTT client command, provisioning 변경, brownout/crash 순으로 약 01:40 reboot 원인 확인 항목을 정리

## [2026-07-31] test | Reproduce two additional unsolicited Target resets

- 첫 boot의 uptime 458초 이후 01:54 KST 표본이 uptime 166초로 돌아가 약 01:51:07 KST 두 번째 boot를 확인했으며 사용자는 전원/reboot/OTA/provisioning 조작이 없었다고 확인
- 01:55~02:07 KST 12분 read-only MQTTS 감시에서 status 678건을 수신하고 uptime 919→7 regression, heartbeat gap 8.288초, `connected` event로 약 02:06:26 KST 세 번째 MCU reset을 직접 포착
- 세 번째 reset 직전 state IDLE, RSSI -58 dBm, free heap 200,648 B였고 cmd/arm/force-open 수신은 0건이라 약한 RF, 누적 heap leak, MQTT reboot/OTA/open command를 직접 trigger에서 강하게 배제
- 후속 `gatekeeper/config/#` wildcard 감사에서 retained `gatekeeper/config/state`만 확인하고 retained command/config input은 없었으며, 새 boot 후 IP 192.168.0.190, RSSI -58 dBm, heap 200,568 B를 확인

## [2026-07-31] code | Add v2.1 retained reset and coredump diagnostics

- `DiagnosticsManager`를 추가해 full eFuse target ID, random boot ID, NVS boot count, `esp_reset_reason()`, planned restart reason을 수집
- RTC no-init breadcrumb에 직전 uptime/state/action/armed/relay command/GPIO level을 checksum과 함께 유지해 panic/software reset 뒤 원격 복구 가능하게 구현
- flash coredump validity와 panic reason, task, exception PC, RISC-V mcause/mtval, crashing ELF SHA를 retained `smart-gatekeeper/boot`에 발행
- status/event payload에 target/boot 식별자와 relay GPIO, min heap/largest block, loop stack watermark, BSSID/channel, MQTT attempt/failure를 추가
- retained `smart-gatekeeper/availability` online과 MQTT LWT offline을 추가하고 firmware version을 2.1.0으로 갱신

## [2026-07-31] fix | Enforce relay timer cutoff and restrict provisioning reset

- relay ON마다 별도 `esp_timer` 기반 Ticker one-shot을 시작해 Arduino loop가 TLS/HTTP에서 block돼도 1초 뒤 timer task가 물리 릴레이를 OFF하도록 변경하고 loop elapsed cutoff를 2차 방어로 유지
- relay ON 중 중복 open 명령은 기존 1초 timer를 연장하지 않도록 제한
- manual open 시 기존 arm을 취소하고 relay ON/hold 중 새 arm을 거부하며 arm expiry를 ARMED 상태로 제한해 FSM overwrite로 OFF transition을 잃는 경로를 차단
- AJ-SR04T 측정을 IDLE 상시 polling에서 Pre-arm 동안으로 제한해 GPIO11 ECHO 과전압 노출과 반복 순간 부하를 축소
- 정상 Wi-Fi 연결을 pure STA로 전환하고 SoftAP를 종료했으며 credential `/save`는 provisioning AP mode에서만 허용
- OTA library 자동 reboot를 끄고 MQTT reboot/OTA success/provisioning save 직전에 planned reason을 NVS/RTC에 기록한 뒤 명시적으로 재부팅하도록 변경
- CI firmware version override와 기본 firmware version을 `2.1.0-g<short_sha>` / `2.1.0`으로 갱신

## [2026-07-31] fix | Correct diagnostics breadcrumb symbol collision

- GitHub Actions run `30566291862`에서 `DiagnosticsManager::previousBreadcrumbValid()` method와 file-local boolean의 이름 충돌로 발생한 ESP32-C6 compile error를 확인
- file-local flag를 `previousBreadcrumbIsValid`로 변경해 member lookup ambiguity와 관련 warning을 제거
- 첫 실패 run은 firmware artifact 생성과 NAS SFTP 전에 중단되어 배포된 binary에는 영향 없음

## [2026-07-31] test | Deploy v2.1 diagnostics firmware and recover retained panic

- GitHub Actions run `30566577543`에서 ESP32-C6 build, NAS SFTP, version metadata 검증이 성공
- non-retained QoS 1 OTA 명령과 PUBACK 뒤 Target status가 `2.0.0-g8eb7cac`에서 `2.1.0-g93cee8d`로 바뀌고 uptime이 초기화돼 실제 설치를 확인
- 새 retained boot에서 target/boot ID, boot count, OTA software reset, Wi-Fi/heap/stack/MQTT diagnostics를 원격 회수
- 이전 flash coredump 11,044 B가 valid였고 `loopTask`의 `udp_new_ip_type` TCPIP core-lock assertion, PC `0x4080EB28`, `mcause=2`를 확인해 적어도 한 번의 software panic을 확정

## [2026-07-31] fix | Remove loopTask raw UDP panic entry points

- Target이 사용하지 않는 wall-clock SNTP `configTime()`과 10초 동기화 대기를 제거
- provisioning AP의 AsyncUDP 기반 captive DNS를 제거하고 WebServer와 수동 `http://192.168.4.1` 접속은 유지
- provisioning AP 시작/성공/실패를 RTC breadcrumb action에 기록해 Wi-Fi boot fallback 직전 상태를 다음 boot에서 확인 가능하게 변경
- CI가 secret-bearing ELF 대신 non-secret `firmware.map`을 30일 Actions artifact로 보존하도록 추가

## [2026-07-31] compile | Android 화면 OFF 출입 실패 원인 분리

- foreground service → monitoring → ranging → RSSI EMA → REST → MQTT → Target 센서/relay의 단계별 실패 판별표를 `wiki/mobile_screen_off_incident_analysis.md`에 추가
- 소스상 화면 OFF 방어는 구현됐지만 실기기 실패 로그가 없어 화면 OFF 단일 원인을 확정할 수 없으며, service/OEM kill·monitoring silent stall·주머니 RF 차폐·구버전 APK를 우선 후보로 분리
- 2026-07-31 02:32 UTC 공개 Backend health/config/version endpoint의 최종 HTTP 503과 upstream connection refused를 직접 관측해 화면 ON/OFF 공통 P0 운영 차단 요인으로 기록
- Backend 복구 후 동일 자세 통제 실험, Android 서비스/logcat, 앱·Backend·Target 타임스탬프 상관 분석과 원인별 확정 기준을 문서화

## [2026-07-31] compile | 화면 ON 성공·OFF 실패 A/B 증거 반영

- 같은 아침 화면 ON에서 실제 출입 성공하고 화면 OFF에서 실패했다는 현장 증거를 반영해, 동일 시간·자세·거리 조건이면 공통 Backend/MQTT/Target보다 모바일 service/scan 경로를 1순위로 재분류
- 화면 OFF와 동시에 주머니·자세가 바뀐 RF 교란 변수, foreground service OEM kill, monitoring/ranging silent stall을 남은 핵심 분기로 정리
- ON 성공 직후 OFF 시험이면 기본 10초 성공 쿨다운이 두 번째 Pre-arm을 차단할 수 있음을 새로 식별하고, 회차 간 15초 이상·시험 순서 교차 조건을 추가
- 이후 관측된 Backend 503은 재시험 차단 요인이지만 인접한 아침 A/B 결과의 화면별 차이를 설명하는 단독 원인으로 보지 않도록 증거 해석을 보정

## [2026-07-31] fix | 화면 OFF monitoring 단일 관문 제거

- foreground service scanner 시작부터 monitoring과 ranging을 병렬 구독해 화면 OFF에서 enter/INSIDE callback이 누락돼도 RSSI와 Pre-arm 경로가 동작하도록 변경
- monitoring OUTSIDE callback에서 ranging을 취소하지 않고 신호 상태만 초기화해 잘못된 OUTSIDE 뒤 영구 IDLE이 되는 경로 제거
- Target 부재 시에도 와야 하는 빈 ranging callback이 6초간 없으면 native silent stall로 판정하고 최소 10초 간격으로 subscription을 재생성
- 권한·GPS·배터리 전제조건 상실 시 idle 표시만 남기지 않고 전체 scanner preflight를 재실행해 조건 복구 후 재초기화 가능하게 수정
- 모바일 스캔 생애주기, 화면 OFF 감사, 장애 분석과 wiki index를 병렬 ranging 계약으로 동기화

## [2026-07-31] compile | 화면 OFF와 UI 종료 지원 경계 명확화

- BLE scanner가 UI가 아닌 foreground-service FlutterEngine/isolate 소유이므로 화면 OFF, Home, 뒤로 가기 Activity 종료는 코드 계약상 계속 동작한다고 명시
- 최근 앱 스와이프는 sticky service/OEM 실측 대상으로, Android 활성 앱 중지·설정 강제 종료는 미지원으로 분리
- 삼성·샤오미 등 OEM process kill은 배터리 예외만으로 절대 보장할 수 없고, 새 병렬-ranging APK는 구현 완료이나 실기기 반복 검증 전이라고 증거 수준을 명시

## [2026-07-31] lint | MQTT 토픽 자동 등록 범위 감사

- MQTT 연결 때 의도된 명령/config 토픽 10개가 자동 subscribe되고 Home Assistant entity 22개가 retained discovery publish되는 소스 경로를 확인
- MQTT 토픽 자체에는 사전 등록 개념이 없으며 boot, availability, event, ultrasonic raw와 v2.1 추가 진단 필드는 모두 별도 HA entity로 discovery되지 않는다고 범위를 명확화
- subscribe/publish 반환값 전체 검증, 실패 항목 재시도, 전체 성공 집계가 없어 연결 성공만으로 broker 수락까지 보장할 수 없는 한계를 기록

## [2026-07-31] fix | HA 기기 정보와 영역 표시 수 차이 판정 보정

- 펌웨어가 정의한 HA entity 22개는 모두 discovery 대상이며 원시 MQTT 토픽/필드가 discovery 범위 밖인 사실과 22개 등록 누락을 구분
- 22개 중 8개가 의도적으로 `diagnostic` 분류되고 Home Assistant 영역 자동 대시보드가 primary entity와 지원 domain만 선별하므로 약 11개 표시가 정상적인 UI 필터링일 수 있음을 확인
- 진단 분류 제거는 의미상 잘못되고 UI 혼잡을 유발하므로 적용하지 않았으며, 22개 전체 표시는 수동 Entities 카드로 구성하도록 운영 지침 추가

## [2026-07-31] compile | Android 상태바 알림 미표시 원인 진단

- `519648b` 전후를 비교해 과거에는 권한 거부와 무관하게 foreground service를 시작했지만 현재는 백그라운드 위치·Bluetooth·알림·GPS·배터리 예외 중 하나라도 미충족이면 `stopService()`로 기존 서비스까지 종료함을 확인
- foreground service 지속 알림이 상태바 표시를 소유하므로 최근 업데이트 직후의 미표시는 알림 문구 갱신보다 필수 조건 게이트에 의한 서비스 미실행/종료가 1차 원인이라고 `mobile_app_scan_lifecycle.md`에 기록
- 모든 필수 조건 충족 후에도 재현될 경우 앱/채널 알림 차단, Android 활성 앱 중지·강제 종료, OEM 절전 정책을 2차 확인 대상으로 분리
- 현재 테스트가 개별 진단 blocker만 검증하고 앱 초기화의 서비스 start/stop 선택 및 실기기 알림 표시를 검증하지 않는 공백을 기록

## [2026-07-31] compile | Android 상태바 알림 미표시 진단 후보 보정

- 사용자가 최신 빌드, 미완료 필수 항목 없음, 거부 권한 없음을 확인해 필수 조건 게이트를 해당 기기의 직접 원인에서 제외
- 현재 진단이 전역 `Permission.notification`만 확인하고 `smart_key_foreground_channel`의 importance/차단 상태를 확인하지 않는 blind spot을 식별
- `foregroundServiceRunning=false`가 blocker가 아닌 warning이라 미완료 필수 항목이 없어도 시작 후 서비스 종료 상태일 수 있음을 확인
- Debug 화면의 `포그라운드 서비스 실행` 또는 Android 13+ 활성 앱 목록으로 서비스 종료와 채널 숨김을 먼저 분리하도록 `mobile_app_scan_lifecycle.md`를 보정

## [2026-07-31] compile | 모바일 앱 실시간 이벤트 로그 0건 원인 확정

- `flutter_foreground_task` 6.5.0 공식 예제는 receive port를 서비스 시작 전에 등록하지만 현재 `ForegroundServiceManager`는 `startService()` 반환 후 등록하는 순서 역전을 확인
- 서비스 isolate의 nullable `SendPort`가 null이면 `AppErrorLogger`와 `BleScanner` IPC가 `backgroundSendPort?.send(...)` 및 빈 catch에서 조용히 전부 유실됨을 확인
- `onStart` 시작 메시지도 앱 이벤트 로거가 아닌 `debugPrint`만 사용해 앱 내 콘솔 0건은 서비스 미실행의 확정 증거가 아님을 기록
- IPC 결함은 foreground 알림 생성 경로와 별개이므로 상태바 미표시 직접 원인과 분리하고, 수정 전에는 Android 활성 앱 목록 또는 ADB로 서비스 생존을 확인하도록 진단 절차 보정

## [2026-07-31] compile | 모바일 앱 상태바 복구 가능 범위 판정

- receive port 선등록 수정은 이벤트·에러·진단 IPC를 복구하지만 native foreground 알림 생성과는 별도 경로라 상태바까지 단독 복구를 보장하지 못한다고 범위를 구분
- 완전한 복구 후보를 port 선등록, 서비스 시작/heartbeat 검증, `updateService()` await·결과 확인, 개별 채널 상태 진단, 실기기 테스트 묶음으로 정의
- 사용자 차단 채널과 OEM 강제 종료는 앱 코드가 강제로 되돌릴 수 없는 외부 조건으로 남기고 Android 설정 안내 대상으로 분류
- 완료 기준을 이벤트 heartbeat, foreground service 실행=true, 알림 표시, 화면 OFF 접근 성공의 동시 확인으로 명시

## [2026-07-31] code | 모바일 foreground 상태바·IPC 복구 구현

- 서비스 시작 전에 receive port를 등록하고 실패를 시작 실패로 승격해 서비스 isolate의 SendPort null로 인한 UI 이벤트·에러·진단 IPC 유실을 차단
- service lifecycle 시작·5초 heartbeat·종료를 UI에 전달하고 초기화/heartbeat 예외를 앱 이벤트 로그에 기록하도록 추가
- 알림 갱신을 await해 false 반환·비동기 예외를 로그로 보존하고, 기존 importance 불변 LOW 채널 대신 DEFAULT·무음 `smart_key_foreground_channel_v2` 채널을 사용
- Android native notification bridge로 앱 전체 알림과 새 channel 존재·차단·importance를 읽어 Debug 화면에 실제 서비스·채널 상태를 표시
- Docker에서 `flutter analyze` 변경 파일 통과 및 `flutter test` 5건 통과; Android APK/Kotlin 전체 컴파일은 Gradle 초기화가 실행 시간 제한을 넘어 실기기 설치 검증이 남음

## [2026-08-01] code | 모바일 foreground 상태바·IPC 복구 변경 main 반영

- `b049a76` 커밋으로 receive port 선등록, 서비스 heartbeat·오류 로그, v2 foreground 알림 채널, Android 채널 상태 진단 및 Debug 표시를 원격 `main`에 반영
- 변경 Dart 파일 `flutter analyze` 및 기존 `flutter test` 5건 통과 결과를 함께 배포 이력으로 보존
- Android APK/Kotlin 전체 컴파일은 Docker Gradle 초기화가 실행 제한을 넘어 실기기 설치 후 상태바·heartbeat 검증이 필요함

## [2026-08-01] fix | 업데이트 자동 실행 foreground service IPC 재연결

- 실기기에서 이벤트 콘솔이 계속 비어 있는 관측을 바탕으로 `autoRunOnMyPackageReplaced`가 UI receive port 등록 전에 service를 시작하는 경로를 확인
- 기존 실행 service가 최초 null `SendPort`를 보존한 채 반환돼 로그 IPC가 계속 유실될 수 있어, 포트 등록 후 `restartService()`로 service isolate를 재생성하도록 수정
- UI isolate에서 IPC 포트 등록, 신규 서비스 시작, 기존 서비스 재시작 요청을 직접 콘솔에 기록해 서비스 IPC와 로그 UI 자체를 즉시 구분할 수 있도록 보완

## [2026-08-01] fix | 구역 이탈 로그와 상태바 표시 정합성 복구

- `didExitRegion` 뒤 RSSI를 초기화하면서 ranging은 유지하는 설계에서 상태 계산이 null RSSI를 "구역 내 신호 약함"으로 오해한 모순을 수정
- scan mode와 분리된 `_isInsideRegion` 상태를 monitoring INSIDE/OUTSIDE에 연결하고, OUTSIDE 뒤 실제 Target ranging 패킷 수신은 더 강한 IN 증거로 처리
- 이탈 뒤에는 "Target 비콘 구역 밖 — 다음 진입 감시"를 표시하면서 병렬 ranging은 유지해 화면 OFF enter 누락 복구 원칙을 보존

## [2026-08-01] fix | 반복 개방 인터록과 화면 OFF 비콘 수신 진단 보강

- Target ARM·수동 개방을 IDLE에서만 수락하고 새 ARM마다 초음파 중앙값 이력을 초기화해 ARMED 갱신·COOLDOWN 우회·이전 근접 표본 재사용을 차단
- 모바일의 중복 Pre-arm은 기존 cooldown 정책으로 허용하고, Android 화면 OFF 때만 RSSI 기준을 임시 우회해 Target 패킷 수신 여부를 로그로 분리
- Backend MQTT 성공은 broker PUBACK까지만 의미하며 Target ACK 연계와 correlation ID가 없고 로컬 broker 후보를 우선 시도하는 보장 공백을 현장 분석 문서에 기록

## [2026-08-01] compile | GITHUB_TOKEN 기반 게시 인증 지침 명문화

- GitHub CLI와 push는 현재 프로세스의 `GITHUB_TOKEN`만 사용하고 토큰 원문을 출력·파일 저장·remote URL 기록하지 않도록 루트 및 IDE 자동 로드 지침에 추가
- 인증 실패 시 저장 계정이나 `gh auth login`으로 우회하지 않고 환경 변수 갱신을 요청하도록 `env_setup.md`와 게시 절차를 동기화

## [2026-08-01] lint | GitHub sandbox 연결 실패와 토큰 인증 실패 구분

- 기본 sandbox에서 GitHub API와 remote socket 연결이 차단돼 `gh auth status`가 토큰을 invalid로 잘못 보고할 수 있음을 확인
- 네트워크 권한을 적용한 재검증에서 `GITHUB_TOKEN` 계정과 repo/workflow 권한이 정상임을 확인하고, 실제 GitHub 연결 후의 401만 토큰 실패로 판정하도록 지침 보완
