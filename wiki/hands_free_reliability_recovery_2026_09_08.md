---
title: Hands-free entry reliability recovery and autonomous diagnosis
type: proposal
project: smart-gatekeeper
status: in_progress
updated: 2026-09-09
source_of_truth: true
applies_to: [android, target, backend, personal-production]
---

# 핵심 출입 유스케이스 복구안 — 2026-09-08

## 1. 판단과 범위

목표는 **등록된 가족이 휴대폰을 주머니에 넣고 접근하면, 화면 조작 없이
인증·센서 판정·개방이 이어지는 것**이다. API/CI/OTA 성공은 이 목표의 성공이
아니다. 또 실패 때마다 사용자가 로그를 복사하거나 재시험해야 하는 구조는
운영 가능한 진단 구조로 보지 않는다.

권장 방향은 기존 local GATT/ACL을 유지하면서 **센서·재인증의 무기한 차단을
정리하고, 화면과 무관하게 사건 증거를 수집·전달·조회하는 경로를 완결**하는
것이다. 진단만 만들고 종료하지 않고 물리 출입 합격 기준까지 닫는다.
임계값/재시도 횟수의 추측성 반복 조정은 중단한다.

최초 분석 단계에서는 코드/설정/릴레이/OTA/배포를 변경하지 않았다.
이후 소유자의 진행 승인으로 구현 중이며 결과는 아래 구현 현황에 구분한다.
새 하드웨어 구매·설치와 장기간 offline 권한 정책은 별도 소유자
결정 사항이다. 사용자가 센서에 지나치게 붙었거나 짧게 머물렀다는 가정은 하지 않는다.

## 2. 이번 실패 구간에서 확보한 사실

보고 시각은 **9월 8일 오후 21:50 이후**로 해석했다. 22:30경 기존 진단 토큰으로
Backend의 21:30 이후 이력과 오늘 전체 이력을 직접 조회했다.

| 확인 대상 | 실제 관측 | 해석 한계 |
| --- | --- | --- |
| 현재 Backend | source `3c08e6b8ce60fd693103df868715215e8fbfe2f2`, `/ready` 모든 검사 true, Target fresh | 사건 당시 전 구간이나 물리 출입 성공 증거가 아님 |
| 사건 구간 첫 세션 | boot 782, GATT 연결/Challenge 후 1,200 ms에 `GATT_DISCONNECTED` 종료 | 휴대폰 측 원인·사용자 귀속 미확정 |
| 사건 구간 다음 세션 | proof 검증 성공 → ARMED → 60,013 ms 뒤 `ARM_TIMEOUT` | 센서 유효 판정/재진입 차단 중 무엇이 원인인지는 측정 증거 부족 |
| 센서/릴레이 | 위 두 세션에 센서 승인·릴레이 이벤트 없음 | 이벤트 보존 공백이 있어 모든 물리 동작 부재를 이 사실만으로 단정하지 않음 |
| 발생 시각/수신 시각 | 다음 세션의 60초 이상 이벤트가 21:57:44.188–21:57:45.003에 묶여 수신 | 21:57 인증 시작이나 21:50부터 7분 인증 지연으로 해석 금지 |
| 모바일 보고서 | 최신 row 141, 9월 7일 15:50:48.856 수신, 앱 44201 | 오늘 설치 버전·wake·작업 상태를 보여주지 않음 |

다음 세션의 Target monotonic 시각은 Challenge 4,760,163 ms, proof 검증
4,760,581 ms, ARMED 4,760,624 ms, timeout 4,820,637 ms다. 인증 연산 자체가
60초 걸린 것이 아니라 ARMED 이후 센서 승인 대기 구간이 60초였다.
이벤트의 credential 참조는 비식별이며 최신 모바일 자료가 없으므로 다른
가족의 인증을 신고자 본인의 인증으로 대체하지 않는다.

