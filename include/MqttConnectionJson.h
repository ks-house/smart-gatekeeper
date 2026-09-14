#pragma once

#include <ArduinoJson.h>
#include "MqttConnectionPolicy.h"

namespace sgk {
// Optional advisory must never overflow/drop the existing signed status.
// All keys, reason names and ring strings are borrowed until immediate
// serialization by the main owner. No copied strings consume the JSON pool.
template <typename Document>
bool appendMqttConnectionJson(Document& doc, const MqttConnectionDiagnostics& d,
                              uint32_t retry_ms, uint32_t now,
                              size_t payload_capacity) {
  constexpr size_t pool_bytes = JSON_OBJECT_SIZE(16) + JSON_ARRAY_SIZE(4);
  constexpr size_t wire_bytes = 1024; // Executable maximum-value regression.
  if (doc.overflowed() || doc.capacity() - doc.memoryUsage() < pool_bytes ||
      measureJson(doc) + wire_bytes >= payload_capacity) return false;
  JsonObject connection = doc.createNestedObject("mqtt_connection");
  connection["schema"] = 1;
  connection["generation"] = d.generation;
  connection["disconnects"] = d.disconnects;
  connection["planned_disconnects"] = d.planned_disconnects;
  connection["last_reason"] = mqttLossName(d.last_reason);
  connection["last_error"] = d.last_error;
  connection["last_disconnect_ms"] = d.last_disconnect_ms;
  connection["last_connected_ms"] = d.last_connected_ms;
  connection["last_connection_duration_ms"] = d.last_connection_duration_ms;
  connection["retry_in_ms"] = retry_ms;
  connection["loop_gap_max_ms"] = d.loop_gap_max_ms;
  connection["flapping"] = d.flapping(now);
  connection["edge_sequence"] = d.edge_sequence;
  connection["edge_overwritten"] = d.edge_overwritten;
  JsonArray edges = connection.createNestedArray("edges");
  for (size_t i = 0; i < d.size(); ++i) edges.add(d.edge(i));
  return true;
}
} // namespace sgk
