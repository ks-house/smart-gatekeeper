# smart-gatekeeper — 비콘 수신 / RSSI 실시간 표시 / 전력 최적화 이슈 정리

> **문서 목적**: 모바일 앱(`gatekeeper_app`)이 ESP32-C6의 iBeacon 신호를 수신해 깨어나고, RSSI를 실시간으로 표시하는 기능이 정상 동작하지 않는 문제의 **근본 원인 전수 조사 결과**와 **수정 지침**입니다.
>
> **독자**: 이 저장소를 수정할 다른 AI 에이전트 / 개발자.
> **작성 기준 커밋**: `8e1358d` (main)
> **분석 범위**: `gatekeeper_app/lib/**`, `gatekeeper_app/android/**`(vendored `flutter_beacon_local` 포함), `src/main.cpp`, `include/config.h`, `backend/app/main.py`

---

> ## 📌 구현 진행 상태 (2026-07-29)
>
> 이 문서의 **P0~P2 대부분이 브랜치 `fix/beacon-rssi-and-power` 에서 구현되었습니다.**
> 처리 내역·미수행 항목·검증 한계는 **[IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)** 를 먼저 읽으십시오.
>
> | 구분 | 상태 |
> |---|---|
> | P0-1, P0-2, P0-3, P0-5 | ✅ 구현 |
> | P0-4 | ⚠️ 부분 구현 — 안 A(isolate 이전) 미수행 |
> | P1-6 ~ P1-12 | ✅ 구현 (P1-10 의 targetSdk 고정만 미수행) |
> | P2-13 | ⚠️ Flags 만 수정 — **UUID 바이트 순서는 실측 전까지 손대지 않음** |
> | P2-14 ~ P2-19 | ✅ 구현 |
> | P2-20 | ⚠️ 부분 |
> | P2-21, P3-23, P3-24 | ⏸️ 미수행 |
> | **P3-22** | ✅ **구현** (fail-closed + X-API-KEY) |
> | **P3-25** | ⏸️ 미수행 — P3-22 작업 중 분리된 신규 항목 |
>
> **⚠️ 빌드 검증도, 실기기 검증도 수행하지 않았습니다.** 이 환경에 Flutter 툴체인이 없습니다.
> 완료 판정은 IMPLEMENTATION_REPORT.md §5 체크리스트를 실기기에서 통과시킨 뒤에 하십시오.

---

## 0. 이 문서를 읽는 에이전트가 반드시 먼저 알아야 할 것

### 0.1 확정된 제품 결정사항 (사용자 승인 완료)

| 항목 | 결정 | 이 문서에 미치는 영향 |
|---|---|---|
| **기동 범위** | **포그라운드 서비스 상주 전제.** 최근앱에서 스와이프로 제거된 상태에서 깨어나는 것은 **요구사항 아님** | `RegionBootstrap` / 커스텀 `Application` 서브클래스 재설계는 **범위 외**. 대신 "포그라운드 서비스가 살아 있는 동안 100% 동작"이 목표 |
| **플랫폼** | **Android 우선, iOS 추후** | iOS 관련 항목은 §7 백로그로 분리. P0~P2는 모두 Android |
| **반응 지연 목표** | **비콘 구역 진입 → 3초 이내 반응** (워크스루 경험 우선) | 전력 절감은 "상시 스캔을 끄는 것"이 아니라 **"ranging 고속 모드를 필요할 때만 켜는 것"** 으로 달성해야 함. §2 참조 |
| **플러그인 전략** | **vendored `flutter_beacon` fork를 직접 패치** | `gatekeeper_app/android/app/libs/flutter_beacon_local/` 안의 Java/Dart를 자유롭게 수정할 것. 기존 Dart 레이어는 최대한 재사용 |

### 0.2 절대 틀리면 안 되는 Android 플랫폼 사실 (여기서 잘못 가정하면 전부 헛수고가 됩니다)

