// src/RelayController.cpp
// =============================================================
// 릴레이 컨트롤러 구현
// Active-LOW / Active-HIGH 모두 지원
// =============================================================
#include "RelayController.h"

// ─────────────────────────────────────────────────────────────
// 생성자
// ─────────────────────────────────────────────────────────────
RelayController::RelayController(uint8_t pin, bool activeLow)
    : _pin(pin), _activeLow(activeLow) {}

// ─────────────────────────────────────────────────────────────
// begin() — GPIO 초기화. 반드시 OFF 상태로 시작.
// ─────────────────────────────────────────────────────────────
void RelayController::begin() {
  pinMode(_pin, OUTPUT);
  _state = RelayState::OFF;
  _applyState();
  Serial.printf("[INFO] RelayController: GPIO%d initialized. "
                "Mode: Active-%s. State: OFF.\n",
                _pin, _activeLow ? "LOW" : "HIGH");
}

// ─────────────────────────────────────────────────────────────
// on() / off() / toggle()
// ─────────────────────────────────────────────────────────────
void RelayController::on() {
  _state = RelayState::ON;
  _applyState();
}

void RelayController::off() {
  _state = RelayState::OFF;
  _applyState();
}

void RelayController::toggle() {
  _state = (_state == RelayState::ON) ? RelayState::OFF : RelayState::ON;
  _applyState();
}

// ─────────────────────────────────────────────────────────────
// _applyState() — 논리 상태 → 실제 GPIO 전압 변환
// Active-LOW 모듈: ON=LOW, OFF=HIGH
// Active-HIGH 모듈: ON=HIGH, OFF=LOW
// ─────────────────────────────────────────────────────────────
void RelayController::_applyState() {
  bool logicOn = (_state == RelayState::ON);
  // activeLow 이면 전압을 반전
  digitalWrite(_pin, (_activeLow ? !logicOn : logicOn) ? HIGH : LOW);
}
