#include "OtaManager.h"

#include <algorithm>
#include <cstring>
#include <ctime>
#include <sys/time.h>
#include <Preferences.h>
#include <esp_app_desc.h>
#include <esp_partition.h>
#include <mbedtls/base64.h>
#include <mbedtls/gcm.h>
#include <mbedtls/platform_util.h>
#include <mbedtls/sha256.h>
#include <psa/crypto.h>

#include "DiagnosticsManager.h"
#include "GattServer.h"
#include "MqttManager.h"
#include "OtaHealthPolicy.h"
#include "OtaVersionPolicy.h"
#include "WifiManager.h"
#include "config.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while (0)

OtaManager::OtaStatus OtaManager::status = OtaManager::OtaStatus::IDLE;
String OtaManager::lastError = "";
OtaManager::SafeStateProvider OtaManager::safeStateProvider = nullptr;

namespace {

constexpr uint32_t kOtaSafeStateTimeoutMs = 45000;
constexpr uint32_t kInitialPeriodicCheckMs = 60000;
constexpr uint32_t kPeriodicCheckMs = 6UL * 60UL * 60UL * 1000UL;
constexpr uint32_t kFailureRetryMs = 15UL * 60UL * 1000UL;
constexpr uint32_t kArtifactIdleTimeoutMs = 30UL * 1000UL;
constexpr uint32_t kArtifactDownloadTimeoutMs = 5UL * 60UL * 1000UL;
constexpr uint32_t kHealthStableMs = 30000;
constexpr uint32_t kHealthTimeoutMs = 120000;
constexpr uint16_t kProtocolMin = 1;
constexpr uint16_t kProtocolMax = 2;
constexpr const char* kBoard = "esp32-c6-devkitc-1";
constexpr const char* kLayout = "dual-ota-16mb-v1";
constexpr uint8_t kEnvelopeMagic[] = {'S', 'G', 'K', 'O', 'T', 'A', '2', 0};
constexpr size_t kEnvelopeNonceSize = 12;
constexpr size_t kEnvelopeTagSize = 16;
constexpr size_t kEnvelopeHeaderSize =
    sizeof(kEnvelopeMagic) + kEnvelopeNonceSize;
constexpr size_t kEnvelopeOverhead = kEnvelopeHeaderSize + kEnvelopeTagSize;
constexpr char kContentAadLabel[] =
    "smart-gatekeeper-target-content-v1\n";
constexpr const char* kContentEncryptionAlgorithm = "AES-256-GCM";
constexpr size_t kDecryptInputChunkSize = 4096;

struct VerifiedManifest {
  String version;
  String artifact_url;
  String commit;
  String sha256;
  String plaintext_sha256;
  uint32_t artifact_size = 0;
  uint32_t plaintext_size = 0;
  uint16_t protocol_min = 0;
  uint16_t protocol_max = 0;
  bool ready = false;
};

VerifiedManifest stagedManifest;
const esp_partition_t* updatePartition = nullptr;
esp_ota_handle_t updateHandle = 0;
mbedtls_sha256_context updateSha;
mbedtls_sha256_context updatePlaintextSha;
mbedtls_gcm_context updateGcm;
size_t updateBytes = 0;
size_t updatePlaintextBytes = 0;
size_t updateCiphertextBytes = 0;
uint8_t updateHeader[kEnvelopeHeaderSize]{};
size_t updateHeaderBytes = 0;
uint8_t updateTag[kEnvelopeTagSize]{};
size_t updateTagBytes = 0;
uint8_t updatePlaintextBuffer[kDecryptInputChunkSize + 15]{};
bool updateShaInitialized = false;
bool updatePlaintextShaInitialized = false;
bool updateGcmInitialized = false;
bool updateGcmStarted = false;
bool updateOpen = false;
uint32_t nextPeriodicCheckMs = kInitialPeriodicCheckMs;

class NvsOtaVersionFloorStorage final : public sgk::OtaVersionFloorStorage {
 public:
  bool read(uint8_t slot, sgk::OtaVersionFloorRecord* record) override {
    if (slot > 1 || record == nullptr) return false;
    Preferences preferences;
    if (!preferences.begin("sgk_ota_ver", true)) return false;
    const char* key = slot == 0 ? "floor_a" : "floor_b";
    const size_t length = preferences.getBytesLength(key);
    const size_t read = length == sizeof(*record)
                            ? preferences.getBytes(key, record, sizeof(*record))
                            : 0;
    preferences.end();
    return read == sizeof(*record);
  }

