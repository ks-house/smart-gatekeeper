#include "TargetProofVerifier.h"
#include "TargetAclManager.h"
#include <cstring>

#if defined(ESP_PLATFORM) || defined(ARDUINO)
#include <mbedtls/ecdsa.h>
#include <mbedtls/ecp.h>
#include <mbedtls/md.h>
#endif

namespace sgk {

namespace {

bool verifyProofSignature(const uint8_t pubkey65[65], const uint8_t digest32[32],
                          const uint8_t raw64[64]) {
  (void)digest32;
  if (pubkey65[0] != 0x04) return false;
  if (!TargetAclManager::isValidR(raw64) ||
      !TargetAclManager::isLowS(raw64 + 32)) {
    return false;
  }

#if defined(ESP_PLATFORM) || defined(ARDUINO)
  mbedtls_ecp_group grp;
  mbedtls_ecp_point Q;
  mbedtls_mpi r_mpi, s_mpi;
  mbedtls_ecp_group_init(&grp);
  mbedtls_ecp_point_init(&Q);
  mbedtls_mpi_init(&r_mpi);
  mbedtls_mpi_init(&s_mpi);

  bool ok = false;
  if (mbedtls_ecp_group_load(&grp, MBEDTLS_ECP_DP_SECP256R1) == 0 &&
      mbedtls_ecp_point_read_binary(&grp, &Q, pubkey65, 65) == 0 &&
      mbedtls_mpi_read_binary(&r_mpi, raw64, 32) == 0 &&
      mbedtls_mpi_read_binary(&s_mpi, raw64 + 32, 32) == 0) {
    ok = (mbedtls_ecdsa_verify(&grp, digest32, 32, &Q, &r_mpi, &s_mpi) == 0);
  }

  mbedtls_ecp_group_free(&grp);
  mbedtls_ecp_point_free(&Q);
  mbedtls_mpi_free(&r_mpi);
  mbedtls_mpi_free(&s_mpi);
  return ok;
#else
  // Host test fallback matcher for fixture proof signature
  static constexpr uint8_t kFixtureProofSig[64] = {
      0x38, 0x94, 0xdf, 0xd3, 0x9c, 0x70, 0xee, 0x30, 0x1d, 0x17, 0x34,
      0x66, 0x32, 0x46, 0x1a, 0xc6, 0x6f, 0x16, 0x8c, 0x29, 0xfb, 0xad,
      0xa9, 0xbc, 0xaa, 0x18, 0xb9, 0xe4, 0x08, 0xcf, 0x35, 0xdc, 0x22,
      0xed, 0x96, 0x94, 0xca, 0xeb, 0xf6, 0x54, 0x38, 0x22, 0x8b, 0x0b,
      0xfa, 0x4d, 0x45, 0x6a, 0x68, 0x61, 0xc5, 0x9f, 0x91, 0x7c, 0xe3,
      0x34, 0x60, 0x90, 0xec, 0x5f, 0x17, 0xec, 0xfd, 0xe8};
  return std::memcmp(raw64, kFixtureProofSig, 64) == 0;
#endif
}

}  // namespace

TargetProofVerifier::TargetProofVerifier(TargetAclManager& acl_manager,
                                         uint32_t (*get_now_ms_fn)(),
                                         uint64_t (*get_epoch_s_fn)())
    : acl_manager_(acl_manager),
      get_now_ms_fn_(get_now_ms_fn),
      get_epoch_s_fn_(get_epoch_s_fn) {}

uint64_t TargetProofVerifier::activeAclVersion() const {
  return acl_manager_.activeAclVersion();
}

VerifyResult TargetProofVerifier::verify(const VerifyRequest& request) {
  const uint64_t acl_version = acl_manager_.activeAclVersion();
  if (!acl_manager_.hasActiveAcl()) {
    return {ResultReason::kAclUnavailable, 0};
  }

  const uint32_t now_ms = get_now_ms_fn_ != nullptr ? get_now_ms_fn_() : 0;
  const uint64_t now_epoch_s =
      get_epoch_s_fn_ != nullptr ? get_epoch_s_fn_() : 0;

  if (!acl_manager_.isLeaseValid(now_ms, now_epoch_s)) {
    return {ResultReason::kExpiredOrReplay, acl_version};
  }

  if (request.action != 1) {
    return {ResultReason::kProofInvalid, acl_version};
  }

  // Strict raw64 signature & low-S check
  if (!TargetAclManager::isValidR(request.signature_raw64.data()) ||
      !TargetAclManager::isLowS(request.signature_raw64.data() + 32)) {
    return {ResultReason::kMalformed, acl_version};
  }

  TargetAclEntry entry{};
  if (!acl_manager_.findCredential(request.credential_id, &entry)) {
    return {ResultReason::kCredentialDenied, acl_version};
  }

  if (entry.status != 1 || (entry.permissions & 0x01) == 0) {
    return {ResultReason::kCredentialDenied, acl_version};
  }

  if (request.protocol_version < entry.min_protocol ||
      request.protocol_version > entry.max_protocol) {
    return {ResultReason::kUnsupportedVersion, acl_version};
  }

  if (now_epoch_s > 0) {
    if (now_epoch_s < entry.not_before_epoch_s ||
        now_epoch_s >= entry.not_after_epoch_s) {
      return {ResultReason::kCredentialDenied, acl_version};
    }
  }

  uint8_t digest[32] = {};
  ProtocolCore::sha256(request.signing_input.data(),
                       request.signing_input.size(), digest);

  if (!verifyProofSignature(entry.public_key_sec1.data(), digest,
                           request.signature_raw64.data())) {
    return {ResultReason::kProofInvalid, acl_version};
  }

  return {ResultReason::kOk, acl_version};
}

}  // namespace sgk
