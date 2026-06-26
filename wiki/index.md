# wiki/index.md — Navigation Map
> **Read this first.** All wiki pages are listed here with one-line summaries.
> Last updated: 2026-06-27

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
| [env_setup.md](env_setup.md) | PlatformIO 설치, ESP32 보드 매니저, 필수 라이브러리 |

---

## 🗂️ Category: Hardware

| Page | Summary |
|------|---------|
| [pin_mapping.md](pin_mapping.md) | ESP32 GPIO ↔ 모든 주변기기 핀 매핑 마스터 테이블 |
| [hardware_test.md](hardware_test.md) | ToF / Relay 단독 테스트 절차 및 결과 기록 |

---

## 🗂️ Category: Architecture

| Page | Summary |
|------|---------|
| [architecture.md](architecture.md) | 시스템 전체 구조, 단계별 로드맵(PoC → 프로덕션) |

---

## 🗂️ Category: Meta

| Page | Summary |
|------|---------|
| [log.md](log.md) | 시간순 변경 이력 |
| [../schema.md](../schema.md) | 위키 거버넌스 규칙 & 컨벤션 |
| [../AGENTS.md](../AGENTS.md) | 에이전트 협업 전체 지질 필독 |
| [../.agents/AGENTS.md](../.agents/AGENTS.md) | IDE 자동 로드 핵심 규칙 (압축본) |

---

## 📌 Quick Reference

| Topic | Location |
|-------|----------|
| I2C 기본 핀 (SDA/SCL) | [pin_mapping.md](pin_mapping.md) |
| I2C 400kHz 활성화 | [ST_VL53L0X_Specs.md](../raw/ST_VL53L0X_Specs.md#7-esp32-특이사항) |
| 65535 sentinel 값 처리 | [ST_VL53L0X_Specs.md](../raw/ST_VL53L0X_Specs.md#7-esp32-특이사항) |
| 릴레이 배선 안전 주의 | [pin_mapping.md](pin_mapping.md) |
| VL53L0X 라이브러리 선택 근거 | [env_setup.md](env_setup.md) |
| 테스트 체크리스트 | [hardware_test.md](hardware_test.md) |
| 다중 ToF 센서 XSHUT 주소할당 | [ST_VL53L0X_Specs.md](../raw/ST_VL53L0X_Specs.md#8-다중-센서-xshut-순차-주소-할당) |
