# 제품 역분석·갭 등록부 / Product gap register

문서 버전: **0.3.0-rc.1** · 제품 기준: `e42d1f417a555b17d7476522aa48f7e4d72306b7`<br>
범위: 매뉴얼→제품→test→독립 walkthrough 반복 결과. `OPEN/BLOCKED/PENDING`이 남아 있으므로 Issue #53 완료나 production readiness를 주장하지 않는다.

## 1. 판정 용어

| 판정 | 의미 |
|---|---|
| `RESOLVED SOFTWARE` | exact source와 negative regression이 있고 이번 fixture에서 재현됨. 물리·운영 증거는 포함하지 않음 |
| `DOCUMENTED CONTRACT` | actor/precondition/input/output/owner/evidence/timeout/retry/escalation이 문서에 있으나 구현 또는 운영 검증이 남음 |
| `BLOCKED` | 필요한 기능·권한·운영 접근이 없어 actor가 여정을 끝낼 수 없음 |
| `OPS PENDING` | 실제 ingress/broker/DB/backup/alert/privacy/support 환경과 승인 필요 |
| `PHYSICAL PENDING` | Samsung/OEM, ESP32-C6, relay/sensor, bootloader/OTA 또는 operator 현장 증거 필요 |
| `PRODUCTION PENDING` | production secret/signing, canary와 risk-owner 승인 필요 |

## 2. Reverse-analysis 회차

| Round | Input baseline | Walkthrough | 발견 | 조치/결과 |
|---|---|---|---|---|
| R0 | PR #58, `c654a18f...` | 기존 6개 manual source trace | #50/#51을 전부 미구현으로 고정, 절차 열 누락, restore/locale/registration 숨은 전제 | baseline은 draft 유지 |
| R1 | exact main `1ce7f16...` | 사용자·관리자·설치자·지원 12개 hardwareless fixture | #50 signed transport/OTA와 #51 recovery/updater 구현이 문서에 반영되지 않음; #52, locale, admin UI, physical gap 확인 | 7개 문서 갱신, fixture와 contract regression 추가 |
| R2 | exact main `e42d1f4...` | #52 source/API/DB/Compose/operations gate 역추적 + 16개 fixture | readiness/liveness 혼동, support consent, retention idempotency, restore 도구를 미구현으로 적은 stale 설명 발견 | exact endpoint·명령·증거 경계 반영; live NAS/법무/독립 restore는 pending 유지 |
| R3 | R2 문서 | 독립 source/fixture/link/UTF-8/secret/stale-claim 검사 | 결과는 PR validation evidence에 고정 | 실패 시 merge 금지; NAS와 physical checklist는 사용자·operator 수행 |

## 3. 해결한 문서·software 불일치

| Gap | 숨은 전제/오해 | 변경 | 판정 |
|---|---|---|---|
| GAP-53-BASELINE | 모든 문서가 `c654a18f...`를 기준으로 #50/#51을 미구현이라 설명 | exact `1ce7f16...` 기준으로 #49/#50/#51 software와 증거 경계를 다시 trace | `RESOLVED SOFTWARE` by manual contract test |
| GAP-53-FIELDS | 표 일부에 timeout/retry/escalation이 없고 success가 화면 문구에 의존 | 모든 핵심 절차를 9-field 계약으로 확장, state/effect 경계 통일 | `RESOLVED SOFTWARE` for document structure |
| GAP-50-DOC | verified MQTTS, per-Target ACL, signed current-boot command, replay ledger, signed inactive-slot OTA/local recovery가 여전히 BLOCKED로 표기 | 구현된 exact source와 source timeout/health를 관리자·설치자·지원 매뉴얼에 반영 | `RESOLVED SOFTWARE`; live broker/ESP32 remains pending |
| GAP-51-DOC | consent/recovery shell, encrypted recent Target, updater artifact identity·first-run health·redaction이 PENDING으로만 표기 | host-tested 구현을 반영하고 Samsung/install/relay를 별도 pending으로 유지 | `RESOLVED SOFTWARE`; OEM/physical remains pending |
| GAP-53-WALKTHROUGH | 실행 가능한 manual fixture가 없음 | 12개 actor journey JSON과 contract test, 사용자 physical checklist 추가 | `RESOLVED SOFTWARE` |
| GAP-52-DOC | `/live`를 전체 정상으로 오해하고 support export/retention/restore를 전부 미구현으로 표기 | exact `/live`·`/ready`·metrics, consent-bound export, payload-bound deletion, HMAC inventory restore와 production Compose를 매뉴얼/fixture/test에 고정 | `RESOLVED SOFTWARE`; NAS/live/legal/independent restore pending |

## 4. 열린 제품·운영 gap

