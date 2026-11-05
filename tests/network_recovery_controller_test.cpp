#include "NetworkRecoveryController.h"

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <string>
#include <vector>

using Policy = sgk::NetworkRecoveryPolicy;
using Controller = sgk::NetworkRecoveryController;
using Action = Policy::Action;
using Failure = Policy::FailureKind;

#define CHECK(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "%s:%d: %s\n", __func__, __LINE__, #condition); \
  return false; } } while (0)

struct Driver {
  bool external = false, safe = true, reserve_ok = true, associated = true;
  bool pending = false, begin_ok = true, finish_ok = true, held = false;
  uint32_t now = 60000, generation = 1, begin_advance_ms = 0;
  unsigned reserves = 0, releases = 0, invalidations = 0, begins = 0, finishes = 0;
  unsigned cancel_restore = 0, cancel_flag = 0, unreserved_mutations = 0;
  std::vector<std::string> events;
  std::vector<Action> finished_actions;
  std::function<void()> after_reserve;
  std::function<void()> during_begin;
  bool externalRecoveryActive() { return external; }
  bool safeForRepair() { return safe; }
  bool stationAssociated() { return associated; }
  uint32_t linkGeneration() { return generation; }
  bool ownsStationRepair() { return pending; }
  uint32_t nowMillis() { return now; }
  bool tryReserve() {
    ++reserves; events.push_back("reserve");
    if (!reserve_ok) return false;
    assert(!held); held = true;
    if (after_reserve) { auto hook = after_reserve; after_reserve = {}; hook(); }
    return true;
  }
  void release() { assert(held); held = false; ++releases; events.push_back("release"); }
  void invalidateTransport() { checkHeld(); ++invalidations; events.push_back("invalidate"); }
  bool beginDisconnect() {
    checkHeld(); ++begins; events.push_back("disconnect"); now += begin_advance_ms;
    if (during_begin) { auto hook = during_begin; during_begin = {}; hook(); }
    if (begin_ok) pending = true;
    return begin_ok;
  }
  bool finishReconnect(Action action) {
    checkHeld(); ++finishes; events.push_back("reconnect"); finished_actions.push_back(action);
    pending = false;
    if (finish_ok) { associated = true; ++generation; }
    return finish_ok;
  }
  void cancelRepair(bool restore_auto) {
    if (restore_auto) { checkHeld(); ++cancel_restore; events.push_back("restore"); }
    else { ++cancel_flag; events.push_back("clear-flag"); }
    pending = false;
  }
  void checkHeld() { if (!held) ++unreserved_mutations; }
};

void qualify(Policy& policy, uint32_t start = 0, uint32_t generation = 1) {
  policy.failure(Failure::kDns, start, generation);
  policy.failure(Failure::kDns, start + 30000, generation);
  policy.failure(Failure::kDns, start + 60000, generation);
}

bool ordered_async_repair_reconnects_once_after_raw_disassociation() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(60000, policy, driver));
  CHECK(controller.active() && !driver.held && driver.pending);
  CHECK(driver.events == std::vector<std::string>({"reserve", "invalidate", "disconnect", "release"}));
  driver.now = 61000;
  CHECK(controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 0 && driver.begins == 1 && driver.reserves == 1);
  driver.associated = false; driver.now = 61001;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(!controller.active() && driver.finishes == 1);
  CHECK(driver.finished_actions[0] == Action::kReassociateStation);
  CHECK(driver.unreserved_mutations == 0 && driver.reserves == driver.releases);
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 1 && controller.diagnostics().completed == 1);
  return true;
}

bool unchanged_association_never_reconnects_and_times_out_exactly() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(60000, policy, driver));
  driver.now = 61999;
  CHECK(controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 0 && driver.cancel_restore == 0);
  driver.now = 62000;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(!controller.active() && driver.finishes == 0 && driver.cancel_restore == 1);
  CHECK(controller.diagnostics().timeouts == 1 && !driver.held);
  return true;
}

bool quick_disconnect_reconnect_generation_skips_reassociate_stage() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(60000, policy, driver));
  ++driver.generation; driver.now = 60001;  // Raw association already recovered.
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 0 && driver.cancel_restore == 1);
  CHECK(controller.diagnostics().completed == 1 && !controller.active());
  return true;
}

bool quick_generation_recovery_does_not_skip_stage_two_restart() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(60000, policy, driver));
  ++driver.generation; driver.now = 60001;
  CHECK(!controller.service(driver.now, policy, driver));
  qualify(policy, 60002, driver.generation);
  driver.now = 180000;
  CHECK(controller.service(driver.now, policy, driver));
  ++driver.generation; driver.now = 180001;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 1 && driver.finished_actions[0] == Action::kRestartStationInterface);
  CHECK(driver.unreserved_mutations == 0 && !driver.held);
  return true;
}

