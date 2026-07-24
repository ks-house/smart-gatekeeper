# 하드웨어 테스트 결과 (hardware_test.md)

ESP32-C6 기반 ToF 센서, 릴레이, Wi-Fi, HTTPS NAS 백엔드, MQTTS HA Auto-Discovery 및 무선 OTA 무선 통합 테스트 기록 문서입니다.

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

---

## 2. Step 3 & Step 4 통합 E2E 테스트 검증 보고

```
+-----------------------------------------------------------------------------------+
|                            E2E Integration Test Flow                              |
+-----------------------------------------------------------------------------------+
| 1. ToF Sensor (GPIO6/7)  --> 50cm 이내 진입 감지                                   |
| 2. WiFiClientSecure      --> HTTPS POST https://tworimpa.synology.me:4442/verify  |
| 3. FastAPI Backend       --> MariaDB 세입자 검증 (HTTP 200, granted: true)          |
| 4. Relay Drive (GPIO23)  --> 릴레이 1000ms ON (Active-LOW LOW) -> OFF (INPUT HighZ) |
| 5. MQTTS (4883 TLS)      --> HA Auto-Discovery & smart-gatekeeper/status 텔레메트리|
| 6. OTA Updater           --> GitHub CI -> NAS SFTP -> ESP32-C6 무선 업그레이드     |
+-----------------------------------------------------------------------------------+
```

### 파라미터 구성 (`include/config.h`)

| 항목 | 설정값 | 비고 |
|---|---|---|
| `DISTANCE_THRESHOLD_MM` | `500` (mm) | ToF 트리거 임계값 |
| `RELAY_HOLD_MS` | `1000` (ms) | 릴레이 유지 시간 |
| `RELAY_COOLDOWN_MS` | `2000` (ms) | 연속 요청 방지 쿨다운 |
| `MQTT_PORT` | `4883` | MQTTS SSL/TLS 포트 |
| `API_URL` | `https://tworimpa.synology.me:4442/api/v1/auth/verify` | 자격 검증 API |

### 🏆 결론
타겟 보드(ESP32-C6)에서 ToF 거리 센서, Wi-Fi 캡티브 포털, 시놀로지 NAS HTTPS 백엔드 연동, MQTTS Home Assistant Auto Discovery 및 무선 OTA 파이프라인까지 **전체 통합 시스템 테스트가 100% 정상 완수**되었습니다.