오늘 00:00부터 조회 시점까지 **59행, 18세션**이 조회되었고 커서는 끝까지
확인했다. terminal 분포는 ARM_TIMEOUT 9, GATT_DISCONNECTED 4,
ACCESS_GRANTED 4, OTA_BUSY 1이다. 여러 단말·자동 재인증·수신 지연을 포함하므로
이를 18번 실제 귀가의 성공률로 계산하지 않는다. boot 782는 sequence 1–4,
6–9가 있고 5는 조회되지 않았다. 완료 세션들에도 SENSOR/RELAY_ON 이벤트가
없는 패턴이 있다. 아래 host 재현은 큐 자체가 이 누락 모양을 만들 수 있음을
입증하지만, 개별 운영 행의 실제 손실 위치를 직접 관측한 것은 아니다.

## 3. 코드에서 확인한 결함 및 진단 공백

### A. 화면 OFF 유스케이스인데 자동 업로드가 화면에 종속

`gatekeeper_app/lib/screens/smart_key_home_screen.dart:71–108,138–188`의
init/resume, resumed-only 30초 timer, mounted 조건이 전송을 담당한다.
따라서 자동 업로드 ON만으로 화면을 열지 않은 사건의 서버 전달이 보장되지 않는다.
Native journal은 있으나 독립적인 내구성 있는 전송 대기열과 서버 수신 확인이 없다.

### B. 무반응의 결정 이유와 복구 경로가 부족

`BleWakeNativeEntrypoint.kt:76`의 ready=false와
`gattworker/BleGattCredentialWorker.kt:47–85`의 throttle/ledger/credential/
scheduling failure 등이 완전한 결정 이력으로 남지 않는다.
`blewake/ContinuousPresencePolicy.kt:38–56`는 PROOF_UNCERTAIN과 활성 ledger를
기한 없이 차단하며, 실패 후 빠른 복구도 실패하면 60초 대기한다.
불확실한 proof 재전송을 막는 원칙은 필요하지만, read-only 결과 조정과
orphan 작업 복구 없이 영구 대기하는 것은 사용성 해법이 아니다.

### C. 센서 재진입 차단이 계속 유지될 수 있음

`src/main.cpp:138,807–834`, `include/PassageRearmPolicy.h:11–24`:
모든 릴레이 pulse 이후 clear 조건의 유효한 센서값 3회가 연속 관측되어야
다음 자동 개방을 허용한다. 빈 공간이 무응답으로 측정되면 차단이 계속될
수 있다. `ready` 광고에는 이 차단과 ACL lease 유효성이 반영되지 않는다.
단, 광고 ready는 인증 가능 힌트이며 개방 권한이 아니다. 이를 그대로
자동 출입 가능 표시로 사용하는 소비자까지 함께 검토해야 한다.

이는 코드로 확인된 지속 차단 위험이다. **이번 boot 782의 원인으로 확정하지
않는다.** 해당 부팅에서 이전 릴레이 pulse가 있었다는 완전한 증거도 없다.
무응답을 무조건 clear로 처리하거나 시간만 지나면 무조건 문을 여는 수정은 금지한다.

### D. 비동기는 유지됐지만 ARMED 전체가 통신 공백

`src/main.cpp:289,853–894`는 ARMED/RELAY_HOLD/COOLDOWN 동안 MQTT 처리를
미룬다. 연결용 worker와 별개로 정상 통신은 메인 제어 루프 소유다.
즉 완전히 독립적인 정상 송신 구조가 아니라 제어 우선 지연 송신이다.
관측한 60초 이벤트 묶음은 이 정책과 일치한다. 이를 고치기 위해 다시
센서 앞에 동기식 TLS/MQTT 대기를 넣어서는 안 된다.

### E. 기록을 남겼더라도 전 과정이 보존된다는 보장이 없음

