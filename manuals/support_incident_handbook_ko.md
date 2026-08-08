# 지원·사고 대응 핸드북 / Support and incident handbook

문서 버전: **0.1.0-baseline** · 기준 커밋: `b246aff9698ccbcbcd864f99aab63654cce2cc78`<br>
대상: 1차 지원, 운영자, 사고 지휘자 (support/operator/incident commander) · 상태: **운영 SLO·연락망·물리 인수 pending**

## 증거와 안전

사고 중에는 문을 반복 개방하거나 TLS 검증·권한 검사를 끄지 않는다. 사람의 안전을 먼저 확보하고, 물리적 emergency procedure가 조직 규정에 있으면 그 절차를 우선한다. 모든 ticket은 opaque identity와 session/boot/event ID만 사용하며 secret·raw MAC·tenant/unit을 첨부하지 않는다.

## 1차 triage

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 1차 지원 | 사용자 동의, ticket ID | 시각·화면 상태·reason·재현 1회 | severity, owner, next action, redaction 안내 | support process | ticket + redacted bundle **PENDING** |
| 운영자 | incident authority | backend/Target/app health 분리 확인 | `online/offline/degraded/unknown`과 correlation ID | #52 observability | event stream + digest **PENDING** |
| 사고 지휘자 | 영향 범위와 안전 상태 확인 | declare/contain/escalate | timeline, decision log, rollback/force-open approval | #49/#50/#52 | immutable audit **PENDING** |

## 증상별 대응

| Symptom | Actor | Preconditions | Input/action | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|---|
| 앱이 Target을 못 찾음 | 사용자→지원 | Bluetooth/권한/OEM 상태 확인 | 한 번 재시도, settings 안내 | `Blocked/Degraded` reason과 다음 행동 | `ble_scanner.dart`, #51 | Samsung/OEM matrix **PENDING** |
| GATT timeout/disconnect | 지원/운영 | 같은 session에서 재시도 가능 | reason code 캡처, 중복 요청 금지 | `GATT_TIMEOUT`/`GATT_DISCONNECTED`, door effect 없음 | `GattSessionEngine.kt` | unit/host tests; physical **PENDING** |
| backend/MQTT offline | 운영자 | fail-closed 상태 확인 | DNS/TLS/DB/broker를 분리 점검 | bounded retry/alert와 owner가 보임 | `main.py`, `MqttManager.cpp`, #52 | fault/alert/soak **PENDING** |
| force-open 요청 | 관리자+승인자 | 재인증, reason, dual control, safe scene | 승인된 단 1회 요청 | request/approved/effect-confirmed를 분리 | #49/#50 | signed command + relay event **PENDING** |
| update 실패 | release owner | 기존 APK/last-known-good slot 보존 | hash/cert/installer/health reason 확인, rollback | 이전 정상 상태와 rollback event | `OtaManager.cpp`, OTA scripts | bad artifact + power-loss physical **PENDING** |
| 전화 분실 | 사용자/관리자 | 본인 확인과 ticket | credential revoke, 새 기기 재등록 | 이전 기기 `revoked`, audit ID | `acl_management.py`, #49 | revoke concurrency/replay **PENDING** |
| 데이터 노출 의심 | 사고 지휘자/privacy owner | legal/privacy contact | access revoke, export 보류, scope 보존 | containment와 notice decision | #52 | redacted incident record **PENDING** |

## 상태·오류 기록 규칙

`pending`, `active`, `armed`, `opening`, `confirmed`, `failed`, `unknown`, `revoked`, `offline`, `rolled_back`를 혼용하지 않는다. `confirmed`는 실제 target event/physical effect가 확인된 경우만 사용한다. `unknown`은 성공으로 재분류하지 않고 operator investigation으로 보낸다. 시간 제한, retry 횟수, escalation 대상은 운영 SLO가 확정되기 전까지 문서에서 임의로 약속하지 않는다.

## Redacted support bundle

포함: ticket ID, time zone, app/firmware/backend version, opaque target/session/boot/event ID, reason code, state transition, network class(offline인지 여부), artifact SHA-256, 재현 단계와 마지막 observable output.<br>
삭제: credentials, tokens, private keys, proofs, nonces, raw tenant/unit/name/MAC, 주소와 원본 URL query. 생성·다운로드·열람·만료를 audit한다. redaction tool/test가 없으므로 현재 기준선의 export 성공은 **PENDING**이다.

## 사고 종료와 반복 루프

1. 사람·문·Target을 안전 상태로 만들고 containment를 기록한다.
2. 영향을 받은 app/backend/Target artifact와 exact commit/digest를 고정한다.
3. #49 auth/RBAC/force-open, #50 TLS/signed command/OTA, #51 OEM/GATT/updater, #52 event/privacy/backup/SLO 중 해당 owner가 원인과 regression을 등록한다.
4. 독립 reviewer가 로그·코드·테스트·물리 evidence를 분리 검토한다.
5. 동일 여정을 매뉴얼만 읽는 actor에게 다시 수행시켜 `observable output`과 실제 state/event/physical effect가 일치하는지 확인한다.
6. 갭이 남으면 incident를 닫지 않고 다음 반복 루프로 넘긴다. 이 기준선에서는 P0/P1 및 physical walkthrough가 남아 있으므로 issue #53 완료를 선언하지 않는다.
