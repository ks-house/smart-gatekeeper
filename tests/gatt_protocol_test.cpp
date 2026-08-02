#include "GattProtocol.h"
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

void testFailClosedAndActions() {
  auto random = canonicalRandom();
  sgk::FailClosedProofVerifier verifier;
  sgk::ProtocolCore core(random, verifier, canonicalDoor());
  start(core);
  auto client = hello();
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             1000));
  drain(core);
  auto arbitrary = proof(core.sessionId());
  CHECK(!send(core, sgk::MessageType::kProof, arbitrary.data(), arbitrary.size(),
              1100, 502, 2));
  auto output = drain(core);
  CHECK(output.size() == 1);
  CHECK(u16(output[0].bytes.data() + 18) == 5);

  core.disconnect(core.connectionOwner(), 1200);
  CHECK(core.connect(7, 1300));
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             1300, 502, 3));
  drain(core);
  auto manual = proof(core.sessionId(), 2);
  CHECK(!send(core, sgk::MessageType::kProof, manual.data(), manual.size(),
              1400, 502, 4));
  output = drain(core);
  CHECK(u16(output[0].bytes.data() + 18) == 7);
}

void testStrictParsingFragmentsAndTimeouts() {
  auto random = canonicalRandom(20);
  FakeVerifier verifier(sgk::ResultReason::kOk);
  sgk::ProtocolCore core(random, verifier, canonicalDoor());
  start(core);
  auto client = hello();

  // Exact hello length and supported framing/ranges only.
  std::array<uint8_t, 17> oversized{};
  std::memcpy(oversized.data(), client.data(), client.size());
  CHECK(!send(core, sgk::MessageType::kClientHello, oversized.data(),
              oversized.size(), 1000));
  CHECK(core.state() == sgk::SessionState::kIdle);
  drain(core);
  auto bad_framing = hello(1, 1, 2, 2);
  CHECK(!send(core, sgk::MessageType::kClientHello, bad_framing.data(),
              bad_framing.size(), 1100, 502, 2));
  CHECK(core.state() == sgk::SessionState::kIdle);
  auto unsupported = drain(core);
  CHECK(unsupported.size() == 1);
  CHECK(unsupported[0].type == sgk::MessageType::kTargetHello);
  CHECK(unsupported[0].bytes[7] == 1);
  CHECK(std::all_of(core.sessionId().begin(), core.sessionId().end(),
                    [](uint8_t value) { return value == 0; }));

  auto nn1 = hello(1, 2);
  CHECK(send(core, sgk::MessageType::kClientHello, nn1.data(), nn1.size(),
             1200, 5, 3));
  drain(core);
  auto exact = proof(core.sessionId(), 1, 104);
  CHECK(!send(core, sgk::MessageType::kProof, exact.data(), exact.size(), 1300,
              8, 4));
  auto result = drain(core);
  CHECK(u16(result[0].bytes.data() + 18) == 2);

  core.disconnect(core.connectionOwner(), 1400);
  CHECK(core.connect(7, 1500));
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             1500, 502, 5));
  drain(core);
  auto valid = proof(core.sessionId());
  uint8_t first[32] = {};
  const size_t first_length = sgk::ProtocolCore::buildFrame(
      sgk::MessageType::kProof, 6, valid.data(), valid.size(), 10, 0, first,
      sizeof(first));
  CHECK(core.receiveFrame(sgk::MessageType::kProof, core.connectionOwner(), first, first_length,
                          1600));
  CHECK(core.receiveFrame(sgk::MessageType::kProof, core.connectionOwner(), first, first_length,
                          1601));  // exact duplicate is idempotent
  first[11] ^= 1;
  CHECK(!core.receiveFrame(sgk::MessageType::kProof, core.connectionOwner(), first, first_length,
                           1602));
  drain(core);
  CHECK(!send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
              1700, 502, 9));
  auto limited = drain(core);
  CHECK(u16(limited[0].bytes.data() + 18) == 9);

  core.disconnect(core.connectionOwner(), 4900);
  CHECK(core.connect(7, 5000));
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             5000, 502, 7));
  drain(core);
  valid = proof(core.sessionId());
  const size_t frame_length = sgk::ProtocolCore::buildFrame(
      sgk::MessageType::kProof, 8, valid.data(), valid.size(), 10, 0, first,
      sizeof(first));
  CHECK(core.receiveFrame(sgk::MessageType::kProof, core.connectionOwner(), first, frame_length,
                          5100));
  core.tick(7100);  // exact 2s deadline
  result = drain(core);
  CHECK(u16(result[0].bytes.data() + 18) == 2);
}

