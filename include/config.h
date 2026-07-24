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
// ⚠️ GPIO23: ESP32-C6 정상 GPIO. GPIO22/23은 I2C 기능이 아닌 일반 핀으로 확인됨.
//    (실제 문제: 3.3V HIGH → 5V 릴레이 포토커플러 Vf 1.4V 넘어 상시 ON 유지 → 시프트 문제)
// 해결책: INPUT 모드(고임피던스)로 OFF 제어 → smartbox 26061301 보고서 참조
constexpr uint8_t PIN_RELAY      = 23;  // 배선 GPIO23 유지


/// true  = 모듈 IN 핀이 LOW일 때 릴레이 ON (오픈콜렉터/광절연 일반 형)
/// false = 모듈 IN 핀이 HIGH일 때 릴레이 ON
/// ⚠️ INPUT 모드 트릭으로 OFF 제어하므로 이 상수는 relayOn() 전용으로만 사용
/// (OFF는 언제나 pinMode(INPUT)로 처리 — smartbox 26061301 보고서)
constexpr bool    RELAY_ACTIVE_LOW = true;  // ON 시 LOW 출력 기준


// ─── 애플리케이션 파라미터 ───────────────────────────────────
/// 이 거리(mm) 이하 감지 시 릴레이 트리거 (통합 테스트용)
/// 2026-07-24: 500mm (50cm) 로 설정
constexpr uint16_t GATE_THRESHOLD_MM = 500;

/// 릴레이 ON 유지 시간 (ms) — 트리거 후 자동 OFF
constexpr uint32_t RELAY_ON_DURATION_MS = 1000;

/// 릴레이 OFF 후 재트리거 방지 쿨다운 (ms)
constexpr uint32_t RELAY_COOLDOWN_MS = 2000;


/// ToF 측정 주기 (ms)
constexpr uint32_t TOF_POLL_INTERVAL_MS = 100;

/// 릴레이 테스트 토글 주기 (ms)
constexpr uint32_t RELAY_TOGGLE_MS = 2000;
