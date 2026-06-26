// include/config.h
// =============================================================
// smart-gatekeeper — 전역 핀 상수 및 프로젝트 설정
// MCU: ESP32-C6-DevKitC-1 (RISC-V, 3.3V)
// ⚠️ 이 파일의 상수만 수정하고, 드라이버 코드에 하드코딩 금지.
// 출처: raw/Espressif_ESP32C6_BoardSpec.md §3, §4
// =============================================================
#pragma once

#include <cstdint>

// ─── I2C ─────────────────────────────────────────────────────
// ESP32-C6 안전 핀: GPIO6(SDA), GPIO7(SCL)
// GPIO4/5는 JTAG 스트래핑 핀 → 사용 금지
// GPIO21/22는 ESP32 legacy pin → C6에서 다른 기능일 수 있음
constexpr uint8_t PIN_SDA        = 6;
constexpr uint8_t PIN_SCL        = 7;

/// XSHUT: 다중 VL53L0X 주소 할당 또는 하드 리셋용 (선택)
/// GPIO6/7/8(LED) 회피 → GPIO10 사용
constexpr uint8_t PIN_TOF_XSHUT  = 10;

// ─── 릴레이 ──────────────────────────────────────────────────
// ESP32-C6 안전 핀 (스트래핑 핀 GPIO4/5/8/9/15 회피)
constexpr uint8_t PIN_RELAY      = 3;

/// true  = 모듈 IN 핀이 LOW일 때 릴레이 ON (오픈컬렉터/광절연 일반 형)
/// false = 모듈 IN 핀이 HIGH일 때 릴레이 ON
/// ⚠️ 자신의 릴레이 모듈 실크스크린 또는 데이터시트로 반드시 확인!
constexpr bool    RELAY_ACTIVE_LOW = true;

// ─── 애플리케이션 파라미터 ───────────────────────────────────
/// 이 거리(mm) 이하 감지 시 릴레이 트리거 (통합 테스트용)
constexpr uint16_t GATE_THRESHOLD_MM = 300;

/// ToF 측정 주기 (ms)
constexpr uint32_t TOF_POLL_INTERVAL_MS = 100;

/// 릴레이 테스트 토글 주기 (ms)
constexpr uint32_t RELAY_TOGGLE_MS = 2000;
