# 제품 역분석·갭 등록부 / Product reverse-analysis gap register

문서 버전: **0.1.2-contract-loop**<br>
통합 기준: `fb827681e1b2f5a8b08aa2784ae419832efff6f7`<br>
분석일: 2026-08-09<br>
상태: **열린 갭 있음; issue #53 완료 아님**

## 분석 방법

신규 사용자·관리자·설치자가 매뉴얼만 읽고 각 여정을 수행한다고 가정한 뒤, 문장에 필요한 상태·권한·오류 이유·복구 경로가 코드/테스트/물리 증거에 실제로 존재하는지 역추적했다. 확인되지 않은 기능은 매뉴얼의 성공 절차로 쓰지 않고 아래 등록부에 제품 또는 테스트 갭으로 열었다.

| 단계 | Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|---|
| R1 기준선 고정 | 문서 소유자 (docs owner) | PR #58 metadata의 `baseRefOid`가 exact current main/base `fb827681e1b2f5a8b08aa2784ae419832efff6f7`이고 `headRefOid`가 검증 대상 `git rev-parse HEAD`와 exact match인지 확인 | PR metadata의 `baseRefOid`/`headRefOid`를 exact 비교한 뒤, `git cat-file blob <baseRefOid>:wiki/log.md`와 `git cat-file blob <headRefOid>:wiki/log.md`를 raw bytes로 읽어 candidate가 base의 exact prefix인지 비교; worktree 텍스트/CRLF 비교는 사용하지 않음 | unexpected base/head 또는 prefix 불일치가 즉시 reject되고, 통과 시 metadata SHA와 raw Git-blob exact-prefix evidence가 매뉴얼에 표시됨 | Git/docs workflow | expected base `fb827681e1b2f5a8b08aa2784ae419832efff6f7`; expected head = exact PR `headRefOid` = candidate `HEAD`; raw `git cat-file` blob check; 독립 reviewer PENDING |

### R1 fail-closed metadata/blob contract

R1은 PR 웹페이지의 제목·branch 이름·worktree 파일을 기준선 증거로 취급하지 않는다. 검증자는 `gh pr view 58 --json baseRefOid,headRefOid`로 metadata를 읽고 `baseRefOid == fb827681e1b2f5a8b08aa2784ae419832efff6f7`, `headRefOid == git rev-parse HEAD`를 각각 exact string으로 확인한 뒤, 두 SHA의 `wiki/log.md` Git blob을 `git cat-file blob`으로 읽어 raw byte prefix를 비교한다. Windows checkout의 CRLF 변환은 비교 대상이 아니다.

필수 mutation/negative case: `baseRefOid`를 `b246aff9698ccbcbcd864f99aab63654cce2cc78` 또는 어떤 unexpected SHA로 바꾼 synthetic PR metadata에 대해 validator가 prefix가 우연히 일치하더라도 **reject**해야 한다. `headRefOid`를 이전 PR head나 다른 candidate SHA로 바꾼 경우도 `git rev-parse HEAD` exact-match 단계에서 reject해야 하며, 이 mutation은 accepted evidence나 physical/production claim을 생성하지 않는다.
| R2 manual walkthrough | 신규 사용자/관리자/설치자 | 각 역할의 계정·장치·안전 조건 | 문서만 사용 | 성공/막힘/추측 지점을 기록 | `manuals/*.md` | walkthrough worksheet NONE; 제품 테스트 필요 |
| R3 갭 triage | 제품·테스트 소유자 | R2 결과와 source trace | 갭 ID, severity, owner | P0/P1/physical과 소프트웨어 갭 분리 | #49–#52 owners | issue/PR/test evidence PENDING |
| R4 재검증 | 독립 reviewer | 수정 PR exact SHA | 동일 입력과 mutation/negative cases | 이전 갭이 닫혔는지와 새 갭이 관찰됨 | 해당 code/test owner | reviewer report PENDING |

## 열린 제품·테스트 갭

