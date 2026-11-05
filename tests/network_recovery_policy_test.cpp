#include "NetworkRecoveryPolicy.h"

#include <cstdint>
#include <cstdio>
#include <vector>

using Policy = sgk::NetworkRecoveryPolicy;
using Failure = Policy::FailureKind;
using Action = Policy::Action;

#define CHECK(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "%s:%d: %s\n", __func__, __LINE__, #condition); \
  return false; } } while (0)

void dns(Policy& policy, uint32_t start, uint32_t generation = 1) {
  policy.failure(Failure::kDns, start, generation);
  policy.failure(Failure::kDns, start + 30000, generation);
  policy.failure(Failure::kDns, start + 60000, generation);
}

bool dns_failure_threshold_is_real_and_bounded() {
  Policy policy;
  policy.failure(Failure::kDns, 0, 7);
  policy.failure(Failure::kDns, 30000, 7);
  CHECK(policy.nextAction(59999, true) == Action::kNone);
  policy.failure(Failure::kDns, 59999, 7);
  CHECK(policy.nextAction(59999, true) == Action::kNone);
  CHECK(policy.nextAction(60000, true) == Action::kNone);
  policy.failure(Failure::kDns, 60000, 7);
  CHECK(policy.nextAction(60000, false) == Action::kNone);
  CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(60000));
  CHECK(policy.nextAction(60000, true) == Action::kNone);
  CHECK(!policy.commitAction(60000));
  return true;
}

bool generic_transport_requires_six_failures_and_three_minutes() {
  Policy policy;
  for (uint32_t i = 0; i < 5; ++i)
    policy.failure(Failure::kTransport, i * 36000, 1);
  CHECK(policy.nextAction(179999, true) == Action::kNone);
  policy.failure(Failure::kTransport, 179999, 1);
  CHECK(policy.nextAction(179999, true) == Action::kNone);
  CHECK(policy.nextAction(180000, true) == Action::kNone);
  policy.failure(Failure::kTransport, 180000, 1);
  CHECK(policy.nextAction(180000, true) == Action::kReassociateStation);
  return true;
}

bool excluded_failures_invalidate_old_pending_radio_requests() {
  for (const auto excluded : {Failure::kAuthorization, Failure::kLocalResource}) {
    Policy policy;
    dns(policy, 0);
    CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
    policy.failure(excluded, 60001, 1);
    CHECK(!policy.commitAction(60001));
    for (uint32_t now = 60001; now < 3600000; now += 1000)
      policy.failure(excluded, now, 1);
    CHECK(policy.nextAction(3600000, true) == Action::kNone);
    dns(policy, 3600001);
    CHECK(policy.nextAction(3660001, true) == Action::kReassociateStation);
  }
  return true;
}

