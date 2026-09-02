// src/MqttManager.cpp
// =============================================================
// smart-gatekeeper verified MQTTS manager
// Verified per-Target MQTTS and signed command dispatch.
// =============================================================
#include "MqttManager.h"
#include "config.h"
#include "ConfigManager.h"
#include "DiagnosticsManager.h"
#include "WifiManager.h"
#include "OtaManager.h"
#include "TargetAclManager.h"
#include "OfflineEventQueue.h"
#include "TargetCommandSecurity.h"
#include "FlatJsonObjectPolicy.h"
#include "DurablePreferences.h"

#include <cstring>
#include <ctime>
#include <sys/time.h>
#include <array>

#include <Preferences.h>
#include <mbedtls/ecdsa.h>
#include <mbedtls/ecp.h>

#include <esp_arduino_version.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

// main.cpp에서 정의된 외부 함수 참조
extern bool triggerManualDoorOpen(); // 원격/MQTT 수동 개방 명령
extern bool triggerArm();
extern void setTxPower(int powerDbm);
extern void setDistanceThresholdCm(int distanceCm);
extern void setPreArmDurationMs(uint32_t durationMs);

namespace {
uint32_t mqttConnectAttempts = 0;
uint32_t mqttConnectFailures = 0;
int mqttLastError = 0;
bool mqttSecurityReady = false;
bool wifiAvailableLastUpdate = false;
String commandTopic;
String aclTopic;
String commandAckTopic;
String availabilityTopic;
String statusTopic;
String eventTopic;
String canonicalEventTopic;
String sensorTopic;
String bootTopic;
String configStateTopic;

// Access events are produced by the gate-control loop and consumed by the same
// Arduino loop only after the physical access-critical phase. Keeping this
// queue single-owner avoids introducing a second PubSubClient task and the
// resulting FSM/ACL/OTA callback races while removing TLS writes from GATT,
// ultrasonic and relay transitions.
static constexpr size_t kEventOutboxCapacity = 16;
std::array<sgk::CanonicalEvent, kEventOutboxCapacity> eventOutbox{};
size_t eventOutboxHead = 0;
size_t eventOutboxCount = 0;
uint32_t eventOutboxOverflowCount = 0;

char pendingTelemetry[2048] = {};
bool pendingTelemetryValid = false;

std::array<uint8_t, 32> accessEvidenceKey{};
char accessEvidenceKeyId[sgk::kAccessEvidenceKeyIdCapacity] = {};
std::array<uint8_t, 16> accessEvidenceDoorId{};
std::array<uint8_t, 16> accessEvidenceBootId{};
char accessEvidenceTargetId[49] = {};
char accessEvidenceBootIdText[33] = {};
uint64_t accessEvidenceBootCount = 0;
uint64_t accessStatusRevision = 0;
bool accessEvidenceReady = false;

struct AccessTerminalSummary {
    bool present = false;
    std::array<uint8_t, 16> session_id{};
    char session_id_text[37] = {};
    uint64_t event_sequence = 0;
    char event_code[32] = {};
    char reason_code[24] = {};
    char credential_ref[sgk::kAccessEventCredentialRefCapacity] = {};
    uint16_t phase_mask = 0;
};

AccessTerminalSummary accessTerminalSummary{};
sgk::SignedCommandAccessTracker signedCommandAccessTracker{};
uint64_t accessEventSequenceHighWater = 0;

bool parseLowerHex16(const char* value, std::array<uint8_t, 16>* output) {
    if (value == nullptr || output == nullptr || std::strlen(value) != 32) {
        return false;
    }
    output->fill(0);
    for (size_t index = 0; index < output->size(); ++index) {
        auto nibble = [](char character, uint8_t* parsed) {
            if (parsed == nullptr) return false;
            if (character >= '0' && character <= '9') {
                *parsed = static_cast<uint8_t>(character - '0');
                return true;
            }
            if (character >= 'a' && character <= 'f') {
                *parsed = static_cast<uint8_t>(character - 'a' + 10);
                return true;
            }
            return false;
        };
        uint8_t high = 0;
        uint8_t low = 0;
        if (!nibble(value[index * 2], &high) ||
            !nibble(value[index * 2 + 1], &low)) {
            output->fill(0);
            return false;
        }
        (*output)[index] = static_cast<uint8_t>((high << 4) | low);
    }
    uint8_t aggregate = 0;
    for (uint8_t byte : *output) aggregate |= byte;
    return aggregate != 0;
}

bool parseLowerUuid4(const char* value, std::array<uint8_t, 16>* output) {
    if (value == nullptr || output == nullptr || std::strlen(value) != 36) {
        return false;
    }
    char compact[33] = {};
    size_t compact_index = 0;
    for (size_t index = 0; index < 36; ++index) {
        if (index == 8 || index == 13 || index == 18 || index == 23) {
            if (value[index] != '-') return false;
            continue;
        }
        if (compact_index >= 32) return false;
        compact[compact_index++] = value[index];
    }
    if (!parseLowerHex16(compact, output) ||
        ((*output)[6] & 0xf0) != 0x40 || ((*output)[8] & 0xc0) != 0x80) {
        output->fill(0);
        return false;
    }
    return true;
}

void bytesToLowerHex(const uint8_t* value, size_t length, char* output,
                     size_t capacity) {
    static constexpr char kHex[] = "0123456789abcdef";
    if (value == nullptr || output == nullptr || capacity < length * 2 + 1) {
        return;
    }
    for (size_t index = 0; index < length; ++index) {
        output[index * 2] = kHex[value[index] >> 4];
        output[index * 2 + 1] = kHex[value[index] & 0x0f];
    }
    output[length * 2] = '\0';
}

bool actorEventCodeAllowsCredentialRef(const char* code) {
    if (code == nullptr) return false;
    return std::strcmp(code, "ACCESS_PROOF_VERIFIED") == 0 ||
           std::strcmp(code, "ACCESS_ARMED") == 0 ||
           std::strcmp(code, "ACCESS_SENSOR_DETECTED") == 0 ||
           std::strcmp(code, "ACCESS_RELAY_ON") == 0 ||
           std::strcmp(code, "ACCESS_RELAY_OFF") == 0 ||
           std::strcmp(code, "ACCESS_SESSION_COMPLETED") == 0 ||
           std::strcmp(code, "ACCESS_SESSION_TERMINATED") == 0;
}

bool enqueueEventOutbox(const sgk::CanonicalEvent& event) {
    if (eventOutboxCount == eventOutbox.size()) {
        ++eventOutboxOverflowCount;
        return false;
    }
    const size_t tail = (eventOutboxHead + eventOutboxCount) % eventOutbox.size();
    eventOutbox[tail] = event;
    ++eventOutboxCount;
    return true;
}

bool peekEventOutbox(sgk::CanonicalEvent* event) {
    if (event == nullptr || eventOutboxCount == 0) return false;
    *event = eventOutbox[eventOutboxHead];
    return true;
}

void popEventOutbox() {
    if (eventOutboxCount == 0) return;
    eventOutboxHead = (eventOutboxHead + 1) % eventOutbox.size();
    --eventOutboxCount;
}

bool enqueueEventWithDurableSpill(const sgk::CanonicalEvent& event) {
    if (enqueueEventOutbox(event)) return true;

    // Preserve global FIFO order when the volatile queue is saturated: spill
    // its oldest record, not the newer incoming record, into the durable queue.
    sgk::CanonicalEvent oldest{};
    if (!peekEventOutbox(&oldest) || !g_offline_queue.push(oldest)) {
        return false;
    }
    popEventOutbox();
    return enqueueEventOutbox(event);
}

class NvsCommandReplayStorage final : public sgk::CommandReplayStorage {
 public:
  bool readLedger(uint8_t slot, sgk::CommandReplayLedger* ledger) override {
    if (ledger == nullptr || slot > 1) return false;
    const char* key = slot == 0 ? "ledger_a" : "ledger_b";
    const size_t read = sgk::readDurableBlobWithLegacyFallback(
        "sgk_cmd", key, ledger, sizeof(*ledger));
    return read == sizeof(*ledger);
  }