| ID / severity | 역분석 관찰 (evidence-gated) | 제품 또는 테스트 요구 | Owner / source trace | 현재 상태 / 필요한 증거 |
|---|---|---|---|---|
| GAP-49-01 P0 | `/api/v1/admin/*`와 tenant 승인/거절 route의 인증·RBAC·CSRF·tenant scope가 기준선에서 보이지 않는다. | deny-by-default middleware, session/MFA/reauth, role/scope matrix와 anonymous/cross-tenant/replay tests | #49; `backend/app/main.py`, `backend/app/static/admin.html` | **BLOCKED/PENDING** — exact-SHA CI와 독립 security review 필요 |
| GAP-49-02 P0 | DB 오류가 admin list/approve/reject에서 mock 데이터/status로 바뀌어 성공처럼 보일 수 있다. | real error response, fail-closed UI state, DB fault regression | #49; `backend/app/main.py` lines around admin routes | **OPEN/PENDING** — fault-injection evidence 필요 |
| GAP-49-03 P0 | force-open route는 현재 구현에서 요청 결과를 `force_opened`로 반환할 수 있으나 역할·재인증·이중 승인·immutable audit 계약이 문서 기준선에 없다. | authorized role, reason, reauth, dual control, effect-confirmed event and audit | #49/#52; `backend/app/main.py`, `src/TargetAccessFsm.cpp` | **BLOCKED/PENDING** — no user-success claim; backend+Target integration evidence 필요 |
| GAP-50-01 P0 | MQTT 처리에 평문/공유 topic 및 TLS 실패 후 `setInsecure()` fallback이 존재한다. | hostname-verified MQTTS/mTLS, credential/topic ACL rotation, fail-closed negative tests | #50; `src/MqttManager.cpp` | **BLOCKED/PENDING** — rogue CA/plaintext/crossover tests 필요 |
| GAP-50-02 P0 | Target 명령의 signed envelope, target binding, freshness, replay/idempotency 계약이 문서와 source에서 일치하지 않는다. | signed command verifier before relay/config/OTA/reboot effects | #50; `src/MqttManager.cpp`, `include/` protocol | **BLOCKED/PENDING** — adversarial vectors + exact artifact evidence 필요 |
| GAP-50-03 P0 | OTA runtime은 version JSON/URL과 `HTTPUpdate`를 사용하지만 signed manifest/digest/layout/health mark/automatic rollback의 실기기 증거가 없다. | dual-slot, inactive image, health window, power-loss rollback, periodic HTTPS and authenticated local recovery | #50/#23; `src/OtaManager.cpp`, `wiki/ota_reliability_contract.md` | **BLOCKED/PHYSICAL PENDING** — host contract is not install/boot evidence |
| GAP-51-01 P0 | fresh install의 native wake opt-in 도달성, permission denied 상황에서 updater/manual/diagnostics 독립 접근 여부가 미확인이다. | Ready/Degraded/Blocked truthful state, independent recovery shell, OEM matrix | #51; `BleWakeRegistrar.kt`, Flutter UI, `MainActivity.kt` | **BLOCKED/OEM PENDING** — Samsung/One UI 100 trials required |
| GAP-51-02 P0 | `TARGET_LOCAL` locator와 secure storage 허용 형식의 호환성 및 revoked/missing/late/duplicate/timeout 이유의 end-to-end 표시가 물리적으로 확인되지 않았다. | authenticated target locator, durable reason propagation, effect-before-success invariant | #51; `MainActivity.kt`, `gattworker/`, `wiki/android_gatt_worker.md` | **BLOCKED/PHYSICAL PENDING** — real target + Samsung evidence required |
| GAP-51-03 P0 | updater artifact hash/signing cert/fallback/install health/old APK preservation은 계약 문서와 tests에 있으나 commercial installer walkthrough가 없다. | release signing fail-closed and fallback proof on bad hash/cert/downgrade/installer failure | #51/#23; `gatekeeper_app/android`, `scripts/ota_contract_gate.py` | **BLOCKED/PHYSICAL PENDING** — signed APK/install/recovery evidence required |
| GAP-52-01 P1 | event/support export가 opaque identity, session/boot ID, digest, redaction, retention/deletion을 실제 운영 저장소와 연결한 증거가 없다. | data inventory, redaction test, retention/deletion and consented export | #52; `observability/`, `wiki/observability_event_schema.md` | **OPEN/PENDING** — schema+runtime+privacy review required |
| GAP-52-02 P1 | backup/restore 절차에 독립 restore, integrity check, measured RPO/RTO, credential/ACL/audit validation 결과가 없다. | MariaDB backup/restore drill, isolated restore, integrity and RPO/RTO artifacts | #52; `backend/db`, `backend/docker-compose.yml` | **BLOCKED/OPS PENDING** — live/isolated restore evidence required |
| GAP-52-03 P1 | broker/API/DB/DNS/certificate/storage 장애의 alert, backpressure, dedupe, SLO와 operator-visible state가 문서에서 확정되지 않았다. | fault matrix, bounded recovery, alert ownership, 24h soak/load evidence | #52; `wiki/observability_event_schema.md`, `wiki/ota_operations_runbook.md` | **OPEN/PENDING** — hosted and live infrastructure evidence separate |
| GAP-53-01 P1 | offline/OEM/GATT/backend/update/lost-phone/privacy 오류뿐 아니라 installer의 relay-idle, Target-offline, OTA boot-failure, sensor fault와 administrator의 auth/RBAC, force-open, backup/restore, audit 상태도 actor·timeout·bounded retry·escalation 계약 없이 일반 안내로 남아 있었다. 문서 계약만으로 구현/API 동작이나 현장 안전을 증명할 수 없다. | #49 admin/auth/RBAC/force-open owner, #50 Target/TLS/OTA owner, #51 OEM/GATT/updater owner, #52 privacy/observability/backup owner가 각 timeout/retry/escalation을 state/event/audit와 연결하고 timeout·duplicate·retry-exhaustion·rollback·fault-injection 회귀를 추가한다. installer/admin이 동일 입력으로 observable output과 evidence artifact를 재현하는 walkthrough도 별도로 수행한다. | #49/#50/#51/#52; `manuals/administrator_manual_ko.md`, `manuals/installer_service_manual_ko.md`, `manuals/general_user_manual_ko.md`, `manuals/support_incident_handbook_ko.md`; `src/MqttManager.cpp`, `src/OtaManager.cpp`, `src/main.cpp`, backend ACL/backup/observability owners | **OPEN/PENDING** — manuals now trace installer/admin owners and target contracts; implementation, SLO, state/event/audit regression, OEM, physical and operator evidence remain required |
| GAP-PHY-01 P0 | GPIO3 relay polarity, High-Z OFF, flyback/power isolation, sensor range, relay operation and local safety sign-off는 소스만으로 판단할 수 없다. | wiring photo, meter trace, repeated physical runs, safety/regulatory sign-off | installer; `wiki/pin_mapping.md`, `wiki/hardware_test.md` | **PHYSICAL PENDING** — no physical acceptance in this PR |
| GAP-PHY-02 P0 | Samsung/OEM screen-off, reboot, process kill, permission transition, Bluetooth/network degradation과 ESP32 boot/rollback/OTA는 host tests가 대체하지 못한다. | exact device/build matrix, 100-run and power-loss evidence | #50/#51; `wiki/android_ble_wake_adr.md`, `wiki/ota_reliability_contract.md` | **PHYSICAL PENDING** — walkthrough cannot close this gate |

