#pragma once

#include <array>
#include <cstdint>
#include "AccessEventCatalog.h"

namespace sgk {
enum class AccessDeliveryResult : uint8_t { kAccepted, kRetry, kInvalid };
enum class AccessDeliveryFailure : uint8_t { kNone, kDownstream, kInvalid, kOverflow };
inline const char* accessDeliveryFailureName(AccessDeliveryFailure reason) {
  switch (reason) {
    case AccessDeliveryFailure::kDownstream: return "DOWNSTREAM_RETRY";
    case AccessDeliveryFailure::kInvalid: return "INVALID_EVENT";
    case AccessDeliveryFailure::kOverflow: return "QUEUE_FULL";
    default: return "NONE";
  }
}
inline bool validDeferredAccessEvent(const Event& event) {
  uint8_t session = 0;
  for (auto byte : event.session_id) session |= byte;
  AccessCatalog fields;
  return session != 0 && event.sequence != 0 &&
      buildAccessCatalog(event, &fields);
}
struct DeferredAccessHealth {
  uint32_t transport_aborts = 0;
  uint32_t depth = 0;
  uint32_t head_age_ms = 0;
  uint32_t head_retries = 0;
  uint32_t retry_count = 0;
  uint32_t invalid_count = 0;
  uint32_t overflow_count = 0;
  bool evidence_gap = false;
  bool stalled = false;
  AccessDeliveryFailure last_failure = AccessDeliveryFailure::kNone;
};
// Caller serializes push/front/resolve/health. One consumer; producers append.
// Quarantine is bounded metadata only: no credential or actor/session identity.
class DeferredAccessQueue {
 public:
  static constexpr size_t kCapacity = 16;
  static constexpr size_t kQuarantineCapacity = 4;
  static constexpr uint32_t kStallMs = 15000;
  struct InvalidRecord {
    uint64_t sequence = 0;
    uint32_t quarantined_ms = 0;
    EventCode code{};
    ResultReason reason{};
  };
  bool push(const Event& event, uint32_t now_ms) {
    if (sealed_) return false;
    if (count_ == kCapacity) {
      increment(overflow_count_);
      evidence_gap_ = true;
      last_failure_ = AccessDeliveryFailure::kOverflow;
      return false;
    }
    const size_t tail = (head_ + count_) % kCapacity;
    events_[tail] = event;
    enqueued_[tail] = now_ms;
    ++count_;
    return true;
  }
  bool front(Event* output) const {
    if (output == nullptr || empty()) return false;
    *output = events_[head_];
    return true;
  }
  void resolve(AccessDeliveryResult result, uint32_t now_ms) {
    if (empty()) return;
    if (result == AccessDeliveryResult::kRetry) {
      increment(retry_count_);
      increment(head_retries_);
      last_failure_ = AccessDeliveryFailure::kDownstream;
      return;
    }
    if (result == AccessDeliveryResult::kInvalid) {
      increment(invalid_count_);
      evidence_gap_ = true;
      last_failure_ = AccessDeliveryFailure::kInvalid;
      const auto& event = events_[head_];
      quarantine_[quarantine_next_] = {
          event.sequence, now_ms, event.code, event.transport_reason};
      quarantine_next_ = (quarantine_next_ + 1) % kQuarantineCapacity;
    }
    // Scrub raw credential bytes before the slot becomes reusable.
    volatile uint8_t* credential = events_[head_].credential_id.data();
    for (size_t i = 0; i < events_[head_].credential_id.size(); ++i) credential[i] = 0;
    events_[head_] = {};
    enqueued_[head_] = 0;
    head_ = (head_ + 1) % kCapacity;
    --count_;
    head_retries_ = 0;
  }
  DeferredAccessHealth health(uint32_t now_ms) const {
    DeferredAccessHealth result;
    result.depth = count_;
    result.head_age_ms = empty() ? 0 : now_ms - enqueued_[head_];
    result.head_retries = head_retries_;
    result.retry_count = retry_count_;
    result.invalid_count = invalid_count_;
    result.overflow_count = overflow_count_;
    result.evidence_gap = evidence_gap_;
    // Idle age alone never flags failure. A retained head must have failed.
    result.stalled = !empty() && head_retries_ != 0 && result.head_age_ms >= kStallMs;
    result.last_failure = last_failure_;
    return result;
  }
  const std::array<InvalidRecord, kQuarantineCapacity>& quarantine() const {
    return quarantine_;
  }
  bool empty() const { return count_ == 0; }
  bool evidenceGap() const { return evidence_gap_; }
  void seal() { sealed_ = true; }
  void clear() {
    for (auto& event : events_) {
      volatile uint8_t* credential = event.credential_id.data();
      for (size_t i = 0; i < event.credential_id.size(); ++i) credential[i] = 0;
      event = {};
    }
    enqueued_ = {};
    quarantine_ = {};
    head_ = count_ = quarantine_next_ = 0;
    head_retries_ = retry_count_ = invalid_count_ = overflow_count_ = 0;
    evidence_gap_ = sealed_ = false;
    last_failure_ = AccessDeliveryFailure::kNone;
  }
 private:
  static void increment(uint32_t& value) { if (value != UINT32_MAX) ++value; }
  std::array<Event, kCapacity> events_{};
  std::array<uint32_t, kCapacity> enqueued_{};
  std::array<InvalidRecord, kQuarantineCapacity> quarantine_{};
  size_t head_ = 0, count_ = 0, quarantine_next_ = 0;
  uint32_t head_retries_ = 0, retry_count_ = 0, invalid_count_ = 0, overflow_count_ = 0;
  bool evidence_gap_ = false, sealed_ = false;
  AccessDeliveryFailure last_failure_ = AccessDeliveryFailure::kNone;
};
}  // namespace sgk
