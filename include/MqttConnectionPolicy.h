#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <limits>

namespace sgk {

// Generation/cancellation validity is independent of a failed attempt's socket.
enum class MqttAdoption { kAdopt, kStale, kFailed };
constexpr MqttAdoption classifyMqttResult(bool stale, bool same_link,
                                         bool wifi_up, bool success,
                                         bool socket_alive) {
  return stale || !same_link || !wifi_up ? MqttAdoption::kStale :
      success && socket_alive ? MqttAdoption::kAdopt : MqttAdoption::kFailed;
}

// One main-task owner, no allocation, wrap-safe deadlines. A briefly successful
// connection must not reset backoff and turn a flapping link into a retry storm.
class MqttReconnectPolicy {
 public:
  static constexpr uint32_t kInitialMs = 5000;
  static constexpr uint32_t kMaximumMs = 30000;
  static constexpr uint32_t kStableMs = 60000;
  void immediate(uint32_t now) { scheduled_ = true; deadline_ = now; live_ = false; }
  void adopted(uint32_t now) { live_ = true; since_ = now; scheduled_ = false; }
  void stable(uint32_t now) {
    if (live_ && now - since_ >= kStableMs) base_ = kInitialMs;
  }
  uint32_t failed(uint32_t now, uint32_t entropy) {
    stable(now);
    live_ = false;
    const uint32_t room = std::min(base_ / 5, kMaximumMs - base_);
    const uint32_t delay = base_ + (room == 0 ? 0 : entropy % (room + 1));
    base_ = std::min(base_ * 2, kMaximumMs);
    scheduled_ = true;
    deadline_ = now + delay;
    return delay;
  }
  bool due(uint32_t now) const {
    return !scheduled_ || static_cast<int32_t>(now - deadline_) >= 0;
  }
  uint32_t remaining(uint32_t now) const {
    return due(now) ? 0 : deadline_ - now;
  }
 private:
  uint32_t base_ = kInitialMs;
  uint32_t deadline_ = 0;
  uint32_t since_ = 0;
  bool scheduled_ = false;
  bool live_ = false;
};

// Stable wire codes; unsigned advisory, never an access or transport authority.
enum class MqttLossReason : uint8_t {
  kNone, kTlsFailed, kMqttFailed, kSubscribeFailed, kAvailabilityFailed,
  kAdoptionLost, kTransportLost, kLoopFailed, kWifiLost, kOtaSuspend,
  kStaleResult, kDnsFailed, kWorkerStartFailed,
};
inline const char* mqttLossName(MqttLossReason reason) {
  static constexpr const char* names[] = {
      "NONE", "CONNECT_TLS_FAILED", "CONNECT_MQTT_FAILED",
      "CONNECT_SUBSCRIBE_FAILED", "CONNECT_AVAILABILITY_FAILED",
      "CONNECT_ADOPTION_LOST", "TRANSPORT_LOST", "LOOP_FAILED", "WIFI_LOST",
      "OTA_SUSPEND", "STALE_RESULT", "DNS_FAILED", "WORKER_START_FAILED"};
  return names[static_cast<uint8_t>(reason)];
}

class MqttConnectionDiagnostics {
 public:
  static constexpr size_t kCapacity = 4;
  static constexpr size_t kEdgeBytes = 112;
  static constexpr uint32_t kFlapWindowMs = 600000;
  void adopted(uint32_t now) {
    live_ = true;
    last_connected_ms = now;
    increment(generation);
  }
  bool live() const { return live_; }
  void loop(uint32_t now) {
    if (loop_seen_) loop_gap_max_ms = std::max(loop_gap_max_ms, now - last_loop_ms_);
    last_loop_ms_ = now;
    loop_seen_ = true;
  }
  void record(MqttLossReason reason, int error, uint32_t now,
              uint32_t heap, uint32_t largest, uint32_t wifi_generation) {
    last_reason = reason;
    last_error = error;
    last_disconnect_ms = now;
    last_connection_duration_ms = live_ ? now - last_connected_ms : 0;
    if (live_) {
      if (reason == MqttLossReason::kOtaSuspend) increment(planned_disconnects);
      else if (reason != MqttLossReason::kStaleResult) {
        increment(disconnects);
        if (now - last_connected_ms >= kFlapWindowMs) flap_latched_ = false;
        flap_times_[flap_next_] = now;
        flap_next_ = (flap_next_ + 1) % flap_times_.size();
        if (flap_count_ < flap_times_.size()) ++flap_count_;
        if (flap_count_ == flap_times_.size() &&
            now - flap_times_[flap_next_] <= kFlapWindowMs) flap_latched_ = true;
      }
    }
    live_ = false;
    // A planned suspension is not a keepalive-service gap in a live session.
    loop_seen_ = false;
    if (edge_sequence == std::numeric_limits<uint32_t>::max()) {
      increment(edge_overwritten);  // Never reuse an identity in the same boot.
      return;
    }
    ++edge_sequence;
    if (size_ == kCapacity) increment(edge_overwritten);
    else ++size_;
    std::snprintf(edges_[next_].data(), kEdgeBytes,
        "%lu,%lu,%u,%d,%lu,%lu,%lu,%lu,%lu",
        static_cast<unsigned long>(edge_sequence), static_cast<unsigned long>(now),
        static_cast<unsigned>(reason), error,
        static_cast<unsigned long>(last_connection_duration_ms),
        static_cast<unsigned long>(heap), static_cast<unsigned long>(largest),
        static_cast<unsigned long>(loop_gap_max_ms),
        static_cast<unsigned long>(wifi_generation));
    next_ = (next_ + 1) % kCapacity;
  }
  bool flapping(uint32_t now) const {
    // An offline interval is not recovery. Require a continuously live session.
    return flap_latched_ && !(live_ && now - last_connected_ms >= kFlapWindowMs);
  }
  size_t size() const { return size_; }
  const char* edge(size_t oldest_index) const {
    return edges_[(next_ + kCapacity - size_ + oldest_index) % kCapacity].data();
  }
  uint32_t generation = 0, disconnects = 0, planned_disconnects = 0;
  uint32_t last_disconnect_ms = 0, last_connected_ms = 0;
  uint32_t last_connection_duration_ms = 0, loop_gap_max_ms = 0;
  uint32_t edge_sequence = 0, edge_overwritten = 0;
  MqttLossReason last_reason = MqttLossReason::kNone;
  int last_error = 0;
 private:
  static void increment(uint32_t& value) {
    if (value != std::numeric_limits<uint32_t>::max()) ++value;
  }
  std::array<std::array<char, kEdgeBytes>, kCapacity> edges_{};
  std::array<uint32_t, 3> flap_times_{};
  uint32_t last_loop_ms_ = 0;
  size_t next_ = 0, size_ = 0, flap_next_ = 0, flap_count_ = 0;
  bool live_ = false, loop_seen_ = false, flap_latched_ = false;
};
static_assert(sizeof(MqttConnectionDiagnostics) <= 640,
              "connection evidence must retain OTA RAM headroom");
}  // namespace sgk
