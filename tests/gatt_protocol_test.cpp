#include "GattProtocol.h"
#include "FlatJsonObjectPolicy.h"
#include "OfflineEventQueue.h"
#include "OtaHealthPolicy.h"
#include "OtaVersionPolicy.h"
#include "TargetAccessFsm.h"
#include "TargetAclManager.h"
#include "TargetProofVerifier.h"
#include "TargetState.h"
#include "TargetCommandSecurity.h"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

int checks = 0;

#define CHECK(condition)                                                    \
  do {                                                                      \
    ++checks;                                                               \
    if (!(condition)) {                                                     \
      std::cerr << "CHECK failed at line " << __LINE__ << ": "             \
                << #condition << std::endl;                                 \
      std::exit(1);                                                         \
    }                                                                       \
  } while (0)

std::vector<uint8_t> hex(const std::string& value) {
  std::vector<uint8_t> output;
  for (size_t index = 0; index < value.size(); index += 2) {
    output.push_back(static_cast<uint8_t>(
        std::stoul(value.substr(index, 2), nullptr, 16)));
  }
  return output;
}

uint16_t u16(const uint8_t* value) {
  return static_cast<uint16_t>((value[0] << 8) | value[1]);
}

class SequenceRandom final : public sgk::RandomSource {
 public:
  std::vector<std::vector<uint8_t>> values;
  size_t index = 0;

  bool fill(uint8_t* output, size_t length) override {
    if (index >= values.size() || values[index].size() != length) return false;
    std::memcpy(output, values[index].data(), length);
    ++index;
    return true;
  }
};

SequenceRandom canonicalRandom(size_t sessions = 8) {
  SequenceRandom random;
  random.values.push_back(
      hex("ffeeddccbbaa99887766554433221100"));
  for (size_t session = 0; session < sessions; ++session) {
    std::vector<uint8_t> session_id =
        session == 0 ? hex("102132435465768798a9bacbdcedfe0f")
                     : std::vector<uint8_t>(16);
    std::vector<uint8_t> nonce(32);
    for (size_t index = 0; session != 0 && index < session_id.size(); ++index) {
      session_id[index] = static_cast<uint8_t>(0x10 + index + session);
    }
    for (size_t index = 0; index < nonce.size(); ++index) {
      nonce[index] = static_cast<uint8_t>(index + session);
    }
    random.values.push_back(session_id);
    random.values.push_back(nonce);
  }
  return random;
}

std::array<uint8_t, 16> canonicalDoor() {
  std::array<uint8_t, 16> door{};
  const auto bytes = hex("00112233445566778899aabbccddeeff");
  std::copy(bytes.begin(), bytes.end(), door.begin());
  return door;
}

class MemoryStorage final : public sgk::TargetAclStorage {
 public:
  bool saveSlot(uint8_t slot, const uint8_t* blob, size_t length) override {
    if (slot > 1 || blob == nullptr || length > sgk::kMaxAclBlobSize) return false;
    slots[slot].assign(blob, blob + length);
    return true;
  }
  bool readSlot(uint8_t slot, uint8_t* buffer, size_t capacity,
                size_t* read_bytes) override {
    if (slot > 1 || buffer == nullptr || read_bytes == nullptr) return false;
    if (slots[slot].empty()) return false;
    size_t copy_len = std::min(capacity, slots[slot].size());
    std::memcpy(buffer, slots[slot].data(), copy_len);
    *read_bytes = copy_len;
    return true;
  }
  bool saveGenerationRecord(uint8_t record_index,
                             const sgk::GenerationRecord& record) override {
    if (record_index > 1) return false;
    gens[record_index] = record;
    gen_valid[record_index] = true;
    return true;
  }
  bool readGenerationRecord(uint8_t record_index,
                             sgk::GenerationRecord* record) override {
    if (record_index > 1 || record == nullptr || !gen_valid[record_index])
      return false;
    *record = gens[record_index];
    return true;
  }
  bool saveHighWatermark(uint64_t version) override {
    high_watermark = version;
    return true;
  }
  uint64_t readHighWatermark() override { return high_watermark; }

  std::vector<uint8_t> slots[2];
  sgk::GenerationRecord gens[2];
  bool gen_valid[2] = {false, false};
  uint64_t high_watermark = 0;
};

class FakeVerifier final : public sgk::ProofVerifier {
 public:
  explicit FakeVerifier(sgk::ResultReason reason, uint64_t version = 42)
      : reason_(reason), version_(version) {}
  uint64_t activeAclVersion() const override { return version_; }
  sgk::VerifyResult verify(const sgk::VerifyRequest& request) override {
    calls++;
    last = request;
    return {reason_, version_};
  }
  sgk::ResultReason reason_;
  uint64_t version_;
  int calls = 0;
  sgk::VerifyRequest last{};
};

class HashSignatureVerifier final : public sgk::ProofVerifier {
 public:
  sgk::VerifyResult verify(const sgk::VerifyRequest& request) override {
    uint8_t digest[32] = {};
    sgk::ProtocolCore::sha256(request.signing_input.data(),
                              request.signing_input.size(), digest);
    const bool valid =
        std::memcmp(request.signature_raw64.data(), digest, 32) == 0 &&
        std::memcmp(request.signature_raw64.data() + 32, digest, 32) == 0;
    return {valid ? sgk::ResultReason::kOk
                  : sgk::ResultReason::kProofInvalid,
            42};
  }
};

class EventRecorder final : public sgk::EventSink {
 public:
  void emit(const sgk::Event& event) override { events.push_back(event); }
  std::vector<sgk::Event> events;
};

class PhaseTrackingEventRecorder final : public sgk::EventSink {
 public:
  void emit(const sgk::Event& event) override {
    uint16_t phase_mask = 0;
    if (phase_tracker.observe(event, &phase_mask)) {
      terminal_count++;
      terminal_phase_mask = phase_mask;
      terminal_session_id = event.session_id;
    }
    events.push_back(event);
  }

  sgk::VerifiedAccessPhaseTracker phase_tracker;
  std::vector<sgk::Event> events;
  size_t terminal_count = 0;
  uint16_t terminal_phase_mask = 0;
  std::array<uint8_t, 16> terminal_session_id{};
};

class FakeAuthControlGate final : public sgk::AuthControlGate {
 public:
  bool beginAuth(uint32_t now_ms) override {
    ++begin_calls;
    last_now_ms = now_ms;
    active = begin_result;
    return begin_result;
  }

  bool commitAuthorizedAction(sgk::LocalAccessAction action,
                              uint32_t now_ms) override {
    ++commit_calls;
    last_action = action;
    last_now_ms = now_ms;
    if (commit_result) active = false;
    return commit_result;
  }

  void abortAuth(uint32_t now_ms) override {
    ++abort_calls;
    active = false;
    last_now_ms = now_ms;
  }

  bool begin_result = true;
  bool commit_result = true;
  bool active = false;
  int begin_calls = 0;
  int commit_calls = 0;
  int abort_calls = 0;
  uint32_t last_now_ms = 0;
  sgk::LocalAccessAction last_action =
      sgk::LocalAccessAction::kArmForSensor;
};

class FsmAuthControlGate final : public sgk::AuthControlGate {
 public:
  FsmAuthControlGate(sgk::TargetAccessFsm* fsm,
                     sgk::LocalGattLifecycleBridge* lifecycle)
      : fsm_(fsm), lifecycle_(lifecycle) {}

  bool beginAuth(uint32_t now_ms) override {
    ++begin_calls;
    return fsm_ != nullptr && fsm_->handleAuthPending(now_ms, 5000);
  }

  bool commitAuthorizedAction(sgk::LocalAccessAction action,
                              uint32_t now_ms) override {
    ++commit_calls;
    if (fsm_ == nullptr || lifecycle_ == nullptr) return false;
    bool accepted = false;
    bool emitted = false;
    if (action == sgk::LocalAccessAction::kOpenImmediately) {
      accepted = fsm_->handleLocalManualOpen(now_ms, 1000, 2000);
      if (accepted) emitted = lifecycle_->emitRelayOn(now_ms);
    } else {
      accepted = fsm_->handleAuthSuccess(now_ms, 60000, 2000);
      if (accepted) emitted = lifecycle_->emitArmed(now_ms);
    }
    lifecycle_emit_ok = lifecycle_emit_ok && (!accepted || emitted);
    if (emitted && core != nullptr) {
      core->advanceEventSequence(lifecycle_->lastSequence());
    }
    return accepted;
  }

  void abortAuth(uint32_t now_ms) override {
    ++abort_calls;
    if (fsm_ != nullptr) fsm_->handleAuthAbort(now_ms, "auth_aborted");
  }

  sgk::ProtocolCore* core = nullptr;
  int begin_calls = 0;
  int commit_calls = 0;
  int abort_calls = 0;
  bool lifecycle_emit_ok = true;

 private:
  sgk::TargetAccessFsm* fsm_ = nullptr;
  sgk::LocalGattLifecycleBridge* lifecycle_ = nullptr;
};

std::array<uint8_t, 16> hello(uint16_t min = 1, uint16_t max = 1,
                              uint8_t framing_min = 1,
                              uint8_t framing_max = 1,
                              uint16_t max_rx = 2048) {
  std::array<uint8_t, 16> value{};
  value[0] = static_cast<uint8_t>(min >> 8);
  value[1] = static_cast<uint8_t>(min);
  value[2] = static_cast<uint8_t>(max >> 8);
  value[3] = static_cast<uint8_t>(max);
  value[4] = framing_min;
  value[5] = framing_max;
  value[6] = static_cast<uint8_t>(max_rx >> 8);
  value[7] = static_cast<uint8_t>(max_rx);
  value[11] = 3;
  value[15] = 100;
  return value;
}

std::vector<uint8_t> proof(const std::array<uint8_t, 16>& session_id,
                           uint8_t action = 1, size_t size = sgk::kProofSize) {
  std::vector<uint8_t> value(size, 0);
  if (size < 39) return value;
  value[1] = 1;
  std::memcpy(value.data() + 2, session_id.data(), session_id.size());
  const auto credential = hex("aabbccddeeff00112233445566778899");
  std::memcpy(value.data() + 18, credential.data(), credential.size());
  value[34] = action;
  value[38] = 3;
  for (size_t index = 39; index < value.size(); ++index) value[index] = 0x5A;
  return value;
}

bool send(sgk::ProtocolCore& core, sgk::MessageType type,
          const uint8_t* payload, size_t length, uint32_t now,
          size_t fragment_capacity = 502, uint16_t message_id = 1,
          sgk::ConnectionToken owner = {}) {
  if (!owner.valid()) owner = core.connectionOwner();
  const size_t count = (length + fragment_capacity - 1) / fragment_capacity;
  bool result = true;
  for (size_t index = 0; index < count; ++index) {
    uint8_t frame[512] = {};
    const size_t frame_length = sgk::ProtocolCore::buildFrame(
        type, message_id, payload, length, fragment_capacity,
        static_cast<uint8_t>(index), frame, sizeof(frame));
    CHECK(frame_length != 0);
    result = core.receiveFrame(type, owner, frame, frame_length,
                               now + static_cast<uint32_t>(index)) &&
             result;
  }
  return result;
}

std::vector<sgk::OutputMessage> drain(sgk::ProtocolCore& core) {
  std::vector<sgk::OutputMessage> output;
  sgk::OutputMessage item;
  while (core.popOutput(&item)) output.push_back(item);
  return output;
}

void start(sgk::ProtocolCore& core, uint32_t now = 1000) {
  CHECK(core.initialize());
  core.setEnabled(true);
  sgk::ConnectionToken owner;
  CHECK(core.connect(7, now, &owner));
  CHECK(owner.valid());
}

void testCanonicalVectorsAndFraming() {
  CHECK(!sgk::effectiveFeatureEnabled(true));  // stale NVS true, compile OFF.
  CHECK(sgk::shouldInitializePersonalHardwarelessState(true, false, true));
  CHECK(!sgk::shouldInitializePersonalHardwarelessState(true, true, true));
  CHECK(!sgk::shouldInitializePersonalHardwarelessState(true, false, false));
  CHECK(!sgk::shouldInitializePersonalHardwarelessState(false, false, true));
  const auto challenge = hex(
      "53474b4348414c31000100112233445566778899aabbccddeeff102132435465"
      "768798a9bacbdcedfe0f000102030405060708090a0b0c0d0e0f101112131415"
      "161718191a1b1c1d1e1fffeeddccbbaa9988776655443322110000000000075b"
      "cd15000000000000002a45d76a3348fedc60d9219dd109bf1f86dc18ac3b9e"
      "de4e971000442bd95cbc8e");
  uint8_t digest[32] = {};
  sgk::ProtocolCore::sha256(challenge.data(), challenge.size(), digest);
  CHECK(std::memcmp(digest,
                    hex("7cebae229af25267c8ae244cdb476a48a692feb81477cbc7f"
                        "36e110e993bd464")
                        .data(),
                    32) == 0);
  const auto expected_frames = std::vector<std::string>{
      "534701101234000e008a53474b4348414c310001",
      "534701101234010e008a00112233445566778899",
      "534701101234020e008aaabbccddeeff10213243",
      "534701101234030e008a5465768798a9bacbdced",
      "534701101234040e008afe0f0001020304050607",
      "534701101234050e008a08090a0b0c0d0e0f1011",
      "534701101234060e008a12131415161718191a1b",
      "534701101234070e008a1c1d1e1fffeeddccbbaa",
      "534701101234080e008a99887766554433221100",
      "534701101234090e008a00000000075bcd150000",
      "5347011012340a0e008a00000000002a45d76a33",
      "5347011012340b0e008a48fedc60d9219dd109bf",
      "5347011012340c0e008a1f86dc18ac3b9ede4e97",
      "5347011012340d0e008a1000442bd95cbc8e"};
  for (size_t index = 0; index < expected_frames.size(); ++index) {
    uint8_t frame[32] = {};
    const size_t length = sgk::ProtocolCore::buildFrame(
        sgk::MessageType::kChallenge, 0x1234, challenge.data(), challenge.size(),
        10, static_cast<uint8_t>(index), frame, sizeof(frame));
    CHECK(std::vector<uint8_t>(frame, frame + length) ==
          hex(expected_frames[index]));
  }
  std::vector<uint8_t> maximum(sgk::kMaxMessageSize, 0x5a);
  uint8_t maximum_frame[512] = {};
  CHECK(sgk::ProtocolCore::buildFrame(
            sgk::MessageType::kProof, 9, maximum.data(), maximum.size(), 502,
            0, maximum_frame, sizeof(maximum_frame)) == 512);
  maximum.push_back(0x5a);
  CHECK(sgk::ProtocolCore::buildFrame(
            sgk::MessageType::kProof, 9, maximum.data(), maximum.size(), 502,
            0, maximum_frame, sizeof(maximum_frame)) == 0);
  CHECK(std::equal(sgk::kIBeaconFilterPrefix.begin(),
                   sgk::kIBeaconFilterPrefix.end(),
                   hex("0215a1b2c3d4e5f67890abcdef1234567890").begin()));

  std::array<uint8_t, 32> event_ref_key{};
  for (size_t index = 0; index < event_ref_key.size(); ++index) {
    event_ref_key[index] = static_cast<uint8_t>(index);
  }
  std::array<uint8_t, 16> event_ref_session{};
  const auto event_ref_session_bytes =
      hex("102132435465768798a9bacbdcedfe0f");
  std::copy(event_ref_session_bytes.begin(), event_ref_session_bytes.end(),
            event_ref_session.begin());
  std::array<uint8_t, 16> event_ref_credential{};
  const auto event_ref_credential_bytes =
      hex("aabbccddeeff00112233445566778899");
  std::copy(event_ref_credential_bytes.begin(),
            event_ref_credential_bytes.end(), event_ref_credential.begin());
  char credential_ref[sgk::kAccessEventCredentialRefCapacity] = {};
  CHECK(sgk::deriveAccessEventCredentialRef(
      event_ref_key, "k1", canonicalDoor(), event_ref_session,
      event_ref_credential, credential_ref));
  CHECK(std::string(credential_ref) ==
        "c_k1_653b090fafcdaffa677766a2");
  CHECK(sgk::deriveAccessEventCredentialRef(
      event_ref_key, "k", canonicalDoor(), event_ref_session,
      event_ref_credential, credential_ref));
  CHECK(std::string(credential_ref) ==
        "c_k_653b090fafcdaffa677766a2");
  CHECK(!sgk::deriveAccessEventCredentialRef(
      event_ref_key, "TOO_LONG", canonicalDoor(), event_ref_session,
      event_ref_credential, credential_ref));

  // Shared with backend/tests/test_access_actor_ref.py.
  event_ref_key.fill(0x11);
  const auto shared_session_bytes =
      hex("22222222222242228222222222222222");
  const auto shared_credential_bytes =
      hex("ffeeddccbbaa99887766554433221100");
  std::copy(shared_session_bytes.begin(), shared_session_bytes.end(),
            event_ref_session.begin());
  std::copy(shared_credential_bytes.begin(), shared_credential_bytes.end(),
            event_ref_credential.begin());
  CHECK(sgk::deriveAccessEventCredentialRef(
      event_ref_key, "k1", canonicalDoor(), event_ref_session,
      event_ref_credential, credential_ref));
  CHECK(std::string(credential_ref) ==
        "c_k1_8e1681bdeb8f7c5f392c48ef");
}

