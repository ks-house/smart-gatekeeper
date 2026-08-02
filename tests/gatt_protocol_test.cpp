#include "GattProtocol.h"

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
          uint16_t connection_id = 7) {
  const size_t count = (length + fragment_capacity - 1) / fragment_capacity;
  bool result = true;
  for (size_t index = 0; index < count; ++index) {
    uint8_t frame[512] = {};
    const size_t frame_length = sgk::ProtocolCore::buildFrame(
        type, message_id, payload, length, fragment_capacity,
        static_cast<uint8_t>(index), frame, sizeof(frame));
    CHECK(frame_length != 0);
    result = core.receiveFrame(type, connection_id, frame, frame_length,
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
  CHECK(core.connect(7, now));
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
  sgk::ProtocolCore core(random, verifier, &events);
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
  sgk::ProtocolCore core(random, verifier);
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

  core.disconnect(7, 1200);
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
  sgk::ProtocolCore core(random, verifier);
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

  core.disconnect(7, 1400);
  CHECK(core.connect(7, 1500));
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             1500, 502, 5));
  drain(core);
  auto valid = proof(core.sessionId());
  uint8_t first[32] = {};
  const size_t first_length = sgk::ProtocolCore::buildFrame(
      sgk::MessageType::kProof, 6, valid.data(), valid.size(), 10, 0, first,
      sizeof(first));
  CHECK(core.receiveFrame(sgk::MessageType::kProof, 7, first, first_length,
                          1600));
  CHECK(core.receiveFrame(sgk::MessageType::kProof, 7, first, first_length,
                          1601));  // exact duplicate is idempotent
  first[11] ^= 1;
  CHECK(!core.receiveFrame(sgk::MessageType::kProof, 7, first, first_length,
                           1602));
  drain(core);
  CHECK(!send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
              1700, 502, 9));
  auto limited = drain(core);
  CHECK(u16(limited[0].bytes.data() + 18) == 9);

  core.disconnect(7, 4900);
  CHECK(core.connect(7, 5000));
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             5000, 502, 7));
  drain(core);
  valid = proof(core.sessionId());
  const size_t frame_length = sgk::ProtocolCore::buildFrame(
      sgk::MessageType::kProof, 8, valid.data(), valid.size(), 10, 0, first,
      sizeof(first));
  CHECK(core.receiveFrame(sgk::MessageType::kProof, 7, first, frame_length,
                          5100));
  core.tick(7100);  // exact 2s deadline
  result = drain(core);
  CHECK(u16(result[0].bytes.data() + 18) == 2);
}

void testLifecycleBusyReplayRolloverAndSafety() {
  auto random = canonicalRandom(30);
  FakeVerifier allow(sgk::ResultReason::kOk);
  sgk::ProtocolCore core(random, allow);
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

  core.disconnect(7, 10);
  CHECK(core.connect(7, 20));
  CHECK(send(core, sgk::MessageType::kClientHello, client.data(), client.size(),
             20, 502, 4));
  drain(core);
  core.setOtaBusy(true, 30);
  CHECK(core.state() == sgk::SessionState::kIdle);
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
  sgk::ProtocolCore core(random, deny);
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
    core.disconnect(7, 2000 + mutation * 10);
    CHECK(core.connect(7, 2001 + mutation * 10));
    uint8_t frame[64] = {};
    const size_t frame_length = sgk::ProtocolCore::buildFrame(
        sgk::MessageType::kClientHello, static_cast<uint16_t>(10 + mutation),
        client.data(), client.size(), client.size(), 0, frame, sizeof(frame));
    CHECK(frame_length != 0);
    frame[mutation % frame_length] ^= static_cast<uint8_t>(1U << (mutation % 8));
    core.receiveFrame(sgk::MessageType::kClientHello, 7, frame, frame_length,
                      2002 + mutation * 10);
    drain(core);
  }

  SequenceRandom zero;
  zero.values = {std::vector<uint8_t>(16, 0), std::vector<uint8_t>(16, 0),
                 std::vector<uint8_t>(16, 0), std::vector<uint8_t>(16, 0)};
  sgk::FailClosedProofVerifier fail_closed;
  sgk::ProtocolCore bad_rng(zero, fail_closed);
  CHECK(!bad_rng.initialize());
  bad_rng.setEnabled(true);
  CHECK(!bad_rng.enabled());

  SequenceRandom duplicate;
  const auto boot = hex("11111111111111111111111111111111");
  const auto repeated_session = hex("22222222222222222222222222222222");
  const auto first_nonce = std::vector<uint8_t>(32, 0x33);
  duplicate.values = {boot, repeated_session, first_nonce, repeated_session,
                      repeated_session, repeated_session, repeated_session};
  sgk::ProtocolCore duplicate_core(duplicate, fail_closed);
  start(duplicate_core);
  CHECK(send(duplicate_core, sgk::MessageType::kClientHello, client.data(),
             client.size(), 1000));
  drain(duplicate_core);
  duplicate_core.disconnect(7, 1100);
  CHECK(duplicate_core.connect(7, 1200));
  CHECK(!send(duplicate_core, sgk::MessageType::kClientHello, client.data(),
              client.size(), 1200, 502, 2));
  CHECK(!duplicate_core.enabled());
}

}  // namespace

int main() {
  testCanonicalVectorsAndFraming();
  testCanonicalSessionAndVerifier();
  testFailClosedAndActions();
  testStrictParsingFragmentsAndTimeouts();
  testLifecycleBusyReplayRolloverAndSafety();
  testDenyVerifierFuzzAndRngGuards();
  std::cout << "GattProtocol host tests passed: " << checks << " checks\n";
  return 0;
}