  bool writeLedger(uint8_t slot,
                   const sgk::CommandReplayLedger& ledger) override {
    if (slot > 1) return false;
    const char* key = slot == 0 ? "ledger_a" : "ledger_b";
    return sgk::writeDurableBlob("sgk_cmd", key, &ledger, sizeof(ledger));
  }
};

class P256CommandVerifier final : public sgk::CommandSignatureVerifier {
 public:
  bool configure(const char* public_key_hex, uint32_t key_id) {
    configured_ = false;
    key_id_ = key_id;
    if (public_key_hex == nullptr || std::strlen(public_key_hex) != 130 ||
        public_key_hex[0] != '0' || public_key_hex[1] != '4' || key_id == 0) {
      return false;
    }
    for (size_t index = 0; index < key_.size(); ++index) {
      char pair[3] = {public_key_hex[index * 2],
                      public_key_hex[index * 2 + 1], '\0'};
      char* end = nullptr;
      const unsigned long value = std::strtoul(pair, &end, 16);
      if (end != pair + 2 || value > 0xff) return false;
      key_[index] = static_cast<uint8_t>(value);
    }
    configured_ = true;
    return true;
  }

  bool verify(uint32_t key_id, const std::array<uint8_t, 32>& digest,
              const std::array<uint8_t, 64>& signature) override {
    if (!configured_ || key_id != key_id_ ||
        !sgk::TargetAclManager::isValidR(signature.data()) ||
        !sgk::TargetAclManager::isLowS(signature.data() + 32)) {
      return false;
    }
    mbedtls_ecp_group group;
    mbedtls_ecp_point point;
    mbedtls_mpi r;
    mbedtls_mpi s;
    mbedtls_ecp_group_init(&group);
    mbedtls_ecp_point_init(&point);
    mbedtls_mpi_init(&r);
    mbedtls_mpi_init(&s);
    const bool ok =
        mbedtls_ecp_group_load(&group, MBEDTLS_ECP_DP_SECP256R1) == 0 &&
        mbedtls_ecp_point_read_binary(&group, &point, key_.data(), key_.size()) == 0 &&
        mbedtls_mpi_read_binary(&r, signature.data(), 32) == 0 &&
        mbedtls_mpi_read_binary(&s, signature.data() + 32, 32) == 0 &&
        mbedtls_ecdsa_verify(&group, digest.data(), digest.size(), &point, &r,
                             &s) == 0;
    mbedtls_ecp_group_free(&group);
    mbedtls_ecp_point_free(&point);
    mbedtls_mpi_free(&r);
    mbedtls_mpi_free(&s);
    return ok;
  }

 private:
  std::array<uint8_t, 65> key_{};
  uint32_t key_id_ = 0;
  bool configured_ = false;
};

NvsCommandReplayStorage commandReplayStorage;
P256CommandVerifier commandSignatureVerifier;
sgk::TargetCommandSecurity commandSecurity(&commandReplayStorage,
                                           &commandSignatureVerifier);

bool parseSignatureHex(const char* value, std::array<uint8_t, 64>* output) {
  if (value == nullptr || output == nullptr || std::strlen(value) != 128) {
    return false;
  }
  for (size_t index = 0; index < output->size(); ++index) {
    char pair[3] = {value[index * 2], value[index * 2 + 1], '\0'};
    char* end = nullptr;
    const unsigned long parsed = std::strtoul(pair, &end, 16);
    if (end != pair + 2 || parsed > 0xff) return false;
    (*output)[index] = static_cast<uint8_t>(parsed);
  }
  return true;
}

}  // namespace


WiFiClientSecure MqttManager::wifiClient;
PubSubClient MqttManager::client(wifiClient);
uint32_t MqttManager::lastPublishMs = 0;
bool MqttManager::connected = false;

void MqttManager::publishCommandAck(
    const sgk::SignedCommandEnvelope& envelope, sgk::CommandResult result) {
    if (!isConnected() || commandAckTopic.isEmpty()) return;
    StaticJsonDocument<384> document;
    document["schema_version"] = 1;
    document["target_id"] = DiagnosticsManager::targetId();
    document["session_id"] = envelope.session_id;
    document["nonce"] = envelope.nonce;
    document["result"] = static_cast<uint8_t>(result);
    char buffer[384]{};
    if (serializeJson(document, buffer, sizeof(buffer)) > 0) {
        client.publish(commandAckTopic.c_str(), buffer, false);
    }
}

