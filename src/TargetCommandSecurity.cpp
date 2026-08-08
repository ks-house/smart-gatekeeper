#include "TargetCommandSecurity.h"

#include <cstdio>
#include <cstring>

#include "GattProtocol.h"

namespace sgk {
namespace {

constexpr uint32_t kLedgerMagic = 0x53474b43;  // SGKC
constexpr uint16_t kLedgerVersion = 1;
constexpr uint64_t kMinimumTrustedUnixSeconds = 1704067200ULL;  // 2024-01-01
constexpr uint64_t kMaximumCommandTtlSeconds = 120;
constexpr uint64_t kMaximumFutureSkewSeconds = 30;

bool same(const char* left, const char* right) {
  return left != nullptr && right != nullptr && std::strcmp(left, right) == 0;
}

void copyToken(char* destination, size_t capacity, const char* source) {
  if (capacity == 0) return;
  std::snprintf(destination, capacity, "%s", source == nullptr ? "" : source);
}

}  // namespace

TargetCommandSecurity::TargetCommandSecurity(CommandReplayStorage* storage,
                                             CommandSignatureVerifier* verifier)
    : storage_(storage), verifier_(verifier) {}

bool TargetCommandSecurity::begin(const char* target_id, const char* tenant_id,
                                  const char* door_id, const char* boot_id,
                                  uint32_t expected_key_id) {
  ready_ = false;
  if (!safeToken(target_id, sizeof(target_id_), false) ||
      !safeToken(tenant_id, sizeof(tenant_id_), false) ||
      !safeToken(door_id, sizeof(door_id_), false) ||
      !safeToken(boot_id, sizeof(boot_id_), false) || expected_key_id == 0 ||
      storage_ == nullptr || verifier_ == nullptr) {
    return false;
  }
  copyToken(target_id_, sizeof(target_id_), target_id);
  copyToken(tenant_id_, sizeof(tenant_id_), tenant_id);
  copyToken(door_id_, sizeof(door_id_), door_id);
  copyToken(boot_id_, sizeof(boot_id_), boot_id);
  expected_key_id_ = expected_key_id;
  ready_ = loadLedger();
  return ready_;
}

CommandResult TargetCommandSecurity::authorize(
    const SignedCommandEnvelope& envelope, uint64_t trusted_unix_seconds,
    bool clock_trusted) {
  std::array<uint8_t, 32> digest{};
  if (!ready_ || envelope.schema_version != 1 ||
      envelope.action == CommandAction::kInvalid ||
      !safeToken(envelope.target_id, sizeof(envelope.target_id), false) ||
      !safeToken(envelope.tenant_id, sizeof(envelope.tenant_id), false) ||
      !safeToken(envelope.door_id, sizeof(envelope.door_id), false) ||
      !safeToken(envelope.boot_id, sizeof(envelope.boot_id), false) ||
      !safeToken(envelope.session_id, sizeof(envelope.session_id), false) ||
      !safeToken(envelope.nonce, sizeof(envelope.nonce), false) ||
      !canonicalDigest(envelope, &digest)) {
    return CommandResult::kMalformed;
  }
  if (!same(envelope.target_id, target_id_) ||
      !same(envelope.tenant_id, tenant_id_) ||
      !same(envelope.door_id, door_id_)) {
    return CommandResult::kIdentityMismatch;
  }
  if (!same(envelope.boot_id, boot_id_)) return CommandResult::kBootMismatch;
  if (!clock_trusted || trusted_unix_seconds < kMinimumTrustedUnixSeconds) {
    return CommandResult::kClockUntrusted;
  }
  if (envelope.issued_at > trusted_unix_seconds + kMaximumFutureSkewSeconds) {
    return CommandResult::kNotYetValid;
  }
  if (envelope.expires_at < trusted_unix_seconds ||
      envelope.expires_at < envelope.issued_at) {
    return CommandResult::kExpired;
  }
  if (envelope.expires_at - envelope.issued_at > kMaximumCommandTtlSeconds) {
    return CommandResult::kTtlTooLong;
  }
  if (envelope.key_id != expected_key_id_) return CommandResult::kKeyMismatch;
  if (!verifier_->verify(envelope.key_id, digest, envelope.signature)) {
    return CommandResult::kBadSignature;
  }

  for (const auto& entry : ledger_.entries) {
    if (entry.state == 0 || !same(entry.nonce, envelope.nonce)) continue;
    if (!same(entry.session_id, envelope.session_id) || entry.digest != digest) {
      return CommandResult::kDuplicateUncertain;
    }
    return entry.state == 2 ? CommandResult::kDuplicateCompleted
                            : CommandResult::kDuplicateUncertain;
  }
  if (ledger_.retired_issued_at_floor != 0 &&
      envelope.issued_at <= ledger_.retired_issued_at_floor) {
    return CommandResult::kExpired;
  }

  const CommandReplayLedger before = ledger_;
  CommandReplayEntry& entry = ledger_.entries[ledger_.next_index];
  if (entry.state != 0 &&
      entry.issued_at > ledger_.retired_issued_at_floor) {
    ledger_.retired_issued_at_floor = entry.issued_at;
  }
  entry = CommandReplayEntry{};
  copyToken(entry.nonce, sizeof(entry.nonce), envelope.nonce);
  copyToken(entry.session_id, sizeof(entry.session_id), envelope.session_id);
  entry.digest = digest;
  entry.issued_at = envelope.issued_at;
  entry.state = 1;
  ledger_.next_index = static_cast<uint16_t>(
      (ledger_.next_index + 1) % ledger_.entries.size());
  if (!persistLedger()) {
    ledger_ = before;
    return CommandResult::kReplayStorageFailure;
  }
  return CommandResult::kAccepted;
}

bool TargetCommandSecurity::markCompleted(
    const SignedCommandEnvelope& envelope) {
  if (!ready_) return false;
  std::array<uint8_t, 32> digest{};
  if (!canonicalDigest(envelope, &digest)) return false;
  for (auto& entry : ledger_.entries) {
    if (entry.state != 0 && same(entry.nonce, envelope.nonce) &&
        same(entry.session_id, envelope.session_id) && entry.digest == digest) {
      if (entry.state == 2) return true;
      const CommandReplayLedger before = ledger_;
      entry.state = 2;
      if (persistLedger()) return true;
      ledger_ = before;
      return false;
    }
  }
  return false;
}

const char* TargetCommandSecurity::actionName(CommandAction action) {
  switch (action) {
    case CommandAction::kArm: return "arm";
    case CommandAction::kManualRemote: return "manual_remote";
    case CommandAction::kSetTxPower: return "set_tx_power";
    case CommandAction::kSetDistanceThreshold: return "set_distance_threshold";
    case CommandAction::kSetDuration: return "set_duration";
    case CommandAction::kSetRelayCooldown: return "set_relay_cooldown";
    case CommandAction::kOtaCheck: return "ota_check";
    case CommandAction::kReboot: return "reboot";
    default: return "invalid";
  }
}

CommandAction TargetCommandSecurity::parseAction(const char* value) {
  if (same(value, "arm")) return CommandAction::kArm;
  if (same(value, "manual_remote")) return CommandAction::kManualRemote;
  if (same(value, "set_tx_power")) return CommandAction::kSetTxPower;
  if (same(value, "set_distance_threshold")) {
    return CommandAction::kSetDistanceThreshold;
  }
  if (same(value, "set_duration")) return CommandAction::kSetDuration;
  if (same(value, "set_relay_cooldown")) {
    return CommandAction::kSetRelayCooldown;
  }
  if (same(value, "ota_check")) return CommandAction::kOtaCheck;
  if (same(value, "reboot")) return CommandAction::kReboot;
  return CommandAction::kInvalid;
}

bool TargetCommandSecurity::canonicalDigest(
    const SignedCommandEnvelope& envelope,
    std::array<uint8_t, 32>* digest) {
  if (digest == nullptr) return false;
  char canonical[640]{};
  const int written = std::snprintf(
      canonical, sizeof(canonical),
      "sgk-command-v1\naction=%s\nboot_id=%s\ndoor_id=%s\nexpires_at=%llu\n"
      "issued_at=%llu\nkey_id=%lu\nnonce=%s\nschema_version=%u\n"
      "session_id=%s\ntarget_id=%s\ntenant_id=%s\nvalue=%lld\n",
      actionName(envelope.action), envelope.boot_id, envelope.door_id,
      static_cast<unsigned long long>(envelope.expires_at),
      static_cast<unsigned long long>(envelope.issued_at),
      static_cast<unsigned long>(envelope.key_id), envelope.nonce,
      static_cast<unsigned int>(envelope.schema_version), envelope.session_id,
      envelope.target_id, envelope.tenant_id,
      static_cast<long long>(envelope.value));
  if (written <= 0 || static_cast<size_t>(written) >= sizeof(canonical)) {
    digest->fill(0);
    return false;
  }
  ProtocolCore::sha256(reinterpret_cast<const uint8_t*>(canonical),
                       static_cast<size_t>(written), digest->data());
  return true;
}

bool TargetCommandSecurity::loadLedger() {
  CommandReplayLedger slots[2]{};
  const bool valid0 = storage_->readLedger(0, &slots[0]) && validLedger(slots[0]);
  const bool valid1 = storage_->readLedger(1, &slots[1]) && validLedger(slots[1]);
  if (!valid0 && !valid1) {
    ledger_ = CommandReplayLedger{};
    ledger_.magic = kLedgerMagic;
    ledger_.version = kLedgerVersion;
    active_slot_ = 0;
    return persistLedger();
  }
  active_slot_ = valid1 && (!valid0 || slots[1].generation > slots[0].generation)
                     ? 1
                     : 0;
  ledger_ = slots[active_slot_];
  return true;
}

bool TargetCommandSecurity::persistLedger() {
  ledger_.magic = kLedgerMagic;
  ledger_.version = kLedgerVersion;
  ledger_.generation++;
  ledger_.crc32 = ledgerCrc(ledger_);
  const uint8_t candidate_slot = active_slot_ == 0 ? 1 : 0;
  if (!storage_->writeLedger(candidate_slot, ledger_)) return false;
  CommandReplayLedger verified{};
  if (!storage_->readLedger(candidate_slot, &verified) ||
      !validLedger(verified) || verified.generation != ledger_.generation) {
    return false;
  }
  active_slot_ = candidate_slot;
  return true;
}

bool TargetCommandSecurity::validLedger(const CommandReplayLedger& ledger) {
  return ledger.magic == kLedgerMagic && ledger.version == kLedgerVersion &&
         ledger.next_index < ledger.entries.size() &&
         ledger.crc32 == ledgerCrc(ledger);
}

uint32_t TargetCommandSecurity::ledgerCrc(const CommandReplayLedger& ledger) {
  CommandReplayLedger copy = ledger;
  copy.crc32 = 0;
  const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&copy);
  uint32_t crc = 0xffffffffU;
  for (size_t index = 0; index < sizeof(copy); ++index) {
    crc ^= bytes[index];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
  }
  return ~crc;
}

bool TargetCommandSecurity::safeToken(const char* value, size_t capacity,
                                      bool allow_empty) {
  if (value == nullptr || capacity == 0) return false;
  size_t length = 0;
  while (length < capacity && value[length] != '\0') ++length;
  if (length >= capacity || (!allow_empty && length == 0)) return false;
  for (size_t index = 0; index < length; ++index) {
    const char c = value[index];
    const bool valid = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                       (c >= '0' && c <= '9') || c == '-' || c == '_' ||
                       c == '.' || c == ':';
    if (!valid) return false;
  }
  return true;
}

}  // namespace sgk
