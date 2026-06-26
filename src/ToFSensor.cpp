// src/ToFSensor.cpp
// =============================================================
// VL53L0X ToF 거리 센서 드라이버 구현
// =============================================================
#include "ToFSensor.h"
#include "config.h"

// ─────────────────────────────────────────────────────────────
// 생성자
// ─────────────────────────────────────────────────────────────
ToFSensor::ToFSensor(int xshutPin)
    : _xshutPin(xshutPin) {}

// ─────────────────────────────────────────────────────────────
// begin() — I2C 버스 초기화 및 센서 부팅
// ─────────────────────────────────────────────────────────────
bool ToFSensor::begin() {
  // XSHUT 핀이 지정된 경우: HIGH로 올려서 센서 활성화
  if (_xshutPin >= 0) {
    pinMode(_xshutPin, OUTPUT);
    digitalWrite(_xshutPin, HIGH);
    delay(10);  // 센서 부팅 대기 (VL53L0X 데이터시트: t_boot ≤ 1.2ms)
  }

  // I2C 초기화 — 400kHz Fast Mode 명시 (기본 100kHz 대비 응답 지연 방지)
  // 출처: raw/ST_VL53L0X_Specs.md §4 — Fast mode 지원 확인
  Wire.begin(PIN_SDA, PIN_SCL, 400000UL);

  // I2C 타임아웃 설정 — 미설정 시 끊어진 센서에 대해 readRange...() 영구 블로킹
  _sensor.setTimeout(500);  // 500ms 내 응답 없으면 에러 처리

  // VL53L0X 초기화 — 실패 시 false 반환
  if (!_sensor.init()) {
    Serial.println("[ERROR] ToFSensor: VL53L0X init failed. "
                   "Check wiring (SDA=GPIO6, SCL=GPIO7) and 3.3V supply.");
    _ready = false;
    return false;
  }

  // 연속 측정 모드 시작 (단발보다 I2C 오버헤드 낮음)
  _sensor.startContinuous(TOF_POLL_INTERVAL_MS);

  Serial.println("[INFO] ToFSensor: VL53L0X initialized. "
                 "Continuous mode @ " +
                 String(TOF_POLL_INTERVAL_MS) + "ms interval.");
  _ready = true;
  return true;
}

// ─────────────────────────────────────────────────────────────
// readMM() — 거리 측정 (mm)
// 측정 실패(타임아웃) 시 0 반환 + 에러 플래그 set
// ─────────────────────────────────────────────────────────────
uint16_t ToFSensor::readMM() {
  if (!_ready) {
    Serial.println("[WARN] ToFSensor: readMM() called before successful begin().");
    _lastError = true;
    return 0;
  }

  // readRangeContinuousMillimeters(): 측정값 준비까지 블로킹.
  // setTimeout(500) 설정 시 500ms 초과하면 내부 타임아웃 플래그 set.
  uint16_t mm = _sensor.readRangeContinuousMillimeters();

  // 65535 = 라이브러리가 I2C 오류/범위 초과 시 반환하는 sentinel 값
  // 출처: raw/ST_VL53L0X_Specs.md §7
  if (_sensor.timeoutOccurred() || mm == 65535) {
    Serial.println("[ERROR] ToFSensor: Measurement timeout or out-of-range "
                   "(returned 65535). Check wiring and target distance.");
    _lastError = true;
    return 0;
  }

  _lastError = false;
  return mm;
}