void testAccessEvidenceMacFixedVectors() {
  CHECK(!sgk::accessEventCodeAllowsCredentialRef(
      sgk::EventCode::kAccessProofRejected));
  CHECK(sgk::accessEventCodeAllowsCredentialRef(
      sgk::EventCode::kAccessProofVerified));
  CHECK(sgk::accessEventCodeAllowsCredentialRef(
      sgk::EventCode::kAccessSessionTerminated));
  const auto bytes16 = [](const char* encoded) {
    std::array<uint8_t, 16> output{};
    const auto decoded = hex(encoded);
    std::copy(decoded.begin(), decoded.end(), output.begin());
    return output;
  };
  std::array<uint8_t, 32> key{};
  key.fill(0x11);

  sgk::AccessEventMacInput event{};
  event.key_id = "k1";
  event.topic_target_id = "sgk-personal-01";
  event.door_id = canonicalDoor();
  event.source_instance_id = "target_0123456789abcdef";
  event.source_boot_id = bytes16("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  event.source_boot_count = 686;
  event.event_id = bytes16("11111111111141118111111111111111");
  event.session_id = bytes16("22222222222242228222222222222222");
  event.sequence = 7;
  event.attempt = 1;
  event.event_code = "ACCESS_SENSOR_DETECTED";
  event.stage = "SENSOR";
  event.outcome = "SUCCEEDED";
  event.reason_code = "SENSOR_THRESHOLD_MET";
  event.has_causation = true;
  event.causation_event_id =
      bytes16("33333333333343338333333333333333");
  event.monotonic_ms = 123456789;
  event.credential_ref = "c_k1_8e1681bdeb8f7c5f392c48ef";
  event.has_distance_mm = true;
  event.distance_mm = 420;

  std::array<uint8_t, sgk::kAccessEventMacInputCapacity> canonical{};
  size_t length = 0;
  CHECK(sgk::buildAccessEventMacInput(
      event, canonical.data(), canonical.size(), &length));
  CHECK(length == 282);
  uint8_t input_digest[32] = {};
  sgk::ProtocolCore::sha256(canonical.data(), length, input_digest);
  CHECK(std::memcmp(
            input_digest,
            hex("fd208a51ceca2a76017b06234befd077d9302c4507a504bf0c896939aeffe3fc")
                .data(),
            sizeof(input_digest)) == 0);
  uint8_t tag[sgk::kAccessEvidenceTagSize] = {};
  CHECK(sgk::deriveAccessEventMac(key, event, tag));
  CHECK(std::memcmp(tag,
                    hex("ee82880739ce2d2ae3a726c641a6dd08").data(),
                    sizeof(tag)) == 0);

  sgk::AccessStatusMacInput status{};
  status.key_id = "k1";
  status.topic_target_id = "sgk-personal-01";
  status.door_id = canonicalDoor();
  status.source_boot_id = bytes16("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  status.source_boot_count = 686;
  status.access_revision = 42;
  status.state = "IDLE";
  status.has_last_terminal = true;
  status.last_terminal_session_id =
      bytes16("22222222222242228222222222222222");
  status.last_terminal_event_sequence = 11;
  status.last_terminal_event_code = "ACCESS_SESSION_COMPLETED";
  status.last_terminal_reason_code = "ACCESS_GRANTED";
  status.last_terminal_credential_ref =
      "c_k1_8e1681bdeb8f7c5f392c48ef";
  status.last_terminal_phase_mask = 0x001f;
  status.relay_commanded_on = false;
  status.relay_pin_level = 1;

  std::array<uint8_t, sgk::kAccessStatusMacInputCapacity> status_canonical{};
  length = 0;
  CHECK(sgk::buildAccessStatusMacInput(
      status, status_canonical.data(), status_canonical.size(), &length));
  CHECK(length == 203);
  sgk::ProtocolCore::sha256(status_canonical.data(), length, input_digest);
  CHECK(std::memcmp(
            input_digest,
            hex("4d171b5fdb6d1de6539dcc966e1c22d8a46f7cf9672bd47e0d4adcbcb9a46c86")
                .data(),
            sizeof(input_digest)) == 0);
  CHECK(sgk::deriveAccessStatusMac(key, status, tag));
  CHECK(std::memcmp(tag,
                    hex("ee13d37c543d4a8e5a046a7fc4cb7a86").data(),
                    sizeof(tag)) == 0);

  event.has_relay_hold_ms = true;
  event.relay_hold_ms = 600001;
  CHECK(!sgk::buildAccessEventMacInput(
      event, canonical.data(), canonical.size(), &length));
  status.last_terminal_phase_mask = 0x0040;
  CHECK(!sgk::buildAccessStatusMacInput(
      status, status_canonical.data(), status_canonical.size(), &length));
}

void testCanonicalSessionAndVerifier() {
  auto random = canonicalRandom();
  FakeVerifier verifier(sgk::ResultReason::kOk);
  EventRecorder events;
  FakeAuthControlGate control;
  sgk::ProtocolCore core(random, verifier, canonicalDoor(), &events, &control);
  start(core, 123451789);
  const auto client = hello();
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             123451789, 502));
  auto output = drain(core);
  CHECK(output.size() == 2);
  CHECK(output[0].type == sgk::MessageType::kTargetHello);
  CHECK(output[0].length == 20);
  CHECK(std::vector<uint8_t>(output[0].bytes.begin(),
                             output[0].bytes.begin() + output[0].length) ==
        hex("0001000100010100080000000003000000c80001"));
  CHECK(output[1].type == sgk::MessageType::kChallenge);
  CHECK(output[1].length == sgk::kChallengeSize);
  CHECK(std::vector<uint8_t>(output[1].bytes.begin(),
                             output[1].bytes.begin() + output[1].length) ==
        hex("53474b4348414c31000100112233445566778899aabbccddeeff102132435465"
            "768798a9bacbdcedfe0f000102030405060708090a0b0c0d0e0f101112131415"
            "161718191a1b1c1d1e1fffeeddccbbaa9988776655443322110000000000075b"
            "cd15000000000000002a45d76a3348fedc60d9219dd109bf1f86dc18ac3b9e"
            "de4e971000442bd95cbc8e"));
  const auto valid_proof = proof(core.sessionId());
  CHECK(send(core, sgk::MessageType::kProof, valid_proof.data(),
             valid_proof.size(), 123451900, 11, 2));
  output = drain(core);
  CHECK(output.size() == 1);
  CHECK(u16(output[0].bytes.data() + 18) == 0);
  CHECK(verifier.calls == 1);
  CHECK(control.begin_calls == 1);
  CHECK(control.commit_calls == 1);
  CHECK(control.last_action == sgk::LocalAccessAction::kArmForSensor);
  CHECK(std::vector<uint8_t>(verifier.last.signing_input.begin(),
                             verifier.last.signing_input.end()) ==
        hex("53474b50524630317cebae229af25267c8ae244cdb476a48a692feb81477cbc7f"
            "36e110e993bd464aabbccddeeff001122334455667788990100000003"));
  CHECK(events.events.size() >= 3);
  const auto expected_credential = hex("aabbccddeeff00112233445566778899");
  bool found_verified = false;
  for (const auto& event : events.events) {
    if (event.code == sgk::EventCode::kAccessProofVerified) {
      found_verified = true;
      CHECK(std::equal(event.credential_id.begin(), event.credential_id.end(),
                       expected_credential.begin()));
    } else {
      CHECK(std::all_of(event.credential_id.begin(), event.credential_id.end(),
                        [](uint8_t value) { return value == 0; }));
    }
  }
  CHECK(found_verified);
}

void testAuthenticatedActionControlBinding() {
  {
    auto random = canonicalRandom();
    FakeVerifier verifier(sgk::ResultReason::kOk);
    EventRecorder events;
    FakeAuthControlGate control;
    sgk::ProtocolCore core(random, verifier, canonicalDoor(), &events,
                           &control);
    start(core, 1000);
    const auto client = hello();
    CHECK(send(core, sgk::MessageType::kClientHello, client.data(),
               client.size(), 1000));
    drain(core);

    const auto manual_proof = proof(
        core.sessionId(),
        static_cast<uint8_t>(sgk::LocalAccessAction::kOpenImmediately));
    CHECK(send(core, sgk::MessageType::kProof, manual_proof.data(),
               manual_proof.size(), 1100, 11, 2));
    CHECK(control.commit_calls == 1);
    CHECK(control.last_action == sgk::LocalAccessAction::kOpenImmediately);
    const auto output = drain(core);
    CHECK(output.size() == 1);
    CHECK(output[0].type == sgk::MessageType::kResult);
    CHECK(u16(output[0].bytes.data() + 18) == 0);
  }

  {
    auto random = canonicalRandom();
    FakeVerifier verifier(sgk::ResultReason::kOk);
    EventRecorder downstream;
    sgk::LocalGattLifecycleBridge events(&downstream);
    FakeAuthControlGate control;
    control.commit_result = false;
    sgk::ProtocolCore core(random, verifier, canonicalDoor(), &events,
                           &control);
    start(core, 2000);
    const auto client = hello();
    CHECK(send(core, sgk::MessageType::kClientHello, client.data(),
               client.size(), 2000));
    drain(core);
    const auto arm_proof = proof(core.sessionId());
    CHECK(!send(core, sgk::MessageType::kProof, arm_proof.data(),
                arm_proof.size(), 2100, 11, 2));
    CHECK(control.abort_calls == 1);
    const auto output = drain(core);
    CHECK(output.size() == 1);
    CHECK(u16(output[0].bytes.data() + 18) ==
          static_cast<uint16_t>(sgk::ResultReason::kInternalFailClosed));
    const auto rejected = std::find_if(
        downstream.events.begin(), downstream.events.end(),
        [](const sgk::Event& event) {
          return event.code == sgk::EventCode::kAccessProofRejected;
        });
    const auto terminated = std::find_if(
        downstream.events.begin(), downstream.events.end(),
        [](const sgk::Event& event) {
          return event.code == sgk::EventCode::kAccessSessionTerminated;
        });
    CHECK(rejected != downstream.events.end());
    CHECK(terminated != downstream.events.end());
    CHECK(std::any_of(rejected->credential_id.begin(),
                      rejected->credential_id.end(),
                      [](uint8_t value) { return value != 0; }));
    CHECK(std::any_of(terminated->credential_id.begin(),
                      terminated->credential_id.end(),
                      [](uint8_t value) { return value != 0; }));
    CHECK(!sgk::accessEventCodeAllowsCredentialRef(rejected->code));
    CHECK(sgk::accessEventCodeAllowsCredentialRef(terminated->code));
  }

  {
    auto random = canonicalRandom();
    FakeVerifier verifier(sgk::ResultReason::kOk);
    EventRecorder events;
    FakeAuthControlGate control;
    control.begin_result = false;
    sgk::ProtocolCore core(random, verifier, canonicalDoor(), &events,
                           &control);
    start(core, 3000);
    const auto client = hello();
    CHECK(!send(core, sgk::MessageType::kClientHello, client.data(),
                client.size(), 3000));
    const auto output = drain(core);
    CHECK(output.size() == 1);
    CHECK(output[0].type == sgk::MessageType::kTargetHello);
    CHECK(output[0].bytes[7] == 2);
    CHECK(control.abort_calls == 1);
    CHECK(control.commit_calls == 0);
  }
}

void testTargetAclManagerAndStorage() {
  MemoryStorage storage;
  sgk::TargetAclManager acl_manager(&storage);
  const auto door = canonicalDoor();

  CHECK(acl_manager.begin(door, 1000));
  CHECK(!acl_manager.hasActiveAcl());
  CHECK(acl_manager.activeAclVersion() == 0);

  // Signer public key from v1.json fixture
  const auto signer_pubkey_bytes = hex(
      "047cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc4766997807775510"
      "db8ed040293d9ac69f7430dbba7dade63ce982299e04b79d227873d1");
  std::array<uint8_t, 65> signer_pubkey{};
  std::copy(signer_pubkey_bytes.begin(), signer_pubkey_bytes.end(),
            signer_pubkey.begin());
  acl_manager.setSignerPublicKey(signer_pubkey);
  acl_manager.setExpectedSigningKeyId(0x07);

  // Canonical signed ACL 242-byte payload (178 bytes header+entry + 64 bytes signature)
  const auto acl_payload = hex(
      "53474b41434c3031000100112233445566778899aabbccddeeff000000000000002a000000"
      "006a6d3700000000006a6d3700000000006a6d45100000038400010001000000070001aabb"
      "ccddeeff00112233445566778899046b17d1f2e12c4247f8bce6e563a440f277037d812deb"
      "33a0f4a13945d898c2964fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb640"
      "6837bf51f50100000001000000006a6d3700000000006a94c4000001000113cdf7246422ab"
      "07576d0328bfe313db997c5d2689df26657b2ec338e690d4f11f2b0f9c7c6dfdc364cad779"
      "162817496b68139c67e38cc51a02aa255870ef8b");

  CHECK(acl_manager.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                   1000, 1785542400) == sgk::ResultReason::kOk);
  CHECK(acl_manager.hasActiveAcl());
  CHECK(acl_manager.activeAclVersion() == 42);
  CHECK(acl_manager.isLeaseValid(1000, 1785542400));

  // Idempotent re-apply returns kOk without extending lease
  CHECK(acl_manager.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                   2000, 1785542400) == sgk::ResultReason::kOk);

  // Re-apply same version with tampered payload -> fail-closed kMalformed
  auto tampered_acl = acl_payload;
  tampered_acl[8] ^= 0xff;  // tamper schema_version
  CHECK(acl_manager.applySignedAcl(tampered_acl.data(), tampered_acl.size(),
                                   2500, 1785542400) ==
        sgk::ResultReason::kMalformed);

  // A stale payload with its old signature fails signature binding before it
  // can be considered a valid rollback candidate.
  auto stale_acl = acl_payload;
  stale_acl[33] = 41;  // acl_version = 41 < 42
  CHECK(acl_manager.applySignedAcl(stale_acl.data(), stale_acl.size(),
                                   3000, 1785542400) ==
        sgk::ResultReason::kProofInvalid);

  // Lease expiry after 900 seconds (900000 ms)
  CHECK(!acl_manager.isLeaseValid(1000 + 900001, 1785542400));

  // Clock rollback / jump detection
  CHECK(!acl_manager.isLeaseValid(500, 1785542400));

  // Find credential lookup
  const auto cred_id = hex("aabbccddeeff00112233445566778899");
  std::array<uint8_t, 16> credential_id{};
  std::copy(cred_id.begin(), cred_id.end(), credential_id.begin());
  sgk::TargetAclEntry found_entry{};
  CHECK(acl_manager.findCredential(credential_id, &found_entry));
  CHECK(found_entry.status == 1);
  CHECK(found_entry.permissions == 1);

  // Non-existent credential lookup returns false
  credential_id[0] ^= 0xFF;
  CHECK(!acl_manager.findCredential(credential_id, nullptr));

  // Storage recovery check: new TargetAclManager using same storage recovers high watermark v42 but fails closed on lease without trusted clock
  sgk::TargetAclManager acl_manager2(&storage);
  acl_manager2.setSignerPublicKey(signer_pubkey);
  CHECK(acl_manager2.begin(door, 5000));
  CHECK(!acl_manager2.hasActiveAcl());
  CHECK(acl_manager2.highWatermark() == 42);
}

void testTargetProofVerifierIntegration() {
  MemoryStorage storage;
  sgk::TargetAclManager acl_manager(&storage);
  const auto door = canonicalDoor();

  uint32_t current_now_ms = 1000;
  uint64_t current_epoch_s = 1785542400;

  static uint32_t s_now_ms = 1000;
  static uint64_t s_epoch_s = 1785542400;
  s_now_ms = current_now_ms;
  s_epoch_s = current_epoch_s;

  sgk::TargetProofVerifier proof_verifier(
      acl_manager, []() -> uint32_t { return s_now_ms; },
      []() -> uint64_t { return s_epoch_s; });

  sgk::VerifyRequest request{};
  request.protocol_version = 1;
  const auto cred_id = hex("aabbccddeeff00112233445566778899");
  std::copy(cred_id.begin(), cred_id.end(), request.credential_id.begin());
  request.action = 1;
  request.client_capabilities = 3;

  // Proof signature from v1.json
  const auto sig_bytes = hex(
      "3894dfd39c70ee301d17346632461ac66f168c29fbada9bcaa18b9e408cf35dc22ed9694ca"
      "ebf65438228b0bfa4d456a6861c59f917ce3346090ec5f17ecfde8");
  std::copy(sig_bytes.begin(), sig_bytes.end(), request.signature_raw64.begin());

  const auto input_bytes = hex(
      "53474b50524630317cebae229af25267c8ae244cdb476a48a692feb81477cbc7f36e110e9"
      "93bd464aabbccddeeff001122334455667788990100000003");
  std::copy(input_bytes.begin(), input_bytes.end(), request.signing_input.begin());

  // Before ACL is loaded -> kAclUnavailable
  auto result = proof_verifier.verify(request);
  CHECK(result.reason == sgk::ResultReason::kAclUnavailable);

  // Load ACL v42
  const auto signer_pubkey_bytes = hex(
      "047cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc4766997807775510"
      "db8ed040293d9ac69f7430dbba7dade63ce982299e04b79d227873d1");
  std::array<uint8_t, 65> signer_pubkey{};
  std::copy(signer_pubkey_bytes.begin(), signer_pubkey_bytes.end(),
            signer_pubkey.begin());
  acl_manager.setSignerPublicKey(signer_pubkey);
  acl_manager.setExpectedSigningKeyId(0x07);
  acl_manager.begin(door, 1000);

  const auto acl_payload = hex(
      "53474b41434c3031000100112233445566778899aabbccddeeff000000000000002a000000"
      "006a6d3700000000006a6d3700000000006a6d45100000038400010001000000070001aabb"
      "ccddeeff00112233445566778899046b17d1f2e12c4247f8bce6e563a440f277037d812deb"
      "33a0f4a13945d898c2964fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb640"
      "6837bf51f50100000001000000006a6d3700000000006a94c4000001000113cdf7246422ab"
      "07576d0328bfe313db997c5d2689df26657b2ec338e690d4f11f2b0f9c7c6dfdc364cad779"
      "162817496b68139c67e38cc51a02aa255870ef8b");
  CHECK(acl_manager.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                   1000, 1785542400) == sgk::ResultReason::kOk);

  // Now proof verification succeeds!
  result = proof_verifier.verify(request);
  CHECK(result.reason == sgk::ResultReason::kOk);
  CHECK(result.active_acl_version == 42);

  // High-S signature rejection check
  auto high_s_request = request;
  // Set s to n - s (which is > n/2)
  high_s_request.signature_raw64[32] = 0x80;
  result = proof_verifier.verify(high_s_request);
  CHECK(result.reason == sgk::ResultReason::kMalformed);

  // Invalid action rejection
  auto bad_action_request = request;
  bad_action_request.action = 3;
  result = proof_verifier.verify(bad_action_request);
  CHECK(result.reason == sgk::ResultReason::kProofInvalid);

  // Unknown credential rejection
  auto unknown_cred_request = request;
  unknown_cred_request.credential_id[0] ^= 0xFF;
  result = proof_verifier.verify(unknown_cred_request);
  CHECK(result.reason == sgk::ResultReason::kCredentialDenied);
}