| Gap / severity | Actor가 막히는 지점 | 정확한 owner·필요 변경 | 종료 증거 | 상태 |
|---|---|---|---|---|
| GAP-52-01 P0 | 신규 사용자가 current Web shell에서 self enrollment 또는 scoped remote credential을 받을 수 없음; anonymous/device-ID route는 안전하게 비활성 | mobile/backend product owner: tenant/door/device-bound possession credential provisioning, mobile v2 envelope, revoke/expiry UI; Backend HMAC secret을 앱에 넣지 않음 | enrollment→approval→manual remote→revoke negative tests, Samsung/Target effect 분리 | `BLOCKED` |
| GAP-52-02 P1 | low-cardinality metrics/SLO/breaker/alert contract는 구현됐으나 NAS에서 fault alert가 실제 on-call에게 전달·ack됐는지 알 수 없음 | NAS ops owner: exact build의 `/ready`·authenticated metrics, DNS/TLS/DB/storage fault matrix와 24h soak를 실행 | deployed alerts + on-call ack/closure + soak artifact | `OPS PENDING` |
| GAP-52-03 P1 | HMAC manifest와 full-inventory isolated restore 도구는 구현됐으나 production-like 암호화 backup/별도 호스트/operator evidence가 없음 | data owner: approved encrypted storage와 isolated MariaDB에서 `inventory`/`verify-backup`/`restore-check` 실행 | exact artifact restore report, measured RPO/RTO, separate reviewer | `OPS PENDING` |
| GAP-52-04 P0 | TLS/Target credential/signing key rotation을 dual review로 실행할 production command·ceremony가 없음 | Issue #52 security/platform: staged old/new, canary, rollback, expiry, session rotation, no secret output | live crossover/expiry/rollback evidence and signed ceremony | `OPS/PRODUCTION PENDING` |
| GAP-52-05 P0 | technical consent export와 retention deletion은 구현됐지만 controller/contact/legal basis/approved retention/processor/rights deadline가 없음 | privacy/legal owner: legal notice 승인; NAS owner: ticket access/deletion drill | approved legal notice, deletion/rights fulfillment and access audit | `BLOCKED/OPS/PRODUCTION PENDING` |
| GAP-51-04 P1 | 앱이 `ko/en` locale을 선언하지만 disclosure는 한국어 고정, recovery는 ko/en 혼합이며 명시적 언어 전환·전체 번역이 없음 | mobile UX owner: generated localization resources, user locale selector 또는 명확한 system-locale 정책, every screen/reason semantics | ko/en golden/widget, TalkBack, 200% and Samsung walkthrough | `BLOCKED/PHYSICAL PENDING` |
| GAP-53-02 P1 | admin HTML은 API security와 달리 상용 operator state/reason, keyboard/TalkBack, 200%, ko/en, audit correlation walkthrough가 없음 | admin UX owner: accessible control plane UI and exact error/reconciliation rendering | browser accessibility tests + independent operator walkthrough | `BLOCKED/OPS PENDING` |
| GAP-53-03 P1 | app/backend redaction과 DB consent-bound export는 host-tested됐지만 앱 preview→NAS ticket 수신·access audit·ticket-close deletion은 미검증 | support/privacy/NAS owner | approved consent capture, export digest, ticket access/deletion drill | `OPS PENDING` |

## 5. 열린 물리·operator·production Gate

| Gate | 필요한 evidence | Owner | 상태 |
|---|---|---|---|
| SAMSUNG-WAKE-100 | 5개 고정 scenario×20회, permission/Bluetooth/network/reboot/kill, TalkBack/200%/ko-en | user + mobile/OEM reviewer | `PHYSICAL PENDING` |
| ESP32-C6-COEXISTENCE-100 | radio, boot/reset, rail, broker TLS와 BLE coexistence | firmware/hardware owner | `PHYSICAL PENDING` |
| GPIO23-RELAY-100 | boot/idle/active/High-Z, 1초 hold/3초 cooldown, actual door effect | installer + separate safety reviewer | `PHYSICAL PENDING` |
| AJ-SR04T-BOUNDARY-100 | GPIO10/11, ECHO protection, 20cm boundary/50cm threshold/timeout | sensor/safety owner | `PHYSICAL PENDING` |
| RELAY-G0/G1/G2 | unauthorized/replay/reset/unknown effect에서 relay fail-closed | security + physical owner | `PHYSICAL PENDING` |
| OTA-G1..G4 | app install health/fallback, inactive-slot boot, continuous health, power/network cut, rollback/local recovery | release/mobile/firmware owners | `PHYSICAL PENDING` |
| OPERATOR-DRILLS | mTLS/RBAC/revoke/force-open/reconcile/TLS rotation/backup/privacy/incident | ops/security/privacy owners | `OPS PENDING` |
| CANARY-STOP-ROLLBACK | exact artifact/cohort, stop rule, rollback and different reviewer/risk owner | release authorization owner | `PRODUCTION PENDING` |

## 6. 다음 반복의 종료 규칙

1. `python -m unittest tests.test_manual_contract`, full root와 Quick를 실행해 #52 source/endpoints/fixture/link를 고정한다.
2. NAS operator가 exact main/image digest로 검증 배포하고 `/live`·`/ready`·metrics, migration backup, support/retention negative path를 기록한다.
3. 사용자가 Issue #54 schema로 physical evidence를 수행하고 독립 reviewer가 raw capture digest를 확인한다.
4. 모든 blocker가 code/test 또는 named owner evidence로 닫힌 뒤 신규 actor가 매뉴얼만 보고 동일 output을 재현한다.
5. `BLOCKED`, `OPS PENDING`, `PHYSICAL PENDING`, `PRODUCTION PENDING`이 하나라도 남으면 Issue #53과 Epic #48을 완료로 표시하지 않는다.