void MqttManager::init() {
    mqttSecurityReady = false;
    accessEvidenceReady = false;
    accessEvidenceKey.fill(0);
    accessEvidenceDoorId.fill(0);
    accessEvidenceBootId.fill(0);
    std::memset(accessEvidenceKeyId, 0, sizeof(accessEvidenceKeyId));
    std::memset(accessEvidenceTargetId, 0, sizeof(accessEvidenceTargetId));
    std::memset(accessEvidenceBootIdText, 0,
                sizeof(accessEvidenceBootIdText));
    accessEvidenceBootCount = 0;
    accessStatusRevision = 0;
    accessEventSequenceHighWater = 0;
    accessTerminalSummary = AccessTerminalSummary{};
    signedCommandAccessTracker.cancel();
    wifiAvailableLastUpdate = false;
    eventOutboxHead = 0;
    eventOutboxCount = 0;
    eventOutboxOverflowCount = 0;
    pendingTelemetryValid = false;
    const String targetId = DiagnosticsManager::targetId();
    const bool transportProvisioned =
        std::strlen(MQTT_HOST) > 0 && MQTT_PORT != 1883 &&
        std::strlen(MQTT_USER) > 0 && std::strlen(MQTT_PASSWORD) > 0 &&
        std::strlen(SECRET_ROOT_CA_CERT) > 0;
    const bool verifierProvisioned = commandSignatureVerifier.configure(
        COMMAND_SIGNER_PUBLIC_KEY_HEX, COMMAND_SIGNING_KEY_ID);
    const bool commandProvisioned = commandSecurity.begin(
        targetId.c_str(), TARGET_TENANT_ID, TARGET_DOOR_ID,
        DiagnosticsManager::bootId(), COMMAND_SIGNING_KEY_ID);
    const char* bootId = DiagnosticsManager::bootId();
    const uint64_t bootCount = DiagnosticsManager::bootCount();
    const bool evidenceProvisioned =
        targetId.length() > 0 &&
        targetId.length() < sizeof(accessEvidenceTargetId) &&
        ConfigManager::getHardwarelessDoorId(&accessEvidenceDoorId) &&
        parseLowerHex16(bootId, &accessEvidenceBootId) && bootCount > 0 &&
        sgk::parseAccessEvidenceProvisioning(
            ACCESS_EVENT_REF_KEY_HEX, ACCESS_EVENT_REF_KEY_ID,
            &accessEvidenceKey, accessEvidenceKeyId);
    if (!transportProvisioned || !verifierProvisioned || !commandProvisioned ||
        !evidenceProvisioned) {
        LOGF("[MQTT-SECURITY] Per-Target provisioning invalid "
             "(transport=%s verifier=%s command=%s evidence=%s); "
             "command/status plane disabled",
             transportProvisioned ? "ready" : "invalid",
             verifierProvisioned ? "ready" : "invalid",
             commandProvisioned ? "ready" : "invalid",
             evidenceProvisioned ? "ready" : "invalid");
        return;
    }
    std::snprintf(accessEvidenceTargetId, sizeof(accessEvidenceTargetId), "%s",
                  targetId.c_str());
    std::snprintf(accessEvidenceBootIdText,
                  sizeof(accessEvidenceBootIdText), "%s", bootId);
    accessEvidenceBootCount = bootCount;
    accessEvidenceReady = true;
    const String prefix = "gatekeeper/v1/targets/" + targetId;
    commandTopic = prefix + "/command";
    aclTopic = prefix + "/acl";
    commandAckTopic = prefix + "/command-ack";
    availabilityTopic = prefix + "/availability";
    statusTopic = prefix + "/status";
    eventTopic = prefix + "/event";
    canonicalEventTopic = prefix + "/canonical-event";
    sensorTopic = prefix + "/sensor";
    bootTopic = prefix + "/boot";
    configStateTopic = prefix + "/config-state";
    wifiClient.setCACert(SECRET_ROOT_CA_CERT);
    client.setServer(MQTT_HOST, MQTT_PORT);
    client.setBufferSize(8192); // boot diagnostics, HA discovery, and 64-entry Signed ACL payload 수용
    client.setKeepAlive(MQTT_KEEP_ALIVE_SECONDS);
    client.setSocketTimeout(15); // TLS Handshake 대기 타임아웃 15초로 확장 (rc=-4 방지)
    client.setCallback(callback);
    mqttSecurityReady = true;
}

