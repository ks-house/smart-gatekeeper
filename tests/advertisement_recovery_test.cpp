#include "AdvertisementPayload.h"
#include "PresenceAdvertisementPolicy.h"

#include <cassert>
#include <cstring>
#include <cstdio>

// Controller model deliberately allows active=true with both custom data lost.
class Radio final : public sgk::PresenceAdvertisementDriver {
 public:
  bool present = true, running = false;
  bool primary_ok = true, response_ok = true, start_ok = true, stop_ok = true;
  bool start_lies = false, reject_live = false;
  bool primary_installed = false, response_installed = false;
  uint32_t applies = 0, starts = 0, stops = 0;
  sgk::AdvertisementPayload primary{}, response{};
  bool available() const override { return present; }
  bool active() const override { return running; }
  bool apply(bool ready, uint32_t epoch) override {
    ++applies;
    if (!primary_ok || (reject_live && running)) return false;
    primary = sgk::primaryAdvertisement(9);
    primary_installed = true;
    if (!response_ok) return false;
    response = sgk::responseAdvertisement(true, ready, epoch);
    response_installed = true;
    return true;
  }
  bool start() override {
    ++starts;
    // A policy must never knowingly restart partial or missing payloads.
    assert(primary_installed && response_installed);
    if (!start_ok) return false;
    running = !start_lies;
    return true;
  }
  bool stop() override {
    ++stops;
    if (!stop_ok) return false;
    running = false;
    return true;
  }
  void hostSyncWithLostData() {
    primary_installed = response_installed = false;
    primary = {}; response = {};
    running = true;  // vendor automatic start loses all custom bytes
  }
  uint32_t mutations() const { return applies + starts + stops; }
};

static void goldenBytes() {
  const uint8_t expected[] = {2, 1, 0x1a, 26, 0xff, 0x4c, 0,
      2, 0x15, 0xa1, 0xb2, 0xc3, 0xd4, 0xe5, 0xf6, 0x78, 0x90,
      0xab, 0xcd, 0xef, 0x12, 0x34, 0x56, 0x78, 0x90, 0, 1, 0, 1, 0xce};
  const auto primary = sgk::primaryAdvertisement(9);
  assert(primary.length == sizeof(expected));
  assert(std::memcmp(primary.bytes.data(), expected, sizeof(expected)) == 0);
  const uint8_t expected_response[] = {4, 9, 'S', 'G', 'K', 23, 0x21,
      0x31, 0x4b, 0x47, 0x53, 0x4d, 0x6f, 0x54, 0x9c,
      0xb1, 0x4f, 0x9e, 0x7d, 0, 0x10, 0x4d, 0x9f,
      1, 1, 0x78, 0x56, 0x34, 0x12};
  const auto response = sgk::responseAdvertisement(true, true, 0x12345678);
  assert(response.length == sizeof(expected_response));
  assert(std::memcmp(response.bytes.data(), expected_response, response.length) == 0);
  for (bool enabled : {false, true}) {
    const auto bytes = sgk::responseAdvertisement(enabled, false, UINT32_MAX);
    assert(bytes.length <= 31);
    size_t offset = 0;
    while (offset < bytes.length) offset += bytes.bytes[offset] + 1;
    assert(offset == bytes.length); // every AD field fits, no silent truncation
    if (!enabled) {
      assert(bytes.length == 17);
      assert(std::memcmp(bytes.bytes.data() + 2, "SmartGatekeeper", 15) == 0);
    }
  }
}

