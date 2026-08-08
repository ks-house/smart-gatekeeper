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
  OtaHealthPolicy(uint32_t stable_ms, uint32_t timeout_ms)
      : stable_ms_(stable_ms), timeout_ms_(timeout_ms) {}

  void begin(uint32_t now_ms) {
    started_ms_ = now_ms;
    healthy_since_ms_ = 0;
    healthy_active_ = false;
  }

  OtaHealthDecision update(uint32_t now_ms, bool all_predicates_healthy) {
    if (!all_predicates_healthy) {
      healthy_active_ = false;
      healthy_since_ms_ = 0;
    } else if (!healthy_active_) {
      healthy_active_ = true;
      healthy_since_ms_ = now_ms;
    } else if (now_ms - healthy_since_ms_ >= stable_ms_) {
      return OtaHealthDecision::kMarkValid;
    }
    if (now_ms - started_ms_ >= timeout_ms_) {
      return OtaHealthDecision::kRollback;
    }
    return OtaHealthDecision::kWait;
  }

 private:
  uint32_t stable_ms_ = 0;
  uint32_t timeout_ms_ = 0;
  uint32_t started_ms_ = 0;
  uint32_t healthy_since_ms_ = 0;
  bool healthy_active_ = false;
};

}  // namespace sgk