void MqttManager::callback(char* topic, byte* payload, unsigned int length) {
    // ─── smart-gatekeeper/target/acl/push — Signed ACL push ───────────────
    if (mqttSecurityReady && strcmp(topic, aclTopic.c_str()) == 0) {
        LOGF("[MQTT-ACL] Signed ACL push 수신 (길이: %u)", length);
        extern sgk::TargetAclManager g_acl_manager;
        sgk::ResultReason res = g_acl_manager.applySignedAcl(
            reinterpret_cast<const uint8_t*>(payload), length, millis(), 0);
        if (res == sgk::ResultReason::kOk) {
            LOGF("[MQTT-ACL] ✅ Signed ACL 적용 성공 (v%llu)",
                 (unsigned long long)g_acl_manager.activeAclVersion());
            StaticJsonDocument<256> ackDoc;
            ackDoc["status"] = "applied";
            ackDoc["acl_version"] = g_acl_manager.activeAclVersion();
            ackDoc["high_watermark"] = g_acl_manager.highWatermark();
            char ackBuf[256] = {};
            serializeJson(ackDoc, ackBuf, sizeof(ackBuf));
            String ackTopic = aclTopic + "/ack";
            client.publish(ackTopic.c_str(), ackBuf, false);
        } else {
            LOGF("[MQTT-ACL] ⚠️ Signed ACL 적용 거부 (reason code: %u)",
                 static_cast<unsigned int>(res));
        }
        return;
    }

    if (!mqttSecurityReady || strcmp(topic, commandTopic.c_str()) != 0) {
        LOGF("[MQTT-SECURITY] Rejected message outside exact Target namespace");
        return;
    }

    char message[1536];
    static constexpr const char* kCommandFields[] = {
        "action", "boot_id", "door_id", "expires_at", "issued_at",
        "key_id", "nonce", "schema_version", "session_id", "signature",
        "target_id", "tenant_id", "value"};
    if (length == 0 || length >= sizeof(message) ||
        !sgk::hasExactUniqueFlatJsonFields(
            payload, length, kCommandFields,
            sizeof(kCommandFields) / sizeof(kCommandFields[0]))) {
        LOGF("[MQTT-SECURITY] Non-canonical raw command schema rejected");
        return;
    }
    memcpy(message, payload, length);
    message[length] = '\0';

    StaticJsonDocument<1536> secureDoc;
    if (deserializeJson(secureDoc, message)) {
        LOGF("[MQTT-SECURITY] Malformed signed command rejected");
        return;
    }
    if (secureDoc.size() !=
        sizeof(kCommandFields) / sizeof(kCommandFields[0])) {
        LOGF("[MQTT-SECURITY] Non-canonical command schema rejected");
        return;
    }
    for (const char* field : kCommandFields) {
        if (!secureDoc.containsKey(field)) {
            LOGF("[MQTT-SECURITY] Missing command field rejected");
            return;
        }
    }
    static constexpr const char* kCommandStringFields[] = {
        "action", "boot_id", "door_id", "nonce", "session_id",
        "signature", "target_id", "tenant_id"};
    for (const char* field : kCommandStringFields) {
        if (!secureDoc[field].is<const char*>()) {
            LOGF("[MQTT-SECURITY] Invalid command field type rejected");
            return;
        }
    }
    if (!secureDoc["schema_version"].is<uint8_t>() ||
        !secureDoc["issued_at"].is<uint64_t>() ||
        !secureDoc["expires_at"].is<uint64_t>() ||
        !secureDoc["key_id"].is<uint32_t>() ||
        !secureDoc["value"].is<int64_t>()) {
        LOGF("[MQTT-SECURITY] Invalid numeric command type rejected");
        return;
    }
    sgk::SignedCommandEnvelope envelope{};
    envelope.schema_version = secureDoc["schema_version"] | 0;
    std::snprintf(envelope.target_id, sizeof(envelope.target_id), "%s",
                  secureDoc["target_id"] | "");
    std::snprintf(envelope.tenant_id, sizeof(envelope.tenant_id), "%s",
                  secureDoc["tenant_id"] | "");
    std::snprintf(envelope.door_id, sizeof(envelope.door_id), "%s",
                  secureDoc["door_id"] | "");
    std::snprintf(envelope.boot_id, sizeof(envelope.boot_id), "%s",
                  secureDoc["boot_id"] | "");
    envelope.action = sgk::TargetCommandSecurity::parseAction(
        secureDoc["action"] | "");
    std::snprintf(envelope.session_id, sizeof(envelope.session_id), "%s",
                  secureDoc["session_id"] | "");
    std::snprintf(envelope.nonce, sizeof(envelope.nonce), "%s",
                  secureDoc["nonce"] | "");
    envelope.issued_at = secureDoc["issued_at"] | 0ULL;
    envelope.expires_at = secureDoc["expires_at"] | 0ULL;
    envelope.key_id = secureDoc["key_id"] | 0U;
    envelope.value = secureDoc["value"] | 0LL;
    if (!parseSignatureHex(secureDoc["signature"] | "", &envelope.signature)) {
        publishCommandAck(envelope, sgk::CommandResult::kMalformed);
        return;
    }

    const time_t systemTime = std::time(nullptr);
    const bool systemClockTrusted = systemTime >= 1704067200;
    const uint64_t verificationTime = systemClockTrusted
        ? static_cast<uint64_t>(systemTime)
        : 0;
    const sgk::CommandResult authorization = commandSecurity.authorize(
        envelope, verificationTime, systemClockTrusted);
    if (authorization != sgk::CommandResult::kAccepted) {
        publishCommandAck(envelope, authorization);
        return;
    }
    bool effectCompleted = true;
    bool accessLifecycleStarted = false;
    if (envelope.action == sgk::CommandAction::kArm ||
        envelope.action == sgk::CommandAction::kManualRemote) {
        const sgk::SignedCommandAccessTracker::Mode mode =
            envelope.action == sgk::CommandAction::kArm
                ? sgk::SignedCommandAccessTracker::Mode::kArm
                : sgk::SignedCommandAccessTracker::Mode::kManualRemote;
        accessLifecycleStarted =
            signedCommandAccessTracker.begin(mode, envelope.session_id);
        if (!accessLifecycleStarted) effectCompleted = false;
    }
    switch (envelope.action) {
      case sgk::CommandAction::kArm:
        if (effectCompleted) effectCompleted = triggerArm();
        break;
      case sgk::CommandAction::kManualRemote:
        if (effectCompleted) effectCompleted = triggerManualDoorOpen();
        break;
      case sgk::CommandAction::kSetTxPower:
        if (envelope.value < -6 || envelope.value > 9) effectCompleted = false;
        else setTxPower(static_cast<int>(envelope.value));
        break;
      case sgk::CommandAction::kSetDistanceThreshold:
        if (envelope.value < 20 || envelope.value > 200) effectCompleted = false;
        else setDistanceThresholdCm(static_cast<int>(envelope.value));
        break;
      case sgk::CommandAction::kSetDuration:
        if (envelope.value < PRE_ARM_MIN_DURATION_MS ||
            envelope.value > PRE_ARM_MAX_DURATION_MS) {
          effectCompleted = false;
        } else {
          setPreArmDurationMs(static_cast<uint32_t>(envelope.value));
        }
        break;
      case sgk::CommandAction::kSetRelayCooldown: {
        if (envelope.value < RELAY_COOLDOWN_MIN_MS ||
            envelope.value > RELAY_COOLDOWN_MAX_MS) {
          effectCompleted = false;
        } else {
          extern void setRelayCooldownMs(uint32_t cooldownMs);
          setRelayCooldownMs(static_cast<uint32_t>(envelope.value));
        }
        break;
      }
      case sgk::CommandAction::kOtaCheck:
        OtaManager::checkAndUpdate(true);
        break;
      case sgk::CommandAction::kReboot:
        DiagnosticsManager::markPlannedRestart("signed_mqtt_reboot");
        break;
      default:
        effectCompleted = false;
        break;
    }
    if (accessLifecycleStarted && !effectCompleted) {
        signedCommandAccessTracker.cancel();
    }
    if (!commandSecurity.markCompleted(envelope)) {
        publishCommandAck(envelope,
                          sgk::CommandResult::kReplayStorageFailure);
        return;
    }
    publishCommandAck(
        envelope, effectCompleted ? sgk::CommandResult::kAccepted
                                  : sgk::CommandResult::kEffectRejected);
    if (envelope.action == sgk::CommandAction::kReboot) {
        delay(100);
        ESP.restart();
    }
    if (!effectCompleted) {
        publishEvent("signed_command_effect_rejected",
                     sgk::TargetCommandSecurity::actionName(envelope.action));
    }
    return;

}

