#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include "SensorSessionDiagnostics.h"

namespace sgk {

enum class PassagePulseSource : uint8_t { kNone, kSensor, kLocalManual, kRemoteManual };
// Unsigned, boot-local evidence only. Never consulted by the admission policy.
enum class RearmEdgeKind : uint8_t { kBlocked = 1, kStreakReset = 2, kCleared = 3 };
enum class RearmEdgeReason : uint8_t { kPulse = 1, kInvalid = 2, kNear = 3, kBand = 4, kClear = 5 };
struct RearmEdge {
  uint32_t at_ms = 0;
  RearmEdgeKind kind = RearmEdgeKind::kBlocked;
  RearmEdgeReason reason = RearmEdgeReason::kPulse;
  uint8_t prior_clear_samples = 0;
};
struct RearmHistory {
  static constexpr size_t kCapacity = 4;
  std::array<RearmEdge, kCapacity> edges{};  // oldest first
  uint32_t sequence = 0;  // saturates; no fabricated continuity after overflow
  uint32_t last_clear_ms = 0;
  uint8_t count = 0;
  bool has_clear = false;
  void record(uint32_t now, RearmEdgeKind kind, RearmEdgeReason reason, uint8_t prior) {
    if (kind == RearmEdgeKind::kCleared) { has_clear = true; last_clear_ms = now; }
    if (sequence == UINT32_MAX) return;
    ++sequence;
    if (count == kCapacity) {
      for (size_t i = 1; i < kCapacity; ++i) edges[i - 1] = edges[i];
    } else { ++count; }
    edges[count - 1] = {now, kind, reason, prior};
  }
};
inline const char* passagePulseSourceName(PassagePulseSource source) {
  switch (source) {
    case PassagePulseSource::kSensor: return "SENSOR";
    case PassagePulseSource::kLocalManual: return "LOCAL_MANUAL";
    case PassagePulseSource::kRemoteManual: return "REMOTE_MANUAL";
    default: return "NONE";
  }
}

// A new proof may renew readiness, but one occupied sensor episode gets one
// automatic pulse. Missing/invalid echoes are never evidence of clearance.
class PassageRearmPolicy {
 public:
  void notePulse(uint32_t now_ms = 0,
                 PassagePulseSource source = PassagePulseSource::kNone) {
    if (!blocked_) {
      blocked_since_ms_ = now_ms;
      history_.record(now_ms, RearmEdgeKind::kBlocked, RearmEdgeReason::kPulse, 0);
    } else if (clear_samples_ > 0) {
      history_.record(now_ms, RearmEdgeKind::kStreakReset, RearmEdgeReason::kPulse, clear_samples_);
    }
    blocked_ = true;
    clear_samples_ = 0;
    last_pulse_ms_ = now_ms;
    pulse_source_ = source;
  }
  void observe(bool valid_clear, uint32_t now_ms = 0,
               RearmEdgeReason reset_reason = RearmEdgeReason::kInvalid) {
    if (!blocked_) return;
    if (!valid_clear && clear_samples_ > 0)
      history_.record(now_ms, RearmEdgeKind::kStreakReset, reset_reason, clear_samples_);
    clear_samples_ = valid_clear ? clear_samples_ + 1 : 0;
    if (clear_samples_ >= 3) {
      history_.record(now_ms, RearmEdgeKind::kCleared, RearmEdgeReason::kClear, 3);
      blocked_ = false;
      clear_samples_ = 0;
    }
  }
  bool blocked() const { return blocked_; }
  uint32_t blockedAgeMs(uint32_t now_ms) const {
    return blocked_ ? now_ms - blocked_since_ms_ : 0;
  }
  uint32_t blockedSinceMs() const { return blocked_since_ms_; }
  uint32_t lastPulseMs() const { return last_pulse_ms_; }
  uint8_t clearSamples() const { return clear_samples_; }
  PassagePulseSource pulseSource() const { return pulse_source_; }
  const RearmHistory& history() const { return history_; }
  void observeDistance(uint16_t raw_mm, uint16_t threshold_mm, uint32_t now_ms = 0) {
    if (raw_mm == kNoSensorMeasurement) {
      if (unknown_samples_ < 10) ++unknown_samples_;
      state_ = unknown_samples_ >= 10 ? SensorClearanceState::kFault : SensorClearanceState::kUnknown;
      observe(false, now_ms, RearmEdgeReason::kInvalid);
      return;
    }
    unknown_samples_ = 0;
    const bool clear = raw_mm > threshold_mm + 100;
    state_ = clear ? SensorClearanceState::kClear : SensorClearanceState::kOccupied;
    observe(clear, now_ms, raw_mm <= threshold_mm ? RearmEdgeReason::kNear : RearmEdgeReason::kBand);
  }
  SensorClearanceState state() const { return state_; }

