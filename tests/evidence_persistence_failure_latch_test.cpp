#include <cstdio>

#include "EvidencePersistenceFailureLatch.h"

namespace {

#define CHECK(condition)                                                   \
  do {                                                                     \
    if (!(condition)) {                                                    \
      std::fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__,       \
                   __LINE__, #condition);                                  \
      return false;                                                        \
    }                                                                      \
  } while (false)

bool carriedFailureSurvivesRepeatedResetUntilAcknowledged() {
  sgk::EvidencePersistenceFailureLatch first_boot;
  first_boot.begin(true);
  CHECK(first_boot.active());
  CHECK(first_boot.carriedFailurePending());

  // A second reset before boot diagnostics publish carries the same signal.
  sgk::EvidencePersistenceFailureLatch second_boot;
  second_boot.begin(first_boot.active());
  CHECK(second_boot.active());
  CHECK(second_boot.carriedFailurePending());

  second_boot.acknowledgeCarriedFailure();
  CHECK(!second_boot.active());
  CHECK(!second_boot.carriedFailurePending());
  return true;
}

bool currentBootFailureIsNotClearedByPreviousFailureAcknowledgement() {
  sgk::EvidencePersistenceFailureLatch latch;
  latch.begin(true);
  latch.mark();
  latch.acknowledgeCarriedFailure();
  CHECK(latch.active());
  CHECK(!latch.carriedFailurePending());
  CHECK(latch.raisedThisBoot());

  // The current-boot failure becomes the carried signal after the next reset.
  sgk::EvidencePersistenceFailureLatch next_boot;
  next_boot.begin(latch.active());
  CHECK(next_boot.active());
  CHECK(next_boot.carriedFailurePending());
  CHECK(!next_boot.raisedThisBoot());
  return true;
}

bool acknowledgementCannotClearCurrentBootOnlyFailure() {
  sgk::EvidencePersistenceFailureLatch latch;
  latch.begin(false);
  latch.mark();
  latch.acknowledgeCarriedFailure();
  CHECK(latch.active());
  CHECK(latch.raisedThisBoot());
  return true;
}

}  // namespace

int main() {
  if (!carriedFailureSurvivesRepeatedResetUntilAcknowledged()) return 1;
  if (!currentBootFailureIsNotClearedByPreviousFailureAcknowledgement()) {
    return 1;
  }
  if (!acknowledgementCannotClearCurrentBootOnlyFailure()) return 1;
  return 0;
}
