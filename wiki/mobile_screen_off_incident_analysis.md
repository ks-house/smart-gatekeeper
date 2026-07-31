# Android 화면 OFF 출입 실패 상세 분석

> 분석일: 2026-07-31  
> 범위: Android 화면 OFF → iBeacon 감지 → REST Pre-arm → MQTT → Target 릴레이  
> 판정 원칙: 소스 감사로 확인한 사실과 실기기 로그가 필요한 가설을 분리한다.
>
> 추가 현장 증거: 같은 날 아침 앱/화면 ON에서는 출입 성공, 화면 OFF에서는 실패.

## 1. 요약 결론

추가된 A/B 결과 때문에 이전 판정을 수정한다. 두 시험이 **짧은 시간 간격, 같은
휴대폰 위치·방향·거리, 같은 사용자/Target** 조건이었다면 화면 OFF와 연결된 모바일
경로 결함일 가능성이 높다. 앱/화면 ON 성공은 그 시점에 비콘 UUID, 사용자 승인,
Backend→MQTT, Target ARMED, 초음파와 relay의 전체 체인이 적어도 한 번 정상
동작했음을 증명한다. 따라서 이 공통 구간들은 1차 원인 후보에서 후순위로 내린다.

아직 확정되지 않은 것은 화면 OFF 뒤 **서비스가 죽었는지**, 서비스는 살았지만
**monitoring callback이 멈췄는지**, 또는 화면을 끄면서 휴대폰 자세/주머니가 바뀌어
**RSSI gate를 통과하지 못했는지**다. 이 세 가지를 구분할 실패 시각의 휴대폰 로그가
없으므로 정확한 코드 지점까지 단정하지는 않는다.

다만 우선순위는 다음과 같다.

1. **화면 OFF 1순위:** foreground-service가 OEM 절전 정책으로 제거되거나,
   AltBeacon monitoring이 화면 OFF에서 enter 이벤트를 만들지 못하는 경우다.
   기존 앱은 ranging을 상시 수행하지 않고 `didEnterRegion` 또는 `INSIDE` 판정 뒤에만
   시작하므로 monitoring이 조용히 멈추면 RSSI와 HTTP 요청도 전부 발생하지 않는다.
   이 단일 관문은 2026-07-31 코드에서 제거해 monitoring과 ranging을 시작부터 병렬
   유지하고, native ranging callback 6초 무수신을 자동 복구하도록 개선했다.
2. **화면 OFF 행동과 결합된 RF 후보:** 비콘을 받아도 RSSI EMA가 기본 `-85 dBm`
   이상이어야 한다. 화면을 끄면서 주머니/가방에 넣었다면 화면 상태가 아니라 인체
   차폐 때문에 실패했을 수 있다. 화면 OFF 상태에서도 손에 든 채 같은 자세로
   실패했는지가 중요한 분기다.
3. **별도로 확인된 현재 운영 장애:** 2026-07-31 02:32 UTC에 공개 Backend의
   `/health`, `/api/v1/config`, `/api/v1/download/version.json`가 모두 최종 HTTP
   503과 `upstream ... Connection refused`를 반환했다. 이 상태에서는 휴대폰이
   비콘을 정상 감지해도 Pre-arm REST 요청이 Target까지 전달될 수 없다. 이는
   화면 ON/OFF 공통 장애다. 아침의 ON 성공과 OFF 실패가 연속 시험이었다면 당시
   Backend 장애가 두 결과를 갈랐다고 보기는 어렵지만, 현재 재시험 전에 복구해야 한다.
4. **배포 버전 후보:** 소스에 수정이 있어도 설치 APK가 해당 commit 기반인지
   별도 확인해야 한다. 운영 APK workflow는 `main` push 또는 수동 실행 때만 NAS에
   배포하며, NAS version endpoint도 분석 시점 503이라 설치 버전을 원격 확인하지
   못했다.

따라서 현재 결론은 **화면 OFF 모바일 경로 문제를 우선 조사하되**, 현재 Backend
503을 복구한 뒤 화면만 바꾸는 즉시 연속 A/B 시험으로 service → monitoring →
ranging 중 끊기는 지점을 찾는 것이다.

## 1.1 새 A/B 증거가 배제하거나 남기는 것

두 시험의 시간·자세·거리 조건이 같았다는 전제에서 우선순위는 다음처럼 바뀐다.

