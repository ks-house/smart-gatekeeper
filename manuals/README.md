# Smart Gatekeeper 매뉴얼 세트

문서 버전: **0.3.0-rc.1**<br>
제품 기준: `e42d1f417a555b17d7476522aa48f7e4d72306b7`<br>
작성일: 2026-08-09<br>
상태: **NAS 검증 배포 준비 문서 — 운영·물리·production 인수는 아직 미완료**

이 문서 세트는 일반 사용자, 관리자, 설치자와 지원 담당자가 같은 상태와 증거를 사용하도록 만든 실행 계약이다. 현재 저장소에서 재현한 host/software 결과와 아직 수행하지 않은 Samsung/OEM, ESP32-C6, relay, bootloader, OTA, 운영자, canary 및 production 결과를 분리한다.

## 문서 구성

| 문서 | 대상 | 주요 내용 |
|---|---|---|
| [일반 사용자 매뉴얼](general_user_manual_ko.md) | 입주자·일반 사용자 | 첫 실행, 동의·권한, 등록, 자동·수동 출입, 장애 복구, 업데이트, 분실·교체 |
| [관리자 매뉴얼](administrator_manual_ko.md) | 보안 관리자·건물 운영자 | hardened 배포, RBAC, tenant/device/door, force-open, TLS·secret, audit, backup·restore, canary·폐기 |
| [설치·서비스 매뉴얼](installer_service_manual_ko.md) | 설치자·서비스 기술자 | GPIO23, 전원·flyback·level shifting, provisioning, 시운전, OTA 복구, RMA |
| [개인정보 안내](privacy_notice_ko.md) | 사용자·관리자·지원팀 | 수집 목적, 최소화, 동의, 보관·삭제, redacted support |
| [지원·사고 대응 핸드북](support_incident_handbook_ko.md) | 1차 지원·on-call·사고 지휘자 | triage, timeout/retry/escalation, 증거, containment·복구·종료 |
| [제품 역분석·갭 등록부](product_gap_register_v1.md) | 제품·개발·QA·운영 owner | 매뉴얼 walkthrough에서 발견한 구현·운영·물리 gap과 반복 결과 |
| [Hardwareless walkthrough](hardwareless_walkthrough_ko.md) | QA·독립 reviewer | 실기기 없이 확인 가능한 16개 여정과 명시적 NAS·물리 인수 체크리스트 |

기계 판독 가능한 fixture는 [`walkthrough-fixtures-v1.json`](walkthrough-fixtures-v1.json)이며 [`tests/test_manual_contract.py`](../tests/test_manual_contract.py)가 필수 필드, 상태 경계, 링크, 비밀정보 금지와 stale 기준을 검사한다.

## 공통 절차 계약

모든 핵심 절차에는 다음 열이 있어야 한다.

| 필드 | 의미 |
|---|---|
| Actor | 행동 주체와 승인 주체. 위험 작업은 동일 인물로 합치지 않는다. |
| Preconditions | 권한, 전원, 네트워크, Bluetooth, Target/door 상태, exact artifact 등 시작 전 조건 |
| Input | 한 번의 명확한 사용자 행동, API, artifact 또는 계측 입력 |
| Observable output | 화면·HTTP detail·상태·event·물리 출력. 관찰할 수 없으면 성공이 아니다. |
| Code/API owner | 해당 결과를 만드는 실제 코드, API 또는 명시적 owner issue |
| Evidence artifact | exact SHA/digest, redacted event ID, test report, 사진·계측 trace, 승인 기록 |
| Timeout | 응답 또는 효과를 더 기다리지 않고 `unknown/failed`로 전환하는 경계 |
| Bounded retry | 안전하게 반복 가능한 횟수와 같은 idempotency/session을 유지해야 하는지 여부 |
| Escalation | 재시도 소진 후 담당 owner, 전달할 redacted 증거, 금지 행동 |

문서의 시간 값이 코드나 운영 SLO로 검증되지 않았으면 **검증 목표**로 표시한다. 목표 시간을 넘겼다고 성공으로 추정하지 않는다.

## 상태와 증거 경계

- `detecting → authorizing → armed → opening → confirmed`는 서로 다른 상태다. `armed`, MQTT `published`, 다운로드 완료 또는 installer 열림은 `confirmed`가 아니다.
- `confirmed`는 Target 결과가 내구성 있게 기록되고 해당 물리 효과가 관찰된 경우만 사용한다. 이번 문서 작업은 물리 효과를 만들거나 관찰하지 않았다.
- `unknown`, `duplicate_uncertain`, `RECONCILIATION_REQUIRED`, `EFFECT_UNKNOWN`은 성공이 아니며 자동 재시도하지 않는다.
- Host/unit tests와 CI는 software evidence다. NAS 검증 배포는 사용자의 실기기 시험을 위한 staging이며 production 승인이 아니다. Samsung/One UI, radio, GPIO23 relay, 센서, dual-slot boot, power-cut rollback, operator drill과 production 승인을 대체하지 않는다.
- public RFC 8032 test key와 `.invalid` URL로 만든 artifact는 canary 검증용이며 production 배포물이 아니다.

## 매뉴얼 갱신 및 역분석 규칙

1. exact 제품 commit과 artifact digest를 고정한다.
2. 신규 actor가 매뉴얼만 보고 fixture를 수행한다.
3. 숨은 전제, 모호한 성공, 막힌 복구, 화면과 state 불일치를 gap으로 등록한다.
4. 안전하고 작은 결함은 코드·test·문서를 함께 수정한다. 운영·실기기 권한이 필요한 결함은 owner와 증거 조건을 정확히 남긴다.
5. 동일 여정을 독립 reviewer가 반복한다.
6. 갭이 하나라도 `BLOCKED`, `OPS PENDING`, `PHYSICAL PENDING`이면 문서 세트를 release-ready나 production-ready로 승격하지 않는다.

## 언어·접근성 기준

한국어를 기준으로 하고 상태 wire name과 핵심 영어 용어를 함께 유지한다. 앱은 OS locale `ko`/`en`을 선언하지만 일부 첫 실행·복구 화면은 혼합 언어이므로 완전한 영문 UX를 주장하지 않는다. TalkBack, 키보드 포커스, 200% 글자 크기, 작은 화면과 가로 화면은 widget/host evidence와 Samsung physical evidence를 분리한다.
