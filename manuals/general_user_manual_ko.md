# 일반 사용자 매뉴얼 / General user manual

문서 버전: **0.3.0-rc.1** · 제품 기준: `e42d1f417a555b17d7476522aa48f7e4d72306b7`<br>
대상: 입주자·일반 사용자 · 상태: **앱 software 구현 반영; Samsung/OEM·Target·relay·production 인수 대기**

## 1. 안전하게 읽는 법

Smart Gatekeeper는 Android 앱, backend, ESP32-C6 Target, 거리 센서와 relay로 구성된다. 앱의 `준비`, `armed`, 다운로드 완료, MQTT 전송 완료만으로 문이 열렸다고 판단하지 않는다. `문 열림 확인 / confirmed`와 실제 문 동작이 일치할 때만 통과한다. `결과 불명 / unknown`이면 버튼을 반복 누르지 말고 현장 안전을 확인한 뒤 지원팀에 연락한다.

| 화면 상태 | 뜻 | 사용자 행동 |
|---|---|---|
| `detecting` | 최근 Target을 찾는 중 | 30초 안에 변화가 없으면 Bluetooth·권한 확인 |
| `authorizing` | 자격과 Target 응답 확인 중 | 추가 탭 금지 |
| `armed` | 접근 감지를 기다림; 문은 아직 닫힘 | 센서 범위로 이동 |
| `opening` | Target 확인 대기; 물리 성공 미확정 | 문과 안전 상태 관찰 |
| `confirmed` | Target 성공 결과가 기록됨 | 실제 문 동작과 불일치하면 즉시 신고 |
| `unknown` | 효과를 확정할 수 없음 | 자동 재시도 금지, event ID 보존 |
| `failed` | 거부 또는 통신 실패 | reason에 따른 1회 복구 후 escalation |

## 2. 설치와 첫 실행

공식 배포 담당자가 제공한 서명 APK만 사용한다. 메신저 링크, WebView 링크, 임의 URL에서 APK를 설치하지 않는다. 앱은 replacement APK의 첫 실행 health를 권한·Bluetooth·WebView보다 먼저 확인한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 사용자 | 공식 APK, Android 저장 공간, 설치 허용 정책 | APK 설치 후 앱 1회 실행 | 이전 update가 있으면 package/build/version/APK digest/signer가 일치할 때만 `healthy`; 불일치는 `failed` | `UpdateChecker.reconcilePendingFirstRunHealth`, `UpdatePackageIdentityPolicy.kt` | APK SHA-256, build/version, 화면 reason | 첫 화면 30초 검증 목표 | 앱 재실행 1회; 재설치 0회 | `UPDATE_HEALTH_*` reason과 digest를 release owner에 전달; 이전 APK 삭제 금지 |
| 사용자 | 첫 실행 안내를 읽을 수 있음 | `동의하고 계속` 또는 `나중에 설정 — 복구 화면 사용` | 동의 전에는 OS 권한·배터리 예외 요청 0회; 미루면 recovery shell | `BackgroundDisclosureScreen`, `BackgroundConsentStore` | consent widget tests와 선택 화면 | 선택 제한 없음 | 저장 실패 시 1회 | `BACKGROUND_CONSENT_UNAVAILABLE`이면 지원팀; 앱 데이터 삭제 금지 |
| 사용자 | 동의 선택, Android 설정 접근 | 요청된 항목만 허용: 위치, Android 12+ Bluetooth, Android 13+ 알림, Android 10+ 항상 위치, 전용 배터리 최적화 예외 | 모두 충족하면 `백그라운드 출입 감지 준비 완료`; 누락 시 항목 목록과 recovery shell | `BackgroundSetupController`, `ForegroundServiceManager`, `BleWakeRegistrar.kt` | permission transition host tests; Samsung 결과 **PENDING** | OS 화면별 30초 검증 목표 | 설정 복귀 후 자동 확인 1회, `다시 시도` 1회 | 누락 항목·OS/OEM/build를 지원팀에 전달; 권한을 무작정 반복 요청하지 않음 |

### Samsung/One UI 확인

