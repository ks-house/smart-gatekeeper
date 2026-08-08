# 제품 역분석·갭 등록부 / Product reverse-analysis gap register

문서 버전: **0.1.2-contract-loop**<br>
통합 기준: `c654a18f0fa278e4530229bb881fe88286d25c2e`<br>
분석일: 2026-08-09<br>
상태: **열린 갭 있음; issue #53 완료 아님**

## 분석 방법

신규 사용자·관리자·설치자가 매뉴얼만 읽고 각 여정을 수행한다고 가정한 뒤, 문장에 필요한 상태·권한·오류 이유·복구 경로가 통합 기준 `c654a18f...`의 코드/테스트/물리 증거에 실제로 존재하는지 다시 역추적했다. PR #57이 제공한 #49 host/software control은 `DOCUMENTED (HOST/SOFTWARE)`로 재분류하고, deployed proxy/operator/Target/physical/production 증거는 별도 `PENDING`으로 유지한다. 확인되지 않은 기능은 매뉴얼의 성공 절차로 쓰지 않고 아래 등록부에 제품 또는 테스트 갭으로 열었다.

| 단계 | Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|---|
| R1 기준선 고정 | 문서 소유자 (docs owner) | PR #58 metadata의 `baseRefOid`가 exact current main/base `c654a18f0fa278e4530229bb881fe88286d25c2e`이고 `headRefOid`가 검증 대상 `git rev-parse HEAD`와 exact match인지 확인 | PR metadata의 `baseRefOid`/`headRefOid`를 exact 비교한 뒤, `git cat-file blob <baseRefOid>:wiki/log.md`와 `git cat-file blob <headRefOid>:wiki/log.md`를 raw bytes로 읽어 candidate가 base의 exact prefix인지 비교; worktree 텍스트/CRLF 비교는 사용하지 않음 | unexpected base/head 또는 prefix 불일치가 즉시 reject되고, 통과 시 metadata SHA와 raw Git-blob exact-prefix evidence가 매뉴얼에 표시됨 | Git/docs workflow | expected base `c654a18f0fa278e4530229bb881fe88286d25c2e`; expected head = exact PR `headRefOid` = candidate `HEAD`; raw `git cat-file` blob check; 독립 reviewer PENDING |

### R1 fail-closed metadata/blob contract

R1은 PR 웹페이지의 제목·branch 이름·worktree 파일을 기준선 증거로 취급하지 않는다. 검증자는 `gh pr view 58 --json baseRefOid,headRefOid`로 metadata를 읽고 `baseRefOid == c654a18f0fa278e4530229bb881fe88286d25c2e`, `headRefOid == git rev-parse HEAD`를 각각 exact string으로 확인한 뒤, 두 SHA의 `wiki/log.md` Git blob을 `git cat-file blob`으로 읽어 raw byte prefix를 비교한다. Windows checkout의 CRLF 변환은 비교 대상이 아니다.

필수 mutation/negative case: `baseRefOid`를 `b246aff9698ccbcbcd864f99aab63654cce2cc78` 또는 어떤 unexpected SHA로 바꾼 synthetic PR metadata에 대해 validator가 prefix가 우연히 일치하더라도 **reject**해야 한다. `headRefOid`를 이전 PR head나 다른 candidate SHA로 바꾼 경우도 `git rev-parse HEAD` exact-match 단계에서 reject해야 하며, 이 mutation은 accepted evidence나 physical/production claim을 생성하지 않는다.
| R2 manual walkthrough | 신규 사용자/관리자/설치자 | 각 역할의 계정·장치·안전 조건 | 문서만 사용 | 성공/막힘/추측 지점을 기록 | `manuals/*.md` | walkthrough worksheet NONE; 제품 테스트 필요 |
| R3 갭 triage | 제품·테스트 소유자 | R2 결과와 source trace | 갭 ID, severity, owner | P0/P1/physical과 소프트웨어 갭 분리 | #49–#52 owners | issue/PR/test evidence PENDING |
| R4 재검증 | 독립 reviewer | 수정 PR exact SHA | 동일 입력과 mutation/negative cases | 이전 갭이 닫혔는지와 새 갭이 관찰됨 | 해당 code/test owner | reviewer report PENDING |

