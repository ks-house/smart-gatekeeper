# 관리자 매뉴얼 / Administrator manual

문서 버전: **0.3.0-rc.1** · 제품 기준: `e42d1f417a555b17d7476522aa48f7e4d72306b7`<br>
대상: 보안 관리자·건물 운영자 · 상태: **#49/#50/#52 software 반영; NAS·운영·물리·production 증거 대기**

## 1. 운영 원칙과 역할

관리자 API의 성공은 database/audit 또는 broker publication 범위다. Target signed event와 물리 relay effect가 없으면 출입 성공이 아니다. `RECONCILIATION_REQUIRED`, `EFFECT_UNKNOWN`, Target ACK pending을 success로 바꾸지 않는다.

| 역할 | 허용 범위 | 금지 |
|---|---|---|
| `TENANT_ADMIN` | 자기 tenant의 승인·거부·credential lifecycle | 타 tenant, force-open 요청·승인 |
| `SECURITY_OPERATOR` | 사유가 있는 force-open proposal | 자기 승인, relay effect 추정 |
| `SECURITY_APPROVER` | 별도 subject가 만든 같은 tenant proposal 승인 | proposal 생성자와 동일인 승인 |
| system/release owner | 배포, TLS·key rotation, canary·rollback | 보안 통제 비활성화, 물리 Gate 대체 |
| installer/service | 배선·provisioning·현장 계측 | 관리자 session·production key 공유 |
| incident commander | containment, evidence, 종료 결정 | 자동 force-open 반복, 증거 없는 종료 |

## 2. Hardened 배포 전 Gate

현재 repository의 `security/target-production-policy.json`은 `production_enabled=false`다. 아래 조건과 [상용 운영 계약](../wiki/commercial_operations.md), 물리 Gate, risk-owner 승인이 모두 충족되기 전 true로 바꾸거나 production job을 승인하지 않는다. 사용자가 요청한 NAS 배포는 실기기 검증용 staging으로 취급하며 이 플래그나 production 승인을 자동으로 바꾸지 않는다.

### 개인 사용자 계정 관리

- 관리자 콘솔의 `정보 수정`에서 이름(최대 50자)과 동/호수(최대 20자)를 변경한다. 변경은 관리자 감사 이력에 남지만 이전 이름/동호수 원문은 감사 로그에 복제하지 않는다.
- `계정 삭제`는 먼저 해당 휴대폰 공개키 자격을 폐기하고 새 ACL을 Target에 발행한 뒤 사용자 개인정보 행을 삭제한다. 오류가 나오면 삭제 완료로 간주하지 않는다.
- 기존 등록 휴대폰에 “휴대폰을 한 번 열어 동기화” 안내가 나오면 그 휴대폰에서 앱을 열고 상태 새로고침을 한 번 수행한다. 공개키가 확인되기 전에는 삭제가 fail-closed 된다.
- 최근 출입 이력의 `MOBILE_REMOTE` 성공은 Backend가 MQTT broker에 명령을 전달했다는 뜻이다. Target 수신, 릴레이 동작, 실제 문 움직임은 별도 현장 증거다.
- 개인 관리자 재인증 기본 유효시간은 15분이다. 세션/CSRF/역할 검증은 그대로 유지되며, 만료 안내가 나오면 다시 로그인한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| deploy owner + security reviewer | exact main SHA, immutable API/DB image digest, external secrets, 검증용 NAS change window | `backend/compose.production.yml` render·migration·reverse proxy 계획 | API/DB host port와 source bind 없음, migration backup 우선, API는 migration 완료 뒤 `/ready`; ingress가 mTLS 종료·client header strip/rebuild | production Compose, DB migration runner, `admin_security.py` | rendered config, image digest, migration backup, NAS `/live`·`/ready` capture **OPS PENDING** | maintenance window | failed deployment 1회 rollback | platform/security owner; mutable tag·직접 API 공개·`.env` secret 복사 금지 |
| security owner | CA, hostname, unique broker/backend/Target principals, secret store | MQTTS provisioning | non-1883, CA verify, hostname verify, per-Target topic ACL, blank config fail-closed | `MqttManager.cpp`, `command_security.py`, `mosquitto.conf`, `target-acl` | rogue-CA/plaintext/crossover host tests present; deployed handshake **PENDING** | TLS socket 15초 source 값 | 연결 2회, 5초→30초 backoff 목표 | broker/PKI owner; `setInsecure`/`CERT_NONE` 금지 |
| manufacturing owner | exact board/layout, unique credentials, secure facility | Target provision | Secure Boot v2, release flash encryption, encrypted NVS, anti-rollback, locked debug/download path | `target-production-policy.json`, build policy | eFuse report, manufacturing record **PHYSICAL PENDING** | 작업 window | fuse 작업 0회 재시도 | 하드웨어 security owner; 불명확하면 격리 |
| release owner | signed app/Target manifests, N/N-1 1..2 overlap, last-known-good | production candidate 입력 | exact artifact digest와 provenance; public test-key canary와 구분 | protected workflows, `ota_contract_gate.py` | exact SHA, manifest, cert digest, policy Gate | CI/job timeout | 동일 candidate rerun 1회 | release/security owner; branch artifact 승격 금지 |