1. 설정에서 Smart Gatekeeper의 근처 기기, 위치 `항상 허용`, 알림을 확인한다.
2. 배터리 설정에서 앱이 최적화 예외 대상인지 확인한다. 앱은 전용 Android 예외 화면을 연다.
3. One UI의 절전 앱/자동 실행 제한이 있으면 조직이 승인한 설정만 변경한다.
4. 앱으로 돌아와 `Ready`, `Degraded`, `Blocked`와 누락 항목을 확인한다.

화면 OFF, 재부팅, 앱 process kill, force-stop은 서로 다른 조건이다. force-stop 이후 Android가 앱을 다시 실행하도록 보장할 수 없으며, 100회 Samsung matrix가 끝나기 전까지 자동 출입을 상용 보장하지 않는다.

## 3. 등록·승인

현재 Web shell의 익명 등록, device-ID 상태 조회와 remote-open은 의도적으로 비활성화되어 있다. 사용자가 화면에서 보이지 않는 URL을 직접 호출하거나 Backend secret을 앱에 넣으면 안 된다. tenant/door/device-bound possession credential과 mobile v2 envelope가 구현·배포될 때까지 등록은 관리자가 승인된 별도 절차로 수행하며, 앱의 remote 기능은 unavailable 상태가 정상이다. #52 운영 병합은 이 사용자 credential gap을 자동으로 닫지 않는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 사용자 | 본인 확인 채널, privacy 안내 확인 | 관리자에게 등록 요청과 opaque 사용자 참조 전달 | 접수 ID와 `unregistered` 또는 `pending`; 즉시 `approved`로 추정 금지 | mobile/backend credential owner; Flutter `EnrollmentState` | 접수 ID; credential workflow **BLOCKED** | 접수 응답 15초 검증 목표 | 동일 접수 ID 1회 | credential owner에 접수 ID 전달; MAC·secret 전송 금지 |
| 관리자 | tenant scope, 대상 door, 승인 권한 | credential 승인/거부 | 앱/Target ACL에서 `approved`, `revoked`, `expired` 중 실제 상태; Target ACK 전 효과 미확정 | `acl_management.py`, `acl_api.py`, Target ACL | ACL version, audit ID, Target ACK **PHYSICAL PENDING** | backend 15초·Target ACK 60초 검증 목표 | 같은 idempotency 1회 | `TARGET_ACK_PENDING`이면 Target owner; force-open으로 우회 금지 |
| 사용자 | 승인 통보 후 앱 재진입 | 상태 새로고침 | `approved`와 만료 시각 또는 정확한 reason | Flutter enrollment model, credential client rollout | redacted screenshot + ACL version | 30초 검증 목표 | foreground 재진입 1회 | 계속 `pending/unregistered`이면 credential owner |

## 4. 자동 출입