void MqttManager::update() {
    if (!mqttSecurityReady) return;
    const bool wifiAvailable = WifiManager::isConnected();
    if (!wifiAvailable) {
        if (wifiAvailableLastUpdate || client.connected()) {
            client.disconnect();
            wifiClient.stop();
            connected = false;
            DiagnosticsManager::noteAction("mqtt_wifi_lost");
        }
        wifiAvailableLastUpdate = false;
        return;
    }
    if (!wifiAvailableLastUpdate) {
        client.disconnect();
        wifiClient.stop();
        connected = false;
        lastPublishMs = millis() - 5001;
        wifiAvailableLastUpdate = true;
        DiagnosticsManager::noteAction("mqtt_wifi_recovered");
    }

    if (!client.connected()) {
        uint32_t now = millis();
        if (now - lastPublishMs > 5000) {
            lastPublishMs = now;
            String clientId =
                "smart-gatekeeper-" + String(DiagnosticsManager::targetId());
            
            static int failCount = 0;

            LOGF("[MQTT-SSL] 브로커 연결 시도 중... (%s:%d)", MQTT_HOST, MQTT_PORT);

            char willPayload[192];
            snprintf(willPayload, sizeof(willPayload),
                     "{\"status\":\"offline\",\"target_id\":\"%s\","
                     "\"boot_id\":\"%s\"}",
                     DiagnosticsManager::targetId(),
                     DiagnosticsManager::bootId());
            mqttConnectAttempts++;

            if (client.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD,
                               availabilityTopic.c_str(), 1, false,
                               willPayload)) {
                LOGF("[MQTT-SSL] 브로커 연결 성공!");
                failCount = 0; // 성공 시 카운트 초기화
                mqttLastError = 0;
                connected = true;
                DiagnosticsManager::noteMqttConnected();

                char onlinePayload[192];
                snprintf(onlinePayload, sizeof(onlinePayload),
                         "{\"status\":\"online\",\"target_id\":\"%s\","
                         "\"boot_id\":\"%s\",\"boot_count\":%lu}",
                         DiagnosticsManager::targetId(),
                         DiagnosticsManager::bootId(),
                         static_cast<unsigned long>(
                             DiagnosticsManager::bootCount()));
                client.publish(availabilityTopic.c_str(), onlinePayload, false);

                const bool commandSubscribed =
                    client.subscribe(commandTopic.c_str(), 1);
                const bool aclSubscribed = client.subscribe(aclTopic.c_str(), 1);
                if (!commandSubscribed || !aclSubscribed) {
                    LOGF("[MQTT-SECURITY] Exact Target subscriptions failed");
                    client.disconnect();
                    wifiClient.stop();
                    return;
                }
                LOGF("[MQTT-SECURITY] Exact per-Target topics subscribed");

                publishBootDiagnostics();
                publishEvent("connected", "ESP32-C6 v2.1 Online (SSL) — AJ-SR04T Ultrasonic Sensor");

                extern int g_tx_power_dbm;
                extern uint16_t g_distance_threshold_cm;
                extern uint32_t g_pre_arm_duration_ms;
                extern uint32_t g_relay_cooldown_ms;
                publishConfigState(g_tx_power_dbm, g_distance_threshold_cm, g_pre_arm_duration_ms, g_relay_cooldown_ms);
                return;
            } else {
                failCount++;
                mqttConnectFailures++;
                mqttLastError = client.state();
                connected = false;
                LOGF("[MQTT-ERROR] 연결 실패 rc=%d (TLS 소켓 리셋, 누적 실패: %d회)", client.state(), failCount);
                wifiClient.stop(); // 이전 소켓 핸들 및 SSL 핸드셰이크 찌꺼기 강제 정돈
            }
        }
    } else {
        client.loop();

        // Deliver the newest signed terminal/IDLE snapshot before draining the
        // audit backlog so the mobile exact-session poll is not delayed behind
        // every QoS0 lifecycle event. A failed status publish does not block the
        // durable event queue from making its own bounded retry.
        if (pendingTelemetryValid &&
            client.publish(statusTopic.c_str(), pendingTelemetry, false)) {
            pendingTelemetryValid = false;
            return;
        }

        extern sgk::OfflineEventQueue g_offline_queue;
        auto publishEventRecord = [](const sgk::CanonicalEvent& evt) {
            bool pub_ok = false;
            if (evt.is_canonical == 1 || std::strcmp(evt.event_type, "canonical_event") == 0) {
                if (evt.event_id[0] != '\0' && evt.stage_text[0] != '\0' && evt.outcome_text[0] != '\0') {
                    const bool authenticated =
                        evt.schema_version == sgk::kCanonicalEventSchemaV2;
                    if (evt.schema_version != sgk::kCanonicalEventSchemaV1 &&
                        !authenticated) {
                        return false;
                    }
                    char auth_key_id[sgk::kAccessEvidenceKeyIdCapacity] = {};
                    uint8_t auth_tag[sgk::kAccessEvidenceTagSize] = {};
                    char credential_ref[sgk::kAccessEventCredentialRefCapacity] = {};
                    if (authenticated &&
                        (evt.boot_count == 0 ||
                         !sgk::canonicalEventAccessAuth(
                             evt, auth_key_id, auth_tag, credential_ref) ||
                         (credential_ref[0] != '\0' &&
                          !actorEventCodeAllowsCredentialRef(evt.event_type)))) {
                        return false;
                    }

                    StaticJsonDocument<1280> doc;
                    doc["schema_version"] = authenticated ? "1.1" : "1.0";
                    doc["event_id"] = evt.event_id;
                    doc["session_id"] = evt.session_id;
                    doc["session_kind"] = "access";
                    doc["source_component"] = "target";
                    doc["source_instance_id"] = evt.target_ref;
                    doc["source_boot_id"] = evt.source_boot_id;
                    doc["sequence"] = evt.sequence;
                    doc["attempt"] = evt.attempt > 0 ? evt.attempt : 1;

                    doc["event_code"] = evt.event_type;
                    doc["stage"] = evt.stage_text;
                    doc["outcome"] = evt.outcome_text;
                    doc["reason_code"] = sgk::canonicalEventReason(evt);

                    JsonObject clock = doc.createNestedObject("clock");
                    clock["wall_time"] = nullptr;
                    clock["monotonic_ms"] = evt.monotonic_ms;
                    clock["quality"] = "UNSYNCED";

                    JsonObject target = doc.createNestedObject("target");
                    target["target_ref"] = evt.target_ref;
                    target["boot_id"] = evt.source_boot_id;
                    if (authenticated) target["boot_count"] = evt.boot_count;

                    if (evt.has_causation && evt.causation_event_id[0] != '\0') {
                        doc["causation_event_id"] = evt.causation_event_id;
                    } else {
                        doc["causation_event_id"] = nullptr;
                    }

                    JsonObject attributes = doc.createNestedObject("attributes");
                    attributes["path"] = "local_gatt";
                    attributes["transport"] = "ble_gatt";
                    if (authenticated && credential_ref[0] != '\0') {
                        attributes["credential_ref"] = credential_ref;
                    }

                    if (authenticated) {
                        char auth_tag_hex[sgk::kAccessEvidenceTagHexCapacity] = {};
                        bytesToLowerHex(auth_tag, sizeof(auth_tag), auth_tag_hex,
                                        sizeof(auth_tag_hex));
                        JsonObject auth = doc.createNestedObject("auth");
                        auth["version"] = 1;
                        auth["key_id"] = auth_key_id;
                        auth["tag"] = auth_tag_hex;
                    }

                    char payload_buf[1280] = {};
                    size_t bytes_needed = measureJson(doc);
                    if (!doc.overflowed() && bytes_needed > 0 &&
                        bytes_needed < sizeof(payload_buf)) {
                        size_t written = serializeJson(doc, payload_buf, sizeof(payload_buf));
                        if (written > 0) {
                            pub_ok = MqttManager::publishCanonicalEvent(payload_buf);
                        }
                    }
                } else {
                    pub_ok = false;
                }
            } else {
                StaticJsonDocument<384> doc;
                doc["event"] = evt.event_type[0] ? evt.event_type : "event";
                doc["detail"] = evt.detail;
                doc["time"] = evt.monotonic_ms;
                if (evt.sequence > 0) doc["sequence"] = evt.sequence;
                doc["target_id"] = evt.target_ref[0] ? evt.target_ref : DiagnosticsManager::targetId();
                doc["boot_id"] = evt.source_boot_id[0] ? evt.source_boot_id : DiagnosticsManager::bootId();
                doc["boot_count"] = evt.boot_count > 0 ? evt.boot_count : DiagnosticsManager::bootCount();
                char buf[384];
                size_t bytes_needed = measureJson(doc);
                if (bytes_needed > 0 && bytes_needed < sizeof(buf)) {
                    size_t written = serializeJson(doc, buf, sizeof(buf));
                    if (written > 0) {
                        pub_ok = client.publish(eventTopic.c_str(), buf, false);
                    }
                }
            }
            return pub_ok;
        };

        // Bound each update pass to one audit write. A stalled TLS socket must
        // never turn recovery flushing into an unbounded burst immediately
        // before a new local access session.
        sgk::CanonicalEvent evt{};
        if (g_offline_queue.peekFront(&evt)) {
            if (publishEventRecord(evt)) {
                g_offline_queue.popFront();
            }
            return;
        }

        if (peekEventOutbox(&evt)) {
            if (publishEventRecord(evt)) {
                popEventOutbox();
            } else if (g_offline_queue.push(evt)) {
                // Preserve the exact event and retry it from durable storage.
                popEventOutbox();
            }
            return;
        }
    }
}

