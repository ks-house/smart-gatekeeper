# 일반 사용자 매뉴얼 / General user manual

문서 버전: **0.1.1-remediation** · 통합 기준: `b2df34977fe866e129eae373e7056f0f9b3ddc6f`<br>
대상: 입주자/일반 사용자 (resident/end user) · 상태: **제품·실기기 인수 대기**

## 먼저 읽기

Smart Gatekeeper는 앱(Flutter native shell/WebView), NAS backend, ESP32-C6 Target, relay/sensor로 구성된다. 화면에 `성공/Success`가 보이는 것만으로 문이 열렸다고 판단하지 말고, `confirmed` 또는 실제 물리 event가 표시될 때까지 기다린다. 권한이 없거나 상태가 `revoked`, `unknown`, `failed`, `degraded`이면 반복 탭하지 말고 표시된 reason과 지원 절차를 따른다.

## 용어 / Terminology

| 한국어 | English | 의미 |
|---|---|---|
| 승인 대기 | pending | 관리자가 아직 권한을 승인하지 않은 상태 |
| 활성 | active | 출입 요청을 제출할 수 있다고 backend가 판단한 상태; 문 열림 보장은 아님 |
| 회수 | revoked | 해당 자격을 더 이상 사용할 수 없는 상태 |
| 사전 승인 | pre-arm | Target이 센서 접근을 잠시 기다리도록 하는 요청 |
| 수동 원격 개방 | manual remote / force-open | 자동 감지와 별도의 위험 동작; 통제·감사 필요 |
| 성능 저하 | degraded | 일부 기능이 제한되어 다음 행동이 필요한 상태 |
| 미확인 | unknown | 요청 결과 또는 물리 효과를 확인하지 못한 상태 |

## 설치·등록·승인

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 사용자 | 공식 APK/앱, 지원 OS, 네트워크 | 앱 설치·실행, Bluetooth/알림 권한 선택 | 권한별 상태와 다음 행동이 보여야 함; 미표시는 `GAP-51-01` | Flutter UI, `MainActivity.kt` | Samsung/OEM fresh-install walkthrough **PENDING** |
| 사용자 | 앱 설정 화면 접근 가능 | 이름·세대/호수 등 최소 등록 정보 제출 | `pending/승인 대기`와 요청 식별자가 표시되어야 함 | WebView `index.html`, backend user API **GAP** | backend integration evidence **PENDING** |
| 관리자 | 인증된 tenant scope와 승인 정책 | 사용자 승인 | 사용자가 `active/활성`으로 보이고 승인 audit가 생성되어야 함 | `backend/app/acl_*`, #49 | #49 auth/RBAC exact-SHA evidence **PENDING** |
| 사용자 | `active`, Target online, 앱이 target을 식별 | 앱 재진입 또는 자동 동기화 | `Ready/준비됨` 또는 `Degraded/제한됨`과 reason | `gatekeeper_app/lib`, #51 | real device state evidence **PENDING** |

## 자동 출입 / Automatic entry

1. Target 근처에서 앱과 Bluetooth를 켠다. 화면이 꺼져도 OS/OEM 설정이 백그라운드 실행을 허용해야 한다.
2. 비콘이 감지되면 앱은 cooldown을 적용해 pre-arm을 요청한다. `armed/대기 중`은 문이 열린 상태가 아니다.
3. 센서 범위에 접근한 뒤 앱 또는 이벤트에 `confirmed/확인됨`이 나타날 때까지 기다린다. 문이 열리지 않으면 [지원·사고 핸드북](support_incident_handbook_ko.md)을 따른다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 사용자 | `active`, Bluetooth/위치 권한, Target beacon online | Target 방향으로 이동 | 앱에 `detecting → authorizing → armed`와 reason이 표시되어야 함 | `ble_scanner.dart`, `BleWakeRegistrar.kt`, `POST /api/v1/door/prearm` | synthetic/host tests only; Samsung screen-off **PENDING** |
| Target/사용자 | pre-arm이 실제 Target에 도달, sensor/relay 안전 상태 | 센서 유효 범위 접근 | `opening` 후 Target event `confirmed`; 화면 문구만으로 성공 금지 | `TargetAccessFsm.cpp`, `src/GattServer.cpp` | ESP32-C6 + relay physical run **PENDING** |
| 사용자 | target disconnect/timeout 가능 | 표시된 Retry 1회 | `failed`와 `GATT_TIMEOUT/GATT_DISCONNECTED` 등 reason; 무한 재시도 금지 | native GATT worker, `GattSessionEngine.kt` | Android unit/host evidence; physical path **PENDING** |

## 수동 출입 / Manual local or remote

수동 버튼은 자동 출입을 대신하는 안전한 우회가 아니다. 현재 기준선에서 backend `force_open` 경로가 실제 relay 효과를 인증·감사·확인된 상태로 묶는 계약은 열려 있으므로, 관리자가 승인한 비상 상황에서만 지원팀의 지시를 받는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 사용자 | 화면에 수동 버튼이 노출되고 권한·사유 입력이 허용됨 | 사유 입력 후 한 번 탭 | 요청 접수와 `pending/unknown/failed/confirmed`를 분리 표시해야 함 | WebView `POST /api/v1/door/open`, `main.py` | #49 force-open auth/audit **PENDING** |
| 관리자/지원 | 이중 승인·재인증·Target ID 확인 | 승인된 비상 개방 실행 | 실제 Target event와 audit ID가 확인될 때만 `confirmed` | `publish_force_open_to_mqtt`, `TargetAccessFsm.cpp` | signed command/physical relay **PENDING** |

## 오프라인·성능 저하·OEM 복구

