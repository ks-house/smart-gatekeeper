// include/UltrasonicSensor.h
// =============================================================
// smart-gatekeeper — AJ-SR04T (JSN-SR04T) 방수 초음파 센서 드라이버
// 맹점 방어(0~20cm 난반사 노이즈 무시) & pulseIn 30ms 타임아웃 적용
// =============================================================
#pragma once

#include <Arduino.h>
#include "config.h"

class UltrasonicSensor {
private:
  static float history[5];
  static uint8_t historyIdx;

public:
  /// GPIO 핀 초기화 (TRIG=OUTPUT, ECHO=INPUT)
  static void init();

  /// 새 Pre-arm 세션이 이전 사람의 거리 표본을 재사용하지 않도록 필터 이력 초기화.
  static void resetHistory();

  /// 초음파 단발 측정 (Raw)
  static float readDistanceCmRaw(unsigned long* outDurationUs = nullptr);

  /// 5단 중앙값 필터(Median Filter)가 적용된 초음파 거리 측정 (cm)
  /// - 맹점(0~19.9cm), Ghost Echo 지터(44~57cm), 타임아웃 시 999.0f 반환
  static float readDistanceCm(unsigned long* outDurationUs = nullptr);
};