자동 출입은 실기기 인수 전에는 시험 기능이다. 첫 물리 시험은 [Issue #54 체크리스트](../physical_validation/checklists.md)를 사용한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 사용자 | `approved`, 모든 background requirement, Bluetooth·위치 service ON, 최근 유효 Target | Target 방향으로 이동 | `detecting → authorizing → armed`; `armed`는 문 열림 아님 | Flutter scanner/native wake, backend pre-arm | session ID, permission/OEM state; Samsung **PENDING** | discovery 30초 | foreground 재진입 1회 | `Blocked/Degraded` reason과 OEM/build를 지원팀에 전달 |
| Target | 유효 자격, safe state, 센서 범위, relay cooldown 종료 | 접근 감지 | `opening` 후 Target 결과; relay는 1초 hold 뒤 OFF | `TargetAccessFsm.cpp`, `GattServer.cpp`, `RelayController.cpp` | boot/session/event ID와 relay trace **PHYSICAL PENDING** | GATT 15초·relay 1초 source 값 | 자동 effect retry 0회 | `unknown`, timeout, unexpected relay면 현장 안전 owner |
| 사용자 | Target 결과 관찰 가능 | 문 통과 | `confirmed`와 실제 문 동작이 일치 | Android durable GATT ledger + Target event | redacted event와 물리 관찰 **PENDING** | 15초 | 동일 session 수동 1회는 reason이 retryable일 때만 | 불일치면 출입 중지, event ID로 incident 접수 |

## 5. 수동 복구 출입

`Manual local`은 최근 OS-filtered wake가 암호화 저장한 Target locator, Keystore identity, 유효 credential, Bluetooth ON과 freshness가 모두 있어야 한다. sentinel 주소나 사용자가 입력한 MAC을 사용하지 않는다. `Manual remote`는 tenant/door/device-bound possession credential이 배포되기 전까지 사용할 수 없다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 사용자 | 승인된 이 휴대폰 credential, Backend 연결 | 정상 Home의 `문 열기` 1회 | exact phone credential 서명 후 Backend가 Target-bound 명령을 전달; broker 수락은 물리 문 열림 확정이 아님 | `RemoteManualOpenService`, `/api/v1/mobile/door/open` | redacted command event와 Target/relay 결과 **PHYSICAL PENDING** | 요청 15초 검증 목표 | 결과 불명이면 자동 재시도 0회 | 비밀키 입력·legacy API 우회 금지; mobile/backend/현장 owner |
| 사용자 | 권한 거부 또는 설정 미완료, recovery shell 접근 | 검증된 앱 update 확인, Android 설정 열기 또는 권한·배터리 설정 재시도 | update/OS 설정/재시도만 노출되고 GATT·RSSI·Target tuning과 수동 문 제어는 노출되지 않음 | `RecoveryShellScreen`, `BackgroundSetupController` | recovery widget tests; Samsung **PENDING** | 화면 30초 검증 목표 | 설정 복귀 후 1회 | 계속 blocked면 reason과 OEM/build를 지원팀에 전달 |
| 관리자 2인 | 안전 현장, 별도 `SECURITY_OPERATOR`/`SECURITY_APPROVER` | 승인된 force-open 절차 | `approval_required → published`; 실제 Target event 전 `EFFECT_UNKNOWN` | admin force-open APIs, signed command plane | approval/audit/broker/Target/relay evidence | proposal 300초, effect 120초 검증 목표 | publication/effect 0회 | incident commander와 현장 safety owner |

## 6. Offline·권한·Bluetooth·재부팅 복구

| 증상 | Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|---|
| Backend/network offline | 사용자 | local UI 접근 가능 | 네트워크 상태 확인 후 앱 복귀 | `offline/degraded`와 마지막 확인 시각; 문 열림 성공 없음 | Flutter, backend `/live`·`/ready` | readiness/event bundle **OPS PENDING** | broker probe 1초 source 값, 사용자 화면 10초 검증 목표 | read-only 확인 5초→30초 최대 2회 | 지원팀·현장 안전 담당; `/live`를 전체 정상으로 해석하거나 TLS 검증 해제 금지 |
| Bluetooth OFF | 사용자 | recovery shell 접근 가능 | Bluetooth ON 후 다시 시도 | `Blocked → Ready/Degraded`와 next action | native wake status | Samsung evidence **PENDING** | 30초 | 1회 | 계속 blocked면 OS/OEM/build 전달 |
| 권한 거부/회수 | 사용자 | Android 설정 접근 가능 | 누락 항목만 수정 | 누락 목록이 줄거나 exact blocked reason 유지 | background setup | permission host tests | 30초 | 설정 복귀 1회 | 앱 재설치·자격 삭제 금지, mobile owner |
| 재부팅/package 교체 | 사용자 | force-stop이 아니며 앱 설치 상태 정상 | 앱 1회 열고 상태 확인 | native wake 재등록과 update health 또는 recovery shell | `BleWakeBootReceiver`, updater | boot/package host tests; OEM **PENDING** | 60초 검증 목표 | 앱 재실행 1회 | `not_registered/unavailable`이면 지원팀 |
| 결과 `unknown` | 사용자 | 현장 안전과 session ID 확인 | boot/event ID 캡처 | 동일 unknown 유지; confirmed로 승격하지 않음 | durable ledger/observability | event correlation **PHYSICAL PENDING** | 15초 | 자동 0회 | 즉시 incident owner |

## 7. 앱·Target 업데이트와 rollback

정상 앱의 `설정`에서 현재 설치 버전, 배포 가능한 버전, 다운로드 진행률과
교체 설치 후 첫 실행 상태를 함께 확인한다. 설치 버튼은 Android 설치 확인
화면으로 이어지며, 사용자가 취소하거나 검증이 실패하면 기존 앱과 자격을
삭제하지 않는다. `다운로드 완료`는 설치 완료가 아니다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 사용자 | primary/secondary HTTPS metadata, pinned key, 충분한 저장 공간 | `Check verified app update` | `checking → available/healthy/failed`; 서명·schema·시간·protocol 불일치는 failed | `UpdateChecker`, `SignedUpdateManifest` | signed manifest, reason; production signature **PENDING** | metadata/download 각 60초 검증 목표 | primary/fallback 각 1회 | failure reason과 artifact digest를 release owner에 전달 |
| 사용자 | verified manifest와 APK | update 설치 시작 | size/hash/package/version/commit/단일 cert 일치 후에만 Android installer; old APK/credential 보존 | `UpdateArtifactValidator`, protected producer | APK/manifest digest, cert digest | 60초 검증 목표 | installer 재호출 0회 | 설치 취소/실패 시 기존 앱 유지, 재서명 금지 |
| replacement 앱 | installer 완료 | 첫 실행 | installed APK identity exact match 후 `healthy`; 아니면 failed/pending 보존 | first-run health reconciliation | app identity record; physical install **PENDING** | 60초 검증 목표 | 앱 재실행 1회 | release owner; 기존 앱 데이터 삭제 금지 |
| release owner/Target | safe state, signed Target manifest, inactive slot, last-known-good slot | canary OTA | install→reboot→연속 30초 health 또는 120초 deadline rollback | `OtaManager.cpp`, ESP-IDF rollback | exact digest, boot/health/rollback event **PHYSICAL PENDING** | health deadline 120초 source 값 | install 0회, rollback 1회 | OTA-G1..G4가 끝날 때까지 production 금지 |

## 8. 휴대폰 분실·교체·회수

1. 공개 채널에 전화번호, MAC, tenant, key를 올리지 말고 승인된 본인 확인 채널로 즉시 신고한다.
2. ticket ID와 분실 시각을 받는다. 이전 credential의 backend `revoked`와 Target ACL ACK는 별도 상태다.
3. 이전 기기의 물리 출입 거부 evidence 전에는 회수 완료로 판단하지 않는다.
4. 새 기기는 공식 APK 설치와 첫 실행부터 다시 수행하며 이전 secret을 복사하지 않는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 사용자 | 분실·교체 사실 | redacted 신고 | ticket ID, `revocation_pending` | credential support process | redacted ticket | 15초 검증 목표 | 동일 ticket 1회 | security owner |
| 관리자 | 본인 확인, tenant scope, reason | old credential revoke, replacement approval | backend `revoked`, monotonic ACL, Target ACK pending/complete | ACL management/Target ACL | audit/ACL/Target event **PHYSICAL PENDING** | backend 15초, Target 60초 목표 | 같은 idempotency 1회 | Target/incident owner |
| 사용자 | 새 기기 별도 승인 | 이전·새 기기 상태 확인 | 이전 기기 거부, 새 기기 `approved`; 한 기기의 성공으로 다른 상태 추정 금지 | mobile enrollment/Target verifier | denied/approved evidence **PHYSICAL PENDING** | 60초 | 0회 | credential + physical owner |

## 9. 접근성·언어·지원 정보

- TalkBack으로 제목→상태→누락 요구사항→주요 행동 순서와 live-region 상태를 읽는다.
- 200% 글자 크기, 작은 화면, 가로 화면에서 버튼과 reason이 잘리지 않는지 확인한다.
- 색상만으로 성공·실패를 구분하지 않고 항상 상태 텍스트와 reason을 확인한다.
- 정상 Home/Activity/Settings와 지원 흐름은 생성된 `ko`/`en` 리소스로 OS
  언어를 따른다. 일부 첫 실행/recovery 문구의 완전한 영문 인수는 연결된
  화면 검증 전까지 보장하지 않는다.

지원 bundle에는 ticket ID, 시간대, app/firmware/backend version, opaque target/session/boot/event ID, reason, state transition, artifact SHA-256와 마지막 관찰 결과만 포함한다. 비밀번호, token, private key, proof, nonce, 원본 tenant/unit/name/MAC, 주소와 URL query는 제거한다. 자세한 절차는 [지원·사고 대응 핸드북](support_incident_handbook_ko.md)을 따른다.

앱의 `설정 → 지원 리포트`에서 먼저 제거된 내용만 미리 본다. 복사 동의
체크 전에는 복사할 수 없으며, 동의 후 복사한 JSON만 승인된 지원 채널에
붙여 넣는다. 화면 캡처나 로그 전체를 대신 보내지 않는다.
