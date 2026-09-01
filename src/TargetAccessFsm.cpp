#include "TargetAccessFsm.h"

namespace sgk {

TargetAccessFsm::TargetAccessFsm(RelayDriveFn relay_drive,
                                 EventEmitFn event_emit)
    : relay_drive_(relay_drive), event_emit_(event_emit) {}

void TargetAccessFsm::begin(uint32_t now_ms) {
  state_ = GateState::IDLE;
  is_armed_ = false;
  relay_on_ = false;
  state_start_ms_ = now_ms;
  setRelay(false);
}

void TargetAccessFsm::setRelay(bool on) {
  relay_on_ = on;
  if (relay_drive_ != nullptr) {
    relay_drive_(on);
  }
}

OtaSafeState TargetAccessFsm::otaSafeState() const {
  return classifyOtaSafeState(state_, is_armed_, relay_on_);
}

void TargetAccessFsm::completeRelayHold(uint32_t now_ms,
                                        uint32_t cooldown_duration_ms,
                                        bool failsafe) {
  if (state_ != GateState::RELAY_HOLD || !relay_on_) {
    return;
  }
  setRelay(false);
  is_armed_ = false;
  cooldown_duration_ms_ = cooldown_duration_ms;
  state_ = GateState::COOLDOWN;
  state_start_ms_ = now_ms;
  if (event_emit_ != nullptr) {
    event_emit_(failsafe ? "door_close_failsafe" : "door_close",
                failsafe ? "Relay forced off after cutoff grace"
                         : "Relay hold timer completed normally");
    event_emit_(failsafe ? "session_terminated_failsafe"
                         : "session_completed",
                failsafe ? "Access session terminated via relay failsafe"
                         : "Access session completed successfully");
  }
}

void TargetAccessFsm::tick(uint32_t now_ms) {
  switch (state_) {
    case GateState::IDLE:
      break;

    case GateState::AUTH_PENDING:
      if (now_ms - state_start_ms_ >= pre_arm_duration_ms_) {
        state_ = GateState::IDLE;
        state_start_ms_ = now_ms;
        if (event_emit_ != nullptr) {
          event_emit_("auth_pending_timeout", "AUTH_PENDING timeout, returning to IDLE");
          event_emit_("session_terminated", "Session terminated due to pending timeout");
        }
      }
      break;

    case GateState::ARMED:
      if (is_armed_ &&
          (now_ms - pre_arm_start_ms_ >= pre_arm_duration_ms_)) {
        is_armed_ = false;
        state_ = GateState::IDLE;
        state_start_ms_ = now_ms;
        if (event_emit_ != nullptr) {
          event_emit_("arm_expired", "Pre-arm timeout, returning to IDLE");
          event_emit_("session_terminated", "Session terminated due to arm timeout");
        }
      }
      break;

    case GateState::RELAY_HOLD:
      if (now_ms - state_start_ms_ >= hold_duration_ms_) {
        completeRelayHold(now_ms, cooldown_duration_ms_, false);
      }
      break;

    case GateState::COOLDOWN:
      if (now_ms - state_start_ms_ >= cooldown_duration_ms_) {
        state_ = GateState::IDLE;
        state_start_ms_ = now_ms;
        if (event_emit_ != nullptr) {
          event_emit_("gate_idle", "Cooldown complete, ready for next access");
        }
      }
      break;
  }
}

bool TargetAccessFsm::handleAuthPending(uint32_t now_ms, uint32_t timeout_ms) {
  if (state_ != GateState::IDLE || relay_on_) {
    return false;
  }
  is_armed_ = false;
  state_ = GateState::AUTH_PENDING;
  state_start_ms_ = now_ms;
  pre_arm_duration_ms_ = timeout_ms;
  if (event_emit_ != nullptr) {
    event_emit_("auth_pending", "AUTH_PENDING verification in progress");
  }
  return true;
}

bool TargetAccessFsm::handleAuthSuccess(uint32_t now_ms,
                                        uint32_t arm_duration_ms,
                                        uint32_t cooldown_duration_ms) {
  // Local GATT auth proof success requires AUTH_PENDING state and arms target for sensor passage
  if (state_ != GateState::AUTH_PENDING || relay_on_) {
    if (event_emit_ != nullptr) {
      event_emit_("auth_open_rejected", "Target is not in AUTH_PENDING state");
    }
    return false;
  }

  is_armed_ = true;
  pre_arm_duration_ms_ = arm_duration_ms;
  pre_arm_start_ms_ = now_ms;
  cooldown_duration_ms_ = cooldown_duration_ms;
  state_ = GateState::ARMED;
  state_start_ms_ = now_ms;

  if (event_emit_ != nullptr) {
    event_emit_("auth_verified_armed", "Proof Verified: Target Armed for passage sensor");
  }
  return true;
}

bool TargetAccessFsm::handleLocalManualOpen(uint32_t now_ms,
                                            uint32_t hold_duration_ms,
                                            uint32_t cooldown_duration_ms) {
  if (state_ != GateState::AUTH_PENDING || relay_on_) {
    if (event_emit_ != nullptr) {
      event_emit_("local_manual_open_rejected",
                  "authenticated local manual open rejected");
    }
    return false;
  }
  is_armed_ = false;
  hold_duration_ms_ = hold_duration_ms;
  cooldown_duration_ms_ = cooldown_duration_ms;
  state_ = GateState::RELAY_HOLD;
  state_start_ms_ = now_ms;
  setRelay(true);

  if (event_emit_ != nullptr) {
    event_emit_("relay_on_local_manual",
                "Access Granted via authenticated local GATT manual open");
  }
  return true;
}

bool TargetAccessFsm::handleAuthAbort(uint32_t now_ms, const char* reason) {
  if (state_ == GateState::AUTH_PENDING) {
    state_ = GateState::IDLE;
    is_armed_ = false;
    state_start_ms_ = now_ms;
    if (event_emit_ != nullptr) {
      event_emit_(reason != nullptr ? reason : "auth_aborted",
                  "Auth pending session aborted/disconnected");
    }
    return true;
  }
  return false;
}

bool TargetAccessFsm::handleManualRemoteOpen(uint32_t now_ms,
                                             uint32_t hold_duration_ms,
                                             uint32_t cooldown_duration_ms) {
  if (state_ != GateState::IDLE || relay_on_) {
    if (event_emit_ != nullptr) {
      event_emit_("manual_open_rejected_not_idle",
                  "manual open rejected: Target is not IDLE");
    }
    return false;
  }

  is_armed_ = false;
  hold_duration_ms_ = hold_duration_ms;
  cooldown_duration_ms_ = cooldown_duration_ms;
  state_ = GateState::RELAY_HOLD;
  state_start_ms_ = now_ms;
  setRelay(true);

  if (event_emit_ != nullptr) {
    event_emit_("relay_on_manual", "Access Granted via MQTT manual remote");
  }
  return true;
}

bool TargetAccessFsm::handlePreArm(uint32_t now_ms, uint32_t pre_arm_duration_ms) {
  if (state_ != GateState::IDLE || relay_on_) {
    return false;
  }
  is_armed_ = true;
  pre_arm_duration_ms_ = pre_arm_duration_ms;
  pre_arm_start_ms_ = now_ms;
  state_ = GateState::ARMED;
  state_start_ms_ = now_ms;

  if (event_emit_ != nullptr) {
    event_emit_("pre_armed", "Pre-armed via MQTT");
  }
  return true;
}

bool TargetAccessFsm::handleSensorTrigger(uint32_t now_ms,
                                           uint32_t hold_duration_ms,
                                           uint32_t cooldown_duration_ms) {
  if (state_ != GateState::ARMED || !is_armed_) {
    return false;
  }

  is_armed_ = false;
  hold_duration_ms_ = hold_duration_ms;
  cooldown_duration_ms_ = cooldown_duration_ms;
  state_ = GateState::RELAY_HOLD;
  state_start_ms_ = now_ms;

  if (event_emit_ != nullptr) {
    event_emit_("sensor_detected", "Ultrasonic passage sensor triggered");
  }

  setRelay(true);

  if (event_emit_ != nullptr) {
    event_emit_("relay_on_sensor", "Access Granted via MQTT Pre-arm + Ultrasonic");
  }
  return true;
}

void TargetAccessFsm::handleRelayTimerOff(uint32_t now_ms,
                                          uint32_t cooldown_duration_ms) {
  completeRelayHold(now_ms, cooldown_duration_ms, false);
}

void TargetAccessFsm::handleRelayFailsafeOff(uint32_t now_ms,
                                             uint32_t cooldown_duration_ms) {
  completeRelayHold(now_ms, cooldown_duration_ms, true);
}

void TargetAccessFsm::cleanupToIdle(uint32_t now_ms) {
  setRelay(false);
  is_armed_ = false;
  state_ = GateState::IDLE;
  state_start_ms_ = now_ms;
}

}  // namespace sgk