void testTargetAccessFsmAndRelayInterlock() {
  static bool last_relay_on = false;
  static std::string last_event_name;
  static std::string last_event_msg;
  last_relay_on = false;

  sgk::TargetAccessFsm fsm(
      [](bool on) { last_relay_on = on; },
      [](const char* event, const char* message) {
        last_event_name = event != nullptr ? event : "";
        last_event_msg = message != nullptr ? message : "";
      });

  fsm.begin(1000);
  CHECK(fsm.state() == GateState::IDLE);
  CHECK(!fsm.isArmed());
  CHECK(!fsm.isRelayOn());
  CHECK(fsm.otaSafeState() == OtaSafeState::SAFE);

  // Auth proof flow: IDLE -> AUTH_PENDING -> ARMED -> SENSOR -> RELAY_HOLD
  CHECK(!fsm.handleAuthSuccess(1000, 60000, 2000)); // Direct AuthSuccess from IDLE is rejected
  CHECK(fsm.handleAuthPending(1000, 5000));
  CHECK(fsm.state() == GateState::AUTH_PENDING);

  CHECK(fsm.handleAuthSuccess(1500, 60000, 2000)); // Transitions AUTH_PENDING -> ARMED
  CHECK(fsm.state() == GateState::ARMED);
  CHECK(!fsm.isRelayOn());

  CHECK(fsm.handleSensorTrigger(2000, 1000, 2000)); // Transitions ARMED -> RELAY_HOLD
  CHECK(fsm.state() == GateState::RELAY_HOLD);
  CHECK(fsm.isRelayOn());
  CHECK(last_relay_on);
  CHECK(fsm.otaSafeState() == OtaSafeState::RELAY_ACTIVE);
  CHECK(last_event_name == "relay_on_sensor");

  // Interlock check: subsequent auth attempt while RELAY_HOLD is rejected (fail-closed)
  CHECK(!fsm.handleAuthSuccess(2500, 60000, 2000));
  CHECK(last_event_name == "auth_open_rejected");

  // Tick past 1000ms hold -> transitions to COOLDOWN and turns relay OFF
  fsm.tick(3001);
  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(!fsm.isRelayOn());
  CHECK(!last_relay_on);
  CHECK(fsm.otaSafeState() == OtaSafeState::ACCESS_SESSION_ACTIVE);
  CHECK(last_event_name == "session_completed");

  // Interlock check: auth attempt while COOLDOWN is rejected
  CHECK(!fsm.handleAuthSuccess(3500, 60000, 2000));

  // Tick past 2000ms cooldown -> transitions to IDLE
  fsm.tick(5002);
  CHECK(fsm.state() == GateState::IDLE);
  CHECK(fsm.otaSafeState() == OtaSafeState::SAFE);
  CHECK(last_event_name == "gate_idle");

  // Authenticated local manual action bypasses ARMED/sensor and drives relay.
  CHECK(fsm.handleAuthPending(5003, 5000));
  CHECK(fsm.handleLocalManualOpen(5004, 1000, 2000));
  CHECK(fsm.state() == GateState::RELAY_HOLD);
  CHECK(fsm.isRelayOn());
  CHECK(last_relay_on);
  CHECK(last_event_name == "relay_on_local_manual");
  fsm.cleanupToIdle(5005);

  // Manual remote trigger (MQTT) when IDLE -> transitions to RELAY_HOLD
  CHECK(fsm.handleManualRemoteOpen(5000, 1000, 2000));
  CHECK(fsm.state() == GateState::RELAY_HOLD);
  CHECK(fsm.isRelayOn());
  CHECK(last_event_name == "relay_on_manual");

  // Cleanup to IDLE turns relay OFF and resets state
  fsm.cleanupToIdle(5500);
  CHECK(fsm.state() == GateState::IDLE);
  CHECK(!fsm.isRelayOn());
  CHECK(!last_relay_on);
  CHECK(fsm.otaSafeState() == OtaSafeState::SAFE);
}

void testVerifiedLocalGattLifecycleBridge() {
  EventRecorder downstream;
  sgk::LocalGattLifecycleBridge bridge(&downstream);
  sgk::Event proof{};
  proof.code = sgk::EventCode::kAccessProofVerified;
  proof.reason = sgk::EventReason::kProofValid;
  proof.transport_reason = sgk::ResultReason::kOk;
  proof.monotonic_ms = 1000;
  const auto session_bytes = hex("102132435465768798a9babbdcddedef");
  const auto boot_bytes = hex("00112233445566778899aabbccddeeff");
  const auto credential_bytes = hex("aabbccddeeff00112233445566778899");
  std::copy(session_bytes.begin(), session_bytes.end(), proof.session_id.begin());
  std::copy(boot_bytes.begin(), boot_bytes.end(), proof.boot_id.begin());
  std::copy(credential_bytes.begin(), credential_bytes.end(),
            proof.credential_id.begin());
  proof.sequence = 41;
  proof.has_causation = true;
  proof.causation_sequence = 40;

  bridge.emit(proof);
  CHECK(bridge.hasVerifiedSession());
  CHECK(bridge.emitArmed(1001));
  CHECK(bridge.emitSensorDetected(1002));
  CHECK(bridge.emitRelayOn(1003));
  CHECK(bridge.emitRelayOff(2003, false));
  CHECK(bridge.emitCompleted(2004));
  CHECK(!bridge.hasVerifiedSession());
  CHECK(!bridge.emitCompleted(2005));

  const std::array<sgk::EventCode, 6> expected = {{
      sgk::EventCode::kAccessProofVerified,
      sgk::EventCode::kAccessArmed,
      sgk::EventCode::kAccessSensorDetected,
      sgk::EventCode::kAccessRelayOn,
      sgk::EventCode::kAccessRelayOff,
      sgk::EventCode::kAccessSessionCompleted,
  }};
  CHECK(downstream.events.size() == expected.size());
  for (size_t i = 0; i < expected.size(); ++i) {
    CHECK(downstream.events[i].code == expected[i]);
    CHECK(downstream.events[i].session_id == proof.session_id);
    CHECK(downstream.events[i].boot_id == proof.boot_id);
    CHECK(downstream.events[i].credential_id == proof.credential_id);
    CHECK(downstream.events[i].sequence == proof.sequence + i);
    if (i > 0) {
      CHECK(downstream.events[i].has_causation);
      CHECK(downstream.events[i].causation_sequence ==
            downstream.events[i - 1].sequence);
    }
  }

  CHECK(bridge.lastSequence() == 46);
  proof.sequence = 47;
  proof.session_id[15] ^= 0x01;
  bridge.emit(proof);
  CHECK(bridge.emitArmed(3000));
  CHECK(bridge.emitTerminated(4000, sgk::EventReason::kArmTimeout));
  CHECK(!bridge.hasVerifiedSession());
  CHECK(bridge.lastSequence() == 49);
  CHECK(downstream.events.back().code ==
        sgk::EventCode::kAccessSessionTerminated);
  CHECK(downstream.events.back().reason == sgk::EventReason::kArmTimeout);
  CHECK(!bridge.emitRelayOn(4001));

  sgk::Event post_terminal{};
  post_terminal.code = sgk::EventCode::kAccessGattConnected;
  post_terminal.session_id = proof.session_id;
  bridge.emit(post_terminal);
  CHECK(std::all_of(downstream.events.back().credential_id.begin(),
                    downstream.events.back().credential_id.end(),
                    [](uint8_t value) { return value == 0; }));
}

void testInterleavedGattPreservesVerifiedLifecycleIntegrity() {
  EventRecorder downstream;
  sgk::LocalGattLifecycleBridge bridge(&downstream);

  sgk::Event proof_a{};
  proof_a.code = sgk::EventCode::kAccessProofVerified;
  proof_a.reason = sgk::EventReason::kProofValid;
  proof_a.transport_reason = sgk::ResultReason::kOk;
  proof_a.session_id = {{0x10, 0x21, 0x32, 0x43, 0x54, 0x65, 0x47, 0x87,
                         0x98, 0xa9, 0xba, 0xcb, 0xdc, 0xed, 0xfe, 0x0f}};
  proof_a.boot_id = {{0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77,
                      0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff}};
  proof_a.credential_id = {{0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x00, 0x11,
                            0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99}};
  proof_a.sequence = 41;
  bridge.emit(proof_a);
  CHECK(bridge.emitArmed(1001));
  CHECK(bridge.emitRelayOn(1002));
  CHECK(bridge.lastSequence() == 43);

  sgk::Event b_connected{};
  b_connected.code = sgk::EventCode::kAccessGattConnected;
  b_connected.reason = sgk::EventReason::kGattConnected;
  b_connected.transport_reason = sgk::ResultReason::kOk;
  b_connected.session_id = {{0x20, 0x31, 0x42, 0x53, 0x64, 0x75, 0x46, 0x86,
                              0x97, 0xa8, 0xb9, 0xca, 0xdb, 0xec, 0xfd, 0x0e}};
  b_connected.boot_id = proof_a.boot_id;
  b_connected.sequence = 44;
  b_connected.has_causation = true;
  b_connected.causation_sequence = 43;
  bridge.emit(b_connected);

  sgk::Event b_terminated = b_connected;
  b_terminated.code = sgk::EventCode::kAccessSessionTerminated;
  b_terminated.reason = sgk::EventReason::kOtaBusy;
  b_terminated.transport_reason = sgk::ResultReason::kBusy;
  b_terminated.sequence = 45;
  b_terminated.causation_sequence = 44;
  bridge.emit(b_terminated);

  CHECK(bridge.hasVerifiedSession());
  CHECK(bridge.lastSequence() == 45);
  CHECK(bridge.emitRelayOff(2002, false));
  CHECK(bridge.emitCompleted(2003));
  CHECK(!bridge.hasVerifiedSession());
  CHECK(bridge.lastSequence() == 47);

  const sgk::Event& a_relay_off = downstream.events[5];
  CHECK(a_relay_off.code == sgk::EventCode::kAccessRelayOff);
  CHECK(a_relay_off.sequence == 46);
  CHECK(a_relay_off.causation_sequence == 43);
  CHECK(a_relay_off.causation_sequence != b_terminated.sequence);
  CHECK(a_relay_off.credential_id == proof_a.credential_id);
  CHECK(std::all_of(downstream.events[3].credential_id.begin(),
                    downstream.events[3].credential_id.end(),
                    [](uint8_t value) { return value == 0; }));
  CHECK(std::all_of(downstream.events[4].credential_id.begin(),
                    downstream.events[4].credential_id.end(),
                    [](uint8_t value) { return value == 0; }));

  std::vector<uint64_t> sequences;
  for (const sgk::Event& event : downstream.events) {
    sequences.push_back(event.sequence);
  }
  std::sort(sequences.begin(), sequences.end());
  CHECK(std::adjacent_find(sequences.begin(), sequences.end()) ==
        sequences.end());
}

void testLegacySupersededTerminalCompatibilityClearsActor() {
  EventRecorder downstream;
  sgk::LocalGattLifecycleBridge bridge(&downstream);

  sgk::Event proof_a{};
  proof_a.code = sgk::EventCode::kAccessProofVerified;
  proof_a.reason = sgk::EventReason::kProofValid;
  proof_a.transport_reason = sgk::ResultReason::kOk;
  proof_a.session_id.fill(0x11);
  proof_a.boot_id.fill(0x22);
  proof_a.credential_id.fill(0x33);
  proof_a.sequence = 100;
  bridge.emit(proof_a);
  CHECK(bridge.emitArmed(3001));

  sgk::Event b_connected{};
  b_connected.code = sgk::EventCode::kAccessGattConnected;
  b_connected.reason = sgk::EventReason::kGattConnected;
  b_connected.transport_reason = sgk::ResultReason::kOk;
  b_connected.session_id.fill(0x44);
  b_connected.boot_id = proof_a.boot_id;
  b_connected.sequence = 102;
  bridge.emit(b_connected);

  // N/N-1 consumers retain this historical terminal reason, although the
  // current Target no longer replaces an ARMED session before proof.
  CHECK(bridge.emitTerminated(3002, sgk::EventReason::kSessionSuperseded));
  CHECK(!bridge.hasVerifiedSession());
  CHECK(bridge.lastSequence() == 103);
  const sgk::Event& superseded = downstream.events.back();
  CHECK(superseded.code == sgk::EventCode::kAccessSessionTerminated);
  CHECK(superseded.reason == sgk::EventReason::kSessionSuperseded);
  CHECK(superseded.session_id == proof_a.session_id);
  CHECK(superseded.credential_id == proof_a.credential_id);
  CHECK(superseded.causation_sequence == 101);

  sgk::Event b_terminated = b_connected;
  b_terminated.code = sgk::EventCode::kAccessSessionTerminated;
  b_terminated.reason = sgk::EventReason::kOtaBusy;
  b_terminated.transport_reason = sgk::ResultReason::kBusy;
  b_terminated.sequence = 104;
  b_terminated.has_causation = true;
  b_terminated.causation_sequence = 102;
  bridge.emit(b_terminated);
  CHECK(bridge.lastSequence() == 104);
  CHECK(std::all_of(downstream.events.back().credential_id.begin(),
                    downstream.events.back().credential_id.end(),
                    [](uint8_t value) { return value == 0; }));
  CHECK(!bridge.emitRelayOn(3003));

  sgk::Event proof_b = proof_a;
  proof_b.session_id = b_connected.session_id;
  proof_b.credential_id.fill(0x55);
  proof_b.sequence = 105;
  bridge.emit(proof_b);
  CHECK(bridge.emitArmed(3004));
  CHECK(downstream.events.back().sequence == 106);
  CHECK(downstream.events.back().causation_sequence == 105);
  CHECK(downstream.events.back().credential_id == proof_b.credential_id);
}

void testVerifiedPhaseTrackerIgnoresUnverifiedInterleaving() {
  sgk::VerifiedAccessPhaseTracker tracker;
  uint16_t terminal_mask = 0xffff;

  sgk::Event actorless_proof{};
  actorless_proof.code = sgk::EventCode::kAccessProofVerified;
  actorless_proof.session_id.fill(0x7a);
  CHECK(!tracker.observe(actorless_proof, &terminal_mask));
  CHECK(!tracker.hasVerifiedSession());
  CHECK(terminal_mask == 0);

  sgk::Event a{};
  a.code = sgk::EventCode::kAccessProofVerified;
  a.session_id.fill(0x11);
  a.credential_id.fill(0x33);
  CHECK(!tracker.observe(a, &terminal_mask));
  CHECK(terminal_mask == 0);
  CHECK(tracker.hasVerifiedSession());
  CHECK(tracker.phaseMask() ==
        sgk::VerifiedAccessPhaseTracker::kProofVerified);

  a.code = sgk::EventCode::kAccessArmed;
  CHECK(!tracker.observe(a, &terminal_mask));
  CHECK(tracker.phaseMask() ==
        (sgk::VerifiedAccessPhaseTracker::kProofVerified |
         sgk::VerifiedAccessPhaseTracker::kArmed));

  sgk::Event b{};
  b.code = sgk::EventCode::kAccessGattConnected;
  b.session_id.fill(0x22);
  CHECK(!tracker.observe(b, &terminal_mask));
  b.code = sgk::EventCode::kAccessSessionTerminated;
  CHECK(!tracker.observe(b, &terminal_mask));
  CHECK(terminal_mask == 0);
  CHECK(tracker.hasVerifiedSession());
  CHECK(tracker.phaseMask() ==
        (sgk::VerifiedAccessPhaseTracker::kProofVerified |
         sgk::VerifiedAccessPhaseTracker::kArmed));

  a.code = sgk::EventCode::kAccessSensorDetected;
  CHECK(!tracker.observe(a));
  a.code = sgk::EventCode::kAccessRelayOn;
  CHECK(!tracker.observe(a));
  a.code = sgk::EventCode::kAccessRelayOff;
  a.reason = sgk::EventReason::kRelayHoldComplete;
  CHECK(!tracker.observe(a));
  a.code = sgk::EventCode::kAccessSessionCompleted;
  CHECK(tracker.observe(a, &terminal_mask));
  CHECK(terminal_mask == 0x001f);
  CHECK(!tracker.hasVerifiedSession());
  CHECK(tracker.phaseMask() == 0);

  // A later unverified terminal cannot replay A's completed phase summary.
  CHECK(!tracker.observe(b, &terminal_mask));
  CHECK(terminal_mask == 0);

  b.code = sgk::EventCode::kAccessProofVerified;
  b.credential_id.fill(0x44);
  CHECK(!tracker.observe(b));
  b.code = sgk::EventCode::kAccessRelayOff;
  b.reason = sgk::EventReason::kRelayFailsafeCutoff;
  CHECK(!tracker.observe(b));
  b.code = sgk::EventCode::kAccessSessionTerminated;
  CHECK(tracker.observe(b, &terminal_mask));
  CHECK(terminal_mask ==
        (sgk::VerifiedAccessPhaseTracker::kProofVerified |
         sgk::VerifiedAccessPhaseTracker::kRelayOff |
         sgk::VerifiedAccessPhaseTracker::kRelayFailsafe));
}

