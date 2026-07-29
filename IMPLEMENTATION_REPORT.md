# 구현 완료 리포트 — 비콘 RSSI / 전력 최적화 수정

**대상 이슈**: [issue.md](issue.md)
**브랜치**: `fix/beacon-rssi-and-power` (base: `main` @ `8e1358d`)
**커밋 수**: 14 · **변경**: 24개 파일
**푸시**: 하지 않음 (지시에 따름)

---

## ⚠️ 먼저 읽어야 할 검증 한계

이 작업은 **빌드 검증도, 실기기 검증도 하지 않았습니다.** 사용자 지시("실측 테스트를 하기 힘든 상황이다, 빌드 테스트는 하지 않고")에 따른 것입니다. 환경 확인 결과도 그와 일치합니다:

```
$ which flutter dart   →  (없음)
$ ls ~/.pub-cache/hosted/pub.dev/  →  0개 (비어 있음)
```

따라서 아래 서술을 이렇게 구분해서 읽으십시오.

| 표기 | 의미 |
|---|---|
| ✅ **구현** | 코드를 작성했고, 아래 §4의 정적 검증을 통과했다 |
| 🧪 **미검증** | 컴파일·동작을 확인하지 않았다. **모든 항목이 여기에 해당한다** |
| ⏸️ **미수행** | 의도적으로 하지 않았다. 사유를 명시했다 |

**즉 "동작한다"고 주장할 수 있는 항목은 하나도 없습니다.** §5의 검증 체크리스트를 실기기에서 통과시켜야 완료입니다.

---

## 1. 처리 결과 요약

### P0 (Blocker)

| ID | 제목 | 상태 |
|---|---|---|
| P0-1 | ranging 스트림 영구 정지 | ✅ 구현 |
| P0-2 | 화면 OFF 시 스캔 결과 폐기 | ✅ 구현 (fork + 호출부) |
| P0-3 | 플러그인 Activity 수명주기 결합 | ✅ 구현 |
| P0-4 | 스캔이 UI isolate에서 동작 | ⚠️ **부분 구현** — §3 참조 |
| P0-5 | ranging 상시 ON (전력) | ✅ 구현 |

### P1 (High)

| ID | 제목 | 상태 |
|---|---|---|
| P1-6 | 3초 타임아웃 상충 | ✅ 6초 + 4회 연속 판정 |
| P1-7 | EventChannel 중복 구독 | ✅ 뮤텍스 직렬화 |
| P1-8 | 위치서비스/권한 무검증 | ✅ 프리플라이트 게이트 (앱 + 플러그인) |
| P1-9 | `setScanPeriod` return 누락 | ✅ 구현 |
| P1-10 | 매니페스트 누락 | ✅ `RECEIVE_BOOT_COMPLETED` · ⏸️ targetSdk 고정 |
| P1-11 | 잘못된 UUID → monitoring NPE | ✅ 네이티브 가드 + Dart 검증 |
| P1-12 | 백엔드가 로컬 쿨다운 덮어씀 | ✅ 앱 + 백엔드 양쪽 |

### P2 (Medium)

| ID | 제목 | 상태 |
|---|---|---|
| P2-13 | ESP32 iBeacon 페이로드 | ✅ Flags 0x1A · ⏸️ **UUID 바이트 순서는 손대지 않음** — §3 |
| P2-14 | 알림 갱신 폭주 | ✅ 중복 차단 + 2초 스로틀 |
| P2-15 | RSSI 원시값 판정 | ✅ EMA(α=0.3) + 8dB 히스테리시스 |
| P2-16 | 실패 시 쿨다운 차단 | ✅ 성공/403만 정상 쿨다운, 실패는 2초 |
| P2-17 | 리빌드가 packetCount에 의존 | ✅ `Listenable.merge` |
| P2-18 | 초기화 순서 블로킹 | ✅ 스캔 먼저, 원격 설정은 백그라운드 |
| P2-19 | 진단 UI 부재 | ✅ 진단 패널 신규 |
| P2-20 | fork 빌드 설정 노후화 | ⚠️ 부분 — compileSdk 34 + Dart SDK 제약, 나머지 TODO |
| P2-21 | WiFi/BLE 공존 | ⏸️ 조사 항목 — 주석으로 기록 |

### P3 (백로그)

