# Smart Gatekeeper 매뉴얼 기준선 / Manuals baseline

문서 버전: **0.1.2-contract-loop**<br>
기준 커밋: `cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f`<br>
작성일: 2026-08-09<br>
상태: **문서 초안 / 제품·실기기 인수 대기 (draft; product and physical acceptance pending)**

이 디렉터리는 이 커밋에서 확인 가능한 동작과 확인되지 않은 동작을 분리한 한국어 우선(Korean-first) 운영 매뉴얼 기준선이다. 매뉴얼은 제품이 제공하지 않는 기능을 절차 문장으로 보완하지 않으며, `PENDING` 또는 `BLOCKED` 표시는 실제 제품·테스트·실기기 증거가 생길 때까지 유지한다.

## 문서 묶음

| 문서 | 대상 | 범위 |
|---|---|---|
| [일반 사용자 매뉴얼](general_user_manual_ko.md) | 입주자/일반 사용자 (resident/end user) | 설치, 승인, 자동·수동 출입, 상태, 장애, 업데이트, 분실·회수, 지원 |
| [관리자 매뉴얼](administrator_manual_ko.md) | 관리자 (administrator) | RBAC/tenant/device/door, 승인·회수, force-open, 모니터링, 백업·복원, OTA 운영 |
| [설치·서비스 매뉴얼](installer_service_manual_ko.md) | 설치자/서비스 기술자 (installer/service) | 배선, GPIO3, 전원·보호, 프로비저닝, 시운전, 유지보수·RMA |
| [개인정보 안내](privacy_notice_ko.md) | 모든 사용자·운영자 (all users/operators) | 수집·이용, 보관·삭제, 최소화, 지원 내보내기, 사고 통지 |
| [지원·사고 핸드북](support_incident_handbook_ko.md) | 지원팀/사고 대응자 (support/incident) | 분류, 증거 수집, 복구, 에스컬레이션, 사후 분석 |
| [제품 역분석·갭 등록부](product_gap_register_v1.md) | 제품·개발·테스트 소유자 | 매뉴얼 walkthrough에서 발견한 결함 후보, 테스트 계약, 반복 루프 |

## 공통 단계 증거 필드

모든 사용자 여정은 아래 필드를 반드시 채운다. `observable output`은 화면 문구만으로 성공을 선언하지 않고, 실제 state/event/physical event가 확인되는 경우에만 성공으로 기록한다.

| 필드 | 작성 규칙 |
|---|---|
| Actor | 해당 단계의 책임 주체와 대체 주체 |
| Preconditions | 권한, 네트워크, Bluetooth, 전원, target state, 버전 등 시작 조건 |
| Input | 사용자가 누르는 동작, 명령, 파일, 식별자 또는 증거 |
| Observable output | 사용자에게 보이는 상태·이유·이벤트·물리 출력; 미확인은 `PENDING` |
| Code/API owner | 실제 소유 파일·모듈·API; 없는 기능은 `GAP(#)` |
| Evidence artifact | 테스트명, 로그/event ID, artifact digest, 사진/측정값, reviewer와 만료일; 없으면 `NONE` |

## 상태·증거 경계

- 로컬 소프트웨어 테스트, hosted CI, 운영 인프라, Samsung/OEM·ESP32-C6 실기기, 생산 승인을 각각 별도 증거로 기록한다.
- Synthetic ADB, host test, 문서 walkthrough는 Samsung/OEM 또는 relay/bootloader/OTA 물리 인수를 대체하지 않는다.
- #49 관리자 인증/RBAC, #50 Target 명령·TLS·OTA/rollback, #51 모바일 wake/GATT/updater/OEM, #52 observability/privacy/backup·restore가 제공하지 않는 절차는 `PENDING`으로 남긴다.
- force-open은 인증된 역할·사유·재인증·이중 승인·감사 이벤트가 확인되기 전까지 비상 절차일 뿐, 운영 성공 절차가 아니다.

## 버전 및 갱신 규칙

1. 제품/API/state/evidence가 바뀌면 이 묶음의 버전을 올리고 기준 커밋을 갱신한다.
2. 갭 등록부의 항목을 코드와 회귀 테스트가 닫은 뒤, 독립 walkthrough를 다시 수행한다.
3. 해결되지 않은 P0/P1·physical 항목이 하나라도 있으면 문서 상태를 `draft/pending`으로 유지하고 issue #53 완료를 선언하지 않는다.
4. 한국어와 English 용어를 함께 유지한다. 번역 변경은 의미·상태·오류 코드의 변경으로 간주하지 않는다.

## 반복 루프

`manual walkthrough → product/test gap → code/API change → regression evidence → independent walkthrough → manual revision` 순서를 #49→#50→#51→#52의 의존성에 따라 반복한다. 매 회차에는 정확한 commit/artifact, reviewer, 남은 P0/P1 및 physical gate를 기록한다.