bool wifi_generation_change_requires_new_same_link_evidence() {
  Policy policy;
  policy.failure(Failure::kDns, 0, 1);
  policy.failure(Failure::kDns, 30000, 1);
  policy.failure(Failure::kDns, 60000, 2);
  CHECK(policy.nextAction(60000, true) == Action::kNone);
  policy.failure(Failure::kDns, 90000, 2);
  policy.failure(Failure::kDns, 120000, 2);
  CHECK(policy.nextAction(120000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(120000));
  dns(policy, 120001, 3);
  CHECK(policy.nextAction(239999, true) == Action::kNone);
  CHECK(policy.nextAction(240000, true) == Action::kRestartStationInterface);
  return true;
}

bool selection_is_not_acceptance_and_safe_deferral_does_not_spend_budget() {
  Policy policy;
  dns(policy, 0);
  CHECK(!policy.commitAction(60000));
  for (uint32_t now = 60000; now < 120000; now += 1000)
    CHECK(policy.nextAction(now, false) == Action::kNone);
  CHECK(policy.nextAction(120000, true) == Action::kReassociateStation);
  CHECK(policy.nextAction(120000, false) == Action::kNone);
  CHECK(!policy.commitAction(120000));
  CHECK(policy.nextAction(120001, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(120001));
  CHECK(!policy.commitAction(120001));
  return true;
}

bool stale_selected_action_cannot_commit_after_new_link_or_adoption() {
  Policy policy;
  dns(policy, 0);
  CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
  policy.failure(Failure::kDns, 60001, 2);
  CHECK(!policy.commitAction(60001));
  policy.failure(Failure::kDns, 90001, 2);
  policy.failure(Failure::kDns, 120001, 2);
  CHECK(policy.nextAction(120001, true) == Action::kReassociateStation);
  policy.adopted(120002);
  CHECK(!policy.commitAction(120002));
  CHECK(policy.nextAction(180002, true) == Action::kNone);
  return true;
}

bool continued_failure_repeats_stage_two_only_after_rolling_budget_and_spacing() {
  Policy policy;
  dns(policy, 0);
  CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(60000));
  CHECK(policy.nextAction(180000, true) == Action::kNone);  // New failures required.
  dns(policy, 180001);
  CHECK(policy.nextAction(240001, true) == Action::kRestartStationInterface);
  CHECK(policy.commitAction(240001));
  dns(policy, 240002);
  CHECK(policy.nextAction(959999, true) == Action::kNone);
  CHECK(policy.nextAction(960000, true) == Action::kRestartStationInterface);
  CHECK(policy.commitAction(960000));
  dns(policy, 960001);
  CHECK(policy.nextAction(1140000, true) == Action::kNone);
  CHECK(policy.nextAction(1140001, true) == Action::kRestartStationInterface);
  CHECK(policy.commitAction(1140001));
  return true;
}

bool short_connection_does_not_reset_stage_or_failure_debt() {
  Policy policy;
  dns(policy, 0);
  CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(60000));
  policy.adopted(60001);
  policy.observeConnected(120000, true);  // 59,999 ms, not stable.
  policy.observeConnected(120001, false);
  dns(policy, 120002);
  CHECK(policy.nextAction(180002, true) == Action::kRestartStationInterface);
  return true;
}