void testUnauthenticatedHelloCannotPreemptArmedLifecycle() {
  auto random = canonicalRandom();
  FakeVerifier verifier(sgk::ResultReason::kOk);
  PhaseTrackingEventRecorder downstream;
  sgk::LocalGattLifecycleBridge lifecycle(&downstream);
  sgk::TargetAccessFsm fsm;
  fsm.begin(0);
  FsmAuthControlGate control(&fsm, &lifecycle);
  sgk::ProtocolCore protocol(random, verifier, canonicalDoor(), &lifecycle,
                             &control);
  control.core = &protocol;
  CHECK(protocol.initialize());
  protocol.setEnabled(true);

  sgk::ConnectionToken owner_a;
  CHECK(protocol.connect(40, 1000, &owner_a));
  const auto client = hello();
  CHECK(send(protocol, sgk::MessageType::kClientHello, client.data(),
             client.size(), 1000, 502, 1, owner_a));
  CHECK(drain(protocol).size() == 2);
  const std::array<uint8_t, 16> session_a = protocol.sessionId();
  const auto proof_a = proof(session_a);
  CHECK(send(protocol, sgk::MessageType::kProof, proof_a.data(),
             proof_a.size(), 2000, 502, 2, owner_a));
  CHECK(drain(protocol).size() == 1);
  CHECK(protocol.state() == sgk::SessionState::kCompleted);
  CHECK(fsm.state() == GateState::ARMED);
  CHECK(fsm.isArmed());
  CHECK(!fsm.isRelayOn());
  CHECK(control.lifecycle_emit_ok);
  CHECK(lifecycle.hasVerifiedSession());
  CHECK(downstream.phase_tracker.phaseMask() ==
        (sgk::VerifiedAccessPhaseTracker::kProofVerified |
         sgk::VerifiedAccessPhaseTracker::kArmed));

  uint64_t armed_sequence = 0;
  std::array<uint8_t, 16> credential_a{};
  for (const sgk::Event& event : downstream.events) {
    if (event.code == sgk::EventCode::kAccessProofVerified) {
      credential_a = event.credential_id;
    }
    if (event.code == sgk::EventCode::kAccessArmed) {
      armed_sequence = event.sequence;
    }
  }
  CHECK(armed_sequence != 0);
  CHECK(!std::all_of(credential_a.begin(), credential_a.end(),
                     [](uint8_t value) { return value == 0; }));

  protocol.disconnect(owner_a, 2100);
  CHECK(lifecycle.hasVerifiedSession());
  sgk::ConnectionToken owner_b;
  CHECK(protocol.connect(41, 12000, &owner_b));
  const size_t b_event_start = downstream.events.size();

  // B is rejected at ClientHello, before it receives a challenge or proof can
  // affect the existing sensor-waiting A lifecycle.
  CHECK(!send(protocol, sgk::MessageType::kClientHello, client.data(),
              client.size(), 12000, 502, 3, owner_b));
  const auto rejected_hello_outputs = drain(protocol);
  CHECK(rejected_hello_outputs.size() == 1);
  CHECK(rejected_hello_outputs[0].type == sgk::MessageType::kTargetHello);
  CHECK(rejected_hello_outputs[0].bytes[7] == 2);
  CHECK(fsm.state() == GateState::ARMED);
  CHECK(fsm.isArmed());
  CHECK(!fsm.isRelayOn());
  CHECK(lifecycle.hasVerifiedSession());
  CHECK(downstream.phase_tracker.phaseMask() ==
        (sgk::VerifiedAccessPhaseTracker::kProofVerified |
         sgk::VerifiedAccessPhaseTracker::kArmed));
  CHECK(downstream.terminal_count == 0);

  // A no-proof B disconnect after that busy response cannot abort A either.
  protocol.disconnect(owner_b, 12500);
  CHECK(fsm.state() == GateState::ARMED);
  CHECK(lifecycle.hasVerifiedSession());
  CHECK(downstream.phase_tracker.phaseMask() ==
        (sgk::VerifiedAccessPhaseTracker::kProofVerified |
         sgk::VerifiedAccessPhaseTracker::kArmed));
  CHECK(downstream.terminal_count == 0);

  // A new peer's proof frame without an accepted hello is invalid in IDLE
  // protocol state and likewise cannot abort or replace A.
  sgk::ConnectionToken owner_c;
  CHECK(protocol.connect(42, 13000, &owner_c));
  std::array<uint8_t, 16> zero_session{};
  const auto invalid_b_proof = proof(zero_session);
  CHECK(!send(protocol, sgk::MessageType::kProof, invalid_b_proof.data(),
              invalid_b_proof.size(), 13000, 502, 4, owner_c));
  drain(protocol);
  CHECK(verifier.calls == 1);
  CHECK(control.begin_calls == 2);
  CHECK(control.commit_calls == 1);
  CHECK(control.abort_calls == 1);
  CHECK(fsm.state() == GateState::ARMED);
  CHECK(fsm.isArmed());
  CHECK(lifecycle.hasVerifiedSession());
  CHECK(downstream.phase_tracker.phaseMask() ==
        (sgk::VerifiedAccessPhaseTracker::kProofVerified |
         sgk::VerifiedAccessPhaseTracker::kArmed));
  CHECK(downstream.terminal_count == 0);
  for (size_t index = b_event_start; index < downstream.events.size(); ++index) {
    CHECK(downstream.events[index].session_id != session_a);
    CHECK(std::all_of(downstream.events[index].credential_id.begin(),
                      downstream.events[index].credential_id.end(),
                      [](uint8_t value) { return value == 0; }));
  }

  // B did not alter A's original 60-second arm deadline. A can still trigger
  // the normal sensor/relay path at the final millisecond of that window.
  fsm.tick(61999);
  CHECK(fsm.state() == GateState::ARMED);
  const uint64_t interleaved_high_water = lifecycle.lastSequence();
  CHECK(fsm.handleSensorTrigger(61999, 1000, 2000));
  CHECK(lifecycle.emitSensorDetected(61999));
  protocol.advanceEventSequence(lifecycle.lastSequence());
  const sgk::Event& sensor_event = downstream.events.back();
  CHECK(sensor_event.session_id == session_a);
  CHECK(sensor_event.credential_id == credential_a);
  CHECK(sensor_event.sequence > interleaved_high_water);
  CHECK(sensor_event.causation_sequence == armed_sequence);
  CHECK(lifecycle.emitRelayOn(61999));
  protocol.advanceEventSequence(lifecycle.lastSequence());

  fsm.handleRelayTimerOff(62999, 2000);
  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(!fsm.isRelayOn());
  CHECK(lifecycle.emitRelayOff(62999, false));
  protocol.advanceEventSequence(lifecycle.lastSequence());
  CHECK(lifecycle.emitCompleted(62999));
  protocol.advanceEventSequence(lifecycle.lastSequence());
  CHECK(!lifecycle.hasVerifiedSession());
  CHECK(downstream.terminal_count == 1);
  CHECK(downstream.terminal_phase_mask == 0x001f);
  CHECK(downstream.terminal_session_id == session_a);

  CHECK(!fsm.handleAuthPending(63000, 5000));
  fsm.tick(64998);
  CHECK(fsm.state() == GateState::COOLDOWN);
  fsm.tick(64999);
  CHECK(fsm.state() == GateState::IDLE);
  CHECK(!fsm.isRelayOn());
  CHECK(fsm.handleAuthPending(65000, 5000));
}

void testRelayFailsafeIsExactlyOnce() {
  static std::vector<std::string> emitted;
  static int relay_off_calls = 0;
  emitted.clear();
  relay_off_calls = 0;
  sgk::TargetAccessFsm fsm(
      [](bool on) {
        if (!on) ++relay_off_calls;
      },
      [](const char* event, const char*) {
        emitted.emplace_back(event != nullptr ? event : "");
      });
  fsm.begin(0);
  relay_off_calls = 0;
  emitted.clear();
  CHECK(fsm.handleAuthPending(1));
  CHECK(fsm.handleAuthSuccess(2));
  CHECK(fsm.handleSensorTrigger(3, 1000, 2000));
  emitted.clear();

  // The independent hardware timer firing at the exact hold deadline is the
  // normal completion path, not a failsafe failure.
  fsm.handleRelayTimerOff(1003, 2000);
  fsm.tick(1003);
  fsm.handleRelayFailsafeOff(1004, 2000);

  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(relay_off_calls == 1);
  CHECK(emitted.size() == 2);
  CHECK(emitted[0] == "door_close");
  CHECK(emitted[1] == "session_completed");
  CHECK(std::find(emitted.begin(), emitted.end(), "door_close_failsafe") ==
        emitted.end());

  // A genuinely late independent fallback remains an exactly-once failsafe
  // and can never also emit the normal relay-off phase.
  fsm.cleanupToIdle(4000);
  relay_off_calls = 0;
  emitted.clear();
  CHECK(fsm.handleAuthPending(4001));
  CHECK(fsm.handleAuthSuccess(4002));
  CHECK(fsm.handleSensorTrigger(4003, 1000, 2000));
  emitted.clear();
  fsm.handleRelayFailsafeOff(5253, 2000);
  fsm.tick(5253);
  fsm.handleRelayFailsafeOff(5254, 2000);

  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(relay_off_calls == 1);
  CHECK(emitted.size() == 2);
  CHECK(emitted[0] == "door_close_failsafe");
  CHECK(emitted[1] == "session_terminated_failsafe");
  CHECK(std::find(emitted.begin(), emitted.end(), "door_close") ==
        emitted.end());
}

void testNewAuthenticationWaitsForFreshIdleAfterTerminalCooldown() {
  sgk::TargetAccessFsm fsm;
  fsm.begin(1000);
  CHECK(fsm.handleAuthPending(1000, 5000));
  CHECK(!fsm.handleAuthPending(1001, 5000));
  CHECK(fsm.state() == GateState::AUTH_PENDING);
  CHECK(fsm.handleAuthSuccess(2000, 60000, 2000));

  // B cannot replace sensor-waiting A before proof. Rejection preserves A's
  // armed state and its original 62,000 ms deadline.
  CHECK(!fsm.handleAuthPending(12000, 5000));
  CHECK(fsm.state() == GateState::ARMED);
  CHECK(fsm.isArmed());
  fsm.tick(61999);
  CHECK(fsm.state() == GateState::ARMED);
  fsm.tick(62000);
  CHECK(fsm.state() == GateState::IDLE);

  // A fresh IDLE may authenticate, but RELAY_HOLD and COOLDOWN reject every
  // new attempt until relay OFF and terminal cooldown are complete.
  CHECK(fsm.handleAuthPending(62001, 5000));
  CHECK(fsm.handleAuthSuccess(62002, 60000, 2000));
  CHECK(fsm.handleSensorTrigger(62003, 1000, 2000));
  CHECK(fsm.state() == GateState::RELAY_HOLD);
  CHECK(!fsm.handleAuthPending(62004, 5000));
  fsm.handleRelayTimerOff(63003, 2000);
  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(!fsm.handleAuthPending(63004, 5000));
  fsm.tick(65002);
  CHECK(fsm.state() == GateState::COOLDOWN);
  fsm.tick(65003);
  CHECK(fsm.state() == GateState::IDLE);
  CHECK(fsm.handleAuthPending(65004, 5000));
}

void testDedicatedManualRemoteRegression() {
  static bool last_relay_on = false;
  static std::string last_event_name;
  static std::string last_event_msg;
  last_relay_on = false;

  sgk::TargetAccessFsm fsm(
      [](bool on) { last_relay_on = on; },
      [](const char* event, const char* message) {
        last_event_name = event != nullptr ? event : "";
        last_event_msg = message != nullptr ? message : "";
      });

  fsm.begin(1000);
  CHECK(fsm.state() == GateState::IDLE);
  CHECK(fsm.otaSafeState() == OtaSafeState::SAFE);

  // 1. Manual remote open from IDLE succeeds
  CHECK(fsm.handleManualRemoteOpen(1000, 1000, 2000));
  CHECK(fsm.state() == GateState::RELAY_HOLD);
  CHECK(fsm.isRelayOn());
  CHECK(last_relay_on);
  CHECK(last_event_name == "relay_on_manual");
  CHECK(fsm.otaSafeState() == OtaSafeState::RELAY_ACTIVE);

  // 2. Re-trigger while RELAY_HOLD fails closed
  CHECK(!fsm.handleManualRemoteOpen(1500, 1000, 2000));
  CHECK(last_event_name == "manual_open_rejected_not_idle");
  CHECK(fsm.isRelayOn());

  // 3. Tick to COOLDOWN
  fsm.tick(2001);
  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(!fsm.isRelayOn());
  CHECK(!last_relay_on);

  // 4. Re-trigger while COOLDOWN fails closed
  CHECK(!fsm.handleManualRemoteOpen(2500, 1000, 2000));
  CHECK(last_event_name == "manual_open_rejected_not_idle");

  // 5. Return to IDLE
  fsm.tick(4002);
  CHECK(fsm.state() == GateState::IDLE);
  CHECK(fsm.otaSafeState() == OtaSafeState::SAFE);
}

void testAdversarialSignaturesAndLowS() {
  uint8_t zero_r[32] = {};
  CHECK(!sgk::TargetAclManager::isValidR(zero_r));

  uint8_t low_s[32] = {0x01};
  CHECK(sgk::TargetAclManager::isLowS(low_s));

  // High-S (> half n)
  uint8_t high_s[32] = {
      0x7F, 0xFF, 0xFF, 0xFF, 0x80, 0x00, 0x00, 0x00, 0x7F, 0xFF, 0xFF,
      0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xDE, 0x73, 0x7D, 0x56, 0xD3, 0x8B,
      0xCE, 0x42, 0x79, 0xDC, 0x65, 0x61, 0x7E, 0x31, 0x92, 0xA9};
  CHECK(!sgk::TargetAclManager::isLowS(high_s));
}

void testCrossDoorAndStaleLeaseReplay() {
  MemoryStorage storage;
  sgk::TargetAclManager acl_manager(&storage);
  const auto door_A = canonicalDoor();

  auto door_B = door_A;
  door_B[0] ^= 0xFF;

  CHECK(acl_manager.begin(door_A, 1000));

  const auto signer_pubkey_bytes = hex(
      "047cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc4766997807775510"
      "db8ed040293d9ac69f7430dbba7dade63ce982299e04b79d227873d1");
  std::array<uint8_t, 65> signer_pubkey{};
  std::copy(signer_pubkey_bytes.begin(), signer_pubkey_bytes.end(),
            signer_pubkey.begin());
  acl_manager.setSignerPublicKey(signer_pubkey);
  acl_manager.setExpectedSigningKeyId(0x07);

  const auto acl_payload = hex(
      "53474b41434c3031000100112233445566778899aabbccddeeff000000000000002a000000"
      "006a6d3700000000006a6d3700000000006a6d45100000038400010001000000070001aabb"
      "ccddeeff00112233445566778899046b17d1f2e12c4247f8bce6e563a440f277037d812deb"
      "33a0f4a13945d898c2964fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb640"
      "6837bf51f50100000001000000006a6d3700000000006a94c4000001000113cdf7246422ab"
      "07576d0328bfe313db997c5d2689df26657b2ec338e690d4f11f2b0f9c7c6dfdc364cad779"
      "162817496b68139c67e38cc51a02aa255870ef8b");

  sgk::TargetAclManager acl_manager_B(&storage);
  acl_manager_B.setSignerPublicKey(signer_pubkey);
  acl_manager_B.setExpectedSigningKeyId(0x07);
  acl_manager_B.begin(door_B, 1000);
  CHECK(acl_manager_B.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                     1000, 1785542400) == sgk::ResultReason::kMalformed);
}

class TestQueueStorage final : public sgk::OfflineQueueStorage {
 public:
  bool saveRecord(size_t slot, const sgk::CanonicalEvent& event) override {
    if (slot >= sgk::OfflineEventQueue::kCapacity || fail_save_record_) return false;
    records_[slot] = event;
    record_valid_[slot] = true;
    return true;
  }

  bool readRecord(size_t slot, sgk::CanonicalEvent* event) override {
    if (slot >= sgk::OfflineEventQueue::kCapacity || !record_valid_[slot] ||
        event == nullptr) {
      return false;
    }
    *event = records_[slot];
    return true;
  }

  bool saveMetaRecord(uint8_t meta_slot, const sgk::QueueMetaRecord& meta) override {
    if (meta_slot > 1 || fail_save_meta_) return false;
    if (meta_slot == 0) { meta0_ = meta; meta0_valid_ = true; }
    else { meta1_ = meta; meta1_valid_ = true; }
    return true;
  }

  bool readMetaRecord(uint8_t meta_slot, sgk::QueueMetaRecord* meta) override {
    if (meta_slot > 1 || meta == nullptr) return false;
    if (meta_slot == 0 && meta0_valid_) { *meta = meta0_; return true; }
    if (meta_slot == 1 && meta1_valid_) { *meta = meta1_; return true; }
    return false;
  }

  bool clearStorage() override {
    meta0_valid_ = false;
    meta1_valid_ = false;
    record_valid_.fill(false);
    records_.fill(sgk::CanonicalEvent{});
    return true;
  }

  std::array<sgk::CanonicalEvent, sgk::OfflineEventQueue::kCapacity> records_{};
  std::array<bool, sgk::OfflineEventQueue::kCapacity> record_valid_{};
  sgk::QueueMetaRecord meta0_{};
  sgk::QueueMetaRecord meta1_{};
  bool meta0_valid_ = false;
  bool meta1_valid_ = false;
  bool fail_save_record_ = false;
  bool fail_save_meta_ = false;
};

void testOfflineEventQueue() {
  sgk::OfflineEventQueue queue;
  CHECK(queue.isEmpty());
  CHECK(queue.size() == 0);

  CHECK(queue.pushEvent("door_open", "Local Auth Success", 1000, 1, "target_1", "boot_1", 1));
  CHECK(queue.pushEvent("door_close", "Relay Hold Expired", 2000, 2, "target_1", "boot_1", 1));
  CHECK(queue.size() == 2);

  sgk::CanonicalEvent front{};
  // 1. Publish failure retention: peekFront returns front event without removal
  CHECK(queue.peekFront(&front));
  CHECK(std::string(front.event_type) == "door_open");
  CHECK(queue.size() == 2);

  sgk::Event compatibility_event{};
  compatibility_event.credential_id.fill(0xff);
  CHECK(queue.peek(&compatibility_event));
  CHECK(std::all_of(compatibility_event.credential_id.begin(),
                    compatibility_event.credential_id.end(),
                    [](uint8_t value) { return value == 0; }));

  // 2. Publish success: popFront removes front event
  CHECK(queue.popFront(&front));
  CHECK(std::string(front.event_type) == "door_open");
  CHECK(queue.size() == 1);

  CHECK(queue.popFront(&front));
  CHECK(std::string(front.event_type) == "door_close");
  CHECK(queue.isEmpty());
}

