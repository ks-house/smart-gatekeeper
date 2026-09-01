# 와이프 폰 로컬 자동 출입 지연 분석 — 2026-09-02

## 1. 범위와 증거 경계

사용자가 첨부한 관리자 `최근 전체 출입 감지 이력` 화면의 단일 세션
`9baab554-b53b-43…`, Target `target_c7b4730f`를 소스와 대조했다. 이번 분석은
read-only이며 phone, Target, Backend, MQTT, 센서, 릴레이와 설정을 변경하지 않았다.

관리자 화면의 시각은 Target 발생 시각이 아니라 Backend의 `received_at`을 브라우저에서
초 단위로 표시한 값이다. API에는 Target `monotonic_ms`가 있지만 현재 표에는 노출되지 않고,
이번 event payload의 `distance_mm`도 비어 있다. 따라서 아래 간격은 수신 시각 기준 근사치이며
물리 접근 시각이나 각 센서 표본의 실제 거리를 직접 증명하지 않는다.

## 2. 첨부 세션 타임라인

| 수신 시각 | seq | 단계 | 관찰 |
|---|---:|---|---|
| 00:12:09 | 69 | GATT_CONNECT | Target BLE 연결 |
| 00:12:09 | 70 | PROOF requested | challenge 발급 |
| 00:12:09 | 71 | PROOF verified | 서명 증명 유효 |
| 00:12:09 | 72 | ARMED | 센서 감지 대기 진입 |
| 00:12:16 | 73 | SENSOR | threshold 조건 충족 |
| 00:12:17 | 74 | RELAY_ON | 릴레이 활성화 명령 |
| 00:12:17 | 75 | RELAY_OFF | 릴레이 유지 시간 완료 |
| 00:12:18 | 76 | COMPLETE | Target software 흐름 완료 |

수신 시각상 핵심 간격은 다음과 같다.

- GATT 연결 → ARMED: 같은 표시 초. 이 단일 세션은 와이프 폰의 최초 BLE/GATT 인증이
  느렸다는 증거가 아니다.
- ARMED → SENSOR: 약 7초. 사용자가 느낀 첫 지연은 인증 이후 Target의 물리 센서 대기
  구간에 위치한다.
- SENSOR → RELAY_ON/OFF/COMPLETE: 약 2초 안. 센서 조건을 만족한 뒤의 Target FSM과
  relay command 단계는 주된 7초 병목이 아니다.

별도로 첨부된 Home Assistant 상태 이력도 `ARMED` 00:12:10,
`RELAY_HOLD` 00:12:17, `COOLDOWN` 00:12:18, `IDLE` 00:12:23을 표시한다. HA의
수신 시각은 canonical 관리자 이력과 정확히 같은 clock은 아니지만, ARMED 뒤 relay 진입까지
약 7초였다는 관찰을 독립적으로 지지하고 live cooldown이 약 5초였음을 보여 준다. 화면에
포함된 상태명과 시각은 진단 증거이며 별도 작업 지시로 해석하지 않았다.

## 3. 사용자 재현 조건 반영 — 접근 거리·머문 시간 설명 제외

사용자는 본인 폰과 와이프 폰을 여러 번 같은 방식으로 비교했고, 센서에 지나치게 가까이
붙지 않았으며 유효 구간에 1초 이상 머물렀다고 확인했다. 따라서 이번 비교에서는 사용자
접근 방식, 20cm 미만 blind zone 진입, 순간적으로 지나간 동작을 7초 지연의 설명으로 사용하지
않는다.

Local GATT action-1이 ARMED에 성공하면 초음파 5-slot history를 모두 invalid sentinel로
초기화한다. 100ms polling에서 중앙값을 통과하려면 현재 세션의 valid 표본이 최소 3개
필요하므로, 사람이 이미 유효 범위에 있고 echo가 정상이라면 필터 자체의 추가 지연은 대략
0.3초 수준이다. 1초 이상 동일한 유효 위치를 유지했다는 재현 조건에서는 이 안전한 session
isolation만으로 7초를 설명할 수 없다.