  bool write(uint8_t slot,
             const sgk::OtaVersionFloorRecord& record) override {
    if (slot > 1) return false;
    Preferences preferences;
    if (!preferences.begin("sgk_ota_ver", false)) return false;
    const char* key = slot == 0 ? "floor_a" : "floor_b";
    const size_t written = preferences.putBytes(key, &record, sizeof(record));
    preferences.end();
    return written == sizeof(record);
  }
};

NvsOtaVersionFloorStorage versionFloorStorage;
sgk::OtaVersionPolicy versionPolicy(&versionFloorStorage);
sgk::OtaHealthPolicy healthPolicy(kHealthStableMs, kHealthTimeoutMs);

bool asciiToken(const char* value, size_t maximum) {
  if (value == nullptr) return false;
  const size_t length = std::strlen(value);
  if (length == 0 || length > maximum) return false;
  for (size_t index = 0; index < length; ++index) {
    const unsigned char c = static_cast<unsigned char>(value[index]);
    if (c < 0x20 || c > 0x7e || c == '"' || c == '\\') return false;
  }
  return true;
}

String quoted(const char* value) {
  StaticJsonDocument<192> document;
  document.set(value == nullptr ? "" : value);
  String output;
  serializeJson(document, output);
  return output;
}

int64_t daysFromCivil(int year, unsigned month, unsigned day) {
  year -= month <= 2;
  const int era = (year >= 0 ? year : year - 399) / 400;
  const unsigned yearOfEra = static_cast<unsigned>(year - era * 400);
  const unsigned dayOfYear =
      static_cast<unsigned>(
          (153 * (static_cast<int>(month) + (month > 2 ? -3 : 9)) + 2) /
          5 +
          static_cast<int>(day) - 1);
  const unsigned dayOfEra =
      yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear;
  return static_cast<int64_t>(era) * 146097 + dayOfEra - 719468;
}

bool setClockFromAuthenticatedHttpDate(const String& value) {
  char weekday[4]{};
  char monthName[4]{};
  char zone[4]{};
  int day = 0;
  int year = 0;
  int hour = 0;
  int minute = 0;
  int second = 0;
  if (std::sscanf(value.c_str(), "%3s, %d %3s %d %d:%d:%d %3s", weekday,
                  &day, monthName, &year, &hour, &minute, &second, zone) != 8 ||
      std::strcmp(zone, "GMT") != 0 || year < 2024 || day < 1 || day > 31 ||
      hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 ||
      second > 60) {
    return false;
  }
  static constexpr const char* kMonths[] = {
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  unsigned month = 0;
  for (unsigned index = 0; index < 12; ++index) {
    if (std::strcmp(monthName, kMonths[index]) == 0) {
      month = index + 1;
      break;
    }
  }
  if (month == 0) return false;
  const int64_t epoch = daysFromCivil(year, month, static_cast<unsigned>(day)) *
                            86400 +
                        hour * 3600 + minute * 60 + second;
  if (epoch < 1704067200) return false;
  const time_t current = std::time(nullptr);
  if (current >= 1704067200 && epoch + 300 < current) return false;
  timeval authenticatedTime{};
  authenticatedTime.tv_sec = static_cast<time_t>(epoch);
  if (settimeofday(&authenticatedTime, nullptr) != 0) return false;
  DiagnosticsManager::noteAction("https_date_clock_trusted");
  return true;
}

bool parseHex(const char* value, uint8_t* output, size_t outputLength) {
  if (value == nullptr || output == nullptr ||
      std::strlen(value) != outputLength * 2) return false;
  for (size_t index = 0; index < outputLength; ++index) {
    char pair[3] = {value[index * 2], value[index * 2 + 1], '\0'};
    char* end = nullptr;
    const unsigned long parsed = std::strtoul(pair, &end, 16);
    if (end != pair + 2 || parsed > 0xff) return false;
    output[index] = static_cast<uint8_t>(parsed);
  }
  return true;
}

bool lowercaseHex(const char* value, size_t length) {
  if (value == nullptr || std::strlen(value) != length) return false;
  for (size_t index = 0; index < length; ++index) {
    const char c = value[index];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return true;
}

bool verifyEd25519(const String& message, const char* signatureBase64) {
  uint8_t publicKey[32]{};
  uint8_t signature[64]{};
  size_t signatureLength = 0;
  if (!parseHex(OTA_SIGNER_PUBLIC_KEY_HEX, publicKey, sizeof(publicKey)) ||
      signatureBase64 == nullptr ||
      mbedtls_base64_decode(signature, sizeof(signature), &signatureLength,
                            reinterpret_cast<const uint8_t*>(signatureBase64),
                            std::strlen(signatureBase64)) != 0 ||
      signatureLength != sizeof(signature) || psa_crypto_init() != PSA_SUCCESS) {
    return false;
  }
  psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
  psa_set_key_usage_flags(&attributes, PSA_KEY_USAGE_VERIFY_MESSAGE);
  psa_set_key_algorithm(&attributes, PSA_ALG_PURE_EDDSA);
  psa_set_key_type(
      &attributes,
      PSA_KEY_TYPE_ECC_PUBLIC_KEY(PSA_ECC_FAMILY_TWISTED_EDWARDS));
  psa_set_key_bits(&attributes, 255);
  psa_key_id_t key = 0;
  const psa_status_t imported = psa_import_key(
      &attributes, publicKey, sizeof(publicKey), &key);
  psa_reset_key_attributes(&attributes);
  if (imported != PSA_SUCCESS) return false;
  const psa_status_t verified = psa_verify_message(
      key, PSA_ALG_PURE_EDDSA,
      reinterpret_cast<const uint8_t*>(message.c_str()), message.length(),
      signature, sizeof(signature));
  psa_destroy_key(key);
  return verified == PSA_SUCCESS;
}

bool verifyManifestJson(const String& payload, VerifiedManifest* output,
                        String* reason) {
  if (output == nullptr || reason == nullptr) return false;
  output->ready = false;
  DynamicJsonDocument document(4096);
  if (deserializeJson(document, payload)) {
    *reason = "manifest_json";
    return false;
  }
  static constexpr const char* kRequiredFields[] = {
      "artifact_size", "artifact_type", "artifact_url", "board",
      "build_id", "commit", "encryption_algorithm", "encryption_key_id",
      "firmware_version", "flash_layout", "mandatory_after",
      "plaintext_sha256", "plaintext_size", "protocol_max", "protocol_min",
      "published_at", "schema_version", "sha256", "signature",
      "signature_algorithm", "signing_key_id", "version"};
  if (document.size() !=
      sizeof(kRequiredFields) / sizeof(kRequiredFields[0])) {
    *reason = "manifest_schema";
    return false;
  }
  for (const char* field : kRequiredFields) {
    if (!document.containsKey(field)) {
      *reason = "manifest_schema";
      return false;
    }
  }
  if (!document["artifact_size"].is<uint32_t>() ||
      !document["plaintext_size"].is<uint32_t>() ||
      !document["protocol_max"].is<uint16_t>() ||
      !document["protocol_min"].is<uint16_t>() ||
      !document["schema_version"].is<uint8_t>() ||
      (!document["mandatory_after"].isNull() &&
       !document["mandatory_after"].is<const char*>())) {
    *reason = "manifest_schema";
    return false;
  }
  static constexpr const char* kStringFields[] = {
      "artifact_type", "artifact_url", "board", "build_id", "commit",
      "encryption_algorithm", "encryption_key_id", "firmware_version",
      "flash_layout", "plaintext_sha256", "published_at", "sha256",
      "signature", "signature_algorithm", "signing_key_id", "version"};
  for (const char* field : kStringFields) {
    if (!document[field].is<const char*>()) {
      *reason = "manifest_schema";
      return false;
    }
  }
  const char* artifactType = document["artifact_type"] | "";
  const char* artifactUrl = document["artifact_url"] | "";
  const char* board = document["board"] | "";
  const char* buildId = document["build_id"] | "";
  const char* commit = document["commit"] | "";
  const char* encryptionAlgorithm = document["encryption_algorithm"] | "";
  const char* encryptionKeyId = document["encryption_key_id"] | "";
  const char* firmwareVersion = document["firmware_version"] | "";
  const char* layout = document["flash_layout"] | "";
  const char* plaintextSha256 = document["plaintext_sha256"] | "";
  const char* publishedAt = document["published_at"] | "";
  const char* sha256 = document["sha256"] | "";
  const char* algorithm = document["signature_algorithm"] | "";
  const char* keyId = document["signing_key_id"] | "";
  const char* signature = document["signature"] | "";
  const char* version = document["version"] | "";
  const uint32_t artifactSize = document["artifact_size"] | 0U;
  const uint32_t plaintextSize = document["plaintext_size"] | 0U;
  const uint16_t protocolMin = document["protocol_min"] | 0U;
  const uint16_t protocolMax = document["protocol_max"] | 0U;
  const uint8_t schemaVersion = document["schema_version"] | 0U;
  const bool mandatoryNull = document["mandatory_after"].isNull();
  const char* mandatoryAfter = mandatoryNull
      ? nullptr : document["mandatory_after"].as<const char*>();
  uint8_t parsedCommit[20]{};
  uint8_t parsedSha256[32]{};
  uint8_t parsedPlaintextSha256[32]{};

  if (schemaVersion != 2 || std::strcmp(artifactType, "target-firmware") != 0 ||
      std::strcmp(board, kBoard) != 0 || std::strcmp(layout, kLayout) != 0 ||
      std::strcmp(encryptionAlgorithm, kContentEncryptionAlgorithm) != 0 ||
      std::strcmp(encryptionKeyId, SECRET_OTA_CONTENT_KEY_ID) != 0 ||
      std::strcmp(algorithm, "Ed25519") != 0 ||
      std::strcmp(keyId, OTA_SIGNING_KEY_ID) != 0 ||
      std::strcmp(version, firmwareVersion) != 0 ||
      !String(artifactUrl).startsWith("https://") ||
      !String(artifactUrl).endsWith(".sgkenc") ||
      artifactSize <= kEnvelopeOverhead ||
      plaintextSize == 0 ||
      static_cast<uint64_t>(artifactSize) !=
          static_cast<uint64_t>(plaintextSize) + kEnvelopeOverhead ||
      std::strlen(sha256) != 64 || std::strlen(commit) != 40 ||
      std::strlen(plaintextSha256) != 64 ||
      !asciiToken(encryptionKeyId, 64) ||
      !asciiToken(SECRET_OTA_CONTENT_KEY_ID, 64) ||
      !lowercaseHex(SECRET_OTA_CONTENT_KEY_HEX, 64) ||
      !lowercaseHex(commit, 40) || !lowercaseHex(sha256, 64) ||
      !lowercaseHex(plaintextSha256, 64) ||
      !parseHex(commit, parsedCommit, sizeof(parsedCommit)) ||
      !parseHex(sha256, parsedSha256, sizeof(parsedSha256)) ||
      !parseHex(plaintextSha256, parsedPlaintextSha256,
                sizeof(parsedPlaintextSha256)) ||
      protocolMin == 0 || protocolMin > protocolMax ||
      protocolMax < kProtocolMin || protocolMin > kProtocolMax ||
      !asciiToken(version, 64) || !asciiToken(artifactUrl, 256) ||
      !asciiToken(buildId, 128) || !asciiToken(publishedAt, 64) ||
      (!mandatoryNull && !asciiToken(mandatoryAfter, 64))) {
    *reason = "manifest_semantics";
    return false;
  }
  const esp_partition_t* candidate = esp_ota_get_next_update_partition(nullptr);
  if (candidate == nullptr || plaintextSize > candidate->size) {
    *reason = "artifact_size";
    return false;
  }
  const sgk::OtaVersionDecision versionDecision =
      versionPolicy.evaluate(version, FIRMWARE_VERSION);
  if (versionDecision == sgk::OtaVersionDecision::kInvalid ||
      versionDecision == sgk::OtaVersionDecision::kStorageFailure) {
    *reason = "version_policy";
    return false;
  }
  if (versionDecision == sgk::OtaVersionDecision::kDowngrade) {
    *reason = "downgrade";
    return false;
  }
  if (versionDecision == sgk::OtaVersionDecision::kIdentityConflict) {
    *reason = "version_identity_conflict";
    return false;
  }

  String canonical = "{";
  canonical += "\"artifact_size\":" + String(artifactSize);
  canonical += ",\"artifact_type\":" + quoted(artifactType);
  canonical += ",\"artifact_url\":" + quoted(artifactUrl);
  canonical += ",\"board\":" + quoted(board);
  canonical += ",\"build_id\":" + quoted(buildId);
  canonical += ",\"commit\":" + quoted(commit);
  canonical += ",\"encryption_algorithm\":" + quoted(encryptionAlgorithm);
  canonical += ",\"encryption_key_id\":" + quoted(encryptionKeyId);
  canonical += ",\"firmware_version\":" + quoted(firmwareVersion);
  canonical += ",\"flash_layout\":" + quoted(layout);
  canonical += ",\"mandatory_after\":";
  canonical += mandatoryNull ? "null" : quoted(mandatoryAfter);
  canonical += ",\"plaintext_sha256\":" + quoted(plaintextSha256);
  canonical += ",\"plaintext_size\":" + String(plaintextSize);
  canonical += ",\"protocol_max\":" + String(protocolMax);
  canonical += ",\"protocol_min\":" + String(protocolMin);
  canonical += ",\"published_at\":" + quoted(publishedAt);
  canonical += ",\"schema_version\":" + String(schemaVersion);
  canonical += ",\"sha256\":" + quoted(sha256);
  canonical += ",\"signature_algorithm\":" + quoted(algorithm);
  canonical += ",\"signing_key_id\":" + quoted(keyId);
  canonical += ",\"version\":" + quoted(version) + "}";
  if (!verifyEd25519(canonical, signature)) {
    *reason = "manifest_signature";
    return false;
  }
  output->version = version;
  output->artifact_url = artifactUrl;
  output->commit = commit;
  output->sha256 = sha256;
  output->plaintext_sha256 = plaintextSha256;
  output->artifact_size = artifactSize;
  output->plaintext_size = plaintextSize;
  output->protocol_min = protocolMin;
  output->protocol_max = protocolMax;
  output->ready = true;
  return true;
}

bool constantTimeEqual(const uint8_t* left, const uint8_t* right,
                       size_t length) {
  if (left == nullptr || right == nullptr) return false;
  uint8_t difference = 0;
  for (size_t index = 0; index < length; ++index) {
    difference |= left[index] ^ right[index];
  }
  return difference == 0;
}

void releaseUpdateCrypto() {
  if (updateShaInitialized) {
    mbedtls_sha256_free(&updateSha);
    updateShaInitialized = false;
  }
  if (updatePlaintextShaInitialized) {
    mbedtls_sha256_free(&updatePlaintextSha);
    updatePlaintextShaInitialized = false;
  }
  if (updateGcmInitialized) {
    mbedtls_gcm_free(&updateGcm);
    updateGcmInitialized = false;
  }
  updateGcmStarted = false;
}

void resetUpdateState() {
  releaseUpdateCrypto();
  updateOpen = false;
  updateHandle = 0;
  updatePartition = nullptr;
  updateBytes = 0;
  updatePlaintextBytes = 0;
  updateCiphertextBytes = 0;
  updateHeaderBytes = 0;
  updateTagBytes = 0;
  mbedtls_platform_zeroize(updateHeader, sizeof(updateHeader));
  mbedtls_platform_zeroize(updateTag, sizeof(updateTag));
  mbedtls_platform_zeroize(updatePlaintextBuffer,
                           sizeof(updatePlaintextBuffer));
}

void abortImageWrite() {
  if (updateOpen) esp_ota_abort(updateHandle);
  resetUpdateState();
}

bool loadContentKey(uint8_t* key, size_t keyLength) {
  return key != nullptr && keyLength == 32 &&
         lowercaseHex(SECRET_OTA_CONTENT_KEY_HEX, keyLength * 2) &&
         parseHex(SECRET_OTA_CONTENT_KEY_HEX, key, keyLength);
}

bool initializeEnvelopeCipher() {
  if (!updateGcmInitialized || updateGcmStarted ||
      updateHeaderBytes != kEnvelopeHeaderSize ||
      std::memcmp(updateHeader, kEnvelopeMagic, sizeof(kEnvelopeMagic)) != 0) {
    return false;
  }
  uint8_t key[32]{};
  if (!loadContentKey(key, sizeof(key))) return false;
  String aad = kContentAadLabel;
  aad += stagedManifest.commit;
  aad += '\n';
  aad += SECRET_OTA_CONTENT_KEY_ID;
  aad += '\n';
  const bool started =
      mbedtls_gcm_setkey(&updateGcm, MBEDTLS_CIPHER_ID_AES, key,
                         sizeof(key) * 8) == 0 &&
      mbedtls_gcm_starts(&updateGcm, MBEDTLS_GCM_DECRYPT,
                         updateHeader + sizeof(kEnvelopeMagic),
                         kEnvelopeNonceSize) == 0 &&
      mbedtls_gcm_update_ad(
          &updateGcm, reinterpret_cast<const uint8_t*>(aad.c_str()),
          aad.length()) == 0;
  mbedtls_platform_zeroize(key, sizeof(key));
  updateGcmStarted = started;
  return started;
}

bool writeDecryptedCiphertext(const uint8_t* data, size_t length) {
  if (!updateOpen || !updateGcmStarted || data == nullptr || length == 0 ||
      updateCiphertextBytes > stagedManifest.plaintext_size ||
      length > stagedManifest.plaintext_size - updateCiphertextBytes) {
    return false;
  }
  size_t offset = 0;
  while (offset < length) {
    const size_t inputLength =
        std::min(length - offset, kDecryptInputChunkSize);
    size_t outputLength = 0;
    if (mbedtls_gcm_update(&updateGcm, data + offset, inputLength,
                           updatePlaintextBuffer,
                           sizeof(updatePlaintextBuffer), &outputLength) != 0 ||
        updatePlaintextBytes > stagedManifest.plaintext_size ||
        outputLength >
            stagedManifest.plaintext_size - updatePlaintextBytes ||
        (outputLength > 0 &&
         mbedtls_sha256_update(&updatePlaintextSha, updatePlaintextBuffer,
                               outputLength) != 0) ||
        (outputLength > 0 &&
         esp_ota_write(updateHandle, updatePlaintextBuffer, outputLength) !=
             ESP_OK)) {
      mbedtls_platform_zeroize(updatePlaintextBuffer,
                               sizeof(updatePlaintextBuffer));
      return false;
    }
    updatePlaintextBytes += outputLength;
    updateCiphertextBytes += inputLength;
    offset += inputLength;
  }
  mbedtls_platform_zeroize(updatePlaintextBuffer,
                           sizeof(updatePlaintextBuffer));
  return true;
}

bool consumeEnvelopePayload(const uint8_t* data, size_t length) {
  if (length == 0) return true;
  if (data == nullptr || !updateGcmStarted) return false;
  if (updateTagBytes < kEnvelopeTagSize) {
    const size_t copied =
        std::min(length, kEnvelopeTagSize - updateTagBytes);
    std::memcpy(updateTag + updateTagBytes, data, copied);
    updateTagBytes += copied;
    data += copied;
    length -= copied;
    if (length == 0) return true;
  }

  if (length >= kEnvelopeTagSize) {
    if (!writeDecryptedCiphertext(updateTag, kEnvelopeTagSize)) return false;
    const size_t directCiphertextLength = length - kEnvelopeTagSize;
    if (directCiphertextLength > 0 &&
        !writeDecryptedCiphertext(data, directCiphertextLength)) {
      return false;
    }
    std::memcpy(updateTag, data + directCiphertextLength, kEnvelopeTagSize);
    return true;
  }

  if (!writeDecryptedCiphertext(updateTag, length)) return false;
  std::memmove(updateTag, updateTag + length, kEnvelopeTagSize - length);
  std::memcpy(updateTag + kEnvelopeTagSize - length, data, length);
  return true;
}

bool beginImageWrite() {
  if (!stagedManifest.ready || updateOpen) return false;
  updatePartition = esp_ota_get_next_update_partition(nullptr);
  if (updatePartition == nullptr || stagedManifest.plaintext_size == 0 ||
      stagedManifest.plaintext_size > updatePartition->size ||
      static_cast<uint64_t>(stagedManifest.artifact_size) !=
          static_cast<uint64_t>(stagedManifest.plaintext_size) +
              kEnvelopeOverhead ||
      esp_ota_begin(updatePartition, stagedManifest.plaintext_size,
                    &updateHandle) != ESP_OK) {
    updatePartition = nullptr;
    updateHandle = 0;
    return false;
  }
  updateOpen = true;
  mbedtls_sha256_init(&updateSha);
  updateShaInitialized = true;
  mbedtls_sha256_init(&updatePlaintextSha);
  updatePlaintextShaInitialized = true;
  mbedtls_gcm_init(&updateGcm);
  updateGcmInitialized = true;
  if (mbedtls_sha256_starts(&updateSha, 0) != 0 ||
      mbedtls_sha256_starts(&updatePlaintextSha, 0) != 0) {
    abortImageWrite();
    return false;
  }
  updateBytes = 0;
  updatePlaintextBytes = 0;
  updateCiphertextBytes = 0;
  updateHeaderBytes = 0;
  updateTagBytes = 0;
  mbedtls_platform_zeroize(updateHeader, sizeof(updateHeader));
  mbedtls_platform_zeroize(updateTag, sizeof(updateTag));
  mbedtls_platform_zeroize(updatePlaintextBuffer,
                           sizeof(updatePlaintextBuffer));
  return true;
}

bool writeImageChunk(const uint8_t* data, size_t length) {
  if (!updateOpen || data == nullptr || length == 0 ||
      updateBytes > stagedManifest.artifact_size ||
      length > stagedManifest.artifact_size - updateBytes ||
      mbedtls_sha256_update(&updateSha, data, length) != 0) {
    return false;
  }
  updateBytes += length;
  size_t offset = 0;
  if (updateHeaderBytes < kEnvelopeHeaderSize) {
    const size_t copied =
        std::min(length, kEnvelopeHeaderSize - updateHeaderBytes);
    std::memcpy(updateHeader + updateHeaderBytes, data, copied);
    updateHeaderBytes += copied;
    offset += copied;
    if (updateHeaderBytes == kEnvelopeHeaderSize &&
        !initializeEnvelopeCipher()) {
      return false;
    }
  }
  return consumeEnvelopePayload(data + offset, length - offset);
}

bool finishImageWrite() {
  if (!updateOpen || !updateGcmStarted ||
      updateBytes != stagedManifest.artifact_size ||
      updateHeaderBytes != kEnvelopeHeaderSize ||
      updateTagBytes != kEnvelopeTagSize ||
      updateCiphertextBytes != stagedManifest.plaintext_size) {
    abortImageWrite();
    return false;
  }

  uint8_t actualDigest[32]{};
  uint8_t expectedDigest[32]{};
  uint8_t actualPlaintextDigest[32]{};
  uint8_t expectedPlaintextDigest[32]{};
  uint8_t actualTag[kEnvelopeTagSize]{};
  uint8_t finalPlaintext[15]{};
  size_t finalPlaintextLength = 0;
  const bool digestFinished =
      mbedtls_sha256_finish(&updateSha, actualDigest) == 0;
  mbedtls_sha256_free(&updateSha);
  updateShaInitialized = false;
  const bool cipherFinished =
      mbedtls_gcm_finish(&updateGcm, finalPlaintext, sizeof(finalPlaintext),
                         &finalPlaintextLength, actualTag,
                         sizeof(actualTag)) == 0;
  const bool finalPlaintextSizeValid =
      updatePlaintextBytes <= stagedManifest.plaintext_size &&
      finalPlaintextLength <=
          stagedManifest.plaintext_size - updatePlaintextBytes &&
      updatePlaintextBytes + finalPlaintextLength ==
          stagedManifest.plaintext_size;
  const bool plaintextDigestFinished =
      cipherFinished && finalPlaintextSizeValid &&
      (finalPlaintextLength == 0 ||
       mbedtls_sha256_update(&updatePlaintextSha, finalPlaintext,
                             finalPlaintextLength) == 0) &&
      mbedtls_sha256_finish(&updatePlaintextSha, actualPlaintextDigest) == 0;
  mbedtls_sha256_free(&updatePlaintextSha);
  updatePlaintextShaInitialized = false;
  const bool authenticated =
      digestFinished && cipherFinished && plaintextDigestFinished &&
      parseHex(stagedManifest.sha256.c_str(), expectedDigest,
               sizeof(expectedDigest)) &&
      parseHex(stagedManifest.plaintext_sha256.c_str(),
               expectedPlaintextDigest, sizeof(expectedPlaintextDigest)) &&
      constantTimeEqual(actualDigest, expectedDigest, sizeof(actualDigest)) &&
      constantTimeEqual(actualPlaintextDigest, expectedPlaintextDigest,
                        sizeof(actualPlaintextDigest)) &&
      constantTimeEqual(actualTag, updateTag, sizeof(actualTag)) &&
      finalPlaintextSizeValid;
  if (!authenticated ||
      (finalPlaintextLength > 0 &&
       esp_ota_write(updateHandle, finalPlaintext, finalPlaintextLength) !=
           ESP_OK)) {
    mbedtls_platform_zeroize(actualDigest, sizeof(actualDigest));
    mbedtls_platform_zeroize(expectedDigest, sizeof(expectedDigest));
    mbedtls_platform_zeroize(actualPlaintextDigest,
                             sizeof(actualPlaintextDigest));
    mbedtls_platform_zeroize(expectedPlaintextDigest,
                             sizeof(expectedPlaintextDigest));
    mbedtls_platform_zeroize(actualTag, sizeof(actualTag));
    mbedtls_platform_zeroize(finalPlaintext, sizeof(finalPlaintext));
    abortImageWrite();
    return false;
  }
  updatePlaintextBytes += finalPlaintextLength;
  mbedtls_platform_zeroize(actualDigest, sizeof(actualDigest));
  mbedtls_platform_zeroize(expectedDigest, sizeof(expectedDigest));
  mbedtls_platform_zeroize(actualPlaintextDigest,
                           sizeof(actualPlaintextDigest));
  mbedtls_platform_zeroize(expectedPlaintextDigest,
                           sizeof(expectedPlaintextDigest));
  mbedtls_platform_zeroize(actualTag, sizeof(actualTag));
  mbedtls_platform_zeroize(finalPlaintext, sizeof(finalPlaintext));
  mbedtls_gcm_free(&updateGcm);
  updateGcmInitialized = false;
  updateGcmStarted = false;

  const esp_ota_handle_t completedHandle = updateHandle;
  const esp_partition_t* completedPartition = updatePartition;
  updateOpen = false;
  updateHandle = 0;
  updatePartition = nullptr;
  const bool imageValid = esp_ota_end(completedHandle) == ESP_OK;
  if (!imageValid || completedPartition == nullptr ||
      esp_ota_set_boot_partition(completedPartition) != ESP_OK) {
    resetUpdateState();
    return false;
  }
  resetUpdateState();
  return true;
}

bool waitForSafeState() {
  GattServer::setOtaBusy(true);
  GattServer::flushOtaBusy(3000);
  const uint32_t started = millis();
  while (OtaManager::getStatus() == OtaManager::OtaStatus::WAIT_SAFE_STATE &&
         !OtaManager::isSafeForOta()) {
    GattServer::update();
    if (millis() - started >= kOtaSafeStateTimeoutMs) return false;
    delay(10);
  }
  return OtaManager::isSafeForOta();
}

}  // namespace

void OtaManager::init() {
  status = OtaStatus::IDLE;
  lastError = "";
  if (!versionPolicy.begin(FIRMWARE_VERSION)) {
    status = OtaStatus::FAILED;
    lastError = "version floor storage";
    return;
  }
  const esp_partition_t* running = esp_ota_get_running_partition();
  esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
  if (running != nullptr && esp_ota_get_state_partition(running, &state) == ESP_OK &&
      state == ESP_OTA_IMG_PENDING_VERIFY) {
    status = OtaStatus::HEALTH_WINDOW;
    healthPolicy.begin(millis());
    DiagnosticsManager::noteAction("ota_health_window");
  }
}

void OtaManager::setSafeStateProvider(SafeStateProvider provider) {
  safeStateProvider = provider;
}

bool OtaManager::isSafeForOta() {
  return safeStateProvider != nullptr &&
         safeStateProvider() == OtaSafeState::SAFE;
}

void OtaManager::update() {
  const uint32_t now = millis();
  if (status == OtaStatus::HEALTH_WINDOW) {
    const bool safe = safeStateProvider != nullptr &&
                      safeStateProvider() == OtaSafeState::SAFE;
    const bool networkHealthy =
        WifiManager::isConnected() && MqttManager::isConnected();
    const sgk::OtaHealthDecision decision = healthPolicy.update(
        now, safe && networkHealthy && ESP.getFreeHeap() >= 65536);
    if (decision == sgk::OtaHealthDecision::kMarkValid) {
      if (versionPolicy.commit(FIRMWARE_VERSION) &&
          esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) {
        status = OtaStatus::SUCCESS;
        DiagnosticsManager::noteAction("ota_mark_valid");
      } else {
        status = OtaStatus::ROLLING_BACK;
        DiagnosticsManager::markPlannedRestart("ota_valid_mark_failed");
        esp_ota_mark_app_invalid_rollback_and_reboot();
      }
    } else if (decision == sgk::OtaHealthDecision::kRollback) {
      status = OtaStatus::ROLLING_BACK;
      DiagnosticsManager::markPlannedRestart("ota_health_rollback");
      esp_ota_mark_app_invalid_rollback_and_reboot();
    }
    return;
  }
  if (status == OtaStatus::DOWNLOADING || status == OtaStatus::VERIFYING ||
      status == OtaStatus::WAIT_SAFE_STATE) return;
  if (WifiManager::isConnected() && static_cast<int32_t>(now - nextPeriodicCheckMs) >= 0) {
    checkAndUpdate(false);
  }
}

void OtaManager::checkAndUpdate(bool force) {
  (void)force;
  status = OtaStatus::WAIT_SAFE_STATE;
  struct BusyGuard {
    ~BusyGuard() { GattServer::setOtaBusy(false); }
  } guard;
  if (!waitForSafeState()) {
    status = OtaStatus::FAILED;
    lastError = "WAIT_SAFE_STATE timeout";
    nextPeriodicCheckMs = millis() + kFailureRetryMs;
    return;
  }
  if (!WifiManager::isConnected()) {
    status = OtaStatus::FAILED;
    lastError = "Wi-Fi unavailable";
    nextPeriodicCheckMs = millis() + kFailureRetryMs;
    return;
  }
  status = OtaStatus::CHECKING;
  WiFiClientSecure manifestClient;
  manifestClient.setCACert(SECRET_ROOT_CA_CERT);
  HTTPClient manifestHttp;
  if (!manifestHttp.begin(manifestClient, OTA_VERSION_URL)) {
    status = OtaStatus::FAILED;
    lastError = "manifest begin";
    nextPeriodicCheckMs = millis() + kFailureRetryMs;
    return;
  }
  manifestHttp.setTimeout(10000);
  const char* responseHeaders[] = {"Date"};
  manifestHttp.collectHeaders(responseHeaders, 1);
  const int manifestCode = manifestHttp.GET();
  if (manifestCode != HTTP_CODE_OK) {
    manifestHttp.end();
    status = OtaStatus::FAILED;
    lastError = "manifest HTTP";
    nextPeriodicCheckMs = millis() + kFailureRetryMs;
    return;
  }
  setClockFromAuthenticatedHttpDate(manifestHttp.header("Date"));
  const String payload = manifestHttp.getString();
  manifestHttp.end();
  status = OtaStatus::VERIFYING;
  String reason;
  if (!verifyManifestJson(payload, &stagedManifest, &reason)) {
    status = OtaStatus::FAILED;
    lastError = reason;
    nextPeriodicCheckMs = millis() + kFailureRetryMs;
    return;
  }
  if (stagedManifest.version == FIRMWARE_VERSION) {
    status = OtaStatus::UP_TO_DATE;
    nextPeriodicCheckMs = millis() + kPeriodicCheckMs;
    return;
  }

  WiFiClientSecure artifactClient;
  artifactClient.setCACert(SECRET_ROOT_CA_CERT);
  HTTPClient artifactHttp;
  if (!artifactHttp.begin(artifactClient, stagedManifest.artifact_url)) {
    status = OtaStatus::FAILED;
    lastError = "artifact begin";
    nextPeriodicCheckMs = millis() + kFailureRetryMs;
    return;
  }
  artifactHttp.setTimeout(15000);
  const int artifactCode = artifactHttp.GET();
  if (artifactCode != HTTP_CODE_OK ||
      artifactHttp.getSize() != static_cast<int>(stagedManifest.artifact_size) ||
      !beginImageWrite()) {
    artifactHttp.end();
    status = OtaStatus::FAILED;
    lastError = "artifact HTTP/size";
    nextPeriodicCheckMs = millis() + kFailureRetryMs;
    return;
  }
  status = OtaStatus::DOWNLOADING;
  WiFiClient* stream = artifactHttp.getStreamPtr();
  uint8_t buffer[4096]{};
  bool downloadOk = true;
  bool downloadTimedOut = false;
  const uint32_t downloadStartedMs = millis();
  uint32_t lastProgressMs = downloadStartedMs;
  while (updateBytes < stagedManifest.artifact_size) {
    const uint32_t observedMs = millis();
    if (observedMs - downloadStartedMs >= kArtifactDownloadTimeoutMs ||
        observedMs - lastProgressMs >= kArtifactIdleTimeoutMs) {
      downloadTimedOut = true;
      downloadOk = false;
      break;
    }
    const size_t remaining = stagedManifest.artifact_size - updateBytes;
    const size_t available = stream->available();
    if (available == 0) {
      if (!artifactHttp.connected()) { downloadOk = false; break; }
      delay(1);
      continue;
    }
    const size_t wanted = std::min(remaining, std::min(available, sizeof(buffer)));
    const int received = stream->readBytes(buffer, wanted);
    if (received <= 0 ||
        !writeImageChunk(buffer, static_cast<size_t>(received))) {
      downloadOk = false;
      break;
    }
    lastProgressMs = millis();
  }
  artifactHttp.end();
  if (!downloadOk || !finishImageWrite()) {
    abortImageWrite();
    status = OtaStatus::FAILED;
    lastError = downloadTimedOut ? "artifact download timeout"
                                 : "image write/hash";
    nextPeriodicCheckMs = millis() + kFailureRetryMs;
    return;
  }
  status = OtaStatus::PENDING_BOOT;
  DiagnosticsManager::markPlannedRestart("ota_pending_verify");
  delay(250);
  ESP.restart();
}

bool OtaManager::stageLocalManifest(const String& manifestJson) {
  String reason;
  bool valid = verifyManifestJson(manifestJson, &stagedManifest, &reason);
  if (valid && stagedManifest.version == FIRMWARE_VERSION) {
    valid = false;
    reason = "current version reflash denied";
    stagedManifest = VerifiedManifest{};
  }
  if (!valid) {
    lastError = reason;
    status = OtaStatus::FAILED;
  } else {
    status = OtaStatus::VERIFYING;
  }
  return valid;
}

bool OtaManager::beginLocalUpload() {
  status = OtaStatus::WAIT_SAFE_STATE;
  if (!waitForSafeState()) {
    abortLocalUpload("WAIT_SAFE_STATE timeout");
    return false;
  }
  if (!beginImageWrite()) {
    abortLocalUpload("local begin failed");
    return false;
  }
  status = OtaStatus::DOWNLOADING;
  return true;
}

bool OtaManager::writeLocalUploadChunk(const uint8_t* data, size_t length) {
  if (!writeImageChunk(data, length)) {
    abortLocalUpload("local write failed");
    return false;
  }
  return true;
}

bool OtaManager::finishLocalUpload() {
  if (!finishImageWrite()) {
    abortLocalUpload("local hash/image failed");
    return false;
  }
  status = OtaStatus::PENDING_BOOT;
  DiagnosticsManager::markPlannedRestart("local_ota_pending_verify");
  GattServer::setOtaBusy(false);
  return true;
}

void OtaManager::abortLocalUpload(const char* reason) {
  abortImageWrite();
  stagedManifest.ready = false;
  lastError = reason == nullptr ? "local upload aborted" : reason;
  status = OtaStatus::FAILED;
  GattServer::setOtaBusy(false);
}

bool OtaManager::localManifestReady() { return stagedManifest.ready; }