| 항목 | 새 판정 | 이유 |
|---|---|---|
| 비콘 UUID 불일치 | 가능성 매우 낮음 | ON 시험에서 같은 앱이 출입 성공 |
| 사용자/기기 미승인 | 가능성 매우 낮음 | ON 시험의 Pre-arm 승인이 전체 체인을 통과 |
| Target relay/센서 상시 고장 | 가능성 매우 낮음 | ON 시험에서 실제 출입 성공 |
| Backend/MQTT 상시 장애 | 아침 원인 가능성 낮음 | 인접 시험이면 ON 성공과 양립하기 어려움 |
| 화면 OFF service/OEM kill | 가능성 높음 | 화면 상태에 직접 종속 |
| monitoring/ranging silent stall | 가능성 높음 | 화면 OFF에서만 BLE callback이 멈출 수 있는 경로 |
| 주머니/자세 RSSI 차이 | 조건부로 높음 | OFF와 함께 자세가 달라졌다면 교란 변수 |
| 쿨다운 | 시험 순서에 따라 가능 | ON 성공 직후 OFF 시험이면 기본 성공 쿨다운 중일 수 있음 |

마지막 `쿨다운`은 반드시 확인해야 한다. 현재 앱은 성공 뒤 기본 10초 동안 다음
Pre-arm을 차단한다. **ON 성공 직후 10초 안에 화면을 끄고 다시 시험했다면**, 화면
OFF 결함이 아니라 정상 쿨다운 때문에 두 번째 요청이 생략됐을 수 있다. 재시험은
각 회차 사이를 최소 15초 이상 띄우거나 진단 설정에서 cooldown 무시를 사용한다.

## 2. 실제 코드 경로와 실패 분기

```text
Android process/service 생존
  → 필수 권한·GPS·배터리 예외 확인
  → AltBeacon monitoring + ranging 병렬 구독 (ACTIVE)
  → didEnterRegion/INSIDE는 진단에 사용하되 RSSI 수신의 전제조건으로 사용하지 않음
  → UUID 일치 + 유효 RSSI + EMA >= threshold
  → POST /api/v1/door/prearm (4초 timeout)
  → HTTP 200 + result=armed + mqtt_published=true
  → Target ARMED
  → 초음파 20~50 cm
  → relay ON
```

| 마지막으로 확인되는 증거 | 실패 구간 | 해석 |
|---|---|---|
| foreground 알림 없음 | 서비스 시작/생존 전 | 권한, 알림, 강제 종료, OEM 절전, 구버전 APK 확인 |
| 알림은 있으나 `monitoringSubscribed=false` | scanner 초기화 | native bind/stream 오류 가능 |
| monitoring=true, ranging callback 없음 | 화면 OFF native scan | 6초 watchdog 재구독 후에도 지속되면 AltBeacon/OEM 단계 |
| ranging callback 있음, beacon 없음 | RF/ScanFilter | 비콘 광고·필터·휴대폰 RF 수신 단계 |
| RSSI 있음, EMA가 -85 미만 | RF gate | 주머니 차폐·거리·비콘 출력 문제 |
| EMA 통과, Pre-arm 기록 없음 | cooldown/in-flight | 성공 쿨다운 또는 요청 guard 확인 |
| status 없음/통신 오류 | 휴대폰→Backend | DNS/TLS/인터넷/Backend 503; 현재 운영 관측과 일치 |
| HTTP 401/403 | 인증/등록 | API key 불일치 또는 기기 미승인 |
| HTTP 503 | Backend→MQTT | broker PUBACK 실패 또는 Backend 자체 unavailable |
| `mqtt_published=true`, Target ARMED 없음 | MQTT→Target | Target online/subscription/command 처리 확인 |
| ARMED, relay 없음 | 센서/릴레이 | 20~50 cm 거리와 하드웨어 확인 |

## 3. 소스에서 확인된 화면 OFF 방어

- BLE 소유자는 UI isolate가 아니라 foreground-service isolate다. Activity가
  background로 가도 동일 service engine에서 `BleScanner.initialize()`를 수행한다.
- 서비스는 sticky 알림, 5초 repeat, wake lock, Wi-Fi lock, boot/package-replace
  자동 실행으로 설정되어 있다.