void testLifecycleBusyReplayRolloverAndSafety() {
  auto random = canonicalRandom(30);
  FakeVerifier allow(sgk::ResultReason::kOk);
  sgk::ProtocolCore core(random, allow, canonicalDoor());
  start(core, 0xfffff000U);
  CHECK(!core.connect(8, 0xfffff010U));
  auto client = hello();
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             0xffffff00U));
  drain(core);
  auto valid = proof(core.sessionId());
  CHECK(send(core, sgk::MessageType::kProof, valid.data(), valid.size(),
             0xffffff80U, 502, 2));  // valid before wrapped deadline
  drain(core);
  CHECK(!send(core, sgk::MessageType::kProof, valid.data(), valid.size(),
              0xffffff90U, 502, 3));
  auto result = drain(core);
  CHECK(u16(result[0].bytes.data() + 18) == 4);

  core.disconnect(core.connectionOwner(), 10);
  CHECK(core.connect(7, 20));
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             20, 502, 4));
  const auto busy_session = core.sessionId();
  core.setOtaBusy(true, 30);
  CHECK(core.state() == sgk::SessionState::kIdle);
  result = drain(core);
  CHECK(result.size() == 1);
  CHECK(u16(result[0].bytes.data() + 18) == 8);
  CHECK(std::memcmp(result[0].bytes.data() + 2, busy_session.data(),
                    busy_session.size()) == 0);
  valid = proof(core.sessionId());
  CHECK(!send(core, sgk::MessageType::kProof, valid.data(), valid.size(), 40,
              502, 5));
  result = drain(core);
  CHECK(u16(result[0].bytes.data() + 18) == 8);
  core.setOtaBusy(false, 50);
  core.setEnabled(false);
  CHECK(!core.connected());
  CHECK(core.state() == sgk::SessionState::kIdle);
  CHECK(!core.connect(7, 60));

  sgk::OutputMessage message;
  message.length = 4;
  message.bytes[0] = 1;
  size_t written = 99;
  CHECK(!sgk::ProtocolCore::copyOutput(message, nullptr, 4, &written));
  CHECK(written == 0);
  uint8_t small[3] = {};
  CHECK(!sgk::ProtocolCore::copyOutput(message, small, sizeof(small), &written));
  CHECK(!sgk::ProtocolCore::copyOutput(message, small, sizeof(small), nullptr));
}

void testDenyVerifierFuzzAndRngGuards() {
  auto random = canonicalRandom(50);
  FakeVerifier deny(sgk::ResultReason::kCredentialDenied);
  sgk::ProtocolCore core(random, deny, canonicalDoor());
  start(core);
  auto client = hello();
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             1000));
  drain(core);
  auto value = proof(core.sessionId());
  CHECK(!send(core, sgk::MessageType::kProof, value.data(), value.size(), 1100,
              502, 2));
  auto result = drain(core);
  CHECK(u16(result[0].bytes.data() + 18) == 6);

  // Deterministic malformed/fuzz corpus exercises the production parser.
  for (uint16_t mutation = 0; mutation < 64; ++mutation) {
    core.disconnect(core.connectionOwner(), 2000 + mutation * 10);
    CHECK(core.connect(7, 2001 + mutation * 10));
    uint8_t frame[64] = {};
    const size_t frame_length = sgk::ProtocolCore::buildFrame(
        sgk::MessageType::kClientHello, static_cast<uint16_t>(10 + mutation),
        client.data(), client.size(), client.size(), 0, frame, sizeof(frame));
    CHECK(frame_length != 0);
    frame[mutation % frame_length] ^= static_cast<uint8_t>(1U << (mutation % 8));
    core.receiveFrame(sgk::MessageType::kClientHello, core.connectionOwner(), frame, frame_length,
                      2002 + mutation * 10);
    drain(core);
  }

  SequenceRandom zero;
  zero.values = {std::vector<uint8_t>(16, 0), std::vector<uint8_t>(16, 0),
                 std::vector<uint8_t>(16, 0), std::vector<uint8_t>(16, 0)};
  sgk::FailClosedProofVerifier fail_closed;
  sgk::ProtocolCore bad_rng(zero, fail_closed, canonicalDoor());
  CHECK(!bad_rng.initialize());
  bad_rng.setEnabled(true);
  CHECK(!bad_rng.enabled());

  SequenceRandom duplicate;
  const auto boot = hex("11111111111111111111111111111111");
  const auto repeated_session = hex("22222222222222222222222222222222");
  const auto first_nonce = std::vector<uint8_t>(32, 0x33);
  duplicate.values = {boot, repeated_session, first_nonce, repeated_session,
                      repeated_session, repeated_session, repeated_session};
  sgk::ProtocolCore duplicate_core(duplicate, fail_closed, canonicalDoor());
  start(duplicate_core);
  CHECK(send(duplicate_core, sgk::MessageType::kClientHello, client.data(),
             client.size(), 1000));
  drain(duplicate_core);
  duplicate_core.disconnect(duplicate_core.connectionOwner(), 1100);
  CHECK(duplicate_core.connect(7, 1200));
  CHECK(!send(duplicate_core, sgk::MessageType::kClientHello, client.data(),
              client.size(), 1200, 502, 2));
  CHECK(!duplicate_core.enabled());
}

