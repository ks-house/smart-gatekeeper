#include "OtaDownload.h"

#include <cassert>
#include <cstring>
#include <vector>

struct FakeIO {
  std::vector<uint8_t> input, written;
  std::vector<uint32_t> offsets;
  uint32_t clock = 0, position = 0, disconnect_at = UINT32_MAX;
  size_t fragment = 4096, read_cap = 4096, reads = 0, writes = 0;
  bool disconnected_once = false, always_fail = false, stall = false;
  bool reject_resume = false, write_fail = false, corrupt = false;
  bool zero_read_once = false;
  uint32_t open_delay = 0, read_delay = 0, write_delay = 0;
  unsigned open_failures = 0;
  unsigned closed = 0, serviced = 0;
  explicit FakeIO(size_t size) : input(size) {
    for (size_t i = 0; i < size; ++i) input[i] = static_cast<uint8_t>(i * 31);
  }
  uint32_t now() { return clock; }
  void service() { ++serviced; }
  void pause() { clock += 10; }
  sgk::OtaOpenResult open(uint32_t offset) {
    offsets.push_back(offset); position = offset; clock += open_delay;
    if (always_fail) return sgk::OtaOpenResult::kRetryable;
    if (open_failures) {
      --open_failures;
      return sgk::OtaOpenResult::kRetryable;
    }
    if (offset && reject_resume) return sgk::OtaOpenResult::kRejected;
    return sgk::OtaOpenResult::kReady;
  }
  int available() {
    if (!disconnected_once && position >= disconnect_at) {
      disconnected_once = true; return -1;
    }
    if (stall) return 0;
    return static_cast<int>(std::min(fragment, input.size() - position));
  }
  bool connected() { return true; }
  void close() { ++closed; }
  int read(uint8_t* data, size_t size) {
    ++reads;
    clock += read_delay;
    if (zero_read_once) {
      zero_read_once = false;
      return 0;
    }
    size = std::min(size, read_cap);
    std::memcpy(data, input.data() + position, size);
    if (corrupt && size) data[0] ^= 1;
    position += size;
    return static_cast<int>(size);
  }
  bool write(const uint8_t* data, size_t size) {
    ++writes;
    clock += write_delay;
    if (write_fail) return false;
    written.insert(written.end(), data, data + size);
    return true;
  }
};

int main() {
  using namespace sgk;
  assert(otaResponseMatches(200, 100, "", "", 0, 100));
  assert(otaResponseMatches(206, 63, "bytes 37-99/100", "identity", 37, 100));
  assert(!otaResponseMatches(200, 63, "", "", 37, 100));
  for (auto bad : {"bytes 0-99/100", "bytes 37-98/100", "bytes 37-99/*",
                   "bytes 37-99/101", "bytes 37-99/100x", "bytes 37-99/4294967396",
                   "bytes 37", "bytes 37-", "bytes 37-99", "bytes -1-99/100"})
    assert(!otaContentRangeMatches(bad, 37, 100));
  assert(!otaResponseMatches(206, 63, "bytes 37-99/100", "gzip", 37, 100));
  assert(!otaResponseMatches(206, -1, "bytes 37-99/100", "", 37, 100));
  assert(!otaResponseMatches(200, 100, "", "", 0, 100, "chunked"));
  assert(!otaResponseMatches(206, 63, "bytes 37-99/100", "", 37, 100, "chunked"));
  assert(!otaContentRangeMatches(nullptr, 0, 100));
  assert(!otaResponseMatches(206, 100, "bytes 0-99/100", "", 37, 100));
  assert(!otaResponseMatches(200, 0, "", "", 0, 0));
  assert(!otaContentRangeMatches("bytes 100-99/100", 100, 100));

  for (size_t fragment : {1U, 15U, 16U, 17U, 4096U}) {
    FakeIO io(1922900); io.fragment = fragment;
    io.disconnect_at = 12347;  // includes a partial uncommitted 4 KiB buffer
    assert(downloadOta(io, io.input.size(), 30, 300000) == OtaDownloadResult::kComplete);
    assert(io.written == io.input);
    assert(io.offsets.size() == 2 && io.offsets[1] >= io.disconnect_at);
    assert(io.writes == (io.input.size() + 4095) / 4096);
    assert(io.closed == 1);
  }
  FakeIO rejected(9000); rejected.fragment = 17; rejected.disconnect_at = 103;
  rejected.reject_resume = true;
  assert(downloadOta(rejected, 9000, 30, 1000) == OtaDownloadResult::kRejected);
  assert(rejected.written.empty());
  FakeIO short_reads(10000); short_reads.read_cap = 7;
  short_reads.zero_read_once = true;
  short_reads.open_failures = 1;
  short_reads.disconnect_at = 301;
  assert(downloadOta(short_reads, 10000, 30, 1000) == OtaDownloadResult::kComplete);
  assert(short_reads.offsets.size() == 4 && short_reads.written == short_reads.input);
  assert(short_reads.writes == 3);
  FakeIO failed(100); failed.always_fail = true;
  assert(downloadOta(failed, 100, 30, 1000) == OtaDownloadResult::kTransport);
  assert(failed.offsets.size() == 4 && failed.written.empty());
  FakeIO idle(100); idle.stall = true;
  assert(downloadOta(idle, 100, 30, 1000) == OtaDownloadResult::kTransport);
  assert(idle.offsets.size() == 4 && idle.clock < 1000);
  FakeIO timeout(100); timeout.stall = true;
  timeout.clock = UINT32_MAX - 20;  // millis rollover
  assert(downloadOta(timeout, 100, 3000, 100) == OtaDownloadResult::kTimeout);
  FakeIO slow_open(100); slow_open.open_delay = 101;
  assert(downloadOta(slow_open, 100, 30, 100) == OtaDownloadResult::kTimeout);
  assert(slow_open.reads == 0);
  FakeIO slow_read(100); slow_read.read_delay = 101;
  assert(downloadOta(slow_read, 100, 30, 100) == OtaDownloadResult::kTimeout);
  assert(slow_read.written.empty());
  FakeIO slow_write(100); slow_write.write_delay = 101;
  assert(downloadOta(slow_write, 100, 30, 100) == OtaDownloadResult::kTimeout);
  FakeIO empty(0);
  assert(downloadOta(empty, 0, 30, 100) == OtaDownloadResult::kRejected);
  assert(empty.offsets.empty());
  FakeIO flash(100); flash.write_fail = true;
  assert(downloadOta(flash, 100, 30, 1000) == OtaDownloadResult::kWrite);
  assert(flash.offsets.size() == 1);
  FakeIO corrupted(100); corrupted.corrupt = true;
  assert(downloadOta(corrupted, 100, 30, 1000) == OtaDownloadResult::kComplete);
  assert(corrupted.written != corrupted.input); // caller MUST still verify hash/tag
}
