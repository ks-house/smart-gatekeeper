# wiki/index.md — Navigation Map
> **Read this first.** All wiki pages are listed here with one-line summaries.
> Last updated: 2026-07-31 (Android 화면 OFF 출입 실패 단계별 분석 추가)

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
| [env_setup.md](env_setup.md) | 현재 firmware/backend/Android 빌드, 시크릿, CI/CD 가이드 |

---

## 🗂️ Category: Hardware

| Page | Summary |
|------|---------|
| [pin_mapping.md](pin_mapping.md) | AJ-SR04T GPIO10/11, relay GPIO23 및 3.3V 전기 안전 기준 |
| [hardware_test.md](hardware_test.md) | 현재 아키텍처 검증표와 과거 ToF 테스트 증거 분리 |
| [relay_troubleshooting_guide.md](relay_troubleshooting_guide.md) | GPIO23 High-Z OFF의 한계와 릴레이 전기·반복 진단 절차 |

---

## 🗂️ Category: Architecture & Planning

| Page | Summary |
|------|---------|
| [architecture.md](architecture.md) | iBeacon → Android → FastAPI → MQTT → 초음파 → relay, retained boot/reset 진단 구조 |
| [current_code_audit.md](current_code_audit.md) | 최신 코드 계약, 기존 문서 불일치, P0/P1/P2 위험과 다음 우선순위 |
| [target_connectivity_root_cause.md](target_connectivity_root_cause.md) | MCU reset 실측, retained coredump의 lwIP UDP panic, v2.1 원격 진단과 relay fail-safe |
| [mobile_app_scenario.md](mobile_app_scenario.md) | Step 6 세입자용 모바일 앱(Smart Key) 공식 시나리오 기획서 (Flutter 하이브리드 Zero-Update, Role Reversal) |
| [mobile_app_scan_lifecycle.md](mobile_app_scan_lifecycle.md) | 서비스-isolate monitoring+ranging 병렬 생애주기, 화면 OFF silent-stall 복구·진단 |
| [mobile_app_background_audit.md](mobile_app_background_audit.md) | 화면 OFF·앱 종료 구현 감사와 P0/P1 수정 결과, 남은 플랫폼 제약·실기기 검증표 |
| [mobile_screen_off_incident_analysis.md](mobile_screen_off_incident_analysis.md) | 화면 OFF 출입 실패의 확정 증거, 원인 우선순위, 단계별 판별·실기기 수집 절차 |



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
| 최신 코드 재분석 결론/위험 | [current_code_audit.md](current_code_audit.md) |
| Target 통신 단절 근본 원인/현장 판별 | [target_connectivity_root_cause.md](target_connectivity_root_cause.md) |
| 현재 전체 출입 시퀀스 | [architecture.md](architecture.md#2-정상-출입-시퀀스) |
| AJ-SR04T/Relay 핀과 전기 안전 | [pin_mapping.md](pin_mapping.md) |
| 현재 빌드·시크릿·CI/CD | [env_setup.md](env_setup.md) |
| 현재 검증 상태와 E2E 절차 | [hardware_test.md](hardware_test.md) |
| 앱/서비스 상태별 동작 | [mobile_app_scan_lifecycle.md](mobile_app_scan_lifecycle.md#3-서비스-생애주기) |
| 화면 OFF·앱 종료 감사 | [mobile_app_background_audit.md](mobile_app_background_audit.md) |
| 화면 OFF 출입 실패 상세 분석 | [mobile_screen_off_incident_analysis.md](mobile_screen_off_incident_analysis.md) |
| 비콘 미감지 신고 대응 | [mobile_app_scan_lifecycle.md](mobile_app_scan_lifecycle.md#9-신고-대응-순서) |