void MqttManager::publishBootDiagnostics() {
    if (!isConnected()) return;

    StaticJsonDocument<1536> doc;
    doc["target_id"] = DiagnosticsManager::targetId();
    doc["boot_id"] = DiagnosticsManager::bootId();
    doc["boot_count"] = DiagnosticsManager::bootCount();
    doc["firmware"] = FIRMWARE_VERSION;
    doc["arduino_core"] = ESP_ARDUINO_VERSION_STR;
    doc["idf_version"] = esp_get_idf_version();
    doc["reset_reason"] = DiagnosticsManager::resetReason();
    doc["reset_reason_code"] = DiagnosticsManager::resetReasonCode();
    doc["planned_restart"] = DiagnosticsManager::plannedRestartReason();

    doc["previous_valid"] = DiagnosticsManager::previousBreadcrumbValid();
    doc["previous_uptime_ms"] = DiagnosticsManager::previousUptimeMs();
    doc["previous_state"] = DiagnosticsManager::previousState();
    doc["previous_action"] = DiagnosticsManager::previousAction();
    doc["previous_armed"] = DiagnosticsManager::previousArmed();
    doc["previous_relay_on"] =
        DiagnosticsManager::previousRelayCommandedOn();
    doc["previous_relay_pin"] =
        DiagnosticsManager::previousRelayPinLevel();

    doc["coredump_valid"] = DiagnosticsManager::coreDumpValid();
    int resetCode = DiagnosticsManager::resetReasonCode();
    doc["coredump_matches_reset"] =
        DiagnosticsManager::coreDumpValid() &&
        (resetCode == ESP_RST_PANIC || resetCode == ESP_RST_INT_WDT ||
         resetCode == ESP_RST_TASK_WDT || resetCode == ESP_RST_WDT ||
         resetCode == ESP_RST_CPU_LOCKUP);
    doc["coredump_status"] = DiagnosticsManager::coreDumpStatus();
    doc["coredump_size"] =
        static_cast<uint32_t>(DiagnosticsManager::coreDumpSize());
    doc["coredump_panic_reason"] =
        DiagnosticsManager::coreDumpPanicReason();
    doc["coredump_task"] = DiagnosticsManager::coreDumpTask();
    doc["coredump_pc"] = DiagnosticsManager::coreDumpPc();
    doc["coredump_mcause"] = DiagnosticsManager::coreDumpMcause();
    doc["coredump_mtval"] = DiagnosticsManager::coreDumpMtval();
    doc["coredump_elf_sha256"] =
        DiagnosticsManager::coreDumpElfSha256();

    doc["ip"] = WifiManager::getIP();
    doc["wifi_bssid"] = WiFi.BSSIDstr();
    doc["wifi_channel"] = WiFi.channel();
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["free_heap"] = ESP.getFreeHeap();
    doc["min_free_heap"] = ESP.getMinFreeHeap();
    doc["largest_free_block"] = ESP.getMaxAllocHeap();
    doc["loop_stack_hwm"] = uxTaskGetStackHighWaterMark(nullptr);
    doc["mqtt_connect_attempts"] = mqttConnectAttempts;
    doc["mqtt_connect_failures"] = mqttConnectFailures;
    doc["mqtt_last_error"] = mqttLastError;
    doc["mqtt_event_outbox_depth"] = eventOutboxCount;
    doc["mqtt_event_outbox_overflow_count"] = eventOutboxOverflowCount;

    char buffer[1536];
    size_t length = serializeJson(doc, buffer, sizeof(buffer));
    bool ok = length > 0 &&
              client.publish(bootTopic.c_str(), buffer, false);
    LOGF("[MQTT-DIAG] retained boot diagnostics publish: %s (%u bytes)",
         ok ? "OK" : "FAIL", static_cast<unsigned int>(length));
}

