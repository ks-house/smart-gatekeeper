# 모바일 앱 화면 OFF·앱 종료 접근 시나리오 구현 감사

> 감사일: 2026-07-30
> 범위: `gatekeeper_app`의 Android 백그라운드 비콘 감지 → Pre-arm REST API 호출 경로
> 관련 문서: [mobile_app_scenario.md](mobile_app_scenario.md) · [mobile_app_scan_lifecycle.md](mobile_app_scan_lifecycle.md)

## 0. 2026-08-31 현재 운영 계약과 다중 휴대폰 관찰

이 문서의 아래 본문은 과거 REST Pre-arm 경로 감사 이력이다. 현재 hands-free
운영 경로는 `iBeacon first-match → Android native wake → authenticated Local GATT
action 1 → Target ARMED → AJ-SR04T → relay`이며, 성공 알림은 Target이 action 1을
검증하고 실제 `ARMED`로 전환한 뒤에 표시된다.

현재 기본값은 다음과 같다.

- `ARMED` 센서 대기 시간: 60초
- 센서 폴링: 약 100 ms 간격, 5개 샘플 중앙값
- 유효 거리: 20 cm 이상 50 cm 이하
- 릴레이 유지: 1초, 이후 기본 3초 cooldown

소유자 휴대폰은 주머니 상태 접근에서 열리지만 다른 승인 휴대폰은 `Target 인증
완료` 알림 후 문앞에서 열리지 않고 앱을 열면 열리는 현상이 1회 보고됐다. 공통
Target 센서·릴레이가 소유자 휴대폰에서 동작하고, 다른 휴대폰도 앱을 연 뒤 동작한
사실은 상시 센서/배선 고장보다 mobile wake 시점 차이를 우선하게 한다.

네이티브 wake는 RSSI 임계값 없이 정확한 iBeacon의 `FIRST_MATCH`에서 인증 작업을
예약한다. 따라서 복도·엘리베이터·주차 위치 등 문앞보다 이른 지점에서 인증되어
60초가 먼저 시작될 수 있다. 성공 알림은 Target의 이후 `arm_expired`를 수신해
취소하거나 남은 시간을 표시하지 않는다. 앱 resume은 권한/백그라운드 설정을 다시
평가하고 네이티브 scan을 stop/start 재등록하므로 새 first-match와 새 action-1이
발생해 60초 창을 갱신할 수 있다. 이것이 현재 관찰과 가장 잘 맞는 가설이지만,
실패 회차의 Target 이벤트와 휴대폰 세션 시각 없이는 확정 원인으로 승격하지 않는다.

확정에는 같은 회차에서 `auth_verified_armed → arm_expired`가 문앞 도착 전에
발생했는지, 앱 resume 뒤 새 `AUTH_PENDING → ARMED → sensor trigger`가 이어졌는지를
상관 분석해야 한다. 단일 성공은 다른 OEM·주머니 방향·반복 접근 신뢰성을 증명하지
않는다.

### 0.1 제한된 접근 세션 갱신 권고

비콘이 보이는 동안 action-1 인증을 무기한 반복해 `ARMED` 만료를 계속 미루는
방식은 채택하지 않는다. 승인 휴대폰이 현관 주변 실내에 놓여 있으면 Target이
상시 `ARMED`가 되어, 휴대폰을 소지하지 않은 외부 사람도 초음파 조건만 만족해
문을 열 수 있기 때문이다. 배터리 소모와 여러 휴대폰의 GATT 경합도 증가한다.

대신 다음의 bounded approach-session을 후보 계약으로 둔다.

1. exact iBeacon 첫 감지는 접근 후보만 만든다.
2. 최근 RSSI가 현장 보정된 근접 진입 조건을 연속 충족할 때 action 1을 수행한다.
3. 근접 조건이 유지되는 동안에만 약 20초 간격으로 인증을 갱신해 Target의 60초
   `ARMED` deadline을 연장한다.
4. 한 접근 세션의 총 갱신 시간은 90~120초로 제한한다.
5. 비콘 무수신 또는 약한 RSSI가 일정 시간 유지될 때만 `OUTSIDE`로 복귀하고,
   다음 접근 세션을 허용한다. 최대 시간에 도달하면 반드시 OUTSIDE 재진입을
   요구한다.
