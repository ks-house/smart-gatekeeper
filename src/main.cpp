// src/main.cpp
// =============================================================
// smart-gatekeeper — 메인 진입점
// 빌드 플래그에 따라 테스트 모드 전환:
//   -DTEST_TOF_ONLY   → ToF 단독 테스트
//   -DTEST_RELAY_ONLY → 릴레이 단독 테스트
//   (없으면)          → 통합 데모 (ToF 임계값 → 릴레이 트리거)
// =============================================================
#include <Arduino.h>

#include "config.h"
#include "RelayController.h"
#include "ToFSensor.h"

// ─────────────────────────────────────────────────────────────
// 인스턴스
// ─────────────────────────────────────────────────────────────
#ifndef TEST_RELAY_ONLY
static ToFSensor tof(PIN_TOF_XSHUT);
#endif

#ifndef TEST_TOF_ONLY
static RelayController relay(PIN_RELAY, RELAY_ACTIVE_LOW);
#endif

// ─────────────────────────────────────────────────────────────
// setup()
// ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);  // 시리얼 모니터 연결 대기
  Serial.println("\n========================================");
  Serial.println(" smart-gatekeeper — Step 1 PoC");

#if defined(TEST_TOF_ONLY)
  Serial.println(" Mode: ToF Sensor Standalone Test");
  Serial.println("========================================\n");
  if (!tof.begin()) {
    Serial.println("[FATAL] Cannot continue without ToF sensor. Halting.");
    while (true) { delay(1000); }
  }

#elif defined(TEST_RELAY_ONLY)
  Serial.println(" Mode: Relay Standalone Test");
  Serial.println("========================================\n");
  relay.begin();

#else
  Serial.println(" Mode: Integrated Demo (ToF + Relay)");
  Serial.println("========================================\n");
  relay.begin();
  if (!tof.begin()) {
    Serial.println("[FATAL] Cannot continue without ToF sensor. Halting.");
    while (true) { delay(1000); }
  }
#endif
}

// ─────────────────────────────────────────────────────────────
// loop()
// ─────────────────────────────────────────────────────────────
void loop() {
  static uint32_t lastRelayToggle = 0;

#if defined(TEST_TOF_ONLY)
  // ── ToF 단독 테스트 ────────────────────────────────────────
  uint16_t mm = tof.readMM();
  if (!tof.hasError()) {
    Serial.printf("[ToF] Distance: %4u mm\n", mm);
  }
  delay(TOF_POLL_INTERVAL_MS);

#elif defined(TEST_RELAY_ONLY)
  // ── 릴레이 단독 테스트 ─────────────────────────────────────
  uint32_t now = millis();
  if (now - lastRelayToggle >= RELAY_TOGGLE_MS) {
    lastRelayToggle = now;
    relay.toggle();
    Serial.printf("[Relay] %s  (t=%lu ms)\n",
                  relay.state() == RelayState::ON ? "ON " : "OFF",
                  now);
  }

#else
  // ── 통합 데모: ToF 감지 → 릴레이 트리거 ──────────────────
  uint16_t mm = tof.readMM();
  if (!tof.hasError()) {
    bool inRange = (mm > 0 && mm < GATE_THRESHOLD_MM);
    Serial.printf("[ToF] %4u mm  →  Gate: %s\n",
                  mm, inRange ? "OPEN " : "CLOSED");
    if (inRange) {
      relay.on();
    } else {
      relay.off();
    }
  }
  delay(TOF_POLL_INTERVAL_MS);
#endif
}
