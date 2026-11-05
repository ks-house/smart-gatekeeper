#pragma once

#include <ArduinoJson.h>
#include "NetworkRecoveryController.h"

namespace sgk {
// Optional, unsigned boot-local counters. Fixed borrowed keys and numeric values
// need no copied strings; insufficient room must leave signed status untouched.
template <typename Document>
bool appendNetworkRecoveryJson(
    Document& doc, const NetworkRecoveryController::Diagnostics& diagnostics,
    bool active, size_t payload_capacity) {
  constexpr size_t pool_bytes = JSON_OBJECT_SIZE(11);  // Parent + ten fields.
  constexpr size_t wire_bytes = 256;  // Executable saturated-U32 bound.
  if (doc.overflowed() || doc.capacity() - doc.memoryUsage() < pool_bytes ||
      measureJson(doc) + wire_bytes >= payload_capacity) return false;
  JsonObject recovery = doc.createNestedObject("network_recovery");
  recovery["schema"] = 1;
  recovery["active"] = active;
  recovery["started"] = diagnostics.started;
  recovery["completed"] = diagnostics.completed;
  recovery["rejected"] = diagnostics.rejected;
  recovery["timeouts"] = diagnostics.timeouts;
  recovery["cancelled"] = diagnostics.cancelled;
  recovery["deferred"] = diagnostics.deferred;
  recovery["reserve_failures"] = diagnostics.reserve_failures;
  recovery["commit_failures"] = diagnostics.commit_failures;
  return true;
}
}  // namespace sgk
