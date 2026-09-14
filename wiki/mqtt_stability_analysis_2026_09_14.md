---
title: MQTT intermittent reconnect analysis and hardening plan
type: proposal
project: smart-gatekeeper
status: in-progress
updated: 2026-09-14
source_of_truth: true
applies_to: [target, backend, mqtt-broker, diagnostic-read-client]
---

# MQTT 반복 재접속 분석 및 보완 계획

## 1. 범위와 결론

9월14일13:04 KST까지 기존 읽기 API, 제한된 MQTT 구독, 배포 소스를 대조했다.
설치 Target은 `2.1.498+main.g7959962`, Backend는 `7afb9f7`, 분석 checkout은
`91a9098`이다. 이번 작업은 분석·계획이며 runtime 수정, 배포, 재부팅, 문 개방,
broker 설정 변경이나 상시 모니터링 활성화는 하지 않았다.

후속 `보완작업시작` 요청으로 1차 소스 보완을 구현했다(§8). 위 시각의 관측과
설치 버전은 분석 당시 기준이며, 아래 로컬 구현을 배포 완료로 해석하지 않는다.

**장시간 완전 단절보다는 간헐적인 세션 재접속 폭증이다.** Wi-Fi 재접속이나
OTA만으로 설명되지 않는다. 최초 연결 종료 원인은 아직 미확정이지만,
실패 분류·오류 보존·관측 도구에서 확정 가능한 결함을 발견했다.

## 2. 실제 증거

- 설치 이후 초기 조회:1568개의 signed health 표본 모두 boot904,
  최대 수신 간격36.1초. 후속1589표본 조회도 cursor 끝까지 읽었다.
  health 표본 간격은 원시 MQTT 단절 시간이나 월간 가용성 측정이 아니다.
- MQTT 누적 접속:00시2회 유지 →01:17경3회 →05:27 OTA 후4회 →
  08시 말11회 →09시 말19회 →11시 말37회 →12:54경75회.
  12시 동안에는 IDLE, GATT 연결 누적3, OTA attempt53이 유지됐다.
  Wi-Fi outage/link-generation 카운터는0이었다(장치 unsigned advisory).
- 13:04:48에도 boot904/IDLE, uptime49096초, 접속75회로 유지됐다.
  자유 heap68248B, largest31220B. 누적 최저 heap26248B는 순간 저점이며
  그 자체로 메모리 누수나 BROWNOUT을 증명하지 않는다.
- 13:00:43–13:03:43 strict-TLS4883 읽기 observer: 연결1회 유지,
  관측344행/4채널/회전 유실0. 결과 경로 `/tmp/sgk-mqtt-stability-20260914-1`.
- 별도45초, 고유 진단 client ID의 strict-TLS 읽기에서 status42개,
  총212491B, 최대5067B, retained Target online/boot904 확인.
  broker 자체 공개 metadata는 Mosquitto2.1.2, uptime70284초였다.
  짧은 현재 구간의 정상은 앞선 재접속 현상을 부정하지 않는다.
- source의 Target client ID는 `smart-gatekeeper-<target-id>`이며, 두 진단
  클라이언트는 별도 임의 read-only prefix를 사용했다. Target ID를 복제한
  CONNECT, test PUBLISH, retained command를 보내지 않았다.

## 3. 확정된 소프트웨어/진단 결함

### A. 실제 연결 실패가 stale 결과로 잘못 분류됨 — P0

`src/MqttManager.cpp`의 worker finish는 성공이 아니면 transport를 닫는다.
그런데 결과를 받는 update의 `resultCurrent`에는 link-generation 일치뿐 아니라
`client.connected() && wifiClient.connected()`도 들어간다. 따라서 정상적인
TLS/MQTT/subscribe/availability 실패도 socket이 닫혔다는 이유로 false가 되어
`kStale || !resultCurrent` 경로를 탄다. 그 경로는 실패 카운터 증가 및
5→30초 backoff를 건너뛰고 즉시 다음 시도를 예약한다.

이는 코드상 확정 결함이다. 다만 이번의 connect attempts와 adopted count는
동일하므로 **이번 모든 재접속을 이 실패 분류 결함이 시작했다고 주장하지 않는다.**
`mqtt_connect_failures=0`은 이미 연결된 세션의 끊김이0이라는 뜻도 아니다.

수정 방향: generation/cancel에 따른 stale 판정, attempt outcome, 성공 후
socket 생존을 서로 분리한다. stale은 실제 세대 변경/취소에만 사용한다.
실패한 시도와 성공 직후 닫힌 세션은 각각 이유를 보존하고 bounded backoff한다.

