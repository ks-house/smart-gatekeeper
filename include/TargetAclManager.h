#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>
#include "GattProtocol.h"

namespace sgk {

constexpr size_t kAclHeaderSize = 72;
constexpr size_t kAclEntrySize = 106;
constexpr size_t kAclSignatureSize = 64;
constexpr size_t kMaxAclEntries = 64;
constexpr size_t kMaxAclBlobSize = kAclHeaderSize + (kMaxAclEntries * kAclEntrySize) + kAclSignatureSize;  // 6920
constexpr uint32_t kGenerationMagic = 0x53474B41;  // ASCII "SGKA"

struct TargetAclEntry {
  std::array<uint8_t, 16> credential_id{};
  std::array<uint8_t, 65> public_key_sec1{};
  uint8_t status = 0;  // 0 = REVOKED, 1 = ACTIVE
  uint32_t permissions = 0;  // bit 0 = OPEN (0x01)
  uint64_t not_before_epoch_s = 0;
  uint64_t not_after_epoch_s = 0;
  uint16_t min_protocol = 0;
  uint16_t max_protocol = 0;
};

struct TargetAclHeader {
  std::array<uint8_t, 8> magic{};  // "SGKACL01"
  uint16_t schema_version = 0;     // 1
  std::array<uint8_t, 16> door_id{};
  uint64_t acl_version = 0;
  uint64_t issued_at_epoch_s = 0;
  uint64_t not_before_epoch_s = 0;
  uint64_t expires_at_epoch_s = 0;
  uint32_t lease_duration_s = 0;
  uint16_t min_protocol = 0;
  uint16_t max_protocol = 0;
  uint32_t signing_key_id = 0;
  uint16_t entry_count = 0;
};

struct TargetAclSnapshot {
  TargetAclHeader header{};
  std::vector<TargetAclEntry> entries{};
  std::array<uint8_t, 64> signature_raw64{};
  std::array<uint8_t, 32> digest{};
};

struct GenerationRecord {
  uint32_t magic = kGenerationMagic; // 0x53474B41 "SGKA"
  uint16_t record_schema = 1;         // 1
  uint16_t reserved = 0;              // explicit padding
  uint64_t generation = 0;
  uint8_t active_slot = 0;            // 0 or 1
  uint8_t padding[7] = {};            // explicit padding
  uint64_t acl_version = 0;
  std::array<uint8_t, 32> acl_digest{};
  uint64_t high_watermark = 0;        // anti-rollback floor
  uint32_t crc32 = 0;
};

class TargetAclStorage {
 public:
  virtual ~TargetAclStorage() = default;
  virtual bool saveSlot(uint8_t slot, const uint8_t* blob, size_t length) = 0;
  virtual bool readSlot(uint8_t slot, uint8_t* buffer, size_t capacity,
                        size_t* read_bytes) = 0;
  virtual bool saveGenerationRecord(uint8_t record_index,
                                     const GenerationRecord& record) = 0;
  virtual bool readGenerationRecord(uint8_t record_index,
                                     GenerationRecord* record) = 0;
  virtual bool saveHighWatermark(uint64_t version) = 0;
  virtual uint64_t readHighWatermark() = 0;
};

class TargetAclManager {
 public:
  using HostAclVerifierCallback = bool (*)(const std::array<uint8_t, 65>& pubkey,
                                          const std::array<uint8_t, 32>& digest,
                                          const std::array<uint8_t, 64>& sig);
  static void setHostAclVerifierCallback(HostAclVerifierCallback cb);

  explicit TargetAclManager(TargetAclStorage* storage = nullptr);

  bool begin(const std::array<uint8_t, 16>& door_id, uint32_t now_ms);

  bool setSignerPublicKey(const std::array<uint8_t, 65>& signer_pubkey);
  void setExpectedSigningKeyId(uint32_t key_id);
  bool isSignerPublicKeySet() const { return signer_set_; }

  ResultReason applySignedAcl(const uint8_t* payload, size_t length,
                              uint32_t now_ms, uint64_t now_epoch_s = 0);

  bool hasActiveAcl() const { return active_ready_; }
  uint64_t activeAclVersion() const {
    return active_ready_ ? active_snapshot_.header.acl_version : 0;
  }
  uint64_t highWatermark() const { return effective_high_watermark_; }

  bool isLeaseValid(uint32_t now_ms, uint64_t now_epoch_s = 0) const;

  bool findCredential(const std::array<uint8_t, 16>& credential_id,
                      TargetAclEntry* entry_out) const;

  const TargetAclSnapshot& activeSnapshot() const { return active_snapshot_; }

  static bool parseHeader(const uint8_t* bytes, size_t length,
                          TargetAclHeader* header_out);
  static bool parseEntry(const uint8_t* bytes, size_t length,
                         TargetAclEntry* entry_out);
  static uint32_t computeCrc32(const uint8_t* data, size_t length);
  static bool isLowS(const uint8_t s[32]);
  static bool isValidR(const uint8_t r[32]);

 private:
  TargetAclStorage* storage_ = nullptr;
  std::array<uint8_t, 16> door_id_{};
  std::array<uint8_t, 65> signer_pubkey_{};
  bool signer_set_ = false;
  uint32_t expected_signing_key_id_ = 0;
  bool signing_key_id_enforced_ = false;

  bool active_ready_ = false;
  uint8_t active_slot_ = 0;
  uint64_t generation_counter_ = 0;
  uint64_t effective_high_watermark_ = 0;
  uint32_t receipt_monotonic_ms_ = 0;
  uint64_t receipt_epoch_s_ = 0;
  uint32_t last_monotonic_ms_ = 0;

  TargetAclSnapshot active_snapshot_{};

  bool parseSnapshot(const uint8_t* payload, size_t length,
                     TargetAclSnapshot* snapshot_out) const;
  bool verifySnapshotSignature(const TargetAclSnapshot& snapshot) const;
  bool validateSnapshotSemantics(const TargetAclSnapshot& snapshot,
                                 uint64_t now_epoch_s) const;
};

}  // namespace sgk