void testAdapterConnectionOwnershipAndReconnectRace() {
  auto random = canonicalRandom(12);
  FakeVerifier verifier(sgk::ResultReason::kOk);
  sgk::ProtocolCore core(random, verifier, canonicalDoor());
  start(core);
  const sgk::ConnectionToken first_owner = core.connectionOwner();
  sgk::AdapterState adapter;
  CHECK(adapter.acceptConnection(first_owner));
  CHECK(!core.connect(8, 1001));
  const auto client = hello();
  uint8_t frame[64] = {};
  const size_t frame_length = sgk::ProtocolCore::buildFrame(
      sgk::MessageType::kClientHello, 1, client.data(), client.size(),
      client.size(), 0, frame, sizeof(frame));
  CHECK(frame_length != 0);
  CHECK(!adapter.enqueueWrite(8, sgk::MessageType::kClientHello, frame,
                              frame_length));
  CHECK(adapter.enqueueWrite(7, sgk::MessageType::kClientHello, frame,
                             frame_length));
  sgk::PendingWrite stale;
  CHECK(adapter.popWrite(&stale));
  CHECK(stale.owner == first_owner);

  core.disconnect(first_owner, 1010);
  adapter.disconnect(first_owner.handle);
  sgk::ConnectionToken second_owner;
  CHECK(core.connect(7, 1020, &second_owner));
  CHECK(second_owner.generation != first_owner.generation);
  CHECK(adapter.acceptConnection(second_owner));
  CHECK(!core.receiveFrame(stale.type, stale.owner, stale.bytes.data(),
                           stale.length, 1030));
  CHECK(core.state() == sgk::SessionState::kIdle);
  CHECK(adapter.setSubscribed(7, sgk::MessageType::kResult, true));
  sgk::OutputMessage stale_result;
  stale_result.type = sgk::MessageType::kResult;
  stale_result.connection_handle = first_owner.handle;
  stale_result.connection_generation = first_owner.generation;
  stale_result.length = sgk::kResultSize;
  CHECK(!adapter.stageOutput(stale_result));
}

