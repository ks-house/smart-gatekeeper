#include "OtaDiagnosticRecord.h"
#include "OtaTransportLease.h"
#include <cassert>
#include <cstring>

struct FakeTransport {
  static bool busy;
  static bool clientAlive;
  static int resumes;
  static bool suspendForOta() { return !busy; }
  static void resumeAfterOta() { assert(!clientAlive); ++resumes; }
};
bool FakeTransport::busy = false;
bool FakeTransport::clientAlive = false;
int FakeTransport::resumes = 0;
struct FakeTlsClient {
  FakeTlsClient() { FakeTransport::clientAlive = true; }
  ~FakeTlsClient() { FakeTransport::clientAlive = false; }
};
void failedAt(unsigned stage) {
  sgk::OtaTransportLease<FakeTransport> lease;
  if (!lease.acquire()) return;
  assert(!lease.acquire());
  FakeTlsClient client;
  // Manifest, signature, HTTP, size, flash, timeout, hash and normal exits.
  for (unsigned i = 0; i < 8; ++i) if (i == stage) return;
}

int main() {
  for (unsigned i = 0; i < 9; ++i) failedAt(i);
  assert(FakeTransport::resumes == 9);
  FakeTransport::busy = true;
  failedAt(0);
  assert(FakeTransport::resumes == 9);
  sgk::OtaDiagnosticRecord r;
  r.attempt = 7;
  r.boot_count = 809;
  r.stage = sgk::OtaStage::kDownload;
  r.total = 1900000;
  r.bytes = 262144;
  std::strcpy(r.target_version, "2.1.487+main.g123abcd");
  r.checksum = sgk::otaDiagnosticChecksum(r);
  assert(sgk::validOtaDiagnostic(r));
  const auto saved = r;
  // Every single-byte corruption/torn write is refused.
  for (size_t i = 0; i < sizeof(r); ++i) {
    r = saved;
    reinterpret_cast<unsigned char*>(&r)[i] ^= 1;
    assert(!sgk::validOtaDiagnostic(r));
  }
  r = saved;
  r.stage = static_cast<sgk::OtaStage>(99);
  r.checksum = sgk::otaDiagnosticChecksum(r);
  assert(!sgk::validOtaDiagnostic(r));
  r = saved;
  r.bytes = r.total + 1;
  r.checksum = sgk::otaDiagnosticChecksum(r);
  assert(!sgk::validOtaDiagnostic(r));
  r = saved;
  std::memset(r.target_version, 'x', sizeof(r.target_version));
  r.checksum = sgk::otaDiagnosticChecksum(r);
  assert(!sgk::validOtaDiagnostic(r));
  assert(sgk::otaStageInFlight(sgk::OtaStage::kPendingBoot));
  assert(!sgk::otaStageInFlight(sgk::OtaStage::kValid));
  assert(!sgk::otaStageInFlight(sgk::OtaStage::kFailed));
}
