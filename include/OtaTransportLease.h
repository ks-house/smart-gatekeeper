#pragma once

namespace sgk {
// Declare before the OTA client, so TLS destruction precedes reconnect.
template <typename Transport>
class OtaTransportLease {
 public:
  OtaTransportLease() = default;
  OtaTransportLease(const OtaTransportLease&) = delete;
  OtaTransportLease& operator=(const OtaTransportLease&) = delete;
  bool acquire() {
    if (owned_) return false;
    owned_ = Transport::suspendForOta();
    return owned_;
  }
  ~OtaTransportLease() {
    if (owned_) Transport::resumeAfterOta();
  }
 private:
  bool owned_ = false;
};
}  // namespace sgk