void MqttManager::publishConfigState(int txPower, int distanceThresholdCm, uint32_t durationMs, uint32_t relayCooldownMs) {
    if (!isConnected()) return;

    StaticJsonDocument<256> doc;
    doc["tx_power"] = txPower;
    doc["distance_threshold_cm"] = distanceThresholdCm;
    doc["tof_distance_cm"] = distanceThresholdCm; // 호환용 하위 별칭
    doc["duration_ms"] = durationMs;
    doc["relay_cooldown_ms"] = relayCooldownMs;
    doc["status"] = "applied_nvs";

    char buffer[256];
    serializeJson(doc, buffer);
    client.publish(configStateTopic.c_str(), buffer, false);
    LOGF("[MQTT-CONFIG] 📡 Retained Config State 발행 완료: %s", buffer);
}




void MqttManager::publishTelemetry(uint16_t distance_mm,
                                   const char* stateStr,
                                   bool is_armed,
                                   uint32_t armRemainingMs,
                                   bool relayCommandedOn,
                                   int relayPinLevel) {
    extern int g_tx_power_dbm;
    extern uint16_t g_distance_threshold_cm;
    extern uint32_t g_pre_arm_duration_ms;
    extern uint32_t g_relay_cooldown_ms;

    if (!accessEvidenceReady || stateStr == nullptr || stateStr[0] == '\0' ||
        (relayPinLevel != 0 && relayPinLevel != 1) ||
        accessStatusRevision == UINT64_MAX) {
        pendingTelemetryValid = false;
        return;
    }
    ++accessStatusRevision;
    sgk::AccessStatusMacInput macInput{};
    macInput.key_id = accessEvidenceKeyId;
    macInput.topic_target_id = accessEvidenceTargetId;
    macInput.door_id = accessEvidenceDoorId;
    macInput.source_boot_id = accessEvidenceBootId;
    macInput.source_boot_count = accessEvidenceBootCount;
    macInput.access_revision = accessStatusRevision;
    macInput.state = stateStr;
    macInput.has_last_terminal = accessTerminalSummary.present;
    macInput.last_terminal_session_id = accessTerminalSummary.session_id;
    macInput.last_terminal_event_sequence =
        accessTerminalSummary.event_sequence;
    macInput.last_terminal_event_code = accessTerminalSummary.event_code;
    macInput.last_terminal_reason_code = accessTerminalSummary.reason_code;
    macInput.last_terminal_credential_ref =
        accessTerminalSummary.credential_ref;
    macInput.last_terminal_phase_mask = accessTerminalSummary.phase_mask;
    macInput.relay_commanded_on = relayCommandedOn;
    macInput.relay_pin_level = static_cast<uint8_t>(relayPinLevel);
    uint8_t accessTag[sgk::kAccessEvidenceTagSize] = {};
    if (!sgk::deriveAccessStatusMac(accessEvidenceKey, macInput, accessTag)) {
        pendingTelemetryValid = false;
        return;
    }
    char accessTagHex[sgk::kAccessEvidenceTagHexCapacity] = {};
    bytesToLowerHex(accessTag, sizeof(accessTag), accessTagHex,
                    sizeof(accessTagHex));

    StaticJsonDocument<2048> doc;
    doc["distance_mm"]     = distance_mm;
    doc["distance_cm"]     = (float)distance_mm / 10.0f;
    doc["state"]           = stateStr ? stateStr : "UNKNOWN";
    doc["is_armed"]        = is_armed;
    doc["arm_remaining_s"] = armRemainingMs / 1000;
    doc["ip"]              = WifiManager::getIP();
    doc["free_heap"]       = ESP.getFreeHeap();
    doc["wifi_rssi"]       = WiFi.RSSI();
    doc["uptime_s"]        = millis() / 1000;
    doc["firmware"]        = FIRMWARE_VERSION;
    doc["target_id"]       = accessEvidenceTargetId;
    doc["boot_id"]         = accessEvidenceBootIdText;
    doc["boot_count"]      = accessEvidenceBootCount;
    doc["reset_reason"]    = DiagnosticsManager::resetReason();
    doc["relay_commanded_on"] = relayCommandedOn;
    doc["relay_pin_level"] = relayPinLevel;
    doc["access_status_revision"] = accessStatusRevision;
    if (accessTerminalSummary.present) {
        doc["last_terminal_session_id"] =
            accessTerminalSummary.session_id_text;
        doc["last_terminal_event_sequence"] =
            accessTerminalSummary.event_sequence;
        doc["last_terminal_event_code"] = accessTerminalSummary.event_code;
        doc["last_terminal_reason_code"] = accessTerminalSummary.reason_code;
        if (accessTerminalSummary.credential_ref[0] != '\0') {
            doc["last_terminal_credential_ref"] =
                accessTerminalSummary.credential_ref;
        } else {
            doc["last_terminal_credential_ref"] = nullptr;
        }
    } else {
        doc["last_terminal_session_id"] = nullptr;
        doc["last_terminal_event_sequence"] = nullptr;
        doc["last_terminal_event_code"] = nullptr;
        doc["last_terminal_reason_code"] = nullptr;
        doc["last_terminal_credential_ref"] = nullptr;
    }
    doc["last_terminal_phase_mask"] = accessTerminalSummary.phase_mask;
    JsonObject accessAuth = doc.createNestedObject("access_auth");
    accessAuth["version"] = 1;
    accessAuth["key_id"] = accessEvidenceKeyId;
    accessAuth["tag"] = accessTagHex;
    doc["min_free_heap"]   = ESP.getMinFreeHeap();
    doc["largest_free_block"] = ESP.getMaxAllocHeap();
    doc["loop_stack_hwm"]  = uxTaskGetStackHighWaterMark(nullptr);
    doc["wifi_bssid"]      = WiFi.BSSIDstr();
    doc["wifi_channel"]    = WiFi.channel();
    doc["tx_power"] = g_tx_power_dbm;
    doc["distance_threshold_cm"] = g_distance_threshold_cm;
    doc["duration_ms"] = g_pre_arm_duration_ms;
    doc["relay_cooldown_ms"] = g_relay_cooldown_ms;
    doc["mqtt_connect_count"] =
        DiagnosticsManager::mqttConnectCount();
    doc["mqtt_connect_attempts"] = mqttConnectAttempts;
    doc["mqtt_connect_failures"] = mqttConnectFailures;
    doc["mqtt_event_outbox_depth"] = eventOutboxCount;
    doc["mqtt_event_outbox_overflow_count"] = eventOutboxOverflowCount;

    const size_t telemetryBytes = measureJson(doc);
    pendingTelemetryValid = !doc.overflowed() && telemetryBytes > 0 &&
        telemetryBytes < sizeof(pendingTelemetry) &&
        serializeJson(doc, pendingTelemetry, sizeof(pendingTelemetry)) ==
            telemetryBytes;
    if (!pendingTelemetryValid) pendingTelemetry[0] = '\0';
}