- Android Manifest에는 background location, Android 12+ Bluetooth,
  Android 13+ notification, connected-device foreground-service 권한이 선언돼 있다.
- 스캔 시작 전에 권한, Bluetooth, GPS, 배터리 최적화 예외를 blocker로 확인한다.
- background mode와 foreground/background scan period를 적용하며 적용 실패를
  진단 값으로 남긴다.
- Activity detach에서 native 채널과 BeaconManager binding을 제거하지 않도록
  vendored plugin이 수정되어 있다.

이 구조는 화면 OFF 지원의 **필요조건**이지 실기기 성공 증거는 아니다. 특히
서비스 알림이 보인다는 사실만으로 native scan callback, REST 성공, Target 동작을
증명하지는 않는다.

## 4. 원인 후보 우선순위

### P0 — Backend가 현재 503

분석 시각의 세 endpoint 모두 proxy 연결 후 upstream connection refused였다. 앱의
Pre-arm은 동일 host/port를 사용하고 4초 timeout을 적용하므로 운영 상태가 같다면
`통신 오류` 또는 HTTP 503으로 실패한다. 먼저 container/process/listener와 reverse
proxy upstream을 복구하고 `/health`, `/api/v1/config`, `/door/prearm` 경로를 재검증해야
한다. 이 문제가 남아 있으면 화면 OFF 스캐너를 튜닝해도 문은 열리지 않는다.

### P0 — 실패 APK가 최신 background hardening을 포함하는지 불명

설치 화면의 package version/build number와 NAS `version.json`의 commit을 비교해야
한다. `pubspec.yaml`의 정적 버전 문자열만 보면 안 되며 workflow가 주입한
`1.0.0-g<sha>`와 build number를 확인해야 한다. 소스 수정과 현장 설치는 서로 다른
사실이다.

### P1 — service/OEM kill

표준 배터리 최적화 예외를 받더라도 삼성 절전 앱, 샤오미 자동 시작 제한 등 제조사
정책이나 Android의 사용자 `중지`/강제 종료는 별개다. 실패 직후 foreground 알림이
사라졌거나 `adb shell dumpsys activity services`에 service가 없다면 이 후보가
강하다. 설정의 강제 종료 또는 Android 13+ 활성 앱 `중지` 뒤 자동 동작은 지원할 수
없으며 사용자가 앱을 다시 열어야 한다.

### P1 — monitoring 단일 관문

기존 구현은 IDLE에서 monitoring만 구독하고 enter/INSIDE 콜백 뒤에야 ranging을
시작했다. Dart watchdog도 stream subscription 객체가 null인지 검사했으므로 객체는
살아 있고 native callback만 멈춘 상태를 감지하지 못했다. 따라서 과거의
`monitoringSubscribed=true`는 실제 광고 수신의 증거가 아니었다.

이 위험에 대해 다음 코드 개선을 적용했다.

- monitoring enter를 기다리지 않고 시작부터 ranging을 병렬 구독
- OUTSIDE callback에도 ranging을 취소하지 않고 신호 표시만 초기화
- 빈 결과를 포함한 ranging callback이 6초간 없으면 silent stall로 판단해 재구독
- 권한/GPS 등 전제조건 상실 시 전체 scanner preflight를 다시 실행해 복구

monitoring과 ranging은 AltBeacon의 같은 native scan cycle을 공유한다. 다만 Dart로
전달되는 빈 ranging callback 처리량은 늘 수 있으므로 실기기 배터리 소모를 함께
측정한다.

### P1 — 시험 순서에 따른 성공 쿨다운

화면 ON 성공 시험을 먼저 하고 곧바로 화면 OFF 시험을 했다면 앱의 기본 10초 성공
쿨다운이 남아 있을 수 있다. 이때 비콘과 RSSI가 정상이어도 `_nextPrearmAllowedAt`
이전에는 REST 요청을 보내지 않는다. 화면 OFF에서만 실패한 것처럼 보이지만 실제로는
두 번째 시험의 순서 효과다. OFF→ON 순서도 수행하고 회차 간 15초 이상 기다려
배제한다.

### P1 — 주머니 차폐와 RSSI gate

