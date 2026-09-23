#pragma once

#include <ArduinoJson.h>
#include <cstdio>
#include "PassageRearmPolicy.h"

namespace sgk {
// Append last: optional history must never crowd out signed status/OTA evidence.
template <typename Document>
bool appendRearmHistoryJson(Document& doc, const RearmHistory& h, size_t payload_capacity) {
  constexpr size_t pool_bytes = JSON_OBJECT_SIZE(6) + JSON_ARRAY_SIZE(4) + 4 * 17;
  constexpr size_t wire_bytes = 256;
  if (doc.overflowed() || doc.capacity() - doc.memoryUsage() < pool_bytes ||
      measureJson(doc) + wire_bytes >= payload_capacity ||
      !doc["passage_rearm"].template is<JsonObject>()) return false;
  JsonObject history = doc["passage_rearm"].template as<JsonObject>().createNestedObject("history");
  history["schema"] = 1;
  history["sequence"] = h.sequence;
  history["overwritten"] = h.sequence - h.count;
  if (h.has_clear) history["last_clear_ms"] = h.last_clear_ms;
  else history["last_clear_ms"] = nullptr;
  JsonArray edges = history.createNestedArray("edges");
  for (uint8_t i = 0; i < h.count; ++i) {
    const auto& edge = h.edges[i];
    // Mutable array is copied into the JSON pool; no dangling stack pointer.
    char encoded[24];
    snprintf(encoded, sizeof(encoded), "%lu,%u,%u,%u",
             static_cast<unsigned long>(edge.at_ms), static_cast<unsigned>(edge.kind),
             static_cast<unsigned>(edge.reason), edge.prior_clear_samples);
    edges.add(encoded);
  }
  return true;
}
}  // namespace sgk