- `include/OfflineEventQueue.h:98`: 영속 큐 8개.
- `src/OfflineEventQueue.cpp:415–445`: full이면 앞선 2개를 제거하고 overflow
  기록과 새 항목을 넣는다. gap 기록은 legacy 진단이며 signed access API 대상이 아니다.
- `src/MqttManager.cpp:665–673`: terminal checkpoint가 공유 RAM FIFO 전체를
  영속 큐로 옮긴다. legacy/canonical 혼합과 긴 송신 유예 중 용량 초과 가능.
- `src/MqttManager.cpp:1732–1744`: local publish 성공이면 큐에서 제거한다.
  Backend DB commit 확인과 동일하지 않다.
- `src/GattServer.cpp:292–294`: 현재 canonical ABI에는 측정 슬롯이 없어
  distance/duration/relay 수치를 absent로 인증한다.
- `src/UltrasonicSensor.cpp:26–32`: 센서 통계가 다음 인증에서 초기화된다.
- `backend/app/main.py:2780–2973`: Target 상태는 최신 highwater 갱신이며
  모든 부팅/센서/연결 변화의 독립 역사 저장소가 아니다.

조회 API는 수집되지 않았거나 이미 제거된 정보를 복원할 수 없다.

**실제 큐 코드의 host 재현:** `src/OfflineEventQueue.cpp`에 항상 성공하는
가상 영속 저장소와 대표 소스 순서의 canonical/legacy 이벤트를 공급했다.
네트워크·센서·실제 문은 사용하지 않았다.

| 입력 시나리오 | push 반환 | 복원 후 살아남은 canonical 기록 |
| --- | --- | --- |
| 정상 출입 14행: canonical 8 + legacy 6 | 14개 모두 true | sequence 7 RELAY_OFF, 8 SESSION_COMPLETED만 보존 |
| ARM timeout 9행: canonical 5 + legacy 4 | 9개 모두 true | sequence 6–9 보존, 5 GATT_CONNECTED 소실 |

각 overflow counter는 12와 2였다. 앞선 경우 SENSOR/RELAY_ON 소실, 뒤 경우
boot 782에서 확인한 sequence 5 누락과 같은 모양을 재현했다. 따라서 이는
단순한 가능성 제시가 아니라 **정상 종료 checkpoint가 원인 사슬을 지우는
증거 보존 결함의 재현**이다. 이번 사용자의 물리 출입 실패 원인을 재현한
것은 아니다. 크기만 늘리는 대신 canonical 예약 용량, legacy 분리,
포화 시 독립적인 signed gap 표시, 서버 확인 뒤 제거를 함께 설계해야 한다.

### F. 이미 local 인증이지만 완전한 offline 출입은 아님

`src/TargetProofVerifier.cpp`는 Target ACL로 로컬 검증한다. 반면
`src/TargetAclManager.cpp:193,450`과 `src/main.cpp:747`에는 부팅 이후 신뢰
시간/ACL 갱신과 lease 제약이 있다. Backend의 기본 ACL lease는 900초다.
단순 캐시 추가로 wake/센서/전원 문제를 해결할 수 없으며 장기 offline은
만료·폐기 정책과 시간 신뢰를 명시적으로 결정해야 한다.

## 4. 권장 수정 묶음과 완료 기준

### 1차 — 사건 증거가 자동으로 끝까지 도착하도록 완결

**Mobile:** Flutter와 분리된 native durable journal/outbox와 업로드 worker.
기존 동의를 유지하며 callback뿐 아니라 모든 skip 결정, enqueue/start/stop,
GATT 단계, process start/exit, BLE/권한/OS 제한, ready epoch, 앱 버전,
capture/upload ACK 시각을 비식별 구조로 기록한다. 서버 ACK까지 보관하고
network 복구/부팅 후 재전송한다. 사용자가 앱 화면을 열 필요가 없어야 한다.
원문 MAC/광고 payload/키/정밀 이동 경로는 수집하지 않는다.