### B. 성공 후 연결이 끊긴 원인이 사라짐 — P0

현재 MQTT update는 `client.loop()` 결과/당시 state 및 TLS read/write/available
실패를 지속 기록하지 않는다. 다음 성공은 `mqttLastError=0`으로 덮는다.
누적 접속 횟수만 남아 peer close, keepalive, read/write 오류, 의도된 OTA
자원 인계 및 중복 client ID 추방을 구별할 수 없다.

추가할 bounded edge record: boot/session generation, 발생 monotonic시각,
계획 여부·원인, 직전 연결 지속시간, 재시도 예정·실제 간격, MQTT state,
가능한 TLS/socket 오류 code, loop 최대 공백, 송신 크기/시간, heap/largest,
FSM·Wi-Fi 세대·OTA attempt. 기존 lastError가 handshake 값만 남기는 경우에는
runtime 오류를 보존하는 작은 하위 계층 hook이 필요하다. 코드0을 원인없음으로
대체하지 않고 관측불가를 명시한다.

오류 문자열/키/명령 payload 없이 작은 고정 ring에 기록하고, 연결 복구 후
전송·서버 ACK로 보존한다. 같은 오류 폭증은 횟수/최초/최종으로 합산하고
유실 수를 노출한다. 진단 추가로498의 RAM 여유와 OTA 회복성을 훼손하지 않는다.

### C. 읽기 observer가 실제 availability 형식을 거부함 — P0

`scripts/observe_diagnostics_mqtt.py:project_message`는 availability 채널을
단순 online/offline 문자열로만 처리한다. 실제 Target은 target/boot/scope가
포함된 JSON을 보낸다. 실제 형식의 안전한 fixture를 넣어 REJECTED를 재현했다.
기존 테스트는 문자열만 사용하여 이 불일치를 놓쳤다.

Target JSON과 bridge 문자열을 채널별로 처리하고 target/boot/scope,
중복키·타입·크기를 엄격히 검증한다. retained snapshot과 새 edge를 분리하며
서명 없는 LWT는 transport 관측일 뿐 인증된 상태로 승격하지 않는다.
관측 reject 총167건 모두가 availability 때문이라고 단정하지 않는다.

## 4. 아직 확정하지 않은 실제 종료 원인

| 후보 | 근거와 제한 | 판별 수단 |
|---|---|---|
| TLS/TCP peer 종료, NAT 경로, broker 정책 또는 중복 client ID | Wi-Fi 세대 불변인 IDLE 중에도 재접속. 짧은 외부 observer는 안정 | Target 종료 edge와 broker 해당 client의 종료 reason을 같은 시각으로 대조 |
| TLS 송수신 자원/지연 | 약5KB status가 초당 전송, contiguous heap 감소/순간 저점 존재 | write/read/available 오류, 송신 시간, heap와 종료 직전 수치 동시 기록. 정상 heap이 장기 하강한다고 단정하지 않음 |
| keepalive/loop 서비스 공백 | keepalive120초, 출입 구간에는 receive loop를 보류 | ping/loop gap 계측. 최근 재접속은 IDLE·GATT 누적불변이어서 출입 보류만으로 설명 불가 |
| broker 재시작 | 현재 broker uptime 약19.5시간 | 현재 조회는 오늘 반복 broker 재시작 가설을 지지하지 않음. 유지보수/과거 로그 별도 |
| 전원/Wi-Fi 장애 | 같은 boot904와 outage0 | 현재 반복 접속의 주원인이라는 증거 없음. 전기적 안정성 확정 아님 |

## 5. 권장 구현 순서

### 1차: 작은 수정으로 원인을 잃지 않고 재접속 폭주 제한

1. A의 분류 수정과 실제 실행 가능한 table-driven state tests를 추가한다.
   현재 connectivity tests는 주로 source 문자열 존재 검사이므로 failure
   outcome × link generation × cancel × socket 상태 조합을 실행해야 한다.
2. B의 연결 edge를 backend 조회까지 전달하고 C의 실제 JSON contract를 수정한다.
3. 실패 backoff는 기존5–30초 범위를 유지하고 jitter를 추가한다. 단순 CONNACK
   직후에는 폭주 이력을 지우지 않고 일정 안정 구간(제안60초) 후 초기화한다.
   정상 Wi-Fi 복귀/계획 OTA 복귀 첫 시도는 빠르게 하되 반복 실패는 제한한다.
