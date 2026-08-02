#include "GattProtocol.h"
#include "OfflineEventQueue.h"
#include "TargetAccessFsm.h"
#include "TargetAclManager.h"
#include "TargetProofVerifier.h"
#include "TargetState.h"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>
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
    if (slot > 1 || blob == nullptr || length > 4096) return false;
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

  // Stale version apply -> anti-rollback rejection (kExpiredOrReplay)
  auto stale_acl = acl_payload;
  stale_acl[33] = 41;  // acl_version = 41 < 42
  CHECK(acl_manager.applySignedAcl(stale_acl.data(), stale_acl.size(),
                                   3000, 1785542400) ==
        sgk::ResultReason::kExpiredOrReplay);

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

  // Storage recovery check: new TargetAclManager using same storage recovers active ACL v42
  sgk::TargetAclManager acl_manager2(&storage);
  acl_manager2.setSignerPublicKey(signer_pubkey);
  CHECK(acl_manager2.begin(door, 5000));
  CHECK(acl_manager2.hasActiveAcl());
  CHECK(acl_manager2.activeAclVersion() == 42);
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

  // Auth success when IDLE -> transitions to RELAY_HOLD and turns relay ON
  CHECK(fsm.handleAuthSuccess(1000, 1000, 2000));
  CHECK(fsm.state() == GateState::RELAY_HOLD);
  CHECK(fsm.isRelayOn());
  CHECK(last_relay_on);
  CHECK(fsm.otaSafeState() == OtaSafeState::RELAY_ACTIVE);
  CHECK(last_event_name == "door_open");

  // Interlock check: subsequent auth attempt while RELAY_HOLD is rejected (fail-closed)
  CHECK(!fsm.handleAuthSuccess(1500, 1000, 2000));
  CHECK(last_event_name == "auth_open_rejected");

  // Tick past 1000ms hold -> transitions to COOLDOWN and turns relay OFF
  fsm.tick(2001);
  CHECK(fsm.state() == GateState::COOLDOWN);
  CHECK(!fsm.isRelayOn());
  CHECK(!last_relay_on);
  CHECK(fsm.otaSafeState() == OtaSafeState::ACCESS_SESSION_ACTIVE);
  CHECK(last_event_name == "door_close");

  // Interlock check: auth attempt while COOLDOWN is rejected
  CHECK(!fsm.handleAuthSuccess(2500, 1000, 2000));

  // Tick past 2000ms cooldown -> transitions to IDLE
  fsm.tick(4002);
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
  acl_manager_B.begin(door_B, 1000);
  CHECK(acl_manager_B.applySignedAcl(acl_payload.data(), acl_payload.size(),
                                     1000, 1785542400) == sgk::ResultReason::kMalformed);
}

void testOfflineEventQueue() {
  sgk::OfflineEventQueue queue;
  CHECK(queue.isEmpty());
  CHECK(queue.size() == 0);

  sgk::Event event1{};
  event1.code = sgk::EventCode::kAccessProofVerified;
  event1.reason = sgk::EventReason::kProofValid;
  event1.sequence = 1;

  sgk::Event event2{};
  event2.code = sgk::EventCode::kAccessSessionTerminated;
  event2.reason = sgk::EventReason::kProofValid;
  event2.sequence = 2;

  CHECK(queue.push(event1, 1000));
  CHECK(queue.push(event2, 1005));
  CHECK(queue.size() == 2);

  sgk::Event popped1{}, popped2{};
  CHECK(queue.pop(&popped1));
  CHECK(popped1.sequence == 1);
  CHECK(queue.pop(&popped2));
  CHECK(popped2.sequence == 2);
  CHECK(queue.isEmpty());

  // Buffer overflow check: push 35 events (capacity is 32)
  for (uint64_t i = 1; i <= 35; ++i) {
    sgk::Event ev{};
    ev.sequence = i;
    queue.push(ev, static_cast<uint32_t>(1000 + i));
  }
  CHECK(queue.size() == 32);

  sgk::Event oldest{};
  CHECK(queue.pop(&oldest));
  // Oldest should be 4 because 1, 2, 3 were overwritten
  CHECK(oldest.sequence == 4);
}

}  // namespace

int main() {
  testCanonicalVectorsAndFraming();
  testCanonicalSessionAndVerifier();
  testTargetAclManagerAndStorage();
  testTargetProofVerifierIntegration();
  testTargetAccessFsmAndRelayInterlock();
  testDedicatedManualRemoteRegression();
  testAdversarialSignaturesAndLowS();
  testCrossDoorAndStaleLeaseReplay();
  testOfflineEventQueue();
  std::cout << "GattProtocol host tests passed: " << checks << " checks\n";
  return 0;
}
