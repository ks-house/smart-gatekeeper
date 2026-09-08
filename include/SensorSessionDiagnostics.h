#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace sgk {

enum class SensorClearanceState : uint8_t { kUnknown, kClear, kOccupied, kFault };
inline const char* sensorClearanceName(SensorClearanceState state) {
  switch (state) {
    case SensorClearanceState::kClear: return "CLEAR";
    case SensorClearanceState::kOccupied: return "OCCUPIED";
    case SensorClearanceState::kFault: return "FAULT";
    default: return "UNKNOWN";
  }
}

constexpr uint16_t kNoSensorMeasurement = UINT16_MAX;
struct SensorSessionSummary {
  uint32_t started_monotonic_ms = 0;
  uint32_t ended_monotonic_ms = 0;
  uint32_t samples = 0;
  uint32_t valid_samples = 0;
  uint32_t timeouts = 0;
  uint32_t invalid_samples = 0;
  uint32_t in_range_samples = 0;
  uint32_t blocked_samples = 0;
  uint32_t clear_samples = 0;
  uint16_t threshold_mm = 0;
  uint16_t min_raw_mm = kNoSensorMeasurement;
  uint16_t max_raw_mm = kNoSensorMeasurement;
  uint16_t last_raw_mm = kNoSensorMeasurement;
  uint16_t last_median_mm = kNoSensorMeasurement;
  bool blocked_at_start = false;
  bool blocked_at_end = false;
  SensorClearanceState clearance_state = SensorClearanceState::kUnknown;
};

// Authorization is intentionally absent: this records measurements and
// decisions, but never changes a relay, authorizes access or clears a latch.
class SensorSessionTracker {
 public:
  static constexpr size_t kPendingCapacity = 4;
  void begin(uint32_t now_ms, uint16_t threshold_mm, bool blocked) {
    current_ = {};
    current_.started_monotonic_ms = now_ms;
    current_.threshold_mm = threshold_mm;
    current_.blocked_at_start = blocked;
    active_ = true;
  }
  void observe(bool echo_received, uint16_t raw_mm, uint16_t median_mm,
               bool blocked, SensorClearanceState clearance) {
    if (!active_) return;
    ++current_.samples;
    current_.last_raw_mm = raw_mm;
    current_.last_median_mm = median_mm;
    current_.clearance_state = clearance;
    if (!echo_received) ++current_.timeouts;
    else if (raw_mm == kNoSensorMeasurement) ++current_.invalid_samples;
    else {
      ++current_.valid_samples;
      if (current_.min_raw_mm == kNoSensorMeasurement || raw_mm < current_.min_raw_mm) current_.min_raw_mm = raw_mm;
      if (current_.max_raw_mm == kNoSensorMeasurement || raw_mm > current_.max_raw_mm) current_.max_raw_mm = raw_mm;
      if (raw_mm <= current_.threshold_mm) ++current_.in_range_samples;
      if (raw_mm > current_.threshold_mm + 100) ++current_.clear_samples;
    }
    if (blocked) ++current_.blocked_samples;
  }
  bool finish(uint32_t now_ms, bool blocked, SensorClearanceState clearance) {
    if (!active_) return false;
    current_.ended_monotonic_ms = now_ms;
    current_.blocked_at_end = blocked;
    current_.clearance_state = clearance;
    active_ = false;
    if (pending_count_ == kPendingCapacity) {
      if (dropped_ != UINT32_MAX) ++dropped_;
      return false;
    }
    pending_[pending_count_++] = current_;
    return true;
  }
  bool take(uint64_t terminal_ms, SensorSessionSummary* output) {
    if (output == nullptr) return false;
    for (size_t i = 0; i < pending_count_; ++i) {
      if (pending_[i].ended_monotonic_ms != terminal_ms) continue;
      *output = pending_[i];
      for (size_t next = i + 1; next < pending_count_; ++next) {
        pending_[next - 1] = pending_[next];
      }
      pending_[--pending_count_] = {};
      return true;
    }
    return false;
  }
  bool active() const { return active_; }
  size_t pending() const { return pending_count_; }
  uint32_t dropped() const { return dropped_; }
 private:
  SensorSessionSummary current_{};
  // Terminal evidence can be backpressured while further access succeeds.
  // Never replace an earlier frozen window with the next person's readings.
  std::array<SensorSessionSummary, kPendingCapacity> pending_{};
  size_t pending_count_ = 0;
  uint32_t dropped_ = 0;
  bool active_ = false;
};

struct SensorSummaryRecord {
  SensorSessionSummary summary{};
  uint64_t source_boot_count = 0;
  uint64_t terminal_sequence = 0;
  char source_boot_id[33] = {};
  char session_id[37] = {};
  char key_id[5] = {};
  uint8_t tag[16] = {};
};

// Four records, two alternating atomic NVS blobs, <2 KiB persistent bytes.
// Independent namespace keeps both legacy event ABI and OTA rollback intact.
class SensorSummaryStorage {
 public:
  virtual ~SensorSummaryStorage() = default;
  virtual size_t read(uint8_t slot, void* output, size_t capacity) = 0;
  virtual bool write(uint8_t slot, const void* bytes, size_t length) = 0;
};

class SensorSummaryQueue {
 public:
  static constexpr size_t kCapacity = 4;
  explicit SensorSummaryQueue(SensorSummaryStorage* storage) : storage_(storage) {}
  void begin();
  bool push(const SensorSummaryRecord& record);
  const SensorSummaryRecord* front() const;
  bool pop();
  size_t size() const { return journal_.count; }
  uint32_t dropped() const { return journal_.dropped; }
  uint32_t persistenceFailures() const { return persistence_failures_; }
  uint32_t invalidJournals() const { return invalid_journals_; }
 private:
  struct Journal {
    uint32_t magic = 0x53475331;
    uint32_t generation = 0;
    uint32_t dropped = 0;
    uint32_t count = 0;
    std::array<SensorSummaryRecord, kCapacity> records{};
    uint32_t crc32 = 0;
  };
  static_assert(sizeof(Journal) * 2 <= 2048, "sensor journal exceeds NVS budget");
  bool commit(Journal candidate);
  SensorSummaryStorage* storage_ = nullptr;
  Journal journal_{};
  uint8_t active_slot_ = 0;
  uint32_t persistence_failures_ = 0;
  uint32_t invalid_journals_ = 0;
};

bool buildSensorSummaryMacInput(const char* target_id,
                               const SensorSummaryRecord& record,
                               uint8_t* output, size_t capacity,
                               size_t* written);
bool deriveSensorSummaryMac(const std::array<uint8_t, 32>& key,
                           const char* target_id,
                           const SensorSummaryRecord& record,
                           uint8_t output[16]);

}  // namespace sgk
