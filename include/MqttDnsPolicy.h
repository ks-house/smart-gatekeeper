#pragma once

#include <cstdint>

namespace sgk {

enum class MqttDnsPoll : uint8_t {
  kIdle,
  kPending,
  kReady,
  kFailed,
  kTimedOut,
};

constexpr uint32_t nextMqttDnsGeneration(uint32_t current) {
  const uint32_t next = current + 1U;
  return next == 0 ? 1U : next;
}

// Allocation-free request lifecycle. The adapter holds its existing DNS mutex
// around this policy and the separate address. Copy a callback address only
// when complete() accepts that generation and the callback succeeded.
// All elapsed intervals must be observed within one uint32_t millis() wrap.
class MqttDnsPolicy {
 public:
  explicit MqttDnsPolicy(uint32_t timeout_ms) : timeout_ms_(timeout_ms) {}

  void reset() {
    invalidate();
    started_ms_ = 0;
    state_ = MqttDnsPoll::kIdle;
  }

  // The caller starts a resolver query only from kIdle. Repeated begin calls
  // cannot extend an outstanding deadline or discard a cached/terminal result.
  uint32_t begin(uint32_t now_ms) {
    if (state_ != MqttDnsPoll::kIdle) return generation_;
    invalidate();
    started_ms_ = now_ms;
    state_ = MqttDnsPoll::kPending;
    return generation_;
  }

  bool complete(uint32_t generation, bool success, uint32_t now_ms) {
    if (state_ != MqttDnsPoll::kPending || generation == 0 ||
        generation != generation_) return false;
    // A late callback cannot win a race against a delayed main-task poll.
    if (expired(now_ms)) {
      state_ = MqttDnsPoll::kTimedOut;
      return false;
    }
    state_ = success ? MqttDnsPoll::kReady : MqttDnsPoll::kFailed;
    return true;
  }

  MqttDnsPoll poll(uint32_t now_ms) {
    if (state_ == MqttDnsPoll::kPending && expired(now_ms)) {
      state_ = MqttDnsPoll::kTimedOut;
    }
    const MqttDnsPoll observed = state_;
    if (observed == MqttDnsPoll::kFailed ||
        observed == MqttDnsPoll::kTimedOut) {
      // Consume exactly once, including synchronous immediate resolver errors.
      reset();
    }
    return observed;
  }

 private:
  bool expired(uint32_t now_ms) const {
    return now_ms - started_ms_ >= timeout_ms_;
  }
  void invalidate() { generation_ = nextMqttDnsGeneration(generation_); }

  uint32_t timeout_ms_;
  uint32_t generation_ = 0;
  uint32_t started_ms_ = 0;
  MqttDnsPoll state_ = MqttDnsPoll::kIdle;
};

}  // namespace sgk