| ID | 제목 | 상태 |
|---|---|---|
| P3-22 | 백엔드 문 제어 fail-open + 인증 부재 | ✅ **구현** — §3.5 참조 |
| P3-25 | `/admin/**` 무인증 (P3-22 후속 신설) | ⏸️ 미수행 — §3.6 참조 |
| P3-23 | 고정 비콘 UUID 스푸핑 | ⏸️ 미수행 (설계 변경) |
| P3-24 | iOS 선결 조건 | ⏸️ 미수행 (Android 우선 결정) |

---

## 2. 커밋별 내용

각 커밋은 독립적으로 되돌릴 수 있도록 이슈 단위로 분리했습니다. 특히 `6ab97e8`(P0-1)은 3줄 변경이므로 **이것만 먼저 배포해 효과를 분리 측정**할 수 있습니다.

| 커밋 | 내용 |
|---|---|
| `abf3ebe` | `issue.md` 근본 원인 분석 문서 |
| `6ab97e8` | **P0-1** — `cancel()` 후 `null` 대입, DebugScreen `forceRestart` 제거 |
| `ee0e900` | **P0-2 / P1-9** — fork에 `setBackgroundMode` 등 4개 노출, return 누락 수정 |
| `ea735df` | **P0-3 / P1-11** — 플러그인을 engine/applicationContext 소유로 리팩터 |
| `863fcb2` | **P0-5 / P1-6,7,8,12 / P2-14,15,16,18** — `BleScanner` 2단 상태 머신 |
| `28ef316` | **P2-19 / P2-17** — 진단 패널, 리빌드 병합 |
| `4be60fe` | **P0-4 부분** — 서비스 시작 순서, 생애주기 복구 |
| `80bc2bc` | **P1-10 / P2-20** — 매니페스트, fork 빌드 설정 |
| `0be9a33` | **P2-13 / P2-21** — AD Flags 0x1A, 미검증 위험 문서화 |
| `f81722b` | **P1-12** — 백엔드 `APP_COOLDOWN_SEC` 분리 |
| `10dcdf9` | 정적 자가 검토에서 찾은 결함 5건 수정 |
| `d2d7ca8` | 완료 리포트 초판 |
| `7099058` | **P0-4 한계 문서화** — `wiki/mobile_app_scan_lifecycle.md` 신규 |
| `01c8e9c` | **P3-22** — 문 제어 fail-closed 전환 + X-API-KEY 인증 |

---

## 3. 의도적으로 하지 않은 것 (중요)

### 3.1 P0-4 안 A — 스캐너를 서비스 isolate로 이전 ⏸️

**하지 않았습니다.** 사유:

`flutter_foreground_task` 6.2.0의 isolate 통신 API(`sendDataToMain` / `sendDataToTask` / `receivePort`)를 이 환경에서 **확인할 수 없습니다.** pub 캐시가 비어 있고 빌드도 불가하므로, 기억에 의존해 IPC 코드를 작성하면 컴파일되지 않을 가능성이 매우 높습니다. 동작하지 않는 코드를 넣는 것보다 명시적으로 남기는 편이 낫다고 판단했습니다.

**대신 구현한 것** (안 B + 안전망):
- 포그라운드 서비스를 스캔보다 먼저 시작
- `WidgetsBindingObserver`로 포그라운드 복귀 시 상태 점검·복구
- `BleScanner` 내부 30초 워치독 — monitoring 구독 소실이나 차단 사유 해소를 감지해 자동 재시작

**남는 한계** (`GatekeeperTaskHandler` 문서 주석에도 기록):

| 상황 | Activity 파괴? | 스캔 유지? |
|---|---|---|
| 화면 OFF | ❌ 아니오 | ✅ 유지 (P0-2 수정이 적용된다면) |
| 홈 버튼 / 앱 전환 | ❌ 아니오 | ✅ 유지 |
| "활동 유지 안 함" ON | ✅ 예 | ❌ **멈춤** |
| 강한 메모리 압박 | ✅ 가능 | ❌ **멈춤** |
| 최근앱 스와이프 종료 | ✅ 예 | ❌ 멈춤 (요구사항 아님) |

즉 **승인하신 "포그라운드 서비스 상주 전제" 범위는 대체로 커버되지만, Activity가 파괴되는 경로는 여전히 취약합니다.** 빌드 환경이 확보되면 안 A를 진행하십시오.

