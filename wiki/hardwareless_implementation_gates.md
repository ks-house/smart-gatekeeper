# Hardwareless Implementation Gates & Release Candidate Specification (`wiki/hardwareless_implementation_gates.md`)

> **Single Source of Truth**: Two-Tier Authorization Gate Structure for Hardwareless Release Candidate & Physical Rollout
> **Last updated**: 2026-08-05

---

## 1. 개요 (Overview)

Epic #13 (모바일 독립 BLE 로컬 인증 및 Gatekeeper 하드웨어리스 아키텍처)의 제2단계 검증 체계에 따라 **소프트웨어 릴리즈 후보 게이트 (`G0-SW`)**와 **물리 장비 검증 게이트 (`G0-HW`)**를 엄격히 분리한다.

---

## 2. 2단계 승인 게이트 (Two-Tier Authorization Structure)

### 2.1 G0-SW: Software Release Candidate Gate (`PASSED` 🟢)
- **대상 이슈**: #14, #15, #16, #23 (Wave 0), #17, #18, #19 (Wave 1), #20 (Wave 2), #21, #22 (Wave 3)
- **허용 범위**:
  - 소프트웨어 단위·통합·가상 E2E 테스트 통과 및 Code Review
  - Draft/Feature PR 병합 및 `main` 브랜치 소프트웨어 통합
  - Feature Flag 기반 선택적 기능 활성화 (`ENABLE_HARDWARELESS_RC`)
- **차단 범위**:
  - Production 프로덕션 상시 활성화 금지 (`production_enable_allowed: false`)
  - 실기기 검증 완료 주장 금지 (`physical_completion_claim_allowed: false`)

### 2.2 G0-HW: Physical Device Verification Gate (`PENDING` 🟡 / Fail-Closed)
- **필수 실기기 증거**:
  1. `samsung_oem_ble_wake`: Samsung Android 기기 100회 자동 스캔/Wake 성공
  2. `esp32_c6_real_ble_gatt_radio_coexistence`: ESP32-C6 실제 BLE GATT 5.3 및 Wi-Fi 6 라디오 공존
  3. `relay_one_shot_and_fail_safe`: GPIO3 릴레이 One-shot 3초 구동 및 부팅 시 High-Z OFF 보장
  4. `sensor_real_passage_detection`: 초음파 센서 19cm/20cm 통과 시 동작 및 미통과 시 ARMED 타임아웃
  5. `bootloader_dual_slot_health_rollback_power_loss`: Dual-slot 파티션 전원 차단 / 롤백 시동
  6. `ota_g1_through_g4`: OTA-G1 ~ OTA-G4 물리 장비 롤아웃 및 롤백 드릴
- **현재 상태**: 실물 기기 미연결 환경으로 인해 **Fail-Closed 차단 유지**

---

## 3. Fault Injection & E2E Test Matrix (`FI-01` ~ `FI-10`)

| ID | Fault Injection Scenario | Automation / Tool | Expected Behavior | Status |
|---|---|---|---|---|
| `FI-01` | HTTP disconnect at 50% download | Host fake server | Active artifact preserved | **PASS** (Software) |
| `FI-02` | Signed ACL / Artifact byte flip | Vector tamper script | Metadata & digest rejected before install/boot | **PASS** (Software) |
| `FI-03` | Manifest signature byte flip | Vector tamper script | Metadata rejected fail-closed | **PASS** (Software) |
| `FI-04` | MQTT broker network isolation | Network deny rule | Target periodic HTTPS fallback active | **PASS** (Software) |
| `FI-05` | Power cut during flash write | Programmable power switch | Bootloader falls back to previous valid slot | Pending Physical |
| `FI-06` | Crashing new firmware image | Deliberately crashing image | Rollback before health mark valid | Pending Physical |
| `FI-07` | BLE scanner & WebView failure | Instrumentation flags | Settings / Manual update manager accessible | **PASS** (Software) |
| `FI-08` | Primary mobile endpoint 503 | HTTP 503 mock | Secondary mobile fallback URL downloads | **PASS** (Software) |
| `FI-09` | APK signing certificate mismatch | Alternate keystore | Package installer rejected fail-closed | **PASS** (Software) |
| `FI-10` | N & N-1 protocol versions | Versioned vector suite | Access planes and update contracts compatible | **PASS** (Software) |

---

## 4. 불변 조건 (Invariants Audit)

1. **`authenticated_mobile_manual_remote_preserved`**: `true` (명시적 원격 버튼 개방 유지)
2. **`legacy_rollback_path_preserved`**: `true` (앱 재설치 없는 REST Pre-arm 롤백 유지)
3. **`production_release_fail_closed`**: `true` (물리 증거 미확인 시 프로덕션 상시 배포 차단)
4. **`target_dual_slot_health_rollback_preserved`**: `true` (ESP32-C6 Dual OTA 슬롯 보존)
5. **`mobile_manual_updater_independent`**: `true` (업데이트 매니저 독립 접근성 유지)

---

## 5. 검증 내역 (Verification Evidence)

- **Python Gate Test Suite**: `python -m unittest tests/test_hardwareless_implementation_gates.py` (4/4 tests PASS)
- **OTA Contract Gate**: `python scripts/ota_contract_gate.py contract` (PASS)
- **Observability Event Schema**: `python -m unittest discover -s observability/tests` (18/18 PASS)
- **Protocol Vector Verifier**: `python protocol/tools/verify_vectors.py` (PASS)
- **Host C++ Unit Tests**: `wsl ./test_runner` (369 checks PASS)
- **Flutter Unit Tests & Analyze**: `flutter test && flutter analyze` (5/5 PASS, 0 issues)
- **PlatformIO ESP32-C6 Firmware Build**: `pio run -e esp32c6` (SUCCESS: RAM 16.5%, Flash 22.4%)