void MqttManager::publishEvent(const char* eventType, const char* detail) {
    if (!eventType) return;

    sgk::CanonicalEvent event{};
    event.monotonic_ms = millis();
    event.boot_count = DiagnosticsManager::bootCount();
    std::strncpy(event.event_type, eventType, sizeof(event.event_type) - 1);
    if (detail != nullptr) {
        std::strncpy(event.detail, detail, sizeof(event.detail) - 1);
    }
    std::strncpy(event.target_ref, DiagnosticsManager::targetId(),
                 sizeof(event.target_ref) - 1);
    std::strncpy(event.source_boot_id, DiagnosticsManager::bootId(),
                 sizeof(event.source_boot_id) - 1);

    if (!enqueueEventWithDurableSpill(event)) {
        LOGF("[ERROR] MQTT event outbox and durable fallback are full");
    }
}

bool MqttManager::enqueueCanonicalEvent(const sgk::CanonicalEvent& event) {
    if (!sgk::isValidCanonicalEventRecord(event) ||
        event.is_canonical != 1 ||
        (event.schema_version == sgk::kCanonicalEventSchemaV1 &&
         event.padding == sgk::kCanonicalV2OverlayMarker) ||
        (event.schema_version != sgk::kCanonicalEventSchemaV1 &&
         event.schema_version != sgk::kCanonicalEventSchemaV2) ||
        event.event_id[0] == '\0' ||
        event.session_id[0] == '\0' || event.source_boot_id[0] == '\0' ||
        event.target_ref[0] == '\0' || event.event_type[0] == '\0' ||
        event.stage_text[0] == '\0' || event.outcome_text[0] == '\0' ||
        event.detail[0] == '\0' ||
        (event.schema_version == sgk::kCanonicalEventSchemaV1 &&
         std::memchr(event.detail, '\0', sizeof(event.detail)) == nullptr)) {
        return false;
    }
    if (event.schema_version == sgk::kCanonicalEventSchemaV2) {
        char keyId[sgk::kAccessEvidenceKeyIdCapacity] = {};
        uint8_t tag[sgk::kAccessEvidenceTagSize] = {};
        char credentialRef[sgk::kAccessEventCredentialRefCapacity] = {};
        if (event.boot_count == 0 ||
            !sgk::canonicalEventAccessAuth(event, keyId, tag, credentialRef) ||
            (credentialRef[0] != '\0' &&
             !actorEventCodeAllowsCredentialRef(event.event_type))) {
            return false;
        }
    }
    return enqueueEventWithDurableSpill(event);
}

void MqttManager::noteAccessTerminal(const char* sessionId,
                                     uint64_t eventSequence,
                                     const char* eventCode,
                                     const char* reasonCode,
                                     const char* credentialRef,
                                     uint16_t phaseMask) {
    std::array<uint8_t, 16> session{};
    const bool terminalCode =
        eventCode != nullptr &&
        (std::strcmp(eventCode, "ACCESS_SESSION_COMPLETED") == 0 ||
         std::strcmp(eventCode, "ACCESS_SESSION_TERMINATED") == 0);
    const bool credentialValid =
        credentialRef == nullptr || credentialRef[0] == '\0' ||
        sgk::isValidCanonicalCredentialRef(
            credentialRef, sgk::kAccessEventCredentialRefCapacity);
    if (!accessEvidenceReady || eventSequence == 0 || !terminalCode ||
        reasonCode == nullptr ||
        reasonCode[0] == '\0' || std::strlen(eventCode) >= 32 ||
        std::strlen(reasonCode) >= 24 || phaseMask > 0x003f ||
        !credentialValid || !parseLowerUuid4(sessionId, &session)) {
        return;
    }
    AccessTerminalSummary next{};
    next.present = true;
    next.session_id = session;
    next.event_sequence = eventSequence;
    next.phase_mask = phaseMask;
    std::snprintf(next.session_id_text, sizeof(next.session_id_text), "%s",
                  sessionId);
    std::snprintf(next.event_code, sizeof(next.event_code), "%s", eventCode);
    std::snprintf(next.reason_code, sizeof(next.reason_code), "%s",
                  reasonCode);
    if (credentialRef != nullptr && credentialRef[0] != '\0') {
        std::snprintf(next.credential_ref, sizeof(next.credential_ref), "%s",
                      credentialRef);
    }
    accessTerminalSummary = next;
    if (eventSequence > accessEventSequenceHighWater) {
        accessEventSequenceHighWater = eventSequence;
    }
}

void MqttManager::noteSignedCommandArmed() {
    signedCommandAccessTracker.noteArmed();
}

void MqttManager::noteSignedCommandSensorDetected() {
    signedCommandAccessTracker.noteSensorDetected();
}

void MqttManager::noteSignedCommandRelayOn() {
    signedCommandAccessTracker.noteRelayOn();
}

void MqttManager::noteSignedCommandRelayOff(bool failsafe) {
    signedCommandAccessTracker.noteRelayOff(failsafe);
}

uint64_t MqttManager::finishSignedCommandAccess(bool failsafe,
                                                const char* failureReason) {
    sgk::SignedCommandAccessTracker::Terminal terminal{};
    if (!signedCommandAccessTracker.finish(failsafe, &terminal) ||
        accessEventSequenceHighWater == UINT64_MAX) {
        return 0;
    }
    const uint64_t sequence = ++accessEventSequenceHighWater;
    noteAccessTerminal(
        terminal.session_id, sequence,
        terminal.completed ? "ACCESS_SESSION_COMPLETED"
                           : "ACCESS_SESSION_TERMINATED",
        terminal.completed
            ? "ACCESS_GRANTED"
            : (failureReason == nullptr ? "INTERNAL_ERROR" : failureReason),
        nullptr, terminal.phase_mask);
    return sequence;
}

bool MqttManager::publishCanonicalEvent(const char* payload) {
    if (payload == nullptr || !client.connected()) return false;
    return client.publish(canonicalEventTopic.c_str(), payload, false);
}

void MqttManager::publishSensorInfo(unsigned long duration_us, float distance_cm) {
    if (!isConnected()) return;

    StaticJsonDocument<256> doc;
    doc["duration_us"] = duration_us;
    doc["distance_cm"] = distance_cm;

    char buf[256];
    serializeJson(doc, buf, sizeof(buf));

    if (isConnected()) {
        client.publish(sensorTopic.c_str(), buf, false);
    }
}
