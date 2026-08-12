# AGENTS.md — smart-gatekeeper Agent Collaboration Guide
> **이 파일을 읽는 모든 AI 에이전트(Gemini, Claude, Antigravity 등)에게:**
> 작업 시작 전 반드시 이 문서 전체를 읽고, 지침을 엄수하라.
> Last updated: 2026-08-12

---

## 0. TL;DR (30초 요약)

```
프로젝트  : ESP32-C6 + Android + NAS 기반 스마트 출입 통제 시스템
현재 단계 : 프로덕션 증거 수집 — 최신 코드와 현장 구형 Target 상태를 분리
MCU       : ESP32-C6-DevKitC-1 (RISC-V, NOT Xtensa)
플랫폼    : pioarduino (공식 espressif32 사용 금지)
센서      : AJ-SR04T TRIG=GPIO10, ECHO=GPIO11 (5V ECHO 보호 필수)
릴레이    : GPIO3 Active-LOW, OFF=INPUT High-Z (현장 전기 검증 필수)
금지 핀   : GPIO 4,5,8,9,15 (스트래핑), 17,18,19,20 (USB/UART)
지식베이스: wiki/index.md 를 먼저 읽어라
로그      : wiki/log.md 에 반드시 기록하라
GitHub 인증: 프로세스 환경 변수 GITHUB_TOKEN만 사용 (출력·파일 저장 금지)
OTA       : 모바일 앱·Target OTA/rollback 경로는 최상위 불변조건 (기능 변경으로 약화 금지)
```

---

## 1. 프로젝트 개요

### 목표
시놀로지 NAS 백엔드, Android 스마트키, ESP32-C6 BLE/MQTTS Target과 초음파·릴레이를 결합한 출입 통제 시스템.

### 5단계 로드맵

| 단계 | 이름 | 상태 |
|------|------|------|
| Step 1 | 초기 Local PoC — VL53L0X + relay | ✅ 역사적 완료 |
| Step 2 | iBeacon/Android background access | ✅ 구현, OEM별 실기기 Gate 유지 |
| Step 3 | Backend + per-Target MQTTS signed command | ✅ 저장소 구현, 현장 배포 확인 필요 |
| Step 4 | Local GATT/ACL Hardwareless RC | 🟡 software core, default-OFF, physical Gate pending |
| **Step 5** | signed OTA·운영·현장 production evidence | 🟡 **현재 진행 중** |

---

## 2. 지식 시스템 (Karpathy LLM Wiki 패턴)

이 프로젝트는 **단일 진실 공급원(Single Source of Truth)** 으로 wiki를 운영한다.

```
smart-gatekeeper/
├── AGENTS.md         ← 지금 읽는 파일 (에이전트 협업 지침)
├── schema.md         ← 위키 거버넌스 규칙 (co-evolve 가능)
├── raw/              ← 읽기 전용 소스 (데이터시트, BOM, 스펙)
│   ├── ST_VL53L0X_Specs.md
│   ├── Espressif_ESP32C6_BoardSpec.md
│   └── BOM_SmartGatekeeper_Step1.md
├── wiki/             ← 에이전트가 작성·유지하는 컴파일 지식
│   ├── index.md      ← 🗺️ 탐색 지도 — 항상 여기부터 읽어라
│   ├── project_status.md ← 구현·검증·배포 상태 분리
│   ├── knowledge_management.md ← Obsidian·승격 규칙
│   ├── log.md        ← 📋 시간순 변경 이력 (항상 append)
│   ├── env_setup.md
│   ├── pin_mapping.md
│   ├── hardware_test.md
│   └── architecture.md
├── src/              ← C++ 펌웨어 소스
├── include/          ← 헤더 (config.h 핀 상수 중앙화)
└── platformio.ini    ← 빌드 설정
```

### 절대 규칙
- **`raw/`** 파일은 수정 금지. 새 버전이 필요하면 새 파일로 추가.
- **`wiki/index.md`** 는 모든 wiki 페이지의 최신 목록을 유지해야 한다.
- **`wiki/log.md`** 는 Append-only. 과거 항목 절대 수정 금지.

---

## 3. 에이전트 필수 워크플로우

**매 턴, 모든 에이전트는 반드시 이 순서를 지켜라:**

