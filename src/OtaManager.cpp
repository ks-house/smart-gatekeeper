#include "OtaManager.h"

#include <algorithm>
#include <cstring>
#include <ctime>
#include <sys/time.h>
#include <Preferences.h>
#include <esp_app_desc.h>
#include <esp_partition.h>
#include <mbedtls/base64.h>
#include <mbedtls/sha256.h>
#include <psa/crypto.h>

#include "DiagnosticsManager.h"
#include "GattServer.h"
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
constexpr uint32_t kHealthStableMs = 30000;
constexpr uint32_t kHealthTimeoutMs = 120000;
constexpr uint16_t kProtocolMin = 1;
constexpr uint16_t kProtocolMax = 2;
constexpr const char* kBoard = "esp32-c6-devkitc-1";
constexpr const char* kLayout = "dual-ota-16mb-v1";

struct VerifiedManifest {
  String version;
  String artifact_url;
  String sha256;
  uint32_t artifact_size = 0;
  uint16_t protocol_min = 0;
  uint16_t protocol_max = 0;
  bool ready = false;
};

VerifiedManifest stagedManifest;
const esp_partition_t* updatePartition = nullptr;
esp_ota_handle_t updateHandle = 0;
mbedtls_sha256_context updateSha;
size_t updateBytes = 0;
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
      "build_id", "commit", "firmware_version", "flash_layout",
      "mandatory_after", "protocol_max", "protocol_min", "published_at",
      "schema_version", "sha256", "signature", "signature_algorithm",
      "signing_key_id", "version"};
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
      "firmware_version", "flash_layout", "published_at", "sha256",
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
  const char* firmwareVersion = document["firmware_version"] | "";
  const char* layout = document["flash_layout"] | "";
  const char* publishedAt = document["published_at"] | "";
  const char* sha256 = document["sha256"] | "";
  const char* algorithm = document["signature_algorithm"] | "";
  const char* keyId = document["signing_key_id"] | "";
  const char* signature = document["signature"] | "";
  const char* version = document["version"] | "";
  const uint32_t artifactSize = document["artifact_size"] | 0U;
  const uint16_t protocolMin = document["protocol_min"] | 0U;
  const uint16_t protocolMax = document["protocol_max"] | 0U;
  const uint8_t schemaVersion = document["schema_version"] | 0U;
  const bool mandatoryNull = document["mandatory_after"].isNull();
  const char* mandatoryAfter = mandatoryNull
      ? nullptr : document["mandatory_after"].as<const char*>();

  if (schemaVersion != 1 || std::strcmp(artifactType, "target-firmware") != 0 ||
      std::strcmp(board, kBoard) != 0 || std::strcmp(layout, kLayout) != 0 ||
      std::strcmp(algorithm, "Ed25519") != 0 ||
      std::strcmp(keyId, OTA_SIGNING_KEY_ID) != 0 ||
      std::strcmp(version, firmwareVersion) != 0 ||
      !String(artifactUrl).startsWith("https://") || artifactSize == 0 ||
      std::strlen(sha256) != 64 || std::strlen(commit) != 40 ||
      protocolMin == 0 || protocolMin > protocolMax ||
      protocolMax < kProtocolMin || protocolMin > kProtocolMax ||
      !asciiToken(version, 64) || !asciiToken(artifactUrl, 256) ||
      !asciiToken(buildId, 128) || !asciiToken(publishedAt, 64) ||
      (!mandatoryNull && !asciiToken(mandatoryAfter, 64))) {
    *reason = "manifest_semantics";
    return false;
  }
  const esp_partition_t* candidate = esp_ota_get_next_update_partition(nullptr);
  if (candidate == nullptr || artifactSize > candidate->size) {
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
  canonical += ",\"firmware_version\":" + quoted(firmwareVersion);
  canonical += ",\"flash_layout\":" + quoted(layout);
  canonical += ",\"mandatory_after\":";
  canonical += mandatoryNull ? "null" : quoted(mandatoryAfter);
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
  output->sha256 = sha256;
  output->artifact_size = artifactSize;
  output->protocol_min = protocolMin;
  output->protocol_max = protocolMax;
  output->ready = true;
  return true;
}

bool beginImageWrite() {
  if (!stagedManifest.ready || updateOpen) return false;
  updatePartition = esp_ota_get_next_update_partition(nullptr);
  if (updatePartition == nullptr ||
      stagedManifest.artifact_size > updatePartition->size ||
      esp_ota_begin(updatePartition, stagedManifest.artifact_size,
                    &updateHandle) != ESP_OK) {
    return false;
  }
  mbedtls_sha256_init(&updateSha);
  if (mbedtls_sha256_starts(&updateSha, 0) != 0) {
    esp_ota_abort(updateHandle);
    updateHandle = 0;
    return false;
  }
  updateBytes = 0;
  updateOpen = true;
  return true;
}

bool writeImageChunk(const uint8_t* data, size_t length) {
  if (!updateOpen || data == nullptr || length == 0 ||
      updateBytes + length > stagedManifest.artifact_size) return false;
  if (esp_ota_write(updateHandle, data, length) != ESP_OK ||
      mbedtls_sha256_update(&updateSha, data, length) != 0) return false;
  updateBytes += length;
  return true;
}

void abortImageWrite() {
  if (updateOpen) esp_ota_abort(updateHandle);
  mbedtls_sha256_free(&updateSha);
  updateOpen = false;
  updateHandle = 0;
  updatePartition = nullptr;
  updateBytes = 0;
}

bool finishImageWrite() {
  if (!updateOpen || updateBytes != stagedManifest.artifact_size) {
    abortImageWrite();
    return false;
  }
  uint8_t actualDigest[32]{};
  uint8_t expectedDigest[32]{};
  const bool digestFinished =
      mbedtls_sha256_finish(&updateSha, actualDigest) == 0;
  mbedtls_sha256_free(&updateSha);
  if (!digestFinished ||
      !parseHex(stagedManifest.sha256.c_str(), expectedDigest,
                sizeof(expectedDigest)) ||
      std::memcmp(actualDigest, expectedDigest, sizeof(actualDigest)) != 0) {
    esp_ota_abort(updateHandle);
    updateOpen = false;
    return false;
  }
  const bool imageValid = esp_ota_end(updateHandle) == ESP_OK;
  updateOpen = false;
  updateHandle = 0;
  if (!imageValid || updatePartition == nullptr ||
      esp_ota_set_boot_partition(updatePartition) != ESP_OK) {
    return false;
  }
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
    const bool networkHealthy = WifiManager::isConnected() || WifiManager::isAPMode();
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
  while (updateBytes < stagedManifest.artifact_size) {
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
  }
  artifactHttp.end();
  if (!downloadOk || !finishImageWrite()) {
    abortImageWrite();
    status = OtaStatus::FAILED;
    lastError = "image write/hash";
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