**Target:** ARM 종료 전에 샘플 수·유효/무응답/범위 내 횟수·최소/최대·필터값·
clear 횟수·차단 시간·설정 버전·종료 사유를 세션 summary로 고정한다.
IDLE에서도 권한 없는 접근/센서 health 관측을 제한된 빈도로 남긴다.
부팅/연결 변화/queue gap을 signed append-only 사건으로 보존한다.
단순 RAM 증설 대신 메모리·flash 마모 예산, legacy 중복 기록, 최악 세션
이벤트 수를 계산해 journal을 설계한다. 새로운 측정 schema도 인증하고,
DB commit ACK와 idempotency를 사용한다. MQTT PUBACK만으로 완료 처리하지 않는다.

**Backend/PC:** 기존 read token으로 `incidents`, `health-history`를 조회하는
사건 API를 추가한다. 모바일/Target/collector를 boot+sequence+session+
비식별 credential로 결합하고 다음 단계별 증거와 누락 사유를 반환한다.

`접근 관측 → phone wake → 작업 시작 → GATT → proof → ARM → 센서 승인 → relay → door contact`

사건은 `관측됨 / 명시적 실패 / 자료 없음 / 독립 관측 불가`를 구분한다.
stale 보고서를 정상 판정에 사용하지 않는다. 접근 후 인증 없음, ARM timeout,
반복 GATT 실패, 생존 자료 지연은 자동 사건 후보로 만든다. 센서 접근은
미등록 방문자일 수도 있으므로 사용자 출입 실패/자동 개방 권한으로 취급하지 않는다.

서버의 결정 규칙이 실패 구간과 필요한 증거를 확정하고, Agent는 read-only
API로 사건을 조회·설명한다. Agent가 상시 살아 있거나 사용자가 실패 시각을
말해야만 기록이 시작되는 구조로 만들지 않는다. 누락 상태도 기록하며,
임의 재부팅·릴레이·OTA를 자동 진단 복구 수단으로 실행하지 않는다.

**1차 합격:** 온라인이고 OS 실행이 허용된 종료 세션은 5분 내 서버 도착,
네트워크 복구 후 backlog 자동 재전송/중복 제거, 의도적으로 주입한 센서·
GATT·전송 실패는 보고서 복사 없이 실패 단계 또는 정확한 증거 공백 확인.
스케줄러가 억제된 폰에 이 시간 목표를 보장한다고 표현하지 않는다.

### 2차 — 핵심 출입 상태 머신과 실행 경로를 정리

- 센서 상태를 CLEAR/OCCUPIED/UNKNOWN/FAULT로 구분하고 현장 빈 공간 특성을
  반영한다. 재진입 차단과 인증 가능 힌트를 분리하고 모든 차단을 이유와
  복구 조건으로 표시한다. UNKNOWN으로 영구 조용히 대기하지 않되,
  UNKNOWN을 자동 허용으로 승격하지 않는다.
- 폰의 pre-proof orphan은 실제 작업 상태와 조정한다. proof 결과 불명은
  Target의 인증된 read-only 세션 조회로 해결한다. 오래된 proof를 재전송하거나
  시간이 지났다는 이유만으로 중복 개방을 허용하지 않는다.
- 실행 중 connected-device native service/직렬 BLE 소유자를 중심으로
  시간 민감한 인증을 처리하고 WorkManager는 전송·복구 역할에 집중하는 안을
  현재 구조와 계측 비교한다. 단순 executor가 프로세스 생존을 보장하지 않는다.
- CompanionDeviceService는 공식 association/주소 정책·가족 여러 폰 연결
  공정성·배터리를 시험한 뒤 채택한다. 서비스를 바꾸면 반드시 해결된다는
  가정으로 전체 구현을 갈아엎지 않는다.
