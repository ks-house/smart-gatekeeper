# 모바일 앱 비콘 스캔 생애주기

## 2026-08-31 off-site native-owner false alert analysis

The owner observed a foreground notification titled `BLE 비콘 스캔 초기화
실패` on the latest installed app while away from home, where no Gatekeeper
Target was present. The notification included the exact
`BLE_OWNER_EXCLUDED` code. Target absence is normal idle state and is not
evidence that Bluetooth, location service or an Android permission was off.

Source tracing establishes the control-path cause. A successful personal
native-GATT feature decision persistently calls `setNativeRequested(true)`.
The vendored Flutter beacon plugin rejects legacy `initializeScanning` whenever
that request marker is true, independently of Target presence and independently
of whether a native GATT session currently holds the kernel lease. The Flutter
foreground scanner still attempts legacy initialization. The earlier issue
#204 correction suppresses only a directly typed `PlatformException` and, on
that suppressed path, does not explicitly replace a preceding failure
notification. The attached alert proves that this runtime attempt entered, or
retained the result of, the generic failure-notification path. Without a
bounded logcat capture the evidence does not distinguish exception wrapping
from a stale notification title, so neither is claimed as the sole mechanism.

The correction must retain mutually exclusive BLE ownership. It must not clear
the signed native-mode request merely because no Target is nearby. Instead:

1. Expose a structured, privacy-safe native ownership mode to the
   foreground-service Flutter engine and model at least `legacy_scanner`,
   `native_wake_idle` and `native_gatt_session` separately.
2. When native wake is authoritative, do not call legacy
   `initializeScanning`. Project Target absence as neutral `감지 대기`; retain a
   bounded transition/watchdog path for authenticated native disable or expiry.
3. Keep exact `BLE_OWNER_EXCLUDED` handling as a fail-safe fallback, but clear
   the stale scanner error and force-replace any preceding failure notification
   with the neutral native-wake state. Do not suppress Bluetooth-disabled,
   permission, location-service, plugin or unexpected ownership failures.
4. Drive resumption from a single-flight structured ownership transition rather
   than a repeated error/recreate loop. The kernel lease, stop-before-native
   ordering, signed feature decision and default-OFF/commercial boundaries stay
   unchanged.
5. Add native coordinator/plugin, Dart scanner-state and notification
   regressions. A latest signed APK must then pass an off-site/no-Target,
   screen-off soak with zero false failure notifications and bounded retries,
   followed by a real Target approach proving native wake, authentication and
   scan-state recovery. OTA install/rollback and ordinary actionable permission
   alerts remain separate required Gates.

The implementation candidate now exposes `getBleOwnershipState` from every
Flutter engine through the vendored beacon plugin. It returns only schema,
mode, native-request and legacy-lease booleans; it carries no Target address,
credential or account data. `BleScanner.startScanning` evaluates that state
before any legacy initialization. Authoritative native wake enters the explicit
`ScanMode.nativeWake`, clears the prior scanner error across isolate IPC and
force-replaces the service notification with neutral `스마트키 감지 대기`.
Monitoring/ranging owner transitions converge through the same single-flight
restart, and the 30-second watchdog polls only for a real native-to-legacy mode
transition. Active GATT session detail remains in the existing native health
journal instead of being guessed from Target absence.

The OTA contract and all 320 Python source/operations regressions pass locally
with one expected PowerShell-only skip. Focused ownership tests cover structured
native/legacy projection, unknown future native mode fail-closed behavior,
native-wake diagnostics and ordering before `initializeScanning`.

PR #318 passed its protected Hosted Trusted, OTA P0 and Flutter/Android canary
checks and merged as exact main
`d9100240c8c9c07faacd2b0c293b46e01462d3ad`. Exact-main mobile run
`33380064991` then passed the production signer/package/source checks and
atomically published signed `1.0.0-gd910024` / `36801` to both NAS roots.
Independent strict-TLS downloads matched the signed CI manifest and the
55,119,001-byte APK at SHA-256
`0f18386709983d157acb23bcb3b7b2b070c123e1d6fef0a27260c12dfc8654f5`
for both primary and fallback paths. This proves artifact publication only.
Replacement installation, an off-site no-Target screen-off soak and real-Target
native wake/authentication recovery remain separate physical Gates.

## 2026-08-29 foreground Target detection dashboard candidate

