// include/config.h
// =============================================================
// smart-gatekeeper — 전역 핀 상수 및 프로젝트 설정 (Step 4 BLE & 이중 검증)
// =============================================================
#pragma once

#include <cstdint>
#include "secrets.h"

// ─── 펌웨어 버전 (GitHub CI 동적 오버라이드 지원) ─────────────────
#ifdef FIRMWARE_VERSION_OVERRIDE
#define FIRMWARE_VERSION FIRMWARE_VERSION_OVERRIDE
#else
#ifndef FIRMWARE_VERSION
#define FIRMWARE_VERSION "1.0.0"
#endif
#endif

// ─── 네트워크 & 시놀로지 NAS 백엔드 API 설정 ────────────────────
constexpr const char* WIFI_SSID     = SECRET_WIFI_SSID;
constexpr const char* WIFI_PASSWORD = SECRET_WIFI_PASSWORD;

constexpr const char* API_URL      = SECRET_API_URL;
constexpr const char* API_KEY      = SECRET_API_KEY;
constexpr const char* TEST_BLE_MAC = SECRET_TEST_BLE_MAC;

// ─── MQTT 브로커 설정 ─────────────────────────────────────────
constexpr const char* MQTT_HOST     = SECRET_MQTT_HOST;
constexpr uint16_t    MQTT_PORT     = SECRET_MQTT_PORT;
constexpr const char* MQTT_USER     = SECRET_MQTT_USER;
constexpr const char* MQTT_PASSWORD = SECRET_MQTT_PASSWORD;

// ─── OTA (Over-The-Air) 배포 주소 ──────────────────────────────
constexpr const char* OTA_VERSION_URL  = SECRET_OTA_VERSION_URL;
constexpr const char* OTA_FIRMWARE_URL = SECRET_OTA_FIRMWARE_URL;

// ─── BLE 5.0 스캔 및 이중 검증 설정 ──────────────────────────────
constexpr const char* BLE_TARGET_UUID   = "12345678-1234-1234-1234-123456789abc";
constexpr int         BLE_RSSI_THRESHOLD = -70; // dBm
constexpr uint32_t    BLE_VALID_MS       = 10000; // BLE 유효 인정 시간 (10초)

// ─── I2C & 핀 매핑 ───────────────────────────────────────────
constexpr uint8_t PIN_SDA        = 6;
constexpr uint8_t PIN_SCL        = 7;
constexpr uint8_t PIN_TOF_XSHUT  = 10;

// ─── 릴레이 제어 핀 ───────────────────────────────────────────
constexpr uint8_t PIN_RELAY      = 23;
constexpr bool    RELAY_ACTIVE_LOW = true;

// ─── 애플리케이션 파라미터 ───────────────────────────────────
constexpr uint16_t DISTANCE_THRESHOLD_MM = 500;
constexpr uint16_t GATE_THRESHOLD_MM     = DISTANCE_THRESHOLD_MM;

constexpr uint32_t RELAY_HOLD_MS        = 1000;
constexpr uint32_t RELAY_ON_DURATION_MS = RELAY_HOLD_MS;

constexpr uint32_t COOLDOWN_MS          = 10000; // 쿨다운 10초
constexpr uint32_t RELAY_COOLDOWN_MS    = COOLDOWN_MS;
constexpr uint32_t TOF_POLL_INTERVAL_MS = 100;
constexpr uint32_t RELAY_TOGGLE_MS      = 2000;
