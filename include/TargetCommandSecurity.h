#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace sgk {

constexpr size_t kCommandReplayEntries = 16;

enum class CommandAction : uint8_t {
  kInvalid = 0,
  kArm,
  kManualRemote,
  kSetTxPower,
  kSetDistanceThreshold,
  kSetDuration,
  kSetRelayCooldown,
  kOtaCheck,
  kReboot,
};

enum class CommandResult : uint8_t {
  kAccepted = 0,
  kDuplicateCompleted,
  kDuplicateUncertain,
  kMalformed,
  kIdentityMismatch,
  kBootMismatch,
  kClockUntrusted,
  kNotYetValid,
  kExpired,
  kTtlTooLong,
  kKeyMismatch,
  kBadSignature,
  kReplayStorageFailure,
  kEffectRejected,
};

struct SignedCommandEnvelope {
  uint8_t schema_version = 0;
  char target_id[49]{};
  char tenant_id[33]{};
  char door_id[33]{};
  char boot_id[33]{};
  CommandAction action = CommandAction::kInvalid;
  char session_id[49]{};
  char nonce[49]{};
  uint64_t issued_at = 0;
  uint64_t expires_at = 0;
  uint32_t key_id = 0;
  int64_t value = 0;
  std::array<uint8_t, 64> signature{};
};

struct CommandReplayEntry {
  char nonce[49]{};
  char session_id[49]{};
  std::array<uint8_t, 32> digest{};
  uint64_t issued_at = 0;
  uint8_t state = 0;  // 1=accepted before effect, 2=effect completed.
};

struct CommandReplayLedger {
  uint32_t magic = 0;
  uint16_t version = 0;
  uint16_t next_index = 0;
  uint64_t generation = 0;
  uint64_t retired_issued_at_floor = 0;
  std::array<CommandReplayEntry, kCommandReplayEntries> entries{};
  uint32_t crc32 = 0;
};

class CommandReplayStorage {
 public:
  virtual ~CommandReplayStorage() = default;
  virtual bool readLedger(uint8_t slot, CommandReplayLedger* ledger) = 0;
  virtual bool writeLedger(uint8_t slot, const CommandReplayLedger& ledger) = 0;
};

class CommandSignatureVerifier {
 public:
  virtual ~CommandSignatureVerifier() = default;
  virtual bool verify(uint32_t key_id,
                      const std::array<uint8_t, 32>& digest,
                      const std::array<uint8_t, 64>& signature) = 0;
};

class TargetCommandSecurity {
 public:
  TargetCommandSecurity(CommandReplayStorage* storage,
                        CommandSignatureVerifier* verifier);

  bool begin(const char* target_id, const char* tenant_id,
             const char* door_id, const char* boot_id,
             uint32_t expected_key_id);
  CommandResult authorize(const SignedCommandEnvelope& envelope,
                          uint64_t trusted_unix_seconds,
                          bool clock_trusted);
  bool markCompleted(const SignedCommandEnvelope& envelope);

  static const char* actionName(CommandAction action);
  static CommandAction parseAction(const char* value);
  static bool canonicalDigest(const SignedCommandEnvelope& envelope,
                              std::array<uint8_t, 32>* digest);

 private:
  bool loadLedger();
  bool persistLedger();
  static bool validLedger(const CommandReplayLedger& ledger);
  static uint32_t ledgerCrc(const CommandReplayLedger& ledger);
  static bool safeToken(const char* value, size_t capacity, bool allow_empty);

  CommandReplayStorage* storage_ = nullptr;
  CommandSignatureVerifier* verifier_ = nullptr;
  CommandReplayLedger ledger_{};
  uint8_t active_slot_ = 0;
  char target_id_[49]{};
  char tenant_id_[33]{};
  char door_id_[33]{};
  char boot_id_[33]{};
  uint32_t expected_key_id_ = 0;
  bool ready_ = false;
};

}  // namespace sgk