void testOfflineEventQueueExactEnvelopePreservation() {
  sgk::OfflineEventQueue queue;
  CHECK(queue.pushEvent("auth_verified_armed", "Proof Verified: Target Armed", 12345, 99,
                        "target_c6_01", "boot_guid_abc", 42));

  sgk::CanonicalEvent evt{};
  CHECK(queue.peekFront(&evt));
  CHECK(std::string(evt.event_type) == "auth_verified_armed");
  CHECK(std::string(evt.detail) == "Proof Verified: Target Armed");
  CHECK(evt.monotonic_ms == 12345);
  CHECK(evt.sequence == 99);
  CHECK(std::string(evt.target_ref) == "target_c6_01");
  CHECK(std::string(evt.source_boot_id) == "boot_guid_abc");
  CHECK(evt.boot_count == 42);
}

void testOfflineEventQueueRebootRestoreAndCorruptRejection() {
  TestQueueStorage storage;
  {
    sgk::OfflineEventQueue queue1(&storage);
    queue1.pushEvent("event_1", "detail_1", 1000, 1, "target_1", "boot_1", 1);
    queue1.pushEvent("event_2", "detail_2", 2000, 2, "target_1", "boot_1", 1);
  }

  // Simulate reboot with queue2 reading same storage
  sgk::OfflineEventQueue queue2(&storage);
  queue2.begin();
  CHECK(queue2.size() == 2);

  sgk::CanonicalEvent evt1{}, evt2{};
  CHECK(queue2.popFront(&evt1));
  CHECK(std::string(evt1.event_type) == "event_1");
  CHECK(queue2.popFront(&evt2));
  CHECK(std::string(evt2.event_type) == "event_2");

  // Re-populate and corrupt record 1 CRC
  {
    sgk::OfflineEventQueue queue3(&storage);
    queue3.pushEvent("valid_event", "valid", 3000, 3, "target_1", "boot_1", 1);
    queue3.pushEvent("corrupt_event", "corrupt", 4000, 4, "target_1", "boot_1", 1);
  }
  // Intentionally invalidate CRC of record 1
  storage.records_[1].crc32 = 0xDEADBEEF;

  sgk::OfflineEventQueue queue4(&storage);
  queue4.begin();
  // Valid event loaded, corrupt record rejected
  CHECK(queue4.size() == 1);
  CHECK(queue4.tornRecoveryCount() == 1);
  sgk::CanonicalEvent restored{};
  CHECK(queue4.peekFront(&restored));
  CHECK(std::string(restored.event_type) == "valid_event");
}

void testOfflineEventQueuePersistenceFailureInterlock() {
  TestQueueStorage storage;
  sgk::OfflineEventQueue queue(&storage);
  queue.begin();

  // 1. Simulate record save failure
  storage.fail_save_record_ = true;
  CHECK(!queue.pushEvent("failed_event", "should_not_mutate_ram", 1000, 1));
  CHECK(queue.isEmpty());
  CHECK(queue.size() == 0);

  // 2. Restore record save, simulate meta save failure
  storage.fail_save_record_ = false;
  storage.fail_save_meta_ = true;
  CHECK(!queue.pushEvent("failed_meta_event", "should_not_mutate_ram", 2000, 2));
  CHECK(queue.isEmpty());
  CHECK(queue.size() == 0);
}
void testOfflineEventQueueBoundedOverflowAndGap() {
  sgk::OfflineEventQueue queue;
  for (uint64_t i = 1; i <= 11; ++i) {
    char event_name[32] = {};
    std::snprintf(event_name, sizeof(event_name), "evt_%llu", static_cast<unsigned long long>(i));
    queue.pushEvent(event_name, "overflow_test", static_cast<uint64_t>(1000 + i), i);
  }

  CHECK(queue.size() == 8);
  CHECK(queue.overflowCount() == 6); // 3 overflows x 2 dropped per overflow

  sgk::CanonicalEvent evt{};
  CHECK(queue.peekFront(&evt));
  CHECK(std::string(evt.event_type) == "evt_7");

  // Pop evt_7 and evt_8 to reach first gap event
  CHECK(queue.popFront(&evt)); // evt_7
  CHECK(queue.popFront(&evt)); // evt_8
  CHECK(queue.popFront(&evt)); // gap_evt1
  CHECK(evt.is_canonical == 0);
  CHECK(evt.schema_version == sgk::kCanonicalEventSchemaV1);
  CHECK(sgk::isValidCanonicalEventRecord(evt));
  CHECK(evt.event_id[0] == '\0');
  CHECK(std::string(evt.event_type) == "queue_overflow");
  CHECK(std::string(evt.detail).find("dropped seq 1-2") != std::string::npos);
  CHECK(queue.popFront(&evt)); // evt_9 must remain reachable after the gap.
  CHECK(std::string(evt.event_type) == "evt_9");
}



void testOfflineEventQueueOverflowGapRebootsAndDrains() {
  TestQueueStorage storage;
  {
    sgk::OfflineEventQueue queue1(&storage);
    queue1.begin();
    for (uint64_t i = 1; i <= 9; ++i) {
      char event_name[32] = {};
      std::snprintf(event_name, sizeof(event_name), "evt_%llu",
                    static_cast<unsigned long long>(i));
      CHECK(queue1.pushEvent(event_name, "durable_overflow_test", 2000 + i,
                             i, "target_1", "boot_1", 7));
    }
    CHECK(queue1.size() == sgk::OfflineEventQueue::kCapacity);
    CHECK(queue1.overflowCount() == 2);
  }

  sgk::OfflineEventQueue queue2(&storage);
  queue2.begin();
  CHECK(queue2.size() == sgk::OfflineEventQueue::kCapacity);
  CHECK(queue2.tornRecoveryCount() == 0);

  const std::vector<std::string> expected = {
      "evt_3", "evt_4", "evt_5", "evt_6", "evt_7", "evt_8",
      "queue_overflow", "evt_9"};
  for (const std::string& event_type : expected) {
    sgk::CanonicalEvent restored{};
    CHECK(queue2.peekFront(&restored));
    CHECK(sgk::isValidCanonicalEventRecord(restored));
    CHECK(std::string(restored.event_type) == event_type);
    if (event_type == "queue_overflow") {
      char key_id[sgk::kAccessEvidenceKeyIdCapacity] = {};
      uint8_t tag[sgk::kAccessEvidenceTagSize] = {};
      char credential_ref[sgk::kAccessEventCredentialRefCapacity] = {};
      CHECK(restored.is_canonical == 0);
      CHECK(restored.event_id[0] == '\0');
      CHECK(!sgk::canonicalEventAccessAuth(restored, key_id, tag,
                                           credential_ref));
      CHECK(std::string(restored.detail).find("dropped seq 1-2") !=
            std::string::npos);
    }
    CHECK(queue2.popFront());
  }
  CHECK(queue2.isEmpty());
}


void testOfflineEventQueueWrappedHeadSurvivesRepeatedReboot() {
  TestQueueStorage storage;
  {
    sgk::OfflineEventQueue queue1(&storage);
    queue1.begin();
    for (uint64_t i = 1; i <= sgk::OfflineEventQueue::kCapacity; ++i) {
      char event_name[32] = {};
      std::snprintf(event_name, sizeof(event_name), "evt_%llu",
                    static_cast<unsigned long long>(i));
      CHECK(queue1.pushEvent(event_name, "wrapped_head_test", 3000 + i, i,
                             "target_1", "boot_1", 9));
    }

    sgk::CanonicalEvent popped{};
    CHECK(queue1.popFront(&popped));
    CHECK(std::string(popped.event_type) == "evt_1");
    CHECK(queue1.pushEvent("evt_9", "wrapped_tail_test", 3009, 9,
                           "target_1", "boot_1", 9));
  }

  // The first reboot restores a full ring whose durable head and tail are both
  // physical slot 1. Popping evt_2 must commit head=2 without compacting RAM.
  {
    sgk::OfflineEventQueue queue2(&storage);
    queue2.begin();
    CHECK(queue2.size() == sgk::OfflineEventQueue::kCapacity);
    CHECK(queue2.tornRecoveryCount() == 0);
    sgk::CanonicalEvent popped{};
    CHECK(queue2.popFront(&popped));
    CHECK(std::string(popped.event_type) == "evt_2");
  }

  // A second reboot must not replay evt_2 or lose the wrapped evt_9 tail.
  sgk::OfflineEventQueue queue3(&storage);
  queue3.begin();
  CHECK(queue3.size() == sgk::OfflineEventQueue::kCapacity - 1);
  CHECK(queue3.tornRecoveryCount() == 0);
  for (uint64_t i = 3; i <= 9; ++i) {
    sgk::CanonicalEvent restored{};
    CHECK(queue3.popFront(&restored));
    CHECK(std::string(restored.event_type) ==
          "evt_" + std::to_string(i));
  }
  CHECK(queue3.isEmpty());

  sgk::OfflineEventQueue queue4(&storage);
  queue4.begin();
  CHECK(queue4.isEmpty());
  CHECK(queue4.tornRecoveryCount() == 0);
}



void testOfflineEventQueueFullQueuePowerLossOverwriting() {
  TestQueueStorage storage;
  sgk::OfflineEventQueue queue1(&storage);
  queue1.begin();

  // Fill queue to capacity (8 events, generations 1..8)
  for (uint64_t i = 1; i <= 8; ++i) {
    char name[32] = {};
    std::snprintf(name, sizeof(name), "evt_%llu", static_cast<unsigned long long>(i));
    CHECK(queue1.pushEvent(name, "fill", static_cast<uint64_t>(1000 + i), i));
  }
  CHECK(queue1.size() == 8);

  // Now fail meta save to simulate power-loss / meta commit abort mid-overwrite
  storage.fail_save_meta_ = true;
  // pushEvent writes slot 0 (overwriting evt_1 with future_evt_9, generation 9), but fails meta save (meta generation remains 8)
  CHECK(!queue1.pushEvent("future_evt_9", "overwrites_slot_0", 2000, 9));

  // Simulate reboot: read from storage using new queue2
  sgk::OfflineEventQueue queue2(&storage);
  queue2.begin();

  // Selected meta generation is 8.
  // Slot 0 has overwritten record with generation 9 > selected_meta.generation (8).
  // begin() stops reading at slot 0 because generation 9 > 8.
  sgk::CanonicalEvent front{};
  // The overwritten record (future_evt_9) must NOT be restored/replayed under old meta!
  CHECK(!queue2.peekFront(&front));
  CHECK(queue2.isEmpty());
  CHECK(queue2.tornRecoveryCount() == 1);
}

void testAuthAbortAndDisconnectFlow() {
  static std::string last_event;
  sgk::TargetAccessFsm fsm(
      [](bool) {},
      [](const char* event, const char*) {
        last_event = event != nullptr ? event : "";
      });

  fsm.begin(1000);
  CHECK(fsm.state() == GateState::IDLE);

  // 1. Abort while IDLE -> returns false, stays IDLE
  CHECK(!fsm.handleAuthAbort(1000, "disconnect"));
  CHECK(fsm.state() == GateState::IDLE);

  // 2. Abort while AUTH_PENDING -> transitions to IDLE immediately
  CHECK(fsm.handleAuthPending(1000, 5000));
  CHECK(fsm.state() == GateState::AUTH_PENDING);
  CHECK(fsm.handleAuthAbort(1200, "auth_disconnected"));
  CHECK(fsm.state() == GateState::IDLE);
  CHECK(last_event == "auth_disconnected");

  // 3. Verified ARMED passage is NOT aborted by disconnect
  CHECK(fsm.handleAuthPending(2000, 5000));
  CHECK(fsm.handleAuthSuccess(2500, 60000, 2000));
  CHECK(fsm.state() == GateState::ARMED);
  CHECK(!fsm.handleAuthAbort(2700, "auth_disconnected"));
  CHECK(fsm.state() == GateState::ARMED);

  // 4. Active RELAY_HOLD is NOT aborted by disconnect
  CHECK(fsm.handleSensorTrigger(3000, 1000, 2000));
  CHECK(fsm.state() == GateState::RELAY_HOLD);
  CHECK(!fsm.handleAuthAbort(3200, "auth_disconnected"));
  CHECK(fsm.state() == GateState::RELAY_HOLD);
}

void testAuthPendingStateFlow() {
  static bool last_relay_on = false;
  static std::string last_event_name;

  sgk::TargetAccessFsm fsm(
      [](bool on) { last_relay_on = on; },
      [](const char* event, const char* message) {
        (void)message;
        last_event_name = event != nullptr ? event : "";
      });

  fsm.begin(1000);
  CHECK(fsm.state() == GateState::IDLE);

  // 1. handleAuthSuccess from IDLE must be rejected!
  CHECK(!fsm.handleAuthSuccess(1000, 60000, 2000));
  CHECK(last_event_name == "auth_open_rejected");

  // 2. Enter AUTH_PENDING from IDLE
  CHECK(fsm.handleAuthPending(1000, 5000));
  CHECK(fsm.state() == GateState::AUTH_PENDING);
  CHECK(fsm.otaSafeState() == OtaSafeState::ACCESS_SESSION_ACTIVE);
  CHECK(last_event_name == "auth_pending");

  // 3. Auth success while AUTH_PENDING transitions to ARMED (arms target, relay stays OFF!)
  CHECK(fsm.handleAuthSuccess(1500, 60000, 2000));
  CHECK(fsm.state() == GateState::ARMED);
  CHECK(fsm.isArmed());
  CHECK(!fsm.isRelayOn());
  CHECK(!last_relay_on);
  CHECK(last_event_name == "auth_verified_armed");

  // 4. A new ClientHello cannot replace a verified sensor-waiting session.
  CHECK(!fsm.handleAuthPending(1600, 5000));
  CHECK(fsm.state() == GateState::ARMED);
  CHECK(fsm.isArmed());
  CHECK(!fsm.isRelayOn());

  // 5. Passage sensor trigger while ARMED transitions to RELAY_HOLD (turns relay ON!)
  CHECK(fsm.handleSensorTrigger(2000, 1000, 2000));
  CHECK(fsm.state() == GateState::RELAY_HOLD);
  CHECK(fsm.isRelayOn());
  CHECK(last_relay_on);
  CHECK(last_event_name == "relay_on_sensor");

  // 6. Failsafe off during RELAY_HOLD transitions to COOLDOWN (never cleanup directly to IDLE!)
  fsm.handleRelayFailsafeOff(2500, 2000);
  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(!fsm.isRelayOn());
  CHECK(!last_relay_on);
  CHECK(last_event_name == "session_terminated_failsafe");

  // 7. Reset and test AUTH_PENDING timeout
  fsm.cleanupToIdle(3000);
  CHECK(fsm.state() == GateState::IDLE);

  CHECK(fsm.handleAuthPending(3000, 5000));
  CHECK(fsm.state() == GateState::AUTH_PENDING);

  // Tick past timeout
  fsm.tick(8001);
  CHECK(fsm.state() == GateState::IDLE);
  CHECK(last_event_name == "session_terminated");
  CHECK(fsm.otaSafeState() == OtaSafeState::SAFE);
}

void testProtocolDisconnectHandoff() {
  SequenceRandom random = canonicalRandom();
  FakeVerifier proof_verifier(sgk::ResultReason::kOk);
  const auto door_A = canonicalDoor();

  EventRecorder event_sink;
  FakeAuthControlGate auth_control;

  // Case 1: Pre-verification disconnect emits ACCESS_GATT_FAILED & ACCESS_SESSION_TERMINATED
  {
    sgk::ProtocolCore protocol(random, proof_verifier, door_A, &event_sink,
                               &auth_control);
    protocol.initialize();
    protocol.setEnabled(true);

    sgk::ConnectionToken owner;
    protocol.connect(1, 1000, &owner);
    const auto client = hello();
    send(protocol, sgk::MessageType::kClientHello, client.data(), client.size(),
         1000, 501);

    event_sink.events.clear();
    protocol.disconnect(owner, 1100);
    bool has_failed = false;
    bool has_terminated = false;
    for (const auto& e : event_sink.events) {
      if (e.code == sgk::EventCode::kAccessGattFailed) has_failed = true;
      if (e.code == sgk::EventCode::kAccessSessionTerminated) has_terminated = true;
    }
    CHECK(has_failed);
    CHECK(has_terminated);
  }

  // Case 2: Post-proof completion disconnect hands off to Target FSM without failure events!
  {
    auto random_post = canonicalRandom();
    sgk::ProtocolCore protocol2(random_post, proof_verifier, door_A,
                                &event_sink, &auth_control);
    protocol2.initialize();
    protocol2.setEnabled(true);

    sgk::ConnectionToken owner2;
    protocol2.connect(2, 2000, &owner2);

    const auto client = hello();
    send(protocol2, sgk::MessageType::kClientHello, client.data(), client.size(), 2000, 502);

    const auto valid_proof = proof(protocol2.sessionId());
    send(protocol2, sgk::MessageType::kProof, valid_proof.data(), valid_proof.size(), 2100, 11, 2);

    CHECK(protocol2.state() == sgk::SessionState::kCompleted);

    event_sink.events.clear();
    protocol2.disconnect(owner2, 2200);

    // On post-proof completion disconnect, NO failure terminal event must be emitted!
    bool has_failed = false;
    bool has_terminated = false;
    for (const auto& e : event_sink.events) {
      if (e.code == sgk::EventCode::kAccessGattFailed) has_failed = true;
      if (e.code == sgk::EventCode::kAccessSessionTerminated) has_terminated = true;
    }
    CHECK(!has_failed);
    CHECK(!has_terminated);
  }
}

