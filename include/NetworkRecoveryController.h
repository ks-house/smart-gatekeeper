#pragma once

#include "NetworkRecoveryPolicy.h"

#include <cstdint>
#include <limits>

namespace sgk {

// Loop-task-only, allocation-free orchestration. The Driver reservation is an
// admission token, not a mutex held across Wi-Fi/socket calls. Driver APIs must
// return promptly; callbacks only publish raw association/generation evidence.
class NetworkRecoveryController {
 public:
  using Action = NetworkRecoveryPolicy::Action;
  static constexpr uint32_t kDisconnectTimeoutMs = 2000;

  struct Diagnostics {
    uint32_t started = 0, completed = 0, rejected = 0, timeouts = 0;
    uint32_t cancelled = 0, deferred = 0, reserve_failures = 0, commit_failures = 0;
  };

  // true means this controller still owns the asynchronous repair phase and
  // ordinary MQTT work must remain deferred. No call loops, delays or reboots.
  template <class Driver>
  bool service(uint32_t now, NetworkRecoveryPolicy& policy, Driver& driver) {
    return active() ? serviceWaiting(now, driver) : serviceIdle(now, policy, driver);
  }

  bool active() const { return action_ != Action::kNone; }
  const Diagnostics& diagnostics() const { return diagnostics_; }

 private:
  template <class Driver>
  class Reservation {
   public:
    explicit Reservation(Driver& driver)
        : driver_(driver), acquired_(driver.tryReserve()) {}
    ~Reservation() { if (acquired_) driver_.release(); }
    Reservation(const Reservation&) = delete;
    Reservation& operator=(const Reservation&) = delete;
    explicit operator bool() const { return acquired_; }
   private:
    Driver& driver_;
    bool acquired_;
  };

  static void increment(uint32_t& value) {
    if (value != std::numeric_limits<uint32_t>::max()) ++value;
  }

  void retire() {
    action_ = Action::kNone;
    started_ms_ = 0;
    link_generation_ = 0;
  }

  template <class Driver>
  bool serviceIdle(uint32_t now, NetworkRecoveryPolicy& policy, Driver& driver) {
    if (driver.externalRecoveryActive() || !driver.stationAssociated() ||
        !driver.safeForRepair()) {
      policy.nextAction(now, false);  // Invalidate an unaccepted old selection.
      return false;
    }
    policy.observeLinkGeneration(driver.linkGeneration());
    const Action action = policy.nextAction(now, true);
    if (action == Action::kNone) return false;
    Reservation<Driver> reservation(driver);
    if (!reservation) {
      increment(diagnostics_.reserve_failures);
      return false;
    }
    if (driver.externalRecoveryActive() || !driver.safeForRepair() ||
        !driver.stationAssociated()) {
      policy.nextAction(driver.nowMillis(), false);
      increment(diagnostics_.deferred);
      return false;
    }

    // Driver events can race the reservation. Re-observe and reselect after
    // admission so old-link qualification cannot mutate a newly recovered STA.
    policy.observeLinkGeneration(driver.linkGeneration());
    if (policy.nextAction(driver.nowMillis(), true) != action) {
      increment(diagnostics_.deferred);
      return false;
    }
    const uint32_t generation = driver.linkGeneration();
    driver.invalidateTransport();
    if (!driver.beginDisconnect()) {
      policy.actionRejected(driver.nowMillis());
      driver.cancelRepair(true);
      increment(diagnostics_.rejected);
      return false;
    }
    const uint32_t accepted_ms = driver.nowMillis();
    if (!policy.commitAction(accepted_ms)) {
      driver.cancelRepair(true);
      increment(diagnostics_.commit_failures);
      return false;
    }
    action_ = action;
    started_ms_ = accepted_ms;
    link_generation_ = generation;
    increment(diagnostics_.started);
    return true;
  }

  template <class Driver>
  bool externalTakeover(Driver& driver) {
    // false clears only our pending flag; it must not touch radio/auto policy
    // while AP, OTA or another local recovery operation owns those settings.
    if (driver.ownsStationRepair()) driver.cancelRepair(false);
    increment(diagnostics_.cancelled);
    retire();
    return false;
  }

  template <class Driver>
  bool serviceWaiting(uint32_t now, Driver& driver) {
    if (driver.externalRecoveryActive()) return externalTakeover(driver);
    if (!driver.ownsStationRepair()) {
      increment(diagnostics_.cancelled);
      retire();
      return false;
    }
    if (!driver.safeForRepair()) {
      increment(diagnostics_.deferred);
      return true;
    }
    const bool associated = driver.stationAssociated();
    const bool changed = driver.linkGeneration() != link_generation_;
    if (associated && !changed && now - started_ms_ < kDisconnectTimeoutMs)
      return true;

    Reservation<Driver> reservation(driver);
    if (!reservation) {
      increment(diagnostics_.reserve_failures);
      return true;
    }
    if (driver.externalRecoveryActive()) return externalTakeover(driver);
    if (!driver.ownsStationRepair()) {
      increment(diagnostics_.cancelled);
      retire();
      return false;
    }
    if (!driver.safeForRepair()) {
      increment(diagnostics_.deferred);
      return true;
    }
    const bool current_associated = driver.stationAssociated();
    const bool current_changed = driver.linkGeneration() != link_generation_;
    if (current_associated && !current_changed) {
      if (driver.nowMillis() - started_ms_ < kDisconnectTimeoutMs) return true;
      driver.cancelRepair(true);
      increment(diagnostics_.timeouts);
      retire();
      return false;
    }

    if (action_ == Action::kReassociateStation && current_associated &&
        current_changed) {
      // A quick raw disconnect/reconnect already repaired stage one. Stage two
      // still restarts STA because mere reassociation was its failed remedy.
      driver.cancelRepair(true);
      increment(diagnostics_.completed);
    } else if (driver.finishReconnect(action_)) {
      increment(diagnostics_.completed);
    } else {
      driver.cancelRepair(true);
      increment(diagnostics_.rejected);
    }
    retire();
    return false;
  }

  Diagnostics diagnostics_{};
  uint32_t started_ms_ = 0;
  uint32_t link_generation_ = 0;
  Action action_ = Action::kNone;
};

static_assert(sizeof(NetworkRecoveryController) <= 80,
              "network recovery controller must preserve OTA memory headroom");
}  // namespace sgk