- MQTT는 단일 소유 네트워크 task+bounded immutable queue로 센서 루프에서
  분리한다. ESP32-C6에서 별도 CPU 코어가 있다고 가정하지 않는다. BLE/TLS/
  flash/OTA 경합과 메모리 부족 시험을 먼저 통과해야 한다.
- local ACL과 OTA 복구를 유지한다. 장기 offline 허용기간/폐기 지연은
  소유자 결정 후 별도 계약으로 다룬다. 이번 무반응을 이유로 인증을 생략하지 않는다.

### 3차 — 독립 관측과 필요한 하드웨어만 보강

Target 자기보고만으로 RF 발신·전원·실제 문 열림을 모두 증명할 수 없다.
상시 BLE 수신기와 door-contact를 붙이면 각각 실제 광고 수신과 문 상태를
분리 관측할 수 있다. 수신기는 같은 집 Wi-Fi에만 의존하지 않는 로컬 저장,
자기 heartbeat, 가능하면 독립 전원을 가져야 한다. 별도 전원 감시는
MCU 전원 상실과 네트워크 단절 분류에 필요하다. 소프트웨어만으로 brownout을
없앴다고 판단하거나 곧바로 220V 모듈 구매를 처방하지 않는다.

외부 RF 관측은 **그 수신기 위치**의 수신 증거이며 소유자 폰의 수신/도착
증거가 아니다. 문 접점도 누가 통과했는지 증명하지 않는다. 하드웨어 설치,
전원/배선 검증과 초기 앱 association·동의에는 한 번의 현장 작업이 필요하다.

## 5. 사용자 반복 시험을 줄이는 검증 방법

현관을 무인으로 반복 개방하지 않는다. 여분 Target, 실제 Android 단말,
센서 입력 모사/기계적 자극, 릴레이 모사 부하의 격리 시험대를 사용한다.
앱/OS lifecycle, GATT 절단 시점, 센서 무응답/clear, queue overflow, broker/WAN
단절, 재부팅, 업로드 도중 종료를 자동화한다. RF/OEM 동작을 mock 테스트로
대체하지 않고 화면 OFF 실제 단말 시험을 포함한다.

제안 개인 설치 초기 합격 기준:

- 가족 각 폰의 잠금/주머니/장시간 idle/일반 프로세스 종료/재접근을 나눈
  초기 20회에서 5초 초과 무반응 0회. 가능한 부분은 시험대 자동화하고,
  최종 동선은 실제 출입으로 확인한다. 20회는 회귀 smoke gate이지 99.9% 증명이 아니다.
- 정의한 접근 영역 진입→ARM p95 ≤3초, 최대 ≤5초를 목표로 계측한다.
  실제 영역 진입 기준 없이 첫 BLE callback부터 재서 전체 지연이라고 하지 않는다.
- 유효 센서 조건 충족→relay ≤0.5초, 물리 문 상태는 별도 측정한다.
- 연속 체류는 같은 점유 구간의 중복 개방을 막고, 실제 이탈 후 재접근은
  새로운 권한/점유 조건에서 정상 동작해야 한다.
- 위 장애 주입마다 자동 사건 자료가 남아야 한다. 이유 없는 조용한 실패는
  단 한 번도 정상 출입으로 집계하지 않는다. 메모리·큐·battery 비용도 비교한다.
- 설치 후 자연스러운 일상 출입으로 연속 관측한다. 실패하면 그 사건의 자료를
  즉시 분석하며 사용자의 재현 산책·보고서 복사를 기본 대응으로 요구하지 않는다.

전원 없음, 센서/릴레이 고장 등에서는 안전한 거부와 원인 범위 식별이 합격
동작이다. WAN 단절 시험은 합의된 유효 ACL 범위와 cold-boot 조건을 구분한다.

## 6. 스마트폰만으로 한계가 남을 때의 결정