모든 아래 값은 **문서 계약 목표이며 구현·Samsung/OEM 실측은 PENDING**이다. `timeout`은 한 시도에 적용하고, `bounded retry`가 끝나면 같은 요청을 무한 반복하지 않고 `escalation`으로 전환한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout / bounded retry / escalation contract |
|---|---|---|---|---|---|---|
| 사용자 → 지원팀 | Wi-Fi/모바일 네트워크가 끊겼거나 backend health가 `offline` | 네트워크 복구 확인, 앱 상태 캡처, redacted bundle 제출 | 10초 내 health/pre-arm 결과 또는 `offline`과 마지막 확인 시각; 문 열림 성공 문구 금지 | Flutter network state, `POST /api/v1/door/prearm`, #51/#52 | offline fault test + event ID **PENDING** | 요청 timeout 10초; 5초·30초 backoff로 최대 2회 재시도; 이후 `offline` 고정, 출입이 필요하면 지원팀/현장 안전 담당으로 즉시 escalation; local authorization은 **미구현/미확인** |
| 사용자 | Bluetooth가 꺼졌거나 필수 권한을 거부함 | 설정에서 Bluetooth/권한을 켠 뒤 앱에 복귀 | 권한별 `Blocked`와 설정 링크·다음 행동이 보임 | `BleWakeRegistrar.kt`, Flutter permission UI, #51 | permission transition test **PENDING** | 권한 요청은 OS 응답까지 30초; 설정 복귀 후 자동 재시도 1회만; 30초 내 상태가 바뀌지 않거나 두 번째 시도도 실패하면 지원팀 escalation; 앱 삭제·자격 재등록 금지 |
| 사용자 | 화면 꺼짐·배터리 최적화·프로세스 종료 가능 OEM | OEM background/auto-start/notification 설정 확인 후 앱 재진입 | 30초 내 `Ready/Degraded/Blocked`와 reason; background 성공을 추정하지 않음 | `BleWakeRegistrar.kt`, `BleWakeBootReceiver.kt`, Flutter service, #51 | Samsung/One UI screen-off/reboot/kill matrix **PENDING** | foreground 복귀 health check 30초; 앱 재진입 1회와 OEM 설정 재확인 1회만; 두 번 후에도 state/event가 없으면 지원팀에 OEM/build 정보로 escalation; Samsung acceptance **PENDING** |
| 사용자 → 지원팀 | 요청 결과가 `unknown`이거나 duplicate callback이 보임 | 현장 안전 확인, session/boot/event ID 캡처 | 15초 내 terminal state 또는 `unknown`; duplicate는 한 번만 기록되고 relay 성공으로 승격되지 않음 | `GattSessionEngine.kt`, `observability/`, #51/#52 | late/duplicate/timeout mutation + physical event **PENDING** | terminal event 대기 15초; 동일 idempotency/session으로 1회만 재시도; 이후 manual force-open 반복 금지, 지원팀/incident owner에 즉시 escalation; physical confirmation **PENDING** |

## 업데이트·rollback / Update and rollback

사용자에게 표시되는 업데이트 성공은 앱 설치 완료 또는 Target 재부팅 후 health confirmation까지 포함해야 한다. 다운로드, MQTT PUBACK, 진행률만으로 성공을 선언하지 않는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 사용자 | 공식 signed artifact와 저장 공간 | 앱 업데이트 시작 | hash/certificate/installer result와 기존 APK 보존 여부가 보임 | `gatekeeper_app/android`, #51/#23 | signed APK install/fallback **PENDING** |
| 사용자/Target | Target safe state, dual slot, signed manifest | Target OTA 승인 | install→reboot→health 확인 또는 자동 rollback과 reason | `src/OtaManager.cpp`, `ota/`, #50/#23 | power-loss/boot/rollback physical **PENDING** |
| 사용자 | update 실패 또는 health timeout | 앱/Target이 제공하는 rollback 선택 | 이전 정상 버전과 자격이 보존되고 상태가 `rolled_back`로 기록 | OTA updater contract | exact artifact digest + event **PENDING** |

## 분실 전화·교체·권한 회수

전화 분실 시 즉시 관리자/지원팀에 연락해 자격을 회수한다. 전화번호, 원본 MAC, 토큰, private key를 일반 채널에 보내지 않는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 사용자 | 분실 또는 교체 사실 확인 | 지원팀에 계정 식별자와 시각을 redacted 방식으로 신고 | 접수 ID와 회수 진행 상태 | #49 ACL API, credential service | revoke audit + device binding **PENDING** |
| 관리자 | 인증·tenant scope·회수 사유 | 기존 credential revoke, 새 기기 승인 | 이전 기기는 `revoked`; 새 기기는 별도 승인 대기 | `backend/app/acl_management.py`, #49 | concurrency/replay test **PENDING** |
| 사용자 | 회수 완료 또는 새 기기 승인 | 이전 기기에서 출입 시도 | `revoked`/`403` reason; 문 열림 없음 | Target ACL/GATT verifier | target event + denied proof **PENDING** |

## 접근성 / Accessibility

한국어 기본, English 전환을 제공하고 모든 상태·오류 이유를 텍스트로 읽을 수 있어야 한다. TalkBack 포커스 순서, 버튼 이름/역할, 색상만으로 의미 전달 금지, 200% text scaling, 작은 화면·가로 화면을 확인한다. 이 항목의 구현·Samsung 실기기 acceptance는 #51에 종속되어 **PENDING**이다.
## 지원 요청에 첨부할 것

지원·사고 핸드북의 redacted bundle 절차에 따라 시각, 상태, reason, app/Target/backend 버전, session/boot/event ID, artifact digest를 보낸다. 토큰·비밀번호·private key·raw tenant/unit/device/MAC는 삭제한다.
