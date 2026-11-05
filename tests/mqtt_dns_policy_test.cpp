#include "MqttDnsPolicy.h"

#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include <limits>
#include <type_traits>

#define CHECK(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "DNS policy check failed at line %d: %s\n", __LINE__, #condition); \
  std::exit(1); } } while (0)

namespace {
using sgk::MqttDnsPolicy;
using sgk::MqttDnsPoll;

void readyPersistsUntilResetAndBeginDoesNotExtendPendingDeadline() {
  MqttDnsPolicy policy(5000);
  CHECK(policy.poll(0) == MqttDnsPoll::kIdle);
  const uint32_t generation = policy.begin(0);
  CHECK(generation != 0);
  CHECK(policy.poll(0) == MqttDnsPoll::kPending);
  CHECK(policy.begin(4999) == generation);
  CHECK(policy.poll(4999) == MqttDnsPoll::kPending);
  CHECK(policy.complete(generation, true, 4999));
  CHECK(policy.poll(5000) == MqttDnsPoll::kReady);
  CHECK(policy.poll(500000) == MqttDnsPoll::kReady);
  CHECK(policy.begin(500001) == generation);
  CHECK(!policy.complete(generation, false, 500001));
  CHECK(policy.poll(500002) == MqttDnsPoll::kReady);
  policy.reset();
  CHECK(policy.poll(500003) == MqttDnsPoll::kIdle);
  CHECK(!policy.complete(generation, true, 500003));
  MqttDnsPolicy still_pending(5000);
  const uint32_t pending_generation = still_pending.begin(0);
  CHECK(still_pending.begin(4999) == pending_generation);
  CHECK(still_pending.poll(5000) == MqttDnsPoll::kTimedOut);
}

void synchronousFailureIsConsumedOnceAndOldCallbackCannotCompleteNextQuery() {
  MqttDnsPolicy policy(5000);
  const uint32_t first = policy.begin(100);
  CHECK(policy.complete(first, false, 100));
  CHECK(!policy.complete(first, true, 101));
  CHECK(policy.begin(101) == first);
  CHECK(policy.poll(100) == MqttDnsPoll::kFailed);
  CHECK(policy.poll(101) == MqttDnsPoll::kIdle);
  CHECK(policy.poll(102) == MqttDnsPoll::kIdle);
  const uint32_t second = policy.begin(102);
  CHECK(second != 0 && second != first);
  CHECK(!policy.complete(first, true, 103));
  CHECK(policy.poll(103) == MqttDnsPoll::kPending);
  CHECK(policy.complete(second, true, 104));
  CHECK(policy.poll(104) == MqttDnsPoll::kReady);
}

void exactDeadlineAndLateCallbackCannotWinBeforeMainPolls() {
  for (uint32_t callback : {5100U, 5101U, 9000U}) {
    MqttDnsPolicy policy(5000);
    const uint32_t generation = policy.begin(100);
    CHECK(!policy.complete(generation, true, callback));
    CHECK(policy.poll(callback) == MqttDnsPoll::kTimedOut);
    CHECK(policy.poll(callback) == MqttDnsPoll::kIdle);
    CHECK(!policy.complete(generation, true, callback + 1));
  }
  MqttDnsPolicy failed(5000);
  const uint32_t generation = failed.begin(100);
  CHECK(!failed.complete(generation, false, 5100));
  CHECK(failed.poll(5100) == MqttDnsPoll::kTimedOut);
  CHECK(failed.poll(5101) == MqttDnsPoll::kIdle);
}

void pendingTimeoutIsConsumedOnceAndRejectsStaleAndZeroGenerations() {
  MqttDnsPolicy policy(5000);
  const uint32_t first = policy.begin(200);
  CHECK(!policy.complete(0, true, 201));
  CHECK(!policy.complete(first + 1, true, 201));
  CHECK(policy.poll(5199) == MqttDnsPoll::kPending);
  CHECK(policy.poll(5200) == MqttDnsPoll::kTimedOut);
  CHECK(policy.poll(5200) == MqttDnsPoll::kIdle);
  CHECK(!policy.complete(first, true, 5201));
  const uint32_t second = policy.begin(5201);
  CHECK(second != first && second != 0);
  CHECK(!policy.complete(first, false, 5202));
  CHECK(policy.complete(second, true, 5203));
  CHECK(policy.poll(5203) == MqttDnsPoll::kReady);
}

void resetInvalidatesOutstandingCallbackAndAcceptedAddressCopy() {
  MqttDnsPolicy policy(5000);
  int copied_address = 0;
  const auto callback = [&](uint32_t generation, int address, uint32_t now) {
    const bool success = address != 0;
    const bool accepted = policy.complete(generation, success, now);
    if (accepted && success) copied_address = address;
  };
  const uint32_t first = policy.begin(0);
  policy.reset();
  callback(first, 17, 1);
  CHECK(copied_address == 0 && policy.poll(1) == MqttDnsPoll::kIdle);
  const uint32_t second = policy.begin(1);
  callback(first, 99, 2);
  CHECK(copied_address == 0 && policy.poll(2) == MqttDnsPoll::kPending);
  callback(second, 23, 3);
  callback(first, 99, 4);
  CHECK(copied_address == 23 && policy.poll(4) == MqttDnsPoll::kReady);

  policy.reset();
  copied_address = 0;
  const uint32_t third = policy.begin(10);
  callback(third, 42, 5010);
  CHECK(copied_address == 0 && policy.poll(5010) == MqttDnsPoll::kTimedOut);
}

void wrapAndZeroTimesPreserveRealDeadline() {
  constexpr uint32_t maximum = std::numeric_limits<uint32_t>::max();
  MqttDnsPolicy late(5000);
  const uint32_t first = late.begin(maximum - 2499);
  CHECK(late.poll(2499) == MqttDnsPoll::kPending);
  CHECK(!late.complete(first, true, 2500));
  CHECK(late.poll(2500) == MqttDnsPoll::kTimedOut);
  CHECK(late.poll(2501) == MqttDnsPoll::kIdle);

  MqttDnsPolicy in_time(5000);
  const uint32_t second = in_time.begin(maximum - 2499);
  CHECK(in_time.complete(second, true, 2499));
  CHECK(in_time.poll(2500) == MqttDnsPoll::kReady);
  MqttDnsPolicy zero_now(5000);
  const uint32_t third = zero_now.begin(maximum);
  CHECK(zero_now.complete(third, true, 0));
  CHECK(zero_now.poll(0) == MqttDnsPoll::kReady);

  MqttDnsPolicy immediate(0);
  const uint32_t fourth = immediate.begin(0);
  CHECK(!immediate.complete(fourth, true, 0));
  CHECK(immediate.poll(0) == MqttDnsPoll::kTimedOut);
  CHECK(immediate.poll(0) == MqttDnsPoll::kIdle);
}

void generationWrapSkipsReservedZero() {
  CHECK(sgk::nextMqttDnsGeneration(0) == 1);
  CHECK(sgk::nextMqttDnsGeneration(1) == 2);
  CHECK(sgk::nextMqttDnsGeneration(std::numeric_limits<uint32_t>::max()) == 1);
}
}  // namespace

int main() {
  static_assert(std::is_trivially_copyable<MqttDnsPolicy>::value,
                "DNS policy must remain value-only and allocation-free");
  readyPersistsUntilResetAndBeginDoesNotExtendPendingDeadline();
  synchronousFailureIsConsumedOnceAndOldCallbackCannotCompleteNextQuery();
  exactDeadlineAndLateCallbackCannotWinBeforeMainPolls();
  pendingTimeoutIsConsumedOnceAndRejectsStaleAndZeroGenerations();
  resetInvalidatesOutstandingCallbackAndAcceptedAddressCopy();
  wrapAndZeroTimesPreserveRealDeadline();
  generationWrapSkipsReservedZero();
  std::puts("MQTT DNS policy host tests PASS");
}
