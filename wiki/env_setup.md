# env_setup.md — 개발 환경 세팅 가이드
> Phase: Step 1 (Local PoC)
> Last updated: 2026-06-26

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