6. Target은 최소 갱신 간격, nonce/replay, credential/ACL, relay/cooldown interlock을
   그대로 강제하고, 앱은 남은 센서 대기 시간과 만료를 사용자에게 표시한다.

Android `PeriodicWorkRequest`는 최소 주기와 Doze 지연 때문에 이 초 단위 제어에
적합하지 않다. processless 경로를 유지하려면 PendingIntent BLE 결과를 native
receiver에서 RSSI/hysteresis와 single-flight로 제한한 뒤 기존 signed GATT worker를
예약해야 한다. 정확한 RSSI와 주기는 현관 매립 상태에서 두 휴대폰의 분포를 측정한
뒤 확정한다.

### 0.2 모바일 관리자 역할과 센서 활성화 경계

모바일 `ADMIN`/`USER` 역할은 관리자 UI와 Backend 관리 권한의 경계이며 Target의
hands-free action-1 허용 조건이 아니다. Target은 signed ACL에서 credential 존재,
`ACTIVE` 상태, `OPEN` permission bit, 프로토콜/시간 유효성과 P-256 서명을 검사한다.
일반 사용자도 이 조건을 충족하면 동일하게 action 1을 실행할 수 있다.

현재 RESULT OK는 control gate가 action 1을 받아 실제 FSM을 `ARMED`로 전환한 뒤에만
전송되며, Android의 `Target 인증 완료` 알림은 이 RESULT OK를 받은 durable session에
대해서만 게시된다. 따라서 새 성공 알림이 정확히 해당 회차의 것이라면 관리자가
아니어서 센서가 처음부터 비활성인 경우와 양립하지 않는다.

다만 알림은 Target의 `arm_expired`와 동기화되지 않고 사용자가 누를 때까지 남을 수
있다. Target은 60초 만료, 새 인증이 기존 `ARMED`를 교체한 뒤 실패/abort한 경우,
relay hold/cooldown 등에서 센서 측정 상태를 벗어난다. 그러므로 문앞 도착 시점에
`ARMED`였는지는 알림 존재가 아니라 같은 회차 Target state/event와 distance telemetry로
확인해야 한다.

### 0.3 2026-08-31 아내 휴대폰 HA 상태 이력 판독

소유자가 제공한 Home Assistant 상태 이력에는 다음 두 가지 결정적 구간이 있다.

- `21:54:20 AUTH_PENDING → 21:54:21 ARMED → 21:54:22 RELAY_HOLD →
  21:54:23 COOLDOWN → 21:54:28 IDLE`: action-1 인증 후 센서 조건이 약 1초 안에
  충족되어 relay까지 진행한 정상 hands-free 형태다. 이 화면만으로 credential/phone
  identity를 직접 상관할 수는 없지만, 같은 현장 Target의 인증-센서-FSM 경로가
  적어도 한 번 동작했음을 증명한다.
- `21:56:26 ARMED → 21:57:26 IDLE`: 소유자 확인상 이미 문이 열린 뒤 사용자가 집
  안으로 이동하던 시간이다. 따라서 실패 회차의 센서 미감지 증거가 아니라, 출입
  완료 후 추가 인증이 Target을 다시 60초간 ARMED한 불필요한 후행 세션이다.
  관리자 권한 거부나 credential 거부라면 ARMED까지 도달할 수 없다는 판정만
  유지한다.

후행 ARMED는 `21:56:05 RELAY_HOLD → 21:56:11 IDLE` 이후 15초 만에 시작됐다. 이는
이미 완료된 접근과 뒤늦은/중복 native wake가 하나의 consumed approach session으로
묶이지 않는 현재 한계를 보여준다. 해당 60초에는 사용자가 외부 센서 앞에 없었으므로
relay 없이 timeout된 것이 정상이며, 최초 무개방 원인을 설명하지 않는다.

`RELAY_HOLD → COOLDOWN`은 약 1초이며 `COOLDOWN → IDLE`은 화면상 약 5초로 반복된다.
따라서 현장 runtime cooldown은 정적 기본값 3초와 다르게 5초로 설정됐을 가능성이
높다. 나머지 IDLE 직행 relay 회차는 이 화면만으로 manual/MQTT와 누락된 sub-second
action-1을 구분하지 않는다.

### 0.4 RELAY_HOLD 전에 ARMED가 보이지 않는 이유

