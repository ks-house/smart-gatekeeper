#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace sgk {

// Legacy text is best-effort telemetry, never canonical audit. Keeping its
// compact eight-record RAM budget separate prevents repeated FSM text from
// displacing the signed access chain during a terminal checkpoint.
struct LegacyEvent {
  uint32_t monotonic_ms = 0;
  char event_type[32] = {};
  char detail[64] = {};
};

class LegacyEventQueue {
 public:
  static constexpr size_t kCapacity = 8;
  bool push(const LegacyEvent& event) {
    if (count_ == records_.size()) {
      if (dropped_ != UINT32_MAX) ++dropped_;
      return false;
    }
    records_[(head_ + count_) % records_.size()] = event;
    ++count_;
    return true;
  }
  bool peek(LegacyEvent* event) const {
    if (event == nullptr || count_ == 0) return false;
    *event = records_[head_];
    return true;
  }
  void pop() {
    if (count_ == 0) return;
    records_[head_] = {};
    head_ = (head_ + 1) % records_.size();
    --count_;
  }
  size_t size() const { return count_; }
  uint32_t dropped() const { return dropped_; }
  void clear() { records_ = {}; head_ = 0; count_ = 0; dropped_ = 0; }

 private:
  std::array<LegacyEvent, kCapacity> records_{};
  size_t head_ = 0;
  size_t count_ = 0;
  uint32_t dropped_ = 0;
};

static_assert(sizeof(LegacyEvent) * LegacyEventQueue::kCapacity <= 800,
              "best-effort text telemetry exceeds its RAM budget");

}  // namespace sgk
