// src/MqttManager.cpp
// =============================================================
// smart-gatekeeper verified MQTTS manager
// Verified per-Target MQTTS and signed command dispatch.
// =============================================================
#include "MqttManager.h"
#include "config.h"
#include "DiagnosticsManager.h"
#include "WifiManager.h"
#include "OtaManager.h"
#include "TargetAclManager.h"
#include "OfflineEventQueue.h"
#include "TargetCommandSecurity.h"

#include <cstring>
#include <ctime>
#include <sys/time.h>

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

class NvsCommandReplayStorage final : public sgk::CommandReplayStorage {
 public:
  bool readLedger(uint8_t slot, sgk::CommandReplayLedger* ledger) override {
    if (ledger == nullptr || slot > 1) return false;
    Preferences preferences;
    if (!preferences.begin("sgk_cmd", true)) return false;
    const char* key = slot == 0 ? "ledger_a" : "ledger_b";
    const size_t length = preferences.getBytesLength(key);
    const size_t read = length == sizeof(*ledger)
                            ? preferences.getBytes(key, ledger, sizeof(*ledger))
                            : 0;
    preferences.end();
    return read == sizeof(*ledger);
  }

  bool writeLedger(uint8_t slot,
                   const sgk::CommandReplayLedger& ledger) override {
    if (slot > 1) return false;
    Preferences preferences;
    if (!preferences.begin("sgk_cmd", false)) return false;
    const char* key = slot == 0 ? "ledger_a" : "ledger_b";
    const size_t written = preferences.putBytes(key, &ledger, sizeof(ledger));
    preferences.end();
    return written == sizeof(ledger);
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
    const String targetId = DiagnosticsManager::targetId();
    const bool transportProvisioned =
        std::strlen(MQTT_HOST) > 0 && MQTT_PORT != 1883 &&
        std::strlen(MQTT_USER) > 0 && std::strlen(MQTT_PASSWORD) > 0 &&
        std::strlen(SECRET_ROOT_CA_CERT) > 0 && targetId == MQTT_USER;
    const bool verifierProvisioned = commandSignatureVerifier.configure(
        COMMAND_SIGNER_PUBLIC_KEY_HEX, COMMAND_SIGNING_KEY_ID);
    const bool commandProvisioned = commandSecurity.begin(
        targetId.c_str(), TARGET_TENANT_ID, TARGET_DOOR_ID,
        DiagnosticsManager::bootId(), COMMAND_SIGNING_KEY_ID);
    if (!transportProvisioned || !verifierProvisioned || !commandProvisioned) {
        LOGF("[MQTT-SECURITY] Per-Target TLS/identity/signing provisioning invalid; command plane disabled");
        return;
    }
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
    client.setKeepAlive(30);
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

    if (length >= sizeof(message)) length = sizeof(message) - 1;
    memcpy(message, payload, length);
    message[length] = '\0';

    StaticJsonDocument<1536> secureDoc;
    if (deserializeJson(secureDoc, message)) {
        LOGF("[MQTT-SECURITY] Malformed signed command rejected");
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
    // The first clock anchor is safe because it remains boot-bound and is not
    // committed or acted on unless the envelope signature verifies.
    const uint64_t verificationTime = systemClockTrusted
        ? static_cast<uint64_t>(systemTime)
        : envelope.issued_at;
    const sgk::CommandResult authorization = commandSecurity.authorize(
        envelope, verificationTime, true);
    if (authorization != sgk::CommandResult::kAccepted) {
        publishCommandAck(envelope, authorization);
        return;
    }
    if (!systemClockTrusted) {
        timeval signedTime{};
        signedTime.tv_sec = static_cast<time_t>(envelope.issued_at);
        settimeofday(&signedTime, nullptr);
    }

    bool effectCompleted = true;
    switch (envelope.action) {
      case sgk::CommandAction::kArm:
        effectCompleted = triggerArm();
        break;
      case sgk::CommandAction::kManualRemote:
        effectCompleted = triggerManualDoorOpen();
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
        if (envelope.value < 1000 || envelope.value > 60000) effectCompleted = false;
        else setPreArmDurationMs(static_cast<uint32_t>(envelope.value));
        break;
      case sgk::CommandAction::kSetRelayCooldown: {
        if (envelope.value < 1000 || envelope.value > 10000) {
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
    if (!mqttSecurityReady || !WifiManager::isConnected()) return;

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
                LOGF("[MQTT-ERROR] 연결 실패 rc=%d (TLS 소켓 리셋, 누적 실패: %d회)", client.state(), failCount);
                wifiClient.stop(); // 이전 소켓 핸들 및 SSL 핸드셰이크 찌꺼기 강제 정돈
            }
        }
    } else {
        client.loop();

        extern sgk::OfflineEventQueue g_offline_queue;
        sgk::CanonicalEvent evt{};
        while (client.connected() && g_offline_queue.peekFront(&evt)) {
            bool pub_ok = false;
            if (evt.is_canonical == 1 || std::strcmp(evt.event_type, "canonical_event") == 0) {
                if (evt.event_id[0] != '\0' && evt.stage_text[0] != '\0' && evt.outcome_text[0] != '\0') {
                    StaticJsonDocument<1024> doc;
                    doc["schema_version"] = "1.0";
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
                    doc["reason_code"] = evt.detail;

                    JsonObject clock = doc.createNestedObject("clock");
                    clock["wall_time"] = nullptr;
                    clock["monotonic_ms"] = evt.monotonic_ms;
                    clock["quality"] = "UNSYNCED";

                    JsonObject target = doc.createNestedObject("target");
                    target["target_ref"] = evt.target_ref;
                    target["boot_id"] = evt.source_boot_id;

                    if (evt.has_causation && evt.causation_event_id[0] != '\0') {
                        doc["causation_event_id"] = evt.causation_event_id;
                    } else {
                        doc["causation_event_id"] = nullptr;
                    }

                    JsonObject attributes = doc.createNestedObject("attributes");
                    attributes["path"] = "local_gatt";
                    attributes["transport"] = "ble_gatt";

                    char payload_buf[1024] = {};
                    size_t bytes_needed = measureJson(doc);
                    if (bytes_needed > 0 && bytes_needed < sizeof(payload_buf)) {
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
            if (pub_ok) {
                g_offline_queue.popFront(); // Dequeue confirmed publish success
            } else {
                break; // Pause flushing if publish failed or record invalid
            }
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
    if (!isConnected()) return;

    StaticJsonDocument<1536> doc;
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
    doc["target_id"]       = DiagnosticsManager::targetId();
    doc["boot_id"]         = DiagnosticsManager::bootId();
    doc["boot_count"]      = DiagnosticsManager::bootCount();
    doc["reset_reason"]    = DiagnosticsManager::resetReason();
    doc["relay_commanded_on"] = relayCommandedOn;
    doc["relay_pin_level"] = relayPinLevel;
    doc["min_free_heap"]   = ESP.getMinFreeHeap();
    doc["largest_free_block"] = ESP.getMaxAllocHeap();
    doc["loop_stack_hwm"]  = uxTaskGetStackHighWaterMark(nullptr);
    doc["wifi_bssid"]      = WiFi.BSSIDstr();
    doc["wifi_channel"]    = WiFi.channel();
    doc["mqtt_connect_count"] =
        DiagnosticsManager::mqttConnectCount();
    doc["mqtt_connect_attempts"] = mqttConnectAttempts;
    doc["mqtt_connect_failures"] = mqttConnectFailures;

    char buf[1536];
    serializeJson(doc, buf, sizeof(buf));

    if (isConnected()) {
        client.publish(statusTopic.c_str(), buf, false);
    }
}

void MqttManager::publishEvent(const char* eventType, const char* detail) {
    if (!eventType) return;

    if (!isConnected()) {
        extern sgk::OfflineEventQueue g_offline_queue;
        g_offline_queue.pushEvent(eventType, detail, millis(), 0,
                                  DiagnosticsManager::targetId(),
                                  DiagnosticsManager::bootId(),
                                  DiagnosticsManager::bootCount());
        return;
    }

    StaticJsonDocument<384> doc;
    doc["event"]  = eventType;
    doc["detail"] = detail ? detail : "";
    doc["time"]   = millis();
    doc["target_id"] = DiagnosticsManager::targetId();
    doc["boot_id"] = DiagnosticsManager::bootId();
    doc["boot_count"] = DiagnosticsManager::bootCount();

    char buf[384] = {};
    const size_t bytes_needed = measureJson(doc);
    if (bytes_needed == 0 || bytes_needed >= sizeof(buf) ||
        serializeJson(doc, buf, sizeof(buf)) == 0) {
        return;
    }

    if (!client.publish(eventTopic.c_str(), buf, false)) {
        extern sgk::OfflineEventQueue g_offline_queue;
        g_offline_queue.pushEvent(eventType, detail, millis(), 0,
                                  DiagnosticsManager::targetId(),
                                  DiagnosticsManager::bootId(),
                                  DiagnosticsManager::bootCount());
    }
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