소유자는 해당 시험에서 원격 수동 개방을 하지 않았다고 확인했다. 그러므로
`21:53:53`, `21:54:42`, `21:56:05`의 `IDLE → RELAY_HOLD`처럼 보이는 회차는 현재
증거상 action-1 `ARMED → sensor trigger`가 HA 스냅샷 사이에서 완료됐을 가능성을
우선한다.

Target은 약 100 ms마다 loop를 돌지만 HA가 구독하는 status MQTT telemetry는 1초마다
한 번만 발행한다. 인증 완료 후 사람이 이미 센서 범위에 있으면 `ARMED`가 100~300 ms
정도만 지속되고 다음 1초 publish 전에 `RELAY_HOLD`가 될 수 있다. 따라서 HA 상태
이력의 ARMED 누락은 FSM이 ARMED를 건너뛰었다는 증거가 아니다. local action-2도
설계상 `AUTH_PENDING → RELAY_HOLD`이므로, 고급 로컬 수동 기능 사용 여부는 canonical
event로 별도 구분해야 한다.

소스 감사에서는 추가 결함 후보도 확인됐다. MQTT pre-arm은 새 세션 전에
`UltrasonicSensor::resetHistory()`를 호출하지만 Local GATT action-1 grant는 호출하지
않는다. 이전 세션의 유효한 5표본이 남으면 새 ARMED 직후 더 빠르게 relay로 전환하거나
현재 사람이 없어도 stale median을 재사용할 수 있다. 정확한 경로 판정은 1초 상태
스냅샷이 아니라 `auth_verified_armed`, `sensor_detected`, `relay_on_sensor`,
`relay_on_local_manual`, `relay_on_manual` canonical/event 순서를 사용해야 한다.

원격 수동 개방이 없었다는 소유자 확인 뒤에는 이 stale-median 가설이 화면의 정확한
패턴까지 설명한다. 초기화된 `[999,999,999,999,999]`에서 첫 정상 회차는 유효 표본
3개가 쌓이는 순간 중앙값이 유효해져 relay로 전환하고 `[valid,valid,valid,999,999]`
형태를 남길 수 있다. 다음 action-1의 첫 invalid 표본은 네 번째 슬롯만, 그 다음
action-1은 다섯 번째 슬롯만 덮으므로 두 회차 모두 중앙값에는 여전히 세 valid가 남아
즉시 relay가 된다. 세 번째 action-1에서 첫 valid 슬롯이 invalid로 덮이면 중앙값이
999가 되어 비로소 ARMED가 유지된다.

이는 `21:54:22` 첫 명시적 ARMED-sensor relay 뒤 `21:54:42`, `21:56:05` 두 개의
ARMED가 보이지 않는 relay, 이어서 `21:56:26`의 60초 ARMED timeout과 정확히 같은
모양이다. canonical event가 없으므로 물리 확정은 아니지만, 단순 telemetry sampling
설명보다 구체적인 source-and-timeline 일치 증거다. 주기적 인증 갱신보다 먼저 모든
Local GATT action-1 성공 시 sensor history를 초기화하고 현 세션의 fresh valid 표본
3개를 요구해야 한다.

## 1. 결론

현재 앱에는 다음 경로가 **구현되어 있다**.

1. 앱 최초 실행 시 BLE·위치·알림 권한 요청
2. 별도 foreground-service Flutter isolate 시작
3. 서비스 isolate 안에서 iBeacon monitoring/ranging을 시작부터 병렬 수행
4. 화면 OFF 대응 `ScanFilter`가 생기도록 AltBeacon background mode 적용
5. Target UUID가 일치하고 RSSI EMA가 임계값 이상이면 `POST /api/v1/door/prearm`
6. 백엔드가 등록·승인된 기기를 확인하고 MQTT `gatekeeper/arm` 발행
7. Target이 60초간 ARMED가 되고 초음파 20~50 cm를 감지하면 릴레이 동작

따라서 **홈 버튼/일반 백그라운드 전환 또는 Activity가 닫힌 뒤 화면이 꺼지는
상황을 지원하려는 구조는 들어가 있다.**

감사에서 발견한 소프트웨어 결함은 2026-07-30 수정했다. 기본 RSSI 임계값은
주머니 인체 차폐를 고려해 `-85 dBm`으로 조정하고 원격 설정화했다. 다만 최근 앱
스와이프/OEM 절전/강제 종료와 실제 RF·초음파 조건은 실기기 검증이 필요하다.

