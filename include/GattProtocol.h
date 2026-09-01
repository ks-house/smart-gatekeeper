#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#ifndef ENABLE_HARDWARELESS_RC
#define ENABLE_HARDWARELESS_RC 0
#endif

#ifndef SGK_PRODUCTION_BUILD
#define SGK_PRODUCTION_BUILD 0
#endif

#ifndef SGK_PERSONAL_INSTALLATION_BUILD
#define SGK_PERSONAL_INSTALLATION_BUILD 0
#endif

namespace sgk {

constexpr bool effectiveFeatureEnabled(bool persisted_runtime_value) {
  return (ENABLE_HARDWARELESS_RC != 0) && persisted_runtime_value;
}

// A personal-production image requests the GATT transport on by default. The
// request is still fail-closed in GattServer when the per-Target door identity,
// canonical event identity, CSPRNG, signed ACL, or client proof is unavailable
// or invalid. A persisted false remains an explicit local kill switch.
constexpr bool hardwarelessRuntimeDefaultEnabled() {
  return (ENABLE_HARDWARELESS_RC != 0) && (SGK_PRODUCTION_BUILD != 0) &&
         (SGK_PERSONAL_INSTALLATION_BUILD != 0);
}

// A persisted false written by an older compile-OFF image is ambiguous when a
// Target first moves to the reviewed personal-production profile. Initialize
// the runtime request exactly once, and only after provisioning is valid. Once
// migrated, a later persisted false remains the local kill switch.
constexpr bool shouldInitializePersonalHardwarelessState(
    bool personal_runtime_default, bool migration_complete,
    bool provisioning_valid) {
  return personal_runtime_default && !migration_complete &&
         provisioning_valid;
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
constexpr uint32_t kIndicationConfirmationTimeoutMs = 1200;
constexpr size_t kPendingWriteCapacity = 4;
constexpr size_t kAdapterFrameCapacity = 512;
constexpr size_t kAccessEventCredentialRefCapacity = 32;
constexpr size_t kAccessEvidenceKeyIdCapacity = 5;
constexpr size_t kAccessEvidenceTagSize = 16;
constexpr size_t kAccessEvidenceTagHexCapacity = 33;
constexpr size_t kAccessEventMacInputCapacity = 512;
constexpr size_t kAccessStatusMacInputCapacity = 384;

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

enum class LocalAccessAction : uint8_t {
  kArmForSensor = 1,
  kOpenImmediately = 2,
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
  kAccessArmed,
  kAccessSensorDetected,
  kAccessRelayOn,
  kAccessRelayOff,
  kAccessSessionCompleted,
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
  kArmAccepted,
  kSensorThresholdMet,
  kRelayActivated,
  kRelayHoldComplete,
  kRelayFailsafeCutoff,
  kAccessGranted,
  kArmTimeout,
  kSessionSuperseded,
};

struct Event {
  EventCode code;
  EventReason reason;
  ResultReason transport_reason;
  uint64_t monotonic_ms;
  std::array<uint8_t, 16> session_id;
  std::array<uint8_t, 16> boot_id;
  uint64_t sequence;
  bool has_causation;
  uint64_t causation_sequence;
  // Verified credential identity is volatile only. It may be retained by the
  // local lifecycle bridge long enough to derive a pseudonymous event
  // reference, but it must never be copied into JSON, logs, or durable NVS.
  std::array<uint8_t, 16> credential_id{};
};

// Only these post-proof lifecycle codes may expose the session-scoped
// pseudonym. In particular, a commit failure emits ACCESS_PROOF_REJECTED after
// proof verification, but that rejection must remain actor-ref free.
bool accessEventCodeAllowsCredentialRef(EventCode code);

// Derives the bounded, pseudonymous identity stored on canonical access
// events. The session UUID is normalized to RFC 4122 UUIDv4 before HMAC input
// construction so the textual session_id and credential reference bind to the
// same identity. key_id is deliberately limited to four lowercase alphanumeric
// characters so c_<keyid>_<24hex> including NUL fits the 32-byte v2 overlay.
bool deriveAccessEventCredentialRef(
    const std::array<uint8_t, 32>& key, const char* key_id,
    const std::array<uint8_t, 16>& door_id,
    const std::array<uint8_t, 16>& session_id,
    const std::array<uint8_t, 16>& credential_id,
    char output[kAccessEventCredentialRefCapacity]);

// The access-evidence key is deliberately independent from MQTT, API, ACL,
// command-signing and OTA credentials. Both the Target event and heartbeat
// contracts use fixed, length-prefixed binary inputs; JSON serialization is
// never part of either MAC.
bool parseAccessEvidenceProvisioning(
    const char* key_hex, const char* key_id,
    std::array<uint8_t, 32>* key_out,
    char key_id_out[kAccessEvidenceKeyIdCapacity]);

struct AccessEventMacInput {
  const char* key_id = nullptr;
  const char* topic_target_id = nullptr;
  std::array<uint8_t, 16> door_id{};
  const char* source_instance_id = nullptr;
  std::array<uint8_t, 16> source_boot_id{};
  uint64_t source_boot_count = 0;
  std::array<uint8_t, 16> event_id{};
  std::array<uint8_t, 16> session_id{};
  uint64_t sequence = 0;
  uint32_t attempt = 0;
  const char* event_code = nullptr;
  const char* stage = nullptr;
  const char* outcome = nullptr;
  const char* reason_code = nullptr;
  bool has_causation = false;
  std::array<uint8_t, 16> causation_event_id{};
  uint64_t monotonic_ms = 0;
  const char* credential_ref = nullptr;
  bool has_distance_mm = false;
  uint32_t distance_mm = 0;
  bool has_duration_ms = false;
  uint64_t duration_ms = 0;
  bool has_relay_hold_ms = false;
  uint32_t relay_hold_ms = 0;
};

struct AccessStatusMacInput {
  const char* key_id = nullptr;
  const char* topic_target_id = nullptr;
  std::array<uint8_t, 16> door_id{};
  std::array<uint8_t, 16> source_boot_id{};
  uint64_t source_boot_count = 0;
  uint64_t access_revision = 0;
  const char* state = nullptr;
  bool has_last_terminal = false;
  std::array<uint8_t, 16> last_terminal_session_id{};
  uint64_t last_terminal_event_sequence = 0;
  const char* last_terminal_event_code = nullptr;
  const char* last_terminal_reason_code = nullptr;
  const char* last_terminal_credential_ref = nullptr;
  uint16_t last_terminal_phase_mask = 0;
  bool relay_commanded_on = false;
  uint8_t relay_pin_level = 0;
};

bool buildAccessEventMacInput(const AccessEventMacInput& input,
                              uint8_t* output, size_t capacity,
                              size_t* written);
bool buildAccessStatusMacInput(const AccessStatusMacInput& input,
                               uint8_t* output, size_t capacity,
                               size_t* written);
bool deriveAccessEventMac(
    const std::array<uint8_t, 32>& key, const AccessEventMacInput& input,
    uint8_t output[kAccessEvidenceTagSize]);
bool deriveAccessStatusMac(
    const std::array<uint8_t, 32>& key, const AccessStatusMacInput& input,
    uint8_t output[kAccessEvidenceTagSize]);

class EventSink {
 public:
  virtual ~EventSink() = default;
  virtual void emit(const Event& event) = 0;
};

// Continues the canonical Target event chain after a locally verified GATT
// proof. Non-GATT/manual paths cannot activate it, and terminal emission
// clears the retained session context.
class LocalGattLifecycleBridge final : public EventSink {
 public:
  explicit LocalGattLifecycleBridge(EventSink* downstream = nullptr)
      : downstream_(downstream) {}

  void setDownstream(EventSink* downstream) { downstream_ = downstream; }
  void emit(const Event& event) override;
  bool hasVerifiedSession() const { return verified_session_active_; }
  uint64_t lastSequence() const { return sequence_high_water_; }
  bool emitArmed(uint64_t now_ms);
  bool emitSensorDetected(uint64_t now_ms);
  bool emitRelayOn(uint64_t now_ms);
  bool emitRelayOff(uint64_t now_ms, bool failsafe);
  bool emitCompleted(uint64_t now_ms);
  bool emitTerminated(uint64_t now_ms, EventReason reason);

 private:
  EventSink* downstream_ = nullptr;
  bool verified_session_active_ = false;
  std::array<uint8_t, 16> session_id_{};
  std::array<uint8_t, 16> boot_id_{};
  std::array<uint8_t, 16> credential_id_{};
  // Every ProtocolCore event advances this process-wide source-position
  // ceiling, even when it belongs to an unverified interleaved session.
  uint64_t sequence_high_water_ = 0;
  // Causation remains scoped to the currently verified session. An unrelated
  // session may advance the global ceiling but can never become its parent.
  uint64_t verified_causation_sequence_ = 0;

  bool emitLifecycle(EventCode code, EventReason reason,
                     ResultReason transport_reason, uint64_t now_ms,
                     bool terminal);
  void clearVerifiedSession();
};

// Accumulates only post-proof lifecycle evidence for one verified session.
// Unverified GATT traffic is still emitted as canonical diagnostics, but it
// cannot reset another session's phase mask or publish a terminal summary.
class VerifiedAccessPhaseTracker final {
 public:
  static constexpr uint16_t kProofVerified = 0x0001;
  static constexpr uint16_t kArmed = 0x0002;
  static constexpr uint16_t kSensorDetected = 0x0004;
  static constexpr uint16_t kRelayOn = 0x0008;
  static constexpr uint16_t kRelayOff = 0x0010;
  static constexpr uint16_t kRelayFailsafe = 0x0020;

  // Returns true only when event is a terminal for the currently verified
  // session. terminal_phase_mask is cleared for every non-terminal/unmatched
  // event and receives the final mask before the verified session is cleared.
  bool observe(const Event& event, uint16_t* terminal_phase_mask = nullptr);
  bool hasVerifiedSession() const { return verified_session_active_; }
  uint16_t phaseMask() const { return phase_mask_; }

 private:
  bool verified_session_active_ = false;
  std::array<uint8_t, 16> session_id_{};
  uint16_t phase_mask_ = 0;

  void clear();
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

// Required control-plane binding between authenticated protocol completion and
// the physical Target FSM. A successful proof must never produce RESULT OK
// unless the requested action was accepted by this gate.
class AuthControlGate {
 public:
  virtual ~AuthControlGate() = default;
  virtual bool beginAuth(uint32_t now_ms) = 0;
  virtual bool commitAuthorizedAction(LocalAccessAction action,
                                      uint32_t now_ms) = 0;
  virtual void abortAuth(uint32_t now_ms) = 0;
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
  uint16_t connection_handle = 0;
  uint64_t connection_generation = 0;
  size_t length = 0;
  std::array<uint8_t, kMaxMessageSize> bytes{};
};

struct ConnectionToken {
  uint16_t handle = 0;
  uint64_t generation = 0;

  bool valid() const { return generation != 0; }
  bool operator==(const ConnectionToken& other) const {
    return handle == other.handle && generation == other.generation;
  }
  bool operator!=(const ConnectionToken& other) const {
    return !(*this == other);
  }
};

struct IndicationToken {
  ConnectionToken owner{};
  uint64_t output_generation = 0;
  uint8_t fragment_index = 0;

  bool valid() const { return owner.valid() && output_generation != 0; }
  bool operator==(const IndicationToken& other) const {
    return owner == other.owner &&
           output_generation == other.output_generation &&
           fragment_index == other.fragment_index;
  }
  bool operator!=(const IndicationToken& other) const {
    return !(*this == other);
  }
};

struct PendingWrite {
  ConnectionToken owner{};
  MessageType type = MessageType::kError;
  size_t length = 0;
  std::array<uint8_t, kAdapterFrameCapacity> bytes{};
};

enum class IndicationResult : uint8_t {
  kIgnored,
  kFragmentConfirmed,
  kMessageConfirmed,
  kAborted,
};

// Shared by the ESP32 BLE callbacks and native host tests. It binds callback
// work to an accepted connection generation, output generation, and fragment index.
class AdapterState {
 public:
  bool acceptConnection(const ConnectionToken& owner);
  void disconnect(uint16_t handle);
  void clear();
  ConnectionToken activeOwner() const { return active_owner_; }
  uint64_t outputGeneration() const { return output_generation_; }
  bool ownerForHandle(uint16_t handle, ConnectionToken* owner) const;

  bool setSubscribed(uint16_t handle, MessageType type, bool subscribed);
  bool isSubscribed(const ConnectionToken& owner, MessageType type) const;

  bool enqueueWrite(uint16_t handle, MessageType type, const uint8_t* value,
                    size_t length);
  // Overflow is fail-closed before queued writes: consuming it discards the
  // complete queue and returns the affected accepted connection generation.
  bool consumeOverflow(ConnectionToken* owner);
  bool popWrite(PendingWrite* pending);
  void clearWrites();

  bool stageOutput(const OutputMessage& output);
  bool beginNextIndication(uint16_t mtu, uint32_t now_ms, uint8_t* frame,
                           size_t capacity, size_t* written,
                           MessageType* type, IndicationToken* token);
  bool beginNextIndication(uint16_t mtu, uint32_t now_ms, uint8_t* frame,
                           size_t capacity, size_t* written,
                           MessageType* type, ConnectionToken* owner);
  IndicationResult confirmIndication(const IndicationToken& token,
                                     MessageType type, bool success);
  bool confirmationTimedOut(uint32_t now_ms) const;
  void abortOutput();
  bool outputActive() const { return output_active_; }
  bool confirmationPending() const { return confirmation_pending_; }

 private:
  static uint8_t subscriptionBit(MessageType type);
  static bool reached(uint32_t now_ms, uint32_t deadline_ms);

  ConnectionToken active_owner_{};
  uint8_t subscriptions_ = 0;
  std::array<PendingWrite, kPendingWriteCapacity> pending_writes_{};
  size_t pending_head_ = 0;
  size_t pending_count_ = 0;
  bool pending_overflow_ = false;
  ConnectionToken overflow_owner_{};

  OutputMessage output_{};
  uint64_t output_generation_ = 0;
  bool output_active_ = false;
  bool confirmation_pending_ = false;
  size_t fragment_payload_capacity_ = 0;
  size_t fragment_count_ = 0;
  size_t fragment_index_ = 0;
  uint32_t confirmation_deadline_ms_ = 0;
};

class ProtocolCore {
 public:
  ProtocolCore(RandomSource& random, ProofVerifier& verifier,
               const std::array<uint8_t, 16>& door_id,
               EventSink* event_sink = nullptr,
               AuthControlGate* auth_control_gate = nullptr);

  bool initialize();
  void setEnabled(bool enabled);
  bool enabled() const { return enabled_ && rng_ready_; }
  void setOtaBusy(bool busy, uint32_t now_ms);
  bool otaBusy() const { return ota_busy_; }

  bool connect(uint16_t connection_id, uint32_t now_ms,
               ConnectionToken* accepted_owner = nullptr);
  void disconnect(const ConnectionToken& owner, uint32_t now_ms);
  bool connected() const { return connection_active_; }
  uint16_t connectionId() const { return connection_id_; }
  ConnectionToken connectionOwner() const {
    return {connection_id_, connection_generation_};
  }

  bool receiveFrame(MessageType expected_type, const ConnectionToken& owner,
                    const uint8_t* frame, size_t frame_length,
                    uint32_t now_ms);
  bool popOutput(OutputMessage* output);
  bool hasOutput() const { return output_count_ != 0; }
  void tick(uint32_t now_ms);
  void resetSession();
  void abortTransport(const ConnectionToken& owner, ResultReason reason,
                      uint32_t now_ms);

  SessionState state() const { return state_; }
  const std::array<uint8_t, 16>& bootId() const { return boot_id_; }
  const std::array<uint8_t, 16>& sessionId() const { return session_id_; }
  uint32_t failedAttempts() const { return failed_attempts_; }
  void advanceEventSequence(uint64_t used_sequence) {
    if (used_sequence > event_sequence_) event_sequence_ = used_sequence;
  }

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
  AuthControlGate* auth_control_gate_;
  bool enabled_ = false;
  bool rng_ready_ = false;
  bool ota_busy_ = false;
  bool connection_active_ = false;
  uint16_t connection_id_ = 0;
  uint64_t connection_generation_ = 0;
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
  std::array<uint8_t, 16> door_id_{};
  bool door_id_ready_ = false;
  std::array<uint8_t, 32> negotiation_hash_{};
  std::array<uint8_t, kChallengeSize> challenge_{};
  Reassembly reassembly_{};
  std::array<OutputMessage, 4> outputs_{};
  size_t output_head_ = 0;
  size_t output_count_ = 0;
  uint64_t event_sequence_ = 0;
  uint64_t event_last_causation_sequence_ = 0;
  uint64_t event_monotonic_high_ = 0;
  uint32_t event_last_now_ms_ = 0;
  bool event_time_initialized_ = false;
  bool auth_control_active_ = false;

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
  void resetSessionPreservingOutputs();
  void abortAuthControl(uint32_t now_ms);
  void emit(EventCode code, ResultReason reason, uint32_t now_ms,
            const std::array<uint8_t, 16>* credential_id = nullptr);
  static EventReason eventReason(EventCode code, ResultReason reason);
};

}  // namespace sgk
