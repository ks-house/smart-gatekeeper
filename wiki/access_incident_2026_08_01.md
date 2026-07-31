# 2026-08-01 출입 지연·반복 개방·화면 OFF 분석

## 1. 현장 증거

Home Assistant 이력은 `01:30:22 ARMED`, `01:30:45 RELAY_HOLD`,
`01:30:46 COOLDOWN`, `01:30:51 IDLE`, `01:30:57 RELAY_HOLD`를 보였다.

- 첫 ARM에서 개방까지 약 23초이므로 Backend→MQTT→Target ARM 전달은 해당 시험에서 성공했다.
- 초음파 센서는 부팅 때 초기화되고 ARMED 중 100ms 간격으로만 읽는다. 5표본 중앙값의
  신규 ARM 초기 지연은 정상적으로 약 0.3초이며 23초 지연을 설명하지 못한다.
- 유효 거리는 20cm 이상 설정 임계값 이하이다. 20cm 미만 맹점, 반사각, echo timeout은
  `999cm`로 처리되어 개방 조건을 통과하지 않는다.
- 두 번째 RELAY_HOLD 전에 ARMED가 HA에 보이지 않는 것은 1초 telemetry 사이에서
  ARM과 센서 감지가 연속 발생했을 가능성이 있다.

## 2. 확인된 반복 개방 원인

모바일은 RSSI가 계속 강한 상태에서도 시간 cooldown이 끝나면 Pre-arm API를 다시
호출할 수 있었다. Target의 `triggerArm()`도 RELAY_HOLD를 제외한 ARMED/COOLDOWN에서
새 ARM을 받아 상태와 유효 시간을 덮어썼다. 초음파 5표본 이력도 다음 출입 세션에
남아 있어 재 ARM 직후 이전 근접 표본이 재사용될 수 있었다.

수정 후 계약은 다음과 같다.

```text
자동 출입: IDLE --새 ARM--> ARMED --새 초음파 표본--> RELAY_HOLD
          --> COOLDOWN --> IDLE
수동 개방: IDLE --force_open--> RELAY_HOLD --> COOLDOWN --> IDLE
```

- Target은 IDLE에서만 ARM과 수동 개방을 수락한다.
- ARMED/RELAY_HOLD/COOLDOWN의 ARM은 `arm_rejected`로 거부한다.
- 새 ARM마다 초음파 중앙값 이력을 `999cm`로 초기화한다.
- 모바일의 중복 Pre-arm 요청은 기존 cooldown 정책에 따라 허용한다. Target이
  IDLE에서만 새 ARM을 수락하므로 상태 순서와 재무장 경계는 Target에서 보장한다.
- 단, IDLE 복귀 뒤 도착한 중복 요청은 새 출입 세션으로 수락된다. 따라서 이 계약은
  `ARMED -> RELAY_HOLD -> COOLDOWN -> IDLE -> ARMED` 순서를 보장하지만, 한 사람의
  물리적 통과를 한 번의 개방으로 묶는 재진입 방지까지 제공하지는 않는다.

## 3. 화면 OFF 임시 진단

Android foreground-service engine이 `PowerManager.isInteractive()`를 5초 heartbeat마다
확인한다. 화면이 실제로 OFF이면 Target UUID 패킷 수신 자체를 확인하기 위해 RSSI
임계값을 임시 우회한다. 사용자·기기 API 인증과 UUID 검증, 기존 cooldown은 유지한다.

성공 시 콘솔 순서는 다음과 같다.

1. `화면 OFF 감지 — 현장 진단용 RSSI 기준 임시 우회 활성`
2. `화면 OFF Target 비콘 수신 확인 (RSSI: ... dBm)`
3. Pre-arm HTTP 200 및 MQTT 발행 확인
4. Target `pre_armed` 이벤트와 HA `ARMED`

이 우회는 원거리에서도 Target 패킷만 수신하면 승인 요청을 보낼 수 있는 현장 진단용
설정이다. 화면 OFF 수신 여부가 확정되면 제거하고 정상 RSSI gate로 복귀해야 한다.

## 4. Backend→MQTT→Target 감사 결과

첨부 이력의 ARMED는 해당 시험 시점에 전체 전달 경로가 실제로 한 번 이상 성공했다는
증거다. 그러나 Backend의 `mqtt_published=true`는 Target 실행 확인이 아니다.

- Backend는 QoS 1 publish의 broker PUBACK만 최대 2초 기다린다.
- Target의 `pre_armed`, `arm_rejected`, `door_open` 이벤트를 Backend가 구독해 명령과
  대응시키지 않는다.
- 명령에 request/correlation ID가 없어 어느 API 요청의 결과인지 연결할 수 없다.
- Backend는 설정된 broker보다 Docker 로컬 후보 주소들을 먼저 시도하므로, 다른 broker가
  해당 주소에서 응답하면 Target이 없는 broker에 성공 발행할 가능성이 있다.

따라서 현재 API가 보장하는 범위는 `Backend -> 어떤 후보 broker의 PUBACK`까지다.
향후에는 설정 broker 우선/단일화, request ID 포함, Target ACK topic QoS 1 발행,
Backend의 ACK 대기 및 timeout 응답을 추가해야 Target 수신·상태 전환까지 보장할 수 있다.

## 5. 실기기 판별표

| 관측 | 판정 |
|---|---|
| 화면 OFF 로그에 Target 패킷 없음 | Android background BLE 수신 구간 문제 |
| 패킷 있음, Pre-arm 요청 없음 | 모바일 cooldown/API 조건 문제 |
| HTTP 200·MQTT true, HA ARMED 없음 | broker 선택 또는 Target 구독/연결 문제 |
| HA ARMED 있음, RELAY_HOLD 없음 | 초음파 맹점·반사각·유효 거리 문제 |
| `arm_rejected` | Target이 IDLE이 아닌 정상 인터록 |
