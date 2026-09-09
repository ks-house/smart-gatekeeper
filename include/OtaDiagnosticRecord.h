#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <type_traits>

namespace sgk {
// Closed diagnostic vocabulary, never URLs, certificates or supplied payloads.
enum class OtaStage : uint32_t {
  kNone, kSafeState, kResourceHandoff, kManifestHttp, kManifestVerify,
  kArtifactHttp, kFlashBegin, kDownload, kImageVerify, kPendingBoot,
  kHealthWindow, kValid, kFailed, kRollback, kCurrent, kInterrupted
};
enum class OtaError : uint32_t {
  kNone, kSafeTimeout, kWifi, kTransportBusy, kManifestBegin, kManifestHttp,
  kManifestRejected, kOrigin, kConnectionReuse, kArtifactHttp, kArtifactSize,
  kFlashBegin, kDownloadTimeout, kDownloadDisconnected, kImageWrite,
  kImageVerify, kVersionStorage, kMarkValid, kHealth, kLocalAbort
};
struct OtaDiagnosticRecord {
  uint32_t schema = 1;
  uint32_t attempt = 0;
  uint32_t boot_count = 0;
  uint32_t updated_uptime_ms = 0;
  OtaStage stage = OtaStage::kNone;
  OtaStage failed_stage = OtaStage::kNone;
  OtaError error = OtaError::kNone;
  int32_t http_code = 0;
  int32_t transport_code = 0;
  uint32_t bytes = 0;
  uint32_t total = 0;
  uint32_t heap_before = 0;
  uint32_t heap_after = 0;
  uint32_t largest_after = 0;
  uint32_t rejection = 0;  // Closed manifest reason, see OTA runbook.
  int32_t flash_code = 0;
  char target_version[64] = {};
  uint32_t checksum = 0;
};
static_assert(std::is_trivially_copyable<OtaDiagnosticRecord>::value,
              "OTA diagnostics must be an independent, bounded NVS blob");
inline uint32_t otaDiagnosticChecksum(const OtaDiagnosticRecord& record) {
  const auto* bytes = reinterpret_cast<const uint8_t*>(&record);
  uint32_t crc = 0xffffffffU;
  for (size_t i = 0; i < offsetof(OtaDiagnosticRecord, checksum); ++i) {
    crc ^= bytes[i];
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
  }
  return ~crc;
}
inline bool validOtaDiagnostic(const OtaDiagnosticRecord& record) {
  return record.schema == 1 && record.checksum == otaDiagnosticChecksum(record) &&
      record.stage <= OtaStage::kInterrupted &&
      record.failed_stage <= OtaStage::kInterrupted &&
      record.error <= OtaError::kLocalAbort &&
      record.rejection <= 9 &&
      std::memchr(record.target_version, '\0', sizeof(record.target_version)) &&
      record.bytes <= record.total;
}
inline bool otaStageInFlight(OtaStage stage) {
  return stage >= OtaStage::kSafeState && stage <= OtaStage::kHealthWindow;
}
}  // namespace sgk
