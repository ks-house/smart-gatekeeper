# relay_troubleshooting_guide.md — 릴레이 Freeze 진단 가이드
> Last updated: 2026-07-30 (current-code audit)

## 1. 증상과 안전 우선순위

릴레이가 반복 동작 뒤 응답하지 않고 소프트 리셋으로도 복구되지 않으며 전원 재인가가 필요한 현상은 단순 상태 머신보다 **5V 역전류, 코일/부하 노이즈, 전원 강하, ESP32 GPIO latch-up**을 먼저 의심합니다. 원인이 확정되기 전에는 무인 운용하지 않습니다.

## 2. 현재 펌웨어 동작

`RelayController`의 Active-LOW 경로는 다음과 같습니다.

| 논리 상태 | GPIO3 모드/레벨 | 이유와 한계 |
|---|---|---|
| ON | OUTPUT + LOW | 릴레이 입력 전류 sink |
| OFF | INPUT High-Z | 이 모듈에서는 OUTPUT HIGH 3.3V로 5V 입력을 완전히 끄지 못해 채택 |

과거 문서의 “INPUT 트릭 제거 후 push-pull HIGH가 해결책”은 실제 모듈에서 릴레이가 상시 ON이 되어 되돌려졌습니다. 반대로 High-Z가 보편적으로 안전하다는 뜻도 아닙니다. 모듈 내부 5V pull-up이 GPIO3으로 유입되면 ESP32-C6 절대정격을 위반할 수 있으므로 **보드 입력 전압과 역전류를 실측**해야 합니다.

## 3. 권장 하드웨어 개선

1. ESP32와 릴레이 입력 사이에 3.3V 호환 optocoupler 또는 NPN/MOSFET driver를 둡니다.
2. 릴레이 모듈에 flyback diode가 없으면 코일 양단에 극성을 맞춰 추가합니다.
3. 자동문/모터 등 외부 인덕티브 부하는 릴레이 코일 보호와 별개로 부하에 맞는 snubber/diode를 적용합니다.
4. MCU와 릴레이 전원을 분리하거나 충분한 regulator 여유를 두고, 릴레이 근처에 bulk + ceramic decoupling을 배치합니다.
5. 접점(COM/NO/NC)은 무전압 접점으로만 사용하고 저전압 제어부와 고전압 배선을 격리합니다.

## 4. 단계별 진단

1. 릴레이 모듈을 분리한 채 Target이 24시간 Wi-Fi/BLE/MQTT를 유지하는지 확인합니다.
2. GPIO3 OFF 상태 전압과 ESP32 3.3V rail로 흐르는 전류를 측정합니다.
3. oscilloscope로 릴레이 ON/OFF 순간 5V/3.3V rail dip과 GPIO overshoot를 기록합니다.
4. 릴레이만 100회 이상 구동해 reset reason, 광고 지속, MQTT heartbeat를 확인합니다.
5. 실제 자동문 접점을 연결한 상태에서 다시 반복하여 부하측 노이즈를 분리합니다.
6. freeze 시 전원/EN reset/소프트 reset 각각의 복구 여부와 serial boot log를 보존합니다.

## 5. I²C bus-clear에 대한 현재 판정

`src/main.cpp`에는 GPIO6/7 bus-clear 루틴이 남아 있지만 현재 AJ-SR04T 센서는 I²C를 사용하지 않습니다. 따라서 이 루틴은 릴레이 freeze의 일반 해결책으로 간주하지 않습니다. GPIO6/7에 실제 I²C 장치가 없다면 제거 후보이며, 현행 배선에서는 두 핀을 비워 둡니다.

## 6. 합격 기준

- GPIO3에 3.3V 허용 범위를 넘는 전압/역전류가 없음
- 100회 이상 반복에서 relay miss, MCU reset, BLE 광고 중단 없음
- 전원 재인가 없이 fault recovery 가능
- 24시간 RF/network soak 동안 MQTT heartbeat와 beacon interval 유지
- 측정 장비, 회로, firmware commit, 반복 횟수를 `hardware_test.md`에 기록
