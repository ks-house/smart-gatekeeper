// include/config.h
// =============================================================
// smart-gatekeeper — 전역 핀 상수 및 프로젝트 설정 (Step 3 개편)
// MCU: ESP32-C6-DevKitC-1 (RISC-V, 3.3V)
// ⚠️ 이 파일의 상수만 수정하고, 드라이버 코드에 하드코딩 금지.
// ⚠️ 보안 민감 정보는 include/secrets.h 참조.
// =============================================================
#pragma once

#include <cstdint>
#include "secrets.h"

// ─── 네트워크 & 시놀로지 NAS 백엔드 API 설정 ────────────────────
// include/secrets.h 에서 로드
constexpr const char* WIFI_SSID     = SECRET_WIFI_SSID;
constexpr const char* WIFI_PASSWORD = SECRET_WIFI_PASSWORD;

constexpr const char* API_URL      = SECRET_API_URL;
constexpr const char* API_KEY      = SECRET_API_KEY;
constexpr const char* TEST_BLE_MAC = SECRET_TEST_BLE_MAC;

// ─── I2C & 핀 매핑 ───────────────────────────────────────────
// ESP32-C6 안전 핀: GPIO6(SDA), GPIO7(SCL)
constexpr uint8_t PIN_SDA        = 6;
constexpr uint8_t PIN_SCL        = 7;

/// XSHUT: VL53L0X 활성화 제어 (GPIO10)
constexpr uint8_t PIN_TOF_XSHUT  = 10;

// ─── 릴레이 제어 핀 ───────────────────────────────────────────
// ESP32-C6 안전 핀: GPIO23
// ⚠️ 5V 릴레이 상시 ON 방지를 위해 OFF 제어 시 pinMode(INPUT) 고임피던스 적용
constexpr uint8_t PIN_RELAY      = 23;
constexpr bool    RELAY_ACTIVE_LOW = true;  // ON 시 LOW 출력 기준

// ─── 애플리케이션 파라미터 ───────────────────────────────────
/// ToF 감지 임계값 (mm) — 500mm (50cm) 이내 진입 시 NAS 검증 트리거
constexpr uint16_t DISTANCE_THRESHOLD_MM = 500;
constexpr uint16_t GATE_THRESHOLD_MM     = DISTANCE_THRESHOLD_MM;  // 이전 버전 호환용

/// 릴레이 ON 유지 시간 (ms) — 승인 수신 시 릴레이 작동 시간
constexpr uint32_t RELAY_HOLD_MS        = 1000;
constexpr uint32_t RELAY_ON_DURATION_MS = RELAY_HOLD_MS;          // 이전 버전 호환용

/// 연속 중복 요청 방지 쿨다운 타이머 (ms)
constexpr uint32_t RELAY_COOLDOWN_MS    = 2000;

/// ToF 측정 주기 (ms)
constexpr uint32_t TOF_POLL_INTERVAL_MS = 100;

/// 릴레이 테스트 토글 주기 (ms)
constexpr uint32_t RELAY_TOGGLE_MS      = 2000;