1. **Android에는 "OS가 죽은 앱을 비콘으로 깨워주는" API가 없습니다.** iOS CoreLocation의 region monitoring과 달리, Android는 앱이 직접 스캔을 돌려야 합니다. AltBeacon의 `didEnterRegion`도 결국 **우리 프로세스가 스캔을 돌린 결과**입니다.
   → 현재 코드의 알림 문구 `"Target 비콘 구역 접근 시 OS가 자동으로 비콘을 감지합니다"` ([ble_scanner.dart:100-102](gatekeeper_app/lib/services/ble_scanner.dart#L100-L102))는 **사실과 다릅니다.** 문구도 수정 대상입니다.

2. **Android 8.1(API 27) 이상에서 화면이 꺼진 동안에는, `ScanFilter`가 없는 BLE 스캔의 결과가 앱에 전달되지 않습니다.** 스캔 자체는 에러 없이 "성공"하고 결과만 0건입니다. 포그라운드 서비스가 살아 있어도 무관합니다.
   → **이것이 화면 OFF 시 RSSI가 멈추는 근본 원인입니다.** (§4 P0-2)

3. **AltBeacon 2.19의 공개 API로는 "ScanFilter + SCAN_MODE_LOW_LATENCY" 조합을 만들 수 없습니다.**
   `CycledLeScannerForLollipop`의 동작이 `backgroundMode` 플래그 하나로 묶여 있습니다:

   | `setBackgroundMode()` | ScanSettings | ScanFilter | 화면 OFF 동작 |
   |---|---|---|---|
   | `false` (기본값) | `SCAN_MODE_LOW_LATENCY` | **없음** | ❌ 결과 0건 |
   | `true` | `SCAN_MODE_LOW_POWER` | **있음** | ✅ 동작 |

   → 즉 **화면 OFF에서 동작시키려면 `setBackgroundMode(true)`가 필수**이고, 그러면 자동으로 `SCAN_MODE_LOW_POWER`가 됩니다. 발견 지연이 늘어날 수 있으므로 §2.3의 실측·판단 절차를 반드시 따르십시오.

4. **monitoring과 ranging은 같은 스캔 사이클을 공유합니다.** ranging을 추가로 켜는 것 자체가 스캔 횟수를 늘리지 않습니다.
   → **전력을 실제로 결정하는 변수는 `scanPeriod` / `betweenScanPeriod`(스캔 듀티 사이클)와 ScanSettings 모드입니다.** "ranging 스트림을 끄면 전력이 절감된다"는 가정은 **부분적으로만** 참입니다(콜백 처리·HTTP·알림 갱신 비용은 줄어듦). §2에서 이를 전제로 설계하십시오.

5. **`setEnableScheduledScanJobs(false)`를 호출하지 않으면** AltBeacon이 JobScheduler(`ScanJob`)에 스캔을 위임하고, 백그라운드 최소 주기(약 15분)에 묶입니다. 자체 포그라운드 서비스를 쓰는 지금 구조에서는 **반드시 `false`** 로 설정해야 하며, **바인딩 전에** 호출해야 합니다.

---

## 1. 증상과 원인의 대응 관계

| 사용자가 보는 증상 | 원인 이슈 |
|---|---|
| 디버그 화면에 들어가면 RSSI가 계속 `연결 안됨` | **P0-1** (결정적) |
| 처음엔 보이다가 어느 순간 영구히 멈춤 | **P0-1**, **P0-3** |
| 화면을 끄면 RSSI 갱신이 멈춤 | **P0-2** |
| 앱을 백그라운드로 보내면 감지가 안 됨 | **P0-3**, **P0-4** |
| 알림은 "감시 중"인데 실제로 문이 안 열림 | **P0-3**, **P0-4** (알림만 살아남는 구조) |
| 아무 오류 로그도 없이 그냥 신호가 안 옴 | **P1-5** (위치서비스/권한 무검증), **P2-11** (송신부 미검증) |
| RSSI가 잡혔다 끊겼다 깜빡임 | **P1-6** (타임아웃 3초), **P1-9** (RSSI 필터링 없음) |
| 배터리가 빨리 닳음 | **P0-5** (ranging 상시 ON), **P1-8** (알림 폭주) |

---

## 2. 목표 아키텍처 (P0-5의 해결책이자 전체 수정의 기준선)

### 2.1 현재 구조의 문제

현재 코드는 **ranging을 앱 시작 시 한 번 켜고 영구히 유지**합니다. [ble_scanner.dart:221-222](gatekeeper_app/lib/services/ble_scanner.dart#L221-L222)의 주석이 그 의도를 명시합니다:

```dart
void _startRangingStream(List<Region> regions) {
  if (_streamRanging != null) return; // 이미 Ranging 스트림 구독 중이면 영구 유지 (네이티브 바인딩 재설정 차단)
```

이는 요구사항("iBeacon으로 깨어난 뒤부터 RSSI 측정")과 **정반대**입니다. 그리고 이 "영구 유지" 가드가 바로 **P0-1 버그의 발생 지점**입니다. 즉 아키텍처를 바로잡으면 P0-1도 구조적으로 해소됩니다.

### 2.2 도입할 2단 전력 모드 상태 머신

`BleScanner`에 명시적 모드 개념을 도입하십시오.

```
                   ┌─────────────────────────────────────────┐
                   │  IDLE  (저전력 감시 모드)                 │
                   │  · monitoring 구독 O                     │
                   │  · ranging 구독 X                        │
                   │  · setBackgroundMode(true)               │
                   │  · scanPeriod 1100ms / between 0ms       │
                   │  · 타임아웃 타이머 정지                    │
                   │  · 알림: "구역 감시 중"                    │
                   └─────────────────────────────────────────┘
                         │                        ▲
        didEnterRegion   │                        │  didExitRegion
        (또는 monitoring  │                        │  또는 ranging 무수신
         상태 INSIDE)     ▼                        │  N초 경과
                   ┌─────────────────────────────────────────┐
                   │  ACTIVE (고속 계측 모드)                  │
                   │  · monitoring 구독 유지                   │
                   │  · ranging 구독 O  ← RSSI 여기서만 나옴    │
                   │  · scanPeriod 1100ms / between 0ms       │
                   │  · 타임아웃 타이머 동작                    │
                   │  · 알림: RSSI 실시간 표시                  │
                   │  · 임계값 충족 시 prearm HTTP 호출         │
                   └─────────────────────────────────────────┘
                         │                        ▲
        디버그 화면 진입   │                        │  디버그 화면 이탈
        (강제 ACTIVE)     ▼                        │
                   ┌─────────────────────────────────────────┐
                   │  DEBUG_FORCED (엔지니어 모드)             │
                   │  · IDLE이어도 ranging 강제 유지           │
                   │  · 사용자가 화면을 보고 있으므로 전력 무관   │
                   └─────────────────────────────────────────┘
```

**핵심 설계 규칙**

- `IDLE`에서 `betweenScanPeriod`를 크게 늘리고 싶은 유혹이 있지만, **반응 지연 3초 목표 때문에 늘릴 수 없습니다.** `betweenScanPeriod = 0`(연속 스캔)을 유지하고, 전력은 `SCAN_MODE_LOW_POWER`(컨트롤러 레벨 듀티 사이클)에 맡기십시오. 호스트 측 듀티 사이클(`betweenScanPeriod`)보다 컨트롤러 측 듀티 사이클(LOW_POWER)이 **더 효율적**입니다 — 호스트 웨이크업이 적기 때문입니다.
- `IDLE`에서 실제로 절감되는 것: ranging 콜백 파싱(1Hz), `ValueNotifier` 갱신, 알림 갱신 IPC, `Timer.periodic`, prearm HTTP 시도. 이것들이 합쳐지면 무시할 수 없습니다.
- 모드 전환은 **반드시 직렬화**하십시오. §4 P1-7의 EventChannel 중복 구독 위험 때문에, `cancel() → await → null 대입 → 재구독` 순서를 지키고 전환 중 재진입을 막는 락(`_isTransitioning`)이 필요합니다.

### 2.3 반응 지연 3초 목표 달성 검증 절차 (Phase 1 → Phase 2)

`SCAN_MODE_LOW_POWER`는 컨트롤러가 대략 512ms window / 5120ms interval로 스캔합니다. ESP32가 100ms 간격으로 광고하므로 window 안에 여러 패킷이 들어오지만, **최악의 경우 발견 지연이 약 5초까지 늘어날 수 있습니다.**

**Phase 1 (먼저 시도)**: `setBackgroundMode(true)` + `backgroundScanPeriod=1100` / `backgroundBetweenScanPeriod=0` + `setEnableScheduledScanJobs(false)`로 구현하고 **실측**하십시오.
- 측정 방법: 비콘 전원 OFF 상태에서 앱 IDLE 대기 → 비콘 전원 ON → `didEnterRegion` 로그까지의 시간을 20회 측정 → p95 기록.
- p95 ≤ 3초면 **여기서 종료**합니다.

**Phase 2 (Phase 1이 목표 미달일 때만)**: §0.2-3의 제약 때문에 AltBeacon 공개 API로는 더 못 갑니다. 두 선택지가 있습니다.
- **(2a)** AltBeacon을 AAR 의존성이 아닌 **소스로 포함**해 `CycledLeScannerForLollipop`에서 `ScanFilter`는 유지하되 `SCAN_MODE_BALANCED` 또는 `SCAN_MODE_LOW_LATENCY`를 쓰도록 수정.
- **(2b)** AltBeacon을 버리고 앱 전용 Kotlin에서 `BluetoothLeScanner.startScan(filters, SCAN_MODE_LOW_LATENCY, callback)`을 직접 호출하고 iBeacon을 직접 파싱. 파싱은 단순합니다 — manufacturer data `0x004C` + `0x02 0x15` + UUID 16바이트 + major 2 + minor 2 + measuredPower 1.
  → **(2b)가 코드량이 더 적고 통제력이 큽니다.** Phase 2로 가야 한다면 (2b)를 권장합니다. 단, Region monitoring(enter/exit 상태 판정)을 직접 구현해야 하므로 `didEnterRegion` 히스테리시스 로직을 손으로 써야 합니다.

> ⚠️ Phase 2로 가는 판단은 **반드시 Phase 1 실측 데이터를 근거로** 하십시오. 추측으로 (2b)를 먼저 하지 마십시오.

---

## 3. 우선순위 요약 표

| ID | 심각도 | 제목 | 예상 작업량 | 선행 의존 |
|---|---|---|---|---|
| **P0-1** | 🔴 Blocker | `forceRestart`로 ranging 스트림이 영구 정지 | XS (3줄) | — |
| **P0-2** | 🔴 Blocker | 화면 OFF 시 Android가 스캔 결과 폐기 (ScanFilter 부재) | S (fork 3파일 · 약 70행) | P1-9 |
| **P0-3** | 🔴 Blocker | 플러그인이 Activity 수명주기에 묶여 백그라운드 상주 불가 | L | — |
| **P0-4** | 🔴 Blocker | 스캔이 UI isolate에서 돌고 서비스 isolate는 빈 껍데기 | M | P0-3 |
| **P0-4b** | 🔴 잔존 | Activity 파괴 시 스캔 정지 (P0-4 안 A 미구현) — [wiki/mobile_app_scan_lifecycle.md §3.1](wiki/mobile_app_scan_lifecycle.md#31-잔존-한계--activity-파괴-시-스캔-정지) | M | 빌드 환경 |
| **P0-5** | 🔴 Blocker | ranging 상시 ON — 요구 아키텍처와 정반대 (전력) | M | P0-1, P0-3 |
| **P1-6** | 🟠 High | 3초 타임아웃이 스캔 주기와 상충해 UI 깜빡임 | XS | — |
| **P1-7** | 🟠 High | EventChannel 중복 구독 시 양쪽 스트림 동반 사망 | S | — |
| **P1-8** | 🟠 High | 위치서비스/권한 무검증 → 무증상 0건 스캔 | S | — |
| **P1-9** | 🟠 High | 플러그인 `setScanPeriod` 계열 `return` 누락 → 호출 시 예외 | XS | — |
| **P1-10** | 🟠 High | 매니페스트 누락 (`RECEIVE_BOOT_COMPLETED` 등) | XS | — |
| **P1-11** | 🟠 High | 잘못된 UUID가 오면 monitoring NPE | XS | — |
| **P1-12** | 🟠 High | 백엔드가 사용자 로컬 쿨다운 설정을 매 부팅마다 덮어씀 | XS | — |
| **P2-13** | 🟡 Medium | ESP32 iBeacon 페이로드 검증 (UUID 바이트 순서 / Flags) | S + 실측 | — |
| **P2-14** | 🟡 Medium | 알림 갱신 폭주 (1Hz) | XS | P0-5 |
| **P2-15** | 🟡 Medium | RSSI 원시값 사용 → 임계값 판정 불안정 | S | — |
| **P2-16** | 🟡 Medium | prearm 실패 시에도 쿨다운이 적용되어 재시도 차단 | XS | — |
| **P2-17** | 🟡 Medium | RSSI 카드 리빌드가 `packetCount`에 우연히 의존 | XS | — |
| **P2-18** | 🟡 Medium | `initialize()` 순서로 스캔 시작이 네트워크에 블로킹됨 | XS | — |
| **P2-19** | 🟡 Medium | 진단 UI 부재 — "왜 안 되는지" 앱 안에서 알 수 없음 | S | P1-8 |
| **P2-20** | 🟡 Medium | vendored fork 빌드 설정 노후화 | XS | — |
| **P2-21** | 🟡 Medium | ESP32 WiFi/BLE 공존으로 광고 드롭 가능성 | 조사 | — |
| **P3-22** | 🔴 보안 | 백엔드 문 제어 fail-open + 인증 부재 | S | — |
| **P3-25** | 🟠 보안 | `/admin/**` 및 `/admin` 페이지 무인증 (P3-22 후속) | M | — |
| **P3-23** | ⚪ Backlog | 고정 비콘 UUID → 스푸핑/리플레이 가능 | L (설계) | — |
| **P3-24** | ⚪ Backlog | iOS 지원 선결 조건 | M | — |

**권장 진행 순서**: `P0-1` → `P1-8`+`P2-19`(진단 능력 확보) → `P2-13`(송신부 확정) → `P1-9`→`P0-2` → `P0-3`+`P0-4`+`P0-5`(구조 변경) → 나머지

> 📌 `P0-1`과 `P1-8`/`P2-19`를 먼저 하는 이유: **현재는 실패 원인을 관측할 수단이 앱 안에 전혀 없습니다.** 큰 구조 변경(P0-3/4/5)을 관측 수단 없이 진행하면 회귀를 감지할 수 없습니다.

---

## 4. P0 — Blocker

### P0-1. `forceRestart`로 ranging 스트림이 영구 정지 🔴

**심각도**: Blocker / **작업량**: XS / **재현율**: 100%

#### 증상
RSSI를 보려고 디버그 화면에 들어가면, 그 즉시 RSSI가 `연결 안됨`으로 고정되고 **앱을 완전히 재시작할 때까지 복구되지 않습니다.**

#### 근본 원인
[ble_scanner.dart:156-163](gatekeeper_app/lib/services/ble_scanner.dart#L156-L163) — `forceRestart` 블록이 `_streamRanging`을 취소하지만 **`null`로 대입하지 않습니다**:

```dart
if (forceRestart) {
  _isScanning = false;
  _timeoutTimer?.cancel();
  liveRssi.value = null;
  isBeaconConnected.value = false;
  await _streamRanging?.cancel();      // ← line 161: null 대입 없음
  await _streamMonitoring?.cancel();
}
```

그 직후 [ble_scanner.dart:218](gatekeeper_app/lib/services/ble_scanner.dart#L218)에서 호출되는 `_startRangingStream()`이 [ble_scanner.dart:222](gatekeeper_app/lib/services/ble_scanner.dart#L222)의 가드에 걸려 **즉시 return**합니다:

```dart
if (_streamRanging != null) return;   // 취소된 subscription 객체도 non-null
```

결과적으로:
- ranging 재구독 실패 → RSSI 이벤트 영구 중단
- 가드 뒤에 있는 [`_startTimeoutCheckTimer()`:238](gatekeeper_app/lib/services/ble_scanner.dart#L238)도 실행 안 됨 → 타임아웃 감시도 죽음
- 네이티브도 함께 정지: Dart `cancel()` → `EventChannel.onCancel` → [FlutterBeaconScanner.stopRanging():106-119](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconScanner.java#L106-L119) → `stopRangingBeaconsInRegion()` + `eventSinkRanging = null`
- [ble_scanner.dart:177](gatekeeper_app/lib/services/ble_scanner.dart#L177)에서 `_isScanning = true`가 무조건 설정되므로 `isScanning` getter가 **거짓을 반환**

#### 그리고 하필 그 호출자가 RSSI 화면 자신
[debug_screen.dart:38](gatekeeper_app/lib/screens/debug_screen.dart#L38):
```dart
_scanner.startScanning(forceRestart: true);   // initState 안
```

[stopScanning():341](gatekeeper_app/lib/services/ble_scanner.dart#L341)도 동일한 결함이 있어, 정지 후 재시작이 영구 불가입니다.

#### 수정 방향
1. `cancel()` 호출 뒤 **반드시** `null` 대입 (161행, 162행, 341행, 342행 — 4곳 모두)
2. `_startRangingStream`의 가드를 "재진입 방지"가 아니라 "중복 구독 방지"로 재정의. §2.2 상태 머신 도입 시 `_mode` 기반 판정으로 대체
3. `DebugScreen.initState`의 `forceRestart: true` **제거**. `BleScanner`는 싱글톤이고 이미 스캔 중이므로 재시작할 이유가 없습니다. §2.2 도입 후에는 `enterDebugMode()` / `exitDebugMode()`(`dispose`에서)로 교체
4. `_isScanning`을 ranging/monitoring 구독 성공 여부에서 파생시키기

#### 검증
- 디버그 화면 진입 → 이탈 → 재진입을 5회 반복하고 매번 RSSI가 계속 갱신되는지 확인
- `adb logcat -s RANGING` 에서 `Start ranging` / `Stop ranging` 쌍이 균형을 이루는지 확인

---

### P0-2. 화면 OFF 시 Android가 스캔 결과를 전부 폐기 🔴

**심각도**: Blocker / **작업량**: S (fork 3파일 · 약 70행) / **선행**: P1-9

> 📌 **P0-3과 독립적인 문제입니다. 함께 묶어 처리하지 마십시오.**
> 화면을 끄는 것은 Activity를 파괴하지 않습니다 — `onPause`/`onStop`만 호출되고 Activity·FlutterEngine·플러그인 채널은 모두 살아 있습니다. `onDetachedFromActivity`는 Activity가 **파괴될 때** 호출됩니다.
> 따라서 **P0-2 단독 수정만으로 화면 OFF 케이스의 대부분이 해결됩니다.** P0-3(Activity 파괴 시 스캔 사망)은 "활동 유지 안 함" 옵션이나 메모리 압박 상황에서만 재현되는 별개 실패 모드입니다.
> → 작은 커밋(P0-2)을 먼저 넣고 §2.3 Phase 1 실측을 확보한 뒤, 큰 리팩터(P0-3/P0-4)로 넘어가십시오.

#### 증상
화면을 끄면 RSSI 갱신이 멈추고, 3초 뒤 `💤 수면 감시 모드`로 넘어갑니다. 화면을 다시 켜면 몇 초 안에 복구됩니다. 오류 로그는 전혀 남지 않습니다.

#### 근본 원인
§0.2-2, §0.2-3 참조. vendored 플러그인은 `BeaconManager.setBackgroundMode()`를 **노출하지도, 호출하지도 않습니다.** 따라서 AltBeacon은 영구히 `backgroundMode = false`(기본값)로 남고, `CycledLeScannerForLollipop`은 **빈 `ScanFilter` 리스트 + `SCAN_MODE_LOW_LATENCY`** 로 스캔합니다. Android 8.1+ 는 화면 OFF + 필터 없는 스캔의 결과를 앱에 전달하지 않습니다.

추가로 [FlutterBeaconPlugin.java:101](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L101) 근처에서 `setEnableScheduledScanJobs(false)`를 호출하지 않으므로, AltBeacon이 `ScanJob`(JobScheduler)에 스캔을 위임할 수 있고 이 경우 백그라운드 최소 주기 약 15분에 묶입니다.

#### 수정 방향

**(a) fork에 MethodChannel 메서드 추가** — `FlutterBeaconPlugin.onMethodCall`에 다음을 추가하고 **각 블록 끝에 `return`을 반드시 넣으십시오** (P1-9 참조):

| 메서드명 | 매핑되는 AltBeacon API | 비고 |
|---|---|---|
| `setBackgroundMode` | `beaconManager.setBackgroundMode(boolean)` | 핵심. `true`가 필터+LOW_POWER |
| `setBackgroundScanPeriod` | `setBackgroundScanPeriod(int)` + `updateScanPeriods()` | 기본 10000ms → 1100ms |
| `setBackgroundBetweenScanPeriod` | `setBackgroundBetweenScanPeriod(int)` + `updateScanPeriods()` | **기본 300000ms(5분) → 0ms**. 이걸 안 바꾸면 RSSI가 5분에 한 번 옵니다 |
| `setEnableScheduledScanJobs` | `setEnableScheduledScanJobs(boolean)` | `false`. **바인딩 전에 호출해야 함** |

**(b) Dart 래퍼 추가** — `flutter_beacon_local/lib/flutter_beacon.dart`의 `setScanPeriod`([182-191행](gatekeeper_app/android/app/libs/flutter_beacon_local/lib/flutter_beacon.dart#L182-L191))과 같은 패턴으로 4개 메서드 추가.

**(c) 호출 순서** — `BleScanner.startScanning()`에서:
```
setEnableScheduledScanJobs(false)     // ← 반드시 initializeScanning 전에
  ↓
flutterBeacon.initializeScanning       // bind
  ↓
setBackgroundMode(true)
setBackgroundScanPeriod(1100)
setBackgroundBetweenScanPeriod(0)
  ↓
monitoring 구독
```

**(d) `setBackgroundMode(true)`를 상시 유지할 것** — 화면이 켜져 있을 때도 `true`로 두십시오. `false`로 되돌리면 필터가 사라져 화면 OFF에서 다시 죽습니다. "화면 ON일 때만 LOW_LATENCY" 같은 최적화는 전환 타이밍 버그를 만들 뿐 이득이 없습니다.

#### 검증 (필수)
1. 앱 실행 → 디버그 화면에서 RSSI 확인 → **화면 OFF** → 60초 대기 → 화면 ON
   → 디버그 화면의 `누적 패킷` 카운터가 **60개 근처로 증가**해 있어야 함 (1Hz). 화면 OFF 동안 멈췄다면 미해결.
2. §2.3 Phase 1 실측: `didEnterRegion` 지연 p95 측정 (20회)
3. `adb shell dumpsys bluetooth_manager | grep -A5 "Scan"` 으로 스캔이 실제로 등록되어 있고 필터가 붙어 있는지 확인

---

### P0-3. 플러그인이 Activity 수명주기에 묶여 백그라운드 상주 불가 🔴

**심각도**: Blocker / **작업량**: L

#### 증상
- 앱을 백그라운드로 보내거나 Activity가 파괴되면 **예외 하나 없이 조용히** ranging이 멈춤
- 그런데 포그라운드 서비스 알림은 `💤 수면 감시 중`으로 그대로 남아 있어 **정상 동작으로 오인**됨
- 이전 커밋 `244fbc6`의 "native AltBeacon IPC crashes"와 같은 뿌리

#### 근본 원인 (4가지가 겹쳐 있음)

| # | 문제 | 위치 | 결과 |
|---|---|---|---|
| 1 | 모든 채널이 `onAttachedToActivity`에서만 생성되고, `onDetachedFromActivity` → `teardownChannels()`가 **모든 StreamHandler를 null로** 설정 | [Plugin.java:70-89](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L70-L89), [127-149](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L127-L149) | ranging 이벤트 전달 중단. **Dart 구독은 살아 있어 `onError`조차 안 옴** → 무증상 |
| 2 | `BeaconConsumer.bindService()`/`unbindService()`가 `activity.get()` 사용 | [Scanner.java:290-304](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconScanner.java#L290-L304) | Activity 파괴 시 OS가 바인딩을 자동 해제 → AltBeacon 서비스 연결 끊김. `WeakReference`이므로 GC 후 **NPE** 가능 |
| 3 | `teardownChannels()`가 `unbind`/`stopRanging`을 하지 않는데, 재부착 시 [Plugin.java:108](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L108)에서 **새 `FlutterBeaconScanner`(= 새 `beaconConsumer`)** 를 만듦 | [Plugin.java:108](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L108), [Scanner.java:82](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconScanner.java#L82) | `isBound(newConsumer)`가 false → 중복 바인딩. 이전 consumer는 방치 → 누수/IPC 예외 |
| 4 | `onDetachedFromActivityForConfigChanges()`가 그대로 `onDetachedFromActivity()`를 호출 | [Plugin.java:77-79](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L77-L79) | Activity가 재생성되는 설정 변경에서 채널이 통째로 날아감 |

추가 NPE 경로: `onDetachedFromEngine`이 먼저 실행되면 `flutterPluginBinding`이 null이 되고, 이후 `onAttachedToActivity`의 [Plugin.java:73](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L73) `flutterPluginBinding.getBinaryMessenger()`에서 NPE. `teardownChannels()`도 이중 호출 시 `channel.setMethodCallHandler(null)`에서 NPE.

#### 수정 방향 — 플러그인을 application-context 기반으로 리팩터

**책임을 분리하십시오.**

| 리소스 | 현재 소유자 | 변경 후 소유자 |
|---|---|---|
| MethodChannel / EventChannel 등록 | Activity (`setupChannels`) | **Engine** (`onAttachedToEngine`) |
| `BeaconManager` 인스턴스 | `activity.getApplicationContext()` (사실상 OK) | 그대로 |
| `BeaconConsumer.bindService` 컨텍스트 | `activity.get()` | **`applicationContext`** |
| `FlutterBeaconScanner` 인스턴스 | Activity 부착마다 새로 생성 | **플러그인 생애 1개** (재사용) |
| 권한 요청 / 설정 화면 열기 (`FlutterPlatform`) | Activity | Activity (유지 — 여기만 Activity 필요) |

구체적 변경:
1. `onAttachedToEngine`에서 `setupChannels(binding.getBinaryMessenger(), binding.getApplicationContext())` 호출. `onDetachedFromEngine`에서만 teardown.
2. `onAttachedToActivity`/`onDetachedFromActivity`는 **`FlutterPlatform`의 Activity 참조 갱신과 `RequestPermissionsResultListener` 등록/해제만** 수행. 채널은 절대 건드리지 말 것.
3. `onDetachedFromActivityForConfigChanges()`는 **빈 구현**으로 두거나 Activity 참조만 해제.
4. `FlutterBeaconScanner`의 `beaconConsumer`에서 `bindService`/`unbindService`/`getApplicationContext`를 모두 **application context** 기반으로 교체. `WeakReference<Activity>` 제거.
5. `FlutterBeaconScanner`를 플러그인 필드로 한 번만 생성하고 재사용. `beaconConsumer` 인스턴스 동일성이 유지되어야 `isBound()`가 정상 동작합니다.
6. `teardownChannels()`에 null 가드 추가 + 이중 호출 방어.
7. `FlutterPlatform`이 Activity 없이 호출될 때(백그라운드) `getActivity() == null` 방어. `checkLocationServicesIfEnabled`/`checkBluetoothIfEnabled`는 **application context로도 동작 가능**하므로 그쪽으로 옮기십시오.

#### 검증
1. 앱을 홈 버튼으로 백그라운드 → 5분 대기 → 알림에 RSSI가 계속 갱신되는지
2. 개발자 옵션에서 **"활동 유지 안 함(Don't keep activities)"** 을 ON → 앱 백그라운드 → ranging이 계속 살아 있는지 (**이 옵션이 P0-3의 결정적 재현 스위치입니다**)
3. 화면 회전 / 다크모드 토글을 10회 반복 후 `adb logcat` 에 AltBeacon 관련 예외가 없는지
4. `adb shell dumpsys activity services | grep -i beacon` 으로 `BeaconService` 바인딩이 **1개만** 존재하는지

---

### P0-4. 스캔이 UI isolate에서 돌고, 서비스 isolate는 빈 껍데기 🔴

**심각도**: Blocker / **작업량**: M / **선행**: P0-3

#### 근본 원인
- [main.dart:69](gatekeeper_app/lib/main.dart#L69) `await BleScanner().initialize();` → **UI isolate**에서 스캔 시작
- [foreground_service.dart:19-22](gatekeeper_app/lib/services/foreground_service.dart#L19-L22) `GatekeeperTaskHandler.onRepeatEvent`는 **완전히 비어 있음**

`flutter_foreground_task`는 서비스용 FlutterEngine/isolate를 **별도로** 띄웁니다. 즉 현재 구조는 "알림만 유지하는 빈 서비스" + "UI isolate에서 도는 실제 스캐너"입니다. P0-3과 결합하면 Activity가 죽는 순간 스캔이 확정적으로 정지하고, 알림만 남습니다.

부수 문제: [main.dart:69-70](gatekeeper_app/lib/main.dart#L69-L70)에서 `initialize()`가 `startService()`보다 **먼저** 호출되어, 포그라운드 서비스 없이 BLE 스캔이 먼저 시작됩니다.

#### 수정 방향 (두 안 중 선택 — 판단 근거 포함)

**안 A (권장): 스캐너를 서비스 isolate로 이전**
- `GatekeeperTaskHandler.onStart`에서 `BleScanner().initialize()` 호출
- UI(디버그 화면)는 `FlutterForegroundTask.sendDataToMain` / `receiveData` 로 RSSI를 전달받아 표시
- 장점: 서비스가 살아 있는 동안 스캔이 보장됨. 요구사항("포그라운드 서비스 상주 전제")과 정확히 일치
- 단점: `ValueNotifier` 직접 참조가 불가해져 디버그 화면의 데이터 경로를 다시 써야 함. `SharedPreferences`/`AppErrorLogger`가 isolate별로 분리되므로 로그 전달도 채널화 필요

**안 B: UI isolate 유지 + P0-3 리팩터에 의존**
- P0-3을 완료하면 채널이 Engine 수명에 묶이므로, 포그라운드 서비스가 UI isolate의 엔진을 살려두는 한 동작
- 장점: 코드 변경 최소, 기존 `ValueNotifier` 구조 그대로
- 단점: **엔진 생존이 OS 재량에 달려 있어 보장되지 않음.** 저사양/메모리 압박 단말에서 재현 어려운 실패가 남음

→ **안 A를 권장합니다.** 다만 P0-3 리팩터를 먼저 완료해 "채널이 Activity에 묶이지 않는" 상태를 만든 뒤에 착수하십시오. 순서를 뒤집으면 두 문제가 뒤엉킵니다.

#### 함께 수정할 것
- `main.dart`: `startService()` → `BleScanner().initialize()` 순서로 교체
- `onRepeatEvent`를 워치독으로 활용: 스캔 상태를 점검하고 죽어 있으면 재구독 시도(단, P1-7의 직렬화 규칙 준수)
- **`AppLifecycleListener` 추가**: 현재 앱 생애주기 훅이 **어디에도 없습니다.** 포그라운드 복귀 시 스캔 상태를 점검·복구하고, §2.2 모드 전환 트리거로도 필요합니다.

---

### P0-5. ranging 상시 ON — 요구 아키텍처와 정반대 (전력) 🔴

**심각도**: Blocker(요구사항 미충족) / **작업량**: M / **선행**: P0-1, P0-3

§2 전체가 이 이슈의 해결책입니다. 여기서는 코드 변경 지점만 정리합니다.

#### 변경 지점

| 파일 | 현재 | 변경 후 |
|---|---|---|
| [ble_scanner.dart:221-239](gatekeeper_app/lib/services/ble_scanner.dart#L221-L239) `_startRangingStream` | 앱 시작 시 1회, 영구 유지 | `didEnterRegion` 또는 디버그 모드 진입 시에만 구독 |
| [ble_scanner.dart:191-215](gatekeeper_app/lib/services/ble_scanner.dart#L191-L215) monitoring 핸들러 | 알림 문구만 갱신 | `didEnterRegion` → `_enterActiveMode()`, `didExitRegion` → `_enterIdleMode()` |
| [ble_scanner.dart:89-115](gatekeeper_app/lib/services/ble_scanner.dart#L89-L115) `_startTimeoutCheckTimer` | 1초 주기 상시 동작 | `ACTIVE` 모드에서만 동작, `IDLE` 진입 시 `cancel()` |
| [ble_scanner.dart:218](gatekeeper_app/lib/services/ble_scanner.dart#L218) | `startScanning` 끝에서 ranging 시작 | 제거 — `IDLE`로 시작 |
| [debug_screen.dart:38](gatekeeper_app/lib/screens/debug_screen.dart#L38) | `startScanning(forceRestart: true)` | `_scanner.enterDebugMode()`; `dispose()`에서 `exitDebugMode()` |

#### 놓치기 쉬운 함정

1. **`didDetermineStateForRegion`도 처리하십시오.** 현재 코드는 `didEnterRegion`/`didExitRegion`만 봅니다([ble_scanner.dart:193-209](gatekeeper_app/lib/services/ble_scanner.dart#L193-L209)). 플러그인은 [Scanner.java:250-266](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconScanner.java#L250-L266)에서 `didDetermineStateForRegion`도 보내주는데, **앱이 이미 구역 안에 있는 상태로 시작하면 `didEnterRegion`이 오지 않고 `didDetermineStateForRegion(INSIDE)`만 옵니다.** 이걸 무시하면 "이미 문 앞에 서 있는 상태로 앱을 켜면 영구히 IDLE" 버그가 생깁니다. **반드시 처리하십시오.**
2. **`didExitRegion`은 늦게 옵니다.** AltBeacon 기본 region exit 판정은 마지막 감지 후 약 10초입니다. `IDLE` 강등은 `didExitRegion`만 믿지 말고 "ranging N초 무수신"(P1-6과 연동) 조건도 함께 쓰십시오.
3. **모드 전환 중 재진입 방지.** §2.2 및 P1-7 참조.
4. **`IDLE`에서 `betweenScanPeriod`를 늘리지 마십시오.** §2.2 설계 규칙 참조 (3초 목표 때문).

---

## 5. P1 — High

### P1-6. 3초 타임아웃이 스캔 주기와 상충해 UI가 깜빡임 🟠

[ble_scanner.dart:94](gatekeeper_app/lib/services/ble_scanner.dart#L94)의 `elapsedMs > 3000`은 AltBeacon foreground 주기(약 1100ms) 대비 여유가 2사이클뿐입니다. 신호 경계에서 한두 사이클만 놓쳐도 `연결 안됨`으로 뒤집혀 UI가 깜빡입니다. P0-2 수정으로 `SCAN_MODE_LOW_POWER`가 되면 사이클 간 편차가 더 커져 **더 자주** 발생합니다.

**수정**: 타임아웃을 6000ms로 늘리고, 단발 미수신이 아니라 **연속 미수신 사이클 카운트**(예: 4회 연속)로 판정. 임계값은 `static const`로 추출.

### P1-7. EventChannel 중복 구독 시 양쪽 스트림 동반 사망 🟠

[flutter_beacon.dart:207-213](gatekeeper_app/android/app/libs/flutter_beacon_local/lib/flutter_beacon.dart#L207-L213)의 `ranging()`은 매 호출마다 `_rangingChannel.receiveBroadcastStream(list)`로 **새 스트림**을 만듭니다. `_rangingChannel`은 `static const` 단일 객체이고, 네이티브 쪽 [Scanner.java:47-57](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconScanner.java#L47-L57) `rangingStreamHandler`는 `eventSinkRanging` **필드 하나**만 보유합니다.

따라서 두 구독이 동시에 살아 있으면:
1. 두 번째 `onListen` → `eventSinkRanging`이 덮어써짐 (첫 번째 스트림은 이벤트를 못 받음)
2. 첫 번째를 `cancel()` → 네이티브 `onCancel` → `stopRanging()` → **두 번째까지 함께 사망**

**수정**:
- `BleScanner`에 `bool _isTransitioning` 락을 두고, 모드 전환은 `cancel() → await → null 대입 → 재구독` 순서로 **엄격히 직렬화**
- 전환 중 들어온 요청은 큐잉하거나 드롭 (전환 후 상태 재평가)
- 이 규칙을 `_startRangingStream` 주변에 주석으로 명시해 다음 수정자가 깨뜨리지 않게 할 것

### P1-8. 위치서비스/권한 무검증 → 무증상 0건 스캔 🟠

`flutterBeacon.initializeScanning`은 네이티브 [Plugin.java:146-157](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L146-L157)의 `initialize` = **그냥 `bind()`** 이고, 권한이나 위치 서비스를 검사하지 않습니다. Android는 **위치 서비스(GPS 토글)가 꺼져 있으면 BLE 스캔 결과를 조용히 0건으로 반환**합니다. 오류가 없습니다.

[main.dart:61-77](gatekeeper_app/lib/main.dart#L61-L77)도 권한 거부를 `allGranted = false` 문자열로만 남기고 **그대로 스캔을 시작**합니다.

플러그인 자체 검사도 부정확합니다:
- [FlutterPlatform.java:50-58](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterPlatform.java#L50-L58) `checkLocationServicesPermission()`이 `ACCESS_COARSE_LOCATION`만 확인
- [FlutterPlatform.java:43-48](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterPlatform.java#L43-L48) `requestAuthorization()`이 위치 권한만 요청하고 **`BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT`(Android 12+)는 전혀 다루지 않음**
- 실제 앱은 `permission_handler`로 BT 권한을 요청하므로 현재는 우연히 커버되지만, 플러그인의 자체 판정은 여전히 거짓 양성을 냅니다

**수정**:
1. `BleScanner`에 스캔 전 게이트 추가 — 다음을 모두 확인하고, 하나라도 실패하면 스캔을 시작하지 않고 **명확한 사유를 `AppErrorLogger`와 알림에 남길 것**:
   - `Permission.locationWhenInUse` 승인
   - `Permission.locationAlways` 승인 (백그라운드)
   - `Permission.bluetoothScan` / `bluetoothConnect` 승인 (API 31+)
   - `Permission.notification` 승인
   - `flutterBeacon.bluetoothState == STATE_ON`
   - `flutterBeacon.checkLocationServicesIfEnabled == true` ← **가장 자주 놓치는 항목**
2. 실패 시 사용자에게 해결 경로 제시 (`openLocationSettings` / `openBluetoothSettings` / `openAppSettings`)
3. `FlutterPlatform.checkLocationServicesPermission()`에 API 31+ 분기로 `BLUETOOTH_SCAN` 확인 추가
4. P2-19의 진단 패널과 함께 구현하십시오 — 둘은 같은 데이터를 씁니다

### P1-9. 플러그인 `setScanPeriod` 계열 `return` 누락 → 호출 시 예외 🟠

[Plugin.java:170-191](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L170-L191)의 `setScanPeriod`, `setBetweenScanPeriod` 블록은 `result.success(true)` 후 **`return`이 없습니다.** 제어가 계속 흘러 마지막 [Plugin.java:308](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconPlugin.java#L308) `result.notImplemented()`까지 도달 → `IllegalStateException: Reply already submitted`.

또한 `call.argument("scanPeriod")`가 null이면 int 언박싱 NPE.

**수정**: 두 블록 끝에 `return;` 추가. `beaconManager` null 가드와 인자 null 가드 추가. **P0-2에서 스캔 주기 API를 쓰게 되므로 선행 수정입니다.**

### P1-10. 매니페스트 누락 🟠

[AndroidManifest.xml](gatekeeper_app/android/app/src/main/AndroidManifest.xml) 점검 결과:

| 항목 | 상태 | 조치 |
|---|---|---|
| `RECEIVE_BOOT_COMPLETED` | ❌ 없음 | [foreground_service.dart:59](gatekeeper_app/lib/services/foreground_service.dart#L59) `autoRunOnBoot: true`가 무효일 수 있음. 플러그인 매니페스트 병합에 의존하지 말고 **앱 매니페스트에 명시** |
| `FOREGROUND_SERVICE_CONNECTED_DEVICE` | ✅ 있음 | 유지 |
| `foregroundServiceType="connectedDevice"` | ✅ 있음 | 유지. 다만 "주변 기기 **탐색**" 용도는 `connectedDevice` 타입 정책 해석 여지가 있어, Play 정책 검토 후 `location` 병기 검토 |
| `BLUETOOTH_SCAN` | ✅ 있음 | `usesPermissionFlags="neverForLocation"`는 **붙이지 마십시오** — 위치 권한이 실제로 필요합니다. 대신 왜 위치 권한이 필요한지 주석으로 남길 것 |
| `targetSdk` | `flutter.targetSdkVersion` (SDK 버전에 따라 34/35) | [build.gradle.kts:33](gatekeeper_app/android/app/build.gradle.kts#L33). **명시적으로 고정하십시오.** Flutter SDK 업그레이드만으로 FGS 정책이 바뀌어 앱이 조용히 깨질 수 있습니다 |
| OEM 절전 | — | [foreground_service.dart:73-75](gatekeeper_app/lib/services/foreground_service.dart#L73-L75)가 배터리 최적화 제외는 요청하지만, **삼성/샤오미 등의 별도 "앱 절전" 목록은 이것으로 해제되지 않습니다.** 필드에서 상수적으로 발생하는 문제이므로 사용자 안내 화면(제조사별 설정 경로)이 필요합니다 |

### P1-11. 잘못된 UUID가 오면 monitoring NPE 🟠

[FlutterBeaconUtils.regionFromMap()](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconUtils.java#L100-L131)은 `Identifier.parse()` 실패 시 `IllegalArgumentException`을 잡고 **`null`을 반환**합니다.

- ranging 경로는 [Scanner.java:72-73](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconScanner.java#L72-L73)에서 null을 걸러냅니다 ✅
- **monitoring 경로는** [Scanner.java:177](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconScanner.java#L177) `regionMonitoring.add(region)` — **null 체크가 없습니다** ❌ → `startMonitoringBeaconsInRegion(null)`에서 NPE

트리거 경로가 실재합니다: [ble_scanner.dart:132-134](gatekeeper_app/lib/services/ble_scanner.dart#L132-L134)의 `fetchRemoteConfig`가 백엔드 `/config`의 `beacon_uuid`를 **검증 없이** `targetBeaconUuid`에 대입합니다. 백엔드가 빈 문자열이나 오타 값을 반환하면 monitoring이 NPE로 죽습니다.

**수정**:
1. `Scanner.java:177`에 `if (region != null)` 가드 추가
2. `regionFromMap`이 null을 반환할 때 `eventSink.error(...)`로 Dart에 알리기 (현재는 조용히 무시)
3. Dart 쪽 `fetchRemoteConfig`에 UUID 형식 검증 추가 (`RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')`), 실패 시 기본값 유지 + 로그

### P1-12. 백엔드가 사용자 로컬 쿨다운 설정을 매 부팅마다 덮어씀 🟠

[backend/app/main.py:387](backend/app/main.py#L387)이 `"cooldown_sec": 30`을 **하드코딩**하고, [ble_scanner.dart:135-137](gatekeeper_app/lib/services/ble_scanner.dart#L135-L137)이 이를 `cooldownSeconds`에 무조건 대입합니다. `SharedPreferences`에 저장된 사용자 설정([ble_scanner.dart:58](gatekeeper_app/lib/services/ble_scanner.dart#L58))이 매 부팅마다 30으로 덮어써지고, 새 값은 저장되지도 않습니다.

결과: 디버그 화면 슬라이더 표시값과 실제 동작이 재시작마다 어긋납니다.

**수정**: (택1, 정책 결정 필요)
- (a) 원격 값을 **기본값**으로만 쓰고, 사용자가 명시적으로 바꾼 적이 있으면(플래그 저장) 로컬 우선
- (b) 백엔드 값을 항상 우선하되 `SharedPreferences`에도 저장하고 UI를 read-only로 (로컬 슬라이더 제거)

→ **(a)를 권장합니다.** 디버그 화면의 슬라이더가 엔지니어 튜닝 목적이므로 로컬 우선이 자연스럽습니다. 아울러 백엔드의 하드코딩 `30`도 DB/환경변수 기반으로 바꾸십시오.

---

## 6. P2 — Medium

### P2-13. ESP32 iBeacon 페이로드 검증 (코드만으로 확정 불가 — 실측 필수) 🟡

> ⚠️ **이 항목은 추측으로 수정하지 마십시오.** git 이력(`bd92dbd` "restore required byte reversal loop")상 이 로직을 넣고 빼기를 반복한 흔적이 있습니다. **먼저 실측하고, 실측 결과에 따라 고치십시오.**

#### (a) UUID 바이트 순서 — 최우선 확인 대상

[main.cpp:86-95](src/main.cpp#L86-L95):
```cpp
uint8_t uuid_bytes[16];
memcpy(uuid_bytes, bleUUID.getNative()->u128.value, 16);
for(int i=0; i<8; i++){ /* 16바이트 반전 */ }
oBeacon.setProximityUUID(BLEUUID(uuid_bytes, 16, false));
```

내부 저장이 little-endian이라는 전제 하에서는 이 조합이 **이론상 올바른 MSB-first 광고**를 만듭니다. 하지만 틀리면 **앱의 Region 필터가 절대 매칭되지 않아 RSSI가 단 한 번도 올라오지 않습니다.**

**검증 방법 (유일하게 확실함)**: nRF Connect(또는 `btmon`)로 raw advertising 데이터를 보고, `4C 00 02 15` 다음 16바이트가 정확히 다음과 같은지 눈으로 확인:
```
A1 B2 C3 D4 E5 F6 78 90 AB CD EF 12 34 56 78 90
```
UUID가 회문(palindrome)이 아니므로 반전 여부가 즉시 구분됩니다. 역순으로 보이면 [main.cpp:89-93](src/main.cpp#L89-L93)의 반전 루프를 제거하거나 `BLEUUID(uuid_bytes, 16, true)`로 바꾸십시오.

#### (b) BLE 스택 정체 불명 — 주석과 코드가 불일치

주석과 [platformio.ini:29-32](platformio.ini#L29-L32)는 "내장 Bluedroid"라고 하지만, [main.cpp:88](src/main.cpp#L88)이 접근하는 `getNative()->u128.value`는 **NimBLE 타입 필드**입니다 (Bluedroid는 `->uuid.uuid128`). 스택이 바뀌면 이 라인의 의미가 통째로 달라집니다.

**조치**: 실제 빌드에서 어느 스택이 링크되는지 확인하고(`pio run -t size` 또는 `#if defined(CONFIG_BT_NIMBLE_ENABLED)` 프로브), 주석을 사실과 일치시키고, `platformio.ini`에 스택을 **명시적으로 고정**하십시오. 프레임워크 업그레이드만으로 조용히 깨지는 것을 막아야 합니다.

#### (c) Advertising Flags 비표준

[main.cpp:106](src/main.cpp#L106) `oAdvertisementData.setFlags(0x04)` — `BR_EDR_NOT_SUPPORTED`만 세팅하고 **`LE General Discoverable Mode (0x02)`가 빠져 있습니다.** 표준 iBeacon은 `0x1A`입니다.

AltBeacon은 manufacturer data를 직접 파싱하므로 보통 동작하지만, 일부 OEM BLE 스택이 non-discoverable 광고를 필터링할 수 있습니다. **`0x1A`로 변경하십시오** (페이로드 길이 여유 있음: flags 3B + manufacturer 27B = 30B ≤ 31B).

#### (d) measuredPower 미보정

[main.cpp:100](src/main.cpp#L100) `int8_t measuredPower = -59 + powerDbm;` → 9dBm에서 -50. 이는 추정치입니다. 현재 앱은 RSSI 임계값만 쓰므로 무해하지만, `accuracy`(거리)를 쓰려면 **실제 1m RSSI를 실측해 보정**해야 합니다.

#### (e) major/minor 엔디안

[main.cpp:96-97](src/main.cpp#L96-L97) `setMajor(1)/setMinor(1)` — Arduino `BLEBeacon`의 major/minor 엔디안 처리에 알려진 이슈가 있습니다. 현재 앱이 major/minor로 필터하지 않아 무해하지만, **나중에 필터를 추가하면 터집니다.** 지금 주석으로 경고를 남기거나 `ENDIAN_CHANGE_U16`을 적용하십시오.

#### (f) Tx Power 변경 시 광고 중단

[main.cpp:79-117](src/main.cpp#L64-L119) `setTxPower()`가 MQTT 수신 시 `pAdv->stop()` → 재구성 → `pAdv->start()`를 수행합니다. 그 순간 앱이 `didExitRegion`을 볼 수 있습니다(§5 P0-5의 IDLE 강등 트리거). 재시작 시간을 최소화하고, 앱 쪽 IDLE 강등에 히스테리시스를 두십시오.

### P2-14. 알림 갱신 폭주 (1Hz) 🟡

[ble_scanner.dart:262-285](gatekeeper_app/lib/services/ble_scanner.dart#L262-L285) — `_processBeacon`이 ranging 콜백마다(약 1Hz) `_updateNotification()`을 호출합니다. RSSI가 임계 미달이면 계속 반복됩니다. 매 호출이 플랫폼 채널 IPC + `NotificationManager` 갱신입니다.

**수정**: 알림에 반영할 문자열이 **실제로 변했을 때만** 갱신. 최소 갱신 간격(예: 2초) 스로틀 추가. `IDLE` 모드에서는 갱신 자체를 정지(P0-5).

### P2-15. RSSI 원시값 사용 → 임계값 판정 불안정 🟡

[ble_scanner.dart:249](gatekeeper_app/lib/services/ble_scanner.dart#L249) `final int rssi = beacon.rssi;` 는 [FlutterBeaconUtils.java:49](gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/com/flutterbeacon/FlutterBeaconUtils.java#L49) `beacon.getRssi()` = **마지막 패킷의 순간값**입니다. BLE RSSI는 순간 변동이 ±10dBm을 넘기 쉬워, [ble_scanner.dart:262](gatekeeper_app/lib/services/ble_scanner.dart#L262) `rssi < rssiThreshold` 판정이 문 앞에서 튑니다.

**수정 (역할 분리)**:
- **표시용**: 순간값 그대로 (디버그 화면은 원시값을 보는 게 목적)
- **판정용**: 별도의 평활값. Dart에서 EMA(`smoothed = α·rssi + (1-α)·smoothed`, α≈0.3)를 계산하거나, fork에서 `BeaconManager.setRssiFilterImplClass(ArmaRssiFilter.class)` 노출
- 임계값 통과 판정에 **히스테리시스** 추가 (진입 -70dBm / 이탈 -78dBm 식)

### P2-16. prearm 실패 시에도 쿨다운이 적용되어 재시도 차단 🟡

[ble_scanner.dart:287-288](gatekeeper_app/lib/services/ble_scanner.dart#L287-L288)에서 `_lastPrearmTime = now`를 **HTTP 요청 전에** 설정합니다. 요청이 타임아웃/실패해도 쿨다운(기본 10초, 원격값 30초)이 걸려 그 동안 재시도가 불가능합니다. 문 앞에 서 있는 사용자에게는 치명적입니다.

**수정**: 성공 시에만 `_lastPrearmTime`을 갱신하거나, 실패 시에는 짧은 재시도 쿨다운(1~2초)을 적용. [ble_scanner.dart:329-333](gatekeeper_app/lib/services/ble_scanner.dart#L329-L333) `catch` 블록에서 실패를 알림과 `AppErrorLogger`에 남기십시오 — **현재는 `debugPrint`만 하고 사용자에게 아무 표시가 없습니다.**

관련 사소한 버그: [ble_scanner.dart:74](gatekeeper_app/lib/services/ble_scanner.dart#L74) `setIgnoreCooldown`의 `_lastPrearmTime = DateTime.now(); // 리셋` — 주석은 "리셋"이지만 실제로는 **새 쿨다운을 시작**합니다. `null`이 의도였을 것입니다.

### P2-17. RSSI 카드 리빌드가 `packetCount`에 우연히 의존 🟡

[debug_screen.dart:200-210](gatekeeper_app/lib/screens/debug_screen.dart#L200-L210) `_buildRssiMonitorCard`는 `isBeaconConnected`와 `packetCount`만 `ValueListenableBuilder`로 듣고, `liveRssi`·`lastRssiUpdateTime`은 `.value`로 **직접 읽습니다.** 현재는 [ble_scanner.dart:252-255](gatekeeper_app/lib/services/ble_scanner.dart#L252-L255)에서 네 값이 동시에 갱신되어 우연히 동작합니다.

**수정**: `Listenable.merge([liveRssi, lastRssiUpdateTime, isBeaconConnected, packetCount])` + `ListenableBuilder` 사용. RSSI만 바뀌는 경로가 생겨도 화면이 굳지 않습니다.

### P2-18. `initialize()` 순서로 스캔 시작이 네트워크에 블로킹됨 🟡

[ble_scanner.dart:117-122](gatekeeper_app/lib/services/ble_scanner.dart#L117-L122):
```dart
await loadSavedPreferences();
await fetchRemoteConfig();              // 최대 5초
await UpdateChecker().checkForUpdates(); // 타임아웃 불명
startScanning();                         // ← 여기까지 스캔 없음
```
네트워크가 느리거나 NAS가 응답하지 않으면 스캔 시작이 수 초~수십 초 지연됩니다.

**수정**: `startScanning()`을 먼저 호출(로컬 기본 UUID 사용)하고, `fetchRemoteConfig`/`checkForUpdates`는 백그라운드로 던지십시오. 원격 UUID가 기본값과 **다를 때만** region을 재생성하십시오(재생성 시 P1-7의 직렬화 규칙 준수).

> 부수 사항: 현재 `fetchRemoteConfig`가 UUID를 바꿔도 이미 만들어진 `Region`은 갱신되지 않습니다([ble_scanner.dart:185-187](gatekeeper_app/lib/services/ble_scanner.dart#L185-L187)). 지금은 순서상 우연히 안전하지만, 순서를 바꾸면 **반드시 region 재생성 로직을 함께 넣으십시오.**

### P2-19. 진단 UI 부재 — "왜 안 되는지" 앱 안에서 알 수 없음 🟡

현재 디버그 화면은 RSSI와 로그만 보여주며, 실패 원인을 알려주는 수단이 없습니다. `AppErrorLogger`([error_logger.dart](gatekeeper_app/lib/services/error_logger.dart))는 메모리 100줄 링버퍼이므로 재시작하면 사라집니다.

**추가할 진단 패널** (P1-8과 같은 데이터 소스 사용):

| 표시 항목 | 출처 |
|---|---|
| 위치 권한 / 백그라운드 위치 권한 | `permission_handler` |
| BLUETOOTH_SCAN / CONNECT 권한 | `permission_handler` |
| 알림 권한 | `permission_handler` |
| 블루투스 ON/OFF | `flutterBeacon.bluetoothState` |
| **위치 서비스(GPS) ON/OFF** | `flutterBeacon.checkLocationServicesIfEnabled` |
| 배터리 최적화 제외 여부 | `FlutterForegroundTask.isIgnoringBatteryOptimizations` |
| 포그라운드 서비스 실행 여부 | `FlutterForegroundTask.isRunningService` |
| 현재 스캔 모드 (IDLE / ACTIVE / DEBUG) | §2.2 상태 머신 |
| monitoring / ranging 구독 상태 | `_streamMonitoring != null` / `_streamRanging != null` |
| 마지막 `didEnterRegion` / `didExitRegion` 시각 | 신규 필드 |
| 마지막 ranging 콜백 시각 · 누적 콜백 수 | 기존 `packetCount` 확장 |
| Target UUID (실제 사용 중인 값) | `targetBeaconUuid` |
| 마지막 prearm HTTP 결과 (코드 + 시각) | 신규 필드 |

각 항목에 ✅/❌ 배지와, ❌일 때 해결 버튼(설정 화면 열기)을 붙이십시오. 로그를 파일로 내보내는 기능(공유 인텐트)도 추가하면 현장 디버깅이 크게 쉬워집니다.

### P2-20. vendored fork 빌드 설정 노후화 🟡

[flutter_beacon_local/android/build.gradle](gatekeeper_app/android/app/libs/flutter_beacon_local/android/build.gradle):

| 항목 | 현재 | 조치 |
|---|---|---|
| `compileSdkVersion` | `33` | 앱은 34/35로 컴파일. 34+로 올리십시오 — 안 올리면 P0-2/P0-3에서 필요한 최신 API 상수를 못 씁니다 |
| AGP classpath | `3.5.1` (buildscript 블록) | Flutter 모듈 빌드에서는 무시되지만 혼란 유발. 제거 권장 |
| `namespace` | `com.alannmaulana.flutterbeacon` | Java 패키지는 `com.flutterbeacon`. 합법이지만 통일 권장 |
| `androidx.legacy:legacy-support-v4:1.0.0` | `api` 의존 | 사용처 없으면 제거 (deprecated) |
| AltBeacon | `2.19` | 유지. 단 `BeaconConsumer.bind()`는 2.19에서 deprecated된 레거시 API임을 인지할 것 |
| `flutter_beacon_local/pubspec.yaml` | `sdk: ">=2.12.0 <3.0.0"` | 앱은 `>=3.0.0 <4.0.0`. **`>=3.0.0 <4.0.0`으로 올리십시오.** 현재 lock 파일로 통과 중이나 clean `pub get`에서 깨질 수 있습니다 |

### P2-21. ESP32 WiFi/BLE 공존으로 광고 드롭 가능성 🟡

ESP32-C6는 WiFi와 BLE가 안테나/무선을 공유합니다. [main.cpp:266-357](src/main.cpp#L266-L357) loop가 MQTT를 유지하고, OTA·재연결·`WifiManager::startAP()`(AP 모드) 상황에서는 BLE 광고가 드롭될 수 있습니다. AP 모드 + BLE 동시 사용이 특히 취약합니다.

**조치**: 진단 항목으로 기록. 앱 쪽 RSSI 무수신 구간과 ESP32의 MQTT 재연결 로그 시각을 대조해 상관관계를 확인하십시오. 상관관계가 확인되면 광고 인터벌 조정([main.cpp:112-113](src/main.cpp#L112-L113), 현재 100ms) 또는 coexistence 설정 조정을 검토하십시오.

> 부수: [platformio.ini:27-28](platformio.ini#L27-L28)에 `; BLE Advertiser Tx Power 최대 출력 허용` 주석만 있고 **실제 플래그가 없습니다.** 오해를 유발하므로 주석을 제거하거나 실제 플래그를 넣으십시오.

---

## 7. P3 — 백로그 (이번 수정 범위 외, 별도 이슈로 분리 권장)

### P3-22. 백엔드 문 제어 fail-open + 인증 부재 🔴(보안) — ✅ 구현 완료

> **상태**: 커밋 `01c8e9c` 에서 수정되었습니다. 아래는 원래 발견 내용이며, 수정 내역과 배포 순서는 [IMPLEMENTATION_REPORT.md §3.5](IMPLEMENTATION_REPORT.md) 를 참조하십시오.

1. **인증이 전혀 없습니다.** [ble_scanner.dart:297-310](gatekeeper_app/lib/services/ble_scanner.dart#L297-L310)은 `Content-Type` 헤더만 보내고, [backend/app/main.py:464-465](backend/app/main.py#L464-L465) `door_prearm`에도 API 키 의존성이 없습니다. 저장소 전체에 `X-API-KEY` 검증 코드가 없습니다. README가 명시한 "엄격한 `X-API-KEY` 검증"과 불일치합니다.
2. **DB 예외 시 문이 열립니다.** [backend/app/main.py:494-497](backend/app/main.py#L494-L497)에서 세입자 검증 중 예외가 발생하면 로그만 남기고 통과하여, 아래 `publish_arm_to_mqtt(user_label, tenant_id)`가 **`tenant_id=1` / `"비콘자동감지"` 로 arm을 발행**합니다. DB가 죽으면 미등록 기기에도 문이 열립니다. **fail-open 설계입니다.**
3. **`device_id`가 비어 있으면 검증을 완전히 건너뜁니다** ([backend/app/main.py:473](backend/app/main.py#L473) `if req.device_id:`) → 무조건 arm.

**수정 방향**: API 키(또는 기기별 토큰) 검증 추가, DB 예외 시 **fail-closed**(403 반환), `device_id` 누락을 400으로 거부.

**✅ 적용된 수정** (`01c8e9c`)
- `/door/prearm` — `require_api_key` 의존성(X-API-KEY, 상수 시간 비교) + device_id 필수(400) + 미등록/미승인 403 + **DB 예외 503 fail-closed**
- `/door/open` — 같은 클래스의 결함이 있어 **함께 수정**했습니다. 이 엔드포인트는 초음파 게이트 없이 즉시 문을 열기 때문에 더 위험했습니다:
  - `device_id` 미등록이어도 `if row:` 를 통과해 개방되던 버그
  - `device_id` 없으면 무조건 개방되던 "마스터 개방" 경로 → 유효한 X-API-KEY 필수로 변경
  - DB 예외 → 503 fail-closed
- **세입자 잠금 방지**: `GATEKEEPER_API_KEY` 미설정 시 prearm 은 경고만 남기고 통과합니다. 여기서 막으면 키 설정 전까지 전 세대 출입이 불가능해집니다. 이 상태에서도 미등록/미승인/DB장애 fail-closed 는 유효하며, 마스터 개방만 불가합니다.
- `/health` 에 `api_key_auth` 노출 (키 값은 노출하지 않음)

> ⚠️ **배포 순서**: ① GitHub Secrets 등록 → ② 앱 재빌드·배포 후 세입자 업데이트 완료 대기 → ③ 서버 환경변수 설정·재시작.
> 순서를 바꾸면 구버전 앱이 401 로 거부되어 출입이 막힙니다. `backend/.env.example` 에도 명시했습니다.

### P3-25. `/admin/**` 및 `/admin` 페이지 무인증 🟠(보안) — P3-22 후속

P3-22 작업 중 분리된 항목입니다. 문 제어 API 는 막았지만 **관리자 API 는 여전히 무인증**입니다.

| 대상 | 위험 |
|---|---|
| `GET /admin` (HTML 페이지) | URL 을 아는 누구나 관리자 콘솔에 접근 |
| `GET /api/v1/admin/tenants` | 전체 세입자 명단·기기 ID 열람 (개인정보) |
| `POST /api/v1/admin/tenants/{id}/approve` \| `/reject` | **누구나 자신을 승인된 세입자로 만들 수 있음 → 문 열기와 동등** |
| `GET`/`POST /api/v1/admin/config` | Target 파라미터 원격 변경 (Tx Power, 감지 거리, 릴레이 쿨다운) |
| `GET /api/v1/logs` | 출입 이력 열람 |

특히 `approve` 는 P3-22 의 fail-closed 검증을 **정면으로 우회**합니다. 등록만 하고 스스로 승인하면 정상 세입자가 됩니다.

**왜 이번에 하지 않았는가**: 이 엔드포인트들은 정적 HTML 페이지(`admin.html`)에서 호출되므로, 브라우저가 비밀을 안전하게 보관할 수 없습니다. X-API-KEY 를 요구하면 관리자가 매번 키를 입력해야 하고 그 키가 브라우저에 남습니다. **세션 기반 로그인 설계가 필요하며, 이는 별도 설계 결정입니다.**

**수정 방향 (택1)**
- (a) 시놀로지 역방향 프록시에서 `/admin*` 경로에 HTTP Basic 인증 또는 IP 화이트리스트 적용 — **코드 변경 없음, 가장 빠름. 권장**
- (b) 백엔드에 세션 로그인(관리자 계정 + 쿠키) 도입 후 `/admin/**` 에 의존성 추가
- (c) 관리자 기능을 별도 내부망 전용 포트로 분리

→ **(a) 를 먼저 적용해 노출을 막고, 그 뒤에 (b) 를 검토하십시오.**

### P3-23. 고정 비콘 UUID → 스푸핑/리플레이 가능

[config.h:40](include/config.h#L40)의 UUID는 정적 하드코딩입니다. 누구나 같은 UUID로 광고하면 앱이 prearm을 발행합니다. README는 "전화번호 해시 기반 UUID/Major/Minor"라고 설명하지만 **실제 구현은 고정 UUID**입니다 — 문서와 코드가 불일치합니다.

현재 설계에서 실제 인증은 "앱이 백엔드에 `device_id`를 제시" 단계에서 이루어지므로(P3-22가 고쳐진다면) 치명적이지는 않으나, 비콘 UUID는 **인증 요소가 아니라 트리거**라는 점을 문서에 명확히 하십시오.

### P3-24. iOS 지원 선결 조건

vendored fork에 `ios/` 디렉터리와 `flutter_beacon.podspec`이 존재하므로 빌드 자체는 가능합니다. 다만 CI([build_app.yml](.github/workflows/build_app.yml))는 Android APK만 빌드합니다. iOS 착수 시 확인할 것:

- `Info.plist`에 `NSLocationWhenInUseUsageDescription`, `NSLocationAlwaysAndWhenInUseUsageDescription`, `NSBluetoothAlwaysUsageDescription` 필요
- Background Modes: `location updates` capability 필요
- [Region 생성자](gatekeeper_app/android/app/libs/flutter_beacon_local/lib/beacon/region.dart#L28-L41)가 iOS에서 `proximityUUID != null`을 **assert**합니다 — 현재 코드는 항상 지정하므로 OK
- **iOS는 §0.2-1의 제약이 없습니다.** CoreLocation region monitoring이 앱이 종료된 상태에서도 OS가 깨워주므로, iOS에서는 §2의 2단 모델이 훨씬 효율적으로 동작합니다. Android용으로 만든 "포그라운드 서비스 상주" 전제를 iOS에 그대로 옮기지 마십시오 — 심사에서 거부될 수 있습니다.
- iOS에서는 `setBackgroundMode` 등 Android 전용 메서드가 `notImplemented`가 되므로, Dart 래퍼에 `Platform.isAndroid` 가드를 넣으십시오.

---

## 8. 최종 검증 체크리스트

수정 완료를 주장하기 전에 **실기기에서** 다음을 전부 통과해야 합니다. 에뮬레이터로는 검증 불가입니다.

### 8.1 기능
- [ ] 앱 최초 실행 → 디버그 화면 진입 → RSSI가 1Hz로 갱신됨
- [ ] 디버그 화면 진입/이탈 **5회 반복** → 매번 RSSI 정상 (P0-1)
- [ ] 이미 비콘 구역 안에 있는 상태로 앱을 켬 → `didDetermineStateForRegion(INSIDE)` 처리로 ACTIVE 진입 (P0-5 함정 1)
- [ ] 비콘 전원 OFF → RSSI가 `연결 안됨`으로 전환되고 IDLE로 강등 → 전원 ON → 3초 이내 ACTIVE 복귀
- [ ] **화면 OFF 60초 → 화면 ON → 누적 패킷이 약 60개 증가** (P0-2 핵심)
- [ ] 홈 버튼으로 백그라운드 → 5분 → 알림 RSSI 계속 갱신 (P0-3)
- [ ] 개발자 옵션 **"활동 유지 안 함" ON** → 백그라운드 → 스캔 유지 (P0-3 결정적 재현)
- [ ] 화면 회전/다크모드 토글 10회 → AltBeacon 예외 없음, 바인딩 1개 유지
- [ ] 위치 서비스(GPS) OFF → **명확한 사유가 알림과 진단 패널에 표시됨** (P1-8)
- [ ] 블루투스 OFF → 동일하게 사유 표시, ON 시 자동 복구
- [ ] 백엔드 응답 없음 → prearm 실패가 사용자에게 표시되고, 2초 후 재시도됨 (P2-16)

### 8.2 반응 지연 (§2.3)
- [ ] `didEnterRegion` 지연 20회 측정, **p95 ≤ 3초**. 미달 시 Phase 2 판단 근거로 기록
- [ ] 임계값 통과 → prearm HTTP → ESP32 `PRE-ARMED` 로그까지의 종단 지연 측정

### 8.3 전력
- [ ] `adb shell dumpsys batterystats --charged <package>` 로 IDLE 8시간 대기 시 소모량 측정
- [ ] IDLE 모드에서 ranging 콜백/알림 갱신/`Timer.periodic`이 **실제로 정지**했는지 로그로 확인 (P0-5)
- [ ] ACTIVE ↔ IDLE 전환이 반복 진동(flapping)하지 않는지 — 히스테리시스 확인

### 8.4 송신부
- [ ] nRF Connect raw adv에서 `4C 00 02 15` 다음 16바이트가 `A1 B2 C3 D4 E5 F6 78 90 AB CD EF 12 34 56 78 90` (P2-13a)
- [ ] Flags가 `0x1A` (P2-13c)
- [ ] MQTT로 Tx Power 변경 → 앱이 IDLE로 오강등되지 않는지 (P2-13f)

### 8.5 회귀
- [ ] `flutter analyze` 무경고
- [ ] CI([build_app.yml](.github/workflows/build_app.yml)) 릴리즈 APK 빌드 성공
- [ ] 깨끗한 환경에서 `flutter pub get` 성공 (P2-20)

---

## 9. 파일 인덱스

| 파일 | 역할 | 관련 이슈 |
|---|---|---|
| [gatekeeper_app/lib/services/ble_scanner.dart](gatekeeper_app/lib/services/ble_scanner.dart) | 비콘 스캔·RSSI·prearm 핵심 로직 | P0-1, P0-5, P1-6, P1-7, P1-8, P1-11, P1-12, P2-14, P2-15, P2-16, P2-18 |
| [gatekeeper_app/lib/main.dart](gatekeeper_app/lib/main.dart) | 권한 요청, 초기화 순서 | P0-4, P1-8, P2-18 |
| [gatekeeper_app/lib/services/foreground_service.dart](gatekeeper_app/lib/services/foreground_service.dart) | 포그라운드 서비스 (현재 빈 핸들러) | P0-4, P1-10 |
| [gatekeeper_app/lib/screens/debug_screen.dart](gatekeeper_app/lib/screens/debug_screen.dart) | RSSI 표시 · 튜닝 UI | P0-1, P2-17, P2-19 |
| [gatekeeper_app/lib/services/error_logger.dart](gatekeeper_app/lib/services/error_logger.dart) | 인메모리 로그 링버퍼 | P2-19 |
| [gatekeeper_app/android/app/src/main/AndroidManifest.xml](gatekeeper_app/android/app/src/main/AndroidManifest.xml) | 권한 · FGS 선언 | P1-10 |
| [gatekeeper_app/android/app/build.gradle.kts](gatekeeper_app/android/app/build.gradle.kts) | targetSdk 등 | P1-10 |
| `flutter_beacon_local/android/.../FlutterBeaconPlugin.java` | 채널 등록 · MethodChannel | P0-2, P0-3, P1-9 |
| `flutter_beacon_local/android/.../FlutterBeaconScanner.java` | ranging/monitoring · BeaconConsumer | P0-3, P1-7, P1-11 |
| `flutter_beacon_local/android/.../FlutterBeaconUtils.java` | Region/Beacon 변환 | P1-11, P2-15 |
| `flutter_beacon_local/android/.../FlutterPlatform.java` | 권한 · 위치서비스 검사 | P0-3, P1-8 |
| `flutter_beacon_local/lib/flutter_beacon.dart` | Dart 채널 래퍼 | P0-2, P1-7 |
| `flutter_beacon_local/android/build.gradle` | AltBeacon 의존성 | P2-20 |
| [src/main.cpp](src/main.cpp) | ESP32 iBeacon 송신 · FSM | P2-13, P2-21 |
| [include/config.h](include/config.h) | 비콘 UUID 등 상수 | P2-13, P3-23 |
| [platformio.ini](platformio.ini) | BLE 스택 · 빌드 플래그 | P2-13b, P2-21 |
| [backend/app/main.py](backend/app/main.py) | `/config`, `/door/prearm` | P1-12, P3-22 |

---

## 10. 수정 담당 에이전트를 위한 주의사항

1. **P0-1을 가장 먼저, 단독 커밋으로 하십시오.** 3줄 변경으로 가장 눈에 보이는 증상이 사라집니다. 다른 변경과 섞으면 무엇이 효과를 냈는지 알 수 없습니다.
2. **관측 수단(P1-8 + P2-19)을 큰 구조 변경보다 먼저 확보하십시오.** 지금은 실패 원인을 앱 안에서 알 방법이 전혀 없습니다.
3. **P2-13은 실측 전에 코드를 고치지 마십시오.** git 이력이 이미 추측 기반 수정으로 왕복한 흔적을 보여줍니다.
4. **§0.2의 플랫폼 사실을 재확인 없이 뒤집지 마십시오.** 특히 "화면 OFF + 무필터 스캔 = 결과 0건"과 "AltBeacon 공개 API로는 필터+LOW_LATENCY 불가"는 이 문서 전체 설계의 전제입니다. 반증하려면 실기기 로그를 근거로 제시하십시오.
5. **에뮬레이터로 검증했다고 완료를 주장하지 마십시오.** BLE 스캔 throttling·Doze·OEM 절전은 실기기에서만 재현됩니다.
6. **커밋하지 마십시오** — 이 문서 작성 시점의 지시사항입니다. 별도 지시가 있을 때까지 작업 트리에만 변경을 남기십시오.
7. 완료 보고 시 §8 체크리스트의 각 항목에 **통과/미통과/미검증**을 명시하고, 미검증 항목을 숨기지 마십시오.
