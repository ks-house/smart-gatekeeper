// src/UltrasonicSensor.cpp
// =============================================================
// smart-gatekeeper — AJ-SR04T (JSN-SR04T) 방수 초음파 센서 구현
// =============================================================
#include "UltrasonicSensor.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

void UltrasonicSensor::init() {
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  digitalWrite(PIN_TRIG, LOW);
  LOGF("[ULTRASONIC] ✅ AJ-SR04T 방수 초음파 센서 초기화 완료 (TRIG: GPIO %d, ECHO: GPIO %d)", PIN_TRIG, PIN_ECHO);
}

float UltrasonicSensor::readDistanceCm() {
  // 1. 트리거 핀에 10µs HIGH 펄스 하달
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  // 2. 에코 핀 수신 시간 측정 (30,000µs 타임아웃 = 최대 약 5.1m)
  // pulseIn 타임아웃 설정으로 무한 대기 블로킹 버그 방지
  unsigned long durationUs = pulseIn(PIN_ECHO, HIGH, 30000UL);

  // 3. 타임아웃(0) 발생 시 -1.0f 반환
  if (durationUs == 0) {
    return -1.0f;
  }

  // 4. 시간을 거리(cm)로 환산 (음속 340m/s = 0.034cm/µs, 왕복이므로 / 2)
  float distanceCm = (float)durationUs * 0.034f / 2.0f;

  // 5. [매우 중요] 맹점 (Blind Zone 0 ~ 20cm) 및 이상 범위 방어
  // AJ-SR04T 초음파 특성상 0~20cm 구간은 진동잔향 난반사 노이즈이므로 무시(-1.0f)
  if (distanceCm < ULTRASONIC_MIN_DISTANCE_CM || distanceCm > 400.0f) {
    return -1.0f;
  }

  return distanceCm;
}