static void failures() {
  for (int stage = 0; stage < 3; ++stage) {
    sgk::PresenceAdvertisementPolicy policy;
    Radio radio;
    radio.primary_ok = stage != 0;
    radio.response_ok = stage != 1;
    radio.start_ok = stage != 2;
    policy.request(true, 42);
    policy.service(0, true, false, false, radio);
    assert(policy.pending && !policy.applied_valid && policy.failures == 1);
    assert(policy.applied_generation == 0 && !radio.running);
    assert(radio.starts == (stage == 2 ? 1U : 0U));
    const auto mutations = radio.mutations();
    policy.request(false, 43, true);
    policy.service(499, true, false, false, radio);
    assert(radio.mutations() == mutations); // force cannot bypass backoff
    radio.primary_ok = radio.response_ok = radio.start_ok = true;
    policy.service(500, true, false, false, radio);
    assert(policy.applied_valid && !policy.pending && !policy.applied_ready);
    assert(policy.applied_epoch == 43 && policy.applied_generation == 2);
  }
  sgk::PresenceAdvertisementPolicy policy;
  Radio radio;
  radio.start_lies = true;
  policy.request(true, 1);
  policy.service(0, true, false, false, radio);
  assert(!policy.applied_valid && policy.pending);
  assert(std::strcmp(policy.last_result, "INACTIVE_AFTER_START") == 0);
}

static void lostWhileActiveAndLeased() {
  for (bool reject_live : {false, true}) {
    sgk::PresenceAdvertisementPolicy policy;
    Radio radio;
    policy.request(true, 5);
    policy.service(100, true, false, false, radio);
    radio.hostSyncWithLostData();
    radio.reject_live = reject_live;
    policy.service(30099, true, false, false, radio);
    assert(!radio.primary_installed && policy.refresh_count == 0);
    const auto mutations = radio.mutations();
    policy.service(30100, true, true, false, radio);
    policy.service(60100, true, false, true, radio);
    policy.service(90100, false, false, false, radio);
    assert(policy.pending && !policy.applied_valid && radio.mutations() == mutations);
    policy.service(90101, true, false, false, radio);
    if (reject_live) {
      assert(policy.pending && !policy.applied_valid);
      radio.stop_ok = false;
      policy.service(90601, true, false, false, radio);
      assert(std::strcmp(policy.last_result, "STOP_FAILED") == 0);
      radio.stop_ok = true;
      policy.service(91601, true, false, false, radio);
      assert(radio.stops == 2 && radio.starts == 2);
    }
    assert(radio.running && radio.primary_installed && radio.response_installed);
    assert(policy.applied_valid && !policy.pending && policy.refresh_count == 1);
    assert(radio.primary.length == 30 && radio.response.length == 29);
    // Advertising stopped after a connection, without any ready/epoch change.
    radio.running = false;
    policy.service(92000, true, false, false, radio);
    assert(radio.running && policy.applied_valid && !policy.pending);
  }
}

static void rolloverAndBoundedRetry() {
  sgk::PresenceAdvertisementPolicy policy;
  Radio radio;
  const uint32_t origin = UINT32_MAX - 100;
  policy.request(true, 1);
  radio.primary_ok = false;
  policy.service(origin, true, false, false, radio);
  policy.service(origin + 499, true, false, false, radio);
  assert(policy.attempts == 1);
  radio.primary_ok = true;
  policy.service(origin + 500, true, false, false, radio);
  assert(policy.applied_valid && policy.attempts == 2);
  // A second fixture places the 30-second refresh itself across rollover.
  policy = {}; radio = {};
  policy.request(true, 1);
  policy.service(origin, true, false, false, radio);
  radio.hostSyncWithLostData();
  policy.service(origin + 29999, true, false, false, radio);
  assert(!radio.primary_installed);
  policy.service(origin + 30000, true, false, false, radio);
  assert(radio.primary_installed && policy.refresh_count == 1);
  radio.primary_ok = false;
  policy.request(false, 2);
  for (uint32_t ms = 40000; ms < 100000; ++ms) {
    policy.request(false, ms, true);
    policy.service(ms, true, false, false, radio);
  }
  assert(policy.failures <= 16 && policy.pending && !policy.applied_valid);
  const auto starts = radio.starts;
  policy.attempts = policy.failures = policy.retries = UINT32_MAX;
  policy.service(110000, true, false, false, radio);
  assert(policy.attempts == UINT32_MAX && policy.failures == UINT32_MAX);
  assert(radio.starts == starts);
}

int main() {
  goldenBytes(); failures(); lostWhileActiveAndLeased(); rolloverAndBoundedRetry();
  std::puts("advertisement recovery: golden bytes, apply/start/stop faults, active data loss, leases, wrap and bounded retry passed");
}