bool idle_external_busy_disconnected_and_no_qualification_do_not_mutate() {
  for (unsigned kind = 0; kind < 4; ++kind) {
    Policy policy; Controller controller; Driver driver;
    if (kind != 3) qualify(policy);
    if (kind == 0) driver.external = true;
    if (kind == 1) driver.safe = false;
    if (kind == 2) driver.associated = false;
    CHECK(!controller.service(driver.now, policy, driver));
    CHECK(!controller.active() && driver.reserves == 0 && driver.invalidations == 0);
  }
  return true;
}

bool denied_reservation_spends_no_policy_budget() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  driver.reserve_ok = false;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.invalidations == 0 && driver.begins == 0 && driver.releases == 0);
  CHECK(controller.diagnostics().reserve_failures == 1);
  driver.reserve_ok = true;
  CHECK(controller.service(driver.now, policy, driver));
  CHECK(controller.diagnostics().started == 1);
  return true;
}

bool idle_guards_are_rechecked_after_successful_reservation() {
  for (unsigned kind = 0; kind < 3; ++kind) {
    Policy policy; Controller controller; Driver driver; qualify(policy);
    driver.after_reserve = [&] {
      if (kind == 0) driver.safe = false;
      if (kind == 1) driver.external = true;
      if (kind == 2) driver.associated = false;
    };
    CHECK(!controller.service(driver.now, policy, driver));
    CHECK(driver.invalidations == 0 && driver.begins == 0 && !driver.held);
    CHECK(driver.reserves == 1 && driver.releases == 1);
    CHECK(!policy.commitAction(driver.now));
  }
  return true;
}

bool external_takeover_clears_only_pending_flag_without_radio_lease() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(driver.now, policy, driver));
  driver.external = true; driver.safe = false; driver.reserve_ok = false;
  CHECK(!controller.service(driver.now + 1, policy, driver));
  CHECK(!controller.active() && driver.cancel_flag == 1 && driver.cancel_restore == 0);
  CHECK(driver.reserves == 1 && driver.finishes == 0 && !driver.held);
  CHECK(controller.diagnostics().cancelled == 1);
  return true;
}

bool lost_wifi_pending_lease_retires_without_touching_other_owners() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(driver.now, policy, driver));
  driver.pending = false;  // Independent WifiManager 15-second escape.
  CHECK(!controller.service(driver.now + 15000, policy, driver));
  CHECK(!controller.active() && driver.finishes == 0 && driver.cancel_restore == 0);
  CHECK(controller.diagnostics().cancelled == 1);
  return true;
}

bool waiting_busy_and_reservation_races_defer_without_new_mutations() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(driver.now, policy, driver));
  driver.associated = false; driver.safe = false; driver.now = 65000;
  CHECK(controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 0 && driver.reserves == 1);
  driver.safe = true;
  driver.after_reserve = [&] { driver.safe = false; };
  CHECK(controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 0 && driver.reserves == driver.releases && !driver.held);
  driver.safe = true;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 1 && driver.unreserved_mutations == 0);
  return true;
}

bool waiting_external_race_only_clears_flag_and_releases_reservation() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(driver.now, policy, driver));
  driver.associated = false; ++driver.now;
  driver.after_reserve = [&] { driver.external = true; };
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 0 && driver.cancel_flag == 1 && driver.cancel_restore == 0);
  CHECK(driver.reserves == driver.releases && !driver.held);
  return true;
}

bool denied_waiting_timeout_reservation_cannot_restore_auto_unreserved() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(driver.now, policy, driver));
  driver.now = 62000; driver.reserve_ok = false;
  CHECK(controller.service(driver.now, policy, driver));
  CHECK(driver.cancel_restore == 0 && controller.active());
  driver.reserve_ok = true;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.cancel_restore == 1 && driver.unreserved_mutations == 0);
  return true;
}

bool rejected_disconnect_is_cleaned_and_retry_is_delayed_without_spending_budget() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  driver.begin_ok = false;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.begins == 1 && driver.cancel_restore == 1 && !controller.active());
  CHECK(controller.diagnostics().rejected == 1 && controller.diagnostics().started == 0);
  driver.begin_ok = true; driver.now = 89999;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.begins == 1);
  driver.now = 90000;
  CHECK(controller.service(driver.now, policy, driver));
  CHECK(driver.begins == 2 && controller.diagnostics().started == 1 && !driver.held);
  return true;
}

bool rejected_reconnect_finishes_once_and_releases_its_pending_flag() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  CHECK(controller.service(driver.now, policy, driver));
  driver.associated = false; driver.finish_ok = false; ++driver.now;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 1 && driver.cancel_restore == 1 && !driver.pending);
  CHECK(controller.diagnostics().rejected == 1 && controller.diagnostics().completed == 0);
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(driver.finishes == 1 && driver.unreserved_mutations == 0);
  return true;
}

