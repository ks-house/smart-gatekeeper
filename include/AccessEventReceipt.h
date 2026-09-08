#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "OfflineEventQueue.h"

namespace sgk {

// Diagnostic-only Backend DB-commit receipt. This is not a command, an access
// authorization, or a high-water ACK. The adapter must first validate the exact
// JSON field set/version and canonical decimal-string representation.
struct AccessEventReceipt {
  char key_id[kAccessEvidenceKeyIdCapacity] = {};
  char target_id[65] = {};
  char event_id[37] = {};
  char source_boot_id[33] = {};
  uint64_t source_boot_count = 0;
  uint64_t source_sequence = 0;
  uint8_t event_tag[kAccessEvidenceTagSize] = {};
  uint8_t tag[kAccessEvidenceTagSize] = {};
};

constexpr size_t kAccessReceiptCanonicalCapacity = 192;

bool canonicalAccessEventReceipt(
    const AccessEventReceipt& receipt, uint8_t* output, size_t capacity,
    size_t* length_out);
bool deriveAccessEventReceiptTag(
    const std::array<uint8_t, 32>& key, const AccessEventReceipt& receipt,
    uint8_t output[kAccessEvidenceTagSize]);
// True acknowledges only this exact retained event, even across a reboot.
// No current-boot check: an old retained event still needs its own commit ACK.
bool verifyAccessEventReceipt(
    const std::array<uint8_t, 32>& key, const char* expected_target_id,
    const CanonicalEvent& retained_event, const AccessEventReceipt& receipt);

// Same bounded storage, different wire names and cryptographic domain:
// event_id=session_id, source_sequence=terminal_sequence, event_tag=summary_tag.
using SensorSessionReceipt = AccessEventReceipt;
bool canonicalSensorSessionReceipt(
    const SensorSessionReceipt& receipt, uint8_t* output, size_t capacity,
    size_t* length_out);
bool deriveSensorSessionReceiptTag(
    const std::array<uint8_t, 32>& key, const SensorSessionReceipt& receipt,
    uint8_t output[kAccessEvidenceTagSize]);
bool verifySensorSessionReceipt(
    const std::array<uint8_t, 32>& key, const char* expected_target_id,
    const char* expected_boot_id, uint64_t expected_boot_count,
    const char* expected_session_id, uint64_t expected_terminal_sequence,
    const char* expected_key_id, const uint8_t expected_summary_tag[16],
    const SensorSessionReceipt& receipt);

}  // namespace sgk