The Smart Key control screen now reads the native authoritative health bridge
once per second while the screen is mounted. A dedicated privacy-safe card
shows the latest filtered Target event as `감지 대기`, `감지됨`, `인증 진행 중`,
`ARMED`, `실패`, or `비활성`, together with receive time/age, strongest RSSI,
screen ON/OFF, durable session state, and presence-to-ARMED latency.

The native wake journal projection deliberately excludes the BLE address,
credential ID, challenge, proof, token, and key material. The UI applies the
same 45-second `maxPresenceAgeMs` boundary used by the worker and returns to
waiting when an event becomes stale. RSSI is the strongest sample from the
latest OS `FIRST_MATCH` callback; it is not continuous ranging, an ultrasonic
distance, or proof that the user is still beside the Target.

Focused Flutter bridge/stage tests, the complete 43-test Flutter suite, and two
native journal projection tests pass locally. This remains source/test evidence
until a production-signed APK is published, replacement-installed on the
connected phone, and a real approach visibly advances the card through
detected/authenticating/ARMED without exposing sensitive identifiers.

## 2026-08-29 initialization ownership transition UX

Connected exact-main Android `1.0.0-gd614d56` completed background action 1
and foreground action 2 against Target `2.1.302+main.gd614d56`, but the
successful screen still carried a red `BLE 비콘 스캔 초기화 실패` banner.
The foreground-service scanner had called `initializeScanning` while the
native credential worker intentionally held the shared BLE lease; the expected
`BLE_OWNER_EXCLUDED` transition was incorrectly routed through
`AppErrorLogger.logError`.

Issue #204 keeps the existing stopped/watchdog recovery but classifies that one
initialization result as a temporary native-GATT lease. It records a neutral
diagnostic without setting `latestError` or publishing a red failure
notification. Bluetooth-disabled, permission, plugin and all other
initialization failures remain user-visible. This is a source/test correction
until hosted CI, production-signed publication and connected replacement
installation prove the banner is absent during a successful ownership handoff.

## 2026-08-26 native GATT BLE ownership recovery

Connected Samsung evidence for issue #158 showed that the foreground-service
Flutter ranging stream received `BLE_OWNER_EXCLUDED` while the native
credential worker correctly owned BLE. The prior `onError` path immediately
created another subscription without first cancelling the exact failed stream.
That produced a tight error/recreate loop, repeated AltBeacon not-bound
warnings and 3,624 Android notification enqueue attempts during the observed
process lifetime.

The issue #158 candidate treats this code as an expected temporary native-GATT
lease. It clears and cancels only the active subscription generation, tolerates
the same ownership guard during EventChannel cancellation, and coalesces all
errors into one delayed recovery. Native ownership uses a one-second retry;
other stream failures use two seconds. Teardown cancels a pending recovery, and
all actual restart work remains serialized by the existing transition lock.
The foreground service therefore resumes ranging after the native lease ends
without competing with action-1/action-2 GATT or creating concurrent streams.

Four focused Dart recovery tests, three source-order contract tests and the
complete 39-test Flutter suite pass under the exact CI Flutter 3.44.8 toolchain. This is source/test evidence only until a
production-signed APK is built, installed and a screen-off GATT lease shows
bounded log volume plus automatic ranging recovery. It does not classify or
close the separate Target terminal-result defect in issue #156.

> Last updated: 2026-08-31
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

### 2026-07-31 상태바 알림 미표시 진단

`519648b` 업데이트 전에는 초기 권한 요청 결과에 거부 항목이 있어도
`ForegroundServiceManager.startService()`를 호출했다. 업데이트 후에는 아래 조건을
모두 만족할 때만 서비스를 시작하고, 하나라도 부족하면 `stopService()`로 기존
서비스까지 종료한다.

- Android 10+ 백그라운드 위치 “항상 허용”
- Android 12+ Bluetooth scan/connect
- Android 13+ 알림
- 위치 서비스(GPS) ON
- 표준 배터리 최적화 예외

foreground service의 지속 알림이 Android 상태바 표시의 소유자이므로 서비스가
종료되면 상태바 알림도 함께 사라진다. 이 때문에 필수 항목을 확인하기 전의 정적 코드
감사에서는 `main.dart`의 필수 조건 게이트를 1차 후보로 분류했다. 특히 최초 진입에서는 사용자 설명 전이라
백그라운드 위치와 배터리 예외를 자동 요청하지 않고 미충족으로 판정할 수 있다.
설정 화면의 **필수 권한·배터리 예외 다시 요청**을 거쳐 모든 항목을 완료해야 서비스와
알림이 다시 시작된다.

