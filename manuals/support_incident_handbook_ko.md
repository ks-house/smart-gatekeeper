# 지원·사고 대응 핸드북 / Support and incident handbook

문서 버전: **0.3.0-rc.1** · 제품 기준: `e42d1f417a555b17d7476522aa48f7e4d72306b7`<br>
대상: 1차 지원·on-call·사고 지휘자 · 상태: **#52 software reason·privacy·readiness 반영; NAS 연락망·SLO·물리 인수 pending**

## 1. 절대 원칙

사람과 문 안전을 먼저 확보한다. TLS/서명/RBAC를 끄거나, relay를 반복 개방하거나, unknown effect를 success로 바꾸지 않는다. 조직의 물리 비상 절차가 있으면 그것을 우선한다. ticket에는 redacted identifier만 사용한다.

Severity/연락처/근무시간/SLA는 #52 운영 설정에서 승인해야 한다. 아래 시간은 코드 source 값 또는 **검증 목표**이며 운영 보장이 아니다.

## 2. 5분 triage

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 1차 지원 | 사용자 동의, ticket ID | 언제/어디까지/화면 state/reason/마지막 effect 질문 | app·backend·Target·physical 중 failure domain과 owner | support process #52 | redacted ticket **OPS PENDING** | acknowledge 15분 목표 | 질문 1회 | safety issue면 즉시 incident commander/현장 owner |
| operator | NAS read-only access, clock/timezone | `/live`→`/ready`→인증된 admin metrics 순서로 API/DB/broker 분리 | process liveness, readiness check map, low-cardinality breaker/queue result; Target·physical은 별도 | backend ops runtime | response/metrics/alert bundle **OPS PENDING** | broker probe 1초 source 값, health 10초 목표 | 5초→30초 2회 | failed component owner + incident commander |
| incident commander | severity와 safety 상태 | declare/contain/owner 지정 | `INCIDENT_OPEN`, timeline, stop/rollback/force-open authority | incident workflow #52 | decision log **OPS PENDING** | 15분 목표 | auto 0회 | security/privacy/release/physical owners |

## 3. 증상별 runbook

| Symptom / reason | Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|---|
| first-run `BACKGROUND_CONSENT_UNAVAILABLE` | 사용자/support | recovery shell 접근 | 앱 재실행, storage/OS 확인 | consent 미확정, system request 없음, recovery 유지 | consent store/logger | host consent tests | 30초 목표 | 앱 재실행 1회 | mobile owner; app data 삭제 금지 |
| `Blocked/Degraded`, Target 미발견 | 사용자/support | Bluetooth/권한/OEM 확인 가능 | 누락 항목 수정 후 foreground 복귀 | exact missing reason 또는 Ready | background/native wake | Samsung evidence **PENDING** | 30초 | app 복귀 1회, settings 재확인 1회 | mobile/OEM owner에 build·reason |
| `GATT_TIMEOUT/GATT_DISCONNECTED` | support | recent Target/credential과 safe scene | reason·session 캡처 | terminal failed, door effect 없음 또는 unknown | GATT engine/ledger | host mutations + physical pending | 15초 목표 | retryable reason이면 same session 1회 | physical + mobile owner |
| `PROOF_UNCERTAIN` / `duplicate_uncertain` | support/operator | physical scene 확인 | boot/session/event/nonce correlation | unknown 유지, duplicate effect 0 | GATT/Target replay ledgers | host replay + physical pending | 15초 | 자동 0회 | security/firmware/physical owner |
| backend/DB 503 | operator | admin HTTP detail 있음 | DB health, transaction/audit 유무 확인 | exact 503; mock success 없음 | backend/admin DB | backend fault tests + deployed pending | 10초 목표 | read-only 2회; mutation 0회 until commit known | DB/backend owner |
| `/live` 200, `/ready` 503 | deploy operator | exact NAS build와 response body | readiness의 DB/schema/MQTT/secret/mTLS/ACL/legacy/build check 분리 | `not_ready`; traffic admission 중지, process success만 보존 | `_readiness_snapshot` | response capture **OPS PENDING** | broker probe 1초 source 값 | read-only 2회 | false check owner; `/live`로 healthcheck 우회 금지 |
| MQTT breaker/backpressure | operator | authenticated metrics와 exact build | queue depth, deadline, breaker state 확인 | bounded failure; 최대 16 in-flight, 3 failures 후 open, half-open probe 1개 | `PersistentMqttPublisher`, `OpsMetrics` | host bounded/fanout tests + NAS fault **OPS PENDING** | PUBACK/probe 1초 class | read-only metrics 1회, effect retry 0회 | broker/network owner; connection fanout·plaintext fallback 금지 |
| MQTTS/TLS offline | operator | DNS/time/CA/hostname 분리 가능 | 순서대로 점검 | verified online 또는 `TLS_VERIFY_FAILED/TARGET_OFFLINE` | MqttManager/backend command plane | host negative + live pending | socket 15초 | 5초→30초 2회 | broker/PKI owner; insecure 금지 |
| force-open 404/503 | commander | approval ID/audit 있음 | proposal/reconciliation state 조회 | expired/unavailable 또는 `RECONCILIATION_REQUIRED`; effect success 없음 | admin force-open state | host crash/replay tests | proposal 300초 | approval/publish 0회 | backend/DB/broker + physical owner |
| force-open `PUBLISHED` but no effect | commander/operator | Target와 relay 관찰 가능 | boot/session/event와 relay 확인 | `EFFECT_UNKNOWN` until verified physical event | signed command/Target FSM | correlation **PHYSICAL PENDING** | 120초 목표 | publish/effect 0회 | 현장 safety + firmware owner |
| app update failed | 사용자/release owner | old APK 보존 | metadata/schema/hash/cert/package/build/commit reason 확인 | `failed/pending`, old APK·credential 유지 | mobile updater/protected producer | host adversarial + install pending | 60초 목표 | primary/fallback 각 1회, installer 0회 | mobile/release owner |
| Target OTA failed | release owner | last-known-good slot | boot/slot/digest/health 확인 | rollback/recovery 또는 `OTA_HEALTH_TIMEOUT` | OtaManager/bootloader | OTA-G1..G4 pending | 120초 source deadline | install 0회, rollback 1회 | firmware/release/physical owner |
| 휴대폰 분실 | support/security | identity verified | old credential revoke ticket | backend revoked, Target ACK pending/confirmed | ACL lifecycle | audit/denial physical pending | 15초/60초 목표 | same request 1회 | credential/Target owner |
| 개인정보 노출 의심 | commander/privacy owner | legal/privacy contact | export hold, access revoke, scope preservation | `CONTAINED` 또는 unverified, legal decision | #52 incident/privacy | record pending | 15분 목표 | containment 1회 | privacy/legal/security |
| support export 400/403/503 | support/privacy owner | mTLS session, tenant scope, consent ticket | reference 형식·purpose·expiry·revocation·tenant와 DB health 확인 | 위조/만료/철회/cross-tenant는 403과 export 0; DB failure는 fixed 503 | support-export API, migration 007 | response + audit digest **OPS PENDING** | HTTP 15초 목표 | corrected consent로 1회 | raw log/DB dump 첨부 금지; privacy/DB owner |
| privacy deletion 409/503 | tenant admin/privacy owner | approved retention schedule, request hash와 job state | 동일 actor/payload/key인지 확인 | mismatch 409 또는 one durable `PENDING→COMPLETED`; 삭제 성공 추정 금지 | privacy delete API | job/audit **OPS PENDING** | HTTP 15초 목표 | same request/key 1회 | 새 key로 우회하지 말고 data/privacy owner |

