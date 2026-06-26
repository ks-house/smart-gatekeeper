# env_setup.md — 개발 환경 세팅 가이드
> Phase: Step 1 (Local PoC)
> Last updated: 2026-06-27

---

## 1. 툴체인 선택: PlatformIO (VS Code)

> **결정 근거**: Arduino IDE 대비 PlatformIO는 의존성 관리(`platformio.ini`), 다중 타깃 빌드, CI 친화적 구조를 제공한다. 이미 `smartbox` 프로젝트에서 PlatformIO를 사용 중이므로 일관성을 유지한다.

### 설치 순서

```
1. VS Code 설치 (https://code.visualstudio.com)
2. Extension: PlatformIO IDE 설치
3. Extension: C/C++ (Microsoft) 설치
```

> ⚠️ Arduino IDE를 반드시 써야 한다면 → [별첨 A: Arduino IDE 세팅](#별첨-a-arduino-ide-세팅) 참조

---

## 2. platformio.ini 구성

> ⚠️ **ESP32-C6는 공식 `espressif32` 플랫폼이 아닌 `pioarduino` 커뮤니티 fork를 사용해야 한다.**
> 공식 플랫폼은 ESP32-C6의 Arduino 3.x 코어를 지원하지 않아 빌드가 불가능하다.

```ini
[platformio]
default_envs = esp32c6

[common]
; pioarduino: ESP32-C6 Arduino 3.x 코어 지원하는 커뮤니티 fork
platform      = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
board         = esp32-c6-devkitc-1
framework     = arduino
monitor_speed = 115200
build_flags   =
    -DCORE_DEBUG_LEVEL=3
    -Wall
    ; ESP32-C6 Native USB CDC 활성화 (없으면 시리얼 모니터 안 열림)
    -DARDUINO_USB_CDC_ON_BOOT=1
    -DARDUINO_USB_MODE=1
lib_deps      =
    pololu/VL53L0X @ ^1.3.1

; 통합 빌드 (기본)
[env:esp32c6]
platform      = ${common.platform}
board         = ${common.board}
framework     = ${common.framework}
monitor_speed = ${common.monitor_speed}
build_flags   = ${common.build_flags}
lib_deps      = ${common.lib_deps}

; ToF 단독 테스트
[env:tof_test]
platform      = ${common.platform}
board         = ${common.board}
framework     = ${common.framework}
monitor_speed = ${common.monitor_speed}
build_flags   =
    ${common.build_flags}
    -DTEST_TOF_ONLY
lib_deps      = ${common.lib_deps}

; 릴레이 단독 테스트
[env:relay_test]
platform      = ${common.platform}
board         = ${common.board}
framework     = ${common.framework}
monitor_speed = ${common.monitor_speed}
build_flags   =
    ${common.build_flags}
    -DTEST_RELAY_ONLY
lib_deps      = ${common.lib_deps}
```

---

## 3. 라이브러리 선택 근거

### VL53L0X 라이브러리 비교

| 라이브러리 | 저자 | 크기 | 특이사항 |
|-----------|------|------|---------|
| `pololu/VL53L0X` ✅ | Pololu | 경량 | 순수 C++, ST HAL 불필요, ESP32 완전 호환 |
| `adafruit/Adafruit_VL53L0X` | Adafruit | 중간 | ST HAL 래핑, 추가 의존성 있음 |
| ST 공식 API | ST Micro | 대형 | HAL 포팅 필요, 임베디드 전문가용 |

**선택: `pololu/VL53L0X`** — 코드가 단순하고 ESP32 I2C와 직접 연동, 예외처리가 명확함.

---

## 4. 프로젝트 디렉토리 구조

```
smart-gatekeeper/
├── platformio.ini
├── src/
│   ├── main.cpp                ← 진입점 (빌드 플래그로 테스트 모드 전환)
│   ├── ToFSensor.cpp           ← VL53L0X 드라이버 구현
│   └── RelayController.cpp    ← 릴레이 드라이버 구현
├── include/
│   ├── config.h               ← 핀 상수 및 전역 설정 (하드코딩 금지)
│   ├── ToFSensor.h
│   └── RelayController.h
└── wiki/ raw/ schema.md       ← 위키
```

---

## 5. 빌드 환경별 업로드 명령

| 환경 | 명령 | 설명 |
|------|------|------|
| 통합 빌드 | `pio run -e esp32c6 -t upload` | ToF + Relay 통합 데모 |
| ToF 단독 | `pio run -e tof_test -t upload` | ToF 센서 단독 테스트 |
| 릴레이 단독 | `pio run -e relay_test -t upload` | 릴레이 단독 테스트 |
| 시리얼 모니터 | `pio device monitor --baud 115200` | 로그 출력 확인 |

---

## 6. 첫 빌드 확인 체크리스트

- [ ] `pio run -e esp32c6` 실행 시 컴파일 오류 없음
- [ ] `pio device monitor` 로 시리얼 연결 확인 (115200 baud)
- [ ] `pio lib list` 에서 `VL53L0X` 확인
- [ ] 시리얼 모니터에 `smart-gatekeeper — Step 1 PoC` 출력 확인

---

## 별첨 A: Arduino IDE 세팅

PlatformIO 없이 Arduino IDE 2.x를 사용하는 경우:

> ⚠️ ESP32-C6는 `esp32 by Espressif Systems` **v3.x** 이상이 필요하다. v2.x는 C6 미지원.

1. File → Preferences → Additional boards manager URLs:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
2. Tools → Board → Boards Manager → `esp32 by Espressif Systems` 설치 (**v3.x** 권장)
3. Sketch → Library Manager → `VL53L0X by Pololu` 검색 후 설치
4. Tools → Board → `ESP32C6 Dev Module` 선택
5. Tools → Port → 해당 COM 포트 선택
6. Tools → USB CDC On Boot → `Enabled` (시리얼 모니터 활성화 필수)


---

## 1. 툴체인 선택: PlatformIO (VS Code)

> **결정 근거**: Arduino IDE 대비 PlatformIO는 의존성 관리(`platformio.ini`), 다중 타깃 빌드, CI 친화적 구조를 제공한다. 이미 `smartbox` 프로젝트에서 PlatformIO를 사용 중이므로 일관성을 유지한다.

### 설치 순서

```
1. VS Code 설치 (https://code.visualstudio.com)
2. Extension: PlatformIO IDE 설치
3. Extension: C/C++ (Microsoft) 설치
```

> ⚠️ Arduino IDE를 반드시 써야 한다면 → [별첨 A: Arduino IDE 세팅](#별첨-a-arduino-ide-세팅) 참조

---

## 2. platformio.ini 구성

```ini
[env:esp32dev]
platform  = espressif32
board     = esp32dev
framework = arduino

; 시리얼 모니터 속도
monitor_speed = 115200

; 필수 라이브러리
lib_deps =
    pololu/VL53L0X @ ^1.3.1   ; ToF 거리 센서 드라이버 (순수 C++, HAL 불필요)

; 빌드 플래그 (strict warnings)
build_flags =
    -DCORE_DEBUG_LEVEL=3
    -Wall
```

---

## 3. 라이브러리 선택 근거

### VL53L0X 라이브러리 비교

| 라이브러리 | 저자 | 크기 | 특이사항 |
|-----------|------|------|---------|
| `pololu/VL53L0X` ✅ | Pololu | 경량 | 순수 C++, ST HAL 불필요, ESP32 완전 호환 |
| `adafruit/Adafruit_VL53L0X` | Adafruit | 중간 | ST HAL 래핑, 추가 의존성 있음 |
| ST 공식 API | ST Micro | 대형 | HAL 포팅 필요, 임베디드 전문가용 |

**선택: `pololu/VL53L0X`** — 코드가 단순하고 ESP32 I2C와 직접 연동, 예외처리가 명확함.

---

## 4. 프로젝트 디렉토리 초기화

```
smart-gatekeeper/
├── platformio.ini
├── src/
│   ├── main.cpp          ← 진입점 (빌드 환경별 조건부 컴파일)
│   ├── ToFSensor.h/.cpp  ← VL53L0X 드라이버 래퍼
│   └── RelayController.h/.cpp
├── include/
│   └── config.h          ← 핀 상수 및 전역 설정
└── wiki/ raw/ schema.md  ← 위키
```

---

## 5. 첫 빌드 확인 체크리스트

- [ ] `pio run` 실행 시 컴파일 오류 없음
- [ ] `pio device monitor` 로 시리얼 연결 확인 (115200 baud)
- [ ] `pio lib list` 에서 `VL53L0X` 확인

---

## 별첨 A: Arduino IDE 세팅

PlatformIO 없이 Arduino IDE 2.x를 사용하는 경우:

1. File → Preferences → Additional boards manager URLs:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
2. Tools → Board → Boards Manager → `esp32 by Espressif Systems` 설치 (v2.x 권장)
3. Sketch → Library Manager → `VL53L0X by Pololu` 검색 후 설치
4. Tools → Board → `ESP32 Dev Module` 선택
5. Tools → Port → 해당 COM 포트 선택
6. Tools → Upload Speed → `921600`