```
1. READ   wiki/index.md        → 관련 wiki 페이지 파악
2. READ   wiki/log.md (최근)   → 직전 에이전트가 무엇을 했는지 확인
3. DO     작업 수행 (코드, 리서치, 테스트)
4. UPDATE 영향받은 wiki 페이지
5. UPDATE wiki/index.md        → 새 페이지가 생겼다면
6. APPEND wiki/log.md          → 형식 엄수 (§4 참조)
7. LINT   링크 깨짐 / 모순 정보 없는지 자가 점검
```

> ⚠️ **wiki를 업데이트하지 않고 턴을 종료하는 행위는 금지다.**

---

## 4. 로그 형식 (엄수)

```markdown
## [YYYY-MM-DD] <type> | <brief description>

- 세부 내용 bullet
```

**허용 type:**

| type      | 용도             |
| --------- | -------------- |
| `ingest`  | raw/ 에 새 소스 추가 |
| `compile` | wiki 페이지 신규/수정 |
| `code`    | 펌웨어 소스 추가/수정   |
| `test`    | 하드웨어 테스트 결과 기록 |
| `fix`     | 오류 수정          |
| `lint`    | 링크·일관성 검사      |

---

## 5. 하드웨어 제약 (현재 코드 기준)

### MCU: ESP32-C6-DevKitC-1

> ⚠️ 구형 ESP32(Xtensa)와 **완전히 다른 칩**이다. GPIO 번호를 혼동하지 마라.

| 항목 | 값 |
|------|-----|
| 아키텍처 | **RISC-V** (Xtensa 아님) |
| Bluetooth | **BLE 5.3 전용** (Classic BT 없음) |
| Logic level | **3.3V** |
| Ultrasonic TRIG | **GPIO 10** |
| Ultrasonic ECHO | **GPIO 11** (sensor 5 V output 보호 필요) |
| Relay IN | **GPIO 3** |

### 절대 사용 금지 핀

```
🔴 스트래핑 핀 (부팅 충돌): GPIO 4, 5, 8, 9, 15
🔴 예약 핀 (USB/UART):      GPIO 17(TX), 18(RX), 19(USB D+), 20(USB D-)
🔴 내장 LED:                GPIO 8
```

### 현재 센서와 과거 I2C 이력

- 현재 거리 센서는 AJ-SR04T/JSN-SR04T 계열이며 `PIN_TRIG=10`, `PIN_ECHO=11`이다.
- VL53L0X와 GPIO6/7 I2C는 초기 PoC 이력이며 현재 배선 지시가 아니다.
- `src/main.cpp`의 GPIO6/7 bus-clear는 잔존 정리 대상이므로 두 핀은 충돌 방지를 위해 비워 둔다.
- ECHO가 5 V이면 ESP32-C6 GPIO에 직결하지 말고 검증된 level shifting/divider를 사용한다.

### 릴레이 극성

```
모듈: Low/High Level Trigger 선택형
현재 config.h: RELAY_ACTIVE_LOW = true (점퍼 "L" 위치 가정)
⚠️ 실제 하드웨어 도착 후 점퍼 확인 필수
```

---

## 6. 빌드 환경

```ini
; 올바른 platformio.ini (ESP32-C6)
platform  = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
board     = esp32-c6-devkitc-1
framework = arduino
build_flags =
    -DARDUINO_USB_CDC_ON_BOOT=1  ; 없으면 시리얼 모니터 안 열림
    -DARDUINO_USB_MODE=1
lib_deps  = ArduinoJson, PubSubClient

; 현재 빌드 환경
[env:esp32c6]            ; 기본, ENABLE_HARDWARELESS_RC=0
[env:esp32c6_hwless_rc]  ; 명시적 lab-only, production 승인 아님
```

---

## 7. 코드 컨벤션

```
언어     : C++17 (PlatformIO / Arduino framework)
스타일   : Google C++ Style Guide, 2-space indent
모듈     : 주변기기 1개 = .cpp + .h 파일 1쌍
핀 상수  : 반드시 include/config.h 에서만 정의. 소스에 하드코딩 금지.
에러     : Serial.printf("[ERROR] %s: ...\n", __func__) + 안전한 fallback
로그 접두어:
  [INFO]  정상 동작
  [WARN]  비정상이지만 계속 진행 가능
  [ERROR] 측정/통신 실패 (복구 시도)
  [FATAL] 복구 불가, while(true) 루프로 정지
```

### 파일 네이밍

