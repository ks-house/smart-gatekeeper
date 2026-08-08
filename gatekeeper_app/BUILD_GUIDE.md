# BUILD_GUIDE.md — Gatekeeper App Docker 빌드 가이드

> 본 가이드는 로컬 개발 환경(Java, Android SDK, Flutter SDK 등)에 의존하지 않고, Docker 격리 환경에서 `gatekeeper_app` Android APK를 빌드하는 절차를 설명합니다.

---

## 1. 전제 조건

* Docker 및 Docker Compose 가 로컬 PC에 설치되어 있어야 합니다.

---

## 2. 단계별 빌드 절차

### Step 1: Docker 빌드 컨테이너 기동
`gatekeeper_app` 디렉토리로 이동한 후 백그라운드에서 빌드 컨테이너를 기동합니다.

```bash
cd gatekeeper_app
docker compose up -d --build
```

### Step 2: 컨테이너 내부 쉘 접속
기동된 `flutter-builder` 컨테이너 내부에 접속합니다.

```bash
docker compose exec flutter-builder bash
```

### Step 3: 의존성 설치 및 린트 검사
컨테이너 내부(`/workspace`)에서 패키지 의존성을 다운로드하고 코드를 검증합니다.

```bash
flutter pub get
flutter analyze
flutter test
cd android
./gradlew --no-daemon --rerun-tasks :app:testDebugUnitTest \
  --tests 'com.kshouse.gatekeeper_app.gattworker.*'
cd ..
```

### Step 4: Android APK 빌드
릴리즈 모드로 Android APK 바이너리를 빌드합니다. 업데이트 공개키와 key ID는
manifest가 아니라 APK 빌드 입력으로 고정해야 하며, primary/fallback metadata URL은
서로 독립된 HTTPS 배포 지점을 사용합니다.

```bash
flutter build apk --release \
  --dart-define=APK_VERSION_URL="$APK_VERSION_URL" \
  --dart-define=APK_FALLBACK_VERSION_URL="$APK_FALLBACK_VERSION_URL" \
  --dart-define=UPDATE_SIGNING_KEY_ID="$UPDATE_SIGNING_KEY_ID" \
  --dart-define=UPDATE_SIGNING_PUBLIC_KEY_B64="$UPDATE_SIGNING_PUBLIC_KEY_B64"
```

정식 `key.properties`와 release keystore가 없으면 release 빌드는 의도적으로
실패합니다. debug 서명 APK를 release 산출물로 대체하지 않으며, 실제 배포 APK는
GitHub Actions가 `ANDROID_KEYSTORE_*` Secrets의 정식 키로 서명하고 `apksigner`
certificate identity Gate를 통과해야 합니다.

서명 key ID 또는 32-byte Ed25519 공개키가 비어 있거나 manifest의 key ID와 다르면
앱은 update를 발견하더라도 설치 경로를 열지 않습니다. metadata는
`ota/schemas/mobile-manifest.schema.json`의 정확한 필드와 `sgk-json-v1` 서명을
사용해야 하며, legacy `artifact_sha256`, `fallback_apk_url`, manifest 내 공개키는
허용되지 않습니다.

빌드 후에는 legacy 5-field `version.json`을 직접 작성하지 않습니다. 실제 APK에서
`apksigner verify --print-certs`로 단일 current signer SHA-256을 얻고, 별도 환경변수에
주입된 Ed25519 private seed를 사용해 다음 생성기와 검증기를 모두 통과시킵니다.

```bash
python ../scripts/sign_mobile_manifest.py create \
  --artifact build/app/outputs/flutter-apk/app-release.apk \
  --output ../dist/version.json \
  --version "$FULL_VERSION" --build-number "$BUILD_NUMBER" \
  --commit "$COMMIT_SHA" \
  --apk-url "$APK_DOWNLOAD_URL" \
  --fallback-url "$APK_FALLBACK_DOWNLOAD_URL" \
  --release-notes-url "$APK_RELEASE_NOTES_URL" \
  --published-at "$PUBLISHED_AT" \
  --certificate-sha256 "$APK_CERTIFICATE_SHA256" \
  --signing-key-id "$UPDATE_SIGNING_KEY_ID" \
  --private-key-env OTA_SIGNING_PRIVATE_KEY_HEX \
  --expected-public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX"
python ../scripts/sign_mobile_manifest.py verify \
  --manifest ../dist/version.json \
  --artifact build/app/outputs/flutter-apk/app-release.apk \
  --public-key-hex "$OTA_SIGNING_PUBLIC_KEY_HEX" \
  --certificate-sha256 "$APK_CERTIFICATE_SHA256"
```

private seed는 인자로 직접 전달하거나 출력하지 않습니다. PR debug canary는 공개된
RFC 8032 test key와 `.invalid` endpoint만 사용하며, 설치 가능한 production release로
취급하지 않습니다.

---

## 3. 빌드 결과물 확인

빌드가 완료되면 로컬 PC의 `gatekeeper_app` 폴더 아래 다음 경로에 APK 파일이 생성됩니다:

```
gatekeeper_app/build/app/outputs/flutter-apk/app-release.apk
```

---

## 4. 컨테이너 종료 및 정리

빌드 작업 완료 후 컨테이너를 종료하고 정리하려면 아래 명령어를 실행합니다:

```bash
docker compose down
```
