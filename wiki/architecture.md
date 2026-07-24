# architecture.md — 시스템 아키텍처 및 로드맵
> Last updated: 2026-07-24 (Step 3 & OTA/MQTTS 통합 완료)

---

## 1. 시스템 아키텍처 개요

`smart-gatekeeper`는 ESP32-C6 (RISC-V) 기반 출입 통제 컨트롤러로, ToF 레이저 센서 감지 ➔ 시놀로지 NAS HTTPS 자격 검증 API ➔ 1채널 릴레이 스위칭 ➔ MQTTS (TLS 4883) Home Assistant 자동 검색 & 텔레메트리 ➔ GitHub CI/CD SFTP OTA 파이프라인으로 구성되어 있습니다.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   smart-gatekeeper                                     │
│                                                                                        │
│  [VL53L0X ToF (GPIO6/7)] ───► [ESP32-C6 Controller] ───► [Relay (GPIO23)] ──► [도어락] │
│                                       │                                                │
│                 ┌─────────────────────┼─────────────────────┐                          │
│                 ▼                     ▼                     ▼                          │
│       [WiFi CaptivePortal]    [HTTPS API Client]     [MQTTS HA Discovery]              │
│       (SmartGatekeeper-Setup)  (tworimpa:4442)         (tworimpa:4883)                 │
│                                       │                     │                          │
│                                       ▼                     ▼                          │
│                                [FastAPI + MariaDB]   [Home Assistant]                  │
│                                (Synology NAS)        (Auto-Discovery)                  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 전체 통합 시퀀스 다이어그램 (Sequence Diagram)

### 2.1. E2E 출입 감지 & 자격 검증 시퀀스

```mermaid
sequenceDiagram
    autonumber
    actor Person as 출입자/사용자
    participant ToF as VL53L0X ToF 센서
    participant ESP as ESP32-C6 (Main & FSM)
    participant Relay as 릴레이 모듈 (GPIO23)
    participant NAS as Synology NAS (FastAPI)
    participant DB as MariaDB (Tenants)
    participant HA as Home Assistant (MQTTS)

    Person->>ToF: 센서 50cm 이내 접근 (<= 500mm)
    ToF->>ESP: Distance Reading (e.g. 350mm)
    ESP->>ESP: FSM State: IDLE -> VERIFYING
    ESP->>HA: MQTTS Publish event: gate_trigger
    
    ESP->>NAS: HTTPS POST /api/v1/auth/verify (JSON: ble_mac, auth_key, distance_mm)
    NAS->>DB: Query tenant qualification (ble_mac)
    DB-->>NAS: Tenant valid (granted=True, "홍길동", "101호")
    NAS-->>ESP: HTTP 200 JSON {"granted": true, "message": "자격 검증 성공"}

    alt 자격 검증 승인 (granted == true)
        ESP->>Relay: relayOn() (pinMode OUTPUT + LOW) [딸깍!]
        ESP->>ESP: FSM State: VERIFYING -> RELAY_HOLD (1000ms 유지)
        ESP->>HA: MQTTS Publish event: door_open
        Note over Relay: 1초간 출입문 잠금 해제 유지
        ESP->>Relay: relayOff() (pinMode INPUT High-Z) [딸깍!]
        ESP->>ESP: FSM State: RELAY_HOLD -> COOLDOWN (2000ms)
        ESP->>HA: MQTTS Publish event: door_close
        ESP->>ESP: FSM State: COOLDOWN -> IDLE
    else 자격 검증 거부 (granted == false)
        ESP->>ESP: 릴레이 미작동 -> COOLDOWN (2000ms)
        ESP->>HA: MQTTS Publish event: door_deny
        ESP->>ESP: FSM State: COOLDOWN -> IDLE
    end
```

### 2.2. MQTTS HA Auto-Discovery & 원격 개방 시퀀스

