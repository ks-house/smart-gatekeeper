# 관리자 매뉴얼 / Administrator manual

문서 버전: **0.1.2-contract-loop** · 통합 기준: `c654a18f0fa278e4530229bb881fe88286d25c2e`<br>
대상: 관리자/건물 운영자 (administrator/operator) · 상태: **#49 host/software 반영; 배포·#50–#52·운영·물리 증거 대기**

## 운영 원칙

통합 기준에는 PR #57의 deny-by-default 관리자 route, proxy-verified mTLS fingerprint 세션, role/tenant scope, CSRF·재인증·idempotency, DB/audit fail-closed 응답, durable two-person force-open publication 상태가 구현되어 있다. 이는 `backend/app/admin_security.py`, `backend/app/main.py`, migrations 003–005와 `backend/tests/test_admin_security.py`가 제공하는 **host/software 증거**이며, 실제 reverse proxy/mTLS 배포, 운영 연락망·SLO, Target signed command, relay effect와 production authorization은 여전히 `PENDING`이다.

화면의 일반 경고 문구보다 아래 표의 HTTP status/detail, approval state와 immutable audit action을 우선 기록한다. 표의 `15초/120초` 같은 응답·관찰 시간은 운영 검증용 **문서 계약 목표**이며 source가 구현한 300초 proposal expiry나 세션 `expires_at`과 구분한다. timeout 후에는 성공을 추정하지 않고 [지원·사고 대응 핸드북](support_incident_handbook_ko.md)의 redacted bundle로 넘긴다.

## 용어와 역할 / Roles and terminology

| 한국어 | English | 책임 |
|---|---|---|
| 시스템 소유자 | system owner | tenant/door 정책과 운영 승인 |
| 관리자 | administrator | 사용자·기기·권한 lifecycle, 감사 조회 |
| 설치자 | installer | 배선·프로비저닝·시운전; 운영 권한과 분리 |
| 지원 대응자 | support responder | 진단·사고 triage; force-open은 별도 승인 |
| 회수 | revoke | 자격을 즉시 무효화하고 대체 ACL을 배포 |
| 강제 개방 | force-open | 위험 동작; 역할·재인증·사유·이중 승인·감사 필요 |

## 관리자 인증·권한 실패 계약

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Reason code / state | Timeout | Bounded retry | Escalation / owner / evidence |
|---|---|---|---|---|---|---|---|---|---|
| 관리자 | mTLS reverse proxy가 client cert를 검증하고 fingerprint가 `ADMIN_MTLS_IDENTITIES_JSON`에 있으며 proxy IP가 allow-list에 있음 | `POST /api/v1/admin/sessions` | 200이면 Secure/HttpOnly/SameSite session과 `expires_at`, CSRF token; 그 외에는 세션 없음 | `admin_security.py`, `POST /api/v1/admin/sessions` | anonymous/forged/rate-limit/stale-session tests **HOST/SOFTWARE PRESENT**; deployed proxy walkthrough **PENDING** | HTTP 401 `verified mTLS client certificate required` / `untrusted client-certificate proxy` / `unrecognized administrator certificate`; 429 `administrator authentication temporarily rate limited`; 503 `admin authentication is not configured` 또는 invalid identity config | 로그인 응답 목표 15초; session TTL 기본 900초는 응답의 `expires_at`을 기준으로 함 | 401은 cert/proxy 확인 뒤 1회; 429는 기본 60초 rate window 중 0회; 503 자동 retry 0회 | security owner + backend deploy owner에게 시각, HTTP status/detail, proxy peer와 fingerprint의 redacted hash만 전달; cert/private key 금지 |
| 관리자 | 유효 session, `X-Tenant-ID`, unsafe 요청의 CSRF·현재 mTLS·`X-Admin-Reauthenticate: mtls`, 128자 이하 `Idempotency-Key` | tenant/config/control mutation 1회 | 권한·scope·CSRF·재인증을 모두 통과해야 handler 진입; 거부는 side effect 없음 | deny-by-default middleware, `AdminSecurity.principal()` | anonymous, cross-tenant, missing-CSRF, stale/revoked, replay negative tests **HOST/SOFTWARE PRESENT** | 401 `administrator session required` / `administrator session expired or revoked`; 403 `CSRF validation failed` / `administrator role is not authorized` / `tenant scope violation` / re-auth actor mismatch; 400 `bounded Idempotency-Key required` | API 응답 목표 15초; 구현 transport timeout 증거 **PENDING** | 새 session/정확한 scope 확인 뒤 원 요청 최대 1회; 같은 mutation을 새 idempotency key로 반복 금지 | tenant security owner와 backend on-call에 actor subject, tenant scope, endpoint, HTTP detail, idempotency **hash**, session expiry를 전달; 원본 cookie/token/key 금지 |

