#include "OfflineEventQueue.h"

namespace sgk {

bool OfflineEventQueue::push(const Event& event, uint32_t now_ms) {
  if (count_ >= kCapacity) {
    // Queue full: discard oldest event to maintain bounded memory
    head_ = (head_ + 1) % kCapacity;
    --count_;
  }
  buffer_[tail_] = {event, now_ms};
  tail_ = (tail_ + 1) % kCapacity;
  ++count_;
  return true;
}

bool OfflineEventQueue::pop(Event* event_out) {
  if (count_ == 0 || event_out == nullptr) return false;
  *event_out = buffer_[head_].event;
  head_ = (head_ + 1) % kCapacity;
  --count_;
  return true;
}

}  // namespace sgk
