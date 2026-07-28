// src/UltrasonicSensor.cpp
// =============================================================
// smart-gatekeeper — AJ-SR04T (JSN-SR04T) 방수 초음파 센서 구현
// =============================================================
#include "UltrasonicSensor.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

float UltrasonicSensor::history[5] = {999.0f, 999.0f, 999.0f, 999.0f, 999.0f};
uint8_t UltrasonicSensor::historyIdx = 0;

void UltrasonicSensor::init() {
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  digitalWrite(PIN_TRIG, LOW);

  for (int i = 0; i < 5; i++) {
    history[i] = 999.0f;
  }
  historyIdx = 0;

  LOGF("[ULTRASONIC] ✅ AJ-SR04T 방수 초음파 센서 및 5단 중앙값 필터 초기화 완료 (TRIG: GPIO %d, ECHO: GPIO %d)", PIN_TRIG, PIN_ECHO);
}

float UltrasonicSensor::readDistanceCmRaw(unsigned long* outDurationUs) {
  // 1. 트리거 핀에 20µs HIGH 펄스 하달
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(20);
  digitalWrite(PIN_TRIG, LOW);

  // 2. 에코 핀 수신 시간 측정 (30,000µs 타임아웃 = 최대 약 5.1m)
  unsigned long durationUs = pulseIn(PIN_ECHO, HIGH, 30000UL);

  if (outDurationUs != nullptr) {
    *outDurationUs = durationUs;
  }

  // 3. 타임아웃(0) 발생 시 999.0f 반환
  if (durationUs == 0) {
    return 999.0f;
  }

  // 4. [AJ-SR04T 고질적 Ghost Echo 지터 방어] 무반사/타임아웃 시 모듈 내부 칩셋이
  // 전원/발진 오차로 약 2570~3320µs (약 44.0cm~56.9cm, 440~569mm) 출렁이는 펄스 예외 처리
  if (durationUs >= 2570UL && durationUs <= 3320UL) {
    return 999.0f;
  }

  // 5. 시간을 거리(cm)로 환산 (음속 343m/s = 0.0343cm/µs, 왕복이므로 / 2)
  float distanceCm = (float)durationUs * 0.0343f / 2.0f;

  // 6. [매우 중요] 맹점 (Blind Zone 0 ~ 20cm) 및 이상 범위 방어
  if (distanceCm < ULTRASONIC_MIN_DISTANCE_CM || distanceCm > 400.0f) {
    return 999.0f;
  }

  return distanceCm;
}

float UltrasonicSensor::readDistanceCm(unsigned long* outDurationUs) {
  float raw = readDistanceCmRaw(outDurationUs);

  history[historyIdx] = raw;
  historyIdx = (historyIdx + 1) % 5;

  // 5개 히스토리 샘플 버블 정렬 후 중앙값(Median) 선택
  float sorted[5];
  for (int i = 0; i < 5; i++) {
    sorted[i] = history[i];
  }

  for (int i = 0; i < 4; i++) {
    for (int j = i + 1; j < 5; j++) {
      if (sorted[i] > sorted[j]) {
        float temp = sorted[i];
        sorted[i] = sorted[j];
        sorted[j] = temp;
      }
    }
  }

  return sorted[2]; // 5개 샘플 중 중앙값 반환
}