2026-07-31 사용자 후속 확인에서 최신 빌드, 미완료 필수 항목 없음, 거부 권한 없음이
확인되었으므로 해당 기기의 현재 증상에서는 필수 조건 게이트를 직접 원인에서 제외했다.
남은 두 경로는 다음과 같다.

1. 서비스가 시작 후 예외·OS/OEM 정책으로 종료됨
2. 서비스는 실행 중이지만 앱 전체 권한과 별개인 foreground 알림 채널이 차단·숨김됨

현재 `ScanDiagnostics.notification`은 `Permission.notification` 전역 권한만 읽고
`smart_key_foreground_channel`의 실제 importance/차단 상태를 읽지 않는다. 또한
`foregroundServiceRunning=false`는 warning일 뿐 필수 항목 blocker가 아니어서,
“미완료 필수 항목 없음”과 “현재 서비스 실행 중”은 동시에 성립하지 않을 수 있다.
Debug 화면의 **포그라운드 서비스 실행** 값 또는 Android 13+ **활성 앱** 목록으로
두 경로를 먼저 구분해야 한다.

#### 실시간 이벤트·에러 로그 0건 원인

사용자 후속 확인에서 Debug 화면의 실시간 앱 이벤트·에러 로그가 완전히 비어 있음이
확인됐다. 이는 서비스 미실행의 확정 증거가 아니라 현재 IPC 등록 순서 결함으로도
재현된다.

- `ForegroundServiceManager.startService()`는 플러그인 서비스를 먼저 시작한다.
- 서비스 시작이 반환된 뒤에야 `_registerReceivePort()`를 호출한다.
- `flutter_foreground_task` 6.5.0 공식 예제는 서비스 시작 **전에** receive port를
  등록해야 한다고 명시한다.
- 서비스 isolate는 `onStart`에서 받은 nullable `SendPort`를
  `backgroundSendPort`에 저장한다.
- `AppErrorLogger`와 `BleScanner._syncToUi()`는 모두
  `backgroundSendPort?.send(...)`를 사용하고 예외를 비워 두므로 port가 null이면
  이벤트, 에러, 진단 snapshot이 아무 표시 없이 전부 유실된다.
- `onStart` 자체의 시작 메시지는 `AppErrorLogger`가 아닌 `debugPrint`만 사용하므로
  앱 내 이벤트 콘솔에는 원래 나타나지 않는다.

따라서 빈 이벤트 콘솔은 현재 상태에서 서비스 실행/미실행을 판별할 수 없는 진단
blind spot이다. 이 IPC 결함은 foreground 알림 생성·`updateService()` 호출과는 별도
경로이므로 상태바 알림 미표시의 직접 원인으로 단정할 수는 없다. receive port 등록
순서를 고치고 서비스 시작/주기 heartbeat를 UI 로그에 명시적으로 보내거나, 수정 전에는
ADB/Android 13+ 활성 앱 목록으로 서비스 생존을 확인해야 한다.

#### 현재 분석으로 가능한 복구 범위

receive port 선등록만 수정하면 서비스→UI 이벤트, 에러, 진단 snapshot 전달은 복구될
가능성이 높지만 Android foreground 알림은 플러그인의 native service가 별도로 생성하므로
상태바 알림까지 자동 복구된다고 보장할 수 없다. 상태바를 포함한 복구판은 다음 항목을
한 묶음으로 적용·검증해야 한다.

1. 서비스 시작 전에 receive port를 등록하고 null/등록 실패를 시작 실패로 처리
2. `startService()` 직후와 5초 heartbeat에서 실제 `isRunningService`를 확인해 UI에 전달
3. `FlutterForegroundTask.updateService()`를 await하고 false/비동기 예외를 로그에 보존
4. 전역 알림 권한과 별도로 `smart_key_foreground_channel`의 실제 차단/importance를 진단
5. 채널이 사용자에 의해 차단됐으면 앱이 임의로 우회하지 않고 해당 Android 설정으로 안내
6. receive port 선등록, 시작 실패, 서비스 중도 종료, 알림 갱신 실패를 포함한 테스트 추가

이 수정 후에도 OEM 강제 종료나 사용자가 끈 알림 채널은 앱 코드만으로 강제 복구할 수
없다. 완료 판정은 앱 이벤트 heartbeat 수신, Debug의 foreground service 실행=true,
알림 표시, 화면 OFF 실기기 접근 성공을 함께 확인해야 한다.

#### 2026-07-31 복구 구현

복구 코드에는 다음을 적용했다.