`ARMED`가 Target FSM에 반영된 이후 센서 판정에는 phone이 참여하지 않는다. 따라서 반복
비교에서 phone에 따라 차이가 난다면 다음 두 갈래를 먼저 구분해야 한다.

- Target가 실제로 `ARMED`에 들어간 뒤 main loop가 수 초간 센서 polling으로 돌아오지 못함
- Target 동작은 빨랐지만 MQTT/Backend 수집 시각 때문에 관리자 화면의 간격만 길어 보임

소스에는 첫 갈래와 연결되는 구체적인 blocking 후보가 있다. `GattServer::update()`는 인증
이벤트를 drain하면서 TLS MQTT `client.publish()`를 동기 호출하고, 이 함수가 끝난 뒤에야
`main.cpp`가 초음파를 읽는다. 이 publish는 QoS 0이라 broker PUBACK을 기다리지는 않지만,
underlying TLS client의 `write()`가 반환할 때까지 Arduino main loop는 진행하지 않는다. 따라서
일시적인 TLS write 정지는 센서 polling 공백을 만들 수 있는 구조다. 코드의
`setSocketTimeout(15)`는 PubSubClient의 connect/read 대기 제한이며 publish write의 정확한 15초
상한으로 해석하지 않는다. 반면 GATT result indication은 비동기이며 확인 timeout도 1.2초라,
정상 설계 경로의 indication 대기만으로 7초를 설명하지는 못한다.

이것은 아직 원인 확정이 아니다. 첨부 화면은 Backend `received_at`만 초 단위로 보여 주고
Target `monotonic_ms`와 센서 raw/median을 숨긴다. seq 72 `ARMED`와 seq 73 `SENSOR`의
`monotonic_ms` 차이가 약 7초이면 Target loop 정지 또는 표본 판정 문제이고, 차이가 짧으면
MQTT/Backend 수집 지연이다. 현재 자료로 두 경우를 분리할 수 없다.

## 4. 2순위 의심 — COMPLETE와 다음 인증 가능 시각의 의미 불일치

Target FSM은 relay hold가 끝나면 `RELAY_OFF`와 `ACCESS_SESSION_COMPLETED`를 방출하면서
`COOLDOWN`에 진입한다. 그러나 새 GATT 인증을 받을 수 있는 `IDLE`은 cooldown이 끝난 뒤다.
현재 기본 cooldown은 3,000ms이고 NVS/원격 설정으로 달라질 수 있다. 과거 연결 시험에는
`COOLDOWN → IDLE`이 5초였던 사례도 있으므로 현재 live 값을 다시 읽기 전에는 3초라고
단정하지 않는다.

관리자 이력에는 `gate_idle`이 canonical `ready_for_next_access` 단계로 표시되지 않는다. 따라서
화면의 `Target 출입 흐름 완료`가 “다음 인증 준비 완료”처럼 보이지만 실제로는 수 초간
`TARGET_BUSY`가 가능한 관측성 공백이 있다. 사용자가 느낀 “문을 연 뒤 다음 인증까지 시간이
걸림”과 직접 일치하는 높은 우선순위 의심점이다.

## 5. 3순위 의심 — Samsung native FIRST_MATCH 재진입 지연

현재 native wake 등록은 Android `SCAN_MODE_LOW_POWER`와
`CALLBACK_TYPE_FIRST_MATCH`를 사용한다. 한 번 인증한 phone이 Target 근처에 계속 있으면 이것은
연속 ranging timer가 아니므로 새 presence callback을 즉시 보장하지 않는다. OS가 이전 match를
잃었다고 판정한 뒤 다시 광고를 처음 본 것으로 처리해야 다음 hands-free session이 생길 수 있고,
Samsung Doze/background scheduling은 이 재진입 시간을 늘릴 수 있다.

다만 첨부 화면에는 다음 session의 GATT_CONNECT가 없고 wife phone의 redacted worker health
(`presenceToDispatchMs`, `presenceToArmedMs`, callback receive time/RSSI)도 없다. 따라서
FIRST_MATCH/OEM 지연은 설계상 가능한 후보이지 이번 한 세션으로 확정된 원인은 아니다.

