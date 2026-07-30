# 모바일 앱 비콘 스캔 생애주기

> Last updated: 2026-07-30
> 대상: Android Smart Key 앱
> 관련 문서: [mobile_app_background_audit.md](mobile_app_background_audit.md) · [mobile_app_scenario.md](mobile_app_scenario.md)

## 1. 현재 구조

BLE 스캔의 유일한 소유자는 foreground-service Flutter isolate다.

```text
Android process
├── UI FlutterEngine / isolate
│   ├── 권한 온보딩
│   ├── WebView / Debug UI
│   ├── 서비스 상태 수신·표시
│   └── SharedPreferences를 통한 설정 저장
│
└── flutter_foreground_task service FlutterEngine / isolate
    ├── BleScanner.initialize()
    ├── AltBeacon monitoring / ranging
    ├── RSSI EMA·히스테리시스
    ├── Pre-arm REST API
    └── 5초마다 전체 진단·설정 동기화
```

UI는 `flutter_beacon`의 monitoring/ranging을 직접 호출하지 않는다. 이 원칙을
깨면 application singleton인 AltBeacon `BeaconManager`의 notifier와 region 상태가
여러 FlutterEngine 사이에서 충돌할 수 있다.

네이티브 fork도 `removeAllRangeNotifiers()` /
`removeAllMonitorNotifiers()`를 사용하지 않고 자기 notifier만 교체한다.

## 2. 시작 조건

앱은 다음 항목을 모두 충족하기 전에는 foreground service를 시작하지 않는다.

- 위치 사용 중 권한
- Android 10+ 백그라운드 위치 “항상 허용”
- Android 12+ Bluetooth scan/connect
- Android 13+ 알림
- 휴대폰 위치 서비스(GPS) ON
- 표준 배터리 최적화 예외

부족한 항목이 있으면 전용 설정 화면을 표시하고 이미 실행 중인 서비스도 중지한다.
`ScanDiagnostics.canScan`도 백그라운드 위치와 배터리 예외를 blocker로 취급하므로,
재부팅 자동 시작 시 권한이 취소된 상태에서도 가짜 “감시 중”으로 진행하지 않는다.

삼성 절전 앱, 샤오미 자동 시작/배터리 제한 등 OEM 정책은 Android 표준 API로
자동 해제할 수 없으므로 설정 화면에 제조사별 안내를 표시한다.

## 3. 서비스 생애주기

| 상황 | 현재 동작 |
|---|---|
| 앱 포그라운드 | 서비스 isolate에서 계속 스캔 |
| Home/앱 전환 | 계속 스캔 |
| 화면 OFF | filtered background scan으로 계속 스캔 |
| Activity 종료 | 서비스 FlutterEngine이 별도이므로 계속 스캔 |
| 최근 앱 스와이프 | 표준 Android에서는 sticky service 유지, OEM별 실측 필요 |
| 앱 업데이트 | `autoRunOnMyPackageReplaced=true`로 재시작 |
| 재부팅 | `autoRunOnBoot=true` + `RECEIVE_BOOT_COMPLETED` |
| Android 13+ 활성 앱 “중지” | 전체 앱이 종료되므로 미동작 |
| 설정 > 강제 종료 | 사용자가 앱을 다시 열기 전까지 미동작 |

서비스 설정:

| 항목 | 값 |
|---|---:|
| repeat event | 5초 |
| sticky | true |
| wake lock | true |
| Wi-Fi lock | true |
| auto run on boot | true |
| auto run after package replace | true |

## 4. 스캔 상태 머신

```text
STOPPED ── 필수 조건 충족 ──▶ IDLE
IDLE ── didEnterRegion / didDetermineState(INSIDE) ──▶ ACTIVE
ACTIVE ── didExitRegion / didDetermineState(OUTSIDE) ──▶ IDLE
ACTIVE ── RSSI 6초 무수신 ──▶ ACTIVE 유지 + ranging 구독 재생성
```

| 모드 | monitoring | ranging | Pre-arm |
|---|---|---|---|
| STOPPED | ✗ | ✗ | ✗ |
| IDLE | ✓ | ✗ | ✗ |
| ACTIVE | ✓ | ✓ | RSSI 조건 충족 시 |

