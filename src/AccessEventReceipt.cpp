#include "AccessEventReceipt.h"

#include <cstring>

namespace sgk {
namespace {
constexpr char kDomain[] = "SGK-ACCESS-RECEIPT-V1";
constexpr char kSensorDomain[] = "SGK-SENSOR-RECEIPT-V1";
static_assert(sizeof(kDomain) == sizeof(kSensorDomain), "receipt domain width");

void zero(void* data, size_t length) {
  volatile uint8_t* cursor = static_cast<volatile uint8_t*>(data);
  while (length-- != 0) *cursor++ = 0;
}

bool nonzero(const uint8_t* data, size_t length) {
  uint8_t aggregate = 0;
  for (size_t index = 0; index < length; ++index) aggregate |= data[index];
  return aggregate != 0;
}

bool equal(const uint8_t* left, const uint8_t* right, size_t length) {
  uint8_t difference = 0;
  for (size_t index = 0; index < length; ++index) {
    difference |= left[index] ^ right[index];
  }
  return difference == 0;
}

bool boundedLength(const char* value, size_t capacity, size_t* length) {
  for (size_t index = 0; index < capacity; ++index) {
    if (value[index] == '\0') {
      *length = index;
      return index != 0;
    }
  }
  return false;
}

int nibble(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  return -1;
}

bool parseId(const char* text, size_t capacity, bool uuid, uint8_t output[16]) {
  size_t length = 0;
  if (!boundedLength(text, capacity, &length) || length != (uuid ? 36U : 32U)) {
    return false;
  }
  size_t octet = 0;
  for (size_t index = 0; index < length;) {
    if (uuid && (index == 8 || index == 13 || index == 18 || index == 23)) {
      if (text[index++] != '-') return false;
      continue;
    }
    const int high = nibble(text[index++]);
    const int low = nibble(text[index++]);
    if (high < 0 || low < 0 || octet >= 16) return false;
    output[octet++] = static_cast<uint8_t>((high << 4) | low);
  }
  return octet == 16 && nonzero(output, 16) &&
         (!uuid || ((output[6] >> 4) == 4 && (output[8] & 0xc0) == 0x80));
}
}  // namespace

bool canonicalAccessEventReceipt(
    const AccessEventReceipt& receipt, uint8_t* output, size_t capacity,
    size_t* length_out) {
  if (length_out != nullptr) *length_out = 0;
  if (output == nullptr || length_out == nullptr ||
      receipt.source_boot_count == 0 || receipt.source_sequence == 0) {
    return false;
  }
  size_t key_length = 0;
  size_t target_length = 0;
  if (!boundedLength(receipt.key_id, sizeof(receipt.key_id), &key_length) ||
      !boundedLength(receipt.target_id, sizeof(receipt.target_id), &target_length)) {
    return false;
  }
  for (size_t index = 0; index < key_length; ++index) {
    const char c = receipt.key_id[index];
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'))) return false;
  }
  for (size_t index = 0; index < target_length; ++index) {
    const char c = receipt.target_id[index];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
  }
  uint8_t event_id[16] = {};
  uint8_t boot_id[16] = {};
  if (!parseId(receipt.event_id, sizeof(receipt.event_id), true, event_id) ||
      !parseId(receipt.source_boot_id, sizeof(receipt.source_boot_id), false, boot_id)) {
    return false;
  }
  const size_t required = sizeof(kDomain) + 2 + key_length + target_length + 64;
  if (capacity < required) return false;
  size_t cursor = 0;
  auto append = [&](const void* data, size_t length) {
    std::memcpy(output + cursor, data, length);
    cursor += length;
  };
  append(kDomain, sizeof(kDomain));  // Domain includes exactly one NUL.
  output[cursor++] = static_cast<uint8_t>(key_length);
  append(receipt.key_id, key_length);
  output[cursor++] = static_cast<uint8_t>(target_length);
  append(receipt.target_id, target_length);
  append(event_id, sizeof(event_id));
  append(boot_id, sizeof(boot_id));
  for (uint64_t value : {receipt.source_boot_count, receipt.source_sequence}) {
    for (int shift = 56; shift >= 0; shift -= 8) {
      output[cursor++] = static_cast<uint8_t>(value >> shift);
    }
  }
  append(receipt.event_tag, sizeof(receipt.event_tag));
  *length_out = cursor;
  return true;
}

namespace {
bool deriveReceiptTag(
    const std::array<uint8_t, 32>& key, const AccessEventReceipt& receipt,
    uint8_t output[kAccessEvidenceTagSize], bool sensor) {
  if (output == nullptr) return false;
  std::memset(output, 0, kAccessEvidenceTagSize);
  if (!nonzero(key.data(), key.size())) return false;
  std::array<uint8_t, kAccessReceiptCanonicalCapacity + 64> inner{};
  std::array<uint8_t, 96> outer{};
  size_t length = 0;
  const bool built = sensor
      ? canonicalSensorSessionReceipt(receipt, inner.data() + 64,
                                       inner.size() - 64, &length)
      : canonicalAccessEventReceipt(receipt, inner.data() + 64,
                                      inner.size() - 64, &length);
  if (!built) return false;
  for (size_t index = 0; index < 64; ++index) {
    const uint8_t key_byte = index < key.size() ? key[index] : 0;
    inner[index] = key_byte ^ 0x36;
    outer[index] = key_byte ^ 0x5c;
  }
  ProtocolCore::sha256(inner.data(), 64 + length, outer.data() + 64);
  uint8_t digest[32] = {};
  ProtocolCore::sha256(outer.data(), outer.size(), digest);
  std::memcpy(output, digest, kAccessEvidenceTagSize);
  zero(inner.data(), inner.size());
  zero(outer.data(), outer.size());
  zero(digest, sizeof(digest));
  return true;
}
}  // namespace

bool deriveAccessEventReceiptTag(
    const std::array<uint8_t, 32>& key, const AccessEventReceipt& receipt,
    uint8_t output[kAccessEvidenceTagSize]) {
  return deriveReceiptTag(key, receipt, output, false);
}

bool canonicalSensorSessionReceipt(
    const SensorSessionReceipt& receipt, uint8_t* output, size_t capacity,
    size_t* length_out) {
  if (!canonicalAccessEventReceipt(receipt, output, capacity, length_out)) return false;
  std::memcpy(output, kSensorDomain, sizeof(kSensorDomain));
  return true;
}

bool deriveSensorSessionReceiptTag(
    const std::array<uint8_t, 32>& key, const SensorSessionReceipt& receipt,
    uint8_t output[kAccessEvidenceTagSize]) {
  return deriveReceiptTag(key, receipt, output, true);
}

bool verifySensorSessionReceipt(
    const std::array<uint8_t, 32>& key, const char* expected_target_id,
    const char* expected_boot_id, uint64_t expected_boot_count,
    const char* expected_session_id, uint64_t expected_terminal_sequence,
    const char* expected_key_id, const uint8_t expected_summary_tag[16],
    const SensorSessionReceipt& receipt) {
  uint8_t expected_tag[kAccessEvidenceTagSize] = {};
  if (expected_target_id == nullptr || expected_boot_id == nullptr ||
      expected_session_id == nullptr || expected_key_id == nullptr ||
      expected_summary_tag == nullptr ||
      !deriveSensorSessionReceiptTag(key, receipt, expected_tag)) return false;
  const bool valid =
      std::strcmp(expected_target_id, receipt.target_id) == 0 &&
      std::strcmp(expected_boot_id, receipt.source_boot_id) == 0 &&
      std::strcmp(expected_session_id, receipt.event_id) == 0 &&
      std::strcmp(expected_key_id, receipt.key_id) == 0 &&
      expected_boot_count == receipt.source_boot_count &&
      expected_terminal_sequence == receipt.source_sequence &&
      equal(expected_summary_tag, receipt.event_tag, 16) &&
      equal(expected_tag, receipt.tag, sizeof(expected_tag));
  zero(expected_tag, sizeof(expected_tag));
  return valid;
}

bool verifyAccessEventReceipt(
    const std::array<uint8_t, 32>& key, const char* expected_target_id,
    const CanonicalEvent& retained_event, const AccessEventReceipt& receipt) {
  uint8_t canonical[kAccessReceiptCanonicalCapacity] = {};
  size_t canonical_length = 0;
  if (expected_target_id == nullptr ||
      !canonicalAccessEventReceipt(receipt, canonical, sizeof(canonical),
                                     &canonical_length) ||
      retained_event.is_canonical != 1 ||
      std::strcmp(expected_target_id, receipt.target_id) != 0 ||
      std::strncmp(retained_event.event_id, receipt.event_id,
                     sizeof(retained_event.event_id)) != 0 ||
      std::strncmp(retained_event.source_boot_id, receipt.source_boot_id,
                     sizeof(retained_event.source_boot_id)) != 0 ||
      retained_event.boot_count != receipt.source_boot_count ||
      retained_event.sequence != receipt.source_sequence) return false;

  char key_id[kAccessEvidenceKeyIdCapacity] = {};
  char credential[kAccessEventCredentialRefCapacity] = {};
  uint8_t event_tag[kAccessEvidenceTagSize] = {};
  uint8_t expected_tag[kAccessEvidenceTagSize] = {};
  const bool valid = canonicalEventAccessAuth(retained_event, key_id, event_tag,
                                             credential) &&
      std::strcmp(key_id, receipt.key_id) == 0 &&
      equal(event_tag, receipt.event_tag, sizeof(event_tag)) &&
      deriveAccessEventReceiptTag(key, receipt, expected_tag) &&
      equal(expected_tag, receipt.tag, sizeof(expected_tag));
  zero(event_tag, sizeof(event_tag));
  zero(expected_tag, sizeof(expected_tag));
  return valid;
}

}  // namespace sgk