## 2. “앱 종료” 상태별 판정

| 사용자 상태 | 현재 판정 | 근거/한계 |
|---|---|---|
| 화면 OFF | 조건부 지원 | foreground service + wake lock + filtered scan 설정 |
| 홈 버튼/다른 앱 전환 | 조건부 지원 | 스캔이 UI isolate가 아닌 서비스 isolate에서 실행됨 |
| 뒤로 가기로 Activity 종료 | 조건부 지원 | 서비스가 별도 엔진을 가지며 Manifest에 `stopWithTask=true` 없음 |
| 최근 앱 목록 스와이프 | 설계상 유지, 실기기 검증 필요 | 제조사 ROM 정책에 따라 서비스가 같이 제거될 수 있음 |
| Android 13+ “활성 앱 > 중지” | 미지원 | OS가 foreground service를 포함한 전체 앱을 메모리에서 제거 |
| 설정 > 강제 종료 | 미지원 | 사용자가 앱을 다시 열 때까지 서비스/스캔 재개 불가 |
| OEM 절전/자동 시작 차단 | 보장 불가 | 표준 배터리 최적화 예외만 요청하며 삼성/샤오미 별도 정책은 제어 못 함 |
| 재부팅 후 | 설정은 존재하나 실기기 검증 필요 | `autoRunOnBoot=true`, `RECEIVE_BOOT_COMPLETED` 선언 |
| iOS 화면 OFF/종료 | 보장 판정 불가 | plist 권한은 있으나 이번 Android 서비스-isolate 경로와 동일하게 검증된 구조가 아님 |

## 3. 실제 코드 경로

### 3.1 앱 시작과 서비스

- `main.dart`는 위치(사용 중), Bluetooth scan/connect, 알림 권한을 요청한 뒤
  `ForegroundServiceManager.startService()`를 실행한다.
- `foreground_service.dart`의 `GatekeeperTaskHandler.onStart()`가
  **서비스 isolate에서** `BleScanner().initialize()`를 호출한다.
- `ForegroundTaskOptions`는 `autoRunOnBoot=true`, `allowWakeLock=true`,
  `allowWifiLock=true`다.
- Android Manifest는 `FOREGROUND_SERVICE_CONNECTED_DEVICE`,
  `RECEIVE_BOOT_COMPLETED`, background location, Bluetooth 권한을 선언한다.

이는 과거의 “UI isolate가 죽으면 스캔도 죽는다” 구조에서 개선된 상태다.
관련 코드 주석과 `mobile_app_scan_lifecycle.md`도 현재 구조로 동기화했다.

### 3.2 비콘 감지

- 기본 UUID는 펌웨어와 앱 모두
  `a1b2c3d4-e5f6-7890-abcd-ef1234567890`으로 일치한다.
- 앱은 시작부터 monitoring과 ranging을 병렬 구독한다. 화면 OFF에서
  `didEnterRegion`이 누락돼도 ranging 패킷으로 Pre-arm할 수 있다.
- Android 화면 OFF에서 필터 없는 BLE 스캔 결과가 중단되는 문제를 피하려고
  `setBackgroundMode(true)`를 유지한다.
- background/foreground scan period는 1100 ms, between period는 0 ms다.
- 수신 UUID를 정규화한 뒤 RSSI 0/-1을 버리고 EMA(`alpha=0.3`)를 계산한다.

### 3.3 API 호출 조건

비콘 패킷을 받았다고 즉시 API가 호출되는 것이 아니다. 아래를 모두 만족해야 한다.

1. UUID가 Target UUID와 일치
2. ranging이 ACTIVE 상태
3. RSSI EMA가 `rssiThreshold` 이상(기본 `-85 dBm`, 원격 가변)
4. Pre-arm 요청이 진행 중이 아님
5. 성공 쿨다운(기본 10초) 중이 아님

호출은 다음과 같다.

```text
POST https://tworimpa.synology.me:4442/api/v1/door/prearm
Content-Type: application/json
X-API-KEY: <빌드 시 주입되었을 때만>

{
  "beacon_uuid": "...",
  "device_id": "...",
  "rssi": -NN,
  "timestamp": "ISO-8601"
}
```

HTTP timeout은 4초다. 200이면 10초 쿨다운, 401/403이면 긴 쿨다운,
그 밖의 오류/예외는 2초 후 재시도 가능 상태가 된다.