## 3. 관리자 로그인·세션·권한

`ADMIN_MTLS_IDENTITIES_JSON`은 certificate SHA-256 fingerprint를 stable subject, roles, tenant scopes에 매핑한다. `ADMIN_TRUSTED_PROXY_IPS`가 비어 있거나 잘못되면 login이 차단되는 것이 정상이다. 세션 cookie는 Secure/HttpOnly/SameSite=Strict이고 unsafe action은 CSRF, 현재 mTLS, `X-Admin-Reauthenticate: mtls`, 128자 이하 `Idempotency-Key`를 모두 요구한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 관리자 | allow-listed proxy가 client cert 검증, fingerprint mapping 존재 | `POST /api/v1/admin/sessions` | 200: `expires_at`, CSRF, secure cookie; 401/429/503: 세션 없음과 exact detail | `AdminSecurity.authenticate`, session API | auth/rate-limit/stale host tests; ingress **PENDING** | 15초 검증 목표, session 기본 900초 | 401은 cert 확인 뒤 1회; 429 window 60초 중 0회 | security/deploy owner에 HTTP detail·fingerprint hash 전달 |
| 관리자 | 유효 session, tenant scope, fresh mTLS | unsafe API 한 번 호출 | role/scope/CSRF/reauth 통과 후 handler; 거부 시 effect 0 | admin middleware | negative tests present | 15초 검증 목표 | 같은 idempotency 1회만 | tenant security owner; cookie/token/key 원문 금지 |
| security owner | identity/key rotation 승인 | `POST /api/v1/admin/sessions/rotate` | 모든 기존 server-side session 무효 | `AdminSecurity.rotate_sessions` | rotation audit/operator evidence **OPS PENDING** | 15초 목표 | 0회 | session store/cluster owner; 확인 전 다음 mutation 금지 |

주요 오류: 401 `verified mTLS client certificate required`, `untrusted client-certificate proxy`, `unrecognized administrator certificate`, `administrator session expired or revoked`; 403 `CSRF validation failed`, `administrator role is not authorized`, `tenant scope violation`; 429 authentication rate limit; 503 authentication not configured.

## 4. Tenant·credential·device·door lifecycle

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| `TENANT_ADMIN` | session/CSRF/reauth, `legacy:<tenant_id>` 또는 `*`, 대상 존재 | `POST /api/v1/admin/tenants/{id}/approve` 또는 `/reject` | DB state와 `admin_audit`가 함께 commit된 뒤 200; 오류면 503, mock row 없음 | `main.py`, migration 003 | backend/admin tests present; deployed DB fault **PENDING** | 15초 목표 | 503이면 state/audit 확인 전 0회; 미commit 확인 후 같은 idempotency 1회 | tenant + DB owner에 status/detail/audit 유무 전달 |
| credential owner | authenticated enrollment actor, tenant/door binding | public key enrollment→approval | challenge/approval, monotonic ACL snapshot, private key 비수집 | `acl_api.py`, `acl_management.py` | concurrency/replay host tests | 15초·Target ACK 60초 목표 | 같은 request ID 1회 | `TARGET_ACK_PENDING`이면 Target owner |
| credential owner | revoke reason, current ACL version | credential revoke/tenant disable | backend `revoked/TENANT_DISABLED`, replacement ACL; Target ACK 전 physical denial 미확정 | ACL management/Target ACL | audit, ACL digest, ACK **PHYSICAL PENDING** | 15초/60초 목표 | same idempotency 1회 | Target/incident owner; force-open 우회 금지 |
| system owner | maintenance window, binding, retention·rollback 계획 | device/door quarantine 또는 decommission | command/access deny, credential revoke, audit, Target denial event | #49/#50, #52 lifecycle | signed decommission record **OPS/PHYSICAL PENDING** | Target event 60초 목표 | 자동 0회 | platform, Target, physical operator |

`pending`, `approved`, `revoked`, `expired`, `quarantined`, `decommissioned`를 구분한다. Backend 값만으로 Target 적용을 추정하지 않는다. 한 door가 여러 tenant에 매핑되거나 Target/topic identity가 다르면 provisioning을 중지한다.

## 5. Force-open 이중 승인

