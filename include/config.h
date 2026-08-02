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

// ─── OTA (Over-The-Air) 배포 주소 ──────────────────────────────
constexpr const char* OTA_VERSION_URL  = SECRET_OTA_VERSION_URL;
constexpr const char* OTA_FIRMWARE_URL = SECRET_OTA_FIRMWARE_URL;

// ─── BLE 5.3 Beacon Advertiser 설정 (v2.0 신규) ───────────────
// ESP32-C6가 상시 발신할 비콘 고유 식별자 (128-bit UUID)
// 스마트폰 앱은 이 UUID를 수신하면 NAS 인증 절차를 개시한다.
constexpr const char* GATEKEEPER_BEACON_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";

// Hardwareless RC compile flag (기본값 OFF)
#ifndef ENABLE_HARDWARELESS_RC
#define ENABLE_HARDWARELESS_RC 0
#endif

// Hardwareless RC Connectable GATT Service 및 Characteristic UUIDs
constexpr const char* HARDWARELESS_SERVICE_UUID     = "9f4d1000-7d9e-4fb1-9c54-6f4d53474b31";
constexpr const char* HARDWARELESS_CHAR_HELLO_UUID  = "9f4d1001-7d9e-4fb1-9c54-6f4d53474b31";
constexpr const char* HARDWARELESS_CHAR_CHAL_UUID   = "9f4d1002-7d9e-4fb1-9c54-6f4d53474b31";
constexpr const char* HARDWARELESS_CHAR_PROOF_UUID  = "9f4d1003-7d9e-4fb1-9c54-6f4d53474b31";
constexpr const char* HARDWARELESS_CHAR_RESULT_UUID = "9f4d1004-7d9e-4fb1-9c54-6f4d53474b31";

// 비콘 광고 인터벌 (ms) — 100ms: 반응성과 전력 균형
constexpr uint32_t BLE_ADV_INTERVAL_MS = 100;

// ─── MQTT Pre-arm 사전 승인 설정 (v2.0 신규) ──────────────────
// NAS로부터 승인 명령(arm)을 수신할 MQTT 구독 토픽
constexpr const char* MQTT_TOPIC_ARM = "gatekeeper/arm";
constexpr const char* MQTT_TOPIC_CONFIG_TX_POWER = "gatekeeper/config/tx_power";
constexpr const char* MQTT_TOPIC_CONFIG_DISTANCE_THRESH = "gatekeeper/config/distance_threshold";
constexpr const char* MQTT_TOPIC_CONFIG_TOF_DIST = "gatekeeper/config/tof_distance"; // 호환용 하위 별칭
constexpr const char* MQTT_TOPIC_CONFIG_DURATION = "gatekeeper/config/duration";

// MQTT arm 메시지 수신 후 초음파 센서를 활성화해 둘 유효 시간 (60초)
// 이 시간 내에 초음파 접근 감지가 없으면 자동으로 IDLE 복귀
constexpr uint32_t PRE_ARM_DURATION_MS = 60000;


// ─── AJ-SR04T (JSN-SR04T) 방수 초음파 센서 핀 매핑 ─────────────────
// ESP32-C6 안전 GPIO 사용 (스트래핑 핀 4, 5, 8, 9, 15 및 USB 핀 17~20 회피)
constexpr uint8_t PIN_TRIG = 10; // TRIG: GPIO 10 (OUTPUT)
constexpr uint8_t PIN_ECHO = 11; // ECHO: GPIO 11 (INPUT)

// ─── 릴레이 제어 핀 ───────────────────────────────────────────
constexpr uint8_t PIN_RELAY      = 3;
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
