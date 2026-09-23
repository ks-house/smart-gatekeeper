---
title: September 13 field failure and automatic diagnostic upload recovery plan
type: proposal
project: smart-gatekeeper
status: deployed-field-acceptance-pending
updated: 2026-09-13
source_of_truth: true
applies_to:
  - gatekeeper_app
  - target
  - backend
  - diagnostic-read-client
---

# 9월 13일 현장 실패 기반 수정 계획

사용자가 계획 전체 구현·배포와 병렬 작업을 승인했다. 아래 1–9절은 설치494/앱44601에서 분석한 근거와 승인된 계획이며, 현재 반영 상태는 이 절에 따로 기록한다. 기존 자동 수집과 진단 API를 확장하며 사용자에게 로그 복사나 반복 방문을 기본 해결 절차로 요구하지 않는다.

## 0. 구현 및 배포 추적

- Backend: schema018의 사건 시각 색인, late-evidence cutoff/휴대폰별 독립 cursor, 발생·capture·수신·신선도·자료 공백 표시, optional 새 모바일/Target 진단 필드, 권한 확인된 진단 ACK의 최신 signed Target baseline을 구현했다. 구앱 보고서/구 API 의미와 immutable ACK identity를 보존한다. 보호 입력2개의 정확한 승인 후 main7afb9f7을22:25:32 KST에 배포했다. NAS 적용·상태 evidence와 public ready12개 검사, 늦게 도착한1017–1020 조회 및 N-1 보고서1049 저장을 확인했다.
- Android: 성공 최대4묶음/30초 drain과 RUNNING predecessor 뒤 단일 continuation, v1 장기 backoff 이관, 실제 실패의 제한 backoff/Retry-After,401/403 보류와400/413/422 최대4건 격리, generation/늦은 ACK 방어, 손실별 카운터를 구현했다. 각 새 묶음은 현재 health snapshot과 순서대로 배출하는 과거 사건 최대64개를 함께 보내며 재시도 중인 bytes는 바꾸지 않는다.
- 앱: 과거 ACK를 현재 성공으로 표시하지 않는다. 수동 요청 전후/실패 사건 수집,10분 incident ref, 미전송·권한·재시도·유실·서버 저장 상태 및 현장 marker와 새 보고서 ACK/Target baseline 준비 확인을 구분한다. BLE foreground 복구 오류는 updater/UI에 전파하지 않는다.
- BLE: fresh matching packet과 등록/콜백을 분리하고, 필터/힌트/예약 카운터·30초 수신 확인을 추가했다. fresh 광고에 hint만 없을 때 분당 최대1회 V2 probe를 허용하되 malformed hint, stale packet, pending/uncertain proof, 기존 TARGET_BUSY/owner guard는 유지한다. 서비스 탐색 시작/콜백/서비스·특성 누락을 구분한다.
- Target: 인증 허용과 자동 pulse 잠금 분리, 차단 중 ARM 최대5초·미해제 자동 시도 후30초 quiet, 공통 초음파 cadence/분류/median 및 거절 계측, 광고 requested/applied 상태와 bounded 재적용을 구현했다. no-echo/시간 경과로 pulse 잠금을 해제하지 않으며 기존 clear3회·임계값·핀·V2 proof·서명 V1/NVS·MQTT 비동기·dual-slot OTA를 유지한다.
- 로컬 검증: personal firmware build PASS(RAM97,400/327,680B, flash1,855,872/7,340,032B); Target 호스트193 tests PASS; Android133 tests PASS(실제 WorkManager2.9.1/Robolectric migration·late producer 포함); Flutter115 tests/analyzer PASS; root409 tests OK(1 platform skip), Backend310 OK(4 integration skip) 및 별도 실제 MariaDB017→018/N-1 writer PASS. 읽기 전용 MQTT collector는4883/TLS 실제 구독·4채널 관측을 확인했다.
- 앱 배포: main5ca450a/44801(`1.0.0-g5ca450a`) 게시 완료. 기본·예비 HTTPS 경로 모두55,659,673B/SHA256 `270804ce20274a7a4320f692c6c16bf9fd4561c5a297b540a3f74ba1ec21bf38` 일치. 휴대폰 설치는 사용자 확인이 필요하며 아직 미확인이다.
- Target 배포/물리 경계:497의 health heap 실패/494 복구 뒤, 메모리 수명 수정 main7959962/498을 설치했다. boot904/23:27:08 KST VALID,23:30:44 uptime253초·IDLE·relay OFF·현재 버전 HTTPS 검사/error0·인증 준비/광고 반영을 Backend health13723으로 확인했다. 자세한 근거는 [OTA runbook §12](ota_operations_runbook.md#12-2026-09-13-497-health-rejection-and-preserved-recovery)에 기록한다. 기존 T1=18:21:04/boot901을 유지하며 OTA·rollback 부팅은 전원 원인과 분리한다. 센서 전기/RF와 실제 문 동작이 고쳐졌다고 소프트웨어·설치 시험만으로 선언하지 않는다.

## 1. 이번에 확인된 사실과 원인 판정

시간은 별도 표기가 없으면 2026-09-13 KST이다. Target firmware는 `2.1.494+main.g87b9754`, 보고 앱은 `44601 / 1.0.0-g87b9754`, Backend는 `8e4bd56`이다. 현재 checkout `2a51c20`과 설치 기준의 관련 Android 업로드·BLE wake·홈 화면·Target main/rearm 소스, Backend 진단 조회 소스에 차이가 없음을 Git diff로 확인했다.

| 근거 | 확인 내용 | 판정 및 한계 |
|---|---|---|
| 현장 고정 구간 20:51:55.080479–20:57:38.312036 | health 12행, access 1행, 두 조회 cursor null. 같은 boot901, MQTT connect4, BLE watchdog1 유지 | 이 구간의 새 재부팅이나 MQTT 단절이 주원인이라는 증거 없음. 전원 장기 안정성 합격은 별도 |
| Target 인증 누적 카운터 | accepted connections 7→7, challenges/proofs/ARMED 각5→5. 수동 전 IDLE | **이번에는 새 Target 인증 연결·ARMED 진입 자체가 관측되지 않음**. 앞선 ARMED 후 timeout5건과 다른 실패 경로 |
| 센서 표본 | 20:54:31.260, 20:56:02.817 OCCUPIED, rearm blocked=false | 센서가 전혀 응답하지 않았다는 설명은 맞지 않음. raw OCCUPIED는 ARMED median 통과나 사람 식별 증거가 아님 |
| 수동 개방 | event9767, boot901/sequence30, `ACCESS_SIGNED_MANUAL_COMPLETED`, 20:56:42.653 수신 | 사용자 수동 개방 보고와 일치. 독립 door-contact 관측은 없음 |
| 수동 개방 이후 | rearm blocked=true, 20:57:13 FAULT/blocked=true | 이번 실패의 최초 원인은 아니지만 **다음 자동 인증을 막을 수 있는 별도 경로** |
| 뒤늦게 도착한 앱 보고서 | report1017–1020, 20:59:43–21:01:13 수신. 새 보고서 생성→수신 약0.4–0.5초 | 자동 업로드가 계속 완전 정지한 것은 아님. 수신 재개 자체가 기존 누락 복구 완료를 뜻하지 않음 |
| 새 보고서의 BLE 기록 | 마지막 matching packet 19:54:12.936. 20:34:36, 20:49:36 재등록 accepted. 테스트 시간 새 wake/session 없음 | 재등록 성공은 수신 성공이 아님. 휴대폰 matching scan 단계까지 새 증거가 없음. Target RF·필터·Android scanner 중 물리 원인은 아직 분리되지 않음 |
| 보고서 신선도·유실 | report1016은 11:59:39 생성→16:59:40 수신. cumulative dropped1027→새 보고서1668. 오래된 lifecycle 묶음이 최신 capture와 함께 실림 | 실제 전송 대기와 기록 손실이 있음. 증가641건 전체를 이번 테스트의 유실이라고 계산하지 않음 |

조회 근거: 기존 읽기 토큰의 `/api/v1/diagnostics/health-history`, `/access-events`, `/bundles`, `/bundles/{id}`. 현장 구간 UTC는 `2026-09-13T11:51:55.080479Z`–`2026-09-13T11:57:38.312036Z`, 새 보고서는 21:02 KST 조회 시 확인했다. 원시 키·credential·주소·서명은 문서에 저장하지 않는다. 휴대폰 간 사건을 시간만으로 동일 사용자에게 귀속하지 않는다.

### 확정 코드 결함: 성공한 업로드를 실패 재시도로 연결

[NativeDiagnosticWorkers.kt](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/NativeDiagnosticWorkers.kt)는 unique upload `KEEP` + 30초 exponential backoff를 사용한다. 서버 ACK 성공 후 다음 보고서를 저장하고, pending이 남으면 **`Result.retry()`**를 반환한다. 따라서 성공한 다음 묶음을 처리할 때도 같은 작업의 실패 시도 횟수와 대기 시간이 누적될 수 있다. 대기 중 새 enqueue는 `KEEP` 때문에 즉시 실행 작업으로 교체되지 않는다.

실제 의존성 WorkManager **2.9.1**의 공식 sources JAR에서 `WorkSpec`의 지수식과 `MAX_BACKOFF_MILLIS = 5 * 60 * 60 * 1000L`을 확인했다. 30초 설정은 30, 60, 120, 240초 … 최대5시간 대기로 늘어난다. 이는 관측된 5시간 보고서 지연과 일치하는 **유력한 직접 원인**이다. 휴대폰 WorkManager DB의 해당 runAttemptCount는 조회하지 않았으므로 과거 모든 지연을 이 결함 하나로 확정하지 않는다. HTTP 전달이 빨랐던 새 보고서와 과거 긴 대기는 구분한다.

### 확정 조회 한계: 사건 종료 뒤 도착한 자료가 빠짐

[diagnostics_read.py](../backend/app/diagnostics_read.py)의 incidents 조회는 mobile 보고서도 `received_at < until`로 제한하고 전체 최신20건만 가져온다. 현장 종료시각을 `until`로 고정하면 **그 이후 업로드된 당시 기록은 다음에 같은 사건을 조회해도 제외**된다. 최신20건이 한 휴대폰의 반복 보고서이면 다른 휴대폰의 필요한 기록도 밀려날 수 있다. `/bundles` 직접 조회로 보완할 수 있지만 현재 사건 API 자체는 이 공백을 해소하지 못한다.

## 2. 수정 우선순위

| 순서 | 범위 | 실제 수정 목표 |
|---|---|---|
| P0-1 | Android 업로드 Worker/outbox | 성공 묶음은 지연 없이 처리하고 실제 전송 실패에만 backoff 적용. 이미5시간 대기 중인 설치 상태도 회복 |
| P0-2 | Backend·PC 사건 조회 | 발생 구간과 증거 수신 마감을 분리하고 늦은 업로드·가족별 기록·누락 범위를 조회 가능하게 함 |
| P0-3 | 진단 UI·자동 사건 수집 | 오래된 ACK를 현재 업로드 완료로 보이지 않게 함. 수동 개방·인증 실패 시 자동으로 주변 기록 보존·전송 |
| P0-4 | Android wake→GATT | 재등록 accepted와 실제 수신을 분리. 필터/ready hint/owner/dispatch별 증거와 제한된 복구로 무반응 경로 개선 |
| P1-1 | Target 재인증/재개방 정책 | 수동 pulse 이후 무기한 인증 억제와 같은 사람에게 반복 pulse하는 문제를 분리하여 수정 |
| P1-2 | 초음파 진단·판정 | timeout/범위 밖/median 탈락/rearm 차단을 분리. 인증 후 열리지 않는 앞선5세션도 함께 해결 대상으로 유지 |
| P1-3 | Target 광고·관측 도구 | 광고 설정 성공/실패·실제 hint 버전·공백과 MQTT 관측의 유실을 구분 |
| 병행 | 전원·OTA·회귀 | T1 전원 관측 유지, 출입 경로 비동기 보존, mobile/Target OTA 접근·rollback 비회귀 |

## 3. Android 자동 업로드 수정

대상: [NativeDiagnostics.kt](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/NativeDiagnostics.kt), [NativeDiagnosticWorkers.kt](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/NativeDiagnosticWorkers.kt), [NativeDiagnosticReport.kt](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/NativeDiagnosticReport.kt), [NativeDiagnosticsTest.kt](../gatekeeper_app/android/app/src/test/kotlin/com/kshouse/gatekeeper_app/gattworker/NativeDiagnosticsTest.kt).

- 한 Worker에서 **성공한 묶음을 제한된 수·시간 안에 연속 drain**한다. 예산 종료 뒤 잔량은 새 continuation으로 넘기고 성공분 때문에 retry attempt가 증가하지 않도록 한다. 단순히 backoff 상수만 줄이지 않는다.
- unique `KEEP`의 종료 직전 생산자 경쟁을 재현한다. durable pending/generation과 재조정 절차로 마지막 Worker 종료 직후 생성된 작업도 빠지지 않게 한다. 업로더는 하나만 소유하며 capture/ACK 경쟁으로 중복 HTTP를 늘리지 않는다.
- 업데이트 시 기존 `native-diagnostic-upload-v1`의 장기 backoff를 새 스케줄로 이관한다. pending bytes, bundle reference, ACK 경계, 동의 generation을 보존하고 활성 HTTP의 늦은 ACK를 안전하게 처리한다. 앱 재설치·Clear·동의 OFF/ON을 복구 조건으로 요구하지 않는다.
- 네트워크 timeout/5xx/429만 재시도 대상으로 분리하고 `Retry-After`를 반영한다. 401/권한 변경은 자격·설정 재조정, 400/422는 형식 오류로 격리·표시한다. 잘못된 보고서1건이 모든 후속 보고서를 영구 차단하지 않게 하되 삭제나 가짜 ACK로 성공 처리하지 않는다.
- lifecycle sequence, 사건 시간 범위, capture 시각, queue oldest age, enqueue/start/stop/ACK 시각, attempt/next eligible time, 고정 오류 코드를 기록한다. scheduler 예외를 조용히 삼키지 말고 enqueue 실패/저장 실패로 구분한다. 다음 실행 예정시각은 Android의 실행 보장 시각으로 표시하지 않는다.
- 같은 heartbeat/반복 등록 기록은 병합하고 실패·복구·개방 전후 사건의 공간을 우선 보존한다. bounded ring은 유지하되 journal overflow, ring eviction, 보고서 export trim을 별도 집계한다. **현재 건강 snapshot의 신선도와 과거 사건 배출을 분리**하고 두 경로를 하나의 제한된 업로더로 공정하게 전송한다. pending 보고서의 재시도 bytes는 불변으로 유지한다.
- disable/Clear/계정 변경의 기존 동의 generation·늦은 ACK 방어를 보존한다. 수집 오류가 BLE callback, 센서 처리, 서명, 수동 개방을 기다리게 하지 않는다.

현재 단위시험은 ACK·보존·유실 카운트·민감정보 제외를 검사하지만, 실제 Worker의 **성공→다음 묶음→backoff** 연쇄와 WorkManager 경쟁을 검사하지 않는다. 이 부분을 회귀시험의 중심으로 추가한다.

## 4. Backend·PC 조회 및 앱 표시 수정

대상: [mobile_diagnostics.py](../backend/app/mobile_diagnostics.py), [diagnostics_read.py](../backend/app/diagnostics_read.py), [read_diagnostics.py](../scripts/read_diagnostics.py), [smart_key_home_screen.dart](../gatekeeper_app/lib/screens/smart_key_home_screen.dart).

- 사건의 `occurred_since/until`과 증거가 도착한 `evidence_received_until`을 구분하는 호환 확장을 한다. Target의 벽시계가 불확실하면 boot/monotonic/서버수신의 근거를 표시하며 임의 발생시각을 만들지 않는다. 기존 receipt-window API 의미는 바꾸지 않는다.
- mobile opaque reference별 필터·독립 cursor와 event 범위 색인을 추가해 뒤늦은 보고서를 다시 연결한다. Target 사건과 연결되지 않은 wake/dispatch 사건도 조회한다. 제한 초과는 `truncated` 및 다음 cursor로 표시하고 시간만으로 다른 가족의 성공을 합치지 않는다.
- 보고서 생성 시각, 포함 사건의 시작/끝, 서버 수신 시각, 최신 건강 시각을 각각 보여준다. 오래된 실패를 최신 실패로, 방금 수신한 과거 snapshot을 현재 건강으로 표시하지 않는다. clock skew는 별도 불확실성 상태로 둔다.
- 앱의 `진단 업로드 완료`는 과거 ACK 유무만으로 결정하지 않는다. `최근 서버 저장 확인 / 미전송 사건 / 재시도 대기 / 수집 기록 유실 / 관측 오래됨 / 동의 꺼짐`을 분리하고 마지막 서버 저장 시각·대기 나이를 함께 표시한다. capture 이전 `pending_uploads=0`도 당시 snapshot 값임을 명시한다.
- `지금 재시도`는 capture 요청만 보내고 끝내지 않고 실제 drain 예약/실행 결과를 갱신한다. 성공이 없는데 cloud-done 아이콘이 뜨거나 native configure 중을 실제 HTTP 업로드 중으로 표시하는 혼동도 제거한다.
- 보고서 전송은 기존 opt-in과 본인 자격을 유지하고 PC 진단 토큰에 쓰기·개방 권한을 추가하지 않는다. 서버 allowlist를 먼저 확장해 새 앱 보고서가 422로 막히는 재발을 막는다. 기존 보고서/API와 구앱도 계속 읽는다.
- 로컬 Clear와 이미 서버에 저장된 이력의 삭제 범위를 구분해서 안내한다. 이번 계획은 기존 서버 이력 삭제나 새 무제한 raw 로그 수집을 승인하지 않는다.

### 별도 조작 없는 실패 자료 확보

현재 홈의 수동 개방 경로는 활동 기록·health refresh를 수행하지만 명시적인 native incident capture를 호출하지 않는다. 자동 업로드 동의가 있는 경우 다음을 추가한다.

1. 수동 개방 요청 전후, 인증 최종 실패, 재인증 장기 차단, scanner 복구 실패를 bounded 사건 트리거로 삼는다. 수동 개방 자체를 자동 출입 실패로 단정하지 않고 `MANUAL_OPEN_CONTEXT`로 남긴다.
2. 직전 최대10분의 보존된 mobile 증거와 이후 짧은 회복 구간을 묶고 로컬에 먼저 저장한다. 온라인일 때 우선 전송, 오프라인이면 durable queue로 회복 후 전송한다. 이미 유실된 과거 사건을 복구했다고 표시하지 않는다.
3. Backend는 수동 명령/Target 이벤트와 같은 구간의 자료를 재조회해 연결한다. 보고서가 없으면 `진단 자료 미도착`을 독립 사건으로 표시한다. 도착할 수 없는 상태에서 원인을 알아냈다고 하지 않는다.
4. `현장 테스트 표시`는 선택 기능으로 남긴다. 준비 확인은 새 모바일 capture의 **서버 저장**과 fresh Target baseline 확인을 포함한다. marker 생성만으로 수집 준비 완료라고 하지 않는다. 일반 출입은 marker와 무관하게 수집한다.

## 5. BLE 무반응 및 사용성 수정

대상: [BleWakeRegistrar.kt](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/blewake/BleWakeRegistrar.kt), [BleWakeScanReceiver.kt](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/blewake/BleWakeScanReceiver.kt), [BleWakeNativeEntrypoint.kt](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/blewake/BleWakeNativeEntrypoint.kt), [ContinuousPresencePolicy.kt](../gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/blewake/ContinuousPresencePolicy.kt).

### 확정할 진단 경계

- 현재 15분 quiet recovery의 accepted는 OS 등록 성공일 뿐이다. `등록됨`, `최근 matching packet 수신`, `인증 예약/실행`, `Target 연결 수락`을 별도 상태로 표시한다. quiet는 외출도 가능하므로 곧바로 고장 판정을 하지 않는다.
- callback 총량/빈 결과/필터 통과량/ready hint 없음·형식 오류/오래된 batch/Target not ready/중복 세션/owner 대기/실제 enqueue 실패를 고정 코드·카운터·시각으로 남긴다. 원시 MAC/광고 payload는 업로드하지 않는다.
- Target controller active, 휴대폰 RF 수신, GATT 서비스 노출은 서로 다른 증거다. 앱의 오래된 최종 `GATT_DISCONNECTED`를 현재 scanner 중단 원인으로 재활용하지 않는다.

### 기능 개선 및 재현 시험

- 앱 foreground 진입·Bluetooth 재활성화·실제 오류 뒤에 단일 BLE owner로 등록을 조정하고 제한된 수신 확인을 수행한다. 재등록 수락만 반복하며 건강 상태를 갱신하지 않는다. 추가 scanner를 무한 병렬 실행하거나 15분 타이머를 단순히 짧게 바꾸지 않는다.
- 실제 Target 광고의 manufacturer 필터와 scan-response ready hint를 설치 버전별 고정 fixture로 검사한다. FIRST_MATCH/ALL_MATCHES/EXIT 교차, screen-off, Activity 소멸, 프로세스 재생성, 장시간 무수신 후 재접근을 같은 replay 하네스에서 재현한다.
- ready hint는 scan response에만 있고, 현재 hint가 없는 일부 fresh 광고는 인증 예약 전에 버려진다. **fresh matching 광고가 있는데 hint만 빠진 경우** 제한된 V2 GATT 확인 경로를 설계·시험한다. hint는 최적화 신호이지 자격 증명이 아니며, 최종 proof/ACL/FSM 검증과 TARGET_BUSY backoff는 유지한다. 이번 테스트에는 matching packet 자체가 없어 이 보강만으로 해결된다고 주장하지 않는다.
- `GATT_DISCONNECTED`, owner 충돌, service discovery 시작 거부/콜백 실패/서비스 없음, proof 이후 outcome uncertain을 별도로 분류한다. 이미 성공 여부가 불확실한 proof의 무조건 재전송이나 캐시 주소만으로 자동 개방하지 않는다.
- 제한된 recovery 뒤에도 matching packet이 없으면 해당 시도 결과와 기간을 서버에 남긴다. isolated 시험으로 광고/RF, OS registration, 앱 dispatch 중 처음 실패하는 경계를 확정하고 해당 구현을 고친다. 기존 foreground service/native owner 활용은 이 재현 결과에 따라 선택하며 Flutter 화면 유지에 의존하는 임시 해결책을 기본으로 삼지 않는다.

## 6. 재인증 차단과 초음파 경로

대상: [PassageRearmPolicy.h](../include/PassageRearmPolicy.h), [main.cpp](../src/main.cpp), [UltrasonicSensor.cpp](../src/UltrasonicSensor.cpp), [SensorSessionDiagnostics.h](../include/SensorSessionDiagnostics.h).

### 수동 개방 후 다음 인증 차단

현재 모든 relay ON이 `notePulse()`를 호출한다. 해제는 threshold+100mm보다 먼 유효 측정3회이며, no-echo는 해제하지 않는다. 동시에 ready 광고가 `!passageRearm.blocked()`를 요구하므로 **수동 개방 후 no-echo가 지속되면 다음 인증 안내도 계속 막힐 수 있다**.

- 마지막 pulse 출처, blocked 시작/경과, clear 누적, 현재 ready 차단 이유를 기록한다.
- **인증 준비/갱신 허용**과 **같은 점유 구간의 자동 pulse 재실행 금지**를 분리한다. fresh V2 proof를 받을 수 있는 시점과 센서로 재개방할 수 있는 시점을 다른 상태로 정의한다. 짧은 유효기간·기존 cooldown·단일 세션/owner를 유지해 반복 GATT가 MQTT/OTA를 굶기지 않게 한다.
- 수동 pulse 후, 센서 pulse 후, 사람이 계속 있음, 떠났다 재접근, 다른 사람이 연속 접근, 영구 no-echo를 가짜 시계/센서로 시험한다. 계속 머무는 경우 무의미한 재인증 반복이나 무기한 잘못된 ‘다음 인증 가능’ 안내가 생기지 않게 한다.
- no-echo를 clear로 간주하거나 일정 시간이 지났다는 이유만으로 자동 pulse 차단을 해제하지 않는다. 장애 상태에서 안전한 재개방 조건을 증명할 수 없으면 수동 경로를 유지하고 `센서 이탈 확인 불가`를 명시한다. 물리 입력의 의미 변경이 필요한 정책은 별도 판단 사항으로 남긴다.

### 센서 진단과 판정

- `FAULT`로 합쳐지는 `NO_ECHO`, `OUT_OF_RANGE`, 유효 near/clear, 연속 무효를 분리한다. 측정하지 않은 상태도 따로 표시하며 no-echo만으로 하드웨어 고장을 선언하지 않는다.
- IDLE/COOLDOWN raw 측정의 카운터·마지막 유효값·측정 시각을 추가한다. 현재 IDLE에서 raw OCCUPIED인데 telemetry `distance_mm=9990`이 나오는 것은 main의 별도 기본값 경로이므로, 유효성·sample age가 있는 표현으로 수정한다. 새 의미는 호환 필드로 제공한다.
- ARMED는 raw/median/센서 trigger 후보/rearm reject/FSM reject를 분리하고 최대·연속 유효 횟수와 요약된 전이만 저장한다. 현재 수집은 ARMED 중심이므로 IDLE 관측과 같은 카운터로 오해하지 않게 한다.
- 진단 주기와 trigger 간격을 상태와 무관하게 명시적으로 제한한다. 현재 blocked 경로는 IDLE에서도 매 loop 측정하므로 무제한 재측정·30ms pulseIn 누적이 제어/통신/OTA에 미치는 영향을 시험한다. 센서 사양과 실제 주기 측정 없이 원인이라고 단정하지 않는다.
- 앞선 boot901 ARM_TIMEOUT5세션과 현장 IDLE 무반응을 별도 fixture로 유지한다. threshold/median/window는 기록된 qualification 탈락을 재현한 뒤 필요한 것만 수정한다. 사용자의 거리·체류 탓이라는 가정을 넣지 않는다.

## 7. 광고·독립 관측·전원 및 OTA

- [GattServer.cpp](../src/GattServer.cpp)의 `setPresenceReady()`는 scan-response 적용 실패 시 반환만 한다. 요청한 ready/epoch와 실제 적용된 값, 실패 횟수/마지막 결과, 광고 stop/start 이유·공백을 기록하고 연결/OTA 상태를 존중하는 bounded 복구를 넣는다. 광고 active만으로 payload 최신성이나 RF 정상으로 판정하지 않는다.
- PC MQTT observer는 allowlist한 상태/변화만 기록하고 반복 availability는 병합한다. 제한 크기 로컬 JSONL과 수집 시작/끝·retained 여부·재연결·누락·API cursor를 보존해 터미널 출력 잘림을 분석 자료 유실로 이어지지 않게 한다. 기존 읽기 권한·TLS와 정확한 Target namespace를 유지하며 자동 publish는 넣지 않는다.
- 새 전원 기준 **T1=18:21:04.122024, boot901**과 승인된 재부팅을 계속 구분한다. 펌웨어 변경 때 version/boot별 관찰 구간을 추가해 전원만의 비교와 섞지 않는다. 24h/72h/7d는 기존 관찰의 평가 시점이며 이번 코드 수정·배포를 며칠 동안 막는 새 조건이 아니다.
- 출입 인증·센서·relay 경로의 MQTT/HTTP 비동기를 유지한다. diagnostics queue 가득 참, Backend 장애, sensor fault, scanner 오류가 local access 또는 mobile updater를 막지 않아야 한다.
- Target HTTPS pull/인증된 복구 OTA, dual slot, 서명·digest, relay OFF, 설치→새 boot→health/VALID 확인과 rollback을 보존한다. 무인 진단을 이유로 실제 문 반복 개방·재부팅·OTA 강제 재시도를 실행하지 않는다.

## 8. 검증과 반영 순서

### 묶음 A — 수집·조회·표시 결함부터

1. 실제 Worker + WorkManager 시험에서 모두2xx인 여러 묶음, 생산 중 ACK, 종료 직전 enqueue, process death, offline→online, 429/5xx/401/422, Clear/disable/계정 변경, 기존5시간 backoff 이관을 재현한다.
2. Backend optional schema와 late-evidence 조회를 먼저 호환 배포한다. 같은 사건 종료 뒤1시간 늦게 도착한 보고서, 최신20건 밖 자료, 가족별 report, 중복·clock skew를 fixture로 검증한다.
3. Android uploader/UI/자동 사건 capture를 같은 APK에 반영한다. 새 설치가 아니라 기존 앱 위에 업데이트하고 durable pending이 재개되는지 확인한다. 명시적인 현장 marker가 없어도 수집되어야 한다.

### 묶음 B — 인증 진입·재인증·센서 경로

1. 묶음 A를 사용하면서 BLE filter/ready-response/owner/dispatch 재현과 Target rearm/sensor 판정 시험을 병행한다. 확정 결함의 수정은 계측만을 위한 별도 릴리스와 불필요하게 분리하지 않는다.
2. 필요 Backend 필드를 먼저 수용하고 Android/Target을 독립 업데이트한다. GATT는 V2 유지, 불필요한 V1 경로를 재도입하지 않는다. signed status/sensor summary 확장은 명시적으로 버전 처리하고 구버전 read/rollback을 보존한다.
3. 기존 personal-production 절차로 component별 exact-main 빌드·서명·게시, NAS/앱/Target의 실제 버전 확인을 각각 기록한다. 문서·정책만 바뀌면 firmware/APK를 다시 만들지 않는다.

### 완료 기준

- **업로드:** 실행 가능한 온라인 Worker의 성공 batch 사이에 실패 backoff가 한 번도 발생하지 않는다. 테스트 서버의 정상 응답 조건에서 현장 사건→서버 저장30초 이내를 시험 목표로 잡고, 실제 기기에서는 queue wait/실행/HTTP/ACK 지연을 분리 측정한다. Android가 실행을 유예한 구간은 달성한 SLA로 계산하지 않는다.
- **복구:** offline/5xx/process death 뒤 같은 bundle의 중복 없는 ACK와 전체 sequence coverage를 확인한다. 유실이 있으면 count와 구간이 표시되고, 이전 누락을 복구했다고 주장하지 않는다. 정상 부하에서 dropped가 증가하지 않는다.
- **사후 조회:** 현장 종료 뒤 늦게 수신된 자료를 원래 사건에서 조회할 수 있다. Target session이 전혀 없어도 모바일 수신/dispatch/자료 공백을 조회할 수 있다. 과거 실패·다른 휴대폰의 성공을 현재 사건에 잘못 붙이지 않는다.
- **자동 출입:** 격리 환경의 실패 replay를 먼저 통과시킨다. 기존 personal profile의 화면 OFF3회·Activity 소멸3회 범위에서 증거를 자동 수집하고, 이후 자연 사용을 관찰한다. 모든 가족에게 같은 반복 시험을 새로 요구하지 않는다. force-stop은 Activity 소멸과 구분한다.
- **재진입:** 정상 clear→재접근은 무기한 막히지 않고, 같은 점유 구간·no-echo에서 자동 pulse를 반복하지 않는다. 새 인증 대기/차단 사유가 실제 FSM과 일치한다.
- **회귀:** MQTT 비동기, 수동 경로, OTA/rollback, 전원 boot 관찰을 유지한다. CI 성공·OTA 성공·실제 문 동작은 별도 결과로 보고한다.

실제 RF나 센서 하드웨어의 원인이 남으면 그 경계와 자동 수집된 증거를 제시한다. 현재 보유 관측으로 보이지 않는 물리 원인까지 자동 확정할 수 있다고 약속하지 않는다. 다만 **자료가 없는데 정상/성공이라고 표시하거나 로그 복사를 사용자에게 되돌리는 경로는 완료로 보지 않는다.**

## 9. 근거 및 관련 문서

- [Android WorkManager: retry/backoff 및 실행 조건](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work): retry는 지정된 backoff를 적용하며 실제 실행 시각은 시스템 제약의 영향을 받는다.
- [WorkManager 2.9.1 공식 sources JAR](https://dl.google.com/dl/android/maven2/androidx/work/work-runtime/2.9.1/work-runtime-2.9.1-sources.jar): 설치 앱 의존성과 일치하는 `WorkRequest.kt`의 최대5시간 상수, `WorkSpec.kt`의 지수식을 확인했다. 이 확인은 코드 경로 설명이지 휴대폰 scheduler DB를 읽은 결과가 아니다.
- [Android BLE background guidance](https://developer.android.com/develop/connectivity/bluetooth/ble/background): PendingIntent scan과 background 실행 경계를 적용하고, 등록만으로 실제 RF 수신을 추론하지 않는다.
- [기존 자동 진단 설계와 구현 이력](field_diagnostics_capture_plan.md), [PC 진단 읽기 API](diagnostics_read_api.md), [신뢰성 복구 이력](hands_free_reliability_recovery_2026_09_08.md), [개인 프로젝트 검증 범위](personal_production_profile.md). 3A 전원 관찰은 기존 T1(9월13일18:21:04 KST)을 유지하며 계획된 OTA 재부팅과 비의도 재부팅을 구분한다.

## 10. 2026-09-24 재개방 관측 보강 — 로컬 구현

- 기존 `ARM_TIMEOUT`을 유지하고, 같은 Target·boot·session·terminal sequence의 검증된 센서 요약이 있을 때만 종료 상세를 제공한다. 종료 시 차단 중이면 무효 표본만 있어도 `REARM_CLEARANCE_UNCONFIRMED`로 구분한다. 이것은 센서 이탈 미확인 상태이며, 실제 사람이 떠나지 않았거나 차단만이 미개방 원인이었다는 단정이 아니다.
- Target은 차단 시작·부분 clear streak 초기화·3회 clear 해제를 최근4건 RAM 이력으로 보존한다. sample마다 기록하거나 NVS에 쓰지 않는다. 덮어씀·부팅별 sequence·마지막 해제 시각을 함께 내보내고 Admin은 서명 밖/사건 연결 미확인으로 표시한다. 전송 공간이 부족하면 이력만 생략해 기존 서명 상태와 OTA 자료를 보존한다.
- **개방 정책은 변경하지 않았다.** raw 거리 `threshold+100mm` 초과3회 연속, no-echo/invalid는 clear로 인정하지 않음, 차단 시 최대5초 ARMED와30초 재시도 quiet, 수동 경로·인증·OTA 안전 조건을 그대로 둔다. 현재800mm threshold라면 clear는900mm 초과지만 다른 설정에도 같은 일반 규칙을 적용한다.
- 로컬 host replay는 322mm 근접39회에도 차단 유지, 무효/근접/경계 거리/추가 수동 pulse에 의한 partial streak 초기화,3회 clear 해제, ring overwrite, millis wrap과 reboot reset을 검증한다. 실제 사람 이탈 후에도 no-echo가 지속되는 설치 상태의 적정성은 아직 별도 현장 증거가 필요하다.
- Backend optional 수용을 먼저 배포한 뒤 Target signed OTA/boot/VALID를 따로 확인하는 순서를 유지한다. 이번 작업은 구현·로컬 시험까지이며 배포·개방 명령을 수행하지 않았다. [API 필드와 증거 한계](diagnostics_read_api.md#2026-09-24-rearm-timeout-detail-and-bounded-history-local-candidate)를 따른다.