> 📄 **이 한계는 위키에 정식 문서로 남겼습니다** — [wiki/mobile_app_scan_lifecycle.md](wiki/mobile_app_scan_lifecycle.md).
> Android 플랫폼 제약, 상황별 동작 매트릭스, 완화 장치의 한계, 근본 해결책의 작업 범위, 신고 대응 순서, 코드 수정자가 지켜야 할 규칙까지 포함합니다.
> `wiki/index.md` 내비게이션과 `wiki/log.md` 이력에도 반영했습니다. (커밋 `7099058`)

### 3.2 P2-13a — ESP32 UUID 바이트 순서 ⏸️

**고치지 않았습니다.** issue.md §10-3의 지침("실측 전에 코드를 고치지 마십시오")을 그대로 따랐습니다.

현재 조합(수동 16바이트 반전 + `msbFirst=false`)은 내부 저장이 LSB-first라는 전제에서 이론상 올바릅니다. 그러나 그 전제는 BLE 스택(Bluedroid vs NimBLE)과 Arduino-ESP32 버전에 따라 달라지고, 코드가 접근하는 `getNative()->u128.value`는 NimBLE 타입 필드인데 주변 주석은 Bluedroid라고 적혀 있어 **실제 링크되는 스택이 불명확합니다.** git 이력(`bd92dbd`)도 이 로직을 넣고 빼기를 반복한 흔적을 보여줍니다.

