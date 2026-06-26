// include/RelayController.h
// =============================================================
// 1채널 릴레이 모듈 드라이버
// Active-HIGH / Active-LOW 모두 지원 (config.h 로 설정)
// =============================================================
#pragma once

#include <Arduino.h>

/// 릴레이 상태를 나타내는 논리적 열거형.
enum class RelayState : uint8_t {
  OFF = 0,
  ON  = 1,
};

class RelayController {
public:
  /// @param pin        릴레이 IN 핀 번호
  /// @param activeLow  true = active-LOW 모듈 (LOW → 릴레이 ON)
  RelayController(uint8_t pin, bool activeLow);

  /// GPIO 핀 초기화. 시작 시 릴레이를 반드시 OFF 상태로 설정.
  void begin();

  /// 릴레이 켜기
  void on();

  /// 릴레이 끄기
  void off();

  /// 현재 상태 토글
  void toggle();

  /// 현재 논리 상태 반환
  RelayState state() const { return _state; }

private:
  uint8_t    _pin;
  bool       _activeLow;
  RelayState _state = RelayState::OFF;

  /// 논리 상태를 실제 GPIO 전압으로 변환하여 출력
  void _applyState();
};
