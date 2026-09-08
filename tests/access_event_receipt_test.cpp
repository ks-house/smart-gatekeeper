#include "AccessEventReceipt.h"

#include <cassert>
#include <cstdio>
#include <cstring>
#include <limits>

int main() {
  std::array<uint8_t, 32> key{};
  for (size_t i = 0; i < key.size(); ++i) key[i] = static_cast<uint8_t>(i + 1);
  sgk::AccessEventReceipt receipt{};
  std::strcpy(receipt.key_id, "a1");
  std::strcpy(receipt.target_id, "test-target");
  std::strcpy(receipt.event_id, "00000000-0000-4000-8000-000000000001");
  std::strcpy(receipt.source_boot_id, "00112233445566778899aabbccddeeff");
  receipt.source_boot_count = 782;
  receipt.source_sequence = UINT64_C(9007199254740993);
  for (size_t i = 0; i < sizeof(receipt.event_tag); ++i) {
    receipt.event_tag[i] = static_cast<uint8_t>(0xa0 + i);
  }
  assert(sgk::deriveAccessEventReceiptTag(key, receipt, receipt.tag));
  uint8_t canonical[sgk::kAccessReceiptCanonicalCapacity] = {};
  size_t length = 0;
  assert(sgk::canonicalAccessEventReceipt(receipt, canonical, sizeof(canonical), &length));
  for (size_t i = 0; i < length; ++i) std::printf("%02x", canonical[i]);
  std::puts("");
  for (uint8_t octet : receipt.tag) std::printf("%02x", octet);
  std::puts("");

  sgk::CanonicalEvent retained{};
  retained.is_canonical = 1;
  std::strcpy(retained.event_id, receipt.event_id);
  std::strcpy(retained.source_boot_id, receipt.source_boot_id);
  retained.boot_count = static_cast<uint32_t>(receipt.source_boot_count);
  retained.sequence = receipt.source_sequence;
  assert(sgk::setCanonicalV2Detail(&retained, "PROOF_VALID", "a1", nullptr,
                                  receipt.event_tag));
  assert(sgk::verifyAccessEventReceipt(key, "test-target", retained, receipt));
  // Out-of-order/wrong-event receipts never acknowledge a different head.
  auto changed = receipt;
  ++changed.source_sequence;
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, changed));
  changed = receipt;
  ++changed.source_boot_count;
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, changed));
  changed = receipt;
  changed.event_id[35] = '2';
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, changed));
  changed = receipt;
  changed.source_boot_id[0] = '1';
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, changed));
  changed = receipt;
  changed.event_tag[0] ^= 1;
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, changed));
  changed = receipt;
  changed.tag[0] ^= 1;
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, changed));
  changed = receipt;
  std::strcpy(changed.key_id, "a2");
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, changed));
  assert(!sgk::verifyAccessEventReceipt(key, "another-target", retained, receipt));
  auto wrong_key = key;
  wrong_key[0] ^= 1;
  assert(!sgk::verifyAccessEventReceipt(wrong_key, "test-target", retained, receipt));
  // The event MAC is never valid as a receipt MAC (domain separation).
  changed = receipt;
  std::memcpy(changed.tag, changed.event_tag, sizeof(changed.tag));
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, changed));
  retained.is_canonical = 0;
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, receipt));

  changed = receipt;
  changed.source_sequence = std::numeric_limits<uint64_t>::max();
  assert(sgk::deriveAccessEventReceiptTag(key, changed, changed.tag));
  changed.source_sequence = 0;
  assert(!sgk::deriveAccessEventReceiptTag(key, changed, changed.tag));
  changed = receipt;
  std::memset(changed.target_id, 'a', sizeof(changed.target_id));
  assert(!sgk::deriveAccessEventReceiptTag(key, changed, changed.tag));
  changed = receipt;
  changed.event_id[14] = '1';
  assert(!sgk::deriveAccessEventReceiptTag(key, changed, changed.tag));
  changed = receipt;
  changed.source_boot_id[0] = 'A';
  assert(!sgk::deriveAccessEventReceiptTag(key, changed, changed.tag));
  assert(!sgk::canonicalAccessEventReceipt(receipt, canonical, 3, &length));
  assert(length == 0);
  assert(!sgk::deriveAccessEventReceiptTag({}, receipt, changed.tag));

  auto sensor = receipt;
  assert(sgk::deriveSensorSessionReceiptTag(key, sensor, sensor.tag));
  for (uint8_t octet : sensor.tag) std::printf("%02x", octet);
  std::puts("");
  auto verify_sensor = [&](const sgk::SensorSessionReceipt& value) {
    return sgk::verifySensorSessionReceipt(
        key, "test-target", receipt.source_boot_id, 782, receipt.event_id,
        receipt.source_sequence, "a1", receipt.event_tag, value);
  };
  assert(verify_sensor(sensor));
  assert(!verify_sensor(receipt));  // Access receipt cannot clear a summary.
  retained.is_canonical = 1;
  assert(!sgk::verifyAccessEventReceipt(key, "test-target", retained, sensor));
  sensor.source_sequence++;
  assert(!verify_sensor(sensor));
}