void testAdapterOverflowAndAckGating() {
  auto random = canonicalRandom(12);
  FakeVerifier verifier(sgk::ResultReason::kOk);
  sgk::ProtocolCore core(random, verifier, canonicalDoor());
  start(core);
  sgk::AdapterState adapter;
  CHECK(adapter.acceptConnection(core.connectionOwner()));
  CHECK(adapter.setSubscribed(7, sgk::MessageType::kTargetHello, true));
  CHECK(adapter.setSubscribed(7, sgk::MessageType::kChallenge, true));
  CHECK(adapter.setSubscribed(7, sgk::MessageType::kResult, true));

  const auto client = hello();
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             1000));
  drain(core);
  const auto valid = proof(core.sessionId());
  uint8_t proof_frame[sgk::kAdapterFrameCapacity] = {};
  const size_t proof_frame_length = sgk::ProtocolCore::buildFrame(
      sgk::MessageType::kProof, 2, valid.data(), valid.size(), valid.size(), 0,
      proof_frame, sizeof(proof_frame));
  for (size_t index = 0; index < sgk::kPendingWriteCapacity; ++index) {
    CHECK(adapter.enqueueWrite(7, sgk::MessageType::kProof, proof_frame,
                               proof_frame_length));
  }
  CHECK(!adapter.enqueueWrite(7, sgk::MessageType::kProof, proof_frame,
                              proof_frame_length));
  sgk::ConnectionToken overflow_owner;
  CHECK(adapter.consumeOverflow(&overflow_owner));
  sgk::PendingWrite discarded;
  CHECK(!adapter.popWrite(&discarded));
  CHECK(!core.receiveFrame(sgk::MessageType::kProof, overflow_owner, nullptr,
                           0, 1100));
  CHECK(verifier.calls == 0);

  auto results = drain(core);
  CHECK(results.size() == 1);
  CHECK(adapter.stageOutput(results[0]));
  uint8_t fragment[64] = {};
  size_t written = 0;
  sgk::MessageType type = sgk::MessageType::kError;
  sgk::IndicationToken token{};
  CHECK(adapter.beginNextIndication(23, 1200, fragment, sizeof(fragment),
                                    &written, &type, &token));
  CHECK(written != 0);
  const sgk::IndicationToken indication_token = token;
  const sgk::MessageType indication_type = type;
  CHECK(!adapter.beginNextIndication(23, 1201, fragment, sizeof(fragment),
                                     &written, &type, &token));
  CHECK(adapter.confirmIndication({{8, indication_token.owner.generation},
                                   indication_token.output_generation,
                                   indication_token.fragment_index},
                                  indication_type, true) ==
        sgk::IndicationResult::kIgnored);
  CHECK(adapter.confirmIndication(indication_token,
                                  sgk::MessageType::kChallenge, true) ==
        sgk::IndicationResult::kIgnored);
  CHECK(adapter.confirmIndication(indication_token, indication_type, true) ==
        sgk::IndicationResult::kFragmentConfirmed);
  sgk::IndicationToken token2{};
  CHECK(adapter.beginNextIndication(23, 1202, fragment, sizeof(fragment),
                                    &written, &type, &token2));
  CHECK(adapter.confirmIndication(token2, type, false) ==
        sgk::IndicationResult::kAborted);
  CHECK(!adapter.outputActive());

  sgk::OutputMessage timeout_output = results[0];
  timeout_output.message_id++;
  CHECK(adapter.stageOutput(timeout_output));
  sgk::IndicationToken token3{};
  CHECK(adapter.beginNextIndication(64, 0xfffffff0U, fragment,
                                    sizeof(fragment), &written, &type,
                                    &token3));
  CHECK(!adapter.confirmationTimedOut(0x0000049fU));
  CHECK(adapter.confirmationTimedOut(0x000004a0U));
  adapter.abortOutput();
}