Android의 PendingIntent wake는 공식 경로지만 Worker 중단·quota/OS 지연이
있다. 주기 작업은 최소 15분이며 정확한 실행 시각을 보장하지 않는다.
Android 15 이상 명시적 force-stop은 PendingIntent를 취소한다. 이 제한을
우회한다고 약속하지 않으며 **이번 사건이 force-stop이었다고 추정하지 않는다**.

계측과 한 차례의 근본 안정화 뒤에도 가족 폰의 정상 화면 OFF 조건에서
누락이 반복되면 무제한 Android 재시도 튜닝을 계속하지 않는다. 그때는
**전용 암호학적 BLE 키를 출입 주체로, 앱을 관리/업데이트/수동 보조로 분리**하는
대안을 소유자와 결정한다. 정적 beacon ID만으로 문을 여는 방식은 금지한다.
전용 키도 RF/배터리/센서 실패가 가능하므로 같은 안전·증거 기준을 적용한다.

궁극적으로 약속할 수 있는 것은 지원 조건을 정의한 신뢰도와 자동 증거다.
모든 전원/OS/RF/기계 고장을 100% 제거하거나 모든 침묵을 즉시 하나의 원인으로
확정하는 약속은 하지 않는다. 관측 불가능하면 UNKNOWN과 마지막 정상 단계,
누락 증거를 명시해야 한다.

## 7. 검토한 공식 자료와 관련 문서

