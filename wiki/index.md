# wiki/index.md — Navigation Map
> Personal production: [personal_production_profile.md](personal_production_profile.md) — reduced single-owner phone and installed-Target release profile.
> **Read this first.** All wiki pages are listed here with one-line summaries.
> Last updated: 2026-08-26 (issue #158 bounds Flutter ranging recovery during native GATT ownership; issue #156 retains the terminal action-1 defect)

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
| [env_setup.md](env_setup.md) | 현재 firmware/backend/Android 빌드, Windows PlatformIO timeout/orphan 안전 복구, OTA 서명 키 최초 등록, CI/CD와 GITHUB_TOKEN 인증 가이드 |
| [orca_development_environment.md](orca_development_environment.md) | Orca 워크트리 자동 setup, doctor/validation, 프로파일 작업 시작과 안전한 완료 수명주기 |
| [orca_lifecycle_incident.md](orca_lifecycle_incident.md) | #55 post-merge packaged worker-start 재발, staged-launcher workaround, 장기 lifecycle transport 증거와 fail-closed 복구 경계 |

---

## 🗂️ Category: Hardware

| Page | Summary |
|------|---------|
| [pin_mapping.md](pin_mapping.md) | AJ-SR04T GPIO10/11, authoritative relay GPIO3 및 3.3V 전기 안전 기준 |
| [hardware_test.md](hardware_test.md) | 현재 아키텍처 검증표와 과거 ToF 테스트 증거 분리 |
| [physical_gate_preparation.md](physical_gate_preparation.md) | #54 Samsung/OEM, ESP32-C6, relay/sensor, OTA, operator/canary evidence preparation |
| [nas_physical_test_delivery.md](nas_physical_test_delivery.md) | exact-main public canary bounded SFTP-only staging/readback/rename, optional pin with audited runtime-keyscan fallback, connected-tier prerequisites and operator handoff |
| [relay_troubleshooting_guide.md](relay_troubleshooting_guide.md) | GPIO3 High-Z OFF의 한계와 릴레이 전기·반복 진단 절차 |

---

## 🗂️ Category: Architecture & Planning

| Page | Summary |
|------|---------|
| [project_status.md](project_status.md) | 저장소 구현·검증 증거·현장 배포를 분리한 현재 프로젝트 대시보드와 열린 Gate |
| [architecture.md](architecture.md) | iBeacon → Android → FastAPI → MQTT → 초음파 → relay, retained boot/reset 진단 구조 |
| [commercial_release_program.md](commercial_release_program.md) | 상용 출시 목표, 작업 DAG, 보안·핵심·모바일·매뉴얼·실기기·production 완료 Gate |
| [current_code_audit.md](current_code_audit.md) | 최신 코드 계약, 기존 문서 불일치, P0/P1/P2 위험과 다음 우선순위 |
| [target_connectivity_root_cause.md](target_connectivity_root_cause.md) | MCU reset 실측, retained coredump의 lwIP UDP panic, v2.1 원격 진단과 relay fail-safe |
| [embedded_target_connectivity_policy.md](embedded_target_connectivity_policy.md) | 벽 매립형 Target의 Wi-Fi/MQTTS 상시 연결 SLO, 자동 복구, 경보, 매립 승인 Gate와 현재 P0 공백 |
| [mobile_app_scenario.md](mobile_app_scenario.md) | Step 6 세입자용 모바일 앱(Smart Key) 공식 시나리오 기획서 (Flutter 하이브리드 Zero-Update, Role Reversal) |
| [mobile_app_scan_lifecycle.md](mobile_app_scan_lifecycle.md) | 서비스-isolate monitoring/ranging, 상태바 알림·IPC 복구, 화면 OFF 진단과 bounded native-GATT ownership recovery |
| [mobile_app_background_audit.md](mobile_app_background_audit.md) | 화면 OFF·앱 종료 구현 감사와 P0/P1 수정 결과, 남은 플랫폼 제약·실기기 검증표 |
| [mobile_screen_off_incident_analysis.md](mobile_screen_off_incident_analysis.md) | 화면 OFF 출입 실패의 확정 증거, 원인 우선순위, 단계별 판별·실기기 수집 절차 |
| [access_incident_2026_08_01.md](access_incident_2026_08_01.md) | 출입 지연·반복 개방·화면 OFF 현장 분석과 Target FSM·Backend MQTT 보장 범위 |
| [personal_prod_incident_2026_08_12.md](personal_prod_incident_2026_08_12.md) | 개인 PROD 모바일 등록·문 열기 배포와 매립 Target MQTT/Wi-Fi/OTA 장애 증거 및 재개 절차 |
| [ha_external_access_incident_2026_08_13.md](ha_external_access_incident_2026_08_13.md) | 2026-08-13 HA nginx 502의 upstream 장애 격리, 안전한 복구 순서와 2026-08-24 복구 경계 |
| [mobile_dependency_redesign.md](mobile_dependency_redesign.md) | 모바일 책임 과밀·화면 OFF 병목 분석과 Door Controller 로컬 인증 중심 재설계안 |
| [mobile_hardwareless_implementation_plan.md](mobile_hardwareless_implementation_plan.md) | 추가 자격 하드웨어 보류 조건의 Android native wake·BLE GATT local auth 단계/병렬 구현 계획 |
| [android_ble_wake_adr.md](android_ble_wake_adr.md) | #14 PendingIntent filtered BLE wake 결정, exact filter contract, hardwareless PoC와 Samsung 20회 pending Gate |
| [android_gatt_worker.md](android_gatt_worker.md) | #17/#133 signed default-OFF rollout, action-1 background ARM, action-2 terminal manual open, BLE lease, crash boundary and pending physical gates |
| [security_protocol.md](security_protocol.md) | Android Keystore/정규 proof, crash-safe ACL watermark, 증거 기반 RELAY-G0/G1/G2 fail-closed Gate, N/N-1과 공통 adversarial vector |
| [backend_acl_management.md](backend_acl_management.md) | #19 public-key enrollment, admin lifecycle, signed ACL push/pull·ACK, migration/rollback과 OTA 독립성 |
| [admin_control_plane_security.md](admin_control_plane_security.md) | #49 deny-by-default mTLS admin sessions, tenant RBAC/CSRF/re-auth, dual-control force-open, immutable audit, OTA/manual boundary |
| [ota_reliability_contract.md](ota_reliability_contract.md) | 모바일 앱·Target update 경로 독립성, dual-slot health/rollback, N/N-1 호환과 release blocking 시험 |
| [target_command_ota_security.md](target_command_ota_security.md) | #50 verified per-Target MQTTS, signed durable commands, signed inactive-slot OTA, local recovery, and production hardening evidence boundary |
| [commercial_operations.md](commercial_operations.md) | #52 privacy-safe operations, bounded resilience, readiness/metrics/SLO, backup/restore, hardened production Compose, supply-chain and evidence Gates |
| [observability_event_schema.md](observability_event_schema.md) | hands-free/수동 버튼 access와 update envelope, immutable artifact correlation, reset/rollback evidence, uint64·causal ordering, I7/I9/OTA 합격 계약 |
| [ota_operations_runbook.md](ota_operations_runbook.md) | canary, release Gate, 장애 중단·rollback, fallback과 OTA 운영 증거 절차 |
| [hardwareless_rc_gatt_transport.md](hardwareless_rc_gatt_transport.md) | #18 default-OFF connection-owned/ACK-gated GATT, OTA safe-state, provisioned door identity, host evidence and physical gates |
| [target_acl_fsm.md](target_acl_fsm.md) | #20/#133 Target-owned ACL, proof-to-FSM Result binding, action-1 sensor ARM, action-2 immediate relay, interlock and evidence boundary |
| [flutter_thin_ui.md](flutter_thin_ui.md) | #21/#133 Flutter Thin UI, terminal 1-tap immediate local GATT open, enrollment, OEM recovery and independent OTA |
| [mobile_commercial_ux.md](mobile_commercial_ux.md) | #51 capability-based recovery shell, fresh-install native wake, authenticated Target resolution, signed updater, truthful states, privacy/accessibility/localization |
| [hardwareless_implementation_gates.md](hardwareless_implementation_gates.md) | #22 Two-tier authorization gate structure, software release candidate G0-SW validation, and physical G0-HW fail-closed boundaries |
| [trusted_workflow_policy.md](trusted_workflow_policy.md) | Trusted workflow digest와 workflow/action exact inventory Gate, policy rotation, self-policy/status-context 잔여 경계 |

## 🗂️ Category: Manuals & Operations

| Document | Summary |
|---|---|
| [manuals/README.md](../manuals/README.md) | Issue #53 v0.3 manual set, NAS staging/evidence boundary, field contract, and repeat loop |
| [general_user_manual_ko.md](../manuals/general_user_manual_ko.md) | Korean-first end-user installation, access, degraded/OEM, update/rollback, lost-phone and support journeys |
| [administrator_manual_ko.md](../manuals/administrator_manual_ko.md) | Admin roles, tenant/device/door lifecycle, force-open, NAS readiness/metrics, privacy, backup/restore, OTA and decommission |
| [installer_service_manual_ko.md](../manuals/installer_service_manual_ko.md) | ESP32-C6 wiring, GPIO3/polarity, power safety, commissioning, and explicit relay/offline/OTA/sensor incident contracts (evidence pending) |
| [privacy_notice_ko.md](../manuals/privacy_notice_ko.md) | Data inventory, minimization, consented/redacted support export, retention/deletion and incident privacy |
| [support_incident_handbook_ko.md](../manuals/support_incident_handbook_ko.md) | Support triage, reason/state handling, force-open, offline/OEM, update, lost phone and incident loop |
| [product_gap_register_v1.md](../manuals/product_gap_register_v1.md) | Manual-to-product reverse analysis with explicit #49–#52, NAS, test, P0/P1 and physical gaps |
| [hardwareless_walkthrough_ko.md](../manuals/hardwareless_walkthrough_ko.md) | 16 actor journeys, #52 operations regressions, NAS staging and user physical-test checklists |



---

## 🗂️ Category: Meta

| Page | Summary |
|------|---------|
| [knowledge_management.md](knowledge_management.md) | Obsidian Vault, 문서 type/status, 세 가지 사실 축, cross-project Knowledge Hub 승격 규칙 |
| [log.md](log.md) | 시간순 변경 이력 |
| [../schema.md](../schema.md) | 위키 거버넌스 규칙 & 컨벤션 |
| [../AGENTS.md](../AGENTS.md) | 에이전트 협업 전체 지침 필독 |
| [../.agents/AGENTS.md](../.agents/AGENTS.md) | IDE 자동 로드 핵심 규칙 (압축본) |
| [../.orca/ORCA.md](../.orca/ORCA.md) | Orca Multi-Agent 오케스트레이션 프로파일 시스템 (gpt5.6-sol, terra, luna 지침) |


---

## 📌 Quick Reference

| Topic | Location |
|-------|----------|
| 현재 구현·검증·현장 배포 상태 | [project_status.md](project_status.md) |
| 최신 코드 재분석 결론/위험 | [current_code_audit.md](current_code_audit.md) |
| Target 통신 단절 근본 원인/현장 판별 | [target_connectivity_root_cause.md](target_connectivity_root_cause.md) |
| 벽 매립형 Target 상시 연결·원격 복구 지침 | [embedded_target_connectivity_policy.md](embedded_target_connectivity_policy.md) |
| 현재 전체 출입 시퀀스 | [architecture.md](architecture.md#2-정상-출입-시퀀스) |
| AJ-SR04T/Relay 핀과 전기 안전 | [pin_mapping.md](pin_mapping.md) |
| 현재 빌드·시크릿·CI/CD | [env_setup.md](env_setup.md) |
| 현재 검증 상태와 E2E 절차 | [hardware_test.md](hardware_test.md) |
| #54 physical Gate pending-only template | [physical_gate_preparation.md](physical_gate_preparation.md) |
| 앱/서비스 상태별 동작 | [mobile_app_scan_lifecycle.md](mobile_app_scan_lifecycle.md#3-서비스-생애주기) |
| 화면 OFF·앱 종료 감사 | [mobile_app_background_audit.md](mobile_app_background_audit.md) |
| 화면 OFF 출입 실패 상세 분석 | [mobile_screen_off_incident_analysis.md](mobile_screen_off_incident_analysis.md) |
| 모바일 병목 근본 재설계 | [mobile_dependency_redesign.md](mobile_dependency_redesign.md) |
| 추가 하드웨어 없는 구현 로드맵 | [mobile_hardwareless_implementation_plan.md](mobile_hardwareless_implementation_plan.md) |
| Android OS-managed BLE wake ADR/실기기 Gate | [android_ble_wake_adr.md](android_ble_wake_adr.md) |
| Android native GATT credential worker / Hardwareless RC | [android_gatt_worker.md](android_gatt_worker.md) |
| 기기 키·BLE proof·signed ACL v1 | [security_protocol.md](security_protocol.md) |
| Backend enrollment·ACL sync·revocation | [backend_acl_management.md](backend_acl_management.md) |
| 모바일·Target OTA 최상위 계약 | [ota_reliability_contract.md](ota_reliability_contract.md) |
| Cross-layer session/event code와 parser fixture | [observability_event_schema.md](observability_event_schema.md) |
| OTA canary·rollback 운영 절차 | [ota_operations_runbook.md](ota_operations_runbook.md) |
| Trusted workflow digest Gate와 policy rotation | [trusted_workflow_policy.md](trusted_workflow_policy.md) |
| 비콘 미감지 신고 대응 | [mobile_app_scan_lifecycle.md](mobile_app_scan_lifecycle.md#9-신고-대응-순서) |