void testCommittedActionSurvivesResultTransportFailure() {
  for (const bool subscribe_to_result : {false, true}) {
    auto random = canonicalRandom();
    FakeVerifier verifier(sgk::ResultReason::kOk);
    EventRecorder downstream;
    sgk::LocalGattLifecycleBridge bridge(&downstream);
    FakeAuthControlGate control;
    sgk::ProtocolCore protocol(random, verifier, canonicalDoor(), &bridge,
                               &control);
    CHECK(protocol.initialize());
    protocol.setEnabled(true);

    sgk::ConnectionToken owner;
    CHECK(protocol.connect(subscribe_to_result ? 31 : 30, 5000, &owner));
    const auto client = hello();
    CHECK(send(protocol, sgk::MessageType::kClientHello, client.data(),
               client.size(), 5000, 502, 1, owner));
    const auto handshake_outputs = drain(protocol);
    CHECK(handshake_outputs.size() == 2);

    const auto valid_proof = proof(protocol.sessionId());
    CHECK(send(protocol, sgk::MessageType::kProof, valid_proof.data(),
               valid_proof.size(), 5100, 502, 2, owner));
    CHECK(protocol.state() == sgk::SessionState::kCompleted);
    CHECK(bridge.hasVerifiedSession());

    sgk::OutputMessage result{};
    CHECK(protocol.popOutput(&result));
    CHECK(result.type == sgk::MessageType::kResult);
    sgk::AdapterState adapter;
    CHECK(adapter.acceptConnection(owner));

    if (!subscribe_to_result) {
      // Production drainOutputs treats this missing subscription as a
      // transport failure after the action has already been committed.
      CHECK(!adapter.stageOutput(result));
    } else {
      CHECK(adapter.setSubscribed(owner.handle, sgk::MessageType::kResult,
                                  true));
      CHECK(adapter.stageOutput(result));
      uint8_t frame[sgk::kAdapterFrameCapacity] = {};
      size_t written = 0;
      sgk::MessageType type = sgk::MessageType::kError;
      sgk::IndicationToken token{};
      CHECK(adapter.beginNextIndication(247, 5101, frame, sizeof(frame),
                                        &written, &type, &token));
      CHECK(written != 0);
      CHECK(adapter.confirmIndication(token, type, false) ==
            sgk::IndicationResult::kAborted);
    }

    const size_t event_count_before_abort = downstream.events.size();
    protocol.abortTransport(owner, sgk::ResultReason::kInternalFailClosed,
                            5102);
    CHECK(protocol.state() == sgk::SessionState::kIdle);
    CHECK(bridge.hasVerifiedSession());
    CHECK(control.abort_calls == 0);
    CHECK(downstream.events.size() == event_count_before_abort);

    // The independent Target FSM may still complete the committed action. Its
    // lifecycle must retain the verified actor despite RESULT transport loss.
    CHECK(bridge.emitArmed(5103));
    CHECK(bridge.emitSensorDetected(5104));
    CHECK(bridge.emitRelayOn(5105));
    CHECK(bridge.emitRelayOff(6105, false));
    CHECK(bridge.emitCompleted(6106));
    CHECK(!bridge.hasVerifiedSession());
    for (size_t index = downstream.events.size() - 5;
         index < downstream.events.size(); ++index) {
      CHECK(!std::all_of(downstream.events[index].credential_id.begin(),
                         downstream.events[index].credential_id.end(),
                         [](uint8_t value) { return value == 0; }));
      CHECK(downstream.events[index].session_id ==
            downstream.events[event_count_before_abort - 1].session_id);
    }
  }
}

void testInvalidTypedCanonicalRecordQuarantine() {
  sgk::OfflineEventQueue queue;

  sgk::CanonicalEvent invalid_evt{};
  invalid_evt.is_canonical = 1;
  // Leave event_id empty -> must fail validation and push returns false!
  CHECK(!queue.push(invalid_evt));
  CHECK(queue.isEmpty());
}

void testStoredAclValidationOnBoot() {
  MemoryStorage storage;
  const auto door_A = canonicalDoor();

  // Write corrupt payload to slot 0 and valid generation record
  uint8_t corrupt_payload[200] = {0x53, 0x47, 0x4b, 0x41, 0x43, 0x4c, 0x30, 0x31};
  storage.saveSlot(0, corrupt_payload, sizeof(corrupt_payload));

  sgk::GenerationRecord gen{};
  gen.magic = sgk::kGenerationMagic;
  gen.record_schema = 1;
  gen.generation = 1;
  gen.active_slot = 0;
  gen.acl_version = 1;
  gen.crc32 = sgk::TargetAclManager::computeCrc32(
      reinterpret_cast<const uint8_t*>(&gen),
      offsetof(sgk::GenerationRecord, crc32));
  storage.saveGenerationRecord(0, gen);

  sgk::TargetAclManager acl_manager(&storage);
  const auto signer_pubkey_bytes = hex(
      "047cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc4766997807775510"
      "db8ed040293d9ac69f7430dbba7dade63ce982299e04b79d227873d1");
  std::array<uint8_t, 65> signer_pubkey{};
  std::copy(signer_pubkey_bytes.begin(), signer_pubkey_bytes.end(),
            signer_pubkey.begin());
  acl_manager.setSignerPublicKey(signer_pubkey);

  // begin() must validate stored snapshot with validateSnapshotSemantics & verifySnapshotSignature
  CHECK(acl_manager.begin(door_A, 1000));
  // Corrupt payload fails validation -> hasActiveAcl() must be false!
  CHECK(!acl_manager.hasActiveAcl());
}

void testAbsentOrInvalidSignerKey() {
  MemoryStorage storage;
  sgk::TargetAclManager acl_manager(&storage);
  const auto door_A = canonicalDoor();
  acl_manager.begin(door_A, 1000);

  CHECK(!acl_manager.isSignerPublicKeySet());

  const auto acl_payload = hex(
      "53474b41434c3031000100112233445566778899aabbccddeeff000000000000002a000000"
      "006a6d3700000000006a6d3700000000006a6d45100000038400010001000000070001aabb"
      "ccddeeff00112233445566778899046b17d1f2e12c4247f8bce6e563a440f277037d812deb"
      "33a0f4a13945d898c2964fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb640"
      "6837bf51f50100000001000000006a6d3700000000006a94c4000001000113cdf7246422ab"
      "07576d0328bfe313db997c5d2689df26657b2ec338e690d4f11f2b0f9c7c6dfdc364cad779"
      "162817496b68139c67e38cc51a02aa255870ef8b");

  // Push without signer key must fail closed with kProofInvalid
  CHECK(acl_manager.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                   1000, 1785542400) == sgk::ResultReason::kProofInvalid);

  // Invalid SEC1 header byte (0x02 instead of 0x04) must fail
  std::array<uint8_t, 65> invalid_key{};
  invalid_key[0] = 0x02;
  CHECK(!acl_manager.setSignerPublicKey(invalid_key));
  CHECK(!acl_manager.isSignerPublicKeySet());
}

void testTornGenerationAndBadCrc() {
  MemoryStorage storage;
  const auto door_A = canonicalDoor();

  sgk::GenerationRecord gen{};
  gen.magic = sgk::kGenerationMagic;
  gen.record_schema = 1;
  gen.generation = 1;
  gen.active_slot = 0;
  gen.acl_version = 10;
  gen.high_watermark = 10;
  gen.crc32 = 0xDEADBEEF; // Bad CRC!
  storage.saveGenerationRecord(0, gen);

  sgk::TargetAclManager acl_manager(&storage);
  CHECK(acl_manager.begin(door_A, 1000));
  // Bad CRC generation record must be rejected
  CHECK(!acl_manager.hasActiveAcl());
  CHECK(acl_manager.highWatermark() == 0);
}

void testExpectedSigningKeyIdMismatch() {
  MemoryStorage storage;
  sgk::TargetAclManager acl_manager(&storage);
  const auto door_A = canonicalDoor();
  acl_manager.begin(door_A, 1000);

  const auto signer_pubkey_bytes = hex(
      "047cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc4766997807775510"
      "db8ed040293d9ac69f7430dbba7dade63ce982299e04b79d227873d1");
  std::array<uint8_t, 65> signer_pubkey{};
  std::copy(signer_pubkey_bytes.begin(), signer_pubkey_bytes.end(),
            signer_pubkey.begin());
  acl_manager.setSignerPublicKey(signer_pubkey);

  // Require expected signing key ID = 0x12345678 (fixture key ID is 0x07)
  acl_manager.setExpectedSigningKeyId(0x12345678);

  const auto acl_payload = hex(
      "53474b41434c3031000100112233445566778899aabbccddeeff000000000000002a000000"
      "006a6d3700000000006a6d3700000000006a6d45100000038400010001000000070001aabb"
      "ccddeeff00112233445566778899046b17d1f2e12c4247f8bce6e563a440f277037d812deb"
      "33a0f4a13945d898c2964fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb640"
      "6837bf51f50100000001000000006a6d3700000000006a94c4000001000113cdf7246422ab"
      "07576d0328bfe313db997c5d2689df26657b2ec338e690d4f11f2b0f9c7c6dfdc364cad779"
      "162817496b68139c67e38cc51a02aa255870ef8b");

  CHECK(acl_manager.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                   1000, 1785542400) == sgk::ResultReason::kMalformed);
}

void testRebootLeaseWithoutTrustedTime() {
  MemoryStorage storage;
  sgk::TargetAclManager acl_manager(&storage);
  const auto door_A = canonicalDoor();

  const auto signer_pubkey_bytes = hex(
      "047cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc4766997807775510"
      "db8ed040293d9ac69f7430dbba7dade63ce982299e04b79d227873d1");
  std::array<uint8_t, 65> signer_pubkey{};
  std::copy(signer_pubkey_bytes.begin(), signer_pubkey_bytes.end(),
            signer_pubkey.begin());
  acl_manager.setSignerPublicKey(signer_pubkey);
  acl_manager.setExpectedSigningKeyId(0x07);
  acl_manager.begin(door_A, 1000);

  const auto acl_payload = hex(
      "53474b41434c3031000100112233445566778899aabbccddeeff000000000000002a000000"
      "006a6d3700000000006a6d3700000000006a6d45100000038400010001000000070001aabb"
      "ccddeeff00112233445566778899046b17d1f2e12c4247f8bce6e563a440f277037d812deb"
      "33a0f4a13945d898c2964fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb640"
      "6837bf51f50100000001000000006a6d3700000000006a94c4000001000113cdf7246422ab"
      "07576d0328bfe313db997c5d2689df26657b2ec338e690d4f11f2b0f9c7c6dfdc364cad779"
      "162817496b68139c67e38cc51a02aa255870ef8b");

  CHECK(acl_manager.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                   1000, 1785542400) == sgk::ResultReason::kOk);
  CHECK(acl_manager.hasActiveAcl());
  CHECK(acl_manager.activeAclVersion() == 42);

  // Simulate reboot: create new TargetAclManager on same storage
  sgk::TargetAclManager rebooted_acl_manager(&storage);
  rebooted_acl_manager.setSignerPublicKey(signer_pubkey);
  rebooted_acl_manager.setExpectedSigningKeyId(0x07);

  // On boot with no trusted wall clock, begin() preserves high watermark floor but does NOT set active_ready_ = true
  CHECK(rebooted_acl_manager.begin(door_A, 2000));
  CHECK(rebooted_acl_manager.highWatermark() == 42);
  CHECK(!rebooted_acl_manager.hasActiveAcl());
}

void testGenerationRecordCrcOffsetAndValidReboot() {
  MemoryStorage storage;
  const auto door_A = canonicalDoor();

  sgk::GenerationRecord gen{};
  gen.magic = sgk::kGenerationMagic;
  gen.record_schema = 1;
  gen.generation = 10;
  gen.active_slot = 0;
  gen.acl_version = 42;
  gen.high_watermark = 42;
  gen.crc32 = sgk::TargetAclManager::computeCrc32(
      reinterpret_cast<const uint8_t*>(&gen),
      offsetof(sgk::GenerationRecord, crc32));
  storage.saveGenerationRecord(0, gen);

  sgk::TargetAclManager acl_manager(&storage);
  const auto signer_pubkey_bytes = hex(
      "047cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc4766997807775510"
      "db8ed040293d9ac69f7430dbba7dade63ce982299e04b79d227873d1");
  std::array<uint8_t, 65> signer_pubkey{};
  std::copy(signer_pubkey_bytes.begin(), signer_pubkey_bytes.end(),
            signer_pubkey.begin());
  acl_manager.setSignerPublicKey(signer_pubkey);
  acl_manager.setExpectedSigningKeyId(0x07);

  // Positive valid generation reboot check
  CHECK(acl_manager.begin(door_A, 1000));
  CHECK(acl_manager.highWatermark() == 42);

  // Mutate CRC and verify rejection
  gen.crc32 ^= 0xFFFFFFFF;
  storage.saveGenerationRecord(0, gen);
  sgk::TargetAclManager acl_manager_corrupt(&storage);
  acl_manager_corrupt.setSignerPublicKey(signer_pubkey);
  acl_manager_corrupt.setExpectedSigningKeyId(0x07);
  CHECK(acl_manager_corrupt.begin(door_A, 2000));
  CHECK(acl_manager_corrupt.highWatermark() == 0);
}

void testKeyPresentKeyIdAbsentOrFailClosed() {
  MemoryStorage storage;
  sgk::TargetAclManager acl_manager(&storage);
  const auto door_A = canonicalDoor();

  const auto signer_pubkey_bytes = hex(
      "047cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc4766997807775510"
      "db8ed040293d9ac69f7430dbba7dade63ce982299e04b79d227873d1");
  std::array<uint8_t, 65> signer_pubkey{};
  std::copy(signer_pubkey_bytes.begin(), signer_pubkey_bytes.end(),
            signer_pubkey.begin());
  acl_manager.setSignerPublicKey(signer_pubkey);
  // Expected signing key ID NOT set (0) -> fail closed!
  acl_manager.begin(door_A, 1000);
  CHECK(!acl_manager.hasActiveAcl());

  const auto acl_payload = hex(
      "53474b41434c3031000100112233445566778899aabbccddeeff000000000000002a000000"
      "006a6d3700000000006a6d3700000000006a6d45100000038400010001000000070001aabb"
      "ccddeeff00112233445566778899046b17d1f2e12c4247f8bce6e563a440f277037d812deb"
      "33a0f4a13945d898c2964fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb640"
      "6837bf51f50100000001000000006a6d3700000000006a94c4000001000113cdf7246422ab"
      "07576d0328bfe313db997c5d2689df26657b2ec338e690d4f11f2b0f9c7c6dfdc364cad779"
      "162817496b68139c67e38cc51a02aa255870ef8b");

  // Apply without expected key ID (0) fails closed
  CHECK(acl_manager.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                   1000, 1785542400) == sgk::ResultReason::kProofInvalid);

  // Apply with key ID mismatch (0x1234 != 0x07) fails closed
  acl_manager.setExpectedSigningKeyId(0x1234);
  CHECK(acl_manager.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                   1000, 1785542400) == sgk::ResultReason::kMalformed);

  // Apply with matching key ID (0x07) succeeds
  acl_manager.setExpectedSigningKeyId(0x07);
  CHECK(acl_manager.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                   1000, 1785542400) == sgk::ResultReason::kOk);
  CHECK(acl_manager.hasActiveAcl());
}

void testQueueMetaSemanticCorruptionMutations() {
  TestQueueStorage storage;

  // 1. Semantic corruption: count > kCapacity
  sgk::QueueMetaRecord meta1{};
  meta1.magic = 0x5347514D;
  meta1.schema_version = 1;
  meta1.generation = 1;
  meta1.head = 0;
  meta1.tail = 1;
  meta1.count = static_cast<uint32_t>(sgk::OfflineEventQueue::kCapacity + 1); // > kCapacity
  meta1.crc32 = sgk::OfflineEventQueue::computeCrc32(
      reinterpret_cast<const uint8_t*>(&meta1),
      offsetof(sgk::QueueMetaRecord, crc32));
  storage.saveMetaRecord(0, meta1);

  sgk::OfflineEventQueue queue1(&storage);
  queue1.begin();
  CHECK(queue1.size() == 0); // Meta rejected due to invalid count

  // 2. Semantic corruption: head >= kCapacity
  sgk::QueueMetaRecord meta2{};
  meta2.magic = 0x5347514D;
  meta2.schema_version = 1;
  meta2.generation = 1;
  meta2.head = static_cast<uint32_t>(sgk::OfflineEventQueue::kCapacity); // >= kCapacity
  meta2.tail = 0;
  meta2.count = 0;
  meta2.crc32 = sgk::OfflineEventQueue::computeCrc32(
      reinterpret_cast<const uint8_t*>(&meta2),
      offsetof(sgk::QueueMetaRecord, crc32));
  storage.saveMetaRecord(0, meta2);

  sgk::OfflineEventQueue queue2(&storage);
  queue2.begin();
  CHECK(queue2.size() == 0); // Meta rejected due to invalid head

  // 3. Semantic corruption: tail != (head + count) % kCapacity
  sgk::QueueMetaRecord meta3{};
  meta3.magic = 0x5347514D;
  meta3.schema_version = 1;
  meta3.generation = 1;
  meta3.head = 0;
  meta3.tail = 5; // Should be 2 for count=2!
  meta3.count = 2;
  meta3.crc32 = sgk::OfflineEventQueue::computeCrc32(
      reinterpret_cast<const uint8_t*>(&meta3),
      offsetof(sgk::QueueMetaRecord, crc32));
  storage.saveMetaRecord(0, meta3);

  sgk::OfflineEventQueue queue3(&storage);
  queue3.begin();
  CHECK(queue3.size() == 0); // Meta rejected due to tail mismatch
}

