# architecture.md — 시스템 아키텍처 및 로드맵
> Last updated: 2026-07-24 (Step 4 스마트 BLE 우선 인증 & 쿨다운 동적 리셋 FSM 개편 완료 🟢)

---

## 1. 시스템 아키텍처 개요

`smart-gatekeeper`는 ESP32-C6 (RISC-V) 기반 출입 통제 컨트롤러로, BLE 5.0 비동기 스마트폰 선-인증 ➔ ToF 레이저 센서 감지 ➔ 스마트 쿨다운 리셋 ➔ 시놀로지 NAS HTTPS 자격 검증 API ➔ 릴레이 스위칭 ➔ MQTTS HA Auto-Discovery ➔ GitHub CI/CD SFTP OTA 파이프라인으로 구현되어 있습니다.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   smart-gatekeeper                                     │
│                                                                                        │
│  [BLE 5.0 Scanner] ───┐                                                                │
│  (RSSI >= -80dBm)     ├─► [BLE 선인증 & ToF 50cm] ──► [HTTPS API] ─► [Relay (GPIO23)]   │
│  [ToF Sensor] ────────┘   (스마트 쿨다운 리셋 유지)   (tworimpa:4442)     (도어락 ON) │
│                                       │                         │                      │
│                 ┌─────────────────────┼─────────────────────────┘                      │
│                 ▼                     ▼                                                │
│       [WiFi CaptivePortal]    [MQTTS HA Discovery & OTA]                               │
│       (SmartGatekeeper-Setup)  (tworimpa:4883 / GitHub CI)                             │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 전체 통합 시퀀스 다이어그램 (Sequence Diagram)

### 2.1. Step 4 BLE 우선 인증 & 스마트 쿨다운 리셋 Walk-through 출입 통제 시퀀스

```mermaid
sequenceDiagram
    autonumber
    actor Person as 스마트폰 소지 출입자
    participant BLE as BLE 5.0 비동기 백그라운드 스캐너
    participant ToF as VL53L0X ToF 센서 (GPIO6/7)
    participant ESP as ESP32-C6 Controller (FSM)
    participant Relay as 릴레이 모듈 (GPIO23)
    participant NAS as Synology NAS (FastAPI)

    Note over BLE: 백그라운드 스캔 (UUID: 12345678-... & RSSI >= -80dBm)
    Person->>BLE: 접근 시 스마트폰 BLE 패킷 감지 (250ms 주기)
    BLE->>ESP: last_ble_detected_time = millis() 실시간 갱신 (isBleValid = true)

    Person->>ToF: 게이트 50cm 이내 진입 (<= 500mm)
    ToF->>ESP: Distance Reading (mm)
    
    alt BLE 선-인증 유효 (isBleValid == true & ToF <= 500mm)
        ESP->>ESP: ✅ BLE + ToF 이중 검증 조건 충족! (GateState: IDLE -> VERIFYING)
        ESP->>NAS: HTTPS POST /api/v1/auth/verify (JSON)
        NAS-->>ESP: HTTP 200 JSON {"granted": true}
        
        alt NAS 승인 완료
            ESP->>Relay: relayOn() (1000ms ON) [딸깍!]
            Note over Relay: 출입문 1초간 개방
            ESP->>Relay: relayOff()
            ESP->>ESP: COOLDOWN 쿨다운 상태 진입
            
            loop 문 주변 상주 중 (BLE 신호 지속 잡힘 or ToF <= 500mm)
                ESP->>ESP: 쿨다운 타이머 지속 리셋 (stateMs = now) -> 릴레이 중복 연타 방지 차단
            end
            
            Note over ESP: 사용자가 문 주변(BLE & ToF 구역)을 완전히 이탈하고 3초 경과
            ESP->>ESP: 🚪 문 주변 이탈 확인 -> IDLE 대기 상태 복귀 (다음 출입 준비)
        end
    else BLE 미인증 진입 시도 (isBleValid == false & ToF <= 500mm)
        ESP->>ESP: ❌ ToF 50cm 감지되었으나 유효 BLE 없음 (외부인/미인증)
        ESP->>ESP: 릴레이 미작동 & [GATE-WARN] 경고 (3초 디바운싱)
    end
```

---

## 3. 단계별 로드맵 및 상태

| 단계 | 이름 | 목표 | 상태 |
|------|------|------|------|
| **Step 1** | Local PoC | ToF + Relay 단독 및 로컬 연동 검증 | 🟢 **완료** (2026-07-24) |
| **Step 2** | 백엔드 구축 | 시놀로지 NAS FastAPI + MariaDB Docker 구축 & HTTPS API 검증 | 🟢 **완료** (2026-07-24) |
| **Step 3** | WiFi + NAS 연동 | ESP32-C6 WiFi/CaptivePortal + NAS HTTPS 자격검증 및 릴레이 연동 | 🟢 **완료** (2026-07-24) |
| **Step 4** | BLE + 스마트 쿨다운 | BLE 5.0 선인증, ToF 이중 검증(Walk-through), 상주 시 동적 쿨다운 리셋 | 🟢 **완료** (2026-07-24) |
| **Step 5** | 프로덕션 | PCB 양산 설계, 하우징 케이스 제작 | 🔲 미시작 |
