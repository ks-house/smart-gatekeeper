#pragma once

#include <cstdint>

namespace sgk {

// One allocator per Target boot, shared by every access event producer.
// The adapter must serialize next()/advance() with its protocol task mutex.
// Never reset on session completion, queue drain, reconnect, or MQTT begin().
class AccessEventSequence {
 public:
  uint64_t next() {
    if (last_ == UINT64_MAX) return 0;  // Exhaustion must not reuse an identity.
    return ++last_;
  }
  void advance(uint64_t used) {
    if (used > last_) last_ = used;
  }

 private:
  uint64_t last_ = 0;
};

}  // namespace sgk