| 레이어 | 규칙 | 예시 |
|--------|------|------|
| `raw/` | `VENDOR_PART_TYPE.md` | `ST_VL53L0X_Specs.md` |
| `wiki/` | `snake_case.md` | `pin_mapping.md` |
| `src/`, `include/` | `PascalCase` | `UltrasonicSensor.cpp` |

---

## 8. 현재 Open Questions / Release Gates

| # | 질문 | 상태 |
|---|------|------|
| Q1 | 매립 Target을 exact-main signed firmware로 복구·갱신하고 boot health를 확인했는가 | 🔴 Pending |
| Q2 | GPIO3 relay High-Z OFF, ECHO 5 V 보호와 반복 구동을 현장에서 확인했는가 | 🔴 Pending |
| Q3 | Wi-Fi/broker/WAN 장애 자동 복구와 wall-install SLO를 증명했는가 | 🔴 Pending |
| Q4 | Android OEM background와 Hardwareless RC physical Gate를 닫았는가 | 🔴 Pending |

---

## 9. 에이전트 간 협업 에티켓

1. **wiki 먼저, 코드 나중**: 코드를 바꾸면 반드시 관련 wiki도 동기화.
2. **추측 금지**: 불확실한 스펙은 `raw/` 문서에서 확인하고 출처를 코드 주석에 명시.
3. **핀 번호 변경 시**: `config.h` → `pin_mapping.md` → `log.md` 순서로 동시 업데이트.
4. **라이브러리 추가 시**: `platformio.ini` lib_deps + `env_setup.md` + `log.md` 동시 업데이트.
5. **테스트 결과**: `hardware_test.md` 결과 테이블에 날짜/결과/비고 기록.
6. **충돌 방지**: 같은 파일을 수정할 때는 log.md의 최근 항목을 확인해 다른 에이전트의 작업과 겹치지 않도록 한다.
7. **절대 금지**: `raw/` 파일 수정, `log.md` 과거 항목 수정, 핀 번호 하드코딩.

---

## 10. OTA 최상위 불변조건

1. **모바일 앱과 ESP32-C6 Target은 어떤 기능 변경 후에도 OTA 가능한 복구 경로를 유지해야 한다.**
2. 새 BLE 인증, local ACL, FSM, Backend, storage, network 변경은 mobile/Target OTA 비회귀를 증명하기 전 병합·배포하지 않는다.
3. Target은 dual OTA partition, 기존 bootable slot 보존, 새 image health 확인, 실패 rollback을 유지한다. single-slot 파티션으로 변경 금지.
4. Target OTA는 MQTT 단일 trigger에만 의존하지 않고 periodic HTTPS pull과 인증된 local wireless recovery 경로를 유지해야 한다.
5. 모바일 update manager는 BLE scanner, foreground service, WebView, tenant/Target 상태와 독립적으로 접근 가능해야 하며 기존 APK를 실패 시 보존한다.
6. 모바일과 Target은 독립 배포를 전제로 N/N-1 protocol compatibility와 rollback을 검증한다.
7. OTA 성공은 artifact 업로드/PUBACK/download 완료가 아니라 모바일 install 또는 Target install→reboot→health confirmation까지 확인한다.
8. 세부 계약과 release blocking 시험은 `wiki/ota_reliability_contract.md` 및 GitHub issue #23을 따른다.

---

## 11. GitHub 인증·게시 규칙

1. 이 프로젝트의 GitHub CLI와 push 인증은 **현재 프로세스의 `GITHUB_TOKEN` 환경 변수**를 사용한다.
2. 토큰 원문을 콘솔, 로그, wiki, 커밋, `.env`, Git remote URL에 출력하거나 저장하지 않는다.
3. 게시 전에 토큰 존재 여부와 `gh auth status` 성공 여부를 확인한다. 확인 로그에는 원문 대신 존재 여부만 남긴다.
4. sandbox의 socket/network 차단은 토큰 오류가 아니다. 연결 거부·timeout이 보이면 네트워크 권한을 적용해 `gh auth status`를 다시 실행하고, GitHub에 실제로 연결된 결과로 판단한다.
5. GitHub 연결 후에도 401/invalid가 확인된 경우에만 토큰 만료·폐기·권한 부족으로 판정한다. 저장 계정이나 `gh auth login`으로 임의 우회하지 말고 사용자에게 환경 변수 갱신을 요청한다.
6. 인증이 성공한 뒤에만 변경 범위 확인, 명시적 staging, commit, push를 수행한다.
