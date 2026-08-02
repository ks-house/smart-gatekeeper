#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#ifndef ENABLE_HARDWARELESS_RC
#define ENABLE_HARDWARELESS_RC 0
#endif

namespace sgk {

constexpr bool effectiveFeatureEnabled(bool persisted_runtime_value) {
  return (ENABLE_HARDWARELESS_RC != 0) && persisted_runtime_value;
}

constexpr size_t kFrameHeaderSize = 10;
constexpr size_t kMaxMessageSize = 2048;
constexpr size_t kClientHelloSize = 16;
constexpr size_t kTargetHelloSize = 20;
constexpr size_t kChallengeSize = 138;
constexpr size_t kProofSize = 103;
constexpr size_t kResultSize = 32;
constexpr uint32_t kAssemblyTimeoutMs = 2000;
constexpr uint32_t kChallengeLifetimeMs = 5000;

constexpr std::array<uint8_t, 18> kIBeaconFilterPrefix = {{
    0x02, 0x15, 0xA1, 0xB2, 0xC3, 0xD4, 0xE5, 0xF6, 0x78,
    0x90, 0xAB, 0xCD, 0xEF, 0x12, 0x34, 0x56, 0x78, 0x90}};

enum class MessageType : uint8_t {
  kClientHello = 0x01,
  kTargetHello = 0x02,
  kChallenge = 0x10,
  kProof = 0x11,
  kResult = 0x12,
  kError = 0x7f,
};

enum class ResultReason : uint16_t {
  kOk = 0,
  kUnsupportedVersion = 1,
  kMalformed = 2,
  kSessionInvalid = 3,
  kExpiredOrReplay = 4,
  kAclUnavailable = 5,
  kCredentialDenied = 6,
  kProofInvalid = 7,
  kBusy = 8,
  kRateLimited = 9,
  kInternalFailClosed = 10,
};

enum class SessionState : uint8_t {
  kIdle,
  kHelloReceived,
  kChallengeIssued,
  kVerifying,
  kConsumed,
  kCompleted,
};

enum class EventCode : uint8_t {
  kAccessGattConnected,
  kAccessGattFailed,
  kAccessProofRequested,
  kAccessProofVerified,
  kAccessProofRejected,
  kAccessSessionTerminated,
};

enum class EventReason : uint8_t {
  kGattConnected,
  kGattDisconnected,
  kProofChallengeIssued,
  kProofValid,
  kMalformedProof,
  kProtocolIncompatible,
  kProofExpired,
  kAclNotFound,
  kCredentialInactive,
  kSignatureInvalid,
  kOtaBusy,
  kSessionTimeout,
  kInternalError,
};

struct Event {
  EventCode code;
  EventReason reason;
  ResultReason transport_reason;
  uint32_t monotonic_ms;
};

class EventSink {
 public:
  virtual ~EventSink() = default;
  virtual void emit(const Event& event) = 0;
};

class RandomSource {
 public:
  virtual ~RandomSource() = default;
  virtual bool fill(uint8_t* output, size_t length) = 0;
};

struct VerifyRequest {
  uint16_t protocol_version;
  std::array<uint8_t, 16> credential_id;
  uint8_t action;
  uint32_t client_capabilities;
  std::array<uint8_t, 61> signing_input;
  std::array<uint8_t, 64> signature_raw64;
};

struct VerifyResult {
  ResultReason reason;
  uint64_t active_acl_version;
};

class ProofVerifier {
 public:
  virtual ~ProofVerifier() = default;
  virtual uint64_t activeAclVersion() const { return 0; }
  virtual VerifyResult verify(const VerifyRequest& request) = 0;
};

// Production default until Issue #20 installs signed ACL storage and P-256
// verification. It intentionally cannot authorize any credential.
class FailClosedProofVerifier final : public ProofVerifier {
 public:
  VerifyResult verify(const VerifyRequest&) override {
    return {ResultReason::kAclUnavailable, 0};
  }
};

struct OutputMessage {
  MessageType type = MessageType::kError;
  uint16_t message_id = 0;
  size_t length = 0;
  std::array<uint8_t, kMaxMessageSize> bytes{};
};

class ProtocolCore {
 public:
  ProtocolCore(RandomSource& random, ProofVerifier& verifier,
               EventSink* event_sink = nullptr);

  bool initialize();
  void setEnabled(bool enabled);
  bool enabled() const { return enabled_ && rng_ready_; }
  void setOtaBusy(bool busy, uint32_t now_ms);
  bool otaBusy() const { return ota_busy_; }