## 열린 제품·테스트 갭

| ID / severity | 역분석 관찰 (evidence-gated) | 제품 또는 테스트 요구 | Owner / source trace | 현재 상태 / 필요한 증거 |
|---|---|---|---|---|
| GAP-49-01 P0 | `c654a18f...`는 `/api/v1/admin/*`에 deny-by-default session middleware를 두고 proxy-verified mTLS fingerprint, server-side expiry/revocation, role/tenant scope, unsafe-request CSRF·현재 mTLS 재인증·bounded idempotency와 auth rate limit을 검사한다. | deployed reverse proxy가 client identity header를 strip/rebuild하고 allow-listed peer에서만 API에 도달하는지, session store 운영 제약과 operator reason 표시를 검증 | #49; `backend/app/admin_security.py`, `backend/app/main.py:356-407,581-695`, `backend/app/static/admin.html`, `wiki/admin_control_plane_security.md` | **DOCUMENTED (HOST/SOFTWARE)** — anonymous/forged/stale/CSRF/cross-tenant/rate-limit tests present; deployed mTLS proxy, multi-replica/session operations, operator UI walkthrough **PENDING** |
| GAP-49-02 P0 | admin tenant list/approve/reject는 DB/audit 예외를 503 `tenant ... unavailable`로 반환하고 unreachable mock rows 뒤로 fall through하지 않는다; 승인/회수는 audit와 state update transaction이 commit된 뒤에만 성공 status를 반환한다. | DB outage/commit ambiguity에서 UI가 generic success를 표시하지 않고 exact detail/audit 유무를 operator에게 전달하는 fault matrix | #49; `backend/app/main.py:621-695`, migration 003, `backend/tests/test_admin_security.py` | **DOCUMENTED (HOST/SOFTWARE)** — fail-closed source/backend suite present; deployed DB fault injection and operator UI reason/evidence walkthrough **PENDING** |
| GAP-49-03 P0 | 관리자 dual-control은 `POST /api/v1/admin/control/force-open` proposal과 `/{approval_id}/approve`로 분리되고 reason, distinct roles/subjects, reauth, tenant scope, idempotency, 300초 expiry, immutable audit와 durable `PENDING → RECONCILIATION_REQUIRED → PUBLISHED` 상태를 가진다. `published`는 broker ACK 범위이며 relay confirmation이 아니다. 별도 mobile compatibility `POST /api/v1/door/open`은 v2 proof/nonce를 요구하고 역시 `broker-ack-only`다. | administrator reason/timeout/retry/escalation 표시, reconciliation 운영; #50 signed Target command와 #52 approval↔Target event correlation 후 physical relay effect 확인 | #49/#50/#52; `backend/app/main.py:945-1100`, `admin_security.py`, migrations 003–005, `backend/tests/test_admin_security.py`, `backend/tests/test_migrations.py`, `src/TargetAccessFsm.cpp` | **DOCUMENTED (HOST/SOFTWARE) / PHYSICAL PENDING** — self/expiry/replay/cross-tenant/duplicate/pre/post-publish/concurrency evidence present; deployed broker/reconciliation, Target signed-command, operator and relay evidence **PENDING** |
| GAP-50-01 P0 | MQTT 처리에 평문/공유 topic 및 TLS 실패 후 `setInsecure()` fallback이 존재한다. | hostname-verified MQTTS/mTLS, credential/topic ACL rotation, fail-closed negative tests | #50; `src/MqttManager.cpp` | **BLOCKED/PENDING** — rogue CA/plaintext/crossover tests 필요 |
| GAP-50-02 P0 | Target 명령의 signed envelope, target binding, freshness, replay/idempotency 계약이 문서와 source에서 일치하지 않는다. | signed command verifier before relay/config/OTA/reboot effects | #50; `src/MqttManager.cpp`, `include/` protocol | **BLOCKED/PENDING** — adversarial vectors + exact artifact evidence 필요 |
| GAP-50-03 P0 | OTA runtime은 version JSON/URL과 `HTTPUpdate`를 사용하지만 signed manifest/digest/layout/health mark/automatic rollback의 실기기 증거가 없다. | dual-slot, inactive image, health window, power-loss rollback, periodic HTTPS and authenticated local recovery | #50/#23; `src/OtaManager.cpp`, `wiki/ota_reliability_contract.md` | **BLOCKED/PHYSICAL PENDING** — host contract is not install/boot evidence |
| GAP-51-01 P0 | fresh install의 native wake opt-in 도달성, permission denied 상황에서 updater/manual/diagnostics 독립 접근 여부가 미확인이다. | Ready/Degraded/Blocked truthful state, independent recovery shell, OEM matrix | #51; `BleWakeRegistrar.kt`, Flutter UI, `MainActivity.kt` | **BLOCKED/OEM PENDING** — Samsung/One UI 100 trials required |
| GAP-51-02 P0 | `TARGET_LOCAL` locator와 secure storage 허용 형식의 호환성 및 revoked/missing/late/duplicate/timeout 이유의 end-to-end 표시가 물리적으로 확인되지 않았다. | authenticated target locator, durable reason propagation, effect-before-success invariant | #51; `MainActivity.kt`, `gattworker/`, `wiki/android_gatt_worker.md` | **BLOCKED/PHYSICAL PENDING** — real target + Samsung evidence required |
| GAP-51-03 P0 | updater artifact hash/signing cert/fallback/install health/old APK preservation은 계약 문서와 tests에 있으나 commercial installer walkthrough가 없다. | release signing fail-closed and fallback proof on bad hash/cert/downgrade/installer failure | #51/#23; `gatekeeper_app/android`, `scripts/ota_contract_gate.py` | **BLOCKED/PHYSICAL PENDING** — signed APK/install/recovery evidence required |
| GAP-52-01 P1 | event/support export가 opaque identity, session/boot ID, digest, redaction, retention/deletion을 실제 운영 저장소와 연결한 증거가 없다. | data inventory, redaction test, retention/deletion and consented export | #52; `observability/`, `wiki/observability_event_schema.md` | **OPEN/PENDING** — schema+runtime+privacy review required |
| GAP-52-02 P1 | backup/restore 절차에 독립 restore, integrity check, measured RPO/RTO, credential/ACL/audit validation 결과가 없다. | MariaDB backup/restore drill, isolated restore, integrity and RPO/RTO artifacts | #52; `backend/db`, `backend/docker-compose.yml` | **BLOCKED/OPS PENDING** — live/isolated restore evidence required |
| GAP-52-03 P1 | broker/API/DB/DNS/certificate/storage 장애의 alert, backpressure, dedupe, SLO와 operator-visible state가 문서에서 확정되지 않았다. | fault matrix, bounded recovery, alert ownership, 24h soak/load evidence | #52; `wiki/observability_event_schema.md`, `wiki/ota_operations_runbook.md` | **OPEN/PENDING** — hosted and live infrastructure evidence separate |
| GAP-53-01 P1 | manuals now give installer and administrator journeys explicit reason/state, timeout, bounded retry, escalation owner and evidence semantics. The administrator manual traces exact #49 auth, approve/revoke, dual-control proposal/approval/reconciliation/effect-unknown routes and links the shared support contract; values labeled 문서 목표 do not claim implementation. | #50/#51/#52 owners must connect remaining Target/OEM/alert/backup reason and timeout contracts to product state/event/audit regression; independent installer/admin/operator walkthrough must reproduce the same observable output and evidence artifact | #49/#50/#51/#52; `manuals/administrator_manual_ko.md`, `manuals/installer_service_manual_ko.md`, `manuals/general_user_manual_ko.md`, `manuals/support_incident_handbook_ko.md`; #49 exact source/tests above, `src/MqttManager.cpp`, `src/OtaManager.cpp`, backend backup/observability owners | **DOCUMENTED CONTRACT / PRODUCT+OPS+PHYSICAL PENDING** — #49 host/software trace present; implemented SLO/alerts/backup, OEM, Target/relay, operator and production evidence remain required |
| GAP-PHY-01 P0 | GPIO3 relay polarity, High-Z OFF, flyback/power isolation, sensor range, relay operation and local safety sign-off는 소스만으로 판단할 수 없다. | wiring photo, meter trace, repeated physical runs, safety/regulatory sign-off | installer; `wiki/pin_mapping.md`, `wiki/hardware_test.md` | **PHYSICAL PENDING** — no physical acceptance in this PR |
| GAP-PHY-02 P0 | Samsung/OEM screen-off, reboot, process kill, permission transition, Bluetooth/network degradation과 ESP32 boot/rollback/OTA는 host tests가 대체하지 못한다. | exact device/build matrix, 100-run and power-loss evidence | #50/#51; `wiki/android_ble_wake_adr.md`, `wiki/ota_reliability_contract.md` | **PHYSICAL PENDING** — walkthrough cannot close this gate |

