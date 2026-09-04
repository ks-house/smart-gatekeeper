#pragma once

#include <cstdint>

namespace sgk {

inline uint32_t MakeRecoveryDeadline(uint32_t now_ms, uint32_t duration_ms) {
  if (duration_ms == 0) return 0;
  const uint32_t deadline_ms = now_ms + duration_ms;
  // Zero is reserved for an indefinite recovery AP. Canonicalizing the one
  // exact wrap case to 1 extends the window by only one millisecond.
  return deadline_ms == 0 ? 1 : deadline_ms;
}

inline bool RecoveryDeadlineReached(uint32_t now_ms, uint32_t deadline_ms) {
  return deadline_ms != 0 &&
         static_cast<int32_t>(now_ms - deadline_ms) >= 0;
}

enum class RecoveryRadioPhase : uint8_t {
  kInactive = 0,
  kApQuiet,
  kStationAttempt,
};

enum class RecoveryRadioAction : uint8_t {
  kNone = 0,
  kStartStationAttempt,
  kStopStationAttempt,
  kReleaseStaleApClients,
  kReleaseStaleClientsAndStartStationAttempt,
};

enum class StationRecoveryPhase : uint8_t {
  kConnected = 0,
  kAutoReconnectGrace,
  kApRetryBackoff,
  kRecoveryAp,
};

enum class StationRecoveryObservation : uint8_t {
  kNone = 0,
  kOutageStarted,
  kRecovered,
};

// Pure policy for escalating a long-lived normal STA outage into the existing
// authenticated Recovery AP. Wi-Fi mutation stays in WifiManager and is only
// serviced while the access-control path is safe.
class StationRecoveryEscalationPolicy {
 public:
  StationRecoveryEscalationPolicy(uint32_t grace_ms, uint32_t retry_ms)
      : grace_ms_(grace_ms), retry_ms_(retry_ms) {}

  StationRecoveryObservation observe(uint32_t now_ms, bool connected) {
    if (connected) {
      if (phase_ == StationRecoveryPhase::kConnected) {
        return StationRecoveryObservation::kNone;
      }
      last_outage_ms_ = now_ms - outage_started_ms_;
      phase_ = StationRecoveryPhase::kConnected;
      outage_started_ms_ = 0;
      phase_started_ms_ = now_ms;
      return StationRecoveryObservation::kRecovered;
    }
    if (phase_ == StationRecoveryPhase::kConnected) {
      phase_ = StationRecoveryPhase::kAutoReconnectGrace;
      outage_started_ms_ = now_ms;
      phase_started_ms_ = now_ms;
      return StationRecoveryObservation::kOutageStarted;
    }
    return StationRecoveryObservation::kNone;
  }

  bool actionDue(uint32_t now_ms) const {
    if (phase_ == StationRecoveryPhase::kAutoReconnectGrace) {
      return now_ms - phase_started_ms_ >= grace_ms_;
    }
    if (phase_ == StationRecoveryPhase::kApRetryBackoff) {
      return now_ms - phase_started_ms_ >= retry_ms_;
    }
    return false;
  }

  void escalationSucceeded() {
    phase_ = StationRecoveryPhase::kRecoveryAp;
    phase_started_ms_ = 0;
  }

  void escalationFailed(uint32_t now_ms) {
    phase_ = StationRecoveryPhase::kApRetryBackoff;
    phase_started_ms_ = now_ms;
  }

  void stop() {
    phase_ = StationRecoveryPhase::kConnected;
    outage_started_ms_ = 0;
    phase_started_ms_ = 0;
  }

  uint32_t currentOutageMs(uint32_t now_ms) const {
    return phase_ == StationRecoveryPhase::kConnected
               ? 0
               : now_ms - outage_started_ms_;
  }
  uint32_t lastOutageMs() const { return last_outage_ms_; }
  StationRecoveryPhase phase() const { return phase_; }

 private:
  uint32_t grace_ms_ = 0;
  uint32_t retry_ms_ = 0;
  uint32_t outage_started_ms_ = 0;
  uint32_t phase_started_ms_ = 0;
  uint32_t last_outage_ms_ = 0;
  StationRecoveryPhase phase_ = StationRecoveryPhase::kConnected;
};

// Pure timing policy for sharing one ESP32-C6 radio between the recovery AP
// and a failed STA. The adapter owns Wi-Fi calls; this class only decides when
// one bounded attempt may start or must stop.
class RecoveryRadioPolicy {
 public:
  RecoveryRadioPolicy(uint32_t ap_quiet_ms, uint32_t station_attempt_ms,
                      uint32_t authenticated_hold_ms,
                      uint32_t ap_client_hold_ms,
                      uint32_t client_release_interval_ms)
      : ap_quiet_ms_(ap_quiet_ms),
        station_attempt_ms_(station_attempt_ms),
        authenticated_hold_ms_(authenticated_hold_ms),
        ap_client_hold_ms_(ap_client_hold_ms),
        client_release_interval_ms_(client_release_interval_ms) {}

  void begin(uint32_t now_ms) {
    phase_ = RecoveryRadioPhase::kApQuiet;
    phase_started_ms_ = now_ms;
    authenticated_activity_seen_ = false;
    last_authenticated_activity_ms_ = 0;
    ap_client_hold_started_ = false;
    ap_client_hold_started_ms_ = 0;
    releasing_stale_clients_ = false;
    last_client_release_ms_ = 0;
    forced_stale_attempt_ = false;
  }

