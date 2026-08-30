# smart-gatekeeper 🚪📱

ESP32-C6, Android 스마트키 앱, Synology NAS 백엔드를 결합한 **외부 진입 전용 스마트 출입 통제 시스템**입니다. 현재 구현은 ESP32가 iBeacon을 상시 광고하고, Android 앱이 근접 신호를 감지해 NAS에 Pre-arm을 요청하며, NAS가 MQTT로 Target을 승인한 뒤 AJ-SR04T 초음파 접근을 확인해 릴레이를 구동합니다.

> 문서 탐색은 [`wiki/index.md`](wiki/index.md), 구현·검증·배포를 분리한 현재 상태는 [`wiki/project_status.md`](wiki/project_status.md), 최신 코드 감사는 [`wiki/current_code_audit.md`](wiki/current_code_audit.md)를 먼저 확인하세요. 과거 VL53L0X/ESP32 스캐너 방식 문서는 이력일 뿐 현재 동작이 아닙니다.

## 현재 구성

| 계층 | 구현 |
|---|---|
| Target | ESP32-C6-DevKitC-1 N16, BLE 5.3 iBeacon/GATT, per-Target MQTTS signed command/ACL, signed dual-slot OTA |
| 접근 센서 | AJ-SR04T/JSN-SR04T 호환 초음파 센서, TRIG GPIO10 / ECHO GPIO11 |
| 도어 출력 | 5V Active-LOW 릴레이, authoritative GPIO23, OFF 시 INPUT High-Z |
| 모바일 | Flutter Android 앱 + foreground scanner + OS BLE wake/native GATT worker + recovery updater |
| 백엔드 | FastAPI + MariaDB + per-Target signed MQTT command + authenticated admin/operations plane |
| 자동화 | `main` push 시 펌웨어 빌드·NAS 배포, 앱은 `main` push 또는 수동 실행 시 빌드·배포 |

## 출입 흐름

1. ESP32-C6가 UUID `a1b2c3d4-e5f6-7890-abcd-ef1234567890` iBeacon을 100 ms 간격으로 광고합니다.
2. Android foreground service가 region monitoring을 유지하고, 진입 시 ranging으로 전환하여 EMA RSSI와 히스테리시스를 적용합니다.
3. 임계값을 넘으면 앱이 `POST /api/v1/door/prearm`을 호출합니다. 서버에 키가 설정된 경우 동일한 `X-API-KEY`가 앱 빌드에 주입되어야 합니다.
4. 백엔드는 승인된 기기와 Target boot state를 확인하고 per-Target topic에 signed arm command를 QoS 1로 발행한 뒤 PUBACK을 확인합니다. 전달 실패는 HTTP 503으로 닫힙니다.
5. Target은 서명·target/tenant/door/boot/time/nonce/replay를 검증한 뒤 기본 60초 동안 ARMED가 되고, 20–50 cm의 유효 초음파 접근을 감지하면 릴레이를 1초 구동한 뒤 기본 3초 COOLDOWN으로 전환합니다.

## 빠른 시작

```bash
cp include/secrets.h.example include/secrets.h
pio run -e esp32c6

cd backend
docker compose config
docker compose up -d --build

cd ../gatekeeper_app
docker compose run --rm flutter-builder flutter pub get
docker compose run --rm flutter-builder flutter analyze
docker compose run --rm flutter-builder flutter test
```

보드 배선과 5V ECHO 레벨 시프팅 요구사항은 [`wiki/pin_mapping.md`](wiki/pin_mapping.md), 빌드·시크릿·배포 상세는 [`wiki/env_setup.md`](wiki/env_setup.md)를 따르세요.

## 저장소 구조

```text
src/, include/             ESP32-C6 PlatformIO 펌웨어
backend/                   FastAPI, MariaDB schema, Docker Compose
gatekeeper_app/            Flutter Android 앱과 로컬 beacon plugin
.github/workflows/         펌웨어 및 APK CI/CD
wiki/                      현재 지식, 감사 결과, 테스트 이력
raw/                       읽기 전용 원본 사양·초기 BOM
```

## 현재 검증 상태

최신 저장소에는 Target 보안 command/ACL/OTA, Android native wake/GATT/update, backend admin/operations 계약과 host/CI 검증이 포함됩니다. 그러나 저장소 구현은 현장 배포 증거가 아닙니다. 매립 Target은 2026-08-12 관측 시 구형 `2.1.0-g75b946a`였으며, 최신 signed firmware의 install→reboot→version/boot/health, 연결 복구, 초음파 ECHO 전압, 릴레이 전기 안전과 Android OEM background를 실측해야 합니다. 과거 ToF 기반 PASS는 현재 초음파 아키텍처의 합격 근거로 재사용하지 않습니다.