void testOfflineCanonicalEventReplayAndPreservation() {
  TestQueueStorage storage;
  {
    sgk::OfflineEventQueue queue1(&storage);
    queue1.begin();

    sgk::CanonicalEvent canonical_evt{};
    canonical_evt.is_canonical = 1;
    canonical_evt.code = static_cast<uint16_t>(sgk::EventCode::kAccessProofVerified);
    canonical_evt.transport_reason = 0;
    canonical_evt.monotonic_ms = 0x123456789ABCDEF0ULL; // Preserved uint64_t > UINT32_MAX!
    canonical_evt.sequence = 42;
    canonical_evt.attempt = 1;
    std::strncpy(canonical_evt.event_type, "ACCESS_PROOF_VERIFIED", sizeof(canonical_evt.event_type) - 1);
    std::strncpy(canonical_evt.stage_text, "PROOF", sizeof(canonical_evt.stage_text) - 1);
    std::strncpy(canonical_evt.outcome_text, "SUCCEEDED", sizeof(canonical_evt.outcome_text) - 1);
    std::strncpy(canonical_evt.detail,
                 "PROOF_VALID_LEGACY_REASON_REMAINS_LONGER_THAN_32",
                 sizeof(canonical_evt.detail) - 1);

    constexpr char kEventId[] = "12345678-1234-1234-1234-123456789abc";
    constexpr char kSessionId[] = "87654321-4321-4321-4321-cba987654321";
    constexpr char kSourceBootId[] = "abcdef12-3456-7890-abcd-ef1234567890";
    constexpr char kCausationEventId[] = "11223344-5566-7788-9900-aabbccddeeff";
    static_assert(sizeof(kEventId) == sizeof(canonical_evt.event_id),
                  "event ID literal must fill destination including NUL");
    static_assert(sizeof(kSessionId) == sizeof(canonical_evt.session_id),
                  "session ID literal must fill destination including NUL");
    static_assert(sizeof(kSourceBootId) == sizeof(canonical_evt.source_boot_id),
                  "boot ID literal must fill destination including NUL");
    static_assert(sizeof(kCausationEventId) ==
                      sizeof(canonical_evt.causation_event_id),
                  "causation ID literal must fill destination including NUL");
    std::memcpy(canonical_evt.event_id, kEventId, sizeof(kEventId));
    std::memcpy(canonical_evt.session_id, kSessionId, sizeof(kSessionId));
    std::memcpy(canonical_evt.source_boot_id, kSourceBootId,
                sizeof(kSourceBootId));
    std::strncpy(canonical_evt.target_ref, "target_c6_01_ref_12345678", sizeof(canonical_evt.target_ref) - 1);
    canonical_evt.has_causation = 1;
    std::memcpy(canonical_evt.causation_event_id, kCausationEventId,
                sizeof(kCausationEventId));
    CHECK(canonical_evt.event_id[sizeof(canonical_evt.event_id) - 1] == '\0');
    CHECK(canonical_evt.session_id[sizeof(canonical_evt.session_id) - 1] == '\0');
    CHECK(canonical_evt.source_boot_id[
              sizeof(canonical_evt.source_boot_id) - 1] == '\0');
    CHECK(canonical_evt.causation_event_id[
              sizeof(canonical_evt.causation_event_id) - 1] == '\0');

    CHECK(queue1.push(canonical_evt));
    CHECK(queue1.size() == 1);
  }

  // Simulate reboot: create new queue2 reading persistent storage
  sgk::OfflineEventQueue queue2(&storage);
  queue2.begin();
  CHECK(queue2.size() == 1);

  sgk::CanonicalEvent restored{};
  CHECK(queue2.peekFront(&restored));
  CHECK(restored.is_canonical == 1);
  CHECK(restored.monotonic_ms == 0x123456789ABCDEF0ULL); // uint64_t preserved!
  CHECK(std::string(restored.event_type) == "ACCESS_PROOF_VERIFIED");
  CHECK(std::string(restored.stage_text) == "PROOF");
  CHECK(std::string(restored.outcome_text) == "SUCCEEDED");
  CHECK(std::string(restored.detail) ==
        "PROOF_VALID_LEGACY_REASON_REMAINS_LONGER_THAN_32");
  CHECK(std::string(restored.event_id) == "12345678-1234-1234-1234-123456789abc");
  CHECK(std::string(restored.session_id) == "87654321-4321-4321-4321-cba987654321");
  CHECK(std::string(restored.source_boot_id) == "abcdef12-3456-7890-abcd-ef1234567890");
  CHECK(std::string(restored.target_ref) == "target_c6_01_ref_12345678");
  CHECK(restored.has_causation == 1);
  CHECK(std::string(restored.causation_event_id) == "11223344-5566-7788-9900-aabbccddeeff");

  // Publish failure retention test: peekFront retains, popFront dequeues only on publish success
  CHECK(queue2.size() == 1);
  CHECK(queue2.popFront(&restored));
  CHECK(queue2.isEmpty());
}

void testOfflineCanonicalV2CredentialRefOverlay() {
  CHECK(sizeof(sgk::CanonicalEvent) == 368);
  CHECK(offsetof(sgk::CanonicalEvent, detail) == 297);
  CHECK(offsetof(sgk::CanonicalEvent, padding) == 362);
  CHECK(offsetof(sgk::CanonicalEvent, crc32) == 364);

  TestQueueStorage storage;
  sgk::OfflineEventQueue queue1(&storage);
  queue1.begin();
  sgk::CanonicalEvent event{};
  event.is_canonical = 1;
  event.code =
      static_cast<uint16_t>(sgk::EventCode::kAccessSensorDetected);
  event.sequence = 77;
  event.boot_count = 686;
  constexpr char kEventId[] = "12345678-1234-4234-8234-123456789abc";
  constexpr char kSessionId[] = "87654321-4321-4321-8321-cba987654321";
  constexpr char kSourceBootId[] =
      "abcdef12-3456-7890-abcd-ef1234567890";
  std::memcpy(event.event_id, kEventId, sizeof(kEventId));
  std::memcpy(event.session_id, kSessionId, sizeof(kSessionId));
  std::memcpy(event.source_boot_id, kSourceBootId, sizeof(kSourceBootId));
  std::strncpy(event.target_ref, "target_c6_01_ref_12345678",
               sizeof(event.target_ref) - 1);
  std::strncpy(event.event_type, "ACCESS_SENSOR_DETECTED",
               sizeof(event.event_type) - 1);
  std::strncpy(event.stage_text, "SENSOR", sizeof(event.stage_text) - 1);
  std::strncpy(event.outcome_text, "SUCCEEDED",
               sizeof(event.outcome_text) - 1);
  const auto tag_bytes = hex("ee82880739ce2d2ae3a726c641a6dd08");
  uint8_t event_tag[sgk::kAccessEvidenceTagSize] = {};
  std::copy(tag_bytes.begin(), tag_bytes.end(), event_tag);
  CHECK(sgk::setCanonicalV2Detail(
      &event, "SENSOR_THRESHOLD_MET", "k1",
      "c_k1_653b090fafcdaffa677766a2", event_tag));
  CHECK(event.schema_version == sgk::kCanonicalEventSchemaV2);
  CHECK(std::string(sgk::canonicalEventReason(event)) ==
        "SENSOR_THRESHOLD_MET");
  char key_id[sgk::kAccessEvidenceKeyIdCapacity] = {};
  uint8_t decoded_tag[sgk::kAccessEvidenceTagSize] = {};
  char credential_ref[sgk::kAccessEventCredentialRefCapacity] = {};
  CHECK(sgk::canonicalEventAccessAuth(event, key_id, decoded_tag,
                                      credential_ref));
  CHECK(std::string(key_id) == "k1");
  CHECK(std::memcmp(decoded_tag, event_tag, sizeof(event_tag)) == 0);
  CHECK(std::string(credential_ref) ==
        "c_k1_653b090fafcdaffa677766a2");
  CHECK(queue1.push(event));

  // Exact N-1 rollback fixture: the previous reader requires record schema 1,
  // checks the unchanged CRC range, and ignores the padding word. It must be
  // able to replay the reason rather than stopping recovery at this record.
  CHECK(storage.meta1_valid_);
  CHECK(storage.meta1_.schema_version == 1);
  CHECK(storage.meta1_.head == 0);
  CHECK(storage.meta1_.count == 1);
  CHECK(storage.record_valid_[0]);
  const sgk::CanonicalEvent& durable = storage.records_[0];
  const auto legacy_v1_reader_accepts = [](const sgk::CanonicalEvent& value) {
    const uint32_t expected_crc = sgk::OfflineEventQueue::computeCrc32(
        reinterpret_cast<const uint8_t*>(&value),
        offsetof(sgk::CanonicalEvent, crc32));
    if (value.magic != 0x53475145 || value.schema_version != 1 ||
        value.crc32 != expected_crc || value.generation == 0) {
      return false;
    }
    if (value.is_canonical != 1) return true;
    return value.event_id[0] != '\0' && value.session_id[0] != '\0' &&
           value.source_boot_id[0] != '\0' &&
           value.target_ref[0] != '\0' && value.event_type[0] != '\0' &&
           value.stage_text[0] != '\0' &&
           value.outcome_text[0] != '\0' && value.detail[0] != '\0';
  };
  CHECK(durable.schema_version == sgk::kCanonicalEventSchemaV1);
  CHECK(durable.padding == sgk::kCanonicalV2OverlayMarker);
  CHECK(!sgk::canonicalEventAccessAuth(durable, key_id, decoded_tag,
                                       credential_ref));
  CHECK(legacy_v1_reader_accepts(durable));
  CHECK(std::string(durable.detail) == "SENSOR_THRESHOLD_MET");
  sgk::CanonicalEvent runtime_front{};
  CHECK(queue1.peekFront(&runtime_front));
  CHECK(runtime_front.schema_version == sgk::kCanonicalEventSchemaV2);
  CHECK(sgk::canonicalEventAccessAuth(runtime_front, key_id, decoded_tag,
                                      credential_ref));
  CHECK(std::string(credential_ref) ==
        "c_k1_653b090fafcdaffa677766a2");

  sgk::CanonicalEvent following_v1 = event;
  following_v1.schema_version = sgk::kCanonicalEventSchemaV1;
  following_v1.padding = 0;
  following_v1.sequence = 78;
  following_v1.event_id[0] = '2';
  std::memset(following_v1.detail, 0, sizeof(following_v1.detail));
  std::strncpy(following_v1.detail, "FOLLOWING_V1_EVENT",
               sizeof(following_v1.detail) - 1);
  CHECK(queue1.push(following_v1));
  CHECK(storage.meta0_valid_);
  CHECK(storage.meta0_.schema_version == 1);
  CHECK(storage.meta0_.head == 0);
  CHECK(storage.meta0_.count == 2);
  CHECK(storage.record_valid_[1]);
  CHECK(legacy_v1_reader_accepts(storage.records_[0]));
  CHECK(legacy_v1_reader_accepts(storage.records_[1]));
  CHECK(std::string(storage.records_[1].detail) == "FOLLOWING_V1_EVENT");

  sgk::OfflineEventQueue queue2(&storage);
  queue2.begin();
  CHECK(queue2.size() == 2);
  sgk::CanonicalEvent restored{};
  CHECK(queue2.peekFront(&restored));
  CHECK(restored.schema_version == sgk::kCanonicalEventSchemaV2);
  CHECK(std::string(sgk::canonicalEventReason(restored)) ==
        "SENSOR_THRESHOLD_MET");
  CHECK(sgk::canonicalEventAccessAuth(restored, key_id, decoded_tag,
                                      credential_ref));
  CHECK(std::string(credential_ref) ==
        "c_k1_653b090fafcdaffa677766a2");
  CHECK(queue2.popFront());
  CHECK(queue2.peekFront(&restored));
  CHECK(restored.schema_version == sgk::kCanonicalEventSchemaV1);
  CHECK(std::string(restored.detail) == "FOLLOWING_V1_EVENT");

  sgk::CanonicalEvent malformed = event;
  malformed.detail[sgk::kCanonicalV2KeyIdOffset] = 'K';
  CHECK(!queue2.push(malformed));

  sgk::CanonicalEvent missing_tag = event;
  std::memset(missing_tag.detail + sgk::kCanonicalV2AuthTagOffset, 0,
              sgk::kCanonicalV2AuthTagSize);
  CHECK(!sgk::isValidCanonicalEventRecord(missing_tag));

  sgk::CanonicalEvent missing_marker = event;
  missing_marker.padding = 0;
  CHECK(!sgk::isValidCanonicalEventRecord(missing_marker));

  sgk::CanonicalEvent unterminated = event;
  std::memset(unterminated.event_id, 'x', sizeof(unterminated.event_id));
  CHECK(!sgk::isValidCanonicalEventRecord(unterminated));
  CHECK(!queue2.push(unterminated));

  sgk::CanonicalEvent noncanonical{};
  noncanonical.schema_version = sgk::kCanonicalEventSchemaV2;
  std::strncpy(noncanonical.event_type, "legacy_event",
               sizeof(noncanonical.event_type) - 1);
  CHECK(!queue2.push(noncanonical));
}

void testProductionMainAuthAbortWiring() {
  std::ifstream file("src/main.cpp");
  CHECK(file.is_open());
  std::string content((std::istreambuf_iterator<char>(file)),
                      std::istreambuf_iterator<char>());

  size_t grant_pos = content.find("GattServer::setOnAuthGrantCallback");
  size_t abort_pos = content.find("GattServer::setOnAuthAbortCallback");
  CHECK(grant_pos != std::string::npos);
  CHECK(abort_pos != std::string::npos);
  CHECK(abort_pos > grant_pos);
  CHECK(content.find("g_access_fsm.handleAuthAbort(now_ms, \"gatt_auth_aborted\")") != std::string::npos);
}

class MemoryCommandStorage final : public sgk::CommandReplayStorage {
 public:
  std::array<sgk::CommandReplayLedger, 2> ledgers{};
  std::array<bool, 2> present{};
  bool fail_writes = false;

  bool readLedger(uint8_t slot, sgk::CommandReplayLedger* ledger) override {
    if (slot > 1 || ledger == nullptr || !present[slot]) return false;
    *ledger = ledgers[slot];
    return true;
  }
  bool writeLedger(uint8_t slot,
                   const sgk::CommandReplayLedger& ledger) override {
    if (slot > 1 || fail_writes) return false;
    ledgers[slot] = ledger;
    present[slot] = true;
    return true;
  }
};

class FixtureCommandVerifier final : public sgk::CommandSignatureVerifier {
 public:
  bool verify(uint32_t key_id, const std::array<uint8_t, 32>&,
              const std::array<uint8_t, 64>& signature) override {
    return key_id == 7 && signature[0] == 0xa5;
  }
};

sgk::SignedCommandEnvelope fixtureCommand() {
  sgk::SignedCommandEnvelope envelope{};
  envelope.schema_version = 1;
  std::snprintf(envelope.target_id, sizeof(envelope.target_id), "target-a");
  std::snprintf(envelope.tenant_id, sizeof(envelope.tenant_id), "tenant-a");
  std::snprintf(envelope.door_id, sizeof(envelope.door_id), "door-a");
  std::snprintf(envelope.boot_id, sizeof(envelope.boot_id), "boot-a");
  envelope.action = sgk::CommandAction::kManualRemote;
  std::snprintf(envelope.session_id, sizeof(envelope.session_id), "session-a");
  std::snprintf(envelope.nonce, sizeof(envelope.nonce), "nonce-a");
  envelope.issued_at = 1800000000;
  envelope.expires_at = 1800000060;
  envelope.key_id = 7;
  envelope.signature[0] = 0xa5;
  return envelope;
}

void testSignedCommandDurableReplayAndMutations() {
  MemoryCommandStorage storage;
  FixtureCommandVerifier verifier;
  sgk::TargetCommandSecurity security(&storage, &verifier);
  CHECK(security.begin("target-a", "tenant-a", "door-a", "boot-a", 7));
  auto command = fixtureCommand();
  CHECK(security.authorize(command, 1800000001, true) ==
        sgk::CommandResult::kAccepted);
  CHECK(security.markCompleted(command));
  CHECK(security.authorize(command, 1800000002, true) ==
        sgk::CommandResult::kDuplicateCompleted);

  sgk::TargetCommandSecurity rebooted(&storage, &verifier);
  CHECK(rebooted.begin("target-a", "tenant-a", "door-a", "boot-a", 7));
  CHECK(rebooted.authorize(command, 1800000002, true) ==
        sgk::CommandResult::kDuplicateCompleted);

  auto forged = command;
  std::snprintf(forged.nonce, sizeof(forged.nonce), "nonce-forged");
  forged.signature[0] = 0;
  CHECK(rebooted.authorize(forged, 1800000002, true) ==
        sgk::CommandResult::kBadSignature);
  auto cross_target = command;
  std::snprintf(cross_target.nonce, sizeof(cross_target.nonce), "nonce-cross");
  std::snprintf(cross_target.target_id, sizeof(cross_target.target_id),
                "target-b");
  CHECK(rebooted.authorize(cross_target, 1800000002, true) ==
        sgk::CommandResult::kIdentityMismatch);
  auto wrong_boot = command;
  std::snprintf(wrong_boot.nonce, sizeof(wrong_boot.nonce), "nonce-boot");
  std::snprintf(wrong_boot.boot_id, sizeof(wrong_boot.boot_id), "boot-old");
  CHECK(rebooted.authorize(wrong_boot, 1800000002, true) ==
        sgk::CommandResult::kBootMismatch);
  auto stale = command;
  std::snprintf(stale.nonce, sizeof(stale.nonce), "nonce-stale");
  stale.issued_at = 1799999800;
  stale.expires_at = 1799999860;
  CHECK(rebooted.authorize(stale, 1800000002, true) ==
        sgk::CommandResult::kExpired);
  auto long_ttl = command;
  std::snprintf(long_ttl.nonce, sizeof(long_ttl.nonce), "nonce-long");
  long_ttl.expires_at = long_ttl.issued_at + 121;
  CHECK(rebooted.authorize(long_ttl, 1800000002, true) ==
        sgk::CommandResult::kTtlTooLong);
  auto untrusted_clock = command;
  std::snprintf(untrusted_clock.nonce, sizeof(untrusted_clock.nonce),
                "nonce-clock");
  CHECK(rebooted.authorize(untrusted_clock, 0, false) ==
        sgk::CommandResult::kClockUntrusted);

  MemoryCommandStorage delayed_first_storage;
  sgk::TargetCommandSecurity delayed_first(&delayed_first_storage, &verifier);
  CHECK(delayed_first.begin("target-a", "tenant-a", "door-a", "boot-a", 7));
  auto never_seen_but_expired = fixtureCommand();
  std::snprintf(never_seen_but_expired.nonce,
                sizeof(never_seen_but_expired.nonce), "nonce-delayed-first");
  CHECK(delayed_first.authorize(never_seen_but_expired, 0, false) ==
        sgk::CommandResult::kClockUntrusted);

  auto uncertain = fixtureCommand();
  std::snprintf(uncertain.nonce, sizeof(uncertain.nonce), "nonce-uncertain");
  CHECK(rebooted.authorize(uncertain, 1800000002, true) ==
        sgk::CommandResult::kAccepted);
  sgk::TargetCommandSecurity after_crash(&storage, &verifier);
  CHECK(after_crash.begin("target-a", "tenant-a", "door-a", "boot-a", 7));
  CHECK(after_crash.authorize(uncertain, 1800000003, true) ==
        sgk::CommandResult::kDuplicateUncertain);

  MemoryCommandStorage failing_storage;
  sgk::TargetCommandSecurity storage_failure(&failing_storage, &verifier);
  CHECK(storage_failure.begin("target-a", "tenant-a", "door-a", "boot-a", 7));
  failing_storage.fail_writes = true;
  auto cannot_commit = fixtureCommand();
  std::snprintf(cannot_commit.nonce, sizeof(cannot_commit.nonce),
                "nonce-storage");
  CHECK(storage_failure.authorize(cannot_commit, 1800000002, true) ==
        sgk::CommandResult::kReplayStorageFailure);
  failing_storage.fail_writes = false;
  CHECK(storage_failure.authorize(cannot_commit, 1800000002, true) ==
        sgk::CommandResult::kAccepted);

  MemoryCommandStorage eviction_storage;
  sgk::TargetCommandSecurity eviction_security(&eviction_storage, &verifier);
  CHECK(eviction_security.begin("target-a", "tenant-a", "door-a", "boot-a", 7));
  auto first_evicted = fixtureCommand();
  for (size_t index = 0; index <= sgk::kCommandReplayEntries; ++index) {
    auto rotating = fixtureCommand();
    std::snprintf(rotating.nonce, sizeof(rotating.nonce), "nonce-%02u",
                  static_cast<unsigned int>(index));
    std::snprintf(rotating.session_id, sizeof(rotating.session_id),
                  "session-%02u", static_cast<unsigned int>(index));
    if (index == 0) first_evicted = rotating;
    CHECK(eviction_security.authorize(rotating, 1800000002, true) ==
          sgk::CommandResult::kAccepted);
    CHECK(eviction_security.markCompleted(rotating));
  }
  CHECK(eviction_security.authorize(first_evicted, 1800000003, true) ==
        sgk::CommandResult::kExpired);
}

