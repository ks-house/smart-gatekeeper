#include "MqttConnectionJson.h"
#include <cassert>
#include <string>

int main() {
  sgk::MqttConnectionDiagnostics d;
  d.generation = d.disconnects = d.planned_disconnects = UINT32_MAX;
  d.last_connected_ms = d.last_disconnect_ms = d.loop_gap_max_ms = UINT32_MAX;
  d.edge_sequence = UINT32_MAX - 4;
  d.edge_overwritten = UINT32_MAX;
  for (int i = 0; i < 4; ++i) {
    d.adopted(0);
    d.record(sgk::MqttLossReason::kAvailabilityFailed, -128, UINT32_MAX,
             UINT32_MAX, UINT32_MAX, UINT32_MAX);
  }
  StaticJsonDocument<2048> doc;
  doc["signed_state"] = "unchanged";
  const auto before = measureJson(doc);
  const auto pool = doc.memoryUsage();
  assert(sgk::appendMqttConnectionJson(doc, d, UINT32_MAX, UINT32_MAX, 7936));
  assert(!doc.overflowed() && measureJson(doc) - before < 1024);
  assert(doc.memoryUsage() - pool == JSON_OBJECT_SIZE(16) + JSON_ARRAY_SIZE(4));
  assert(doc["mqtt_connection"]["edges"].size() == 4);
  std::string wire;
  serializeJson(doc, wire);
  // A queued status owns its serialized bytes even after the ring changes.
  const auto copy = wire;
  d.record(sgk::MqttLossReason::kLoopFailed, -3, 4, 1, 1, 0);
  assert(wire == copy);

  StaticJsonDocument<JSON_OBJECT_SIZE(1)> small;
  small["signed_state"] = "unchanged";
  assert(!sgk::appendMqttConnectionJson(small, d, 0, 0, 7936));
  assert(!small.overflowed() && small["signed_state"] == "unchanged");
  StaticJsonDocument<2048> short_wire;
  short_wire["signed_state"] = "unchanged";
  assert(!sgk::appendMqttConnectionJson(short_wire, d, 0, 0, 1024));
  assert(!short_wire.overflowed() && !short_wire.containsKey("mqtt_connection"));
}
