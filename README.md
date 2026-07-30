# smart-gatekeeper 🚪📡

**smart-gatekeeper**는 ESP32-C6가 송출하는 **BLE 5.3 iBeacon**, Flutter 모바일 앱,
시놀로지 NAS 인증 백엔드, MQTT Pre-arm, 방수 초음파 센서를 결합한 스마트 출입 통제
시스템입니다.

사용자가 공동 현관에 접근하면 스마트폰 앱이 게이트의 iBeacon을 감지하고 NAS에 자격을
확인합니다. 승인된 요청만 MQTT로 ESP32-C6를 사전 무장(Pre-arm)하며, 이후 실제 접근이
초음파 센서로 확인될 때 릴레이를 작동합니다. 전화번호 해시를 BLE UUID에 싣거나
ESP32-C6가 주변 스마트폰을 스캔하지 않습니다.

## 🛠️ 기술 스택 (Tech Stack)

- **게이트 하드웨어:** ESP32-C6-DevKitC-1 N16 (RISC-V, 16 MB Flash),
  AJ-SR04T/JSN-SR04T 방수 초음파 센서, 1채널 5 V Active-LOW 릴레이
- **무선/네트워크:** Wi-Fi 6, **Bluetooth LE 5.3**, HTTPS, MQTTS
- **펌웨어:** C++17, Arduino framework, PlatformIO + pioarduino, Dual-OTA
- **모바일 앱:** Flutter/Android iBeacon 감지, NAS HTTPS Pre-arm 요청, 앱 자체 업데이트
- **백엔드:** Synology NAS Container Manager, FastAPI, MariaDB, MQTT broker
- **운영:** NAS 역방향 프록시 HTTPS, API 키 및 등록 기기 검증, Home Assistant MQTT
  Auto-Discovery, 펌웨어/모바일 앱 OTA

## 📐 v2.0 핵심 흐름

1. **ESP32 iBeacon Advertiser:** ESP32-C6가 고정된 게이트 식별 UUID로 iBeacon을
   상시 송출합니다. 개인 전화번호나 전화번호 해시는 광고 데이터에 포함하지 않습니다.
2. **Flutter 앱 감지:** 세입자 앱이 iBeacon과 RSSI를 감지하면 등록된 기기 ID와 비콘
   정보를 NAS의 HTTPS Pre-arm API로 전송합니다.
3. **NAS HTTPS 인증:** FastAPI가 MariaDB에서 등록 기기와 세입자 승인 상태를 검증합니다.
4. **MQTT Pre-arm:** 인증 성공 시 NAS가 MQTTS `gatekeeper/arm` 토픽을 발행하고,
   ESP32-C6는 제한된 시간 동안만 접근 감지를 활성화합니다.
5. **초음파 확인 및 개방:** AJ-SR04T/JSN-SR04T가 설정 거리 안의 접근을 확인하면
   GPIO23 릴레이로 자동문 무전압 접점을 구동한 뒤 쿨다운 상태로 전환합니다.

이 역할 반전 구조에서는 BLE가 사용자의 비밀 자격 증명이 아니라 게이트 발견 신호이며,
최종 권한 판단은 NAS가 담당합니다.

## 📌 하드웨어 핀 맵 (ESP32-C6-DevKitC-1)

핀 번호의 단일 진실 공급원은 [`include/config.h`](include/config.h)입니다.

| 장치 | 신호 | GPIO | 비고 |
|------|------|------|------|
| AJ-SR04T/JSN-SR04T | TRIG | **GPIO10** | 10 µs 트리거 출력 |
| AJ-SR04T/JSN-SR04T | ECHO | **GPIO11** | ESP32-C6 입력은 3.3 V이므로 센서 출력 전압 확인 및 필요 시 레벨 시프팅 |
| 1채널 5 V 릴레이 | IN | **GPIO23** | Active-LOW, 현재 OFF는 High-Z 방식 |

> `raw/ST_VL53L0X_Specs.md`와 과거 Step 1 BOM은 수정하지 않는 원본 기록이자 역사적
> 참고자료입니다. 현재 장착 거리 센서는 VL53L0X ToF가 아니라
> **AJ-SR04T/JSN-SR04T 초음파 센서**입니다.

## 📁 저장소 구조 (Repository Structure)

```text
smart-gatekeeper/
├── backend/                 # Synology NAS 배포용 FastAPI 서비스
│   ├── app/                 # HTTPS 인증 API 및 MQTT Pre-arm 발행
│   ├── db/schema.sql        # MariaDB 스키마
│   └── docker-compose.yml   # 백엔드 컨테이너 구성
├── gatekeeper_app/          # Flutter 모바일 앱 (iBeacon 감지/HTTPS 인증/앱 업데이트)
├── src/                     # ESP32-C6 펌웨어 구현 (BLE, Wi-Fi, MQTTS, 센서, 릴레이, OTA)
├── include/                 # 펌웨어 헤더와 config.h 핀/설정 단일 공급원
├── raw/                     # 읽기 전용 원본·역사 자료 (현재 구성과 구분)
├── wiki/                    # 아키텍처, 핀 맵, 테스트와 append-only 변경 로그
├── partitions_16MB_ota.csv  # ESP32-C6 N16 Dual-OTA 파티션
├── platformio.ini           # pioarduino 통합 빌드 설정
├── AGENTS.md                # 에이전트 협업 및 v2.0 현행 규칙
└── schema.md                # wiki 거버넌스 규칙
```

개발자는 작업 전에 [`wiki/index.md`](wiki/index.md)와 최근
[`wiki/log.md`](wiki/log.md)를 확인해야 합니다.
