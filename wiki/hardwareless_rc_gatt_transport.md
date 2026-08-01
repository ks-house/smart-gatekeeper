# hardwareless_rc_gatt_transport.md — ESP32-C6 Connectable GATT Transport & Coexistence (Issue #18)

> 작성일: 2026-08-02
> 상태: **G0-SW / Hardwareless RC 구현 완료**
> 추적: GitHub [#18](https://github.com/ks-house/smart-gatekeeper/issues/18), Epic [#13](https://github.com/ks-house/smart-gatekeeper/issues/13)
> 상위 불변조건: [ota_reliability_contract.md](ota_reliability_contract.md), [security_protocol.md](security_protocol.md)

---

## 1. 개요

이 문서는 ESP32-C6 Target의 Hardwareless RC (Connectable BLE GATT 인증 transport) 구현 및 Wi-Fi/MQTT/OTA/릴레이 공존 구조를 정의한다. 기존 iBeacon 비콘 파라미터와 Android ScanFilter 계약을 100% 보존하면서 Connectable GATT 서비스 및 특성을 추가하고, default-OFF compile/runtime feature flag 아래 안전하게 제어한다.

---

## 2. Feature Flags (기본 OFF)

| 분류 | 식별자 | 기본값 | 비고 |
|---|---|---|---|
| Compile flag | `ENABLE_HARDWARELESS_RC` | `0` (OFF) | 빌드 타임 플래그 (`config.h` / `platformio.ini`) |
| Runtime flag | `ConfigManager::getHardwarelessRcEnabled()` / `GattServer::setEnabled()` | `false` (OFF) | NVS `hwless_rc` 키로 영구 저장 및 동적 제어 |

---

## 3. BLE Advertising & Legacy iBeacon 보존

1. **iBeacon payload 보존:**
   - Apple Company ID: `0x004C`
   - Header: `0x02 0x15`
   - Proximity UUID: `a1b2c3d4-e5f6-7890-abcd-ef1234567890`
   - Major: `1`, Minor: `1`
   - AD Flags: `0x1A`
2. **ScanFilter 100% 일치:**
   - `oAdvertisementData`에는 기존 iBeacon manufacturer data만 탑재하여 Android OS-managed BLE wake ADR (`android_ble_wake_adr.md`)의 exact `ScanFilter` (byte data/mask)와 100% 일치한다.
3. **Connectable GATT Scan Response:**
   - Hardwareless RC 활성화 시 `oScanResponseData`에 Service UUID `9f4d1000-7d9e-4fb1-9c54-6f4d53474b31`를 추가하여 GATT 스캔 discovery를 제공한다.

---

## 4. Canonical GATT Services & Characteristics

| 용도 | UUID | 속성 |
|---|---|---|
| Primary Auth Service | `9f4d1000-7d9e-4fb1-9c54-6f4d53474b31` | primary service |
| Hello / Control | `9f4d1001-7d9e-4fb1-9c54-6f4d53474b31` | Write + Indicate |
| Challenge | `9f4d1002-7d9e-4fb1-9c54-6f4d53474b31` | Read + Indicate |
| Proof | `9f4d1003-7d9e-4fb1-9c54-6f4d53474b31` | Write |
| Result | `9f4d1004-7d9e-4fb1-9c54-6f4d53474b31` | Indicate |

---

## 5. Protocol Negotiation & Bounded Sessions

- **N / N-1 Negotiation:**
  - `CLIENT_HELLO` (16 bytes) 수신 후 `highest(min(client_max, target_max))` 알고리즘 적용 (target=[1,1], security_floor=1).
  - N-1 앱 및 N 앱과의 호환을 유지하며, 미지원 버전 요청 시 `UNSUPPORTED_VERSION` (reason=1) 반환.
- **Bounded Challenge Session:**
  - 138-byte canonical challenge payload (`SGKCHAL1` header, selected_protocol, door_id, session_id, nonce, boot_id, expiry_monotonic_ms, acl_version, negotiation_hash).
  - Challenge 수명: 5,000 ms. Expiry 경과 시 automatic session invalidation.
- **Single-Use CAS & Disconnect Cleanup:**
  - Proof 수신 즉시 세션 상태를 `CONSUMED`로 CAS 전환하여 동일 proof 재전송 및 replay attack 차단.
  - Client 연결 해제(`onDisconnect`) 시 재조립 버퍼 및 active session 데이터 즉시 파기.
  - Concurrent active auth connection 제한 (최대 1개).

---

## 6. Coexistence Arbitration & Telemetry

- **OTA & MQTT Coexistence Arbitration:**
  - OTA 업그레이드 진행 중(`s_ota_busy = true`)에 들어오는 GATT proof write는 `BUSY` (reason=8)로 거부되며 릴레이 safe-state를 최우선 보존한다.
  - MQTT pre-arm 및 `manual_remote` 수동 버튼 개방 명령과의 IDLE-only 상호 잠금을 유지한다.
- **Telemetry 수집 항목 (`GattServer::getTelemetry()`):**
  - `heap_free` (`ESP.getFreeHeap()`)
  - `heap_min` (`ESP.getMinFreeHeap()`)
  - `stack_high_watermark`
  - `negotiation_latency_ms`
  - `proof_latency_ms`
  - `active_connections`, `total_sessions`, `failed_auth_count`
  - `boot_id`, `reset_reason`

---

## 7. 하드웨어 불변조건 보존

- MCU: **ESP32-C6-DevKitC-1** (RISC-V 32-bit), PlatformIO `pioarduino` 프레임워크.
- 릴레이 제어: GPIO23 (Active-LOW, boot default OFF, esp_timer 독립 fail-safe 유지).
- I2C 버스 복구: GPIO6 (SDA), GPIO7 (SCL) clear sequence 보존.
- Dual-slot OTA rollback 및 authenticated `manual_remote` 모바일 수동 버튼 문열기 경로 독립성 유지.

---

## 8. 검증 세트 (Automated Hardwareless Verification)

`tests/test_hardwareless_rc.py`가 아래 7개 항목을 자동 검증한다.

1. **100 Cycles Test:** 연속 100회 deterministic GATT auth session 100% 성공.
2. **Fuzz & Malformed Test:** Truncated header, invalid magic, bad length, corrupted signature의 strict rejection 및 릴레이 미작동.
3. **Timeout & Reset Test:** 5초 challenge expiry 만료 및 Target boot reset 시 세션 파기.
4. **Concurrent MQTT & OTA Test:** OTA busy 시 GATT `BUSY` 거부 및 릴레이 안전성.
5. **Relay Safety Test:** Boot default OFF, single-use CAS로 replay 차단.
6. **N / N-1 Test:** N, N-1 버전 협상 성공 및 미지원 버전 거부.
7. **Advertisement Agreement Test:** Target raw advertising payload와 Android ScanFilter exact match.
