# wiki/index.md — Navigation Map
> **Read this first.** All wiki pages are listed here with one-line summaries.
> Last updated: 2026-07-24 (Step 1, Step 2, Step 3, Step 4 통합 완료 🟢)

---

## 🗂️ Category: Raw Sources

| File | Summary |
|------|---------|
| [ST_VL53L0X_Specs.md](../raw/ST_VL53L0X_Specs.md) | VL53L0X 데이터시트 코어 스펙, I²C 타이밍, Pololu API, ESP32-C6 특이사항 |
| [Espressif_ESP32C6_BoardSpec.md](../raw/Espressif_ESP32C6_BoardSpec.md) | ESP32-C6-DevKitC-1 사양, 스트래핑 핀 목록, pioarduino 설정 |
| [BOM_SmartGatekeeper_Step1.md](../raw/BOM_SmartGatekeeper_Step1.md) | Step 1 구매 확정 BOM + 호환성 검토 (⚠️ 브레드보드/점퍼 와이어 주의사항 포함) |

---

## 🗂️ Category: Environment & Toolchain

| Page | Summary |
|------|---------|
| [env_setup.md](env_setup.md) | PlatformIO 설치, ESP32 보드 매니저, 필수 라이브러리 목록 |

---

## 🗂️ Category: Hardware

| Page | Summary |
|------|---------|
| [pin_mapping.md](pin_mapping.md) | ESP32 GPIO ↔ 모든 주변기기 핀 매핑 마스터 테이블 |
| [hardware_test.md](hardware_test.md) | ToF / Relay / WiFi / HTTPS NAS / MQTTS HA / OTA E2E 통합 테스트 결과 |

---

## 🗂️ Category: Architecture & Planning

| Page | Summary |
|------|---------|
| [architecture.md](architecture.md) | 시스템 전체 아키텍처, 3대 통합 시퀀스 다이어그램 (E2E, MQTTS HA, OTA), 로드맵 |
| [mobile_app_scenario.md](mobile_app_scenario.md) | Step 6 세입자용 모바일 앱(Smart Key) 공식 시나리오 기획서 (Flutter 하이브리드 Zero-Update, Role Reversal) |



---

## 🗂️ Category: Meta

| Page | Summary |
|------|---------|
| [log.md](log.md) | 시간순 변경 이력 |
| [../schema.md](../schema.md) | 위키 거버넌스 규칙 & 컨벤션 |
| [../AGENTS.md](../AGENTS.md) | 에이전트 협업 전체 지침 필독 |
| [../.agents/AGENTS.md](../.agents/AGENTS.md) | IDE 자동 로드 핵심 규칙 (압축본) |

---

## 📌 Quick Reference

| Topic | Location |
|-------|----------|
| I2C 기본 핀 (SDA/SCL) | [pin_mapping.md](pin_mapping.md) |
| I2C 400kHz 활성화 | [ST_VL53L0X_Specs.md](../raw/ST_VL53L0X_Specs.md#7-esp32-특이사항) |
| 65535 sentinel 값 처리 | [ST_VL53L0X_Specs.md](../raw/ST_VL53L0X_Specs.md#7-esp32-특이사항) |
| 릴레이 배선 안전 주의 | [pin_mapping.md](pin_mapping.md) |
| E2E 출입 감지 시퀀스 | [architecture.md](architecture.md#21-e2e-출입-감지--자격-검증-시퀀스) |
| MQTTS HA Auto Discovery 시퀀스 | [architecture.md](architecture.md#22-mqtts-ha-auto-discovery--원격-개방-시퀀스) |
| GitHub CI/CD SFTP OTA 시퀀스 | [architecture.md](architecture.md#23-github-cicd--무선-ota-배포-시퀀스) |
| E2E 통합 테스트 결과 | [hardware_test.md](hardware_test.md) |
