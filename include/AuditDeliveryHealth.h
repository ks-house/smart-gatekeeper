#pragma once

#include <cstdint>
#include <cstring>

#include "OfflineEventQueue.h"

namespace sgk {

// Advisory observation, not an event timestamp or authenticated access verdict.
// Old-boot monotonic event time must never be subtracted from current uptime.
class AuditDeliveryHealth {
 public:
  void observe(const CanonicalEvent* head, uint64_t now_ms) {
    if (head == nullptr) {
      pending_ = false;
      attempts_ = 0;
      return;
    }
    if (!pending_ || std::strncmp(event_id_, head->event_id, sizeof(event_id_)) != 0 ||
        sequence_ != head->sequence || boot_count_ != head->boot_count) {
      pending_ = true;
      std::memcpy(event_id_, head->event_id, sizeof(event_id_));
      sequence_ = head->sequence;
      boot_count_ = head->boot_count;
      observed_ms_ = now_ms;
      attempts_ = 0;
    }
  }
  void noteAttempt(const CanonicalEvent& head, uint64_t now_ms) {
    observe(&head, now_ms);
    if (attempts_ != UINT32_MAX) ++attempts_;
  }
  uint32_t waitMs(uint64_t now_ms) const {
    if (!pending_ || now_ms < observed_ms_) return 0;
    const uint64_t elapsed = now_ms - observed_ms_;
    return elapsed > UINT32_MAX ? UINT32_MAX : static_cast<uint32_t>(elapsed);
  }
  uint32_t attempts() const { return attempts_; }
  bool stalled(uint64_t now_ms) const {
    return pending_ && waitMs(now_ms) >= 15000;
  }

 private:
  bool pending_ = false;
  char event_id_[37]{};
  uint64_t sequence_ = 0;
  uint32_t boot_count_ = 0;
  uint64_t observed_ms_ = 0;
  uint32_t attempts_ = 0;
};

}  // namespace sgk
