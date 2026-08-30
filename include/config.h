// include/config.h
// =============================================================
// smart-gatekeeper — 전역 핀 상수 및 프로젝트 설정
// v2.0: BLE Beacon Advertiser + MQTT Pre-arm 아키텍처
// =============================================================
#pragma once

#include <cstdint>
#include "secrets.h"

// ─── 펌웨어 버전 (GitHub CI 동적 오버라이드 지원) ─────────────────
#ifdef FIRMWARE_VERSION_OVERRIDE
#define FIRMWARE_VERSION FIRMWARE_VERSION_OVERRIDE
#else
#ifndef FIRMWARE_VERSION
#define FIRMWARE_VERSION "2.1.0"
#endif
#endif

// ─── 네트워크 & 시놀로지 NAS 백엔드 API 설정 ────────────────────
constexpr const char* WIFI_SSID     = SECRET_WIFI_SSID;
constexpr const char* WIFI_PASSWORD = SECRET_WIFI_PASSWORD;

constexpr const char* API_URL       = SECRET_API_URL;
constexpr const char* API_KEY       = SECRET_API_KEY;

// ─── MQTT 브로커 설정 ─────────────────────────────────────────
constexpr const char* MQTT_HOST     = SECRET_MQTT_HOST;
constexpr uint16_t    MQTT_PORT     = SECRET_MQTT_PORT;
constexpr const char* MQTT_USER     = SECRET_MQTT_USER;
constexpr const char* MQTT_PASSWORD = SECRET_MQTT_PASSWORD;

// A production Target uses one broker principal and one exact topic namespace.
// The broker ACL maps that principal to gatekeeper/v1/targets/<target-id>/#.
#ifndef SECRET_TARGET_TENANT_ID
#define SECRET_TARGET_TENANT_ID ""
#endif
#ifndef SECRET_TARGET_DOOR_ID
#define SECRET_TARGET_DOOR_ID ""
#endif
#ifndef SECRET_COMMAND_SIGNER_PUBLIC_KEY_HEX
#define SECRET_COMMAND_SIGNER_PUBLIC_KEY_HEX ""
#endif
#ifndef SECRET_COMMAND_SIGNING_KEY_ID
#define SECRET_COMMAND_SIGNING_KEY_ID 0
#endif
constexpr const char* TARGET_TENANT_ID = SECRET_TARGET_TENANT_ID;
constexpr const char* TARGET_DOOR_ID = SECRET_TARGET_DOOR_ID;
constexpr const char* COMMAND_SIGNER_PUBLIC_KEY_HEX =
    SECRET_COMMAND_SIGNER_PUBLIC_KEY_HEX;
constexpr uint32_t COMMAND_SIGNING_KEY_ID = SECRET_COMMAND_SIGNING_KEY_ID;

// ─── OTA (Over-The-Air) 배포 주소 ──────────────────────────────
constexpr const char* OTA_VERSION_URL  = SECRET_OTA_VERSION_URL;
constexpr const char* OTA_FIRMWARE_URL = SECRET_OTA_FIRMWARE_URL;
#ifndef SECRET_OTA_SIGNER_PUBLIC_KEY_HEX
#define SECRET_OTA_SIGNER_PUBLIC_KEY_HEX ""
#endif
#ifndef SECRET_OTA_SIGNING_KEY_ID
#define SECRET_OTA_SIGNING_KEY_ID ""
#endif
#ifndef SECRET_OTA_CONTENT_KEY_HEX
#define SECRET_OTA_CONTENT_KEY_HEX ""
#endif
#ifndef SECRET_OTA_CONTENT_KEY_ID
#define SECRET_OTA_CONTENT_KEY_ID ""
#endif
#ifndef SECRET_LOCAL_RECOVERY_USER
#define SECRET_LOCAL_RECOVERY_USER ""
#endif
#ifndef SECRET_LOCAL_RECOVERY_PASSWORD
#define SECRET_LOCAL_RECOVERY_PASSWORD ""
#endif
#ifndef SECRET_LOCAL_RECOVERY_AP_PASSWORD
#define SECRET_LOCAL_RECOVERY_AP_PASSWORD ""
#endif
constexpr const char* OTA_SIGNER_PUBLIC_KEY_HEX =
    SECRET_OTA_SIGNER_PUBLIC_KEY_HEX;
constexpr const char* OTA_SIGNING_KEY_ID = SECRET_OTA_SIGNING_KEY_ID;
constexpr const char* OTA_CONTENT_KEY_HEX = SECRET_OTA_CONTENT_KEY_HEX;
constexpr const char* OTA_CONTENT_KEY_ID = SECRET_OTA_CONTENT_KEY_ID;
constexpr const char* LOCAL_RECOVERY_USER = SECRET_LOCAL_RECOVERY_USER;
constexpr const char* LOCAL_RECOVERY_PASSWORD = SECRET_LOCAL_RECOVERY_PASSWORD;
constexpr const char* LOCAL_RECOVERY_AP_PASSWORD =
    SECRET_LOCAL_RECOVERY_AP_PASSWORD;

