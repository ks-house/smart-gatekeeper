// src/main.cpp
// =============================================================
// smart-gatekeeper — Step 1 로컬 통합 테스트 (ToF + Relay)
//
// 동작: ToF 거리 ≤ 500mm 감지 시 릴레이 1초 ON → 자동 OFF
//       2초 쿨다운 후 재트리거 가능
//
// 배선:
//   VL53L0X VCC   → ESP32-C6 3V3
//   VL53L0X GND   → ESP32-C6 GND
//   VL53L0X SDA   → ESP32-C6 GPIO6
//   VL53L0X SCL   → ESP32-C6 GPIO7
//   VL53L0X XSHUT → ESP32-C6 GPIO10
//   릴레이 VCC    → ESP32-C6 5V
//   릴레이 GND    → ESP32-C6 GND
//   릴레이 IN     → ESP32-C6 GPIO23
//
// 빌드: pio run -e esp32c6 -t upload
// =============================================================
#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>

#include "config.h"

// ─────────────────────────────────────────────────────────────
// ESP-IDF stdout 경로 출력 (Serial.println 대신)
// ─────────────────────────────────────────────────────────────
#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

// ─────────────────────────────────────────────────────────────
// 릴레이 제어 — INPUT 모드 트릭
// 이유: ESP32-C6 3.3V HIGH로는 5V 릴레이 포토커플러(Vf=1.4V) 완전 차단 불가
//      INPUT(고임피던스) 시 모듈 내부 풀업이 IN을 5V로 올려 완전 OFF
// 출처: smartbox/reports/26061301_릴레이연결_report.md
// ─────────────────────────────────────────────────────────────
static inline void relayOn() {
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, LOW);   // Active-LOW: LOW = 코일 통전 = ON
}

static inline void relayOff() {
  pinMode(PIN_RELAY, INPUT);      // 고임피던스: 전류 차단 = 확실한 OFF
}

// ─────────────────────────────────────────────────────────────
// 상태 머신 (State Machine)
// ─────────────────────────────────────────────────────────────
enum class GateState {
  IDLE,       // 대기 중 — 트리거 가능
  RELAY_ON,   // 릴레이 ON 중 (1초 유지)
  COOLDOWN    // 쿨다운 중 (2초, 재트리거 방지)
};

// ─────────────────────────────────────────────────────────────
// 전역 객체
// ─────────────────────────────────────────────────────────────
static VL53L0X sensor;
static GateState state     = GateState::IDLE;
static uint32_t  stateMs   = 0;   // 상태 진입 시각

// ─────────────────────────────────────────────────────────────
// setup()
// ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // 릴레이 초기화 — INPUT 모드(고임피던스) = 확실한 OFF
  relayOff();

  // XSHUT HIGH → VL53L0X 활성화
  // (저가 모듈은 내부 풀업 없음 → 미연결 시 LOW floating → 센서 리셋 상태)
  pinMode(PIN_TOF_XSHUT, OUTPUT);
  digitalWrite(PIN_TOF_XSHUT, HIGH);
  delay(10);  // t_boot: 최대 1.2ms

  // I2C 초기화 (Wire.begin 이후 Serial 출력 가능)
  Wire.begin(PIN_SDA, PIN_SCL, 400000UL);
  delay(20);

  // 배너
  LOGF("\n============================================");
  LOGF(" smart-gatekeeper — Step 1 로컬 통합 테스트");
  LOGF(" ToF(GPIO6/7/10) + Relay(GPIO23)");
  LOGF(" 임계값: %u mm | ON: %lu ms | 쿨다운: %lu ms",
       GATE_THRESHOLD_MM,
       (unsigned long)RELAY_ON_DURATION_MS,
       (unsigned long)RELAY_COOLDOWN_MS);
  LOGF("============================================");

  // VL53L0X 초기화
  sensor.setTimeout(500);
  LOGF("[INFO] sensor.init() 호출...");
  if (!sensor.init()) {
    LOGF("[FATAL] VL53L0X init 실패! 배선 확인 후 리셋.");
    while (true) { delay(1000); }
  }
  sensor.startContinuous(TOF_POLL_INTERVAL_MS);
  LOGF("[INFO] VL53L0X 초기화 성공! 측정 시작.");
  LOGF("--------------------------------------------");
}

// ─────────────────────────────────────────────────────────────
// loop() — millis() 기반 비블로킹 상태 머신
// ─────────────────────────────────────────────────────────────
void loop() {
  uint32_t now = millis();

  // ── ToF 거리 측정 ──────────────────────────────────────────
  uint16_t mm = sensor.readRangeContinuousMillimeters();
  bool validReading = !(sensor.timeoutOccurred() || mm == 65535);

  if (!validReading) {
    LOGF("[ERROR] ToF 측정 실패 (타임아웃/범위초과)");
  }

  // ── 상태 머신 ─────────────────────────────────────────────
  switch (state) {

    case GateState::IDLE:
      if (validReading) {
        LOGF("[ToF] %4u mm  |  State: IDLE", mm);
      }
      // 임계값 이내 감지 시 트리거
      if (validReading && mm <= GATE_THRESHOLD_MM) {
        LOGF("[GATE] *** 감지! %u mm <= %u mm → 릴레이 ON ***",
             mm, GATE_THRESHOLD_MM);
        relayOn();
        state   = GateState::RELAY_ON;
        stateMs = now;
      }
      break;

    case GateState::RELAY_ON:
      // 1초 후 자동 OFF
      if (now - stateMs >= RELAY_ON_DURATION_MS) {
        relayOff();
        LOGF("[GATE] 릴레이 OFF (1초 경과). 쿨다운 %lu ms 시작.",
             (unsigned long)RELAY_COOLDOWN_MS);
        state   = GateState::COOLDOWN;
        stateMs = now;
      }
      break;

    case GateState::COOLDOWN:
      // 쿨다운 종료 후 IDLE 복귀
      if (now - stateMs >= RELAY_COOLDOWN_MS) {
        LOGF("[GATE] 쿨다운 완료. IDLE 상태 복귀.");
        state = GateState::IDLE;
      }
      break;
  }

  delay(TOF_POLL_INTERVAL_MS);
}
