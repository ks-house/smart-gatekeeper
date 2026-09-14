#include "MqttConnectionPolicy.h"

#include <cassert>
#include <cstdio>
#include <cstring>
#include <limits>

int main() {
  using namespace sgk;
  // All combinations, not just presence of names in the integration source.
  for (int bits = 0; bits < 32; ++bits) {
    bool stale = bits & 1, same = bits & 2, wifi = bits & 4;
    bool success = bits & 8, alive = bits & 16;
    auto expected = stale || !same || !wifi ? MqttAdoption::kStale :
        success && alive ? MqttAdoption::kAdopt : MqttAdoption::kFailed;
    assert(classifyMqttResult(stale, same, wifi, success, alive) == expected);
  }
  assert(classifyMqttResult(false, true, true, false, false) == MqttAdoption::kFailed);
  MqttReconnectPolicy retry;
  assert(retry.due(0));
  assert(retry.failed(0, 0) == 5000);
  assert(!retry.due(4999) && retry.due(5000));
  retry.adopted(5000);
  assert(retry.failed(5001, 0) == 10000);
  retry.adopted(15001);
  assert(retry.failed(15002, 0) == 20000);
  retry.adopted(35002);
  assert(retry.failed(35003, 0) == 30000);
  retry.adopted(65003);
  retry.stable(125003);
  assert(retry.failed(125004, 0) == 5000);
  for (uint32_t seed = 0; seed < 5000; ++seed) {
    MqttReconnectPolicy jitter;
    uint32_t t = std::numeric_limits<uint32_t>::max() - 1000;
    auto wait = jitter.failed(t, seed);
    assert(wait >= 5000 && wait <= 6000);
    assert(!jitter.due(t + wait - 1));
    assert(jitter.remaining(t + wait - 1) == 1);
    assert(jitter.due(t + wait));
    jitter.immediate(t);
    assert(jitter.due(t));
  }
  // Deadline exactly zero after wrap must remain a real scheduled deadline.
  MqttReconnectPolicy wrap;
  uint32_t start = UINT32_MAX - 4999;
  wrap.failed(start, 0);
  assert(!wrap.due(UINT32_MAX) && wrap.due(0));

  MqttConnectionDiagnostics d;
  d.adopted(0);
  d.loop(1); d.loop(50);
  d.record(MqttLossReason::kOtaSuspend, 0, 100, 68000, 32000, 0);
  assert(d.planned_disconnects == 1 && d.disconnects == 0);
  assert(d.last_connection_duration_ms == 100 && !d.flapping(100));
  for (uint32_t n = 1; n <= 3; ++n) {
    d.adopted(n * 1000);
    d.record(MqttLossReason::kTransportLost, -3, n * 1000 + 1, 67000, 30000, 0);
  }
  assert(d.flapping(4000) && d.disconnects == 3);
  assert(d.size() == 4 && d.edge_sequence == 4 && d.edge_overwritten == 0);
  assert(std::strncmp(d.edge(0), "1,100,9,0,100,", 14) == 0);
  assert(d.last_error == -3);
  assert(d.flapping(700000)); // Time offline cannot clear the warning.
  d.adopted(4000); // Reconnect success must not erase last failure.
  assert(d.last_error == -3 && d.last_reason == MqttLossReason::kTransportLost);
  assert(d.flapping(603999) && !d.flapping(604000));
  d.record(MqttLossReason::kWifiLost, 0, 700000, 66000, 29000, 1);
  assert(!d.flapping(700000) && d.edge_overwritten == 1);
  assert(std::strncmp(d.edge(0), "2,1001,6,-3,1,", 14) == 0);
  assert(d.loop_gap_max_ms == 49);
  MqttConnectionDiagnostics failures;
  failures.record(MqttLossReason::kTlsFailed, -2, 1, 1, 1, 0);
  assert(failures.disconnects == 0 && failures.edge_sequence == 1);
  failures.edge_sequence = UINT32_MAX;
  failures.record(MqttLossReason::kTlsFailed, -2, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX);
  assert(failures.edge_sequence == UINT32_MAX && failures.edge_overwritten == 1);
  MqttConnectionDiagnostics maximal;
  maximal.record(MqttLossReason::kWorkerStartFailed, -128, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX);
  assert(std::strlen(maximal.edge(0)) < MqttConnectionDiagnostics::kEdgeBytes - 1);
  std::printf("connection policy/diagnostics PASS (%zu bytes)\n", sizeof(d));
}
