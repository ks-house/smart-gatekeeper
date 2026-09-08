#include "LegacyEventQueue.h"
#include "OfflineEventQueue.h"

#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

struct Storage final : sgk::OfflineQueueStorage {
  std::array<sgk::CanonicalEvent, sgk::OfflineEventQueue::kCapacity> records{};
  std::array<sgk::QueueMetaRecord, 2> metas{};
  bool saveRecord(size_t slot, const sgk::CanonicalEvent& event) override {
    records[slot] = event; return true;
  }
  bool readRecord(size_t slot, sgk::CanonicalEvent* event) override {
    *event = records[slot]; return true;
  }
  bool saveMetaRecord(uint8_t slot, const sgk::QueueMetaRecord& meta) override {
    metas[slot] = meta; return true;
  }
  bool readMetaRecord(uint8_t slot, sgk::QueueMetaRecord* meta) override {
    *meta = metas[slot]; return true;
  }
  bool clearStorage() override { records = {}; metas = {}; return true; }
};

sgk::CanonicalEvent canonical(const char* name, unsigned sequence) {
  sgk::CanonicalEvent event{};
  event.is_canonical = 1;
  event.sequence = sequence;
  event.boot_count = 782;
  std::snprintf(event.event_type, sizeof(event.event_type), "%s", name);
  std::snprintf(event.event_id, sizeof(event.event_id),
                "00000000-0000-4000-8000-%012u", sequence);
  std::strcpy(event.session_id, "00000000-0000-4000-8000-000000000001");
  std::strcpy(event.source_boot_id, "11111111111111111111111111111111");
  std::strcpy(event.target_ref, "test-target");
  std::strcpy(event.stage_text, "TEST");
  std::strcpy(event.outcome_text, "SUCCEEDED");
  uint8_t tag[sgk::kAccessEvidenceTagSize] = {1};
  assert(sgk::setCanonicalV2Detail(&event, "TEST_REASON", "a1", nullptr, tag));
  return event;
}

void mixedSession(bool timeout) {
  Storage storage;
  sgk::OfflineEventQueue audit(&storage);
  sgk::LegacyEventQueue text;
  audit.begin();
  const std::vector<const char*> normal = {
      "auth_pending", "ACCESS_GATT_CONNECTED", "ACCESS_PROOF_REQUESTED",
      "ACCESS_PROOF_VERIFIED", "auth_verified_armed", "ACCESS_ARMED",
      "sensor_detected", "relay_on_sensor", "ACCESS_SENSOR_DETECTED",
      "ACCESS_RELAY_ON", "door_close", "session_completed",
      "ACCESS_RELAY_OFF", "ACCESS_SESSION_COMPLETED"};
  const std::vector<const char*> expired = {
      "auth_pending", "ACCESS_GATT_CONNECTED", "ACCESS_PROOF_REQUESTED",
      "ACCESS_PROOF_VERIFIED", "auth_verified_armed", "ACCESS_ARMED",
      "arm_expired", "session_terminated", "ACCESS_SESSION_TERMINATED"};
  unsigned sequence = 0;
  for (const auto* name : timeout ? expired : normal) {
    if (std::strncmp(name, "ACCESS_", 7) == 0) {
      assert(audit.push(canonical(name, ++sequence)));
    } else {
      sgk::LegacyEvent event{};
      std::snprintf(event.event_type, sizeof(event.event_type), "%s", name);
      assert(text.push(event));
    }
  }
  // An unlimited burst of best-effort chatter cannot spend audit capacity.
  for (int i = 0; i < 100; ++i) text.push({});
  assert(text.dropped() > 0);
  assert(audit.overflowCount() == 0);
  sgk::OfflineEventQueue restored(&storage);
  restored.begin();
  const unsigned expected = timeout ? 5 : 8;
  assert(restored.size() == expected);
  for (unsigned i = 1; i <= expected; ++i) {
    sgk::CanonicalEvent event{};
    assert(restored.popFront(&event));
    assert(event.is_canonical == 1 && event.sequence == i);
    if (!timeout && i == 5) assert(std::string(event.event_type) == "ACCESS_SENSOR_DETECTED");
    if (!timeout && i == 6) assert(std::string(event.event_type) == "ACCESS_RELAY_ON");
  }
}

int main() {
  auto authenticated = canonical("ACCESS_ARMED", 1);
  assert(sgk::canonicalEventRequiresCommitReceipt(authenticated));
  authenticated.schema_version = sgk::kCanonicalEventSchemaV1;
  authenticated.padding = sgk::kCanonicalV2OverlayMarker;
  assert(sgk::canonicalEventRequiresCommitReceipt(authenticated));
  authenticated.padding = 0;
  assert(!sgk::canonicalEventRequiresCommitReceipt(authenticated));
  authenticated.is_canonical = 0;
  assert(!sgk::canonicalEventRequiresCommitReceipt(authenticated));
  mixedSession(false);
  mixedSession(true);
  Storage storage;
  sgk::OfflineEventQueue audit(&storage);
  audit.begin();
  for (unsigned i = 1; i <= 8; ++i) assert(audit.push(canonical("ACCESS_ARMED", i)));
  const auto records_before = storage.records;
  const auto metas_before = storage.metas;
  assert(!audit.push(canonical("ACCESS_SESSION_TERMINATED", 9)));
  assert(!audit.pushEvent("legacy_overflow", "must not displace audit", 100));
  assert(audit.backpressureCount() == 2);
  assert(audit.overflowCount() == 0);
  assert(std::memcmp(records_before.data(), storage.records.data(), sizeof(records_before)) == 0);
  assert(std::memcmp(metas_before.data(), storage.metas.data(), sizeof(metas_before)) == 0);
  sgk::OfflineEventQueue restored(&storage);
  restored.begin();
  for (unsigned i = 1; i <= 8; ++i) {
    sgk::CanonicalEvent event{};
    assert(restored.popFront(&event));
    assert(event.sequence == i);
  }
  assert(restored.push(canonical("ACCESS_SESSION_TERMINATED", 9)));
  std::puts("normal/timeout mixed flows and canonical backpressure passed");
}
