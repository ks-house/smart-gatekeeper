#include "MqttConnectionJson.h"
#include "NetworkRecoveryJson.h"
#include "BleAdvertisementJson.h"
#include "RearmHistoryJson.h"
#include "AccessEvidenceJson.h"
#include <cassert>
#include <cstdio>
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

  struct Advertisement {
    bool primary_applied = true, response_applied = true;
    uint32_t payload_generation = UINT32_MAX, applied_generation = UINT32_MAX;
    uint32_t refresh_count = UINT32_MAX, last_apply_ms = 0;
    uint32_t primary_apply_failures = UINT32_MAX, response_apply_failures = UINT32_MAX;
    uint8_t primary_length = 31, response_length = 31;
    uint32_t refresh_interval_ms = UINT32_MAX;
    const char* last_error = "RESPONSE_ENCODING_FAILED";
  } advertisement;
  StaticJsonDocument<2048> adv;
  adv["signed_state"] = "unchanged";
  const auto adv_before = measureJson(adv);
  assert(sgk::appendBleAdvertisementJson(adv, advertisement, UINT32_MAX, 7936));
  assert(!adv.overflowed() && measureJson(adv) - adv_before < 640);
  assert(adv["ble_advertisement"]["last_apply_age_ms"].as<uint32_t>() == UINT32_MAX);
  assert(adv["signed_state"] == "unchanged");
  assert(!sgk::appendBleAdvertisementJson(small, advertisement, 0, 7936));
  assert(!small.overflowed() && !small.containsKey("ble_advertisement"));
  assert(!sgk::appendBleAdvertisementJson(short_wire, advertisement, 0, 640));
  assert(!short_wire.overflowed() && !short_wire.containsKey("ble_advertisement"));
  adv.clear();
  advertisement.applied_generation = 0;
  advertisement.last_error = nullptr;
  assert(sgk::appendBleAdvertisementJson(adv, advertisement, 0, 7936));
  assert(adv["ble_advertisement"]["last_apply_age_ms"].isNull());
  assert(adv["ble_advertisement"]["last_error"] == "NONE");

  sgk::RearmHistory history;
  for (int i = 0; i < 4; ++i)
    history.record(UINT32_MAX - i, sgk::RearmEdgeKind::kCleared, sgk::RearmEdgeReason::kClear, 3);
  history.sequence = UINT32_MAX;
  history.last_clear_ms = UINT32_MAX;
  StaticJsonDocument<2048> rearm;
  rearm.createNestedObject("passage_rearm")["blocked"] = false;
  rearm["signed_state"] = "unchanged";
  const auto rearm_before = measureJson(rearm);
  const auto rearm_pool = rearm.memoryUsage();
  assert(sgk::appendRearmHistoryJson(rearm, history, 7936));
  assert(!rearm.overflowed() && measureJson(rearm) - rearm_before < 256);
  assert(rearm.memoryUsage() - rearm_pool <= JSON_OBJECT_SIZE(6) + JSON_ARRAY_SIZE(4) + 4 * 17);
  assert(rearm["passage_rearm"]["history"]["edges"][0] == "4294967295,3,5,3");
  assert(rearm["passage_rearm"]["history"]["edges"][3] == "4294967292,3,5,3");
  assert(rearm["signed_state"] == "unchanged");
  std::string rearm_wire;
  serializeJson(rearm, rearm_wire);
  history = {};
  std::string after_reset;
  serializeJson(rearm, after_reset);
  assert(rearm_wire == after_reset); // JSON owns copies, even after the ring changes.
  StaticJsonDocument<JSON_OBJECT_SIZE(2)> rearm_small;
  rearm_small.createNestedObject("passage_rearm")["blocked"] = false;
  assert(!sgk::appendRearmHistoryJson(rearm_small, history, 7936));
  assert(!rearm_small.overflowed() && !rearm_small["passage_rearm"].containsKey("history"));
  rearm.clear();
  rearm.createNestedObject("passage_rearm")["blocked"] = false;
  assert(!sgk::appendRearmHistoryJson(rearm, history, 256));
  assert(!rearm.overflowed() && !rearm["passage_rearm"].containsKey("history"));
  assert(sgk::appendRearmHistoryJson(rearm, history, 7936));
  assert(rearm["passage_rearm"]["history"]["last_clear_ms"].isNull());
  assert(rearm["passage_rearm"]["history"]["edges"].size() == 0);
  sgk::DeferredAccessHealth evidence;
  evidence.transport_aborts = UINT32_MAX;
  evidence.depth = 16;
  evidence.head_age_ms = evidence.head_retries = evidence.retry_count = UINT32_MAX;
  evidence.invalid_count = evidence.overflow_count = UINT32_MAX;
  evidence.evidence_gap = evidence.stalled = true;
  evidence.last_failure = sgk::AccessDeliveryFailure::kDownstream;
  StaticJsonDocument<2048> audit;
  audit["signed_state"] = "unchanged";
  const auto audit_before = measureJson(audit);
  assert(sgk::appendAccessEvidenceJson(audit, evidence, UINT32_MAX, UINT32_MAX, 7936));
  assert(!audit.overflowed() && measureJson(audit) - audit_before < 480);
  assert(audit["signed_state"] == "unchanged");
  assert(audit["access_evidence"]["last_failure"] == "DOWNSTREAM_RETRY");
  assert(!sgk::appendAccessEvidenceJson(small, evidence, 0, 0, 7936));
  assert(!small.overflowed() && !small.containsKey("access_evidence"));
  assert(!sgk::appendAccessEvidenceJson(short_wire, evidence, 0, 0, 480));
  assert(!short_wire.overflowed() && !short_wire.containsKey("access_evidence"));
  // Eight saturated counters have a fixed slot/wire budget. Insufficient pool
  // or wire room must leave existing signed status and optional groups intact.
  sgk::NetworkRecoveryController::Diagnostics recovery;
  recovery.started = recovery.completed = recovery.rejected = recovery.timeouts =
      recovery.cancelled = recovery.deferred = recovery.reserve_failures =
      recovery.commit_failures = UINT32_MAX;
  StaticJsonDocument<JSON_OBJECT_SIZE(12)> recovery_doc;
  recovery_doc["signed_state"] = "unchanged";
  const auto recovery_before = measureJson(recovery_doc);
  const auto recovery_pool = recovery_doc.memoryUsage();
  assert(sgk::appendNetworkRecoveryJson(recovery_doc, recovery, false, 7936));
  assert(!recovery_doc.overflowed());
  assert(recovery_doc.memoryUsage() - recovery_pool == JSON_OBJECT_SIZE(11));
  assert(measureJson(recovery_doc) - recovery_before == 239);
  std::printf("network recovery JSON max_growth=239 pool_growth=%zu\n",
              recovery_doc.memoryUsage() - recovery_pool);
  assert(recovery_doc["network_recovery"].size() == 10);
  assert(recovery_doc["network_recovery"]["schema"] == 1);
  assert(recovery_doc["network_recovery"]["active"] == false);
  assert(recovery_doc["network_recovery"]["commit_failures"].as<uint32_t>() == UINT32_MAX);
  assert(recovery_doc["signed_state"] == "unchanged");
  std::string recovery_wire;
  serializeJson(recovery_doc, recovery_wire);
  recovery = {};
  std::string recovery_after;
  serializeJson(recovery_doc, recovery_after);
  assert(recovery_wire == recovery_after);  // JSON owns numeric values.
  StaticJsonDocument<JSON_OBJECT_SIZE(11)> recovery_small;
  recovery_small["signed_state"] = "unchanged";
  const auto small_pool = recovery_small.memoryUsage();
  std::string small_before, small_after;
  serializeJson(recovery_small, small_before);
  assert(!sgk::appendNetworkRecoveryJson(recovery_small, recovery, true, 7936));
  serializeJson(recovery_small, small_after);
  assert(small_before == small_after && recovery_small.memoryUsage() == small_pool);
  assert(!recovery_small.overflowed());
  StaticJsonDocument<2048> recovery_short_wire;
  recovery_short_wire["signed_state"] = "unchanged";
  const size_t base_wire = measureJson(recovery_short_wire);
  const size_t base_pool = recovery_short_wire.memoryUsage();
  std::string short_before, short_after;
  serializeJson(recovery_short_wire, short_before);
  assert(!sgk::appendNetworkRecoveryJson(recovery_short_wire, recovery, true, base_wire + 256));
  serializeJson(recovery_short_wire, short_after);
  assert(short_before == short_after && recovery_short_wire.memoryUsage() == base_pool);
  assert(!recovery_short_wire.overflowed());
  assert(sgk::appendNetworkRecoveryJson(recovery_short_wire, recovery, true, base_wire + 257));
  assert(recovery_short_wire["network_recovery"]["active"] == true);
  StaticJsonDocument<0> overflow;
  overflow["cannot_fit"] = 1;
  assert(overflow.overflowed());
  assert(!sgk::appendNetworkRecoveryJson(overflow, recovery, false, 7936));
  assert(!overflow.containsKey("network_recovery"));

}
