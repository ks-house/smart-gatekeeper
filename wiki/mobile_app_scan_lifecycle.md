# wiki/mobile_app_scan_lifecycle.md — 모바일 앱 비콘 스캔 생애주기와 잔존 한계

> **작성**: 2026-07-29 (브랜치 `fix/beacon-rssi-and-power`)
> **관련 문서**: [issue.md](../issue.md) · [IMPLEMENTATION_REPORT.md](../IMPLEMENTATION_REPORT.md) · [mobile_app_scenario.md](mobile_app_scenario.md)
> **대상 코드**: `gatekeeper_app/lib/services/ble_scanner.dart`, `foreground_service.dart`, `main.dart`,
> `gatekeeper_app/android/app/libs/flutter_beacon_local/**`

이 문서는 **"앱이 살아 있는 조건"** 을 정리한다. 비콘 감지가 되지 않는다는 신고를 받았을 때 가장 먼저 확인할 표는 [§3 상황별 동작 매트릭스](#3-상황별-동작-매트릭스)다.

---

## 1. Android 플랫폼 제약 (이 설계 전체의 전제)

이 절의 내용은 우리 코드의 선택이 아니라 **Android 플랫폼이 강제하는 사실**이다. 여기서 잘못 가정하면 이후 모든 판단이 무너진다.

### 1.1 Android에는 "OS가 죽은 앱을 비콘으로 깨우는" API가 없다

iOS CoreLocation의 region monitoring은 앱이 종료된 상태에서도 OS가 앱을 깨워준다. **Android에는 대응 기능이 없다.** AltBeacon의 `didEnterRegion`도 결국 **우리 프로세스가 직접 스캔을 돌린 결과**다.

따라서 Android에서 "비콘으로 앱이 깨어난다"는 표현은 정확히 이렇게 읽어야 한다:

> 포그라운드 서비스로 프로세스를 살려 둔 상태에서, 우리가 돌리는 저전력 스캔이 비콘을 발견하면 앱 내부 상태를 IDLE → ACTIVE로 승격한다.

프로세스가 죽으면 그것으로 끝이다.

### 1.2 화면이 꺼지면 ScanFilter 없는 스캔 결과는 폐기된다

Android 8.1(API 27) 이상에서 화면이 꺼진 동안에는 **`ScanFilter`가 없는 BLE 스캔의 결과가 앱에 전달되지 않는다.** 스캔 자체는 오류 없이 "성공"하고 결과만 0건이다. 포그라운드 서비스가 살아 있어도 무관하다.

### 1.3 AltBeacon에서 필터와 스캔 모드는 하나의 플래그로 묶여 있다

| `setBackgroundMode()` | ScanSettings | ScanFilter | 화면 OFF |
|---|---|---|---|
| `false` (기본값) | `SCAN_MODE_LOW_LATENCY` | **없음** | ❌ 결과 0건 |
| `true` | `SCAN_MODE_LOW_POWER` | **있음** | ✅ 동작 |

공개 API로는 "필터 + LOW_LATENCY" 조합을 만들 수 없다. 그래서 우리는 **`setBackgroundMode(true)`를 화면이 켜져 있을 때도 유지**한다. `false`로 되돌리면 필터가 사라져 화면 OFF에서 다시 죽는다.

그 대가로 발견 지연이 늘어난다 — §4 참조.

### 1.4 `setEnableScheduledScanJobs(false)`가 필요하다

`true`로 두면 AltBeacon이 스캔을 JobScheduler(`ScanJob`)에 위임하고 백그라운드 최소 주기(약 15분)에 묶인다. 자체 포그라운드 서비스를 쓰는 우리 구조에서는 반드시 `false`이며, **바인딩 전에** 호출해야 한다.

### 1.5 monitoring과 ranging은 같은 스캔 사이클을 공유한다

ranging을 추가로 켜는 것 자체가 스캔 횟수를 늘리지 않는다. **전력을 결정하는 변수는 스캔 듀티 사이클과 ScanSettings 모드다.**

즉 IDLE 모드에서 절감되는 것은 라디오가 아니라 다음이다:
ranging 콜백 파싱(약 1Hz) · `ValueNotifier` 갱신 · 알림 갱신 IPC · `Timer.periodic` · Pre-arm HTTP 시도.

무시할 수 없는 양이지만, **"IDLE이면 전력을 거의 안 쓴다"는 기대는 틀렸다.**

---

## 2. 현재 구조

### 2.1 2단 전력 상태 머신 (`BleScanner`)

```
STOPPED ──(startScanning: 프리플라이트 통과)──▶ IDLE ──(구역 진입)──▶ ACTIVE
   ▲                                             ▲                     │
   └──(stopScanning / 프리플라이트 실패)          └──(이탈 / 무수신 10초)┘
                                                         │
                                        디버그 화면 열림: 강등 보류
```

| 모드 | monitoring | ranging | RSSI | 타임아웃 타이머 |
|---|---|---|---|---|
| STOPPED | ✗ | ✗ | — | ✗ |
| IDLE | ✓ | ✗ | 안 나옴 | ✗ |
| ACTIVE | ✓ | ✓ | 약 1Hz | ✓ |

ACTIVE 승격 트리거는 **두 가지**다. 둘 다 처리해야 한다.

- `didEnterRegion` — 구역 밖에서 안으로 들어올 때
- `didDetermineStateForRegion(INSIDE)` — **이미 구역 안에 있는 상태로 앱을 켤 때.**
  이 경우 `didEnterRegion`은 오지 않는다. 이걸 놓치면 "문 앞에 서 있는 상태로 앱을 켜면 영구히 IDLE"이 된다.

### 2.2 프로세스/엔진 소유 관계

```
Android 프로세스
├── 포그라운드 서비스 (flutter_foreground_task)
│   └── 서비스 isolate — 알림 유지, wake lock. 스캔은 하지 않는다.
│
└── Activity (MainActivity)
    └── UI isolate + FlutterEngine
        ├── BleScanner 싱글톤          ← 실제 스캔 주체
        └── flutter_beacon 플러그인 채널  ← Engine 수명에 묶임
             └── AltBeacon BeaconService 바인딩 (applicationContext 기준)
```

포그라운드 서비스의 역할은 **프로세스를 포그라운드 우선순위로 유지해 UI isolate의 엔진이 살아 있게 하는 것**이다. 스캔 자체는 UI isolate에서 돈다.

---

## 3. 상황별 동작 매트릭스

**⚠️ 이 표가 이 문서의 핵심이다.**

| 상황 | Activity 파괴? | UI isolate 엔진 | 스캔 | 비고 |
|---|---|---|---|---|
| 앱 포그라운드 | ✗ | 생존 | ✅ 동작 | |
| **화면 OFF** | ✗ | 생존 | ✅ 동작 | `setBackgroundMode(true)` 덕분 |
| 홈 버튼 / 앱 전환 | ✗ | 생존 | ✅ 동작 | |
| 화면 회전 / 다크모드 전환 | 경우에 따라 ✓ | 생존 | ✅ 동작 | 채널이 Engine 소유이므로 영향 없음 |
| **"활동 유지 안 함" ON + 백그라운드** | ✓ | **소멸** | ❌ **정지** | 개발자 옵션. 아래 §3.1 |
| **강한 메모리 압박** | ✓ 가능 | **소멸** | ❌ **정지** | 저사양 단말에서 발생 |
| 최근앱 스와이프 종료 | ✓ | 소멸 | ❌ 정지 | **요구사항 아님** (사용자 승인된 범위 밖) |
| OEM 앱 절전 목록에 포함 | — | 강제 종료 가능 | ❌ 정지 | 삼성/샤오미 등. §3.2 |
| 단말 재부팅 후 | — | — | ⚠️ 확인 필요 | `autoRunOnBoot` + `RECEIVE_BOOT_COMPLETED` |

### 3.1 잔존 한계 — Activity 파괴 시 스캔 정지

**이것이 현재 남아 있는 가장 큰 구조적 한계다.**

기본 Flutter 앱의 `MainActivity`는 자신의 `FlutterEngine`을 직접 생성·파괴한다. 따라서 Activity가 파괴되면 UI isolate 엔진도 함께 사라지고, 그 안에 있는 `BleScanner` 싱글톤도 소멸한다. **포그라운드 서비스 알림은 그대로 남기 때문에 "감시 중"으로 오인하기 쉽다.**

플러그인을 Engine/applicationContext 소유로 리팩터한 것(issue.md P0-3)은 이 문제를 **완화하지 못한다.** 채널이 Activity에 묶이지 않게 된 것은 맞지만, 엔진 자체가 사라지면 Dart 쪽 스캐너도 사라진다.

#### 완화 장치 (현재 적용됨)

| 장치 | 위치 | 효과 |
|---|---|---|
| 포그라운드 서비스 우선 시작 | `main.dart` | 프로세스가 메모리 회수 대상에서 밀려남 |
| 배터리 최적화 예외 요청 | `foreground_service.dart` | Doze 영향 완화 |
| `WidgetsBindingObserver` 복귀 훅 | `main.dart` | 포그라운드 복귀 시 스캔 상태 점검·복구 |
| 30초 워치독 | `ble_scanner.dart` | monitoring 구독 소실·차단 사유 해소 감지 후 자동 재시작 |

**한계**: 위 장치는 모두 **UI isolate 안에서 동작한다.** 엔진이 사라지면 워치독도 함께 사라지므로, 이 경로를 실제로 막지는 못한다. 앱을 다시 열 때까지 복구되지 않는다.

#### 근본 해결책 (미구현)

**스캐너를 포그라운드 서비스 isolate로 이전** (issue.md P0-4 안 A).

`flutter_foreground_task`는 서비스용 FlutterEngine을 별도로 띄우므로, 스캐너를 그쪽으로 옮기면 Activity 파괴와 무관하게 살아남는다.

| 항목 | 내용 |
|---|---|
| 작업 | `GatekeeperTaskHandler.onStart`에서 `BleScanner().initialize()` 호출 |
| 통신 | `FlutterForegroundTask.sendDataToMain` / `sendDataToTask`로 UI에 RSSI·진단 전달 |
| 영향 | 디버그 화면의 `ValueNotifier` 직접 참조가 불가 → 데이터 경로 재작성 필요. `SharedPreferences`·`AppErrorLogger`가 isolate별로 분리되므로 로그 전달도 채널화 필요 |
| 미구현 사유 | `flutter_foreground_task` 6.2.0의 isolate 통신 API를 검증할 환경이 없었다 (Flutter 툴체인 부재, pub 캐시 비어 있음). 추측으로 작성하면 컴파일 실패 가능성이 높다 |
| 선행 조건 | 빌드 환경 확보 |

### 3.2 OEM 절전 (코드로 해결 불가)

`FlutterForegroundTask.requestIgnoreBatteryOptimization()`은 **Android 표준 배터리 최적화**만 해제한다. 삼성 "앱 절전", 샤오미 MIUI 자동 시작 관리 등 **제조사별 별도 목록은 해제되지 않는다.**

이건 코드로 해결할 수 없다. 제조사별 설정 경로를 안내하는 사용자 가이드 화면이 필요하다 (미구현, issue.md P1-10).

---

## 4. 반응 지연과 전력의 트레이드오프

승인된 목표는 **구역 진입 → 3초 이내 반응**이다. 그런데 §1.3 때문에 `SCAN_MODE_LOW_POWER`가 강제된다. 컨트롤러가 대략 512ms window / 5120ms interval로 스캔하므로 **최악 발견 지연이 약 5초까지 늘어날 수 있다.**

즉 **3초 목표 미달 가능성이 실재한다.** 이건 구현 품질 문제가 아니라 AltBeacon 공개 API의 구조적 제약이다.

현재 설정:

| 파라미터 | 값 | 이유 |
|---|---|---|
| `backgroundMode` | `true` (상시) | 화면 OFF 대응. 필수 |
| `backgroundScanPeriod` | 1100ms | AltBeacon 기본 10000ms → 단축 |
| `backgroundBetweenScanPeriod` | **0ms** | 기본 300000ms(5분)를 그대로 두면 RSSI가 5분에 한 번 온다 |
| `enableScheduledScanJobs` | `false` | JobScheduler 위임 차단 |

`betweenScanPeriod`를 0(연속 스캔)으로 두는 것은 3초 목표 때문이다. **전력 절감 여지를 스스로 제한한 선택이며, 의도된 것이다.** 호스트 측 듀티 사이클보다 컨트롤러 측 듀티 사이클(LOW_POWER)이 호스트 웨이크업이 적어 더 효율적이라는 판단도 포함된다.

### 실측 후 판단할 것

`didEnterRegion` 지연을 20회 측정해 p95를 구한다. 3초를 초과하면 두 선택지가 있다 (issue.md §2.3 Phase 2).

- **(2a)** AltBeacon을 소스로 포함해 `CycledLeScannerForLollipop`에서 필터를 유지하되 `SCAN_MODE_BALANCED`/`LOW_LATENCY` 사용
- **(2b)** AltBeacon을 버리고 앱 전용 Kotlin에서 `BluetoothLeScanner.startScan(filters, SCAN_MODE_LOW_LATENCY)` 직접 호출 + iBeacon 직접 파싱 — **코드량이 더 적고 통제력이 크다. 권장**

---

## 5. 신고 대응 순서

"문이 안 열린다" / "RSSI가 안 보인다" 신고를 받으면 이 순서로 확인한다.

1. **앱 디버그 화면 → 진단 패널**을 먼저 본다. 차단 사유(빨강)가 있으면 그것이 원인이다.
   - 위치 서비스(GPS) OFF가 가장 흔하다. Android는 이 경우 스캔 결과를 오류 없이 0건으로 반환한다.
2. **현재 모드**를 본다. IDLE에 머물러 있는데 비콘 앞이라면 §2.1의 승격 트리거 문제다.
3. **누적 패킷 카운터**를 본다. 화면 OFF 60초 뒤 약 60개가 늘어야 정상이다.
4. **포그라운드 서비스 실행** 항목이 ✗면 §3.1 또는 §3.2다.
5. ESP32 쪽이 의심되면 nRF Connect로 raw advertising을 확인한다 —
   `4C 00 02 15` 다음 16바이트가 `A1 B2 C3 D4 E5 F6 78 90 AB CD EF 12 34 56 78 90`인지.
   역순이면 [src/main.cpp](../src/main.cpp) 주석대로 수정한다 (issue.md P2-13a, 미검증 상태).

---

## 6. 코드를 고칠 사람이 지켜야 할 규칙

1. **`onDetachedFromActivity()`에 정리 코드를 넣지 마라.** 채널·스캔을 여기서 정리하면 백그라운드 상주가 깨진다 (issue.md P0-3 재발).
2. **모드 전환은 반드시 `_synchronized()` 뮤텍스 안에서** `필드 null 대입 → await cancel → 재구독` 순서로 해라.
   `ranging()`은 호출마다 새 broadcast stream을 만들지만 네이티브는 sink 필드가 하나뿐이다. 두 구독이 겹치면 첫 번째 cancel이 두 번째까지 죽인다 (issue.md P1-7).
3. **뮤텍스 안에서 `startScanning`/`stopScanning`/`_enterActiveMode`/`_enterIdleMode`를 호출하면 데드락이다.**
   이름에 `Locked`가 붙은 메서드만 호출해라.
4. **`setBackgroundMode(false)`로 되돌리지 마라.** 화면 OFF에서 스캔이 죽는다 (§1.3).
5. **`didDetermineStateForRegion(INSIDE)` 처리를 지우지 마라** (§2.1).
6. `cancel()` 뒤 필드를 `null`로 비우는 것을 잊지 마라 (issue.md P0-1이 정확히 이 실수였다).
