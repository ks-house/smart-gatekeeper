# AGENTS.md — smart-gatekeeper Agent Collaboration Guide
> 이 파일을 읽는 모든 AI 에이전트는 작업 전에 전체 문서를 읽고 지침을 준수하라.
> Last updated: 2026-07-30 (v2.0)

---

## 0. TL;DR (30초 요약)

```text
프로젝트  : ESP32-C6 iBeacon → Flutter → NAS HTTPS 인증 → MQTTS Pre-arm 출입 통제
현재 단계 : v2.0 통합 구현/현장 검증 (기존 Local PoC 단계가 아님)
MCU       : ESP32-C6-DevKitC-1 N16 (RISC-V, BLE 5.3, 16 MB Flash)
거리 센서 : AJ-SR04T/JSN-SR04T 초음파 — TRIG=GPIO10, ECHO=GPIO11
릴레이    : GPIO23 (`include/config.h`가 단일 진실 공급원)
플랫폼    : pioarduino (공식 espressif32 사용 금지)
지식베이스: 매 작업 전 wiki/index.md와 wiki/log.md 최근 항목을 읽어라
로그      : 모든 작업은 wiki/log.md에 append하라
```

---

## 1. 프로젝트 개요와 v2.0 흐름

ESP32-C6는 스마트폰을 스캔하지 않고 게이트 고유 iBeacon을 송출한다. Flutter 앱이 이를
감지해 NAS FastAPI에 HTTPS Pre-arm 요청을 보내며, FastAPI가 MariaDB의 등록 기기와 승인
상태를 검증한다. 승인 시 NAS가 MQTTS `gatekeeper/arm`을 발행한다. ESP32-C6는 정해진
시간 동안 초음파 접근 감지를 활성화하고, 접근 확인 시 릴레이를 구동한다.

전화번호 해시 기반 UUID는 현재 설계가 아니다. iBeacon UUID는 게이트 식별자이며 사용자
자격 증명이 아니다.

### 로드맵

| 단계 | 범위 | 상태 |
|------|------|------|
| Step 1 | 거리 센서 + 릴레이 Local PoC | 🟢 완료 (역사 단계) |
| Step 2 | NAS FastAPI + MariaDB + HTTPS 인증 | 🟢 완료 |
| Step 3 | ESP32 Wi-Fi/MQTT/릴레이 통합 | 🟢 완료 |
| Step 4 | 기존 BLE Scanner + ToF 검증 | 🟢 완료 후 v2.0으로 대체 |
| **Step 5 / v2.0** | **ESP32 iBeacon Advertiser → Flutter → NAS → MQTT Pre-arm + 초음파** | 🟡 통합 구현/현장 검증 |
| Step 6 | PCB, 절연/전원, 실외 케이스 등 프로덕션화 | 🔲 미시작 |

---

## 2. 지식 시스템 (Karpathy LLM Wiki 패턴)

이 프로젝트는 wiki를 단일 진실 공급원으로 운영한다.

```text
smart-gatekeeper/
├── backend/          # FastAPI + MariaDB schema + NAS Docker 구성
├── gatekeeper_app/   # Flutter 모바일 앱
├── src/              # ESP32-C6 펌웨어
├── include/          # config.h 핀/설정 중앙화
├── raw/              # 수정 금지 원본 및 역사 자료
├── wiki/
│   ├── index.md      # 탐색 지도 — 항상 먼저 읽기
│   ├── log.md        # 시간순 변경 이력 — append-only
│   ├── architecture.md
│   ├── pin_mapping.md
│   └── hardware_test.md
└── platformio.ini
```

- `raw/`는 수정하지 않는다. `ST_VL53L0X_Specs.md`와 초기 BOM은 과거 PoC를 보존한
  **불변 원본/역사적 참고자료**이며 VL53L0X가 현재 장착 센서라는 뜻이 아니다.
- `wiki/index.md`는 모든 wiki 페이지의 최신 목록을 유지한다.
- `wiki/log.md`의 과거 항목은 절대 수정하지 않고 새 항목만 끝에 추가한다.

---

## 3. 에이전트 필수 워크플로우

```text
1. READ   wiki/index.md
2. READ   wiki/log.md 최근 항목
3. DO     코드/문서/테스트 작업
4. UPDATE 영향받은 wiki 페이지
5. UPDATE wiki/index.md (페이지가 추가/이동된 경우)
6. APPEND wiki/log.md
7. LINT   링크, 핀, 용어, 문서-코드 일관성
```

wiki를 업데이트하지 않고 턴을 종료하지 않는다.

### 로그 형식

```markdown
## [YYYY-MM-DD] <type> | <brief description>

- 세부 내용 bullet
```

허용 type: `ingest`, `compile`, `code`, `test`, `fix`, `lint`.

---

## 4. 하드웨어 절대 규칙

### ESP32-C6-DevKitC-1 N16

| 항목 | 현재 값 |
|------|---------|
| 아키텍처 | RISC-V (Xtensa 아님) |
| Bluetooth | **BLE 5.3 전용** (Classic Bluetooth 없음) |
| 로직 레벨 | 3.3 V |
| 거리 센서 | AJ-SR04T/JSN-SR04T 방수 초음파 |
| 초음파 TRIG | **GPIO10** (OUTPUT) |
| 초음파 ECHO | **GPIO11** (INPUT) |
| Relay IN | **GPIO23**, Active-LOW |