class MemoryVersionStorage final : public sgk::OtaVersionFloorStorage {
 public:
  bool read(uint8_t slot, sgk::OtaVersionFloorRecord* record) override {
    if (slot > 1 || record == nullptr || !present[slot]) return false;
    *record = records[slot];
    return true;
  }

  bool write(uint8_t slot,
             const sgk::OtaVersionFloorRecord& record) override {
    if (slot > 1 || fail_writes) return false;
    records[slot] = record;
    present[slot] = true;
    return true;
  }

  std::array<sgk::OtaVersionFloorRecord, 2> records{};
  std::array<bool, 2> present{};
  bool fail_writes = false;
};

void testRawCommandSchemaRejectsEveryDuplicateField() {
  static constexpr const char* kFields[] = {
      "action", "boot_id", "door_id", "expires_at", "issued_at",
      "key_id", "nonce", "schema_version", "session_id", "signature",
      "target_id", "tenant_id", "value"};
  static constexpr const char* kValues[] = {
      "\"arm\"", "\"11111111111111111111111111111111\"", "\"door-a\"",
      "1800000120", "1800000000", "7", "\"nonce-a\"", "1",
      "\"session-a\"", "\"0000\"", "\"target-a\"", "\"tenant-a\"",
      "0"};
  static constexpr const char* kDifferentValues[] = {
      "\"reboot\"", "\"22222222222222222222222222222222\"", "\"door-b\"",
      "1800000121", "1800000001", "8", "\"nonce-b\"", "2",
      "\"session-b\"", "\"1111\"", "\"target-b\"", "\"tenant-b\"",
      "1"};
  static constexpr size_t kFieldCount =
      sizeof(kFields) / sizeof(kFields[0]);
  const auto build = [&](int duplicate, const char* duplicate_value) {
    std::string document = "{";
    for (size_t index = 0; index < kFieldCount; ++index) {
      if (index > 0) document += ',';
      document += '"';
      document += kFields[index];
      document += "\":";
      document += kValues[index];
    }
    if (duplicate >= 0) {
      document += ",\"";
      document += kFields[duplicate];
      document += "\":";
      document += duplicate_value;
    }
    document += '}';
    return document;
  };
  const auto accepted = [&](const std::string& document) {
    return sgk::hasExactUniqueFlatJsonFields(
        reinterpret_cast<const uint8_t*>(document.data()), document.size(),
        kFields, kFieldCount);
  };

  const std::string canonical = build(-1, nullptr);
  CHECK(accepted(canonical));
  for (size_t index = 0; index < kFieldCount; ++index) {
    CHECK(!accepted(build(static_cast<int>(index), kValues[index])));
    CHECK(!accepted(build(static_cast<int>(index), kDifferentValues[index])));
  }
  std::string escaped_alias = canonical;
  escaped_alias.replace(escaped_alias.find("\"action\""), 8,
                        "\"acti\\u006fn\"");
  CHECK(!accepted(escaped_alias));
  std::string additional = canonical;
  additional.insert(additional.size() - 1, ",\"extra\":0");
  CHECK(!accepted(additional));
  std::string nested = canonical;
  nested.replace(nested.find("\"arm\""), 5, "{\"alias\":\"arm\"}");
  CHECK(!accepted(nested));
  CHECK(!accepted(canonical.substr(0, canonical.size() - 1)));
  CHECK(!accepted(canonical + "{}"));
}

void testOtaHealthRequiresContinuousPredicates() {
  sgk::OtaHealthPolicy policy(30000, 120000, 1000);
  policy.begin(1000);
  CHECK(policy.update(1000, true) == sgk::OtaHealthDecision::kWait);
  for (uint32_t now = 2000; now <= 30000; now += 1000) {
    CHECK(policy.update(now, true) == sgk::OtaHealthDecision::kWait);
  }
  CHECK(policy.update(30001, false) == sgk::OtaHealthDecision::kWait);
  CHECK(policy.update(40000, true) == sgk::OtaHealthDecision::kWait);
  for (uint32_t now = 41000; now <= 69000; now += 1000) {
    CHECK(policy.update(now, true) == sgk::OtaHealthDecision::kWait);
  }
  CHECK(policy.update(69999, true) == sgk::OtaHealthDecision::kWait);
  CHECK(policy.update(70000, true) == sgk::OtaHealthDecision::kMarkValid);

  sgk::OtaHealthPolicy late_recovery(30000, 120000, 1000);
  late_recovery.begin(0);
  CHECK(late_recovery.update(100000, false) == sgk::OtaHealthDecision::kWait);
  CHECK(late_recovery.update(110000, true) == sgk::OtaHealthDecision::kWait);
  CHECK(late_recovery.update(120000, true) == sgk::OtaHealthDecision::kRollback);

  sgk::OtaHealthPolicy exact_deadline(30000, 120000, 1000);
  exact_deadline.begin(0);
  CHECK(exact_deadline.update(90000, true) == sgk::OtaHealthDecision::kWait);
  for (uint32_t now = 91000; now <= 119000; now += 1000) {
    CHECK(exact_deadline.update(now, true) == sgk::OtaHealthDecision::kWait);
  }
  CHECK(exact_deadline.update(119999, true) == sgk::OtaHealthDecision::kWait);
  CHECK(exact_deadline.update(120000, true) ==
        sgk::OtaHealthDecision::kMarkValid);

  sgk::OtaHealthPolicy after_deadline(30000, 120000, 1000);
  after_deadline.begin(0);
  CHECK(after_deadline.update(90000, true) == sgk::OtaHealthDecision::kWait);
  for (uint32_t now = 91000; now <= 119000; now += 1000) {
    CHECK(after_deadline.update(now, true) == sgk::OtaHealthDecision::kWait);
  }
  CHECK(after_deadline.update(119999, true) == sgk::OtaHealthDecision::kWait);
  CHECK(after_deadline.update(120001, true) ==
        sgk::OtaHealthDecision::kRollback);

  sgk::OtaHealthPolicy stalled_sampling(30000, 120000, 1000);
  stalled_sampling.begin(0);
  CHECK(stalled_sampling.update(90000, true) == sgk::OtaHealthDecision::kWait);
  CHECK(stalled_sampling.update(119999, true) ==
        sgk::OtaHealthDecision::kWait);
  CHECK(stalled_sampling.update(120000, true) ==
        sgk::OtaHealthDecision::kRollback);
}

void testOtaVersionFloorAndReplayMutations() {
  int comparison = 0;
  CHECK(sgk::OtaVersionPolicy::compare("2.2.0-rc.1", "2.2.0", &comparison));
  CHECK(comparison < 0);
  CHECK(sgk::OtaVersionPolicy::compare("2.2.0", "2.2.0-rc.9", &comparison));
  CHECK(comparison > 0);
  CHECK(sgk::OtaVersionPolicy::compare("2.2.0+one", "2.2.0+two", &comparison));
  CHECK(comparison == 0);
  CHECK(sgk::OtaVersionPolicy::compare(
      "2.1.204+main.g2222222", "2.1.203+main.g1111111", &comparison));
  CHECK(comparison > 0);
  CHECK(sgk::OtaVersionPolicy::compare(
      "2.2.0", "2.1.204+main.g2222222", &comparison));
  CHECK(comparison > 0);
  CHECK(!sgk::OtaVersionPolicy::compare("2.2", "2.2.0", &comparison));

  MemoryVersionStorage storage;
  sgk::OtaVersionPolicy policy(&storage);
  CHECK(policy.begin("2.2.0"));
  CHECK(policy.evaluate("2.2.0-rc.1", "2.2.0") ==
        sgk::OtaVersionDecision::kDowngrade);
  CHECK(policy.evaluate("2.2.0+different", "2.2.0") ==
        sgk::OtaVersionDecision::kIdentityConflict);
  CHECK(policy.evaluate("2.2.1", "2.2.0") ==
        sgk::OtaVersionDecision::kUpgrade);
  CHECK(policy.commit("2.2.1"));

  sgk::OtaVersionPolicy after_rollback(&storage);
  CHECK(after_rollback.begin("2.2.0"));
  CHECK(after_rollback.evaluate("2.2.0", "2.2.0") ==
        sgk::OtaVersionDecision::kDowngrade);
  CHECK(after_rollback.evaluate("2.2.1", "2.2.0") ==
        sgk::OtaVersionDecision::kDowngrade);
  CHECK(after_rollback.evaluate("2.2.1+alternate", "2.2.0") ==
        sgk::OtaVersionDecision::kIdentityConflict);
  CHECK(after_rollback.evaluate("2.2.2", "2.2.0") ==
        sgk::OtaVersionDecision::kUpgrade);

  storage.fail_writes = true;
  CHECK(!after_rollback.commit("2.2.2"));
  storage.fail_writes = false;
  CHECK(after_rollback.commit("2.2.2"));
  sgk::OtaVersionPolicy after_crash(&storage);
  CHECK(after_crash.begin("2.2.1"));
  CHECK(after_crash.evaluate("2.2.1", "2.2.1") ==
        sgk::OtaVersionDecision::kDowngrade);

  MemoryVersionStorage corrupted = storage;
  corrupted.records[0].version[0] ^= 1;
  corrupted.records[1].version[0] ^= 1;
  sgk::OtaVersionPolicy corrupt_policy(&corrupted);
  CHECK(corrupt_policy.begin("2.2.1"));
  CHECK(std::string(corrupt_policy.floor()) == "2.2.1");
}

}  // namespace

int main() {
  sgk::TargetAclManager::setHostAclVerifierCallback(
      [](const std::array<uint8_t, 65>& pubkey,
         const std::array<uint8_t, 32>& digest,
         const std::array<uint8_t, 64>& sig) -> bool {
        static constexpr uint8_t kExpectedPubkey[65] = {
            0x04, 0x7c, 0xf2, 0x7b, 0x18, 0x8d, 0x03, 0x4f, 0x7e, 0x8a, 0x52,
            0x38, 0x03, 0x04, 0xb5, 0x1a, 0xc3, 0xc0, 0x89, 0x69, 0xe2, 0x77,
            0xf2, 0x1b, 0x35, 0xa6, 0x0b, 0x48, 0xfc, 0x47, 0x66, 0x99, 0x78,
            0x07, 0x77, 0x55, 0x10, 0xdb, 0x8e, 0xd0, 0x40, 0x29, 0x3d, 0x9a,
            0xc6, 0x9f, 0x74, 0x30, 0xdb, 0xba, 0x7d, 0xad, 0xe6, 0x3c, 0xe9,
            0x82, 0x29, 0x9e, 0x04, 0xb7, 0x9d, 0x22, 0x78, 0x73, 0xd1};
        static constexpr uint8_t kFixtureSig[64] = {
            0x13, 0xcd, 0xf7, 0x24, 0x64, 0x22, 0xab, 0x07, 0x57, 0x6d, 0x03,
            0x28, 0xbf, 0xe3, 0x13, 0xdb, 0x99, 0x7c, 0x5d, 0x26, 0x89, 0xdf,
            0x26, 0x65, 0x7b, 0x2e, 0xc3, 0x38, 0xe6, 0x90, 0xd4, 0xf1, 0x1f,
            0x2b, 0x0f, 0x9c, 0x7c, 0x6d, 0xfd, 0xc3, 0x64, 0xca, 0xd7, 0x79,
            0x16, 0x28, 0x17, 0x49, 0x6b, 0x68, 0x13, 0x9c, 0x67, 0xe3, 0x8c,
            0xc5, 0x1a, 0x02, 0xaa, 0x25, 0x58, 0x70, 0xef, 0x8b};
        static constexpr uint8_t kExpectedDigest[32] = {
            0xcc, 0x70, 0x10, 0xe3, 0x28, 0xc5, 0xe5, 0xe8,
            0x9f, 0x5f, 0xac, 0xf3, 0x0f, 0xec, 0x10, 0x97,
            0x1e, 0x92, 0x5c, 0xb3, 0x4b, 0x89, 0x84, 0x24,
            0x5d, 0x62, 0x3c, 0xb8, 0x45, 0x44, 0xce, 0xa5};
        if (std::memcmp(pubkey.data(), kExpectedPubkey, 65) != 0) return false;
        if (std::memcmp(sig.data(), kFixtureSig, 64) != 0) return false;
        return std::memcmp(digest.data(), kExpectedDigest, 32) == 0;
      });

  sgk::TargetProofVerifier::setHostProofVerifierCallback(
      [](const std::array<uint8_t, 65>& pubkey,
         const std::array<uint8_t, 61>& input,
         const std::array<uint8_t, 64>& sig) -> bool {
        static constexpr uint8_t kFixtureProofSig[64] = {
            0x38, 0x94, 0xdf, 0xd3, 0x9c, 0x70, 0xee, 0x30, 0x1d, 0x17, 0x34,
            0x66, 0x32, 0x46, 0x1a, 0xc6, 0x6f, 0x16, 0x8c, 0x29, 0xfb, 0xad,
            0xa9, 0xbc, 0xaa, 0x18, 0xb9, 0xe4, 0x08, 0xcf, 0x35, 0xdc, 0x22,
            0xed, 0x96, 0x94, 0xca, 0xeb, 0xf6, 0x54, 0x38, 0x22, 0x8b, 0x0b,
            0xfa, 0x4d, 0x45, 0x6a, 0x68, 0x61, 0xc5, 0x9f, 0x91, 0x7c, 0xe3,
            0x34, 0x60, 0x90, 0xec, 0x5f, 0x17, 0xec, 0xfd, 0xe8};
        static const auto kFixtureInput = hex(
            "53474b50524630317cebae229af25267c8ae244cdb476a48a692feb81477cbc7f36e110e9"
            "93bd464aabbccddeeff001122334455667788990100000003");
        if (pubkey[0] != 0x04) return false;
        if (std::memcmp(sig.data(), kFixtureProofSig, 64) != 0) return false;
        if (input.size() != 61) return false;
        if (std::memcmp(input.data(), kFixtureInput.data(), 61) != 0) return false;
        return true;
      });

  testCanonicalVectorsAndFraming();
  testAccessEvidenceMacFixedVectors();
  testCanonicalSessionAndVerifier();
  testAuthenticatedActionControlBinding();
  testTargetAclManagerAndStorage();
  testTargetProofVerifierIntegration();
  testTargetAccessFsmAndRelayInterlock();
  testVerifiedLocalGattLifecycleBridge();
  testInterleavedGattPreservesVerifiedLifecycleIntegrity();
  testLegacySupersededTerminalCompatibilityClearsActor();
  testVerifiedPhaseTrackerIgnoresUnverifiedInterleaving();
  testUnauthenticatedHelloCannotPreemptArmedLifecycle();
  testRelayFailsafeIsExactlyOnce();
  testNewAuthenticationWaitsForFreshIdleAfterTerminalCooldown();
  testDedicatedManualRemoteRegression();
  testAdversarialSignaturesAndLowS();
  testCrossDoorAndStaleLeaseReplay();
  testOfflineEventQueue();
  testOfflineEventQueueExactEnvelopePreservation();
  testOfflineEventQueueRebootRestoreAndCorruptRejection();
  testOfflineEventQueuePersistenceFailureInterlock();
  testOfflineEventQueueBoundedOverflowAndGap();
  testOfflineEventQueueOverflowGapRebootsAndDrains();
  testOfflineEventQueueWrappedHeadSurvivesRepeatedReboot();
  testOfflineEventQueueFullQueuePowerLossOverwriting();
  testAuthAbortAndDisconnectFlow();
  testProductionMainAuthAbortWiring();
  testAuthPendingStateFlow();
  testStoredAclValidationOnBoot();
  testAbsentOrInvalidSignerKey();
  testTornGenerationAndBadCrc();
  testExpectedSigningKeyIdMismatch();
  testRebootLeaseWithoutTrustedTime();
  testGenerationRecordCrcOffsetAndValidReboot();
  testKeyPresentKeyIdAbsentOrFailClosed();
  testQueueMetaSemanticCorruptionMutations();
  testOfflineCanonicalEventReplayAndPreservation();
  testOfflineCanonicalV2CredentialRefOverlay();
  testProtocolDisconnectHandoff();
  testCommittedActionSurvivesResultTransportFailure();
  testInvalidTypedCanonicalRecordQuarantine();
  testSignedCommandDurableReplayAndMutations();
  testRawCommandSchemaRejectsEveryDuplicateField();
  testOtaHealthRequiresContinuousPredicates();
  testOtaVersionFloorAndReplayMutations();
  std::cout << "GattProtocol host tests passed: " << checks << " checks\n";
  return 0;
}