#ifndef SGK_PRODUCTION_BUILD
#define SGK_PRODUCTION_BUILD 0
#endif

// ─── BLE 5.3 Beacon Advertiser 설정 (v2.0 신규) ───────────────
// ESP32-C6가 상시 발신할 비콘 고유 식별자 (128-bit UUID)
// 스마트폰 앱은 이 UUID를 수신하면 NAS 인증 절차를 개시한다.
constexpr const char* GATEKEEPER_BEACON_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";

// Hardwareless RC compile flag. The default developer image keeps the
// transport compiled out; only the explicit personal-production profile opts in.
#ifndef ENABLE_HARDWARELESS_RC
#define ENABLE_HARDWARELESS_RC 0
#endif

#ifndef SGK_PERSONAL_INSTALLATION_BUILD
#define SGK_PERSONAL_INSTALLATION_BUILD 0
#endif

#if SGK_PRODUCTION_BUILD && ENABLE_HARDWARELESS_RC && \
    !SGK_PERSONAL_INSTALLATION_BUILD
#error "Commercial production firmware must compile Hardwareless RC out"
#endif

// Provision per Target through secrets.h or NVS key "hwless_door". Empty is
// deliberately invalid: no firmware image ships the canonical sample door ID.
#ifndef SECRET_HARDWARELESS_DOOR_ID_HEX
#define SECRET_HARDWARELESS_DOOR_ID_HEX ""
#endif
constexpr const char* HARDWARELESS_DOOR_ID_HEX =
    SECRET_HARDWARELESS_DOOR_ID_HEX;

// Hardwareless RC Connectable GATT Service 및 Characteristic UUIDs
constexpr const char* HARDWARELESS_SERVICE_UUID     = "9f4d1000-7d9e-4fb1-9c54-6f4d53474b31";
constexpr const char* HARDWARELESS_CHAR_HELLO_UUID  = "9f4d1001-7d9e-4fb1-9c54-6f4d53474b31";
constexpr const char* HARDWARELESS_CHAR_CHAL_UUID   = "9f4d1002-7d9e-4fb1-9c54-6f4d53474b31";
constexpr const char* HARDWARELESS_CHAR_PROOF_UUID  = "9f4d1003-7d9e-4fb1-9c54-6f4d53474b31";
constexpr const char* HARDWARELESS_CHAR_RESULT_UUID = "9f4d1004-7d9e-4fb1-9c54-6f4d53474b31";

// 비콘 광고 인터벌 (ms) — 100ms: 반응성과 전력 균형
constexpr uint32_t BLE_ADV_INTERVAL_MS = 100;

// Signed arm command behavior after per-Target authorization.
// MQTT arm 메시지 수신 후 초음파 센서를 활성화해 둘 유효 시간 (60초)
// 이 시간 내에 초음파 접근 감지가 없으면 자동으로 IDLE 복귀
constexpr uint32_t PRE_ARM_DURATION_MS = 60000;


// ─── AJ-SR04T (JSN-SR04T) 방수 초음파 센서 핀 매핑 ─────────────────
// ESP32-C6 안전 GPIO 사용 (스트래핑 핀 4, 5, 8, 9, 15 및 USB 핀 17~20 회피)
constexpr uint8_t PIN_TRIG = 10; // TRIG: GPIO 10 (OUTPUT)
constexpr uint8_t PIN_ECHO = 11; // ECHO: GPIO 11 (INPUT)

// ─── 릴레이 제어 핀 ───────────────────────────────────────────
// Restored to the physically proven/wall-wired Gatekeeper relay input.
constexpr uint8_t PIN_RELAY      = 23;
constexpr bool    RELAY_ACTIVE_LOW = true;

// ─── 애플리케이션 파라미터 ───────────────────────────────────
// 초음파 센서 맹점(Blind Zone): 0 ~ 19.9cm 구간은 난반사 노이즈로 간주하고 무시
constexpr float ULTRASONIC_MIN_DISTANCE_CM = 20.0f;

// 초음파 감지 기준 거리 (기본값 50cm, 범위 20cm ~ 200cm)
constexpr uint16_t DEFAULT_DISTANCE_THRESHOLD_CM = 50;

// 릴레이 ON 유지 시간 (1초)
constexpr uint32_t RELAY_HOLD_MS        = 1000;
constexpr uint32_t RELAY_ON_DURATION_MS = RELAY_HOLD_MS;

// 릴레이 작동 후 쿨다운 시간 (기본 3초, 원격 가변 조절 가능)
constexpr uint32_t DEFAULT_RELAY_COOLDOWN_MS = 3000;
extern uint32_t g_relay_cooldown_ms;

// 초음파 폴링 인터벌 (ARMED 상태에서만 적용)
constexpr uint32_t ULTRASONIC_POLL_INTERVAL_MS = 100;
