#pragma once

#include <cstdint>
#include "SensorSessionDiagnostics.h"

namespace sgk {

// A new proof may renew readiness, but one occupied sensor episode gets one
// automatic pulse. Missing/invalid echoes are never evidence of clearance.
class PassageRearmPolicy {
 public:
  void notePulse() { blocked_ = true; clear_samples_ = 0; }
  void observe(bool valid_clear) {
    if (!blocked_) return;
    clear_samples_ = valid_clear ? clear_samples_ + 1 : 0;
    if (clear_samples_ >= 3) {
      blocked_ = false;
      clear_samples_ = 0;
    }
  }
  bool blocked() const { return blocked_; }
  void observeDistance(uint16_t raw_mm, uint16_t threshold_mm) {
    if (raw_mm == kNoSensorMeasurement) {
      if (unknown_samples_ < 10) ++unknown_samples_;
      state_ = unknown_samples_ >= 10 ? SensorClearanceState::kFault : SensorClearanceState::kUnknown;
      observe(false);
      return;
    }
    unknown_samples_ = 0;
    const bool clear = raw_mm > threshold_mm + 100;
    state_ = clear ? SensorClearanceState::kClear : SensorClearanceState::kOccupied;
    observe(clear);
  }
  SensorClearanceState state() const { return state_; }

 private:
  bool blocked_ = false;
  uint8_t clear_samples_ = 0;
  uint8_t unknown_samples_ = 0;
  SensorClearanceState state_ = SensorClearanceState::kUnknown;
};

// Advisory radio hint only: GATT proof/ACL/FSM remain the authorization path.
// Each eligible IDLE window has a new boot-random-seeded epoch. One second of
// IDLE gives queued MQTT/OTA work a chance before continuous presence re-arms.
class PresenceReadyPolicy {
 public:
  explicit PresenceReadyPolicy(uint32_t seed) : epoch_(seed) {}
  bool update(uint32_t now, bool idle) {
    if (!idle) { waiting_ = false; ready_ = false; return false; }
    if (!waiting_) { waiting_ = true; since_ = now; }
    if (!ready_ && now - since_ >= 1000) { ++epoch_; ready_ = true; }
    return ready_;
  }
  bool ready() const { return ready_; }
  uint32_t epoch() const { return epoch_; }
 private:
  uint32_t epoch_;
  uint32_t since_ = 0;
  bool waiting_ = false;
  bool ready_ = false;
};

}  // namespace sgk