## Tenant·device·door lifecycle

1. tenant를 생성할 때 원본 주민 정보와 device/door identity를 분리하고 필요한 최소 정보만 저장한다.
2. device/door는 제조 identity, target binding, protocol range, 상태(`provisioned`, `active`, `quarantined`, `decommissioned`)를 확인한다.
3. 사용자는 `pending → active → revoked` 흐름을 따른다. DB 오류/timeout은 `unknown` 또는 실패로 보이며 mock `approved`가 아니다.
4. tenant disable은 영향을 받는 모든 credential과 Target ACL replacement job을 원자적으로 처리해야 한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Reason code / state | Timeout | Bounded retry | Escalation / owner / evidence |
|---|---|---|---|---|---|---|---|---|---|
| `TENANT_ADMIN` | 유효 session/CSRF/재인증, `legacy:<tenant_id>` scope, 대상 존재, 요청별 idempotency key | `POST /api/v1/admin/tenants/{tenant_id}/approve` 또는 `/reject` | DB transaction과 `admin_audit`가 함께 commit된 뒤에만 200 `approved`/`rejected`; list DB 오류도 mock row 없이 503 | `main.py` tenant routes, migration 003 | source + backend/AdminSecurity negative tests **HOST/SOFTWARE PRESENT**; deployed DB fault/operator walkthrough **PENDING** | 성공 `approved` / `rejected`; 503 `tenant data unavailable` / `tenant approval unavailable` / `tenant rejection unavailable`; auth/scope reason은 위 표 | 응답 목표 15초; 구현 SLO **PENDING** | timeout/503이면 상태·audit 확인 전 retry 0회; backend owner가 미commit을 확인한 경우에만 **같은 idempotency key**로 1회 | tenant security owner + DB on-call에게 tenant opaque scope, endpoint, actor, idempotency hash, HTTP detail와 audit 유무를 전달 |
| 관리자 | revoke 사유·current ACL version, ACL management prerequisites | credential 회수와 replacement ACL 요청 | backend revoke/tenant disable state와 monotonic replacement job; Target ACK 전에는 현장 거부 완료를 선언하지 않음 | `acl_management.py`, `acl_api.py`, `backend_acl_management.md` | concurrency/replay host tests present; Target ACK/physical denial **PENDING** | backend `revoked`/`TENANT_DISABLED`; Target ACK 없음은 `TARGET_ACK_PENDING` 문서 reason | backend 응답 목표 15초, Target ACK 관찰 목표 60초; 운영 SLO **PENDING** | backend request 같은 idempotency로 최대 1회; Target ACK 없는 상태에서 반복 revoke/force-open 0회 | credential owner + Target/incident owner에게 ACL version, job/audit ID, ACK state/event를 전달 |
| 관리자 | device binding, maintenance window, rollback/decommission plan | device quarantine/decommission | 신규 출입·명령 거부와 audit가 필요; current #49 admin routes만으로 Target 적용 성공을 추정하지 않음 | #49/#50 Target ACL | backend/source trace present; Target denial/operator evidence **PENDING** | `QUARANTINE_PENDING` / `DECOMMISSION_PENDING` 문서 reason until Target denial event | change window 또는 Target event 60초 목표; 구현 증거 **PENDING** | 자동 retry 0회; 상태 확인 뒤 승인된 작업 1회만 | system owner + Target owner + physical operator에게 binding, artifact, ACL/audit/Target event를 전달 |

## Force-open 통제

