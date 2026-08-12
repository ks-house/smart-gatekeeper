---
title: smart-gatekeeper current code audit
type: reference
project: smart-gatekeeper
status: active
updated: 2026-08-12
source_of_truth: true
applies_to:
  - firmware
  - android
  - backend
  - ci
---

# 최신 코드 기준 구현 감사

> Audit baseline: branch `main`, commit `406707c`
>
> 범위: repository implementation과 저장소 내 검증 계약. 현장 배포 상태는 [personal_prod_incident_2026_08_12.md](personal_prod_incident_2026_08_12.md)를 별도로 따른다.

## 1. 결론

현재 저장소는 초기 “ESP32 scanner + VL53L0X + 직접 HTTPS 인증” PoC가 아니다. 기준 아키텍처는 **ESP32-C6 iBeacon/secure Target + Android foreground/native worker + FastAPI/MariaDB 관리면 + per-Target MQTTS signed command/ACL + AJ-SR04T + GPIO3 relay + signed recoverable OTA**다.

Hardwareless RC의 Android worker, connectable GATT transport, signed ACL verifier와 Target FSM 연동은 소프트웨어에 존재하지만 기본·production 빌드는 `ENABLE_HARDWARELESS_RC=0`이다. 구현 존재를 production 활성화나 실기기 합격으로 확대 해석하지 않는다.

## 2. 현재 코드 계약

| 계층 | 현재 값/동작 | 주요 근거 |
|---|---|---|
| Target build | ESP32-C6, pioarduino, `esp32c6`, 16 MB dual OTA; lab-only `esp32c6_hwless_rc` | `platformio.ini`, `partitions_16MB_ota.csv` |
| Sensor/relay | AJ-SR04T GPIO10/11, 20 cm min, 50 cm default; GPIO3 Active-LOW relay | `include/config.h`, `src/UltrasonicSensor.cpp`, `src/RelayController.cpp` |
| Access FSM | `IDLE → ARMED → RELAY_HOLD → COOLDOWN → IDLE`; IDLE만 새 arm/manual open 허용 | `src/TargetAccessFsm.cpp`, `src/main.cpp` |
| MQTT transport | Root CA, non-1883, Target ID principal, exact `gatekeeper/v1/targets/<id>/...` namespace; invalid provisioning closes command plane | `src/MqttManager.cpp` |
| Command security | signed canonical envelope, target/tenant/door/boot binding, expiry, nonce/replay storage, command ACK | `src/TargetCommandSecurity.cpp`, `src/MqttManager.cpp`, `backend/app/command_security.py` |
| Local ACL/GATT | signed ACL anti-rollback, P-256 proof, connection-owned GATT, offline event queue; compile/runtime default-OFF | `src/TargetAclManager.cpp`, `src/TargetProofVerifier.cpp`, `src/GattServer.cpp` |
| Target OTA | periodic HTTPS, CA validation, Ed25519 manifest, SHA-256/size, inactive partition, safe-state wait, health mark/rollback, version floor | `src/OtaManager.cpp`, `include/OtaHealthPolicy.h`, `src/OtaVersionPolicy.cpp` |
| Local recovery | provisioned authenticated recovery endpoints/AP with bounded AP window | `src/WifiManager.cpp`, `include/secrets.h.example` |
| Android scanning | foreground-service isolate, monitoring/ranging, RSSI filtering, IPC/diagnostics | `gatekeeper_app/lib/services/foreground_service.dart`, `ble_scanner.dart` |
| Android native path | PendingIntent BLE wake, secure storage/signing, durable GATT worker, manual retry | `gatekeeper_app/android/app/src/main/.../blewake`, `.../gattworker` |
| Mobile update | signed manifest/artifact identity, recovery shell and first-run health contract | `gatekeeper_app/lib/services/update_checker.dart`, `update_contract.dart`, native identity policy |
| Backend access | approved device lookup, signed boot-bound arm/manual/config commands, PUBACK wait | `backend/app/main.py`, `backend/app/command_security.py` |
| Admin plane | mTLS trusted-proxy or personal session, server-side session, CSRF, RBAC/tenant scope, re-auth, rate limit | `backend/app/admin_security.py`, `backend/app/main.py` |
| Operations | `/live` process liveness, `/ready` dependency/schema admission, metrics/privacy/retention, migration and production Compose contracts | `backend/app/ops_runtime.py`, `backend/compose.production.yml`, migrations 002–007 |

## 3. 2026-07-30 감사에서 해결된 오래된 위험

