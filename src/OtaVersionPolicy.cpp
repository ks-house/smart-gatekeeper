#include "OtaVersionPolicy.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace sgk {
namespace {

constexpr uint32_t kMagic = 0x53474b56;  // SGKV
constexpr uint16_t kSchemaVersion = 1;

struct SemVer {
  std::array<uint64_t, 3> core{};
  std::vector<std::string> prerelease;
};

bool validIdentifier(const std::string& value) {
  if (value.empty()) return false;
  return std::all_of(value.begin(), value.end(), [](unsigned char c) {
    return std::isalnum(c) || c == '-';
  });
}

bool numericIdentifier(const std::string& value) {
  return !value.empty() &&
         std::all_of(value.begin(), value.end(), [](unsigned char c) {
           return std::isdigit(c);
         });
}

bool parseIdentifiers(const std::string& value,
                      std::vector<std::string>* output,
                      bool reject_numeric_leading_zero) {
  if (output == nullptr || value.empty()) return false;
  size_t start = 0;
  while (start <= value.size()) {
    const size_t dot = value.find('.', start);
    const std::string item = value.substr(
        start, dot == std::string::npos ? std::string::npos : dot - start);
    if (!validIdentifier(item) ||
        (reject_numeric_leading_zero && numericIdentifier(item) &&
         item.size() > 1 && item[0] == '0')) {
      return false;
    }
    output->push_back(item);
    if (dot == std::string::npos) break;
    start = dot + 1;
  }
  return true;
}

bool parseSemVer(const char* text, SemVer* output) {
  if (text == nullptr || output == nullptr) return false;
  const size_t length = std::strlen(text);
  if (length == 0 || length >= 64) return false;
  const std::string value(text);
  const size_t plus = value.find('+');
  if (plus != std::string::npos) {
    std::vector<std::string> build;
    if (!parseIdentifiers(value.substr(plus + 1), &build, false) ||
        value.find('+', plus + 1) != std::string::npos) {
      return false;
    }
  }
  const std::string precedence = value.substr(0, plus);
  const size_t dash = precedence.find('-');
  const std::string core = precedence.substr(0, dash);
  size_t start = 0;
  for (size_t index = 0; index < output->core.size(); ++index) {
    const size_t dot = core.find('.', start);
    const std::string item = core.substr(
        start, dot == std::string::npos ? std::string::npos : dot - start);
    if (item.empty() || !numericIdentifier(item) ||
        (item.size() > 1 && item[0] == '0')) {
      return false;
    }
    uint64_t parsed = 0;
    for (const char c : item) {
      const uint8_t digit = static_cast<uint8_t>(c - '0');
      if (parsed > (UINT64_MAX - digit) / 10) return false;
      parsed = parsed * 10 + digit;
    }
    output->core[index] = parsed;
    if (index < 2) {
      if (dot == std::string::npos) return false;
      start = dot + 1;
    } else if (dot != std::string::npos) {
      return false;
    }
  }
  if (dash != std::string::npos &&
      !parseIdentifiers(precedence.substr(dash + 1), &output->prerelease,
                        true)) {
    return false;
  }
  return true;
}

int comparePrerelease(const SemVer& left, const SemVer& right) {
  if (left.prerelease.empty() || right.prerelease.empty()) {
    if (left.prerelease.empty() == right.prerelease.empty()) return 0;
    return left.prerelease.empty() ? 1 : -1;
  }
  const size_t count = std::min(left.prerelease.size(), right.prerelease.size());
  for (size_t index = 0; index < count; ++index) {
    const std::string& a = left.prerelease[index];
    const std::string& b = right.prerelease[index];
    if (a == b) continue;
    const bool aNumeric = numericIdentifier(a);
    const bool bNumeric = numericIdentifier(b);
    if (aNumeric != bNumeric) return aNumeric ? -1 : 1;
    if (aNumeric) {
      if (a.size() != b.size()) return a.size() < b.size() ? -1 : 1;
    }
    return a < b ? -1 : 1;
  }
  if (left.prerelease.size() == right.prerelease.size()) return 0;
  return left.prerelease.size() < right.prerelease.size() ? -1 : 1;
}

}  // namespace

bool OtaVersionPolicy::begin(const char* current_version) {
  ready_ = false;
  int ignored = 0;
  if (storage_ == nullptr ||
      !compare(current_version, current_version, &ignored)) {
    return false;
  }
  OtaVersionFloorRecord slots[2]{};
  const bool valid0 = storage_->read(0, &slots[0]) && valid(slots[0]);
  const bool valid1 = storage_->read(1, &slots[1]) && valid(slots[1]);
  if (valid0 || valid1) {
    active_slot_ = valid1 && (!valid0 || slots[1].generation > slots[0].generation)
                       ? 1
                       : 0;
    record_ = slots[active_slot_];
    if (!compare(record_.version, record_.version, &ignored)) return false;
    ready_ = true;
    int installedVsFloor = 0;
    if (!compare(current_version, record_.version, &installedVsFloor)) {
      ready_ = false;
      return false;
    }
    if (installedVsFloor > 0 && !persist(current_version)) {
      ready_ = false;
      return false;
    }
    if (installedVsFloor == 0 &&
        std::strcmp(current_version, record_.version) != 0) {
      ready_ = false;
      return false;
    }
    return true;
  }
  record_ = OtaVersionFloorRecord{};
  record_.magic = kMagic;
  record_.schema_version = kSchemaVersion;
  active_slot_ = 0;
  ready_ = true;
  if (!persist(current_version)) {
    ready_ = false;
    return false;
  }
  return true;
}