- [Android BLE background guidance](https://developer.android.com/develop/connectivity/bluetooth/ble/background): PendingIntent, Worker 중단과 connected-device service 선택지.
- [CompanionDeviceManager](https://developer.android.com/reference/android/companion/CompanionDeviceManager): association, API 36 presence API, 주소/RPA·bond 제약.
- [WorkManager requests](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work): expedited/주기 실행의 조건과 시간 한계.
- [Android 15 stopped state](https://developer.android.com/about/versions/15/behavior-changes-all): 명시적 force-stop의 PendingIntent 취소.
- [진단 API와 배포](diagnostics_read_api.md), [기존 현장 진단 계획](field_diagnostics_capture_plan.md), [지속 체류 분석](continuous_presence_reauth_2026_09_06.md), [OTA 계약](ota_reliability_contract.md).

## 8. 승인 후 구현 현황

소유자는 사용자 로그 추출에 의존하지 않는 개선 진행을 승인했다.
`codex/hands-free-reliability-recovery`에서 모바일 native 전송, Target 기록 보존과
센서 요약, Backend incident/health API를 병행 구현했다. PR #392가 exact main
`81fbc6dc9b9286b2d4375afeda9129566789ad2a`으로 병합됐다. 배포·설치·실제 출입
증거는 아래에서 별도로 구분한다.

- `AccessEventReceipt`는 기존 command topic의 별도 진단 메시지로 수신한
  DB commit 응답만 검증한다. Target/event/boot/count/sequence/원래 event MAC을
  domain-separated HMAC으로 묶고 정확한 queue head만 확인한다. 센서 요약은
  다른 type/domain과 session/terminal sequence/summary MAC을 사용한다.
- 독립 Python HMAC 벡터와 실제 C++ helper 시험에서 변조·다른 사건·다른
  boot·다른 Target·다른 key·cross-domain 응답을 거부했다. uint64의 2^53 초과
  값을 보존하며 JSON position은 canonical decimal string을 사용한다.
- `MqttTelemetryWorker`는 제어 루프가 준비한 signed status를 복사한 뒤
  단일 publication 동안만 socket을 소유한다. ARMED 센서 대기에 통합했다. 차단된
  fake socket 동안 제어 tick 1,000회 진행, 원본 버퍼 변경과 응답 generation
  분리, 이중 소유·task/heap/watchdog 실패 경로를 실제 worker host 시험으로
  확인했다. 이 결과는 실제 TLS/RF/릴레이 시험을 대체하지 않는다.

- 정상 출입의 canonical 8행을 legacy RAM journal과 분리하고, canonical
  큐 포화 시 앞선 기록을 지우지 않는 backpressure로 바꿨다. 서버의 정확한
  commit receipt 전에는 head를 제거하지 않는다. 용량은 무한하지 않으며
  RAM/RTC fallback과 포화·저장 실패 수치를 노출한다.
- 센서 종료 요약은 원래 종료 시각으로 고정하고, pending 4개와 별도 NVS
  4개 journal에 보존한다. 샘플/무응답/유효/차단/clear 횟수와 raw/filter
  범위를 서명한다. IDLE에서도 1 Hz health를 관측하며 ready 광고는 센서
  재진입 차단과 ACL lease를 반영한다. UNKNOWN/FAULT를 자동 개방으로
  바꾸지 않는다. 이 변경은 센서 하드웨어 장애 자체를 복구했다는 뜻이 아니다.
- Native 모바일은 skip/enqueue/worker/GATT/process/OS snapshot을 기록하고
  화면 독립 worker와 내구성 있는 단일 pending report로 업로드한다. 동의,
  credential 및 전송 권한 범위에 묶으며 Clear/로그아웃과 늦은 ACK를 분리한다.
  pre-proof의 실제 WorkManager 작업이 사라진 경우만 ledger orphan을 복구한다.
  PROOF_UNCERTAIN은 재전송하지 않으며 전체 BLE 실행기를 교체하지 않았다.
- Backend schema 016은 sampled health와 서명된 센서 요약 이력을 보존한다.
  실제 MariaDB에서 반복 migration, 중복·충돌, 불변 이력, 31일 보존 정책과
  rollback 보존을 시험했다. 사건 API는 Target 기록이 없는 모바일 실패/skip과
  canonical chain이 없는 센서 요약도 독립 관측으로 반환한다.
- ARMED에서 분리한 전송은 immutable status publication에 한정한다.
  command 수신·ACL callback과 canonical 감사 이력 전송은 IDLE에서 처리한다.
  따라서 완전한 steady-state MQTT 비동기화나 즉시 모든 이벤트 도착을 주장하지 않는다.

보호 입력 2개(DB image migration 파일과 Backend bundle 목록)는 별도 정책
PR #391에서 사전 승인한 뒤 main을 feature에 병합 연결했다. 기존 23-path
범위와 배포 권한을 유지했으며 최종 root 391개 시험이 PASS했다(환경상
PowerShell 1개 skip). 정책 42개와 PR의 모든 필수 검사도 PASS했다. Target/app OTA 경로와
dual-slot rollback은 유지한다. 실제 폰 화면 OFF, 현장 RF/센서/릴레이와
일상 출입 SLO는 소프트웨어 시험만으로 완료 처리하지 않는다.

배포 후보 로컬 검증: Backend/PC 264개 PASS(별도 실행 대상 DB 시험 3개 skip),
실제 MariaDB 신규 이력·API SQL 및 production image 016 반복 migration/rollback
시험은 따로 PASS했다. Native 94개와 Flutter 110개 PASS, 변경 Dart analyze
무결함, Kotlin 실제 생성 report의 strict schema/API 인증·exact ACK 교차 검증
PASS다. 운영 GATT를 활성화한 `esp32c6_personal_production` 빌드 PASS이며
RAM 93,112B, Flash 1,842,052B다. OTA contract와 protocol 16개 시험도 PASS했다.
구형 unsigned V1 기록은 서명 ACK를 받을 수 없으므로 기존 best-effort 전송
정책으로만 배출하고, authenticated V2와 rollback overlay는 ACK 전 보존한다.

새 APK는 최초 한 번 앱을 열어 기존 업로드 동의와 인증 설정을 native로
이관해야 한다. 이후 Flutter 화면은 전송 조건이 아니다. 상시 관측 동의,
앱 설치·OS 실행 허용과 실제 수집 여부는 구분한다. 문 앞 재현 산책이나
지원 보고서 복사를 배포 확인의 기본 요구로 삼지 않는다.

## 9. Exact-main 배포 및 현장 증거

- Source: PR #392, `81fbc6dc9b9286b2d4375afeda9129566789ad2a`.
- Target run `34240363227`은 9월 8일 23:51 KST에
  **2.1.480+main.g81fbc6d**를 게시했다. 서명/암호화 검증, NAS atomic publish,
  실제 HTTPS manifest와 immutable firmware artifact exact readback을 통과했다.
  이 결과는 Target 설치·재부팅·health confirmation이 아니다.
- Backend run `34240363175`는 23:54:11 KST 배포 성공했고, 독립 `/ready`가
  exact source/12개 check true/Target fresh를 반환했다. 실제 sampled health가
  약 30초 간격으로 row 1→2→3 증가하고 사건 API와 구형 보고서 조회가
  통과했다. 무토큰/잘못된 토큰은 401이다. 기존 PC 진단 토큰/NAS wrapper는
  변경하지 않았다.
- Mobile run `34240363172`는 9월 9일 00:02:20 KST에
  **1.0.0-g81fbc6d / 44401** 게시를 완료했다. APK 서명 및 primary/fallback
  atomic publish, 두 경로의 HTTPS metadata/APK exact-byte 검증이 모두
  PASS했다. APK 55,659,673B, SHA-256
  `d1efd6dfeb68b4885b1f229c3ccb665b72d283b8edcf262f46f6df78494138e4`다.
  휴대폰 설치나 화면 OFF 동작 증거는 아니다.
- 이번 작업에서 문 열기, 릴레이 시험 또는 수동 Target OTA trigger를
  전송하지 않았다. Target의 기존 periodic HTTPS pull은 6시간 주기이므로
  게시 시각을 장치 설치 시각으로 대체하지 않는다.
- 실제 화면 OFF 자동 출입, 센서 재진입 회복, OTA 장기 health와 실제 문
  움직임은 아직 현장 완료 증거가 없다. 새 자동 이력으로 자연 사용을
  확인하며 사용자의 로그 복사나 재현 산책을 기본 전제에 두지 않는다.
- 이 작업에 `SGK 출입 신뢰성 후속 진단` heartbeat(`sgk`)를 매시간 등록했다.
  새 설치·장애·수집 원인을 기존 API로 읽고 의미 있는 변화만 알린다.
  문 열기/OTA trigger/재부팅/설정 변경/자동 배포는 허용하지 않는다.
  이 Agent 점검은 PC와 데스크톱 앱이 실행 중이어야 하며, NAS의 이력 저장과
  모바일 native 수집을 대체하지 않는다. 동일 stale 상태를 반복 보고하지 않는다.
- 운영 readback에서 발견한 두 공백을 Backend-only 후속 수정으로 처리한다.
  전역 middleware의 no-store 덮어쓰기를 실제 app 경로 시험으로 고치고,
  이미 발행되는 retained `/boot`의 닫힌 참고 필드를 최대 32개 캐시에
  보관한 뒤 exact signed-status boot와 일치할 때만 이력에 연결한다.
  수신 시각/retained 여부/생성 시각 미관측/unsigned를 명시하고 boot authority나
  liveness는 바꾸지 않는다. PR #393 / exact Backend
  `a105539273f9eb2aeaf0362d17bcc967336d85a7` / run `34243125046`이
  9월 9일 00:16:16 KST에 배포됐다. 네 진단 경로의 200/401/422 no-store,
  기존 row 1/36 보존, 새 row 46의 동일 boot 784 unsigned 부팅 참고 정보
  연결을 독립 HTTPS 조회로 검증했다. Backend/PC 274개(통합 선택 3개 skip),
  root 391개(PowerShell 1개 skip) 회귀와 모든 PR/main 검사가 PASS했다.
  앱/Target 게시 버전은 81fbc6d 그대로이며 재게시하지 않았다.
