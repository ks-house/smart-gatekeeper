#pragma once

#include "GattProtocol.h"
#include "TargetAclManager.h"

namespace sgk {

class TargetProofVerifier final : public ProofVerifier {
 public:
  TargetProofVerifier(TargetAclManager& acl_manager,
                      uint32_t (*get_now_ms_fn)(),
                      uint64_t (*get_epoch_s_fn)() = nullptr);

  uint64_t activeAclVersion() const override;
  VerifyResult verify(const VerifyRequest& request) override;

 private:
  TargetAclManager& acl_manager_;
  uint32_t (*get_now_ms_fn_)();
  uint64_t (*get_epoch_s_fn_)();
};

}  // namespace sgk