OtaVersionDecision OtaVersionPolicy::evaluate(
    const char* candidate_version, const char* current_version) const {
  if (!ready_) return OtaVersionDecision::kStorageFailure;
  int currentComparison = 0;
  int floorComparison = 0;
  int installedVsFloor = 0;
  if (!compare(candidate_version, current_version, &currentComparison) ||
      !compare(candidate_version, record_.version, &floorComparison) ||
      !compare(current_version, record_.version, &installedVsFloor)) {
    return OtaVersionDecision::kInvalid;
  }
  if (currentComparison < 0 || floorComparison < 0) {
    return OtaVersionDecision::kDowngrade;
  }
  if ((currentComparison == 0 &&
       std::strcmp(candidate_version, current_version) != 0) ||
      (floorComparison == 0 &&
       std::strcmp(candidate_version, record_.version) != 0)) {
    return OtaVersionDecision::kIdentityConflict;
  }
  // A lower running image with a higher persisted floor means the bootloader
  // rolled back an unconfirmed candidate. Quarantine that exact candidate so
  // the unchanged NAS pointer cannot reinstall it after every stable boot.
  // A strictly newer candidate remains eligible to recover the installation.
  if (installedVsFloor < 0 && floorComparison == 0) {
    return OtaVersionDecision::kDowngrade;
  }
  return currentComparison == 0 ? OtaVersionDecision::kCurrent
                                : OtaVersionDecision::kUpgrade;
}

bool OtaVersionPolicy::commit(const char* accepted_version) {
  if (!ready_) return false;
  int comparison = 0;
  if (!compare(accepted_version, record_.version, &comparison) ||
      comparison < 0 ||
      (comparison == 0 &&
       std::strcmp(accepted_version, record_.version) != 0)) {
    return false;
  }
  if (std::strcmp(accepted_version, record_.version) == 0) return true;
  return persist(accepted_version);
}

bool OtaVersionPolicy::compare(const char* left, const char* right,
                               int* result) {
  if (result == nullptr) return false;
  SemVer a;
  SemVer b;
  if (!parseSemVer(left, &a) || !parseSemVer(right, &b)) return false;
  for (size_t index = 0; index < a.core.size(); ++index) {
    if (a.core[index] != b.core[index]) {
      *result = a.core[index] < b.core[index] ? -1 : 1;
      return true;
    }
  }
  *result = comparePrerelease(a, b);
  return true;
}

bool OtaVersionPolicy::persist(const char* version) {
  if (version == nullptr || std::strlen(version) >= sizeof(record_.version)) {
    return false;
  }
  const OtaVersionFloorRecord before = record_;
  record_.magic = kMagic;
  record_.schema_version = kSchemaVersion;
  record_.generation++;
  std::snprintf(record_.version, sizeof(record_.version), "%s", version);
  record_.crc32 = crc(record_);
  const uint8_t candidate = active_slot_ == 0 ? 1 : 0;
  if (!storage_->write(candidate, record_)) {
    record_ = before;
    return false;
  }
  OtaVersionFloorRecord verified{};
  if (!storage_->read(candidate, &verified) || !valid(verified) ||
      verified.generation != record_.generation ||
      std::strcmp(verified.version, version) != 0) {
    record_ = before;
    return false;
  }
  active_slot_ = candidate;
  return true;
}

bool OtaVersionPolicy::valid(const OtaVersionFloorRecord& record) {
  return record.magic == kMagic &&
         record.schema_version == kSchemaVersion &&
         std::memchr(record.version, '\0', sizeof(record.version)) != nullptr &&
         record.version[0] != '\0' && record.crc32 == crc(record);
}

uint32_t OtaVersionPolicy::crc(const OtaVersionFloorRecord& record) {
  std::array<uint8_t, 80> bytes{};
  size_t offset = 0;
  const auto appendLittleEndian = [&bytes, &offset](uint64_t value,
                                                   size_t width) {
    for (size_t index = 0; index < width; ++index) {
      bytes[offset++] = static_cast<uint8_t>(value >> (index * 8));
    }
  };
  appendLittleEndian(record.magic, sizeof(record.magic));
  appendLittleEndian(record.schema_version, sizeof(record.schema_version));
  appendLittleEndian(record.reserved, sizeof(record.reserved));
  appendLittleEndian(record.generation, sizeof(record.generation));
  std::memcpy(bytes.data() + offset, record.version, sizeof(record.version));
  offset += sizeof(record.version);
  if (offset != bytes.size()) return 0;
  uint32_t value = 0xffffffffU;
  for (const uint8_t byte : bytes) {
    value ^= byte;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      value = (value >> 1) ^ (0xedb88320U & (0U - (value & 1U)));
    }
  }
  return ~value;
}

}  // namespace sgk