### 3.4 백엔드와 Target 연계

- 백엔드는 `device_id`가 DB에 등록되어 있고 `is_active=true`인지 확인한다.
- 성공하면 MQTT `gatekeeper/arm`을 발행한다.
- Target은 기본 60초 동안 ARMED 상태를 유지한다.
- 초음파 유효 범위는 “일정 값 이하” 전체가 아니라 **20 cm 이상 50 cm 이하**다.
  20 cm 미만은 센서 맹점 노이즈로 버린다.

## 4. 발견 결함과 수정 결과

| 항목 | 수정 결과 |
|---|---|
| P0-1 초기 ranging 무수신 후 영구 IDLE | 시작부터 ranging 병렬 유지, native callback 6초 무수신 시 10초 최소 간격으로 subscription 재생성 |
| P0-5 화면 OFF monitoring enter 누락 | monitoring을 Pre-arm의 단일 관문에서 제거하고 OUTSIDE에도 ranging 유지 |
| P0-2 UI/service AltBeacon 충돌 | 서비스 isolate 단일 소유로 고정, Debug 직접 스캔 제거, native `removeAll*Notifiers()` 제거 |
| P0-3 background location 미승인 | 교육/설정 화면 추가, “항상 허용”·배터리 예외를 blocker로 승격, 미충족 시 서비스 중지 |
| P0-4 MQTT 실패를 HTTP 200 성공 처리 | QoS 1 PUBACK 확인, 미발행 시 백엔드 503, 앱도 200 body의 `mqtt_published=true` 확인 |
| P1-1 주머니 RSSI | 기본 `-85 dBm`, `APP_RSSI_THRESHOLD` remote config 및 사용자 override 지원 |
| P1-2 진단 오탐 | 전체 `ScanDiagnostics`를 service → UI IPC로 전달, 5초 자동 갱신 |
| P1-3 build ID 기반 device ID | 신규 설치는 random UUID, 기존 `DEV-*`는 서버 등록 호환을 위해 유지 |
| P1-4 배터리/OEM | 표준 배터리 예외는 필수화, 삼성/샤오미 설정 안내 추가 |
| P1-5 빌드 미검증 | Docker Flutter 3.44.8에서 analyze/test/release APK 빌드 통과 |

## 5. 남은 비소프트웨어/플랫폼 검증

1. 최근 앱 스와이프 후 제조사 ROM별 sticky service 생존
2. Android 13+ 활성 앱 “중지” 및 설정 “강제 종료”는 플랫폼상 미지원
3. 삼성/샤오미 별도 절전 정책을 사용자가 실제로 해제했는지
4. 주머니 방향별 RSSI EMA의 `-85 dBm` 통과율
5. Target 초음파의 물리적 유효 범위 20~50 cm

## 6. 필수 실기기 검증

각 테스트 전 앱 데이터와 서버 로그 시간을 맞추고 다음을 20회 이상 반복한다.

| 테스트 | 조작 | 확인 항목 |
|---|---|---|
| A | 앱 실행 → Home → 화면 OFF 5분 → 접근 | service 생존, enter 시각, RSSI, HTTP, MQTT, ARMED |
| B | 최근 앱 스와이프 → 화면 OFF → 접근 | 제조사별 서비스 생존 여부 |
| C | Android 13+ 활성 앱에서 “중지” → 접근 | 미동작이 정상이며 사용자 안내 필요 |
| D | 주머니 방향 4종 × 거리 단계 | raw RSSI/EMA 분포, -85 dBm 통과율 |
| E | 비콘 첫 감지를 6초 이상 지연 | ACTIVE 유지 + ranging 재구독 확인 |
| F | 디버그 화면 진입/이탈 후 화면 OFF | service notifier와 RSSI 유지 확인 |
| G | MQTT broker 차단 후 접근 | HTTP 503·앱 실패 알림·2초 재시도 확인 |
| H | 19 cm / 20 cm / 50 cm / 51 cm | 초음파 경계 동작 |

최소 로그 상관관계는 아래 순서로 한 건의 출입을 추적해야 한다.

```text
service onStart
→ monitoring didEnter/didDetermine INSIDE
→ ranging RSSI/EMA threshold pass
→ app POST /door/prearm
→ backend device approval
→ backend mqtt_published=true
→ Target [MQTT-ARM]
→ Target ARMED
→ ultrasonic valid range
→ relay ON
```