```mermaid
sequenceDiagram
    autonumber
    participant HA as Home Assistant
    participant MQTT as Mosquitto Broker (Port 4883)
    participant ESP as ESP32-C6 (MqttManager)
    participant Relay as 릴레이 모듈 (GPIO23)

    Note over ESP,MQTT: TLS Root CA (ISRG Root X1) Certificate Pinning 접속
    ESP->>MQTT: MQTTS Connect (tworimpa.synology.me:4883)
    MQTT-->>ESP: Connected
    ESP->>MQTT: Subscribe "smart-gatekeeper/cmd"
    ESP->>MQTT: Publish Auto-Discovery Configs (homeassistant/button/..., homeassistant/sensor/...)
    MQTT-->>HA: Register Entities (button.open_gate, sensor.distance, etc.)

    Note over HA,ESP: 원격 출입문 개방 명령 트리거
    HA->>MQTT: Publish "smart-gatekeeper/cmd" {"command": "open_gate"}
    MQTT->>ESP: Message Received
    ESP->>ESP: callback() -> triggerManualDoorOpen()
    ESP->>Relay: relayOn() (1000ms ON)
    Note over Relay: 출입문 릴레이 1초간 ON
    ESP->>Relay: relayOff()
```

### 2.3. GitHub CI/CD & 무선 OTA 배포 시퀀스

```mermaid
sequenceDiagram
    autonumber
    actor Dev as 개발자
    participant Git as GitHub Repository
    participant Action as GitHub Actions CI
    participant NAS as Synology NAS (SFTP)
    participant ESP as ESP32-C6 (OtaManager)

    Dev->>Git: git push origin main
    Git->>Action: Trigger deploy.yml Workflow
    Action->>Action: Build firmware.bin (PLATFORMIO_BUILD_FLAGS: -DFIRMWARE_VERSION_OVERRIDE="1.0.0-g<sha>")
    Action->>Action: Generate version.json
    Action->>NAS: SFTP Upload to /volume1/docker/smart-gatekeeper-ota/

    Note over ESP,NAS: ESP32-C6 부팅 또는 1시간 주기 OTA 체크
    ESP->>NAS: GET https://tworimpa.synology.me:4443/firmware/version.json
    NAS-->>ESP: Return version.json {"version": "1.0.0-g<sha>", ...}
    alt 신규 버전 감지
        ESP->>NAS: GET https://tworimpa.synology.me:4443/firmware/gatekeeper-firmware.bin
        NAS-->>ESP: Stream firmware binary
        ESP->>ESP: HTTPUpdate Flash Memory
        ESP->>ESP: ESP.restart() (새 펌웨어 부팅)
    end
```

---

## 3. 단계별 로드맵 및 상태

| 단계 | 이름 | 목표 | 상태 |
|------|------|------|------|
| **Step 1** | Local PoC | ToF + Relay 단독 및 로컬 연동 검증 | 🟢 **완료** (2026-07-24) |
| **Step 2** | 백엔드 구축 | 시놀로지 NAS FastAPI + MariaDB Docker 구축 & HTTPS API 검증 | 🟢 **완료** (2026-07-24) |
| **Step 3** | WiFi + NAS 연동 | ESP32-C6 WiFi/CaptivePortal + NAS HTTPS 자격검증 및 릴레이 연동 | 🟢 **완료** (2026-07-24) |
| **Step 4** | MQTTS & OTA | HA Auto-Discovery, MQTTS 4883 TLS Pinning, GitHub CI/CD SFTP OTA | 🟢 **완료** (2026-07-24) |
| **Step 5** | BLE / 방향 감지 | 스마트폰 BLE 키 인증 및 2채널 ToF IN/OUT 판별 | 🔲 미시작 |
| **Step 6** | 프로덕션 | PCB 설계, 케이스, 양산 가공 | 🔲 미시작 |

---

## 4. 소프트웨어 구조

```
smart-gatekeeper/
├── include/
│   ├── config.h          — 전역 핀 매핑 및 임계값 설정
│   ├── ConfigManager.h   — Preferences NVS 설정 관리
│   ├── MqttManager.h     — MQTTS TLS (4883) & HA Auto-Discovery
│   ├── OtaManager.h      — HTTPS OTA 무선 업데이트
│   ├── ToFSensor.h       — VL53L0X 드라이버 래퍼
│   ├── secrets.h         — 보안 자격 증명 (Git 제외)
│   └── secrets.h.example — 보안 템플릿
├── src/
│   ├── main.cpp          — 메인 루프 & FSM
│   ├── ConfigManager.cpp
│   ├── MqttManager.cpp
│   ├── OtaManager.cpp
│   ├── ToFSensor.cpp
│   └── WifiManager.cpp   — Captive Portal AP 설정
├── backend/
│   ├── app/main.py       — FastAPI REST API (/api/v1/auth/verify)
│   ├── docker-compose.yml
│   └── init.sql          — MariaDB DDL 스키마
└── .github/workflows/
    └── deploy.yml        — GitHub CI/CD 빌드 및 SFTP 자동 배포
```
