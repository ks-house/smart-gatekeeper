# Hardwareless 매뉴얼 walkthrough

문서 버전: **0.3.0-rc.1** · 제품 기준: `e42d1f417a555b17d7476522aa48f7e4d72306b7`<br>
목적: 신규 사용자·관리자·설치자·지원자가 매뉴얼만으로 핵심 여정과 실패 경계를 이해하는지 host에서 반복 검증한다.

## 실행 방법

1. reviewer는 대상 매뉴얼만 읽고 [`walkthrough-fixtures-v1.json`](walkthrough-fixtures-v1.json)의 scenario를 순서대로 수행한다.
2. `command`는 실제 hardware effect를 만들지 않는 unit/contract test 또는 문서 검사만 사용한다.
3. `expected` token과 exit code가 모두 맞을 때 hardwareless pass로 기록한다.
4. 결과에 exact commit, command, start/end, stdout artifact digest와 reviewer를 기록한다.
5. hardwareless pass를 physical/operator/production pass로 복사하지 않는다.

## 16개 독립 여정

| ID | Actor | 목표 | 기대 결과 | 남은 Gate |
|---|---|---|---|---|
| HWL-USER-01 | 신규 사용자 | consent 전 system request가 없고 defer recovery가 있는지 확인 | disclosure/defer와 consent-order tests PASS | Samsung permission UI |
| HWL-USER-02 | 권한 거부 사용자 | recovery shell에서 manual/update/diagnostics 접근 | recovery capability widget tests PASS | Samsung/OEM screen-off |
| HWL-USER-03 | 출입 사용자 | `unknown`과 `confirmed`를 구분 | model/GATT terminal-state tests PASS | Target/radio/relay effect |
| HWL-USER-04 | 업데이트 사용자 | unsigned/changed APK가 installer에 도달하지 않음 | manifest/artifact identity mutations PASS | signed production APK install |
| HWL-ADMIN-01 | tenant 관리자 | anonymous/cross-tenant/CSRF 요청 fail closed | admin security negative suite PASS | deployed mTLS ingress |
| HWL-ADMIN-02 | 보안 관리자 2인 | proposal과 approval, reconciliation 분리 | force-open tests PASS | broker/Target/relay correlation |
| HWL-ADMIN-03 | release owner | plaintext/rogue CA/invalid command·OTA 거부 | Target security suites PASS | NAS broker/ESP32 physical |
| HWL-ADMIN-04 | backup owner | HMAC manifest와 전체 inventory restore 계약 검증 | operations gate mutation tests PASS | isolated production-like restore |
| HWL-ADMIN-05 | deploy owner | `/live`와 `/ready` admission 경계 구분 | readiness API/contract tests PASS | NAS ingress·broker·DB fault |
| HWL-ADMIN-06 | privacy owner | tenant/purpose/expiry/revocation consent와 redacted export 검증 | support-export negative tests PASS | approved consent capture/ticket lifecycle |
| HWL-ADMIN-07 | tenant admin | retention request와 idempotency key binding 검증 | deletion concurrency/mismatch tests PASS | legal retention approval/NAS drill |
| HWL-INSTALL-01 | 설치자 | GPIO23/GPIO10/11/금지 핀과 3.3V 경계 식별 | source/manual contract PASS | continuity/voltage/waveform |
| HWL-INSTALL-02 | service 기술자 | dual-slot health와 rollback 상태 식별 | OTA host state tests PASS | power-cut/bootloader |
| HWL-SUPPORT-01 | 1차 지원 | redacted bundle의 허용/금지 필드 분류 | logger/manual redaction tests PASS | support system access/retention |
| HWL-SUPPORT-02 | 사고 지휘자 | published/unknown/physical evidence 분리 | event/force-open/manual contract PASS | operator drill/canary |
| HWL-SUPPORT-03 | on-call | MQTT deadline/backpressure/breaker의 bounded failure 확인 | runtime fanout/deadline tests PASS | real DNS/TLS/broker fault and alert ack |

## 반복 결과 기록