## 4. Force-open 상세

1. `SECURITY_OPERATOR`가 safe scene, tenant scope, 8–256자 reason과 idempotency key로 proposal을 만든다.
2. 202 `approval_required`와 approval ID, `FORCE_OPEN_PROPOSED` audit만 확인한다. 아직 publish/effect는 없다.
3. 300초 안에 별도 `SECURITY_APPROVER`가 새 idempotency key로 승인한다.
4. Backend는 broker call 전에 `RECONCILIATION_REQUIRED`를 commit한다. 오류면 자동 재시도하지 않는다.
5. Broker ACK 후 `PUBLISHED`와 audit는 publication만 의미한다.
6. current Target boot ID에 묶인 signed event와 relay trace를 확인한 경우만 `confirmed`다. 120초 검증 목표를 넘기면 `EFFECT_UNKNOWN`으로 incident를 유지한다.

## 5. Evidence bundle

포함: ticket ID, timezone 포함 시각, exact commit/app/firmware/backend version, artifact SHA-256, opaque target/session/boot/event/approval ID, HTTP status/detail, reason/state transition, retry 횟수, 마지막 observable output, owner와 다음 행동.

제거: credentials, password/token/cookie/CSRF/private key, proof/signature/nonce, raw tenant/unit/name/device/MAC, 주소·원본 URL/query, Wi-Fi 정보, 무제한 stack. 앱 sink, backend filter와 consent-bound export의 software test는 구현됐다. NAS ticket 접근 통제, 실제 consent capture, 보관·삭제와 privacy/legal 승인은 `OPS PENDING`이다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| support agent | current tenant/purpose consent, mTLS ticket scope | 앱 preview 후 bounded support-export 검토 | 금지 필드 0, opaque refs, canonical digest, expiry/owner | app logger + support-export API | logger/export tests + ticket audit pending | 30초 목표 | bundle/API 생성 1회 | 의심 필드면 전송 중지, privacy owner |
| on-call | read-only evidence access | causal IDs로 상관 | app/backend/Target/physical evidence를 별도 section으로 유지 | event schema | digest + access audit pending | 15분 목표 | query 1회 | observability owner |
| reviewer | incident 종료 전 독립성 | exact artifact와 evidence 검증 | 사실/추정/pending 구분, missing evidence 목록 | incident process | signed review pending | closure window | review 1회 | missing evidence면 `RECOVERY_UNVERIFIED` 유지 |

## 6. 종료·postmortem·반복

incident 종료 조건은 containment, root cause, regression, 복구/rollback, 영향 범위, privacy decision, exact artifact와 독립 review가 모두 있는 것이다. software CI green만으로 physical incident를 닫지 않는다.

1. 사람·문·Target을 안전 상태로 둔다.
2. affected artifact와 configuration provenance를 고정한다.
3. #49 auth/RBAC, #50 TLS/command/OTA, #51 mobile/OEM/updater, #52 ops/privacy/backup, #54 physical owner를 지정한다.
4. 결함을 code/test 또는 precise blocker로 반영한다.
5. [Hardwareless walkthrough](hardwareless_walkthrough_ko.md)를 반복하고 해당 physical checklist는 사용자가 실행한다.
6. observable output과 실제 state/effect가 일치하지 않거나 증거가 없으면 `RECOVERY_UNVERIFIED`로 유지한다.
