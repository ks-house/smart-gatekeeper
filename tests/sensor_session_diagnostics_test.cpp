#include "SensorSessionDiagnostics.h"
#include "PassageRearmPolicy.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>

class Storage final : public sgk::SensorSummaryStorage {
 public:
  std::array<std::vector<uint8_t>, 2> blobs;
  bool fail = false;
  size_t read(uint8_t slot, void* output, size_t capacity) override {
    if (blobs[slot].size() > capacity) return 0;
    std::memcpy(output, blobs[slot].data(), blobs[slot].size());
    return blobs[slot].size();
  }
  bool write(uint8_t slot, const void* bytes, size_t length) override {
    if (fail) return false;
    const auto* data = static_cast<const uint8_t*>(bytes);
    blobs[slot].assign(data, data + length);
    return true;
  }
};

int main() {
  sgk::PassageRearmPolicy clearance;
  clearance.notePulse();
  for (int i = 0; i < 10; ++i) clearance.observeDistance(sgk::kNoSensorMeasurement, 500);
  assert(clearance.state() == sgk::SensorClearanceState::kFault && clearance.blocked());
  clearance.observeDistance(400, 500);
  assert(clearance.state() == sgk::SensorClearanceState::kOccupied && clearance.blocked());
  for (int i = 0; i < 3; ++i) clearance.observeDistance(900, 500);
  assert(clearance.state() == sgk::SensorClearanceState::kClear && !clearance.blocked());

  sgk::SensorSessionTracker tracker;
  tracker.begin(1000, 500, true);
  tracker.observe(false, sgk::kNoSensorMeasurement, sgk::kNoSensorMeasurement,
                  true, sgk::SensorClearanceState::kUnknown);
  tracker.observe(true, sgk::kNoSensorMeasurement, sgk::kNoSensorMeasurement,
                  true, sgk::SensorClearanceState::kUnknown);
  tracker.observe(true, 300, sgk::kNoSensorMeasurement,
                  true, sgk::SensorClearanceState::kOccupied);
  tracker.observe(true, 900, 700, false, sgk::SensorClearanceState::kClear);
  assert(tracker.finish(61000, false, sgk::SensorClearanceState::kClear));
  assert(!tracker.finish(62000, false, sgk::SensorClearanceState::kClear));
  // Beginning the next authentication does not overwrite the frozen snapshot.
  tracker.begin(63000, 800, false);
  sgk::SensorSummaryRecord record;
  assert(!tracker.take(62000, &record.summary));
  assert(tracker.take(61000, &record.summary));
  assert(!tracker.take(61000, &record.summary));
  assert(record.summary.threshold_mm == 500);
  assert(record.summary.samples == 4 && record.summary.valid_samples == 2);
  assert(record.summary.timeouts == 1 && record.summary.invalid_samples == 1);
  assert(record.summary.in_range_samples == 1 && record.summary.blocked_samples == 3);
  assert(record.summary.clear_samples == 1);
  assert(record.summary.min_raw_mm == 300 && record.summary.max_raw_mm == 900);
  record.source_boot_count = 782;
  record.terminal_sequence = 9;
  std::strcpy(record.source_boot_id, "00112233445566778899aabbccddeeff");
  std::strcpy(record.session_id, "00000000-0000-4000-8000-000000000002");
  std::strcpy(record.key_id, "a1");
  std::array<uint8_t, 32> key{};
  for (size_t i = 0; i < key.size(); ++i) key[i] = static_cast<uint8_t>(i + 1);
  assert(sgk::deriveSensorSummaryMac(key, "target-1", record, record.tag));
  std::printf("tag=");
  for (auto b : record.tag) std::printf("%02x", b);
  std::puts("");
  auto tampered = record;
  ++tampered.summary.blocked_samples;
  uint8_t changed[16]{};
  assert(sgk::deriveSensorSummaryMac(key, "target-1", tampered, changed));
  assert(std::memcmp(record.tag, changed, 16) != 0);
  tampered.summary.blocked_samples = 5;
  assert(!sgk::deriveSensorSummaryMac(key, "target-1", tampered, changed));
  tampered = record;
  std::memset(tampered.key_id, 'a', sizeof(tampered.key_id));
  assert(!sgk::deriveSensorSummaryMac(key, "target-1", tampered, changed));
  tampered = record;
  tampered.session_id[14] = '1';
  assert(!sgk::deriveSensorSummaryMac(key, "target-1", tampered, changed));
  tampered = record;
  tampered.source_boot_id[0] = 'A';
  assert(!sgk::deriveSensorSummaryMac(key, "target-1", tampered, changed));

  // Unsigned millis wraps after 49 days; no session or MAC is lost at wrap.
  sgk::SensorSessionTracker wrapped;
  wrapped.begin(UINT32_MAX - 999, 500, false);
  assert(wrapped.finish(1000, false, sgk::SensorClearanceState::kUnknown));
  auto wrap_record = record;
  assert(wrapped.take(1000, &wrap_record.summary));
  assert(static_cast<uint32_t>(wrap_record.summary.ended_monotonic_ms -
                              wrap_record.summary.started_monotonic_ms) == 2000);
  assert(sgk::deriveSensorSummaryMac(key, "target-1", wrap_record, changed));

  // Multiple backpressured terminal windows stay distinct; the bounded ring
  // rejects a new window explicitly instead of replacing the oldest silently.
  sgk::SensorSessionTracker stalled;
  for (uint32_t i = 0; i < 4; ++i) {
    stalled.begin(i * 100, 500, false);
    assert(stalled.finish(i * 100 + 50, false, sgk::SensorClearanceState::kUnknown));
  }
  stalled.begin(400, 500, false);
  assert(!stalled.finish(450, false, sgk::SensorClearanceState::kUnknown));
  assert(stalled.pending() == 4 && stalled.dropped() == 1 && !stalled.active());
  sgk::SensorSessionSummary frozen;
  for (uint32_t i = 0; i < 4; ++i) {
    assert(stalled.take(i * 100 + 50, &frozen));
    assert(frozen.started_monotonic_ms == i * 100);
  }
  assert(!stalled.take(450, &frozen));

  Storage storage;
  sgk::SensorSummaryQueue queue(&storage);
  queue.begin();
  for (unsigned i = 0; i < 4; ++i) {
    record.terminal_sequence = 9 + i;
    assert(sgk::deriveSensorSummaryMac(key, "target-1", record, record.tag));
    assert(queue.push(record));
  }
  assert(!queue.push(record));
  assert(queue.size() == 4 && queue.dropped() == 1);
  sgk::SensorSummaryQueue restored(&storage);
  restored.begin();
  assert(restored.size() == 4 && restored.dropped() == 1);
  assert(restored.front()->terminal_sequence == 9);
  storage.fail = true;
  assert(!restored.pop());
  assert(restored.front()->terminal_sequence == 9 && restored.persistenceFailures() == 1);
  storage.fail = false;
  assert(restored.pop());
  sgk::SensorSummaryQueue afterAck(&storage);
  afterAck.begin();
  assert(afterAck.size() == 3 && afterAck.front()->terminal_sequence == 10);
  // Latest blob torn: previous committed generation remains readable. An old
  // head can replay, but Backend idempotency/exact receipt handles it safely.
  for (auto& blob : storage.blobs) {
    if (blob.size() >= 8 && blob[4] == 6) blob.resize(7);
  }
  sgk::SensorSummaryQueue afterTear(&storage);
  afterTear.begin();
  assert(afterTear.size() == 4 && afterTear.front()->terminal_sequence == 9);
  assert(afterTear.invalidJournals() == 1);
  for (auto& blob : storage.blobs) {
    if (blob.size() > 8) blob[8] ^= 0x80;
  }
  sgk::SensorSummaryQueue afterBothCorrupted(&storage);
  afterBothCorrupted.begin();
  assert(afterBothCorrupted.front() == nullptr && afterBothCorrupted.invalidJournals() == 2);
  std::puts("sensor freeze, MAC, bounded durable ring, ACK/torn-save passed");
}