| 과거 감사 내용 | 현재 판정 |
|---|---|
| MQTT가 TLS 실패 뒤 `setInsecure()` | **해결됨**: 현재 코드에 fallback이 없고 CA/identity/signing provisioning 실패 시 command plane이 비활성화된다. |
| `/admin`과 admin API에 앱 인증 없음 | **해결됨(소프트웨어)**: session, CSRF, RBAC, tenant scope, fresh re-auth와 rate limit이 구현됐다. live proxy·operator 증거는 별도다. |
| GATT transport가 ACL verifier/FSM/relay를 호출하지 않음 | **해결됨(소프트웨어, default-OFF)**: production event sink와 proof verifier, Target FSM lifecycle bridge가 연결됐다. physical Gate는 열리지 않았다. |
| Target OTA가 MQTT 수동 `HTTPUpdate`뿐 | **해결됨(저장소 구현)**: periodic pull, signed manifest, inactive-slot install, health/rollback과 local recovery가 구현됐다. 구형 현장 Target에는 아직 설치되지 않았다. |
| 관리자 force-open 단일 호출 | **상용 경로 강화됨**: dual-control, distinct approver, re-auth, idempotency/reconciliation 계약이 존재한다. 개인 profile은 별도 범위를 따른다. |

## 4. 여전히 현재인 경계와 위험

### P0 — 현장/배포 증거

1. 매립 Target은 감사 시점에 구형 `2.1.0-g75b946a`였으며 최신 secure MQTT/periodic OTA 구현이 배포됐다는 증거가 없다.
2. 최신 signed artifact의 install → reboot → expected version/boot ID → health confirmation이 필요하다.
3. GPIO3 Active-LOW relay의 High-Z OFF, ECHO 5 V 보호, 전원 강하·노이즈·반복 구동은 물리 Gate다.
4. Wi-Fi/AP/broker/WAN 장애 자동 복구와 벽 매립 연결 SLO는 실기기 증거가 필요하다.
5. Android 화면 OFF/Activity 종료 증거와 force-stop/OEM kill 한계는 구분해야 한다.

### P1 — production 운영

1. production Compose, reverse proxy mTLS, migration, backup/restore는 코드 계약과 live NAS 실행 증거를 구분한다.
2. signed command의 PUBACK/HTTP 성공은 Target authorization, command ACK, FSM과 relay 실행을 증명하지 않는다.
3. Hardwareless RC는 software-complete라는 표현만 허용하며 compile/runtime default-OFF와 physical Gate를 유지한다.
4. iBeacon은 presence hint이지 자격 증명이 아니다. 권한은 approved identity, signed command 또는 local proof가 결정한다.

### P2 — 정리 부채

1. `src/main.cpp`의 GPIO6/7 I²C bus-clear는 현재 AJ-SR04T 배선과 무관한 잔존 코드다.
2. 일부 source 주석과 초기 governance 문서에는 Bluedroid/NimBLE, VL53L0X/ultrasonic 이력이 혼재했다. 현행 지침은 AJ-SR04T와 실제 source를 따른다.
3. 문서별 frontmatter와 status는 새 문서부터 적용하며 기존 전체를 한 번에 재작성하지 않는다.

## 5. 현재 출입 증거 사슬

```text
iBeacon observed
→ Android threshold/session decision
→ HTTPS request accepted
→ approved device/tenant
→ broker PUBACK
→ Target signed command authorization and ACK
→ Target FSM ARMED
→ ultrasonic valid sample
→ relay ON/OFF event
→ physical door outcome
```

각 화살표는 별도 실패 경계다. `mqtt_published=true`는 broker PUBACK까지만 증명한다.

## 6. 현재 OTA 증거 사슬

```text
signed manifest/artifact published
→ Target/mobile identity verification
→ inactive/recoverable staging
→ install/flash
→ reboot/restart
→ expected version and boot identity
→ health window
→ valid mark/application health
```

artifact upload, download 완료, workflow green 또는 MQTT PUBACK만으로 OTA 성공을 선언하지 않는다.

## 7. 문서 신뢰도 규칙

- 현재 요약: [project_status.md](project_status.md)와 이 문서
- 세부 현재 계약: 실제 source/tests와 각 component 문서
- 현장 배포: 사건·release evidence 문서
- 검증 결과: [hardware_test.md](hardware_test.md) 및 run/artifact 식별자가 있는 기록
- 과거 사실: append-only [log.md](log.md); 당시 사실을 현행으로 사용하지 않는다.
- 초기 원본: `raw/`; 현재 BOM이나 현재 배선 지시가 아니다.

## 8. 이번 감사의 한계

이 갱신은 commit `406707c`의 source/config/test 계약을 정적으로 추적한다. 새 physical test, NAS 배포, firmware flash, APK install 또는 production authorization을 수행했다는 뜻이 아니다. 테스트 실행 결과는 이번 문서 정리의 최종 검증 기록과 `wiki/log.md`에 별도로 남긴다.
