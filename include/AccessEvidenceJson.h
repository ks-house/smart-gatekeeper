#pragma once
#include <ArduinoJson.h>
#include "DeferredAccessQueue.h"

namespace sgk {
// Optional unsigned fields appended after signed/OTA evidence, with admission.
template <typename Document>
bool appendAccessEvidenceJson(Document& doc, const DeferredAccessHealth& h,
                              uint32_t capture_age, uint32_t orphaned,
                              size_t payload_capacity) {
  constexpr size_t pool_bytes = JSON_OBJECT_SIZE(14);
  constexpr size_t wire_bytes = 480;
  if (doc.overflowed() || doc.capacity() - doc.memoryUsage() < pool_bytes ||
      measureJson(doc) + wire_bytes >= payload_capacity) return false;
  JsonObject evidence = doc.createNestedObject("access_evidence");
  evidence["schema"] = 1;
  evidence["transport_aborts"] = h.transport_aborts;
  evidence["deferred_depth"] = h.depth;
  evidence["head_age_ms"] = h.head_age_ms;
  evidence["head_retries"] = h.head_retries;
  evidence["retry_count"] = h.retry_count;
  evidence["invalid_count"] = h.invalid_count;
  evidence["overflow_count"] = h.overflow_count;
  evidence["evidence_gap"] = h.evidence_gap || orphaned != 0;
  evidence["stalled"] = h.stalled;
  evidence["last_failure"] = accessDeliveryFailureName(h.last_failure);
  evidence["capture_oldest_age_ms"] = capture_age;
  evidence["capture_orphaned"] = orphaned;
  return true;
}
}  // namespace sgk
