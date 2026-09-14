#pragma once

#include <ArduinoJson.h>
#include <cstdint>

namespace sgk {
// Optional controller-application evidence, not an over-the-air observation.
// Append after required signed/OTA fields; preserve them on budget exhaustion.
template <typename Document, typename Diagnostics>
bool appendBleAdvertisementJson(Document& doc, const Diagnostics& d,
                                uint32_t now, size_t payload_capacity) {
  constexpr size_t pool_bytes = JSON_OBJECT_SIZE(15);
  constexpr size_t wire_bytes = 640;
  if (doc.overflowed() || doc.capacity() - doc.memoryUsage() < pool_bytes ||
      measureJson(doc) + wire_bytes >= payload_capacity) return false;
  JsonObject value = doc.createNestedObject("ble_advertisement");
  value["schema"] = 1;
  value["primary_applied"] = d.primary_applied;
  value["response_applied"] = d.response_applied;
  value["payload_generation"] = d.payload_generation;
  value["applied_generation"] = d.applied_generation;
  value["refresh_count"] = d.refresh_count;
  if (d.applied_generation != 0) value["last_apply_age_ms"] = now - d.last_apply_ms;
  else value["last_apply_age_ms"] = nullptr;
  value["primary_apply_failures"] = d.primary_apply_failures;
  value["response_apply_failures"] = d.response_apply_failures;
  value["primary_length"] = d.primary_length;
  value["response_length"] = d.response_length;
  value["refresh_interval_ms"] = d.refresh_interval_ms;
  value["last_error"] = d.last_error != nullptr ? d.last_error : "NONE";
  return true;
}
}  // namespace sgk
