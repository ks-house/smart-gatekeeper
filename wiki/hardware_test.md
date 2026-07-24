# 하드웨어 테스트 결과 (hardware_test.md)

ESP32-C6 기반 ToF 센서, 릴레이, Wi-Fi, HTTPS NAS 백엔드, MQTTS HA Auto-Discovery, BLE 5.0 스마트 쿨다운 리셋 및 무선 OTA 무선 통합 테스트 기록 문서입니다.

---

## 1. 테스트 이력 종합 (Test History Matrix)

| Test ID | 구분 | 대상 | 검증 내용 | 결과 | 비고 |
|:---:|:---:|:---:|:---|:---:|:---|
| **#1** | Unit | ToF VL53L0X | I2C (SDA:6, SCL:7) 400kHz 연속 거리 측정 | 🟢 PASS | 20mm~1200mm 정상 측정 |
| **#2** | Unit | Relay Module | GPIO23 INPUT-HighZ 트릭 릴레이 토글 | 🟢 PASS | 5V Active-LOW 모듈 상시 ON 우회 성공 |
| **#3** | E2E | HTTPS NAS Auth | ToF 50cm 감지 -> NAS REST API POST -> 릴레이 ON | 🟢 PASS | HTTP 200 / granted:true 수신 즉시 스위칭 |
| **#4** | Network | Captive Portal | AP 모드(`SmartGatekeeper-Setup`) NVS 저장 | 🟢 PASS | 브라우저 팝업 Wi-Fi 저장 및 자동 재접속 |
| **#5** | Security | MQTTS (4883) | Let's Encrypt Root CA Certificate Pinning | 🟢 PASS | TLS 4883 포트 보안 접속 및 텔레메트리 발행 |
| **#6** | IoT | HA Auto-Discovery | Home Assistant 5개 엔티티 자동 검색 및 원격 제어 | 🟢 PASS | `open_gate`, `ota_update`, `reboot`, 센서 정상 작동 |
| **#7** | OTA | GitHub CI/CD OTA | GitHub Push -> SFTP 업로드 -> ESP32-C6 무선 업데이트 | 🟢 PASS | `1.0.0-g<sha>` 동적 버전 오버라이드 및 무선 플래싱 완벽 통과 |
| **#8** | BLE | BLE + ToF FSM | BLE 5.0 선인증 & 문 주변 상주 시 동적 쿨다운 리셋 | 🟢 PASS | 문 주변 상주 중 중복 릴레이 연타 차단 & 이탈 시 3초 후 복귀 |

---

## 2. Step 3 & Step 4 통합 E2E 테스트 검증 보고

```
+-----------------------------------------------------------------------------------+
|                            E2E Integration Test Flow                              |
+-----------------------------------------------------------------------------------+
| 1. BLE 5.0 Scanner       --> 128-bit UUID & RSSI >= -80dBm 비동기 선인증           |
| 2. ToF Sensor (GPIO6/7)  --> 50cm 이내 진입 감지                                   |
| 3. WiFiClientSecure      --> HTTPS POST https://tworimpa.synology.me:4442/verify  |
| 4. FastAPI Backend       --> MariaDB 세입자 검증 (HTTP 200, granted: true)          |
| 5. Relay Drive (GPIO23)  --> 릴레이 1000ms ON (Active-LOW LOW) -> OFF (INPUT HighZ) |
| 6. Smart Cooldown        --> 문 주변 상주 시 쿨다운 지속 리셋 (이탈 시 3초 후 IDLE)   |
| 7. MQTTS (4883 TLS)      --> HA Auto-Discovery & smart-gatekeeper/status 텔레메트리|
| 8. OTA Updater           --> GitHub CI -> NAS SFTP -> ESP32-C6 무선 업그레이드     |
+-----------------------------------------------------------------------------------+
```

### 파라미터 구성 (`include/config.h`)

| 항목 | 설정값 | 비고 |
|---|---|---|
| `DISTANCE_THRESHOLD_MM` | `500` (mm) | ToF 트리거 임계값 |
| `BLE_RSSI_THRESHOLD` | `-80` (dBm) | BLE 수신 인지 임계값 |
| `BLE_VALID_MS` | `10000` (ms) | BLE 인증 신호 유효 인정 시간 |
| `RELAY_HOLD_MS` | `1000` (ms) | 릴레이 유지 시간 |
| `COOLDOWN_MS` | `3000` (ms) | 이탈 후 복귀 대기 시간 |
| `API_URL` | `https://tworimpa.synology.me:4442/api/v1/auth/verify` | 자격 검증 API |

### 🏆 결론
타겟 보드(ESP32-C6 N16)에서 ToF 거리 센서, Wi-Fi 캡티브 포털, 시놀로지 NAS HTTPS 백엔드 연동, MQTTS Home Assistant Auto Discovery, BLE 5.0 선인증 & 스마트 쿨다운 리셋 FSM 및 무선 OTA 파이프라인까지 **전체 통합 시스템 테스트가 100% 정상 완수**되었습니다.
