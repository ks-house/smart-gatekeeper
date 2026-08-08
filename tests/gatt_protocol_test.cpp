#include "GattProtocol.h"
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
}

void testCanonicalSessionAndVerifier() {
  auto random = canonicalRandom();
  FakeVerifier verifier(sgk::ResultReason::kOk);
  EventRecorder events;
  sgk::ProtocolCore core(random, verifier, canonicalDoor(), &events);
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
  CHECK(std::vector<uint8_t>(verifier.last.signing_input.begin(),
                             verifier.last.signing_input.end()) ==
        hex("53474b50524630317cebae229af25267c8ae244cdb476a48a692feb81477cbc7f"
            "36e110e993bd464aabbccddeeff001122334455667788990100000003"));
  CHECK(events.events.size() >= 3);
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
  bad_action_request.action = 2;
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
  std::copy(session_bytes.begin(), session_bytes.end(), proof.session_id.begin());
  std::copy(boot_bytes.begin(), boot_bytes.end(), proof.boot_id.begin());
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
    CHECK(downstream.events[i].sequence == proof.sequence + i);
    if (i > 0) {
      CHECK(downstream.events[i].has_causation);
      CHECK(downstream.events[i].causation_sequence ==
            downstream.events[i - 1].sequence);
    }
  }

  bridge.emit(proof);
  CHECK(bridge.emitArmed(3000));
  CHECK(bridge.emitTerminated(4000, sgk::EventReason::kArmTimeout));
  CHECK(!bridge.hasVerifiedSession());
  CHECK(downstream.events.back().code ==
        sgk::EventCode::kAccessSessionTerminated);
  CHECK(downstream.events.back().reason == sgk::EventReason::kArmTimeout);
  CHECK(!bridge.emitRelayOn(4001));
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

  fsm.handleRelayFailsafeOff(4, 2000);
  fsm.handleRelayFailsafeOff(5, 2000);
  fsm.tick(1004);

  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(relay_off_calls == 1);
  CHECK(emitted.size() == 2);
  CHECK(emitted[0] == "door_close_failsafe");
  CHECK(emitted[1] == "session_completed");
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
  CHECK(evt.is_canonical == 1);
  CHECK(std::string(evt.event_type) == "queue_overflow");
  CHECK(std::string(evt.detail).find("dropped seq 1-2") != std::string::npos);
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

  // 4. Passage sensor trigger while ARMED transitions to RELAY_HOLD (turns relay ON!)
  CHECK(fsm.handleSensorTrigger(2000, 1000, 2000));
  CHECK(fsm.state() == GateState::RELAY_HOLD);
  CHECK(fsm.isRelayOn());
  CHECK(last_relay_on);
  CHECK(last_event_name == "relay_on_sensor");

  // 5. Failsafe off during RELAY_HOLD transitions to COOLDOWN (never cleanup directly to IDLE!)
  fsm.handleRelayFailsafeOff(2500, 2000);
  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(!fsm.isRelayOn());
  CHECK(!last_relay_on);
  CHECK(last_event_name == "session_completed");

  // 6. Reset and test AUTH_PENDING timeout
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

  // Case 1: Pre-verification disconnect emits ACCESS_GATT_FAILED & ACCESS_SESSION_TERMINATED
  {
    sgk::ProtocolCore protocol(random, proof_verifier, door_A, &event_sink);
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
    sgk::ProtocolCore protocol2(random_post, proof_verifier, door_A, &event_sink);
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
    std::strncpy(canonical_evt.detail, "PROOF_VALID", sizeof(canonical_evt.detail) - 1);

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
  CHECK(std::string(restored.detail) == "PROOF_VALID");
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

void testOtaHealthRequiresContinuousPredicates() {
  sgk::OtaHealthPolicy policy(30000, 120000);
  policy.begin(1000);
  CHECK(policy.update(1000, true) == sgk::OtaHealthDecision::kWait);
  CHECK(policy.update(30000, true) == sgk::OtaHealthDecision::kWait);
  CHECK(policy.update(30001, false) == sgk::OtaHealthDecision::kWait);
  CHECK(policy.update(40000, true) == sgk::OtaHealthDecision::kWait);
  CHECK(policy.update(69999, true) == sgk::OtaHealthDecision::kWait);
  CHECK(policy.update(70000, true) == sgk::OtaHealthDecision::kMarkValid);

  sgk::OtaHealthPolicy late_recovery(30000, 120000);
  late_recovery.begin(0);
  CHECK(late_recovery.update(100000, false) == sgk::OtaHealthDecision::kWait);
  CHECK(late_recovery.update(110000, true) == sgk::OtaHealthDecision::kWait);
  CHECK(late_recovery.update(120000, true) == sgk::OtaHealthDecision::kRollback);
}

void testOtaVersionFloorAndReplayMutations() {
  int comparison = 0;
  CHECK(sgk::OtaVersionPolicy::compare("2.2.0-rc.1", "2.2.0", &comparison));
  CHECK(comparison < 0);
  CHECK(sgk::OtaVersionPolicy::compare("2.2.0", "2.2.0-rc.9", &comparison));
  CHECK(comparison > 0);
  CHECK(sgk::OtaVersionPolicy::compare("2.2.0+one", "2.2.0+two", &comparison));
  CHECK(comparison == 0);
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
  testCanonicalSessionAndVerifier();
  testTargetAclManagerAndStorage();
  testTargetProofVerifierIntegration();
  testTargetAccessFsmAndRelayInterlock();
  testVerifiedLocalGattLifecycleBridge();
  testRelayFailsafeIsExactlyOnce();
  testDedicatedManualRemoteRegression();
  testAdversarialSignaturesAndLowS();
  testCrossDoorAndStaleLeaseReplay();
  testOfflineEventQueue();
  testOfflineEventQueueExactEnvelopePreservation();
  testOfflineEventQueueRebootRestoreAndCorruptRejection();
  testOfflineEventQueuePersistenceFailureInterlock();
  testOfflineEventQueueBoundedOverflowAndGap();
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
  testProtocolDisconnectHandoff();
  testInvalidTypedCanonicalRecordQuarantine();
  testSignedCommandDurableReplayAndMutations();
  testOtaHealthRequiresContinuousPredicates();
  testOtaVersionFloorAndReplayMutations();
  std::cout << "GattProtocol host tests passed: " << checks << " checks\n";
  return 0;
}
