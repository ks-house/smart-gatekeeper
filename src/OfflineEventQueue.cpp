#include "OfflineEventQueue.h"
#include <cstdio>
#include <cstring>

sgk::OfflineEventQueue g_offline_queue;

namespace sgk {

namespace {

bool hasTerminator(const char* value, size_t capacity) {
  return value != nullptr && std::memchr(value, '\0', capacity) != nullptr;
}

bool hasCanonicalV2Overlay(const CanonicalEvent& event) {
  return event.is_canonical == 1 &&
         event.padding == kCanonicalV2OverlayMarker &&
         (event.schema_version == kCanonicalEventSchemaV2 ||
          event.schema_version == kCanonicalEventSchemaV1);
}

bool allZero(const uint8_t* value, size_t length) {
  if (value == nullptr) return true;
  uint8_t aggregate = 0;
  for (size_t index = 0; index < length; ++index) aggregate |= value[index];
  return aggregate == 0;
}

bool validKeyIdCharacter(char value) {
  return (value >= 'a' && value <= 'z') ||
         (value >= '0' && value <= '9');
}

bool decodeCanonicalV2Overlay(
    const CanonicalEvent& event,
    char key_id_out[kAccessEvidenceKeyIdCapacity],
    uint8_t tag_out[kAccessEvidenceTagSize],
    char credential_ref_out[kAccessEventCredentialRefCapacity]) {
  if (key_id_out != nullptr) {
    std::memset(key_id_out, 0, kAccessEvidenceKeyIdCapacity);
  }
  if (tag_out != nullptr) std::memset(tag_out, 0, kAccessEvidenceTagSize);
  if (credential_ref_out != nullptr) {
    std::memset(credential_ref_out, 0,
                kAccessEventCredentialRefCapacity);
  }
  if (!hasCanonicalV2Overlay(event) ||
      !hasTerminator(event.detail, kCanonicalV2ReasonCapacity)) {
    return false;
  }
  const uint8_t key_id_length = static_cast<uint8_t>(
      event.detail[kCanonicalV2KeyIdLengthOffset]);
  if (key_id_length == 0 || key_id_length > kCanonicalV2KeyIdStorageSize) {
    return false;
  }
  for (size_t index = 0; index < kCanonicalV2KeyIdStorageSize; ++index) {
    const char value = event.detail[kCanonicalV2KeyIdOffset + index];
    if (index < key_id_length) {
      if (!validKeyIdCharacter(value)) return false;
      if (key_id_out != nullptr) key_id_out[index] = value;
    } else if (value != '\0') {
      return false;
    }
  }
  const uint8_t credential_present = static_cast<uint8_t>(
      event.detail[kCanonicalV2CredentialPresentOffset]);
  if (credential_present > 1) return false;
  const uint8_t* digest = reinterpret_cast<const uint8_t*>(event.detail) +
                          kCanonicalV2CredentialDigestOffset;
  if (credential_present == 0 &&
      !allZero(digest, kCanonicalV2CredentialDigestSize)) {
    return false;
  }
  const uint8_t* tag = reinterpret_cast<const uint8_t*>(event.detail) +
                       kCanonicalV2AuthTagOffset;
  if (allZero(tag, kCanonicalV2AuthTagSize)) return false;
  for (size_t index = 0; index < kCanonicalV2ReservedSize; ++index) {
    if (event.detail[kCanonicalV2ReservedOffset + index] != '\0') return false;
  }
  if (tag_out != nullptr) std::memcpy(tag_out, tag, kAccessEvidenceTagSize);
  if (credential_present != 0 && credential_ref_out != nullptr) {
    static constexpr char kHex[] = "0123456789abcdef";
    size_t offset = 0;
    credential_ref_out[offset++] = 'c';
    credential_ref_out[offset++] = '_';
    for (size_t index = 0; index < key_id_length; ++index) {
      credential_ref_out[offset++] =
          event.detail[kCanonicalV2KeyIdOffset + index];
    }
    credential_ref_out[offset++] = '_';
    for (size_t index = 0; index < kCanonicalV2CredentialDigestSize; ++index) {
      credential_ref_out[offset++] = kHex[digest[index] >> 4];
      credential_ref_out[offset++] = kHex[digest[index] & 0x0f];
    }
    credential_ref_out[offset] = '\0';
  }
  return true;
}

CanonicalEvent durableRecord(const CanonicalEvent& runtime_event) {
  CanonicalEvent durable = runtime_event;
  if (runtime_event.schema_version == kCanonicalEventSchemaV2) {
    // The previous firmware accepts only schema v1 records. It ignores the
    // padding word and sees the first NUL-terminated reason string, while the
    // new reader uses the marker to restore the v2 credential_ref overlay.
    durable.schema_version = kCanonicalEventSchemaV1;
    durable.padding = kCanonicalV2OverlayMarker;
  }
  durable.crc32 = OfflineEventQueue::computeCrc32(
      reinterpret_cast<const uint8_t*>(&durable),
      offsetof(CanonicalEvent, crc32));
  return durable;
}

}  // namespace

const char* canonicalEventReason(const CanonicalEvent& event) {
  return event.detail;
}

bool isValidCanonicalCredentialRef(const char* credential_ref,
                                   size_t capacity) {
  if (credential_ref == nullptr || capacity < 29 ||
      !hasTerminator(credential_ref, capacity)) {
    return false;
  }
  const size_t length = std::strlen(credential_ref);
  if (length < 28 || length > 31 || credential_ref[0] != 'c' ||
      credential_ref[1] != '_') {
    return false;
  }
  const char* separator = std::strchr(credential_ref + 2, '_');
  if (separator == nullptr) return false;
  const size_t key_id_length =
      static_cast<size_t>(separator - (credential_ref + 2));
  if (key_id_length == 0 || key_id_length > 4 ||
      std::strlen(separator + 1) != 24) {
    return false;
  }
  for (const char* cursor = credential_ref + 2; cursor < separator; ++cursor) {
    if (!((*cursor >= 'a' && *cursor <= 'z') ||
          (*cursor >= '0' && *cursor <= '9'))) {
      return false;
    }
  }
  for (const char* cursor = separator + 1; *cursor != '\0'; ++cursor) {
    if (!((*cursor >= '0' && *cursor <= '9') ||
          (*cursor >= 'a' && *cursor <= 'f'))) {
      return false;
    }
  }
  return true;
}

bool canonicalEventAccessAuth(
    const CanonicalEvent& event,
    char key_id_out[kAccessEvidenceKeyIdCapacity],
    uint8_t tag_out[kAccessEvidenceTagSize],
    char credential_ref_out[kAccessEventCredentialRefCapacity]) {
  if (event.is_canonical != 1 ||
      event.schema_version != kCanonicalEventSchemaV2) {
    return false;
  }
  return decodeCanonicalV2Overlay(event, key_id_out, tag_out,
                                  credential_ref_out);
}

bool setCanonicalV2Detail(CanonicalEvent* event, const char* reason_code,
                          const char* key_id, const char* credential_ref,
                          const uint8_t tag[kAccessEvidenceTagSize]) {
  if (event == nullptr || reason_code == nullptr || reason_code[0] == '\0' ||
      std::strlen(reason_code) >= kCanonicalV2ReasonCapacity ||
      key_id == nullptr || tag == nullptr ||
      allZero(tag, kAccessEvidenceTagSize)) {
    return false;
  }
  const size_t key_id_length = std::strlen(key_id);
  if (key_id_length == 0 ||
      key_id_length > kCanonicalV2KeyIdStorageSize) {
    return false;
  }
  for (size_t index = 0; index < key_id_length; ++index) {
    if (!validKeyIdCharacter(key_id[index])) return false;
  }
  const bool has_credential_ref =
      credential_ref != nullptr && credential_ref[0] != '\0';
  if (has_credential_ref) {
    if (!isValidCanonicalCredentialRef(
            credential_ref, kAccessEventCredentialRefCapacity)) {
      return false;
    }
    const char* separator = std::strchr(credential_ref + 2, '_');
    if (separator == nullptr ||
        static_cast<size_t>(separator - (credential_ref + 2)) !=
            key_id_length ||
        std::memcmp(credential_ref + 2, key_id, key_id_length) != 0) {
      return false;
    }
  }
  std::memset(event->detail, 0, sizeof(event->detail));
  std::memcpy(event->detail, reason_code, std::strlen(reason_code));
  event->detail[kCanonicalV2KeyIdLengthOffset] =
      static_cast<char>(key_id_length);
  std::memcpy(event->detail + kCanonicalV2KeyIdOffset, key_id,
              key_id_length);
  event->detail[kCanonicalV2CredentialPresentOffset] =
      has_credential_ref ? 1 : 0;
  if (has_credential_ref) {
    const char* digest_hex = std::strrchr(credential_ref, '_') + 1;
    auto nibble = [](char value) -> uint8_t {
      return value <= '9' ? static_cast<uint8_t>(value - '0')
                          : static_cast<uint8_t>(value - 'a' + 10);
    };
    uint8_t* digest = reinterpret_cast<uint8_t*>(event->detail) +
                      kCanonicalV2CredentialDigestOffset;
    for (size_t index = 0; index < kCanonicalV2CredentialDigestSize; ++index) {
      digest[index] = static_cast<uint8_t>(
          (nibble(digest_hex[index * 2]) << 4) |
          nibble(digest_hex[index * 2 + 1]));
    }
  }
  std::memcpy(event->detail + kCanonicalV2AuthTagOffset, tag,
              kAccessEvidenceTagSize);
  event->schema_version = kCanonicalEventSchemaV2;
  event->padding = kCanonicalV2OverlayMarker;
  return true;
}

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

bool isValidCanonicalEventRecord(const CanonicalEvent& evt) {
  if (evt.is_canonical != 1) {
    return evt.schema_version == kCanonicalEventSchemaV1;
  }
  if (evt.schema_version != kCanonicalEventSchemaV1 &&
      evt.schema_version != kCanonicalEventSchemaV2) {
    return false;
  }
  if (evt.event_id[0] == '\0' || evt.session_id[0] == '\0' ||
      evt.source_boot_id[0] == '\0' || evt.target_ref[0] == '\0' ||
      evt.event_type[0] == '\0' || evt.stage_text[0] == '\0' ||
      evt.outcome_text[0] == '\0' || evt.detail[0] == '\0') {
    return false;
  }
  if (!hasTerminator(evt.event_id, sizeof(evt.event_id)) ||
      !hasTerminator(evt.session_id, sizeof(evt.session_id)) ||
      !hasTerminator(evt.source_boot_id, sizeof(evt.source_boot_id)) ||
      !hasTerminator(evt.causation_event_id,
                     sizeof(evt.causation_event_id)) ||
      !hasTerminator(evt.target_ref, sizeof(evt.target_ref)) ||
      !hasTerminator(evt.event_type, sizeof(evt.event_type)) ||
      !hasTerminator(evt.stage_text, sizeof(evt.stage_text)) ||
      !hasTerminator(evt.outcome_text, sizeof(evt.outcome_text))) {
    return false;
  }
  if (hasCanonicalV2Overlay(evt)) {
    return decodeCanonicalV2Overlay(evt, nullptr, nullptr, nullptr);
  }
  if (evt.schema_version == kCanonicalEventSchemaV2) return false;
  if (!hasTerminator(evt.detail, sizeof(evt.detail))) return false;
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
  // Preserve the durable ring's physical slot indices in RAM.  Compacting a
  // non-zero durable head into buffer_[0] makes the next pop persist RAM
  // indices as if they were storage slots, which can replay an already-popped
  // record and exclude the wrapped tail after a second reboot.
  head_ = cur_head;
  tail_ = cur_head;
  count_ = 0;

  for (size_t i = 0; i < target_count; ++i) {
    size_t slot = (cur_head + i) % kCapacity;
    CanonicalEvent evt{};
    if (storage_->readRecord(slot, &evt)) {
      uint32_t expected_crc = computeCrc32(
          reinterpret_cast<const uint8_t*>(&evt),
          offsetof(CanonicalEvent, crc32));
      if (evt.magic == 0x53475145 &&
          (evt.schema_version == kCanonicalEventSchemaV1 ||
           evt.schema_version == kCanonicalEventSchemaV2) &&
          evt.crc32 == expected_crc &&
          evt.generation > 0 && evt.generation <= selected_meta.generation &&
          isValidCanonicalEventRecord(evt)) {
        CanonicalEvent runtime_evt = evt;
        if (runtime_evt.schema_version == kCanonicalEventSchemaV1 &&
            runtime_evt.padding == kCanonicalV2OverlayMarker) {
          runtime_evt.schema_version = kCanonicalEventSchemaV2;
        }
        buffer_[slot] = runtime_evt;
        tail_ = (slot + 1) % kCapacity;
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
  if (incoming.schema_version != kCanonicalEventSchemaV1 &&
      incoming.schema_version != kCanonicalEventSchemaV2) {
    return false;
  }
  if (incoming.is_canonical == 1 &&
      incoming.schema_version == kCanonicalEventSchemaV1 &&
      incoming.padding == kCanonicalV2OverlayMarker) {
    incoming.schema_version = kCanonicalEventSchemaV2;
  }
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

    // A queue gap reports transport loss; it is not a Target access lifecycle
    // event and cannot carry a valid event UUID or access-evidence HMAC. Keep it
    // on the legacy diagnostic topic so it can be published and removed without
    // forging signed physical/access evidence or poisoning the durable head.
    gap_evt.is_canonical = 0;
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
    gap_evt.schema_version = kCanonicalEventSchemaV1;
    gap_evt.generation = next_gen;
    gap_evt.crc32 = computeCrc32(reinterpret_cast<const uint8_t*>(&gap_evt),
                                 offsetof(CanonicalEvent, crc32));
    if (!isValidCanonicalEventRecord(gap_evt)) {
      return false;
    }
  }


  incoming.magic = 0x53475145;
  incoming.generation = next_gen;
  incoming.crc32 = computeCrc32(reinterpret_cast<const uint8_t*>(&incoming),
                                offsetof(CanonicalEvent, crc32));
  const CanonicalEvent durable_incoming = durableRecord(incoming);

  if (overflow_occurred) {
    size_t gap_slot = new_tail;
    size_t inc_slot = (new_tail + 1) % kCapacity;
    if (storage_ != nullptr) {
      if (!storage_->saveRecord(gap_slot, gap_evt) ||
          !storage_->saveRecord(inc_slot, durable_incoming)) {
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
      if (!storage_->saveRecord(new_tail, durable_incoming)) {
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
    *event_out = Event{};
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
    *event_out = Event{};
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
