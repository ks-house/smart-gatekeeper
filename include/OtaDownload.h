#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace sgk {

enum class OtaOpenResult { kReady, kRetryable, kRejected };
enum class OtaDownloadResult { kComplete, kRejected, kTransport, kTimeout, kWrite };

// A resumed response must describe exactly the remaining immutable ciphertext.
// Never append a full 200 response, an unknown total or an overlapping range.
inline bool otaContentRangeMatches(const char* text, uint32_t offset,
                                   uint32_t total) {
  if (!text || std::strncmp(text, "bytes ", 6) != 0 || offset >= total) return false;
  const char* p = text + 6;
  auto number = [&p](uint32_t* output) {
    if (*p < '0' || *p > '9') return false;
    uint32_t value = 0;
    while (*p >= '0' && *p <= '9') {
      const uint32_t digit = static_cast<uint32_t>(*p++ - '0');
      if (value > (UINT32_MAX - digit) / 10) return false;
      value = value * 10 + digit;
    }
    *output = value;
    return true;
  };
  uint32_t first = 0, last = 0, size = 0;
  return number(&first) && *p++ == '-' && number(&last) && *p++ == '/' &&
      number(&size) && *p == '\0' && first == offset && last == total - 1 &&
      size == total;
}

inline bool otaResponseMatches(int code, int length, const char* range,
                               const char* encoding, uint32_t offset,
                               uint32_t total, const char* transfer = nullptr) {
  if (offset >= total || length < 0 || static_cast<uint32_t>(length) != total - offset ||
      (encoding && *encoding && std::strcmp(encoding, "identity") != 0) ||
      (transfer && *transfer)) return false;
  if (code == 200) return offset == 0 && (!range || !*range);
  return code == 206 && otaContentRangeMatches(range, offset, total);
}

// IO owns the authenticated connection and inactive image writer. It must bound
// open/read calls independently; this deadline is checked again after each call.
// No heap allocation. Short TCP/TLS reads are coalesced before decrypt/flash work.
// Across reconnects, buffered ciphertext and writer hash/GCM state remain intact.
template <typename IO>
OtaDownloadResult downloadOta(IO& io, uint32_t total, uint32_t idle_ms,
                              uint32_t total_ms, unsigned max_retries = 3) {
  uint8_t buffer[4096]{};
  size_t buffered = 0;
  uint32_t received = 0;
  const uint32_t started = io.now();
  uint32_t progress = started;
  bool opened = false;
  unsigned retries = 0;
  auto timedOut = [&]() { return uint32_t(io.now() - started) >= total_ms; };
  while (received < total) {
    io.service();
    if (timedOut()) return OtaDownloadResult::kTimeout;
    if (!opened) {
      const OtaOpenResult result = io.open(received);
      if (timedOut()) return OtaDownloadResult::kTimeout;
      if (result == OtaOpenResult::kRejected) return OtaDownloadResult::kRejected;
      if (result == OtaOpenResult::kRetryable) {
        if (retries++ >= max_retries) return OtaDownloadResult::kTransport;
        io.close();
        io.pause();
        continue;
      }
      opened = true;
      progress = io.now();
    }
    const int available = io.available();
    if (timedOut()) return OtaDownloadResult::kTimeout;
    if (available <= 0) {
      if (available < 0 || !io.connected() || uint32_t(io.now() - progress) >= idle_ms) {
        if (retries++ >= max_retries) return OtaDownloadResult::kTransport;
        io.close();
        opened = false;
      } else {
        io.pause();
      }
      continue;
    }
    const size_t wanted = std::min<size_t>(total - received,
        std::min<size_t>(static_cast<size_t>(available), sizeof(buffer) - buffered));
    const int bytes = io.read(buffer + buffered, wanted);
    if (timedOut()) return OtaDownloadResult::kTimeout;
    if (bytes <= 0) {
      if (retries++ >= max_retries) return OtaDownloadResult::kTransport;
      io.close();
      opened = false;
      continue;
    }
    if (static_cast<size_t>(bytes) > wanted) return OtaDownloadResult::kRejected;
    received += static_cast<uint32_t>(bytes);
    buffered += static_cast<size_t>(bytes);
    progress = io.now();
    if (buffered == sizeof(buffer) || received == total) {
      if (!io.write(buffer, buffered)) return OtaDownloadResult::kWrite;
      buffered = 0;
      if (timedOut()) return OtaDownloadResult::kTimeout;
    }
  }
  return received == total && total != 0 ? OtaDownloadResult::kComplete
                                        : OtaDownloadResult::kRejected;
}
}  // namespace sgk
