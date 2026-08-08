# 개인정보 안내 / Privacy notice

문서 버전: **0.1.0-baseline** · 기준 커밋: `b246aff9698ccbcbcd864f99aab63654cce2cc78`<br>
대상: 사용자·관리자·지원팀 (users/operators/support) · 상태: **법무·운영 데이터 검증 pending**

이 안내는 현재 저장소의 데이터 흐름을 기준으로 한 문서 초안이다. 실제 수집·보관·삭제 기간, 법적 근거, 처리자 목록은 운영 배포 전에 조직의 privacy owner와 관할 법률에 따라 확정해야 한다.

## 데이터 최소화 / Data minimization

| 데이터 분류 | 목적 | 기본 표시/전송 원칙 | 보관·삭제 | Owner / evidence |
|---|---|---|---|---|
| 계정·tenant·unit 정보 | 승인·출입 권한 | operator UI와 support bundle에서 최소화·opaque화 | retention owner가 기간 확정 후 삭제 | #52 privacy inventory **PENDING** |
| device/target reference | 올바른 door binding | raw MAC 대신 opaque reference; URL/log에 원본 금지 | revoke/decommission policy | #49/#52 **PENDING** |
| access/update/reset event | 보안·장애 분석 | session/boot/event ID와 artifact digest만 지원 내보내기에 포함 | immutable audit와 retention policy 필요 | `observability/`, #52 **PENDING** |
| credential/proof/secret | 인증 | 화면·일반 로그·지원 export에 절대 노출하지 않음 | rotation/revoke 후 secure deletion policy | #49/#50 security review **PENDING** |
| support export | 사용자 동의 기반 지원 | redacted, time-bounded, access audited | ticket 종료 후 삭제 시각 기록 | support owner **PENDING** |

## 사용자 여정과 증거 필드

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 사용자 | privacy notice를 읽을 수 있음 | 동의/거부 또는 철회 선택 | 선택 상태·적용 범위·다음 행동을 명확히 표시 | app/WebView **GAP-52-01** | consent test **PENDING** |
| 사용자 | 본인 확인 절차 | access/correction/deletion 요청 | 접수 ID, 보존 예외, 완료/거절 사유 표시 | backend privacy API **GAP** | request/fulfillment audit **PENDING** |
| 관리자 | 최소 권한과 목적 제한 | retention/deletion job 실행 | 삭제 대상·보존 예외·결과 건수만 표시 | #52 data lifecycle | deletion verification **PENDING** |
| 지원팀 | 사용자 동의와 ticket scope | redacted bundle 생성 | token/secret/raw identity가 제거된 파일과 expiry 표시 | support tooling **GAP-52-01** | redaction mutation test **PENDING** |
| 사고 대응자 | incident authority, legal/privacy owner | breach/overexposure 신고 | containment, affected scope, notice decision과 audit | #52 incident process | incident record **PENDING** |

## 지원 export redaction checklist

포함: 시간대, app/firmware/backend version, opaque target/session/boot/event ID, reason code, state transition, artifact digest, 재현 단계.<br>
삭제: 비밀번호, API/MQTT token, private key, proof/signature/nonce, 원본 tenant/unit/name, raw MAC, 주소, 원본 URL query, 주민 식별 정보.

## 오프라인·OEM·업데이트와 개인정보

offline 상태의 local queue나 OEM retry가 발생해도 secret을 평문 파일·로그에 저장하지 않는다. update/rollback 시 기존 credential과 user data를 보존해야 하며, 실패 진단을 위해 무제한 데이터를 수집하지 않는다. 실제 retention, encrypted storage, rollback preservation은 #49–#52와 실기기/운영 증거가 생기기 전까지 **PENDING**이다.

## 문의

사용자는 support ticket에 문서의 redaction 규칙을 지켜 접수한다. privacy request와 access incident를 같은 공개 채널에 원문으로 올리지 않는다. 조직의 privacy contact, 처리 기간, 법적 고지는 운영 배포본에서 채워야 한다.
