# 지원·사고 대응 핸드북 / Support and incident handbook

문서 버전: **0.1.1-remediation** · 통합 기준: `b2df34977fe866e129eae373e7056f0f9b3ddc6f`<br>
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

모든 아래 값은 **운영 계약 목표이며 구현·운영 증거는 PENDING**이다. 각 오류는 timeout, bounded retry, escalation을 모두 가지며, retry가 끝난 뒤 성공으로 추정하지 않는다.

| Symptom | Actor | Preconditions | Input/action | Observable output | Code/API owner | Evidence artifact | Timeout / bounded retry / escalation contract |
|---|---|---|---|---|---|---|---|
| 앱이 Target을 못 찾음 | 사용자→지원 | Bluetooth/권한/OEM 상태 확인 | 설정 확인 후 재시도 1회 | 30초 내 `Blocked/Degraded` reason과 다음 행동 | `ble_scanner.dart`, `BleWakeRegistrar.kt`, #51 | Samsung/OEM matrix **PENDING** | target discovery 30초; foreground/OEM 재시도 최대 1회; 이후 지원팀에 OEM/build/session 정보 escalation |
| GATT timeout/disconnect | 지원/운영 | 같은 session에서 안전한 재시도 가능 | reason code 캡처, 중복 요청 금지 | 15초 내 `GATT_TIMEOUT`/`GATT_DISCONNECTED`, door effect 없음 | `GattSessionEngine.kt`, #51 | late/duplicate/timeout mutation + physical **PENDING** | operation timeout 15초; 동일 session/idempotency로 retry 최대 1회; 다시 실패하면 incident owner와 physical operator escalation |
| backend/MQTT offline | 운영자 | fail-closed 상태 확인 | DNS/TLS/DB/broker를 분리 점검 | 10초 내 health 결과 또는 `offline`, alert와 owner가 보임 | `main.py`, `MqttManager.cpp`, #52 | fault/alert/soak **PENDING** | health/request timeout 10초; 5초·30초 backoff 최대 2회; 이후 circuit/`offline` 유지와 on-call escalation, TLS 검증 해제 금지 |
| force-open 요청 | 관리자+승인자 | 재인증, reason, dual control, safe scene | 승인된 단 1회 요청 | 2분 내 `requested/approved/effect-confirmed` 중 하나; effect 미확인은 `unknown` | #49/#50, `POST /api/v1/door/open` | signed command + relay event **PENDING** | approval/effect timeout 120초; 자동 retry 금지(재인증·새 승인 필요); timeout/unknown이면 incident commander와 현장 안전 담당 escalation |
| update 실패 | release owner | 기존 APK/last-known-good slot 보존 | hash/cert/installer/health reason 확인, rollback | 각 단계 reason과 이전 정상 상태/rollback event | `OtaManager.cpp`, `scripts/ota_contract_gate.py` | bad artifact + power-loss physical **PENDING** | download/install 단계 timeout 60초; artifact fetch 최대 2회, health timeout 후 retry 금지·rollback 1회; 실패 시 release owner/on-call escalation |
| 전화 분실 | 사용자/관리자 | 본인 확인과 ticket | credential revoke, 새 기기 재등록 | 15초 내 접수/회수 상태와 이전 기기 `revoked` 또는 `pending` | `acl_management.py`, #49 | revoke concurrency/replay **PENDING** | revoke API timeout 15초; 동일 request ID로 retry 최대 1회; 30초 내 회수 확인이 없으면 security owner escalation, 출입 허용 추정 금지 |
| 데이터 노출 의심 | 사고 지휘자/privacy owner | legal/privacy contact | access revoke, export 보류, scope 보존 | 15분 내 containment 상태, affected scope와 notice decision | #52 privacy/incident process | redacted incident record **PENDING** | containment acknowledgement 15분; 자동 재시도 금지, 승인된 containment action 1회 후 privacy/security escalation; 원본 secret export 금지 |

## 상태·오류 기록 규칙

`pending`, `active`, `armed`, `opening`, `confirmed`, `failed`, `unknown`, `revoked`, `offline`, `rolled_back`를 혼용하지 않는다. `confirmed`는 실제 target event/physical effect가 확인된 경우만 사용한다. `unknown`은 성공으로 재분류하지 않고 operator investigation으로 보낸다. 위 timeout·retry·escalation 값은 이 문서가 요구하는 **검증 대상 계약**이다. 실제 구현과 운영 SLO가 일치한다는 증거가 생기기 전까지 사용자는 이를 제품 보장으로 해석하지 않으며, `PENDING` 상태를 유지한다.

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