## 6. 판정과 다음 최소 증거

1. **현재 세션의 최초 인증은 정상적으로 빠름** — 같은 표시 초에 GATT→proof→ARMED.
2. **접근 거리·머문 시간은 원인 후보에서 제외** — 동일 방식 반복 비교와 1초 이상 유효 위치
   유지라는 사용자 확인을 반영했다.
3. **첫 체감 지연은 Target/수집 구간** — ARMED→SENSOR 약 7초이며, 의도된 3-sample 필터나
   정상 GATT indication 경로로 설명되지 않는다. 동기 MQTT publish에 의한 Target loop 정지와
   수집 시각 왜곡을 우선 분리해야 한다.
4. **다음 인증 지연에는 확정적인 UI 의미 공백이 있음** — COMPLETE 뒤 실제 cooldown/IDLE이
   표시되지 않는다.
5. **wife phone 고유 재진입 지연은 아직 미확정** — 다음 비교 session과 native worker timing이
   없다.

다음 재현 한 번에서는 다음 항목만 같은 시간축으로 수집한다.

- wife phone의 redacted `presenceToDispatchMs`, `presenceToArmedMs`, FIRST_MATCH 수신 시각과 RSSI
- seq 72/73 canonical event의 `monotonic_ms`, SENSOR 시점 `distance_mm`, 그 사이 main-loop
  최대 소요시간과 MQTT publish 소요시간
- Target status의 현재 `distance_threshold_cm`, `relay_cooldown_ms`, `state`
- 문에서 충분히 이탈한 시각과 재진입 시각, 다음 GATT_CONNECT 시각

이 자료면 `phone wake`, `GATT`, `sensor`, `Target cooldown`, `OS 재진입`을 각각 분리할 수 있다.
거리 기준이나 cooldown을 먼저 낮추면 원인 증거를 지우고 relay 재트리거 위험을 바꿀 수 있으므로,
이번 분석만으로 설정을 변경하지 않는다.

## 7. 안전 개선 소스 후보

2026-09-02 source candidate는 새 MQTT task를 추가하지 않고 기존 Arduino loop의 PubSubClient
single-owner 계약을 유지한다. 이는 MQTT callback에서 FSM, ACL, OTA를 동시에 실행시키는 새 race를
피하기 위한 보수적 선택이다.

- GATT canonical event와 legacy event는 TLS socket에 쓰지 않고 16-entry 고정 RAM outbox에
  순서대로 복사한다.
- outbox가 가득 차면 새 이벤트가 아니라 가장 오래된 volatile 이벤트를 기존 durable NVS queue로
  먼저 spill하여 global FIFO를 보존한다. durable queue까지 실패하면 명시적인 error를 남긴다.
- main loop 순서를 `GATT → ultrasonic → relay/FSM telemetry snapshot → network`로 바꾸고,
  `AUTH_PENDING`, `ARMED`, `RELAY_HOLD`, `COOLDOWN` 또는 진행 중인 GATT protocol output 동안
  Wi-Fi web handler, MQTT connect/read/publish/flush와 OTA update를 실행하지 않는다.
- access-critical 상태가 끝난 뒤에도 persisted event를 먼저, volatile event를 다음으로 루프당 한 건만
  전송한다. telemetry는 최신 state만 coalesce하고 FSM 전환 때 즉시 갱신해 stale COOLDOWN을 IDLE
  이후에 내보내지 않는다.
- outbox depth/overflow count를 boot/status telemetry에 추가했다.

이 설계는 의도된 3개 sensor sample이 네트워크 write 사이에 끼지 않도록 만들지만, 실제 매립
Target에서 ARMED→sensor latency가 줄었다는 물리 증거는 설치 후 동일 재현 전까지 성립하지 않는다.
또한 access-critical 동안 HA status 수신은 의도적으로 보류되므로 HA history의 수신 시각은 Target
발생 시각이 아니다. canonical event의 `monotonic_ms`가 정확한 원인 분석 기준으로 남는다.
