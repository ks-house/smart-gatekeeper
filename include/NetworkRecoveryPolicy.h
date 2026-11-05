#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>

namespace sgk {

// Loop-task-only policy. It grants bounded station repair, never access,
// credential changes, firmware installation, or a Target reboot.
class NetworkRecoveryPolicy {
 public:
  enum class FailureKind : uint8_t {
    kDns, kTransport, kAuthorization, kLocalResource,
  };
  enum class Action : uint8_t {
    kNone, kReassociateStation, kRestartStationInterface,
  };

  static constexpr uint32_t kDnsSpanMs = 60000;
  static constexpr uint32_t kTransportSpanMs = 180000;
  static constexpr uint32_t kStableMs = 60000;
  static constexpr uint32_t kMinimumActionGapMs = 120000;
  static constexpr uint32_t kActionWindowMs = 15 * 60 * 1000;
  static constexpr uint32_t kRejectedRetryMs = 30000;
  static constexpr uint16_t kDnsFailures = 3;
  static constexpr uint16_t kTransportFailures = 6;

  // A natural reassociation can occur without a failed attempt. Observe it
  // before considering repair so a new link cannot inherit old qualification.
  // Stage, global rolling budget and rejection spacing remain untouched.
  void observeLinkGeneration(uint32_t wifi_generation) {
    if (!generation_seen_ || wifi_generation_ != wifi_generation) {
      clearEvidence();
      wifi_generation_ = wifi_generation;
      generation_seen_ = true;
    }
  }

  // Invoke once per completed actual failure, not once per loop or DNS poll.
  // DNS also counts toward the slower mixed-transport threshold. The first-to-last actual failure span must meet the time threshold;
  // silence after a burst cannot qualify. Both streaks belong to one Wi-Fi generation; radio budget and stage never do.
  void failure(FailureKind kind, uint32_t now, uint32_t wifi_generation) {
    if (suspended_) return;
    selected_ = Action::kNone;
    connected_ = false;
    stable_observed_ = false;
    observeLinkGeneration(wifi_generation);
    if (kind == FailureKind::kAuthorization ||
        kind == FailureKind::kLocalResource) {
      // A stale DNS request must not reset the radio after the failure has
      // become an explicit credential/configuration/resource problem.
      clearEvidence();
      return;
    }
    if (failures_ == 0) first_failure_ms_ = now;
    increment(failures_);
    last_failure_ms_ = now;
    if (kind == FailureKind::kDns) {
      if (dns_failures_ == 0) first_dns_ms_ = now;
      increment(dns_failures_);
      last_dns_ms_ = now;
    }
  }

  // Only a generation-checked adopted MQTT session starts this clock. DNS,
  // association, request start, or raw connected observations cannot reset it.
  void adopted(uint32_t now) {
    if (suspended_) return;
    selected_ = Action::kNone;
    connected_ = true;
    stable_observed_ = false;
    adopted_ms_ = now;
  }

  void observeConnected(uint32_t now, bool connected) {
    if (suspended_) return;
    if (!connected) {
      connected_ = false;
      stable_observed_ = false;
      return;
    }
    if (connected_ && !stable_observed_ && now - adopted_ms_ >= kStableMs) {
      clearEvidence();
      stage_ = 0;
      stable_observed_ = true;
      // Global radio timestamps and last-action spacing intentionally survive.
    }
  }

  // safe must cover access/GATT, all transport owners, OTA and authenticated
  // local recovery. Selection changes no action budget. The adapter must
  // atomically re-check its guards before accepting the selected action.
  Action nextAction(uint32_t now, bool safe) {
    pruneActions(now);
    selected_ = safe ? candidate(now) : Action::kNone;
    return selected_;
  }

  // Call only after the adapter accepts the selected asynchronous operation.
  // A false return refuses a missing or superseded selection. One accepted
  // operation can be committed once, including at millis()==0.
  bool commitAction(uint32_t now) {
    pruneActions(now);
    const Action action = candidate(now);
    if (selected_ == Action::kNone || selected_ != action) {
      selected_ = Action::kNone;
      return false;
    }
    action_times_[action_count_++] = now;
    last_action_ms_ = now;
    action_seen_ = true;
    stage_ = 1;  // Every later repair in this episode restarts only STA.
    clearEvidence();
    rejection_seen_ = false;
    return true;
  }

