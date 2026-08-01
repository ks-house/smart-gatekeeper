# 추가 자격 하드웨어 없는 모바일 병목 축소 구현 계획

> 작성일: 2026-08-01
> 상태: **Wave 0 진행 중 — #14 code PoC 완료, Samsung 실기기 Gate pending**
> 결정: secure BLE fob, NFC reader/card, QR scanner 등 추가 자격 하드웨어는 보류
> 현재 하드웨어: ESP32-C6 Target + AJ-SR04T + relay 유지
> 1차 플랫폼: 현재 운영 대상인 Android. iOS 자동 출입은 별도 후속 의사결정
> P0 불변조건: 모바일 앱·Target OTA/rollback 가능성은 모든 단계에서 유지 ([#23](https://github.com/ks-house/smart-gatekeeper/issues/23))

2026-08-01 #14 진행 상황: filtered `BluetoothLeScanner` + `PendingIntent`를 기준
wake 경로로 선택하고 Flutter-independent native receiver, exact iBeacon filter contract,
hardwareless test seam을 구현했다. 상세 결정과 미완료 20회 Gate는
[android_ble_wake_adr.md](android_ble_wake_adr.md)를 따른다. Samsung 실기기 수치가
없으므로 I1과 G0는 아직 완료가 아니다.

## 1. 목표와 현실적 한계

### 목표

추가 하드웨어 없이 현재 smartphone 기반 자동 출입을 유지하면서 다음 모바일 책임을
정상 출입의 필수 경로에서 제거하거나 Android system API로 이동한다.

- 상시 Flutter foreground-service isolate
- Flutter↔native scanner IPC
- AltBeacon monitoring/ranging 상태 머신
- 모바일 RSSI EMA와 화면 OFF 임시 우회
- 모바일의 Pre-arm REST 호출
- 정상 출입 시점의 NAS·DB·MQTT 실시간 응답
- 모바일 cooldown이 소유하는 출입 세션

### 제거할 수 없는 한계

추가 자격 하드웨어가 없으면 스마트폰은 여전히 유일한 사용자 자격이다. 따라서 다음은
소프트웨어만으로 완전히 제거할 수 없다.

- 사용자가 Android 설정에서 앱을 force-stop한 뒤 자동 실행 차단
- Android 13+ 활성 앱 `중지`, OEM restricted battery 상태
- Bluetooth OFF, 권한 회수, 휴대폰 전원 OFF
- Android가 BLE scan event 전달을 지연하거나 누락하는 가능성

따라서 본 계획의 완료 정의는 **“모바일 무관 보장”이 아니라 “Flutter 상시 실행과 WAN
실시간 의존 제거, Android OS-managed wake 사용, 실패 시 사용자 동작 fallback 제공”**이다.

### OTA 불변조건

본 계획의 모든 작업은 [ota_reliability_contract.md](ota_reliability_contract.md)를
release blocking 기준으로 사용한다. BLE wake/GATT/local ACL/FSM 전환 중에도 mobile APK
update와 Target dual OTA는 독립적으로 발견·검증·설치·rollback할 수 있어야 한다.
OTA 비회귀가 확인되지 않으면 해당 Wave는 완료되지 않는다.

## 2. 목표 아키텍처

### 2.1 자동 출입 hot path

```text
ESP32-C6
  connectable BLE advertisement
  + stable service/manufacturer filter
          │
          ▼
Android OS-managed filtered presence trigger
  PendingIntent scan 또는 CompanionDeviceService
          │ app process wake/bind
          ▼
Native Android credential worker
  BLE GATT connect
  → Target nonce/session_id read
  → Android Keystore device key로 proof 서명
          │
          ▼
ESP32-C6 local verification
  local ACL + nonce/counter/expiry 검증
  → IDLE일 때만 ARMED
  → AJ-SR04T 접근 확인
  → relay one-shot
          │
          ▼
Backend에는 access event를 비동기 업로드
```

정상 출입에서 제거되는 경로는 다음과 같다.

```text
제거 전: BLE → Flutter FGS → RSSI → REST → DB → MQTT → Target ARM
제거 후: OS BLE wake → native GATT proof → Target local ARM
```

### 2.2 관리 plane

Backend는 실시간 개방 오케스트레이터에서 관리 plane으로 이동한다.

- 앱 설치 시 Android Keystore device key의 public key 등록
- 관리자 tenant/device 승인
- 승인된 credential ACL을 버전·만료·서명과 함께 Target에 동기화
- 회수/revocation 전파
- Target access event와 health 수집
- 원격 수동 개방은 별도 관리자 경로로 유지

### 2.3 사용자 동작 fallback

OS가 자동 wake를 차단한 상태에는 추가 하드웨어 없이 완전 자동 복구할 수 없다. 다음
fallback을 제공한다.

1. 앱의 명시적 **문 열기/재시도** 동작
2. Android notification action 또는 Quick Settings tile 검토
3. 사용자 동작으로 앱이 visible 상태가 된 뒤 BLE GATT local auth 우선 실행
4. local auth가 실패하고 Backend가 online일 때만 기존 원격 개방 API를 제한적으로 사용

fallback은 자동 출입 실패를 숨기지 않고 `AUTO_WAKE_BLOCKED`, `BLE_AUTH_FAILED`,
`TARGET_OFFLINE` 같은 reason code를 표시해야 한다.

## 3. 핵심 기술 결정

### 3.1 Android presence trigger

다음 두 후보를 PoC로 비교한 뒤 하나를 기준 경로로 확정한다.

| 후보 | 장점 | 제약 | 선정 기준 |
|---|---|---|---|
| Filtered `BluetoothLeScanner` + `PendingIntent` | process가 없을 때 matching scan result로 깨울 수 있음, 기존 iBeacon payload 활용 가능 | Android 12+ background 후속 작업 제약, OEM 실측 필요 | 화면 OFF/프로세스 kill 뒤 wake 성공률과 지연 |
| Companion Device Manager/Service | system association, background service 권한 경로 | filter 제한, Target 광고/GATT 변경 가능성 | association UX, stable identity, OEM 생존성 |

현재 AltBeacon callback scan은 비교 기준선으로만 유지한다. PoC는 동일 Target·거리에서
화면 OFF, Activity 종료, process kill, 재부팅 조건을 각각 20회 이상 측정한다.

### 3.2 BLE transport

Target은 iBeacon-only advertiser에서 **connectable BLE GATT peripheral**을 병행하는
방향으로 설계한다.

- advertisement에는 OS filter가 가능한 stable service/manufacturer identifier 포함
- 인증 characteristic은 challenge read, proof write, result indication으로 분리
- session은 짧은 timeout과 단일 사용 nonce를 가진다.
- GATT 연결이 Wi-Fi/MQTTS/OTA와 공존할 때 heap, latency, reset이 없는지 먼저 검증한다.
- 광고 UUID/RSSI는 presence 후보일 뿐 최종 인증 자격이 아니다.
- 현재 phone-only BLE proof는 key possession을 인증하지만 transparent real-time relay에 대한
  proximity를 증명하지 않는다. hands-free production은
  [security protocol의 RELAY-G](security_protocol.md#44-실시간-relaywormhole-경계와-배포-gate)를
  통과하기 전 기본 비활성이다. `relay_resistant_channel` feature flag만으로 enable하지 않고,
  threat-model/proxy 결과/risk-owner 승인(G0), 선택 경로와 일치하는 방어 evidence(G1), 같은 경로의
  100회 전 성공 실기기 운용과 OTA rollback evidence(G2)가 모두 유효할 때만 fail-closed 정책을 연다.

### 3.3 기기 자격

> 아래 보안 계약의 동결 기준과 canonical bytes는
> [security_protocol.md](security_protocol.md)를 따른다.

- 앱 최초 등록 때 Android Keystore에서 device별 P-256 key pair 생성
- private key는 export하지 않으며 자동 출입을 위해 user-auth requirement는 두지 않는
  안을 기본 PoC로 검토
- Backend에는 public key, credential ID, tenant, 상태, expiry만 저장
- Target ACL에는 public key 또는 검증에 필요한 최소 정보만 저장
- 기존 random `device_id`와 shared API key는 migration lookup에만 쓰고 최종 proof가 아님

자동 출입에서 잠금 해제를 요구하지 않는 선택은 편의성과 분실 휴대폰 위험의 trade-off다.
회수 지연, Android 화면 잠금, 관리자 비활성화 정책을 보안 검토에서 확정한다.
user-auth 없는 silent signing은 피해자 근처 proxy가 문 앞 real Target과 5초 안에 통신을 중계하는
wormhole을 막지 못하므로, 이 모드는 low-consequence door의 명시적 risk acceptance 또는
relay-resistant channel이 없으면 PoC에만 한정한다.

### 3.4 challenge-response

Target이 매 연결마다 다음 challenge를 만든다.

```text
protocol_version | door_id | session_id | nonce | target_boot_id | expires_at
```

Android credential worker는 challenge 전체를 device private key로 서명하고 credential ID와
함께 보낸다. Target은 다음을 확인한다.

- protocol version 지원
- session/nonce 미사용 및 timeout 전
- credential이 local ACL에서 active
- ACL lease가 유효
- signature가 해당 public key와 일치
- Target FSM이 IDLE

성공/거부 결과에는 동일 `session_id`와 고정 reason code를 포함한다.

### 3.5 local ACL과 offline 정책

- Backend가 단조 증가 `acl_version`과 `issued_at`, `expires_at`을 가진 signed snapshot 발행
- Target은 서명·버전·expiry 검증 뒤 새 namespace에 저장하고 원자적으로 active 전환
- revocation은 MQTT push + 주기적 HTTPS/MQTT pull 중 최소 두 경로로 수렴
- ACL lease 만료 뒤에는 자동 출입 fail-closed
- issue #16 보안 검토 결과 offline lease는 기본 900초, hard max 3,600초로 확정
- trusted UTC가 없는 reset 뒤에는 새 signed snapshot을 받기 전 자동 출입 fail-closed
- 현재 broker 후보 순회는 ACL/명령 계약에서 제거하고 명시된 logical broker만 사용

## 4. Target 상태 머신

```text
IDLE
  ├─ BLE 연결/challenge 발급 → AUTH_PENDING
  │    ├─ proof valid → ARMED
  │    ├─ proof invalid/expired → IDLE
  │    └─ disconnect/timeout → IDLE
  └─ admin force_open → RELAY_HOLD

ARMED
  ├─ 유효 초음파 접근 → RELAY_HOLD
  └─ arm timeout → IDLE

RELAY_HOLD → COOLDOWN → PASSAGE_CLEAR/timeout → IDLE
```

- 인증 성공과 물리 접근은 같은 `session_id`에 속한다.
- ARMED/RELAY_HOLD/COOLDOWN 중 새 proof는 `BUSY`로 거부한다.
- 한 물리 접근이 끝나기 전 같은 credential의 재인증은 새 개방으로 처리하지 않는다.
- relay timer one-shot과 boot default OFF는 기존 fail-safe를 유지한다.
- 향후 door contact가 없으므로 `PASSAGE_CLEAR`는 현재 센서 기반 휴리스틱이며 한계를
  별도 기록한다.

## 5. 작업 파동과 병렬 실행

```text
Wave 0 — 계약과 측정
  I1 Android wake ADR ─────────────┐
  I2 session/event observability ──┼─────────────┐
  I3 security/ACL protocol ────────┘             │
  I10 mobile/Target OTA contract ────────────────┤
                                                 │
Wave 1 — 병렬 구현                               │
  I4 Android native wake/credential worker ◀ I1,I3
  I5 Target GATT transport/coexistence     ◀ I1,I3
  I6 Backend key enrollment/signed ACL     ◀ I3
  I7 Target local auth/FSM                 ◀ I2,I3,I5
                                                 │
Wave 2 — 통합                                    │
  I8 Flutter thin UI + user fallback       ◀ I4,I6,I7
                                                 │
Wave 3 — 검증/전환                               │
  I9 E2E fault injection/rollout           ◀ I2,I4,I6,I7,I8
```

### 병렬화 규칙

- Wave 0의 I1/I2/I3는 서로 독립적으로 시작한다.
- I10은 I1/I2/I3와 병렬로 시작하며 Wave 1~3 전체의 release blocking 계약이다.
- I3가 protocol field와 cryptographic primitive를 freeze하면 I4/I5/I6이 병렬 시작한다.
- I5는 GATT transport와 radio coexistence만, I7은 proof/ACL/FSM을 담당해 같은 Target
  파일 충돌을 줄인다. 두 작업의 interface header/contract는 I3에서 먼저 고정한다.
- I8은 Flutter UI만 소유하며 native worker와 Target protocol을 재구현하지 않는다.
- I9 전에는 legacy path feature flag와 rollback 절차가 반드시 존재해야 한다.

## 6. GitHub 작업 단위

| ID | GitHub issue | 작업 | 병렬 가능 | 선행조건 |
|---|---|---|---|---|
| I0 | [#13](https://github.com/ks-house/smart-gatekeeper/issues/13) | Epic: 추가 하드웨어 없는 모바일 병목 축소 | 조정 | 없음 |
| I1 | [#14](https://github.com/ks-house/smart-gatekeeper/issues/14) | Android OS-managed BLE wake ADR/PoC | 예 | 없음 |
| I2 | [#15](https://github.com/ks-house/smart-gatekeeper/issues/15) | cross-layer session ID·event reason schema | 예 | 없음 |
| I3 | [#16](https://github.com/ks-house/smart-gatekeeper/issues/16) | device key·challenge-response·signed ACL 규격 | 예 | 없음 |
| I4 | [#17](https://github.com/ks-house/smart-gatekeeper/issues/17) | native Android wake·GATT credential worker | I5/I6과 병렬 | #14, #16 |
| I5 | [#18](https://github.com/ks-house/smart-gatekeeper/issues/18) | ESP32-C6 connectable GATT·radio coexistence | I4/I6과 병렬 | #14, #16 |
| I6 | [#19](https://github.com/ks-house/smart-gatekeeper/issues/19) | Backend key enrollment·ACL sync/revocation | I4/I5와 병렬 | #16 |
| I7 | [#20](https://github.com/ks-house/smart-gatekeeper/issues/20) | Target local auth·access session FSM | 제한적 병렬 | #15, #16, #18, #19 계약 |
| I8 | [#21](https://github.com/ks-house/smart-gatekeeper/issues/21) | Flutter thin UI·사용자 동작 fallback·legacy flag | 통합 단계 | #17, #19, #20 |
| I9 | [#22](https://github.com/ks-house/smart-gatekeeper/issues/22) | E2E 장애 주입·OEM matrix·staged rollout | 마지막 | #15, #17, #19, #20, #21 |
| I10 | [#23](https://github.com/ks-house/smart-gatekeeper/issues/23) | 모바일 앱·Target OTA 비회귀·복구 계약 | Wave 0 병렬/전 단계 blocking | 없음 |

## 7. 이슈별 완료 계약

### I1 — Android wake ADR/PoC

산출물:

- PendingIntent scan과 CompanionDeviceService 비교표
- 현재/변경 Target advertisement filter byte contract
- Android API/OEM별 20회 측정 결과와 p50/p95/max wake latency
- 선정 ADR과 미선정 후보 사유

완료 기준:

- 화면 OFF와 UI process 비실행 상태에서 선정 방식이 app native entrypoint를 호출
- force-stop은 미지원으로 명시하고 탐지/안내 계약 정의
- 위치·BLE·FGS 권한 최소 세트 확정

### I2 — session/event observability

산출물:

- `session_id`, `boot_id`, monotonic sequence, stage, reason code schema
- Android/Target/Backend 공통 event 이름과 timestamp 규칙
- 기존 로그와 새 schema migration mapping

완료 기준:

- 한 출입을 scan wake부터 relay OFF까지 단일 session으로 조회 가능
- 성공/거부/timeout이 자유 텍스트가 아닌 고정 reason code를 가짐

### I3 — security/ACL protocol

산출물:

- Keystore key lifecycle과 enrollment/revocation sequence
- BLE challenge/proof/result binary or CBOR/JSON schema
- signed ACL snapshot schema, lease/offline 정책, threat model
- nonce/counter/replay, clock 부정확, Target reset 처리 규칙

완료 기준:

- 고정 UUID, BLE MAC, device ID, shared API key만으로 승인 불가
- 캡처 proof 재전송과 다른 door/session 재사용이 거부됨
- crypto primitive와 canonical signing bytes test vector 제공

### I4 — native Android worker

산출물:

- OS-managed presence callback receiver/service
- BLE GATT connect, challenge read, Keystore sign, proof write, result receive
- native 진단 저장과 Flutter 조회 bridge

완료 기준:

- Flutter engine이 실행 중이지 않아도 자동 인증 시도
- 동일 presence event 중복 병합과 backoff 적용
- network가 꺼져 있어도 local GATT auth 시도
- legacy scanner와 동시 BLE ownership 금지

### I5 — Target GATT/coexistence

산출물:

- connectable advertisement와 filter contract
- auth GATT service/characteristics
- session timeout, disconnect cleanup, connection limit
- Wi-Fi/MQTT/OTA/advertising/GATT coexistence 측정

완료 기준:

- 100회 connect/challenge/proof transport에서 reset·heap regression 없음
- MQTT reconnect와 OTA check 중에도 relay fail-safe 유지
- malformed/oversized write가 crash를 유발하지 않음

### I6 — Backend enrollment/ACL

산출물:

- device public key 등록·관리자 승인·회수 API/DB migration
- signed ACL snapshot/version/lease 발행
- Target ACK가 있는 sync 상태와 운영 UI

완료 기준:

- private key 또는 공통 device secret을 Backend가 받지 않음
- 비활성화된 tenant/credential이 다음 sync에서 Target ACL에서 제거
- stale/downgrade ACL 거부와 감사 로그 존재

### I7 — Target local auth/FSM

산출물:

- ACL atomic storage/load/validation
- signature, nonce, expiry, active 상태 검증
- AUTH_PENDING/ARMED/RELAY_HOLD/COOLDOWN state transition
- session event publish/queue

완료 기준:

- Backend·MQTT가 끊긴 상태에서도 lease 내 credential은 출입 가능
- lease 만료/회수/invalid proof는 fail-closed
- 한 접근에서 relay 1회, timer cutoff 보존

### I8 — Flutter thin UI/fallback

산출물:

- credential 등록/승인/회수 상태 화면
- native worker health와 마지막 session reason 표시
- 사용자 동작 local retry 및 제한된 remote fallback
- legacy/new path feature flag와 rollback UI

완료 기준:

- Flutter UI가 BLE scanner owner가 아님
- 정상 자동 출입에 WebView·foreground service·REST prearm이 필요하지 않음
- 자동 wake 차단 상태를 숨기지 않고 사용자 복구 동작 제공

### I9 — 검증과 rollout

산출물:

- 화면 ON/OFF, Activity kill, process kill, reboot, force-stop, Bluetooth/권한 변화 matrix
- Backend/DB/MQTT/Wi-Fi 차단과 ACL lease/revocation 시험
- Samsung 운영 기기 중심 OEM 반복 시험과 latency/success 통계
- legacy/new A/B, canary, rollback runbook

완료 기준:

- new path 유효 credential 100회 연속 성공 목표 검증
- local auth p95, door-open p95, battery impact 수치화
- 모든 실패가 session/reason으로 추적됨
- legacy 제거 여부를 데이터 기반으로 결정

### I10 — 모바일 앱·Target OTA 비회귀와 복구

산출물과 완료 기준은 [ota_reliability_contract.md](ota_reliability_contract.md)와
GitHub [#23](https://github.com/ks-house/smart-gatekeeper/issues/23)을 따른다.

- Target dual-slot health/rollback, periodic HTTPS, MQTT, local wireless recovery
- mobile update manager의 scanner/UI 독립성, artifact 검증, fallback distribution
- mobile/Target 독립 배포와 N/N-1 compatibility
- 다운로드·설치·flash·부팅 실패 시 기존 정상 버전 보존
- #17~#22가 사용할 공통 OTA regression matrix와 release gate

## 8. 공통 Definition of Done

모든 구현 이슈는 다음을 만족해야 완료할 수 있다.

- 해당 모듈 단위 테스트와 protocol test vector 통과
- 실패가 fail-closed이며 relay 기본 OFF와 one-shot cutoff 유지
- 신규 시크릿 원문을 log, wiki, issue, artifact에 기록하지 않음
- 관련 wiki 페이지와 `wiki/log.md` 동기화
- legacy와 new path가 동시에 동일 BLE owner/relay session을 소유하지 않음
- 기능 flag, rollback 조건, 운영 관측 항목 문서화
- 코드 리뷰에서 security contract와 state ownership 변경을 별도 확인
- mobile/Target OTA reachability, artifact integrity, N/N-1 호환, rollback 영향 확인

## 9. 전환 gate

| Gate | 통과 조건 | 실패 시 |
|---|---|---|
| G0 설계 freeze | I1/I2/I3/I10 승인, protocol·OTA contract 확정 | 구현 시작 금지 |
| G1 component PoC | I4/I5/I6 독립 테스트 통과 | 해당 track 재설계 |
| G2 local E2E | Backend/MQTT 차단 상태에서 local auth→relay 성공 | legacy 유지, rollout 금지 |
| G3 field canary | Samsung 실기기 100회, 화면 OFF 성공률/지연 목표 충족 | feature flag OFF |
| G4 production | 회수·lease·OTA rollback·관측 runbook 승인 | legacy 병행 유지 |
| G5 legacy retirement | 충분한 운영 기간 동안 new path SLO 충족 | legacy 제거 보류 |

## 10. 이번 범위 밖

- NFC reader/card, secure BLE fob, QR scanner 추가
- iOS background automatic entry 보장
- UWB/geofence/Wi-Fi presence
- door contact/exit button 신규 하드웨어
- 관리자 인증 전체 개편과 PCB 양산

다만 소프트웨어 경로가 운영 SLO를 충족하지 못하면 추가 자격 하드웨어 보류 결정을
재검토하는 것이 최종 fallback이다.