사람의 안전을 먼저 확보하고 현장의 승인된 비상 절차가 있으면 그것을 우선한다. software force-open은 일반 출입 실패의 retry 수단이 아니다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| `SECURITY_OPERATOR` | valid session/CSRF/reauth, tenant scope, safe scene, 8–256자 reason | `POST /api/v1/admin/control/force-open` + idempotency key | 202 `approval_required`, 48자 approval ID, `FORCE_OPEN_PROPOSED`; publish 0회 | `request_force_open`, migrations 003–005 | proposal/no-publish tests | HTTP 15초 목표, expiry 300초 source 값 | 같은 key로 조회/재전송 1회 | incident commander에 approval ID·audit action 전달 |
| 별도 `SECURITY_APPROVER` | same tenant, 다른 subject, proposal PENDING/미만료 | `POST .../{approval_id}/approve` + 새 key | 먼저 `RECONCILIATION_REQUIRED` durable commit; broker ACK 후만 `PUBLISHED` + audit | `approve_force_open`, signed command publisher | self/expiry/replay/crash tests present; deployed broker **PENDING** | HTTP 15초, proposal 300초 | approval/publication 자동 0회 | 404/503이면 backend/DB/broker owner; 새 proposal은 commander 승인 필요 |
| Target + 현장 operator | `PUBLISHED`, current boot identity, safe relay scene | approval과 Target event correlation | verified Target event와 물리 relay effect가 모두 있을 때만 `confirmed`; 없으면 `EFFECT_UNKNOWN` | signed command verifier, `TargetAccessFsm` | approval/audit/boot/session/event/relay trace **PHYSICAL PENDING** | effect 120초 검증 목표 | effect/publish 0회 | incident commander + physical safety owner |

## 6. Broker·TLS·secret rotation

Target은 MAC-derived Target ID와 동일한 broker username, `gatekeeper/v1/targets/<target_id>/command|acl` QoS 1 topic만 사용한다. 명령은 current durable boot ID에 묶인 `sgk-command-v1` P-256 envelope이며 TTL 최대 120초, future skew 최대 30초, N/N-1 protocol 1..2다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| PKI/broker owner | rotation plan, old/new validity overlap, canary Target, rollback secret | CA/server credential stage | old+new verified handshake, rogue CA/plaintext 거부, expiry visible | MQTTS client/server configs | deployed TLS/crossover report **OPS PENDING** | maintenance window, connect 15초 | canary connect 2회 | security owner; verifier 완화 금지 |
| Target credential owner | unique principal/topic ACL, current boot record | per-Target credential rotation | one Target cannot access another namespace; boot state monotonic | broker ACL, boot registry | crossover/rollback tests + live broker **PENDING** | 60초 목표 | new credential 1회, old rollback 1회 | broker/Target owner; shared credential 금지 |
| signing owner | offline key custody, new key ID, N/N-1 signer window | command/ACL/OTA signer rotation | allowed key IDs와 expiry, old-key rejection 시점, session rotation | command/ACL/OTA verifiers | key ceremony + adversarial report **OPS PENDING** | approved window | 0회 자동 | security/release owner |

관리자 session 전체 폐기는 구현됐지만 CA, Target credential, command/ACL/OTA signing key의 production crossover ceremony는 저장소에서 자동 승인하지 않는다(`GAP-52-04`). 임의 shell 명령으로 보완하지 말고 dual review, canary, old/new overlap, expiry와 rollback evidence가 갖춰질 때까지 production key rotation을 금지한다.

## 7. Readiness·metrics·audit·incident

`admin_audit`은 stable actor, tenant scope, action/object reference, hashed idempotency, timestamp만 기록하며 UPDATE/DELETE trigger로 보호된다. 원본 secret이나 PII를 audit에 넣지 않는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| operator | NAS ingress 경계, exact build SHA | `GET /live`와 `GET /health` | `scope=process_liveness_only`; Python process 응답만 확인하고 DB/MQTT/Target 정상으로 승격하지 않음 | `main.py` liveness routes | status/body/timestamp **OPS PENDING** | HTTP 10초 목표 | read-only 5초→30초 2회 | `/live`만 성공하면 deploy owner; traffic admission 금지 |
| deploy owner | DB migration `007`, broker probe, runtime/control secrets, mTLS proxy, ACL runtime, legacy pre-arm OFF | `GET /ready` | 모든 check가 true면 200 `ready`, 하나라도 실패하면 503 `not_ready`와 check map | `_readiness_snapshot`, production Compose healthcheck | exact build·rendered Compose·readiness body **OPS PENDING** | broker probe 1초 source 값, admission 10초 목표 | read-only 2회 | 실패 component owner; `/live`로 우회 금지 |
| auditor/operator | current mTLS admin/auditor session, tenant scope `*` | `GET /api/v1/admin/metrics` | low-cardinality request/MQTT/breaker metrics; tenant/device/MAC label 없음 | `OpsMetrics.prometheus`, admin principal | scrape digest + alert route/ack **OPS PENDING** | scrape 10초·ack 15분 목표 | read-only 1회 | metrics/PKI owner; 인증 없는 scrape port 공개 금지 |
| auditor | tenant scope와 ticket | audit 조회/상관 | proposal→approval→publish→Target/relay을 separate state로 표시 | admin audit + event schema | append-only DB test present; cross-system correlation **PENDING** | query 15초 목표 | read-only 1회 | data/incident owner |
| incident commander | 안전 상태, severity/owner | declare→contain→recover→review | timeline, reason/state, exact artifact, rollback, independent closure | support handbook, #52 | redacted incident record **PENDING** | acknowledge 15분 목표 | containment 1회 승인, auto close 0회 | security/privacy/physical owners |

