#pragma once

#include <cstddef>
#include <cstdint>
#include <new>

namespace sgk {

struct OtaBufferAllocation {
  static uint8_t* allocate(size_t size) {
    return new (std::nothrow) uint8_t[size];
  }
  static void release(uint8_t* data) { delete[] data; }
};

// Allocate once before an inactive-slot write, never per packet or at boot.
// Zero before free, including abort/early return. The allocator seam exercises
// exhaustion and erasure in host tests without changing production ownership.
template <size_t Capacity, typename Allocation = OtaBufferAllocation>
class OtaPlaintextBuffer {
 public:
  OtaPlaintextBuffer() = default;
  OtaPlaintextBuffer(const OtaPlaintextBuffer&) = delete;
  OtaPlaintextBuffer& operator=(const OtaPlaintextBuffer&) = delete;
  ~OtaPlaintextBuffer() { release(); }

  bool allocate() {
    if (data_ != nullptr) return false;
    data_ = Allocation::allocate(Capacity);
    if (data_ == nullptr) return false;
    clear();
    return true;
  }
  uint8_t* data() { return data_; }
  static constexpr size_t size() { return Capacity; }
  explicit operator bool() const { return data_ != nullptr; }

  void clear() {
    if (data_ == nullptr) return;
    volatile uint8_t* cursor = data_;
    for (size_t i = 0; i < Capacity; ++i) cursor[i] = 0;
  }
  void release() {
    if (data_ == nullptr) return;
    clear();
    Allocation::release(data_);
    data_ = nullptr;
  }

 private:
  uint8_t* data_ = nullptr;
};

}  // namespace sgk