| Round | Exact base | Result | 발견한 gap | 반영 |
|---|---|---|---|---|
| R0 baseline | `c654a18f...` | 문서 scaffold | #50/#51을 미구현으로 고정한 stale 설명, mixed locale, ops·physical gap | baseline PR #58 |
| R1 current | `1ce7f16...` | fixture/test 작성, 실행 결과는 PR evidence에 기록 | #50/#51 software를 반영; #52 ops와 Samsung/Target/relay/OTA는 pending; 완전한 ko/en과 admin operator UI gap | 0.2.0-rc.1 매뉴얼과 gap register |
| R2 current | `e42d1f4...` | #52 exact source/API/DB/Compose 역분석과 16개 fixture; 실행 결과는 PR evidence에 기록 | liveness/readiness, consent export, retention, restore, MQTT bounded failure를 반영; NAS/live/legal/physical은 pending | 0.3.0-rc.1 매뉴얼과 gap register |

## NAS 검증 배포 체크리스트

아래는 사용자의 실기기 시험을 가능하게 하는 staging 인수다. production 승격은 아니다.

- [ ] exact main commit과 API/DB image `repository@sha256`를 기록하고 mutable tag를 사용하지 않는다.
- [ ] 외부 secret, internal data network, API/DB host port 없음, source/SQL bind 없음이 rendered `backend/compose.production.yml`과 일치한다.
- [ ] migration이 변경 전 backup+SHA sidecar를 만들고 exact `007` ledger를 기록한 뒤에만 API가 시작한다.
- [ ] `/live` body가 `process_liveness_only`임을 기록하고 `/ready`의 모든 check가 true일 때만 실기기 traffic을 허용한다.
- [ ] mTLS admin/auditor로 metrics를 읽고 tenant/device/MAC label이 없음을 확인한다. alert 전달·ack가 없으면 `OPS PENDING`이다.
- [ ] 위조·만료·철회·cross-tenant consent support export가 403이고, retention key/payload mismatch가 409이며 부작용이 없음을 확인한다.
- [ ] NAS의 APK·firmware·manifest URL, exact digest와 public 접근 범위는 release owner가 별도 검증한다. download/PUBACK는 설치·부팅·물리 성공이 아니다.

## 사용자가 수행할 물리 체크리스트

아래 항목은 이 PR에서 실행하지 않았다. 사용자가 candidate SHA와 app/firmware artifact SHA-256를 고정한 뒤 [Issue #54 plan](../physical_validation/issue54_gate_plan.json), [field checklist](../physical_validation/checklists.md)와 [evidence schema](../physical_validation/schemas/issue54_evidence.schema.json)를 사용한다.

- [ ] `SAMSUNG-WAKE-100`: fresh install, screen-off, reboot, process kill, permission/Bluetooth/network transition을 각 20회
- [ ] `ESP32-C6-COEXISTENCE-100`: BLE/Wi-Fi/Target command coexistence와 reset/rail 관찰
- [ ] `GPIO23-RELAY-100`: boot/idle/active/1초 hold/High-Z OFF/3초 cooldown waveform과 실제 문 effect
- [ ] `AJ-SR04T-BOUNDARY-100`: 20cm blind boundary, 50cm threshold, out-of-range/timeout, 5V ECHO protection
- [ ] `RELAY-G0/G1/G2`: replay, unknown, reset, ACL/credential denial에서 effect-before-success 불변조건
- [ ] `OTA-G1..G4`: signed artifact, inactive-slot boot, continuous health, power/network cut, rollback, local recovery
- [ ] `OPERATOR-DRILLS`: mTLS login, revoke, dual-control, TLS rotation, backup/restore, privacy/support, incident
- [ ] `CANARY-STOP-ROLLBACK`: exact cohort, stop condition, rollback, 별도 reviewer/risk-owner approval

각 trial은 executor와 다른 reviewer, raw capture digest, timestamp, pass-condition ID와 approval을 가져야 한다. capture가 없거나 unsafe observation이 있으면 해당 Gate는 incomplete다.