4. fresh signed status만으로 flapping 경고를 숨기지 않는다. 계획된 OTA와
   unplanned reconnect rate, 마지막 안정 연결 지속시간을 별도 표시한다.
   제안 경보: 계획 외3회/10분, 경고 해제는10분 안정 후. 기존15/90초
   상태 freshness 규칙과 signed command 안전 조건은 그대로 유지한다.

### 2차: broker 증거와 원인별 수정

- 기존 진단 읽기 token으로 조회할 수 있는 **해당 Target 한정 broker connection
  history**를 추가한다. 현재 API에 broker 종료 로그가 제공된다는 증거는 없다.
- Mosquitto connection/error/warning/notice 로그를 제한된 reader가 읽어
  Target별 원인 code·시각·connection generation만 저장한다. 중복 ID,
  keepalive timeout, socket/TLS 종료를 구분하고 원문 IP·다른 client·payload는
  API로 내보내지 않는다. 보존7일/용량 상한과 손실 표시를 둔다.
- NAS 로그 읽기 권한·mount가 없으면 그 항목은 추가 운영 설정 필요로 명시한다.
  사용자에게 로그 복사를 요구하는 설계가 아니다. 익명 외부 broker의 공개
  `$SYS`에 전체 로그를 새로 노출하지 않고, 인증/ACL 이관은 별도 단계로 다룬다.
- 최초 새 단절의 양쪽 증거로 원인별 수정을 선택한다. 동일 ID 충돌이면 진단
  client/배포 중복을 수정하고, TLS 오류면 자원 수명/버퍼/송수신 오류 처리를,
  keepalive면 loop 서비스 공백을, broker/NAT면 해당 정책을 수정한다.

### 3차: 상태 송신 부하와 단일 transport 소유권 보강

- 필수 signed 상태/변화/출입 terminal의 신선도는 유지한다. 큰 상세 진단은
  별도 저주기(제안30초)·변화시 전송으로 분리하고 사건 edge는 즉시 보낸다.
  크기 상한, 기존Backend/N-1호환, bounded queue와 ACK를 함께 검증한다.
- 연결마다 boot/config/event를 반복 발행하는 양을 측정하고 불필요한 중복만
  줄인다. audit replay·receipt·최초 boot evidence는 생략하지 않는다.
- 현행 connect/status worker의 단일 소유권은 유지한다. main의 IDLE publish,
  receive/callback이 실제 BLE·센서 지연을 만드는 증거가 있으면 전용 I/O task와
  main의 검증된 command queue로 분리한다. callback에서 actuator를 실행하거나
  두 task가 PubSubClient/TLS를 동시에 호출하지 않는다. 큰 라이브러리 교체는
  첫 조치가 아니며, 필요시 pinned provider의 기능/메모리 시험 후 결정한다.

## 6. 검증과 완료 기준

- 호스트/격리 broker: DNS/TCP/TLS/CONNACK/subscribe/write/peer-close,
  정상/취소/late result, 짧은 성공 반복, client ID 충돌, 부분 MQTT packet,
  backoff wraparound, observer JSON/LWT 및 지연 진단 ACK를 실행 시험한다.
- 초기 원인 수집 패치 설치 후 첫 발생부터 양쪽 종료 사유를 분석한다.
  원인 없이 timeout/keepalive만 늘려 겉으로 보이는 offline을 숨기지 않는다.
- 원인별 수정 뒤 계획 외 재접속0인24시간을 1차 목표로 하고72시간 추적한다.
  계획 OTA 단절과 외부망 장애는 별도 분모/원인으로 남긴다. 기존월간99.5%
  연결 목표를 짧은 PASS로 대신하지 않는다.
- 격리된 장애 복구 시험은 네트워크 복원 후2분 내 연결·구독·새 signed 상태·
  진단 ACK까지 확인한다. 보안상 command 구독 승인과 물리 문 개방은 별도 증거다.
- 센서 타이밍/relay fail-safe/GATT 지연, 기존 Android/Backend 호환,
  OTA 설치→재부팅→VALID 및 rollback을 비회귀 조건으로 유지한다.
  배포·설치는 최신 사건이 저장되고 재접속 횟수가 안정화된 것과 구분한다.

## 7. 근거 위치

- 로컬: `src/MqttManager.cpp` update/connectWorkerEntry/suspendForOta,
  `src/MqttTelemetryWorker.cpp`, `src/main.cpp`, `include/config.h`,
  `tests/test_connectivity_recovery_contract.py`,
  `scripts/observe_diagnostics_mqtt.py`, `tests/test_diagnostics_mqtt_observer.py`.
