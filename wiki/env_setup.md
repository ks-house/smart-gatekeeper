# env_setup.md — 현재 개발·빌드 환경
> Last updated: 2026-07-31 (Target CI symbol-map retention)

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
```

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
| `.github/workflows/deploy.yml` | `main` push | PlatformIO 빌드, firmware/version JSON, NAS SFTP 배포, 30일 symbol-map artifact |
| `.github/workflows/build_app.yml` | 앱 경로의 `main` push 또는 `workflow_dispatch` | Flutter analyze/release APK, NAS SFTP, Actions artifact |

앱 workflow는 PR/feature branch에서 운영 NAS 배포가 실행되지 않도록 trigger와 job 조건을 모두 둡니다. 펌웨어 workflow는 현재 `main`의 모든 push에 배포되므로 문서-only 변경도 운영 배포를 촉발할 수 있다는 점을 운영 정책에서 검토해야 합니다.
Target workflow는 원격 panic 주소 해석용 `firmware.map`만 Actions artifact로 보존합니다.
운영 자격 증명 문자열이 포함될 수 있는 `firmware.elf`는 public artifact/NAS에 게시하지 않습니다.

## 5. 릴리스 전 체크

- [ ] `pio run -e esp32c6`
- [ ] `docker compose config` (backend)
- [ ] Dart format/analyze/test
- [ ] Android release APK 서명 빌드
- [ ] iBeacon raw payload UUID 순서·100 ms 간격 실측
- [ ] 화면 OFF, task swipe-away, OEM 절전 정책별 접근 시험
- [ ] MQTT PUBACK 실패 시 HTTP 503 및 앱 재시도 확인
- [ ] ECHO 5V → 3.3V 레벨 시프터와 릴레이 절연 확인