현재 기준선은 관리자 인증·사유·별도 role·재인증·이중 승인·durable audit/publication 상태를 묶지만, MQTT `published`와 Target signed-command/relay effect를 묶지는 않는다. 따라서 아래 절차는 #49 host/software 경로를 정확히 사용하면서 #50/#52/physical evidence를 끝까지 분리한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Reason code / state | Timeout | Bounded retry | Escalation / owner / evidence |
|---|---|---|---|---|---|---|---|---|---|
| `SECURITY_OPERATOR` 요청자 | 유효 session/CSRF/current mTLS, tenant scope, 안전 현장, 8–256자 사고 사유, idempotency key | `POST /api/v1/admin/control/force-open` 1회 | 202 `approval_required` + 48자 `approval_id`; MQTT publish 없음; `FORCE_OPEN_PROPOSED` audit | `main.py:request_force_open`, migrations 003–005 | proposal/no-publish and missing-CSRF tests **HOST/SOFTWARE PRESENT** | `approval_required`; 400 bounded idempotency; 401/403 auth/scope; 503 `force-open proposal unavailable` | HTTP 목표 15초; proposal expiry **300초(source-enforced)** | 15초 timeout이면 같은 idempotency key로 proposal 재전송 최대 1회; 새 key·반복 탭 금지 | incident commander + backend control owner에게 approval ID, actor/scope, reason의 redacted 분류, idempotency hash, `FORCE_OPEN_PROPOSED` audit를 전달 |
| 별도 `SECURITY_APPROVER` | 같은 tenant scope, 요청자와 다른 subject, 유효 session/CSRF/current mTLS, proposal `PENDING`/미만료, 새 idempotency key | `POST /api/v1/admin/control/force-open/{approval_id}/approve` 1회 | broker 호출 전 `RECONCILIATION_REQUIRED`+audit를 commit; broker ACK와 final audit commit 후에만 200 `published`; relay 성공 문구 금지 | `main.py:approve_force_open`, migrations 004–005 | self/expiry/replay/cross-tenant/duplicate/precommit/post-publish/concurrency tests **HOST/SOFTWARE PRESENT** | 403 `force-open requires a distinct approver`/tenant reason; 404 `force-open proposal is unavailable`; 503 `force-open publication unavailable or reconciliation required`; durable `RECONCILIATION_REQUIRED` | 승인 HTTP 목표 15초; proposal 전체 expiry 300초 | 승인/publication 자동 retry **0회**. 404면 새 proposal 필요; 503/`RECONCILIATION_REQUIRED`는 reconciliation 전 재승인 금지 | incident commander + backend/DB/broker owners에게 approval row state, immutable audit actions, broker attempt와 DB transaction 결과를 전달 |
| Target/operator | backend `published` 또는 `RECONCILIATION_REQUIRED`, 현장 안전 담당 배치 | approval ID에 대응하는 Target event/relay 측정 확인 | Target-bound verified event와 물리 effect가 있을 때만 `confirmed`; 없으면 `EFFECT_UNKNOWN`, `published`를 승격하지 않음 | #50 `TargetAccessFsm.cpp`, `MqttManager.cpp`, observability #52 | backend broker ACK host evidence only; signed Target command/relay/operator correlation **PHYSICAL PENDING** | `EFFECT_UNKNOWN`, Target reason/event, 또는 `confirmed`; `RECONCILIATION_REQUIRED`는 성공 아님 | effect 관찰 목표 120초; 구현 SLO/physical evidence **PENDING** | 자동 publish/approve/relay retry **0회**; 새 proposal도 incident commander 승인 전 금지 | incident commander + 현장 safety owner + #50/#52 owners에게 approval ID, broker result, Target session/boot/event ID, meter/relay evidence를 전달 |

## Broker·TLS·secret rotation

plain broker, shared credentials, hostname 미검증, `setInsecure()` fallback은 production 절차로 승인하지 않는다. rotation은 old/new overlap window, target binding, rollback owner, expiry와 독립 검증을 포함해야 한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 보안 관리자 | 새 인증서/credential이 승인·감사됨 | staged rotation | old/new 상태와 만료 시각이 보임; rogue CA는 거부 | `src/MqttManager.cpp`, #50 | hostname/rogue-CA/crossover tests **PENDING** |
| 운영자 | canary target과 rollback credential 보존 | canary connect/publish | online event는 verified TLS와 target ID를 포함 | MQTT manager/observability | exact target event **PENDING** |

## 모니터링·장애·복구