1. `startService()`가 `FlutterForegroundTask.receivePort`를 먼저 등록하고 실패하면
   서비스를 시작하지 않도록 변경했다.
2. 서비스 `onStart`/`onRepeatEvent`/`onDestroy`가 UI로 시작·5초 heartbeat·종료를
   전송하고, 초기화와 heartbeat 예외를 앱 내 로그로 보존하도록 변경했다.
3. 알림 갱신을 await하고 false 반환과 비동기 예외를 앱 내 로그에 남기도록 변경했다.
4. 기존 LOW 채널은 Android가 importance를 변경하지 않으므로
   `smart_key_foreground_channel_v2`를 DEFAULT·무음으로 새로 만들어 상태바 표시를
   복구하도록 변경했다.
5. Android native bridge로 앱 전체 알림, 새 채널 존재/차단/importance를 읽고 Debug
   화면의 서비스 실행 행과 채널 상태 행에 표시하도록 변경했다.

Docker Flutter 환경에서 변경 Dart 파일 정적 분석과 기존 단위 테스트는 통과했다.
Android APK/Kotlin 전체 컴파일은 Gradle 초기화가 실행 환경의 2분 명령 제한을 넘어
완료 결과를 얻지 못했으므로, 실제 기기 설치 후 아래 시나리오로 최종 검증해야 한다.

2026-08-01 실기기에서 이벤트 콘솔이 계속 비어 있는 후속 관측으로 자동 실행 경로를
재검토했다. 앱 업데이트 때 `autoRunOnMyPackageReplaced`가 foreground service를 UI
receive port 등록보다 먼저 시작할 수 있는데, 기존 구현은 실행 중인 서비스를 그대로
반환했다. 그러면 해당 service isolate가 최초 `onStart`에서 null `SendPort`를 보존해
모든 IPC가 계속 유실된다. 따라서 receive port 등록 후 실행 중인 서비스를
`restartService()`하고, UI isolate에서 포트 등록·시작/재시작 요청 로그를 직접
기록하도록 보완했다.

1. 앱 실행 직후 실시간 콘솔에 `foreground service 시작`이 나타나는지 확인
2. 5초 뒤 Debug의 서비스·알림 채널 상태와 foreground service 실행=true를 확인
3. 상태바에 새 Smart Key 지속 알림이 나타나는지 확인
4. Home 이동·화면 OFF 뒤 30초 이상 heartbeat가 계속되고 비콘 접근이 동작하는지 확인

#### 2026-08-01 구역 이탈 상태 표시 정합성 수정

`didExitRegion`은 `_resetSignalState()`로 RSSI를 비우지만 ranging을 계속 유지한다.
기존 상태 계산은 RSSI가 null이면 무조건 “구역 내에 있지만 신호가 일시적으로 약함”을
표시해, `구역 이탈 감지 — 병렬 ranging 유지` 로그와 모순됐다.

`_isInsideRegion`을 scan mode와 분리해 추가했다. monitoring INSIDE/OUTSIDE가 이를
갱신하고, OUTSIDE 뒤에도 실제 Target ranging 패킷이 오면 IN으로 즉시 복구한다. 따라서
OUTSIDE 뒤에는 “Target 비콘 구역 밖 — 다음 진입 감시”를 표시하면서 ranging은 계속
유지하고, 화면 OFF에서 monitoring enter가 누락된 경우에도 패킷 수신으로 정상 진입한다.

모든 필수 조건이 충족되고 Debug 화면에서 foreground service가 실행 중인데도 알림만
보이지 않으면 다음 2차 원인을 확인한다.

1. Android 설정에서 앱 전체 알림 또는 `smart_key_foreground_channel` 채널이 꺼졌는지
2. 활성 앱 화면/강제 종료/OEM 절전 정책으로 service process가 제거됐는지

현재 단위 테스트는 `ScanDiagnostics.canScan`의 개별 blocker만 검증하고
`_initializeApp()`이 서비스 시작/종료를 선택하는 통합 경로와 알림 표시 자체는
검증하지 않는다. 또한 receive port 선등록과 서비스→UI 로그 전달을 검증하는 테스트도
없다. 따라서 IPC 수정 전 최종 원인 항목은 실기기 Android 서비스 상태나 ADB로
확정해야 한다.

### 지원 범위 결론

