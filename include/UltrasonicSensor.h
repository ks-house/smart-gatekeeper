// include/UltrasonicSensor.h
// =============================================================
// smart-gatekeeper — AJ-SR04T (JSN-SR04T) 방수 초음파 센서 드라이버
// 맹점 방어(0~20cm 난반사 노이즈 무시) & pulseIn 30ms 타임아웃 적용
// =============================================================
#pragma once

#include <Arduino.h>
#include "config.h"

class UltrasonicSensor {
public:
  /// GPIO 핀 초기화 (TRIG=OUTPUT, ECHO=INPUT)
  static void init();

  /// 초음파 거리 측정 (cm)
  /// - 10µs HIGH 펄스로 발사 후 pulseIn(30ms 타임아웃)으로 펄스 수신
  /// - 맹점(0~19.9cm) 또는 타임아웃(0) 시 -1.0f (유효하지 않음) 반환
  static float readDistanceCm();
};
