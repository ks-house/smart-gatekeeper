#include "RecoveryRadioPolicy.h"
#include "AccessCriticalLeasePolicy.h"

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>

namespace {

int checks = 0;

#define CHECK(condition)                                                    \
  do {                                                                      \
    ++checks;                                                               \
    if (!(condition)) {                                                     \
      std::cerr << "CHECK failed at line " << __LINE__ << ": "             \
                << #condition << std::endl;                                 \
      std::exit(1);                                                         \
    }                                                                       \
  } while (0)

constexpr uint32_t kQuietMs = 30000;
constexpr uint32_t kAttemptMs = 10000;
constexpr uint32_t kAuthenticatedHoldMs = 30000;
constexpr uint32_t kApClientHoldMs = 10UL * 60UL * 1000UL;
constexpr uint32_t kClientReleaseIntervalMs = 1000;

sgk::RecoveryRadioPolicy makePolicy() {
  return sgk::RecoveryRadioPolicy(kQuietMs, kAttemptMs,
                                  kAuthenticatedHoldMs, kApClientHoldMs,
                                  kClientReleaseIntervalMs);
}

sgk::StationRecoveryEscalationPolicy makeStationPolicy() {
  return sgk::StationRecoveryEscalationPolicy(30000, 60000);
}

void testStationOutageEscalatesAfterGrace() {
  auto policy = makeStationPolicy();
  CHECK(policy.observe(100, false) ==
        sgk::StationRecoveryObservation::kOutageStarted);
  CHECK(policy.phase() ==
        sgk::StationRecoveryPhase::kAutoReconnectGrace);
  CHECK(!policy.actionDue(30099));
  CHECK(policy.actionDue(30100));
  CHECK(policy.actionDue(45000));
}

void testStationApFailureUsesBoundedRetry() {
  auto policy = makeStationPolicy();
  policy.observe(10, false);
  CHECK(policy.actionDue(30010));
  policy.escalationFailed(30010);
  CHECK(policy.phase() == sgk::StationRecoveryPhase::kApRetryBackoff);
  CHECK(!policy.actionDue(90009));
  CHECK(policy.actionDue(90010));
}

void testStationRecoveryTracksFullOutage() {
  auto policy = makeStationPolicy();
  policy.observe(500, false);
  CHECK(policy.observe(20499, false) ==
        sgk::StationRecoveryObservation::kNone);
  CHECK(policy.currentOutageMs(20500) == 20000);
  CHECK(policy.observe(20500, true) ==
        sgk::StationRecoveryObservation::kRecovered);
  CHECK(policy.lastOutageMs() == 20000);
  CHECK(policy.currentOutageMs(30000) == 0);
  CHECK(policy.phase() == sgk::StationRecoveryPhase::kConnected);
}

void testStationRecoveryApOwnsEscalationUntilAssociation() {
  auto policy = makeStationPolicy();
  policy.observe(1000, false);
  policy.escalationSucceeded();
  CHECK(policy.phase() == sgk::StationRecoveryPhase::kRecoveryAp);
  CHECK(!policy.actionDue(1000 + 24UL * 60UL * 60UL * 1000UL));
  CHECK(policy.observe(42000, true) ==
        sgk::StationRecoveryObservation::kRecovered);
  CHECK(policy.lastOutageMs() == 41000);
}

void testStationRecoveryMillisWrapIsSafe() {
  auto policy = makeStationPolicy();
  const uint32_t start = std::numeric_limits<uint32_t>::max() - 10000;
  policy.observe(start, false);
  CHECK(!policy.actionDue(start + 29999));
  CHECK(policy.actionDue(start + 30000));
  CHECK(policy.currentOutageMs(start + 30000) == 30000);
}

void testBootQuietPrecedesFirstAttempt() {
  auto policy = makePolicy();
  policy.begin(100);
  CHECK(policy.phase() == sgk::RecoveryRadioPhase::kApQuiet);
  CHECK(policy.update(100, false, false, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(30099, false, false, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(30100, false, false, false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
  CHECK(policy.phase() == sgk::RecoveryRadioPhase::kStationAttempt);
}

void testClientAndAuthenticatedWorkBlockAttempts() {
  auto policy = makePolicy();
  policy.begin(0);
  CHECK(policy.update(kQuietMs, false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(kQuietMs + 5000, false, false, true) ==
        sgk::RecoveryRadioAction::kNone);
  policy.noteAuthenticatedActivity(kQuietMs + 5000);
  CHECK(policy.update(kQuietMs + 5000 + kAuthenticatedHoldMs - 1, false,
                      false, false) == sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(kQuietMs + 5000 + kAuthenticatedHoldMs, false, false,
                      false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
}

void testAttemptIsBoundedAndReturnsToFullQuietWindow() {
  auto policy = makePolicy();
  policy.begin(0);
  CHECK(policy.update(kQuietMs, false, false, false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
  CHECK(policy.update(kQuietMs + kAttemptMs - 1, false, false, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(kQuietMs + kAttemptMs, false, false, false) ==
        sgk::RecoveryRadioAction::kStopStationAttempt);
  CHECK(policy.phase() == sgk::RecoveryRadioPhase::kApQuiet);
  CHECK(policy.update(kQuietMs + kAttemptMs + kQuietMs - 1, false, false,
                      false) == sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(kQuietMs + kAttemptMs + kQuietMs, false, false,
                      false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
}

void testClientInterruptsAttemptAndRestartsQuietWindow() {
  auto policy = makePolicy();
  policy.begin(0);
  CHECK(policy.update(kQuietMs, false, false, false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
  CHECK(policy.update(kQuietMs + 1000, false, true, false) ==
        sgk::RecoveryRadioAction::kStopStationAttempt);
  CHECK(policy.update(kQuietMs + 1000 + kQuietMs - 1, false, false, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(kQuietMs + 1000 + kQuietMs, false, false, false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
}

void testIdleClientHoldIsBoundedBeforeReleaseAndFreshQuiet() {
  auto policy = makePolicy();
  policy.begin(0);
  CHECK(policy.update(kQuietMs, false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(kQuietMs + kApClientHoldMs - 1, false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(kQuietMs + kApClientHoldMs, false, true, false) ==
        sgk::RecoveryRadioAction::kReleaseStaleApClients);
  CHECK(policy.update(kQuietMs + kApClientHoldMs + 1, false, false, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(kQuietMs + kApClientHoldMs + kQuietMs - 1, false,
                      false, false) == sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(kQuietMs + kApClientHoldMs + kQuietMs, false, false,
                      false) ==
        sgk::RecoveryRadioAction::
            kReleaseStaleClientsAndStartStationAttempt);
}

void testStaleClientThatReconnectsIsReleasedAtBoundedRate() {
  auto policy = makePolicy();
  policy.begin(0);
  CHECK(policy.update(1, false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(1 + kApClientHoldMs, false, true, false) ==
        sgk::RecoveryRadioAction::kReleaseStaleApClients);
  CHECK(policy.update(1 + kApClientHoldMs + kClientReleaseIntervalMs - 1,
                      false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(1 + kApClientHoldMs + kClientReleaseIntervalMs,
                      false, true, false) ==
        sgk::RecoveryRadioAction::kReleaseStaleApClients);
  CHECK(policy.update(1 + kApClientHoldMs + kQuietMs - 1,
                      false, true, false) ==
        sgk::RecoveryRadioAction::kReleaseStaleApClients);
  CHECK(policy.update(1 + kApClientHoldMs + kQuietMs,
                      false, true, false) ==
        sgk::RecoveryRadioAction::kReleaseStaleClientsAndStartStationAttempt);
  CHECK(policy.update(1 + kApClientHoldMs + kQuietMs + 1,
                      false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(1 + kApClientHoldMs + kQuietMs + kAttemptMs,
                      false, true, false) ==
        sgk::RecoveryRadioAction::kStopStationAttempt);
}

void testAuthenticatedWorkStillInterruptsForcedStaleAttempt() {
  auto policy = makePolicy();
  policy.begin(0);
  CHECK(policy.update(1, false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  const uint32_t release = 1 + kApClientHoldMs;
  CHECK(policy.update(release, false, true, false) ==
        sgk::RecoveryRadioAction::kReleaseStaleApClients);
  const uint32_t attempt = release + kQuietMs;
  CHECK(policy.update(attempt, false, true, false) ==
        sgk::RecoveryRadioAction::kReleaseStaleClientsAndStartStationAttempt);
  policy.noteAuthenticatedActivity(attempt + 1);
  CHECK(policy.update(attempt + 1, false, true, true) ==
        sgk::RecoveryRadioAction::kStopStationAttempt);
  CHECK(policy.update(attempt + 1 + kQuietMs, false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
}

void testAuthenticatedClientActivityRenewsBoundedHold() {
  auto policy = makePolicy();
  policy.begin(0);
  CHECK(policy.update(kQuietMs, false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  const uint32_t activity = kQuietMs + kApClientHoldMs - 1;
  policy.noteAuthenticatedActivity(activity);
  CHECK(policy.update(activity + kAuthenticatedHoldMs, false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(activity + kApClientHoldMs - 1, false, true, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(activity + kApClientHoldMs, false, true, false) ==
        sgk::RecoveryRadioAction::kReleaseStaleApClients);
}

void testImmediateDriverFailureRestartsQuietWindow() {
  auto policy = makePolicy();
  policy.begin(500);
  CHECK(policy.update(500 + kQuietMs, false, false, false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
  policy.stationAttemptFailed(500 + kQuietMs + 1);
  CHECK(policy.phase() == sgk::RecoveryRadioPhase::kApQuiet);
  CHECK(policy.update(500 + kQuietMs + 1 + kQuietMs - 1, false, false,
                      false) == sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(500 + kQuietMs + 1 + kQuietMs, false, false, false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
}

void testStationSuccessStopsRecoveryPolicy() {
  auto policy = makePolicy();
  policy.begin(0);
  CHECK(policy.update(kQuietMs, false, false, false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
  CHECK(policy.update(kQuietMs + 1, true, false, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.phase() == sgk::RecoveryRadioPhase::kInactive);
  CHECK(policy.update(kQuietMs * 4, false, false, false) ==
        sgk::RecoveryRadioAction::kNone);
}

void testUnsignedMillisWrapIsSafe() {
  auto policy = makePolicy();
  const uint32_t start = std::numeric_limits<uint32_t>::max() - 10000;
  policy.begin(start);
  CHECK(policy.update(start + kQuietMs - 1, false, false, false) ==
        sgk::RecoveryRadioAction::kNone);
  CHECK(policy.update(start + kQuietMs, false, false, false) ==
        sgk::RecoveryRadioAction::kStartStationAttempt);
}

void testTimedRecoveryDeadlineNeverCollidesWithIndefiniteSentinel() {
  CHECK(sgk::MakeRecoveryDeadline(123, 0) == 0);
  const uint32_t duration = 10UL * 60UL * 1000UL;
  const uint32_t exact_wrap_start =
      std::numeric_limits<uint32_t>::max() - duration + 1;
  const uint32_t deadline =
      sgk::MakeRecoveryDeadline(exact_wrap_start, duration);
  CHECK(deadline == 1);
  CHECK(!sgk::RecoveryDeadlineReached(exact_wrap_start, deadline));
  CHECK(!sgk::RecoveryDeadlineReached(0, deadline));
  CHECK(sgk::RecoveryDeadlineReached(1, deadline));

  const uint32_t operation_lease = 30000;
  const uint32_t lease_wrap_start =
      std::numeric_limits<uint32_t>::max() - operation_lease + 1;
  const uint32_t extended =
      sgk::MakeRecoveryDeadline(lease_wrap_start, operation_lease);
  CHECK(extended == 1);
  CHECK(!sgk::RecoveryDeadlineReached(lease_wrap_start, extended));
  CHECK(!sgk::RecoveryDeadlineReached(0, extended));
  CHECK(sgk::RecoveryDeadlineReached(1, extended));
}

void testAccessCriticalReconnectCannotRenewUnverifiedLease() {
  sgk::AccessCriticalLeasePolicy lease(85000, 30000);
  CHECK(!lease.expired(1000, true, 0, 10000));
  CHECK(!lease.expired(5000, false, 0, 10000));
  CHECK(!lease.expired(5001, true, 0, 10000));
  CHECK(!lease.expired(10999, true, 0, 10000));
  CHECK(lease.expired(11000, true, 0, 10000));
  CHECK(!lease.expired(11001, false, 0, 10000));
  CHECK(lease.expired(11002, true, 0, 10000));
}

void testAccessCriticalContinuousQuietWindowRearmsLease() {
  sgk::AccessCriticalLeasePolicy lease(85000, 30000);
  CHECK(!lease.expired(1000, true, 0));
  CHECK(!lease.expired(2000, false, 0));
  CHECK(!lease.expired(31999, false, 0));
  CHECK(!lease.expired(32000, false, 0));
  CHECK(!lease.expired(100000, true, 0));
  CHECK(!lease.expired(184999, true, 0));
  CHECK(lease.expired(185000, true, 0));
}

void testVerifiedActionStartsFreshPhysicalLease() {
  sgk::AccessCriticalLeasePolicy lease(85000, 30000);
  CHECK(!lease.expired(1000, true, 0, 10000));
  CHECK(lease.expired(11000, true, 0, 10000));
  CHECK(!lease.expired(11001, true, 1, 85000));
  CHECK(!lease.expired(96000, true, 1, 85000));
  CHECK(lease.expired(96001, true, 1, 85000));
}

void testAccessCriticalLeaseHandlesMillisWrap() {
  sgk::AccessCriticalLeasePolicy lease(85000, 30000);
  const uint32_t start = std::numeric_limits<uint32_t>::max() - 5000;
  CHECK(!lease.expired(start, true, 0));
  CHECK(!lease.expired(start + 84999, true, 0));
  CHECK(lease.expired(start + 85000, true, 0));
}

}  // namespace

int main() {
  testStationOutageEscalatesAfterGrace();
  testStationApFailureUsesBoundedRetry();
  testStationRecoveryTracksFullOutage();
  testStationRecoveryApOwnsEscalationUntilAssociation();
  testStationRecoveryMillisWrapIsSafe();
  testBootQuietPrecedesFirstAttempt();
  testClientAndAuthenticatedWorkBlockAttempts();
  testAttemptIsBoundedAndReturnsToFullQuietWindow();
  testClientInterruptsAttemptAndRestartsQuietWindow();
  testIdleClientHoldIsBoundedBeforeReleaseAndFreshQuiet();
  testStaleClientThatReconnectsIsReleasedAtBoundedRate();
  testAuthenticatedWorkStillInterruptsForcedStaleAttempt();
  testAuthenticatedClientActivityRenewsBoundedHold();
  testImmediateDriverFailureRestartsQuietWindow();
  testStationSuccessStopsRecoveryPolicy();
  testUnsignedMillisWrapIsSafe();
  testTimedRecoveryDeadlineNeverCollidesWithIndefiniteSentinel();
  testAccessCriticalReconnectCannotRenewUnverifiedLease();
  testAccessCriticalContinuousQuietWindowRearmsLease();
  testVerifiedActionStartsFreshPhysicalLease();
  testAccessCriticalLeaseHandlesMillisWrap();
  std::cout << "RecoveryRadioPolicy host tests passed: " << checks
            << " checks" << std::endl;
  return 0;
}