현재 코드 계약상 **화면 OFF, Home 이동, 뒤로 가기로 UI Activity 종료**에서는 계속
동작한다. BLE 소유자는 UI가 아니라 foreground-service FlutterEngine/isolate이고,
vendored beacon plugin도 Activity detach 때 scanner channel/binding을 해제하지 않는다.
따라서 UI 화면이 없어져도 서비스 알림과 service process가 살아 있으면 병렬
monitoring/ranging 및 Pre-arm은 계속 수행된다.

단, 여기서 "앱 종료"는 상태가 서로 다르다.

- Home/다른 앱/뒤로 가기 UI 종료: 지원
- 최근 앱 스와이프: 표준 동작상 sticky service 유지·재시작 대상이지만 OEM 실측 필요
- Android 13+ 활성 앱 화면의 `중지`: 미지원
- 설정의 `강제 종료`: 미지원, 사용자가 앱을 다시 열어야 함
- 삼성/샤오미 등 OEM이 service process를 강제 정리: 코드만으로 보장 불가

즉 **정상적인 화면 OFF/UI 종료는 설계상 동작한다**가 정확한 답이고, 모든 제조사에서
강제 종료까지 무조건 동작한다고 보장하는 것은 아니다. 아직 새 병렬-ranging APK의
화면 OFF·UI 종료 실기기 반복시험이 완료되지 않았으므로 "검증 완료"가 아니라
"구현 완료, 실기기 검증 필요" 상태다.

| 상황 | 현재 동작 |
|---|---|
| 앱 포그라운드 | 서비스 isolate에서 monitoring + ranging 계속 스캔 |
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
STOPPED ── 필수 조건 충족 ──▶ ACTIVE (monitoring + ranging 병렬)
ACTIVE ── didEnterRegion / INSIDE ──▶ 진입 진단 기록, ranging 유지
ACTIVE ── didExitRegion / OUTSIDE ──▶ 신호 상태 초기화, ranging 유지
ACTIVE ── ranging callback 6초 무수신 ──▶ ranging 구독 재생성
```

| 모드 | monitoring | ranging | Pre-arm |
|---|---|---|---|
| STOPPED | ✗ | ✗ | ✗ |
| ACTIVE | ✓ | ✓ | RSSI 조건 충족 시 |

중요한 복구 규칙:

- 화면 OFF에서 monitoring enter callback이 누락돼도 출입할 수 있도록 ranging을
  시작 시점부터 병렬로 유지한다. monitoring과 ranging은 같은 native scan cycle을
  공유하므로 별도 radio scan을 추가하지 않는다.
- native OUTSIDE 오판 때 ranging을 끄면 다음 enter까지 누락될 경우 영구 정지하므로
  신호 표시만 초기화하고 ranging subscription은 유지한다.
- Target이 없어도 발생해야 하는 빈 ranging callback까지 6초간 없으면 Dart stream
  객체가 살아 있어도 native silent stall로 판단하고 subscription을 재생성한다.
- 재생성 최소 간격은 10초다.
- monitoring/ranging stream error는 해당 구독을 null로 표시한 뒤 자동 재시작한다.
- 30초 watchdog은 필수 조건과 monitoring subscription을 확인한다.

#### 2026-08-01 알림창 복귀 시 스캔 재시작·오경고 제거

알림창을 닫아 앱이 `resumed`가 될 때 초기화 루틴이 다시 실행된다. 기존에는 IPC
heartbeat가 이미 UI에 연결된 foreground service도 무조건 `restartService()`로
재시작해 scanner 초기화가 반복됐다. 이제 health가 실행 중으로 확인된 서비스는
재시작하지 않고 상태만 새로고침한다. 자동 실행·업데이트 직후처럼 heartbeat가 아직
없는 서비스만 재시작해 IPC를 복구한다.

또한 `setBackgroundMode(true)`를 호출하기 전 진단의 false 값을 콘솔 경고로 기록하던
순서를 수정했다. 설정 적용 뒤에만 warning을 기록하며, native API가 예외 없이 false를
반환하는 경우도 실제 적용 실패로 처리한다.

#### 2026-08-01 화면 OFF RSSI gate 임시 우회

현장 진단을 위해 foreground-service engine에서 Android
`PowerManager.isInteractive()`를 조회한다. 화면 OFF 중에는 Target UUID 패킷이
수신되는지만 분리 확인할 수 있도록 RSSI 임계값을 임시 우회한다. 중복 Pre-arm 요청은
기존 cooldown 정책으로 제한하며, Target이 IDLE에서만 ARM을 수락해 상태 전이 순서를
보장한다.
이 우회는 장기 운영 설정이 아니며 화면 OFF 수신 검증 뒤 제거한다.

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
