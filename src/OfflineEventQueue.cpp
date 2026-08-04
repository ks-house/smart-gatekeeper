#include "OfflineEventQueue.h"
#include <cstdio>
#include <cstring>

sgk::OfflineEventQueue g_offline_queue;

namespace sgk {

uint32_t OfflineEventQueue::computeCrc32(const uint8_t* data, size_t len) {
  uint32_t crc = 0xFFFFFFFF;
  for (size_t i = 0; i < len; ++i) {
    crc ^= data[i];
    for (int j = 0; j < 8; ++j) {
      crc = (crc >> 1) ^ (0xEDB88320 & (-(crc & 1)));
    }
  }
  return ~crc;
}

static bool isValidCanonicalEventRecord(const CanonicalEvent& evt) {
  if (evt.is_canonical != 1) return true;
  if (evt.event_id[0] == '\0' || evt.session_id[0] == '\0' ||
      evt.source_boot_id[0] == '\0' || evt.target_ref[0] == '\0' ||
      evt.event_type[0] == '\0' || evt.stage_text[0] == '\0' ||
      evt.outcome_text[0] == '\0' || evt.detail[0] == '\0') {
    return false;
  }
  return true;
}

OfflineEventQueue::OfflineEventQueue(OfflineQueueStorage* storage)
    : storage_(storage) {}

void OfflineEventQueue::begin() {
  if (storage_ == nullptr) return;

  auto isValidMeta = [](const QueueMetaRecord& meta) {
    if (meta.magic != 0x5347514D || meta.schema_version != 1) return false;
    if (meta.count > kCapacity || meta.head >= kCapacity || meta.tail >= kCapacity) return false;
    if (meta.tail != (meta.head + meta.count) % kCapacity) return false;
    uint32_t expected_crc = computeCrc32(reinterpret_cast<const uint8_t*>(&meta),
                                         offsetof(QueueMetaRecord, crc32));
    return meta.crc32 == expected_crc;
  };

  QueueMetaRecord meta0{}, meta1{};
  bool m0_valid = storage_->readMetaRecord(0, &meta0) && isValidMeta(meta0);
  bool m1_valid = storage_->readMetaRecord(1, &meta1) && isValidMeta(meta1);

  if (!m0_valid && !m1_valid) {
    head_ = 0;
    tail_ = 0;
    count_ = 0;
    generation_ = 0;
    active_meta_slot_ = 0;
    overflow_count_ = 0;
    return;
  }

  QueueMetaRecord selected_meta{};
  if (m0_valid && m1_valid) {
    if (meta1.generation > meta0.generation) {
      selected_meta = meta1;
      active_meta_slot_ = 1;
    } else {
      selected_meta = meta0;
      active_meta_slot_ = 0;
    }
  } else if (m0_valid) {
    selected_meta = meta0;
    active_meta_slot_ = 0;
  } else {
    selected_meta = meta1;
    active_meta_slot_ = 1;
  }

  generation_ = selected_meta.generation;
  overflow_count_ = selected_meta.overflow_count;

  size_t target_count = (selected_meta.count > kCapacity) ? kCapacity : selected_meta.count;
  size_t cur_head = selected_meta.head % kCapacity;

  buffer_.fill(CanonicalEvent{});
  head_ = 0;
  tail_ = 0;
  count_ = 0;

  for (size_t i = 0; i < target_count; ++i) {
    size_t slot = (cur_head + i) % kCapacity;
    CanonicalEvent evt{};
    if (storage_->readRecord(slot, &evt)) {
      uint32_t expected_crc = computeCrc32(
          reinterpret_cast<const uint8_t*>(&evt),
          offsetof(CanonicalEvent, crc32));
      if (evt.magic == 0x53475145 && evt.schema_version == 1 &&
          evt.crc32 == expected_crc &&
          evt.generation > 0 && evt.generation <= selected_meta.generation &&
          isValidCanonicalEventRecord(evt)) {
        buffer_[tail_] = evt;
        tail_ = (tail_ + 1) % kCapacity;
        ++count_;
      } else {
        ++torn_recovery_count_;
        break; // Stop at first invalid record to prevent corrupted evidence replay
      }
    } else {
      ++torn_recovery_count_;
      break;
    }
  }
}

bool OfflineEventQueue::persistMeta(size_t head, size_t tail, size_t count,
                                    uint32_t overflow_count) {
  if (storage_ == nullptr) return true;

  uint8_t next_meta_slot = (active_meta_slot_ == 0) ? 1 : 0;
  QueueMetaRecord meta{};
  meta.magic = 0x5347514D;
  meta.schema_version = 1;
  meta.reserved = 0;
  meta.generation = generation_ + 1;
  meta.head = static_cast<uint32_t>(head);
  meta.tail = static_cast<uint32_t>(tail);
  meta.count = static_cast<uint32_t>(count);
  meta.overflow_count = overflow_count;
  meta.crc32 = computeCrc32(reinterpret_cast<const uint8_t*>(&meta),
                            offsetof(QueueMetaRecord, crc32));

  if (!storage_->saveMetaRecord(next_meta_slot, meta)) {
    return false;
  }
  generation_ = meta.generation;
  active_meta_slot_ = next_meta_slot;
  return true;
}

bool OfflineEventQueue::push(const CanonicalEvent& event) {
  if (!isValidCanonicalEventRecord(event)) {
    return false;
  }
  CanonicalEvent incoming = event;
  uint32_t next_gen = generation_ + 1;

  size_t new_head = head_;
  size_t new_tail = tail_;
  size_t new_count = count_;
  uint32_t new_overflow = overflow_count_;

  bool overflow_occurred = false;
  CanonicalEvent gap_evt{};

  if (new_count >= kCapacity) {
    overflow_occurred = true;
    CanonicalEvent dropped_evt1 = buffer_[new_head];
    CanonicalEvent dropped_evt2 = buffer_[(new_head + 1) % kCapacity];
    new_head = (new_head + 2) % kCapacity;
    new_count -= 2;
    new_overflow += 2;

    gap_evt.is_canonical = 1;
    gap_evt.code = 1007; // canonical queue overflow code
    gap_evt.transport_reason = static_cast<uint16_t>(ResultReason::kInternalFailClosed);

    std::strncpy(gap_evt.event_type, "queue_overflow", sizeof(gap_evt.event_type) - 1);
    std::strncpy(gap_evt.stage_text, "OVERFLOW", sizeof(gap_evt.stage_text) - 1);
    std::strncpy(gap_evt.outcome_text, "DROPPED", sizeof(gap_evt.outcome_text) - 1);

    if (dropped_evt1.sequence == dropped_evt2.sequence) {
      std::snprintf(gap_evt.detail, sizeof(gap_evt.detail),
                    "Queue overflow: dropped seq %llu (overflow_count=%u)",
                    static_cast<unsigned long long>(dropped_evt1.sequence),
                    static_cast<unsigned int>(new_overflow));
    } else {
      std::snprintf(gap_evt.detail, sizeof(gap_evt.detail),
                    "Queue overflow: dropped seq %llu-%llu (overflow_count=%u)",
                    static_cast<unsigned long long>(dropped_evt1.sequence),
                    static_cast<unsigned long long>(dropped_evt2.sequence),
                    static_cast<unsigned int>(new_overflow));
    }
    gap_evt.monotonic_ms = incoming.monotonic_ms;
    gap_evt.sequence = dropped_evt1.sequence;
    gap_evt.boot_count = incoming.boot_count;
    std::strncpy(gap_evt.target_ref, incoming.target_ref, sizeof(gap_evt.target_ref) - 1);
    std::strncpy(gap_evt.source_boot_id, incoming.source_boot_id, sizeof(gap_evt.source_boot_id) - 1);
    std::strncpy(gap_evt.session_id, dropped_evt1.session_id, sizeof(gap_evt.session_id) - 1);
    gap_evt.magic = 0x53475145;
    gap_evt.schema_version = 1;
    gap_evt.generation = next_gen;
    gap_evt.crc32 = computeCrc32(reinterpret_cast<const uint8_t*>(&gap_evt),
                                 offsetof(CanonicalEvent, crc32));
  }


  incoming.magic = 0x53475145;
  incoming.schema_version = 1;
  incoming.generation = next_gen;
  incoming.crc32 = computeCrc32(reinterpret_cast<const uint8_t*>(&incoming),
                                offsetof(CanonicalEvent, crc32));

  if (overflow_occurred) {
    size_t gap_slot = new_tail;
    size_t inc_slot = (new_tail + 1) % kCapacity;
    if (storage_ != nullptr) {
      if (!storage_->saveRecord(gap_slot, gap_evt) ||
          !storage_->saveRecord(inc_slot, incoming)) {
        return false;
      }
    }
    size_t next_tail = (new_tail + 2) % kCapacity;
    size_t next_count = new_count + 2;
    if (!persistMeta(new_head, next_tail, next_count, new_overflow)) {
      return false;
    }
    buffer_[gap_slot] = gap_evt;
    buffer_[inc_slot] = incoming;
    head_ = new_head;
    tail_ = next_tail;
    count_ = next_count;
    overflow_count_ = new_overflow;
  } else {
    if (storage_ != nullptr) {
      if (!storage_->saveRecord(new_tail, incoming)) {
        return false;
      }
    }
    size_t next_tail = (new_tail + 1) % kCapacity;
    size_t next_count = new_count + 1;
    if (!persistMeta(new_head, next_tail, next_count, new_overflow)) {
      return false;
    }
    buffer_[new_tail] = incoming;
    head_ = new_head;
    tail_ = next_tail;
    count_ = next_count;
    overflow_count_ = new_overflow;
  }

  return true;
}

bool OfflineEventQueue::pushEvent(const char* event_type, const char* detail,
                                  uint64_t now_ms, uint64_t sequence,
                                  const char* target_id, const char* boot_id,
                                  uint32_t boot_count) {
  CanonicalEvent evt{};
  evt.monotonic_ms = now_ms;
  evt.sequence = sequence;
  evt.boot_count = boot_count;
  if (event_type) std::strncpy(evt.event_type, event_type, sizeof(evt.event_type) - 1);
  if (detail) std::strncpy(evt.detail, detail, sizeof(evt.detail) - 1);
  if (target_id) std::strncpy(evt.target_ref, target_id, sizeof(evt.target_ref) - 1);
  if (boot_id) std::strncpy(evt.source_boot_id, boot_id, sizeof(evt.source_boot_id) - 1);
  return push(evt);
}

bool OfflineEventQueue::peekFront(CanonicalEvent* event_out) const {
  if (count_ == 0 || event_out == nullptr) return false;
  *event_out = buffer_[head_];
  return true;
}

bool OfflineEventQueue::popFront(CanonicalEvent* event_out) {
  if (count_ == 0) return false;

  size_t new_head = (head_ + 1) % kCapacity;
  size_t new_count = count_ - 1;

  // Persist updated meta before considering record removed
  if (!persistMeta(new_head, tail_, new_count, overflow_count_)) {
    return false; // Do not dequeue from RAM if persistent commit fails
  }

  if (event_out != nullptr) {
    *event_out = buffer_[head_];
  }
  head_ = new_head;
  count_ = new_count;
  return true;
}

bool OfflineEventQueue::push(const Event& event, uint64_t now_ms) {
  CanonicalEvent evt{};
  evt.code = static_cast<uint16_t>(event.code);
  evt.transport_reason = static_cast<uint16_t>(event.reason);
  evt.monotonic_ms = now_ms;
  evt.sequence = event.sequence;
  std::strncpy(evt.event_type, "gatt_event", sizeof(evt.event_type) - 1);
  return push(evt);
}

bool OfflineEventQueue::pop(Event* event_out) {
  CanonicalEvent evt{};
  if (!popFront(&evt)) return false;
  if (event_out != nullptr) {
    event_out->code = static_cast<EventCode>(evt.code);
    event_out->reason = static_cast<EventReason>(evt.transport_reason);
    event_out->sequence = evt.sequence;
    event_out->monotonic_ms = evt.monotonic_ms;
  }
  return true;
}

bool OfflineEventQueue::peek(Event* event_out) const {
  CanonicalEvent evt{};
  if (!peekFront(&evt)) return false;
  if (event_out != nullptr) {
    event_out->code = static_cast<EventCode>(evt.code);
    event_out->reason = static_cast<EventReason>(evt.transport_reason);
    event_out->sequence = evt.sequence;
    event_out->monotonic_ms = evt.monotonic_ms;
  }
  return true;
}

void OfflineEventQueue::clear() {
  head_ = 0;
  tail_ = 0;
  count_ = 0;
  generation_ = 0;
  active_meta_slot_ = 0;
  overflow_count_ = 0;
  torn_recovery_count_ = 0;
  if (storage_ != nullptr) {
    storage_->clearStorage();
  }
}

}  // namespace sgk
