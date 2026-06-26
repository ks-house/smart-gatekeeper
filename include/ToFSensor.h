// include/ToFSensor.h
// =============================================================
// VL53L0X ToF 거리 센서 드라이버 래퍼
// 라이브러리: pololu/VL53L0X
// =============================================================
#pragma once

#include <Arduino.h>
#include <VL53L0X.h>
#include <Wire.h>

/// VL53L0X 센서 1개를 추상화한 드라이버 클래스.
/// - 초기화 실패 시 isReady() == false 로 안전하게 종료.
/// - read() 는 측정 실패 시 0 을 반환하고 에러를 시리얼에 기록.
class ToFSensor {
public:
  /// @param xshutPin  XSHUT 핀 번호. -1 이면 사용 안 함.
  explicit ToFSensor(int xshutPin = -1);

  /// I2C 초기화 및 센서 boot. true = 성공.
  bool begin();

  /// 거리를 mm 단위로 반환. 측정 실패 시 0 반환.
  uint16_t readMM();

  /// 마지막 측정이 타임아웃/오류였는지 여부.
  bool hasError() const { return _lastError; }

  /// begin() 이 성공했는지 여부.
  bool isReady() const { return _ready; }

private:
  VL53L0X _sensor;
  int      _xshutPin;
  bool     _ready     = false;
  bool     _lastError = false;
};
