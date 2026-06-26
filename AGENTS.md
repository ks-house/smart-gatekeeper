# AGENTS.md — smart-gatekeeper Agent Collaboration Guide
> **이 파일을 읽는 모든 AI 에이전트(Gemini, Claude, Antigravity 등)에게:**
> 작업 시작 전 반드시 이 문서 전체를 읽고, 지침을 엄수하라.
> Last updated: 2026-06-27

---

## 0. TL;DR (30초 요약)

```
프로젝트  : ESP32-C6 기반 BLE + ToF 스마트 출입 통제 시스템
현재 단계 : Step 1 — 로컬 PoC (하드웨어 단독 테스트)
MCU       : ESP32-C6-DevKitC-1 (RISC-V, NOT Xtensa)
플랫폼    : pioarduino (공식 espressif32 사용 금지)
I2C 핀    : SDA=GPIO6, SCL=GPIO7 (GPIO21/22 절대 사용 금지)
금지 핀   : GPIO 4,5,8,9,15 (스트래핑), 17,18,19,20 (USB/UART)
지식베이스: wiki/index.md 를 먼저 읽어라
로그      : wiki/log.md 에 반드시 기록하라
```

---

## 1. 프로젝트 개요

### 목표
시놀로지 NAS 백엔드 연동형 스마트폰 BLE + ToF 레이저 출입 통제 시스템.

### 5단계 로드맵

| 단계 | 이름 | 상태 |
|------|------|------|
| **Step 1** | Local PoC — ToF + Relay 하드웨어 단독 검증 | 🟡 **현재 진행 중** |
| Step 2 | BLE 연동 — 스마트폰 ↔ ESP32 잠금/해제 | 🔲 |
| Step 3 | WiFi + MQTT — 시놀로지 NAS 연동 | 🔲 |
| Step 4 | 방향 감지 — ToF 2채널 IN/OUT 판별 | 🔲 |
| Step 5 | 프로덕션 — PCB, OTA, 케이스 가공 | 🔲 |

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

| type | 용도 |
|------|------|
| `ingest` | raw/ 에 새 소스 추가 |
| `compile` | wiki 페이지 신규/수정 |
| `code` | 펌웨어 소스 추가/수정 |
| `test` | 하드웨어 테스트 결과 기록 |
| `fix` | 오류 수정 |
| `lint` | 링크·일관성 검사 |

---

## 5. 하드웨어 제약 (반드시 암기)

### MCU: ESP32-C6-DevKitC-1

> ⚠️ 구형 ESP32(Xtensa)와 **완전히 다른 칩**이다. GPIO 번호를 혼동하지 마라.

| 항목 | 값 |
|------|-----|
| 아키텍처 | **RISC-V** (Xtensa 아님) |
| Bluetooth | **BLE 5.3 전용** (Classic BT 없음) |
| Logic level | **3.3V** |
| I2C SDA | **GPIO 6** |
| I2C SCL | **GPIO 7** |
| Relay IN | **GPIO 3** |
| ToF XSHUT | GPIO 10 (선택) |

### 절대 사용 금지 핀

```
🔴 스트래핑 핀 (부팅 충돌): GPIO 4, 5, 8, 9, 15
🔴 예약 핀 (USB/UART):      GPIO 17(TX), 18(RX), 19(USB D+), 20(USB D-)
🔴 내장 LED:                GPIO 8
```

### VL53L0X 함정 (데이터시트 기반)

```cpp
// ✅ 올바른 초기화
Wire.begin(6, 7, 400000UL);  // 400kHz 반드시 명시
sensor.setTimeout(500);       // init() 전에 설정 필수

// ✅ 올바른 읽기 (65535 sentinel 반드시 체크)
uint16_t mm = sensor.readRangeContinuousMillimeters();
if (mm == 65535 || sensor.timeoutOccurred()) { /* 에러 처리 */ }

// ❌ 잘못된 초기화 (절대 금지)
Wire.begin(21, 22);   // 구 ESP32 핀, C6에서 동작 불보장
Wire.begin(6, 7);     // 100kHz 기본값 → 지연 발생
```

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
lib_deps  = pololu/VL53L0X @ ^1.3.1

; 빌드 환경 3개
[env:esp32c6]    ; 통합 빌드 (기본)
[env:tof_test]   ; -DTEST_TOF_ONLY
[env:relay_test] ; -DTEST_RELAY_ONLY
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
| `src/`, `include/` | `PascalCase` | `ToFSensor.cpp` |

---

## 8. 현재 Open Questions (작업 시 참고)

| # | 질문 | 상태 |
|---|------|------|
| Q2 | 릴레이 점퍼 실제 위치 확인 | 🟡 하드웨어 도착 후 확인 필요 |
| Q3 | ToF 센서 1개 vs 2개 (방향 감지 필요?) | 🔴 미결 |
| Q4 | BLE 스택 선택 (NimBLE 권장) | 🔴 Step 2 진입 시 결정 |

---

## 9. 에이전트 간 협업 에티켓

1. **wiki 먼저, 코드 나중**: 코드를 바꾸면 반드시 관련 wiki도 동기화.
2. **추측 금지**: 불확실한 스펙은 `raw/` 문서에서 확인하고 출처를 코드 주석에 명시.
3. **핀 번호 변경 시**: `config.h` → `pin_mapping.md` → `log.md` 순서로 동시 업데이트.
4. **라이브러리 추가 시**: `platformio.ini` lib_deps + `env_setup.md` + `log.md` 동시 업데이트.
5. **테스트 결과**: `hardware_test.md` 결과 테이블에 날짜/결과/비고 기록.
6. **충돌 방지**: 같은 파일을 수정할 때는 log.md의 최근 항목을 확인해 다른 에이전트의 작업과 겹치지 않도록 한다.
7. **절대 금지**: `raw/` 파일 수정, `log.md` 과거 항목 수정, 핀 번호 하드코딩.
