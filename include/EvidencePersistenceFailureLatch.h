#pragma once

namespace sgk {

// Separates a failure carried from the previous boot from a new failure raised
// in the current boot. A successful boot-diagnostics publish may acknowledge
// only the carried signal; a newly raised signal must survive the next reset.
class EvidencePersistenceFailureLatch {
 public:
  void begin(bool carried_failure) {
    carried_failure_pending_ = carried_failure;
    raised_this_boot_ = false;
  }

  void mark() { raised_this_boot_ = true; }

  void acknowledgeCarriedFailure() { carried_failure_pending_ = false; }

  bool active() const {
    return carried_failure_pending_ || raised_this_boot_;
  }

  bool carriedFailurePending() const { return carried_failure_pending_; }
  bool raisedThisBoot() const { return raised_this_boot_; }

 private:
  bool carried_failure_pending_ = false;
  bool raised_this_boot_ = false;
};

}  // namespace sgk