void testAdversarialStaleIndicationAndEpochs() {
  auto random = canonicalRandom();
  FakeVerifier verifier(sgk::ResultReason::kOk);
  const auto door = canonicalDoor();
  sgk::ProtocolCore core(random, verifier, door);
  sgk::AdapterState adapter;

  CHECK(core.initialize());
  core.setEnabled(true);
  sgk::ConnectionToken owner_v1;
  CHECK(core.connect(1, 1000, &owner_v1));
  CHECK(adapter.acceptConnection(owner_v1));
  CHECK(adapter.setSubscribed(1, sgk::MessageType::kResult, true));

  sgk::OutputMessage msg1{};
  msg1.connection_handle = owner_v1.handle;
  msg1.connection_generation = owner_v1.generation;
  msg1.type = sgk::MessageType::kResult;
  msg1.message_id = 1;
  msg1.length = 32;
  std::memset(msg1.bytes.data(), 0xAA, 32);

  // 1. Stage msg1 and obtain IndicationToken for fragment 0.
  CHECK(adapter.stageOutput(msg1));
  uint8_t frame[64] = {};
  size_t written = 0;
  sgk::MessageType type = sgk::MessageType::kError;
  sgk::IndicationToken token1{};
  CHECK(adapter.beginNextIndication(23, 1000, frame, sizeof(frame), &written, &type, &token1));
  CHECK(token1.valid());
  const uint64_t gen1 = token1.output_generation;
  CHECK(gen1 != 0);
  CHECK(token1.fragment_index == 0);

  // 2. Abort msg1. Output generation increments to gen1 + 1.
  adapter.abortOutput();
  CHECK(!adapter.outputActive());

  // 3. Stale callbacks (success or failure) using token1 must return kIgnored.
  CHECK(adapter.confirmIndication(token1, sgk::MessageType::kResult, true) == sgk::IndicationResult::kIgnored);
  CHECK(adapter.confirmIndication(token1, sgk::MessageType::kResult, false) == sgk::IndicationResult::kIgnored);

  // 4. Same-owner same-type replacement: stage msg2 (type kResult) for same owner_v1.
  sgk::OutputMessage msg2 = msg1;
  msg2.message_id = 2;
  std::memset(msg2.bytes.data(), 0xBB, 32);

  CHECK(adapter.stageOutput(msg2));
  sgk::IndicationToken token2{};
  CHECK(adapter.beginNextIndication(23, 1005, frame, sizeof(frame), &written, &type, &token2));
  CHECK(token2.valid());
  CHECK(token2.output_generation > gen1);
  CHECK(token2.fragment_index == 0);

  // 5. Late callback from aborted msg1 (token1) arrives now for same owner and same type.
  // It MUST NOT confirm msg2!
  CHECK(adapter.confirmIndication(token1, sgk::MessageType::kResult, true) == sgk::IndicationResult::kIgnored);
  CHECK(adapter.outputActive());
  CHECK(adapter.confirmationPending());

  // 6. Valid callback for msg2 (token2) confirms fragment 0.
  CHECK(adapter.confirmIndication(token2, sgk::MessageType::kResult, true) == sgk::IndicationResult::kFragmentConfirmed);

  // 7. Duplicate callback for fragment 0 (token2) arrives now. MUST return kIgnored because fragment_index is now 1.
  CHECK(adapter.confirmIndication(token2, sgk::MessageType::kResult, true) == sgk::IndicationResult::kIgnored);

  // 8. Fragment 1 confirmation for token2.
  sgk::IndicationToken token2_frag1{};
  CHECK(adapter.beginNextIndication(23, 1010, frame, sizeof(frame), &written, &type, &token2_frag1));
  CHECK(token2_frag1.fragment_index == 1);
  CHECK(token2_frag1.output_generation == token2.output_generation);

  // Out-of-order callback for fragment 2 (invalid fragment_index) returns kIgnored.
  sgk::IndicationToken token2_frag2_bogus = token2_frag1;
  token2_frag2_bogus.fragment_index = 2;
  CHECK(adapter.confirmIndication(token2_frag2_bogus, sgk::MessageType::kResult, true) == sgk::IndicationResult::kIgnored);

  CHECK(adapter.confirmIndication(token2_frag1, sgk::MessageType::kResult, true) == sgk::IndicationResult::kFragmentConfirmed);
}

void testAdversarialDisconnectReconnectGeneration() {
  sgk::AdapterState adapter;

  sgk::ConnectionToken owner_v1{1, 100};
  CHECK(adapter.acceptConnection(owner_v1));
  CHECK(adapter.setSubscribed(1, sgk::MessageType::kResult, true));

  sgk::OutputMessage msg{};
  msg.connection_handle = owner_v1.handle;
  msg.connection_generation = owner_v1.generation;
  msg.type = sgk::MessageType::kResult;
  msg.message_id = 1;
  msg.length = 16;

  CHECK(adapter.stageOutput(msg));
  uint8_t frame[64] = {};
  size_t written = 0;
  sgk::MessageType type = sgk::MessageType::kError;
  sgk::IndicationToken token_v1{};
  CHECK(adapter.beginNextIndication(23, 1000, frame, sizeof(frame), &written, &type, &token_v1));

  // Disconnect handle 1 and reconnect handle 1 (generation 101).
  adapter.disconnect(1);
  sgk::ConnectionToken owner_v2{1, 101};
  CHECK(adapter.acceptConnection(owner_v2));
  CHECK(adapter.setSubscribed(1, sgk::MessageType::kResult, true));

  // Callback from owner_v1 (token_v1) MUST return kIgnored.
  CHECK(adapter.confirmIndication(token_v1, sgk::MessageType::kResult, true) == sgk::IndicationResult::kIgnored);
}

