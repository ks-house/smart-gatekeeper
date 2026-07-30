# pin_mapping.md — 현재 하드웨어 핀 매핑
> Last updated: 2026-07-30 (AJ-SR04T current-code audit)

## 1. 실제 펌웨어 핀

| 기능 | ESP32-C6 GPIO | 방향 | 코드 | 주의 |
|---|---:|---|---|---|
| 초음파 TRIG | 10 | OUTPUT | `PIN_TRIG` | 10 µs trigger pulse |
| 초음파 ECHO | 11 | INPUT | `PIN_ECHO` | **센서가 5V ECHO를 내면 저항 분배/레벨 시프터 필수** |
| 릴레이 IN | 23 | OUTPUT(ON) / INPUT(OFF) | `PIN_RELAY` | Active-LOW; OFF는 High-Z |
| Native USB D+ / D- | 19 / 20 | 예약 | USB CDC | 사용 금지 |

현재 런타임 거리 센서는 AJ-SR04T/JSN-SR04T 계열이며 VL53L0X는 제거되었습니다. GPIO6/7은 센서 핀이 아닙니다.

## 2. 회피 핀

| 분류 | GPIO | 정책 |
|---|---|---|
| Strapping | 4, 5, 8, 9, 15 | 부팅 충돌 위험으로 사용 금지 |
| UART/USB | 17, 18, 19, 20 | 프로젝트 예약, 주변기기 연결 금지 |
| 내장 LED | 8 | strapping과 중복, 사용 금지 |

GPIO21/22는 현재 보드에서 일반 GPIO 후보일 수 있으나 이 프로젝트에는 배정하지 않습니다. 과거 문서의 “기본 I²C 21/22” 또는 현재 센서용 “I²C 6/7” 배선은 적용하지 마세요.

## 3. 전기 안전

- ESP32-C6 GPIO는 3.3V 로직입니다. 5V ECHO를 GPIO11에 직결하지 않습니다.
- 릴레이 접점(COM/NO/NC)과 코일/입력 전원을 구분하고 자동문에는 무전압 접점만 연결합니다.
- Active-LOW 릴레이 OFF는 현재 호환성 때문에 `INPUT` High-Z를 사용합니다. 이는 보드/모듈 조합에 의존하므로 풀업, 옵토커플러, 역전류를 실측해야 합니다.
- 코일 역기전력 억제, 공통 GND 구성, 별도 전원 또는 광절연을 권장합니다.

## 4. 잔존 I²C 복구 코드

`src/main.cpp`는 부팅 때 GPIO6/7에 I²C bus-clear 펄스를 보내지만 현재 초음파 센서는 I²C를 사용하지 않습니다. 코드와 배선이 충돌하지 않도록 GPIO6/7을 비워 두고, 이 루틴의 필요성은 다음 펌웨어 정리에서 재평가합니다. 이는 현재 센서 배선 지시가 아닙니다.

## 5. 주요 무선·동작 기본값

| 값 | 기본값 |
|---|---:|
| iBeacon interval | 100 ms |
| BLE Tx power | +9 dBm |
| Pre-arm | 60 s |
| 초음파 유효 하한 | 20 cm |
| 접근 임계값 | 50 cm (NVS/MQTT 20–200 cm) |
| 릴레이 hold | 1 s |
| Target cooldown | 3 s |