`online/offline`, backend/API/DB/MQTT/DNS/certificate/storage 상태와 event lag를 별도로 본다. 화면 health가 healthy라고 하더라도 relay 또는 OTA physical health를 의미하지 않는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Reason code / state | Timeout | Bounded retry | Escalation / owner / evidence |
|---|---|---|---|---|---|---|---|---|---|
| 운영자 | alert routing, redacted logs, backend/DB/broker/Target health를 분리할 수 있음 | health 조회와 해당 실패 요청 1회, DNS/TLS/DB/broker 분리 점검 | API의 401/403/429/503 detail과 approval state를 그대로 기록; alert/owner/next action이 없으면 장애가 해소된 것으로 보지 않음 | #49 API errors, #52 observability | #49 fail-closed host tests present; alert fault matrix/24h soak **PENDING** | `ADMIN_AUTH_UNAVAILABLE`, `ADMIN_DB_UNAVAILABLE`, `BROKER_UNAVAILABLE`, `RECONCILIATION_REQUIRED`, `ALERT_NOT_OBSERVED` 문서 분류 + 원본 HTTP detail/state 병기 | health/API 목표 10초; alert acknowledgement 목표 15분; 운영 SLO **PENDING** | read-only health는 5초→30초 backoff 최대 2회; mutation/force-open retry 0회 | backend/DB/broker on-call과 incident commander에게 첫/마지막 시각, endpoint, HTTP detail, approval/audit/event ID, alert 유무를 전달; TLS 검증 완화 금지 |
| backup owner + 독립 restore reviewer | 암호화 backup artifact/digest, 격리 restore 환경, 승인된 key, schema/migration 버전 | 격리 restore drill 1회 | tenant/ACL/nonce/force-open state와 `admin_audit` immutability/count, RPO/RTO, artifact digest가 모두 검증될 때만 `RESTORE_VERIFIED` | #52, `backend/db`, migrations 002–005 | migration/immutable trigger software tests present; independent backup/restore report **PENDING** | `BACKUP_ARTIFACT_INVALID`, `RESTORE_TIMEOUT`, `RESTORE_INTEGRITY_UNKNOWN`, 또는 `RESTORE_VERIFIED` 문서 reason | 승인된 drill window 또는 60분 목표 중 먼저 도달; 실제 measured RPO/RTO **PENDING** | production restore 자동 retry 0회; 격리 환경에서 원인 확인 후 새 환경으로 최대 1회 | data/platform owner + security/privacy owner에게 digest, schema SHA, 시작/종료, row/count/integrity 결과, reviewer와 RPO/RTO를 전달; 원본 secret 금지 |
| 사고 지휘자 | 안전 상태, owner 지정, 위 timeout/retry 소진 또는 `RECONCILIATION_REQUIRED`/`EFFECT_UNKNOWN` | incident declare/contain/resolve | timeline, reason/state, evidence IDs, rollback/closure reviewer; PENDING evidence가 있으면 closure 금지 | support handbook/#52 | immutable audit where available; operator postmortem **PENDING** | `INCIDENT_OPEN`, `CONTAINED`, `RECOVERY_UNVERIFIED`, `CLOSED` | declare acknowledgement 목표 15분; closure deadline 대신 evidence gate 사용 | containment action 승인 1회; 자동 closure/retry 0회 | incident commander가 system/security/physical owner에게 redacted bundle을 배포하고 독립 reviewer가 evidence boundary 확인 |

## OTA canary·rollback·decommission

OTA는 signed manifest/digest/board/layout/anti-downgrade 검증 → inactive slot 설치 → reboot → health window → valid mark 또는 rollback 순서여야 한다. MQTT remote trigger 하나만 성공으로 기록하지 않는다. 기준선은 이 순서의 실기기 증거가 없다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| Release owner | signed artifact, N/N-1 compatibility, canary set | release candidate | canary state와 digest, stop/rollback decision visible | `ota/`, `scripts/ota_contract_gate.py` | host gate + target install **PENDING** |
| Operator | old slot bootable, health window | power/network interruption mutation | last-known-good 유지, automatic rollback, credential/ACL/NVS preservation | `src/OtaManager.cpp`, bootloader | power-loss physical evidence **PENDING** |
| Owner | data retention/credential revocation plan | decommission target/tenant | commands revoked, data export/deletion/audit complete | #49/#52 | signed decommission record **PENDING** |

## 접근성·권한 안전

관리자 UI/API에는 keyboard/TalkBack accessible labels, 200% text, focus order, contrast, ko/en terminology, dangerous-action confirmation과 audit link가 필요하다. #49의 API 권한 경계는 host/software로 존재하지만 현재 `admin.html`의 generic alert와 proposal-only UI는 위 reason/evidence 계약을 완전히 표시하지 않으므로 operator UI walkthrough는 `PENDING`이다. #51 accessibility/OEM acceptance 전에는 운영 승인하지 않는다.
