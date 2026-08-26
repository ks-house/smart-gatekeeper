#pragma once

namespace sgk {

// Decides when the one-shot BLE stack initialization is safe. Personal
// Hardwareless builds must not advertise an actionable wake target until the
// signed ACL has been refreshed after boot. Non-Hardwareless builds preserve
// the legacy immediate beacon startup contract.
class BleStartupPolicy {
 public:
  explicit BleStartupPolicy(bool require_active_acl)
      : require_active_acl_(require_active_acl) {}

  bool shouldStart(bool active_acl_available) {
    if (started_) return false;
    if (require_active_acl_ && !active_acl_available) return false;
    started_ = true;
    return true;
  }

  bool started() const { return started_; }

 private:
  bool require_active_acl_ = false;
  bool started_ = false;
};

}  // namespace sgk