bool stable_connection_resets_stage_but_preserves_global_budget_and_spacing() {
  Policy policy;
  dns(policy, 0);
  CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(60000));
  policy.adopted(60001);
  policy.observeConnected(120001, true);
  dns(policy, 120002, 2);
  CHECK(policy.nextAction(180002, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(180002));
  policy.adopted(180003);
  policy.observeConnected(240003, true);
  dns(policy, 240004, 3);
  CHECK(policy.nextAction(300004, true) == Action::kNone);
  CHECK(policy.nextAction(959999, true) == Action::kNone);
  CHECK(policy.nextAction(960000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(960000));
  return true;
}

bool rejected_adapter_action_retries_slowly_without_consuming_radio_budget() {
  Policy policy;
  dns(policy, 0);
  CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
  policy.actionRejected(60000);
  CHECK(!policy.commitAction(60000));
  CHECK(policy.nextAction(89999, true) == Action::kNone);
  CHECK(policy.nextAction(90000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(90000));
  dns(policy, 90001);
  CHECK(policy.nextAction(209999, true) == Action::kNone);
  CHECK(policy.nextAction(210000, true) == Action::kRestartStationInterface);
  CHECK(policy.commitAction(210000));  // Rejection did not spend one of the two slots.
  return true;
}

bool zero_timestamps_and_clock_wrap_preserve_thresholds_and_budget() {
  Policy policy;
  const uint32_t start = UINT32_MAX - 59999;
  policy.failure(Failure::kDns, start, 0);
  policy.failure(Failure::kDns, start + 30000, 0);
  policy.failure(Failure::kDns, UINT32_MAX, 0);
  CHECK(policy.nextAction(UINT32_MAX, true) == Action::kNone);
  CHECK(policy.nextAction(0, true) == Action::kNone);
  policy.failure(Failure::kDns, 0, 0);
  CHECK(policy.nextAction(0, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(0));
  dns(policy, 1, 1);
  CHECK(policy.nextAction(119999, true) == Action::kNone);
  CHECK(policy.nextAction(120000, true) == Action::kRestartStationInterface);
  CHECK(policy.commitAction(120000));
  dns(policy, 120001, 2);
  CHECK(policy.nextAction(899999, true) == Action::kNone);
  CHECK(policy.nextAction(900000, true) == Action::kRestartStationInterface);
  CHECK(policy.commitAction(900000));
  return true;
}

bool planned_suspend_excludes_deliberate_time_and_ignored_failures() {
  Policy policy;
  policy.failure(Failure::kDns, 0, 1);
  policy.failure(Failure::kDns, 30000, 1);
  policy.suspend(30001);
  policy.suspend(40001);  // Idempotent nested notification.
  policy.failure(Failure::kDns, 60000, 1);
  CHECK(policy.nextAction(90000, true) == Action::kNone);
  policy.resume(90001);
  policy.resume(90002);
  policy.failure(Failure::kDns, 119999, 1);
  CHECK(policy.nextAction(119999, true) == Action::kNone);
  CHECK(policy.nextAction(120000, true) == Action::kNone);
  policy.failure(Failure::kDns, 120000, 1);
  CHECK(policy.nextAction(120000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(120000));
  return true;
}

bool planned_suspend_does_not_extend_the_real_time_radio_budget() {
  Policy policy;
  dns(policy, 0);
  CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(60000));
  policy.suspend(60001);
  policy.resume(960001);
  dns(policy, 960002);
  CHECK(policy.nextAction(1020002, true) == Action::kRestartStationInterface);
  CHECK(policy.commitAction(1020002));
  dns(policy, 1020003);
  CHECK(policy.nextAction(1140001, true) == Action::kNone);
  CHECK(policy.nextAction(1140002, true) == Action::kRestartStationInterface);
  return true;
}

bool raw_connected_observation_is_not_an_adopted_stable_session() {
  Policy policy;
  dns(policy, 0);
  CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(60000));
  policy.observeConnected(60001, true);  // No adopted callback.
  policy.observeConnected(120001, true);
  dns(policy, 120002);
  CHECK(policy.nextAction(180002, true) == Action::kRestartStationInterface);
  return true;
}

bool uninterrupted_two_hour_fault_remains_bounded_without_exhausting_recovery() {
  Policy policy;
  std::vector<uint32_t> actions;
  uint32_t generation = 1;
  // Rolling windows are (now - 900,000, now]; the observation is [0, 7,200,000).
  for (uint32_t now = 0; now < 7200000; now += 1000) {
    if (now % 30000 == 0) policy.failure(Failure::kDns, now, generation);
    const auto action = policy.nextAction(now, true);
    if (action == Action::kNone) continue;
    CHECK(action == (actions.empty() ? Action::kReassociateStation
                                   : Action::kRestartStationInterface));
    CHECK(actions.empty() || now - actions.back() >= 120000);
    CHECK(policy.commitAction(now));
    actions.push_back(now);
    ++generation;  // Accepted station recovery produces a new Wi-Fi link.
    size_t in_window = 0;
    for (const uint32_t previous : actions)
      if (now - previous < 900000) ++in_window;
    CHECK(in_window <= 2);
  }
  CHECK(actions.size() >= 4);  // Stage two must not stop recovery permanently.
  CHECK(actions.size() <= 16);
  return true;
}


bool old_failure_burst_cannot_become_new_progress_evidence_after_silence() {
  Policy policy;
  policy.failure(Failure::kDns, 0, 1);
  policy.failure(Failure::kDns, 1, 1);
  policy.failure(Failure::kDns, 2, 1);
  CHECK(policy.nextAction(60000, true) == Action::kNone);
  CHECK(policy.nextAction(3600000, true) == Action::kNone);
  policy.failure(Failure::kDns, 3600001, 1);
  CHECK(policy.nextAction(3600001, true) == Action::kReassociateStation);
  return true;
}

bool mixed_qualifying_failures_use_the_slower_transport_threshold() {
  Policy policy;
  for (uint32_t i = 0; i < 6; ++i)
    policy.failure(i < 2 ? Failure::kDns : Failure::kTransport, i * 36000, 1);
  CHECK(policy.nextAction(180000, true) == Action::kReassociateStation);
  return true;
}

bool failure_counter_saturation_does_not_disable_recovery() {
  Policy policy;
  for (uint32_t i = 0; i < 70000; ++i)
    policy.failure(Failure::kDns, i * 100, 1);
  CHECK(policy.nextAction(7000000, true) == Action::kReassociateStation);
  return true;
}


bool observed_new_link_retires_old_qualification_without_a_new_failure() {
  Policy policy;
  dns(policy, 0, 1);
  CHECK(policy.nextAction(60000, true) == Action::kReassociateStation);
  policy.observeLinkGeneration(2);
  CHECK(!policy.commitAction(60000));
  CHECK(policy.nextAction(60000, true) == Action::kNone);
  policy.failure(Failure::kDns, 60001, 2);
  policy.observeLinkGeneration(2);
  policy.failure(Failure::kDns, 90001, 2);
  policy.observeLinkGeneration(2);
  policy.failure(Failure::kDns, 120001, 2);
  CHECK(policy.nextAction(120001, true) == Action::kReassociateStation);
  CHECK(policy.commitAction(120001));
  policy.observeLinkGeneration(3);
  dns(policy, 120002, 3);
  CHECK(policy.nextAction(240000, true) == Action::kNone);
  CHECK(policy.nextAction(240001, true) == Action::kRestartStationInterface);
  CHECK(policy.commitAction(240001));
  policy.observeLinkGeneration(4);
  dns(policy, 240002, 4);
  CHECK(policy.nextAction(1020000, true) == Action::kNone);
  CHECK(policy.nextAction(1020001, true) == Action::kRestartStationInterface);
  return true;
}

int main() {
  const struct { const char* name; bool (*run)(); } cases[] = {
    {"DNS threshold", dns_failure_threshold_is_real_and_bounded},
    {"transport threshold", generic_transport_requires_six_failures_and_three_minutes},
    {"excluded failures", excluded_failures_invalidate_old_pending_radio_requests},
    {"same-link evidence", wifi_generation_change_requires_new_same_link_evidence},
    {"safe deferred selection", selection_is_not_acceptance_and_safe_deferral_does_not_spend_budget},
    {"stale selection", stale_selected_action_cannot_commit_after_new_link_or_adoption},
    {"repeated stage two", continued_failure_repeats_stage_two_only_after_rolling_budget_and_spacing},
    {"transient connection", short_connection_does_not_reset_stage_or_failure_debt},
    {"stable connection", stable_connection_resets_stage_but_preserves_global_budget_and_spacing},
    {"rejected action", rejected_adapter_action_retries_slowly_without_consuming_radio_budget},
    {"clock wrap", zero_timestamps_and_clock_wrap_preserve_thresholds_and_budget},
    {"planned suspend", planned_suspend_excludes_deliberate_time_and_ignored_failures},
    {"real-time budget", planned_suspend_does_not_extend_the_real_time_radio_budget},
    {"raw connected flag", raw_connected_observation_is_not_an_adopted_stable_session},
    {"two-hour fault", uninterrupted_two_hour_fault_remains_bounded_without_exhausting_recovery},
    {"old error burst", old_failure_burst_cannot_become_new_progress_evidence_after_silence},
    {"mixed failure threshold", mixed_qualifying_failures_use_the_slower_transport_threshold},
    {"counter saturation", failure_counter_saturation_does_not_disable_recovery},
    {"link observation without failure", observed_new_link_retires_old_qualification_without_a_new_failure},
  };
  unsigned failures = 0;
  for (const auto& test : cases) {
    if (!test.run()) {
      std::fprintf(stderr, "FAIL: %s\n", test.name);
      ++failures;
    }
  }
  if (failures != 0) return 1;
  std::printf("network recovery policy PASS (%zu scenarios, no reboot action)\n",
              sizeof(cases) / sizeof(cases[0]));
}
