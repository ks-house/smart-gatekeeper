# 모바일 앱 화면 OFF·앱 종료 접근 시나리오 구현 감사

> 감사일: 2026-07-30
> 범위: `gatekeeper_app`의 Android 백그라운드 비콘 감지 → Pre-arm REST API 호출 경로
> 관련 문서: [mobile_app_scenario.md](mobile_app_scenario.md) · [mobile_app_scan_lifecycle.md](mobile_app_scan_lifecycle.md)

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
