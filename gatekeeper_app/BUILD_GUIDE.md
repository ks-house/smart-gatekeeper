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
```

### Step 4: Android APK 빌드
릴리즈 모드로 Android APK 바이너리를 빌드합니다.

```bash
flutter build apk --release
```

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
