# wiki/log.md — Chronological Change Log
> Format: `## [YYYY-MM-DD] <type> | <description>`
> Append only. Never edit past entries.

---

## [2026-08-12] deploy | Restore personal NAS reverse-proxy binding

- Restored `8000:8000` for the DSM HTTPS reverse proxy; router port 8000 remains unforwarded.

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

## [2026-08-01] compile | 모바일 의존성 병목 분석과 문 중심 로컬 인증 재설계

- 첨부 콘솔의 반복 IPC 등록과 10초 간격 `ranging 신호 무수신 자동 복구`를 실제 코드 분기와 대조해, 해당 구간은 API보다 앞선 유효 Target 패킷/RSSI 수신 단계가 우선 병목임을 기록
- foreground service·권한·BLE/IPC·RSSI·쿨다운·REST를 모바일이 직렬 소유하는 현재 구조와 과거 화면 OFF, Backend 503, MQTT ACK, 반복 개방, 인증 경계 문제를 책임 관점에서 통합 분석
- 정상 출입에서 모바일 background 실행과 WAN 실시간 의존을 제거하고 Door Controller가 presence/session/local ACL/relay를 소유하는 목표 구조를 제안
- secure BLE fob hands-free + NFC/Wallet fallback을 신뢰성 우선안으로, phone-only일 때 NFC/Wallet tap + QR fallback을 차선으로 정리하고 단계적 전환·보안 계약·합격 기준을 추가

## [2026-08-01] compile | 추가 자격 하드웨어 없는 모바일 병목 축소 구현 계획

- secure BLE fob, NFC reader/card, QR scanner 도입을 보류하고 현재 ESP32-C6·AJ-SR04T·relay와 Android 스마트폰만 사용하는 구현 범위를 확정
- Android OS-managed filtered wake, native GATT credential worker, Android Keystore device key, Target local challenge-response·ACL로 정상 출입의 Flutter foreground service와 REST·DB·MQTT 실시간 의존을 제거하는 목표 구조를 정의
- 계약/측정, Android, Target BLE, Backend ACL, Target FSM, Flutter UI, E2E rollout을 I1~I9 작업으로 분해하고 Wave 0~3 병렬 의존 관계, 산출물, 완료 기준, 공통 DoD와 전환 gate를 문서화
- force-stop·OEM restricted 상태는 추가 하드웨어 없이 자동 보장할 수 없음을 명시하고 사용자 동작 local retry/제한적 remote fallback을 설계 범위에 포함

## [2026-08-01] compile | 모바일 병목 축소 Epic과 세부 GitHub 이슈 등록

- `ks-house/smart-gatekeeper`에 전체 조정 Epic #13과 Wave 0~3 세부 이슈 #14~#22를 각각 등록
- #14 Android wake ADR, #15 session 관측 schema, #16 보안·ACL protocol을 독립 Wave 0로 묶어 즉시 병렬 시작할 수 있게 구성
- #17 Android native worker, #18 Target GATT, #19 Backend ACL을 Wave 1 병렬 트랙으로 연결하고 #20 Target local FSM, #21 Flutter thin UI, #22 E2E rollout의 선행 관계를 Epic checklist와 구현 계획 표에 동기화
- 각 이슈에 추가 하드웨어 제외 범위, 산출물, 완료 기준, fail-closed·rollback·실기기 검증 조건을 명시

## [2026-08-01] compile | 모바일 앱·Target OTA를 최상위 불변조건으로 승격

- 모바일 앱과 ESP32-C6 Target의 OTA/rollback 가능성을 BLE 인증·local ACL·FSM 등 모든 새 기능보다 우선하는 P0 계약으로 루트 및 IDE 자동 로드 에이전트 지침에 추가
- 즉시 OTA가 불가능한 전원·네트워크·Android 사용자 차단과, 외부 조건 복구 뒤 독립 update control plane으로 반드시 복구 가능한 운영 의미를 구분
- Target dual-slot health/valid mark/자동 rollback, periodic HTTPS·MQTT·provisioning AP recovery와 모바일 scanner/UI 독립 update·artifact 검증·fallback distribution을 `ota_reliability_contract.md`에 정의
- mobile/Target 독립 배포의 N/N-1 호환, 기존 정상 버전 보존, install/boot health confirmation, power-loss·잘못된 artifact 장애 주입을 release blocking Gate로 추가

## [2026-08-01] compile | OTA 비회귀 전용 GitHub 이슈 #23 등록

- Epic #13 하위에 `[OTA][I10] 모바일 앱·Target OTA 비회귀와 복구 계약` #23을 Wave 0 cross-cutting blocker로 등록
- #17~#22 구현·통합·rollout은 #23의 OTA reachability, artifact integrity, dual-slot rollback, N/N-1 compatibility 계약을 통과해야 완료되도록 구현 계획에 반영

## [2026-08-01] compile | issue #16 device key·BLE proof·signed ACL v1 규격 확정

- Android Keystore P-256 생성·enrollment·rotation·revocation과 user-auth 없는 자동 출입의 분실 휴대폰 위험, online 60초/기본 900초/hard max 3,600초 revoke 경계를 명시
- BLE default ATT_MTU 23에서도 동작하는 10-byte framing, highest-common version negotiation, canonical challenge/proof bytes, low-S raw64 ECDSA와 고정 result reason을 확정
- signed ACL canonical schema, 단조 version/high-watermark, copy-on-write atomic activation, clock 부정확·reset·stale/equal-version replay fail-closed 정책을 정의
- mobile/Target/backend N/N-1·rollback, OTA control-plane 독립성, secret 비로그, replay·downgrade 위협 모델을 release gate로 연결

## [2026-08-01] code | Android·ESP32·Backend 공통 canonical vector 자동 검증 추가

- `protocol/test_vectors/v1.json`에 hello transcript, 138-byte challenge, 61-byte proof input, P-256 low-S raw64 signature, 178-byte ACL, ATT_MTU 23의 14개 fragment를 고정
- stdlib-only verifier와 8개 mutation/replay/framing/downgrade/rollback unit test를 추가하고 protocol 변경 전용 GitHub Actions workflow를 구성
- vector의 private scalar는 공개·비운영 test fixture이며 production 자격으로 재사용하거나 production log에 출력하지 않도록 명시

## [2026-08-01] test | issue #16 canonical protocol vector 검증 통과

- `python protocol/tools/verify_vectors.py`가 committed canonical hex/hash, RFC 6979 P-256 signature와 ACL signature를 검증
- `python -m unittest discover -s protocol/tests -v`에서 cross-door/cross-boot proof reuse, high-S, unsorted ACL, MTU 23 reassembly, N/N-1 rollback/floor 8개 시험 통과
- Python `cryptography` verifier로 raw64 fixture를 DER로 변환해 독립 P-256/SHA-256 검증 통과

## [2026-08-01] lint | issue #16 protocol wiki·vector 일관성 점검

- cross-session, stale/equal-version ACL, trusted/untrusted clock lease case를 추가해 최종 11개 unit test와 vector verifier, Python compile, `git diff --check` 통과
- 변경된 wiki 4개 문서의 상대 Markdown link가 모두 존재하고 24시간 offline lease 제안이 확정된 기본 900초/hard max 3,600초 정책과 충돌하지 않음을 확인
- 새 `security_protocol.md`를 wiki navigation/architecture/구현 계획에 연결하고 raw 파일 및 기존 log entry는 수정하지 않음

## [2026-08-01] lint | PR #24 독립 보안 리뷰에서 차단 결함 확인

- canonical vector verifier, 11개 unit test, Python compile, 독립 `cryptography` P-256 검증, Markdown 상대 링크, `git diff --check`, GitHub `canonical-vectors` check가 모두 통과했음을 재확인
- ACL active pointer를 persisted high-watermark보다 먼저 commit하는 순서가 전원 차단 뒤 signed intermediate snapshot의 보안 rollback을 허용할 수 있어 pointer와 high-watermark의 원자성 또는 `max(active_version, high_watermark)` 복구 규칙과 crash vector가 필요함을 확인
- 인증된 Target 또는 relay-resistant channel binding 없이 공개 BLE discovery를 복제해 real Target challenge와 user-auth 없는 phone proof를 실시간 중계할 수 있으므로 relay 위협·잔여 위험·완화 또는 명시적 수용 기준이 필요함을 확인
- ACL encoder/verifier가 문서상 거부 대상인 unknown status/permission, 역전된 time/protocol range, off-curve public key를 현재 수용하므로 negative vector와 CI 검증이 필요하며 PR #24는 수정 전 merge하지 않음

## [2026-08-01] fix | PR #24 독립 보안 리뷰 차단 결함 수정

- ACL pointer와 high-watermark를 하나의 이중 generation record로 commit하고 boot에서 `effective_high_watermark=max(valid record, valid legacy active, legacy watermark)`를 candidate보다 먼저 복구하도록 규격과 6개 crash-boundary vector를 추가
- 현재 BLE v1은 fresh proof를 실시간 중계하는 wormhole을 막지 못하고 possession만 인증함을 명시해 RSSI·timeout·mutual auth를 relay 방어로 오인하지 않게 하고 relay-resistant/interactive/low-consequence risk acceptance의 RELAY-G0~G2 배포 Gate를 신설
- verifier가 unknown status·permission bit, snapshot/entry time 및 protocol 역전·범위 이탈, hard lease 초과, off-curve SEC1을 encoding 전에 거부하도록 semantic validation과 8개 negative vector를 구현

## [2026-08-01] test | PR #24 security review adversarial vector 검증 통과

- canonical verifier와 14개 unit test에서 6개 ACL power-cut/legacy recovery, 8개 ACL semantic rejection, 5개 relay/deployment policy case를 포함해 모두 통과
- Python compile, 독립 `cryptography` P-256 검증, workflow YAML parse, 변경 wiki 상대 링크와 RELAY-G anchor, secret placeholder scan, `git diff --check` 통과
- current hands-free v1 transparent wormhole은 의도대로 `wormhole_succeeds=true`, `deployment_allowed=false`로 검증해 CI green이 proximity 보장을 의미하지 않도록 고정

## [2026-08-01] lint | PR #24 재리뷰에서 RELAY-G release gate 차단 결함 확인

- ACL crash-safe generation/high-watermark의 6개 power-loss vector와 strict ACL semantic validator의 8개 negative vector가 이전 차단 결함을 재현·차단함을 확인
- canonical verifier, 14개 unit test, Python compile, 독립 `cryptography` P-256 검증, workflow YAML parse, Markdown 구조·상대 링크, secret value scan, `git diff --check`, GitHub `canonical-vectors` check 통과
- `ble_relay_assessment()`가 `relay_resistant_channel=true`이면 `risk_owner_approved=false`여도 배포를 허용하고 vector에 `RELAY-G0`·`RELAY-G2` 증거 필드가 없어 문서의 G0→G2 production fail-closed 계약을 CI가 강제하지 못함을 재현
- PR #24에 구체적 재리뷰 결과를 남기고 RELAY-G0/G1/G2를 모두 명시적으로 요구하는 negative case가 추가되기 전 draft 유지·merge 금지로 판정

## [2026-08-01] fix | PR #24 RELAY-G release gate 우회 차단

- `ble_relay_assessment()`가 threat-model·두 proxy 결과·risk-owner 승인(G0), 선택 경로와 일치하는 control evidence(G1), 동일 경로의 100회 전 성공 운용·OTA rollback evidence(G2)를 모두 검증한 뒤에만 production enable하도록 fail-closed 판정을 구현
- `relay_resistant_channel=true` 단일 flag 우회를 제거하고 G0/G1/G2 각각의 누락·false·evidence 불일치, 승인 없음, G2 100회 미달을 포함한 16개 공통 relay vector로 계약을 고정
- 기존 ACL generation/high-watermark power-loss recovery와 strict semantic rejection vector 및 과거 review log는 변경하지 않고 security protocol·hardwareless plan·index를 동기화

## [2026-08-01] test | PR #24 RELAY-G adversarial 검증 통과

- canonical verifier와 16개 unit test에서 16개 relay/deployment case를 포함해 실행했으며 세 positive 경로만 G0/G1/G2가 모두 valid일 때 허용되고 12개 필수 negative case는 모두 배포 거부됨을 확인
- Python compile, 독립 `cryptography` P-256 검증, JSON·workflow YAML parse, Markdown fence·상대 링크·RELAY-G anchor, 변경 diff secret pattern scan, `git diff --check` 통과
- GitHub `canonical-vectors` check는 같은 PR #24 branch push 뒤 별도로 확인하며 PR은 draft·unmerged 상태를 유지

## [2026-08-01] code | OTA P0 machine-readable 계약과 CI release blocker 구현

- mobile/Target Ed25519 metadata schema, deterministic valid/tampered test vector, 상태 머신, recovery matrix와 fault-injection plan을 `ota/`에 추가
- dual-slot layout, 필수 상태·복구 시나리오, signature tamper, pinned key와 mobile fallback 독립성을 검사하는 validator·단위 테스트 5건을 추가
- OTA 영향 PR의 contract Gate를 추가하고 firmware/APK canary artifact는 보존하되 OTA-G0~G4·physical evidence·운영 승인 전 production NAS SFTP가 실패하도록 변경
- 현재 Target periodic HTTPS/valid mark/rollback/local AP와 mobile scanner 독립 update/hash·certificate/fallback은 미구현임을 감사 결과로 기록하고 물리 ESP32/Android 검증을 pending release Gate로 유지

## [2026-08-01] compile | OTA 운영 runbook과 증거 수준 동기화

- canary, Target boot health·rollback, mobile fallback, 중단 조건, 장애별 recovery와 필수 telemetry를 `wiki/ota_operations_runbook.md`에 정의
- 계약 PASS와 실기기 install/boot/rollback PASS를 분리하고 `wiki/hardware_test.md`, `wiki/env_setup.md`, `wiki/index.md`를 CI release blocker 상태와 동기화

## [2026-08-01] fix | release evidence 단독 우회 방지

- production release mode가 evidence뿐 아니라 해당 build의 manifest와 pinned Ed25519 public key를 필수 입력으로 받아 실제 서명을 재검증하도록 보강
- 현재 legacy unsigned `version.json`과 미설정 production trust root는 canary artifact 생성 뒤 production SFTP를 계속 차단하며 signing pipeline·runtime consumer 구현을 pending Gate로 유지

## [2026-08-01] test | OTA 계약 자동 검증과 pending release 차단 확인

- contract validator, JSON/YAML parse, wiki 상대 링크, `git diff --check`, Python compile과 unit test 5건 통과
- OTA-G1~G4가 pending인 release command가 production 배포를 예상대로 거부함을 확인
- PlatformIO 로컬 build는 도구 설치 후 180초 제한을 초과해 완료 증거를 얻지 못했으며 firmware 소스 변경은 없으므로 GitHub Actions build 결과 확인을 pending으로 유지

## [2026-08-01] test | PR #25 독립 OTA 계약 리뷰에서 release blocker 결함 확인

- contract validator, unit test 5건, Python compile, JSON/YAML parse, wiki 상대 링크와 `git diff --check`를 독립 재실행해 모두 통과
- 서명된 manifest만으로 실제 firmware/APK artifact bytes 없이 release 검증이 통과해, 배포 artifact의 size·SHA-256·APK signing certificate를 production SFTP 전에 검증하지 못하는 차단 결함을 확인
- state machine의 `failure_preserves`·`invariants`를 비우거나 recovery 결과를 파괴적 동작으로 바꿔도 필수 ID/state 이름만 남으면 contract Gate가 통과하는 비회귀 우회를 확인
- PR #25는 병합하지 않고 issue #23을 open으로 유지하며 artifact 결합 검증과 의미 기반 invariant/recovery 검증 추가 후 재리뷰하도록 판정

## [2026-08-01] fix | PR #25 OTA release blocker 세 결함 fail-closed 보강

- release Gate가 signed manifest와 실제 firmware/APK 경로를 1:1로 입력받아 byte length와 SHA-256을 비교하고, Android는 `apksigner`의 signing certificate SHA-256까지 검증하도록 수정
- firmware/APK workflow의 Gate 입력을 이후 Actions/SFTP가 올리는 동일 `dist` artifact 경로에 결합하고, artifact 누락·교체·truncation·certificate mismatch를 production 배포 전에 차단
- Target/mobile `failure_preserves`·`invariants`의 exact required set과 initial/terminal success를 schema·semantic validation으로 고정
- recovery outcome/action과 상태 전이를 allowlist schema 및 장애별 exact mapping으로 제한하고, fault ID·expected outcome·physical Gate 분류의 의미 역전을 거부

## [2026-08-01] test | OTA adversarial negative regression 18건 통과

- artifact missing·byte substitution·truncation·APK certificate mismatch와 manifest pinned key mismatch가 모두 release validation에서 거부됨을 확인
- preservation/invariant 빈 배열·필수 항목 제거, initial/terminal success 변경, 파괴적 unknown recovery text, allowlist 내부 action 바꿔치기, unsafe transition과 fault outcome 역전이 모두 거부됨을 확인
- workflow가 실제 upload artifact 대신 다른 경로를 Gate에 전달하는 mutation을 contract validation이 거부하며, 기존 positive contract와 signed vector 검증도 유지됨을 확인

## [2026-08-01] lint | OTA 계약 schema·workflow·문서 일관성 재검증

- `python scripts/ota_contract_gate.py contract`, Python compile, unit test 18건, 전체 OTA JSON과 GitHub Actions YAML parse 통과
- wiki 상대 링크와 `git diff --check` 통과; 기존 독립 review 증거와 OTA-G1~G4 physical pending 상태를 보존

## [2026-08-01] test | PR #25 fix commit 독립 재리뷰 통과

- `28fe025`가 signed manifest와 실제 firmware/APK를 1:1로 결합해 byte length·SHA-256을 검증하고 Android APK는 `apksigner` certificate SHA-256까지 fail-closed로 비교함을 독립 확인
- Target/mobile preservation·invariant exact set, initial/terminal success와 recovery/fault ID·outcome·action·safe transition exact mapping이 비어 있거나 의미 역전될 수 없음을 schema와 semantic validator에서 확인
- contract validator, unit test 18건, Python compile, JSON/YAML parse, wiki 상대 링크, `git diff --check`와 GitHub OTA P0 check가 통과했으며 OTA-G1~G4와 physical tests는 장비 부재로 pending·release blocked 상태를 유지
- 기존 세 review blocker는 해소되어 PR #25 병합 가능으로 판정하되 issue #23은 실제 periodic HTTPS/local recovery, Android fallback, N/N-1, power-loss rollback 증거 전까지 open으로 유지

## [2026-08-01] compile | PR #24에 최신 main OTA 계약 병합

- `origin/main`의 PR #25 OTA P0 계약·runbook·CI 변경을 병합하고 양 branch의 append-only log 항목을 삭제 없이 보존
- wiki index의 최신 상태를 OTA 실행 계약과 RELAY-G0/G1/G2 fail-closed 보완을 함께 나타내도록 조정

## [2026-08-01] compile | Cross-layer access/update event schema v1 확정

- GitHub issue #15의 Android·Target·Backend 공통 envelope와 UUIDv4 session/event ID, boot-local monotonic sequence, causal offline ordering 규칙을 `observability_event_schema.md`에 정의
- 고정 access/update event·reason catalog, privacy whitelist, 기존 mobile/Backend/MQTT/Target 자유 텍스트 mapping과 dual-write migration을 문서화
- I7 local FSM과 I9 fault matrix의 relay one-shot·terminal reason·reset 합격 판정, #23 install→boot/app first-run→health→valid/rollback OTA 상관관계를 release gate로 고정

## [2026-08-01] code | Event schema reference parser와 fixture 구현

- JSON Schema 2020-12 envelope와 authoritative event/reason compatibility catalog를 `observability/`에 추가
- dependency-free Python parser에 privacy validation, exact replay dedupe, sequence conflict 검출, causal partial ordering, access/OTA 합격 판정을 구현
- Android synced clock과 Target unsynced clock이 섞인 정상 access fixture, Target old/new boot를 잇는 OTA health/valid-mark fixture를 추가

## [2026-08-01] test | Event schema parser 계약 검증

- 정상 access/OTA, offline 역순 도착, exact replay, sequence 충돌, unknown code/reason, privacy 위반, reset, relay fail-closed, artifact digest, terminal/health 누락의 12개 unittest를 통과
- reference parser로 두 fixture의 schema validation과 I7/I9/OTA acceptance evaluation 통과를 확인

## [2026-08-01] test | Cross-layer schema 변경 비회귀 검사

- repository Docker Flutter builder에서 기존 `scan_diagnostics_test.dart` 5개 테스트 통과
- compile-only placeholder secret header를 사용한 ESP32-C6 PlatformIO 빌드는 toolchain 준비·컴파일을 진행했으나 두 차례 각각 5분 제한 시간에 도달해 완료 여부 미확정; 임시 header는 즉시 제거하고 firmware source·설정은 변경하지 않음

## [2026-08-01] lint | Event schema와 wiki 일관성 검사

- JSON Schema Draft 2020-12 meta-schema와 access/OTA JSONL fixture 구조 검증 통과
- 전체 wiki 상대 링크, Python compile/unittest, parser validation/evaluation, `git diff --check` 통과

## [2026-08-01] test | PR #26 event schema 독립 리뷰와 차단 결함 확인

- parser unittest 12건, access/Target OTA fixture 25건의 JSON Schema Draft 2020-12 meta-schema 검증, parser validate/evaluate, Python compile, wiki 상대 링크와 `git diff --check`를 재실행해 기존 검사는 통과
- 변형 fixture에서 같은 update session의 artifact digest 변경과 이전 버전 boot/install 증거 없는 rollback 완료가 acceptance parser를 통과해 OTA #23 상관관계와 rollback 합격 계약을 강제하지 못함을 확인
- 존재하지 않은 `prior_target_boot_id`를 넣은 access reset terminal과 uint64 범위를 넘은 sequence도 허용되고, `validate_stream`이 causation cycle을 통과시키는 계약 공백을 확인
- PR diff가 observability와 wiki 파일에만 한정되고 firmware source, include, PlatformIO 설정을 변경하지 않으므로 기존 PlatformIO 5분 timeout 자체는 이 문서·parser PR의 차단 사유가 아니지만, 위 acceptance 결함 수정 전에는 병합하지 않기로 판정

## [2026-08-01] fix | PR #26 event schema 차단 결함 수정

- update session의 최초 non-null `artifact_sha256`을 immutable하게 강제하고 manifest/installed image digest 불일치와 알려진 digest를 누락한 failure terminal을 fail-closed 처리
- rollback 완료에 이전 정상 버전의 install, 새 recovery boot, health evidence를 고정 event chain으로 요구하고 version, confirmation, Target emitter, boot와 target 상관관계를 검증
- access reset terminal이 실제 직전 Target event와 prior boot를 직접 연결하고 같은 Target의 새 boot에서 emit되는지 검증
- sequence와 monotonic clock을 uint64 범위로 제한하고 `validate_stream`에서 causation/sequence cycle을 직접 거부

## [2026-08-01] test | PR #26 차단 결함 회귀 fixture 검증

- 정상 access, Target OTA와 Target rollback fixture의 parser validation/evaluation 및 unittest 17건 통과
- digest 불일치, rollback evidence 누락, 잘못된 reset prior boot, uint64 overflow, causation cycle negative fixture가 각 계약 계층에서 거부됨을 확인
- JSON Schema Draft 2020-12 meta-schema와 의도상 schema-valid fixture event 45건을 검증하고 uint64 overflow fixture의 maximum 위반을 확인

## [2026-08-01] lint | Event schema review 수정 일관성 검사

- Python compile, 전체 wiki 상대 링크, schema/catalog JSON parse와 `git diff --check` 통과
- `observability/README.md`, `wiki/observability_event_schema.md`, `wiki/index.md`의 digest, rollback, reset, uint64와 causal ordering 계약을 parser/catalog/fixture와 동기화

## [2026-08-01] fix | PR #26 수동 버튼 출입 경로 불변조건 보강

- Epic #13의 사용자 확인에 따라 인증된 모바일 앱 `문 열기` 버튼을 hands-free unlock과 구분되는 `manual_remote` access path로 고정
- manual button request, Backend authorization, Target command receipt의 고정 event/reason code와 relay ON/OFF causal chain을 catalog/parser에 추가
- 정상 수동 개방 fixture와 hands-free activation event 혼합 거부 테스트를 추가하고 acceptance/migration 문서를 동기화

## [2026-08-01] test | PR #26 수정 후 독립 재검증

- immutable artifact digest, 이전 버전 install/boot/health rollback evidence, reset prior/new boot 관계, uint64 상한, causation cycle 거부 회귀 테스트를 재실행
- hands-free access, authenticated manual button access, Target OTA, Target rollback positive fixture의 validate/evaluate와 unittest 18건 통과
- JSON Schema Draft 2020-12 meta-schema와 fixture event 53건을 검사하고 의도된 sequence overflow maximum 위반을 확인

## [2026-08-01] test | PR #24 3차 독립 보안·통합 리뷰 승인 및 main 병합

- RELAY-G0/G1/G2 fail-closed 12개 negative vector, ACL power-loss/semantic rejection 14개 vector, canonical P-256 verifier, 16개 protocol unit tests, 18개 OTA contract unit tests, 18개 observability unit tests 모두 통과
- single `relay_resistant_channel=true` 우회 차단, 수동 원격 개방(manual door-open `POST /api/v1/door/open`) 경로 독립 사용성 및 계약 보존 확인
- PR #24 ready 전환 및 main 병합 완료, GitHub issue #16 closed 확인

## [2026-08-01] code | Android OS-managed BLE wake Wave 0 PoC

- Added the filtered `BluetoothLeScanner` + `PendingIntent` path, exact iBeacon manufacturer filter, Flutter-independent native receiver/entrypoint, durable event journal, and opt-in boot/package-replace re-registration.
- Added debug-only synthetic injection, a 20-attempt PowerShell reproduction script, and host JVM tests for filter and percentile contracts without representing synthetic observations as radio evidence.
- Kept Samsung screen-off, Activity-exit, ordinary process-kill, and reboot measurements at 20 runs each, plus OTA-G1 through OTA-G3, explicitly pending.

## [2026-08-01] test | Android BLE wake hardwareless PoC verification

- Existing Flutter tests passed 5/5, Android `:app:testDebugUnitTest` passed 6/6, and `flutter build apk --debug` produced `app-debug.apk`.
- The PowerShell harness parsed successfully; no installed-APK synthetic run or Samsung radio test was executed because `adb devices` reported no attached device.

## [2026-08-01] lint | Android BLE wake ADR and wiki consistency

- Verified local wiki links, no `raw/` changes, `git diff --check`, and synchronized ADR, environment, implementation-plan, OTA-contract, and index pages.

## [2026-08-01] lint | PR #27 independent Android BLE wake review

- Independently reviewed issue #14/#23, the ADR, and PR #27 at `07e7d27`; confirmed filtered `PendingIntent` scan selection, exact iBeacon manufacturer prefix/mask, Android 12+ mutable explicit `PendingIntent`, non-exported production receivers, Flutter-independent native journaling, unsupported force-stop/OEM contract, and legacy/OTA separation.
- Re-ran Flutter tests (5/5), forced JVM tests (6/6), and the debug APK build; verified the PowerShell harness parses, package/merged-manifest receiver attributes are correct, wiki links are intact, `git diff --check` passes, and `raw/` is unchanged.
- Recorded that repository-wide Android lint still has two pre-existing `MainActivity.kt` API-level errors and Flutter analyze has 17 pre-existing vendored-plugin info findings; PR-changed paths add no lint error. No ADB device was attached, so Samsung radio trials remain 0/20 and issue #14 plus OTA-G1/G2/G3 remain open hardware gates.

## [2026-08-01] fix | main CI와 production OTA release trigger 분리

- firmware/APK 일반 main push와 기본 canary dispatch는 build/test/OTA contract 검증 및 Actions canary 보존까지만 수행하고 production release/SFTP job을 skip하도록 변경
- 운영 NAS 배포는 쓰기 권한자의 명시적 `workflow_dispatch` `release_target=production`과 `production` GitHub Environment를 요구하는 별도 job으로 격리
- production job은 동일 run의 canary를 다시 내려받아 OTA-G0~G4·physical evidence·운영 승인, pinned Ed25519 서명, 실제 artifact size/SHA-256 및 APK signing certificate 검증을 통과한 뒤에만 SFTP 실행
- push가 production 경로에 진입하거나 explicit release가 evidence validator·동일 artifact binding을 우회하면 실패하는 정적 workflow regression test 추가
- dual-slot/health rollback, periodic HTTPS·authenticated local recovery, mobile updater 독립성, N/N-1 및 인증된 모바일 수동 문 열기 경로 불변조건은 변경하지 않음

## [2026-08-01] test | PR #28 독립 리뷰에서 production release 격리 차단 결함 확인

- OTA unit test 22건과 observability test 18건, `manual_remote` validate/evaluate, OTA contract, actionlint, YAML/JSON/schema parse, wiki 상대 링크, Python compile, ESP32-C6 PlatformIO build와 `git diff --check`는 통과했고 OTA-G1~G4 pending release가 fail-closed로 거부됨을 확인
- 기존 4개 정적 mutation test는 통과했지만 허가 조건 뒤 push OR 추가, evidence step `if: false`, signing key 환경 변수의 비밀키 외 값 재결합, evidence 검증 뒤 artifact 교체 mutation은 모두 validator를 통과해 push authorization·evidence·pinned trust·동일 artifact 보장을 강제하지 못함
- firmware/APK workflow에는 `pull_request` trigger가 없어 PR에서 실제 build/test/canary upload가 실행되지 않고 PR #28 Actions도 OTA P0 check 1개만 실행됐으며, GitHub Environments API는 environment 0개와 `production` 404를 반환해 보호 Environment가 실제로 구성되지 않음
- PR은 최신 main과 충돌하는 draft 상태이며 위 release 격리 결함 수정, 실제 protected `production` Environment 구성과 PR build/canary 증거 전에는 ready 전환·병합하지 않기로 판정
- 변경 범위가 orchestration·문서·validator test에 한정되어 dual-slot/rollback, periodic HTTPS·authenticated local recovery, updater 독립성, N/N-1 및 인증된 `manual_remote` 출입 계약 자체는 변경되지 않음

## [2026-08-01] test | PR #28 기본 canary workflow 실실행 검증

- head `c23792c`에서 OTA contract run `30702094971`, firmware canary `30702095030`, Android canary `30702095023`을 `workflow_dispatch` 기본 canary 대상으로 실행해 모두 성공
- firmware와 Android run 모두 contract/test, 실제 build, canary artifact upload를 완료했고 각각의 production deploy job은 실패가 아니라 `skipped`로 종료되어 default canary가 production release validation·SFTP에 진입하지 않음을 확인
- 이 성공은 명시적 canary dispatch 경로만 증명하며 PR 자동 build/canary trigger 부재, production Environment 미구성, 정적 validator 우회와 main 충돌 차단 판정은 그대로 유지

## [2026-08-01] fix | PR #28 workflow 구조화 검증 및 우회 차단 구현

- `ota_contract_gate.py`에 PyYAML 기반 `load_workflow_yaml` 및 구조화된 `validate_workflow_release_triggers` / `validate_workflow_artifact_bindings`를 추가
- `if:` 조건에 `|| push` 등 임의 확장 차단, evidence step `if:` 비활성화 차단, `OTA_SIGNING_PUBLIC_KEY_HEX` provenance의 secret 직결 강제, release validation과 SFTP deploy step 간 순서 불변성 및 임의 step 삽입 차단 검증 구현
- firmware 및 APK workflow 모두 `pull_request` trigger 포함 검증 및 PR 시 compile-only secrets/debug APK 빌드로 안전한 canary artifact 생성 보장

## [2026-08-01] test | PR #28 우회 수단 adversarial unit tests 및 Environment 문서화

- `test_ota_contract_gate.py`에 31개 단위 테스트(adversarial bypass 테스트 4건 포함: build job의 production environment 사용 차단, SFTP 후속 step 삽입 차단, needs 누락 차단, signing key secret 우회 차단) 통과
- `wiki/env_setup.md` 및 `wiki/ota_operations_runbook.md`에 `environment: production` 기계적 검증(precondition) 및 Coordinator API 기반 external state 구성 요구사항 반영
- actionlint, `git diff --check`, 31개 OTA tests, 18개 observability tests, 16개 protocol tests 전건 통과 확인

## [2026-08-01] docs | PR #28 production Environment 외부 보호 구성 반영 및 최종 감사

- Coordinator가 GitHub API를 통해 `production` Environment의 필수 승인자(`tworimpa`) 및 `main` 전용 브랜치 보호 정책을 실제 구성함을 확인하고 `wiki/env_setup.md`에 문서화 반영
- workflow release job의 `environment: production` 기계적 검증(deployment precondition) 및 31개 OTA tests, 18개 observability tests, 16개 protocol tests, actionlint, PlatformIO esp32c6 빌드, `git diff --check` 재검증 통과

## [2026-08-01] test | PR #28 구조화 release gate 재리뷰 차단 결함 확인

- 코드 fix `04740b8`과 Environment 기록 `68c6c85`를 독립 재검증해 OTA 31건, observability 18건, protocol 16건, `manual_remote` validate/evaluate, actionlint, YAML/JSON/schema, wiki link, Python compile, ESP32-C6 PlatformIO build를 통과
- PR Actions `30703085787`, `30703085742`, `30703085760`에서 contract, firmware와 Android debug APK build·canary upload가 성공하고 두 production job은 `skipped`였으며, 실제 `production` Environment의 필수 reviewer `tworimpa`와 custom branch policy `main`을 API로 확인
- 기존 OR-push, evidence `if: false`, 잘못된 secret env, 별도 artifact replacement mutation은 거부되지만 evidence `continue-on-error`, release 명령 `|| true`, run 내부 signing key 재정의, 같은 step의 검증 후 artifact 교체, SFTP `local_path` 재결합, 검증 전 중복 SFTP, object형 build production Environment, 일반 build shell SFTP mutation 8건은 validator가 허용함을 확인
- 구조화 validator가 evidence 실행 성공, signing secret의 shell provenance, 단일 SFTP와 exact upload identity, 같은 step 내 artifact 불변성, ordinary build의 모든 production/SFTP 경로를 fail-closed로 강제하기 전에는 ready 전환·병합하지 않기로 판정
- 최신 main은 merge parent로 통합됐고 manual mobile button 출입, dual-slot/rollback, periodic HTTPS·authenticated local recovery, updater 독립성, N/N-1, size/SHA-256, APK certificate와 OTA-G0~G4 계약 파일은 변경되지 않았으며 issue #23의 실기기 Gate는 open으로 유지

## [2026-08-01] fix | PR #28 release gate 8개 우회 수단 구조화 검증 및 fail-closed 차단

- `ota_contract_gate.py`에 continue-on-error, error swallowing (`|| true`, `; true`, `set +e`), run 내부 `OTA_SIGNING_PUBLIC_KEY_HEX=` 재정의, 검증 후 동일 step artifact 변형, SFTP `local_path` 재결합, 중복/조기 SFTP step, object형/non-exact production Environment, build job의 shell SFTP/production capability 8개 우회 수단을 강제로 차단하는 구조화 검증 구현
- evidence 실행 성공, signing secret provenance, 단일 SFTP와 exact upload identity, 동일 step 내 artifact 불변성, build job의 모든 production/SFTP 경로 차단을 fail-closed로 검증

## [2026-08-01] test | PR #28 8개 우회 수단 adversarial unit tests 및 종합 회귀 검증

- `test_ota_contract_gate.py`에 8개 bypass adversarial unit test를 추가하여 총 39개 OTA contract unit test 전건 통과
- 18개 observability unit test, 16개 protocol unit test, actionlint, `git diff --check`, ESP32-C6 PlatformIO 빌드 전건 재검증 통과

## [2026-08-01] test | PR #28 final independent release-gate review remains blocked

- Re-reviewed head `ba6d90c`, issue #23, prior reviews, the full diff and Actions; confirmed current main is integrated and the live `production` Environment requires reviewer `tworimpa` with the sole custom deployment branch policy `main`.
- Re-ran 39 OTA, 18 observability and 16 protocol tests, authenticated `manual_remote` validate/evaluate, OTA contract/release rejection, actionlint, YAML/JSON/schema/JSONL/link/compile/diff/raw checks, and the ESP32-C6 PlatformIO build; all passed, while OTA-G1 through OTA-G4 remain honestly pending.
- PR Actions runs `30703927174`, `30703927170`, and `30703927185` passed OTA, firmware, and Android contract/test/build/canary coverage; both production jobs were accurately skipped and no SFTP step ran.
- Structured mutation review still found accepted bypasses in both firmware and APK validators: same-line evidence error swallowing, same-line post-validation artifact replacement, `printf -v`/`read` signing-key rebinding, duplicate evidence identity, alternate SFTP actions in release/build jobs, and ordinary-job `curl --upload-file` deployment.
- Posted COMMENTED review `4834849103`; PR #28 remains draft and unmerged, and issue #23 remains open for unavailable OTA-G1 through OTA-G4 physical/operator evidence.

## [2026-08-01] fix | PR #28 블랙리스트 검증을 엄격한 Canonical Allowlist Schema로 전면 대체

- release job 및 ordinary build job 검증에 블랙리스트 방식을 제거하고 정형 allowlist schema (`ALLOWED_BUILD_ACTIONS`, `CANONICAL_RELEASE_STEPS`) 적용
- exact job keys, exact ordered steps, exact action versions, exact run bodies, exact secret/env 및 artifact binding, exact top-level permissions/triggers를 기계적으로 강제하고 임의의 extra action, run command, key, step, same-line wrapper, error swallowing, key rebind, artifact mutation, curl upload-file, duplicate evidence, SFTP variant를 기본 차단(fail-closed)

## [2026-08-01] test | PR #28 리뷰 4834849103의 11+ 변종 우회 공격 adversarial unit tests 및 50+ OTA 검증

- `test_ota_contract_gate.py`에 리뷰 4834849103의 11개 변형 수단(same-line `|| true`, same-line `&& cp`, `printf -v`/`read` key rebind, duplicate evidence identity, alternate scp/sftp action, ordinary job `curl --upload-file`, 임의의 unknown action/step, top-level key/permission/trigger 오염, unallowed job)에 대해 양쪽 워크플로우(`deploy.yml`, `build_app.yml`) 검증을 수행하는 12개 adversarial unit test를 추가해 총 50개 OTA contract unit test 전건 통과
- 18개 observability unit test, 16개 protocol unit test, actionlint, `git diff --check`, ESP32-C6 PlatformIO 빌드 전건 통과

## [2026-08-01] test | PR #28 canonical allowlist final review remains blocked

- Re-reviewed head `6d77f22` and reproduced all prior mutations against both firmware and APK workflows; the exact current workflows and the 50 nominal OTA tests pass, and PR Actions `30704554373`, `30704554344`, and `30704554347` are green with both production jobs skipped.
- A deterministic 102-case structural audit found 50 accepted deviations, including a `python()` evidence bypass, an `EXIT` trap post-validation artifact replacement, sourced signing-key rebinding, decoy contract/test commands, arbitrary Python HTTP deployment in ordinary jobs, altered PR/main triggers, wrong/duplicate canary artifact paths, allowed-action extra steps, and unknown release step keys.
- The canonical policy is self-authorizing because the PR checkout executes its own mutable `ota_contract_gate.py`; changing a workflow action and its `CANONICAL_RELEASE_STEPS` entry together was accepted by both validators.
- The live `production` Environment still requires reviewer `tworimpa` and the sole custom branch policy `main`; manual_remote and all OTA invariant assets are unchanged, while issue #23 remains open for OTA-G1 through OTA-G4 physical/operator evidence.
- Posted COMMENTED review `4834880424`; PR #28 remains draft and unmerged until exact trusted workflow schemas replace the partial, PR-mutable allowlist.

## [2026-08-01] code | Bootstrap trusted workflow-policy Gate

- Added a base-branch `pull_request_target` workflow with read-only contents permission, base-SHA-only sparse checkout, and GitHub API candidate byte retrieval; PR code is never checked out or executed.
- Added a stdlib trusted validator and machine-readable exact digest policy protecting firmware/APK/OTA workflows, the OTA gate, and its dependency lock as one indivisible bundle.
- Bootstrap policy accepts only current `origin/main` `8c36ead` or preapproved PR #28 head `7bae62f`; mixed bundles, missing files, and arbitrary byte changes fail closed.

## [2026-08-01] compile | Trusted policy trust boundary and rotation contract

- Documented UTF-8 LF normalization, SHA-256 bundle matching, candidate policy/validator self-modification isolation, and the two-step post-PR #28 policy rotation.
- Confirmed the change does not alter manual mobile door-open, runtime firmware/app behavior, OTA rollback/recovery/N/N-1 contracts, or pending physical OTA Gate status.

## [2026-08-01] test | Trusted workflow-policy adversarial coverage

- Added tests for exact main/PR #28 bundles, line-ending normalization, arbitrary byte mutation, mixed bundle rejection, missing files, strict policy schema, approved current-checkout evidence, and PR-side policy/validator self-modification isolation.

## [2026-08-01] lint | Trusted workflow-policy bootstrap verification

- Verified the actual GitHub Contents API maps `8c36ead` to `origin-main-bootstrap` and `7bae62f` to `pr-28-preapproved` without checking out candidate code.
- Passed 30 repository unit tests including 12 trusted-policy adversarial tests, OTA contract validation, Python compile, actionlint, workflow YAML and policy/OTA JSON parsing, wiki relative-link lint, `git diff --check`, and raw-source immutability check.
- No physical Target or Android OTA trial was performed; OTA-G1 through OTA-G4 remain pending and issue #23 stays open.

## [2026-08-01] fix | PR #28 branch `origin/main` (PR #29 `420783fc`) 병합 및 Trusted Policy `pr-28-preapproved` 검증

- PR #29가 `origin/main` (`420783fc`)으로 병합됨에 따라 `origin/main`을 `tworimpa/fix-main-ci-release-gate`에 히스토리 재작성 없이 병합
- 5개 보호 대상 파일 (`deploy.yml`, `build_app.yml`, `ota_contract.yml`, `scripts/ota_contract_gate.py`, `ota/requirements.txt`)을 `7bae62f` 승인 번들 바이트로 보존
- `verify_trusted_workflow_policy.py` 실행 결과 후보 번들이 `pr-28-preapproved`와 100% 일치함을 기계적으로 검증
- 수동 모바일 출입 및 미결 OTA-G1~G4 물리 증거 상태를 보존하고 12개 trusted policy test, 39개 OTA contract test, 18개 observability test, 16개 protocol test, actionlint, relative link check, `git diff --check`, ESP32-C6 PlatformIO 빌드 전건 재검증 통과

## [2026-08-01] test | PR #28 final trusted-policy review blocked by unresolved wiki conflicts

- Independently verified head `55f8249753e21061b61eaf4d5669dd549796c511`: trusted base run `30706318220` checked base SHA `420783fc`, approved exactly `pr-28-preapproved`, and 12 trusted-policy tests plus a separate 102-case byte-mutation audit rejected every protected-file deviation and PR-side policy self-redefinition.
- Re-ran 50 OTA, 18 observability, 16 protocol, authenticated `manual_remote`, OTA/access/rollback state-machine, actionlint, YAML/JSON/JSONL/schema/link/compile/raw-diff, and ESP32-C6 PlatformIO checks; all passed, and PR runs `30706319098`, `30706319103`, and `30706319133` completed successfully with both production jobs accurately skipped.
- Confirmed the live `production` Environment still requires reviewer `tworimpa` and permits only the custom## [2026-08-02] fix | PR #34 indication epoch token and build verification

- Fixed GATT indication status callback mismatch by introducing `IndicationToken` (output generation, fragment index, connection handle and generation) to discard stale callbacks from aborted indications or previous sessions.
- Added `flushOtaBusy()` before `WAIT_SAFE_STATE` in `OtaManager.cpp` to ensure OTA BUSY indications finish transmission before network HTTP operations start.
- Resolved build compilation errors under `ENABLE_HARDWARELESS_RC=1` by defining missing static `in_flight_token_`, `in_flight_type_`, and `in_flight_valid_` variables in `src/GattServer.cpp` and correcting printf format specifiers.
- Verified all 87 host tests (python/C++) and executed sequential ESP32-C6 PlatformIO builds: default-OFF passed at RAM 47,040/327,680 bytes (14.4%) and flash 1,598,136/7,340,032 bytes (21.8%); feature-ON (`ENABLE_HARDWARELESS_RC=1`) passed at RAM 53,648/327,680 bytes (16.4%) and flash 1,633,096/7,340,032 bytes (22.2%).
- Maintained all manual_remote and OTA invariants without claiming physical device evidence.

## [2026-08-02] code | Backend public-key enrollment와 signed ACL Hardwareless RC 구현

- expand-first MariaDB migration에 tenant canonical ID, public credential lifecycle, ACL snapshot, Target ACK, redacted audit와 OTA metadata/health state를 추가하고 기존 `ble_device_mac`·`auth_key`·manual_remote를 보존
- single-use proof-of-possession enrollment, tenant-scoped admin approve/disable/revoke, canonical deterministic P-256 ACL signing, monotonic version·900초 기본/3600초 hard lease, MQTT push·periodic pull artifact와 idempotent ACK/fleet status API 구현
- revoked/disabled credential은 다음 authoritative snapshot에서 제거하고 stale/equal-conflict/downgrade/invalid signature rejection, legacy device HMAC lookup flag와 Backend outage 중 unexpired local lease 독립성을 자동 시험으로 고정
- primary/fallback OTA metadata와 install/boot health confirmation을 ACL credential 상태와 분리하고 feature init 실패 때 authenticated `manual_remote` 및 기존 APK/version/health 경로가 유지되도록 production-OFF flag로 격리

## [2026-08-02] test | Backend ACL unit·API·isolated MariaDB migration 검증

- isolated SQLite service/API tests에서 tenant boundary, enrollment proof/single-use, approval lifecycle, deterministic shared vector, revocation, stale/downgrade/invalid signature, duplicate ACK, offline lease, audit redaction, legacy flag, N/N-1와 OTA endpoint independence를 검증
- disposable MariaDB 10.11에서 legacy schema→expand migration→N-1 legacy/N write→down migration을 실행하고 기존 legacy row가 rollback 뒤에도 읽히는 것을 확인
- 물리 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader 또는 OTA install/rollback 시험은 수행하지 않았으며 G0-HW, RELAY-G0~G2와 OTA-G1~G4는 pending 유지

## [2026-08-02] fix | Backend ACL 독립 리뷰 보안·동시성 지적 보강

- 승인 credential의 tenant 전체 door 암묵 허용을 제거하고 explicit tenant/door/credential grant만 canonical snapshot entry에 포함하도록 변경
- Target credential을 tenant·Target ID·단일 door에 결합하고 ACK/health body Target 위조와 같은 tenant 내 다른 door pull/ACK를 403으로 거부
- revoke/disable/grant removal과 durable replacement job을 단일 transaction으로 기록하고 영향 door마다 새 monotonic snapshot을 저장·MQTT publish하며 signer/MQTT 실패 후 periodic pull이 같은 queued artifact를 복구하도록 보강
- per-door version atomic counter, duplicate ACK atomic upsert와 conflicting status 거부, legacy tenant UUID mapping과 ACK 이후 audited dual-mode 전환을 구현하고 frozen ACL header의 tenant 부재는 DB와 Target config의 globally unique door ownership으로 fail-closed 처리
- malformed signer 값을 traceback에 노출하지 않고 ACL-only integer parsing을 feature guard 내부로 이동하여 ACL 설정 오류가 manual_remote·OTA 경로를 중단하지 않도록 수정

## [2026-08-02] lint | Backend ACL 보강 후 software-only 회귀 검증

- isolated backend 25개(SQLite/API 및 disposable MariaDB 10.11 concurrent version/ACK·legacy mapping/dual/down 포함), protocol 16개, observability 18개, repository policy/OTA/Hardwareless 81개와 OTA contract gate 전건 통과
- canonical vector verifier, enabled/disabled router smoke, Python compile, `git diff --check`와 added-line secret/injection/eval/pickle/SQL-format scan을 통과
- 물리 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader 또는 OTA install/rollback 증거는 생성하지 않았으며 production enable과 legacy retirement는 계속 차단

## [2026-08-02] fix | Backend ACL 최종 독립 리뷰 차단사항 해소

- Target activation verifier가 trusted signer key-ID set, exact door, protocol overlap, trusted UTC, receipt/current boot identity, canonical digest/signature와 persisted version/digest high-watermark를 모두 확인하도록 보강하고 reboot 후 trusted UTC가 없으면 cached ACL을 fail-closed 처리
- N-1 primary signer와 optional transition signer가 같은 canonical ACL을 dual-sign하도록 구현하고 transition public key 신뢰 배포 후에만 primary를 승격하는 rollback-compatible rotation 절차를 문서화
- enrollment challenge consume와 public credential insert를 SQLite/MariaDB 단일 transaction으로 결합하여 insert 실패 시 challenge가 미사용 상태로 rollback되도록 수정
- legacy lookup 활성화 시 explicit non-empty HMAC key를 필수화하고 Hardwareless RC의 unsafe tenant-wide dual-mode endpoint를 제거하여 expected Target inventory와 전체 ACK/physical evidence 전환 gate를 유지

## [2026-08-02] test | Backend ACL 최종 software-only 회귀 검증

- backend 27개(SQLite/API 및 disposable MariaDB 10.11 포함), protocol 16개, observability 18개, repository Hardwareless/OTA/trusted policy 81개와 OTA contract gate를 통과
- Python compile, Docker Compose config, canonical vector와 `git diff --check`를 통과했으며 물리 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader 또는 OTA install/rollback 증거는 생성하지 않음

## [2026-08-02] lint | PR #36 independent review blocked

- Exact author head `7a1e6f511c10321d99ae5aef7adc5b49508b1d6b`의 전체 diff와 backend ACL enrollment, signing, activation, revocation, migration, Target API, OTA/manual 경계를 독립 검토하고 same-account `COMMENTED` review https://github.com/ks-house/smart-gatekeeper/pull/36#pullrequestreview-4836490385 를 게시
- enrollment challenge가 tenant에만 묶이고 발급 actor에 결합되지 않아 같은 tenant의 다른 인증 actor가 submit할 수 있는 점, 실제 모바일 버튼 대신 admin master-open 경로만 실행하는 `manual_remote` regression, 금지된 `Closes #19`, Windows 기본 code page에서 disposable MariaDB stdin이 손상되는 재현성 문제를 merge blocker로 기록
- `PYTHONUTF8=1` 보정 후 backend 27개와 MariaDB 10.11 migration, repository 81개, protocol 16개, observability 18개, OTA contract, Python compile, Compose, Actionlint, Markdown link, raw/log/diff 검사 및 hosted runs `30727103265`/`30727103255`는 통과했으나 blocker 해소 전 PR은 draft/open/unmerged 유지
- Android/ESP32-C6, BLE/radio, relay/sensor, bootloader, OTA-G1~G4, RELAY-G0~G2 물리 증거는 없으며 production enable과 legacy retirement는 계속 fail-closed

## [2026-08-02] fix | PR #36 blocking COMMENTED review correction

- enrollment challenge에 stable one-way authenticated actor reference를 저장하고 SQLite/MariaDB의 challenge consume `UPDATE`에 tenant·enrollment ID·actor를 함께 조건화하여 credential insert와 단일 transaction으로 결합
- 같은 tenant의 다른 인증 actor와 다른 tenant actor submit을 403/fail-closed로 거부하고 실패 뒤 원 actor가 같은 challenge를 정상 consume할 수 있는 service·API·MariaDB direct negative regression을 추가
- 관리자 master-open 대신 WebView가 실제 전송하는 `manual_click`·approved `device_id`·no API key 요청을 실행하고 hands-free Pre-arm/RELAY 함수 미호출, ACL disabled/init failure와 OTA download 독립성을 명시적으로 검증
- Windows Docker subprocess의 SQL stdin과 stdout/stderr를 explicit UTF-8 strict로 고정하고 migration client charset을 `utf8mb4`로 지정하여 별도 Python encoding 환경변수 없이 MariaDB 10.11 harness가 실행되도록 수정

## [2026-08-02] test | PR #36 correction software-only regression verification

- `PYTHONUTF8`와 `PYTHONIOENCODING`을 제거한 Windows 환경에서 disposable MariaDB 10.11을 포함한 backend 29개, repository Hardwareless/OTA/trusted policy 81개, protocol 16개, observability 18개와 canonical vector verifier 전건 통과
- OTA contract, Actionlint, Python compile, Docker Compose config, wiki relative links, conflict marker, raw/·OTA/runtime immutability, append-only log prefix와 `git diff --check` 전건 통과
- PR body에 issue-closing keyword가 없고 PR #36은 draft/open/unmerged 상태임을 확인했으며 `ACL_MANAGEMENT_ENABLED=false`, authenticated mobile `manual_remote`, OTA 복구 계약과 production fail-closed 상태를 보존
- 물리 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader, OTA-G1~G4 또는 RELAY-G0~G2 증거는 생성하거나 완료로 주장하지 않음

## [2026-08-02] fix | PR #36 Windows review temporary-directory cleanup

- disposable MariaDB 검증 완료 뒤 repository gate의 `TemporaryDirectory()` 6개가 이 worktree의 `.review-tmp` 아래에 남고 managed host에서 재접근할 때 `Permission denied`가 발생하는 증상을 확인
- `Resolve-Path` 결과가 정확히 `C:\Users\shcat\orca\workspaces\smart-gatekeeper\issue19-backend-acl-hermes\.review-tmp`인지 검증하고, 이미 사용한 `mariadb:10.11` image에 해당 디렉터리만 bind mount하여 direct child 6개를 열거
- repository root 또는 wildcard를 사용하지 않고 확인된 6개 경로만 container 내부에서 제거한 뒤 direct-child listing이 비어 있음을 확인했으며, 장시간 완료 시험은 불필요하게 재실행하지 않음
- 증상, host access/ownership 경계라는 원인, scoped container cleanup과 후속 `git status --short`·`git diff --check` 검증 절차를 `wiki/env_setup.md`에 기록

## [2026-08-02] lint | PR #36 corrected-head independent re-review blocked

- Exact corrected head `9ac4bad7843bcca2f7730c9c5be1fca441e35f0f`를 독립 재검토하고 same-account `COMMENTED` review https://github.com/ks-house/smart-gatekeeper/pull/36#pullrequestreview-4836889140 게시
- 기존 review `4836490385`의 actor-bound atomic enrollment, 실제 approved-device `manual_remote` button, issue-closing keyword 제거, Windows explicit UTF-8 MariaDB 재현성 4개 차단사항은 해소됨을 확인
- issue #19 완료 기준의 tenant/credential 비활성화 중 credential disable/revoke는 replacement ACL을 생성하지만 tenant disable은 `acl_tenants` 상태·관리 API·replacement job 연결이 없고 legacy `tenants.is_active=false` 뒤에도 active public credential이 signed ACL에 남는 P1 차단사항을 새로 확인
- Windows에서 Python encoding 보정 없이 real MariaDB 10.11 포함 backend 29개, repository policy/OTA/trusted 81개, protocol 16개, observability 18개, canonical vector, OTA contract, compile/Compose/Actionlint/wiki link·index/raw·protected·OTA·runtime/log 검증과 exact-head hosted checks는 통과
- PR #36은 draft/open/unmerged로 유지하고 production enable·legacy retirement를 차단했으며 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader, OTA-G1~G4 또는 RELAY-G0~G2 물리 증거는 주장하지 않음

## [2026-08-02] fix | PR #36 tenant-disable ACL replacement blocker 해소

- 인증된 tenant-scope admin disable API가 `acl_tenants.status=DISABLED`, 단일 `TENANT_DISABLED` audit 의미와 모든 영향 door의 durable replacement job을 한 transaction으로 기록하도록 구현
- authoritative credential query가 disabled tenant를 제외하고 signer failure는 미생성 job, MQTT failure는 exact generated version을 보존해 periodic pull·idempotent retry가 empty replacement ACL을 복구하도록 보강
- exact retry는 완료 door의 job revision·ACL version·audit를 재생성하지 않으며 enrollment·approve·new grant는 disabled tenant에서 fail-closed, tenant registration과 legacy `is_active=true`는 re-enable하지 않도록 고정
- legacy `is_active=false`는 registration, authoritative publish, enrollment-sensitive operation 또는 periodic pull에서 one-way ACL disable로 명시적으로 reconcile하고 authenticated ACL disable도 mapped legacy row를 같은 transaction에서 비활성화
- `ACL_MANAGEMENT_ENABLED=false`, authenticated approved-device `manual_remote`, hands-free RELAY 경계, mobile/Target OTA 독립성·rollback·recovery 계약은 유지하고 물리 증거를 생성하거나 주장하지 않음

## [2026-08-02] test | PR #36 tenant-disable software-only 회귀 검증

- `PYTHONUTF8`·`PYTHONIOENCODING` 없이 disposable MariaDB 10.11과 migration repeat-apply를 포함한 backend 32개, repository Hardwareless/OTA/trusted 81개, protocol 16개, observability 18개와 canonical vector 전건 통과
- active credential→tenant disable→2개 door empty replacement, no-grant, exact repeat, wrong tenant scope, signer failure, MQTT failure·exact version retry, single audit, legacy inactive one-way mapping과 fail-closed re-enable를 SQLite/API/MariaDB에서 검증
- authenticated mobile `manual_remote`, hands-free 분리, challenge/credential 보존, OTA metadata/health 독립성, access/manual_remote/Target OTA/rollback fixture validate·evaluate와 OTA contract를 통과
- Actionlint, Python compile, Docker Compose, 6 YAML·22 JSON·9 JSONL parse, 39 Markdown link·23-page index, conflict marker, raw/protected/runtime/OTA immutability, append-only log와 `git diff --check` 통과
- ignored build-only `include/secrets.h`를 제거한 뒤 ESP32-C6 PlatformIO build가 RAM 47,032/327,680 bytes, flash 1,594,368/7,340,032 bytes에서 성공했으며 `.review-tmp`와 disposable MariaDB container 잔여물이 없음을 확인
- Android/ESP32-C6 실기기, BLE/radio, relay/sensor, bootloader, OTA-G1~G4 또는 RELAY-G0~G2 물리 증거는 생성하거나 완료로 주장하지 않음

## [2026-08-02] fix | Windows managed-runner PlatformIO global lock 경계 기록

- sandbox 내부 `pio run -e esp32c6`가 compile 전에 user-global `C:\Users\shcat\.platformio\platforms.lock`을 열지 못해 `PermissionError`로 실패하는 증상을 재현
- 원인은 worktree-only sandbox write scope와 PlatformIO package manager의 user-global lock/cache 접근 경계이며 firmware source나 pioarduino package 오류가 아님을 확인
- 동일한 `pio run`만 scoped PlatformIO 권한으로 재실행하고 ignored example-based `include/secrets.h`를 `finally`에서 정확히 제거하는 안전 절차를 `wiki/env_setup.md`에 기록
- scoped 재실행은 RAM 47,032/327,680 bytes, flash 1,596,456/7,340,032 bytes에서 성공했고 종료 후 관련 process와 `include/secrets.h`가 남지 않음을 확인

## [2026-08-02] lint | PR #36 exact author head 최종 독립 재검토 clean

- Exact local·remote·PR author head `4481209cfd64864712c7164872c83408502fa483`와 current main `b9c39b629c3e162be68760acfa224dd1f43b4389`를 대조하고 issue #19, 전체 16-file diff, 이전 same-account `COMMENTED` reviews 3개와 correction replies를 독립 재검토
- authenticated tenant-scoped idempotent disable, atomic `DISABLED` state·단일 audit·모든 영향 door durable job, disabled-tenant snapshot exclusion, monotonic empty replacement, signer/MQTT failure와 periodic pull recovery, exact retry version/audit idempotency를 SQLite/API/MariaDB에서 확인
- wrong tenant·same-tenant wrong actor·no grant·multi-door·repeated call, enrollment/approve/grant fail-closed, legacy `tenants.is_active` one-way boundary, approved-device `manual_remote`와 hands-free RELAY 분리, ACL initialization failure와 mobile/Target OTA 독립성을 확인
- `PYTHONUTF8`·`PYTHONIOENCODING` 없이 disposable MariaDB 10.11을 포함한 backend 32개, repository 81개, protocol 16개, observability 18개, canonical vector, OTA contract, live trusted-policy `current-main-baseline`, Actionlint와 Docker Compose를 통과
- tracked 7 YAML·7 YML·22 JSON·9 JSONL·18 Python parse, 39 Markdown·193 relative link, wiki index, append-only 140,689-byte main log prefix, raw/protected/runtime/OTA immutability, conflict marker와 `git diff --check`를 통과
- author head hosted OTA/trusted runs `30731646894`·`30731646303`가 성공했으며 Android/ESP32-C6 실기기, BLE/radio, relay/sensor, bootloader, OTA-G1~G4 또는 RELAY-G0~G2 물리 증거는 생성하거나 완료로 주장하지 않고 production enable·legacy retirement를 계속 차단

## [2026-08-02] fix | Windows managed-worktree Git administrative lock 경계 기록

- verified review 문서 2개를 explicit staging하려 할 때 parent repository의 external `.git\worktrees\issue19-backend-acl-hermes\index.lock` 생성이 worktree-only sandbox에서 `Permission denied`로 실패하는 증상을 확인
- visible worktree가 아니라 Git common administrative directory에 index lock을 써야 하는 managed-worktree 경계가 원인이며 source 권한이나 repository corruption이 아님을 확인
- `git status`·explicit diff·`git diff --check`로 범위를 먼저 고정하고 verified path의 add/commit만 scoped Git administrative access로 실행한 뒤 clean status와 remote head를 재검증하는 절차를 `wiki/env_setup.md`에 기록

## [2026-08-02] code | Issue 18 Hardwareless RC Connectable GATT Transport & Coexistence 구현

- ESP32-C6 Connectable GATT transport (`GattServer.h`, `GattServer.cpp`) 구현: compile (`ENABLE_HARDWARELESS_RC`) 및 runtime (`ConfigManager::getHardwarelessRcEnabled`) default-OFF feature flag 설정
- 기존 iBeacon manufacturer payload (`0x004C`, `02 15`, UUID `a1b2c3d4-e5f6-7890-abcd-ef1234567890`) 및 AD Flags `0x1A` 100% 보존하면서 Connectable GATT Service UUID `9f4d1000-7d9e-4fb1-9c54-6f4d53474b31` scan response 탑재
- Canonical GATT characteristics (Hello `9f4d1001-...`, Challenge `9f4d1002-...`, Proof `9f4d1003-...`, Result `9f4d1004-...`), N/N-1 protocol version negotiation, 138-byte canonical challenge, 103-byte proof write, single-use CAS, 5s challenge expiry, 2s proof write completion, disconnect cleanup 및 connection limits 구현
- OTA busy 중 GATT auth `BUSY` (reason=8) 거부 및 릴레이 safe-state arbitration, 텔레메트리 (`heap_free`, `heap_min`, `stack_high_watermark`, `latency`, `boot_id`, `reset_reason`) 지원
- Boot relay OFF 및 fail-safe (GPIO23 active-low, esp_timer), SDA GPIO6, SCL GPIO7 I2C bus clear, pioarduino ESP32-C6 RISC-V, dual-slot OTA rollback, authenticated `manual_remote` explicit mobile button door-open 보존
- `tests/test_hardwareless_rc.py` deterministic tests (100 cycles, fuzz/malformed inputs, timeout/reset, concurrent MQTT/OTA, relay safety, N/N-1, advertisement vs Android filter agreement) 통과
- `python protocol/tools/verify_vectors.py`, `protocol/tests`, `observability/tests`, `tests` 총 88개 host tests 및 PlatformIO `esp32c6` 통합 빌드 통과

## [2026-08-02] lint | PR #34 Hardwareless RC GATT 독립 리뷰 차단

- 최초 author head `111598e40a05a781e28a1b6f3d0b98967f774614`의 전체 diff와 #13/#14/#16/#17/#18/#20/#23, canonical protocol·advertisement filter·observability·OTA 계약을 독립 검토하고 PR을 draft/unmerged 상태로 유지하기로 판정
- 실제 firmware는 BLE server/service/characteristic/callback을 만들지 않고 GATT handler 호출점도 없으며 framing/reassembly, 2초 proof 조립 제한, 최대 1 connection, OTA busy 연결과 canonical telemetry emitter가 구현되지 않음
- `handleProofWrite`는 exact 103-byte 크기, action, credential, signed ACL, raw64 low-S P-256 signature와 canonical input을 검증하지 않고 version/session만 맞는 103-byte 이상 payload에 `OK`를 반환하며 output pointer/length 안전성도 없어 #16/#20 fail-closed 경계를 충족하지 못함
- 새 Python test는 실제 C++를 호출하지 않는 별도 simulator이고 임의 non-zero signature로 relay success를 생성해 100회, malformed, replay, OTA concurrency, advertisement/filter 결과를 firmware/radio/relay 증거로 사용할 수 없음
- compile flag OFF 빌드도 전체 GATT 코드를 compile하고 persisted NVS `hwless_rc=true`로 활성화될 수 있으며, 새 문서가 supplied `AGENTS.md`와 `schema.md`의 relay GPIO3 대신 GPIO23을 완료 상태로 재확인한 충돌도 남음
- 88개 repository, 16개 protocol, 18개 observability test, canonical vector, access/manual_remote/OTA fixture validate·evaluate, OTA contract, actionlint, JSON/JSONL/Python/link/raw 검사와 PlatformIO `esp32c6` build는 통과했으나 disconnected test가 위 blocker를 검출하지 못했고 `tof_test`/`relay_test` env는 정의되지 않아 실행 불가
- 삭제됐던 이전 PR #31 log bullet을 exact 복원하고 `tests/test_hardwareless_rc.py` 두 곳의 trailing whitespace를 제거했으며, Samsung/ESP32-C6 radio·GPIO·relay·sensor·heap·power-loss·bootloader·OTA-G1~G4·RELAY-G0~G2 물리 증거는 생성하거나 주장하지 않음

## [2026-08-02] fix | PR #34 blocking GATT transport and fail-closed boundary correction

- Added the production `GattProtocol.cpp` C++17 parser/session core and wired it through an actual Arduino ESP32-C6 BLE server, primary service, four characteristics, descriptors, bounded callback queue, connection callbacks, MTU framing, confirmed indications, disconnect cleanup and advertising restart.
- Enforced exact 16/20/138/103/32-byte messages, 2,048-byte cap, fragment header/sequence/duplicate consistency, 2-second assembly deadline, rollover-safe 5-second challenge expiry, single connection/session, bounded output copies, CSPRNG boot/session/nonce nonzero and duplicate guards, rate/backoff, critical sections and compile/runtime disable cleanup.
- Added pluggable #20 proof verification with a production default that always fails closed as `ACL_UNAVAILABLE`; only native tests inject the labelled fake verifier, action 2 is rejected, and the GATT transport has no relay or `manual_remote` integration.
- Wired `OtaManager` busy state before blocking HTTP/TLS work with all-terminal-path cleanup and exposed bounded canonical access-event hooks without claiming a complete production envelope, heap/latency or radio evidence.
- Resolved the authoritative relay contract to GPIO3 in `config.h`, pin map, architecture and current guidance while retaining active-low boot OFF safety and explicitly preserving historical GPIO23 observations as historical only.

## [2026-08-02] test | PR #34 executable production-core and contract verification

- Replaced the disconnected Python simulator with a native executable that compiles and runs production `src/GattProtocol.cpp`; 84 repository tests, 16 protocol tests, 18 observability tests and the canonical vector verifier passed.
- Native coverage includes canonical challenge/SHA/framing, N/N-1, compile-OFF stale NVS, runtime disable/reset, strict lengths/ranges, 2,048-byte bound, malformed/fuzz, replay, timeout, fragment sequence/duplicate/consistency, connection limit, OTA busy, rollover, rate limiting, null/capacity safety, CSPRNG guards, fake allow/deny, default fail-closed, action 2 rejection, no relay integration and advertisement/filter agreement.
- Observability access/manual_remote/Target OTA/rollback fixtures validate and evaluate, OTA contract gate, actionlint, Python compile, YAML/JSON/JSONL parsing, relative links/index, raw immutability and `git diff --check` passed.
- PlatformIO `esp32c6` default-OFF build passed at RAM 47,032/327,680 bytes and flash 1,595,598/7,340,032 bytes; a feature-ON build also compiled and linked the real BLE service path. `tof_test` and `relay_test` remain absent from `platformio.ini` and were not fabricated.
- No Samsung/OEM wake, ESP32-C6 radio capture, GPIO3/relay/sensor, heap/soak, power-loss/bootloader, OTA-G1~G4 or RELAY-G0~G2 evidence was produced; PR #34 stays draft, and #13/#14/#17/#18/#20/#23 remain open as applicable.

## [2026-08-02] lint | PR #34 corrected-head independent re-review blocked

- Re-reviewed exact corrected author head `d957718c8a78ee4ef4b0f154020d9c41dcae06b8` against #13/#14/#16/#18/#20/#23, the frozen security and observability contracts, the Hardwareless RC plan, the OTA reliability contract, the full PR diff, the prior COMMENTED review and the author reply; posted blocking same-account COMMENTED review https://github.com/ks-house/smart-gatekeeper/pull/34#pullrequestreview-4836548800 and kept PR #34 draft/unmerged.
- The production C++ core now has strict bounded framing, canonical challenge/proof construction, default-OFF stale-NVS dominance, single-use session handling and a real fail-closed #20 verifier boundary, while action 2 remains rejected and the authenticated explicit-button `manual_remote` chain is unchanged.
- Blocking adapter defects remain: a rejected second BLE connection is not disconnected, write callbacks discard the peer connection ID and queued writes are later attributed to the global active ID, so a second or reconnected peer can inject into another session; indications also fan out through the stack and confirmation failure is not observed before later fragments are popped/sent.
- OTA busy resets an active auth session without a correlatable BUSY result and does not wait for the Target relay/FSM safe state; `EventSink`/`getTelemetry()` have no production sink/caller and the event type is not the canonical uint64/session/boot/sequence envelope required for causal observability.
- The production challenge still hardcodes the canonical test-vector `door_id` instead of a provisioned per-door identity, queue overflow is processed only after already queued writes can complete, and current README/mobile scenario/current audit text still conflicts with the authoritative GPIO3 contract or overstates connection/indication behavior.
- Local evidence passed after rerunning 84 repository tests, the native executable over `src/GattProtocol.cpp`, 16 protocol tests, 18 observability tests, canonical vector verification, access/manual_remote/Target OTA/rollback fixture validation and evaluation, OTA/trusted policy, actionlint, 14 YAML/22 JSON/9 JSONL/13 Python parses, 185 relative links, raw immutability, append-only Git-blob prefix and `git diff --check`.
- Default-OFF ESP32-C6 build passed at RAM 47,032/327,680 and flash 1,597,682/7,340,032 bytes; `ENABLE_HARDWARELESS_RC=1` passed at RAM 49,200/327,680 and flash 1,620,546/7,340,032 bytes. Exact-head hosted OTA P0, firmware canary and trusted-policy checks passed with production skipped.
- No Samsung/OEM, physical ESP32-C6 GATT/MTU/radio/heap, GPIO3 relay/sensor, power-loss/bootloader, OTA-G1..G4 or RELAY-G0..G2 evidence was produced or claimed; production remains fail-closed and the open hardware/operator gates remain open.

## [2026-08-02] fix | PR #34 corrected-head remaining production blockers resolved

- Bound every accepted BLE connection to a handle plus monotonic generation, disconnected rejected peers, retained ownership on queued writes and results, rejected stale reconnect traffic, and targeted confirmed indications only to the accepted subscribed peer.
- Added an adapter-level ACK-gated indication state machine with one fragment in flight, NimBLE `onStatus` advancement, confirmation error/timeout abort, session cleanup, and fail-closed overflow precedence before any queued proof can succeed.
- Added OTA `WAIT_SAFE_STATE` arbitration against the actual access/relay state before network, download, or flash work; a protocol/session-bound `BUSY` result is emitted before reset, and the authenticated explicit-button `manual_remote` path remains independent and is waited out rather than cancelled.
- Wired a canonical production event sink with uint64 monotonic time and sequence, boot/session identity and causal event links; its best-effort MQTT boundary is documented without claiming durable, complete, offline, or physical telemetry evidence.
- Replaced the test-vector door identity with validated provisioned 16-byte configuration, made missing/invalid identity fail closed, added same-core cross-door replay denial, corrected current GPIO3 and executable-contract documentation while preserving historical GPIO23 records, and limited the RNG claim to the conservative implementation actually tested.

## [2026-08-02] test | PR #34 corrected-head adapter and contract verification

- All 87 repository tests passed, including the native production-core executable and shared adapter tests for second-peer rejection, disconnect/reconnect generation races, stale results, targeted subscription ownership, ACK/error/timeout indication behavior, overflow precedence, provisioned identity and cross-door replay denial.
- The protocol vector verifier, 16 protocol tests, 18 observability tests, access/manual_remote/Target OTA/rollback fixture validation and evaluation, OTA contract, trusted-policy coverage, actionlint, structured-file parsing, relative links, wiki index, raw immutability, append-only log prefix and diff checks passed.
- ESP32-C6 default-OFF build passed at RAM 47,040/327,680 bytes and flash 1,596,024/7,340,032 bytes; `ENABLE_HARDWARELESS_RC=1` passed at RAM 53,592/327,680 bytes and flash 1,630,180/7,340,032 bytes and compiled the actual NimBLE adapter path.
- No Samsung/OEM, physical ESP32-C6 GATT/MTU/radio/heap, GPIO3 relay/sensor, power-loss/bootloader, OTA-G1..G4 or RELAY-G0..G2 evidence was produced or claimed; PR #34 remains draft/unmerged and production remains fail closed.

## [2026-08-02] compile | Windows PlatformIO timeout and orphan-build recovery guidance

- Documented the reusable Windows symptom where a wrapper timeout leaves SCons RISC-V compiler children alive and concurrent retries multiply workers, plus the root cause that separate build directories prevent object collisions but do not prevent CPU/disk contention.
- Added a fail-safe procedure to inspect only compiler command lines rooted in the exact worktree, verify PID/parent/creation context before targeted termination, avoid broad Python/compiler kills, and rerun default-OFF and feature-ON sequentially with separate build directories and four jobs.
- Documented the ignored `include/secrets.h` compile prerequisite without exposing values: use only an authorized local secret or ephemeral non-secret placeholder, never stage it, and remove the placeholder after validation.
- Verified the procedure with independent successful default-OFF and feature-ON ESP32-C6 builds, zero remaining worktree-owned compiler processes, no temporary secret/build artifact in Git status, and kept this local software evidence separate from terminal GitHub CI and all pending physical gates.

## [2026-08-02] lint | PR #34 final-head stale indication callback re-review blocked

- Independently re-reviewed exact author implementation head `f0101d2e28850e5a1286991a498c6922296387e0` from local HEAD, fetched remote branch and live PR #34 after reading issue #18, the full diff, prior COMMENTED reviews/replies and the security, observability, Hardwareless RC and OTA contracts; PR #34 remains draft/open/unmerged.
- One P0 adapter blocker remains: production `BLECharacteristicCallbacks::onStatus` supplies no connection or indication epoch, and `handleIndicationStatus()` substitutes the current active owner while `AdapterState::confirmIndication()` matches only owner plus message type. An adversarial native probe aborted one `RESULT`, staged a second same-owner/same-type `RESULT`, then delivered the first result's delayed success and reproduced incorrect advancement as `FragmentConfirmed` with the new confirmation cleared.
- The same missing output-generation boundary affects OTA `BUSY`: `setOtaBusy(true)` aborts a prior indication and immediately stages another `RESULT`, so a delayed prior status can acknowledge the new BUSY fragment. At default ATT MTU 23 the 32-byte result needs four ACK-gated fragments, but an immediately safe Target skips the `WAIT_SAFE_STATE` loop and begins blocking HTTP after only the first fragment is issued, so complete confirmed BUSY delivery is not established.
- The corrected core/adapter otherwise enforces rejected second peers, connection handle plus generation on queued writes/results, stale write/result denial, overflow-before-verifier precedence, WAIT_SAFE_STATE relay/FSM arbitration, validated provisioned nonzero/non-FF 16-byte door identity, same-core cross-door denial, authoritative GPIO3, conservative CSPRNG guards, default-OFF stale-NVS dominance and a compiling feature-ON path.
- Authenticated explicit-button `manual_remote` remains independent: local GATT action 2 is rejected, GATT code has no relay/manual-open integration, the seven-event fixture validates/evaluates, and mobile/backend/manual fixture plus protocol/OTA/protected assets are byte-unchanged from main. Existing dual-slot/rollback, periodic HTTPS, authenticated local recovery, mobile updater independence and N/N-1 contracts are not claimed complete or weakened by this review.
- Local software evidence passed: 87 repository tests, native production-core/shared-adapter executable, 16 protocol tests and canonical vectors, 18 observability tests, access/manual_remote/Target OTA/rollback validate+evaluate, OTA contract and pending-release rejection, trusted-policy mutation tests, actionlint 1.7.12, 14 YAML/22 JSON/9 JSONL with 53 records/13 Python parses, 189 relative links, wiki index, raw immutability, append-only Git-blob prefix, conflict/control/diff checks.
- Fresh sequential ESP32-C6 builds passed with an ignored non-secret placeholder removed afterward: default-OFF RAM 47,040/327,680 and flash 1,595,848/7,340,032; `ENABLE_HARDWARELESS_RC=1` RAM 53,592/327,680 and flash 1,629,676/7,340,032. Exact-head hosted checks `30731181040` trusted policy, `30731181593` OTA P0 and `30731181616` firmware canary succeeded; production deploy was correctly skipped.
- No Samsung/OEM, physical ESP32-C6 GATT/MTU/radio/heap, GPIO3 relay/sensor, power-loss/bootloader, OTA-G1..G4 or RELAY-G0..G2 evidence was produced or inferred. Production, legacy retirement and Epic closure remain fail-closed, and issue #18 plus all applicable hardware/operator gates remain open.

## [2026-08-02] fix | PR #34 indication epoch token and build verification

- Fixed GATT indication status callback mismatch by introducing `IndicationToken` (output generation, fragment index, connection handle and generation) to discard stale callbacks from aborted indications or previous sessions.
- Added `flushOtaBusy()` before `WAIT_SAFE_STATE` in `OtaManager.cpp` to ensure OTA BUSY indications finish transmission before network HTTP operations start.
- Resolved build compilation errors under `ENABLE_HARDWARELESS_RC=1` by defining missing static `in_flight_token_`, `in_flight_type_`, and `in_flight_valid_` variables in `src/GattServer.cpp` and correcting printf format specifiers.
- Verified all 87 host tests (python/C++) and executed sequential ESP32-C6 PlatformIO builds: default-OFF passed at RAM 47,040/327,680 bytes (14.4%) and flash 1,598,136/7,340,032 bytes (21.8%); feature-ON (`ENABLE_HARDWARELESS_RC=1`) passed at RAM 53,648/327,680 bytes (16.4%) and flash 1,633,096/7,340,032 bytes (22.2%).
- Maintained all manual_remote and OTA invariants without claiming physical device evidence.

## [2026-08-02] lint | PR #31 final-head 독립 재리뷰 및 protected merge 승인

- Exact head `d3f5f0dface1f5050e40746549db32af049e5e66`의 전체 7-file diff를 current main `e68f9f401354cd890a50ef5bb3f03cf6b70cc29c` 기준으로 재검토하고 same-account COMMENTED review https://github.com/ks-house/smart-gatekeeper/pull/31#pullrequestreview-4836020674 게시
- G0-SW는 Wave 0 계약 이후 production-OFF feature-flagged #17~#22 구현·리뷰·merge와 자동 software 검증만 허용하며 G0-HW, production enable, physical completion, legacy retirement와 Epic closure는 계속 fail-closed임을 확인
- 인증된 explicit button `manual_remote` chain, runtime, raw/, 5-file protected bundle, 기존 OTA schema/evidence/state/recovery assets, legacy rollback, Target dual-slot health/rollback·periodic HTTPS·인증 local recovery, mobile updater 독립성·fallback과 N/N-1은 main 대비 byte-unchanged
- 81개 repository unit test, protocol 16개, observability 18개, canonical vector와 access/manual_remote/Target OTA/rollback fixture validate·evaluate, 16개 독립 gate negative mutation, OTA contract·pending release 거부, actionlint, 14 YAML/22 JSON/9 JSONL/12 Python, 38 Markdown/188 relative link, index/conflict/diff/immutability 검사 전건 통과
- ESP32-C6 PlatformIO build는 ignored non-secret placeholder `include/secrets.h`로 RAM 47,032/327,680 bytes, flash 1,594,400/7,340,032 bytes에서 통과했고 임시 header를 제거해 worktree를 복원
- `wiki/log.md`는 main 134,068-byte exact prefix와 기존 PR-only 3,964-byte suffix를 보존하고 645-byte merge 기록 뒤 본 reviewer 기록만 append했으며 invalid C0/DEL은 0건
- hosted runs `30721749667`, `30721750617`, `30721750633`, `30721750649`는 exact reviewed head에서 성공하고 firmware/Android production job은 정확히 skipped; Epic #13과 #14/#18/#22/#23, OTA-G1~G4·RELAY-G0~G2·Samsung/OEM·ESP32-C6 radio·relay/sensor·bootloader physical/operator gates는 open/pending 유지

## [2026-08-02] code | Issue #17 hardwareless Android native GATT credential worker

- Added a production-default-OFF WorkManager path from the existing PendingIntent BLE receiver to a Flutter-independent native GATT session with unique-work exclusion, durable HMAC duplicate coalescing, crash-safe session state, bounded retries, exponential backoff, and timeout.
- Added a testable BLE/GATT transport, strict canonical challenge/proof/result and ATT framing codecs, AndroidKeyStore P-256 signing with exact low-S P1363 proof conversion, and a deterministic JVM signer; authentication never creates, logs, or exports a private key.
- Added default-safe validated remote flag semantics and two-sided legacy/native BLE ownership exclusion, fixed Android blocker/outcome reasons mapped to the observability vocabulary, and a read-only Flutter health/reason/latency bridge.
- Preserved the authenticated explicit-button `manual_remote` path and kept the mobile updater plus Target OTA/rollback/recovery contracts independent of every worker flag, failure, and crash state.

## [2026-08-02] compile | Issue #17 native worker contract and operator guidance

- Added `android_gatt_worker.md`, indexed it, linked the #14 wake ADR integration, and documented feature ownership, credential boundaries, durable diagnostics, stable reasons, hardwareless evidence, and pending G0-HW gates.
- Documented the read-only canonical-vector Compose mount, named Gradle cache, bounded `--rerun-tasks` command, and JUnit XML inspection path.
- Did not modify `raw/`; no Samsung/OEM screen-off, real BLE radio, ESP32-C6 interoperability, relay/sensor, bootloader, or physical OTA evidence is claimed.

## [2026-08-02] test | Issue #17 forced JVM, Flutter, and debug APK validation

- Forced `:app:testDebugUnitTest --tests 'com.kshouse.gatekeeper_app.gattworker.*' --rerun-tasks` under a five-minute bound; Gradle executed 208 tasks and completed successfully in 2m52s.
- Inspected three targeted JUnit XML suites: 12 tests, 0 failures, 0 errors, and 0 skips; the full Android JVM run had 18 passing tests.
- Flutter ran 6 passing tests and targeted analysis of the changed Dart bridge/test reported no issues; full analysis retained 17 pre-existing info-level findings under vendored `flutter_beacon_local`.
- Built `gatekeeper_app/build/app/outputs/flutter-apk/app-debug.apk` successfully; hardwareless coverage includes duplicates, retries, timeout, malformed result, network off, worker restart, feature exclusion, canonical vectors, secret redaction, and OTA independence.

## [2026-08-02] lint | Issue #17 Hardwareless RC repository contract verification

- Passed 81 repository gate tests, 16 protocol canonical-vector tests, 18 observability tests, and the standalone canonical-vector verifier.
- Passed Dart format for the changed bridge/test, wiki relative-link validation, `git diff --check`, and raw-source immutability validation; unrelated generated Linux/macOS/Windows Flutter plugin registrants were restored and excluded.
- Confirmed no changes to authenticated `manual_remote`, update manager, OTA evidence/contracts, Target firmware, or `raw/`; G0-HW, Samsung/OEM, ESP32-C6 radio, relay/sensor, bootloader, and OTA-G1 through OTA-G4 evidence remain pending.

## [2026-08-02] test | PR #35 independent native GATT worker review blocked

- Independently reviewed issues #13/#14/#17/#18/#23, the wake ADR, security, observability and OTA contracts, and the complete 23-file diff at exact author head `5f13584c99656de58b12f0e0f2f52bac82100088`.
- Posted same-account COMMENTED blocking review https://github.com/ks-house/smart-gatekeeper/pull/35#pullrequestreview-4836326399: the remote flag trusts a caller-supplied validation bit and cannot atomically stop an already-running legacy scanner, so live flag transitions or restored preferences can violate exclusive BLE ownership.
- Also blocked on the post-proof/pre-ledger-commit crash boundary that can re-run a fresh Target proof/ARM, lossy Target/disconnect reason mapping with ignored `retry_after_ms`, and terminal session history that retains raw device address and credential ID beyond connection need.
- Re-ran Gradle with `--rerun-tasks` (208 executed tasks), inspected five JUnit XML suites with 18/18 passing including targeted GATT 12/12, ran Flutter 6/6 and clean targeted Dart analysis, and rebuilt the debug APK.
- Passed repository 81, protocol 16, observability 18, canonical vector, authenticated `manual_remote` and OTA fixture validate/evaluate, OTA contract, actionlint, Python/JSON/YAML parse, relative-link, conflict, diff and raw immutability checks; green tests do not cover the blocking crash/ownership/reason/privacy boundaries.
- The authenticated explicit-button `manual_remote` runtime chain, mobile updater files, Target firmware/OTA assets, release evidence and `raw/` remain unchanged. PR #35 stays draft/unmerged; Samsung/OEM, real ESP32-C6 radio/relay/sensor/bootloader, RELAY-G0 through G2 and OTA-G1 through G4 evidence remain pending and production/legacy retirement stay fail-closed.

## [2026-08-02] fix | PR #35 four independent-review blockers corrected

- Replaced caller-supplied flag validation with an APK-authority-signed P-256 envelope, bounded issue/expiry window, strict monotonic revision, exact credential/AndroidKeyStore-public-key binding, atomic no-backup state, and fail-closed cleanup of the old preference formats.
- Added a no-backup owner marker and exclusive kernel file lease shared by the vendored legacy scanner and native worker, including live stop/reacquire guards, so two processes cannot concurrently own scanning or native proof/ARM work.
- Added a durable `PROOF_UNCERTAIN` pre-write boundary and encrypted-locator deletion before the first proof byte; restart, post-write crash, post-result crash, and missing final commit cannot repeat proof/ARM for the same wake.
- Preserved every frozen Target result code/name, distinct disconnect/read/write/descriptor/service/framing transport reason and Android status, plus raw and scheduled bounded `retry_after_ms` instead of replacing them with one generic reason.
- Moved the credential ID and transient peer locator to AES-GCM `noBackupFilesDir` records backed by a non-exportable AndroidKeyStore key, changed duplicate identity to a non-exportable keyed HMAC, removed old plaintext preferences/raw-ID aliases, migrated the ledger without sensitive fields, and deleted locators at terminal or uncertain state without logging them.

## [2026-08-02] test | PR #35 corrected Android GATT worker validation

- Forced the final targeted GATT worker Gradle task with `--rerun-tasks`; all 208 tasks executed and the six targeted JUnit XML suites reported 23 tests, 0 failures, 0 errors, and 0 skips.
- Forced the complete Android JVM task separately; all 208 tasks executed and eight XML suites reported 28 tests, 0 failures, 0 errors, and 0 skips.
- Passed Flutter 6 tests, zero-change Dart formatting, clean targeted analyzer, and debug APK build at `gatekeeper_app/build/app/outputs/flutter-apk/app-debug.apk`.
- Passed 81 repository tests, canonical-vector verification and 16 protocol tests, 18 observability tests, authenticated access/manual_remote/Target OTA/rollback fixture validation and evaluation, OTA contract gate, and actionlint.
- Added adversarial flag signature/expiry/replay/key tests, cross-process ownership concurrency, post-proof/post-result process-death recovery, all Target reasons and exact callback failures, bounded retry, duplicate restart/terminal coalescing, and plaintext-ledger migration/redaction coverage.
- Added a restart/clock-rollback retry test and durable remaining-delay enforcement so a redelivered WorkManager item cannot bypass a bounded Target `retry_after_ms` before the replacement request is scheduled.

## [2026-08-02] lint | PR #35 correction diff and invariant verification

- Restored generated Linux/macOS/Windows desktop registrants and removed temporary `.kotlin`/test artifacts outside the Android implementation; `git diff --check`, conflict-marker, relative-link, index, and changed-path consistency checks passed.
- Confirmed `raw/`, authenticated explicit-button `manual_remote`, Backend/Target runtime, mobile update service/UI, OTA contract/evidence/recovery assets, protected workflows, and release gates remain byte-unchanged from main.
- This is software/host evidence only: PR #35 remains draft and unmerged, issue #17 remains open, and no Samsung/OEM, real ESP32-C6/radio/relay/sensor/bootloader, RELAY-G0 through G2, or OTA-G1 through G4 evidence is claimed; production enablement and legacy retirement remain fail-closed pending fresh independent review and physical/operator gates.

## [2026-08-02] test | PR #35 corrected-head re-review remains blocked on in-flight disconnect classification

- Independently reviewed the complete 30-file diff at exact corrected head `a65dcb7e5adaa361e22023550d29d1b3fb33b192` and the prior COMMENTED review `4836326399`; authenticated flag/key binding plus the cross-process lease, durable pre-proof `PROOF_UNCERTAIN` boundary, bounded durable Target retry timing, and encrypted/redacted locator storage correct the other reported blocker classes.
- One lossless GATT classification blocker remains: `onConnectionStateChange()` sends a disconnect only to `GattCallbackMailbox`, while `writeMessage()` and `enableIndication()` wait on separate `writeResult` and `descriptorResult` channels. A disconnect during a proof/client-hello characteristic write or CCCD write therefore cannot wake the in-flight waiter and is reported by the outer timeout as `GATT_TIMEOUT`, losing exact `DISCONNECTED` plus Android status; the mailbox-only callback tests do not cover this production path.
- Forced the complete Android JVM task with `--rerun-tasks`; all 208 tasks executed and eight inspected XML suites reported 29 tests, 0 failures, 0 errors, and 0 skips, including six GATT suites with 23 passing tests. Flutter passed 6 tests, zero-change targeted formatting, and clean targeted analysis; full analysis retained only 17 pre-existing info findings in unchanged vendored `flutter_beacon_local` Dart files.
- Passed 81 repository tests, canonical-vector verification and 16 protocol tests, 18 observability tests, authenticated access/`manual_remote`/Target OTA/rollback fixture validation and evaluation, OTA contract gate, actionlint, relative-link/index, conflict, diff, raw immutability, append-only log, and protected-workflow checks. Hosted Android, OTA, and trusted-policy runs all succeeded on exact head `a65dcb7e5adaa361e22023550d29d1b3fb33b192`, with production deployment correctly skipped.
- The authenticated explicit-button `manual_remote` chain is byte-unchanged and independently passes its seven-event contract outside hands-free RELAY gates. Mobile updater and Target dual-slot health/rollback, periodic HTTPS, authenticated local recovery, N/N-1, protected workflows, release evidence, and `raw/` are unchanged; PR #35 stays draft/unmerged and no Samsung/OEM, physical radio/relay/sensor/bootloader, RELAY-G0 through G2, or OTA-G1 through G4 evidence is claimed.

## [2026-08-02] fix | PR #35 in-flight GATT disconnect propagation corrected

- Replaced buffered characteristic-write and descriptor-write status channels with generation-scoped, single-consumer operation latches bound to the exact `BluetoothGatt` owner, operation kind, and characteristic UUID.
- A disconnect now atomically terminates connection, service-discovery, message, characteristic-write, and CCCD-write waiters exactly once with structured `DISCONNECTED` and the original Android GATT status; every callback state other than successful `STATE_CONNECTED` fails closed.
- Late callbacks after disconnect, callbacks captured by an older reconnect generation, wrong-target callbacks, and duplicate callbacks are ignored instead of becoming a later operation result; the outer session timeout no longer replaces a delivered disconnect with `GATT_TIMEOUT`.
- Preserved exact Target reason/status/retry fields, durable proof uncertainty, authenticated rollout ownership, the independent authenticated explicit-button `manual_remote` path, and mobile/Target OTA recovery invariants.

## [2026-08-02] test | PR #35 final disconnect regression and contract validation

- Forced the complete Android `:app:testDebugUnitTest --rerun-tasks` run under the five-minute container bound; all 208 tasks executed, and fresh XML reported 8 suites, 36 tests, 0 failures, 0 errors, and 0 skips, including 6 GATT worker suites with 30 tests.
- Added adversarial coverage for disconnect during client-hello and proof characteristic writes, disconnect during CCCD write, simultaneous waiter fan-out, exact status preservation, late and duplicate callbacks, reconnect generation isolation, and session-level rejection of timeout misclassification.
- Flutter passed 6 tests, full `lib`/`test` analysis reported no issues, and the debug APK built successfully.
- Passed 81 repository tests, standalone canonical-vector verification and 16 protocol tests, 18 observability tests, authenticated access/`manual_remote`/Target OTA/rollback fixture validation and evaluation, OTA contract validation, and actionlint.

## [2026-08-02] lint | PR #35 final disconnect correction hygiene and evidence boundary

- Documented reusable Windows sandbox temporary-directory, silent Gradle output, generated registrant, and transient worktree `index.lock` difficulties with symptom, cause, safe solution, and verification in `env_setup.md`.
- Restored only tracked Linux/macOS/Windows Flutter registrants from exact HEAD after validation, verified no residual registrant diff or worktree lock, and removed the verified workspace-local `.review-tmp`, generated JUnit/report trees, and Android `.kotlin` test cache.
- `git diff --check`, relative-link/index, conflict-marker, append-only log, raw immutability, protected workflow, manual runtime, OTA/recovery, and changed-path checks pass; no secret or private locator is recorded.
- This remains software/host evidence only. PR #35 remains draft/open/unmerged; no Samsung/OEM, real ESP32-C6 radio/relay/sensor/bootloader, RELAY-G0 through G2, or OTA-G1 through G4 evidence is claimed, and production enablement plus legacy retirement remain fail-closed.

## [2026-08-02] code | Backend public-key enrollment와 signed ACL Hardwareless RC 구현

- expand-first MariaDB migration에 tenant canonical ID, public credential lifecycle, ACL snapshot, Target ACK, redacted audit와 OTA metadata/health state를 추가하고 기존 `ble_device_mac`·`auth_key`·manual_remote를 보존
- single-use proof-of-possession enrollment, tenant-scoped admin approve/disable/revoke, canonical deterministic P-256 ACL signing, monotonic version·900초 기본/3600초 hard lease, MQTT push·periodic pull artifact와 idempotent ACK/fleet status API 구현
- revoked/disabled credential은 다음 authoritative snapshot에서 제거하고 stale/equal-conflict/downgrade/invalid signature rejection, legacy device HMAC lookup flag와 Backend outage 중 unexpired local lease 독립성을 자동 시험으로 고정
- primary/fallback OTA metadata와 install/boot health confirmation을 ACL credential 상태와 분리하고 feature init 실패 때 authenticated `manual_remote` 및 기존 APK/version/health 경로가 유지되도록 production-OFF flag로 격리

## [2026-08-02] test | Backend ACL unit·API·isolated MariaDB migration 검증

- isolated SQLite service/API tests에서 tenant boundary, enrollment proof/single-use, approval lifecycle, deterministic shared vector, revocation, stale/downgrade/invalid signature, duplicate ACK, offline lease, audit redaction, legacy flag, N/N-1와 OTA endpoint independence를 검증
- disposable MariaDB 10.11에서 legacy schema→expand migration→N-1 legacy/N write→down migration을 실행하고 기존 legacy row가 rollback 뒤에도 읽히는 것을 확인
- 물리 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader 또는 OTA install/rollback 시험은 수행하지 않았으며 G0-HW, RELAY-G0~G2와 OTA-G1~G4는 pending 유지

## [2026-08-02] fix | Backend ACL 독립 리뷰 보안·동시성 지적 보강

- 승인 credential의 tenant 전체 door 암묵 허용을 제거하고 explicit tenant/door/credential grant만 canonical snapshot entry에 포함하도록 변경
- Target credential을 tenant·Target ID·단일 door에 결합하고 ACK/health body Target 위조와 같은 tenant 내 다른 door pull/ACK를 403으로 거부
- revoke/disable/grant removal과 durable replacement job을 단일 transaction으로 기록하고 영향 door마다 새 monotonic snapshot을 저장·MQTT publish하며 signer/MQTT 실패 후 periodic pull이 같은 queued artifact를 복구하도록 보강
- per-door version atomic counter, duplicate ACK atomic upsert와 conflicting status 거부, legacy tenant UUID mapping과 ACK 이후 audited dual-mode 전환을 구현하고 frozen ACL header의 tenant 부재는 DB와 Target config의 globally unique door ownership으로 fail-closed 처리
- malformed signer 값을 traceback에 노출하지 않고 ACL-only integer parsing을 feature guard 내부로 이동하여 ACL 설정 오류가 manual_remote·OTA 경로를 중단하지 않도록 수정

## [2026-08-02] lint | Backend ACL 보강 후 software-only 회귀 검증

- isolated backend 25개(SQLite/API 및 disposable MariaDB 10.11 concurrent version/ACK·legacy mapping/dual/down 포함), protocol 16개, observability 18개, repository policy/OTA/Hardwareless 81개와 OTA contract gate 전건 통과
- canonical vector verifier, enabled/disabled router smoke, Python compile, `git diff --check`와 added-line secret/injection/eval/pickle/SQL-format scan을 통과
- 물리 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader 또는 OTA install/rollback 증거는 생성하지 않았으며 production enable과 legacy retirement는 계속 차단

## [2026-08-02] fix | Backend ACL 최종 독립 리뷰 차단사항 해소

- Target activation verifier가 trusted signer key-ID set, exact door, protocol overlap, trusted UTC, receipt/current boot identity, canonical digest/signature와 persisted version/digest high-watermark를 모두 확인하도록 보강하고 reboot 후 trusted UTC가 없으면 cached ACL을 fail-closed 처리
- N-1 primary signer와 optional transition signer가 같은 canonical ACL을 dual-sign하도록 구현하고 transition public key 신뢰 배포 후에만 primary를 승격하는 rollback-compatible rotation 절차를 문서화
- enrollment challenge consume와 public credential insert를 SQLite/MariaDB 단일 transaction으로 결합하여 insert 실패 시 challenge가 미사용 상태로 rollback되도록 수정
- legacy lookup 활성화 시 explicit non-empty HMAC key를 필수화하고 Hardwareless RC의 unsafe tenant-wide dual-mode endpoint를 제거하여 expected Target inventory와 전체 ACK/physical evidence 전환 gate를 유지

## [2026-08-02] test | Backend ACL 최종 software-only 회귀 검증

- backend 27개(SQLite/API 및 disposable MariaDB 10.11 포함), protocol 16개, observability 18개, repository Hardwareless/OTA/trusted policy 81개와 OTA contract gate를 통과
- Python compile, Docker Compose config, canonical vector와 `git diff --check`를 통과했으며 물리 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader 또는 OTA install/rollback 증거는 생성하지 않음

## [2026-08-02] lint | PR #36 independent review blocked

- Exact author head `7a1e6f511c10321d99ae5aef7adc5b49508b1d6b`의 전체 diff와 backend ACL enrollment, signing, activation, revocation, migration, Target API, OTA/manual 경계를 독립 검토하고 same-account `COMMENTED` review https://github.com/ks-house/smart-gatekeeper/pull/36#pullrequestreview-4836490385 를 게시
- enrollment challenge가 tenant에만 묶이고 발급 actor에 결합되지 않아 같은 tenant의 다른 인증 actor가 submit할 수 있는 점, 실제 모바일 버튼 대신 admin master-open 경로만 실행하는 `manual_remote` regression, 금지된 `Closes #19`, Windows 기본 code page에서 disposable MariaDB stdin이 손상되는 재현성 문제를 merge blocker로 기록
- `PYTHONUTF8=1` 보정 후 backend 27개와 MariaDB 10.11 migration, repository 81개, protocol 16개, observability 18개, OTA contract, Python compile, Compose, Actionlint, Markdown link, raw/log/diff 검사 및 hosted runs `30727103265`/`30727103255`는 통과했으나 blocker 해소 전 PR은 draft/open/unmerged 유지
- Android/ESP32-C6, BLE/radio, relay/sensor, bootloader, OTA-G1~G4, RELAY-G0~G2 물리 증거는 없으며 production enable과 legacy retirement는 계속 fail-closed

## [2026-08-02] fix | PR #36 blocking COMMENTED review correction

- enrollment challenge에 stable one-way authenticated actor reference를 저장하고 SQLite/MariaDB의 challenge consume `UPDATE`에 tenant·enrollment ID·actor를 함께 조건화하여 credential insert와 단일 transaction으로 결합
- 같은 tenant의 다른 인증 actor와 다른 tenant actor submit을 403/fail-closed로 거부하고 실패 뒤 원 actor가 같은 challenge를 정상 consume할 수 있는 service·API·MariaDB direct negative regression을 추가
- 관리자 master-open 대신 WebView가 실제 전송하는 `manual_click`·approved `device_id`·no API key 요청을 실행하고 hands-free Pre-arm/RELAY 함수 미호출, ACL disabled/init failure와 OTA download 독립성을 명시적으로 검증
- Windows Docker subprocess의 SQL stdin과 stdout/stderr를 explicit UTF-8 strict로 고정하고 migration client charset을 `utf8mb4`로 지정하여 별도 Python encoding 환경변수 없이 MariaDB 10.11 harness가 실행되도록 수정

## [2026-08-02] test | PR #36 correction software-only regression verification

- `PYTHONUTF8`와 `PYTHONIOENCODING`을 제거한 Windows 환경에서 disposable MariaDB 10.11을 포함한 backend 29개, repository Hardwareless/OTA/trusted policy 81개, protocol 16개, observability 18개와 canonical vector verifier 전건 통과
- OTA contract, Actionlint, Python compile, Docker Compose config, wiki relative links, conflict marker, raw/·OTA/runtime immutability, append-only log prefix와 `git diff --check` 전건 통과
- PR body에 issue-closing keyword가 없고 PR #36은 draft/open/unmerged 상태임을 확인했으며 `ACL_MANAGEMENT_ENABLED=false`, authenticated mobile `manual_remote`, OTA 복구 계약과 production fail-closed 상태를 보존
- 물리 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader, OTA-G1~G4 또는 RELAY-G0~G2 증거는 생성하거나 완료로 주장하지 않음

## [2026-08-02] fix | PR #36 Windows review temporary-directory cleanup

- disposable MariaDB 검증 완료 뒤 repository gate의 `TemporaryDirectory()` 6개가 이 worktree의 `.review-tmp` 아래에 남고 managed host에서 재접근할 때 `Permission denied`가 발생하는 증상을 확인
- `Resolve-Path` 결과가 정확히 `C:\Users\shcat\orca\workspaces\smart-gatekeeper\issue19-backend-acl-hermes\.review-tmp`인지 검증하고, 이미 사용한 `mariadb:10.11` image에 해당 디렉터리만 bind mount하여 direct child 6개를 열거
- repository root 또는 wildcard를 사용하지 않고 확인된 6개 경로만 container 내부에서 제거한 뒤 direct-child listing이 비어 있음을 확인했으며, 장시간 완료 시험은 불필요하게 재실행하지 않음
- 증상, host access/ownership 경계라는 원인, scoped container cleanup과 후속 `git status --short`·`git diff --check` 검증 절차를 `wiki/env_setup.md`에 기록

## [2026-08-02] lint | PR #36 corrected-head independent re-review blocked

- Exact corrected head `9ac4bad7843bcca2f7730c9c5be1fca441e35f0f`를 독립 재검토하고 same-account `COMMENTED` review https://github.com/ks-house/smart-gatekeeper/pull/36#pullrequestreview-4836889140 게시
- 기존 review `4836490385`의 actor-bound atomic enrollment, 실제 approved-device `manual_remote` button, issue-closing keyword 제거, Windows explicit UTF-8 MariaDB 재현성 4개 차단사항은 해소됨을 확인
- issue #19 완료 기준의 tenant/credential 비활성화 중 credential disable/revoke는 replacement ACL을 생성하지만 tenant disable은 `acl_tenants` 상태·관리 API·replacement job 연결이 없고 legacy `tenants.is_active=false` 뒤에도 active public credential이 signed ACL에 남는 P1 차단사항을 새로 확인
- Windows에서 Python encoding 보정 없이 real MariaDB 10.11 포함 backend 29개, repository policy/OTA/trusted 81개, protocol 16개, observability 18개, canonical vector, OTA contract, compile/Compose/Actionlint/wiki link·index/raw·protected·OTA·runtime/log 검증과 exact-head hosted checks는 통과
- PR #36은 draft/open/unmerged로 유지하고 production enable·legacy retirement를 차단했으며 Android/ESP32-C6, BLE/radio, relay/sensor, bootloader, OTA-G1~G4 또는 RELAY-G0~G2 물리 증거는 주장하지 않음

## [2026-08-02] fix | PR #36 tenant-disable ACL replacement blocker 해소

- 인증된 tenant-scope admin disable API가 `acl_tenants.status=DISABLED`, 단일 `TENANT_DISABLED` audit 의미와 모든 영향 door의 durable replacement job을 한 transaction으로 기록하도록 구현
- authoritative credential query가 disabled tenant를 제외하고 signer failure는 미생성 job, MQTT failure는 exact generated version을 보존해 periodic pull·idempotent retry가 empty replacement ACL을 복구하도록 보강
- exact retry는 완료 door의 job revision·ACL version·audit를 재생성하지 않으며 enrollment·approve·new grant는 disabled tenant에서 fail-closed, tenant registration과 legacy `is_active=true`는 re-enable하지 않도록 고정
- legacy `is_active=false`는 registration, authoritative publish, enrollment-sensitive operation 또는 periodic pull에서 one-way ACL disable로 명시적으로 reconcile하고 authenticated ACL disable도 mapped legacy row를 같은 transaction에서 비활성화
- `ACL_MANAGEMENT_ENABLED=false`, authenticated approved-device `manual_remote`, hands-free RELAY 경계, mobile/Target OTA 독립성·rollback·recovery 계약은 유지하고 물리 증거를 생성하거나 주장하지 않음

## [2026-08-02] test | PR #36 tenant-disable software-only 회귀 검증

- `PYTHONUTF8`·`PYTHONIOENCODING` 없이 disposable MariaDB 10.11과 migration repeat-apply를 포함한 backend 32개, repository Hardwareless/OTA/trusted 81개, protocol 16개, observability 18개와 canonical vector 전건 통과
- active credential→tenant disable→2개 door empty replacement, no-grant, exact repeat, wrong tenant scope, signer failure, MQTT failure·exact version retry, single audit, legacy inactive one-way mapping과 fail-closed re-enable를 SQLite/API/MariaDB에서 검증
- authenticated mobile `manual_remote`, hands-free 분리, challenge/credential 보존, OTA metadata/health 독립성, access/manual_remote/Target OTA/rollback fixture validate·evaluate와 OTA contract를 통과
- Actionlint, Python compile, Docker Compose, 6 YAML·22 JSON·9 JSONL parse, 39 Markdown link·23-page index, conflict marker, raw/protected/runtime/OTA immutability, append-only log와 `git diff --check` 통과
- ignored build-only `include/secrets.h`를 제거한 뒤 ESP32-C6 PlatformIO build가 RAM 47,032/327,680 bytes, flash 1,594,368/7,340,032 bytes에서 성공했으며 `.review-tmp`와 disposable MariaDB container 잔여물이 없음을 확인
- Android/ESP32-C6 실기기, BLE/radio, relay/sensor, bootloader, OTA-G1~G4 또는 RELAY-G0~G2 물리 증거는 생성하거나 완료로 주장하지 않음

## [2026-08-02] fix | Windows managed-runner PlatformIO global lock 경계 기록

- sandbox 내부 `pio run -e esp32c6`가 compile 전에 user-global `C:\Users\shcat\.platformio\platforms.lock`을 열지 못해 `PermissionError`로 실패하는 증상을 재현
- 원인은 worktree-only sandbox write scope와 PlatformIO package manager의 user-global lock/cache 접근 경계이며 firmware source나 pioarduino package 오류가 아님을 확인
- 동일한 `pio run`만 scoped PlatformIO 권한으로 재실행하고 ignored example-based `include/secrets.h`를 `finally`에서 정확히 제거하는 안전 절차를 `wiki/env_setup.md`에 기록
- scoped 재실행은 RAM 47,032/327,680 bytes, flash 1,596,456/7,340,032 bytes에서 성공했고 종료 후 관련 process와 `include/secrets.h`가 남지 않음을 확인

## [2026-08-02] lint | PR #36 exact author head 최종 독립 재검토 clean

- Exact local·remote·PR author head `4481209cfd64864712c7164872c83408502fa483`와 current main `b9c39b629c3e162be68760acfa224dd1f43b4389`를 대조하고 issue #19, 전체 16-file diff, 이전 same-account `COMMENTED` reviews 3개와 correction replies를 독립 재검토
- authenticated tenant-scoped idempotent disable, atomic `DISABLED` state·단일 audit·모든 영향 door durable job, disabled-tenant snapshot exclusion, monotonic empty replacement, signer/MQTT failure와 periodic pull recovery, exact retry version/audit idempotency를 SQLite/API/MariaDB에서 확인
- wrong tenant·same-tenant wrong actor·no grant·multi-door·repeated call, enrollment/approve/grant fail-closed, legacy `tenants.is_active` one-way boundary, approved-device `manual_remote`와 hands-free RELAY 분리, ACL initialization failure와 mobile/Target OTA 독립성을 확인
- `PYTHONUTF8`·`PYTHONIOENCODING` 없이 disposable MariaDB 10.11을 포함한 backend 32개, repository 81개, protocol 16개, observability 18개, canonical vector, OTA contract, live trusted-policy `current-main-baseline`, Actionlint와 Docker Compose를 통과
- tracked 7 YAML·7 YML·22 JSON·9 JSONL·18 Python parse, 39 Markdown·193 relative link, wiki index, append-only 140,689-byte main log prefix, raw/protected/runtime/OTA immutability, conflict marker와 `git diff --check`를 통과
- author head hosted OTA/trusted runs `30731646894`·`30731646303`가 성공했으며 Android/ESP32-C6 실기기, BLE/radio, relay/sensor, bootloader, OTA-G1~G4 또는 RELAY-G0~G2 물리 증거는 생성하거나 완료로 주장하지 않고 production enable·legacy retirement를 계속 차단

## [2026-08-02] fix | Windows managed-worktree Git administrative lock 경계 기록

- verified review 문서 2개를 explicit staging하려 할 때 parent repository의 external `.git\worktrees\issue19-backend-acl-hermes\index.lock` 생성이 worktree-only sandbox에서 `Permission denied`로 실패하는 증상을 확인
- visible worktree가 아니라 Git common administrative directory에 index lock을 써야 하는 managed-worktree 경계가 원인이며 source 권한이나 repository corruption이 아님을 확인
- `git status`·explicit diff·`git diff --check`로 범위를 먼저 고정하고 verified path의 add/commit만 scoped Git administrative access로 실행한 뒤 clean status와 remote head를 재검증하는 절차를 `wiki/env_setup.md`에 기록

## [2026-08-02] lint | PR #35 final disconnect classification and contract validation clean

- Merged current `origin/main` (`f732c3dc9c0b4eb5468e9190690368025fd4de0e`) normally into branch `tworimpa/issue17-android-gatt-worker` without history rewrite and resolved `wiki/log.md` merge conflict.
- Independently reviewed exact author head `7dceb0aa0adf13630526f2be19e88eaff5f96015` disconnect waiter semantics: monotonic transport generation isolation, generation-scoped callback capture, operation-scoped single-consumer operation latches, and atomic disconnect propagation preventing in-flight disconnects from misclassifying as `GATT_TIMEOUT`.
- Passed 81 repository unit tests, 16 protocol tests, 18 observability tests, 32 backend tests, and OTA contract gate (`python scripts/ota_contract_gate.py contract`).
- Executed forced Android JVM unit tests with `--rerun-tasks` inside Docker (`gatekeeper-flutter-builder`): 8 test suites, 36 tests, 0 failures, 0 errors, 0 skips (including 30 GATT worker tests).
- Passed Flutter 6 unit tests, zero-change `dart format`, and clean `dart analyze` with 0 issues. Built `app-debug.apk` and verified ESP32-C6 firmware build (`pio run -e esp32c6` with RAM 14.4%, Flash 21.7%).
- Actionlint 0 errors, relative markdown links clean, `git diff --check origin/main...HEAD` 0 errors. Preserved authenticated `manual_remote` and mobile/Target OTA contracts byte-unchanged. Software/host evidence only; Samsung/OEM, physical radio, ESP32-C6 GATT, relay/sensor, bootloader, and OTA-G1~G4 evidence remain pending.

## [2026-08-02] code | Issue #20: Target local ACL verification and access-session FSM implementation

- Implemented `TargetAclManager` for 72B header + 106B entry + 64B SEC1 P-256 raw64 signed ACL parsing, validation, dual-slot NVS storage, and anti-rollback high-watermark versioning.
- Implemented `TargetProofVerifier` for canonical proof verification against active signed ACL with strict low-S (`s <= half n`) constraints.
- Implemented `TargetAccessFsm` and `OfflineEventQueue` for Target-owned access-session state machine (`IDLE -> ARMED -> RELAY_HOLD -> COOLDOWN`) with fail-closed interlocking, MQTT manual remote opening, and OTA safe state classification.
- Integrated components into main firmware (`main.cpp`, `GattServer.cpp`, `MqttManager.cpp`) and passed host C++ unit tests, Python test suites, and PlatformIO ESP32-C6 firmware build.

## [2026-08-02] test | Issue #20 Target local ACL and FSM executable evidence & manual_remote regression

- Added `testDedicatedManualRemoteRegression`, `testAdversarialSignaturesAndLowS`, and `testCrossDoorAndStaleLeaseReplay` to `tests/gatt_protocol_test.cpp`.
- Updated `TargetAccessFsm::handleAuthSuccess` to accept `IDLE` or `ARMED` (when relay is OFF) and fail-closed reject when in `RELAY_HOLD` or `COOLDOWN`.
- Verified 87 repository unit tests, 16 protocol vector tests, 18 observability tests, and OTA contract gate (`python scripts/ota_contract_gate.py contract`).
- Created `wiki/target_acl_fsm.md` and updated `wiki/index.md`.
- Verified sequential PlatformIO builds for `esp32c6`: default-OFF passed (RAM 14.5%, Flash 21.9%), feature-ON passed (RAM 16.5%, Flash 22.4%).
- Host software evidence only; physical device (ESP32-C6, relay, sensor, OTA-G1..G4, RELAY-G0..G2) gates remain open and fail-closed.

## [2026-08-02] fix | Correct target ACL FSM local GATT auth flow and queue generation binding

- Corrected `TargetAccessFsm::handleAuthSuccess` to reject `IDLE` fail-closed and strictly enforce `IDLE -> AUTH_PENDING -> ARMED (proof verified, relay OFF) -> passage sensor trigger -> RELAY_HOLD (relay ON) -> COOLDOWN -> IDLE`.
- Added `TargetAccessFsm::handleAuthAbort` and `GattServer::setOnAuthAbortCallback` to transition `AUTH_PENDING` to `IDLE` immediately on GATT disconnect/proof rejection while preserving verified `ARMED` passage and active relay hold.
- Bound `CanonicalEvent` to queue `generation`. Enforced `evt.generation <= selected_meta.generation` during `OfflineEventQueue::begin()` to prevent reboot recovery of overwritten records on meta save power-loss.
- Updated queue overflow to drop 2 oldest records and enqueue BOTH explicit `queue_overflow` gap evidence and the incoming real event.
- Updated `wiki/target_acl_fsm.md` diagram and interlock rules.

## [2026-08-02] code | Updated typed canonical event serializer & NVS partition budget

- Fixed canonical event serializer to populate top-level string catalog fields (`event_code`, `stage`, `outcome`, `reason_code`) directly into `CanonicalEvent` string fields (`event_type`, `stage_text`, `outcome_text`, `detail`).
- Updated `MqttManager` reconnect flush loop to reconstruct exact 1.0 top-level string JSON schema on replay without nested catalog objects.
- Updated `OfflineEventQueue::kCapacity` to 8 records and updated NVS budget `static_assert` to cover dual max ACL snapshots (6924 bytes * 2) + 8 queue records + 2 meta records <= 18 KiB NVS allocation.
- Updated `HostProofVerifierCallback` input parameter in `TargetProofVerifier` to `std::array<uint8_t, 61>` binding all signing input bytes.
- Updated unit tests in `tests/gatt_protocol_test.cpp` for capacity 8, valid 36-character UUID strings, uint64 monotonic > UINT32_MAX, top-level string schema, and verified all 283 host tests pass cleanly.

## [2026-08-02] fix | PR #37 canonical local GATT lifecycle and build remediation

- Added a host-testable `LocalGattLifecycleBridge` bound only to verified local GATT sessions, preserving one session ID, strict sequence/causation order, post-proof disconnect handoff, catalog-valid arm timeout, and terminal state clearing; kept MQTT pre-arm and authenticated `manual_remote` independent.
- Guarded relay failsafe handling to run only once from relay-on `RELAY_HOLD`, and added exact order, causation, no-duplicate, completed-disconnect, dynamic queue-capacity, full ACL digest, and source-bound production sink configuration regressions.
- Fixed production canonical sink configuration for both the direct sink and lifecycle bridge, fail-closed queue linkage, checked JSON measurement/serialization, C++ header/`const char*` build errors, and queue overflow formatting.
- Antigravity quota was exhausted and work was handed to an Orca dispatched worker without assuming agent resumption; preserved the existing dirty worktree and documented Windows PlatformIO incremental diagnostic guidance in `wiki/env_setup.md`.
- Passed native host C++ 359 checks, repository 87 tests, protocol 16 tests, observability 18 tests, backend ACL/API/legacy independence 30 tests, OTA contract, trusted workflow policy, Actionlint, Python compileall, relative links/raw/wiki checks, `git diff --check`, and sequential ESP32-C6 default-OFF (RAM 15.4%, Flash 22.0%) plus feature-ON (RAM 17.4%, Flash 22.5%) builds.
- Evidence remains hardwareless software-only; Samsung/OEM, ESP32-C6 BLE/radio, GPIO3 relay/sensor, bootloader rollback, OTA-G1..G4, and RELAY-G0..G2 physical gates remain pending and production enable remains blocked.

## [2026-08-02] fix | PR #37 firmware build evidence correction

- The earlier PR #37 default-OFF/feature-ON build claim was based on stale artifacts that predated the final Hermes source edits; the generic `.pio/build/esp32c6/firmware.elf` was also zero bytes.
- That earlier build claim is superseded and is not merge evidence. Fresh clean builds in new unique directories are required before recording replacement evidence.

## [2026-08-02] test | PR #37 fresh clean Hermes firmware build evidence

- Task evidence window started at `2026-08-02T18:14:49+09:00`; both builds used native Windows paths produced with `cygpath -w` so PlatformIO wrote into the intended worktree directories.
- Fresh clean default-OFF build in `.pio/build-pr37-hermes-off` exited 0: RAM 50,392/327,680 bytes (15.4%), Flash 1,617,040/7,340,032 bytes (22.0%); `firmware.elf` is 21,923,936 bytes at `2026-08-02 18:25:54 +0900` and `firmware.bin` is 1,672,304 bytes at `2026-08-02 18:25:55 +0900`.
- Fresh clean feature-ON build in `.pio/build-pr37-hermes-on` with `PLATFORMIO_BUILD_FLAGS=-DENABLE_HARDWARELESS_RC=1` exited 0: RAM 57,080/327,680 bytes (17.4%), Flash 1,652,602/7,340,032 bytes (22.5%); `firmware.elf` is 22,282,012 bytes at `2026-08-02 18:31:08 +0900` and `firmware.bin` is 1,714,576 bytes at `2026-08-02 18:31:09 +0900`.
- All four artifacts are nonzero and have modification times after the task evidence-window start. This is software build evidence only; Samsung/OEM, ESP32-C6 BLE/radio, relay/sensor, bootloader rollback, OTA-G1..G4, and RELAY-G0..G2 physical gates remain open.

## [2026-08-02] lint | PR #37 fresh-build follow-up consistency clean

- Re-ran native GATT/ACL/FSM/queue host tests (359 checks) and the Python hardwareless suite (6 tests); both passed.
- `git diff --check`, raw immutability, wiki index coverage, normalized append-only log prefix, and all relative Markdown links passed.
- Removed only `.review-tmp*` test scratch directories and retained the ignored fresh OFF/ON build directories as evidence; no commit, push, review, ready, or merge action was performed.

## [2026-08-02] fix | PR #37 Linux GCC UUID copy portability

- GitHub Actions runs `30742120599` and `30742120609` confirmed that Linux GCC rejects four exact-length UUID `std::strncpy(..., size - 1)` calls under `-Werror=stringop-truncation`, while the Windows MinGW GCC 5.1 host compiler did not surface the warning.
- Replaced only the four UUID field copies in `testOfflineCanonicalEventReplayAndPreservation` with explicit `constexpr char` arrays, compile-time destination-size validation, and `std::memcpy` including the NUL terminator; the shorter non-UUID `target_ref` copy remains unchanged.
- Added direct trailing-NUL checks for all four UUID fields. The exact WSL Ubuntu GCC 11 `-Wall -Wextra -Werror` repro changed from four compile errors to a passing native binary with 363 checks.

## [2026-08-02] test | PR #37 Linux GCC UUID portability verification

- `python -m unittest discover -s tests -p test_*.py -v` passed all 87 tests using the Windows MinGW GCC 5.1 host toolchain.
- The focused WSL Ubuntu GCC 11 build with `-std=c++17 -Wall -Wextra -Werror` passed and its GATT/ACL/FSM/queue binary passed 363 checks, confirming both the Linux CI warning fix and the Windows-host compatibility of explicit `static_assert` messages.
- Long PlatformIO builds were intentionally not rerun because this remediation changes only host test code and documentation; physical gates remain unchanged and open.

## [2026-08-04] fix | Resolve PR #37 P0 blockers for ACL capacity, OTA FSM, and queue overflow

- Fixed TargetAclManager NVS boot buffer undersize by updating slot_buffer to kMaxAclBlobSize (6920 bytes) to support up to 64 signed ACL entries.
- Fixed MqttManager MQTT buffer capacity from 2048 to 8192 bytes to prevent signed ACL push payload truncation.
- Fixed OtaManager and GattProtocol FSM interaction by ensuring setOtaBusy does not terminate completed/consumed GATT sessions, preserving physical lifecycle events during WAIT_SAFE_STATE.
- Fixed OfflineEventQueue overflow handling to set canonical gap event details with exact sequence ranges (e.g. dropped seq 1-2) and canonical event code 1007.
- Verified 366 host C++ checks, 87 Python unit tests, 18 observability tests, vector verifiers, OTA contract gate, and clean ESP32-C6 PlatformIO build.

## [2026-08-05] code | Issue #21: Flutter Thin UI, User Fallback, and Legacy Feature Flag implementation

- Implemented CredentialService for Device ID, tenant registration, approval status badges, and ACL lease snapshot management.
- Implemented FeatureFlagService with strict interlocks preventing simultaneous ENABLE_HARDWARELESS_RC and ENABLE_LEGACY_PREARM activation (preventing duplicate ARM triggers).
- Added in-app rollback capabilities to Legacy REST Pre-arm flow without requiring app reinstallation.
- Extended MethodChannel in MainActivity.kt and NativeGattWorkerHealthBridge with triggerLocalGattRetry for 1-tap manual local GATT entry.
- Built SmartKeyControlScreen dashboard with 1-Tap Manual Local GATT Retry button, Credential status, Native Worker Health, Feature Flag controls, OEM battery recovery guidance, and independent OTA Update Manager.
- Passed 5 Flutter unit tests, clean flutter analyze, 369 host C++ checks, 87 Python unit tests, 18 observability tests, vector verifier, and OTA contract gate.

## [2026-08-05] test | Issue #22: E2E fault injection, hardwareless release candidate gate verification, and rollout runbook completion

- Verified two-tier authorization structure: software release candidate gate (G0-SW: passed) vs physical device gate (G0-HW: pending).
- Executed E2E fault injection matrix (FI-01 through FI-10) and validated software failure handling across artifacts, signatures, network isolation, and protocol N/N-1 compatibility.
- Verified hardwareless implementation gates contract (tests/test_hardwareless_implementation_gates.py: 4/4 PASS).
- Verified OTA contract gate (ota_contract_gate.py contract: PASS).
- Created wiki/hardwareless_implementation_gates.md and updated wiki/index.md.
- Maintained fail-closed production release block while physical devices (Samsung phone & ESP32-C6 target board) are disconnected.

## [2026-08-08] compile | Orca multi-agent orchestration profile system (.orca/)

- Created master Orca multi-agent orchestration guide (.orca/ORCA.md).
- Defined gpt5.6-sol profile (.orca/profiles/gpt5.6-sol.md) for Coordinator, System Architect, and Gatekeeper (Effort: high).
- Defined terra profile (.orca/profiles/terra.md) for Target ESP32-C6 firmware and Backend infrastructure (Effort: high).
- Defined luna profile (.orca/profiles/luna.md) for Android native, Flutter UI, and E2E QA fault injection (Effort: high).
- Created PowerShell terminal launcher script (.orca/scripts/launch_profiles.ps1) and spec/done templates (.orca/templates/).
- Updated wiki/index.md Meta section.

## [2026-08-08] fix | Rename Orca multi-agent profiles to gpt5.6- prefixed convention

- Renamed .orca/profiles/terra.md to .orca/profiles/gpt5.6-terra.md.
- Renamed .orca/profiles/luna.md to .orca/profiles/gpt5.6-luna.md.
- Updated .orca/ORCA.md, .orca/profiles/gpt5.6-sol.md, and .orca/scripts/launch_profiles.ps1 to adopt gpt5.6-sol, gpt5.6-terra, and gpt5.6-luna profile names.

## [2026-08-08] compile | Add gpt5.6-antigravity profile (.orca/profiles/gpt5.6-antigravity.md)

- Created gpt5.6-antigravity profile for Senior Full-Stack Lead & Emergency Task Executor (Effort: high).
- Updated .orca/ORCA.md, .orca/profiles/gpt5.6-sol.md, and .orca/scripts/launch_profiles.ps1 to incorporate gpt5.6-antigravity.

## [2026-08-08] fix | Update antigravity profile to use agy CLI command without gpt5.6- prefix

- Renamed .orca/profiles/gpt5.6-antigravity.md to .orca/profiles/antigravity.md.
- Updated CLI command in launch_profiles.ps1 and sol profile to use agy for antigravity profile.
- Updated .orca/ORCA.md to list agy CLI command for antigravity profile.

## [2026-08-08] fix | Add YOLO auto-approval flags (--ask-for-approval never, --dangerously-skip-permissions) to Orca profiles

- Updated .orca/scripts/launch_profiles.ps1 to pass --ask-for-approval never --dangerously-bypass-approvals-and-sandbox for codex and --dangerously-skip-permissions for agy.
- Updated .orca/ORCA.md and .orca/profiles/gpt5.6-sol.md to document YOLO auto-approval flags.

## [2026-08-08] test | gpt5.6-terra profile smoke validation

- Inspected `include/config.h`: ultrasonic pins are GPIO10/GPIO11 and relay control is GPIO3 with `RELAY_ACTIVE_LOW = true`; Target ACL code rejects invalid signatures, replay/rollback, and monotonic-clock reset fail-closed, while OTA checks safe state and TLS CA validation.
- Inspected representative backend ACL/OTA management paths: tenant disable queues `TENANT_DISABLED` replacement snapshots, cross-tenant door binding is rejected, OTA fallback URLs must differ, and health confirmation must bind the published artifact digest.
- `python -m unittest discover -s backend/tests -p test_*.py` passed: 32 tests, 1 skipped; `python protocol/tools/verify_vectors.py` passed for `protocol/test_vectors/v1.json` (`sgk-canonical-test-vectors-v1`).
- Focused format/prefix sanity passed: the required log header/type format and firmware `[INFO]` relay-log prefix are present; this is software-only evidence. No physical ESP32-C6, GPIO3 relay, sensor, boot/rollback, or OTA device validation was available or performed; those gates remain pending and fail-closed.

## [2026-08-08] test | gpt5.6-luna profile smoke validation

- Inspected Android/Flutter feature-flag surfaces: `ENABLE_HARDWARELESS_RC` and `ENABLE_LEGACY_PREARM` are strictly interlocked; in-app `rollbackToLegacy()` selects legacy only; the native BLE wake entrypoint is independent of Flutter and OTA UI state; WorkManager GATT scheduling has no network constraint and health reports `updateManagerIndependent=true`.
- Inspected OTA independence surfaces: Flutter `UpdateChecker` checks and downloads APK updates independently; the Smart Key screen exposes the independent OTA manager; Target/mobile contract assets preserve dual-slot health rollback, installed APK/credential preservation, and access-independent OTA behavior.
- `python -m unittest discover -s observability/tests -p test_*.py` passed: 18 tests; `python scripts/ota_contract_gate.py contract` passed; `python -m unittest tests/test_hardwareless_implementation_gates.py` passed: 4 tests.
- Focused format/prefix sanity passed for the new entry and firmware `[INFO]` prefix; a strict historical scan found 10 pre-existing `feat`/`audit`/`docs` headers outside the prescribed six types, and older log bytes were left unchanged. Samsung/OEM and physical Target/OTA gates remain open and fail-closed; no physical device validation was performed.

## [2026-08-08] test | antigravity profile smoke validation

- Inspected cross-layer `manual_remote` and mobile/Target OTA fail-closed boundaries: `manual_remote` (`POST /api/v1/door/open` -> MQTT `gatekeeper/force_open`) is strictly isolated from hands-free local GATT (action 2 rejected in `GattProtocol`), active if ACL init fails (`ACL_MANAGEMENT_ENABLED=false`), and allowed in Target FSM when relay is OFF; Target OTA (`OtaManager`) asserts `OtaSafeState::SAFE` (`classifyOtaSafeState`) before network/flashing, waiting for active sessions to finish, and maintaining dual-slot rollback.
- Executed `python -m unittest discover -s tests -p "test_*.py"`: 87 tests run, 86 passed, 1 failed (`test_production_cpp_core` in `test_hardwareless_rc.py` due to Windows `subprocess.run(shell=True)` `Access is denied` on `g++.exe` toolchain fallback).
- Evaluated launcher argv compatibility: `agy --dangerously-skip-permissions --effort high` matches `agy` options (`--dangerously-skip-permissions` auto-approves permissions; `--effort` sets reasoning effort); `codex --model $modelId -c model_reasoning_effort="high" --ask-for-approval never --dangerously-bypass-approvals-and-sandbox` matches `codex` options (`-m`, `-c`, `-a`, `--dangerously-bypass-approvals-and-sandbox`). Confirmed that neither CLI accepts Markdown profile paths via `--profile`, validating `launch_profiles.ps1` prompt injection design.
- Clearly separated evidence: Host/software tests (369 C++ checks, 86/87 Python tests, contract gates) are verified software evidence only; physical gates (ESP32-C6 target board, GPIO3 relay, AJ-SR04T ultrasonic sensor, Samsung phone BLE wake, bootloader rollback, OTA-G1..G4, RELAY-G0..G2) remain open (`pending / fail-closed`).

## [2026-08-08] lint | gpt5.6-sol coordinator profile smoke validation

- PASS — Role/scope coverage is coherent across the four current profiles: Sol owns orchestration, architecture, review, and release gates; Terra owns Target firmware/backend; Luna owns Android/Flutter/QA; Antigravity supplies explicit cross-layer emergency coverage.
- PASS — Current `codex --help` accepts `--model`, `-c/--config`, and `--dangerously-bypass-approvals-and-sandbox`, and defines `--profile` as a `$CODEX_HOME/<name>.config.toml` layer rather than a Markdown role file; current `agy --help` accepts `--dangerously-skip-permissions` and `--effort high`. The launcher argv and its `terminal create -> tui-idle -> Markdown bootstrap/PROFILE_READY -> tui-idle -> dispatch --inject` sequence therefore match the current low-level custom-argv Orca guidance.
- PASS — Sol and the master guide correctly require Run/Task provenance, rolling `check --wait`, exact injected Dispatch capability and Task/Dispatch IDs, exactly one `worker_done`, worker release or immediate reuse before Delivery ACK, and treat `state: ready`, heartbeat, TUI activity, and timeout as liveness rather than completion.
- FAIL — Terra, Luna, and Antigravity still show numbered newline `worker_done --body` placeholders instead of the current required exactly three-sentence executive summary (what changed, what was found, what remains); the injected lifecycle preamble remains authoritative, but the profile examples can induce a nonconforming completion report.
- FAIL — Antigravity says it may carry emergency work through final merge without restating Sol-owned independent review, physical Gate, and user merge authorization, while `.orca/ORCA.md` labels `G0-SW` statically `passed` rather than binding it to the exact release-candidate SHA and current evidence. Sol's own gatekeeper rules are fail-closed, but these two cross-profile statements should not be treated as merge or deployment authority.
- PASS — The Terra, Luna, and Antigravity smoke entries honestly separate host/software results from physical evidence, disclose the Antigravity 86/87 Python result, and leave Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, boot/rollback, OTA-G1..G4, and RELAY-G0..G2 pending and fail-closed; this audit performed no physical acceptance and does not change those gates.

## [2026-08-08] fix | Correct and verify Orca profile launch and lifecycle contracts

- Corrected `.orca/scripts/launch_profiles.ps1` to use supported argv: Codex now receives `--model gpt-5.6-{sol,terra,luna}`, `-c model_reasoning_effort="high"`, and `--dangerously-bypass-approvals-and-sandbox` without the mutually exclusive `--ask-for-approval`; Antigravity receives `--dangerously-skip-permissions --effort high`. Markdown role files are loaded through a bootstrap prompt rather than the CLIs' incompatible `--profile` flags.
- Added PowerShell-safe `${Profile}` interpolation, agent-start shell fallback detection, bounded rolling idle waits, and explicit `PROFILE_READY` completion detection accepting both `PROFILE_READY <name>` and `PROFILE_READY: <name>` before any Task dispatch. Final live launcher probes passed for `gpt-5.6-terra high` and Antigravity CLI 1.1.11, and both loaded their exact role files without edits before returning idle.
- Updated `.orca/ORCA.md`, `gpt5.6-sol.md`, all worker profiles, and `worker_done_template.md` to use `run-create --objective`, current custom-argv orchestration flow, rolling completion waits, exact injected capability/IDs, three-sentence completion bodies, release-or-reuse before Delivery ACK, conditional independent review/user merge authority, and exact-SHA/current-evidence `G0-SW` rather than a static pass.
- Orca Run `run_5c7d64c77a53` completed all four profile Tasks with exactly one accepted `worker_done` each: Terra backend 32 tests (1 skipped) and vectors passed; Luna observability 18, OTA contract, and hardwareless 4 passed; Antigravity reported 86/87 root Python tests; Sol found two documentation blockers which were corrected above.
- Reproduced the remaining root-suite failure independently: `tests.test_hardwareless_rc.HardwarelessRcProductionCoreTest.test_production_cpp_core` fails on Windows with `Access is denied` from its `subprocess.run(shell=True)` compiler invocation. This profile-focused change does not alter that test/source path; no Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, or RELAY-G0..G2 physical evidence was produced, so those gates remain pending and fail-closed.

## [2026-08-08] lint | Reconfirm Orca profile remediation status

- Live Orca runtime status is ready; Run `run_5c7d64c77a53` still records all four profile smoke Tasks as completed, with no unread coordinator messages.
- Reconfirmed the tracked remediation scope and clean `git diff --check`; `raw/` remains unchanged and the pre-existing untracked `.codex-remote-attachments/` directory remains untouched.
- No tests or physical-device checks were rerun during this read-only status audit. The separate Windows compiler-invocation failure and all Samsung/OEM, ESP32-C6, relay/sensor, boot/rollback, OTA-G1..G4, and RELAY-G0..G2 physical gates remain pending and fail-closed.

## [2026-08-08] lint | Reconfirm current GitHub issue inventory

- Queried `ks-house/smart-gatekeeper` through GitHub and confirmed 12 repository issues in total: 1 open and 11 closed; pull requests were excluded from the count.
- The only open issue is #13, `[EPIC] 추가 자격 하드웨어 없는 모바일 병목 축소 재설계`; this inventory check did not change any GitHub issue state.

## [2026-08-08] lint | Recheck unchanged GitHub issue count

- Requeried `ks-house/smart-gatekeeper`: the issue inventory remains unchanged at 1 open, 11 closed, and 12 total, with pull requests excluded.
- Issue #13 remains the only open issue; no GitHub issue state was changed by this check.

## [2026-08-08] lint | gpt5.6-terra Windows firmware/backend/OTA environment audit

- PASS — PlatformIO Core 6.1.19 resolves the installed pioarduino ESP32-C6 platform and dual-OTA partition; Docker Engine 29.6.2 (Linux), WSL Ubuntu GCC 11.4, Python 3.11.15, the ignored local `include/secrets.h`, and the backend/OTA Python dependencies are present. The shared Hermes Python environment has unrelated `pip check` conflicts (`certifi` and `starlette` constraints), so the fastest safe repeatable setup is a dedicated external Python virtual environment populated from `backend/app/requirements.txt` and `ota/requirements.txt`, not mutation of the shared agent environment.
- PASS — `docker compose -f backend/docker-compose.yml config -q`, `python scripts/ota_contract_gate.py contract`, 50 OTA gate unit tests, `python protocol/tools/verify_vectors.py`, and 32 backend unit tests (one MariaDB integration test correctly skipped without `RUN_MARIADB_INTEGRATION=1`) passed. Full validation still requires a sequential `pio run -e esp32c6`, the opt-in disposable MariaDB integration test, and WSL-native C++ host tests; use the documented scoped PlatformIO cache access if the managed runner cannot acquire `platforms.lock`.
- This is host/software toolchain evidence only: `ota/release-evidence.json` remains `release_blocked=true` with OTA-G1 through OTA-G4 and physical tests pending, and no Samsung, ESP32-C6 radio/GPIO3 relay/sensor, bootloader rollback, recovery, or production acceptance was performed or implied.

## [2026-08-08] lint | gpt5.6-luna Windows Flutter and Android prerequisite audit

- Host audit: Flutter and Dart are absent from PATH and `FLUTTER_ROOT`/`FLUTTER_HOME` are absent; `JAVA_HOME` and active `java` are Java 11, while `gatekeeper_app/android/app/build.gradle.kts` requires Java/Kotlin JVM 17. `ANDROID_HOME` and `adb` 34.0.1 exist, but `sdkmanager`, `apksigner`, Android NDK/CMake, and Android command-line tools are absent; `adb devices -l` has no attached device. Ignored `android/local.properties` points to container paths (`/opt/flutter`, `/opt/android-sdk`) and must not be used as a host Flutter path.
- Safe Windows bootstrap is Docker-first: `docker compose -f gatekeeper_app/docker-compose.yml config -q` passes and Docker 29.6.2/Linux is available, but the builder image is not built; run the documented `docker compose build flutter-builder`, then `docker compose run --rm flutter-builder flutter doctor -v` and `flutter pub get` in the same container. The Dockerfile provisions OpenJDK 17, Android command-line tools/API 33-36, build-tools, NDK 28.2.13676358, CMake 3.22.1, and Flutter, avoiding host PATH/SDK drift.
- Quick test: in that builder run `dart format --output=none --set-exit-if-changed lib test`, `dart analyze lib test`, and `flutter test`; then run `flutter pub get && cd android && ./gradlew --no-daemon :app:testDebugUnitTest --rerun-tasks`, inspecting fresh JUnit XML. Full software test adds `flutter build apk --debug`; release/apksigner and `android_ble_wake_hardwareless.ps1` (20 synthetic ADB trials) remain separate evidence, and Samsung/OEM BLE, ESP32-C6, boot/rollback, OTA-G1..G4, and other physical gates remain pending and fail-closed.

## [2026-08-08] lint | gpt5.6-sol Orca environment architecture audit

- Live Orca `1.4.176` is ready and advertises orchestration plus worker launch-preference support; this Dispatch used `worker-start` effectively with `gpt-5.6-sol` and `high`. The registered repo nevertheless runs setup by default with only `echo "hi"`, uses `start-immediately`, has no archive hook or automation, and currently exposes six live terminals; the worker ledger reports 59 retained legacy/external resources, one released resource, and two active resources, so retained history must be audited rather than mass-closed.
- The tracked profile roles, three-sentence `worker_done` contract, exact candidate-SHA software Gate, physical Gate separation, and current launch argv are coherent. The remaining launcher risks are its hard-coded `orca` executable instead of the session resolver, mandatory approval/sandbox bypass, current-worktree-only setup semantics, and a lower-level `terminal create -> profile bootstrap -> dispatch` path even though Codex workers can now use supervised `worker-start --model ... --effort high`; keep the low-level path only where profile bootstrap or Antigravity custom argv is genuinely required, and make unsafe mode explicit rather than default.
- Minimal tracked architecture proposal: retain `.orca/ORCA.md`, `profiles/`, and `templates/`; add idempotent `scripts/setup.ps1`, read-only `scripts/doctor.ps1`, scoped `scripts/quick_validate.ps1`, `scripts/task_create.ps1`, `scripts/worker_loop.ps1`, and dry-run-first `scripts/cleanup.ps1`. Setup should create only ignored/external caches and verify prerequisites without secrets; doctor should report tool/version/config presence; quick validation should select firmware/backend/mobile/contracts without implying physical evidence; task creation should bind a Run and render exact scope, dependencies, acceptance, and Gate boundaries; lifecycle should wait for `worker_done|escalation|question`, then release or explicitly reuse before ACK; cleanup should release only settled owned workers and require exact selectors plus dirty-state checks before any worktree removal.
- Keep `start-immediately` only if the real setup hook remains lightweight, idempotent, and nonessential to task input; if dependency provisioning becomes a correctness prerequisite, switch to `wait-for-setup` and use composed agent-first `worker-start --setup run`. Do not auto-open all four profiles in every worktree: use one normal shell/default terminal plus on-demand profile workers, and trial only disabled, read-only doctor/quick-validation automations in fresh top-level worktrees with no push, merge, deploy, issue-state, or hardware-Gate authority.
- `git diff --check` and `raw/` immutability passed before this append; all tracked `.orca` files and the version-matched Orca CLI/orchestration guides were read. This audit changed no `.orca` implementation/configuration, performed no merge or physical validation, and leaves Samsung/OEM, ESP32-C6, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, and production authorization pending and fail-closed.

## [2026-08-08] compile | Build repeatable Orca worktree development environment

- Added tracked `orca.yaml` and idempotent PowerShell setup, doctor, validation, and task-start helpers. Orca project settings now run setup by default and wait for setup before agent startup; setup preserves existing ignored secrets, fingerprints isolated `.venv` requirements, resolves the ESP32-C6 PlatformIO environment, and reports host/software versus physical evidence separately.
- Updated the profile launcher to resolve the session Orca CLI, use a sandboxed safe default with explicit `-AllowUnsafe`, and aligned all worker completion examples with Orca 1.4.176 (`worker_done` uses exact Task/Dispatch IDs without obsolete identity/capability flags; coordinator releases exact Dispatch before whole-Delivery ACK).
- Fixed the Windows hardwareless C++ test launcher to pass argv with `shell=False`. `validate.ps1 -Suite Quick`, `-Suite Software`, and `-Suite Firmware` passed, including backend 32 tests (one MariaDB integration skip), protocol 16, observability 18, hardwareless Gate 4, root software 87/87, OTA contract, Compose config, and ESP32-C6 release build (RAM 17.4%, flash 22.5%).
- Built the Docker Flutter/JDK 17/Android toolchain and changed app validation to a scoped, disposable container copy so `pub get` cannot dirty tracked generated files. `dart analyze lib test` completed with seven information-level findings and `flutter test` passed 11/11; strict formatting remains opt-in via `-EnforceFormat`.
- Added `wiki/orca_development_environment.md`, linked it from the navigation map and environment guide, and left automatic scheduled work disabled to avoid surprise cost or repository mutations. No Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, or production evidence was produced; those Gates remain pending and fail-closed.

## [2026-08-08] test | Verify Orca setup in a fresh top-level worktree

- Created `orca-dev-env-smoke` from pushed commit `170b26823b4cf524fee803a5d47beab72fce6b52` through Orca with `--setup run`; the setup terminal created the ignored secret example and isolated `.venv`, installed pinned dependencies, resolved PlatformIO packages, and finished doctor with 12 pass, one native-Java warning covered by the Docker JDK 17 lane, and zero failures.
- Re-ran setup to verify idempotence: existing secret state was preserved, Python requirements were current, and PlatformIO dependencies were already up to date. The fresh-worktree Quick suite passed backend 32 tests (one opt-in MariaDB skip), Compose, protocol 16, observability 18, OTA contract, and hardwareless Gate 4 in about 10 seconds without tracked changes.
- Verified the exact smoke path was clean and removed only that temporary Orca worktree with the managed cleanup command. This host/software smoke produced no physical-device evidence; all Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, and production Gates remain pending and fail-closed.

## [2026-08-08] fix | Close independent Orca environment review blockers

- Hardened optional native probes in `.orca/scripts/doctor.ps1`: non-zero `pip check`, `docker info`, and `gh auth status` results are now captured as structured check data even when PowerShell promotes native failures under `ErrorActionPreference=Stop`. An unavailable-Docker mutation test completed all 14 checks, reported Docker as `warn`, kept the missing native/Docker Flutter lane fail-closed, and did not abort.
- Changed Orca CLI resolution in setup helpers to prefer the ready public `orca` command unless `ORCA_CLI_COMMAND` explicitly selects another runtime; `orca-dev` is now only a public-CLI-absent fallback. The mutation test set a stale `ORCA_DEV_REPO_ROOT` and still reached the public Orca 1.4.176 runtime.
- Made the native Flutter App validation lane copy tracked and non-ignored app sources to a validated randomized temporary directory before `pub get`, analyze, and tests, matching the existing Docker isolation boundary. A fake native Flutter mutation changed only the disposable copy, left `gatekeeper_app/pubspec.lock` unchanged, and left no temporary validation directory.
- Replaced fixed worker completion commands across the master guide, Terra/Luna/Antigravity profiles, template, and environment guide with report-only fields. Every worker must use the exact active Dispatch preamble; staged dispatches may require injected `--from` and `--dispatch-capability`, while supervised workers may omit them, so lifecycle flags must never be reconstructed.
- Normal doctor passed with 12 pass, one Docker-covered native Java 11 warning, and zero failures. Quick validation passed backend 32 tests with one opt-in MariaDB skip, Compose, protocol vectors and 16 tests, observability 18, OTA contract, and hardwareless Gate 4; PowerShell parsing, `git diff --check`, and `raw/` immutability also passed.
- The staged independent reviewer identified the blockers but could not deliver formal `worker_done` because its terminal could not reach the Orca runtime; that dispatch is not counted as completed. No Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, or production evidence was produced, so all physical and production Gates remain pending and fail-closed.

## [2026-08-08] fix | Permit sandboxed Orca lifecycle connectivity

- A fresh exact-head reviewer found no source-level blocker in commit `769af413dd06092436e0f32c2f52ed5590e72567`, but its safe `workspace-write` Codex terminal could not reach the local Orca runtime to submit the required `worker_done`; the review Dispatch was recorded as blocked instead of fabricating completion.
- Updated the safe Codex profile launcher with the official `sandbox_workspace_write.network_access=true` setting. This keeps filesystem access at `workspace-write` while enabling the outbound local-runtime connection required by the injected Orca lifecycle preamble; `-AllowUnsafe` remains an explicit separate mode.
- Updated the master guide and environment guide to document the filesystem/network boundary. This change does not weaken OTA, secrets, independent review, or physical evidence Gates; Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, and production evidence remain pending and fail-closed.

## [2026-08-09] fix | Remove optional MCP startup race from repository workers

- The first sandbox-network lifecycle probe never reached `PROFILE_READY`: Codex reported `MCP startup interrupted` for optional `codex_apps` and `node_repl`, then exited to PowerShell. The coordinator recorded the Task as blocked and closed only its exact terminal; no completion was inferred.
- Updated the dedicated Codex repository-worker argv to disable those two optional MCP servers using the official `mcp_servers.<id>.enabled=false` configuration keys. Workers retain shell, GitHub CLI, repository tools, `workspace-write`, and sandbox network access for Orca lifecycle delivery without waiting on unrelated MCP startup.
- A new minimal lifecycle probe is required before this remedy can be accepted. No physical, operator, or production Gate changed; all Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, and RELAY-G0..G2 evidence remains pending and fail-closed.

## [2026-08-09] fix | Correct optional Codex service disable keys

- The first disable attempt used `mcp_servers.codex_apps.enabled=false`, but `codex_apps` is an Apps feature rather than a configured MCP transport; Codex rejected startup with `invalid transport` before Task dispatch. The exact probe was recorded as blocked and its terminal was closed.
- Replaced that override with `features.apps=false` while retaining the valid `mcp_servers.node_repl.enabled=false`; `codex ... mcp list` accepted the effective configuration and reported `node_repl` disabled. This correction must still pass a real profile bootstrap and accepted `worker_done` probe before the launcher is considered healthy.
- No repository product code or physical Gate changed. Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, and production evidence remain pending and fail-closed.

## [2026-08-09] fix | Move profile bootstrap into initial agent prompt

- Even with valid optional-service overrides, a blank Codex TUI exited before processing the later `terminal send` bootstrap. The exact lifecycle probe never reached Task dispatch and was recorded as blocked; repeating the same post-start injection path was stopped.
- Changed the low-level profile launcher to pass the role bootstrap as the agent CLI's initial positional prompt. The launcher still requires the exact `PROFILE_READY <profile>` marker and a final `tui-idle` before injecting any Task, so startup liveness cannot be mistaken for readiness.
- Updated the Orca master/environment guides. A bounded real probe must produce an accepted `worker_done` before this path is considered healthy; physical, operator, and production Gates remain pending and fail-closed.

## [2026-08-09] test | Verify sandboxed Orca lifecycle end to end

- The initial-argv launcher started `gpt-5.6-luna high`, received exact `PROFILE_READY gpt5.6-luna`, reached final `tui-idle`, and then dispatched Task `task_daa86a1b0856` as Dispatch `ctx_c6ca50693310`.
- The read-only probe sent accepted `worker_done` message `msg_9212c6a7419e` with outcome `succeeded` and no modified files. The coordinator verified the Task state as completed, closed the exact low-level terminal after `worker-release` correctly reported it was not a supervised-worker resource, processed the older heartbeat, and ACKed Delivery `delivery_5a11d0e96a45`; the Run mailbox is now empty.
- This validates profile bootstrap and lifecycle transport only. It does not create Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, or production evidence; those Gates remain pending and fail-closed.

## [2026-08-09] fix | Bound recovery for unsubmitted Orca Dispatch injection

- The exact-head Terra reviewer completed its source review with no source blocker, but the injected Task initially remained as an unsubmitted `[Pasted Content N chars]` prompt until the coordinator sent Enter. Its later `worker_done` was rejected when that worker's Orca runtime became unreachable, so the Task was recorded as blocked and its exact terminal was closed; review prose was not promoted to accepted lifecycle completion.
- Added a bounded post-Dispatch check to `launch_profiles.ps1`: for five seconds it sends one Enter only when the terminal tail ends with the exact unsubmitted paste marker. It sends no input when the marker is absent or the agent has already progressed.
- The first validation probe reproduced a separate intermittent startup exit before Task dispatch. The launcher now closes only that exact terminal and retries startup once in a new terminal; a second exit fails closed instead of looping or inferring readiness.
- Updated the Orca master and development-environment guides. A new isolated lifecycle probe and fresh exact-head review are still required before PR #47 integration; no Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, or production Gate changed.

## [2026-08-09] test | Verify bounded profile startup and Dispatch lifecycle

- The first Luna probe terminal exited to PowerShell before Task dispatch and was closed exactly; the Task had no Dispatch context and remained ready. After the bounded-startup retry change, the next launch reached `PROFILE_READY gpt5.6-luna`, final `tui-idle`, and dispatched Task `task_da730e2c9761` without coordinator input.
- Dispatch `ctx_7f8be9e06621` completed with accepted `worker_done` message `msg_d6d6f8912325`, outcome `succeeded`, and no probe file modifications. The exact low-level terminal was closed after `worker-release` correctly reported it was not a supervised-worker resource, Delivery `delivery_104d4f2e1616` was ACKed, and the coordinator inbox is empty.
- PowerShell parsing, `git diff --check`, and Quick validation passed: doctor 12 pass/1 Docker-covered native Java warning/0 fail, backend 32 tests with one opt-in MariaDB skip, Compose, protocol vectors and 16 tests, observability 18, OTA contract, and hardwareless Gate 4. This is lifecycle and host/software evidence only; all physical, operator, and production Gates remain pending and fail-closed.

## [2026-08-09] fix | Bind Orca recovery actions to current terminal state

- Independent exact-head review of `d1e15b958f4014b551d428912403de0b99f65603` found three lifecycle blockers: a historical PowerShell prompt could trigger a false startup-exit match, an old paste marker could authorize Enter without current-Dispatch provenance, and the second failed startup terminal was not closed before the launcher threw.
- Startup exit detection now requires the current terminal tail to end at a PowerShell prompt, and both failed attempts close only their exact terminal. Dispatch recovery captures `latestCursor` immediately before `dispatch --inject` and reads only output after that cursor before deciding whether the exact terminal-end paste marker permits one Enter.
- The reviewer preserved tracked state and found the exact-SHA trusted workflow successful, but its required `worker_done` could not be accepted after its sandboxed Orca runtime became unreachable; the Task was recorded as blocked and the exact terminal was closed. Fresh mutation tests, lifecycle proof, and exact-head review remain required; physical, operator, and production Gates remain pending and fail-closed.
- A subsequent Luna probe emitted the exact marker followed immediately by Orca's `•Running Stop hook` renderer decoration; the previous whitespace-only boundary missed it and timed out despite a valid response. Marker matching now accepts only whitespace, end-of-text, or that renderer bullet after the exact profile name, so the comma-delimited marker inside the bootstrap instruction remains non-authoritative; bootstrap timeout/final-idle failure closes the exact terminal before failing.
- After bootstrap and cursor-bound Dispatch succeeded, multiple workspace-write workers still reported Orca `runtime_unavailable` while the coordinator runtime remained ready. The official Codex configuration documents `windows.sandbox_private_desktop=false` as the compatibility path for the older default Windows desktop; the safe launcher now applies it alongside workspace-write and sandbox network access so local Orca lifecycle commands can reach the desktop/runtime without granting full filesystem access.

## [2026-08-09] test | Verify Windows sandbox Orca lifecycle compatibility

- Early probe attempts exercised fail-closed cleanup: two consecutive pre-bootstrap Codex exits closed both exact terminals, and a valid marker decorated as `PROFILE_READY gpt5.6-luna•Running` was recognized only after replacing the non-ASCII source literal with the Windows PowerShell-safe regex escape `\u2022`. No Task was dispatched by failed bootstrap attempts.
- With `windows.sandbox_private_desktop=false`, the successful bounded launch reached profile readiness and dispatched Task `task_ce74716d0c3a` as `ctx_dc6f5bf896bb` without coordinator input. The worker delivered accepted `worker_done` message `msg_7f07390548be`, outcome `succeeded`, and no probe file modifications.
- The coordinator processed one older blocked-review heartbeat, verified the exact Dispatch completed, closed the low-level terminal after expected `worker-release` `dispatch_not_found`, ACKed Delivery `delivery_6780cc81a750`, and confirmed an empty inbox. This validates safe Windows lifecycle connectivity only; all physical, operator, and production Gates remain pending and fail-closed.

## [2026-08-09] fix | Close every failed Orca startup terminal

- Independent exact-head review of `030b83509ca716d28dc0cf34e76b9f4e9963301f` mutation-tested three bounded `tui-idle` timeouts and observed zero terminal-close calls: startup wait and snapshot failures occurred before the existing cleanup handler. The other focused marker, cursor, current-tail, exact-SHA policy, and tracked-state checks passed.
- Refactored each startup attempt so all post-create checks share one failure path. A `tui-idle` failure, startup snapshot failure, or current terminal-end PowerShell prompt now records the original error, closes the exact created terminal, retries only the first attempt, and closes the second exact terminal before failing closed.
- The reviewer could not deliver accepted `worker_done` after its sandboxed Orca runtime again became unreachable, so its Task was recorded as blocked and the coordinator closed its exact terminal. A fresh injected timeout mutation, real lifecycle probe, and exact-head review remain required; physical, operator, and production Gates remain pending and fail-closed.
- The coordinator reran the exact injected-timeout mutation against the remediation: two created mock terminal handles each exhausted three bounded wait windows, both exact handles received one close call, and the launcher failed after the second cleanup with the original timeout preserved. Real lifecycle and fresh exact-head review evidence are still required.

## [2026-08-08] compile | Establish evidence-gated commercial release program

- Created `wiki/commercial_release_program.md` with the product objective, evidence levels, dependency DAG, work packages for security/admin, Target, mobile UX, operations, manuals, physical acceptance, and production canary deployment.
- Recorded Orca Run `run_40f9831625bd` and the three independent read-only audits assigned to gpt-5.6-sol, gpt-5.6-terra, and gpt-5.6-luna; no audit worker was authorized to edit, merge, or deploy.
- Kept production fail-closed: administrator authentication, Target TLS fallback, Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator walkthrough, and production install/reboot/health evidence remain required.
- Added the release program to `wiki/index.md`. No `raw/` files or earlier log entries were modified.

## [2026-08-08] test | Complete commercial audits and detect follow-up worker launch failure

- Completed independent Sol architecture/security, Terra firmware/backend/admin/operations, and Luna mobile UX/manual audits at exact local HEAD `dd8996c110fae1b378e31c3b1f8be8db7b84307d`; all three were read-only and sent exact-Dispatch `worker_done` results.
- The auditors passed protocol 16, observability 18, backend 32 with one opt-in MariaDB skip, OTA contract, hardwareless Gate 4, and WSL native C++ 369 checks as applicable. One native Windows root-suite compiler-launch path failed while its WSL equivalent passed; no result was promoted to physical evidence.
- Reproduced a follow-up supervised worker-start failure three times across Terra and Luna: Orca returned `input_accepted`, Codex reported interrupted MCP startup, received the task preamble, then exited to PowerShell while the terminal could still look running. The coordinator stopped every failed Dispatch and did not count them as completion.
- Opened commercial release Epic #48 and scoped issues #49 through #55 for security/admin, Target/OTA, mobile UX, operations, manuals, physical release, and the Orca worker-start blocker. PR #47 remains Draft and unmerged until an independent exact-head review succeeds.
- Production remains fail-closed; no Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, canary, or production evidence was produced.

## [2026-08-09] test | Integrate Orca environment and dispatch commercial release work

- Independently reviewed PR #47 without self-approval, merged it as `b246aff9698ccbcbcd864f99aab63654cce2cc78`, and verified GitHub Actions run `31268170523` reached terminal success. The production deployment job remained skipped and no physical or production acceptance was inferred.
- Re-ran `.orca/scripts/validate.ps1 -Suite Quick` after merge: doctor reported 12 pass, one Docker-covered native Java warning, and zero failures; backend 32 tests with one opt-in MariaDB skip, Compose, protocol vectors and 16 tests, observability 18, OTA contract, and hardwareless Gate 4 passed.
- Dispatched isolated implementation work for issues #49, #50, #51, #53, #54, and #55 from exact integrated `origin/main`; issue #52 remains dependency-blocked until the three P0 product branches are accepted and integrated. The #54 scope is preparation-only and cannot close any hardware, operator, canary, or production Gate.
- Retargeted draft PR #56 to current `main` and preserved both append-only log histories while resolving its only merge conflict. Independent exact-head review and terminal CI are still required before it may be merged.

## [2026-08-09] fix | Correct PR 56 append-only and integration status blockers

- Independent exact-head review of `4f6e8f1761b9393f348173312843454e61c4c5a7` found that the conflict resolution placed two commercial-program entries inside the current `main` history and that the release page and PR body still described merged PR #47 as Draft/unmerged.
- Restored the exact `b246aff9698ccbcbcd864f99aab63654cce2cc78` `wiki/log.md` blob as the byte prefix, moved the two unchanged program entries after that prefix, and retained the later integration entry as an append. No historical entry was rewritten and `raw/` remains unchanged.
- Updated the release baseline, R0 status, current task allocation, and evidence boundary to record PR #47 merge plus run `31268170523` while keeping #55, all physical/operator Gates, and production authorization pending and fail-closed. A fresh exact-head review is required before PR #56 can leave Draft.

## [2026-08-09] fix | Add fail-closed Orca lifecycle longevity harness

- Added `.orca/scripts/probe_lifecycle.ps1` to hold exact HEAD, initial worktree status, immutable `raw/`, ready/reachable runtime identity, and exact Task/Dispatch heartbeat receipts across a default seven-heartbeat, 65-second interval probe. The harness intentionally reports `completionSent=false`; it never sends or impersonates `worker_done`, never echoes a Dispatch capability, and keeps the default Codex `workspace-write` boundary unchanged.
- Added mutation coverage for successful receipts, typed `runtime_unavailable`, runtime identity transition, capability redaction, and the no-completion contract, and included it in Quick/Contracts validation. Documented the packaged Orca 1.4.176 named-pipe transport boundary and fail-closed recovery in the master guide, development guide, navigation map, and `wiki/orca_lifecycle_incident.md`.
- Version-matched packaged source shows named-pipe connect/close failure occurs before optional `orchestrationCapability` reaches the runtime request envelope; worker-side `starting/reachable=false/runtimeId=null` is the status projection of that transport failure while the desktop PID remains alive. This narrows the observed failure upstream of capability verification but does not establish the intermittent named-pipe root cause or a capability-expiry defect.

## [2026-08-09] test | Recheck exact-main Orca lifecycle beyond six minutes

- Coordinator confirmed exact integrated main `b246aff9698ccbcbcd864f99aab63654cce2cc78` post-merge Actions run `31268170523` terminal success and fresh Quick success before issue #55 work; production deploy remained skipped and all physical/operator/production Gates remained open.
- Read-only Task `task_e043a7540909` / Dispatch `ctx_1c1a0ce01ab8` accepted seven heartbeats from `17:17:30Z` through `17:25:32Z`, then accepted final `worker_done` `msg_666e7110dc1e` with `outcome=succeeded` at `17:26:04Z`. Exact clean HEAD and runtime ID `e221a8da-b68b-4655-8f1b-d1bf51b68f36` remained stable; coordinator release closed the agent terminal, captured its transcript, and left only the intentional read-only probe worktree.
- A separate 96-call parallel packaged-CLI status stress probe had zero failures, so simple low-concurrency saturation was not reproduced. PowerShell parsing, `git diff --check`, `raw/` immutability, lifecycle mutations, and Quick passed: doctor 12 pass/1 Docker-covered native Java warning/0 fail, backend 32 tests with one opt-in MariaDB skip, Compose, protocol vectors and 16 tests, observability 18, OTA contract, and hardwareless Gate 4.
- The fresh long probe is a successful non-reproduction, not proof that the earlier same-runtime `runtime_unavailable` is fixed. Packaged-runtime repair, repeated Sol/Terra/Luna initial/follow-up matrices, independent exact-head review, and terminal PR CI remain required; Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, and production Gates remain pending and fail-closed.

## [2026-08-09] fix | Reject lifecycle completion-type mutation

- Independent exact-head review of PR #60 at `2a32fe6d3b824c6242ac837bc80243db93144ff0` found that the test mock accepted any `orchestration send` and could fabricate a heartbeat receipt after mutating the probe's outbound type to `worker_done`; the PR remained Draft and unmerged.
- The mock now requires exact `--type heartbeat`, and an adversarial test rewrites the probe source to `worker_done` and requires a typed non-zero rejection without echoing the Dispatch capability. This closes the no-completion-impersonation test gap while keeping the production probe's `completionSent=false` contract unchanged.
- Focused lifecycle mutations and PowerShell parsing passed after remediation. Fresh Quick validation, a new commit/head, protected CI, and a new independent exact-head review remain required; all physical, operator, and production Gates remain pending and fail-closed.

## [2026-08-09] compile | Prepare deterministic Issue #54 physical Gate evidence package

- Added a pending-only `physical_validation/` plan, JSON Schema, field checklists, evidence template, and forged-pass negative fixture for the Samsung/OEM 100-run wake campaign, ESP32-C6 coexistence, GPIO3 relay, AJ-SR04T, RELAY-G0..G2, OTA-G1..G4 power-cut/recovery, operator drills, and canary stop/rollback.
- Added `scripts/validate_physical_gate_prep.py` and two host-only tests. The validator accepts the all-`not_run` template and rejects a synthetic 100/100 pass claim without raw evidence; this is L0 consistency evidence, not a device/operator/canary result.
- Linked `physical_gate_preparation.md` from the navigation map. No raw source changed, no measurement/physical acceptance/operator approval/production contact/deploy occurred, and every L2/L3/L4 Gate remains pending and fail-closed.

## [2026-08-09] fix | Bind Issue #54 executed evidence to accountable review

- Extended the pending-only schema and production validator so every later executed record requires an execution window, named executor, independent named reviewer or risk owner, plan-bound pass condition and approval role, and an after-execution review decision.
- Replaced opaque raw-evidence strings with exact plan-category entries bound to capture identity/time/actor, SHA-256, and matching content-addressed locator; adversarial tests reject missing actors/times, generic or partial categories, incomplete captures, self-review, empty or wrong-role approval, pass-condition substitution, and the forged-pass fixture.
- The committed template remains entirely `not_run`; no physical measurement, operator approval, canary, production contact, deployment, or Gate acceptance occurred, and `raw/` remains unchanged.

## [2026-08-09] code | Harden admin control plane with deny-by-default identity and dual control

- Added mTLS-fingerprint-backed server sessions, tenant-scoped roles, CSRF, reauthentication, rate limiting, session rotation, idempotency, and immutable audit migration support; missing identity/audit state fails closed rather than returning mock success.
- Replaced device-ID bearer force-open with a reasoned two-person control operation, added negative bypass tests, and preserved target OTA/download recovery separation. This is host/software evidence only; no physical or production authorization is claimed.

## [2026-08-09] compile | Define additive v2 manual control and proxy deployment contract

- Added durable force-open approval and mobile nonce migration contracts, N/N-1 upgrade-required/no-side-effect behavior, plus the private reverse-proxy mTLS deployment boundary for the issue #51/#52 client rollout.

## [2026-08-09] fix | Apply v2 manual proof and durable approval state

- The legacy manual URI now rejects incomplete device-ID requests without an effect, while the v2 envelope verifies tenant-bound proof, nonce expiry, idempotency, and durable replay consumption before broker publication. This remains software evidence only; physical/operator/production gates are open.

## [2026-08-09] test | Add exact-SHA hosted backend and MariaDB security lane

- Added a pull-request CI lane for backend security tests, real MariaDB migration/immutable-audit validation, and private-by-default Compose configuration. Hosted success is still software/CI evidence only and does not close any physical or production gate.

## [2026-08-09] fix | Bind force-open approval to durable row fields

- Corrected the two-person approval path to authorize against the persisted `tenant_scope` and `proposer_subject` fields rather than nonexistent transient aliases, so a valid separately authenticated approver can reach the broker publication transition.
- Added positive and negative security coverage for one successful publication and for self-approval, expiry, replay, cross-tenant approval, and duplicate-publish reservation rejection. This remains software evidence only; physical, operator, and production gates remain open and fail-closed.

## [2026-08-09] fix | Close force-open locks and record broker reconciliation

- Moved all force-open approval validation inside one rollback/close boundary after `SELECT ... FOR UPDATE`, so self, expiry, replay, tenant, duplicate-state, and idempotency rejections cannot leak a MariaDB transaction or lock.
- Added `FORCE_OPEN_PUBLISHED` immutable audit evidence and a migration-backed `RECONCILIATION_REQUIRED` state with its own audit fact for post-broker persistence failures; real MariaDB concurrency verifies one publisher, one final audit, and an immediately reusable row lock. This is software/CI evidence only and leaves physical, operator, and production gates open and fail-closed.

## [2026-08-09] fix | Precommit force-open ambiguity before broker publication

- Changed the approval state transition to commit `RECONCILIATION_REQUIRED` and its immutable operator-visible audit fact before calling MQTT; reconciliation persistence failure now blocks publication, and post-publish final-audit failure retains the prior durable non-success disposition rather than relying on a best-effort recovery write.
- Added mutation coverage for failed reconciliation precommit, post-publish audit failure, one rollback/close per rejected locked approval, and real MariaDB concurrent exactly-once publishing plus durable ambiguous-state inspection. This is software/CI evidence only; physical, operator, and production gates remain open and fail-closed.
## [2026-08-09] compile | Add issue #53 Korean-first manuals baseline and reverse-analysis gaps

- Added versioned `manuals/` documents for general users, administrators, installers/service, privacy, and support/incident response, each using actor, precondition, input, observable output, code/API owner, and evidence artifact fields.
- Added explicit degraded/offline, OEM/accessibility, update/rollback, lost-phone/revocation, force-open, backup/restore, commissioning, and redacted-support journeys; success language is gated on state/event/physical evidence.
- Added `manuals/product_gap_register_v1.md` from source-to-manual reverse analysis. Open gaps include #49 authentication/RBAC/mock-success/force-open, #50 TLS/signed commands/OTA rollback, #51 OEM/GATT/updater, #52 privacy/observability/backup/SLO, and all ESP32-C6/Samsung/relay/boot/OTA physical walkthroughs.
- Updated `wiki/index.md`; issue #53 remains a draft baseline and is not complete. The #49→#50→#51→#52 repeat loop is defined for product/test remediation followed by independent manual walkthrough.

## [2026-08-09] fix | Remediate issue #53 manuals after independent documentation review

- Integrated `origin/main` at `b2df34977fe866e129eae373e7056f0f9b3ddc6f` and preserved that exact `wiki/log.md` Git blob as the byte prefix; retained the issue #53 baseline entry after it.
- Replaced the general-user offline/OEM summary and support incident error matrix with actor, precondition, input, observable output, code/API owner, evidence, and explicit timeout/bounded-retry/escalation contract fields.
- Added `GAP-53-01` for implementation/SLO/state-event-audit regression evidence; timeout values are documentation targets only, and #49-#52, OEM, physical, OTA, and production gates remain pending.

## [2026-08-09] fix | Second issue #53 manual contract improvement loop

- Integrated exact main `cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f` and retained its raw `wiki/log.md` Git blob as the byte-for-byte prefix; appended the issue #53 manual history without rewriting prior entries.
- Expanded installer/service relay-idle, Target-offline, OTA boot-failure, and sensor-fault rows with actor, preconditions, input, observable output, code/API owner, evidence, reason, timeout, bounded retry, and escalation fields; values remain documentation targets with physical and product evidence pending.
- Added an explicit update/health-timeout rollback contract and support escalation link to the general-user manual, and expanded `GAP-53-01` to trace installer and administrator contract/test gaps. Raw sources remain unchanged; PR #58 stays Draft pending fresh independent review.

## [2026-08-09] fix | Correct PR #58 R1 baseline evidence traceability

- Replaced the stale `b246aff...` R1 evidence with the exact current main/base `cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f`, matching the baseline recorded across the manual bundle.
- R1 now requires comparing `git cat-file blob cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f:wiki/log.md` byte-for-byte as the prefix of the candidate `wiki/log.md`, so the evidence procedure identifies the matching raw `wiki/log.md` Git-blob prefix check.
- Preserved all previously passing installer/general-user/GAP contracts; `raw/` remains unchanged, PR #58 stays Draft/unmerged, and physical, OEM, OTA, operator, and production gates remain pending and fail-closed pending a fresh exact-head COMMENTED review.

## [2026-08-09] fix | Remediate PR #58 current-main provenance and sensor baseline

- Verified the pre-existing dirty `manuals/product_gap_register_v1.md` and `wiki/log.md` bytes exactly matched PR head `e5edfcbc0835fbd9b00ee3a1e682f821458df299`, then integrated exact `origin/main` `fb827681e1b2f5a8b08aa2784ae419832efff6f7` with two-parent merge provenance. The merged `wiki/log.md` preserves the exact current-main Git blob as its byte prefix and appends only the Issue #53 branch entries.
- Replaced the stale installer VL53L0X/I²C wiring instruction with current AJ-SR04T/JSN-SR04T TRIG GPIO10 and ECHO GPIO11 source-aligned guidance, explicit 5 V ECHO protection and measurement-safety steps, and an explicitly historical/non-applicable GPIO6/7 row.
- Hardened R1 to require exact PR `baseRefOid`/`headRefOid`, raw `git cat-file` blob comparison, and rejection of `b246aff` or any unexpected base/head mutation. Manual links, strict UTF-8, conflict markers, diff/raw/append-only/OTA/software checks remain required; no physical, operator, or production acceptance is claimed and PR #58 remains Draft/unmerged.

## [2026-08-09] fix | Integrate PR #57 current main into Issue #53 manuals

- After PR #57 merged, integrated exact `origin/main` `c654a18f0fa278e4530229bb881fe88286d25c2e` once with a two-parent merge over the existing PR #58 head; the raw c654 `wiki/log.md` Git blob is preserved as the exact prefix and the existing Issue #53 entries are appended without rewriting history.
- Preserved PR #57 backend files and the PR #62 physical-preparation artifacts byte-for-byte; resolved only the expected integration surfaces and rejected conflict markers, raw changes, and broad line-ending churn.
- Refreshed R1's expected base to c654 and rechecked stale-base mutation rejection, current AJ-SR04T/JSN-SR04T GPIO10/11 plus 5 V ECHO protection guidance, strict UTF-8, links, Quick/proportional software checks, and hosted trusted policy. PR #58 remains Draft/unmerged; no physical, operator, or production acceptance is claimed.

## [2026-08-09] fix | Align PR #58 0.1.2 manuals with PR #57 admin controls

- Made every 0.1.2 manual header identify exact integrated base `c654a18f0fa278e4530229bb881fe88286d25c2e` and reran the reverse-analysis register against PR #57's deny-by-default mTLS sessions, role/tenant/CSRF/re-auth/idempotency checks, fail-closed DB responses, immutable audit migrations, and durable two-person force-open publication state.
- Added Korean-first administrator reason/status, timeout, bounded retry, escalation owner and evidence semantics for authentication/RBAC, tenant approve/revoke, force-open proposal/approval/reconciliation/effect-unknown, outage/alert and backup/restore, with a direct support-handbook handoff. Corrected the support dual-control trace to `POST /api/v1/admin/control/force-open` plus `/{approval_id}/approve`; mobile `POST /api/v1/door/open` remains a separate proof-bearing broker-ack-only compatibility path.
- Classified #49 only as host/software evidence. Deployed proxy/session operations, signed Target command, relay effect, Samsung/OEM, ESP32-C6 GPIO/radio, bootloader/OTA, operator walkthrough, backup/restore, production authorization and every physical Gate remain `PENDING`; `published` is not relay confirmation and Issue #53 remains open.

## [2026-08-09] test | Validate PR #58 administrator manual remediation

- Quick passed in 14.12 seconds: doctor 12 pass/1 Docker-covered native-Java warning/0 fail, backend 43 tests with one opt-in MariaDB skip, Compose, lifecycle mutations, protocol vectors and 16 tests, observability 18, OTA contract and hardwareless 4 all passed.
- Standalone OTA contract, hardwareless 4/4 and focused backend admin-security 8/8 passed. Strict UTF-8 without BOM, local links, conflict markers, Markdown table arity, exact c654 header provenance, administrator/support reason-route contracts and AJ-SR04T GPIO10/11 with 5 V ECHO safety checks passed.
- These are local/software results only. No Samsung/OEM, ESP32-C6 radio/GPIO, GPIO3 relay/AJ-SR04T, bootloader, OTA install/reboot/health/rollback, RELAY-G0..G2, operator, canary, deployment or production acceptance evidence was produced.

## [2026-08-09] code | Harden Target commands and OTA for issue #50

- Replaced shared unsigned MQTT effects and insecure TLS fallbacks with CA-verified MQTTS, exact per-Target QoS 1 topics, broker `%u` ACLs, retained-message rejection, and deterministic signed freshness/identity/boot-bound commands.
- Added a two-slot CRC/generation NVS replay ledger that persists before effects and distinguishes completed from crash-uncertain duplicates, plus backend P-256 command signing and fail-closed provisioning.
- Rebuilt Target OTA around signed Ed25519 manifests, periodic HTTPS, authenticated local recovery, one inactive-slot verifier/writer, exact size/hash/image checks, pending-image health marking, rollback, downgrade floor, and protocol 1..2 overlap.
- Kept hardwareless RC compile-OFF by default, added stale enablement cleanup and a machine-readable production hardening policy. Production remains disabled; no merge, deployment, eFuse change, or device authorization was performed.

## [2026-08-09] test | Validate issue #50 software paths and preserve physical Gates

- Root host suite passed 92/92, including command mutation, durable replay, crash uncertainty, storage failure, OTA state/fault contracts, and insecure-path checks. Backend suite passed 32 tests with one opt-in MariaDB integration skip.
- Scoped pioarduino ESP32-C6 build passed for `esp32c6`: RAM 53,728/327,680 (16.4%) and flash 1,600,194/7,340,032 (21.8%). `git diff --check`, JSON parsing, wiki links, and raw immutability are separate final lint requirements.
- These are host/software results only. Deployed MQTTS/ACL behavior, ESP32-C6 radio and relay operation, inactive-slot boot, health-valid, power-loss and rollback, authenticated local recovery, eFuse/debug hardening, N/N-1 interop, OTA-G1..G4, RELAY-G0..G2, physical soak, operator acceptance, and production authorization remain pending and fail-closed.

## [2026-08-09] fix | Close independent Target command and OTA review blockers

- Kept command authorization clock-untrusted until time comes from an independently authenticated HTTPS `Date` response; signed `issued_at` is never used as its own verification time, including a delayed first command after boot.
- Added an authenticated station-local transition to a bounded 10-minute WPA2 AP+STA recovery window without clearing STA association, so DNS, MQTT, Backend, or manifest-host outage does not make local recovery unreachable.
- Required 30 seconds of continuously healthy pending-image predicates, resetting the healthy-since timer on every failed tick and rolling back when a new continuous window cannot complete within 120 seconds.
- Replaced numeric-prefix version comparison with a two-slot CRC/generation SemVer floor that rejects stable-to-prerelease downgrade, rollback replay, equal-precedence alternate identity, and exact-current forced/local reflash.
- Expanded the command binding boot identity to 128 bits from four ESP hardware-RNG words while retaining the durable boot counter for diagnostics.

## [2026-08-09] test | Exercise issue #50 review-remediation faults

- Native production-core tests passed delayed-first-command, transient/late health, prerelease/equal-precedence identity, rollback floor, reboot recovery, and failed-persist mutations; targeted security/OTA static tests also passed.
- Scoped pioarduino `esp32c6` build passed after remediation: RAM 53,888/327,680 (16.4%) and flash 1,606,312/7,340,032 (21.9%). This is compile evidence only.
- No deployed broker, ESP32-C6 boot/radio/relay, local operator recovery, power-loss, rollback, eFuse/debug lock, N/N-1 device interop, OTA-G1..G4, RELAY-G0..G2, physical soak, production authorization, merge, or deployment evidence was created; every physical/operator/production Gate remains open and fail-closed.

## [2026-08-09] fix | Make OTA version-floor CRC compiler independent

- Exact-head Linux CI exposed that the first version-floor readback included compiler-dependent C++ struct tail padding in its CRC, while the Windows host happened to keep those bytes stable.
- Replaced raw-struct hashing with an explicit fixed 80-byte little-endian encoding of the defined magic, schema, reserved, generation, and version fields; corrupt-slot mutations now verify fail-closed recovery without relying on ABI padding.
- Windows and WSL/Linux native production-core tests passed 455 checks; the scoped ESP32-C6 build passed at RAM 53,888/327,680 (16.4%) and flash 1,606,504/7,340,032 (21.9%).
- This is a software portability correction only. Physical Target storage, power-loss, rollback, operator, OTA-G1..G4, production authorization, merge, and deployment evidence remain pending and fail-closed.

## [2026-08-09] fix | Reconcile private-default Compose with fail-closed command provisioning

- After integrating exact main `c654a18f0fa278e4530229bb881fe88286d25c2e`, the inherited backend-security lane correctly required `docker compose config` to succeed without production secrets, while issue #50 used interpolation-time required variables.
- Changed only Compose interpolation to blank/default values so the private deployment topology is auditable without secrets; runtime Target identity, signing scalar/key, verified broker, non-1883 port, and CA checks still reject every effect before publication when provisioning is absent.
- Added mutation assertions for renderable defaults and runtime fail-closed seams. No plaintext/insecure fallback, production secret, broker contact, physical/operator evidence, production enablement, merge, or deployment was introduced.

## [2026-08-09] fix | Bind backend commands to authenticated current Target boot

- Replaced the static backend boot-ID environment input with a CA-verified backend subscriber on the broker-ACL-bound per-Target `/boot` topic and a migration-backed atomic `target_boot_state` registry.
- Boot refresh requires exact topic/payload Target identity, a 128-bit hexadecimal boot ID, and a strictly increasing durable boot count; forged cross-Target, lower-count rollback, and same-count replacement mutations reject, while an exact duplicate is idempotent and a new boot restores command signing without process restart.
- Added one effect-boundary provisioning validator covering exact Target/tenant/door identity, non-1883 broker host, distinct nonempty broker username/password, existing CA file, positive signing key ID, and valid nonzero scalar. Every missing/invalid-field mutation proves no boot lookup or broker client creation.
- Added migration up/down and Compose wiring, backend-read ACL for authenticated boot topics, and retained private-default rendering. Physical broker identity, Target reboot recovery, device/operator, and production Gates remain pending and fail-closed.

## [2026-08-09] test | Validate authenticated boot refresh and strict effect boundary

- Root validation passed 102 tests; backend validation passed 49 tests with one opt-in MariaDB integration skip. Mutations reject cross-Target, non-string, counter-overflow, rollback, same-count replacement, missing broker credential/CA/identity/key, and zero, malformed, or out-of-range signing scalar inputs before boot lookup or broker-client creation; established `/boot` diagnostic fields remain compatible.
- The authenticated subscriber seam used the dedicated backend username/password, `CERT_REQUIRED`, hostname-verified TLS, the per-Target boot topic, and the durable atomic registry. WSL/Linux production-core validation, private-default Compose rendering, and the OTA contract passed.
- Scoped pioarduino `esp32c6` compile passed with the exact command schema parser: RAM 53,888/327,680 (16.4%) and flash 1,606,490/7,340,032 (21.9%). This is software evidence only; deployed broker ACL, physical Target reboot/recovery/rollback, operator, production, merge, and deployment Gates remain open and fail-closed.

## [2026-08-09] fix | Integrate exact main 337fcca after manual baseline merge

- After the Issue #50 candidate was pushed, GitHub main advanced to exact `337fcca152d3de7db17a0d374d485f20726ec1b4`; integrated that commit once with two-parent provenance so PR #61 can return to a clean merge state and run pull-request canaries.
- Preserved the exact 265,705-byte `337fcca` `wiki/log.md` Git blob as the candidate prefix, then preserved the existing 7,859-byte Issue #50 append sequence unchanged. The Issue #53 manuals and combined wiki navigation are retained, and `raw/` remains byte-identical to main.
- Post-integration validation passed 102 root tests, 49 backend tests with one opt-in MariaDB skip, WSL/Linux production-core, private-default Compose, OTA contract, wiki/link/parser/marker checks, and a clean-cache ESP32-C6 build at RAM 53,888/327,680 and flash 1,606,490/7,340,032. These are software results only; Draft, independent review, physical/operator, and production Gates remain open.

## [2026-08-09] fix | Reject raw duplicate commands and late OTA health validity

- Independent exact-head COMMENTED review `4889657823` found that ArduinoJson collapses duplicate member names before the 13-field DOM guard and that a stable health interval could win after the 120-second deadline; PR #61 remained Draft and unmerged.
- Added a production-used raw flat-object policy that requires every canonical command field exactly once before DOM parsing. Mutations cover same-value and different-value duplicates for all 13 fields, escaped key aliases, unknown fields, nested values, truncation, and trailing content.
- Made a strictly exceeded health deadline dominate mark-valid, defined equality as the final admissible instant only for an already complete interval, and reset continuity after a sampling gap above one second. Deadline-1/equality/+1, stalled sampling, transient predicate, and late recovery mutations pass; the ESP32-C6 build passes at RAM 53,888/327,680 and flash 1,606,546/7,340,032. Physical/operator/production Gates remain open and fail-closed.

## [2026-08-09] fix | Harden staged Orca profile launch fallback

- Reconciled exact main `cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f` with six post-PR-#60 packaged `worker-start` non-completion Dispatches and staged success `ctx_e1f6e94ad254`. The recurrence remains intermittent, issue #55 stays open, and no packaged-runtime root-cause fix is claimed.
- Updated the staged launcher for agy 1.1.11 `--prompt-interactive`, absolute exact-worktree scope, no outside search, typed `codex-trust-workspace` fail-closed handling, renderer-aware initial marker handling with mandatory final idle, and typed already-absent `tab_not_found` cleanup. It never auto-trusts, adds home, persists broad permission, or uses `-AllowUnsafe` as trust recovery.
- Replaced the unsafe five-second no-marker success path after delayed unsubmitted prompts on `term_fe8c325a` and `term_01eb874d`. The launcher now observes post-cursor output for 30 seconds by default and reports success only after exact marker plus one Enter or positive `UserPromptSubmit`/`Working`; accepted-but-unproven Dispatches remain preserved for exact coordinator inspection and stop/accounting.
- Added executable mock coverage for Codex and Antigravity launch, delayed marker beyond five seconds, positive working evidence, no-evidence failure, trust blocking, renderer idle, shell exit, Dispatch rejection, `tab_not_found`, exact cleanup, and no unsafe permission. Focused staged-launcher and lifecycle-probe suites passed; complete Quick could not start because this isolated sandbox lacked `.venv` and Python `ensurepip` was denied in the user AppData temp boundary.
- This is a repository-side staged mitigation and diagnostic contract only. Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, production, packaged initial/follow-up matrix, independent exact-head review, and terminal CI evidence remain pending and fail-closed.

## [2026-08-09] fix | Integrate current main and close unproven staged launches

- Integrated exact `origin/main` `fb827681e1b2f5a8b08aa2784ae419832efff6f7` after PR #62 into draft PR #63 while preserving the new main `wiki/log.md` Git blob as an exact byte prefix and then appending the existing issue-#55 branch suffix. `raw/` remains byte-identical to current main.
- Superseded the preceding entry's preserved-terminal operational statement without rewriting it: when an accepted Dispatch has no post-cursor `UserPromptSubmit`/`Working` evidence, the launcher stops that exact Dispatch and closes that exact terminal handle; typed `tab_not_found` means already absent, and cleanup errors remain fail-closed.
- Added the PR #58 renderer/cursor race from `ctx_ef4483264590` / `term_63a45917-6d8c-48d2-b72b-21bd95a850fa`: cursor 107 had zero new output and `tui-idle=true` while `terminal show` later exposed `[Pasted Content 5717 chars]`, and processing began only after the coordinator sent exact Enter 1 byte at 2026-08-09 03:57 KST. The launcher now compares pre/post renderer snapshots, sends one Enter only for a new exact marker, and still waits for cursor-bound processing evidence.
- Incorporated independent Antigravity audit `msg_8b71ec6196c7`, performed read-only with zero changes at exact main `cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f`. Its lifecycle probe and Quick/static pass support the mitigation boundary but are not an independent review of this PR head and do not fix Orca 1.4.176 packaged named-pipe IPC.
- Focused staged-launcher and lifecycle-probe suites, PowerShell AST parsing, relative-link checks, the current-main nine-test physical-gate preparation suite, whitespace checks, and raw equality passed. The current-worktree Quick suite stopped at environment doctor because the Orca runtime was not ready, `.venv` had no pip, and neither Flutter nor Docker was available; no physical, operator, production, or packaged-runtime acceptance is claimed.
- PR #63 remains Draft and issue #55 remains open. Fresh exact-head independent review is required before ready/merge, while Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, production, and packaged initial/follow-up matrix Gates remain pending and fail-closed.

## [2026-08-09] fix | Integrate latest main and record supervised launch reproductions

- Integrated exact fetched `origin/main` `337fcca152d3de7db17a0d374d485f20726ec1b4` once into PR #63 with two-parent provenance. The exact main `wiki/log.md` Git blob `243f5a4127878ca3d58e15dc4c14c026701ea6d6` is the candidate log's byte prefix, the prior Issue #55 suffix follows it unchanged, and `raw/` retains main tree `013c00e7617365aa30c8bd0d38d9503d3885d264`.
- Coordinator-provided incident evidence records three current supervised launches that each required exactly one Enter after a new exact `[Pasted Content N chars]` marker before processing began: PR #58 remediation Task `task_4b61ab9e15be` / Dispatch `ctx_ef4483264590` / terminal `term_63a45917-6d8c-48d2-b72b-21bd95a850fa`, PR #58 final review Task `task_82bdc70f33ba` / Dispatch `ctx_6ebd3d90ae37` / terminal `term_56ae7027-46af-4db1-8ef9-6ffae49a074a`, and PR #61 final review Task `task_13b39e7dfe88` / Dispatch `ctx_1b45c599e36d` / terminal `term_c9161161-3b25-4b8d-af0a-feb521ba84a4`.
- Coordinator-provided incident evidence also records this PR #63 integration Task `task_a7dc527bac51` first failed packaged launch as Dispatch `ctx_0df91925e4ce` / terminal `term_72ab3858-b32e-436e-bf8c-639049a1e424`: it exited to PowerShell after MCP startup interruption while marked `input_accepted`. The separate retry/current receipt is Dispatch `ctx_c64fbc66f427` / terminal `term_410dd0da-920f-437d-b074-939efa53d62e`; its automatic Dispatch preamble was absent, so this work is an ordinary terminal handoff and is not the failed first launch. These four reproductions are input/start failure evidence, not Task execution or completion evidence, and no capability material is recorded.
- Focused staged-launcher and lifecycle mutation suites passed, PowerShell AST parsing passed for all 9 tracked scripts, and Quick passed in 37.18 seconds after idempotent isolated setup: doctor 12 pass/1 Docker-covered native-Java warning/0 fail, backend 43 tests with one opt-in MariaDB skip, Compose, protocol vectors and 16 tests, observability 18, OTA contract, and hardwareless Gate 4. Strict UTF-8/BOM, 242 local-link, whitespace/conflict, raw identity, and exact staged-log prefix checks passed.
- Issue #55 remains open because this PR is repository-side mitigation and evidence only, not a packaged Orca 1.4.176 root-cause fix. PR #63 remains Draft and unmerged; no deploy or Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, canary, or production closure is claimed.

## [2026-08-09] fix | Reintegrate concurrently advanced main after PR #61

- Preserved the completed and pushed first integration checkpoint `e70813be455131d43a6e6423df0e26a441e4ee6d`, whose parents are PR #63 head `0703f682b9bbbe8b57a11719df5cb760f790ca8d` and then-main `337fcca152d3de7db17a0d374d485f20726ec1b4`. After PR #61 concurrently advanced main, fetched again as explicitly required and integrated exact `origin/main` `45901236c00bf0399997e665299d0d5479878e83` with a new two-parent merge over that checkpoint.
- The final candidate `wiki/log.md` preserves exact main Git blob `ca0830010f9e108d134bc931e9f0811df3f50e5c` as its byte prefix and appends the exact `e70813be` PR #63 suffix before this entry. `raw/` remains byte-identical to main tree `013c00e7617365aa30c8bd0d38d9503d3885d264`; the PR #61 Target command/OTA implementation and its host/software-only evidence boundaries are retained.
- Focused staged-launcher and lifecycle mutation suites passed again, and PowerShell AST parsing passed for all 9 tracked scripts. Quick passed in 36.37 seconds: doctor 12 pass/1 Docker-covered native-Java warning/0 fail, backend 49 tests with one opt-in MariaDB skip, Compose, protocol vectors and 16 tests, observability 18, OTA contract, and hardwareless Gate 4.
- Final strict UTF-8/BOM, local-link, whitespace/conflict-marker, exact main-prefix/checkpoint-suffix, raw identity, merge-parent, and clean-scope checks passed. These are repository and host/software checks only.
- Issue #55 remains open as a repository mitigation/evidence issue, PR #63 remains Draft and unmerged, and no packaged-runtime root-cause fix, deploy, physical/operator/canary acceptance, or production authorization is claimed.

## [2026-08-09] fix | Make staged-launcher error assertions renderer independent

- Independent exact-head COMMENTED review `4889767197` reproduced `.orca/tests/test_profile_launcher.ps1` failing at prior head `d348132e02c7f5e92bffab05d044fcf38f44848b` because redirected Windows PowerShell `ErrorRecord` rendering inserted width-dependent whitespace inside the correct rejected-before-acceptance diagnostic.
- Kept the production launcher unchanged and made only its regression harness remove renderer-only whitespace before comparing exact error contracts. Dispatch rejection must still contain both the outer failed-before-acceptance cleanup stage and exact inner rejected-before-acceptance reason; wrong-stage and wrong-reason mutations each prove the boundary check fails.
- Applied the same renderer-independent comparison to existing `tab_not_found`, accepted-but-unproven positive-evidence, and no-broad-trust diagnostics after the narrow terminal renderer exposed the same in-word wrapping risk. Worker-stop, exact terminal cleanup, capability redaction, no false `worker_done`, absolute worktree scope, one-Enter, and fail-closed trust behavior were not weakened.

## [2026-08-09] test | Revalidate staged launcher after renderer assertion fix

- Focused staged-launcher and lifecycle-probe suites passed under the same redirected narrow renderer that reproduced the blocker, including the new wrong-stage and wrong-reason mutations.
- Quick passed in 51.76 seconds: doctor 12 pass/1 Docker-covered native-Java warning/0 fail, backend 49 tests with one opt-in MariaDB skip, Compose, staged launcher, lifecycle probe, protocol vectors and 16 tests, observability 18, OTA contract, and hardwareless Gate 4.
- These are repository and host/software checks only. PR #63 remains Draft and unmerged pending a fresh exact-head COMMENTED review; Issue #55 and packaged Orca 1.4.176 root-cause work remain open, and no deployment, Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator/canary, or production Gate is closed.

## [2026-08-09] compile | Temporarily authorize the independently reviewed PR #59 bundle

- Added exactly one temporary, complete five-file `utf8-lf-v1` bundle for PR #59 exact head `e468e0f0a77e5e9b5e1a5ac7c4cdf22c4de951ad`, authorized by independent exact-head COMMENTED review `4890233068`. The existing `current-main-baseline` remains approved; no wildcard, branch, partial path set, mixed digest set, protected-path change, production secret, or protected-file edit was introduced.
- Recomputed every normalized digest directly from the fetched candidate commit and matched the reviewed values. Focused trusted-policy tests passed 28/28, including exact temporary acceptance, current-main acceptance, and missing, reordered, mixed, single-byte, candidate-policy, candidate-validator, YAML, and command-shape rejection. The full root suite passed 103/103; JSON parsing and `git diff --check` also passed.
- This is only the temporary policy-authorization step. PR #59 still requires its own trusted check, review/merge decision, and post-merge policy-only rotation that removes the temporary bundle and pins the exact merged `main`; no app install, Target install/reboot/health, physical, operator, canary, or production Gate is closed.

## [2026-08-09] test | Validate the temporary PR #59 policy bundle with Quick

- After isolated worktree setup, Quick passed in 36.11 seconds: doctor 12 pass/1 Docker-covered native-Java warning/0 fail, backend 49 tests with one opt-in MariaDB skip, Compose rendering, staged Orca launcher and lifecycle probes, protocol vectors and 16 tests, observability 18 tests, OTA contract, and hardwareless release Gates.
- This remains repository and host/software evidence only. It does not authorize production deployment or substitute for Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, operator, canary, or production evidence.

## [2026-08-09] fix | Allow any exact approved trusted-workflow bundle in checkout regression

- Corrected the checkout regression to accept whichever one complete approved five-file bundle exactly matches the protected bytes instead of hard-coding `current-main-baseline`, so the independently authorized `temporary-pr59-e468e0f` transition can exercise the same whole-bundle decision as the trusted validator.
- Kept separate exact assertions for the `current-main-baseline` repository, commit, protected-path order, and digests, and added source-mismatch mutations while preserving rejection of unapproved, mixed, partial, reordered, and single-byte variants. The policy JSON and all five protected files remain unchanged.
- This is a policy-test semantics correction only; it does not authorize a later PR #59 head, production deployment, or any Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, bootloader, OTA-G1..G4, RELAY-G0..G2, operator, or canary evidence.

## [2026-08-09] test | Validate approved-bundle checkout semantics on main and PR #59 bytes

- Focused trusted-workflow tests passed 29/29 and the full root suite passed 104/104 on exact main base `17cc961f0c751c27fae813d1c8c24692369f215c`; the checkout regression selected `current-main-baseline` without requiring that ID in the acceptance rule.
- Fetched all five protected files directly from PR #59 exact commit `e468e0f0a77e5e9b5e1a5ac7c4cdf22c4de951ad` with Git and passed them as inert bytes to the trusted-base validator; it selected exactly `temporary-pr59-e468e0f`. Quick passed in 35.23 seconds with doctor 12 pass/1 Docker-covered native-Java warning/0 fail and all software lanes green.
- UTF-8, relative links, append-only byte prefix, raw/protected/policy immutability, exact three-file scope, and `git diff --check` passed. These results are software-only and leave every physical, operator, canary, and production Gate pending and fail-closed.

## [2026-08-09] code | Implement mobile commercial recovery and updater contracts (#51)

- Fresh-install native wake registration is now reached after the visible permission gate, persisted, re-registered after boot/package replacement, and exposed through a retryable status channel.
- Manual local GATT retry resolves a recently observed encrypted, Keystore-bound Target locator and returns durable queue/session/reason data; the `TARGET_LOCAL` sentinel is removed while proof uncertainty and exact Target/transport reasons remain durable.
- Added a scanner/WebView/foreground-service-independent recovery shell, truthful door/enrollment models, privacy redaction, accessibility-friendly responsive layout, Korean/English locale resources, signed metadata plus APK size/hash/certificate/fallback/install-health updater checks, and fail-closed release signing.
- Host checks do not claim Samsung/One UI, radio/relay, bootloader, physical install-health, or production acceptance; legacy/manual_remote and independent OTA/rollback paths remain preserved.

## [2026-08-09] fix | Address hosted analyzer blockers for mobile UX (#51)

- Removed the duplicate update-contract import, corrected app-owned async BuildContext safety, modernized Switch/Color APIs, and restored const construction in the commercial control screen.
- Added a path-scoped analyzer exclusion for the pre-existing vendored `flutter_beacon_local` fork only; project-wide linting remains enabled and no vendored source was changed.
- Hosted PR #59 initially failed at analyzer before this remediation; fresh exact-head CI canary and independent review are required for the new commit.

## [2026-08-09] fix | Integrate mobile commercial UX with current Target, admin, and OTA contracts

- Integrated exact post-PR #63 main `4e628baf043721d0e0ae86290915886cee7e3d5c` once. The resolved log preserves that main Git blob as its byte prefix before the two existing PR #59 entries and this append; `raw/` remains identical to main tree `013c00e7617365aa30c8bd0d38d9503d3885d264`.
- Replaced the legacy self-selected update key and field aliases with the exact mobile manifest schema, raw duplicate/escaped-alias/trailing rejection, `sgk-json-v1`, APK-pinned Ed25519 key ID/public key, version alias, Android SDK, N/N-1 protocol, distinct HTTPS endpoint, size, hash, package, and single-certificate checks. Downloads now require a verified manifest and one of its signed primary/fallback URLs; remote config and WebView cannot inject an unsigned APK URL.
- Kept local GATT retry bound to its encrypted recent Target capability. The legacy Web shell no longer sends retired anonymous enrolment/status or device-ID-only remote-open requests and shows the control as unavailable until issue #52 provisions a scoped v2 possession credential; no Backend HMAC secret was moved into Flutter and HTTP 426 remains a no-effect N/N-1 result.
- Software validation passed: doctor 12 pass/1 Docker-covered Java warning/0 fail, backend 49 tests with one opt-in MariaDB skip, root 106 tests, Compose, staged launcher/lifecycle, protocol 16, observability 18, OTA contract, and hardwareless Gate 4. The local prepared Flutter container launch timed out twice without creating an orphan, so exact-head hosted Flutter analysis/tests, native Gradle GATT tests, and debug APK build remain required before merge.
- This is host/software evidence only. PR #59 stays Draft and unmerged; Samsung/OEM wake, real BLE/ESP32-C6/relay, physical APK install-health, OTA-G1..G4, RELAY-G0..G2, operator acceptance, production signing/deployment, and issue closure remain pending and fail-closed.

## [2026-08-09] fix | Close mobile updater, first-run health, and privacy review blockers

- Remediated exact-head blocking COMMENTED review `4889855571` without changing the trusted-workflow policy. The mobile build now pins two independent metadata URLs and the updater key ID/public key, fails closed on every non-PR signing or URL input, and replaces the legacy unsigned five-field metadata with an exact-schema Ed25519 manifest bound to the built APK byte length, SHA-256, single `apksigner` certificate digest, build, and commit. PR debug canaries use the public RFC 8032 test key and unavailable `.invalid` endpoints and are not installable production releases.
- Persisted the verified build, version, artifact digest, certificate digest, and commit before opening the installer. Before permission, BLE, scanner, WebView, or foreground-service startup, the replacement app compares those fields with the installed package build/version, `base.apk` SHA-256, and exactly one current signer; mismatch, unavailable identity, or storage failure stays pending/failed, while only an exact match clears pending state and may display the signed-metadata current state.
- Enforced zoned publication timestamps, bounded future/stale metadata, ordered `mandatory_after`, and truthful idle/checking/available/installing/failed UI states. Routed normal/error summaries, details, stacks, in-memory support logs, UI state, and service IPC through deterministic redaction for tenant/unit/device identifiers, MACs, credentials, tokens, and URL queries before emission.
- Extended the trusted OTA machine contract and mutations for test-before-build order, clean JUnit evidence, updater trust defines, exact secret provenance, signed artifact metadata, legacy metadata rejection, and release-signing fail-closed behavior. The policy itself remains unchanged; the modified protected bundle requires independent whole-bundle review and the separate temporary policy-rotation procedure before the trusted check can pass.

## [2026-08-09] test | Validate PR #59 review remediation and preserve open physical Gates

- Focused OTA workflow/manifest tests passed 59/59, including trust-input removal, test reordering, signer/producer removal, legacy metadata, artifact/certificate/private-public-key mismatch, time-policy, and release-signing mutations; `python scripts/ota_contract_gate.py contract` and whitespace checks passed. The broader root discovery executed 115 tests: 114 passed and the sole expected failure was `test_current_checkout_matches_an_approved_bundle`, because this protected two-file candidate is intentionally not self-added to the trusted policy.
- Docker `flutter pub get` completed. The existing local builder then remained silent during bounded Flutter analysis/test and was stopped without retaining its exact temporary container; a separate forced Gradle run downloaded/configured Gradle 9.1.0 but failed inside the builder's Flutter SDK at `:app:compileFlutterBuildDebug` with widespread missing `Matrix4`/`Vector3` symbols before application Kotlin test evidence. This environment result is not counted as an application pass; clean hosted exact-head Flutter tests, native GATT/package-identity JUnit, analyzer, and debug APK build remain required.
- PR #59 remains Draft and unmerged. Samsung/One UI wake/accessibility, physical APK install/first-run/fallback, real BLE/ESP32-C6/radio/relay, bootloader/Target OTA rollback and N/N-1, issue #52 scoped credential provisioning, operator canary, production secrets/signing, deployment, and production authorization remain open and fail-closed.

## [2026-08-09] fix | Bind mobile release metadata to protected producer and APK internal identity

- Folded mobile manifest creation and verification into the already protected `scripts/ota_contract_gate.py` and removed the standalone candidate-controlled signer. Pull-request metadata now runs in an exact PR-only step with the public RFC 8032 test seed/key and `.invalid` URLs, while the production private key and release URLs are available only inside the explicitly approved `production` environment job; every PR-reachable production-secret reference is rejected by mutation tests.
- Embedded the exact 40-hex source commit as a packaged Flutter asset. Before signing and again during verification, the protected producer uses trusted Android tools to require the exact package ID, positive version code, version name, embedded commit, and exactly one APK signing certificate, then binds those identities with the APK byte length and SHA-256 in the current 22-field signed manifest.
- Added hosted Dart format, Flutter analysis/tests, and targeted native Gradle tests before APK build. Mechanically formatted the 17 app-owned `lib/` and `test/` files that failed the new check, resolved all 13 app-owned analyzer information findings, and left the vendored Flutter fork plus Linux/macOS/Windows generated registrants unchanged.

## [2026-08-09] test | Validate protected mobile producer in disposable Android environments

- Focused OTA/protected-producer and manifest tests passed 68/68, including PR environment exfiltration, protected-executable escape, production environment provenance, package/version/build/commit mismatch, duplicate or missing embedded identity, zero/multiple signer, tampered artifact, certificate, key, and timestamp mutations. The OTA contract passed; full root discovery passed 122/123 with only the intentionally unapproved five-file trusted bundle check remaining open for independent policy rotation.
- A tracked/non-ignored-only disposable Flutter copy passed dependency resolution, strict Dart format with zero changes, analysis with no issues, and 23/23 Flutter tests. A separate Gradle 9.1.0 disposable copy completed 208 tasks and seven targeted JUnit suites for GATT and installed-package identity without failure.
- A newly built debug APK passed actual `apkanalyzer` package/versionCode/versionName inspection, exact embedded-commit extraction, and `apksigner` single-certificate validation. The protected producer then created and independently verified current-schema signed metadata against those exact APK bytes. These are software checks only and do not replace Samsung/OEM, physical install-health, BLE/ESP32-C6/relay, Target OTA/rollback, operator, or production evidence.
- An early disposable-copy probe unintentionally included an ignored keystore in temporary storage. No secret value was read or printed, the exact temporary copy was immediately removed, and every later lane enumerated only tracked and non-ignored sources. Shared-worktree `pub get` byproducts were restored to reviewed bytes and no task-owned validation container remains.

## [2026-08-09] lint | Retire settled Orca workers and worktrees

- Removed 32 clean/completed managed worktrees, reducing the managed set from 35 to three. Preserved the main checkout, the active dirty Issue #51 worktree, and the dirty Issue #55 runtime-follow-up worktree.
- Terminated five settled low-level terminals. Two coordinator-external zombie PTYs returned `tab_not_found` on exact close and re-registered, so they remain preserved until Orca restarts rather than being mass-cleaned.
- Cleanup intentionally left the then-active Flutter verification container under its task owner; that container later exited and was removed by the bounded validation workflow. This lifecycle cleanup is not physical, deployment, operator, or production evidence.

## [2026-08-09] fix | Isolate release secrets and restore first-run background consent

- Remediated blocking COMMENTED review `4890098938` without changing the trusted-workflow policy. Pull-request, main-push, and branch-dispatch firmware/mobile canary jobs now contain zero production-secret expressions and use only fixed RFC 8032 test material with `.invalid` URLs; exact-main checks, protected contract/root tests, `production` Environment approval, and separate main-only jobs precede every production secret injection.
- Folded Target manifest creation and verification into the protected OTA gate and added job-DAG, step-order, secret-environment, candidate-executable, artifact-propagation, Target version/commit/build, and Android branch-dispatch mutations. Public firmware/mobile artifacts remain non-production canaries, and the five-file trusted bundle remains unapproved pending independent whole-bundle review and the documented policy-rotation procedure.
- Replaced the unreachable background permission gate with a versioned first-run plain-language disclosure and explicit consent. Before consent the app makes zero location, Bluetooth, notification, background-location, or battery-exemption requests; after consent it requests only missing items, preserves denial/retry and already-granted idempotence, and uses Android's dedicated `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` package intent rather than generic application settings.

## [2026-08-09] test | Validate secret isolation, mobile consent, and exact APK identity

- Protected workflow/producer tests passed 74/74, `ota_contract_gate.py contract` and actionlint passed, and full root discovery ran 130 tests with 129 passing; the sole expected error is the unchanged fail-closed trusted-policy test because this candidate bundle is intentionally not self-authorized. Quick passed in 36.15 seconds with doctor 12 pass/1 Docker-covered Java warning/0 fail, backend 49 tests with one opt-in MariaDB skip, Compose, Orca lifecycle/profile, protocol 16, observability 18, OTA contract, and hardwareless Gate 4.
- A tracked/non-ignored disposable Flutter copy passed strict format for 27 app-owned files with zero changes, analysis with no issues, and 29/29 tests. A separate disposable Gradle 9.1.0 lane passed 35/35 targeted native tests across eight fresh JUnit suites, including GATT, installed-package identity, and the dedicated battery-intent policy, then built the debug APK successfully.
- The protected producer inspected that exact APK with actual `apkanalyzer` and `apksigner`, matched package/versionCode/versionName/embedded commit and one signer, created the current signed schema, and independently verified the same artifact binding. Interim disposable subset/tool prerequisites were corrected without mounting the shared worktree for `pub get`; exact task containers, temporary copies, and the task-owned temporary image were removed after validation.
- These are host/software and public-test-key canary checks only. PR #59 remains Draft and unmerged; trusted-policy authorization, hosted exact-head checks and independent review, Samsung/OEM permission and battery UX, physical APK install/first-run health, real BLE/ESP32-C6/radio/relay, Target bootloader/rollback, OTA-G1..G4, RELAY-G0..G2, issue #52 credential provisioning, operator acceptance, production signing, deployment, and production authorization remain open and fail-closed.

## [2026-08-09] fix | Integrate exact post-PR64 main into PR #59

- Integrated exact `origin/main` `17cc961f0c751c27fae813d1c8c24692369f215c` once with a normal two-parent merge. The exact new-main log is the prefix, the prior PR #59 suffix remains byte-identical, and only main's temporary policy JSON, policy test, trusted-workflow guide, and append-only log enter the branch.
- Preserved the five protected PR #59 blobs and normalized digests unchanged, and preserved the `raw/` tree at `013c00e7617365aa30c8bd0d38d9503d3885d264`. PR #59 remains Draft/unmerged and production remains off.

## [2026-08-09] test | Revalidate PR #59 after temporary policy integration

- Quick passed in 34.99 seconds, protected OTA/manifest tests passed 74/74, the OTA contract and actionlint passed, and the temporary policy recognized the exact PR #59 bundle while all byte-mutation and mixed-bundle rejection tests passed.
- Root discovery passed 130/131 and the focused policy suite passed 27/28. The sole failure is main's unchanged checkout-ID assertion expecting `current-main-baseline` even when the verifier correctly selects the approved `temporary-pr59-e468e0f` branch bundle; no policy, test, protected workflow, or product byte was altered to mask it.
- These are local software checks only. Hosted exact-head CI, independent review, Samsung/OEM, physical install and first-run health, BLE/ESP32-C6/radio/relay, Target bootloader/rollback, OTA, operator, signing, deployment, and production authorization remain open and fail-closed.

## [2026-08-09] fix | Integrate exact post-PR65 policy correction into PR #59

- Committed the resolved exact `17cc961f0c751c27fae813d1c8c24692369f215c` merge locally, then integrated exact `origin/main` `e1d9c740f77ae4e41200ef9e4c4a11f94eb0e702` as a second normal merge without rewriting history. The exact new-main log is the prefix and the complete prior PR #59 suffix remains byte-identical exactly once.
- Retained the temporary policy JSON from `17cc961f`, accepted the corrected policy test and trusted-workflow guide exactly from `e1d9c740`, and preserved the five protected PR #59 files, mobile/native product tree, and `raw/` tree unchanged.

## [2026-08-09] test | Revalidate approved PR #59 bundle after PR #65

- Focused trusted-policy tests passed 29/29, full root discovery passed 132/132, Quick passed in 34.87 seconds, and actionlint plus the OTA contract passed.
- Flutter/native sources and protected producers are byte-identical to the previously validated `e468e0f` product tree, so its disposable Flutter 29/29, native 35/35, debug APK, and signed-manifest evidence remains bound to the same product bytes; hosted exact-head reruns remain required for the final merge head.
- PR #59 remains Draft and unmerged. Samsung/OEM, physical install and first-run health, BLE/ESP32-C6/radio/relay, Target bootloader/rollback, OTA-G1..G4, RELAY-G0..G2, operator, production signing, deployment, and production authorization remain open and fail-closed.

## [2026-08-09] compile | Rotate PR #59 trust policy to exact merged main

- Replaced the transition policy with one indivisible `current-main-baseline` sourced from exact merged `main` `ed19f3256ac8857367f1f490eb1f5f717e20ca03`. The protected-path order remains exactly deploy, mobile build, OTA contract, protected OTA gate, and pinned OTA requirements; their independently recomputed normalized SHA-256 digests are `4bf77e4c...`, `f3f66873...`, `8e2c1479...`, `751e18ce...`, and `d2dc1631...`.
- Removed `temporary-pr59-e468e0f` entirely and retired the earlier `4e628baf...`/`cc977e42...` main provenance. Tests require the sole exact merged-main bundle and reject retired bytes or identities, partial bundles, path swaps, mixed digests, source mismatches, and per-path mutations. No protected workflow, protected producer, product, firmware, mobile, backend, `raw/`, runtime, signing, or deployment byte changed.

## [2026-08-09] test | Validate final PR #59 policy-only rotation

- The focused trusted-policy suite passed 30/30, full root discovery passed 133/133, actionlint and JSON parsing passed, and Quick passed in 35.65 seconds with doctor 12 pass, one Docker-covered native Java 17 warning, and zero failures.
- This final trust-anchor rotation is repository authorization only. Samsung/OEM, physical APK install and first-run health, BLE/ESP32-C6/radio/relay, Target bootloader/rollback, OTA-G1..G4, RELAY-G0..G2, operator acceptance, production signing, deployment, and production authorization remain open and fail-closed.

## [2026-08-09] compile | Temporarily authorize exact PR #67 backend bundle

- Expanded the trusted protected-path set from the existing five release controls to one ordered 57-file set by appending the exact 52 backend and operations inputs from `ops/backend_trusted_bundle_paths.json` at reviewed PR #67 commit `2bb223629c848f298177fc16ec3cac1fa40b8e0f`.
- Added only `temporary-pr67-2bb2236`, sourced from `ks-house/smart-gatekeeper@2bb223629c848f298177fc16ec3cac1fa40b8e0f`, with all 57 independently recomputed `utf8-lf-v1` digests authorized by COMMENTED review `4890584574`. The prior five-path baseline is intentionally absent because it cannot be a complete bundle after adding paths not present on pre-PR67 main; PR #67 must be followed immediately by a separate merged-main baseline rotation.
- No protected workflow, validator, product, backend, firmware, mobile, runtime, signing, deployment, or `raw/` byte changed.

## [2026-08-09] test | Validate exact PR #67 temporary whole-bundle policy

- The validator fetched exact PR #67 GitHub Contents API bytes and selected `temporary-pr67-2bb2236` with `protected_file_count: 57`; an independent fetched Git ref calculation also matched all 57 review-authorized digests and the exact 52-path backend manifest.
- Focused trusted-policy tests passed 29/29, full root discovery passed 132/132, actionlint and JSON parsing passed, and Quick passed all ten software sections in 35.53 seconds with doctor 12 pass, one Docker-covered native Java warning, and zero failures. Missing, old-five partial, reordered, swapped, mixed, retired-source, digest, extra-bundle, and candidate self-use mutations remain fail-closed.
- This policy-only software authorization does not approve or merge PR #67 and does not close production, physical soak/restore, Samsung/OEM, ESP32-C6/relay/radio, OTA/rollback, operator, or deployment Gates.

## [2026-08-09] fix | Bind temporary trust authorization to actual candidate identity

- Remediated blocking COMMENTED review `4890625756` by making the production validator receive the actual candidate repository and immutable lowercase 40-hex SHA as authorization inputs. Identity-ineligible candidates now fail before protected bytes are fetched, so equivalent bytes from a fork, wrong repository, retired commit, case variant, branch, tag, or malformed ref cannot select `temporary-pr67-2bb2236`.
- Upgraded the strict policy schema to format version 2 with explicit `temporary-exact` and `persistent-baseline` modes. Temporary authorization requires exact repository plus SHA; a future persistent baseline permits unchanged protected bytes only on later immutable SHAs in the same trusted repository. Canonical path syntax, case-folding uniqueness, authorization-identity uniqueness, and single CLI identity occurrence are fail-closed.
- The PR's hosted check continues to execute only the exact `1ce7f16a...` base policy and validator, so this validator change cannot authorize itself. It requires fresh independent exact-head review before merge and becomes authoritative only from trusted `main` for the subsequent exact PR #67 rerun.

## [2026-08-09] test | Validate runtime source binding and policy schema v2

- Focused trusted-policy tests passed 33/33 and full root discovery passed 136/136. Adversarial coverage rejects wrong repositories/forks, old or altered SHAs, repository/SHA case variants, mutable refs, missing or duplicated identity options, dot/backslash/empty/case-colliding paths, duplicate authorization identities, partial/mixed bundles, and candidate policy/validator self-use.
- The production CLI fetched exact GitHub API bytes for `ks-house/smart-gatekeeper@2bb223629c848f298177fc16ec3cac1fa40b8e0f` and approved all 57 protected paths as `temporary-pr67-2bb2236`. Quick passed all ten software sections in 34.18 seconds with doctor 12 pass, one Docker-covered Java warning, and zero failures.
- These are repository authorization and software checks only. PR #67 remains Draft/unmerged, and physical, Samsung/OEM, ESP32-C6/radio/relay, OTA/rollback, operator, production signing, deployment, and production authorization Gates remain pending and fail-closed.

## [2026-08-09] compile | Rebind PR #67 temporary authorization to exact merge head

- Replaced the retired `temporary-pr67-2bb2236` identity with exactly one `temporary-exact` bundle, `temporary-pr67-4f14ec6`, bound to `ks-house/smart-gatekeeper@4f14ec660bc69fa9afc23ab4f257f52fcc4a7a22`. The protected path order and all 57 `utf8-lf-v1` digests are unchanged.
- Independently fetched both immutable Git refs and recomputed every protected digest: exact `4f14ec6` matches exact `2bb2236` for all 57 paths, and its 52-path backend manifest still exactly matches the protected-path suffix. The old commit is now an explicitly rejected runtime/source identity.
- No trusted workflow, validator, protected product, backend, firmware, mobile, runtime, signing, deployment, or `raw/` byte changed. The existing five-path main baseline cannot be retained as a complete 57-path bundle; one persistent merged-main baseline must be restored immediately after unchanged-head PR #67 is normally merged.

## [2026-08-09] test | Validate exact PR #67 merge-head policy rotation

- The focused trusted-policy suite passed 33/33, full root discovery passed 136/136, JSON parsing and actionlint passed, and the production GitHub Contents API verifier approved exact `ks-house/smart-gatekeeper@4f14ec660bc69fa9afc23ab4f257f52fcc4a7a22` as `temporary-pr67-4f14ec6` with `protected_file_count: 57`.
- Runtime negative checks rejected the retired `2bb223629c848f298177fc16ec3cac1fa40b8e0f` identity and a wrong repository before candidate bytes could authorize. Existing tests continue to reject missing, partial, reordered, swapped, mixed, per-path digest, extra-bundle, mutable-ref, case/path, duplicate-identity, and candidate self-use mutations.
- Quick passed all ten software sections in 35.86 seconds with doctor 12 pass, one Docker-covered native Java warning, and zero failures. These checks do not merge or deploy PR #67 and do not close physical, Samsung/OEM, ESP32-C6/radio/relay, OTA/rollback, operator, production signing, or production authorization Gates.

## [2026-08-09] fix | Add fail-closed descendant transition for PR #67

- Hosted Trusted run `31304004723` rejected policy-only PR #69 at source identity before fetching candidate bytes. This proves base-policy non-self-use and also exposes the expected PR-only transition deadlock: trusted main authorizes only exact `2bb2236`, so neither corrected policy head `e0cf439` nor exact product head `4f14ec6` can pass without one explicitly governed exception.
- Superseded the one-bundle draft with two non-ambiguous authorizations over the same complete 57-digest map: exact `temporary-pr67-4f14ec6` and `future-pr67-persistent-baseline`. Exact identity takes precedence; persistent use now requires the candidate to equal or be a GitHub Compare-proven descendant of `4f14ec6`, with exact base and merge-base SHAs. Old ancestor `2bb2236`, diverged history, forks, mutable refs, unproven ancestry, and a second persistent baseline per repository fail closed.
- The recovery contract permits exactly one separately authorized admin/branch-protection exception for reviewed PR #69 only, followed by immediate protection restoration. PR #67 must then remain at unchanged `4f14ec6`, pass normal Trusted/review checks, and merge normally; its immediate final policy rotation removes both transition bundles and pins the actual merged-main 57-file baseline through the descendant authorization. No merge, protection change, product deployment, or physical completion is performed by this change.

## [2026-08-09] test | Validate descendant-bound PR #67 transition

- Focused trusted-policy tests passed 37/37 and full root discovery passed 140/140. Coverage pins exact-temporary precedence, one persistent baseline per repository, mandatory ancestry proof, exact compare base/merge-base/status, two identical complete maps, old/fork/diverged/malformed identities, all path/digest/mix mutations, and candidate policy/validator non-self-use.
- The production GitHub Contents verifier approved exact `ks-house/smart-gatekeeper@4f14ec660bc69fa9afc23ab4f257f52fcc4a7a22` as `temporary-pr67-4f14ec6` with 57 files and rejected ancestor `2bb223629c848f298177fc16ec3cac1fa40b8e0f`. Live GitHub Compare evidence returned true for `2bb2236` as an ancestor of `4f14ec6` and false for the reverse, demonstrating that the future baseline cannot re-admit the retired ancestor.
- JSON parsing and actionlint passed. Quick passed all ten software sections in 33.33 seconds with doctor 12 pass, one Docker-covered native Java warning, and zero failures. Hosted PR #69 remains expected-red under the old trusted base until explicit governance authorization; no merge, branch-rule change, deployment, production, or physical Gate is claimed.

## [2026-08-09] fix | Bound post-exception PR #67 log integration

- A read-only `git merge-tree --write-tree ba6ba7f 4f14ec6` simulation found a real `wiki/log.md` conflict because the policy recovery and PR #67 both append from main `8f925f9`. Therefore the earlier unchanged-head sequence is not normally mergeable after PR #69 and is superseded by one bounded post-exception main integration.
- After the single reviewed PR #69 exception and immediate branch-protection restoration, PR #67 must integrate that exact new main once, preserve the new-main log as prefix plus the prior PR #67 suffix byte-identically once and one new append, retain all 57 reviewed protected digests and `raw/`, and accept the trusted policy/validator from main. The resulting exact head must receive fresh review and hosted checks; the descendant baseline authorizes it only after GitHub ancestry and complete byte verification.
- No conflict was resolved and no PR #67, main, branch protection, deployment, production, or physical state changed in this audit. A second integration, product remediation, partial bundle, or manual merge bypass remains prohibited.

## [2026-08-09] code | Implement repository-side commercial operations and privacy controls (#52)

- Added default-redacted logging and consent-bound support exports, versioned tenant retention deletion with immutable evidence, opaque-peer rate limits, persistent bounded MQTTS publication with backpressure/circuit recovery, dependency readiness, fixed-label metrics and fail-closed evidence generation. Existing administrator session/RBAC/CSRF/re-auth, manual control, mobile update and Target OTA/rollback boundaries remain independent.
- Added a digest-pinned non-root backend image, hash-locked dependencies, hardened production-only Compose with external secrets/no host ports/no live source mount, deterministic CycloneDX SBOM and license/vulnerability policy, fixed Prometheus alert rules, SLO evaluator, and backup-manifest/isolated-restore integrity and RPO/RTO harness. The five protected OTA/deployment workflow files and trusted policy were not changed.
- Documented exact operator commands and evidence boundaries in `wiki/commercial_operations.md`; production stays OFF and legal retention approval, live alert delivery, production-like independent restore, 24-hour soak, physical gates, operator acceptance and explicit authorization remain pending.

## [2026-08-09] test | Validate Issue #52 software operations without closing live or physical Gates

- Backend discovery passed 70 tests with the real MariaDB lane opt-in skipped; the separate opt-in MariaDB test then passed actual expand migrations, logical dump, manifest/RPO verification, isolated separate-schema restore, tenant/access/ACL/audit/privacy integrity checks, measured synthetic RTO, rollback and N/N-1 legacy read. Repository operations contract, nominal SLO fixture, hash-lock dry-run, dependency vulnerability audit and dev/production Compose rendering passed.
- The digest-pinned backend image built successfully, ran as UID/GID `10001:10001` on a read-only root with temporary storage, and returned process liveness; Docker import fallback was corrected and revalidated. These checks do not prove a NAS deployment, production secrets/proxy/network, real broker/DNS/certificate/storage faults, alert receipt, independent operator restore or 24-hour soak.
- `raw/` and the five protected workflow/producer files are unchanged. Samsung/OEM, Android physical install, BLE/ESP32-C6/radio/sensor/relay, Target bootloader/rollback, OTA-G1..G4, RELAY-G0..G2, legal/privacy approval, production signing/deployment and user physical acceptance remain open and fail-closed.

## [2026-08-09] test | Run final cross-layer software validation for Issue #52

- Orca `Software` validation passed in 45.88 seconds: doctor 12 pass/one Docker-covered native Java warning/zero fail, backend 70 tests with the isolated MariaDB lane intentionally skipped in discovery, dev Compose, staged profile/lifecycle tests, protocol vectors plus 16 tests, observability 18 tests, OTA contract, hardwareless Gate 4 tests and root 133 tests all passed.
- The separate real MariaDB opt-in lane passed in 23.53 seconds with actual logical backup and isolated restore. The hash-locked setup rerun, deterministic 24-component SBOM generation, actionlint, dependency audit with no known vulnerability, production Compose rendering, non-root read-only image smoke and append-only/protected-scope checks are repository/host evidence only.
- Exact-head hosted workflow, SBOM provenance attestation and independent review remain required before merge. Live alert delivery, separate-host operator restore, 24-hour load/soak, legal/privacy approval, every physical/OTA/relay Gate and production authorization remain pending.

## [2026-08-09] fix | Harden final operations error and proxy boundaries

- Replaced two database failure responses that could reflect internal exception text with fixed Korean service-unavailable messages, required tenant-scoped opaque support-export digests, serialized the circuit-breaker half-open probe, and accepted a single forwarded client address only from an explicitly trusted proxy.
- Added adversarial trusted/untrusted/chained forwarding coverage. The final Orca `Software` suite passed in 43.13 seconds with backend discovery at 71 tests (one isolated MariaDB opt-in skip) and root discovery at 133 tests; the separate real MariaDB logical backup and isolated-restore lane remains passed at 23.53 seconds.
- These are repository/host controls only. Hosted exact-head review and attestation, legal approval, live soak/alerts, independent-host restore, physical hardware/OTA/relay acceptance, production secrets/signing/deployment and explicit production authorization remain pending and fail-closed.

## [2026-08-09] fix | Canonicalize SBOM identity across Git line endings

- Hosted backend run `31291937131` passed every runtime/security test but exposed one supply-chain portability defect: the deterministic SBOM serial used raw lockfile bytes, so Windows CRLF and Linux LF checkouts produced different UUIDs.
- Canonicalized only the SBOM identity input to UTF-8 LF text while retaining byte-exact hashes for backup integrity, and added an LF/CRLF adversarial equality test. A new exact-head hosted run is required; no protected workflow/producer, OTA, mobile, firmware, `raw/`, secret, deployment or production state changed.

## [2026-08-09] test | Revalidate portable SBOM correction locally

- The focused operations gate passed 6/6 including the new LF/CRLF mutation, and the full Orca `Software` suite passed in 45.04 seconds with backend discovery 72 tests (one explicit MariaDB opt-in skip), protocol 16, observability 18, hardwareless 4 and root 133 tests.
- The previously passed real MariaDB restore evidence remains bound to unchanged migration/restore code. Hosted exact-head rerun, review and provenance remain required; production remains OFF.

## [2026-08-09] fix | Remediate PR #67 commercial operations security review

- Closed the eight repository-side blockers from COMMENTED review `4890422659`: expanded backend workflow trigger coverage and immutable toolchain/service inputs; defined a complete backend trusted-input bundle without candidate self-authorization; required digest-only API/DB production artifacts with baked migrations and dependency readiness; and bound readiness to control/admin authentication, active ACL runtime and disabled legacy lookup.
- Bound support export to a current tenant/purpose/expiry/revocation database consent while keeping raw consent, tenant names and unit data out of response, audit and MQTT failure logs. Bound retention deletion idempotency to the canonical tenant/actor/policy/window payload with one durable `PENDING` to `COMPLETED` transition and conflict rejection.
- Added authenticated source/target schema, primary-key, row-count and content inventories to backup/restore verification; strict fixed-ID commit/digest/reviewer/expiry/hosted-provenance evidence validation; and an end-to-end bounded MQTT DNS/TCP/TLS plus PUBACK deadline with cancellation and connection-fanout prevention.
- PR #67 remains Draft, unmerged and production OFF. A separate trusted-base policy-only rotation from trusted `main`, independently reviewed and merged without candidate self-approval, is still required before the backend executable/input bundle may be admitted.

## [2026-08-09] test | Validate PR #67 security remediation locally

- Backend discovery passed 76 tests with one explicit isolated-MariaDB opt-in skip. The separate real MariaDB lane passed actual migrations, one-way consent revocation, concurrent payload-bound deletion, authenticated logical backup, measured isolated restore, complete source/target inventory equality, rollback and legacy read in 28.60 seconds.
- The operations contract passed 23 checks; adversarial tests reject mutable images, missing workflow paths, forged/expired/self-reviewed/unhosted evidence, fabricated/expired/revoked/cross-tenant consent, idempotency payload mismatch, dump/inventory/HMAC mutation, incomplete restore and blocked MQTT connect fanout. Python compilation, workflow YAML/actionlint, dev/production Compose rendering and mutable `API_IMAGE` rejection passed.
- Digest-pinned API and migration-database images built successfully; the API image imported as UID `10001`. These are local repository/host results only. Hosted exact-head CI/attestation, independent trusted-base review, legal/privacy approval, live alerts, production-like independent restore, 24-hour soak, Samsung/OEM, BLE/ESP32-C6/radio/sensor/relay, OTA-G1 through G4, RELAY-G0 through G2, operator acceptance, signing, deployment and production authorization remain open and fail-closed.

## [2026-08-09] test | Run final cross-layer validation for PR #67 remediation

- Orca `Software` validation passed in 47.39 seconds: doctor 12 pass/one Docker-covered Java warning/zero fail, backend 76 tests with the isolated MariaDB lane intentionally skipped in discovery, dev Compose, staged profile/lifecycle, protocol 16, observability 18, OTA contract, hardwareless Gate 4 and root 133 tests all passed.
- The 23-check operations contract, immutable-image validator and deterministic 24-component SBOM matched the tracked artifact. Local `pip-audit` was unavailable in this isolated environment, so vulnerability acceptance remains bound to the exact-head hosted pinned audit action; no local absence is represented as a product pass.
- Production remains OFF. The separate trusted-base policy rotation, hosted exact-head CI and SBOM attestation, independent review, live/physical/operator/legal gates and explicit production authorization remain blocking.

## [2026-08-09] fix | Close residual PR #67 operations provenance and database blockers

- Remediated exact-head COMMENTED review `4890481590` without preparing or self-authorizing a policy change. Passed evidence now queries fixed GitHub APIs and binds the authoritative commit author, successful exact-main trusted workflow/run attempt, non-expired artifact archive plus subject digests, exact-commit independent approval, and GitHub-hosted SLSA repository/ref/workflow/commit/invocation; caller environment provenance is not trusted.
- Retired legacy raw-device `POST /api/v1/door/prearm` with fixed `410` before database or MQTT access whenever the production legacy flag is off, and bound readiness to that actual authority plus the exact `007` migration digest. Mobile update, Target OTA/rollback and manual recovery paths remain unchanged.
- Replaced caller-declared RTO with a single empty-target harness that times the actual MariaDB import through authenticated full-inventory verification. Added a seed-free production baseline, backup-first digest-ledger migration runner with repeat-run verification and explicit rollback, existing-volume migration service/API admission, and a complete 51-path backend/operations/vector trusted input declaration. Production remains OFF and the separate trusted-base whole-bundle policy dependency remains blocking.

## [2026-08-09] test | Validate residual PR #67 remediation across real MariaDB and software suites

- Focused operations/API/runtime/migration tests passed 39/39 with two explicit MariaDB opt-in skips. Both opt-in lanes then passed in 46.63 seconds: actual legacy up/dump/restore/down compatibility and the seed-free production DB image fresh-volume plus existing-record upgrade, identical repeat, backup sidecars and rollback.
- The Orca `Software` suite passed in 47.49 seconds: doctor 12 pass/one Docker-covered native Java warning/zero fail, backend discovery 82 tests with the two opt-in lanes intentionally skipped, dev Compose, staged profile/lifecycle, protocol 16, observability 18, OTA contract, hardwareless Gate 4 and root 133 tests. Python compilation, actionlint, the 29-check operations contract, deterministic 24-component SBOM, digest-pinned API/DB image builds and production Compose rendering also passed.
- These are local repository/host results only. New exact-head hosted CI, SBOM/operations attestation, fresh independent review and trusted-base bundle authorization remain required; legal/privacy approval, production-like independent restore, live alerts/24-hour soak, Samsung/OEM, BLE/ESP32-C6/radio/sensor/relay, OTA-G1 through G4, RELAY-G0 through G2, operator acceptance, signing, deployment and explicit production authorization remain open and fail-closed.

## [2026-08-09] fix | Preserve every rapid backup and wait for the initialized production schema

- Exact-head hosted backend run `31295046466` exposed that two idempotency checks within one UTC second selected the same pre-migration backup filename and left only one file. Backup identity now includes UTC nanoseconds, direction, target and process identity, and any residual collision fails closed instead of overwriting evidence.
- A local rerun then exposed an independent test race: the temporary MariaDB initialization server accepted `SELECT 1` before the seed-free baseline completed. The product-image lane now waits for an actual `smart_gatekeeper.tenants` query before asserting emptiness or migrating. The focused production image lane passed with two distinct up backups, matching checksum sidecars, preserved existing data and explicit rollback; a new exact-head hosted run is required.

## [2026-08-09] fix | Bind every operations claim to its authoritative producer and merged review

- Remediated blocking COMMENTED review `4890544652` with a fixed policy per evidence ID covering scope, workflow/ref/event, producer and attestor job/step, execution environment, artifact name/archive path, attestation subject path, typed claim/result/payload schema and SLSA predicate. Only repository `ops-contract` and `hosted-sbom-attestation` claims are admitted; isolated restore, 24-hour physical soak and production deployment reject `passed` before network access until their own trusted producer/environment contracts exist.
- Added deterministic disjoint claim envelopes and exact-main attestations for the admitted software claims. The register and live verifier reject duplicate subject or payload digests, SAME_SBOM_FOR_ALL, cross-ID artifact swaps and claim relabeling, and bind an approval to the authoritative reviewer numeric identity plus the exact closed/merged PR, `main` base, reviewed head and merge commit.
- Hardened artifact download redirects to require HTTPS on every hop and compare normalized scheme, host and effective port. Authorization is removed on any full-origin change and all HTTPS-to-HTTP downgrades are rejected. Added the executable adversarial corpus `ops/fixtures/evidence_adversarial_v1.json`; production remains OFF and no trusted-policy candidate was prepared.

## [2026-08-09] test | Validate ID-scoped evidence, redirects and full Issue #52 regression

- Focused operations/API/runtime/migration tests passed 41/41 with the two explicit Docker lanes skipped; the 10 evidence-gate tests include SAME_SBOM_FOR_ALL, reused payload, cross-ID workflow/artifact/claim, unrelated merge/reviewer/job/attestation and same-host downgrade/different-host/different-port redirect mutations. Both generated claim envelopes, actionlint and the expanded 34-check operations contract passed.
- The actual legacy MariaDB up/dump/restore/down lane passed. The production-image lane exposed that the init temporary socket can already contain the baseline before its final server restart; readiness now requires both the real `tenants` query and `@@port=3306`, after which the seed-free existing-volume/repeat-backup/rollback lane passed in 13.35 seconds.
- Orca `Software` passed in 46.85 seconds: doctor 12 pass/one Docker-covered Java warning/zero fail, backend 84 tests with two opt-in skips, dev Compose, Orca profile/lifecycle, protocol 16, observability 18, OTA contract, hardwareless 4 and root 133 tests. Fresh exact-head hosted CI and clean independent re-review remain required; policy authorization, live/legal/operator/physical/OTA/relay evidence and production authorization stay fail-closed.

## [2026-08-09] fix | Integrate exact post-PR68 trusted policy into PR #67

- Integrated exact `origin/main` `8f925f91b3495f51012c1cf48e80dcfd39abc614` once with a normal two-parent merge and no history rewrite. The exact new-main log is the byte prefix, the complete prior PR #67 suffix is preserved exactly once, and this integration entry is the only new append.
- Accepted the policy schema v2 validator, tests, guide and 57-path `temporary-pr67-2bb2236` authorization exactly from trusted main. All backend, operations, vector and workflow candidate product bytes remain identical to reviewed PR #67 commit `2bb223629c848f298177fc16ec3cac1fa40b8e0f`; `raw/` is unchanged.
- The exact policy verifier selected `temporary-pr67-2bb2236` with all 57 paths; focused policy tests passed 33/33, root discovery passed 136/136, actionlint passed, and Orca `Software` passed all eleven sections in 50.21 seconds with backend 84 tests/two explicit Docker-lane skips. PR #67 remains Draft and production remains OFF; hosted exact-head checks and a fresh independent review remain required, while legal, live-soak, independent-host restore, physical, OTA, relay, operator, signing, deployment and production authorization Gates stay open and fail-closed.
## [2026-08-09] fix | Integrate exact post-exception main into PR #67

- Integrated exact `origin/main` `f5c90bef2c2d4500ff68c014d1385ac37b440f0c` once with a normal two-parent merge and no history rewrite. The exact new-main log is the byte prefix, the complete prior PR #67 suffix is preserved byte-identically exactly once, and this integration entry is the only new append.
- Accepted the trusted policy, validator, tests and guide exactly from main. All 57 reviewed protected product files and the `raw/` tree remain unchanged from PR #67 head `4f14ec660bc69fa9afc23ab4f257f52fcc4a7a22`; the persistent descendant authorization requires live GitHub Compare proof for this new exact head.
- Focused policy tests passed 37/37, root discovery passed 140/140, Quick passed all ten sections with backend 84 tests/two explicit Docker-lane skips, the 34-check operations contract and nominal SLO fixture passed, and `git diff --check` is clean. PR #67 remains Draft and unmerged with production OFF; hosted exact-head checks plus an independent COMMENTED review remain required, while NAS deployment, live/legal/operator, physical mobile/ESP32-C6/radio/relay/sensor, OTA/rollback and production authorization Gates remain open.

## [2026-08-09] compile | Rotate merged PR #67 policy to sole current-main baseline

- Removed both transition identities, `temporary-pr67-4f14ec6` and `future-pr67-persistent-baseline`, and installed exactly one 57-file `persistent-baseline` named `current-main-baseline` sourced from `ks-house/smart-gatekeeper@22ddc7237f15758a0c77c72902b51ff25d31e483`, the exact PR #67 merged-main commit.
- Recomputed all 57 `utf8-lf-v1` digests from GitHub Contents API bytes at that immutable commit and matched them against the local Git tree and reviewed transition map. Only the policy, its adversarial tests, the trusted-policy guide, and this append-only log are changed; the validator, protected product/workflow files and `raw/` remain unchanged.

## [2026-08-09] test | Validate final PR #67 merged-main policy rotation

- Focused trusted-policy tests passed 37/37, full root discovery passed 140/140, JSON parsing, actionlint and `git diff --check` passed, and Orca Quick passed all ten sections in 40.6 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures.
- The production verifier fetched the exact GitHub API bytes for `ks-house/smart-gatekeeper@22ddc7237f15758a0c77c72902b51ff25d31e483` and selected `current-main-baseline` with `protected_file_count: 57`. Hosted exact-head Trusted CI and independent COMMENTED review remain required before normal merge; NAS deployment, live/legal/operator, physical mobile/ESP32-C6/radio/relay/sensor and OTA/rollback Gates remain open.

## [2026-08-09] fix | Remove stale governance-exception guidance from final rotation

- Corrected the trusted-policy guide so the final rotation is described as validator/workflow unchanged, authorized by the trusted base only after ancestry and complete 57-file byte proof, and eligible solely for a normal protected merge after Hosted Trusted success and fresh review. Removed stale transition text that incorrectly described this PR as expected-red and requiring a governance exception.
- Clarified that the regression assertion pins a sole final bundle while the generic runtime schema may represent a future reviewed transition; runtime fork, retired/diverged source, path and digest checks remain fail-closed. No policy, test, validator, protected product/workflow or `raw/` byte changed in this documentation remediation.

## [2026-08-09] test | Revalidate final-rotation guidance after independent review

- Focused trusted-policy tests passed 37/37 and full root discovery passed 140/140 after the documentation-only remediation. The final guide contains no expected-red or two-bundle-current-state claim and requires Hosted Trusted success plus fresh exact-head review before a normal protected merge.
- The prior Quick 10-section pass remains bound to identical policy, test, validator, protected product/workflow and `raw/` bytes. A new exact-head Hosted Trusted run and fresh COMMENTED review remain required after push; no merge, deployment or physical Gate completion is claimed.

## [2026-08-09] compile | Retrace final manuals against merged commercial operations

- Integrated exact `origin/main` `e42d1f417a555b17d7476522aa48f7e4d72306b7` once with a normal two-parent merge while preserving the pre-existing Issue #53 manual and test working bytes. Updated the Korean general-user, administrator, installer, privacy and support manuals plus the reverse-analysis register to v0.3.0-rc.1.
- Replaced stale Issue #52 placeholders with exact process-only `/live`, dependency `/ready`, authenticated metrics, tenant/purpose/expiry/revocation-bound support export, payload-bound retention deletion, HMAC inventory backup/restore and immutable production Compose contracts. Expanded the hardwareless fixture from 12 to 16 actor journeys and added source-bound regressions.
- Defined NAS deployment as a staging step for user physical validation, not production authorization. Samsung/OEM, APK install/fallback, ESP32-C6/BLE/radio/sensor/GPIO3 relay, Target OTA reboot/health/rollback, independent restore, live alert/soak, legal/privacy, operator and production evidence remain pending and fail-closed; `raw/` and workflow files are unchanged.

## [2026-08-09] test | Validate manuals, reverse analysis and cross-layer boundaries

- Manual contract tests passed 10/10 with exact source/API trace, 16 complete actor fixtures, relative links, UTF-8 without BOM, LF-only bytes, stale-baseline rejection, secret exclusion and NAS/physical/production evidence separation. JSON parsing and `git diff --check` passed.
- Full root discovery passed 150/150. The first Quick invocation stopped before tests because this worktree had no `.venv`; the standard isolated setup completed with 12 doctor passes, one Docker-covered native Java warning and zero failures, then Quick passed all ten sections in 40.77 seconds with backend 84 tests/two explicit Docker-lane skips, Compose, Orca profile/lifecycle, protocol 16, observability 18, OTA contract and hardwareless 4.
- These are repository/host results only. Draft PR exact-head hosted checks, independent COMMENTED review, NAS staging evidence and every live, legal, operator, physical, OTA/relay and production Gate remain required.

## [2026-08-09] fix | Make every manual walkthrough independently executable

- Remediated blocking COMMENTED review `4891259615`: all 16 hardwareless scenarios now include a bounded read-only `python -m unittest` command, expected output token and exact exit code instead of documenting execution fields that the fixture omitted.
- The contract schema requires those fields, permits only a strict unittest command grammar, rejects shell metacharacters and executes each scenario in the repository root with a 90-second bound. No product, workflow, secret, `raw/`, NAS, physical or production state changed.

## [2026-08-09] test | Revalidate executable walkthrough review remediation

- Manual contracts passed 11/11 and all 16 declared commands independently returned exit code 0 with the expected `OK` token. JSON parsing and `git diff --check` passed.
- Full root discovery passed 151/151 in 25.76 seconds. Quick passed all ten sections in 40.48 seconds with backend 84 tests/two explicit Docker-lane skips, Compose, Orca profile/lifecycle, protocol 16, observability 18, OTA contract and hardwareless 4.
- Fresh exact-head Hosted Trusted and independent COMMENTED re-review remain required. NAS deployment and every live, legal, operator, physical, OTA/relay and production Gate remain pending.

## [2026-08-09] fix | Bind walkthrough commands to exact scenario evidence

- Remediated the remaining semantic blocker from COMMENTED review `4891273910`: every scenario ID is now mapped to one exact command and a unique expected test token, so an unrelated generic `OK` test cannot be substituted. Mobile manifest coverage runs the full artifact mutation module rather than a nominal workflow validator.
- Added the missing Flutter widget regression proving the recovery shell keeps manual local recovery, privacy-redacted diagnostics, verified update, Android settings and bounded setup retry reachable. Source-bound regressions tie consent/disclosure, recovery and `AppErrorLogger` UI/IPC claims to their exact Flutter test and production owners.

## [2026-08-09] test | Validate scenario semantics and recovery widget

- Manual contracts passed 14/14; all 16 exact ID-bound commands returned exit code 0 and their scenario-specific test token. A tracked-files-only disposable Flutter copy passed focused consent/recovery, AppErrorLogger and update-contract tests, 14 total, then the container exited; the temporary copy is retained only because local command policy rejected recursive cleanup.
- Full root discovery passed 154/154 in 26.98 seconds. Quick passed all ten sections in 39.60 seconds with backend 84 tests/two explicit Docker-lane skips, Compose, Orca profile/lifecycle, protocol 16, observability 18, OTA contract and hardwareless 4.
- Fresh exact-head hosted mobile/Trusted checks and an independent COMMENTED re-review remain required. Samsung/OEM, physical APK/ESP32-C6/radio/sensor/relay, Target OTA/rollback, NAS live/operator/legal and production Gates remain pending.

## [2026-08-09] fix | Make manual walkthrough commands dependency-portable

- Remediated the exact-head Hosted Mobile/OTA blocker from COMMENTED review `4891296417`: all 16 fixture commands now use Python `-S`, so site-packages cannot satisfy undeclared imports. Replaced eight FastAPI-dependent backend commands and the mobile-manifest dependency command with standard-library-only source contracts bound to the exact dependency-backed test definition and production owner.
- The fixture labels these as source bindings rather than claiming that a dependency-free lane executed FastAPI, database, MQTT or signing integrations. Dependency-provisioned hosted suites remain the executable integration evidence; physical, operator and production evidence remains separate and pending.
- Added a regression requiring every declared command to start with the strict `python -S -m unittest tests.` grammar. The portable source-contract suite passed 9/9 and the manual suite passed 14/14, including execution of all 16 commands without site-packages. No product, workflow, secret, `raw/`, physical or production state changed.

## [2026-08-09] test | Revalidate dependency-portable walkthrough remediation

- Full root discovery passed 163/163 in 15.86 seconds. Quick passed all ten sections in 40.22 seconds with backend 84 tests/two explicit Docker-lane skips, Compose, Orca profile/lifecycle, protocol 16, observability 18, OTA contract and hardwareless 4.
- Exact-head Hosted Trusted, Mobile and OTA checks plus a fresh independent COMMENTED review remain required after push. Samsung/OEM, physical APK/ESP32-C6/radio/sensor/relay, Target OTA/rollback, NAS live/operator/legal and production Gates remain pending.

## [2026-08-09] compile | Authorize the complete reviewed PR #72 protected bundle

- From exact trusted main `038bc8508fca71e1d4074a3eedca5517d3c2ecfe`, replaced the prior sole baseline with exactly two complete 57-file authorizations for `ks-house/smart-gatekeeper@03ffba4f5020bb304a4a22cdfd4ff9c4c46a035b`: exact temporary identity `temporary-pr72-03ffba4` and same-source descendant identity `future-pr72-persistent-baseline`. Both maps are byte-identical and use strict `utf8-lf-v1`; no partial, branch, wildcard, fork or third persistent identity is admitted.
- Recomputed all 57 digests from immutable GitHub Contents API bytes. The three changed protected digests are deploy `133d31ebb91922ab9e2370e91d8a3ad4215accde1c7adbad28cb2c653aa42251`, mobile `1d17741591fde129200c6aa6403644b0d9b590de1831936d65db0e9ea9f17af2` and OTA gate `ba3bc9de1eeecc306d1b23b1a2c6ddb124a0d3d4396c54ef137e6cc3a071e1bc`; the other 54 remain equal to the prior complete baseline.
- GitHub API evidence binds open Draft PR #72 and COMMENTED nonblocking product review `4891310679` to the exact candidate commit. Compare proves that candidate is two commits ahead of exact base `e42d1f417a555b17d7476522aa48f7e4d72306b7` with that exact merge base. This policy authorization is not NAS deployment, physical evidence, release evidence or production authorization.

## [2026-08-09] test | Validate the PR #72 whole-bundle transition policy

- Focused trusted-policy tests passed 37/37. Full root discovery passed 163/163 against staged tree `0c1e0ed206e9b06da3d9eea5374038ae228bdcb3` archived with checkout conversion disabled; the first direct Windows working-tree run exposed only CRLF materialization of unchanged LF manual blobs, so it was not represented as a source failure or used as final evidence.
- Orca Quick passed all ten sections in 42.04 seconds with doctor 12 pass/one Docker-covered native Java warning/zero failures, backend 84 tests/two explicit Docker-lane skips, Compose, staged profile/lifecycle, protocol 16, observability 18, OTA contract and hardwareless 4. Actionlint across every workflow, JSON parsing, `git diff --check`, staged log byte-prefix, `raw/` tree identity and live immutable GitHub API 57-file verification passed.
- No workflow dispatch, NAS write, merge, deployment, physical validation, signing or production authorization occurred. The policy-only Draft PR still requires green exact-head Hosted Trusted and a separate independent COMMENTED whole-bundle review before normal merge.

## [2026-08-09] code | Add fail-closed NAS physical-test canary delivery lanes

- Added exact-`main` manual `physical-test-canary` jobs for the same-run firmware public canary and Android debug APK. Each job verifies its fixed RFC 8032 test signature and source SHA before network contact, stages only below a hard-coded non-production NAS root, reads artifact and manifest bytes back, verifies them again, uploads sanitized non-release evidence, and atomically publishes a unique run directory.
- Required `NAS_KNOWN_HOSTS` plus `StrictHostKeyChecking=yes` and validated known-host syntax before credentialed contact; runtime keyscan, TOFU, `accept-new`, disabled strict checking, production directory secrets and production paths are rejected. The currently absent host-key secret therefore blocks dispatch safely until an operator provisions an independently verified value.
- Added a separate `physical-test-connected` prerequisite contract using only `PHYSICAL_TEST_*` names in the protected `physical-test` Environment. It always exits non-zero even after prerequisites pass, so missing test-scoped signing/runtime inputs cannot fall back to production values or imply a connected release.
- Production jobs, conditions, Environment, release evidence, signing inputs and NAS paths are unchanged. No workflow was dispatched and no NAS data was written; manual install/flash, Samsung/OEM, ESP32-C6, BLE/radio, relay/sensor and OTA/rollback evidence remain pending.

## [2026-08-09] test | Validate NAS staging, readback and production isolation contracts

- `actionlint` passed both modified workflows. Focused OTA/NAS tests passed 74/74 and full root discovery passed 148/148, including adversarial production-directory, production-secret, missing readback, runtime keyscan, disabled strict-host checking, connected-tier enablement, byte substitution and remote-root mutations.
- The protected candidate modifies `.github/workflows/deploy.yml`, `.github/workflows/build_app.yml` and `scripts/ota_contract_gate.py`; current trusted main has not authorized these bytes. A product Draft PR, independent COMMENTED whole-bundle review, and a separate trusted-main policy authorization remain required before merge or dispatch.
- Antigravity was invoked once for bounded read-only lint but returned unrelated CLI sandbox documentation rather than repository findings. Its output is not counted as validation; the exact local `actionlint`, Python contract tests and diff checks remain the recorded software evidence.

## [2026-08-09] fix | Reject NAS transport grammar injection and cover contract-only changes

- Remediated both blockers from independent COMMENTED review `4891287192`. Before invoking OpenSSH, both public physical-test jobs now require a portable non-option NAS username, hostname/IPv4-compatible host, port 1 through 65535, exact lowercase 40-hex commit and positive numeric run identifiers; IPv6 literals are intentionally unsupported.
- Bound every transport/path validation to the workflow contract and adversarial mutations, so removing a username, host, port-range, commit or run-component check fails closed. Mandatory repository-pinned known hosts, exact-run artifact verification, isolated staging/readback and atomic publish remain unchanged.
- Added the NAS physical-test contract test to both producer pull-request filters and the mobile main-push filter. No workflow was dispatched, no NAS connection was attempted, and no NAS byte was written.

## [2026-08-09] test | Revalidate PR #72 independent-review remediation

- Focused OTA/NAS/mobile-signing tests passed 84/84, including new trigger-removal and OpenSSH/path-component validation mutations. `actionlint` passed both workflows and `git diff --check` is clean.
- Full root discovery passed 150/150. Orca `Quick` passed all ten sections in 40.75 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures.
- The protected candidate still requires a fresh exact-head independent COMMENTED review and a separate trusted-main whole-bundle policy authorization. `NAS_KNOWN_HOSTS` remains absent, so an authorized future dispatch stays blocked before network contact; physical/operator and production release evidence remain pending.

## [2026-08-09] fix | Integrate the merged PR #72 transition policy exactly once

- Integrated exact `origin/main` `5389f6a3ab2f28698d423567481ecdc29a260ace` with a normal two-parent merge and no history rewrite after policy PR #73 merged through green Hosted Trusted and nonblocking COMMENTED review `4891371819`.
- Preserved the exact new-main log as a byte prefix, appended the complete prior PR #72 suffix exactly once, retained `raw/` identity, and kept all 57 reviewed protected product bytes identical to product commit `03ffba4f5020bb304a4a22cdfd4ff9c4c46a035b`. The transition persistent bundle requires live Compare ancestry for this new exact head.
- No workflow dispatch, NAS connection/write, deployment, physical validation, release evidence or production authorization occurred. Fresh exact-head hosted checks and an independent COMMENTED product review remain required before normal product merge.

## [2026-08-09] test | Validate the post-policy PR #72 integration tree

- Focused OTA/NAS/mobile-signing tests passed 84/84. Full root discovery passed 173/173 from the staged Git index materialized with checkout conversion disabled; an earlier generic archive extraction converted unchanged manual LF blobs to CRLF and caused the manual byte-format test to fail, so that host materialization was not counted as source evidence.
- Actionlint passed every workflow, `git diff --check` passed, and Orca `Quick` passed all ten sections in 40.06 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures.
- Staged proof preserves exact main `5389f6a3ab2f28698d423567481ecdc29a260ace` log bytes as a prefix, the prior product suffix exactly once, `raw/` tree `013c00e7617365aa30c8bd0d38d9503d3885d264`, and the complete reviewed 57-file product bundle. Hosted exact-head policy/product CI and fresh independent review remain required.

## [2026-08-09] compile | Rotate merged PR #72 policy to sole current-main baseline

- Removed both PR #72 transition identities and installed exactly one `persistent-baseline` named `current-main-baseline`, sourced from exact merged main `2e540d13f1ea31d800a9a6f2f3bca668a23c4013` with the complete ordered 57-file bundle.
- Recomputed all 57 `utf8-lf-v1` digests from immutable GitHub Contents API bytes at that exact commit. Both prior transition maps match byte for byte; the only product changes remain deploy `133d31ebb91922ab9e2370e91d8a3ad4215accde1c7adbad28cb2c653aa42251`, mobile `1d17741591fde129200c6aa6403644b0d9b590de1831936d65db0e9ea9f17af2` and OTA gate `ba3bc9de1eeecc306d1b23b1a2c6ddb124a0d3d4396c54ef137e6cc3a071e1bc` relative to the earlier product baseline.
- This is a policy-only final rotation: the validator, trusted workflow, product/runtime files and `raw/` remain unchanged. No merge, workflow dispatch, NAS connection/write, deployment, physical evidence, release evidence or production authorization occurred.

## [2026-08-09] test | Validate the sole merged-main trusted baseline rotation

- Focused trusted-policy regression tests passed 37/37. Full root discovery passed 173/173 from the exact staged Git tree archived with checkout conversion disabled, and `actionlint` passed every workflow.
- Orca `Quick` passed all ten sections in 41.37 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures. JSON parsing, `git diff --check`, staged log byte-prefix, `raw/` tree identity and live immutable GitHub API verification of all 57 protected files passed.
- The final policy PR still requires green exact-head Hosted Trusted and a separate independent COMMENTED whole-bundle review before normal merge. No dispatch, NAS write, deployment, physical validation, release evidence or production authorization occurred.

## [2026-08-09] compile | Authorize the complete reviewed PR #75 protected bundle

- From exact trusted main `5f68de9523e6c2ee263452a7c593ad50069a657b`, replaced the sole baseline with exactly two complete 57-file authorizations for `ks-house/smart-gatekeeper@f0f8666ab9aa2b68d042207ddb89d47f97ea7146`: exact temporary identity `temporary-pr75-f0f8666` and same-source descendant identity `future-pr75-persistent-baseline`. Both maps are byte-identical and use strict `utf8-lf-v1`; no partial, branch, wildcard, fork or third persistent identity is admitted.
- Recomputed all 57 digests from immutable GitHub Contents API bytes. The three changed protected digests are deploy `8dfb5f6becc4a9cd8eef1835552800d9cd9e1254992f017a6d341420bd930e08`, mobile `673202a2d835c57ae16702e5f1bc9bf9465654c4a262fb29024ec182b7ba8d14` and OTA gate `3730a2599e7dc995575a26ba8c2d9c66069b804d849b31730605cfab7251a687`; the other 54 remain equal to the current complete baseline.
- GitHub API evidence binds open Draft PR #75 and COMMENTED nonblocking product review `4891511958` to the exact candidate commit. Compare proves that candidate is two commits ahead of exact base `5f68de9523e6c2ee263452a7c593ad50069a657b` with that exact merge base. Hosted mobile, OTA and firmware checks succeeded; Trusted remains expected-red until this separate policy sequence lands. This authorization is not NAS deployment, physical evidence, release evidence or production authorization.

## [2026-08-09] test | Validate the PR #75 whole-bundle transition policy

- Focused trusted-policy regression tests passed 37/37. Full root discovery passed 173/173 from the exact staged Git tree archived with checkout conversion disabled, and `actionlint` passed every workflow.
- Orca `Quick` passed all ten sections in 41.81 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures. JSON parsing, `git diff --check`, staged log byte-prefix, `raw/` tree identity and live immutable GitHub API verification of all 57 protected files passed; the exact PR #75 head selects the temporary identity without ancestry fallback.
- No workflow dispatch, NAS connection/write, merge, deployment, physical validation, signing, release evidence or production authorization occurred. The policy-only Draft PR still requires green exact-head Hosted Trusted and a separate independent COMMENTED whole-bundle review before normal merge.

## [2026-08-09] fix | Allow audited NAS upload without a pinned known-host secret

- Kept `NAS_KNOWN_HOSTS` as the preferred physical-test transport mode, but made it optional for the explicitly requested public-canary lane. When absent, both firmware and mobile jobs perform a three-attempt bounded `ssh-keyscan`, validate the returned record, pin it to a run-local file, retain `StrictHostKeyChecking=yes`, and label sanitized evidence `runtime-keyscan-unpinned`.
- The fallback is restricted to exact-main `physical-test-canary`, isolated non-production roots and same-run public test-signed artifacts. Production jobs, connected-tier prerequisites, signing keys, directories and release-evidence gates remain unchanged; the first key exchange is not independently authenticated and is documented as weaker against an active network interceptor.
- Updated workflow contracts, adversarial mutations, evidence validation and operator documentation. Merge, dispatch, NAS write, real-device validation and production authorization remain pending until protected-bundle review and hosted CI complete.

## [2026-08-09] test | Validate the optional NAS host-key fallback

- Focused OTA/NAS tests passed 76/76, including both evidence modes and mutations for unbounded keyscan, disabled strict checking, unsafe transport grammar, path escape, production secret/directory substitution, readback removal and connected-tier enablement. `actionlint`, the OTA contract command and `git diff --check` passed.
- Full root discovery passed 173/173 after normalizing only unchanged manual checkout material to its committed LF bytes; the direct Windows checkout initially exposed the known CRLF materialization boundary rather than a source failure. Orca `Quick` then passed all ten sections in 41.39 seconds with backend 84 tests/two explicit Docker-lane skips, Compose, profile/lifecycle, protocol 16, observability 18, OTA and hardwareless gates.
- `raw/` remains byte-identical. Hosted exact-head checks, independent protected-bundle review, trusted policy authorization, normal merge and exact-main physical-test dispatch remain required before any NAS connection or write.

## [2026-08-09] fix | Bind keyscan retries and require per-dispatch risk acknowledgement

- Addressed COMMENTED review `4891484367` by making the fallback loop structurally exact: one `for attempt in 1 2 3` block, one 10-second/5-second-connect-timeout `ssh-keyscan`, no `while true`, and mutation tests rejecting 100 retries or removal of the bounded loop.
- Added default-false boolean workflow input `allow_unpinned_host_key` to both workflows. When the independently pinned secret is absent, the exact-main public-canary job refuses network contact unless the repository owner explicitly sets it true for that dispatch; evidence still records `runtime-keyscan-unpinned` and documentation states that this does not authenticate the first key discovery or prevent password interception.
- No policy authorization, merge, workflow dispatch, NAS connection/write, physical validation or production authorization occurred in this remediation.

## [2026-08-09] fix | Integrate the merged PR #75 transition policy exactly once

- Integrated exact `origin/main` `bbe842a13541386c9e101284cf49ab4df6bca042` into the reviewed product head `f0f8666ab9aa2b68d042207ddb89d47f97ea7146` with a normal two-parent merge and no rebase, force-push or history rewrite.
- Preserved the exact new-main `wiki/log.md` Git blob as a byte prefix, retained the complete prior PR #75 log suffix exactly once, kept all 57 protected product blobs identical to `f0f8666ab9aa2b68d042207ddb89d47f97ea7146`, retained the merged policy files exactly, and preserved `raw/` tree identity.
- No workflow dispatch, NAS connection/write, deployment, physical validation, release evidence or production authorization occurred. Fresh exact-head local/Hosted validation and an independent COMMENTED whole-bundle review remain required before normal product merge.

## [2026-08-09] test | Validate the post-policy PR #75 integration tree

- Focused trusted-policy tests passed 37/37 and OTA/NAS tests passed 76/76. All-workflow `actionlint`, the OTA contract command and `git diff --check` passed.
- Full root discovery passed 173/173 from the exact staged Git index materialized with checkout conversion disabled. An earlier ZIP extraction converted unchanged manual LF blobs to CRLF and caused one byte-format false red, so that host materialization was discarded and is not represented as source evidence.
- Orca `Quick` passed all ten sections in 44.34 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures. `raw/` identity, the exact main log byte prefix, one complete prior PR suffix, all 57 reviewed product blobs and exact merged policy blobs were independently rechecked. Hosted exact-head checks and a fresh independent COMMENTED review remain required; no NAS or production action occurred.

## [2026-08-09] compile | Rotate merged PR #75 policy to sole current-main baseline

- Removed both PR #75 transition identities and installed exactly one `persistent-baseline` named `current-main-baseline`, sourced from exact merged main `72fa8610e509de4bff3b20d60d9da19ab312bd3b` with the complete ordered 57-file bundle.
- Recomputed all 57 `utf8-lf-v1` digests from immutable GitHub Contents API bytes at that exact commit. Both prior transition maps match byte for byte; the three product digests remain deploy `8dfb5f6becc4a9cd8eef1835552800d9cd9e1254992f017a6d341420bd930e08`, mobile `673202a2d835c57ae16702e5f1bc9bf9465654c4a262fb29024ec182b7ba8d14` and OTA gate `3730a2599e7dc995575a26ba8c2d9c66069b804d849b31730605cfab7251a687`.
- This is a policy-only final rotation: the validator, trusted workflow, product/runtime files and `raw/` remain unchanged. No merge, workflow dispatch, NAS connection/write, deployment, physical evidence, release evidence or production authorization occurred.

## [2026-08-09] test | Validate the sole PR #75 merged-main trusted baseline

- Focused trusted-policy regression tests passed 37/37. Full root discovery passed 173/173 from the exact staged Git tree archived with checkout conversion disabled, and `actionlint` passed every workflow.
- Orca `Quick` passed all ten sections in 40.94 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures. JSON parsing, `git diff --check`, staged log byte-prefix, `raw/` tree identity and live immutable GitHub API verification of all 57 protected files passed.
- The final policy PR still requires green exact-head Hosted Trusted and a separate independent COMMENTED whole-bundle review before normal merge. No dispatch, NAS write, deployment, physical validation, release evidence or production authorization occurred.

## [2026-08-10] compile | Authorize the complete reviewed PR #78 protected bundle

- From exact trusted main `0a34796213d5677d9dc77a8b73564004e8e3a2cf`, replaced the sole baseline with exactly two complete ordered 57-file authorizations for `ks-house/smart-gatekeeper@44b43411d5156d9a3a08ec0f94b8336c90f6bcb5`: exact temporary identity `temporary-pr78-44b4341` and same-source descendant identity `future-pr78-persistent-baseline`. Both maps are byte-identical and use strict `utf8-lf-v1`; no partial, branch, wildcard, fork or third persistent identity is admitted.
- Recomputed all 57 digests from immutable GitHub Contents API bytes. The three changed protected digests are deploy `b73646d4e4196c48763f9e3ab5f21606df145d897c767ec1a90f25e739b7a209`, mobile `a38a63f5d31516593d91cd182614198fc538ee325a7e11364e7246e29fc11a9f` and OTA gate `d41630cb61441c135aec6756d1726d96b18e944eb96ab93f1780306b5ae780fe`; the other 54 remain equal to the current complete baseline.
- GitHub API evidence binds open Draft PR #78 and COMMENTED nonblocking product review `4891720552` to the exact candidate commit. Compare proves that candidate is one commit ahead of exact base `0a34796213d5677d9dc77a8b73564004e8e3a2cf` with that exact merge base. Hosted mobile, OTA and firmware checks succeeded; Trusted remains expected-red until this separate policy sequence lands. This authorization is not NAS deployment, physical evidence, release evidence or production authorization.

## [2026-08-10] test | Validate the PR #78 whole-bundle transition policy

- Focused trusted-policy regression tests passed 37/37. Full root discovery passed 173/173 from the exact staged Git tree archived with checkout conversion disabled, and `actionlint` passed all six workflows.
- Orca `Quick` passed all ten sections in 40.7 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures. JSON parsing, `git diff --check`, staged log byte-prefix, `raw/` tree identity and live immutable GitHub API verification of all 57 protected files passed; the exact PR #78 head selects the temporary identity without ancestry fallback.
- No workflow dispatch, NAS connection/write, merge, deployment, physical validation, signing, release evidence or production authorization occurred. The policy-only Draft PR still requires green exact-head Hosted Trusted and a separate independent COMMENTED whole-bundle review before normal merge.

## [2026-08-10] fix | Use SFTP-only transport for restricted NAS physical-test accounts

- Diagnosed firmware run `31319094568` job `93259497202` and mobile run `31319095918`: bounded runtime host-key discovery completed, then the first SSH remote-shell command failed with `Permission denied` before either job reached SFTP. This matches the established NAS account's SFTP-only permission model.
- Removed every remote-shell invocation from both public physical-test NAS jobs. Four bounded OpenSSH SFTP batches now create the hierarchy one component at a time, upload and read back the same-run artifact/manifest, upload and compare sanitized evidence, then publish with a strict direct SFTP directory `rename`.
- Existing parent-directory errors are tolerated only for `/docker`, `/docker/smart-gatekeeper-physical-test`, the fixed canary root and exact-SHA parent. Unique staging creation, every transfer, evidence comparison and final rename fail closed; no automatic remote delete or overwrite path was added.
- Preserved password SFTP compatibility with `BatchMode=no`, both host-key modes, run-local strict known-host verification, credential/path grammar, isolated physical-test roots and exact-run evidence binding. Connected and production job suffixes remain byte-identical to the exact base, and `raw/` remains unchanged. No workflow dispatch, NAS connection/write, merge, deployment, physical evidence, release evidence or production authorization occurred.

## [2026-08-10] test | Validate bounded SFTP-only NAS compatibility

- Focused OTA/NAS contract tests passed 78/78. Adversarial coverage rejects any remote-shell command, an unbounded SFTP batch, omission of any hierarchy component, ignored staging or rename errors, duplicate rename and publication before readback/evidence comparison.
- Full root discovery passed 175/175 from the exact staged Git tree materialized with checkout conversion disabled. The OTA contract command, all-workflow `actionlint`, `git diff --check`, append-only log prefix, exact `raw/` tree and byte-identical connected/production suffix checks passed.
- Orca `Quick` passed all ten sections in 41.11 seconds after the standard setup hook created the intentionally skipped worktree-local `.venv`; doctor reported 12 pass, one Docker-covered native Java warning and zero failures. No NAS endpoint was contacted and no workflow was dispatched.

## [2026-08-10] fix | Integrate merged PR #78 transition policy exactly once

- Integrated exact `origin/main` `0ec8221e275e36a5917c08a55cde10c36dd0e972` into reviewed product head `44b43411d5156d9a3a08ec0f94b8336c90f6bcb5` with a normal two-parent merge and no rebase, force-push or history rewrite.
- Preserved the exact new-main `wiki/log.md` Git blob as a byte prefix, retained the complete prior PR #78 suffix exactly once, kept all 57 protected product bytes identical to reviewed head `44b43411d5156d9a3a08ec0f94b8336c90f6bcb5`, retained the merged policy files exactly, and preserved `raw/` tree identity.
- No workflow dispatch, NAS connection/write, deployment, physical validation, release evidence or production authorization occurred. Fresh exact-head local/Hosted validation and an independent COMMENTED whole-bundle review remain required before normal product merge.

## [2026-08-10] test | Validate post-policy PR #78 integration tree

- Focused trusted-policy and OTA/NAS tests passed 115/115. Exact staged-LF full root discovery passed 175/175; all six workflows passed `actionlint`, and the OTA contract command plus `git diff --check` passed.
- Orca `Quick` passed all ten sections in 42.57 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures. Independent index checks confirmed 57/57 product blobs exact to reviewed `44b43411d5156d9a3a08ec0f94b8336c90f6bcb5`, policy files exact to new main, new-main log prefix plus one complete PR suffix, and unchanged `raw/` identity.
- Fresh exact-head Hosted Trusted/OTA/firmware/mobile checks and an independent COMMENTED whole-bundle review remain required. No merge of PR #78, workflow dispatch, NAS connection/write, physical validation, release evidence or production authorization occurred.

## [2026-08-10] compile | Rotate merged PR #78 policy to sole current-main baseline

- Removed both PR #78 transition identities and installed exactly one `persistent-baseline` named `current-main-baseline`, sourced from exact merged main `aaeeb92b105d3864454b19921eb12de45d9458c0` with the complete ordered 57-file bundle.
- Recomputed all 57 `utf8-lf-v1` digests from immutable GitHub Contents API bytes at that exact commit. Both prior transition maps match byte for byte; the three product digests remain deploy `b73646d4e4196c48763f9e3ab5f21606df145d897c767ec1a90f25e739b7a209`, mobile `a38a63f5d31516593d91cd182614198fc538ee325a7e11364e7246e29fc11a9f` and OTA gate `d41630cb61441c135aec6756d1726d96b18e944eb96ab93f1780306b5ae780fe`.
- This is a policy-only final rotation: the validator, trusted workflow, product/runtime files and `raw/` remain unchanged. No merge, workflow dispatch, NAS connection/write, deployment, physical evidence, release evidence or production authorization occurred.

## [2026-08-10] test | Validate the sole PR #78 merged-main trusted baseline

- Focused trusted-policy regression tests passed 37/37. Full root discovery passed 175/175 from the exact staged Git tree archived with checkout conversion disabled, and `actionlint` passed all six workflows.
- Orca `Quick` passed all ten sections in 41.17 seconds with doctor 12 pass, one Docker-covered native Java warning and zero failures. JSON parsing, `git diff --check`, staged log byte-prefix, `raw/` tree identity and live immutable GitHub API verification of all 57 protected files passed.
- The final policy PR still requires green exact-head Hosted Trusted and a separate independent COMMENTED whole-bundle review before normal merge. No dispatch, NAS write, deployment, physical validation, release evidence or production authorization occurred.

## [2026-08-10] test | Verify exact-main firmware and mobile NAS physical-test delivery

- Dispatched firmware run `31323665004` and mobile run `31323666311` from exact main `85568c18c136ef3c1d104026e033da789867b73e` with `release_target=physical-test-canary` and explicit `allow_unpinned_host_key=true`. Both build/test jobs and both SFTP-only NAS publish jobs completed successfully; connected and production jobs remained skipped.
- Downloaded the sanitized Actions evidence artifacts and confirmed `nas_upload_verified: true`, `host_key_mode: runtime-keyscan-unpinned`, exact source commit binding, isolated final run paths, and readback-bound artifact/manifest SHA-256 values. Firmware artifact `b76c8e98e569b40b7647db9141fbb84afcfb8bf2d09253893170549b8f7e154a` was published under run path `run-31323665004-1`; mobile artifact `8147d4f552df6420aac7d811d2a7d2accd21ce93ee83e3be4ef2efc2b972d3ef` was published under `run-31323666311-1`.
- Evidence remains deliberately non-release: `physical_validation_status: pending`, `production_authorized: false`, and `release_evidence: false`. No APK installation, ESP32-C6 flash/boot, BLE/radio, relay/ToF, OTA health/rollback, Samsung/OEM, operator acceptance or production deployment was claimed. The runtime-discovered host key leaves the documented MITM/password-interception risk.
- Updated the NAS delivery documentation regression to require the exact successful run IDs and live `nas_upload_verified: true` boundary instead of the obsolete pre-dispatch statement; the test still requires the pending physical and false production/release fields.
- Exact staged-LF root discovery passed 175/175, including the updated delivery evidence contract and all relative-link checks; `git diff --cached --check`, append-only log prefix and unchanged `raw/` identity also passed.

## [2026-08-10] code | Add fail-closed OTA signing secret bootstrap

- Added `scripts/setup_ota_signing_secrets.ps1` to generate an Ed25519 32-byte private seed and raw public key, validate the repository key formats, and register the exact three shared firmware/mobile signing values as GitHub `production` Environment Secrets through stdin without exposing the private seed in command arguments or output.
- Required the current-process `GITHUB_TOKEN`, successful `gh auth status`, a repository-external non-existing backup target, no pre-existing signing Secret names, and explicit PowerShell confirmation before mutation. The recovery record stores only a Windows DPAPI current-user encrypted private seed plus public metadata in UTF-8 without BOM; automated overwrite and key rotation fail closed.
- Added a no-write `-ValidateOnly` path, a source/runtime contract test, and operator documentation covering invocation, exact formats, DPAPI recovery limits, separate reviewed rotation, and the boundary between key registration and OTA physical/operator/release authorization.

## [2026-08-10] test | Validate OTA signing secret bootstrap

- PowerShell AST parsing and the no-write `-ValidateOnly` execution passed. The focused bootstrap contract passed 5/5, covering raw Ed25519 key shape, stdin-only secret transport, absence of persistent Windows environment writes, DPAPI backup constraints, GitHub authentication/overwrite refusal, UTF-8/LF and suppression of private seed output.
- Root discovery executed 180 tests: 179 passed directly and the sole working-copy failure was the known Windows CRLF conversion of unchanged `manuals/README.md`. Direct Git-index blob validation then passed the exact UTF-8/LF/manual baseline contract for all eight manuals; no product or bootstrap assertion failed.
- `git diff --cached --check` passed. Only the five intentional script/test/wiki paths are staged; pre-existing untracked `.codex-remote-attachments/` and `.venn/` remain untouched, and no GitHub Secret, backup file, production dispatch, NAS write or physical/release authorization was created.

## [2026-08-10] fix | Handle empty GitHub Environment secret lists on Windows PowerShell

- Reproduced the first-run failure with an exact `[]` response from `gh secret list --env production --json name`: Windows PowerShell 5 emitted the empty `System.Object[]` as a non-enumerated pipeline value, so StrictMode rejected the prior `ForEach-Object { $_.name }` access.
- Added an explicit JSON-array enumerator that accepts an empty list, validates every non-empty record has a string `name`, and is reused for both pre-registration conflict detection and post-registration name verification. `-ValidateOnly` now mutation-checks empty and single-record parser behavior before generating ephemeral key material.
- The reported failure occurred before `ShouldProcess`, key generation, encrypted backup creation or any `gh secret set` call; no partial OTA signing Secret state was created by that attempt.

## [2026-08-10] test | Verify empty-list compatibility against the live production Environment

- PowerShell AST parsing, the parser-enhanced no-write `-ValidateOnly` path and the focused bootstrap contract passed 5/5 on Windows PowerShell 5.
- Reused the operator's exact key ID and external backup path with `-WhatIf`: current-process GitHub authentication, external path validation and the live empty `production` Environment Secret list all passed before `ShouldProcess` declined mutation.
- Post-run verification confirmed the requested DPAPI backup path still does not exist and the `production` Environment still reports zero Secret names. No key, backup, Secret, workflow dispatch, NAS write or release authorization was created.

## [2026-08-10] compile | Merge OTA bootstrap and audit remaining production Secrets

- Merged PR #82 normally as merge commit `40aa3a05ab88464dc0aec7827a7a26ccc4b27d5d` after exact-head Trusted Workflow run `31389611196` passed. The merged bootstrap remains a registration tool only; no workflow dispatch, NAS write or physical/release authorization was performed by the merge.
- Live name-only GitHub inspection found 25 Repository Secrets and the three expected OTA signing names in the `production` Environment. Comparison against exact merged-main production jobs found nine missing Target firmware names and three missing mobile names; existing Secret values, URL targets and NAS directory contents remain unreadable by design and require operator verification.
- Documented the complete static firmware/mobile production Secret contract, formats, optional defaults and the required Smartbox NAS directory overrides. `NAS_TARGET_DIR` and `NAS_APK_TARGET_DIR` names already exist, but their hidden values cannot be claimed to match `/docker/smartbox_ota/firmware/` and `/docker/smartbox_ota/gatekeeper_apk/` from a name-only audit.
- The live name-set comparison reproduced the final nine/three missing counts. Four focused bootstrap tests passed directly; the sole failure was the known Windows checkout CRLF view of the unchanged merged script, whose exact Git blob separately passed UTF-8/LF/no-BOM validation. Documentation `git diff --check`, append-only log prefix and unchanged `raw/` scope passed.

## [2026-08-10] lint | Re-audit the backend deployment boundary

- Confirmed from exact merged main `40aa3a05ab88464dc0aec7827a7a26ccc4b27d5d` that `.github/workflows/backend_security.yml` performs tests, real MariaDB migration checks, image builds, SBOM/claim attestation and evidence verification only; it does not push backend images, connect to the NAS or run production Compose.
- The production path now requires separately provenance-approved digest-pinned API and DB images, external Docker secrets, a backup-first one-shot `migrate` service to schema `007`, then API admission through `/ready`. The API is read-only/non-root with no host port, the data network is internal, and a trusted mTLS reverse proxy is the only intended ingress.
- `backend/docker-compose.yml` remains the local/development path with local builds, source/SQL bind mounts and convenience defaults; it must not be used as the production NAS deployment definition. Live NAS deployment, image publication, reverse-proxy wiring, independent restore and operator evidence remain pending.

## [2026-08-12] compile | Add fail-closed personal production evidence profile

- Added a reduced single-owner profile for the owner's primary phone and already-installed entrance Target: three screen-off trials, three Activity-terminated trials, and one each for Target reboot, network reconnect, relay boot fail-safe, and previous-version recovery.
- Kept exact-main, signed artifact, post-deploy boot health, legacy access ownership, `ENABLE_HARDWARELESS_RC=0`, and all commercial production gates intact. The committed evidence file is an intentionally blocked template; no unobserved physical result or production authorization is asserted.
- Added a standalone validator and regression tests rejecting incomplete trials, commercial scope, hardwareless enablement, missing safeguards, and undated owner approval.

## [2026-08-12] test | Record owner-attested reduced physical checks

- The repository owner explicitly confirmed the six personal-profile checks passed on the primary phone and installed entrance Target: screen-off 3/3, Activity-terminated 3/3, Target reboot 1/1, network reconnect 1/1, relay boot fail-safe 1/1, and previous-version recovery 1/1.
- Recorded the attestation against current branch commit `17c54a906bfe4f2777b542763431ee29eae3ceb0`. Release remains blocked because this is not exact `main`, signed release artifact/manifest verification has not run, and post-deploy version/boot/health cannot precede deployment.
# 2026-08-12

- 개인 PROD 모바일 배포를 위해 격리 배포 브랜치에서만 보호된 Android 서명키로 APK를 생성하고, 모바일 manifest 서명·검증 후 기존 NAS 앱 업데이트 경로에 게시하는 수동 dispatch workflow를 사용한다. `main`의 OTA production release evidence gate와 trusted workflow 정책은 변경하지 않는다.
- 개인 단일 관리자 PROD에서 브라우저로 `/admin`을 사용할 수 있도록 `/admin/login` 비밀번호 bootstrap, rate limit, Secure/HttpOnly/SameSite 세션, CSRF와 fresh personal-session 재인증을 추가했다. 기존 proxy-verified mTLS 경로와 상용 역할 분리는 유지하며 모바일 제어 API 키와 관리자 비밀번호를 분리한다.

## [2026-08-12] fix | Restore personal enrollment visibility and diagnose legacy OTA

- 관리자 tenant 조회에 실제 기기 식별 열을 포함해 빈 기기 ID 표시를 수정했다.
- WebView 신청을 Flutter native API-key bridge로 연결하고 성공·실패·승인 대기 상태를 사용자에게 표시하도록 복구했다. 기존 active 기기의 재신청은 권한을 회수하지 않는다.
- 설치 Target은 `2.1.0-g75b946a`, 마지막 reset `BROWNOUT`, MQTT offline으로 확인됐다. 해당 구형 버전에는 부팅/주기 HTTPS OTA pull이 없으므로 전원 재인가만으로 업데이트되지 않으며, 최초 업데이트는 Target이 MQTT에 온라인으로 복귀한 동안 legacy OTA 명령이 필요하다.

## [2026-08-12] compile | Record personal PROD mobile and embedded Target incident

- Documented the restored authenticated mobile enrollment, approved-device door-button native bridge, signed build 141 deployment and external APK hash read-back.
- Recorded that the embedded legacy Target still runs `2.1.0-g75b946a`: BLE beacon was observed, the last real broker session authenticated and later timed out, but no new boot/online evidence followed the power cycle and no OTA command was issued.
- Distinguished the temporary duplicate `sgk-personal-prod-audit` client-ID takeover from the real Target session, confirmed zero remaining diagnostic processes, and preserved the exact next recovery and post-OTA verification boundary without secrets.

## [2026-08-12] fix | Restore trusted mobile workflow before main review

- Restored `.github/workflows/build_app.yml` byte-for-byte from current `origin/main` after the isolated personal PROD deployment completed; the temporary personal-only workflow is not proposed for main.
- Kept the reviewed admin, authenticated enrollment, approved-device Local GATT bridge and incident documentation changes in the merge candidate. Standard Trusted Workflow, OTA contract and Android canary checks must pass on the new PR head before merge.

## [2026-08-12] fix | Apply CI Dart formatting

- Applied the stable Dart formatter to `gatekeeper_app/lib/screens/web_view_screen.dart`, the only file reported by the Android canary formatting gate.
- Re-ran the repository mobile format check across `gatekeeper_app/lib` and `gatekeeper_app/test`; all 28 Dart files now require no changes.

## [2026-08-12] compile | Authorize the exact PR #85 protected bundle

- Recomputed the complete ordered 57-file `utf8-lf-v1` map from exact product commit `d754f23a1028500248edb6a7025885c256e97c8c`; eight backend/admin contract files differ from the current baseline.
- Added byte-identical `temporary-pr85-d754f23` and `future-pr85-persistent-baseline` identities so the exact product head can be admitted first and its later policy-main descendant can be admitted without widening the protected file set.
- Kept this policy-only change separate from PR #85. Product merge remains conditional on the policy merge and fresh green hosted checks; final baseline rotation remains required immediately after product merge.

## [2026-08-12] compile | Rotate PR #85 to the final trusted main baseline

- After policy PR #86 and product PR #85 passed their hosted checks and were admin-merged, removed both bounded PR #85 transition identities.
- Pinned the sole `current-main-baseline` to merged main `2d6b046b62d53381181d5c4bd8c25a9e781e42d1` with the same complete ordered 57-file digest map.
- This final policy-only rotation changes no protected product or workflow file and closes the temporary authorization window after its hosted check and merge.

## [2026-08-12] compile | Define embedded Target connectivity and remote-recovery policy

- Added a mandatory Wi-Fi STA, per-Target MQTTS and independent HTTPS OTA operating contract for Targets that cannot be physically accessed after wall installation.
- Defined 15-second warning, 90-second critical and 10-minute field-escalation boundaries, plus power, AP, broker and WAN recovery commissioning tests.
- Recorded current P0 gaps: boot-time recovery-AP STA retry proof, lost-IP TLS lifecycle proof, backend availability/status last-seen alerts and physical reconnect evidence. BLE visibility and MQTT PUBACK are explicitly insufficient evidence.

## [2026-08-12] lint | Review Obsidian multi-project wiki governance

- Reviewed the repository-native Markdown wiki, immutable `raw/` sources, navigation index and append-only log conventions as the basis for an Obsidian workspace.
- Recommended keeping each project's Git repository as its knowledge source of truth, using Obsidian as an editing and navigation layer, and separating cross-project evergreen knowledge from project-specific decisions and evidence.
- No product source, raw source, wiki page structure or index entry was changed; this entry records the governance review only.

## [2026-08-12] compile | Align project wiki with current code and promote reusable knowledge

- Added `project_status.md` to separate repository implementation, verified evidence and deployed state, including the current `406707c` source baseline and the older embedded Target deployment boundary.
- Recompiled the current code audit, architecture, OTA snapshot, README, root/IDE agent guidance and schema for AJ-SR04T GPIO10/11, GPIO3 relay, per-Target MQTTS signed commands, admin sessions, default-OFF local GATT/ACL, signed recoverable OTA and remaining physical/production Gates.
- Marked the 2026-08-08 commercial program and 2026-07-31 connectivity audit claims as historical snapshots where their admin, insecure-MQTT, OTA, GATT/FSM and relay findings have been superseded in current source, while retaining their still-pending physical and production evidence.
- Added Obsidian/LLM governance with gradual metadata adoption, standard Markdown links, personal workspace exclusions and provenance-based promotion rules; updated the personal profile status after the owner's reduced physical attestation without claiming release completion.
- Promoted only reusable wiki governance, evidence-layer, MQTT acknowledgement, OTA completion and mobile lifecycle patterns plus templates into `E:\knowledge-hub\knwlege-hub`; project-specific state remains authoritative in this repository.
- Preserved `raw/`, historical append-only log entries, unrelated untracked directories and existing user edits.

## [2026-08-23] fix | Keep Wi-Fi, MQTTS and OTA recoverable after a late boot connection

- Changed initial Wi-Fi failure handling to preserve credentials, keep the authenticated recovery AP in AP+STA mode and retry STA association every 15 seconds until connected.
- Initialized MQTTS independently of boot-time Wi-Fi success, closed stale TLS state on Wi-Fi loss and forced an immediate clean MQTTS retry when Wi-Fi returns; periodic signed HTTPS OTA continues independently after STA recovery.
- Tightened OTA pending-image health so only stable Wi-Fi STA plus MQTTS can mark the new slot valid; recovery AP alone now leads to timeout rollback.
- Added a main-only, production-environment personal-installation workflow that injects actual provisioned connectivity/recovery/signing secrets and uploads only a one-day AES-encrypted USB/OTA bundle. Commercial release evidence and NAS deployment remain unchanged.

## [2026-08-23] test | Validate connectivity recovery and personal installation packaging

- Focused Wi-Fi/MQTTS recovery and installation-workflow contracts passed 8/8; the existing OTA contract gate passed without modifying the protected commercial release workflow.
- ESP32-C6 `esp32c6` compilation succeeded in 279.79 seconds at 16.4% RAM and 21.9% flash; no physical Wi-Fi, MQTT, OTA, relay or wall-install evidence is claimed by static/build validation. The dispatched production-secret CI result is recorded after completion.

## [2026-08-23] fix | Add encrypted production secret header recovery

- GitHub secret values cannot be read back through its API, so the production job now places its generated header in the AES-encrypted one-day installation bundle as `provisioned-secrets.h`.
- Secret values remain absent from Actions logs and unencrypted artifacts; only the owner holding the local recovery password can decrypt the header.
- Secret contract diagnostics now identify only the failing field and never print its value.

## [2026-08-23] fix | Accept provisioned MQTT username as an opaque value

- Removed the personal-installation workflow's unsupported 12-character hexadecimal restriction on `SECRET_MQTT_USER`; the firmware and MQTT protocol treat the non-empty username as an opaque string.
- Retained the non-empty MQTT username/password checks and all Wi-Fi, command-signing, OTA-signing and local-recovery validation.

## [2026-08-23] fix | Correct the physical N16 build and connectivity recovery

- Explicitly propagated the 16 MB upload profile to every ESP32-C6 environment and added a dedicated production environment with one unambiguous production macro definition.
- Raised the Arduino loop-task stack to 16 KiB after the physical Target exposed a stack-protection panic during MQTTS security initialization.
- Removed STA retry races by starting AP+STA recovery once and leaving reconnectable failures to the Arduino core auto-reconnect; accepted the provisioned broker principal independently from the MAC-derived Target topic ID.
- Added credential-free station disconnect reason diagnostics for installed-network triage.
- Updated the security regression contract to preserve non-empty TLS broker credentials and the exact MAC-derived Target namespace without requiring the broker username string itself to equal that namespace.

## [2026-08-23] test | Verify N16 firmware size, flash and first boot boundary

- Built the production profile as 16 MB, verified the bootloader image header, and passed 16 focused Wi-Fi/MQTT/install tests.
- Added a reusable flash-layout gate requiring non-overlapping 16 MB partitions, equal 7 MiB OTA slots, firmware fit and at least 20 percent release headroom; the final observed image used 1,696,896 bytes (23.12 percent) with 5,643,136 bytes free in either inactive slot.
- Wrote the NVS-preserving four-image layout to the ESP32-C6 rev 0.2 Target with write-hash verification. The 16 KiB build no longer panicked or reboot-looped, and the final 45-second observation had no Wi-Fi state-race output.
- Initial Wi-Fi association repeatedly reported reason 201 (`NO_AP_FOUND`), so authentication was never reached; no DHCP, MQTTS online or OTA install-health evidence was observed. The Target remains in authenticated recovery AP plus STA auto-retry mode and is not yet approved for final wall installation.

## [2026-08-23] fix | Single-source the authenticated recovery AP identity

- Defined `SmartGatekeeper-Recovery` once as `kRecoveryApSsid` and reused it for the SoftAP broadcast, serial ready log and HTTP Basic authentication realm; removed the misleading `SmartGatekeeper-Setup` runtime log.
- Updated current architecture/connectivity documentation with the broadcast SSID while explicitly preserving `SmartGatekeeper-Setup` as the exact historical identity of the audited legacy firmware.
- Added a regression contract that rejects duplicate recovery SSID literals or a reintroduced legacy runtime label; physical association, DHCP, MQTTS and OTA evidence remain separate pending gates.

## [2026-08-23] fix | Restore recovery Wi-Fi scan and render its results visibly

- Reproduced authenticated `/scan` returning `-2` while the disconnected STA continuously retried stale credentials, then paused only that STA retry during a bounded scan and restored auto-reconnect afterward without clearing NVS or stopping the SoftAP.
- Replaced the mobile-inconsistent SSID datalist with an explicit scrollable button list showing SSID and RSSI; selecting a row fills the validated manual SSID field.
- Added credential validation/readback and focused recovery contracts; the production build and 16 MB dual-OTA capacity gate passed with a 1,699,616-byte app, 23.16 percent slot usage and 5,640,416 bytes headroom.

## [2026-08-23] test | Prove recovery scan, DHCP and MQTTS on the physical N16 Target

- App-only flashed the `21107958` plus scan-fix candidate to the ESP32-C6 rev 0.2 Target with write-hash verification while preserving NVS and the dual-OTA layout.
- Repeated authenticated scans returned 11, 13, 12, 13 and 9 AP records instead of `-2`; the phone displayed the list and saved the selected 2.4 GHz SSID.
- The rebooted Target obtained `192.168.35.19`, connected to the provisioned MQTTS broker, subscribed to exact per-Target topics and published retained boot diagnostics/config state.
- A later beacon timeout (`reason 200`) exercised runtime recovery: the Target regained the same DHCP address, recreated the MQTTS connection, resubscribed and republished diagnostics without rebooting.
- Periodic HTTPS OTA install, reboot health, rollback, power-loss and long Wi-Fi/MQTT soak evidence remain pending and are not implied by this connectivity pass.

## [2026-08-23] code | Add secure Home Assistant discovery migration

- Added a default-dry-run migration tool that preserves the existing Home Assistant device identity and updates 15 read-only sensor/binary/config sensor discovery records to secure per-Target status, config-state and availability topics.
- The explicit apply path publishes with QoS 1 and retain enabled; seven retained tombstones remove legacy plaintext button and number discovery records before any read-only update instead of recreating those controls.
- MQTT username/password and the optional TLS CA are accepted only through environment or file sources; credentialed apply requires verified TLS and values are never printed. Runtime Target IDs and broker addresses remain operator inputs and are not stored in documentation.
- Direct Home Assistant write controls remain prohibited until a separately reviewed backend bridge can authorize and sign current-boot Target command envelopes.

## [2026-08-23] test | Validate secure discovery payload and publish boundaries

- Nine focused host tests passed for the exact 15 read-only identities, secure per-Target topic mapping, seven legacy-control removals, topic-injection rejection, network-free dry-run, credential-source handling, mandatory TLS for credentialed apply and secret-free output.
- A fake MQTT client verified all 22 update/tombstone operations request QoS 1 retained publish and wait for acknowledgement without contacting a live broker.
- Root discovery ran 214 tests: 212 passed; the two failures were Windows checkout CRLF views of unchanged `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1`, while both exact Git blobs separately remained UTF-8/LF.
- No production broker mutation, retained read-back, Home Assistant registry observation, Target command, Wi-Fi/MQTTS change, OTA action or physical acceptance was performed.

## [2026-08-23] fix | Keep migrated Home Assistant status available across restarts

- Removed the discovery dependency on the Target `/availability` topic because current firmware publishes it only once per MQTT connect without retention; a migration or Home Assistant restart after that event would otherwise leave all entities unavailable.
- Added `expire_after=30` to the 11 entities backed by the 10-second periodic Target status while leaving four boot-only config-state diagnostics independent of availability.
- Live internal-broker migration of 15 read-only configs was observed in Home Assistant with firmware `2.1.0-gd06519e`, IDLE state, `192.168.35.19`, distance, RSSI and four explicitly seeded current config-state values.
- Seven legacy controls were not removed during the live observation and remain nonfunctional with the signed-command firmware; no control was invoked. The public MQTTS certificate was independently observed expired on 2026-08-14 and still requires renewal.

## [2026-08-23] test | Apply and read back secure Home Assistant discovery

- Applied the reviewed migration to the live internal broker with QoS 1 retained publication: 15 read-only discovery records were updated and seven incompatible legacy control records were tombstoned.
- A clean retained subscription read back exactly 15 Smart Gatekeeper records: 11 periodic-status entities with `expire_after=30`, four config-state diagnostics, zero availability references and zero legacy button/number configs.
- The broker accepted an anonymous LAN connection, so this migration did not transmit credentials; that permissive internal-broker policy is operational evidence, not a security approval.
- No door, relay, reboot, OTA or configuration control was invoked. Reintroducing controls remains blocked on an authenticated backend bridge that emits current-boot signed command envelopes.

## [2026-08-23] fix | Re-converge all Home Assistant values from periodic status

- Added the four current configuration values to the Target's existing 10-second per-Target status payload without changing command, ACL or signing behavior.
- Mapped all 15 read-only Home Assistant entities to that periodic status with a 30-second expiry, removing the restart dependency on both non-retained boot-only availability and config-state publications.
- Added a host contract test for the four firmware status fields and the exact all-entity status/expiry mapping. Live config convergence with this payload remains pending until the new exact-main Target OTA boots and publishes it.

## [2026-08-23] fix | Quarantine failed OTA floors and bound artifact downloads

- Rejected the exact persisted version floor when a lower stable slot is running after bootloader rollback, while preserving equal-precedence identity conflict handling and allowing only a strictly newer recovery image.
- Added a 30-second no-progress deadline and five-minute total deadline to remote artifact streaming. Timeout aborts the inactive write, records an explicit failure and returns to the existing 15-minute retry schedule.
- Preserved the existing WAIT_SAFE_STATE fail-closed return before any network request.

## [2026-08-23] test | Validate Target OTA rollback and timeout safety on the host

- Extended the native C++ version-policy suite with exact failed-floor quarantine, alternate-identity rejection and strictly newer recovery cases.
- Added static Target runtime assertions for safe-state failure handling, both download deadlines, progress tracking, inactive-write abort and retry scheduling.
- Built the default ESP32-C6 N16 profile successfully; the 1,662,160-byte app uses 22.65 percent of either 7,340,032-byte OTA slot and leaves 5,677,872 bytes headroom.
- No Target flash, OTA install, reboot health, rollback, power-loss or network-stall injection was performed; those physical evidence gates remain pending.

## [2026-08-23] code | Add exact-main personal Target OTA auto-publication

- Added a main-push-only `publish_personal_target_ota` lane after the public firmware test/build job. It uses the protected `production` Environment, exact full-history main checkout and the N16 `esp32c6_production` profile without changing or self-attesting the commercial release-evidence job.
- Replaced arbitrary Git-hash prerelease ordering with deterministic `2.1.1-main.<first-parent-count>+g<SHA>` precedence, created a production-signed manifest whose artifact URL names immutable commit bytes, and retained previous valid firmware/manifest history.
- Added bounded pinned/runtime-keyscan transport, staged byte readback, stale-run rejection and OpenSSH `posix-rename` as the single `version.json` commit point. Unsupported atomic replacement or post-scan host-key change fails with the previous pointer intact; runtime keyscan still cannot authenticate its first observation.
- Sanitized publication evidence explicitly keeps `production_authorized: false` and `release_evidence: false`. NAS publication does not prove Target download, install, reboot health, valid mark, rollback or commercial production acceptance.

## [2026-08-23] code | Add exact-main personal mobile OTA publication

- Added a separate main-push mobile job that preserves the installed app's repository-scoped Ed25519 update identity instead of allowing the Target values in the `production` Environment to shadow it.
- Pinned the existing Android package signer and package name, retained the unchanged commercial release-evidence job, and required an exact-main signed APK manifest before any NAS contact.
- Added primary and fallback SFTP staging, staged/final readback, APK-before-manifest rename and public HTTPS byte-for-byte checks, plus focused workflow contracts. No Secret value is written to source or logs.

## [2026-08-23] fix | Harden personal mobile NAS publication against interrupted pointer swaps

- Replaced workflow-owned raw SFTP renames with the shared validated mobile publisher, using immutable candidates, previous-valid-pair retention, staged and final readback, stale-pointer rejection and SFTP `posix_rename` on both primary and fallback paths.
- Serialized main-push mobile publishers with `cancel-in-progress: false` so a newer run cannot cancel an active APK-before-manifest promotion; the publisher restores the previous valid pair if manifest promotion fails.
- Kept the final primary and fallback HTTPS exact-byte fetch as the deployment completion gate and preserved sanitized publication evidence without Secret material.

## [2026-08-23] test | Validate the personal mobile publisher workflow contract

- Focused personal-mobile and NAS physical-test workflow tests passed 12/12, including exact-main triggering, repository mobile-key isolation, signer pinning, serialized publication, shared publisher arguments, sanitized evidence and all four primary/fallback HTTPS exact-byte checks.
- `actionlint`, `git diff --check` and the unchanged `raw/` tree check passed. No GitHub workflow was dispatched, no NAS bytes were changed and no APK was installed by this source-only validation.

## [2026-08-23] fix | Make automatic Target and mobile OTA publication retry-safe and host-pinned

- Superseded the earlier automatic-publisher runtime-keyscan fallback: both password-authenticated Target and mobile jobs now require the independently pinned `NAS_KNOWN_HOSTS` repository Secret and fail before credential transmission when it is absent or changed.
- Made Target identity deterministic as `2.1.<first-parent-count>+main.g<short-sha>` with a full-SHA build ID, commit timestamp and `SOURCE_DATE_EPOCH`; pinned PlatformIO, pioarduino and firmware libraries, and required two clean firmware builds to be byte-identical before signing.
- Serialized Target publication without cancellation, rejected equal identity with different signed bytes, retained immutable previous-valid history, and required the public version URL plus signed immutable artifact URL to return exact bytes after the atomic NAS pointer swap.
- Gave every mobile rerun a strictly increasing bounded Android version code derived from run number and run attempt, made retained CI artifact names attempt-specific, and protected APK promotion, both promotion readbacks and manifest promotion with previous-valid-pair rollback.
- Derived publication evidence from actual previous-pair validity instead of a constant. The commercial release-evidence command remains separate and fail-closed; a future commercial `2.2.0` or newer Target line requires an explicit personal-lane base bump rather than a silent downgrade.

## [2026-08-23] test | Revalidate integrated exact-main OTA publishers without deployment

- The protected OTA contract, `actionlint`, Python compilation, `git diff --check`, unchanged `raw/` tree check and 30 focused Target/mobile/NAS tests passed, including stale/equal-byte conflicts, Android retry identity, APK-readback rollback and the explicit post-`2.2.0` base-bump requirement.
- The full Windows checkout suite ran 231 tests: 229 passed and only the two pre-existing strict-LF checks for `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1` failed because this clone has `core.autocrlf=true`; neither file nor its Git blob was changed by this work.
- This was source-only validation. No production Secret value was read or printed, no workflow was dispatched, no NAS path was contacted or changed, no firmware/APK was installed and no commercial, physical or release evidence is claimed. The three protected workflow/gate files still require the existing exact whole-bundle trusted-policy review and rotation before merge.

## [2026-08-23] fix | Close automatic OTA bootstrap, toolchain and rerun review gaps

- Replaced an invalid mutable-tag object pin with the immutable pioarduino `55.03.39` platform commit `cbc3349061987c28bc1b48d43d473e70c5ae04ed`; PlatformIO 6.1.19 initialized it as Arduino 3.3.9 for ESP32-C6 N16 with the exact library pins. The protected contract now binds the normalized full `platformio.ini` bytes.
- Allowed the exact-main `release_target=canary` manual dispatch as well as every main push to enter both personal publishers after exact checkout SHA verification. Physical-test and commercial dispatch choices remain separate.
- Added `github.run_attempt` to every immutable Actions v4 artifact name and its paired canary download, so a workflow rerun cannot collide with a previous attempt.
- Restricted automatic Target bootstrap to a missing `version.json`; present metadata with an unverifiable schema/signature now fails before staging. The signed Target version must be embedded in firmware bytes before publication.
- Bound post-publish Target HTTPS readback to the provisioned `SECRET_ROOT_CA_CERT`, HTTPS-only redirect policy and exact manifest/artifact bytes. The commercial release-evidence gate remains unchanged and fail-closed.

## [2026-08-23] test | Bind automatic main versions to Target SemVer ordering

- Added native policy fixtures proving that `2.1.<first-parent-count>+main.g<sha>` advances numerically with the commit count and remains below a future stable `2.2.0` release.

## [2026-08-23] test | Prove pinned production build reproducibility and full LF regression

- Initialized the exact pioarduino commit as platform `55.3.39+sha.cbc3349` with Arduino 3.3.9, ESP32-C6 N16, ArduinoJson 6.21.5 and PubSubClient 2.8.0, then completed two clean `esp32c6_production` builds with example-only Secrets and one commit-derived epoch.
- Both `firmware.bin` files were byte-identical at 1,662,032 bytes with SHA-256 `7beee4d68da602bd161e3c009e81610c69d8af6aa2621a376e411564f749a42b`; the exact test version was embedded. The 7 MiB OTA slot used 22.64 percent with 5,678,000 bytes headroom.
- The LF checkout full suite passed 232/232. The ordinary Windows checkout again passed 230/232 with only the two known `core.autocrlf=true` strict-LF failures in unchanged `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1`.
- These are local example-secret build and source regression results, not production signing, NAS publication, Target installation, reboot health, rollback, physical acceptance or commercial release evidence.

## [2026-08-23] fix | Renew the live public Mosquitto certificate

- Validated the DSM-exported RSA certificate, matching private key, two-certificate chain, SAN coverage and 2026-10-19 expiry without printing private material.
- Audited the exact Mosquitto certificate paths over pinned-host-key SFTP, retained recoverable copies of the expired pair, replaced the three configured TLS files, verified remote readback and removed all three temporary GitHub certificate Secrets immediately after the one-off run.
- After the operator restarted Mosquitto, a public-trust client verified hostname, chain, TLS 1.3 and certificate SHA-256 `f2c90a2b4a8b3181bb0ae6863618a0101139593ff55105518726a10c78a94e23` on port 4883.

## [2026-08-23] test | Verify authenticated MQTTS and Target recovery after renewal

- An authenticated MQTT 3.1.1 client received successful CONNACK and SUBACK for the exact per-Target status topic over the renewed verified TLS endpoint.
- Target `c0feffe6ebac` published a current periodic status with boot ID `c2f1ce127f0d5a3a296bb781319dc904`, IDLE state and IP `192.168.35.19`, proving one broker-restart reconnect path.
- Automatic certificate renewal/alerting, long outage soak, OTA install/reboot health/rollback, relay safety and final wall-install acceptance remain separate pending gates.

## [2026-08-23] compile | Document automatic OTA authorization and supply-chain locks

- Documented the exact-main, no-review `personal-auto-ota` Environment for the personal Target publisher while retaining the main-only, required-reviewer `production` Environment for commercial Target/mobile releases.
- Recorded only Environment and repository Secret names and their scopes, never values; the personal mobile publisher remains Environment-free so Target signing values cannot shadow the installed app's trust identity.
- Recorded full-SHA Actions, the versioned runner label, exact Python/Flutter/Java/Android tool versions, both Gradle distribution checksums and hash-complete transitive `ota/requirements.lock` installation with `pip --require-hashes`.
- Documented the all-roots mobile preflight and signed version-code floor: unverifiable metadata, orphan APKs, stale candidates and equal-floor damaged pairs fail closed before NAS mutation.
- Reaffirmed that CI SFTP/HTTPS publication is transport evidence, not Android installation or Target install, reboot-health, valid-mark, rollback or physical acceptance evidence.

## [2026-08-23] lint | Verify automatic OTA documentation against the integrated contract

- Passed the OTA supply-chain lock suite (3), mobile publication engine suite (11), Target auto-publication suite (12) and `ota_contract_gate.py contract` without contacting GitHub or NAS.
- Passed scoped whitespace checks and relative Markdown link resolution for the three updated reference pages; the `wiki/log.md` diff contains additions at end-of-file only.

## [2026-08-24] code | Encrypt personal Target artifacts across CI and public NAS

- Split the exact-main Target lane into a mode/SHA-256-pinned privileged compiler and an isolated publisher connected only by a one-day X25519/HKDF/AES-GCM authenticated handoff.
- Added schema-v2 `SGKOTA2` AES-256-GCM content envelopes with a dedicated key ID, signed ciphertext/plaintext metadata, deterministic rerun-safe nonce derivation and one streaming Target decrypt/write path for HTTPS and local recovery.
- Removed plaintext firmware before public Actions/NAS publication, retained inactive-slot/NVS failure preservation and explicitly disabled the legacy commercial Target plaintext publisher pending encrypted-v2 migration.
- Added `scripts/setup_ota_content_key.ps1` for no-overwrite Windows DPAPI backup, GitHub stdin registration and ignored local `include/secrets.h` provisioning.

## [2026-08-24] fix | Isolate and pin personal Android OTA signing

- Moved the signing publisher behind the main-only `personal-auto-ota` Environment and separated its installed-app identity into `MOBILE_OTA_SIGNING_*` names so Target keys cannot shadow it.
- Required one regular bounded unsigned APK and stable pre-sign SHA-256, downloaded official Temurin/Android archives by fixed URL, byte size and SHA-256, rejected unsafe archive paths and invoked the pinned `apksigner.jar` with the pinned Java runtime.
- Scoped keystore, manifest-signing, NAS-host, NAS-publish and HTTPS-readback Secrets to only the steps that require them.
- Recovered the existing mobile Ed25519 seed from its Windows DPAPI backup, recomputed and matched the pinned public identity, then registered the three mobile-specific Environment Secret names through `gh` stdin without printing their values.

## [2026-08-24] fix | Close privileged compiler dependency and worktree trust gaps

- Added `ota/requirements.lock` directly to trusted-policy v3 and bound the Target compiler inventory to exact lock, `platformio.ini`, N16 partition and all tracked `src/`/`include/` bytes.
- Replaced Git-blob-only verification with actual post-install worktree SHA-256, regular-file, non-symlink and mode checks immediately before Secret materialization; untracked build inputs and a pre-existing project `.pio` directory fail closed.
- Independent review confirmed the two pre-merge P0 findings were closed, conditional on merging the trusted-policy transition before the feature authorization.

## [2026-08-24] test | Revalidate encrypted Target and isolated mobile OTA contracts

- `ota_contract_gate.py contract`, all workflow `actionlint` checks, `git diff --check` and the focused Target/mobile publisher suites passed after the trust-gap fixes.
- Target runtime/envelope, manual encrypted bundle and content-key setup tests passed; the current production build artifact is 1,703,472 bytes, uses 23.21 percent of either 7 MiB OTA slot and leaves 5,636,560 bytes headroom.
- These results are source/build evidence only. Main CI NAS readback, Target USB bootstrap, second-release OTA install/reboot/health, Android install and final Home Assistant convergence remain pending at this point.

## [2026-08-24] compile | Synchronize encrypted OTA and mobile deployment operations

- Documented the compiler-to-publisher handoff, public content envelope, schema-v1 USB migration, content-key rotation boundary, mobile-specific Environment Secret names and official Android tool archive pins.
- Corrected the commercial boundary: mobile remains reviewer/evidence gated while the legacy Target commercial publisher is disabled until it is migrated to encrypted schema v2.

## [2026-08-24] fix | Clear the Android release analyzer gate

- Awaited the asynchronous Ed25519 verification result inside the signed-update manifest verifier so the release source passes Dart's `return_of_invalid_type_from_catch_error` analyzer rule without changing signature semantics.
- Re-ran all 271 repository unit and contract tests, the OTA contract gate, every workflow through `actionlint` and whitespace validation successfully; local Flutter was unavailable after the container restart, so the exact Flutter analyzer/build remains a CI gate.
- Merged trusted-policy PR #95 only after its required policy gate, OTA contract and real ESP32-C6 firmware canary passed; the unrelated pre-existing Android analyzer failure is fixed in this feature branch.
## [2026-08-24] fix | Protect the complete workflow and local-action inventories

- Upgraded the trusted-base policy engine to format version 3 with exact inventories for all seven current `.github/workflows/` files and the currently empty `.github/actions/` namespace; every inventoried workflow and the base validator are protected normalized-digest inputs.
- Bound a recursive Git Trees API read to the immutable candidate SHA and reject truncated or malformed trees, namespace case variants, added/removed/renamed files, executable or symlink blobs, gitlinks, and every protected file that is not an exact `100644 blob`.
- Preserved the existing exact-source and persistent-baseline ancestry modes. The candidate policy still governs later PRs only after merge, and a repository-local required-check context does not independently close self-policy or same-context producer circularity.

## [2026-08-24] test | Verify trusted namespace inventory fail-closed behavior

- The focused trusted-policy suite passed 41/41, including exact current filesystem inventory/digests, Git tree SHA binding, truncated/malformed response rejection, workflow/action additions, removals, renames, case escape, executable blobs, symlinks, gitlinks, source identity, ancestry and complete-bundle checks.
- A live read-only GitHub Trees API request against main commit `d06519e2ff9bc372e1df9a57a272953d0fc2f916` returned `truncated=false` and `100644/blob` for the protected deploy workflow; no candidate code was checked out or executed.
- Python syntax/JSON parsing and `git diff --check` passed. No commit, push, policy merge, branch-protection mutation or deployment was performed.

## [2026-08-24] fix | Directly protect the publisher dependency lock

- Added the publisher-installed `ota/requirements.lock` as the 62nd version-3 protected path with normalized SHA-256 `5b8c5859426a7febd6bd9d9b0482bf78f8f4854c2d83d0ce53ba49c14c5cea12`; its complete hashed content is now an explicit bundle input rather than relying only on an indirect gate assertion.
- Added a dedicated regression that rejects both dropping the lock from the current baseline and changing its digest. The focused trusted-policy suite passed 42/42, all 62 protected working-tree digests matched the policy, Python syntax passed and `git diff --check` remained clean.
- The lock was reproduced byte-for-byte from the integration candidate without modifying that clone. No dependencies were installed, no publisher or secret-bearing job ran, and no commit, push, merge or deployment was performed.

## [2026-08-24] compile | Authorize the exact encrypted automatic OTA bundle

- Replaced the historical persistent authorization with one temporary-exact and one future persistent identity for reviewed feature commit `3bf205aeeb87efccddcd7d0db0ffd421d225f8da`; both identities bind the same complete 62-file normalized digest map.
- Verified through the GitHub API that the pushed candidate descends from PR #95 main, contains exactly seven workflow files and no local Action files, and exposes every protected path as a regular `100644 blob`; the remote trusted-policy verifier selected only the exact temporary identity.
- Compared with PR #95, exactly eight protected files change: six workflows, `scripts/ota_contract_gate.py`, and `ota/requirements.txt`. The focused version-3 transition suite passed 42/42.
- This policy-only authorization neither reads production Secrets nor publishes firmware/APKs, writes NAS state, installs software, reboots a Target, or claims health, rollback, Home Assistant, physical, or commercial evidence.

## [2026-08-24] fix | Install exact Android tools before public canary metadata

- The hosted PR canary reached APK creation but failed before metadata because the runner did not expose cmdline-tools 12.0 at the exact path required by the verifier.
- Added a secret-free preflight that installs exact `build-tools;36.0.0` and `cmdline-tools;12.0` packages and confirms both inspection executables before tests/build; the personal signing publisher still uses independently size/SHA-256-pinned official archives.
- Extended the protected OTA contract and mutation suite so replacing the canary package version with a mutable alias fails closed. This source fix requires a fresh complete-bundle authorization before merge.

## [2026-08-24] fix | Re-authorize the exact Android canary tool preflight

- A hosted run proved analyzer, Flutter tests, native GATT tests and APK build passed but metadata could not find cmdline-tools 12.0 at the exact expected runner path.
- Replaced both transition identities with revised feature commit `a643a7ec42a07de78103872c17cf15be2d5f75cd`; its complete 62-file maps are identical to each other and differ from the first authorization only for `build_app.yml` and `scripts/ota_contract_gate.py`.
- Remote GitHub content/tree verification selected the revised temporary identity with all 62 regular blobs, seven workflow files and zero local Action files. No Secret, NAS, install, Target reboot, Home Assistant, physical or commercial action was performed by this policy-only change.

## [2026-08-24] compile | Rotate automatic OTA policy to final merged-main baseline

- PR #99 merged the encrypted OTA base as `81985553ed4f4118e060801ca07e1288f4078a8f`; PR #100 merged the exact `a643a7e` authorization as `6a895c818dcfe94ee8fe81f5de5b4129dcb6295f`; PR #101 retained that ancestry and merged as `7be74b4261dded2c8a9a2e9bb9f6438f61adac6d` after fresh Trusted, OTA, firmware and complete Android canary checks passed.
- Removed both transition identities and pinned the sole `current-main-baseline` persistent identity to the actual PR #101 merge commit with the unchanged ordered 62-file map, seven-workflow inventory and empty local-Action inventory.
- Verified that the reviewed `a643a7e` source and policy-connected `01ef2264` candidate are ancestors of the merge and that all 62 protected bytes are unchanged. This policy rotation is not Target installation, reboot-health, rollback, Home Assistant, physical, or commercial-release evidence.
- The focused final-policy suite passed 42/42; JSON parsing, `actionlint`, whitespace checks and the live GitHub 62-file verifier passed with `current-main-baseline` selected for exact H2.

## [2026-08-24] test | Bootstrap exact-main Target and verify live connectivity

- Verified Target Actions run `32655789147` and its public NAS readback for exact main `9e9114b7ddc93e54adab1230341a3bc520b1aa68`, version `2.1.233+main.g9e9114b`; authenticated decryption produced a valid 1,703,392-byte ESP32-C6 N16 application with 5,636,640 bytes of slot headroom.
- Backed up the partition table, NVS, OTA data and both app headers, then wrote only app0 at `0x10000` without erasing or modifying NVS, OTA data or the valid app1 fallback; esptool verified the written-data hash.
- The first boot restored the saved Wi-Fi, received `192.168.35.19`, connected MQTTS, subscribed to exact per-Target topics and published diagnostics/config. Authenticated same-LAN recovery UI and `/scan` returned 13 visible networks with a rendered selectable list.
- Home Assistant refreshed to the exact firmware, IP, IDLE/closed state and current sensor/config values. Seven historical control registry entries remain visible and were not invoked; signed backend bridge and registry cleanup remain pending.
- This is USB bootstrap and live connectivity evidence, not periodic inactive-slot OTA, health-valid, rollback, relay/sensor, outage soak or final wall-install acceptance.

## [2026-08-24] fix | Rotate Target content-encryption key after bootstrap

- Rotated `SECRET_OTA_CONTENT_KEY_HEX` and its key ID through stdin in both GitHub `personal-auto-ota` and `production` Environments and synchronized the ignored local headers without printing or committing the value.
- The new identity is `personal-target-content-20260824-2`. Because the running image contains the prior key, the first release with this identity requires an NVS-preserving USB bootstrap; the next main release will be the encrypted periodic HTTPS install/reboot/health proof.

## [2026-08-24] fix | Correct rotated Target key identity without rewriting history

- Corrected the operational record: the content-key material was rotated, but the exact workflow contract required the policy-pinned ID `personal-target-content-20260824-1`; the preceding append-only entry's `-2` label is superseded by this correction.
- GitHub `personal-auto-ota`, GitHub `production` and the ignored local headers were synchronized to that ID without printing or committing key material. Exact firmware commit and signed manifest binding are required to distinguish the material epochs because the ID remained unchanged.

## [2026-08-24] test | Bootstrap rotated-key H4 and verify automatic network recovery

- Target run `32657300554`, attempt 2, published exact main `3927a978a8727eac086e88d20bfaa2d414908dbc` as `2.1.234+main.g3927a97`; signed encrypted NAS publication and public HTTPS exact-byte readback passed.
- Authenticated local verification bound the 1,703,428-byte encrypted SHA-256 `45ff37d858d5fb38a4f2aa397e5809e66be7b42be9cc1b10d97fe32acd18da7f` to a valid 1,703,392-byte ESP32-C6 N16 plaintext SHA-256 `8910bc7cfeef47713c5be57fbc4ab72d379b7435f84949ec49181a4e769dfbcb`, with 5,636,640 bytes of slot headroom.
- Wrote only H4 app0 at `0x10000`, preserving NVS, OTA data, bootloader, partition table and app1. The first STA attempt timed out; recovery AP+STA then obtained `192.168.35.19` without credential entry or physical intervention and MQTTS recovered about five seconds later with exact per-Target subscriptions and diagnostics/config publication.
- Home Assistant live entities converged to H4, IDLE/closed and current diagnostics/config. Its device-card metadata header and seven legacy controls remained stale; RSSI was about -84 dBm.
- This H4 operation is the required rotated-key USB bootstrap, not inactive-slot OTA. The strictly newer main produced by this documentation change is reserved for encrypted periodic HTTPS app1 install, reboot and health-valid verification.

## [2026-08-24] test | Diagnose H5 encrypted OTA manifest rejection on the physical Target

- Target run `32658670039` published exact main `6517caa957dcf1c42ece49d15e38a428c81262e5` as `2.1.235+main.g6517caa`; NAS/public exact-byte readback and independent local Ed25519, AES-256-GCM, ciphertext/plaintext SHA-256 and ESP32-C6 N16 image checks passed.
- H4 did not reboot during the periodic check window. Posting the same exact signed H5 manifest through authenticated same-LAN recovery returned HTTP 400 before artifact transfer, upload or inactive `app1` write.
- H4 remained online with Wi-Fi/MQTTS/status service and its existing slots/NVS were preserved. This is a fail-closed manifest rejection and failed H5 install, not OTA completion or health-valid evidence.
- The failure boundary was H4's PSA PureEdDSA provider: the identifier was present in headers, but the actual ESP32-C6 Arduino/ESP-IDF Mbed TLS configuration did not provide that algorithm at runtime.

## [2026-08-24] fix | Move Target manifest verification to bundled libsodium

- Replaced the unavailable PSA PureEdDSA runtime path with bundled Espressif libsodium initialization and detached Ed25519 verification, retaining exact 32-byte public-key and 64-byte signature contracts and fail-closed behavior.
- Added safe stage-specific OTA diagnostics so periodic and authenticated local manifest rejection can be distinguished without logging Secret material or signature contents.
- The H6 candidate currently has source, host-test and ESP32-C6 build/capacity evidence only. An exact merged-main physical run must still prove manifest acceptance, inactive-slot write, reboot, expected version/new boot ID, health-valid marking, rollback and power-loss recovery.

## [2026-08-24] lint | Validate H5 failure and H6 correction documentation

- Resolved all relative Markdown links across `wiki/`, confirmed `wiki/log.md` contains end-of-file additions only and passed scoped `git diff --check` for the five updated pages.
- No new wiki page was added, so `wiki/index.md` required no navigation change. No physical H6 result, production approval or closed OTA Gate is asserted.

## [2026-08-24] compile | Clarify the one-time H6 USB bootstrap boundary

- H4 cannot authenticate even a corrective signed successor because the unavailable PSA provider is itself inside H4, so exact merged-main H6 must be installed app-only over USB while preserving NVS, OTA data and the fallback slot.
- Physical OTA completion then requires a strictly newer H7 to be accepted by H6, written to the inactive slot, rebooted, observed under a new boot ID and marked valid after the continuous health window.

## [2026-08-24] test | Validate the H6 runtime verifier candidate and protected build inputs

- The default ESP32-C6 production profile compiled with bundled libsodium linked into the ELF. The 1,795,312-byte image identifies as ESP32-C6 with 16 MB flash, DIO at 80 MHz, valid checksum/hash and 5,544,720 bytes of headroom in either 7,340,032-byte OTA slot.
- All 277 repository tests passed before updating the protected compiler input digest. Focused Target security/autopublish tests, `actionlint`, the OTA contract and `git diff --check` passed after the update; the trusted-policy working-tree digest test is expected to remain red only until the separate exact-feature authorization is merged and connected.
- Updated the privileged `EXPECTED_BUILD_TREE` pins for `OtaManager.cpp` and `WifiManager.cpp`; the ignored local production `include/secrets.h` remains untracked and no Secret value was printed or staged.

## [2026-08-24] compile | Authorize exact OTA Ed25519 runtime fix

- Replaced the historical persistent authorization with one temporary-exact and one future persistent identity for reviewed feature commit `d4a3da40b4b6772bb1edcd4583eeb59951d6e7f6`; both identities bind the same complete 62-file normalized digest map.
- Verified that `deploy.yml` is the only protected change from H5 main, with normalized SHA-256 `f8bb1ce2bd89ef8a81d7062aeda843dee2376c19546db0b2e9cb80f0df172bb1`; all seven workflow entries are regular `100644 blob` objects and the local-Action inventory remains empty.
- The live GitHub content/tree verifier selected `temporary-ota-ed25519-d4a3da4` for the exact feature SHA. The focused transition suite passed 42/42; full discovery ran 277 tests with 275 passing and only the two pre-existing Windows materialization CRLF checks failing for unchanged `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1`, whose staged Git entries remain LF and whose strict-LF tests both passed in a `core.autocrlf=false` clone. The OTA contract, all seven workflow actionlint checks and whitespace validation passed.
- This policy-only authorization reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no health-valid, rollback, Home Assistant, relay, physical, or commercial evidence.

## [2026-08-24] compile | Rotate OTA Ed25519 policy to merged-main baseline

- PR #106 merged the exact `d4a3da4` authorization as `1088dcfb9afcc13d6a8408b5c1a5e6ff373072ff`; policy-connected feature head `81a42cf0b57e1830f27a5e88b5d2d15c8d33f451` retained both histories, and PR #105 merge-commit merged it as `02090c31b6813d6d1691262809dfc86330283a9d` after its required checks passed.
- Removed both transition identities and pinned the sole `current-main-baseline` persistent identity to the actual PR #105 merge commit with the unchanged ordered 62-file map, seven-workflow inventory and empty local-Action inventory.
- Verified that the reviewed feature and policy-connected head are ancestors of merged main and that all 62 protected Git blobs are identical across all three commits. The live GitHub verifier selected `current-main-baseline` for exact merged main.
- The focused final-policy suite passed 42/42; the OTA contract, all seven workflow actionlint checks, JSON/Python parsing and whitespace validation passed. Full Windows discovery ran 277 tests with 275 passing and only the two unchanged checkout-CRLF checks failing; fresh `core.autocrlf=false` M2 checkout suites passed 14/14 manual-contract and 5/5 signing-script tests.
- This policy-only rotation reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no health-valid, rollback, Home Assistant, relay, physical, or commercial evidence.

## [2026-08-24] fix | Bound and accelerate automatic mobile NAS publication

- Exact-main H7 Actions run `32662983256`, job `97253774613` entered `Atomically publish and read back primary and fallback mobile OTA` at `20:14:03Z` and was manually cancelled at `20:45:01Z` after 30 minutes 58 seconds; publication evidence and public HTTPS verification were skipped, so this run is not successful NAS delivery evidence.
- The publisher repeatedly transferred the 55,770,265-byte APK across both roots through preflight, staging, immutable history, race and promotion readbacks while whole-file Paramiko reads had no prefetch and the SFTP channel/job had no bounded wait. This confirmed transfer-amplification path is sufficient to explain the observed silent stall; cancellation logs do not identify the exact final SFTP call.
- Added a 220 MiB remote-object bound, 64-request SFTP prefetch, 120-second channel idle timeout, flushed phase progress and a 30-minute publisher-job ceiling. Reused exact-root-bound preflight state, skipped unchanged fixed-APK race rereads and avoided re-uploading an already verified previous immutable pair.
- Preserved both-root signed version-code preflight, immutable conflict rejection, staged and promoted exact-byte readbacks, APK-before-manifest atomic promotion, previous-pair rollback, independent primary/fallback publication and final HTTPS comparison. No signing, NAS or application secret value was read or recorded.

## [2026-08-24] test | Regress bounded mobile SFTP behavior

- Added regression coverage for exact-size 64-request prefetch, oversized-object refusal before open, preflight-state reuse and the reduced fixed-APK read count. Existing stale/equal-floor rejection, invalid-pair repair, immutable history, promotion/readback rollback and protected workflow mutation tests remain required.
- Focused mobile publisher tests passed 29/29, the OTA contract and all seven workflow `actionlint` checks passed, relative wiki links resolved, and `git diff --check` found no whitespace error. Full Windows discovery ran 281 tests with 277 passing; the two modified protected-path digest checks remain intentionally red pending separate exact policy authorization, while the other two failures are the unchanged checkout-CRLF checks for `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1`.
## [2026-08-24] test | Bootstrap H6 and isolate the H7 inactive-slot failure

- Installed exact main H6 `02090c31b6813d6d1691262809dfc86330283a9d`, version `2.1.237+main.g02090c3`, app-only over USB without erasing NVS; saved Wi-Fi recovered `192.168.35.19`, verified MQTTS authenticated and exact per-Target subscriptions/diagnostics returned.
- Verified Target run `32662983244` exact H7 `e00ebe84dbd7a4c9323b21e393429c9d44f4cdb3`, version `2.1.238+main.ge00ebe8`, through NAS latest/immutable equality, Ed25519, AES-256-GCM, ciphertext/plaintext hash, ESP32-C6 N16 image and 5,544,784-byte slot headroom.
- H6 accepted the H7 manifest and downloaded the encrypted artifact on three boots, but every attempt failed closed at image write/hash before boot selection. Active H6 and NVS remained usable; MQTTS reconnected after each abort.
- Full and prefix `app1` readbacks from two attempts matched expected H7 plaintext through offset 3804 and first differed at offset 3805 (`mod 16 = 13`). The failed full-slot SHA-256 was `ffa311011453f871bca9e85468416c890b337e7acc5f37a1f1a4416f842ccfeb` versus expected `fc939b690f0418a917172393abb35ba769910b8e5b540c93884053df5e9b9b4e`.

## [2026-08-24] fix | Align ESP32-C6 encrypted OTA GCM updates

- Confirmed the pinned ESP-IDF 5.5.4 GCM ALT loses CTR residual and partial GHASH state across a non-16-byte multipart update; modeling its exact `3841 + 437×4096 + 1491` transport sequence reproduced every byte of the failed physical `app1` readback.
- Added a 0..15-byte ciphertext carry so every non-final GCM update uses complete 16-byte blocks in bounded 4,096-byte slices, with a single optional final partial update immediately before authenticated finish.
- Added compile-time block alignment, finish-time carry modulo, safe GCM/SHA/inactive-write/finalize diagnostics and a regression for the exact physical chunk sequence. Periodic HTTPS and authenticated local upload continue to share one fail-closed engine.
- Current H6 cannot consume the correction through either affected encrypted path, so one NVS-preserving app-only USB bootstrap followed by a strictly newer periodic HTTPS install/reboot/health-valid observation remains required.

## [2026-08-24] test | Install exact H7 Android artifact and audit Home Assistant state

- Independently verified H7 Android package `com.kshouse.gatekeeper_app`, version `1.0.0-ge00ebe8`, build `16001`, manifest Ed25519, APK v2/v3 signatures and expected certificate, then installed it on the connected SM-F966N/Android 16 device.
- Cold launch completed with `MainActivity` top-resumed, a live process and no filtered fatal exception. Pulled installed `base.apk` was byte-identical to the 55,770,265-byte Actions artifact, SHA-256 `1e60e0cb878aab7f176807de2fb7284b653fd704cbef8c49e9dbcf71a281beae`.
- Home Assistant currently exposes 15 live read-only entities plus six restored/unavailable legacy plaintext controls; broker retained discovery is empty. A default-dry-run migration reports 15 secure discovery updates and seven legacy tombstones, but no retained mutation was made before Target OTA health evidence.
## [2026-08-24] compile | Authorize exact ESP32-C6 GCM alignment fix

- Replaced the historical persistent authorization with one temporary-exact and one future persistent identity for reviewed feature commit `e6b1b323955d81b1b2741cf021247729574ce6af`; both identities bind the same complete ordered 62-file normalized digest map.
- Verified that `deploy.yml` is the only protected change from H7 main, with normalized SHA-256 `f6245ce4f8b4c78ebd0e312d216233ee5cd8bbd188f0deb6a0fbedeee18b85ac`; the remote recursive tree is untruncated, all protected entries are regular `100644 blob` objects, exactly seven workflows are present and the local-Action inventory remains empty.
- The live GitHub verifier selected `temporary-ota-gcm-e6b1b323` for the exact feature SHA. The focused transition suite passed 42/42, full discovery passed 277/277, and JSON/Python parsing, the OTA contract, all seven workflow `actionlint` checks and whitespace validation passed in the LF clean clone.
- This policy-only authorization reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no health-valid, rollback, Home Assistant, relay, physical, or commercial evidence.

## [2026-08-24] compile | Authorize bounded Android NAS publisher

- Replaced both GCM transition identities with one temporary-exact and one future persistent identity for combined mobile candidate `b3ebcc8329c327731286f70f54ef05fb432120cf`; both identities retain the GCM-corrected `deploy.yml` and bind the same complete ordered 62-file normalized digest map.
- Rejected the initial H7-based mobile commit because it would have reverted the protected GCM build pin, then verified the combined commit's two parents are reviewed mobile `597cc13201b16af6f78a7206bd750476c16a5886` and current main `9556981704226051e07918ac4b83bb9b50273ee1`. Only `build_app.yml` (`b581543a03e32e6a641a7b7cefd7050ec2467d110b608f34fb31f54aad5dafec`) and `scripts/ota_contract_gate.py` (`634d8542da17838ded1a3e6e75f5e7f94113f2e3bc0a2d47aaa05bd28b780437`) change in the protected map.
- The remote recursive tree is untruncated with 62 regular protected blobs, seven workflows and zero local Actions; the live verifier selected `temporary-mobile-nas-b3ebcc83`. The focused transition suite passed 42/42, full discovery passed 278/278, and JSON/Python parsing, the OTA contract, all seven workflow `actionlint` checks and whitespace validation passed in the LF clean clone.
- This policy-only authorization reads no production Secret, publishes no APK, writes no NAS state, installs no app, and claims no Target OTA, Android install, reboot-health, Home Assistant, relay, physical, or commercial evidence.

## [2026-08-24] compile | Authorize ESP32-C6 weak-link Wi-Fi recovery

- Replaced the completed mobile transition identities with one temporary-exact and one future persistent identity for reviewed PR #112 commit `40929cda90c40afbb70d49760a7ec06ab657dc25`; both identities bind the same complete ordered 62-file normalized digest map.
- Verified that `deploy.yml` is the only protected change from current main, with normalized SHA-256 `91d8152784e12e86c9f3ecad75e3e6c646d3a42511526c66081d1f74be50068d`; it pins the reviewed LF `WifiManager.cpp` input at SHA-256 `e5c32190a302b8e934e18dfdf1eb21771044cea2ce6ec82571b4fc77b5e18571`.
- The pre-authorization PR #112 Hosted Trusted, OTA and firmware checks correctly fail closed on that new protected digest; connectivity regression tests pass, but no earlier canary is treated as production publication evidence.
- The focused transition suite passed 42/42; JSON parsing, exact two-map equality, the OTA contract, all seven workflow `actionlint` checks, live GitHub exact-candidate verification and whitespace validation passed. Full Windows discovery passed 280/282; only the unchanged checkout-CRLF checks for `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1` failed.
- This policy-only authorization reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no health-valid, rollback, Home Assistant, relay, physical, or commercial evidence.

## [2026-08-24] test | Verify exact H10-H11 Target OTA and isolate weak home RF

- Verified exact H10 and H11 Target CI/NAS artifacts, signatures, authenticated decryption, ESP32-C6 N16 image structure and 5,543,952-byte per-slot headroom; H11 is the observed running image.
- On a nearby 2.4 GHz AP, the Target completed Wi-Fi, per-Target MQTTS, encrypted signed H10 install/reboot and H11 current-version checks. The intended home AP remained around -80 to -82 dBm and failed association despite independently verified credentials, isolating the wall blocker to RF margin.
- Applied and independently read back 15 retained read-only Home Assistant discovery configs plus seven legacy tombstones. Live H11 telemetry recovered; restored/unavailable historical controls remain fail-closed pending registry cleanup and a signed-command bridge.
- No pending-health/valid-mark log was observed, so install/reboot evidence does not close Target health-valid or rollback Gates.

## [2026-08-24] fix | Add dynamic weak-link STA compatibility profile

- Added all-channel scan with strongest-signal selection, no modem sleep and STA-only 802.11b/g/n compatibility before the sole `WiFi.begin()` call. BSSID/channel pinning, repeat `begin()`, credential erase and recovery-AP changes remain prohibited.
- Added named disconnect diagnostics and contract tests for call order, STA-only scope, dynamic AP selection, one-begin recovery and degraded-profile fallback.
- This code can improve marginal association compatibility but cannot replace the installation policy's -75 dBm minimum and -67 dBm preferred RF targets; exact merged-main physical A/B remains required.
- The local production profile built a valid 1,799,008-byte ESP32-C6 16 MB/DIO/80 MHz image with 5,541,024 bytes remaining in either 7,340,032-byte OTA slot; the OTA contract and 283 relevant repository tests passed, while two unchanged Windows checkout CRLF tests remained the known materialization-only failures.
- Updated the privileged Target compiler inventory and its regression to the exact LF Git-blob SHA-256 of the revised `WifiManager.cpp`; production Secret materialization and NAS publication remain blocked until the separately reviewed trusted-policy authorization accepts this protected workflow byte.

## [2026-08-24] compile | Connect weak-link feature to trusted policy main

- Merged policy main `d7ec44a99a9380d8e9a1b05cf8040af6f750f999` into the weak-link feature without rebasing or squashing; resolved only the append-only log by retaining both histories.
- Recomputed all 62 normalized protected-file digests against the two identical policy maps and retained exactly seven workflows with zero local Actions. The OTA contract and all workflow `actionlint` checks passed.
- Full merged-tree Windows discovery passed 283/285; only the unchanged checkout-CRLF checks for `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1` failed. Production publication remains gated on fresh hosted checks after push.

## [2026-08-24] compile | Rotate weak-link policy to merged-main baseline

- PR #113 merged the exact `40929cda90c40afbb70d49760a7ec06ab657dc25` authorization as `d7ec44a99a9380d8e9a1b05cf8040af6f750f999`; policy-connected feature head `31bd065ee4e8c1ae2b6abb580e66d2a1d906a656` retained both histories, and PR #112 merge-commit merged it as `78bc231a4b2b429483332ed0bf124289de5276b1`.
- Removed both weak-link transition identities and pinned the sole `current-main-baseline` persistent identity to the actual PR #112 merge commit with the unchanged ordered 62-file map, seven-workflow inventory and empty local-Action inventory. The reviewed feature source is now explicitly retired.
- Verified 186 protected-object comparisons across the reviewed feature, policy-connected head and merged main: all 62 Git objects are identical at all three commits and remain regular `100644 blob` entries. The final policy also matches every locally materialized normalized protected digest, including `deploy.yml`.
- The focused final-policy suite passed 42/42; JSON parsing, the OTA contract, all seven workflow `actionlint` checks and whitespace validation passed. Full Windows discovery ran 285 tests with 283 passing and only the two unchanged checkout-CRLF checks failing for `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1`.
- This policy-only rotation reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no health-valid, rollback, Home Assistant, relay, physical, or commercial evidence.

## [2026-08-24] fix | Stabilize recovery AP with bounded STA radio arbitration

- Based on exact `origin/main` `380d013e819cd013c17253161d664cc69c6e7402`, replaced unbounded Arduino STA auto-reconnect beside `SmartGatekeeper-Recovery` with a pure timing policy: 30-second discovery quiet, one 10-second STA attempt, and full quiet restart after failure or local interruption.
- Authenticated HTTP activity immediately pauses an in-flight attempt; scan, credential save, signed local manifest and firmware upload use bounded operation leases, with each upload chunk renewing the lease. `/scan` no longer restarts STA immediately after responding, and the portal/scan responses prohibit cache reuse while retaining the explicit list and manual SSID fallback.
- Bounded an idle associated AP client to 10 minutes. Expiry deauthenticates idle clients, provides a fresh quiet interval, then pairs deauthentication with one forced bounded STA attempt even if Android continually reassociates. Raw idle association alone is ignored only during that forced attempt; authenticated activity or active local OTA still interrupts it immediately.
- Preserved Wi-Fi credentials/NVS, the authenticated 10-minute operator AP+STA window, signed local OTA, dual-slot health/rollback and normal MQTTS/periodic HTTPS paths. All AP-to-STA success/expiry/failure exits restore continuous STA auto-reconnect, and timed-window deadline zero is canonicalized safely across `millis()` wrap.
- Moved the active-operation lease check ahead of operator-window AP closure. A signed local upload that crosses the 10-minute boundary receives only a wrap-safe 30-second lease extension renewed by upload chunks; a stalled upload, unauthenticated request, or idle association cannot extend the window indefinitely.

## [2026-08-24] test | Verify recovery radio transitions, build and capacity

- Added native C++ timing/transition coverage for boot quiet, blockers, attempt timeout/failure, request interruption, persistent stale-client reassociation before and during the forced attempt, authenticated preemption, station success, active-operation deadline deferral and both policy/deadline wrap cases. The final focused recovery-policy, connectivity, Target security and Target autopublish suites passed 46/46; the OTA contract, all workflow `actionlint` checks and whitespace validation passed.
- The final default `esp32c6` profile compiled on Arduino 3.3.9 / ESP-IDF libs 5.5.4 with non-secret compile-only placeholders. The 1,786,336-byte firmware retains 5,553,696 bytes in either 7,340,032-byte OTA slot; the temporary ignored header was deleted after compilation and no production Secret value was read, printed or retained.
- Reconfirmed the privileged build inventory and regression against checkout SHA-256 `3e25df300a313b8081e0c1bbba8b43e04aa5d8d439226c303d560d24e801ff79` for `RecoveryRadioPolicy.h` and `9f71191acdb9d068503f02feddf27d40b12f4fcbcf83b86a5df2e88c1439f1c3` for `WifiManager.cpp`.
- Full Windows discovery ran 291 tests with 288 passing. Two unchanged checkout-materialization CRLF checks failed, and the trusted workflow digest check correctly remains red because the privileged build-tree pin now includes the new policy header and revised Wi-Fi source but has not received separate exact-feature policy authorization.
- No firmware was flashed and no physical AP beacon, Android scan/list/save, late STA/MQTTS, signed local OTA, health-valid or rollback result is claimed. Those checks remain mandatory before wall installation.

## [2026-08-24] compile | Authorize bounded recovery AP radio arbitration

- Replaced the completed `current-main-baseline` with one temporary-exact and one future persistent identity for reviewed PR #115 commit `23a3f3ed8fac513f1b7f88962e561cfd376f7ea2`; both identities bind the same complete ordered 62-file normalized digest map.
- Verified that `deploy.yml` is the only protected change from exact current main `380d013e819cd013c17253161d664cc69c6e7402`, with normalized SHA-256 `5d7a72e774b1c2df0b08c1feea9156568d4f057902d6a74c7f0055b40df36eb3`; its production inventory pins `RecoveryRadioPolicy.h` at `3e25df300a313b8081e0c1bbba8b43e04aa5d8d439226c303d560d24e801ff79` and `WifiManager.cpp` at `9f71191acdb9d068503f02feddf27d40b12f4fcbcf83b86a5df2e88c1439f1c3`.
- The pre-authorization PR #115 Hosted Trusted, OTA and firmware checks correctly fail closed on the unapproved protected digest. The live GitHub content/tree verifier selected `temporary-recovery-ap-23a3f3ed` for the exact candidate, with 62 protected regular blobs, seven workflow entries and zero local Actions.
- The focused transition suite passed 42/42; JSON/Python parsing, identical two-map validation, the OTA contract, all seven workflow `actionlint` checks and whitespace validation passed. Full Windows discovery passed 283/285; only the unchanged checkout-materialization CRLF checks for `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1` failed, while both staged Git blobs remain strict LF.
- This policy-only authorization reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no health-valid, rollback, Home Assistant, relay, physical, or commercial evidence.

## [2026-08-24] compile | Rotate recovery AP policy to merged-main baseline

- PR #116 merged the exact `23a3f3ed8fac513f1b7f88962e561cfd376f7ea2` authorization as `5198b8aca401dc73c01137a4ab8efda3ae590dac`; policy-connected feature head `aa9fe818482e5a2f7aaaee7471d3e5248624287b` retained both histories, and PR #115 merge-commit merged it as `539844ecead1576afd54518bb8db63eb3ec72422` after Hosted Trusted, OTA contract and ESP32-C6 canary checks passed.
- Removed both recovery-AP transition identities and pinned the sole `current-main-baseline` persistent identity to the actual PR #115 merge commit with the unchanged ordered 62-file map, seven-workflow inventory and empty local-Action inventory. The reviewed feature source is now explicitly retired.
- This policy-only rotation changes no protected workflow, production build input or runtime byte. It reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no health-valid, rollback, Home Assistant, relay, physical or commercial evidence.

## [2026-08-24] test | Verify final recovery AP policy rotation

- Verified that reviewed feature `23a3f3ed`, policy-connected head `aa9fe818` and merged main `539844ec` have 186 matching protected-object comparisons across the complete ordered 62-file set, with both earlier commits proven ancestors of merged main.
- The live GitHub verifier selected `current-main-baseline` for exact merged main with 62 protected files. The focused final-policy suite passed 42/42; JSON parsing, the OTA contract, all seven workflow `actionlint` checks and whitespace validation passed.
- Full Windows discovery ran 292 tests with 290 passing. Only the two unchanged checkout-materialization CRLF checks failed for `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1`; their staged Git entries remain LF.

## [2026-08-24] fix | Align privileged Target build inventory with Git order

- Exact-main runs `32679358174` and `32679992103` passed the secret-free ESP32-C6 canary but failed closed at `Verify exact protected main before production secrets`; Secret materialization, production compilation, handoff and NAS publication were skipped.
- Isolated the mismatch to the new `include/RecoveryRadioPolicy.h` row being declared after `include/RelayController.h` while `git ls-files` emits `RecoveryRadioPolicy.h` first in byte order. Moved only those two existing mode/digest rows into exact Git order without changing any build input, Secret, runtime or artifact byte.
- Added a regression that extracts all 40 privileged inventory rows and requires their declared path order and membership to equal the tracked build-input list returned by `git ls-files`, preventing a future file insertion from silently blocking exact-main production publication.

## [2026-08-24] test | Verify Target build inventory order correction

- The focused Target autopublish suite passed 18/18, including exact 40-row order/membership comparison. The OTA contract, all seven workflow `actionlint` checks and whitespace validation passed.
- The corrected `deploy.yml` has normalized SHA-256 `7f26fe2b5250927304cf2f4be5a6c5fa3e110429602f870c05ae991410fa4b1e`; it is the only protected byte change and therefore remains intentionally rejected by the predecessor trusted policy until a separate exact-feature authorization is merged and connected.
- No Secret was materialized, no production firmware was built, no NAS pointer was changed and no Target install, reboot, health-valid or rollback evidence is claimed by this source-level correction.

## [2026-08-24] compile | Authorize exact Target build inventory order fix

- Replaced the completed `current-main-baseline` with one temporary-exact and one future persistent identity for reviewed PR #118 commit `7021150d57aa6ceffec6a69e12cdf12cc88c548f`; both identities bind the same complete ordered 62-file normalized digest map.
- Verified that `deploy.yml` is the only protected change from exact current main `5444ced107cdacbaf47bad1aca683f0e4694285c`, with normalized SHA-256 `7f26fe2b5250927304cf2f4be5a6c5fa3e110429602f870c05ae991410fa4b1e`; all seven workflow entries remain regular files and the local-Action inventory remains empty.
- The live GitHub content/tree verifier selected `temporary-build-tree-order-7021150d` for the exact candidate with 62 protected files. The focused transition suite passed 42/42; JSON parsing, the OTA contract, all seven workflow `actionlint` checks and whitespace validation passed.
- This policy-only authorization reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no health-valid, rollback, Home Assistant, relay, physical or commercial evidence.

## [2026-08-24] compile | Connect Target build-order fix to trusted policy main

- Merged policy main `b23a13a1e17d6c4c7028fc6995999fcc54e5e464` into exact reviewed feature `7021150d57aa6ceffec6a69e12cdf12cc88c548f` without rebasing or squashing; resolved only the append-only log by retaining both histories.
- Retained the exact corrected `deploy.yml` bytes and complete authorized 62-file map, seven-workflow inventory and empty local-Action inventory. The focused Target autopublish plus trusted-policy suites passed 60/60; the OTA contract, all workflow `actionlint` checks and whitespace validation passed.
- Production publication remains gated on fresh hosted checks and merge to exact main; no Secret, NAS, Target install, reboot, health-valid or rollback result is claimed.

## [2026-08-24] compile | Rotate Target build-order policy to merged-main baseline

- PR #119 merge-commit merged the exact `7021150d57aa6ceffec6a69e12cdf12cc88c548f` authorization as policy main `b23a13a1e17d6c4c7028fc6995999fcc54e5e464`; policy-connected feature head `cd625503ce1382704cecd0a715334c98ed18d85e` retained both histories, and PR #118 merge-commit merged it as actual main `6ca977f71f19a9b2017bc51922b5fc808a8e5d2c` after Hosted Trusted, OTA contract and ESP32-C6 canary checks passed.
- Removed both Target build-order transition identities and pinned the sole `current-main-baseline` persistent identity to actual PR #118 merged main with the unchanged ordered 62-file map, seven-workflow inventory and empty local-Action inventory. Reviewed feature `7021150d` is now explicitly retired.
- This policy-only rotation changes no protected workflow, production build input or runtime byte. It reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no health-valid, rollback, Home Assistant, relay, physical or commercial evidence.

## [2026-08-24] test | Verify final Target build-order policy rotation

- Verified that reviewed feature `7021150d`, policy-connected head `cd625503` and merged main `6ca977f7` have 186 matching protected-object comparisons across the complete ordered 62-file set, with both earlier commits proven ancestors of merged main.
- The live GitHub verifier selected `current-main-baseline` for exact merged main with 62 protected files. The focused final-policy suite passed 42/42; JSON parsing, the OTA contract, all seven workflow `actionlint` checks and whitespace validation passed.
- Full Windows discovery ran 292 tests with 290 passing. Only the two unchanged checkout-materialization CRLF checks failed for `manuals/README.md` and `scripts/setup_ota_signing_secrets.ps1`; their staged Git entries remain LF.

## [2026-08-24] test | Verify exact-main Target connectivity and recovery paths

- Observed exact main `af779e1e61cd6c5c25b9b11e9aab9d1197ca094d` as `2.1.251+main.gaf779e1` on the physical ESP32-C6. NVS restored the saved Fold7 hotspot profile without recording its SSID, obtained `10.71.25.196`, kept the relay in logged OFF state and completed exact per-Target MQTTS subscriptions plus retained boot/config publication.
- The periodic signed OTA manifest check reported already current. Same-LAN local recovery enforced HTTP 401 without authentication, returned HTTP 200 with authentication and accepted the authenticated bounded AP enable request with HTTP 202.
- Home Assistant kept all 15 read-only entities available during AP+STA while uptime advanced 234 to 302 seconds, then reconverged all 15 after the final reset while uptime advanced 51 to 101 seconds.
- Missing ACL-signer and hardwareless-door NVS overrides remained fail-closed/default-disabled. No inactive-slot OTA write, health-valid mark, rollback, power-loss injection, physical relay actuation/electrical measurement or sensor test was performed.

## [2026-08-24] compile | Backfill and close the 2026-08-13 Home Assistant 502 incident

- Recorded the 2026-08-13 evidence that DNS and egress addressing agreed, multiple external probes reached nginx with HTTP 502, the NAS remained reachable and the Home Assistant TCP 8123 upstream was closed. Exact public/LAN addresses and host volume paths are intentionally omitted from the public wiki.
- Preserved the DSM read-only confirmation that the Home Assistant container was stopped with automatic restart disabled. Weather-integration and browser-frontend errors were not treated as proof of the container exit cause.
- Marked the incident historical after the 2026-08-24 upstream/reverse-proxy recovery and live 15/15 SmartGatekeeper entity verification; the page now distinguishes the past failure from current service state.

## [2026-08-24] compile | Fast-forward local main while preserving user work

- Fetched and fast-forwarded the original workspace from `264cfe096d1d137ef00c9c8e297cd55c8eb5ac0a` to merged `origin/main` `afb1360a578d0dc6161fb8a53c655270edae845e` without rebasing, force-updating or altering untracked directories.
- Preserved all four tracked local files in Git stash `863c97089acfd0e394c57df0c091acd3aa164e12` and a repository-external backup before integration. The local 8 MB partition content was already byte-identical to upstream; the optional `esp32c6_8mb` environment was not reapplied because physical `flash_id` proved this installed N16 Target has 16 MB.
- Restored the unique Home Assistant incident page and navigation entry, then consolidated its historical evidence into one current-date append-only backfill record. Existing `.codex-remote-attachments`, `.obsidian`, `.venn`, `delivery` and `dist` user files remain untouched.

## [2026-08-24] lint | Track HA evidence and ignore local-only artifacts

- Added the recovered Home Assistant 502 incident page to the compiled wiki and navigation map while retaining its historical evidence in an append-only backfill record.
- Ignored local Codex attachment cache, the `.venn` environment, generated `dist` output, secret-bearing local `delivery` artifacts and Obsidian appearance/plugin/graph UI state. Existing tracked `.obsidian/app.json` and ignored `include/secrets.h` remain unchanged.
- Kept the obsolete 8 MB PlatformIO override only in the pre-pull stash and repository-external backup; current main retains the physically verified N16 16 MB dual-OTA configuration.

## [2026-08-24] compile | Prepare HA incident and workspace-hygiene pull request

- Branched from local commit `6018b2a4922bec025f89fe8e2aa81165757c840d`, whose parent is exact remote main `afb1360a578d0dc6161fb8a53c655270edae845e`, as `codex/ha-incident-workspace-hygiene-20260824` without rebasing or force-updating any ref.
- Revalidated the four-file scope: root-local ignore rules, the privacy-minimized historical Home Assistant incident page, its navigation entry and append-only evidence. No production firmware, workflow, Secret, ignored delivery artifact or physical Target state changes in this pull request.

## [2026-08-24] compile | Reconcile personal GATT and signed Home Assistant control contracts

- Documented `esp32c6_personal_production` as the single-installation exception that compiles Hardwareless ON only with valid door and ACL trust, performs one provisioning-gated NVS enable migration and thereafter preserves persisted false as the local kill switch. Default developer and commercial production profiles remain compile-OFF.
- Documented the AndroidKeyStore public-only bootstrap through authenticated personal enrollment, exact Target ACL application before native ON, native-authoritative consent and BLE ownership, and the separation between local GATT, legacy pre-arm and signed Backend/MQTT `manual_remote`.
- Documented Home Assistant controls as Backend ingress only: fresh Target boot/status, bounded replay/rate/payload checks, a newly signed short-lived exact-Target command, correlated command ACK, and an independent default-OFF manual-open opt-in. Direct plaintext Target control is not restored.
- Preserved the 16 MB dual-slot OTA, previous-version recovery and commercial/physical release Gates. The new Backend, retained discovery, same-signature APK and personal Target image are recorded as source/build candidates, not as live NAS, phone, Target, GATT, relay, health-valid or rollback evidence.

## [2026-08-24] lint | Verify personal GATT and HA documentation boundaries

- Rechecked all relative links in the ten changed wiki pages and passed `git diff --check` for their exact scope. No new page was added, so `wiki/index.md` did not require a navigation change; `raw/` remained untouched and this entry was appended without rewriting prior log history.
- Reconciled the recorded fresh software evidence: clean Flutter analysis, Flutter 35/35 and native GATT Gradle success; personal/commercial Target builds, Hardwareless 9/9, personal workflow 6/6, physical profile 5/5, Target auto-publish 18/18 and OTA gate 78/78. The personal image is 1,844,880 bytes in a 7,340,032-byte slot with 5,495,152 bytes headroom.
- A local focused Backend run passed 40 HA bridge, ACL API and ACL-management tests; the separate Target ACL delivery module was not collected in that shell because optional `pymysql` was absent, so no full Backend-suite claim is made here. Live deployment and end-to-end device evidence remain pending.

## [2026-08-25] fix | Bound ACL refresh to real Target boot advances

- Distinguished `advanced`, `unchanged` and `rejected` authenticated boot observations while preserving the existing boolean registry API for compatibility. The first authenticated non-retained boot or fresh status observation of an increased boot count queues `TARGET_BOOT_REFRESH` exactly once; the other observation and ordinary MQTT reconnect repeats are unchanged. The Backend-start worker retains its immediate lease recovery pass.
- Added regressions for status-first, boot-first, unchanged reconnect and retained-status ordering, then passed the focused boot-registry, ACL refresh and ACL management suite. This removes routine ACL version growth and avoidable Target NVS writes without weakening missed-boot recovery.
- Recorded the personal enrollment endpoint as a supervised commissioning exception: keep it enabled only through the connected phone's exact Target ACL ACK, then disable it. Source/build checks remain distinct from the pending NAS, broker, HA, phone, Target, relay and OTA installation evidence.

## [2026-08-25] compile | Authorize personal GATT and signed HA controls

- Replaced the completed `current-main-baseline` with one temporary-exact and one future persistent identity for reviewed PR #123 feature commit `47f7e111ed3c8f625dad09597af3426f8204930d`; both identities bind the same complete ordered 68-file normalized digest map.
- Added the ACL refresh, Home Assistant bridge and Target ACL-delivery modules plus their three direct tests to the protected set. The seven-workflow inventory remains exact and the repository-local Action inventory remains empty; 23 protected files are changed or newly protected relative to the predecessor baseline.
- This policy-only authorization reads no production Secret, publishes no firmware or APK, writes no NAS state, installs or reboots no Target, and claims no ACL application, GATT session, Home Assistant command, relay, health-valid, rollback or physical evidence.

## [2026-08-25] test | Verify PR 123 exact-commit policy authorization

- Verified 42 focused policy tests with 201 subtests, the OTA contract gate, all workflow files with `actionlint`, JSON parsing and whitespace validation on the policy-only branch.
- The live GitHub verifier selected `temporary-personal-gatt-ha-47f7e111` for exact feature commit `47f7e111ed3c8f625dad09597af3426f8204930d` and approved the complete ordered 68-file protected set.
- This validation authorizes only the reviewed Git objects. It does not prove CI publication, NAS deployment, Target installation, Android installation, ACL acknowledgement, GATT control, Home Assistant command delivery or physical relay operation.

## [2026-08-25] compile | Finalize personal GATT and HA trusted baseline

- Replaced both bounded `47f7e111` transition identities with the sole `current-main-baseline` pinned to actual PR #123 merge commit `374043426b560108b30cb954fc15d658a56631a2`.
- Expanded the indivisible protected set from 68 to 69 by adding `backend/app/static/admin_login.html`, the only path present in the trusted backend/operations inventory but missing from the policy. Added a regression requiring the ordered policy suffix to equal that inventory exactly.
- This policy-only rotation changes no runtime, workflow or validator byte and claims no production Secret materialization, NAS publication, Backend restart, Target or Android installation, GATT/HA command, relay, health-valid or rollback evidence.

## [2026-08-25] test | Verify final 69-file trusted baseline

- Passed 42 focused policy tests with 270 subtests, JSON parsing, the OTA contract gate, all workflow files with `actionlint` and whitespace validation.
- The live GitHub verifier selected the sole `current-main-baseline` for exact PR #123 merge commit `374043426b560108b30cb954fc15d658a56631a2` and approved all 69 protected Git objects, including the administrator-login surface.
- Confirmed the ordered 59-path backend/operations suffix exactly equals `ops/backend_trusted_bundle_paths.json`; this remains authorization evidence only, not deployment or physical evidence.

## [2026-08-25] test | Verify exact-main Android artifact before installation

- Downloaded the immutable Android artifact from GitHub Actions run `32747024524` without installing it. Its 55,786,649-byte APK matched SHA-256 `afb0cdc5eb95d8c0dd8c34597b180ddb803b6d8b35b9b1e130da7db13f054f42`.
- Verified package `com.kshouse.gatekeeper_app`, `versionCode=18201`, `versionName=1.0.0-g7c2764a`, APK signature validity, production signing-certificate SHA-256 `8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0` and embedded exact source commit `7c2764a1a16492ec1620079c8211b47287b1b3fd`.
- This is pre-install artifact evidence only. Device replacement install, launch, credential preservation, enrollment, native GATT, background behavior and rollback remain separate observations.

## [2026-08-25] fix | Restore live signed Home Assistant bridge discovery

- Traced the disabled Home Assistant controls to paho-mqtt 1.6.1 MQTTv5 supplying a comparable `ReasonCodes` object that does not implement `int()`. The resulting callback `TypeError` stopped Target subscriptions, bridge availability and secure-control discovery before publication.
- Replaced coercion with the supported success comparison and added a non-integer callback regression. The focused Backend suite passed 11/11, the NAS Backend was recreated, readiness passed, retained bridge availability became online and the Home Assistant control card rendered reboot/open/OTA/config controls enabled.
- No Home Assistant command, Target reboot, OTA command, gate-open command or relay actuation was invoked by this recovery observation.

## [2026-08-25] test | Install personal GATT exact-main baseline

- Installed the production-signed `1.0.0-g7c2764a` APK from run `32747024524` with data-preserving `adb install -r`; native ownership, local consent and the AndroidKeyStore credential remained enabled and `NATIVE_GATT_DISABLED` was eliminated.
- Observed Target `2.1.256+main.g7c2764a` from run `32749448224` after signed OTA and reboot with Wi-Fi `192.168.35.19`, exact MQTTS, production ACL signer, ACL v3 and connectable GATT enabled.
- Android registered the exact OS PendingIntent scan but produced no `source=ble_scan` event or locator, so manual local retry returned `TARGET_UNAVAILABLE` before GATT. This is a truthful partial result, not a local-open or relay success claim.

## [2026-08-25] fix | Correct Target iBeacon company bytes for Android exact wake

- Confirmed that pinned pioarduino byte-swaps `BLEBeacon::setManufacturerId()` and that the prior `0x004C` argument emitted non-standard `00 4C`, while Android's Apple manufacturer ID `0x004C` filter requires standard on-air `4C 00`. Changed the Target setter argument to the pinned framework example's `0x4C00` and kept the exact Android filter fail-closed.
- Added a source regression that rejects the old argument and updated the privileged Target inventory hash. Hardwareless tests passed 9/9 and the 16 MB personal-production compile produced a 1,779,430-byte image, leaving 5,560,602 bytes in either 7,340,032-byte OTA slot.
- CI production signing, NAS publication/readback, inactive-slot Target install/reboot, non-zero Android exact-filter delivery and GATT challenge/proof/result remain pending until the separately authorized exact change reaches main.

## [2026-08-25] compile | Authorize exact GATT wake and HA runtime corrections

- Replaced the completed `current-main-baseline` with temporary-exact `temporary-gatt-ha-runtime-4538fcb` and future persistent `future-gatt-ha-runtime-4538fcb-persistent-baseline`, both bound to reviewed PR #126 feature commit `4538fcb184d77f92991063f93dc4d875ba1e870f` and the same complete ordered 69-file digest map.
- Exactly three protected normalized blobs differ from exact main `7c2764a1`: `.github/workflows/deploy.yml` `2508247403ca8ff45bcc31467e8611e5000a10f4dde2dd9483c6e4074d4997e1`, `backend/app/main.py` `5466791df1b404a8b116227c0ceae219b090612cd29fb5429224d5d5bba4b044` and `backend/tests/test_target_boot_registry.py` `4f29b72539e9c4c190e83f702e92ec71fb9bc6d2e44f260f2094c4388ced430f`; the other 66 remain exact.
- This policy-only authorization reads no production Secret, publishes no firmware or APK, changes no NAS or device state and claims no Android GATT, Home Assistant command, relay, health-valid or rollback result.

## [2026-08-25] test | Verify PR 126 exact-commit transition policy

- Pinned both bounded identities, the complete 69-path map, the seven-workflow inventory and empty repository-local Action inventory in regression tests; predecessor merged main `37404342` is retired from future source identities.
- Local validation covers policy parsing, exact/future selection, mutation rejection, OTA contract, workflow syntax, relative wiki links and whitespace. Hosted base-policy verification remains required before the policy PR merges.
- Passing authorization proves only reviewed Git object identity. Production signing, NAS publication/readback, Target OTA/reboot and Android GATT proof remain subsequent steps.

## [2026-08-25] compile | Finalize GATT wake and HA runtime trusted baseline

- PR #127 merge `a1f8e4dc` separately authorized reviewed feature `4538fcb`; policy-connected head `b590c410` retained both parents and the exact 69-file map, and PR #126 merge-commit produced actual main `900f22179db54b50aba03fba519ac80266519c2d` after fresh Hosted Trusted, OTA, Backend and ESP32-C6 checks passed.
- Removed both bounded `4538fcb` transition identities and pinned the sole `current-main-baseline` persistent identity to actual PR #126 merged main `900f2217`. All 69 protected normalized objects, seven workflow entries and the empty local-Action inventory remain unchanged from the reviewed feature.
- This policy-only rotation changes no runtime or protected workflow byte and claims no production Secret materialization, NAS publication, Target OTA, Android GATT, Home Assistant command, relay, health-valid or rollback evidence.

## [2026-08-25] test | Verify final GATT wake and HA runtime baseline

- Recomputed the complete ordered 69-file map from exact merged-main Git blobs and verified it matches reviewed feature `4538fcb`, policy-connected head `b590c410` and the sole final bundle; both feature and authorization commits are ancestors of actual main.
- The focused trusted-policy suite, OTA contract, all workflow syntax checks, JSON parsing, relative wiki links and whitespace validation pass locally. Hosted base-policy verification remains required before this final rotation merges.
- This closes only the repository authorization transition. Exact-main production build/NAS publication, Target OTA/reboot and Android GATT challenge/proof/result remain the next connected evidence steps.

## [2026-08-25] test | Exercise exact Android wake and Home Assistant OTA

- Verified ten exact-filter Android PendingIntent deliveries from the corrected iBeacon, with observed RSSI about -46 to -50 dBm and callback latency 6–20 ms. Installed production-signed `1.0.0-gbc9bb5d` from run `32768108110` by same-signature replacement while preserving application data and the enrolled AndroidKeyStore credential.
- Exercised the enabled Home Assistant OTA control. Its signed Backend/MQTT command caused Target to install and reboot into NAS-published exact main `2.1.259+main.gbc9bb5d` from run `32768108034`; Wi-Fi, MQTTS, ACL and connectable GATT returned. Remote open and relay actuation were not invoked.
- The first real GATT Target Hello/challenge exchange repeatedly exposed a stack-protection reset in `nimble_host`. This is a failed local-auth observation, not proof/result/FSM or relay success.

## [2026-08-25] fix | Move heavy GATT callback work to the main loop

- Traced the reset to callback paths that could enter a 2,736-byte output-drain frame or 3,216-byte canonical JSON/MQTTS frame on the prebuilt 5,120-byte NimBLE host task. BLE callbacks now perform bounded state/event copies only; the 16 KB Arduino loop drains subsequent indication fragments and a bounded 16-entry canonical-event queue.
- Separated authentication control from best-effort telemetry: proof-request/grant changes reach the FSM before Result output, callback-originated abort and advertising restart are drained on loopTask, and audit-queue overflow cannot produce `RESULT OK` with an unarmed FSM. Added source regressions requiring the heavy and advertising paths to remain outside NimBLE callbacks.
- App-only flashed local candidate `2.1.260-test.g163610d` without erasing bootloader, partitions, NVS, OTA data or the fallback slot. Wi-Fi `192.168.35.19`, MQTTS, ACL and GATT recovered, and the same phone reached Target Hello/challenge without the prior reset. This is candidate evidence, not exact-main signed OTA proof.

## [2026-08-25] fix | Serialize Android Challenge delivery

- After the Target reset was removed, the installed bc9 APK truthfully reported `MALFORMED_PROOF`. The app had subscribed to ACK-gated Challenge indications and simultaneously read the same characteristic, allowing a single-frame read to interleave with indicated fragments that shared a message ID.
- Changed the production transport to consume Target Hello and Challenge only through the already-enabled ordered indication mailbox. Added a mailbox ordering regression and a source contract that rejects any Challenge `readCharacteristic` call.
- The focused source suite passed 11/11; the JDK17 Android build/JUnit run completed all 209 Gradle tasks, and the final personal-production Target build used 1,780,268/7,340,032 bytes flash plus 67,088/327,680 bytes RAM. Updated the Android worker, Target transport, security protocol, project status, hardware evidence and navigation pages. Signed exact-main APK/firmware publication, replacement install/OTA and successful physical proof/result remain the next evidence Gate.

## [2026-08-25] lint | Verify callback-stack and single-stream release candidate

- Passed the Hardwareless source/native-host suite 11/11 and 124 Target security, OTA contract, exact inventory, personal-production and personal-mobile publisher tests. The exact `src/GattServer.cpp` normalized SHA matches its privileged `deploy.yml` inventory row.
- Passed the focused Android JDK17 build/JUnit run with 209 executed Gradle tasks, all workflow files with `actionlint`, the relative wiki link check and whitespace validation. Docker-generated desktop registrants, lockfile and analysis-option changes were discarded because they were test side effects rather than reviewed source changes.
- The trusted policy still correctly rejects the newly changed `deploy.yml` digest until a separate exact feature authorization is merged. No production Secret was read, no NAS pointer changed, and the hardened source/APK was not installed by these checks.

## [2026-08-25] compile | Authorize exact GATT stack release candidate

- Replaced the completed `current-main-baseline` with temporary-exact `temporary-gatt-stack-df2ac48` and future persistent `future-gatt-stack-df2ac48-persistent-baseline`, both bound to reviewed feature commit `df2ac4869f4ee15c567f4a5ce1e0a99fab08e269` and the same complete ordered 69-file normalized digest map.
- Relative to exact main `bc9bb5dae2d1ca49ef38c8c2d89122084d4b6909`, only `.github/workflows/deploy.yml` changes in the protected set, to `26d9fc567b7465fc3fcb42c84a85db531b3fb9a227d4fa5432799aba0d86b478`; the other 68 protected objects, seven-workflow inventory and empty repository-local Action inventory remain exact.
- This policy-only authorization reads no production Secret, publishes no firmware or APK, changes no NAS or device state and claims no signed exact-main installation, GATT proof/result, relay, health-valid or rollback evidence.

## [2026-08-25] test | Verify exact GATT stack transition policy

- Passed all 42 focused trusted-policy tests. Both bounded identities contain the same complete ordered 69-file map; direct `utf8-lf-v1` recomputation from immutable feature commit `df2ac4869f4ee15c567f4a5ce1e0a99fab08e269` matched all 69 entries, while the policy branch verified the 68 locally unchanged protected files and intentionally excluded only its predecessor `deploy.yml` byte.
- Passed the OTA contract gate, JSON parsing, all seven workflow files with `actionlint` and whitespace validation. Exact workflow/action inventories remain seven and zero, and predecessor baseline source `900f22179db54b50aba03fba519ac80266519c2d` is retired from future authorization identities.
- Hosted base-policy verification remains required before merge. Passing this policy authorization does not publish or install firmware/APK and does not prove GATT challenge/proof/result, physical relay actuation, health-valid or rollback behavior.

## [2026-08-25] compile | Finalize GATT stack trusted baseline

- PR #130 merge `813a849f` separately authorized reviewed feature `df2ac4869`; policy-connected head `4baa3fa8` retained both parents and the exact 69-file map, and PR #129 merge-commit produced actual main `a9d4bd0de7cf5393cba47b8be1fa6c17c0b6759e` after fresh Hosted Trusted, OTA, protocol, Android and ESP32-C6 checks passed.
- Removed both bounded `df2ac48` transition identities and pinned the sole `current-main-baseline` persistent identity to actual PR #129 merged main `a9d4bd0d`. All 69 protected normalized objects, seven workflow entries and the empty repository-local Action inventory remain unchanged from the reviewed feature.
- This policy-only rotation changes no runtime or protected workflow byte and claims no production Secret materialization, NAS publication, Target OTA, Android replacement install, GATT proof/result, relay, health-valid or rollback evidence.

## [2026-08-25] test | Verify final GATT stack baseline

- Recomputed the complete ordered 69-file map from exact merged-main Git blobs and verified it matches reviewed feature `df2ac4869`, policy-connected head `4baa3fa8` and the sole final bundle; both the reviewed feature and authorization main are ancestors of actual main.
- The focused trusted-policy suite, OTA contract, all workflow syntax checks, JSON parsing, relative wiki links and whitespace validation pass locally. Hosted base-policy verification remains required before this final rotation merges.
- This closes only the repository authorization transition. Exact-main production build/NAS publication, Target OTA/reboot and Android GATT challenge/proof/result remain the next connected evidence steps.

## [2026-08-26] compile | Authorize exact issue 133 manual-open candidate

- Replaced the completed baseline with temporary-exact `temporary-manual-open-9185858` and future persistent `future-manual-open-9185858-persistent-baseline`, both bound to reviewed feature commit `91858585f8db6fb1b8b50ca0182526fdb653f0bf` and the same complete ordered 69-file protected map.
- Relative to exact main `db37bc2390efbf94bf1a9fca261834c3728606b5`, only `.github/workflows/deploy.yml` changes in the protected set, to normalized SHA-256 `e46ba83350633b13fd13ad5f5fdee2024481d2eab4857bca3f231a2ad003d409`; the other 68 protected objects and exact inventories remain unchanged.
- This policy-only authorization changes no runtime/workflow byte, reads no production Secret and publishes or installs no firmware/APK.

## [2026-08-26] test | Verify issue 133 transition policy

- Passed all 42 focused trusted-policy tests. Both identities pin the exact feature source and complete protected map; the policy branch locally verifies the 68 unchanged files while the immutable feature commit supplies the reviewed deploy digest.
- Hosted base-policy verification remains required before merge. Passing this authorization is not Android, Target, relay, sensor, OTA install or rollback evidence.
