// Host-only platform seams. Production sink, wire serializer and receipt
// consumer are inserted verbatim; no broker, GPIO or field secret is used.
#include "AccessEventReceipt.h"
#include "FlatJsonObjectPolicy.h"
#include <iostream>
#include <string>
using String = std::string;

class MemoryQueueStorage final : public sgk::OfflineQueueStorage {
 public:
  std::array<sgk::CanonicalEvent, sgk::OfflineEventQueue::kCapacity> records{};
  std::array<sgk::QueueMetaRecord, 2> meta{};
  bool fail = false;
  bool saveRecord(size_t slot, const sgk::CanonicalEvent& value) override {
    if (fail) return false;
    records[slot] = value; return true;
  }
  bool readRecord(size_t slot, sgk::CanonicalEvent* value) override {
    *value = records[slot]; return true;
  }
  bool saveMetaRecord(uint8_t slot, const sgk::QueueMetaRecord& value) override {
    if (fail) return false;
    meta[slot] = value; return true;
  }
  bool readMetaRecord(uint8_t slot, sgk::QueueMetaRecord* value) override {
    *value = meta[slot]; return true;
  }
  bool clearStorage() override { records = {}; meta = {}; return true; }
} queueStorage;
class MemorySensorStorage final : public sgk::SensorSummaryStorage {
 public:
  std::array<std::vector<uint8_t>, 2> slots{};
  bool fail = false;
  size_t read(uint8_t slot, void* output, size_t capacity) override {
    if (slots[slot].size() > capacity) return 0;
    std::memcpy(output, slots[slot].data(), slots[slot].size());
    return slots[slot].size();
  }
  bool write(uint8_t slot, const void* bytes, size_t length) override {
    if (fail) return false;
    const auto* p = static_cast<const uint8_t*>(bytes);
    slots[slot].assign(p, p + length); return true;
  }
} sensorStorage;

sgk::SensorSummaryQueue sensorSummaryQueue(&sensorStorage);
std::array<uint8_t, 32> accessEvidenceKey{};
const char* accessEvidenceTargetId = "test-target";
uint32_t auditPublishRetryAtMs = 0, auditReceiptsAccepted = 0, auditReceiptRejected = 0;
std::string eventTopic = "unused-host-only", published;
bool peekEventOutbox(sgk::CanonicalEvent*) { return false; }
void popEventOutbox() { assert(false); }
bool MqttManager::publishCanonicalEvent(const char* payload) {
  published = payload; return true;
}
bool MqttManager::publishPacket(const char*, const char*, bool, size_t, const char*) {
  assert(false); return false;
}

// MQTT_HELPERS
// RECEIPT_CONSUMER

bool wire(const sgk::CanonicalEvent& evt) {
  // EVENT_SERIALIZER
  return publishEventRecord(evt);
}
void sensorDocument(JsonDocument& doc) {
  // SENSOR_SERIALIZER
}
void restartQueues() {
  g_offline_queue = sgk::OfflineEventQueue(&queueStorage);
  g_offline_queue.begin();
  sensorSummaryQueue = sgk::SensorSummaryQueue(&sensorStorage);
  sensorSummaryQueue.begin();
}
void snapshot() {
  StaticJsonDocument<3072> doc;
  doc["events_pending"] = g_offline_queue.size();
  doc["sensor_pending"] = sensorSummaryQueue.size();
  doc["accepted"] = auditReceiptsAccepted;
  doc["rejected"] = auditReceiptRejected;
  sgk::CanonicalEvent head{};
  if (g_offline_queue.peekFront(&head)) {
    assert(wire(head));
    doc["head_wire"] = published;
  } else doc["head_wire"] = nullptr;
  sensorDocument(doc);
  std::string output;
  serializeJson(doc, output);
  std::cout << output << std::endl;
}
int main() {
  produce();
  for (size_t i = 0; i < accessEvidenceKey.size(); ++i)
    accessEvidenceKey[i] = static_cast<uint8_t>(i + 1);
  g_offline_queue.setStorage(&queueStorage);
  g_offline_queue.begin();
  uint64_t last_sequence = 0;
  for (const auto& event : MqttManager::attempted) {
    if (event.sequence == last_sequence) continue;  // Same failed enqueue retry.
    assert(g_offline_queue.push(event));
    last_sequence = event.sequence;
    assert(wire(event));
    std::cout << published << std::endl;
  }
  const auto& terminal = MqttManager::attempted.back();
  sgk::SensorSummaryRecord sensor{};
  sensor.summary = MqttManager::summary;
  sensor.source_boot_count = terminal.boot_count;
  sensor.terminal_sequence = terminal.sequence;
  assert(std::strlen(terminal.source_boot_id) == 32);
  std::memcpy(sensor.source_boot_id, terminal.source_boot_id, 33);
  std::snprintf(sensor.session_id, sizeof(sensor.session_id), "%s", terminal.session_id);
  std::snprintf(sensor.key_id, sizeof(sensor.key_id), "%s", ACCESS_EVENT_REF_KEY_ID);
  assert(sgk::deriveSensorSummaryMac(accessEvidenceKey, accessEvidenceTargetId, sensor, sensor.tag));
  assert(sensorSummaryQueue.push(sensor));
  restartQueues();  // Real queue recovery from its persisted bytes, no live MCU.
  snapshot();
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line == "restart") restartQueues();
    else if (line == "fail_storage") queueStorage.fail = sensorStorage.fail = true;
    else if (line == "restore_storage") queueStorage.fail = sensorStorage.fail = false;
    else if (line != "peek")
      (void)consumeDiagnosticReceipt(reinterpret_cast<const uint8_t*>(line.data()), line.size());
    snapshot();
  }
}