## 상태 문장 규칙

- `DOCUMENTED (HOST/SOFTWARE)`: exact integrated source and local/host regression evidence are present and reproducible; it does not imply deployed infrastructure, operator, physical, or production acceptance.
- `DOCUMENTED CONTRACT`: the manual contains the required executable fields, but the referenced implementation/SLO/operational evidence may remain pending.
- `OPEN`: product/test owner must add behavior or contract evidence.
- `BLOCKED`: prerequisite #49–#52 or security contract is missing; do not write a workaround as user success.
- `PHYSICAL PENDING`: hardware/OEM/operator/production walkthrough has not run; host/CI evidence is insufficient.

## #49–#52 이후 반복 루프

1. **#49**: `c654a18f...`의 authentication/RBAC/tenant scope, fail-closed errors, durable force-open audit/publication host controls을 exact-SHA negative tests로 재확인한다. 배포 proxy/session, operator reconciliation과 Target/physical effect는 별도 evidence로 닫는다.
2. **#50**: signed command/TLS/OTA verifier와 dual-slot health/rollback을 구현하고 host adversarial tests 후 Target power/network/rollback 실기기로 검증한다.
3. **#51**: wake/GATT/updater 상태 shell을 연결하고 Samsung/OEM에서 screen-off/reboot/kill/permission/Bluetooth/network 및 install failure를 반복한다.
4. **#52**: event redaction/retention, backup/restore, alert/SLO/soak를 운영 환경 또는 격리 복원으로 측정한다.
5. 각 회차 종료 시 동일 매뉴얼을 독립 actor가 다시 읽고, 모든 단계의 `observable output`이 state/event/physical effect와 일치하는지 확인한다.
6. 남은 P0/P1 또는 physical item이 0이 될 때까지 버전을 올리며 반복한다. 이 기준선은 그 조건을 충족하지 않으므로 issue #53을 닫지 않는다.

## Remediation review boundary

이번 수정은 exact integrated base `c654a18f...`에 맞춘 0.1.2 provenance와 reverse analysis, 그리고 관리자/지원 문서 계약만 갱신한다. #49의 host/software 결과는 PR #57 source/tests 범위에서만 `DOCUMENTED`이며, timeout/retry/escalation 값은 제품 구현 또는 운영 SLO 완료를 주장하지 않는다. #50–#52 owner와 deployment/operator/physical owners가 exact state/event/audit evidence, negative regression, Target/relay correlation으로 남은 gate를 닫아야 한다.
