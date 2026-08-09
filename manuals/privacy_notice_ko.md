# 개인정보 안내 / Privacy notice

문서 버전: **0.3.0-rc.1** · 제품 기준: `e42d1f417a555b17d7476522aa48f7e4d72306b7`<br>
대상: 사용자·관리자·지원팀 · 상태: **기술적 최소화 반영; 법무 고지·운영 보관/삭제·처리자 검증 pending**

이 문서는 현재 제품의 기술 경계를 설명한다. 개인정보처리자 이름, 연락처, 관할 법적 근거, 보관 기간, 처리자/국외 이전 목록과 권리 처리 기한은 production 배포 전에 privacy/legal owner가 채워 승인해야 한다. 빈 placeholder 상태로 사용자 동의를 받거나 production을 시작하지 않는다.

## 1. 첫 실행 동의와 선택

첫 실행 화면은 background BLE 출입 감지를 위해 위치·근처 기기, background location과 배터리 최적화 예외가 필요한 이유를 권한 요청 전에 알린다. `나중에 설정`을 선택하면 OS 권한 요청은 발생하지 않고 manual recovery, verified update와 redacted diagnostics로 이동한다. 이 동의는 제품 privacy notice 전체에 대한 법적 동의를 대신하지 않는다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 사용자 | notice를 읽을 수 있음 | 동의 또는 나중에 설정 | versioned consent 또는 defer; 동의 전 system request 0회 | `BackgroundConsentStore`, disclosure screen | consent/order widget tests | 선택 제한 없음 | 저장 실패 1회 | `BACKGROUND_CONSENT_UNAVAILABLE`이면 support; 앱 data 삭제 금지 |
| 사용자 | consent 후 Android prompt | 필요한 권한만 allow/deny | 누락 항목, `Ready/Degraded/Blocked`, recovery path | background setup | permission host tests; OEM **PENDING** | OS prompt 30초 목표 | 설정 복귀 1회 | mobile/privacy owner에 OS/build/reason 전달 |
| 사용자 | production privacy contact와 identity verification | 열람·정정·삭제·철회 요청 | ticket ID, scope, legal hold/거절 reason, 완료 시각 | #52 privacy workflow | fulfillment audit **OPS PENDING** | 법정/내부 SLA 미정 | 동일 ticket 1회 | privacy/legal owner |

## 2. 데이터 분류와 최소화

| 데이터 | 목적 | 앱·지원 표시 | 보관·삭제 | Owner / evidence |
|---|---|---|---|---|
| tenant/user/unit 참조 | 승인·권한 scope | 일반 log/export에서 HMAC opaque ID; 이름·unit 원문 금지 | 기술적 삭제 범위 30–3650일, 실제 기간은 법무 승인 전 미정 | privacy/data owner **OPS PENDING** |
| Target/device/door 참조 | 올바른 binding | raw MAC 대신 opaque target/session/boot/event ID | revoke/decommission 후 검증 삭제 | #49/#50 host controls; ops pending |
| access/command/update/reset event | 안전·보안·장애 분석 | state/reason, causal IDs, artifact digest | audit/incident 보존 기간 미정 | event schema + #52 storage |
| credential, proof, nonce, token, private key | 인증·replay 방지 | UI, 일반 log, support export에 포함 금지 | rotate/revoke 후 secure deletion | Keystore/NVS/backend security; physical/ops pending |
| app diagnostic | 사용자가 동의한 지원 | bounded exception, query 제거, identifier redaction | ticket expiry 후 삭제 | `AppErrorLogger` sink tests present |
| 관리자 audit | 책임 추적 | stable actor, scope, action, object ref, hashed idempotency만 | 법적/보안 보존 기간 미정 | migration 003 immutable host test |

모바일 logger는 tenant/unit/device, Bluetooth address, credential, token/API key/password, URL/query, proof와 unbounded exception을 plain/error/debug/UI/IPC sink에서 redaction한다. Backend root logging filter와 support export도 MAC, secret assignment, URL query와 중첩 필드를 제거하고 생산자는 fixed code와 opaque reference를 사용한다. 이는 NAS reverse proxy·broker·ticket system의 실제 설정과 법적 적합성까지 증명하지 않는다.

## 3. Redacted support bundle

### 포함

- ticket ID, offset이 있는 시각과 timezone
- app/firmware/backend version, exact artifact SHA-256
- opaque target/session/boot/event/approval ID
- 화면 state, reason, 마지막 observable output, 재현 1회
- network class(`online/offline` 정도), Android/OEM/build

### 제거

