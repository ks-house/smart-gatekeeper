# 관리자 매뉴얼 / Administrator manual

문서 버전: **0.1.2-contract-loop** · 기준 커밋: `cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f`<br>
대상: 관리자/건물 운영자 (administrator/operator) · 상태: **#49–#52 및 운영 증거 대기**

## 운영 원칙

관리자 화면은 인증된 세션, 명시적 tenant scope, 최소 권한, 재인증이 전제다. 기준선의 admin route에 이 계약이 모두 구현되었다고 가정하지 않는다. DB 오류가 mock 성공을 반환하거나 `force-open` 요청 접수와 실제 relay 효과를 혼동하지 않는다.

## 용어와 역할 / Roles and terminology

| 한국어 | English | 책임 |
|---|---|---|
| 시스템 소유자 | system owner | tenant/door 정책과 운영 승인 |
| 관리자 | administrator | 사용자·기기·권한 lifecycle, 감사 조회 |
| 설치자 | installer | 배선·프로비저닝·시운전; 운영 권한과 분리 |
| 지원 대응자 | support responder | 진단·사고 triage; force-open은 별도 승인 |
| 회수 | revoke | 자격을 즉시 무효화하고 대체 ACL을 배포 |
| 강제 개방 | force-open | 위험 동작; 역할·재인증·사유·이중 승인·감사 필요 |

## 공통 단계 필드

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 관리자 | OIDC/mTLS 또는 승인된 세션, tenant scope, MFA/재인증 | 사용자·door·device lifecycle 조작 | 상태 전이와 audit ID; 권한 오류는 fail-closed | #49 auth middleware/API **GAP-49-01** | auth/RBAC matrix + negative CI **PENDING** |
| 관리자 | 운영 change 승인과 rollback plan | 정책/secret/config 변경 | diff, actor, reason, expiry, reviewer 표시 | #49/#50/#52 | immutable audit + reviewer **PENDING** |

## Tenant·device·door lifecycle

1. tenant를 생성할 때 원본 주민 정보와 device/door identity를 분리하고 필요한 최소 정보만 저장한다.
2. device/door는 제조 identity, target binding, protocol range, 상태(`provisioned`, `active`, `quarantined`, `decommissioned`)를 확인한다.
3. 사용자는 `pending → active → revoked` 흐름을 따른다. DB 오류/timeout은 `unknown` 또는 실패로 보이며 mock `approved`가 아니다.
4. tenant disable은 영향을 받는 모든 credential과 Target ACL replacement job을 원자적으로 처리해야 한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 관리자 | 인증·tenant scope, 대상 존재 | 사용자 승인/거절 | `active`/`rejected`와 audit; DB 장애는 오류 | `backend/app/main.py`, `acl_management.py` | #49 integration + fault injection **PENDING** |
| 관리자 | revoke 사유·current ACL version | credential 회수 | 즉시 denied, monotonic ACL replacement queued | `backend/app/acl_management.py`, `acl_api.py` | concurrency/replay/Target ACK **PENDING** |
| 관리자 | device binding와 maintenance window | device quarantine/decommission | 신규 출입·명령이 거부되고 audit 생성 | #49/#50 Target ACL | target denial + audit **PENDING** |

## Force-open 통제

현재 기준선의 MQTT/API 경로는 force-open payload와 relay 결과를 별도의 인증·승인·감사·물리 확인 contract로 묶었다고 볼 수 없다. 따라서 아래 표는 운영 절차가 아니라 #49/#50/#52를 닫기 위한 승인 기준이다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 요청자 | 최소 권한, 대상 door, 명확한 사고 사유 | force-open request | `requested`, 재인증/2차 승인 대기; relay 성공 문구 금지 | backend force-open API **GAP-49-03** | request audit **PENDING** |
| 승인자 | 독립 계정, tenant/door scope, 최근 재인증 | approve once with reason | signed/idempotent command envelope 발행 | #49/#50 command verifier | dual-control/replay vector **PENDING** |
| Target/operator | safe state, signed target-bound command | command receive | relay event와 audit correlation; 실패/unknown reason | `TargetAccessFsm.cpp`, `MqttManager.cpp` | ESP32 relay + event evidence **PHYSICAL PENDING** |

## Broker·TLS·secret rotation

plain broker, shared credentials, hostname 미검증, `setInsecure()` fallback은 production 절차로 승인하지 않는다. rotation은 old/new overlap window, target binding, rollback owner, expiry와 독립 검증을 포함해야 한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 보안 관리자 | 새 인증서/credential이 승인·감사됨 | staged rotation | old/new 상태와 만료 시각이 보임; rogue CA는 거부 | `src/MqttManager.cpp`, #50 | hostname/rogue-CA/crossover tests **PENDING** |
| 운영자 | canary target과 rollback credential 보존 | canary connect/publish | online event는 verified TLS와 target ID를 포함 | MQTT manager/observability | exact target event **PENDING** |

## 모니터링·장애·복구

`online/offline`, backend/API/DB/MQTT/DNS/certificate/storage 상태와 event lag를 별도로 본다. 화면 health가 healthy라고 하더라도 relay 또는 OTA physical health를 의미하지 않는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 운영자 | alert routing과 redacted logs | broker/API/DB 장애 확인 | alert, bounded retry/circuit breaker, owner와 next action | #52 observability | fault matrix + 24h soak **PENDING** |
| 관리자 | 백업 artifact, 격리 restore 환경, 승인된 key | restore drill | RPO/RTO, tenant/ACL/audit integrity 결과 | #52, `backend/db` | independent restore report **PENDING** |
| 관리자 | incident commander 지정 | incident declare/resolve | timeline, evidence IDs, rollback/closure review | support handbook/#52 | postmortem + reviewer **PENDING** |

## OTA canary·rollback·decommission

OTA는 signed manifest/digest/board/layout/anti-downgrade 검증 → inactive slot 설치 → reboot → health window → valid mark 또는 rollback 순서여야 한다. MQTT remote trigger 하나만 성공으로 기록하지 않는다. 기준선은 이 순서의 실기기 증거가 없다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| Release owner | signed artifact, N/N-1 compatibility, canary set | release candidate | canary state와 digest, stop/rollback decision visible | `ota/`, `scripts/ota_contract_gate.py` | host gate + target install **PENDING** |
| Operator | old slot bootable, health window | power/network interruption mutation | last-known-good 유지, automatic rollback, credential/ACL/NVS preservation | `src/OtaManager.cpp`, bootloader | power-loss physical evidence **PENDING** |
| Owner | data retention/credential revocation plan | decommission target/tenant | commands revoked, data export/deletion/audit complete | #49/#52 | signed decommission record **PENDING** |

## 접근성·권한 안전

관리자 UI/API에는 keyboard/TalkBack accessible labels, 200% text, focus order, contrast, ko/en terminology, dangerous-action confirmation과 audit link가 필요하다. #49 RBAC와 #51 accessibility/OEM acceptance가 완료되기 전까지 운영 승인하지 않는다.
