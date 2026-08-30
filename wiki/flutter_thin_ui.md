# Flutter Thin UI, User Fallback, and Legacy Feature Flag Architecture (`wiki/flutter_thin_ui.md`)

> **Single Source of Truth**: Flutter Thin UI, immediate manual Local GATT open, and interlocked fallback specification
> **Last updated**: 2026-08-30

---

## 1. 개요 (Overview)

Issue #21 (`[APP][I8]`)에서는 Flutter 스마트폰 앱의 역할을 **BLE Scanner / Pre-arm 오케스트레이터에서 Credential 관리, 1-Tap 수동 출입 및 상태 대시보드 UI**로 축소(Thin UI)하고, 백그라운드 자동 Wake 차단 시 사용자가 즉시 복구할 수 있는 **1-Tap terminal Local GATT action-2 open**과 **앱 재설치 없는 Legacy 롤백 / Kill-switch**를 제공한다.

---

## 2. 핵심 구성 요소를 (Core Components)

### 2.1 Native-authoritative Credential and Target ACL Status
- **Device ID**: 설치별 영구 랜덤 ID (`DeviceIdService`)이며 Backend enrollment의 식별자로 사용한다.
- **기기 키 상태**: `NativeGattWorkerHealthBridge`의
  `credentialProvisioned`와 `localConsentValid`를 함께 확인한다. Flutter
  `SharedPreferences` 값을 승인 근거로 사용하지 않는다.
- **Target ACL 상태**: 성공한 native GATT 세션이 반환한
  `lastActiveAclVersion`이 양수일 때만 `등록 · ACL 확인됨`으로 표시한다.
  키는 있지만 성공 세션 증거가 없으면 `키 등록됨 · ACL 미확인`으로
  구분한다.
- **오류 경계**: Native bridge를 읽지 못한 상태는 `미등록`으로 오인하지
  않고 `상태 확인 불가`로 표시한다.
- **Tenant 권한 경계**: Tenant 승인/회수는 Backend 관리 상태다. 앱은
  Backend 요청 없이 로컬 이름·호수·상태만 저장하던 기존 등록 폼을
  제공하지 않으며, UI도 Tenant 승인을 추정하지 않는다.

### 2.2 1-Tap Explicit Manual Local GATT Open
- **목적**: 삼성 One UI, 샤오미 MIUI 등 OEM 백그라운드 절전 정책이나 위치/Bluetooth 권한 차단으로 인해 자동 비콘 스캔/Wake가 실패한 경우 사용자가 단 1회의 터치로 출입 시도.
- **채널 연동**: WebView `open_door`와 `SmartKeyControlScreen`의 `1-Tap 수동 로컬 개방`은 모두 `triggerLocalGattOpen`을 호출하고 foreground coroutine에서 GATT action 2를 즉시 실행한다. 진단용 `triggerLocalGattRetry`의 WorkManager queue 수락은 문 열림 성공으로 취급하지 않는다.
- **완료 의미**: Target terminal `RESULT OK` / native `OPENED`는 인증된 개방 명령이 Target FSM에서 실행되었음을 뜻한다. 앱은 `개방 명령 실행 완료`와 latency를 표시하되 `실제 문 열림은 별도 확인이 필요`함을 함께 밝힌다. 릴레이 접점·actuator·문 상태를 보증하는 독립 이벤트 없이 `문 열림 확인`으로 승격하지 않는다. Target non-OK와 transport 실패는 실패, proof 불확실은 자동 재시도 금지 결과로 표시한다.
- **action-1 선행 상태**: background action 1이 이미 Target을 `ARMED`로 만든 경우에도 새 인증 세션이 기존 sensor-waiting arm을 `AUTH_PENDING`으로 대체한 뒤 action 2를 검증한다. `RELAY_HOLD`와 `COOLDOWN`은 대체하지 않는다. Target Hello busy status는 `TARGET_BUSY`로 표시하며 protocol version 오류로 오인하지 않는다.
- **네트워크 경계**: 최초 credential/ACL enrollment에는 HTTPS가 필요하지만 이미 유효한 local consent가 있으면 버튼 실행 시 backend status GET이나 MQTT를 기다리지 않는다.
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
- `credentialProvisioned`, `localConsentValid`, `lastActiveAclVersion`

### 2.5 OTA P0 Non-Regression Contract (`UpdateChecker`)
- **독립성 유지**: 앱 업데이트 확인 및 다운로드 UI는 BLE Scanner, Native Worker, WebView, Tenant 승인 여부와 독립적으로 언제나 접근 가능.
- **안전성**: 다운로드 후 APK hash/signing identity를 검증하며, 설치 실패 시 기존 APK를 안전하게 보존.

---

## 3. UI 구조 (Screen Navigation)

```
SmartKeyApp (MaterialApp)
 ├── WebViewScreen (메인 앱 화면)
 │    └── AppBar Actions
 │         ├── ⚙️ AppSettingsScreen (단일 설정 진입점)
 │         │    ├── Smart Key 탭 → SmartKeyControlScreen
 │         │    └── 진단·튜닝 탭 → DebugScreen
 │         └── 🔄 Refresh
 ├── SetupScreen (필수 권한/배터리 예외 요청)
 └── RecoveryShellScreen
      └── ⚙️ AppSettingsScreen (동일한 단일 설정 진입점)
```

`SmartKeyControlScreen`과 `DebugScreen`은 기존 직접 라우트 호환성을
유지하지만, 사용자에게 노출되는 WebView/복구 네비게이션은
`AppSettingsScreen` 하나로 통일한다. 탭 구조는 Target 실시간 감지,
1-Tap 수동 개방, credential/feature flag, 독립 OTA, RSSI/스캔 진단,
Target 튜닝 및 로그 기능을 삭제하지 않고 하나의 설정 면으로 묶는다.

---

## 4. 검증 내역 (Verification)

- **Flutter Unit Tests**: native 자격/ACL projection을 포함한 전체 45개 PASS
- **Flutter Code Analysis**: 변경 Flutter 파일 targeted analysis (No issues found!)
- **Android Native Tests**: `gattworker.*` unit suite와 debug Kotlin compile PASS
- **Host C++ Unit Tests**: `wsl ./test_runner` (369 checks PASS)
- **Repository Contracts**: `python3 -m unittest discover -s tests` (317 PASS, 1 expected skip)
- **Vector Verifier**: `verify_vectors.py` (PASS)
- **OTA Contract Gate**: `ota_contract_gate.py contract` (PASS)
