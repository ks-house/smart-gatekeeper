// Platform seams only. The production CanonicalMqttEventSink class is inserted
// verbatim by test_gatt_evidence_delivery.py; conversion/signing is not copied.
#include <ArduinoJson.h>
#include "GattProtocol.h"
#include "OfflineEventQueue.h"
#include "DeferredAccessQueue.h"
#include "SensorSessionDiagnostics.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>

#define LOGF(...) ((void)0)
const char* API_KEY = "synthetic-api";
const char* ACCESS_EVENT_REF_KEY_HEX = "0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20";
const char* ACCESS_EVENT_REF_KEY_ID = "a1";
struct mbedtls_md_info_t {};
constexpr int MBEDTLS_MD_SHA256 = 1;
const mbedtls_md_info_t* mbedtls_md_info_from_type(int) { static mbedtls_md_info_t v; return &v; }
int mbedtls_md_hmac(const mbedtls_md_info_t*, const uint8_t*, size_t,
                    const uint8_t*, size_t, uint8_t* out) {
  std::memset(out, 1, 32); return 0; // Target pseudonym seam only.
}
uint32_t random_calls = 0;
void esp_fill_random(void* output, size_t length) {
  std::memset(output, ++random_calls, length);
}
uint32_t challenges_issued_, proofs_verified_, proofs_rejected_, armed_entries_,
    sensor_detections_, relay_on_count_, relay_off_count_, terminal_count_;
void noteDiagnosticStage(const char*, const char*, uint32_t* counter = nullptr) {
  if (counter != nullptr) ++*counter;
}
struct DiagnosticsManager {
  static const char* targetId() { return "test-target"; }
  static const char* bootId() { return "00112233445566778899aabbccddeeff"; }
  static uint64_t bootCount() { return 782; }
};
sgk::SensorSessionTracker captures;
struct MqttManager {
  static bool fail;
  static std::vector<sgk::CanonicalEvent> attempted;
  static uint32_t terminals;
  static sgk::SensorSessionSummary summary;
  static bool enqueueCanonicalEvent(const sgk::CanonicalEvent& event) {
    attempted.push_back(event);
    return !fail && sgk::isValidCanonicalEventRecord(event);
  }
  static void noteAccessTerminal(const char*, uint64_t, const char*, const char*,
                                 const char*, uint16_t, uint64_t terminal_ms) {
    ++terminals;
    assert(captures.take(terminal_ms, &summary));
  }
};
bool MqttManager::fail = true;
std::vector<sgk::CanonicalEvent> MqttManager::attempted;
uint32_t MqttManager::terminals = 0;
sgk::SensorSessionSummary MqttManager::summary;

// PRODUCTION_SINK

int main() {
  CanonicalMqttEventSink sink;
  std::array<uint8_t, 16> door{};
  door[0] = 1;
  assert(sink.configure(door));
  sgk::Event event{};
  event.code = sgk::EventCode::kAccessProofVerified;
  event.reason = sgk::EventReason::kProofValid;
  event.session_id[0] = 2;
  event.credential_id.fill(3);
  event.sequence = 1;
  event.monotonic_ms = 100;
  auto invalid = event;
  invalid.session_id = {};
  assert(sink.tryEmit(invalid) == sgk::AccessDeliveryResult::kInvalid);
  assert(MqttManager::attempted.empty());
  invalid = event;
  invalid.code = sgk::EventCode::kAccessProofRejected;
  invalid.transport_reason = sgk::ResultReason::kInternalFailClosed;
  assert(sink.tryEmit(invalid) == sgk::AccessDeliveryResult::kInvalid);
  for (int i = 0; i < 3; ++i)
    assert(sink.tryEmit(event) == sgk::AccessDeliveryResult::kRetry);
  assert(random_calls == 1 && proofs_verified_ == 0 && MqttManager::terminals == 0);
  MqttManager::fail = false;
  assert(sink.tryEmit(event) == sgk::AccessDeliveryResult::kAccepted);
  assert(random_calls == 1 && proofs_verified_ == 1);
  for (const auto& attempt : MqttManager::attempted)
    assert(std::memcmp(&attempt, &MqttManager::attempted[0], sizeof(attempt)) == 0);
  captures.begin(100, 500, false);
  assert(captures.finish(200, false, sgk::SensorClearanceState::kClear));
  const auto codes = {sgk::EventCode::kAccessArmed, sgk::EventCode::kAccessSensorDetected,
      sgk::EventCode::kAccessRelayOn, sgk::EventCode::kAccessRelayOff,
      sgk::EventCode::kAccessSessionCompleted};
  for (auto code : codes) {
    event.code = code;
    event.has_causation = true;
    event.causation_sequence = event.sequence++;
    event.monotonic_ms = code == sgk::EventCode::kAccessSessionCompleted ? 200 : 150;
    const auto previous = MqttManager::attempted.back();
    assert(sink.tryEmit(event) == sgk::AccessDeliveryResult::kAccepted);
    const auto& accepted = MqttManager::attempted.back();
    assert(accepted.has_causation);
    assert(std::strcmp(previous.event_id, accepted.causation_event_id) == 0);
    assert(std::strcmp(previous.session_id, accepted.session_id) == 0);
  }
  assert(MqttManager::terminals == 1 && terminal_count_ == 1 && captures.pending() == 0);
  assert(MqttManager::summary.ended_monotonic_ms == 200);
  std::puts("production sink retry identity and sensor terminal passed");
}
