# Flutter Thin UI, User Fallback, and Legacy Feature Flag Architecture (`wiki/flutter_thin_ui.md`)

> **Single Source of Truth**: Flutter Thin UI, 1-Tap Local GATT Retry, and Interlocked Fallback Specification
> **Last updated**: 2026-08-05

---

## 1. 개요 (Overview)

Issue #21 (`[APP][I8]`)에서는 Flutter 스마트폰 앱의 역할을 **BLE Scanner / Pre-arm 오케스트레이터에서 Credential 관리, 1-Tap 수동 출입 및 상태 대시보드 UI**로 축소(Thin UI)하고, 백그라운드 자동 Wake 차단 시 사용자가 즉시 복구할 수 있는 **1-Tap 수동 Local GATT Retry**와 **앱 재설치 없는 Legacy 롤백 / Kill-switch**를 제공한다.

---

## 2. 핵심 구성 요소를 (Core Components)

### 2.1 Credential & Tenant Approval Lifecycle (`CredentialService`)
- **Device ID**: Android HW/Installation 고유 식별자 (`DeviceIdService`)
- **Tenant Approval Status**:
  - `APPROVED` (🟢 승인 완료): 로컬 ACL 갱신 및 백그라운드 자동 GATT 출입 허용
  - `PENDING` (⏳ 승인 대기): 동의 등록 제출 후 승인 대기
  - `REVOKED` (🔴 권한 회수): 관리자에 의해 ACL 차단됨
  - `UNREGISTERED` (⚪ 미등록): 최초 실행 상태
- **ACL Lease Snapshot**: 로컬 저장소에 고정된 ACL 버전을 표시하며 만료 시 갱신 유도

### 2.2 1-Tap Explicit Manual Local GATT Retry (`SmartKeyControlScreen`)
- **목적**: 삼성 One UI, 샤오미 MIUI 등 OEM 백그라운드 절전 정책이나 위치/Bluetooth 권한 차단으로 인해 자동 비콘 스캔/Wake가 실패한 경우 사용자가 단 1회의 터치로 출입 시도.
- **채널 연동**: `MethodChannel('com.kshouse.gatekeeper_app/ble_gatt_worker_health')`의 `triggerLocalGattRetry` 호출 ➡️ `BleGattWorkScheduler.onPresence(appContext, "TARGET_LOCAL", eventId)` 실행.
- **인터락**: Remote Kill-Switch 활성화 시 수동 출입 시도가 차단되고 경고 메시지를 표시.

### 2.3 Feature Flags & Interlocked Fallback (`FeatureFlagService`)
- **플래그 종류**:
  1. `ENABLE_HARDWARELESS_RC`: Hardwareless GATT 로컬 인증 경로
  2. `ENABLE_LEGACY_PREARM`: 구형 서버 REST Pre-arm 경로
  3. `REMOTE_KILL_SWITCH`: 원격 비상 차단 스위치
- **중복 ARM 방지 인터락 (Interlock)**: `ENABLE_HARDWARELESS_RC`가 `true`로 설정되면 `ENABLE_LEGACY_PREARM`은 자동으로 `false`로 강제 조율되어 동일 비콘 수신 시 중복 ARM 트리가 발생하지 않음.
- **In-App Rollback**: 문제 발생 시 앱 재설치 없이 `ENABLE_LEGACY_PREARM = true`, `ENABLE_HARDWARELESS_RC = false`로 즉시 롤백 가능.

### 2.4 Native GATT Worker Health Status (`NativeGattWorkerHealthBridge`)
- `healthy` (🟢 / 🔴)
- `bleOwner` (`native_worker` vs `legacy`)
- `lastReasonCode`, `lastTargetReasonName`, `lastLatencyMs`

### 2.5 OTA P0 Non-Regression Contract (`UpdateChecker`)
- **독립성 유지**: 앱 업데이트 확인 및 다운로드 UI는 BLE Scanner, Native Worker, WebView, Tenant 승인 여부와 독립적으로 언제나 접근 가능.
- **안전성**: 다운로드 후 APK hash/signing identity를 검증하며, 설치 실패 시 기존 APK를 안전하게 보존.

---

## 3. UI 구조 (Screen Navigation)

```
SmartKeyApp (MaterialApp)
 ├── WebViewScreen (메인 앱 화면)
 │    └── AppBar Actions
 │         ├── 🎛️ SmartKeyControlScreen (Smart Key 대시보드 & 1-Tap 수동 제어)
 │         ├── 🛠️ DebugScreen (엔지니어 디버그 모드)
 │         └── 🔄 Refresh
 └── SetupScreen (필수 권한/배터리 예외 요청)
```

---

## 4. 검증 내역 (Verification)

- **Flutter Unit Tests**: `flutter test` (5/5 tests PASS)
- **Flutter Code Analysis**: `flutter analyze` (No issues found!)
- **Host C++ Unit Tests**: `wsl ./test_runner` (369 checks PASS)
- **Python Unit Tests**: `python -m unittest discover -s tests` (87/87 PASS)
- **Observability Tests**: `python -m unittest discover -s observability/tests` (18/18 PASS)
- **Vector Verifier**: `verify_vectors.py` (PASS)
- **OTA Contract Gate**: `ota_contract_gate.py contract` (PASS)
