# pin_mapping.md — 핀 매핑 마스터 테이블
> MCU: **ESP32-C6-DevKitC-1** (RISC-V, 3.3V)
> Phase: Step 1 (Local PoC)
> Last updated: 2026-06-27
> ⚠️ Open Question #2: 릴레이 모듈 극성(Active-HIGH/LOW) 확인 필요

---

## 1. ESP32-C6-DevKitC-1 GPIO 사용 가능 여부

```
┌─────────────────────────────────────────────────────────┐
│            ESP32-C6-DevKitC-1 핀 사용 분류             │
├──────────┬─────────────────────────────────────────────┤
│ 🔴 금지  │ GPIO4, GPIO5        (JTAG 스트래핑)        │
│ 🔴 금지  │ GPIO8               (보드 내장 RGB LED)     │
│ 🔴 금지  │ GPIO9               (BOOT 버튼, 스트래핑)  │
│ 🔴 금지  │ GPIO15              (스트래핑)              │
│ 🔴 금지  │ GPIO17, GPIO18      (USB-UART TXD0/RXD0)   │
│ 🔴 금지  │ GPIO19, GPIO20      (USB D+/D-)             │
├──────────┼─────────────────────────────────────────────┤
│ 🟢 사용  │ GPIO0, 1, 2, 3, 6, 7, 10, 11, 12          │
│ 가능     │ GPIO13, 14, 16, 21, 22, 23                 │
└──────────┴─────────────────────────────────────────────┘
```

---

## 2. I2C 버스 — VL53L0X ToF 센서

| ESP32-C6 핀 | GPIO# | VL53L0X 핀 | 비고 |
|------------|-------|----------|------|
| SDA | **GPIO6** | SDA | ✅ 안전 핀 (스트래핑 無) |
| SCL | **GPIO7** | SCL | ✅ 안전 핀 (스트래핑 無) |
| 3.3V | 3V3 | VIN / VDD | **반드시 3.3V** — 5V 인가 시 센서 손상 |
| GND | GND | GND | |
| (선택) GPIO10 | GPIO10 | XSHUT | 센서 하드 리셋 / 다중 센서 주소 변경용 |

> ⚠️ **구 ESP32 핀(GPIO21/22)은 사용 금지**: C6에서 용도가 다를 수 있음.
> ⚠️ **VL53L0X는 3.3V only** — 5V 공급 시 즉시 파손.

### I2C 초기화 코드 (필수)
```cpp
// ESP32-C6에서는 항상 핀과 속도를 명시해야 함
Wire.begin(6, 7, 400000UL);  // SDA=GPIO6, SCL=GPIO7, 400kHz
```

### I2C 기본 주소
- `0x29` (7-bit)

---

## 3. 릴레이 모듈 (1채널 5V)

| ESP32-C6 핀 | GPIO# | 릴레이 모듈 핀 | 비고 |
|------------|-------|------------|------|
| GPIO3 | **GPIO3** | IN (Signal) | ✅ 안전 핀. Active-LOW: LOW=ON ⚠️ 극성 확인 필요 |
| 5V (VIN) | 5V | VCC | 릴레이 코일 구동 전원 (USB 5V에서 직접) |
| GND | GND | GND | ESP32-C6 GND와 공통 접지 필수 |

> ⚠️ **안전 주의사항**:
> 1. ESP32-C6 GPIO: 권장 최대 **12mA**. 릴레이 코일 직접 구동 불가.
> 2. 오토커플러(광절연) 내장 모듈이라면 GPIO 직결 가능.
> 3. 오토커플러 없는 모듈이라면 **NPN 트랜지스터(S8050)** + 플라이백 다이오드 필요.
> 4. 릴레이 접점에 AC 연결 시 반드시 절연 및 안전 거리 확보.

---

## 4. 전체 배선 요약

```
[VL53L0X] ──3.3V──┐
                   ├── ESP32-C6 3V3
[릴레이 VCC]──5V──┘    (별도 5V rail)

[VL53L0X SDA]  ──── GPIO6
[VL53L0X SCL]  ──── GPIO7
[VL53L0X GND]  ──── GND ──── [릴레이 GND]
[릴레이 IN]    ──── GPIO3
[VL53L0X XSHUT]──── GPIO10  (선택)
```

---

## 5. `config.h` 상수 정의 (참조용)

```cpp
// include/config.h (현재 값)
constexpr uint8_t PIN_SDA        = 6;   // I2C SDA (ESP32-C6 안전 핀)
constexpr uint8_t PIN_SCL        = 7;   // I2C SCL (ESP32-C6 안전 핀)
constexpr uint8_t PIN_TOF_XSHUT  = 10;  // VL53L0X XSHUT (선택)
constexpr uint8_t PIN_RELAY      = 3;   // 릴레이 IN (안전 핀)
constexpr bool    RELAY_ACTIVE_LOW = true;  // ⚠️ 모듈 확인 후 수정
```

---

## 6. 이전 ESP32 (Xtensa) vs 현재 ESP32-C6 핀 비교

| 기능 | 구 ESP32 (잘못된 설정) | **ESP32-C6 (현재)** |
|------|---------------------|-------------------|
| I2C SDA | GPIO21 | **GPIO6** |
| I2C SCL | GPIO22 | **GPIO7** |
| Relay IN | GPIO26 | **GPIO3** |
| ToF XSHUT | GPIO16 | **GPIO10** |
