#include "TargetAclManager.h"

#include <algorithm>
#include <cstring>

#if defined(ESP_PLATFORM) || defined(ARDUINO)
#include <mbedtls/ecdsa.h>
#include <mbedtls/ecp.h>
#include <mbedtls/md.h>
#endif

namespace sgk {

namespace {

uint16_t readU16(const uint8_t* p) {
  return static_cast<uint16_t>((p[0] << 8) | p[1]);
}

uint32_t readU32(const uint8_t* p) {
  return (static_cast<uint32_t>(p[0]) << 24) |
         (static_cast<uint32_t>(p[1]) << 16) |
         (static_cast<uint32_t>(p[2]) << 8) | static_cast<uint32_t>(p[3]);
}

uint64_t readU64(const uint8_t* p) {
  return (static_cast<uint64_t>(p[0]) << 56) |
         (static_cast<uint64_t>(p[1]) << 48) |
         (static_cast<uint64_t>(p[2]) << 40) |
         (static_cast<uint64_t>(p[3]) << 32) |
         (static_cast<uint64_t>(p[4]) << 24) |
         (static_cast<uint64_t>(p[5]) << 16) |
         (static_cast<uint64_t>(p[6]) << 8) | static_cast<uint64_t>(p[7]);
}

constexpr uint8_t kHalfN[32] = {
    0x7F, 0xFF, 0xFF, 0xFF, 0x80, 0x00, 0x00, 0x00, 0x7F, 0xFF, 0xFF,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xDE, 0x73, 0x7D, 0x56, 0xD3, 0x8B,
    0xCE, 0x42, 0x79, 0xDC, 0x65, 0x61, 0x7E, 0x31, 0x92, 0xA8};

constexpr uint8_t kOrderN[32] = {
    0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xBC, 0xE6, 0xFA, 0xAD, 0xA7, 0x17,
    0x9E, 0x84, 0xF3, 0xB9, 0xCA, 0xC2, 0xFC, 0x63, 0x25, 0x51};

}  // namespace

bool TargetAclManager::isLowS(const uint8_t s[32]) {
  bool all_zero = true;
  for (size_t i = 0; i < 32; ++i) {
    if (s[i] != 0) {
      all_zero = false;
      break;
    }
  }
  if (all_zero) return false;
  for (size_t i = 0; i < 32; ++i) {
    if (s[i] < kHalfN[i]) return true;
    if (s[i] > kHalfN[i]) return false;
  }
  return true;
}

bool TargetAclManager::isValidR(const uint8_t r[32]) {
  bool all_zero = true;
  for (size_t i = 0; i < 32; ++i) {
    if (r[i] != 0) {
      all_zero = false;
      break;
    }
  }
  if (all_zero) return false;
  for (size_t i = 0; i < 32; ++i) {
    if (r[i] < kOrderN[i]) return true;
    if (r[i] > kOrderN[i]) return false;
  }
  return false;
}

uint32_t TargetAclManager::computeCrc32(const uint8_t* data, size_t length) {
  uint32_t crc = 0xFFFFFFFF;
  for (size_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (int j = 0; j < 8; ++j) {
      crc = (crc & 1) ? ((crc >> 1) ^ 0xEDB88320) : (crc >> 1);
    }
  }
  return ~crc;
}

TargetAclManager::TargetAclManager(TargetAclStorage* storage)
    : storage_(storage) {}

bool TargetAclManager::begin(const std::array<uint8_t, 16>& door_id,
                             uint32_t now_ms) {
  door_id_ = door_id;
  receipt_monotonic_ms_ = now_ms;
  last_monotonic_ms_ = now_ms;
  active_ready_ = false;

  if (storage_ == nullptr) {
    effective_high_watermark_ = 0;
    return true;
  }

  uint64_t hw = storage_->readHighWatermark();
  effective_high_watermark_ = hw;

  auto isValidGenerationRecord = [](const GenerationRecord& gen) {
    if (gen.magic != kGenerationMagic) return false;
    if (gen.record_schema != 1) return false;
    if (gen.active_slot != 0 && gen.active_slot != 1) return false;
    uint32_t computed_crc = computeCrc32(
        reinterpret_cast<const uint8_t*>(&gen),
        offsetof(GenerationRecord, crc32));
    return gen.crc32 == computed_crc;
  };

  GenerationRecord gen0{}, gen1{};
  bool valid0 = storage_->readGenerationRecord(0, &gen0) && isValidGenerationRecord(gen0);
  bool valid1 = storage_->readGenerationRecord(1, &gen1) && isValidGenerationRecord(gen1);

  if (valid0) {
    if (gen0.high_watermark > effective_high_watermark_) {
      effective_high_watermark_ = gen0.high_watermark;
    }
  }
  if (valid1) {
    if (gen1.high_watermark > effective_high_watermark_) {
      effective_high_watermark_ = gen1.high_watermark;
    }
  }

  GenerationRecord selected_gen{};
  bool found_gen = false;
  if (valid0 && valid1) {
    if (gen0.generation >= gen1.generation) {
      selected_gen = gen0;
      found_gen = true;
    } else {
      selected_gen = gen1;
      found_gen = true;
    }
  } else if (valid0) {
    selected_gen = gen0;
    found_gen = true;
  } else if (valid1) {
    selected_gen = gen1;
    found_gen = true;
  }

  if (!found_gen) {
    return true;
  }

  generation_counter_ = selected_gen.generation;
  active_slot_ = selected_gen.active_slot;

  // Load snapshot from active_slot
  uint8_t slot_buffer[kMaxAclBlobSize] = {};
  size_t read_bytes = 0;
  if (!storage_->readSlot(selected_gen.active_slot, slot_buffer,
                          sizeof(slot_buffer), &read_bytes)) {
    return true;
  }

  TargetAclSnapshot snapshot{};
  if (!parseSnapshot(slot_buffer, read_bytes, &snapshot)) {
    return true;
  }

  if (!validateSnapshotSemantics(snapshot, 0)) {
    return true;  // Invalid semantics -> reject on boot
  }

  if (!verifySnapshotSignature(snapshot)) {
    return true;  // Invalid signature / untrusted signer -> reject on boot
  }

  if (snapshot.header.acl_version != selected_gen.acl_version) {
    return true;  // Version mismatch with generation record -> reject on boot
  }

  if (snapshot.header.acl_version < effective_high_watermark_) {
    return true;  // Anti-rollback rejection
  }

  if (snapshot.digest != selected_gen.acl_digest) {
    return true;  // Digest mismatch -> reject on boot
  }

  // Preserve anti-rollback floor and generation history.
  // With no trusted wall clock on reboot, do not reactivate stored lease.
  active_snapshot_ = snapshot;
  active_ready_ = false;

  return true;
}

bool TargetAclManager::setSignerPublicKey(
    const std::array<uint8_t, 65>& signer_pubkey) {
  if (signer_pubkey[0] != 0x04) {
    signer_set_ = false;
    return false;
  }
  signer_pubkey_ = signer_pubkey;
  signer_set_ = true;
  return true;
}

void TargetAclManager::setExpectedSigningKeyId(uint32_t key_id) {
  expected_signing_key_id_ = key_id;
  signing_key_id_enforced_ = (key_id != 0);
}

bool TargetAclManager::parseHeader(const uint8_t* bytes, size_t length,
                                   TargetAclHeader* header_out) {
  if (length < kAclHeaderSize || bytes == nullptr || header_out == nullptr) {
    return false;
  }
  std::memcpy(header_out->magic.data(), bytes, 8);
  if (std::memcmp(header_out->magic.data(), "SGKACL01", 8) != 0) return false;

  header_out->schema_version = readU16(bytes + 8);
  std::memcpy(header_out->door_id.data(), bytes + 10, 16);
  header_out->acl_version = readU64(bytes + 26);
  header_out->issued_at_epoch_s = readU64(bytes + 34);
  header_out->not_before_epoch_s = readU64(bytes + 42);
  header_out->expires_at_epoch_s = readU64(bytes + 50);
  header_out->lease_duration_s = readU32(bytes + 58);
  header_out->min_protocol = readU16(bytes + 62);
  header_out->max_protocol = readU16(bytes + 64);
  header_out->signing_key_id = readU32(bytes + 66);
  header_out->entry_count = readU16(bytes + 70);

  return true;
}

bool TargetAclManager::parseEntry(const uint8_t* bytes, size_t length,
                                  TargetAclEntry* entry_out) {
  if (length < kAclEntrySize || bytes == nullptr || entry_out == nullptr) {
    return false;
  }
  std::memcpy(entry_out->credential_id.data(), bytes, 16);
  std::memcpy(entry_out->public_key_sec1.data(), bytes + 16, 65);
  entry_out->status = bytes[81];
  entry_out->permissions = readU32(bytes + 82);
  entry_out->not_before_epoch_s = readU64(bytes + 86);
  entry_out->not_after_epoch_s = readU64(bytes + 94);
  entry_out->min_protocol = readU16(bytes + 102);
  entry_out->max_protocol = readU16(bytes + 104);

  return true;
}

bool TargetAclManager::parseSnapshot(const uint8_t* payload, size_t length,
                                      TargetAclSnapshot* snapshot_out) const {
  if (payload == nullptr || snapshot_out == nullptr || length < kAclHeaderSize) {
    return false;
  }
  if (!parseHeader(payload, length, &snapshot_out->header)) {
    return false;
  }

  const size_t expected_canonical =
      kAclHeaderSize + snapshot_out->header.entry_count * kAclEntrySize;
  const size_t expected_total = expected_canonical + kAclSignatureSize;

  if (length != expected_total && length != expected_canonical) {
    return false;
  }

  snapshot_out->entries.clear();
  for (size_t i = 0; i < snapshot_out->header.entry_count; ++i) {
    TargetAclEntry entry{};
    if (!parseEntry(payload + kAclHeaderSize + i * kAclEntrySize,
                    kAclEntrySize, &entry)) {
      return false;
    }
    snapshot_out->entries.push_back(entry);
  }

  ProtocolCore::sha256(payload, expected_canonical, snapshot_out->digest.data());

  if (length == expected_total) {
    std::memcpy(snapshot_out->signature_raw64.data(),
                payload + expected_canonical, kAclSignatureSize);
  } else {
    snapshot_out->signature_raw64.fill(0);
  }

  return true;
}

static TargetAclManager::HostAclVerifierCallback s_host_acl_verifier_cb = nullptr;

void TargetAclManager::setHostAclVerifierCallback(HostAclVerifierCallback cb) {
  s_host_acl_verifier_cb = cb;
}

bool TargetAclManager::verifySnapshotSignature(
    const TargetAclSnapshot& snapshot) const {
  if (!isValidR(snapshot.signature_raw64.data()) ||
      !isLowS(snapshot.signature_raw64.data() + 32)) {
    return false;
  }
  if (!signer_set_ || signer_pubkey_[0] != 0x04 || expected_signing_key_id_ == 0) {
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
      mbedtls_ecp_point_read_binary(&grp, &Q, signer_pubkey_.data(), 65) == 0 &&
      mbedtls_mpi_read_binary(&r_mpi, snapshot.signature_raw64.data(), 32) ==
          0 &&
      mbedtls_mpi_read_binary(&s_mpi, snapshot.signature_raw64.data() + 32,
                              32) == 0) {
    ok = (mbedtls_ecdsa_verify(&grp, snapshot.digest.data(), 32, &Q, &r_mpi,
                               &s_mpi) == 0);
  }

  mbedtls_ecp_group_free(&grp);
  mbedtls_ecp_point_free(&Q);
  mbedtls_mpi_free(&r_mpi);
  mbedtls_mpi_free(&s_mpi);
  return ok;
#else
  if (s_host_acl_verifier_cb != nullptr) {
    return s_host_acl_verifier_cb(signer_pubkey_, snapshot.digest, snapshot.signature_raw64);
  }
  return false;
#endif
}

bool TargetAclManager::validateSnapshotSemantics(
    const TargetAclSnapshot& snapshot, uint64_t now_epoch_s) const {
  (void)now_epoch_s;
  const auto& h = snapshot.header;
  if (h.schema_version != 1 || h.acl_version < 1) return false;
  if (h.lease_duration_s < 1 || h.lease_duration_s > 3600) return false;
  if (h.issued_at_epoch_s > h.not_before_epoch_s ||
      h.not_before_epoch_s >= h.expires_at_epoch_s) {
    return false;
  }
  if (h.min_protocol < 1 || h.min_protocol > h.max_protocol) return false;
  if (h.entry_count > kMaxAclEntries || h.entry_count != snapshot.entries.size()) {
    return false;
  }
  if (h.door_id != door_id_) return false;
  if (signing_key_id_enforced_ && h.signing_key_id != expected_signing_key_id_) {
    return false;
  }

  for (size_t i = 0; i < snapshot.entries.size(); ++i) {
    const auto& e = snapshot.entries[i];
    if (e.status != 0 && e.status != 1) return false;
    if ((e.permissions & ~0x00000001u) != 0) return false;
    if (e.not_before_epoch_s >= e.not_after_epoch_s) return false;
    if (h.min_protocol > e.min_protocol || e.min_protocol > e.max_protocol ||
        e.max_protocol > h.max_protocol) {
      return false;
    }
    if (e.public_key_sec1[0] != 0x04) return false;

    if (i > 0) {
      if (e.credential_id <= snapshot.entries[i - 1].credential_id) {
        return false;  // Must be strictly sorted ascending
      }
    }
  }

  return true;
}

ResultReason TargetAclManager::applySignedAcl(const uint8_t* payload,
                                               size_t length, uint32_t now_ms,
                                               uint64_t now_epoch_s) {
  TargetAclSnapshot snapshot{};
  if (!parseSnapshot(payload, length, &snapshot)) {
    return ResultReason::kMalformed;
  }
  if (!validateSnapshotSemantics(snapshot, now_epoch_s)) {
    return ResultReason::kMalformed;
  }
  if (!verifySnapshotSignature(snapshot)) {
    return ResultReason::kProofInvalid;
  }

  // Idempotent ACL re-apply check
  if (active_ready_ &&
      snapshot.header.acl_version == active_snapshot_.header.acl_version) {
    if (snapshot.digest == active_snapshot_.digest) {
      return ResultReason::kOk;  // Idempotent ACK without extending lease
    } else {
      return ResultReason::kMalformed;  // Same version, different digest -> fail-closed
    }
  }

  // Version check against high-watermark (anti-rollback)
  if (snapshot.header.acl_version <= effective_high_watermark_) {
    return ResultReason::kExpiredOrReplay;
  }

  // Atomic NVS storage update if storage provided
  if (storage_ != nullptr) {
    uint8_t target_slot = (active_slot_ == 0) ? 1 : 0;
    if (!storage_->saveSlot(target_slot, payload, length)) {
      return ResultReason::kInternalFailClosed;
    }

    GenerationRecord gen{};
    gen.magic = kGenerationMagic;
    gen.record_schema = 1;
    gen.generation = generation_counter_ + 1;
    gen.active_slot = target_slot;
    gen.acl_version = snapshot.header.acl_version;
    gen.acl_digest = snapshot.digest;
    gen.high_watermark = snapshot.header.acl_version;
    gen.crc32 = computeCrc32(reinterpret_cast<const uint8_t*>(&gen),
                             offsetof(GenerationRecord, crc32));

    uint8_t gen_slot = (target_slot == 1) ? 1 : 0;
    if (!storage_->saveGenerationRecord(gen_slot, gen)) {
      return ResultReason::kInternalFailClosed;
    }
    storage_->saveHighWatermark(snapshot.header.acl_version);
    generation_counter_ = gen.generation;
    active_slot_ = target_slot;
  }

  effective_high_watermark_ = snapshot.header.acl_version;
  active_snapshot_ = snapshot;
  active_ready_ = true;
  receipt_monotonic_ms_ = now_ms;
  receipt_epoch_s_ = now_epoch_s;
  last_monotonic_ms_ = now_ms;

  return ResultReason::kOk;
}

bool TargetAclManager::isLeaseValid(uint32_t now_ms,
                                    uint64_t now_epoch_s) const {
  if (!active_ready_) return false;

  // Clock jump / reset detection: monotonic clock cannot jump backwards
  if (now_ms < last_monotonic_ms_) {
    return false;  // Monotonic clock reset -> fail-closed
  }

  const uint32_t elapsed_ms = now_ms - receipt_monotonic_ms_;
  const uint32_t lease_ms = active_snapshot_.header.lease_duration_s * 1000;
  if (elapsed_ms >= lease_ms) {
    return false;
  }

  if (now_epoch_s > 0) {
    if (now_epoch_s < active_snapshot_.header.not_before_epoch_s ||
        now_epoch_s >= active_snapshot_.header.expires_at_epoch_s) {
      return false;
    }
  }

  return true;
}

bool TargetAclManager::findCredential(
    const std::array<uint8_t, 16>& credential_id,
    TargetAclEntry* entry_out) const {
  if (!active_ready_) return false;

  auto it = std::lower_bound(
      active_snapshot_.entries.begin(), active_snapshot_.entries.end(),
      credential_id, [](const TargetAclEntry& entry, const std::array<uint8_t, 16>& val) {
        return entry.credential_id < val;
      });

  if (it != active_snapshot_.entries.end() && it->credential_id == credential_id) {
    if (entry_out != nullptr) {
      *entry_out = *it;
    }
    return true;
  }
  return false;
}

}  // namespace sgk
