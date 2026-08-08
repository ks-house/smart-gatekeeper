#include "OtaManager.h"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <Preferences.h>
#include <esp_app_desc.h>
#include <esp_partition.h>
#include <mbedtls/base64.h>
#include <mbedtls/sha256.h>
#include <psa/crypto.h>

#include "DiagnosticsManager.h"
#include "GattServer.h"
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
uint32_t healthStartedMs = 0;
uint32_t nextPeriodicCheckMs = kInitialPeriodicCheckMs;

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

int compareVersion(const String& left, const String& right) {
  size_t leftStart = 0;
  size_t rightStart = 0;
  for (int component = 0; component < 3; ++component) {
    const int leftDot = left.indexOf('.', leftStart);
    const int rightDot = right.indexOf('.', rightStart);
    String leftPart = left.substring(
        leftStart, leftDot < 0 ? left.length() : static_cast<size_t>(leftDot));
    String rightPart = right.substring(
        rightStart, rightDot < 0 ? right.length() : static_cast<size_t>(rightDot));
    if (component == 2) {
      int suffix = leftPart.indexOf('-');
      const int metadata = leftPart.indexOf('+');
      if (suffix < 0 || (metadata >= 0 && metadata < suffix)) suffix = metadata;
      if (suffix >= 0) leftPart = leftPart.substring(0, suffix);
      suffix = rightPart.indexOf('-');
      const int rightMetadata = rightPart.indexOf('+');
      if (suffix < 0 || (rightMetadata >= 0 && rightMetadata < suffix)) {
        suffix = rightMetadata;
      }
      if (suffix >= 0) rightPart = rightPart.substring(0, suffix);
    }
    if (leftPart.length() == 0 || rightPart.length() == 0) return -2;
    for (size_t i = 0; i < leftPart.length(); ++i) {
      if (!std::isdigit(static_cast<unsigned char>(leftPart[i]))) return -2;
    }
    for (size_t i = 0; i < rightPart.length(); ++i) {
      if (!std::isdigit(static_cast<unsigned char>(rightPart[i]))) return -2;
    }
    const long leftValue = leftPart.toInt();
    const long rightValue = rightPart.toInt();
    if (leftValue != rightValue) return leftValue < rightValue ? -1 : 1;
    if (leftDot < 0 || rightDot < 0) {
      if (component != 2) return -2;
    }
    leftStart = static_cast<size_t>(leftDot + 1);
    rightStart = static_cast<size_t>(rightDot + 1);
  }
  return 0;
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
  Preferences preferences;
  String floor = FIRMWARE_VERSION;
  if (preferences.begin("sgk_ota", true)) {
    floor = preferences.getString("version_floor", FIRMWARE_VERSION);
    preferences.end();
  }
  if (compareVersion(version, FIRMWARE_VERSION) < 0 ||
      compareVersion(version, floor) < 0) {
    *reason = "downgrade";
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
  const esp_partition_t* running = esp_ota_get_running_partition();
  esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
  if (running != nullptr && esp_ota_get_state_partition(running, &state) == ESP_OK &&
      state == ESP_OTA_IMG_PENDING_VERIFY) {
    status = OtaStatus::HEALTH_WINDOW;
    healthStartedMs = millis();
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
    if (safe && networkHealthy && ESP.getFreeHeap() >= 65536 &&
        now - healthStartedMs >= kHealthStableMs) {
      if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) {
        Preferences preferences;
        if (preferences.begin("sgk_ota", false)) {
          preferences.putString("version_floor", FIRMWARE_VERSION);
          preferences.end();
        }
        status = OtaStatus::SUCCESS;
        DiagnosticsManager::noteAction("ota_mark_valid");
      }
    } else if (now - healthStartedMs >= kHealthTimeoutMs) {
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
  const int manifestCode = manifestHttp.GET();
  if (manifestCode != HTTP_CODE_OK) {
    manifestHttp.end();
    status = OtaStatus::FAILED;
    lastError = "manifest HTTP";
    nextPeriodicCheckMs = millis() + kFailureRetryMs;
    return;
  }
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
  if (!force && stagedManifest.version == FIRMWARE_VERSION) {
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
  const bool valid = verifyManifestJson(manifestJson, &stagedManifest, &reason);
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
