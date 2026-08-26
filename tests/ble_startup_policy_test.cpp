#include "BleStartupPolicy.h"

#include <cstdlib>
#include <iostream>

namespace {

int checks = 0;

#define CHECK(condition)                                                \
  do {                                                                  \
    ++checks;                                                           \
    if (!(condition)) {                                                 \
      std::cerr << "CHECK failed at line " << __LINE__ << ": "        \
                << #condition << std::endl;                             \
      std::exit(1);                                                     \
    }                                                                   \
  } while (0)

void testHardwarelessWaitsForActiveAclAndStartsOnce() {
  sgk::BleStartupPolicy policy(true);
  CHECK(!policy.started());
  CHECK(!policy.shouldStart(false));
  CHECK(!policy.started());
  CHECK(policy.shouldStart(true));
  CHECK(policy.started());
  CHECK(!policy.shouldStart(true));
  CHECK(!policy.shouldStart(false));
}

void testLegacyBeaconStartsWithoutAclAndStartsOnce() {
  sgk::BleStartupPolicy policy(false);
  CHECK(policy.shouldStart(false));
  CHECK(policy.started());
  CHECK(!policy.shouldStart(true));
}

}  // namespace

int main() {
  testHardwarelessWaitsForActiveAclAndStartsOnce();
  testLegacyBeaconStartsWithoutAclAndStartsOnce();
  std::cout << "BleStartupPolicy host tests passed: " << checks
            << " checks" << std::endl;
  return 0;
}