  bool connect(uint16_t connection_id, uint32_t now_ms);
  void disconnect(uint16_t connection_id, uint32_t now_ms);
  bool connected() const { return connection_active_; }
  uint16_t connectionId() const { return connection_id_; }

  bool receiveFrame(MessageType expected_type, uint16_t connection_id,
                    const uint8_t* frame, size_t frame_length,
                    uint32_t now_ms);
  bool popOutput(OutputMessage* output);
  void tick(uint32_t now_ms);
  void resetSession();

  SessionState state() const { return state_; }
  const std::array<uint8_t, 16>& bootId() const { return boot_id_; }
  const std::array<uint8_t, 16>& sessionId() const { return session_id_; }
  uint32_t failedAttempts() const { return failed_attempts_; }

  static bool copyOutput(const OutputMessage& source, uint8_t* destination,
                         size_t capacity, size_t* written);
  static size_t buildFrame(MessageType type, uint16_t message_id,
                           const uint8_t* payload, size_t payload_length,
                           size_t fragment_payload_capacity,
                           uint8_t fragment_index, uint8_t* output,
                           size_t output_capacity);
  static void sha256(const uint8_t* data, size_t length, uint8_t output[32]);

 private:
  struct Reassembly {
    bool active = false;
    MessageType type = MessageType::kError;
    uint16_t message_id = 0;
    uint8_t fragment_count = 0;
    uint8_t next_index = 0;
    uint16_t total_length = 0;
    size_t length = 0;
    uint32_t started_ms = 0;
    size_t last_frame_length = 0;
    std::array<uint8_t, 512> last_frame{};
    std::array<uint8_t, kMaxMessageSize> bytes{};
  };

  RandomSource& random_;
  ProofVerifier& verifier_;
  EventSink* event_sink_;
  bool enabled_ = false;
  bool rng_ready_ = false;
  bool ota_busy_ = false;
  bool connection_active_ = false;
  uint16_t connection_id_ = 0;
  SessionState state_ = SessionState::kIdle;
  uint16_t selected_protocol_ = 0;
  uint16_t next_message_id_ = 1;
  uint32_t challenge_deadline_ms_ = 0;
  uint32_t failed_attempts_ = 0;
  uint32_t failure_window_started_ms_ = 0;
  uint32_t backoff_until_ms_ = 0;
  uint64_t active_acl_version_ = 0;
  std::array<uint8_t, 16> boot_id_{};
  std::array<uint8_t, 16> session_id_{};
  std::array<uint8_t, 16> previous_session_id_{};
  std::array<uint8_t, 32> nonce_{};
  std::array<uint8_t, 32> previous_nonce_{};
  std::array<uint8_t, 16> door_id_ = {{
      0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77,
      0x88, 0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF}};
  std::array<uint8_t, 32> negotiation_hash_{};
  std::array<uint8_t, kChallengeSize> challenge_{};
  Reassembly reassembly_{};
  std::array<OutputMessage, 4> outputs_{};
  size_t output_head_ = 0;
  size_t output_count_ = 0;

  static bool reached(uint32_t now_ms, uint32_t deadline_ms);
  static uint16_t readU16(const uint8_t* value);
  static uint32_t readU32(const uint8_t* value);
  static void writeU16(uint8_t* output, uint16_t value);
  static void writeU32(uint8_t* output, uint32_t value);
  static void writeU64(uint8_t* output, uint64_t value);
  static bool allZero(const uint8_t* value, size_t length);
  bool randomUnique(uint8_t* output, size_t length, const uint8_t* previous);
  void clearReassembly();
  bool processMessage(MessageType type, const uint8_t* payload, size_t length,
                      uint32_t now_ms);
  bool processHello(const uint8_t* payload, size_t length, uint32_t now_ms);
  bool processProof(const uint8_t* payload, size_t length, uint32_t now_ms);
  void buildChallenge(uint32_t now_ms);
  void queueTargetHello(uint16_t selected, uint8_t status);
  void queueResult(ResultReason reason, uint32_t retry_after_ms,
                   uint64_t acl_version);
  bool queue(MessageType type, const uint8_t* payload, size_t length);
  void reject(ResultReason reason, uint32_t now_ms, bool count_failure = true);
  void emit(EventCode code, ResultReason reason, uint32_t now_ms);
  static EventReason eventReason(EventCode code, ResultReason reason);
};

}  // namespace sgk