틀리면 앱이 비콘을 전혀 인식하지 못하는 치명적 지점이므로, 추측 수정 대신 **검증 절차를 코드 주석으로 남겼습니다** ([src/main.cpp:87-117](src/main.cpp#L87-L117)).

> **가장 먼저 해야 할 확인**: nRF Connect로 raw advertising을 열어 `4C 00 02 15` 다음 16바이트가 정확히
> `A1 B2 C3 D4 E5 F6 78 90 AB CD EF 12 34 56 78 90` 인지 보십시오. UUID가 회문이 아니라 반전 여부가 즉시 구분됩니다.

### 3.3 P1-10 — targetSdk 명시적 고정 ⏸️

현재 `targetSdk = flutter.targetSdkVersion`입니다. 임의의 값으로 고정하면 Play 정책 요구 수준(오늘 기준으로 34인지 35인지 36인지)을 확인할 수 없는 상태에서 릴리즈를 깨뜨릴 수 있습니다. issue.md에 남겨 두고, 빌드 환경에서 `flutter --version`과 Play Console 요구사항을 확인한 뒤 고정하십시오.

### 3.4 P2-20 — fork 빌드 설정 일부 ⚠️

`compileSdkVersion 33 → 34`와 Dart SDK 제약(`<3.0.0` → `>=3.0.0 <4.0.0`)만 반영했습니다. 다음 3건은 제거 시 빌드 검증이 필요해 `TODO(issue.md P2-20)` 주석으로만 남겼습니다.

- AGP 3.5.1 `buildscript` 블록 잔재
- `namespace`(`com.alannmaulana.flutterbeacon`)와 Java 패키지(`com.flutterbeacon`) 불일치
- deprecated `androidx.legacy:legacy-support-v4` — 이 플러그인이 `androidx.core`(ActivityCompat/ContextCompat)를 여기서 전이로 얻고 있어, 제거하려면 `androidx.core:core`를 명시 추가해야 합니다

### 3.5 P3-22 — 백엔드 문 제어 fail-open ✅ **구현 완료** (`01c8e9c`)

지시에 따라 이 브랜치에서 처리했습니다. 발견된 fail-open 은 두 엔드포인트에 걸쳐 있었고, **`/door/open` 이 더 위험했습니다** — 초음파 게이트 없이 즉시 문을 여는 경로이기 때문입니다.

#### 수정 전

| 엔드포인트 | fail-open 경로 |
|---|---|
| `/door/prearm` | ① `device_id` 없으면 검증 생략 후 arm ② DB 예외 시 로그만 남기고 `tenant_id=1` 로 arm ③ 인증 없음 |
| `/door/open` | ① `device_id` 없으면 검증 없이 개방 (관리자 "마스터 개방"이 이에 의존) ② 미등록 기기여도 `if row:` 통과해 개방 ③ DB 예외 시 개방 |

②번이 특히 문제였습니다 — **DB가 죽으면 미등록 기기에도 문이 열렸습니다.**

#### 수정 후

두 엔드포인트 공통으로 다음을 모두 거부합니다.

| 조건 | 응답 |
|---|---|
| `device_id` 누락 | 400 |
| 미등록 기기 | 403 |
| 미승인(`is_active=False`) 세입자 | 403 |
| DB 예외 | **503 (fail-closed — 절대 arm/open 하지 않음)** |

- `/door/prearm` → `require_api_key` 의존성 추가 (`X-API-KEY`, `secrets.compare_digest` 상수 시간 비교)
- `/door/open` → 두 경로만 허용: **세입자 경로**(등록+승인된 `device_id`) 또는 **마스터 경로**(`device_id` 없이 유효한 `X-API-KEY`). 관리자 콘솔은 마스터 키를 입력받아 헤더로 보내고 `sessionStorage` 에만 보관하며, 실패 시 캐시를 비웁니다.
- `/health` 에 `api_key_auth` 노출 (키 값은 노출하지 않음)

#### 세입자 잠금(lockout) 방지 설계 — 의도적 선택

`GATEKEEPER_API_KEY` 가 **미설정이면 prearm 은 경고만 남기고 통과시킵니다.** 여기서 막으면 키를 설정하기 전까지 **전 세대의 출입이 불가능해지기 때문**입니다. 실제 현관문을 다루므로 잠금보다 경고를 택했습니다.

이 상태에서도 다음은 계속 유효합니다: 미등록/미승인 기기 거부, `device_id` 누락 거부, DB 장애 시 fail-closed. **마스터 개방만 사용할 수 없습니다.** 기동 시와 요청마다 `[SECURITY]` 경고를 남깁니다.

#### ⚠️ 배포 순서 — 반드시 지킬 것

```
① GitHub Secrets 에 GATEKEEPER_API_KEY 등록
② 앱 재빌드·배포 → 세입자들의 업데이트 완료를 기다린다
③ 그 다음에 서버 환경변수를 설정하고 컨테이너를 재시작한다
```

순서를 바꾸면 구버전 앱이 401 로 거부되어 출입이 막힙니다. 앱은 401 을 받으면 "앱을 최신 버전으로 업데이트해주세요" 알림을 띄웁니다. `backend/.env.example` 에도 이 순서를 명시했습니다.

키 전달 경로: CI `--dart-define` → 앱 `String.fromEnvironment` → `X-API-KEY` 헤더 / `docker-compose` → 서버 환경변수.
`GATEKEEPER_BEACON_UUID` 와 `APP_COOLDOWN_SEC` 도 compose 에 누락되어 있어 함께 추가했습니다.

### 3.6 P3-25 — `/admin/**` 무인증 ⏸️ **신규 발견, 미수행**

P3-22 작업 중 분리한 항목입니다. 문 제어는 막았지만 **관리자 API 는 여전히 무인증**입니다.

가장 위험한 것은 `POST /api/v1/admin/tenants/{id}/approve` 입니다. **누구나 자신을 승인된 세입자로 만들 수 있고, 그러면 P3-22 의 fail-closed 검증을 정면으로 우회합니다.** 그 외 세입자 명단·기기 ID 열람(개인정보), Target 파라미터 원격 변경, 출입 이력 열람이 모두 열려 있습니다. `/admin` HTML 페이지 자체도 무인증입니다.

**이번에 하지 않은 이유**: 정적 HTML 페이지에서 호출되므로 브라우저가 비밀을 안전히 보관할 수 없습니다. 세션 기반 로그인 설계가 필요하고, 이는 별도 설계 결정입니다.

**권장 조치**: 시놀로지 역방향 프록시에서 `/admin*` 경로에 **HTTP Basic 인증 또는 IP 화이트리스트**를 먼저 적용하십시오 — 코드 변경 없이 즉시 노출을 막을 수 있습니다. 그 뒤에 세션 인증을 검토하십시오. 상세는 [issue.md P3-25](issue.md) 참조.

## 4. 수행한 정적 검증

컴파일러가 없으므로 스크립트로 기계적 검증을 수행했습니다. **컴파일 성공을 보장하지는 않습니다** — 타입 추론 오류, 누락된 `@Override` 시그니처 불일치 등은 이 방법으로 잡히지 않습니다.

| 검증 | 결과 |
|---|---|
| Dart/Java 12개 파일 괄호·중괄호 균형 (문자열/주석 토크나이즈 후) | ✅ 전체 통과 |
| Dart가 호출하는 `flutterBeacon.*` 멤버 11개가 fork에 존재 | ✅ 11/11 |
| `debug_screen`/`main`이 참조하는 `BleScanner` 공개 멤버 | ✅ 20/20 |
| `debug_screen`이 참조하는 `ScanDiagnostics` 필드·게터 | ✅ 28/28 |
| `invokeMethod` 21개 ↔ Java 핸들러 이름 일치 | ✅ 21/21 |
| MethodChannel 인자 키 이름 일치 (`scanPeriod`, `backgroundMode` 등) | ✅ 전체 일치 |
| `onMethodCall` 모든 분기에 `return` 존재 (P1-9 회귀 방지) | ✅ 21/21 |
| `_synchronized` 액션 본문의 뮤텍스 재획득 (데드락) | ✅ 없음 |
| `backend/app/main.py` 파이썬 구문 (`ast.parse`) | ✅ 통과 |
| YAML 유효성 (`build_app.yml`, `docker-compose.yml`) | ✅ 통과 |
| 문 제어 두 핸들러의 fail-closed 5개 조건 | ✅ 10/10 |
| API 키 전달 경로 배선 (앱·관리자콘솔·CI·compose·env) | ✅ 7/7 |
| `admin.html` 신규 JS 블록 괄호 균형 | ✅ 통과 |

### 정적 검토에서 실제로 잡은 결함 5건 (`10dcdf9`)

1. 디버그 화면이 열린 상태에서 워치독이 재시작하면 ranging 강제 유지가 복원되지 않아 RSSI가 멈추는 구멍
2. 디버그 모드에서 신호가 없을 때 4초마다 강등 시도 로그가 쌓여 100줄 링버퍼를 잠식
3. 프리플라이트 실패 경로에서 진단 스냅샷의 모드 표시가 한 주기 낡음
4. 원격 `APP_COOLDOWN_SEC`이 슬라이더 범위를 벗어나면 `Slider`가 assert로 죽음
5. AltBeacon 스캔 주기 setter의 `Integer` → `long` 변환을 `longValue()`로 명시

---

## 5. 인수 검증 체크리스트 (실기기 필수)

빌드 환경이 확보되면 **이 순서로** 진행하십시오. 앞 단계가 실패하면 뒤 단계 결과는 의미가 없습니다.

### 5.0 빌드 (최우선)
- [ ] `flutter pub get` (fork의 Dart SDK 제약을 바꿨으므로 clean 환경에서)
- [ ] `flutter analyze --no-fatal-infos`
- [ ] `flutter build apk --release`
- [ ] fork Java 컴파일 통과 (compileSdk 34로 올림)

### 5.1 P2-13 송신부 확정 — 이것부터
- [ ] nRF Connect raw adv에서 `4C 00 02 15` 다음 16바이트가 `A1 B2 … 78 90` 정순
- [ ] AD Flags가 `0x1A`
- [ ] 역순이면 [src/main.cpp:87-117](src/main.cpp#L87-L117) 주석대로 수정

### 5.2 P1-8 / P2-19 진단 능력
- [ ] 디버그 화면 진단 패널의 모든 항목이 실제 상태와 일치
- [ ] 위치 서비스(GPS) OFF → 차단 사유가 패널·알림·로그에 표시되고 스캔이 시작되지 않음
- [ ] GPS를 다시 켜면 **30초 안에** 워치독이 자동 재시작

### 5.3 P0-1 (가장 눈에 보이는 증상)
- [ ] 디버그 화면 진입/이탈 5회 반복 → 매번 RSSI가 계속 갱신
- [ ] `adb logcat -s RANGING`에서 `Start ranging` / `Stop ranging` 쌍이 균형

### 5.4 P0-5 상태 머신
- [ ] IDLE에서 비콘 접근 → ACTIVE 승격, RSSI 표시 시작
- [ ] **이미 구역 안에 있는 상태로 앱을 켬** → `didDetermineStateForRegion(INSIDE)` 처리로 ACTIVE 진입 (이 케이스가 가장 놓치기 쉽습니다)
- [ ] 비콘 전원 OFF → 약 10초 후 IDLE 강등
- [ ] IDLE에서 ranging 콜백·타임아웃 타이머·알림 갱신이 **실제로 정지**했는지 로그로 확인
- [ ] ACTIVE ↔ IDLE 전환이 진동(flapping)하지 않는지

### 5.5 P0-2 화면 OFF (핵심)
- [ ] 디버그 화면에서 누적 패킷 확인 → **화면 OFF 60초** → 화면 ON
      → 누적 패킷이 **약 60개 증가**해 있어야 함. 멈췄다면 미해결
- [ ] `adb shell dumpsys bluetooth_manager | grep -A5 Scan`으로 스캔에 필터가 붙었는지

### 5.6 §2.3 Phase 1 실측 — 3초 목표 판정
- [ ] 비콘 전원 OFF → 앱 IDLE 대기 → 전원 ON → `didEnterRegion` 로그까지 시간을 **20회** 측정, p95 기록
- [ ] p95 ≤ 3초면 종료. 초과하면 issue.md §2.3 Phase 2 판단 (권장: 옵션 2b)

> ⚠️ `setBackgroundMode(true)`가 `SCAN_MODE_LOW_POWER`를 강제하므로(컨트롤러 duty ≈ 512ms/5120ms) **최악 발견 지연이 약 5초까지 늘어날 수 있습니다.** 3초 목표 미달 가능성이 실재합니다. 이건 구현 품질 문제가 아니라 AltBeacon 공개 API의 구조적 제약입니다(issue.md §0.2-3).

### 5.7 P0-3 / P0-4 백그라운드
- [ ] 홈 버튼 → 5분 → 알림 RSSI 계속 갱신
- [ ] 개발자 옵션 **"활동 유지 안 함" ON** → 백그라운드
      → **P0-4 안 A 미구현이므로 여기서 실패할 것으로 예상됩니다.** 실패를 확인해 두십시오
- [ ] 화면 회전 / 다크모드 토글 10회 → AltBeacon 예외 없음
- [ ] `adb shell dumpsys activity services | grep -i beacon` → `BeaconService` 바인딩이 **1개만**

### 5.8 P2-16 / P1-12
- [ ] 백엔드 중단 → 문 앞 접근 → 실패가 알림에 표시되고 **2초 후 재시도**
- [ ] 디버그 화면에서 쿨다운 조정 → 앱 재시작 → 조정값이 유지 (서버값에 덮어써지지 않음)

### 5.8b P3-22 문 제어 보안 (백엔드 — 실기기 없이도 검증 가능)

`GATEKEEPER_API_KEY` **미설정** 상태:
- [ ] 기동 로그에 `⚠️ GATEKEEPER_API_KEY 미설정` 경고
- [ ] `GET /health` → `"api_key_auth": false`
- [ ] `device_id` 없이 prearm → **400**
- [ ] 미등록 `device_id` 로 prearm → **403**
- [ ] 미승인 세입자 `device_id` 로 prearm → **403**
- [ ] 등록+승인 `device_id` 로 prearm → **200** (키 없이도 통과 — 잠금 방지 설계)
- [ ] `device_id` 없이 `/door/open` → **403** (마스터 개방 차단)
- [ ] DB 컨테이너 중지 후 prearm → **503**, MQTT arm 이 발행되지 **않음**
- [ ] DB 컨테이너 중지 후 `/door/open` → **503**, 문이 열리지 **않음**

`GATEKEEPER_API_KEY` **설정** 상태:
- [ ] `GET /health` → `"api_key_auth": true`
- [ ] `X-API-KEY` 없이 prearm → **401**
- [ ] 잘못된 `X-API-KEY` 로 prearm → **401**
- [ ] 올바른 키 + 승인된 `device_id` → **200**
- [ ] 관리자 콘솔 마스터 개방 → 키 입력 프롬프트 후 성공
- [ ] 잘못된 키로 마스터 개방 → 403 + 다음 시도에서 다시 프롬프트

앱 호환성:
- [ ] 서버에 키 설정 + 구버전 앱(키 없음) → 401 → 앱에 "업데이트해주세요" 알림
- [ ] 신버전 앱(키 포함) → 정상

### 5.9 전력
- [ ] `adb shell dumpsys batterystats --charged <package>` — IDLE 8시간 대기 소모량 기준선 측정

---

## 6. 구조 변경 요약 (리뷰어용)

### `BleScanner` — 상태 머신

```
STOPPED ──(startScanning: 프리플라이트 통과)──▶ IDLE ──(구역 진입)──▶ ACTIVE
   ▲                                            ▲                      │
   └──(stopScanning / 프리플라이트 실패)         └──(이탈/무수신 10초)──┘
                                                         │
                                          DEBUG_FORCED: 강등 보류
```

- 모든 전환은 `_synchronized()` 뮤텍스로 직렬화 — `필드 null 대입 → await cancel → 재구독` 순서를 강제합니다. **이 순서를 깨면 P1-7이 재발합니다** (`ranging()`은 호출마다 새 스트림을 만들지만 네이티브는 sink 필드가 하나뿐).
- `_subscribeRangingLocked()` / `_teardownStreamsLocked()`는 이름에 `Locked`가 붙은 대로 **반드시 뮤텍스 안에서만** 호출하십시오.
- 뮤텍스 안에서 다시 `startScanning`/`stopScanning`/`_enterActiveMode`/`_enterIdleMode`를 호출하면 **데드락**입니다. §4에서 스크립트로 검증했으니, 수정 시 다시 확인하십시오.

### 플러그인 소유권 이동

| 리소스 | 변경 전 | 변경 후 |
|---|---|---|
| MethodChannel / EventChannel | Activity | **Engine** |
| `BeaconConsumer.bindService` | `Activity.bindService` | **applicationContext** |
| `FlutterBeaconScanner` | Activity 부착마다 새로 생성 | **플러그인 생애 1개** |
| `FlutterPlatform` 읽기 검사 | Activity | **applicationContext** |
| 권한 요청 / 설정 화면 | Activity | Activity (유지, null 허용) |

`onDetachedFromActivity()`는 이제 **채널과 스캔을 건드리지 않습니다.** 여기에 정리 코드를 다시 넣으면 P0-3이 재발합니다.

### 전력 절감의 실제 내용 (기대치 조정)

issue.md §0.2-4에 적은 대로, **monitoring과 ranging은 같은 스캔 사이클을 공유합니다.** ranging을 끄는 것은 라디오를 끄는 것이 아닙니다.

IDLE에서 실제로 절감되는 것: ranging 콜백 파싱(1Hz) · `ValueNotifier` 갱신 · 알림 IPC · `Timer.periodic` · prearm HTTP 시도.
스캔 자체의 전력은 `setBackgroundMode(true)`가 선택하는 컨트롤러 duty cycle이 결정합니다.

**3초 반응 목표 때문에 `betweenScanPeriod`를 0(연속 스캔)으로 유지했습니다.** 전력 절감 여지가 크지 않다는 뜻이며, §5.9에서 기준선을 측정해 실제 효과를 확인하십시오.

---

## 7. 다음 담당자에게

1. **§5.0 빌드부터** 하십시오. 이 리포트의 모든 항목은 미검증입니다.
2. **§5.1 송신부 확정을 그다음에** 하십시오. 비콘이 애초에 잘못 광고하고 있으면 앱 수정은 전부 무의미합니다.
3. `issue.md` §0.2의 플랫폼 사실 5가지는 이 설계 전체의 전제입니다. 반증하려면 실기기 로그를 근거로 제시하십시오.
4. 남은 큰 작업은 **P0-4 안 A**(isolate 이전)와, §5.6 실측이 3초를 못 맞출 경우의 **Phase 2**입니다.
5. **P3-22 는 구현되었습니다.** 다만 배포에는 §3.5의 **순서 제약**이 있습니다 — 앱을 먼저 배포하고, 세입자 업데이트가 끝난 뒤에 서버 키를 설정하십시오. 순서를 바꾸면 출입이 막힙니다.
6. **P3-25(`/admin/**` 무인증)가 새로 발견되었습니다.** `approve` 엔드포인트가 P3-22 의 검증을 우회할 수 있으므로, 역방향 프록시에서 `/admin*` 에 Basic 인증이나 IP 제한을 **먼저** 걸어 두십시오 (코드 변경 불필요).
7. 앱 스캔 생애주기와 잔존 한계는 [wiki/mobile_app_scan_lifecycle.md](wiki/mobile_app_scan_lifecycle.md) 에 정리했습니다. 코드를 고치기 전에 §6 "지켜야 할 규칙"을 읽으십시오.
