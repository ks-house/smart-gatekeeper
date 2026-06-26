# architecture.md — 시스템 아키텍처 및 로드맵
> Last updated: 2026-06-26

---

## 1. 시스템 개요

```
┌─────────────────────────────────────────────────────────┐
│                   smart-gatekeeper                      │
│                                                         │
│  [스마트폰 BLE] ──── ESP32 ──── [VL53L0X ToF × N]      │
│                        │                                │
│                  [릴레이 1ch] ──── [도어락/전자문]      │
│                        │                                │
│                  [WiFi/MQTT] ──── [시놀로지 NAS]         │
│                                        │                │
│                                   [Node-RED]            │
│                                   [InfluxDB]            │
│                                   [Grafana]             │
└─────────────────────────────────────────────────────────┘
```

---

## 2. 단계별 로드맵

| 단계 | 이름 | 목표 | 상태 |
|------|------|------|------|
| **Step 1** | Local PoC | ToF + Relay 단독 하드웨어 검증 | 🟡 진행 중 |
| Step 2 | BLE 연동 | 스마트폰 BLE → ESP32 잠금/해제 명령 | 🔲 미시작 |
| Step 3 | WiFi + MQTT | 시놀로지 NAS MQTT 브로커 연동 | 🔲 미시작 |
| Step 4 | 방향 감지 | ToF 2채널 IN/OUT 방향 판별 알고리즘 | 🔲 미시작 |
| Step 5 | 프로덕션 | PCB 설계, 케이스, OTA 업데이트 | 🔲 미시작 |

---

## 3. Step 1 소프트웨어 모듈 구조

```
src/
├── main.cpp              — 진입점 (빌드 플래그로 모드 전환)
├── ToFSensor.cpp/.h      — VL53L0X I2C 드라이버 래퍼
└── RelayController.cpp/.h — 릴레이 GPIO 드라이버

include/
└── config.h              — 핀 상수 / 파라미터 중앙화
```

### 의존성 그래프
```
main.cpp
  ├── ToFSensor.h  ←→  pololu/VL53L0X (lib)  ←→  Wire (Arduino)
  └── RelayController.h  ←→  Arduino GPIO
```

---

## 4. 하드웨어 BOM (Step 1 — 구매 확정)
> 상세 호환성 검토: [raw/BOM_SmartGatekeeper_Step1.md](../raw/BOM_SmartGatekeeper_Step1.md)

| 부품 | 수량 | 비고 |
|------|------|------|
| ESP32-C6-DevKitC (Type-C) | 2개 | 스페어 1 포함. RISC-V, Wi-Fi 6, BLE 5.3 |
| VL53L0X ToF 레이저 센서 | 2개 | 스페어 1 포함. 3.3V I2C, SDA=GPIO6/SCL=GPIO7 |
| 1채널 5V 릴레이 모듈 (Low/High 선택형) | 2개 | 스페어 1 포함. 점퍼로 극성 선택. 광절연 내장 |
| ABS 박스 100×60×40mm | 2개 | 가공 실패 대비 여분. 전면 3mm ToF용 타공 필요 |
| 5V 2A USB Type-C 전원 어댑터 | 1세트 | 24시간 연속 가동. 스마트폰 충전기 대체 가능 |
| 400홀 미니 브레드보드 | 1개 | ⚠️ C6 DevKitC-1이 브레드보드를 가득 채울 수 있음 |
| 듀폰 점퍼 와이어 세트 | 1세트 | ⚠️ M-M(수-수) 포함 여부 확인 필요 |
