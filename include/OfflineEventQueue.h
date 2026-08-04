#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include "GattProtocol.h"

namespace sgk {

struct CanonicalEvent {
  uint32_t magic = 0x53475145; // "SGQE"
  uint16_t schema_version = 1;
  uint16_t code = 0;           // numeric EventCode
  uint16_t transport_reason = 0;
  uint8_t is_canonical = 0;    // 1 if typed canonical event
  uint8_t has_causation = 0;   // 1 if causation_event_id set
  uint32_t generation = 0;
  uint64_t monotonic_ms = 0;   // uint64_t preserved
  uint64_t sequence = 0;
  uint32_t boot_count = 0;
  uint32_t attempt = 1;

  char event_id[37] = {};           // UUID string
  char session_id[37] = {};         // UUID string
  char source_boot_id[37] = {};     // UUID string
  char causation_event_id[37] = {}; // UUID string
  char target_ref[37] = {};         // Target ref string

  char event_type[32] = {};  // Used for event_code text (or fallback event type)
  char stage_text[24] = {};   // Used for stage text
  char outcome_text[16] = {}; // Used for outcome text
  char detail[64] = {};       // Used for reason_code text (or fallback detail)

  uint16_t padding = 0;
  uint32_t crc32 = 0;
};

struct QueueMetaRecord {
  uint32_t magic = 0x5347514D; // "SGQM"
  uint16_t schema_version = 1;
  uint16_t reserved = 0;
  uint32_t generation = 0;
  uint32_t head = 0;
  uint32_t tail = 0;
  uint32_t count = 0;
  uint32_t overflow_count = 0;
  uint32_t crc32 = 0;
};

class OfflineQueueStorage {
 public:
  virtual ~OfflineQueueStorage() = default;
  virtual bool saveRecord(size_t slot, const CanonicalEvent& event) = 0;
  virtual bool readRecord(size_t slot, CanonicalEvent* event) = 0;
  virtual bool saveMetaRecord(uint8_t meta_slot, const QueueMetaRecord& meta) = 0;
  virtual bool readMetaRecord(uint8_t meta_slot, QueueMetaRecord* meta) = 0;
  virtual bool clearStorage() = 0;
};

class OfflineEventQueue {
 public:
  static constexpr size_t kCapacity = 8;

  explicit OfflineEventQueue(OfflineQueueStorage* storage = nullptr);

  void setStorage(OfflineQueueStorage* storage) { storage_ = storage; }
  void begin();
  bool push(const CanonicalEvent& event);
  bool pushEvent(const char* event_type, const char* detail, uint64_t now_ms,
                 uint64_t sequence = 0, const char* target_id = "",
                 const char* boot_id = "", uint32_t boot_count = 0);
  bool peekFront(CanonicalEvent* event_out) const;
  bool popFront(CanonicalEvent* event_out = nullptr);

  // Backward compatibility aliases
  bool push(const Event& event, uint64_t now_ms);
  bool pop(Event* event_out);
  bool peek(Event* event_out) const;

  bool isEmpty() const { return count_ == 0; }
  size_t size() const { return count_; }
  uint32_t overflowCount() const { return overflow_count_; }
  uint32_t tornRecoveryCount() const { return torn_recovery_count_; }
  void clear();

  static uint32_t computeCrc32(const uint8_t* data, size_t len);

 private:
  OfflineQueueStorage* storage_ = nullptr;
  std::array<CanonicalEvent, kCapacity> buffer_{};
  size_t head_ = 0;
  size_t tail_ = 0;
  size_t count_ = 0;
  uint32_t generation_ = 0;
  uint8_t active_meta_slot_ = 0;
  uint32_t overflow_count_ = 0;
  uint32_t torn_recovery_count_ = 0;

  bool persistMeta(size_t head, size_t tail, size_t count, uint32_t overflow_count);
};

static constexpr size_t kMaxAclSnapshotBytes = 6924;
static_assert(sizeof(CanonicalEvent) <= 384, "CanonicalEvent struct size exceeds 384 byte budget");
static_assert(2 * kMaxAclSnapshotBytes + OfflineEventQueue::kCapacity * sizeof(CanonicalEvent) + 2 * sizeof(QueueMetaRecord) <= 18432,
              "Offline event queue and dual ACL snapshot storage budget exceeds 18 KiB NVS allocation");

}  // namespace sgk

extern sgk::OfflineEventQueue g_offline_queue;
