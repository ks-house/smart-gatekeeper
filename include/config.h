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
#define FIRMWARE_VERSION "2.0.0"
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

// 비콘 광고 인터벌 (ms) — 100ms: 반응성과 전력 균형
constexpr uint32_t BLE_ADV_INTERVAL_MS = 100;

// ─── MQTT Pre-arm 사전 승인 설정 (v2.0 신규) ──────────────────
// NAS로부터 승인 명령(arm)을 수신할 MQTT 구독 토픽
constexpr const char* MQTT_TOPIC_ARM = "gatekeeper/arm";

// MQTT arm 메시지 수신 후 ToF 센서를 활성화해 둘 유효 시간 (60초)
// 이 시간 내에 ToF 감지가 없으면 자동으로 IDLE 복귀
constexpr uint32_t PRE_ARM_DURATION_MS = 60000;

// ─── I2C & 핀 매핑 ───────────────────────────────────────────
constexpr uint8_t PIN_SDA        = 6;
constexpr uint8_t PIN_SCL        = 7;
constexpr uint8_t PIN_TOF_XSHUT  = 10;

// ─── 릴레이 제어 핀 ───────────────────────────────────────────
constexpr uint8_t PIN_RELAY      = 23;
constexpr bool    RELAY_ACTIVE_LOW = true;

// ─── 애플리케이션 파라미터 ───────────────────────────────────
// ToF 감지 임계 거리 (50cm = 500mm)
constexpr uint16_t DISTANCE_THRESHOLD_MM = 500;
constexpr uint16_t GATE_THRESHOLD_MM     = DISTANCE_THRESHOLD_MM;

// 릴레이 ON 유지 시간 (1초)
constexpr uint32_t RELAY_HOLD_MS        = 1000;
constexpr uint32_t RELAY_ON_DURATION_MS = RELAY_HOLD_MS;

// 릴레이 작동 후 쿨다운 시간 (10초, 중복 개방 방지)
constexpr uint32_t COOLDOWN_MS          = 10000;
constexpr uint32_t RELAY_COOLDOWN_MS    = COOLDOWN_MS;

// ToF 폴링 인터벌 (ARMED 상태에서만 적용)
constexpr uint32_t TOF_POLL_INTERVAL_MS = 100;
