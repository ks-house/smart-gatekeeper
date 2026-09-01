#pragma once

#include <cstdint>
#include "GattProtocol.h"
#include "TargetState.h"

namespace sgk {

class TargetAccessFsm {
 public:
  using RelayDriveFn = void (*)(bool on);
  using EventEmitFn = void (*)(const char* event, const char* message);

  TargetAccessFsm(RelayDriveFn relay_drive = nullptr,
                  EventEmitFn event_emit = nullptr);

  void begin(uint32_t now_ms);
  void tick(uint32_t now_ms);

  GateState state() const { return state_; }
  bool isArmed() const { return is_armed_; }
  bool isRelayOn() const { return relay_on_; }

  OtaSafeState otaSafeState() const;

  // Only a fresh IDLE/relay-OFF Target may enter AUTH_PENDING. Once a proof
  // has armed an access session, every new ClientHello remains rejected until
  // that lifecycle reaches its terminal cooldown and returns to IDLE.
  bool handleAuthPending(uint32_t now_ms, uint32_t timeout_ms = 5000);

  // Local GATT Auth Proof verification success transitions AUTH_PENDING -> ARMED (arms target for passage sensor).
  bool handleAuthSuccess(uint32_t now_ms, uint32_t arm_duration_ms = 60000,
                         uint32_t cooldown_duration_ms = 2000);

  // Authenticated local manual-open action: AUTH_PENDING -> RELAY_HOLD.
  bool handleLocalManualOpen(uint32_t now_ms,
                             uint32_t hold_duration_ms = 1000,
                             uint32_t cooldown_duration_ms = 2000);

  bool handleAuthAbort(uint32_t now_ms, const char* reason = "auth_aborted");

  // Manual remote trigger (MQTT): only allowed when IDLE.
  bool handleManualRemoteOpen(uint32_t now_ms,
                              uint32_t hold_duration_ms = 1000,
                              uint32_t cooldown_duration_ms = 2000);

  // Pre-arm activation (legacy MQTT pre-arm).
  bool handlePreArm(uint32_t now_ms, uint32_t pre_arm_duration_ms = 5000);

  // Ultrasonic sensor trigger when ARMED.
  bool handleSensorTrigger(uint32_t now_ms, uint32_t hold_duration_ms = 1000,
                           uint32_t cooldown_duration_ms = 2000);

  // Independent relay timeout / hardware failsafe transition to COOLDOWN.
  void handleRelayTimerOff(uint32_t now_ms,
                           uint32_t cooldown_duration_ms = 2000);
  void handleRelayFailsafeOff(uint32_t now_ms, uint32_t cooldown_duration_ms = 2000);

  // Called on session timeout, GATT disconnect, or reset cleanup.
  void cleanupToIdle(uint32_t now_ms);

  // Configurable thresholds
  void setPreArmDurationMs(uint32_t ms) { pre_arm_duration_ms_ = ms; }
  void setCooldownDurationMs(uint32_t ms) { default_cooldown_duration_ms_ = ms; }

 private:
  RelayDriveFn relay_drive_ = nullptr;
  EventEmitFn event_emit_ = nullptr;

  GateState state_ = GateState::IDLE;
  bool is_armed_ = false;
  bool relay_on_ = false;

  uint32_t state_start_ms_ = 0;
  uint32_t hold_duration_ms_ = 1000;
  uint32_t cooldown_duration_ms_ = 2000;
  uint32_t default_cooldown_duration_ms_ = 2000;
  uint32_t pre_arm_duration_ms_ = 5000;
  uint32_t pre_arm_start_ms_ = 0;

  void setRelay(bool on);
  void completeRelayHold(uint32_t now_ms, uint32_t cooldown_duration_ms,
                         bool failsafe);
};

}  // namespace sgk