  void stop() {
    phase_ = RecoveryRadioPhase::kInactive;
    phase_started_ms_ = 0;
    authenticated_activity_seen_ = false;
    last_authenticated_activity_ms_ = 0;
    ap_client_hold_started_ = false;
    ap_client_hold_started_ms_ = 0;
    releasing_stale_clients_ = false;
    last_client_release_ms_ = 0;
    forced_stale_attempt_ = false;
  }

  void noteAuthenticatedActivity(uint32_t now_ms) {
    authenticated_activity_seen_ = true;
    last_authenticated_activity_ms_ = now_ms;
    if (ap_client_hold_started_) {
      ap_client_hold_started_ms_ = now_ms;
      releasing_stale_clients_ = false;
      forced_stale_attempt_ = false;
    }
  }

  void pauseForLocalWork(uint32_t now_ms) {
    phase_ = RecoveryRadioPhase::kApQuiet;
    phase_started_ms_ = now_ms;
    forced_stale_attempt_ = false;
  }

  void stationAttemptFailed(uint32_t now_ms) {
    phase_ = RecoveryRadioPhase::kApQuiet;
    phase_started_ms_ = now_ms;
    forced_stale_attempt_ = false;
  }

  RecoveryRadioAction update(uint32_t now_ms, bool station_connected,
                             bool ap_client_connected,
                             bool local_operation_active) {
    if (phase_ == RecoveryRadioPhase::kInactive) {
      return RecoveryRadioAction::kNone;
    }
    if (station_connected) {
      stop();
      return RecoveryRadioAction::kNone;
    }

    const bool authenticated_hold_active =
        authenticated_activity_seen_ &&
        now_ms - last_authenticated_activity_ms_ < authenticated_hold_ms_;

    if (ap_client_connected && !ap_client_hold_started_) {
      ap_client_hold_started_ = true;
      ap_client_hold_started_ms_ = now_ms;
    }
    const bool station_attempt_blocked =
        local_operation_active || authenticated_hold_active ||
        (ap_client_connected && !forced_stale_attempt_);

    if (phase_ == RecoveryRadioPhase::kStationAttempt) {
      if (station_attempt_blocked ||
          now_ms - phase_started_ms_ >= station_attempt_ms_) {
        phase_ = RecoveryRadioPhase::kApQuiet;
        phase_started_ms_ = now_ms;
        forced_stale_attempt_ = false;
        return RecoveryRadioAction::kStopStationAttempt;
      }
      return RecoveryRadioAction::kNone;
    }

    if (releasing_stale_clients_ && !local_operation_active &&
        !authenticated_hold_active &&
        now_ms - phase_started_ms_ >= ap_quiet_ms_) {
      // A phone can automatically reassociate after deauthentication. Pair
      // client release with the bounded attempt and ignore only raw idle
      // association during that attempt; authenticated/local work still wins.
      phase_ = RecoveryRadioPhase::kStationAttempt;
      phase_started_ms_ = now_ms;
      forced_stale_attempt_ = true;
      return RecoveryRadioAction::kReleaseStaleClientsAndStartStationAttempt;
    }

    if (ap_client_connected && !local_operation_active &&
        !authenticated_hold_active) {
      if (!releasing_stale_clients_ &&
          now_ms - ap_client_hold_started_ms_ >= ap_client_hold_ms_) {
        releasing_stale_clients_ = true;
        last_client_release_ms_ = now_ms;
        phase_started_ms_ = now_ms;
        return RecoveryRadioAction::kReleaseStaleApClients;
      }
      if (releasing_stale_clients_ &&
          now_ms - last_client_release_ms_ >=
              client_release_interval_ms_) {
        last_client_release_ms_ = now_ms;
        return RecoveryRadioAction::kReleaseStaleApClients;
      }
      return RecoveryRadioAction::kNone;
    }

    if (!station_attempt_blocked &&
        now_ms - phase_started_ms_ >= ap_quiet_ms_) {
      phase_ = RecoveryRadioPhase::kStationAttempt;
      phase_started_ms_ = now_ms;
      ap_client_hold_started_ = false;
      ap_client_hold_started_ms_ = 0;
      releasing_stale_clients_ = false;
      last_client_release_ms_ = 0;
      forced_stale_attempt_ = false;
      return RecoveryRadioAction::kStartStationAttempt;
    }
    return RecoveryRadioAction::kNone;
  }

  RecoveryRadioPhase phase() const { return phase_; }

 private:
  uint32_t ap_quiet_ms_ = 0;
  uint32_t station_attempt_ms_ = 0;
  uint32_t authenticated_hold_ms_ = 0;
  uint32_t ap_client_hold_ms_ = 0;
  uint32_t client_release_interval_ms_ = 0;
  uint32_t phase_started_ms_ = 0;
  uint32_t last_authenticated_activity_ms_ = 0;
  uint32_t ap_client_hold_started_ms_ = 0;
  uint32_t last_client_release_ms_ = 0;
  RecoveryRadioPhase phase_ = RecoveryRadioPhase::kInactive;
  bool authenticated_activity_seen_ = false;
  bool ap_client_hold_started_ = false;
  bool releasing_stale_clients_ = false;
  bool forced_stale_attempt_ = false;
};

}  // namespace sgk