중요한 복구 규칙:

- native region이 `INSIDE`인데 ranging 무수신을 이유로 IDLE로 내리면 다음
  `didEnterRegion`이 오지 않아 영구 정지할 수 있다.
- 따라서 6초 무수신 시 ACTIVE를 유지하고 ranging subscription만 직렬화해
  재생성한다.
- 재생성 최소 간격은 10초다.
- monitoring/ranging stream error는 해당 구독을 null로 표시한 뒤 자동 재시작한다.
- 30초 watchdog은 필수 조건과 monitoring subscription을 확인한다.

## 5. 화면 OFF 스캔 설정

Android는 화면이 꺼졌을 때 ScanFilter 없는 BLE scan 결과를 중단할 수 있다.
현재 설정은 다음과 같다.

| 설정 | 값 |
|---|---:|
| `setBackgroundMode` | true |
| background scan period | 1100 ms |
| background between period | 0 ms |
| foreground scan period | 1100 ms |
| foreground between period | 0 ms |
| scheduled scan jobs | false |

AltBeacon background mode는 ScanFilter를 사용하지만 LOW_POWER scan mode를 선택한다.
따라서 최악 발견 지연은 수 초가 될 수 있다. 반응 시간은 실기기 20회 이상 측정해
p95로 관리한다.

## 6. 비콘에서 Pre-arm까지

기본 Target UUID:

```text
a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

API 호출 조건:

1. UUID 일치
2. ACTIVE ranging
3. 유효 RSSI
4. RSSI EMA가 threshold 이상
5. 요청 진행 중/성공 쿨다운 아님

현재 기본 RSSI threshold는 `-85 dBm`이다. 백엔드
`APP_RSSI_THRESHOLD` → `/api/v1/config`로 원격 변경할 수 있고, 사용자가 디버그
화면에서 직접 저장하면 로컬 설정이 우선한다.

Pre-arm 성공은 단순 HTTP 200이 아니라 아래를 모두 확인한다.

```json
{
  "result": "armed",
  "mqtt_published": true
}
```

백엔드 MQTT QoS 1 PUBACK가 확인되지 않으면 HTTP 503을 반환한다. 앱도 방어적으로
200 body를 검사하며 MQTT 미발행이면 성공 알림을 표시하지 않고 2초 후 재시도한다.

## 7. UI 상태 동기화

서비스 → UI IPC에는 다음을 포함한다.

- raw/EMA RSSI
- packet count, 연결 여부, mode/state
- Target UUID
- RSSI threshold, cooldown, ignore cooldown
- 권한·OS 스위치
- monitoring/ranging subscription
- 마지막 region/ranging/prearm/error

Debug 화면은 이 snapshot만 표시한다. 새로고침을 위해 UI에서 별도 scanner를
시작하지 않으며 서비스가 5초마다 자동 갱신한다.

UI에서 변경한 RSSI/cooldown 설정은 SharedPreferences에 저장되고 서비스가 5초
주기로 읽어 반영한다.

## 8. 기기 식별자

신규 설치는 OS build ID를 사용하지 않고 cryptographic random UUID를 생성해
SharedPreferences에 보존한다.

기존 설치의 `DEV-*` 값은 서버 등록이 갑자기 끊기지 않도록 그대로 유지한다.
앱 삭제 후 재설치하면 새 ID가 생성되므로 관리자 재승인이 필요하다.

## 9. 신고 대응 순서

문이 열리지 않으면 다음 순서로 한 출입 건을 추적한다.

1. 설치 앱이 최신 빌드인지 확인
2. 앱 설정 화면에 미완료 필수 항목이 없는지 확인
3. foreground service 알림 생존 확인
4. Debug snapshot의 monitoring/ranging/mode 확인
5. packet count와 EMA가 `-85 dBm` threshold를 통과했는지 확인
6. 앱 마지막 Pre-arm status/body 확인
7. 백엔드 `mqtt_published=true` 확인
8. Target `[MQTT-ARM]` 및 ARMED 확인
9. 초음파 유효 거리 20~50 cm 확인
10. relay ON 로그 확인

실기기 필수 시나리오는
[mobile_app_background_audit.md](mobile_app_background_audit.md#6-필수-실기기-검증)를
따른다.