- password, API/MQTT token, cookie, CSRF, private/signing key
- credential, proof, signature, nonce, raw BLE/MAC
- tenant/unit/name/address/전화번호와 직접 식별자
- 원본 URL과 query, Wi-Fi SSID/password, certificate 원문
- 무제한 stack/exception 또는 다른 사용자의 event

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 사용자 | ticket과 명시적 export 동의 | diagnostics 화면에서 필요한 항목 검토 | redacted preview와 범위; 자동 upload 없음 | Flutter diagnostics/logger | redaction tests present; export UX **PENDING** | 30초 목표 | 생성 1회 | 의심 값이 보이면 전송 중지, privacy owner |
| support agent/auditor | current mTLS session, tenant scope, DB에 저장된 `support-diagnostics` consent가 현재·미철회 | `GET /api/v1/admin/privacy/support-export?hours=1..168&limit=1..500`, `X-Support-Consent` | 위조·만료·철회·타 tenant consent는 403; 성공은 opaque consent/tenant ref, redacted records, canonical SHA-256와 audit | `create_support_export`, `support_export_consents` | response digest + `SUPPORT_EXPORT_CREATED` audit **OPS PENDING** | HTTP 15초 목표 | 동일 범위 read 1회 | 403/503이면 privacy/DB owner; raw DB/log로 우회 금지 |
| privacy owner/tenant admin | 승인된 법적 보관표, current mTLS/CSRF/reauth, 새 idempotency key | `POST /api/v1/admin/privacy/delete` with `sgk-retention-v1`, `before_days=30..3650` | tenant access records만 삭제; 동일 요청은 `already_completed`, actor/payload가 다른 key 재사용은 409 | `delete_expired_privacy_data`, migration 007 | job request hash, deleted count, immutable audit **OPS PENDING** | HTTP 15초 목표 | 같은 request/key 1회 | 409/503이면 자동 새 key 발급 금지; privacy/data owner가 state 확인 |
| privacy owner | ticket 종료/expiry | ticket export deletion verification | deleted count, exception/legal hold, reviewer | 승인된 ticket lifecycle | deletion report **OPS PENDING** | 법무 승인 기한 | 0회 자동 | data owner/legal owner |

`before_days` 범위는 software의 안전 경계이지 법적 기본 보관 기간이 아니다. 개인정보처리자와 privacy/legal owner가 관할별 일정을 승인하기 전 deletion API를 정기 job으로 연결하지 않는다. Support consent 원문은 응답·audit에 기록하지 않고 SHA-256 lookup과 HMAC opaque reference로만 연결하며, ticket 종료 시 export 복사본을 승인된 절차로 삭제한다.

## 4. Offline·update·rollback·분실

- Offline queue나 OEM retry 중 secret을 평문 파일·log에 저장하지 않는다.
- 앱 update는 기존 credential과 app data를 pre-install 실패 동안 보존하고 replacement identity가 일치하기 전 pending health를 지우지 않는다.
- Target OTA는 credential/ACL/NVS 보존과 rollback을 host contract로 요구하지만 power-loss·실기기 증거는 pending이다.
- 휴대폰 분실 시 공개 채널에 개인정보를 게시하지 않고 credential revoke ticket을 만든다. Backend revoke와 Target physical denial을 분리 확인한다.
- RMA/폐기는 legal hold와 credential revoke 뒤 secure erase 또는 quarantine 증거를 남긴다.

## 5. 보안·개인정보 사고

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| 신고자/support | 노출 의심, public channel 미사용 | ticket과 최소 증거 | severity, privacy/security owner, containment 대기 | support process #52 | redacted ticket **OPS PENDING** | 15분 acknowledge 목표 | 동일 ticket 1회 | privacy/security on-call |
| incident commander | authority, legal/privacy contact | access revoke·export hold·scope preservation | `CONTAINED` 또는 `RECOVERY_UNVERIFIED`, decision log | #52 incident workflow | immutable incident record **OPS PENDING** | 15분 containment 목표 | 승인 containment 1회 | 법무·security·data owner |
| privacy/legal owner | affected scope와 관할 확인 | notice/권리 대응 결정 | 근거, 대상, 기한, reviewer | organization policy | signed decision **PRODUCTION PENDING** | 법정 기한 미정 | 0회 자동 | production authorization owner |

## 6. Production 전 필수 기입 항목

개인정보처리자/담당자, 연락처, 목적별 법적 근거, 분류별 보관 기간, backup 보관과 삭제, 위탁 처리자, 위치/국외 이전, 사용자 권리와 이의제기 기한, 미성년자/공동주택 정책, breach notice 기한을 privacy/legal owner가 승인해야 한다. `GAP-52-05`가 닫히기 전 이 문서는 법적 개인정보처리방침이 아니며 production 배포를 승인하지 않는다.
