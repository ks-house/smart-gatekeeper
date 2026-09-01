# Flutter Thin UI, User Fallback, and Legacy Feature Flag Architecture (`wiki/flutter_thin_ui.md`)

> **Single Source of Truth**: Flutter Thin UI, immediate manual Local GATT open, and interlocked fallback specification
> **Last updated**: 2026-09-02

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
- **action-1 선행 상태**: background action 1이 Target을 `ARMED`로 만들면 새 action 2는
  인증 전 `TargetHello/BUSY`로 거부되며 기존 sensor-waiting 세션을 대체하지 않는다.
  앱은 `TARGET_BUSY`를 protocol version 오류로 오인하지 않고, exact-session 상태의
  `다음 인증 가능`(fresh `IDLE` + relay OFF)을 확인한 뒤 사용자가 다시 시도하게 한다.
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

### 2.6 Exact-session Target completion status

- **기존 성공의 의미**: Native action-1 `SUCCEEDED`와 알림 `출입 준비 완료`는 AndroidKeyStore
  proof가 Target에서 승인되고 FSM이 sensor 대기 `ARMED`에 들어간 상태다. Sensor 감지, relay
  ON/OFF, cooldown 종료 또는 실제 문 열림까지 완료됐다는 뜻이 아니다.
- **정확한 session 결합**: Native Result의 lowercase UUIDv4 `lastTargetSessionId`를 Flutter에
  전달한다. Flutter는 이 ID를 임의로 만들거나 현재 Target 전역 상태로 대체하지 않는다.
  Android native code는 현재 non-exportable credential key로
  `SGKASR01 || credential_id || target_session_id || 32-byte nonce || expires_at`의 고정
  80-byte input을 서명한다. Proof TTL은 20초이며 Backend 허용 상한 30초 안에 둔다.
- **bounded polling**: 앱은 action-1 `SUCCEEDED` 직후 정확한 session 하나를 4초 간격으로 최대
  120초 조회한다. 429는 최소 4초의 `Retry-After`, network/5xx는 4/8/16초 최대 3회만 재시도한다.
  매 poll은 새 nonce/proof를 만들고 Backend의 durable credential nonce ledger가 검증 직후 한 번만
  소비한다. 같은 proof replay, 400/401/403/422와 예상 밖 응답은 lookup을 끝내며 BLE 성공 상태를
  변조하지 않는다.
- **신뢰 경계**: Backend는 active credential, exact door grant, session-bound Target HMAC actor
  ref, signed event/status와 current boot를 검증한다. 다른 사람이나 이전 session의 Target global
  state는 반환하지 않는다. 앱은 raw MQTT를 직접 읽거나 이름/호수로 session을 추측하지 않는다.
- **표시 단계**: `출입 준비 완료 · 센서 대기` → `센서 감지 · 개방 동작 중` → `개방 동작 완료 ·
  다음 출입 준비 중` → `출입 동작 완료 · 다음 인증 가능` 또는 `출입 동작 종료`를 표시한다.
  `다음 인증 가능`은 signed terminal과 fresh Target `IDLE`, relay command OFF 및 configured OFF
  pin level이 모두 맞을 때만 표시한다. Target가 AUTH_PENDING~COOLDOWN 동안 MQTT를 보류하므로
  중간 문구는 실시간 전환을 보장하지 않는다. 4초 poll은 도착한 최선 evidence를 보여 주며
  `센서 대기`에서 최종 완료로 바로 건너뛸 수 있다.
- **재인증 동작**: Terminal 표시가 다음 BLE scan, WorkManager job 또는 GATT proof를 자동 생성하지
  않는다. 사용자가 아직 같은 beacon 영역에 머무는 동안의 OEM FIRST_MATCH/re-entry 조건은 별도다.
- **물리 경계**: `센서 감지`, relay OFF, `다음 인증 가능`은 Target software/FSM/GPIO 결과다.
  현재 door-contact sensor가 없으므로 실제 문짝이 열리거나 닫혔다고 표시하지 않는다.
- **power-loss/N-1**: 최신 terminal summary는 Target same-boot RAM best-effort다. Backend 수신 전
  power loss 또는 Target N-1 rollback으로 signed summary가 없으면 앱은 ARMED 또는 확인 불가에서
  안전하게 멈추고 `complete`를 합성하지 않는다. 기존 APK/Target OTA recovery 경로는 유지한다.

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

- **Flutter Unit Tests**: Flutter 3.44.8/Dart 3.12.2에서 exact-session polling을 포함한 전체 95개 PASS
- **Flutter Formatting/Analysis**: `lib`, `test` 54개 파일 format 변경 0건, 전체 analysis `No issues found!`
- **Android Native Tests**: Gradle 9.1.0 debug JVM unit 전체 70개 PASS(실패/오류/skip 0), Kotlin debug compile PASS
- **Final mobile security review**: Native Result의 canonical UUIDv4만 조회에 사용하고, 매 poll의 새
  AndroidKeyStore 80-byte proof는 Backend가 evidence read 전에 durable ledger에서 한 번만 소비한다.
  다른 session 응답은 UI 상태에 결합하지 않으며, terminal/failsafe는 fresh signed IDLE/relay-OFF
  없이 `다음 인증 가능`으로 승격되지 않는다. Poll은 dispose/session 교체/terminal/120초 deadline에
  종료되고 BLE scan, WorkManager 또는 GATT 인증을 자동 재시작하지 않는다.
- **Host C++ Unit Tests**: `wsl ./test_runner` (369 checks PASS)
- **Repository Contracts**: `python3 -m unittest discover -s tests` (317 PASS, 1 expected skip)
- **Vector Verifier**: `verify_vectors.py` (PASS)
- **OTA Contract Gate**: `ota_contract_gate.py contract` (PASS)
- **Exact-main mobile publication**: PR #278 merge main `b96afb7...`, run `33298655135` personal signed primary/fallback OTA and strict HTTPS readback PASS; connected replacement install/ko-en readback pending

위 목록의 과거 exact-main publication은 §2.6 candidate의 phone 설치 증거가 아니다. 새 상태 계약은
canonical UUID/80-byte proof, polling rate/backoff/terminal 조건과 locale 문구의 host tests로 검증하되,
최종 합격은 reviewed exact-main APK replacement install, matching Target/Backend 배포, 한 번의 실제
sensor/relay cycle과 다음 인증 시도에서 별도로 기록한다. Door-contact가 추가되기 전에는 그 시험도
physical door leaf confirmation으로 승격하지 않는다.
