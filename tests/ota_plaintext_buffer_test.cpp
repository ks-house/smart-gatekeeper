#include "OtaPlaintextBuffer.h"

#include <cassert>
#include <cstring>

namespace {
constexpr size_t kCapacity = 4096 + 15;
struct ObservedAllocation {
  static inline bool fail = false;
  static inline unsigned allocated = 0;
  static inline unsigned released = 0;
  static uint8_t* allocate(size_t size) {
    assert(size == kCapacity);
    if (fail) return nullptr;
    ++allocated;
    auto* data = new uint8_t[size];
    std::memset(data, 0xa5, size);
    return data;
  }
  static void release(uint8_t* data) {
    for (size_t i = 0; i < kCapacity; ++i) assert(data[i] == 0);
    ++released;
    delete[] data;
  }
};
using Buffer = sgk::OtaPlaintextBuffer<kCapacity, ObservedAllocation>;
static_assert(sizeof(Buffer) == sizeof(uint8_t*));
static_assert(Buffer::size() == kCapacity);
}  // namespace

int main() {
  Buffer buffer;
  assert(!buffer && buffer.data() == nullptr);
  assert(ObservedAllocation::allocated == 0);
  buffer.release();  // Cleanup before initialization is harmless.
  ObservedAllocation::fail = true;
  assert(!buffer.allocate() && !buffer);
  assert(ObservedAllocation::allocated == 0);
  ObservedAllocation::fail = false;
  for (unsigned attempt = 0; attempt < 100; ++attempt) {
    assert(buffer.allocate());
    for (size_t i = 0; i < kCapacity; ++i) assert(buffer.data()[i] == 0);
    std::memset(buffer.data(), 0x7e, buffer.size());
    const auto* owned = buffer.data();
    assert(!buffer.allocate());  // Never overwrite a live write's ownership.
    assert(buffer.data() == owned && buffer.data()[4096] == 0x7e);
    buffer.clear();
    assert(buffer.data() == owned);
    for (size_t i = 0; i < kCapacity; ++i) assert(buffer.data()[i] == 0);
    std::memset(buffer.data(), 0x5b, buffer.size());
    buffer.release();  // Fake deallocator verifies erasure before deletion.
    buffer.release();
    assert(!buffer);
    assert(ObservedAllocation::allocated == ObservedAllocation::released);
  }
  const auto earlyReturn = [] {
    Buffer aborted;
    assert(aborted.allocate());
    std::memset(aborted.data(), 0x4c, aborted.size());
  };
  earlyReturn();
  assert(ObservedAllocation::allocated == ObservedAllocation::released);
  sgk::OtaPlaintextBuffer<kCapacity> production;
  assert(production.allocate());
  production.data()[kCapacity - 1] = 0xff;
  production.release();
  assert(!production);
}