```text
🔴 스트래핑/부팅 충돌 회피: GPIO4, GPIO5, GPIO8, GPIO9, GPIO15
🔴 USB/UART 예약 회피:      GPIO17, GPIO18, GPIO19, GPIO20
🔴 보드 내장 RGB LED:       GPIO8
```

- 모든 핀 상수는 `include/config.h`에서만 정의한다. 소스에 GPIO 숫자를 하드코딩하지 않는다.
- 센서가 5 V ECHO를 출력하는 모델/모드라면 GPIO11에 직접 인가하지 말고 분압 또는 레벨
  시프터를 사용한다. 실제 모듈의 출력 전압을 먼저 측정한다.
- 초음파 측정은 타임아웃과 유효 거리 검증을 유지한다. 현재 0~19.9 cm는 맹점/난반사
  노이즈로 취급한다.
- VL53L0X의 `Wire.begin`, 400 kHz, 65535 sentinel 초기화 규칙은 현행 펌웨어 규칙에서
  제거한다. 역사 자료를 재현할 때만 `raw/ST_VL53L0X_Specs.md`를 참조한다.

### 릴레이

현재 `include/config.h`의 `PIN_RELAY = 23`, `RELAY_ACTIVE_LOW = true`가 기준이다.
현행 5 V 모듈은 OFF 시 High-Z(INPUT)를 사용하는 구현이므로, 전기적 절연·역전압·플라이백
보호와 실제 점퍼 극성을 현장에서 검증한다.

---

## 5. 빌드 및 실행 환경

### ESP32-C6 펌웨어

```ini
[platformio]
default_envs = esp32c6

[common]
platform  = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
board     = esp32-c6-devkitc-1
framework = arduino
board_build.partitions = partitions_16MB_ota.csv
build_flags =
    -DARDUINO_USB_CDC_ON_BOOT=1
    -DARDUINO_USB_MODE=1
lib_deps =
    bblanchon/ArduinoJson @ ^6.21.5
    knolleary/PubSubClient @ ^2.8
```

- 통합 빌드 환경은 `[env:esp32c6]` 하나다. 과거 `tof_test`/`relay_test` 환경이나
  `pololu/VL53L0X` 의존성을 현재 설정으로 복원하지 않는다.
- BLE advertiser는 Arduino-ESP32 BLE API를 사용한다. UUID 바이트 순서/실제 링크 BLE
  스택은 프레임워크 변경 때마다 실기기 패킷으로 검증한다.
- MQTTS와 HTTPS 인증서, Wi-Fi, API, OTA 비밀값은 `include/secrets.h`에 두며 커밋하지 않는다.

### 앱과 NAS

- Flutter 앱: `gatekeeper_app/` (`flutter analyze`, `flutter test`, Android 빌드).
- FastAPI/MariaDB: `backend/`의 Docker Compose와 `backend/db/schema.sql`.
- NAS는 HTTPS API, MariaDB, MQTTS broker, 펌웨어/앱 업데이트 파일을 제공한다.
- OTA는 ESP32 N16 Dual-OTA 파티션과 NAS 버전/펌웨어 URL을 사용한다.

---

## 6. 코드 컨벤션

```text
펌웨어 : C++17, Google C++ Style Guide, 2-space indent
모듈   : 주변기기 하나당 .cpp + .h 한 쌍
핀     : include/config.h에서만 정의
로그   : [INFO], [WARN], [ERROR], [FATAL]
오류   : 안전한 fallback과 타임아웃을 제공
```

파일 이름은 `raw/`와 `wiki/`에서 각각 기존 벤더 원본 규칙과 `snake_case.md`를 따르고,
펌웨어 클래스 파일은 `PascalCase`를 사용한다. import 주위에 try/catch를 두지 않는다.

---

## 7. 현재 Open Questions / 현장 검증 항목

| # | 항목 | 상태 |
|---|------|------|
| Q1 | AJ-SR04T/JSN-SR04T ECHO 실제 전압과 GPIO11 레벨 시프팅 필요 여부 | 🟡 실측 필요 |
| Q2 | Active-LOW 릴레이의 절연, 플라이백, 별도 전원 및 High-Z OFF 장기 안정성 | 🟡 현장 검증 필요 |
| Q3 | Arduino BLE 구현의 iBeacon UUID 바이트 순서와 Android 실기기 수신 호환성 | 🟡 패킷 실측 필요 |
| Q4 | Android 백그라운드/화면 OFF/재부팅 후 iBeacon 감지 생애주기 | 🟡 실기기 회귀 테스트 필요 |
| Q5 | MQTTS 인증서 검증과 NAS 장애 시 fail-closed 동작 | 🟡 E2E 장애 주입 테스트 필요 |

---

## 8. 협업 에티켓

1. wiki 먼저, 코드 나중: 변경한 동작과 관련 wiki를 함께 동기화한다.
2. 추측하지 않는다. 불확실한 전기/무선 특성은 실측 필요로 명시한다.
3. 핀 변경 시 `config.h` → `wiki/pin_mapping.md` → `wiki/log.md` 순서로 갱신한다.
4. 의존성 변경 시 설정 파일, `wiki/env_setup.md`, 로그를 함께 갱신한다.
5. 테스트 결과는 `wiki/hardware_test.md`에 날짜, 결과, 비고와 함께 기록한다.
6. `raw/` 수정, `wiki/log.md` 과거 항목 수정, 핀 하드코딩은 금지한다.
