#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include "GattProtocol.h"

namespace sgk {

struct BufferedEvent {
  Event event{};
  uint32_t queued_at_ms = 0;
};

class OfflineEventQueue {
 public:
  static constexpr size_t kCapacity = 32;

  bool push(const Event& event, uint32_t now_ms);
  bool pop(Event* event_out);
  bool isEmpty() const { return count_ == 0; }
  size_t size() const { return count_; }
  void clear() {
    head_ = 0;
    tail_ = 0;
    count_ = 0;
  }

 private:
  std::array<BufferedEvent, kCapacity> buffer_{};
  size_t head_ = 0;
  size_t tail_ = 0;
  size_t count_ = 0;
};

}  // namespace sgk
