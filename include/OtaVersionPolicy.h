#pragma once

#include <cstddef>
#include <cstdint>

namespace sgk {

enum class OtaVersionDecision : uint8_t {
  kUpgrade = 0,
  kCurrent,
  kInvalid,
  kDowngrade,
  kIdentityConflict,
  kStorageFailure,
};

struct OtaVersionFloorRecord {
  uint32_t magic = 0;
  uint16_t schema_version = 0;
  uint16_t reserved = 0;
  uint64_t generation = 0;
  char version[64]{};
  uint32_t crc32 = 0;
};

class OtaVersionFloorStorage {
 public:
  virtual ~OtaVersionFloorStorage() = default;
  virtual bool read(uint8_t slot, OtaVersionFloorRecord* record) = 0;
  virtual bool write(uint8_t slot, const OtaVersionFloorRecord& record) = 0;
};

class OtaVersionPolicy {
 public:
  explicit OtaVersionPolicy(OtaVersionFloorStorage* storage)
      : storage_(storage) {}

  bool begin(const char* current_version);
  OtaVersionDecision evaluate(const char* candidate_version,
                              const char* current_version) const;
  bool commit(const char* accepted_version);
  const char* floor() const { return record_.version; }

  static bool compare(const char* left, const char* right, int* result);

 private:
  bool persist(const char* version);
  static bool valid(const OtaVersionFloorRecord& record);
  static uint32_t crc(const OtaVersionFloorRecord& record);

  OtaVersionFloorStorage* storage_ = nullptr;
  OtaVersionFloorRecord record_{};
  uint8_t active_slot_ = 0;
  bool ready_ = false;
};

}  // namespace sgk