 private:
  RearmHistory history_;
  bool blocked_ = false;
  uint8_t clear_samples_ = 0;
  uint8_t unknown_samples_ = 0;
  SensorClearanceState state_ = SensorClearanceState::kUnknown;
  uint32_t blocked_since_ms_ = 0;
  uint32_t last_pulse_ms_ = 0;
  PassagePulseSource pulse_source_ = PassagePulseSource::kNone;
};

// Advisory radio hint only: GATT proof/ACL/FSM remain the authorization path.
// Each eligible IDLE window has a new boot-random-seeded epoch. One second of
// IDLE gives queued MQTT/OTA work a chance before continuous presence re-arms.
// An automatic attempt without confirmed clearance earns a longer quiet
// interval. The same admission is checked at the proof commit, so a missing
// hint / eager phone cannot keep renewing ARMED behind a false radio hint.
class PresenceReadyPolicy {
 public:
  static constexpr uint32_t kIdleYieldMs = 1000;
  static constexpr uint32_t kRetryQuietMs = 30000;
  static constexpr uint32_t kBlockedArmMs = 5000;
  explicit PresenceReadyPolicy(uint32_t seed) : epoch_(seed) {}
  bool update(uint32_t now, bool idle) {
    if (!idle) { waiting_ = false; ready_ = false; return false; }
    if (!waiting_) { waiting_ = true; since_ = now; }
    if (!ready_ && now - since_ >= quietMs()) { ++epoch_; ready_ = true; }
    return ready_;
  }
  void noteAutomaticArm() { retry_quiet_ = true; waiting_ = ready_ = false; }
  void noteConfirmedClearance() { retry_quiet_ = false; }
  uint32_t remainingMs(uint32_t now) const {
    if (!waiting_) return quietMs();
    const uint32_t elapsed = now - since_;
    return elapsed >= quietMs() ? 0 : quietMs() - elapsed;
  }
  static uint32_t armDurationMs(uint32_t configured_ms, bool blocked) {
    return blocked && configured_ms > kBlockedArmMs ? kBlockedArmMs : configured_ms;
  }
  bool ready() const { return ready_; }
  uint32_t epoch() const { return epoch_; }
 private:
  uint32_t epoch_;
  uint32_t since_ = 0;
  bool waiting_ = false;
  bool ready_ = false;
  bool retry_quiet_ = false;
  uint32_t quietMs() const { return retry_quiet_ ? kRetryQuietMs : kIdleYieldMs; }
};

struct PassageRearmTelemetry {
  RearmHistory history;
  bool auth_ready = false;
  bool pulse_ready = false;
  const char* auth_reason = "BOOTING";
  const char* pulse_reason = "AUTH_REQUIRED";
  uint32_t retry_after_ms = 0;
  uint32_t blocked_since_ms = 0;
  uint32_t blocked_age_ms = 0;
  uint32_t last_pulse_ms = 0;
  uint8_t clear_samples = 0;
  PassagePulseSource pulse_source = PassagePulseSource::kNone;
};

}  // namespace sgk