## 상태 문장 규칙

- `DOCUMENTED`: source/test/evidence is present and independently reproducible; does not imply physical or production acceptance.
- `OPEN`: product/test owner must add behavior or contract evidence.
- `BLOCKED`: prerequisite #49–#52 or security contract is missing; do not write a workaround as user success.
- `PHYSICAL PENDING`: hardware/OEM/operator/production walkthrough has not run; host/CI evidence is insufficient.

## #49–#52 이후 반복 루프

1. **#49**: authentication/RBAC/tenant scope, fail-closed errors, force-open audit contract을 merge 전 exact-SHA negative tests로 닫는다.
2. **#50**: signed command/TLS/OTA verifier와 dual-slot health/rollback을 구현하고 host adversarial tests 후 Target power/network/rollback 실기기로 검증한다.
3. **#51**: wake/GATT/updater 상태 shell을 연결하고 Samsung/OEM에서 screen-off/reboot/kill/permission/Bluetooth/network 및 install failure를 반복한다.
4. **#52**: event redaction/retention, backup/restore, alert/SLO/soak를 운영 환경 또는 격리 복원으로 측정한다.
5. 각 회차 종료 시 동일 매뉴얼을 독립 actor가 다시 읽고, 모든 단계의 `observable output`이 state/event/physical effect와 일치하는지 확인한다.
6. 남은 P0/P1 또는 physical item이 0이 될 때까지 버전을 올리며 반복한다. 이 기준선은 그 조건을 충족하지 않으므로 issue #53을 닫지 않는다.

## Remediation review boundary

이번 수정은 main 통합과 문서 계약 명시만 수행했다. timeout/retry/escalation 값은 제품 구현 또는 운영 SLO를 완료로 주장하지 않으며, #49–#52 owner가 exact state/event/audit evidence와 negative regression으로 닫아야 한다.