  // A rejected adapter request spends no radio budget, but cannot busy-loop.
  void actionRejected(uint32_t now) {
    if (selected_ == Action::kNone) return;
    selected_ = Action::kNone;
    rejected_ms_ = now;
    rejection_seen_ = true;
  }

  // Planned OTA suspension is not failure time. It breaks continuous-MQTT
  // stability, but keeps episode stage, real-time spacing and rolling budget.
  void suspend(uint32_t now) {
    if (suspended_) return;
    suspended_ = true;
    suspended_ms_ = now;
    selected_ = Action::kNone;
    connected_ = false;
    stable_observed_ = false;
  }

  void resume(uint32_t now) {
    if (!suspended_) return;
    const uint32_t pause_ms = now - suspended_ms_;
    if (failures_ != 0) {
      first_failure_ms_ += pause_ms;
      last_failure_ms_ += pause_ms;
    }
    if (dns_failures_ != 0) {
      first_dns_ms_ += pause_ms;
      last_dns_ms_ += pause_ms;
    }
    suspended_ = false;
  }

 private:
  static void increment(uint16_t& value) {
    if (value != std::numeric_limits<uint16_t>::max()) ++value;
  }

  void clearEvidence() {
    failures_ = 0;
    dns_failures_ = 0;
    first_failure_ms_ = 0;
    last_failure_ms_ = 0;
    first_dns_ms_ = 0;
    last_dns_ms_ = 0;
    selected_ = Action::kNone;
  }

  // The rolling window is (now - kActionWindowMs, now]. Expiry at exactly
  // fifteen minutes permits one replacement; generation/stability never erase
  // these two accepted timestamps. All durations use unsigned elapsed time.
  void pruneActions(uint32_t now) {
    size_t retained = 0;
    for (size_t i = 0; i < action_count_; ++i) {
      if (now - action_times_[i] < kActionWindowMs)
        action_times_[retained++] = action_times_[i];
    }
    action_count_ = retained;
  }

  Action candidate(uint32_t now) const {
    if (suspended_ || connected_ || action_count_ == action_times_.size() ||
        (action_seen_ && now - last_action_ms_ < kMinimumActionGapMs) ||
        (rejection_seen_ && now - rejected_ms_ < kRejectedRetryMs))
      return Action::kNone;
    const bool dns_due = dns_failures_ >= kDnsFailures &&
        last_dns_ms_ - first_dns_ms_ >= kDnsSpanMs;
    const bool transport_due = failures_ >= kTransportFailures &&
        last_failure_ms_ - first_failure_ms_ >= kTransportSpanMs;
    if (!dns_due && !transport_due) return Action::kNone;
    return stage_ == 0 ? Action::kReassociateStation
                       : Action::kRestartStationInterface;
  }

  std::array<uint32_t, 2> action_times_{};
  size_t action_count_ = 0;
  uint32_t wifi_generation_ = 0;
  uint32_t first_failure_ms_ = 0;
  uint32_t last_failure_ms_ = 0;
  uint32_t first_dns_ms_ = 0;
  uint32_t last_dns_ms_ = 0;
  uint32_t adopted_ms_ = 0;
  uint32_t last_action_ms_ = 0;
  uint32_t rejected_ms_ = 0;
  uint32_t suspended_ms_ = 0;
  uint16_t failures_ = 0;
  uint16_t dns_failures_ = 0;
  uint8_t stage_ = 0;
  Action selected_ = Action::kNone;
  bool generation_seen_ = false;
  bool action_seen_ = false;
  bool rejection_seen_ = false;
  bool connected_ = false;
  bool stable_observed_ = false;
  bool suspended_ = false;
};

static_assert(sizeof(NetworkRecoveryPolicy) <= 96,
              "network recovery policy must preserve OTA memory headroom");
}  // namespace sgk
