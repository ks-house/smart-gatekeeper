# env_setup.md — 현재 개발·빌드 환경
> Last updated: 2026-08-02 (Windows PlatformIO timeout/orphan recovery guidance and managed-runner PlatformIO lock 경계 반영)

## 1. 펌웨어

- MCU: ESP32-C6-DevKitC-1 N16 (RISC-V, 16 MB flash)
- PlatformIO platform: pioarduino stable ZIP
- Framework: Arduino
- 환경: `esp32c6` 하나
- 파티션: `partitions_16MB_ota.csv` (dual OTA)
- 라이브러리: ArduinoJson 6.21.x, PubSubClient 2.8; BLE 헤더는 Arduino-ESP32 코어 제공

```bash
cp include/secrets.h.example include/secrets.h  # 실제 값 입력, 커밋 금지
pio run -e esp32c6
pio run -e esp32c6 -t upload
pio device monitor -b 115200
```

`include/secrets.h`에는 Wi-Fi, API, MQTT, OTA 주소와 TLS Root CA가 필요합니다. CI는 GitHub Secrets로
이 파일을 생성하고 `FIRMWARE_VERSION_OVERRIDE`를 주입합니다. v2.1부터 main firmware build ID는
`2.1.0-g<short_sha>` 형식입니다. Target local ACL 및 access session FSM (Issue #20) 검증을 위한
`TargetAclManager`, `TargetProofVerifier`, `TargetAccessFsm`, `OfflineEventQueue` 모듈이 포함되며
host unit test는 `python -m unittest tests/test_hardwareless_rc.py`로 실행할 수 있습니다. 공식 `espressif32`나 과거 `tof_test`/`relay_test` 환경은 현재
`platformio.ini`에 없습니다.

### 1.1 Windows에서 긴 PlatformIO 빌드가 timeout된 경우

#### 증상과 원인

- 실행 도구가 exit 124/timeout을 반환했는데도 작업 관리자나
  `Get-CimInstance Win32_Process`에는 `riscv32-esp-elf-g++`가 계속 남아 있을 수 있습니다.
  이 상태에서 build를 재시도하면 compiler 수가 계속 증가하고 두 build가 모두 매우 느려집니다.
- Windows에서 wrapper/shell timeout은 이미 생성된 SCons compiler 자식 프로세스까지 항상 종료하지
  않습니다. default-OFF와 feature-ON을 동시에 실행하면 각각의 SCons `--jobs`가 합쳐져 CPU와 disk를
  과도하게 점유할 수 있습니다. 서로 다른 build directory는 object 충돌을 막지만 동시 실행의
  resource contention까지 해결하지는 않습니다.
- repository는 실제 `include/secrets.h`를 의도적으로 추적하지 않습니다. 이 파일이 없는 checkout은
  firmware compile 전에 실패할 수 있지만, 실제 secret이나 token을 임시 파일·로그·명령행에 넣어
  해결해서는 안 됩니다.

#### 안전한 절차

1. 인증된 개발 환경에서는 실제 local `include/secrets.h`가 ignore되는지만 확인하고 내용을 출력하지
   않습니다. 일회성 검증 환경에서는 필요한 macro 이름만 가진 non-secret compile placeholder를
   사용하고 검증 직후 삭제하며 절대 stage하지 않습니다.

   ```powershell
   git check-ignore include/secrets.h
   git status --short
   ```

2. 두 구성을 동시에 실행하지 말고 build directory와 jobs를 분리해 순차 실행합니다. feature build가
   끝난 뒤 환경 변수도 제거합니다.

   ```powershell
   $env:PYTHONUTF8 = "1"
   chcp 65001

   $env:PLATFORMIO_BUILD_DIR = ".pio/build-default-final"
   Remove-Item Env:PLATFORMIO_BUILD_FLAGS -ErrorAction SilentlyContinue
   pio run -e esp32c6 -j 4

   $env:PLATFORMIO_BUILD_DIR = ".pio/build-feature-final"
   $env:PLATFORMIO_BUILD_FLAGS = "-DENABLE_HARDWARELESS_RC=1"
   pio run -e esp32c6 -j 4
   Remove-Item Env:PLATFORMIO_BUILD_FLAGS -ErrorAction SilentlyContinue
   ```

3. timeout 후에는 즉시 재실행하지 않습니다. 먼저 현재 worktree 경로가 command line의 response-file
   경로에 들어 있는 compiler만 읽기 전용으로 확인합니다. 다른 worktree나 사용자의 build process를
   함께 종료하지 않도록 이름만으로 broad kill하지 않습니다.

   ```powershell
   $sgkWorkspace = (Resolve-Path .).Path
   $ownedCompilers = Get-CimInstance Win32_Process | Where-Object {
     $_.Name -like "riscv32-esp-elf-*" -and
     $_.CommandLine -like "*$sgkWorkspace*"
   }
   $ownedCompilers |
     Select-Object ProcessId, ParentProcessId, Name, CommandLine
   ```

   출력에서 exact worktree와 PID/parent를 사람이 확인한 뒤에만 해당 PID를
   `Stop-Process -Id <verified_pid> -Force`로 종료합니다. SCons Python command line은 project path를
   인코딩할 수 있으므로 추측으로 Python 전체를 종료하지 말고, 확인한 compiler의 parent 관계와
   생성 시각을 함께 대조합니다. 종료 후 위 조회 결과가 0인지 확인하고 순차 build를 재개합니다.

#### 검증 기준과 증거 구분

- 각 명령은 `[SUCCESS]`와 독립적인 `firmware.elf`/`firmware.bin` 생성, RAM/flash size 출력을 모두
  확인해야 합니다. 2026-08-02 PR #34 software 검증에서는 순차 재실행 결과 default-OFF가
  RAM 47,040/327,680, flash 1,598,136/7,340,032, feature-ON이 RAM 53,648/327,680,
  flash 1,633,096/7,340,032로 성공했고 실제 NimBLE/Bluedroid adapter source가 compile/link되었습니다.
- 검증 후 workspace-owned compiler가 0개이고, ephemeral `include/secrets.h`가 제거됐으며,
  `git status --short`에 build/secret artifact가 없는지 확인합니다.
- 위 결과는 local software/toolchain evidence입니다. 별도의 GitHub Actions 결과와 혼합하지 않으며,
  ESP32-C6 radio, GPIO3 relay/sensor, Samsung/OEM, power-loss/bootloader, OTA-G1..G4 또는
  RELAY-G0..G2 physical evidence를 대신하지 않습니다.

### 1.2 Windows managed-runner PlatformIO package lock

Managed sandbox 안에서 `pio run -e esp32c6`를 실행하면 compile 전에
`PermissionError: [Errno 13] Permission denied: 'C:\Users\shcat\.platformio\platforms.lock'`로
실패할 수 있습니다. PlatformIO가 project 외부의 user-global package manager lock/cache를
획득해야 하지만 sandbox write scope가 worktree로 제한되는 것이 원인입니다. 이 실패는 firmware
source, pioarduino package 또는 `include/secrets.h` 내용의 오류가 아닙니다.

동일한 `pio run` 명령만 user-global PlatformIO cache 접근이 허용된 scoped execution으로 다시
실행합니다. build 전에는 ignored `include/secrets.h`를 example에서 만들고, 성공·실패와 관계없이
정확한 해당 파일만 `finally` cleanup합니다. 광범위한 shell/Python 권한이나 repository 외부 삭제는
허용하지 않으며 실제 secret을 출력하거나 test placeholder에 넣지 않습니다.

명령 wrapper가 종료된 child process 뒤에도 대기하는 것처럼 보이면 먼저 issue worktree와 관련된
`pio` process가 실제로 없는지 read-only로 확인합니다. 살아 있는 build가 없고
`include/secrets.h`도 없을 때만 중복 build를 재시작합니다. 2026-08-02 PR #36 review에서는 scoped
재실행이 RAM 47,032/327,680 bytes, flash 1,596,456/7,340,032 bytes에서 성공했고, cleanup 뒤
`include/secrets.h` 부재와 clean worktree를 다시 확인했습니다.

## 2. 백엔드

요구사항은 Docker + Compose입니다. `backend/docker-compose.yml`이 MariaDB 10.11과 FastAPI 컨테이너을 구성합니다.

```bash
cd backend
cp .env.example .env
# DB/MQTT/GATEKEEPER_API_KEY 값을 운영 환경에 맞게 설정
# Issue #19 RC는 expand migration 후에도 ACL_MANAGEMENT_ENABLED=false로 시작
docker compose config
docker compose up -d --build
docker compose ps
```

`GATEKEEPER_API_KEY`를 활성화하면 앱도 같은 키로 빌드해야 합니다. MQTT TLS 여부와 broker 주소는 backend `.env`, Target TLS CA와 포트는 `include/secrets.h`에서 각각 설정하므로 서로 일치시켜야 합니다.

Issue #19 Hardwareless RC는 `backend/db/migrations/002_acl_management_expand_up.sql`을
먼저 적용하고 identity-bound `ACL_ENROLLMENT_AUTH_JSON`, `ACL_ADMIN_API_KEY`,
tenant/door/identity-bound `ACL_TARGET_AUTH_JSON`, explicit `ACL_LEGACY_REF_HMAC_KEY`, 격리된
primary ACL signer를 설정한 뒤에만 feature flag를 켠다. signer rotation 중에는
`ACL_TRANSITION_SIGNING_PRIVATE_SCALAR_HEX`와 `ACL_TRANSITION_SIGNING_KEY_ID`를 함께 설정하고
N-1 signer를 primary로 유지한다. 새 volume은 Compose init script가 expand
migration을 실행하지만 기존 volume은 명시적으로 적용해야 한다. rollback 순서는
[backend_acl_management.md](backend_acl_management.md)를 따르며 production은 G0-HW와 #23
Gate 전까지 OFF다.

Windows의 disposable MariaDB 10.11 통합 검증은 실행 중인 Docker engine과 localhost 임시
포트 bind 권한만 필요하다. harness가 SQL stdin과 subprocess stdout/stderr를 UTF-8로, MariaDB
client charset을 `utf8mb4`로 명시하므로 `PYTHONUTF8` 또는 `PYTHONIOENCODING` 환경변수 보정은
필요하지 않다.

```powershell
$env:RUN_MARIADB_INTEGRATION = "1"
python -m unittest backend.tests.test_migrations -v
Remove-Item Env:RUN_MARIADB_INTEGRATION
```

### Windows managed-runner `.review-tmp` cleanup

Disposable MariaDB validation can finish successfully while a later repository-gate run leaves
`tempfile.TemporaryDirectory()` fixtures under `.review-tmp`. In the 2026-08-02 PR #36 review,
the managed host sandbox could see those directories but could not reopen or remove them, so
`git status` printed `Permission denied` warnings. This was a host access/ownership boundary on
test scratch directories, not a MariaDB migration failure and not repository content.

First resolve the path and require it to be exactly this worktree's `.review-tmp`. Then mount only
that directory into the already present `mariadb:10.11` image, list its direct children, and remove
only the individually verified failed-run directories. Never mount the repository root and never
use a wildcard or broad recursive delete.

```powershell
$reviewTmp = (Resolve-Path -LiteralPath '.review-tmp').Path
$expectedReviewTmp = Join-Path (Get-Location).Path '.review-tmp'
if ($reviewTmp -cne $expectedReviewTmp) { throw "unexpected review temp path" }

docker run --rm --mount "type=bind,source=$reviewTmp,target=/reviewtmp" `
  mariadb:10.11 sh -c "find /reviewtmp -mindepth 1 -maxdepth 1 -print"

# PR #36 incident: delete only the six names confirmed by the preceding listing.
docker run --rm --mount "type=bind,source=$reviewTmp,target=/reviewtmp" `
  mariadb:10.11 sh -c "rm -rf -- /reviewtmp/tmp8oyfvwq5 /reviewtmp/tmp9kyj8nwy /reviewtmp/tmpleix_s5l /reviewtmp/tmprqxfzj6q /reviewtmp/tmpycbfhu2k /reviewtmp/tmpzudhyejf"
```

After cleanup, rerun the direct-child listing (it must be empty), then run `git status --short`
and `git diff --check`. Do not rerun a completed long test suite solely because cleanup was needed;
rerun only validations whose assertions did not execute.

## 3. Android 앱

앱은 Flutter/Dart 3, Java 17, Android SDK/NDK가 필요하며 로컬 fork `gatekeeper_app/android/app/libs/flutter_beacon_local`을 path dependency로 사용합니다. 재현 가능한 검증은 Docker builder를 권장합니다.

```bash
cd gatekeeper_app
docker compose build flutter-builder
docker compose run --rm flutter-builder flutter pub get
docker compose run --rm flutter-builder dart format --output=none --set-exit-if-changed lib test
docker compose run --rm flutter-builder dart analyze lib test
docker compose run --rm flutter-builder flutter test
docker compose run --rm flutter-builder bash -lc \
  "flutter pub get && cd android && ./gradlew :app:testDebugUnitTest"
docker compose run --rm flutter-builder flutter build apk --debug
```

For issue #17 native GATT tests, Compose mounts the repository `protocol/` directory read-only at
`/repo-protocol` so JVM tests consume the same canonical vector as firmware and backend tests. The
named Gradle cache avoids re-downloading the Android toolchain. A forced, bounded targeted run is:

```bash
cd gatekeeper_app
docker compose up -d flutter-builder
docker compose exec -T flutter-builder bash -lc \
  "cd android && timeout --signal=TERM --kill-after=15s 300s \
  ./gradlew --no-daemon :app:testDebugUnitTest \
  --tests 'com.kshouse.gatekeeper_app.gattworker.*' --rerun-tasks"
```

Inspect `build/app/test-results/testDebugUnitTest/TEST-com.kshouse.gatekeeper_app.gattworker*.xml`
afterward. `--rerun-tasks` and the XML counts distinguish executed tests from an `UP-TO-DATE` task.
See [android_gatt_worker.md](android_gatt_worker.md) for scope and evidence boundaries.

### Current Orca/Windows validation difficulties

- **Symptom:** repository tests that use `tempfile.TemporaryDirectory()` can fail with
  `PermissionError` under the user profile `%TEMP%` even though contract assertions are passing.
  **Cause:** the managed Windows sandbox can create the temporary directory but deny later child
  writes or cleanup outside the workspace. **Safe solution:** create a workspace-local disposable
  `.review-tmp`, set both `TEMP` and `TMP` to its resolved path for the test process only, and remove
  the directory after evidence inspection; do not weaken filesystem permissions or alter the tests.
  **Verification:** the same repository suite then completes all 81 tests with zero failures/errors.
- **Symptom:** a forced Gradle run through `docker compose exec -T` may show no incremental output
  for one or more minutes. **Cause:** the single-use Gradle daemon and container/terminal buffering
  delay output while the 208-task graph executes. **Safe solution:** keep the five-minute in-container
  `timeout`, use `--rerun-tasks`, and wait for the bounded process rather than treating silence as a
  hang. **Verification:** require `208 actionable tasks: 208 executed`, then inspect fresh JUnit XML
  modification times and aggregate failures/errors/skips before recording evidence.
- **Symptom:** `flutter pub get`, Flutter tests, or APK builds may modify generated desktop plugin
  registrants and leave Gradle/JUnit output trees. **Cause:** Flutter regenerates platform glue and the
  builder bind-mounts output into the worktree. **Safe solution:** inspect the evidence first, restore
  only tracked generated registrants to the reviewed HEAD, and delete only known generated test/build
  artifacts. **Verification:** final `git status --short` contains only intentional source, test, wiki,
  and append-only log changes.
- **Symptom:** an exact-file `git restore --source=HEAD` can transiently fail with `Unable to create
  .../index.lock: Permission denied` even when no lock file or Git process remains. **Cause:** a short
  Windows managed-sandbox `CreateProcess`/worktree-index lock race can outlive the command that held
  the filesystem handle. **Safe solution:** do not delete a guessed lock and do not retry a broad
  restore; first resolve `git rev-parse --git-dir`, confirm `index.lock` is absent, confirm no Git
  process is running, then retry small explicit generated-file groups against exact `HEAD` with the
  required worktree-index permission. **Verification:** each narrow restore exits zero, the resolved
  worktree Git directory still has no `index.lock`, and `git diff --name-only` reports no generated
  registrant path.

Android Gradle wrapper script는 생성 파일로 취급되어 checkout 직후 없을 수 있으므로 native
unit test 전에 `flutter pub get`을 같은 container에서 먼저 실행한다. #14 BLE wake의
hardwareless installed-APK 재현은 `gatekeeper_app/tool/android_ble_wake_hardwareless.ps1`,
실기기 Gate와 결과 구분은 [android_ble_wake_adr.md](android_ble_wake_adr.md)를 따른다.

운영 APK는 release keystore와 다음 dart define이 필요합니다.

```bash
flutter build apk --release \
  --dart-define=GATEKEEPER_API_KEY='<backend와 동일한 값>' \
  --dart-define=APK_VERSION_URL='<version.json URL>' \
  --dart-define=APK_DOWNLOAD_URL='<APK URL>'
```

`BACKEND_URL`은 코드 기본값이 있지만 환경별 빌드에서는 명시적으로 주입하는 편이 안전합니다.

## 4. CI/CD 동작

| Workflow | Trigger | 결과 |
|---|---|---|
| `.github/workflows/ota_contract.yml` | OTA 영향 PR/main | schema, signature tamper vector, dual-slot/recovery/release blocker 자동 검사 |
| `.github/workflows/deploy.yml` | `main` push 또는 `workflow_dispatch` | PlatformIO 시험·빌드·contract 검증과 canary 보존; `physical-test-canary`는 exact-main 공개 테스트 서명 artifact만 host-key-mode-labelled 격리 NAS 경로에 staging/readback하며 production은 별도 |
| `.github/workflows/build_app.yml` | 앱 경로의 `main` push 또는 `workflow_dispatch` | Flutter 분석·빌드·contract 검증과 canary 보존; `physical-test-canary`는 exact-main debug APK만 host-key-mode-labelled 격리 NAS 경로에 staging/readback하며 production은 별도 |
| `.github/workflows/trusted_workflow_policy.yml` | 보호 파일 변경 PR (`pull_request_target`) | default-branch validator/policy로 candidate bytes의 exact approved bundle 검증 |

일반 `main` push와 기본 `workflow_dispatch`의 `release_target=canary`는 build/test/contract job만
실행하고 production job을 skip하므로, physical Gate가 정직하게 pending이어도 CI 자체는 성공합니다.
`release_target=physical-test-canary`는 [`nas_physical_test_delivery.md`](nas_physical_test_delivery.md)의
별도 NAS 디렉터리로 bounded SFTP-only batch를 사용해 test-signed public canary를 전달하고 읽어 검증하지만 physical Gate를 통과시키지
않습니다. `NAS_KNOWN_HOSTS`가 없으면 public canary는 dispatch의 default-false `allow_unpinned_host_key=true` 승인을 요구하고, bounded runtime `ssh-keyscan` 결과를 run-local 파일에 고정해 `runtime-keyscan-unpinned`를 기록하며, `physical-test-connected`는
별도 `PHYSICAL_TEST_*` 자격증명과 후속 보호 번들이 없으므로 의도적으로 fail-closed입니다.
운영 NAS 배포는 저장소 쓰기 권한자가 `release_target=production`을 명시한 dispatch에서만 요청할 수
있고 `production` GitHub Environment 정책을 통과해야 합니다. `ota_contract_gate.py`는 release job이
`environment: production`을 기재했는지 기계적으로 검증하며(deployment precondition), 실제 저장소 외부
Environment 구성(`PUT /repos/{owner}/{repo}/environments/production`)은 Coordinator가 인증된 GitHub API를
통해 필수 승인자(`tworimpa`) 및 `main` 전용 브랜치 보호 정책을 지정하여 완성했습니다. 이 별도 job은
`ota/release-evidence.json`의 OTA-G0~G4와 physical Gate가 완전히 승인되지 않으면 SFTP 전에
fail-closed로 종료합니다. Actions canary artifact를 받아 USB/emulator/실기기

시험을 수행한 뒤에만 evidence를 갱신합니다. release Gate는 signed manifest와 실제 SFTP 대상 firmware/APK를
1:1로 입력받아 size·SHA-256을 비교하고, APK는 Android SDK `apksigner`로 signing certificate SHA-256도
검증합니다. Gate에 전달한 파일과 upload 대상이 달라지면 안 됩니다. Target workflow는 원격 panic
주소 해석용 `firmware.map`도 보존합니다.

운영 자격 증명 문자열이 포함될 수 있는 `firmware.elf`는 public artifact/NAS에 게시하지 않습니다.

Trusted workflow Gate는 PR code를 checkout하거나 실행하지 않습니다. `base.sha`의 sparse checkout에서
validator와 policy만 읽고, candidate의 5개 보호 파일은 GitHub Contents API를 통해 inert bytes로
가져와 `utf8-lf-v1` normalized SHA-256 bundle을 비교합니다. bootstrap/rotation 절차는
[trusted_workflow_policy.md](trusted_workflow_policy.md)를 따릅니다.

## 5. 로컬 GitHub 인증

로컬 에이전트와 GitHub CLI는 현재 프로세스의 `GITHUB_TOKEN` 환경 변수만 사용합니다.
토큰 원문은 출력하거나 repository 파일, 로그, Git remote URL에 저장하지 않습니다.
push 전에는 환경 변수의 존재 여부와 `gh auth status` 성공을 확인합니다. 환경 변수가 존재해도
sandbox의 socket/network 차단으로 GitHub에 연결하지 못하면 토큰 오류로 판정하지 말고 네트워크
권한을 적용해 다시 확인합니다. 실제 GitHub 연결 후에도 401/invalid가 확인될 때만 만료·폐기·오입력
가능성으로 판정하며, `gh auth login`이나 저장 계정으로 우회하지 않고 실행 환경의
`GITHUB_TOKEN`을 갱신해야 합니다.

### Windows managed-worktree Git administrative lock

Orca worktree의 visible path가 write 가능해도 Git common directory가 parent repository 아래에
있으면 `git add` 또는 `git commit`이
`Permission denied: ...\.git\worktrees\<worktree>\index.lock`으로 실패할 수 있습니다. Git이
worktree 내부가 아니라 external common `.git` administrative directory에 lock과 index를 써야
하지만 managed sandbox가 visible worktree만 허용하는 것이 원인입니다. source file 권한이나
repository corruption으로 판정하지 않습니다.

먼저 `git status --short`, explicit path diff와 `git diff --check`로 변경 범위를 확인합니다. 그 뒤
`git add -- <verified paths>`와 `git commit`만 Git administrative directory 접근이 허용된 scoped
execution으로 실행하고, broad staging 또는 parent repository file mutation은 허용하지 않습니다.
완료 후 commit SHA, `git status --short --branch`, staged/unstaged diff 부재와 remote branch head를
다시 확인합니다. GitHub 게시에는 계속 process environment의 `GITHUB_TOKEN`만 사용합니다.

## 6. 릴리스 전 체크

- [ ] `python scripts/ota_contract_gate.py contract`
- [ ] signed manifest, 동일 upload artifact, `OTA_SIGNING_PUBLIC_KEY_HEX`를 전달한 `python scripts/ota_contract_gate.py release`
- [ ] Android release는 `--apksigner` certificate digest 검증 통과
- [ ] `pio run -e esp32c6`
- [ ] `docker compose config` (backend)
- [ ] Dart format/analyze/test
- [ ] Android release APK 서명 빌드
- [ ] iBeacon raw payload UUID 순서·100 ms 간격 실측
- [ ] 화면 OFF, task swipe-away, OEM 절전 정책별 접근 시험
- [ ] MQTT PUBACK 실패 시 HTTP 503 및 앱 재시도 확인
- [ ] ECHO 5V → 3.3V 레벨 시프터와 릴레이 절연 확인

## 7. PR #37 Windows build 및 에이전트 handoff 주의사항

- 2026-08-02 review remediation 중 Antigravity 사용량 한도가 소진되어 해당 agent의 재개를
  전제로 두지 않고 Orca dispatched worker로 인계했다. 인계 시 dirty worktree를 그대로 보존하고,
  새 worker가 전체 diff를 독립 재검토해야 한다.
- Windows/MSYS PlatformIO 복합 실행에서 간헐적으로
  `C:\WINDOWS\System32\cmd.exe: Permission denied` (`Error 126`)가 발생할 수 있다. 이를 source
  compiler error로 추정하지 말고 동일한 `PLATFORMIO_BUILD_DIR`로 targeted incremental
  `pio run -e esp32c6`를 다시 실행해 첫 실제 compiler/linker diagnostic을 확보한다.
- PR #37에서는 첫 incremental default-OFF 진단으로 missing C++ headers, 잘못된 `const char*`
  `.c_str()` 사용, 그리고 feature-ON anonymous-namespace queue symbol link 오류를 식별해 수정했다.
  기본-OFF가 green이 된 뒤에만 `PLATFORMIO_BUILD_FLAGS=-DENABLE_HARDWARELESS_RC=1` feature-ON을
  순차 실행한다.
- 위 빌드는 hardwareless software evidence다. Samsung/OEM 화면 OFF·task swipe-away,
  ESP32-C6 BLE radio/GATT, GPIO3 relay/sensor timing, bootloader rollback 및 OTA-G1..G4 물리 gate를
  대체하지 않는다.

## 8. Linux GCC `strncpy` literal 경고

- Windows host 검증에 사용하는 MinGW GCC 5.1은 길이가 정확히 destination capacity - 1인
  문자열 literal을 `std::strncpy(destination, literal, sizeof(destination) - 1)`로 복사해도
  경고하지 않을 수 있다. Linux GCC 11 이상은 동일 패턴을 `-Wstringop-truncation`으로 진단하며,
  CI의 `-Werror` 설정에서는 빌드 실패가 된다.
- 고정 길이 UUID처럼 terminator를 포함한 literal 크기가 destination 배열 크기와 정확히 같아야
  하는 경우 `constexpr char` 배열로 literal을 선언하고 `static_assert(sizeof(literal) ==
  sizeof(destination))`로 길이를 검증한 뒤, `std::memcpy(destination, literal, sizeof(literal))`로
  NUL terminator까지 함께 복사한다. 이 패턴은 UUID 36 bytes와 trailing NUL을 모두 보존하며
  Windows/Linux compiler 차이에 의존하지 않는다.

## 9. Orca 워크트리 빠른 시작

Orca는 저장소 루트의 `orca.yaml`과 로컬 프로젝트 훅에서 동일한 idempotent setup 명령을 사용한다.
새 워크트리에서는 setup이 기본 실행되고, 의존성 설치가 끝난 뒤에만 에이전트를 시작한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/setup_worktree.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/doctor.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/validate.ps1 -Suite Quick
```

setup은 ignored `.venv`, ignored `include/secrets.h`, PlatformIO package cache만 준비하며 기존 시크릿을
읽거나 덮어쓰지 않는다. 상세 suite, Docker Flutter 격리, 프로파일 시작법은
[orca_development_environment.md](orca_development_environment.md)를 따른다.
## Target security build environments (2026-08-09)

`esp32c6` is the default release-mode software build with `ENABLE_HARDWARELESS_RC=0` and `SGK_PRODUCTION_BUILD=0`. `esp32c6_hwless_rc` is an explicit lab-only environment and is never a production authorization path. Production packaging must set `SGK_PRODUCTION_BUILD=1`, keep hardwareless RC at zero, provision exact per-Target MQTT and recovery credentials plus command/OTA public keys, and separately satisfy `security/target-production-policy.json` physical/eFuse/operator Gates.

Use a worktree-scoped PlatformIO directory on Windows, for example `$env:PLATFORMIO_BUILD_DIR='.pio/build-issue50'; pio run -e esp32c6 -j 4`. A successful build is software evidence only and does not validate secure boot, flash/NVS encryption, debug locks, broker deployment, radio, relay, or OTA rollback on hardware.