## 8. Backup·restore

저장소에는 HMAC 인증 manifest, source/target 전체 inventory 비교, 비어 있는 격리 MariaDB restore와 실제 command 시간을 재는 hardwareless 도구가 구현돼 있다. 이 결과는 도구 계약이다. production-like 암호화 backup을 별도 호스트에서 독립 운영자가 복구하기 전에는 `RESTORE_VERIFIED` 또는 승인된 RPO/RTO로 표시하지 않는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| backup owner | encrypted destination, consistent snapshot, 32-byte 이상 manifest key의 secret-file custody | `inventory`→`backup-manifest`→`verify-backup` | dump SHA, exact source commit, migration/table schema·PK·row/content hash와 HMAC가 일치 | `scripts/ops_commercial_gate.py` | source inventory + authenticated manifest **OPS PENDING** | candidate RPO 15분, manifest age 900초 예시; 운영 승인 전 목표 | backup job 1회 | data/platform owner; password CLI·manifest 포함 금지 |
| restore owner + 독립 reviewer | 새 격리 MariaDB, no production egress, 검증된 dump/manifest | `restore-check` | non-empty target 거부, 실제 import→전체 inventory equality, monotonic elapsed; 성공 시에만 report | operations gate, migrations 001–007 | restore report + artifact/manifest digest **OPS PENDING** | candidate RTO 1800초; 운영 검증 전 목표 | 격리 restore 1회 | 실패 artifact 격리, repair query·production restore 금지 |
| deploy owner | current DB image, 외부 `migration_backups` volume | `sgk-migrate up 007` | 변경 전 logical backup+SHA sidecar, exact ledger digest; 동일 재실행 검증, 충돌 overwrite 없음 | DB image `run_migrations.sh` | backup ID, sidecar, ledger, rendered Compose **OPS PENDING** | change window | 실패 시 원인 확인 후 1회; blind rerun 금지 | DB/data owner; API admission 중지 |
| incident commander | business 승인, 독립 restore verified, rollback plan | production restore decision | named approver, restore point, expected loss, post-health와 rollback | commercial operations runbook | decision/audit **PRODUCTION PENDING** | change window | 자동 0회 | data/security/privacy owners |

## 9. OTA canary·rollback

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| release owner | exact main, signed manifest, board/layout, N/N-1, candidate set | canary 시작 승인 | exact firmware/mobile digest, cohort, stop/rollback criteria | protected workflows, OTA contract | software Gate + approval; production signing **PENDING** | release window | artifact 재생성 0회 | mismatch면 release 중단 |
| Target canary | safe state, inactive slot, last-known-good | signed OTA | size/hash/image verify→boot→continuous 30초 health→valid 또는 120초 rollback | `OtaManager.cpp` | OTA-G1..G4 power/network evidence **PHYSICAL PENDING** | 120초 source deadline | install 0회, rollback 1회 | release/firmware owner |
| mobile canary | signed APK/manifest, old APK 보존 | staged install | signer/package/build/version/commit health 또는 failed/pending | mobile updater | Samsung install/fallback **PHYSICAL PENDING** | 60초 검증 목표 | installer 0회 | release/mobile owner |
| release owner | operator drill과 canary evidence, risk approval | promote/stop/rollback | immutable decision and observed cohort health | #52 runbook + Issue #54 | operator/canary record **PENDING** | approved window | 0회 자동 | production authorization owner |

## 10. Decommission

Tenant/door/Target 폐기 전에 access·command credential을 revoke하고, broker ACL과 signer trust를 제거하고, mobile binding을 해제하고, retention/legal hold에 따라 export/delete하며, Target/NVS의 secure erase 또는 RMA quarantine을 기록한다. 마지막 단계는 Target이 명령과 출입을 실제 거부하는지 현장에서 확인하는 것이다. 이 증거가 없으면 `DECOMMISSION_PENDING`이다.

접근성: 관리자 UI는 keyboard/TalkBack label, 200% 글자 크기, focus order, danger confirmation, ko/en 상태, audit link를 검증해야 한다. 현재 API security host evidence와 admin HTML의 상용 operator UX는 별도이며 `GAP-53-02`로 남는다.