bool superseded_policy_selection_is_not_committed_after_driver_acceptance() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  driver.during_begin = [&] { policy.failure(Failure::kAuthorization, driver.now, 1); };
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(!controller.active() && !driver.pending && driver.cancel_restore == 1);
  CHECK(controller.diagnostics().commit_failures == 1 && controller.diagnostics().started == 0);
  qualify(policy, 60001);
  driver.now = 120001;
  CHECK(controller.service(driver.now, policy, driver));
  CHECK(controller.diagnostics().started == 1 && !driver.held);
  return true;
}

bool current_driver_clock_sets_commit_and_timeout_even_if_service_time_is_old() {
  Policy policy; Controller controller; Driver driver; qualify(policy);
  driver.begin_advance_ms = 777;
  CHECK(controller.service(60000, policy, driver));
  CHECK(driver.now == 60777);
  driver.begin_advance_ms = 0; driver.now = 62776;
  CHECK(controller.service(driver.now, policy, driver));
  driver.now = 62777;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(controller.diagnostics().timeouts == 1);
  qualify(policy, 62778);
  driver.now = 180776;
  CHECK(!controller.service(driver.now, policy, driver));
  driver.now = 180777;
  CHECK(controller.service(driver.now, policy, driver));
  return true;
}

bool timeout_and_pending_start_work_at_clock_wrap() {
  Policy policy; Controller controller; Driver driver;
  driver.now = UINT32_MAX - 1000;
  qualify(policy, driver.now - 60000);
  CHECK(controller.service(driver.now, policy, driver));
  driver.now += 1999;
  CHECK(controller.service(driver.now, policy, driver));
  ++driver.now;
  CHECK(!controller.service(driver.now, policy, driver));
  CHECK(controller.diagnostics().timeouts == 1 && driver.finishes == 0 && !driver.held);
  return true;
}

bool uninterrupted_fault_obeys_real_policy_budget_and_all_reservations_release() {
  Policy policy; Controller controller; Driver driver;
  std::vector<uint32_t> accepted;
  for (uint32_t now = 0; now < 7200000; now += 1000) {
    driver.now = now;
    if (controller.active()) { driver.associated = false; ++driver.generation; }
    if (now % 30000 == 0)
      policy.failure(Failure::kDns, now, driver.generation);
    const unsigned before = driver.begins;
    controller.service(now, policy, driver);
    if (driver.begins != before) {
      accepted.push_back(now);
      size_t in_window = 0;
      for (const uint32_t at : accepted) if (now - at < 900000) ++in_window;
      CHECK(in_window <= 2);
      if (accepted.size() > 1) CHECK(now - accepted[accepted.size() - 2] >= 120000);
    }
    CHECK(!driver.held && driver.reserves == driver.releases);
  }
  CHECK(accepted.size() >= 4 && accepted.size() <= 16);
  CHECK(driver.unreserved_mutations == 0 && driver.finishes == accepted.size());
  return true;
}

int main() {
  const struct { const char* name; bool (*run)(); } cases[] = {
    {"async order and once", ordered_async_repair_reconnects_once_after_raw_disassociation},
    {"disconnect deadline", unchanged_association_never_reconnects_and_times_out_exactly},
    {"quick reassociation", quick_disconnect_reconnect_generation_skips_reassociate_stage},
    {"stage two quick link", quick_generation_recovery_does_not_skip_stage_two_restart},
    {"idle exclusions", idle_external_busy_disconnected_and_no_qualification_do_not_mutate},
    {"reservation denial", denied_reservation_spends_no_policy_budget},
    {"idle guard races", idle_guards_are_rechecked_after_successful_reservation},
    {"external takeover", external_takeover_clears_only_pending_flag_without_radio_lease},
    {"lost pending lease", lost_wifi_pending_lease_retires_without_touching_other_owners},
    {"waiting guard race", waiting_busy_and_reservation_races_defer_without_new_mutations},
    {"waiting external race", waiting_external_race_only_clears_flag_and_releases_reservation},
    {"timeout reservation", denied_waiting_timeout_reservation_cannot_restore_auto_unreserved},
    {"disconnect rejection", rejected_disconnect_is_cleaned_and_retry_is_delayed_without_spending_budget},
    {"reconnect rejection", rejected_reconnect_finishes_once_and_releases_its_pending_flag},
    {"superseded selection", superseded_policy_selection_is_not_committed_after_driver_acceptance},
    {"driver current clock", current_driver_clock_sets_commit_and_timeout_even_if_service_time_is_old},
    {"clock wrap", timeout_and_pending_start_work_at_clock_wrap},
    {"two-hour policy budget", uninterrupted_fault_obeys_real_policy_budget_and_all_reservations_release},
  };
  unsigned failed = 0;
  for (const auto& test : cases) {
    if (!test.run()) { std::fprintf(stderr, "FAIL: %s\n", test.name); ++failed; }
  }
  if (failed) return 1;
  std::printf("network recovery controller PASS (%zu scenarios, %zu bytes)\n",
      sizeof(cases) / sizeof(cases[0]), sizeof(Controller));
}
