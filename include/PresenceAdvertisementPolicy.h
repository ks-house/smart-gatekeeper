#pragma once

#include <cstdint>

namespace sgk {

class PresenceAdvertisementDriver {
 public:
  virtual ~PresenceAdvertisementDriver() = default;
  virtual bool available() const = 0;
  virtual bool active() const = 0;
  virtual bool apply(bool ready, uint32_t epoch) = 0;
  virtual bool stop() = 0;
  virtual bool start() = 0;
};

// Main-loop-owned controller API evidence, never RF reception evidence. A
// failed apply remains pending. Retry spacing survives changing requested
// epochs, and controller mutation is forbidden during connection/OTA leases.
class PresenceAdvertisementPolicy {
 public:
  bool requested_ready = false;
  uint32_t requested_epoch = 0;
  bool applied_ready = false;
  uint32_t applied_epoch = 0;
  bool applied_valid = false;
  bool pending = false;
  const char* status = "NOT_REQUESTED";
  const char* last_result = "NONE";
  uint32_t attempts = 0;
  uint32_t failures = 0;
  uint32_t retries = 0;
  uint32_t stops = 0;
  uint32_t last_attempt_ms = 0;
  uint32_t applied_ms = 0;
  uint32_t gap_count = 0;
  uint32_t last_gap_ms = 0;

  void request(bool ready, uint32_t epoch, bool force = false) {
    if (requested_ && !force && requested_ready == ready && requested_epoch == epoch) return;
    requested_ = true;
    requested_ready = ready;
    requested_epoch = epoch;
    if (force) applied_valid = false;  // Another owner rebuilt the scan response.
    pending = !applied_valid || applied_ready != ready || applied_epoch != epoch;
    status = pending ? "PENDING" : "APPLIED";
  }

  void observeController(uint32_t now_ms, bool active, bool expected_unleased) {
    if (!expected_unleased) {
      // Connection/OTA intervals are intentional exclusions, not inferred
      // advertising outages. Do not include their duration in a later gap.
      if (gap_open_) last_gap_ms = now_ms - gap_since_ms_;
      gap_open_ = false;
      return;
    }
    if (!active && !gap_open_) {
      gap_open_ = true;
      gap_since_ms_ = now_ms;
      increment(gap_count);
    } else if (active && gap_open_) {
      last_gap_ms = now_ms - gap_since_ms_;
      gap_open_ = false;
    }
  }
  uint32_t gapMs(uint32_t now_ms) const { return gap_open_ ? now_ms - gap_since_ms_ : 0; }

  void service(uint32_t now_ms, bool enabled, bool connected, bool ota_busy,
               PresenceAdvertisementDriver& driver) {
    if (!requested_) return;
    if (!enabled) { status = "DISABLED"; return; }
    if (connected) { status = "DEFERRED_CONNECTION"; return; }
    if (ota_busy) { status = "DEFERRED_OTA"; return; }
    if (!pending) { status = "APPLIED"; return; }
    if (failed_attempt_ && now_ms - last_attempt_ms < retry_ms_) {
      status = "RETRY_WAIT";
      return;
    }
    if (failed_attempt_) increment(retries);
    increment(attempts);
    last_attempt_ms = now_ms;
    if (!driver.available()) { fail("UNAVAILABLE"); return; }
    // Try a normal in-place update first. Some controller states reject it;
    // only the bounded retry uses stop -> apply -> start recovery.
    if (failed_attempt_ && driver.active()) {
      if (!driver.stop()) { fail("STOP_FAILED"); return; }
      increment(stops);
      observeController(now_ms, false, true);
    }
    if (!driver.apply(requested_ready, requested_epoch)) {
      applied_valid = false;
      fail("APPLY_FAILED");
      // Preserve discoverability even if the replacement payload failed.
      // This restart is still under the caller's connection/OTA mutex guard.
      if (!driver.active() && !driver.start()) last_result = "APPLY_START_FAILED";
      return;
    }
    applied_ready = requested_ready;
    applied_epoch = requested_epoch;
    applied_valid = true;
    applied_ms = now_ms;
    if (!driver.active() && !driver.start()) { fail("START_FAILED"); return; }
    observeController(now_ms, driver.active(), true);
    pending = false;
    failed_attempt_ = false;
    retry_ms_ = 500;
    status = last_result = "APPLIED";
  }

 private:
  bool requested_ = false;
  bool failed_attempt_ = false;
  uint32_t retry_ms_ = 500;
  bool gap_open_ = false;
  uint32_t gap_since_ms_ = 0;
  static void increment(uint32_t& counter) { if (counter != UINT32_MAX) ++counter; }
  void fail(const char* result) {
    increment(failures);
    status = last_result = result;
    if (failed_attempt_ && retry_ms_ < 5000) {
      retry_ms_ *= 2;
      if (retry_ms_ > 5000) retry_ms_ = 5000;
    }
    failed_attempt_ = pending = true;
  }
};

}  // namespace sgk
