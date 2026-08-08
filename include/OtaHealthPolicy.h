#pragma once

#include <cstdint>

namespace sgk {

enum class OtaHealthDecision : uint8_t {
  kWait = 0,
  kMarkValid,
  kRollback,
};

class OtaHealthPolicy {
 public:
  OtaHealthPolicy(uint32_t stable_ms, uint32_t timeout_ms,
                  uint32_t max_sample_gap_ms = 1000)
      : stable_ms_(stable_ms), timeout_ms_(timeout_ms),
        max_sample_gap_ms_(max_sample_gap_ms) {}

  void begin(uint32_t now_ms) {
    started_ms_ = now_ms;
    healthy_since_ms_ = 0;
    healthy_active_ = false;
    sample_seen_ = false;
    last_sample_ms_ = 0;
  }

  OtaHealthDecision update(uint32_t now_ms, bool all_predicates_healthy) {
    const uint32_t elapsed_ms = now_ms - started_ms_;
    // A strictly exceeded deadline dominates every later healthy sample.
    if (elapsed_ms > timeout_ms_) return OtaHealthDecision::kRollback;
    if (sample_seen_ && now_ms - last_sample_ms_ > max_sample_gap_ms_) {
      healthy_active_ = false;
      healthy_since_ms_ = 0;
    }
    sample_seen_ = true;
    last_sample_ms_ = now_ms;
    if (!all_predicates_healthy) {
      healthy_active_ = false;
      healthy_since_ms_ = 0;
    } else if (!healthy_active_) {
      healthy_active_ = true;
      healthy_since_ms_ = now_ms;
    } else if (now_ms - healthy_since_ms_ >= stable_ms_) {
      return OtaHealthDecision::kMarkValid;
    }
    // Equality is the last admissible instant: a stable interval that
    // completes exactly here is valid; every other state rolls back.
    if (elapsed_ms >= timeout_ms_) {
      return OtaHealthDecision::kRollback;
    }
    return OtaHealthDecision::kWait;
  }

 private:
  uint32_t stable_ms_ = 0;
  uint32_t timeout_ms_ = 0;
  uint32_t max_sample_gap_ms_ = 0;
  uint32_t started_ms_ = 0;
  uint32_t healthy_since_ms_ = 0;
  uint32_t last_sample_ms_ = 0;
  bool healthy_active_ = false;
  bool sample_seen_ = false;
};

}  // namespace sgk
