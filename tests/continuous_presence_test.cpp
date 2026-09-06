#include "AccessCriticalLeasePolicy.h"
#include "PassageRearmPolicy.h"
#include "TargetAccessFsm.h"
#include <cassert>
#include <cstdio>

int main() {
  for (bool sensor : {false, true}) {
    sgk::AccessCriticalLeasePolicy lease(85000, 30000);
    sgk::TargetAccessFsm fsm(nullptr, nullptr);
    fsm.begin(0);
    assert(fsm.handleAuthPending(0, 5000));
    assert(!lease.expired(0, true, 0, 10000));
    assert(fsm.handleAuthSuccess(2000, 60000, 3000));
    assert(!lease.expired(2000, true, 1, 85000));
    uint32_t terminal = 62000;
    if (sensor) {
      assert(fsm.handleSensorTrigger(12000, 1000, 3000));
      fsm.tick(13000);
      assert(fsm.state() == GateState::COOLDOWN);
      terminal = 16000;
    }
    fsm.tick(terminal);
    assert(fsm.state() == GateState::IDLE);
    lease.retireVerifiedAction(1);
    assert(fsm.handleAuthPending(terminal + 1, 5000));
    assert(!lease.expired(terminal + 1, true, 1, 10000));
    assert(!lease.expired(terminal + 2000, true, 1, 10000));
    assert(fsm.handleAuthSuccess(terminal + 2000, 60000, 3000));
    assert(!lease.expired(terminal + 2000, true, 2, 85000));
  }
  sgk::AccessCriticalLeasePolicy unverified(85000, 30000);
  assert(!unverified.expired(0, true, 0, 10000));
  unverified.retireVerifiedAction(0);
  unverified.retireVerifiedAction(1);
  assert(unverified.expired(10000, true, 0, 10000));

  sgk::PassageRearmPolicy passage;
  assert(!passage.blocked());
  passage.notePulse();
  for (int i = 0; i < 100; ++i) passage.observe(false);
  assert(passage.blocked());
  passage.observe(true);
  passage.observe(true);
  assert(passage.blocked());
  passage.observe(false);
  passage.observe(true);
  passage.observe(true);
  assert(passage.blocked());
  passage.observe(true);
  assert(!passage.blocked());
  passage.notePulse();
  assert(passage.blocked());

  sgk::PresenceReadyPolicy ready(42);
  assert(!ready.update(100, true));
  assert(!ready.update(1099, true));
  assert(ready.update(1100, true));
  assert(ready.epoch() == 43);
  assert(ready.update(9999, true));
  assert(ready.epoch() == 43);
  assert(!ready.update(10000, false));
  assert(!ready.update(10001, true));
  assert(ready.update(11001, true));
  assert(ready.epoch() == 44);
  std::puts("continuous-presence terminal, no-replay, clearance and network-yield cases passed");
}
