#include "SensorSessionDiagnostics.h"
#include "OfflineEventQueue.h"

#include <cstring>

namespace sgk {

void SensorSummaryQueue::begin() {
  if (storage_ == nullptr) return;
  for (uint8_t slot = 0; slot < 2; ++slot) {
    Journal candidate{};
    const size_t read = storage_->read(slot, &candidate, sizeof(candidate));
    if (read == 0) continue;  // A new namespace has no journal yet.
    if (read != sizeof(candidate) ||
        candidate.magic != 0x53475331 || candidate.count > kCapacity ||
        candidate.generation == 0 ||
        candidate.crc32 != OfflineEventQueue::computeCrc32(
            reinterpret_cast<const uint8_t*>(&candidate), offsetof(Journal, crc32))) {
      if (invalid_journals_ != UINT32_MAX) ++invalid_journals_;
      continue;
    }
    if (candidate.generation > journal_.generation) {
      journal_ = candidate;
      active_slot_ = slot;
    }
  }
}

bool SensorSummaryQueue::commit(Journal candidate) {
  if (journal_.generation == UINT32_MAX) return false;
  candidate.generation = journal_.generation + 1;
  candidate.crc32 = OfflineEventQueue::computeCrc32(
      reinterpret_cast<const uint8_t*>(&candidate), offsetof(Journal, crc32));
  const uint8_t slot = active_slot_ ^ 1;
  if (storage_ == nullptr || !storage_->write(slot, &candidate, sizeof(candidate))) {
    if (persistence_failures_ != UINT32_MAX) ++persistence_failures_;
    return false;
  }
  journal_ = candidate;
  active_slot_ = slot;
  return true;
}

bool SensorSummaryQueue::push(const SensorSummaryRecord& record) {
  Journal next = journal_;
  if (next.count == kCapacity) {
    if (next.dropped != UINT32_MAX) ++next.dropped;
    (void)commit(next);
    return false;
  }
  next.records[next.count++] = record;
  return commit(next);
}

const SensorSummaryRecord* SensorSummaryQueue::front() const {
  return journal_.count == 0 ? nullptr : &journal_.records[0];
}

bool SensorSummaryQueue::pop() {
  if (journal_.count == 0) return false;
  Journal next = journal_;
  for (size_t i = 1; i < next.count; ++i) next.records[i - 1] = next.records[i];
  next.records[--next.count] = {};
  return commit(next);
}

}  // namespace sgk
