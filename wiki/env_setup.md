# env_setup.md — 현재 개발·빌드 환경
> Last updated: 2026-08-02 (Windows PlatformIO timeout/orphan recovery guidance added)

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
`2.1.0-g<short_sha>` 형식입니다. 공식 `espressif32`나 과거 `tof_test`/`relay_test` 환경은 현재
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

## 2. 백엔드

요구사항은 Docker + Compose입니다. `backend/docker-compose.yml`이 MariaDB 10.11과 FastAPI 컨테이너을 구성합니다.

```bash
cd backend
cp .env.example .env
# DB/MQTT/GATEKEEPER_API_KEY 값을 운영 환경에 맞게 설정
docker compose config
docker compose up -d --build
docker compose ps
```

`GATEKEEPER_API_KEY`를 활성화하면 앱도 같은 키로 빌드해야 합니다. MQTT TLS 여부와 broker 주소는 backend `.env`, Target TLS CA와 포트는 `include/secrets.h`에서 각각 설정하므로 서로 일치시켜야 합니다.

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
| `.github/workflows/deploy.yml` | `main` push 또는 `workflow_dispatch` | PlatformIO 시험·빌드·contract 검증과 canary 보존; 운영 배포는 명시적 production dispatch에서만 별도 실행 |
| `.github/workflows/build_app.yml` | 앱 경로의 `main` push 또는 `workflow_dispatch` | Flutter 분석·빌드·contract 검증과 canary 보존; 운영 배포는 명시적 production dispatch에서만 별도 실행 |
| `.github/workflows/trusted_workflow_policy.yml` | 보호 파일 변경 PR (`pull_request_target`) | default-branch validator/policy로 candidate bytes의 exact approved bundle 검증 |

일반 `main` push와 기본 `workflow_dispatch`의 `release_target=canary`는 build/test/contract job만
실행하고 production job을 skip하므로, physical Gate가 정직하게 pending이어도 CI 자체는 성공합니다.
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