- 빌드가 사용하는 PubSubClient2.8과 Arduino NetworkClientSecure 소스를 직접
  확인했다. MQTT protocol read timeout과 TLS/TCP timeout은 서로 다른 경계다.
- [Mosquitto 공식 configuration 문서](https://mosquitto.org/man/mosquitto-conf-5.html):
  connection_messages, log_dest, log_type. 운영2.1.2에 적용할 옵션은 실제
  버전의 설정 검사로 확인하고 무조건 log_type all을 켜지 않는다.
- [PubSubClient 공식 구현](https://github.com/knolleary/pubsubclient/blob/v2.8/src/PubSubClient.cpp):
  loop/connected/readPacket. 설치 라이브러리 소스를 판정 기준으로 삼는다.
- [기존 연결 정책](embedded_target_connectivity_policy.md),
  [진단 조회 API](diagnostics_read_api.md), [OTA 계약](ota_reliability_contract.md).

## 8. 1차 구현 — 로컬 검증 기록 (후속 배포는 §9)

- `MqttConnectionPolicy`가 실패 outcome과 stale/link-generation을 분리한다.
  짧은 성공 후 단절도 backoff를 유지하며 60초 연속 연결 뒤 초기화한다.
  대기는 5–6초 →10–12초 →20–24초 →30초 상한이다. Wi-Fi/OTA 복귀의
  첫 시도는 즉시 가능하고, 실패하면 다시 제한한다. millis wrap도 실행 시험한다.
- MQTT loop 실패/transport 종료/handshake 단계/DNS/worker 생성/OTA 인계를
  구별하여 마지막 오류를 재연결 뒤에도 보존한다. OTA 인계 전에 이미 끊긴
  socket은 계획 단절로 계산하지 않고, adoption 직전 유실은 실제 MQTT state를 남긴다.
- 계획 외 단절 3회/10분이면 `flapping=true`; 경고 해제는 연속 연결10분이다.
  단지10분 동안 offline이거나 signed 상태가 새로 왔다고 해제하지 않는다.
- `mqtt_connection.schema=1`에 boot 내부 connection generation, count, 시각,
  loop 최대 공백 및 최근4개 edge를 넣는다. 각 edge는 정확히9개 정수의 CSV:
  sequence, occurred_ms, reason_code, last_error, connection_duration_ms,
  free_heap, largest_block, loop_gap_ms, wifi_generation.
  sequence는 U32에서 포화하며 같은 boot의 identity를 재사용하지 않는다.
- 진단 object 추가 전 JSON pool과 payload 여유를 검사한다. 부족하면 이 optional
  advisory만 생략하여 기존 signed 상태 전송을 보존하고, 조회에서는 source unavailable로
  표시한다. 최대값/부족한 pool/부족한 wire budget을 ArduinoJson 실행 시험으로 검증한다.
- 읽기 observer는 실제 Target JSON availability와 bridge의 실제 connectivity
  diagnostic을 구분한다. 다른 Target/중복키/잘못된 타입/크기를 거부하고 채널별
  reject를 계수한다. retained replay를 새 live 상태로 승격하지 않는다.
- 기존 read token의 `/mqtt-history` 및 CLI `--mqtt-history`로 boot/sequence를
  보존한 unsigned 관측을 조회한다. 반복 health 행은 새로운 edge가 아니다.
  자세한 조회·페이지 및 수집 제한은 [진단 API](diagnostics_read_api.md)를 따른다.
- 평상시30초 health 저장은 유지하되 새로운 head edge는 Target별 마지막 저장
  이후5초가 지나면 우선 보존한다. signed 상태 전이는 즉시 저장하고, 변경된
  unsigned 수치만으로 DB 기록을 무제한 증가시키지 않는다. 억제된 관측은
  persisted checkpoint를 이동시키지 않아 후속 signed 상태에서 다시 저장할 수 있다.

### 이번 단계의 명시적 한계

최근4개는 **RAM ring**이며 반복 status를 통해 저장한다. 전원 단절 영속성,
전용 edge ACK, 완전한 전달 보장은 아직 없다. `edge_overwritten`은 ring 교체 횟수로,
그 자체가 Backend 유실 횟수는 아니다. 기존 저장 주기 사이의 손실 가능성과
새 펌웨어 설치 전 자료 부재를 조회 결과에 표시한다.

브로커 reader/mount는 아직 연결되지 않아 `broker_history.operation_status=NOT_CONFIGURED`다.
TLS 상세 errno hook, filtered broker 로그 수집, 진단 저주기 분리, 격리 broker 장애
주입 및 설치 후24/72시간 검증은 다음 단계다. 최초 반복 종료 원인은 아직 미확정이다.
추가 진단은 unsigned이며 signed 출입 판정/명령 권한, OTA health와 rollback,
비동기 access 처리, 센서와 릴레이 코드를 변경하지 않는다.

### 로컬 검증 결과

- root449개 중448통과/1환경 skip, Backend310개 중305통과/5환경 skip.
  ArduinoJson 헤더를 명시하여 최대 진단값·pool/wire 부족 시험도 실제 실행했다.
- 분담 검증에서 격리 MariaDB의 저장 gate10개 시나리오 모두 통과했다.
  테스트 컨테이너는 제거됐고 운영 DB/broker를 변경하지 않았다.
- ESP32-C6 personal production build 성공: 정적RAM88648B(498대비+528B),
  flash1858300B. 이는 실행 중 heap 최저점이나 설치 후 OTA health 통과 증거가 아니다.
- 교차 검토 지적 세 가지(상태 buffer overflow, 이미 단절된 OTA handoff,
  adoption 오류0 덮어쓰기)를 수정하고 최종 검토에서 추가 blocker 없음.
- 새 cross-layer API/CLI 검증은 root tests에 두어 보호된 Backend 배포 inventory,
  workflow/policy/서명 gate를 변경하지 않았다. 임시 provisioning symlink는 제거했다.
  Git push, 배포, OTA, 재부팅 및 문 개방은 수행하지 않았다.

## 9. 9월14일 배포·설치 확인

- PR [412](https://github.com/ks-house/smart-gatekeeper/pull/412)를 일반 CI 통과 후
  main `c74a5573555248b5f7a48e8d0bbf268fa05009b3`로 병합했다.
  초기 firmware CI의 FastAPI 부재는 root cross-layer test의 환경 의존 문제였다.
  firmware-only 환경에서만 명시적으로 skip하고, 기존 Backend test module의
  `load_tests`가 동일 테스트를 반드시 실행하도록 수정했다. 집중47개 시험 통과,
  이후 PR의 firmware/OTA/Backend/policy 검사가 모두 통과했다.
- Backend run [34814216681](https://github.com/ks-house/smart-gatekeeper/actions/runs/34814216681)
  성공. NAS apply/status receipt가 같은 source/image/bundle을 가리키며
  `2026-09-14T06:46:27Z` (15:46:27 KST) 배포를 확인한다. 독립 `/ready`도
  exact SHA, 12개 정상 check 및 fresh HMAC Target 상태를 반환했다.
- Target publisher run [34814216700](https://github.com/ks-house/smart-gatekeeper/actions/runs/34814216700)
  성공. provisioning의 공개 signer key로 manifest 서명을 검증하고 immutable
  artifact 1,935,044B의 SHA256
  `2e1d6f71002adf9b9a721cbbfbad8acd87a0e0765d3dc36253db8d5155eedee0`을 직접 확인했다.
- 15:47:31 KST, fresh signed health15625와 live Target/bridge의 IDLE·relay OFF·
  BLE 연결0을 확인하고 기존 bridge OTA 경로에 비-retained 요청을 **1회** 보냈다.
  boot904/498에서 boot905/`2.1.500+main.gc74a557`로 전환했고,
  15:48:37 live 상태 및 health15627(15:48:36 수신)에서 `running_image_valid=true`,
  stage11/error0을 확인했다. 새 boot ID는 `918df53eca9fc25d7c7160a19566ab27`이다.
- 같은 토큰의 `/mqtt-history`는 새 boot의 `source_status=AVAILABLE`, schema1
  진단을 반환했다. 초기 연결 generation1, 계획 외 단절0, flapping=false이며
  아직 실제 단절 edge의 전달을 검증한 것은 아니다. heap68836B, lifetime min52444B,
  largest63476B는 해당 초기 snapshot일 뿐 장기 최저치가 아니다.
- 앱 변경/업데이트, 수동 문 개방, 추가 재부팅, broker 설정 변경은 하지 않았다.
  기존 PAUSED 관측 설정도 유지했다. broker reader는 `NOT_CONFIGURED`,
  최초 단절 원인과 24/72시간 안정성, 센서 NO_ECHO/ARM_TIMEOUT의 물리 출입
  문제는 여전히 별도 검증 대상이다. 설치 성공을 전체 출입 성공으로 해석하지 않는다.
