#pragma once

#include <cstdint>

namespace sgk {

// Bounds how long local ingress may suppress network/OTA servicing. A brief
// non-critical gap resumes those services immediately but does not mint a new
// lease; only a continuous quiet window or a verified action generation does.
class AccessCriticalLeasePolicy {
 public:
  AccessCriticalLeasePolicy(uint32_t hard_timeout_ms,
                            uint32_t quiet_rearm_ms)
      : hard_timeout_ms_(hard_timeout_ms),
        quiet_rearm_ms_(quiet_rearm_ms) {}

  bool expired(uint32_t now_ms, bool critical,
               uint32_t verified_action_generation,
               uint32_t timeout_ms = 0) {
    if (!critical) {
      if (epoch_active_) {
        if (!quiet_active_) {
          quiet_active_ = true;
          quiet_started_ms_ = now_ms;
        } else if (elapsed(now_ms, quiet_started_ms_) >= quiet_rearm_ms_) {
          epoch_active_ = false;
          quiet_active_ = false;
          generation_ = verified_action_generation;
        }
      }
      return false;
    }

    quiet_active_ = false;
    if (!epoch_active_ || generation_ != verified_action_generation) {
      epoch_active_ = true;
      epoch_started_ms_ = now_ms;
      generation_ = verified_action_generation;
      return false;
    }
    const uint32_t effective_timeout_ms =
        timeout_ms == 0 ? hard_timeout_ms_ : timeout_ms;
    return elapsed(now_ms, epoch_started_ms_) >= effective_timeout_ms;
  }

  bool epochActive() const { return epoch_active_; }
  uint32_t epochStartedMs() const { return epoch_started_ms_; }

 private:
  static uint32_t elapsed(uint32_t now_ms, uint32_t started_ms) {
    return now_ms - started_ms;
  }

  const uint32_t hard_timeout_ms_;
  const uint32_t quiet_rearm_ms_;
  bool epoch_active_ = false;
  bool quiet_active_ = false;
  uint32_t epoch_started_ms_ = 0;
  uint32_t quiet_started_ms_ = 0;
  uint32_t generation_ = 0;
};

}  // namespace sgk