void testProvisionedDoorBindingAndCanonicalEventFields() {
  SequenceRandom missing_random = canonicalRandom();
  sgk::FailClosedProofVerifier fail_closed;
  std::array<uint8_t, 16> missing_door{};
  sgk::ProtocolCore missing(missing_random, fail_closed, missing_door);
  CHECK(!missing.initialize());

  auto random_a = canonicalRandom();
  auto random_b = canonicalRandom();
  HashSignatureVerifier verifier_a;
  HashSignatureVerifier verifier_b;
  EventRecorder events;
  const auto door_a = canonicalDoor();
  auto door_b = door_a;
  door_b[0] ^= 0x10;
  sgk::ProtocolCore core_a(random_a, verifier_a, door_a, &events);
  sgk::ProtocolCore core_b(random_b, verifier_b, door_b);
  start(core_a, 1000);
  start(core_b, 1000);
  const auto client = hello();
  CHECK(send(core_a, sgk::MessageType::kClientHello, client.data(),
             client.size(), 1000));
  CHECK(send(core_b, sgk::MessageType::kClientHello, client.data(),
             client.size(), 1000));
  const auto output_a = drain(core_a);
  const auto output_b = drain(core_b);
  CHECK(output_a.size() == 2 && output_b.size() == 2);
  CHECK(output_a[1].bytes[10] != output_b[1].bytes[10]);

  auto signed_proof = proof(core_a.sessionId());
  std::array<uint8_t, 61> signing_input{};
  std::memcpy(signing_input.data(), "SGKPRF01", 8);
  sgk::ProtocolCore::sha256(output_a[1].bytes.data(), output_a[1].length,
                            signing_input.data() + 8);
  std::memcpy(signing_input.data() + 40, signed_proof.data() + 18, 16);
  signing_input[56] = signed_proof[34];
  std::memcpy(signing_input.data() + 57, signed_proof.data() + 35, 4);
  uint8_t signature_digest[32] = {};
  sgk::ProtocolCore::sha256(signing_input.data(), signing_input.size(),
                            signature_digest);
  std::memcpy(signed_proof.data() + 39, signature_digest, 32);
  std::memcpy(signed_proof.data() + 71, signature_digest, 32);
  CHECK(send(core_a, sgk::MessageType::kProof, signed_proof.data(),
             signed_proof.size(), 1100, 502, 2));
  CHECK(!send(core_b, sgk::MessageType::kProof, signed_proof.data(),
              signed_proof.size(), 1100, 502, 2));
  const auto denied = drain(core_b);
  CHECK(denied.size() == 1);
  CHECK(u16(denied[0].bytes.data() + 18) == 7);

  CHECK(events.events.size() >= 3);
  CHECK(events.events[0].sequence != 0);
  CHECK(events.events[1].sequence == events.events[0].sequence + 1);
  CHECK(events.events[1].has_causation);
  CHECK(events.events[1].causation_sequence == events.events[0].sequence);
  CHECK(events.events[0].monotonic_ms == 1000);
  CHECK(events.events[0].session_id == core_a.sessionId());
  CHECK(events.events[0].boot_id == core_a.bootId());
}

void testOtaSafeStateClassification() {
  CHECK(classifyOtaSafeState(GateState::IDLE, false, false) ==
        OtaSafeState::SAFE);
  CHECK(classifyOtaSafeState(GateState::ARMED, true, false) ==
        OtaSafeState::ACCESS_SESSION_ACTIVE);
  CHECK(classifyOtaSafeState(GateState::COOLDOWN, false, false) ==
        OtaSafeState::ACCESS_SESSION_ACTIVE);
  CHECK(classifyOtaSafeState(GateState::IDLE, false, true) ==
        OtaSafeState::RELAY_ACTIVE);
  CHECK(classifyOtaSafeState(GateState::RELAY_HOLD, false, false) ==
        OtaSafeState::RELAY_ACTIVE);
}

}  // namespace

int main() {
  testCanonicalVectorsAndFraming();
  testCanonicalSessionAndVerifier();
  testFailClosedAndActions();
  testStrictParsingFragmentsAndTimeouts();
  testLifecycleBusyReplayRolloverAndSafety();
  testDenyVerifierFuzzAndRngGuards();
  testAdapterConnectionOwnershipAndReconnectRace();
  testAdapterOverflowAndAckGating();
  testAdversarialStaleIndicationAndEpochs();
  testAdversarialDisconnectReconnectGeneration();
  testProvisionedDoorBindingAndCanonicalEventFields();
  testOtaSafeStateClassification();
  std::cout << "GattProtocol host tests passed: " << checks << " checks\n";
  return 0;
}
