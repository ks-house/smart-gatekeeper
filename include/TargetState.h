#pragma once

#include <cstdint>

enum class GateState : uint8_t {
  IDLE,
  AUTH_PENDING,
  ARMED,
  RELAY_HOLD,
  COOLDOWN,
};

enum class OtaSafeState : uint8_t {
  SAFE,
  ACCESS_SESSION_ACTIVE,
  RELAY_ACTIVE,
};

constexpr OtaSafeState classifyOtaSafeState(GateState state, bool armed,
                                            bool relay_on) {
  if (relay_on || state == GateState::RELAY_HOLD) {
    return OtaSafeState::RELAY_ACTIVE;
  }
  if (armed || state == GateState::AUTH_PENDING || state == GateState::ARMED ||
      state == GateState::COOLDOWN) {
    return OtaSafeState::ACCESS_SESSION_ACTIVE;
  }
  return OtaSafeState::SAFE;
}