실제 API 호출 조건은 단순 UUID 감지가 아니라 EMA `>= -85 dBm`이다. 화면을 끄는
행동과 주머니에 넣는 행동이 동시에 일어나면 사용자는 화면 OFF 문제로 인식하지만
실제 분기는 RF gate일 수 있다. raw RSSI/EMA를 화면 ON 손-held, 화면 OFF 책상,
화면 OFF 주머니 네 조건으로 각각 20회 측정해 분리한다.

### P2 — downstream 센서 조건

Pre-arm 성공 뒤에도 문은 즉시 열리지 않는다. Target은 ARMED 상태에서 초음파가
20~50 cm일 때만 relay를 동작시킨다. 앱 알림에 승인 완료가 남았는데 문만 열리지
않았다면 모바일 화면 OFF 분석을 중단하고 Target ARMED, 거리, relay 로그로 넘어간다.

## 5. 재현 및 수집 절차

### 5.1 사전 확인

1. 공개 `/health`와 `/api/v1/config`가 200인지 확인한다.
2. 설치 앱의 version/build/commit을 기록하고 최신 운영 APK와 비교한다.
3. 앱 설정 화면에서 위치 `항상 허용`, 근처 기기, 알림, GPS ON, 배터리 최적화
   제외를 확인한다.
4. 제조사별 절전/자동 시작 제한도 해제한다.
5. Target availability/status heartbeat와 firmware version을 기록한다.

### 5.2 통제 실험

같은 위치·방향·거리에서 각각 20회 실시한다. 각 회차는 성공 쿨다운을 피하도록
최소 15초 간격을 두고, 시험 순서는 A→B로 고정하지 말고 교차하거나 무작위화한다.

| 실험 | 화면 | 휴대폰 위치 | 목적 |
|---|---|---|---|
| A | ON | 손 | 기준 성공률 |
| B | OFF | 책상/손과 같은 방향 | 화면 상태만 분리 |
| C | ON | 주머니 | 차폐만 분리 |
| D | OFF | 주머니 | 실제 사용 복합 조건 |

각 회차마다 아래 시각을 한 줄로 묶는다.

```text
service alive
→ monitoring enter/INSIDE
→ first ranging callback + raw/EMA RSSI
→ threshold pass
→ POST start/status/body
→ backend approval/PUBACK
→ Target arm receive/state
→ ultrasonic distance
→ relay ON/OFF
```

### 5.3 Android 현장 명령 예시

```bash
adb shell dumpsys activity services com.kshouse.gatekeeper_app
adb shell dumpsys deviceidle whitelist | grep com.kshouse.gatekeeper_app
adb shell dumpsys package com.kshouse.gatekeeper_app
adb logcat -v threadtime Flutter:D RANGING:D MONITORING:D BeaconManager:D '*:S'
```

`grep` 예시는 현장 단말 명령이며 저장소 lint 규칙과 무관하다. logcat은 화면을 끄기
전부터 켜고 실패 뒤까지 보존해야 한다. 화면을 다시 켜 앱 Debug 화면만 보면 화면
복귀 과정에서 상태가 바뀌어 원래 실패를 오판할 수 있다.

## 6. 판정 기준

- **화면 OFF 앱 결함 확정:** B만 반복 실패하고 service는 생존하며 Backend/Target은
  정상인데 monitoring 또는 ranging callback이 OFF 구간에서만 끊기는 증거가 있다.
- **OEM service kill 확정:** OFF 뒤 service process/foreground notification이
  사라지고 시스템 로그에 kill/stop 근거가 있다.
- **RF 원인 확정:** ON/OFF보다 주머니 여부에 따라 EMA threshold 통과율이 갈린다.
- **Backend 원인 확정:** threshold pass/POST가 있고 같은 시각 503 또는 connection
  refused가 있으며 화면 ON 요청도 동일하게 실패한다.
- **Target 원인 확정:** 앱이 `mqtt_published=true`를 받았지만 Target arm/relay chain의
  특정 단계가 없다.

현재 최종 판정은 **아침의 통제 조건이 동일했다면 화면 OFF와 연관된 모바일
service/scan 경로가 1순위**다. 단, ON 성공 직후 10초 이내 OFF 시험이었다면 성공
쿨다운을 먼저 배제해야 한다. Backend 운영 장애는 이후 별도로 직접 관측됐으므로
재시험 전 복구가 필요하고, service kill과 native callback stall 중 정확한 지점은
실기기 상관 로그가 있어야 확정된다.
