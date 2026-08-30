# pin_mapping.md — 현재 하드웨어 핀 매핑
> Last updated: 2026-08-30 (historical Gatekeeper GPIO23 relay mapping restored in source)

## 1. 실제 펌웨어 핀

| 기능 | ESP32-C6 GPIO | 방향 | 코드 | 주의 |
|---|---:|---|---|---|
| 초음파 TRIG | 10 | OUTPUT | `PIN_TRIG` | 10 µs trigger pulse |
| 초음파 ECHO | 11 | INPUT | `PIN_ECHO` | **센서가 5V ECHO를 내면 저항 분배/레벨 시프터 필수** |
| 릴레이 IN | 23 | OUTPUT(ON) / INPUT(OFF) | `PIN_RELAY` | Active-LOW; OFF는 High-Z; 재설치 펌웨어의 실기기 검증 pending |
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

## 6. SmartBox 배선은 호환되지 않음

`/home/sh-cat-lee/workspaces/smartbox`는 같은 ESP32-C6 계열을 사용하지만
별도 제품이며 핀과 actuator topology가 다르다. SmartBox 배선을 이
Smart Gatekeeper Target에 그대로 적용하지 않는다.

| 기능 | Smart Gatekeeper | SmartBox | 영향 |
|---|---:|---:|---|
| AJ-SR04T TRIG | GPIO10 | GPIO4 | SmartBox 배선에서는 Gatekeeper trigger가 센서에 도달하지 않음 |
| AJ-SR04T ECHO | GPIO11 | GPIO5 | SmartBox 배선에서는 Gatekeeper가 echo를 읽지 못함 |
| 문 개방 relay IN | GPIO23 단일 Active-Low | GPIO6 main, GPIO7/8 direction | Gatekeeper는 GPIO6/7/8 actuator relay를 구동하지 않음 |

Gatekeeper의 GPIO23은 자동문 제어기의 무전압 입력을 위한 단일
COM/NO relay를 구동한다. SmartBox의 GPIO6 main-power와 GPIO7/8
forward/reverse actuator 회로를 대체하지 않는다. 또한 Gatekeeper의
현재 부팅 코드에는 잔존 GPIO6/7 I2C bus-clear가 있으므로 그 두 핀을
relay input에 연결하면 부팅 중 예기치 않은 전위 변화가 생길 수 있다.

배선을 바꾸기 전에 Target, sensor, relay와 door-side load 전원을 모두
차단한다. 첫 재시험은 실제 문 입력을 분리하고 GPIO23 relay 접점과
GPIO10/11 sensor 신호를 계측한 뒤 수행한다. GPIO11에는 5 V ECHO를
직결하지 않는다.

## 7. 저장소 배선 변경 이력 감사

Git history는 다음 세 기준선을 구분한다.

| 날짜/commit | 센서 | relay | 증거 경계 |
|---|---|---:|---|
| 2026-06-27 `e8c01f9` | VL53L0X SDA/SCL GPIO6/7, XSHUT GPIO10 | GPIO3 | 초기 계획; 뒤의 현장 배선 확인 전 |
| 2026-07-24 `ddd7961` | VL53L0X GPIO6/7/10 | GPIO23 | 실제 배선과 sensor/relay/integration PASS가 당시 `hardware_test.md`에 기록됨 |
| 2026-07-27 `f3eee35` | AJ-SR04T TRIG/ECHO GPIO10/11 | GPIO23 | ToF를 ultrasonic으로 교체하고 당시 문서에 배선 완료로 기록 |
| 2026-08-02 `d957718` | AJ-SR04T GPIO10/11 | GPIO3 | Hardwareless GATT 계약 정리와 함께 authoritative pin을 GPIO3으로 변경; 같은 변경이 physical validation pending을 명시 |
| 2026-08-30 source candidate | AJ-SR04T GPIO10/11 | GPIO23 | 소유자가 설치 배선을 확인해 과거 Gatekeeper 조합으로 복원; 빌드·서명 OTA·재부팅 health와 물리 접점 시험은 각각 별도 Gate |

Smart Gatekeeper의 전체 Git history에는 AJ-SR04T GPIO4/5 또는 relay
GPIO6을 정의한 revision이 없다. 그 값은 별도 SmartBox 프로젝트의
배선이다. 따라서 “초기 Gatekeeper 동작 배선으로 복귀”와 “현재
SmartBox식 현장 배선을 firmware가 수용”하는 것은 다른 변경이다.

현재 authoritative 조합은 소유자가 확인한 과거 Gatekeeper 배선인
relay GPIO23과 ultrasonic GPIO10/11이다. SmartBox GPIO4/5/6 배선은
지원하지 않는다. 서명 OTA 적용 후에도 GPIO11 ECHO 전압, relay 접점과
실제 문 동작은 별도 현장 증거로 확인해야 한다.
