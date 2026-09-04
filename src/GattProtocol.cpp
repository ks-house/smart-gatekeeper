#include "GattProtocol.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

namespace sgk {
namespace {

constexpr uint32_t kShaK[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b,
    0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7,
    0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152,
    0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
    0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
    0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
    0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

constexpr char kAccessEventCredentialRefDomain[] =
    "SGK-CREDENTIAL-REF-V1";
constexpr char kAccessEventMacDomain[] = "SGK-ACCESS-EVENT-MAC-V1";
constexpr char kAccessStatusMacDomain[] = "SGK-ACCESS-STATUS-MAC-V1";
constexpr uint8_t kFastNegotiationTranscript[] = {
    'S', 'G', 'K', 'F', 'A', 'S', 'T', '2',
    0x00, 0x02,  // protocol v2
    0x01,        // framing v1
    0x00, 0x03,  // Target capabilities
};

uint32_t rotateRight(uint32_t value, uint32_t bits) {
  return (value >> bits) | (value << (32 - bits));
}

bool allZeroBytes(const uint8_t* value, size_t length) {
  uint8_t aggregate = 0;
  for (size_t index = 0; index < length; ++index) aggregate |= value[index];
  return aggregate == 0;
}

bool isCanonicalProofRejection(ResultReason reason) {
  switch (reason) {
    case ResultReason::kUnsupportedVersion:
    case ResultReason::kMalformed:
    case ResultReason::kExpiredOrReplay:
    case ResultReason::kAclUnavailable:
    case ResultReason::kCredentialDenied:
    case ResultReason::kProofInvalid:
      return true;
    default:
      // Session/transport/internal failures belong to the terminal event. They
      // are not proof verdicts in the canonical event catalog.
      return false;
  }
}

// Volatile writes provide the same optimization barrier required from
// mbedtls_platform_zeroize while keeping native host tests dependency-free.
void secureZeroBytes(void* value, size_t length) {
  volatile uint8_t* cursor =
      reinterpret_cast<volatile uint8_t*>(value);
  while (length-- != 0) *cursor++ = 0;
}

bool validAccessEvidenceKeyId(const char* value, size_t* length_out = nullptr) {
  if (length_out != nullptr) *length_out = 0;
  if (value == nullptr) return false;
  size_t length = 0;
  while (value[length] != '\0' && length <= 4) {
    const char character = value[length];
    if (!((character >= 'a' && character <= 'z') ||
          (character >= '0' && character <= '9'))) {
      return false;
    }
    ++length;
  }
  if (length == 0 || length > 4 || value[length] != '\0') return false;
  if (length_out != nullptr) *length_out = length;
  return true;
}

bool validCredentialRefText(const char* value) {
  if (value == nullptr || value[0] == '\0') return false;
  const size_t length = std::strlen(value);
  if (length < 28 || length > 31 || value[0] != 'c' || value[1] != '_') {
    return false;
  }
  const char* separator = std::strchr(value + 2, '_');
  if (separator == nullptr) return false;
  const size_t key_id_length = static_cast<size_t>(separator - (value + 2));
  if (key_id_length == 0 || key_id_length > 4 ||
      std::strlen(separator + 1) != 24) {
    return false;
  }
  for (const char* cursor = value + 2; cursor < separator; ++cursor) {
    if (!((*cursor >= 'a' && *cursor <= 'z') ||
          (*cursor >= '0' && *cursor <= '9'))) {
      return false;
    }
  }
  for (const char* cursor = separator + 1; *cursor != '\0'; ++cursor) {
    if (!((*cursor >= '0' && *cursor <= '9') ||
          (*cursor >= 'a' && *cursor <= 'f'))) {
      return false;
    }
  }
  return true;
}

bool isUuid4(const std::array<uint8_t, 16>& value) {
  return !allZeroBytes(value.data(), value.size()) &&
         (value[6] & 0xf0) == 0x40 && (value[8] & 0xc0) == 0x80;
}

class CanonicalBinaryBuilder {
 public:
  CanonicalBinaryBuilder(uint8_t* output, size_t capacity)
      : output_(output), capacity_(capacity) {}

  bool append(const void* value, size_t length) {
    if (!valid_ || value == nullptr || length > capacity_ - size_) {
      valid_ = false;
      return false;
    }
    std::memcpy(output_ + size_, value, length);
    size_ += length;
    return true;
  }

  bool appendU8(uint8_t value) { return append(&value, sizeof(value)); }

  bool appendU16(uint16_t value) {
    const uint8_t encoded[2] = {static_cast<uint8_t>(value >> 8),
                                static_cast<uint8_t>(value)};
    return append(encoded, sizeof(encoded));
  }

  bool appendU32(uint32_t value) {
    const uint8_t encoded[4] = {
        static_cast<uint8_t>(value >> 24),
        static_cast<uint8_t>(value >> 16),
        static_cast<uint8_t>(value >> 8),
        static_cast<uint8_t>(value)};
    return append(encoded, sizeof(encoded));
  }

  bool appendU64(uint64_t value) {
    uint8_t encoded[8] = {};
    for (size_t index = 0; index < sizeof(encoded); ++index) {
      encoded[index] = static_cast<uint8_t>(value >> (56 - index * 8));
    }
    return append(encoded, sizeof(encoded));
  }

  bool appendLpAscii(const char* value, bool allow_empty = false) {
    if (!valid_ || value == nullptr) {
      valid_ = false;
      return false;
    }
    const size_t length = std::strlen(value);
    if ((!allow_empty && length == 0) || length > 0xffff) {
      valid_ = false;
      return false;
    }
    for (size_t index = 0; index < length; ++index) {
      if (static_cast<unsigned char>(value[index]) > 0x7f) {
        valid_ = false;
        return false;
      }
    }
    return appendU16(static_cast<uint16_t>(length)) &&
           (length == 0 || append(value, length));
  }

  bool appendOptionalUuid(bool present,
                          const std::array<uint8_t, 16>& value) {
    return appendU8(present ? 1 : 0) &&
           (!present || append(value.data(), value.size()));
  }

  bool appendOptionalU32(bool present, uint32_t value) {
    return appendU8(present ? 1 : 0) && (!present || appendU32(value));
  }

  bool appendOptionalU64(bool present, uint64_t value) {
    return appendU8(present ? 1 : 0) && (!present || appendU64(value));
  }

  bool valid() const { return valid_; }
  size_t size() const { return size_; }

 private:
  uint8_t* output_ = nullptr;
  size_t capacity_ = 0;
  size_t size_ = 0;
  bool valid_ = true;
};

bool hmacSha256(const std::array<uint8_t, 32>& key, const uint8_t* message,
                size_t message_length, uint8_t output[32]) {
  if (message == nullptr || message_length == 0 || output == nullptr ||
      allZeroBytes(key.data(), key.size()) ||
      message_length > kAccessEventMacInputCapacity) {
    return false;
  }
  std::array<uint8_t, 64> inner_pad{};
  std::array<uint8_t, 64> outer_pad{};
  for (size_t index = 0; index < inner_pad.size(); ++index) {
    const uint8_t key_byte = index < key.size() ? key[index] : 0;
    inner_pad[index] = static_cast<uint8_t>(key_byte ^ 0x36);
    outer_pad[index] = static_cast<uint8_t>(key_byte ^ 0x5c);
  }
  std::array<uint8_t, 64 + kAccessEventMacInputCapacity> inner_input{};
  std::memcpy(inner_input.data(), inner_pad.data(), inner_pad.size());
  std::memcpy(inner_input.data() + inner_pad.size(), message, message_length);
  std::array<uint8_t, 32> inner_digest{};
  ProtocolCore::sha256(inner_input.data(), inner_pad.size() + message_length,
                       inner_digest.data());

  std::array<uint8_t, 96> outer_input{};
  std::memcpy(outer_input.data(), outer_pad.data(), outer_pad.size());
  std::memcpy(outer_input.data() + outer_pad.size(), inner_digest.data(),
              inner_digest.size());
  ProtocolCore::sha256(outer_input.data(), outer_input.size(), output);

  secureZeroBytes(inner_pad.data(), inner_pad.size());
  secureZeroBytes(outer_pad.data(), outer_pad.size());
  secureZeroBytes(inner_input.data(), inner_input.size());
  secureZeroBytes(inner_digest.data(), inner_digest.size());
  secureZeroBytes(outer_input.data(), outer_input.size());
  return true;
}

}  // namespace

bool parseAccessEvidenceProvisioning(
    const char* key_hex, const char* key_id,
    std::array<uint8_t, 32>* key_out,
    char key_id_out[kAccessEvidenceKeyIdCapacity]) {
  if (key_out == nullptr || key_id_out == nullptr) return false;
  secureZeroBytes(key_out->data(), key_out->size());
  secureZeroBytes(key_id_out, kAccessEvidenceKeyIdCapacity);
  size_t key_id_length = 0;
  if (key_hex == nullptr || std::strlen(key_hex) != key_out->size() * 2 ||
      !validAccessEvidenceKeyId(key_id, &key_id_length)) {
    return false;
  }
  for (size_t index = 0; index < key_out->size(); ++index) {
    const char high = key_hex[index * 2];
    const char low = key_hex[index * 2 + 1];
    const auto nibble = [](char value, uint8_t* parsed) {
      if (parsed == nullptr) return false;
      if (value >= '0' && value <= '9') {
        *parsed = static_cast<uint8_t>(value - '0');
        return true;
      }
      if (value >= 'a' && value <= 'f') {
        *parsed = static_cast<uint8_t>(value - 'a' + 10);
        return true;
      }
      return false;
    };
    uint8_t high_value = 0;
    uint8_t low_value = 0;
    if (!nibble(high, &high_value) || !nibble(low, &low_value)) {
      secureZeroBytes(key_out->data(), key_out->size());
      return false;
    }
    (*key_out)[index] =
        static_cast<uint8_t>((high_value << 4) | low_value);
  }
  if (allZeroBytes(key_out->data(), key_out->size())) {
    secureZeroBytes(key_out->data(), key_out->size());
    return false;
  }
  std::memcpy(key_id_out, key_id, key_id_length);
  return true;
}

bool buildAccessEventMacInput(const AccessEventMacInput& input,
                              uint8_t* output, size_t capacity,
                              size_t* written) {
  if (written == nullptr) return false;
  *written = 0;
  if (output == nullptr || capacity == 0) return false;
  output[0] = 0;
  if (!validAccessEvidenceKeyId(input.key_id) ||
      allZeroBytes(input.door_id.data(), input.door_id.size()) ||
      allZeroBytes(input.source_boot_id.data(), input.source_boot_id.size()) ||
      input.source_boot_count == 0 || !isUuid4(input.event_id) ||
      !isUuid4(input.session_id) || input.attempt == 0 ||
      (input.has_causation && !isUuid4(input.causation_event_id)) ||
      (input.has_distance_mm && input.distance_mm > 10000) ||
      (input.has_duration_ms && input.duration_ms > 86400000ULL) ||
      (input.has_relay_hold_ms && input.relay_hold_ms > 600000U) ||
      (input.credential_ref != nullptr && input.credential_ref[0] != '\0' &&
       !validCredentialRefText(input.credential_ref))) {
    return false;
  }
  CanonicalBinaryBuilder builder(output, capacity);
  builder.append(kAccessEventMacDomain, sizeof(kAccessEventMacDomain));
  builder.appendLpAscii(input.key_id);
  builder.appendLpAscii(input.topic_target_id);
  builder.append(input.door_id.data(), input.door_id.size());
  builder.appendLpAscii(input.source_instance_id);
  builder.append(input.source_boot_id.data(), input.source_boot_id.size());
  builder.appendU64(input.source_boot_count);
  builder.append(input.event_id.data(), input.event_id.size());
  builder.append(input.session_id.data(), input.session_id.size());
  builder.appendU64(input.sequence);
  builder.appendU32(input.attempt);
  builder.appendLpAscii(input.event_code);
  builder.appendLpAscii(input.stage);
  builder.appendLpAscii(input.outcome);
  builder.appendLpAscii(input.reason_code);
  builder.appendOptionalUuid(input.has_causation, input.causation_event_id);
  builder.appendU64(input.monotonic_ms);
  builder.appendLpAscii(input.credential_ref == nullptr
                            ? ""
                            : input.credential_ref,
                        true);
  builder.appendOptionalU32(input.has_distance_mm, input.distance_mm);
  builder.appendOptionalU64(input.has_duration_ms, input.duration_ms);
  builder.appendOptionalU32(input.has_relay_hold_ms, input.relay_hold_ms);
  if (!builder.valid()) return false;
  *written = builder.size();
  return true;
}

bool buildAccessStatusMacInput(const AccessStatusMacInput& input,
                               uint8_t* output, size_t capacity,
                               size_t* written) {
  if (written == nullptr) return false;
  *written = 0;
  if (output == nullptr || capacity == 0) return false;
  output[0] = 0;
  const char* terminal_code = input.last_terminal_event_code;
  const char* terminal_reason = input.last_terminal_reason_code;
  const char* terminal_ref = input.last_terminal_credential_ref;
  if (!validAccessEvidenceKeyId(input.key_id) ||
      allZeroBytes(input.door_id.data(), input.door_id.size()) ||
      allZeroBytes(input.source_boot_id.data(), input.source_boot_id.size()) ||
      input.source_boot_count == 0 || input.access_revision == 0 ||
      input.relay_pin_level > 1 || input.last_terminal_phase_mask > 0x003f ||
      (input.has_last_terminal &&
       (!isUuid4(input.last_terminal_session_id) || terminal_code == nullptr ||
        terminal_code[0] == '\0' || terminal_reason == nullptr ||
        terminal_reason[0] == '\0' ||
        (terminal_ref != nullptr && terminal_ref[0] != '\0' &&
         !validCredentialRefText(terminal_ref)))) ||
      (!input.has_last_terminal &&
       (input.last_terminal_phase_mask != 0 ||
        (terminal_ref != nullptr && terminal_ref[0] != '\0')))) {
    return false;
  }
  CanonicalBinaryBuilder builder(output, capacity);
  builder.append(kAccessStatusMacDomain, sizeof(kAccessStatusMacDomain));
  builder.appendLpAscii(input.key_id);
  builder.appendLpAscii(input.topic_target_id);
  builder.append(input.door_id.data(), input.door_id.size());
  builder.append(input.source_boot_id.data(), input.source_boot_id.size());
  builder.appendU64(input.source_boot_count);
  builder.appendU64(input.access_revision);
  builder.appendLpAscii(input.state);
  builder.appendOptionalUuid(input.has_last_terminal,
                             input.last_terminal_session_id);
  builder.appendU8(input.has_last_terminal ? 1 : 0);
  if (input.has_last_terminal) {
    builder.appendU64(input.last_terminal_event_sequence);
  }
  builder.appendLpAscii(input.has_last_terminal ? terminal_code : "", true);
  builder.appendLpAscii(input.has_last_terminal ? terminal_reason : "", true);
  builder.appendLpAscii(
      input.has_last_terminal && terminal_ref != nullptr ? terminal_ref : "",
      true);
  builder.appendU16(input.last_terminal_phase_mask);
  builder.appendU8(input.relay_commanded_on ? 1 : 0);
  builder.appendU8(input.relay_pin_level);
  if (!builder.valid()) return false;
  *written = builder.size();
  return true;
}

bool deriveAccessEventMac(
    const std::array<uint8_t, 32>& key, const AccessEventMacInput& input,
    uint8_t output[kAccessEvidenceTagSize]) {
  if (output == nullptr) return false;
  secureZeroBytes(output, kAccessEvidenceTagSize);
  std::array<uint8_t, kAccessEventMacInputCapacity> canonical{};
  size_t length = 0;
  std::array<uint8_t, 32> digest{};
  const bool ok = buildAccessEventMacInput(input, canonical.data(),
                                            canonical.size(), &length) &&
                  hmacSha256(key, canonical.data(), length, digest.data());
  if (ok) std::memcpy(output, digest.data(), kAccessEvidenceTagSize);
  secureZeroBytes(canonical.data(), canonical.size());
  secureZeroBytes(digest.data(), digest.size());
  return ok;
}

bool deriveAccessStatusMac(
    const std::array<uint8_t, 32>& key, const AccessStatusMacInput& input,
    uint8_t output[kAccessEvidenceTagSize]) {
  if (output == nullptr) return false;
  secureZeroBytes(output, kAccessEvidenceTagSize);
  std::array<uint8_t, kAccessStatusMacInputCapacity> canonical{};
  size_t length = 0;
  std::array<uint8_t, 32> digest{};
  const bool ok = buildAccessStatusMacInput(input, canonical.data(),
                                             canonical.size(), &length) &&
                  hmacSha256(key, canonical.data(), length, digest.data());
  if (ok) std::memcpy(output, digest.data(), kAccessEvidenceTagSize);
  secureZeroBytes(canonical.data(), canonical.size());
  secureZeroBytes(digest.data(), digest.size());
  return ok;
}

bool deriveAccessEventCredentialRef(
    const std::array<uint8_t, 32>& key, const char* key_id,
    const std::array<uint8_t, 16>& door_id,
    const std::array<uint8_t, 16>& session_id,
    const std::array<uint8_t, 16>& credential_id,
    char output[kAccessEventCredentialRefCapacity]) {
  if (output == nullptr) return false;
  output[0] = '\0';

  size_t key_id_length = 0;
  if (key_id != nullptr) {
    while (key_id[key_id_length] != '\0' && key_id_length <= 4) {
      const char value = key_id[key_id_length];
      if (!((value >= 'a' && value <= 'z') ||
            (value >= '0' && value <= '9'))) {
        return false;
      }
      ++key_id_length;
    }
  }
  if (key_id_length == 0 || key_id_length > 4 ||
      key_id[key_id_length] != '\0' ||
      allZeroBytes(key.data(), key.size()) ||
      allZeroBytes(door_id.data(), door_id.size()) ||
      allZeroBytes(session_id.data(), session_id.size()) ||
      allZeroBytes(credential_id.data(), credential_id.size())) {
    return false;
  }

  std::array<uint8_t, 16> normalized_session = session_id;
  normalized_session[6] =
      static_cast<uint8_t>((normalized_session[6] & 0x0f) | 0x40);
  normalized_session[8] =
      static_cast<uint8_t>((normalized_session[8] & 0x3f) | 0x80);

  constexpr size_t kMessageSize =
      sizeof(kAccessEventCredentialRefDomain) + 16 + 16 + 16;
  std::array<uint8_t, kMessageSize> message{};
  size_t offset = 0;
  // sizeof includes the required domain separator NUL.
  std::memcpy(message.data() + offset, kAccessEventCredentialRefDomain,
              sizeof(kAccessEventCredentialRefDomain));
  offset += sizeof(kAccessEventCredentialRefDomain);
  std::memcpy(message.data() + offset, door_id.data(), door_id.size());
  offset += door_id.size();
  std::memcpy(message.data() + offset, normalized_session.data(),
              normalized_session.size());
  offset += normalized_session.size();
  std::memcpy(message.data() + offset, credential_id.data(),
              credential_id.size());

  std::array<uint8_t, 64> inner_pad{};
  std::array<uint8_t, 64> outer_pad{};
  for (size_t index = 0; index < inner_pad.size(); ++index) {
    const uint8_t key_byte = index < key.size() ? key[index] : 0;
    inner_pad[index] = static_cast<uint8_t>(key_byte ^ 0x36);
    outer_pad[index] = static_cast<uint8_t>(key_byte ^ 0x5c);
  }
  std::array<uint8_t, 64 + kMessageSize> inner_input{};
  std::memcpy(inner_input.data(), inner_pad.data(), inner_pad.size());
  std::memcpy(inner_input.data() + inner_pad.size(), message.data(),
              message.size());
  std::array<uint8_t, 32> inner_digest{};
  ProtocolCore::sha256(inner_input.data(), inner_input.size(),
                       inner_digest.data());

  std::array<uint8_t, 96> outer_input{};
  std::memcpy(outer_input.data(), outer_pad.data(), outer_pad.size());
  std::memcpy(outer_input.data() + outer_pad.size(), inner_digest.data(),
              inner_digest.size());
  std::array<uint8_t, 32> digest{};
  ProtocolCore::sha256(outer_input.data(), outer_input.size(), digest.data());

  static constexpr char kHex[] = "0123456789abcdef";
  char truncated_hex[25] = {};
  for (size_t index = 0; index < 12; ++index) {
    truncated_hex[index * 2] = kHex[digest[index] >> 4];
    truncated_hex[index * 2 + 1] = kHex[digest[index] & 0x0f];
  }
  const int written = std::snprintf(output, kAccessEventCredentialRefCapacity,
                                    "c_%s_%s", key_id, truncated_hex);

  secureZeroBytes(inner_pad.data(), inner_pad.size());
  secureZeroBytes(outer_pad.data(), outer_pad.size());
  secureZeroBytes(inner_input.data(), inner_input.size());
  secureZeroBytes(inner_digest.data(), inner_digest.size());
  secureZeroBytes(outer_input.data(), outer_input.size());
  secureZeroBytes(digest.data(), digest.size());
  secureZeroBytes(message.data(), message.size());
  secureZeroBytes(truncated_hex, sizeof(truncated_hex));
  return written > 0 &&
         static_cast<size_t>(written) < kAccessEventCredentialRefCapacity;
}

bool accessEventCodeAllowsCredentialRef(EventCode code) {
  switch (code) {
    case EventCode::kAccessProofVerified:
    case EventCode::kAccessArmed:
    case EventCode::kAccessSensorDetected:
    case EventCode::kAccessRelayOn:
    case EventCode::kAccessRelayOff:
    case EventCode::kAccessSessionCompleted:
    case EventCode::kAccessSessionTerminated:
      return true;
    default:
      return false;
  }
}

void LocalGattLifecycleBridge::emit(const Event& event) {
  sequence_high_water_ = std::max(sequence_high_water_, event.sequence);
  if (event.code == EventCode::kAccessProofVerified && event.sequence != 0 &&
      !allZeroBytes(event.session_id.data(), event.session_id.size()) &&
      !allZeroBytes(event.credential_id.data(), event.credential_id.size())) {
    session_id_ = event.session_id;
    boot_id_ = event.boot_id;
    credential_id_ = event.credential_id;
    verified_causation_sequence_ = event.sequence;
    verified_session_active_ = true;
  }
  const bool matches_verified_session =
      verified_session_active_ && event.session_id == session_id_;
  Event forwarded = event;
  if (matches_verified_session) {
    forwarded.credential_id = credential_id_;
  }
  if (downstream_ != nullptr) downstream_->emit(forwarded);
  secureZeroBytes(forwarded.credential_id.data(),
                  forwarded.credential_id.size());
  if (matches_verified_session) {
    if (event.code == EventCode::kAccessSessionTerminated) {
      clearVerifiedSession();
    } else if (event.sequence > verified_causation_sequence_) {
      verified_causation_sequence_ = event.sequence;
    }
  }
}

bool LocalGattLifecycleBridge::emitLifecycle(
    EventCode code, EventReason reason, ResultReason transport_reason,
    uint64_t now_ms, bool terminal) {
  if (!verified_session_active_ || downstream_ == nullptr ||
      sequence_high_water_ == UINT64_MAX) {
    return false;
  }
  const uint64_t cause = verified_causation_sequence_;
  const uint64_t sequence = ++sequence_high_water_;
  Event event{code, reason, transport_reason, now_ms, session_id_, boot_id_,
              sequence, cause != 0, cause, credential_id_};
  downstream_->emit(event);
  secureZeroBytes(event.credential_id.data(), event.credential_id.size());
  verified_causation_sequence_ = sequence;
  if (terminal) {
    clearVerifiedSession();
  }
  return true;
}

bool LocalGattLifecycleBridge::emitArmed(uint64_t now_ms) {
  return emitLifecycle(EventCode::kAccessArmed, EventReason::kArmAccepted,
                       ResultReason::kOk, now_ms, false);
}

bool LocalGattLifecycleBridge::emitSensorDetected(uint64_t now_ms) {
  return emitLifecycle(EventCode::kAccessSensorDetected,
                       EventReason::kSensorThresholdMet, ResultReason::kOk,
                       now_ms, false);
}

bool LocalGattLifecycleBridge::emitRelayOn(uint64_t now_ms) {
  return emitLifecycle(EventCode::kAccessRelayOn, EventReason::kRelayActivated,
                       ResultReason::kOk, now_ms, false);
}

bool LocalGattLifecycleBridge::emitRelayOff(uint64_t now_ms, bool failsafe) {
  return emitLifecycle(EventCode::kAccessRelayOff,
                       failsafe ? EventReason::kRelayFailsafeCutoff
                                : EventReason::kRelayHoldComplete,
                       ResultReason::kOk, now_ms, false);
}

bool LocalGattLifecycleBridge::emitCompleted(uint64_t now_ms) {
  return emitLifecycle(EventCode::kAccessSessionCompleted,
                       EventReason::kAccessGranted, ResultReason::kOk, now_ms,
                       true);
}

bool LocalGattLifecycleBridge::emitTerminated(uint64_t now_ms,
                                               EventReason reason) {
  return emitLifecycle(EventCode::kAccessSessionTerminated, reason,
                       reason == EventReason::kInternalError
                           ? ResultReason::kInternalFailClosed
                           : ResultReason::kExpiredOrReplay,
                       now_ms, true);
}

void LocalGattLifecycleBridge::clearVerifiedSession() {
  verified_session_active_ = false;
  session_id_.fill(0);
  boot_id_.fill(0);
  secureZeroBytes(credential_id_.data(), credential_id_.size());
  verified_causation_sequence_ = 0;
}

bool VerifiedAccessPhaseTracker::observe(const Event& event,
                                         uint16_t* terminal_phase_mask) {
  if (terminal_phase_mask != nullptr) *terminal_phase_mask = 0;

  if (event.code == EventCode::kAccessProofVerified) {
    if (allZeroBytes(event.session_id.data(), event.session_id.size()) ||
        allZeroBytes(event.credential_id.data(), event.credential_id.size())) {
      return false;
    }
    verified_session_active_ = true;
    session_id_ = event.session_id;
    phase_mask_ = kProofVerified;
    return false;
  }

  if (!verified_session_active_ || event.session_id != session_id_) {
    return false;
  }

  switch (event.code) {
    case EventCode::kAccessArmed:
      phase_mask_ |= kArmed;
      break;
    case EventCode::kAccessSensorDetected:
      phase_mask_ |= kSensorDetected;
      break;
    case EventCode::kAccessRelayOn:
      phase_mask_ |= kRelayOn;
      break;
    case EventCode::kAccessRelayOff:
      phase_mask_ |= kRelayOff;
      if (event.reason == EventReason::kRelayFailsafeCutoff) {
        phase_mask_ |= kRelayFailsafe;
      }
      break;
    default:
      break;
  }

  const bool terminal =
      event.code == EventCode::kAccessSessionCompleted ||
      event.code == EventCode::kAccessSessionTerminated;
  if (!terminal) return false;

  if (terminal_phase_mask != nullptr) *terminal_phase_mask = phase_mask_;
  clear();
  return true;
}

void VerifiedAccessPhaseTracker::clear() {
  verified_session_active_ = false;
  session_id_.fill(0);
  phase_mask_ = 0;
}

bool AdapterState::acceptConnection(const ConnectionToken& owner) {
  if (!owner.valid() || active_owner_.valid()) return false;
  active_owner_ = owner;
  subscriptions_ = 0;
  clearWrites();
  abortOutput();
  return true;
}

void AdapterState::disconnect(uint16_t handle) {
  if (!active_owner_.valid() || active_owner_.handle != handle) return;
  active_owner_ = {};
  subscriptions_ = 0;
  clearWrites();
  abortOutput();
}

void AdapterState::clear() {
  active_owner_ = {};
  subscriptions_ = 0;
  clearWrites();
  abortOutput();
}

bool AdapterState::ownerForHandle(uint16_t handle,
                                  ConnectionToken* owner) const {
  if (owner == nullptr) return false;
  *owner = {};
  if (!active_owner_.valid() || active_owner_.handle != handle) return false;
  *owner = active_owner_;
  return true;
}

uint8_t AdapterState::subscriptionBit(MessageType type) {
  switch (type) {
    case MessageType::kTargetHello:
      return 0x01;
    case MessageType::kChallenge:
      return 0x02;
    case MessageType::kResult:
    case MessageType::kError:
      return 0x04;
    case MessageType::kFastChallenge:
    case MessageType::kFastResult:
      return 0x08;
    default:
      return 0;
  }
}

bool AdapterState::setSubscribed(uint16_t handle, MessageType type,
                                 bool subscribed) {
  if (!active_owner_.valid() || active_owner_.handle != handle) return false;
  const uint8_t bit = subscriptionBit(type);
  if (bit == 0) return false;
  if (subscribed) {
    subscriptions_ |= bit;
  } else {
    subscriptions_ &= static_cast<uint8_t>(~bit);
  }
  return true;
}

bool AdapterState::isSubscribed(const ConnectionToken& owner,
                                MessageType type) const {
  const uint8_t bit = subscriptionBit(type);
  return owner.valid() && owner == active_owner_ && bit != 0 &&
         (subscriptions_ & bit) != 0;
}

bool AdapterState::enqueueWrite(uint16_t handle, MessageType type,
                                const uint8_t* value, size_t length) {
  ConnectionToken owner;
  if (!ownerForHandle(handle, &owner)) return false;
  if (value == nullptr || length == 0 ||
      length > pending_writes_[0].bytes.size() ||
      pending_count_ == pending_writes_.size()) {
    pending_overflow_ = true;
    overflow_owner_ = owner;
    return false;
  }
  const size_t slot = (pending_head_ + pending_count_) % pending_writes_.size();
  pending_writes_[slot] = PendingWrite{};
  pending_writes_[slot].owner = owner;
  pending_writes_[slot].type = type;
  pending_writes_[slot].length = length;
  std::memcpy(pending_writes_[slot].bytes.data(), value, length);
  pending_count_++;
  return true;
}

bool AdapterState::consumeOverflow(ConnectionToken* owner) {
  if (owner == nullptr) return false;
  *owner = {};
  if (!pending_overflow_) return false;
  *owner = overflow_owner_;
  clearWrites();
  return owner->valid() && *owner == active_owner_;
}

bool AdapterState::popWrite(PendingWrite* pending) {
  if (pending == nullptr || pending_count_ == 0) return false;
  *pending = pending_writes_[pending_head_];
  secureZeroBytes(&pending_writes_[pending_head_],
                  sizeof(pending_writes_[pending_head_]));
  pending_head_ = (pending_head_ + 1) % pending_writes_.size();
  pending_count_--;
  return true;
}

void AdapterState::clearWrites() {
  secureZeroBytes(pending_writes_.data(), sizeof(pending_writes_));
  pending_head_ = 0;
  pending_count_ = 0;
  pending_overflow_ = false;
  overflow_owner_ = {};
}

bool AdapterState::stageOutput(const OutputMessage& output) {
  const ConnectionToken owner{output.connection_handle,
                              output.connection_generation};
  if (output_active_ || !owner.valid() || owner != active_owner_ ||
      output.length == 0 || output.length > output.bytes.size() ||
      !isSubscribed(owner, output.type)) {
    return false;
  }
  output_generation_++;
  output_ = output;
  output_active_ = true;
  confirmation_pending_ = false;
  fragment_payload_capacity_ = 0;
  fragment_count_ = 0;
  fragment_index_ = 0;
  confirmation_deadline_ms_ = 0;
  return true;
}

bool AdapterState::beginNextIndication(uint16_t mtu, uint32_t now_ms,
                                       uint8_t* frame, size_t capacity,
                                       size_t* written, MessageType* type,
                                       IndicationToken* token) {
  if (written == nullptr || type == nullptr || token == nullptr) return false;
  *written = 0;
  *type = MessageType::kError;
  *token = {};
  if (!output_active_ || confirmation_pending_ ||
      active_owner_ != ConnectionToken{output_.connection_handle,
                                       output_.connection_generation} ||
      !isSubscribed(active_owner_, output_.type)) {
    return false;
  }
  const size_t payload_capacity =
      mtu > kFrameHeaderSize + 3 ? mtu - 3 - kFrameHeaderSize : 1;
  const size_t fragment_count =
      (output_.length + payload_capacity - 1) / payload_capacity;
  if (fragment_count == 0 || fragment_count > 255 ||
      (fragment_payload_capacity_ != 0 &&
       fragment_payload_capacity_ != payload_capacity)) {
    return false;
  }
  fragment_payload_capacity_ = payload_capacity;
  fragment_count_ = fragment_count;
  const size_t frame_length = ProtocolCore::buildFrame(
      output_.type, output_.message_id, output_.bytes.data(), output_.length,
      fragment_payload_capacity_, static_cast<uint8_t>(fragment_index_), frame,
      capacity);
  if (frame_length == 0) return false;
  confirmation_pending_ = true;
  confirmation_deadline_ms_ = now_ms + kIndicationConfirmationTimeoutMs;
  *written = frame_length;
  *type = output_.type;
  *token = IndicationToken{active_owner_, output_generation_,
                           static_cast<uint8_t>(fragment_index_)};
  return true;
}

bool AdapterState::beginNextIndication(uint16_t mtu, uint32_t now_ms,
                                       uint8_t* frame, size_t capacity,
                                       size_t* written, MessageType* type,
                                       ConnectionToken* owner) {
  IndicationToken token{};
  const bool res =
      beginNextIndication(mtu, now_ms, frame, capacity, written, type, &token);
  if (res && owner != nullptr) {
    *owner = token.owner;
  }
  return res;
}

IndicationResult AdapterState::confirmIndication(const IndicationToken& token,
                                                  MessageType type,
                                                  bool success) {
  if (!token.valid() || !output_active_ || !confirmation_pending_ ||
      token.owner != active_owner_ ||
      token.owner != ConnectionToken{output_.connection_handle,
                                       output_.connection_generation} ||
      token.output_generation != output_generation_ ||
      token.fragment_index != fragment_index_ ||
      type != output_.type) {
    return IndicationResult::kIgnored;
  }
  confirmation_pending_ = false;
  confirmation_deadline_ms_ = 0;
  if (!success) {
    abortOutput();
    return IndicationResult::kAborted;
  }
  fragment_index_++;
  if (fragment_index_ >= fragment_count_) {
    abortOutput();
    return IndicationResult::kMessageConfirmed;
  }
  return IndicationResult::kFragmentConfirmed;
}

bool AdapterState::reached(uint32_t now_ms, uint32_t deadline_ms) {
  return static_cast<int32_t>(now_ms - deadline_ms) >= 0;
}

bool AdapterState::confirmationTimedOut(uint32_t now_ms) const {
  return confirmation_pending_ && reached(now_ms, confirmation_deadline_ms_);
}

void AdapterState::abortOutput() {
  output_generation_++;
  output_ = OutputMessage{};
  output_active_ = false;
  confirmation_pending_ = false;
  fragment_payload_capacity_ = 0;
  fragment_count_ = 0;
  fragment_index_ = 0;
  confirmation_deadline_ms_ = 0;
}

ProtocolCore::ProtocolCore(RandomSource& random, ProofVerifier& verifier,
                           const std::array<uint8_t, 16>& door_id,
                           EventSink* event_sink,
                           AuthControlGate* auth_control_gate)
    : random_(random),
      verifier_(verifier),
      event_sink_(event_sink),
      auth_control_gate_(auth_control_gate),
      door_id_(door_id) {
  door_id_ready_ = !allZero(door_id_.data(), door_id_.size()) &&
                   !std::all_of(door_id_.begin(), door_id_.end(),
                                [](uint8_t value) { return value == 0xff; });
}

bool ProtocolCore::initialize() {
  resetSession();
  if (!door_id_ready_) {
    enabled_ = false;
    rng_ready_ = false;
    return false;
  }
  rng_ready_ = randomUnique(boot_id_.data(), boot_id_.size(), nullptr);
  if (!rng_ready_) enabled_ = false;
  return rng_ready_;
}

void ProtocolCore::setEnabled(bool enabled) {
  enabled_ = enabled && rng_ready_;
  if (!enabled_) {
    abortAuthControl(0);
    connection_active_ = false;
    resetSession();
  }
}

void ProtocolCore::setOtaBusy(bool busy, uint32_t now_ms) {
  ota_busy_ = busy;
  if (busy && state_ != SessionState::kIdle &&
      state_ != SessionState::kCompleted &&
      state_ != SessionState::kConsumed) {
    // Bind BUSY to the still-live protocol/session before clearing secrets.
    // Supersede any unsent hello/challenge so the fixed-capacity output queue
    // cannot prevent the terminal BUSY result from being staged.
    outputs_ = {};
    output_head_ = 0;
    output_count_ = 0;
    queueResult(ResultReason::kBusy, 1000, active_acl_version_);
    emit(EventCode::kAccessSessionTerminated, ResultReason::kBusy, now_ms);
    abortAuthControl(now_ms);
    resetSessionPreservingOutputs();
  }
}


bool ProtocolCore::connect(uint16_t connection_id, uint32_t now_ms,
                           ConnectionToken* accepted_owner) {
  if (accepted_owner != nullptr) *accepted_owner = {};
  if (!enabled() || connection_active_) return false;
  connection_active_ = true;
  connection_id_ = connection_id;
  connection_generation_++;
  if (connection_generation_ == 0) connection_generation_ = 1;
  resetSession();
  if (accepted_owner != nullptr) *accepted_owner = connectionOwner();
  (void)now_ms;
  return true;
}

void ProtocolCore::disconnect(const ConnectionToken& owner, uint32_t now_ms) {
  if (!connection_active_ || owner != connectionOwner()) return;
  connection_active_ = false;
  if (state_ != SessionState::kIdle &&
      state_ != SessionState::kCompleted) {
    emit(EventCode::kAccessGattFailed, ResultReason::kSessionInvalid, now_ms);
    emit(EventCode::kAccessSessionTerminated, ResultReason::kSessionInvalid,
         now_ms);
    abortAuthControl(now_ms);
  }
  resetSession();
}

void ProtocolCore::abortTransport(const ConnectionToken& owner,
                                  ResultReason reason, uint32_t now_ms) {
  if (!connection_active_ || owner != connectionOwner()) return;
  // RESULT delivery is downstream of the already committed Target action.
  // Losing that indication must not fabricate a failed access terminal or
  // clear the verified actor while ARMED/RELAY_HOLD continues independently.
  if (state_ != SessionState::kCompleted) {
    emit(EventCode::kAccessSessionTerminated, reason, now_ms);
    abortAuthControl(now_ms);
  }
  resetSession();
}

bool ProtocolCore::reached(uint32_t now_ms, uint32_t deadline_ms) {
  return static_cast<int32_t>(now_ms - deadline_ms) >= 0;
}

uint16_t ProtocolCore::readU16(const uint8_t* value) {
  return static_cast<uint16_t>((static_cast<uint16_t>(value[0]) << 8) |
                               value[1]);
}

uint32_t ProtocolCore::readU32(const uint8_t* value) {
  return (static_cast<uint32_t>(value[0]) << 24) |
         (static_cast<uint32_t>(value[1]) << 16) |
         (static_cast<uint32_t>(value[2]) << 8) | value[3];
}

void ProtocolCore::writeU16(uint8_t* output, uint16_t value) {
  output[0] = static_cast<uint8_t>(value >> 8);
  output[1] = static_cast<uint8_t>(value);
}

void ProtocolCore::writeU32(uint8_t* output, uint32_t value) {
  output[0] = static_cast<uint8_t>(value >> 24);
  output[1] = static_cast<uint8_t>(value >> 16);
  output[2] = static_cast<uint8_t>(value >> 8);
  output[3] = static_cast<uint8_t>(value);
}

void ProtocolCore::writeU64(uint8_t* output, uint64_t value) {
  for (size_t index = 0; index < 8; ++index) {
    output[index] = static_cast<uint8_t>(value >> (56 - index * 8));
  }
}

bool ProtocolCore::allZero(const uint8_t* value, size_t length) {
  uint8_t aggregate = 0;
  for (size_t index = 0; index < length; ++index) aggregate |= value[index];
  return aggregate == 0;
}

bool ProtocolCore::randomUnique(uint8_t* output, size_t length,
                                const uint8_t* previous) {
  if (output == nullptr || length == 0) return false;
  for (size_t attempt = 0; attempt < 4; ++attempt) {
    if (!random_.fill(output, length) || allZero(output, length)) continue;
    if (previous != nullptr && std::memcmp(output, previous, length) == 0) {
      continue;
    }
    return true;
  }
  std::memset(output, 0, length);
  return false;
}

void ProtocolCore::clearReassembly() {
  secureZeroBytes(&reassembly_, sizeof(reassembly_));
  reassembly_.type = MessageType::kError;
}

void ProtocolCore::resetSession() {
  state_ = SessionState::kIdle;
  selected_protocol_ = 0;
  challenge_deadline_ms_ = 0;
  active_acl_version_ = 0;
  session_id_.fill(0);
  nonce_.fill(0);
  negotiation_hash_.fill(0);
  challenge_.fill(0);
  clearReassembly();
  output_head_ = 0;
  output_count_ = 0;
}

void ProtocolCore::tick(uint32_t now_ms) {
  if (reassembly_.active &&
      reached(now_ms, reassembly_.started_ms + kAssemblyTimeoutMs)) {
    reject(ResultReason::kMalformed, now_ms);
  } else if (state_ == SessionState::kChallengeIssued &&
             reached(now_ms, challenge_deadline_ms_)) {
    reject(ResultReason::kExpiredOrReplay, now_ms);
  }
}

bool ProtocolCore::receiveFrame(MessageType expected_type,
                                const ConnectionToken& owner,
                                const uint8_t* frame,
                                size_t frame_length, uint32_t now_ms) {
  if (!enabled() || !connection_active_ || owner != connectionOwner()) {
    return false;
  }
  if (ota_busy_) {
    queueResult(ResultReason::kBusy, 1000, active_acl_version_);
    return false;
  }
  if (state_ == SessionState::kCompleted) {
    // The authenticated action is already irrevocably committed. A duplicate
    // or malformed trailing write must neither execute it again nor fabricate
    // a failed terminal that clears the verified lifecycle actor.
    queueResult(ResultReason::kExpiredOrReplay, 0, active_acl_version_);
    return false;
  }
  if (reached(now_ms, backoff_until_ms_) == false && failed_attempts_ >= 3) {
    queueResult(ResultReason::kRateLimited,
                static_cast<uint32_t>(backoff_until_ms_ - now_ms),
                active_acl_version_);
    return false;
  }
  if (frame == nullptr || frame_length <= kFrameHeaderSize ||
      frame_length > reassembly_.last_frame.size()) {
    reject(ResultReason::kMalformed, now_ms);
    return false;
  }
  if (frame[0] != 'S' || frame[1] != 'G' || frame[2] != 1 ||
      frame[3] != static_cast<uint8_t>(expected_type)) {
    reject(ResultReason::kMalformed, now_ms);
    return false;
  }
  const uint16_t message_id = readU16(frame + 4);
  const uint8_t fragment_index = frame[6];
  const uint8_t fragment_count = frame[7];
  const uint16_t total_length = readU16(frame + 8);
  const size_t data_length = frame_length - kFrameHeaderSize;
  if (message_id == 0 || fragment_count == 0 ||
      fragment_index >= fragment_count || total_length == 0 ||
      total_length > kMaxMessageSize || data_length == 0) {
    reject(ResultReason::kMalformed, now_ms);
    return false;
  }

  if (!reassembly_.active) {
    if (fragment_index != 0) {
      reject(ResultReason::kMalformed, now_ms);
      return false;
    }
    reassembly_.active = true;
    reassembly_.type = expected_type;
    reassembly_.message_id = message_id;
    reassembly_.fragment_count = fragment_count;
    reassembly_.total_length = total_length;
    reassembly_.started_ms = now_ms;
  } else if (frame_length == reassembly_.last_frame_length &&
             fragment_index + 1 == reassembly_.next_index &&
             std::memcmp(frame, reassembly_.last_frame.data(), frame_length) ==
                 0) {
    return true;  // Idempotent retransmission of the immediately prior frame.
  }

  if (reached(now_ms, reassembly_.started_ms + kAssemblyTimeoutMs) ||
      reassembly_.type != expected_type ||
      reassembly_.message_id != message_id ||
      reassembly_.fragment_count != fragment_count ||
      reassembly_.total_length != total_length ||
      reassembly_.next_index != fragment_index ||
      reassembly_.length + data_length > total_length) {
    reject(ResultReason::kMalformed, now_ms);
    return false;
  }

  std::memcpy(reassembly_.bytes.data() + reassembly_.length,
              frame + kFrameHeaderSize, data_length);
  reassembly_.length += data_length;
  reassembly_.next_index++;
  std::memcpy(reassembly_.last_frame.data(), frame, frame_length);
  reassembly_.last_frame_length = frame_length;

  if (fragment_index + 1 != fragment_count) {
    if (reassembly_.length >= total_length) {
      reject(ResultReason::kMalformed, now_ms);
      return false;
    }
    return true;
  }
  if (reassembly_.length != total_length) {
    reject(ResultReason::kMalformed, now_ms);
    return false;
  }

  std::array<uint8_t, kMaxMessageSize> complete = reassembly_.bytes;
  const size_t complete_length = reassembly_.length;
  const MessageType complete_type = reassembly_.type;
  clearReassembly();
  const bool processed =
      processMessage(complete_type, complete.data(), complete_length, now_ms);
  secureZeroBytes(complete.data(), complete.size());
  return processed;
}

bool ProtocolCore::processMessage(MessageType type, const uint8_t* payload,
                                  size_t length, uint32_t now_ms) {
  if (type == MessageType::kClientHello) {
    return processHello(payload, length, now_ms);
  }
  if (type == MessageType::kProof &&
      selected_protocol_ != kFastProtocolVersion) {
    return processProof(payload, length, now_ms);
  }
  if (type == MessageType::kFastProof &&
      selected_protocol_ == kFastProtocolVersion) {
    return processProof(payload, length, now_ms);
  }
  reject(ResultReason::kMalformed, now_ms);
  return false;
}

bool ProtocolCore::beginFastSession(const ConnectionToken& owner,
                                    uint32_t now_ms) {
  if (!enabled() || !connection_active_ || owner != connectionOwner() ||
      state_ != SessionState::kIdle) {
    return false;
  }
  selected_protocol_ = kFastProtocolVersion;
  if (!randomUnique(session_id_.data(), session_id_.size(),
                    previous_session_id_.data()) ||
      !randomUnique(nonce_.data(), nonce_.size(), previous_nonce_.data())) {
    rng_ready_ = false;
    enabled_ = false;
    reject(ResultReason::kInternalFailClosed, now_ms);
    return false;
  }
  previous_session_id_ = session_id_;
  previous_nonce_ = nonce_;
  active_acl_version_ = verifier_.activeAclVersion();
  event_last_causation_sequence_ = 0;
  emit(EventCode::kAccessGattConnected, ResultReason::kOk, now_ms);

  if (ota_busy_) {
    queueResult(ResultReason::kBusy, 1000, active_acl_version_);
    emit(EventCode::kAccessSessionTerminated, ResultReason::kBusy, now_ms);
    resetSessionPreservingOutputs();
    return false;
  }
  if (!reached(now_ms, backoff_until_ms_) && failed_attempts_ >= 3) {
    queueResult(ResultReason::kRateLimited,
                static_cast<uint32_t>(backoff_until_ms_ - now_ms),
                active_acl_version_);
    emit(EventCode::kAccessSessionTerminated, ResultReason::kRateLimited,
         now_ms);
    resetSessionPreservingOutputs();
    return false;
  }

  auth_control_active_ = auth_control_gate_ != nullptr;
  if (!auth_control_active_ || !auth_control_gate_->beginAuth(now_ms)) {
    abortAuthControl(now_ms);
    queueResult(auth_control_gate_ == nullptr
                    ? ResultReason::kInternalFailClosed
                    : ResultReason::kBusy,
                auth_control_gate_ == nullptr ? 0 : 1000,
                active_acl_version_);
    emit(EventCode::kAccessSessionTerminated,
         auth_control_gate_ == nullptr ? ResultReason::kInternalFailClosed
                                       : ResultReason::kBusy,
         now_ms);
    resetSessionPreservingOutputs();
    return false;
  }

  sha256(kFastNegotiationTranscript, sizeof(kFastNegotiationTranscript),
         negotiation_hash_.data());
  state_ = SessionState::kHelloReceived;
  buildChallenge(now_ms);
  return true;
}

bool ProtocolCore::processHello(const uint8_t* payload, size_t length,
                                uint32_t now_ms) {
  if (length != kClientHelloSize || state_ != SessionState::kIdle) {
    reject(ResultReason::kMalformed, now_ms);
    return false;
  }
  const uint16_t client_min = readU16(payload);
  const uint16_t client_max = readU16(payload + 2);
  const uint8_t framing_min = payload[4];
  const uint8_t framing_max = payload[5];
  const uint16_t max_rx = readU16(payload + 6);
  constexpr uint16_t target_min = 1;
  constexpr uint16_t target_max = 1;
  constexpr uint16_t security_floor = 1;
  const bool framing_supported =
      framing_min <= 1 && framing_max >= 1 && framing_min <= framing_max;
  const bool receive_supported =
      max_rx >= kChallengeSize && max_rx <= kMaxMessageSize;
  const uint16_t candidate = std::min(client_max, target_max);
  const uint16_t floor = std::max(std::max(client_min, target_min),
                                  security_floor);
  if (client_min == 0 || client_min > client_max || !framing_supported ||
      !receive_supported || candidate < floor || client_max < target_min ||
      client_min > target_max) {
    queueTargetHello(0, 1);
    return false;
  }

  if (!randomUnique(session_id_.data(), session_id_.size(),
                    previous_session_id_.data()) ||
      !randomUnique(nonce_.data(), nonce_.size(), previous_nonce_.data())) {
    rng_ready_ = false;
    enabled_ = false;
    reject(ResultReason::kInternalFailClosed, now_ms);
    return false;
  }
  previous_session_id_ = session_id_;
  previous_nonce_ = nonce_;
  selected_protocol_ = candidate;
  active_acl_version_ = verifier_.activeAclVersion();
  state_ = SessionState::kHelloReceived;
  event_last_causation_sequence_ = 0;
  emit(EventCode::kAccessGattConnected, ResultReason::kOk, now_ms);

  auth_control_active_ = auth_control_gate_ != nullptr;
  if (!auth_control_active_ || !auth_control_gate_->beginAuth(now_ms)) {
    abortAuthControl(now_ms);
    queueTargetHello(0, 2);
    emit(EventCode::kAccessSessionTerminated,
         auth_control_gate_ == nullptr ? ResultReason::kInternalFailClosed
                                       : ResultReason::kBusy,
         now_ms);
    resetSessionPreservingOutputs();
    return false;
  }
  uint8_t target_hello[kTargetHelloSize] = {};
  writeU16(target_hello, selected_protocol_);
  writeU16(target_hello + 2, target_min);
  writeU16(target_hello + 4, target_max);
  target_hello[6] = 1;
  target_hello[7] = 0;
  writeU16(target_hello + 8, kMaxMessageSize);
  writeU32(target_hello + 10, 3);
  writeU32(target_hello + 14, 200);
  writeU16(target_hello + 18, security_floor);
  std::array<uint8_t, kClientHelloSize + kTargetHelloSize> transcript{};
  std::memcpy(transcript.data(), payload, kClientHelloSize);
  std::memcpy(transcript.data() + kClientHelloSize, target_hello,
              kTargetHelloSize);
  sha256(transcript.data(), transcript.size(), negotiation_hash_.data());
  queue(MessageType::kTargetHello, target_hello, sizeof(target_hello));
  buildChallenge(now_ms);
  return true;
}

void ProtocolCore::buildChallenge(uint32_t now_ms) {
  if (state_ != SessionState::kHelloReceived) {
    reject(ResultReason::kSessionInvalid, now_ms);
    return;
  }
  challenge_.fill(0);
  std::memcpy(challenge_.data(),
              selected_protocol_ == kFastProtocolVersion ? "SGKCHAL2"
                                                         : "SGKCHAL1",
              8);
  writeU16(challenge_.data() + 8, selected_protocol_);
  std::memcpy(challenge_.data() + 10, door_id_.data(), door_id_.size());
  std::memcpy(challenge_.data() + 26, session_id_.data(), session_id_.size());
  std::memcpy(challenge_.data() + 42, nonce_.data(), nonce_.size());
  std::memcpy(challenge_.data() + 74, boot_id_.data(), boot_id_.size());
  challenge_deadline_ms_ = now_ms + kChallengeLifetimeMs;
  writeU64(challenge_.data() + 90, challenge_deadline_ms_);
  writeU64(challenge_.data() + 98, active_acl_version_);
  std::memcpy(challenge_.data() + 106, negotiation_hash_.data(),
              negotiation_hash_.size());
  state_ = SessionState::kChallengeIssued;
  queue(selected_protocol_ == kFastProtocolVersion
            ? MessageType::kFastChallenge
            : MessageType::kChallenge,
        challenge_.data(), challenge_.size());
  emit(EventCode::kAccessProofRequested, ResultReason::kOk, now_ms);
}

bool ProtocolCore::processProof(const uint8_t* payload, size_t length,
                                uint32_t now_ms) {
  if (state_ != SessionState::kChallengeIssued) {
    reject(ResultReason::kExpiredOrReplay, now_ms);
    return false;
  }
  state_ = SessionState::kConsumed;  // Single-use before all later checks.
  if (length != kProofSize) {
    reject(ResultReason::kMalformed, now_ms);
    return false;
  }
  if (reached(now_ms, challenge_deadline_ms_)) {
    reject(ResultReason::kExpiredOrReplay, now_ms);
    return false;
  }
  const uint16_t protocol = readU16(payload);
  if (protocol != selected_protocol_ ||
      std::memcmp(payload + 2, session_id_.data(), session_id_.size()) != 0) {
    reject(ResultReason::kSessionInvalid, now_ms);
    return false;
  }
  const uint8_t action = payload[34];
  if (action != static_cast<uint8_t>(LocalAccessAction::kArmForSensor) &&
      action != static_cast<uint8_t>(LocalAccessAction::kOpenImmediately)) {
    reject(ResultReason::kProofInvalid, now_ms);
    return false;
  }

  VerifyRequest request{};
  request.protocol_version = protocol;
  std::memcpy(request.credential_id.data(), payload + 18,
              request.credential_id.size());
  request.action = action;
  request.client_capabilities = readU32(payload + 35);
  std::memcpy(request.signature_raw64.data(), payload + 39,
              request.signature_raw64.size());
  std::memcpy(request.signing_input.data(),
              selected_protocol_ == kFastProtocolVersion ? "SGKPRF02"
                                                         : "SGKPRF01",
              8);
  sha256(challenge_.data(), challenge_.size(), request.signing_input.data() + 8);
  std::memcpy(request.signing_input.data() + 40, request.credential_id.data(),
              request.credential_id.size());
  request.signing_input[56] = action;
  writeU32(request.signing_input.data() + 57, request.client_capabilities);

  state_ = SessionState::kVerifying;
  const VerifyResult result = verifier_.verify(request);
  state_ = SessionState::kConsumed;
  active_acl_version_ = result.active_acl_version;
  if (result.reason != ResultReason::kOk) {
    const ResultReason public_reason =
        result.reason == ResultReason::kAclUnavailable
            ? ResultReason::kAclUnavailable
            : (result.reason == ResultReason::kCredentialDenied
                   ? ResultReason::kCredentialDenied
                   : ResultReason::kProofInvalid);
    secureZeroBytes(&request, sizeof(request));
    reject(public_reason, now_ms);
    return false;
  }

  emit(EventCode::kAccessProofVerified, ResultReason::kOk, now_ms,
       &request.credential_id);
  secureZeroBytes(&request, sizeof(request));
  const bool action_committed =
      auth_control_active_ && auth_control_gate_ != nullptr &&
      auth_control_gate_->commitAuthorizedAction(
          static_cast<LocalAccessAction>(action), now_ms);
  if (!action_committed) {
    abortAuthControl(now_ms);
    reject(ResultReason::kInternalFailClosed, now_ms, false);
    return false;
  }
  auth_control_active_ = false;

  queueResult(ResultReason::kOk, 0, active_acl_version_);
  state_ = SessionState::kCompleted;
  failed_attempts_ = 0;
  return true;
}

void ProtocolCore::queueTargetHello(uint16_t selected, uint8_t status) {
  uint8_t payload[kTargetHelloSize] = {};
  writeU16(payload, selected);
  writeU16(payload + 2, 1);
  writeU16(payload + 4, 1);
  payload[6] = 1;
  payload[7] = status;
  writeU16(payload + 8, kMaxMessageSize);
  writeU32(payload + 10, 3);
  writeU32(payload + 14, 200);
  writeU16(payload + 18, 1);
  queue(MessageType::kTargetHello, payload, sizeof(payload));
}

void ProtocolCore::queueResult(ResultReason reason, uint32_t retry_after_ms,
                               uint64_t acl_version) {
  uint8_t payload[kResultSize] = {};
  writeU16(payload, selected_protocol_);
  std::memcpy(payload + 2, session_id_.data(), session_id_.size());
  writeU16(payload + 18, static_cast<uint16_t>(reason));
  writeU32(payload + 20, retry_after_ms);
  writeU64(payload + 24, acl_version);
  queue(selected_protocol_ == kFastProtocolVersion
            ? MessageType::kFastResult
            : MessageType::kResult,
        payload, sizeof(payload));
}

bool ProtocolCore::queue(MessageType type, const uint8_t* payload,
                         size_t length) {
  if (payload == nullptr || length == 0 || length > kMaxMessageSize ||
      output_count_ == outputs_.size()) {
    return false;
  }
  const size_t slot = (output_head_ + output_count_) % outputs_.size();
  outputs_[slot] = OutputMessage{};
  outputs_[slot].type = type;
  outputs_[slot].message_id = next_message_id_++;
  outputs_[slot].connection_handle = connection_id_;
  outputs_[slot].connection_generation = connection_generation_;
  if (next_message_id_ == 0) next_message_id_ = 1;
  outputs_[slot].length = length;
  std::memcpy(outputs_[slot].bytes.data(), payload, length);
  output_count_++;
  return true;
}

bool ProtocolCore::popOutput(OutputMessage* output) {
  if (output == nullptr || output_count_ == 0) return false;
  *output = outputs_[output_head_];
  output_head_ = (output_head_ + 1) % outputs_.size();
  output_count_--;
  return true;
}

void ProtocolCore::reject(ResultReason reason, uint32_t now_ms,
                          bool count_failure) {
  queueResult(reason, reason == ResultReason::kRateLimited ? 1000 : 0,
              active_acl_version_);
  const bool has_session =
      !allZeroBytes(session_id_.data(), session_id_.size());
  if (has_session) {
    if (isCanonicalProofRejection(reason)) {
      emit(EventCode::kAccessProofRejected, reason, now_ms);
    }
    emit(EventCode::kAccessSessionTerminated, reason, now_ms);
  }
  abortAuthControl(now_ms);
  if (count_failure) {
    if (failed_attempts_ == 0 ||
        reached(now_ms, failure_window_started_ms_ + 10000)) {
      failed_attempts_ = 0;
      failure_window_started_ms_ = now_ms;
    }
    failed_attempts_++;
    if (failed_attempts_ >= 3) {
      const uint32_t shift = std::min<uint32_t>(failed_attempts_ - 3, 3);
      backoff_until_ms_ = now_ms + (1000U << shift);
    }
  }
  resetSessionPreservingOutputs();
}

void ProtocolCore::abortAuthControl(uint32_t now_ms) {
  if (!auth_control_active_) return;
  auth_control_active_ = false;
  if (auth_control_gate_ != nullptr) auth_control_gate_->abortAuth(now_ms);
}

void ProtocolCore::resetSessionPreservingOutputs() {
  const size_t preserved_output_head = output_head_;
  const size_t preserved_output_count = output_count_;
  const auto preserved_outputs = outputs_;
  resetSession();
  output_head_ = preserved_output_head;
  output_count_ = preserved_output_count;
  outputs_ = preserved_outputs;
}

void ProtocolCore::emit(
    EventCode code, ResultReason reason, uint32_t now_ms,
    const std::array<uint8_t, 16>* credential_id) {
  if (event_sink_ != nullptr) {
    if (event_time_initialized_ && now_ms < event_last_now_ms_) {
      event_monotonic_high_ += (uint64_t{1} << 32);
    }
    event_time_initialized_ = true;
    event_last_now_ms_ = now_ms;
    const uint64_t sequence = ++event_sequence_;
    Event event{code,
                eventReason(code, reason),
                reason,
                event_monotonic_high_ + now_ms,
                session_id_,
                boot_id_,
                sequence,
                event_last_causation_sequence_ != 0,
                event_last_causation_sequence_};
    if (credential_id != nullptr) event.credential_id = *credential_id;
    event_sink_->emit(event);
    secureZeroBytes(event.credential_id.data(), event.credential_id.size());
    event_last_causation_sequence_ = sequence;
  }
}

EventReason ProtocolCore::eventReason(EventCode code, ResultReason reason) {
  if (code == EventCode::kAccessGattConnected) return EventReason::kGattConnected;
  if (code == EventCode::kAccessGattFailed) return EventReason::kGattDisconnected;
  if (code == EventCode::kAccessProofRequested) {
    return EventReason::kProofChallengeIssued;
  }
  if (code == EventCode::kAccessProofVerified) return EventReason::kProofValid;
  switch (reason) {
    case ResultReason::kUnsupportedVersion:
      return EventReason::kProtocolIncompatible;
    case ResultReason::kMalformed:
      return EventReason::kMalformedProof;
    case ResultReason::kExpiredOrReplay:
      return EventReason::kProofExpired;
    case ResultReason::kAclUnavailable:
      return EventReason::kAclNotFound;
    case ResultReason::kCredentialDenied:
      return EventReason::kCredentialInactive;
    case ResultReason::kProofInvalid:
      return EventReason::kSignatureInvalid;
    case ResultReason::kBusy:
      return EventReason::kOtaBusy;
    case ResultReason::kRateLimited:
      return EventReason::kSessionTimeout;
    default:
      return EventReason::kInternalError;
  }
}

bool ProtocolCore::copyOutput(const OutputMessage& source,
                              uint8_t* destination, size_t capacity,
                              size_t* written) {
  if (written == nullptr) return false;
  *written = 0;
  if (destination == nullptr || source.length > capacity ||
      source.length > source.bytes.size()) {
    return false;
  }
  std::memcpy(destination, source.bytes.data(), source.length);
  *written = source.length;
  return true;
}

size_t ProtocolCore::buildFrame(MessageType type, uint16_t message_id,
                                const uint8_t* payload, size_t payload_length,
                                size_t fragment_payload_capacity,
                                uint8_t fragment_index, uint8_t* output,
                                size_t output_capacity) {
  if (payload == nullptr || output == nullptr || payload_length == 0 ||
      payload_length > kMaxMessageSize || fragment_payload_capacity == 0) {
    return 0;
  }
  const size_t count_size =
      (payload_length + fragment_payload_capacity - 1) /
      fragment_payload_capacity;
  if (count_size == 0 || count_size > 255 || fragment_index >= count_size) {
    return 0;
  }
  const size_t offset = fragment_index * fragment_payload_capacity;
  const size_t fragment_length =
      std::min(fragment_payload_capacity, payload_length - offset);
  if (output_capacity < kFrameHeaderSize + fragment_length) return 0;
  output[0] = 'S';
  output[1] = 'G';
  output[2] = 1;
  output[3] = static_cast<uint8_t>(type);
  writeU16(output + 4, message_id);
  output[6] = fragment_index;
  output[7] = static_cast<uint8_t>(count_size);
  writeU16(output + 8, static_cast<uint16_t>(payload_length));
  std::memcpy(output + kFrameHeaderSize, payload + offset, fragment_length);
  return kFrameHeaderSize + fragment_length;
}

void ProtocolCore::sha256(const uint8_t* data, size_t length,
                          uint8_t output[32]) {
  uint32_t state[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                       0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  const uint64_t bit_length = static_cast<uint64_t>(length) * 8;
  const size_t padded_length = ((length + 9 + 63) / 64) * 64;
  std::array<uint8_t, kMaxMessageSize + 128> padded{};
  if (data == nullptr || padded_length > padded.size()) {
    std::memset(output, 0, 32);
    return;
  }
  std::memcpy(padded.data(), data, length);
  padded[length] = 0x80;
  for (size_t index = 0; index < 8; ++index) {
    padded[padded_length - 8 + index] =
        static_cast<uint8_t>(bit_length >> (56 - 8 * index));
  }
  for (size_t offset = 0; offset < padded_length; offset += 64) {
    uint32_t words[64] = {};
    for (size_t index = 0; index < 16; ++index) {
      words[index] = readU32(padded.data() + offset + index * 4);
    }
    for (size_t index = 16; index < 64; ++index) {
      const uint32_t s0 = rotateRight(words[index - 15], 7) ^
                          rotateRight(words[index - 15], 18) ^
                          (words[index - 15] >> 3);
      const uint32_t s1 = rotateRight(words[index - 2], 17) ^
                          rotateRight(words[index - 2], 19) ^
                          (words[index - 2] >> 10);
      words[index] = words[index - 16] + s0 + words[index - 7] + s1;
    }
    uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
    uint32_t e = state[4], f = state[5], g = state[6], h = state[7];
    for (size_t index = 0; index < 64; ++index) {
      const uint32_t s1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^
                          rotateRight(e, 25);
      const uint32_t choose = (e & f) ^ ((~e) & g);
      const uint32_t temp1 = h + s1 + choose + kShaK[index] + words[index];
      const uint32_t s0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^
                          rotateRight(a, 22);
      const uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
      const uint32_t temp2 = s0 + majority;
      h = g;
      g = f;
      f = e;
      e = d + temp1;
      d = c;
      c = b;
      b = a;
      a = temp1 + temp2;
    }
    state[0] += a;
    state[1] += b;
    state[2] += c;
    state[3] += d;
    state[4] += e;
    state[5] += f;
    state[6] += g;
    state[7] += h;
  }
  for (size_t index = 0; index < 8; ++index) {
    writeU32(output + index * 4, state[index]);
  }
}

}  // namespace sgk
