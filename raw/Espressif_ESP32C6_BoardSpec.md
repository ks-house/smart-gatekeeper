# raw/Espressif_ESP32C6_BoardSpec.md
# ESP32-C6-DevKitC-1 — 보드 사양 레퍼런스
> 모델: ESP32-C6-DevKit C N4R2 / N8R2 / N16R2
> Ingested: 2026-06-27
> Status: Immutable

---

## 1. 칩 개요

| 항목 | ESP32 (구) | **ESP32-C6 (현재 사용)** |
|------|-----------|----------------------|
| 아키텍처 | Xtensa LX6 (32-bit) | **RISC-V (32-bit)** |
| 코어 수 | 2 (동일 성능) | 2 (HP 240MHz + LP 20MHz) |
| Wi-Fi | 802.11 b/g/n (Wi-Fi 4) | **802.11 ax (Wi-Fi 6)** |
| Bluetooth | BT 4.2 Classic + BLE | **BLE 5.3 전용 (Classic 없음)** |
| 추가 무선 | — | **Zigbee 3.0, Thread, Matter** |
| Flash | 4MB | N4=4MB, **N8=8MB, N16=16MB** |
| PSRAM | — | R2=2MB (일부 모델) |
| GPIO 수 | 34 | **23** (총 GPIO23개) |
| ADC | 18채널 | **7채널** (ADC1만, ADC2 없음) |
| 논리 레벨 | 3.3V | **3.3V** |
| 최대 GPIO 전류 | 40mA | **40mA (단, 권장 12mA 이하)** |

---

## 2. PlatformIO 설정 (Arduino 프레임워크)

> ⚠️ **공식 espressif32 플랫폼은 ESP32-C6 Arduino 미지원.**
> pioarduino(커뮤니티 fork) 필수.

```ini
platform = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
board    = esp32-c6-devkitc-1
framework = arduino
build_flags =
    -DARDUINO_USB_CDC_ON_BOOT=1   ; Native USB Serial 활성화 필수
    -DARDUINO_USB_MODE=1
```

---

## 3. GPIO 사용 가이드

### 3-A. 스트래핑 핀 (부팅 시 회로 충돌 위험 — 사용 금지)

| GPIO | 부팅 기능 | 비고 |
|------|---------|------|
| GPIO4 (MTMS) | JTAG / 부팅 모드 | 스트래핑 핀 |
| GPIO5 (MTDI) | JTAG / 플래시 전압 | 스트래핑 핀 |
| GPIO8 | RGB LED (보드 내장) / 스트래핑 | onboard LED |
| GPIO9 | BOOT 버튼 / 스트래핑 | 부팅 후 일반 GPIO 가능 |
| GPIO15 | 스트래핑 | |

### 3-B. 예약 핀 (사용 금지)

| GPIO | 용도 |
|------|------|
| GPIO19 | USB D+ (Native USB) |
| GPIO20 | USB D- (Native USB) |
| GPIO17 | TXD0 (USB-UART 브리지) |
| GPIO18 | RXD0 (USB-UART 브리지) |

### 3-C. 안전하게 사용 가능한 GPIO

```
GPIO0, GPIO1, GPIO2, GPIO3
GPIO6, GPIO7, GPIO10, GPIO11, GPIO12
GPIO13, GPIO14, GPIO16, GPIO21, GPIO22, GPIO23
```

---

## 4. I2C (Wire) 권장 핀

ESP32-C6는 GPIO 매트릭스로 임의 핀에 I2C 라우팅 가능.

| 용도 | 권장 핀 | 비고 |
|------|--------|------|
| SDA | **GPIO6** | 안전 핀, 스트래핑 無 |
| SCL | **GPIO7** | 안전 핀, 스트래핑 無 |

> Arduino 프레임워크에서 **`Wire.begin(SDA, SCL, speed)`** 를 명시하지 않으면
> 컴파일러가 임의 기본값을 사용할 수 있음. **항상 명시 필수.**

---

## 5. 참고 문서

| 문서 | URL |
|------|-----|
| Espressif 공식 DevKitC-1 문서 | https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32c6/esp32-c6-devkitc-1/index.html |
| pioarduino GitHub | https://github.com/pioarduino/platform-espressif32 |
| ESP32-C6 Technical Reference | https://www.espressif.com/sites/default/files/documentation/esp32-c6_technical_reference_manual_en.pdf |
