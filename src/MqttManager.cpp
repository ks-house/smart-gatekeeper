// src/MqttManager.cpp
// =============================================================
// smart-gatekeeper verified MQTTS manager
// Verified per-Target MQTTS and signed command dispatch.
// =============================================================
#include "MqttManager.h"
#include "config.h"
#include "ConfigManager.h"
#include "DiagnosticsManager.h"
#include "GattServer.h"
#include "WifiManager.h"
#include "OtaManager.h"
#include "TargetAclManager.h"
#include "OfflineEventQueue.h"
#include "TargetCommandSecurity.h"
#include "FlatJsonObjectPolicy.h"
#include "DurablePreferences.h"
#include "RestartEvidenceRetention.h"

#include <cstring>
#include <ctime>
#include <sys/time.h>
#include <algorithm>
#include <array>
#include <new>

#include <Preferences.h>
#include <mbedtls/ecdsa.h>
#include <mbedtls/ecp.h>

#include <esp_arduino_version.h>
#include <esp_attr.h>
#include <esp_err.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <lwip/dns.h>
#include <lwip/tcpip.h>

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
uint32_t mqttReconnectDelayMs = MQTT_RECONNECT_INITIAL_MS;
uint32_t mqttNextConnectAttemptMs = 0;
uint32_t mqttLastConnectDurationMs = 0;
uint32_t mqttMaxConnectDurationMs = 0;
uint32_t mqttConnectWorkerWatchdogFailures = 0;
bool mqttSecurityReady = false;
bool wifiAvailableLastUpdate = false;
bool wifiLinkGenerationInitialized = false;
uint32_t wifiLinkGenerationLastUpdate = 0;
bool accessActionStartedDuringLoop = false;
bool signedRestartPending = false;
bool bootDiagnosticsPending = true;
bool configStatePending = true;
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

enum class MqttDnsState : uint8_t {
    kIdle,
    kPending,
    kReady,
    kFailed,
};

enum class MqttDnsPollResult : uint8_t {
    kPending,
    kReady,
    kFailed,
};

portMUX_TYPE mqttDnsMux = portMUX_INITIALIZER_UNLOCKED;
MqttDnsState mqttDnsState = MqttDnsState::kIdle;
ip_addr_t mqttDnsAddress{};
uint32_t mqttDnsGeneration = 0;
uint32_t mqttDnsStartedMs = 0;

enum class MqttConnectOutcome : uint8_t {
    kSuccess,
    kTlsFailed,
    kMqttFailed,
    kSubscribeFailed,
    kAvailabilityFailed,
    kStale,
};

struct MqttConnectRequest {
    IPAddress broker_address;
    uint32_t request_id = 0;
    uint32_t wifi_link_generation = 0;
    char client_id[96] = {};
    char will_payload[192] = {};
};

struct MqttConnectResult {
    MqttConnectOutcome outcome = MqttConnectOutcome::kTlsFailed;
    uint32_t request_id = 0;
    uint32_t wifi_link_generation = 0;
    uint32_t duration_ms = 0;
    int mqtt_error = MQTT_CONNECT_FAILED;
    esp_err_t watchdog_error = ESP_OK;
};

portMUX_TYPE mqttConnectWorkerMux = portMUX_INITIALIZER_UNLOCKED;
bool mqttConnectWorkerRunning = false;
bool mqttConnectWorkerResultReady = false;
bool mqttConnectWorkerCancelRequested = false;
uint32_t mqttConnectWorkerRequestId = 0;
MqttConnectResult mqttConnectWorkerResult{};

struct PendingSignedAccessCommand {
    bool ready = false;
    sgk::SignedCommandEnvelope envelope{};
};

PendingSignedAccessCommand pendingSignedAccessCommand{};

bool connectWorkerIsRunning() {
    portENTER_CRITICAL(&mqttConnectWorkerMux);
    const bool running = mqttConnectWorkerRunning;
    portEXIT_CRITICAL(&mqttConnectWorkerMux);
    return running;
}

uint32_t connectWorkerWatchdogFailuresSnapshot() {
    portENTER_CRITICAL(&mqttConnectWorkerMux);
    const uint32_t failures = mqttConnectWorkerWatchdogFailures;
    portEXIT_CRITICAL(&mqttConnectWorkerMux);
    return failures;
}

void requestConnectWorkerCancellation() {
    portENTER_CRITICAL(&mqttConnectWorkerMux);
    if (mqttConnectWorkerRunning) mqttConnectWorkerCancelRequested = true;
    portEXIT_CRITICAL(&mqttConnectWorkerMux);
}

bool connectWorkerAttemptIsStale(uint32_t requestId,
                                 uint32_t wifiLinkGeneration) {
    portENTER_CRITICAL(&mqttConnectWorkerMux);
    const bool cancelled = mqttConnectWorkerCancelRequested ||
        !mqttConnectWorkerRunning ||
        mqttConnectWorkerRequestId != requestId;
    portEXIT_CRITICAL(&mqttConnectWorkerMux);
    return cancelled ||
           WifiManager::linkGeneration() != wifiLinkGeneration;
}

void completeConnectWorker(const MqttConnectResult& result) {
    portENTER_CRITICAL(&mqttConnectWorkerMux);
    if (mqttConnectWorkerRunning &&
        mqttConnectWorkerRequestId == result.request_id) {
        mqttConnectWorkerResult = result;
        mqttConnectWorkerResultReady = true;
        mqttConnectWorkerRunning = false;
        mqttConnectWorkerCancelRequested = false;
    }
    portEXIT_CRITICAL(&mqttConnectWorkerMux);
}

bool takeConnectWorkerResult(MqttConnectResult* result) {
    if (result == nullptr) return false;
    portENTER_CRITICAL(&mqttConnectWorkerMux);
    const bool ready = mqttConnectWorkerResultReady;
    if (ready) {
        *result = mqttConnectWorkerResult;
        mqttConnectWorkerResult = MqttConnectResult{};
        mqttConnectWorkerResultReady = false;
    }
    portEXIT_CRITICAL(&mqttConnectWorkerMux);
    return ready;
}

const char* connectOutcomeName(MqttConnectOutcome outcome) {
    switch (outcome) {
      case MqttConnectOutcome::kSuccess: return "success";
      case MqttConnectOutcome::kTlsFailed: return "tls_failed";
      case MqttConnectOutcome::kMqttFailed: return "mqtt_failed";
      case MqttConnectOutcome::kSubscribeFailed: return "subscribe_failed";
      case MqttConnectOutcome::kAvailabilityFailed:
        return "availability_failed";
      case MqttConnectOutcome::kStale: return "stale";
    }
    return "unknown";
}

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

// A controlled software restart normally spills the volatile FIFO to NVS.
// If that write path is unavailable, retain the exact remaining records in LP
// SRAM across the restart. Keep this carrier trivially initialized: placing a
// CanonicalEvent/std::array object directly in RTC_NOINIT could run a C++
// constructor at boot and erase the evidence before validation.
constexpr uint32_t kRtcEventFallbackMagic = 0x53475245;  // "SGRE"
constexpr uint16_t kRtcEventFallbackVersion = 1;
using RtcEventRetention = sgk::RestartEvidenceRetention<
    sgk::CanonicalEvent, kEventOutboxCapacity,
    kRtcEventFallbackMagic, kRtcEventFallbackVersion>;
using RtcEventFallbackJournal = RtcEventRetention::Journal;
static_assert(sizeof(RtcEventFallbackJournal) <= 12288,
              "MQTT restart evidence journal exceeds RTC SRAM budget");
RTC_NOINIT_ATTR RtcEventFallbackJournal rtcEventFallback;
RtcEventRetention rtcEventRetention;
uint32_t rtcEventFallbackRestoredCount = 0;
bool rtcEventFallbackInvalid = false;

char pendingTelemetry[4096] = {};
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

void resetMqttDnsResolution() {
    portENTER_CRITICAL(&mqttDnsMux);
    ++mqttDnsGeneration;
    if (mqttDnsGeneration == 0) ++mqttDnsGeneration;
    mqttDnsState = MqttDnsState::kIdle;
    mqttDnsStartedMs = 0;
    ip_addr_set_zero(&mqttDnsAddress);
    portEXIT_CRITICAL(&mqttDnsMux);
}

void completeMqttDnsResolution(uint32_t generation,
                               const ip_addr_t* address) {
    portENTER_CRITICAL(&mqttDnsMux);
    if (mqttDnsState == MqttDnsState::kPending &&
        mqttDnsGeneration == generation) {
        if (address == nullptr || ip_addr_isany(address)) {
            mqttDnsState = MqttDnsState::kFailed;
        } else {
            ip_addr_copy(mqttDnsAddress, *address);
            mqttDnsState = MqttDnsState::kReady;
        }
    }
    portEXIT_CRITICAL(&mqttDnsMux);
}

void mqttDnsFound(const char*, const ip_addr_t* address, void* callbackArg) {
    const uint32_t generation = static_cast<uint32_t>(
        reinterpret_cast<uintptr_t>(callbackArg));
    completeMqttDnsResolution(generation, address);
}

MqttDnsPollResult pollMqttDns(IPAddress* resolvedAddress) {
    if (resolvedAddress == nullptr) return MqttDnsPollResult::kFailed;

    IPAddress literal;
    if (literal.fromString(MQTT_HOST)) {
        *resolvedAddress = literal;
        return MqttDnsPollResult::kReady;
    }

    const uint32_t now = millis();
    MqttDnsState state;
    uint32_t generation;
    uint32_t startedMs;
    ip_addr_t address{};
    portENTER_CRITICAL(&mqttDnsMux);
    state = mqttDnsState;
    generation = mqttDnsGeneration;
    startedMs = mqttDnsStartedMs;
    if (state == MqttDnsState::kReady) {
        ip_addr_copy(address, mqttDnsAddress);
    }
    portEXIT_CRITICAL(&mqttDnsMux);

    if (state == MqttDnsState::kReady) {
        *resolvedAddress = IPAddress(&address);
        return MqttDnsPollResult::kReady;
    }
    if (state == MqttDnsState::kFailed) {
        resetMqttDnsResolution();
        return MqttDnsPollResult::kFailed;
    }
    if (state == MqttDnsState::kPending) {
        if (now - startedMs < MQTT_DNS_RESOLVE_TIMEOUT_MS) {
            return MqttDnsPollResult::kPending;
        }
        resetMqttDnsResolution();
        DiagnosticsManager::noteAction("mqtt_dns_timeout");
        return MqttDnsPollResult::kFailed;
    }

    portENTER_CRITICAL(&mqttDnsMux);
    ++mqttDnsGeneration;
    if (mqttDnsGeneration == 0) ++mqttDnsGeneration;
    generation = mqttDnsGeneration;
    mqttDnsStartedMs = now;
    mqttDnsState = MqttDnsState::kPending;
    portEXIT_CRITICAL(&mqttDnsMux);

    ip_addr_t immediate{};
    LOCK_TCPIP_CORE();
    const err_t result = dns_gethostbyname_addrtype(
        MQTT_HOST, &immediate, mqttDnsFound,
        reinterpret_cast<void*>(static_cast<uintptr_t>(generation)),
        LWIP_DNS_ADDRTYPE_DEFAULT);
    UNLOCK_TCPIP_CORE();
    if (result == ERR_OK) {
        completeMqttDnsResolution(generation, &immediate);
        *resolvedAddress = IPAddress(&immediate);
        return MqttDnsPollResult::kReady;
    }
    if (result == ERR_INPROGRESS) {
        DiagnosticsManager::noteAction("mqtt_dns_started");
        return MqttDnsPollResult::kPending;
    }
    completeMqttDnsResolution(generation, nullptr);
    return MqttDnsPollResult::kFailed;
}

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

bool enqueueEventWithDurableSpill(const sgk::CanonicalEvent& event);
bool enqueueEventOutbox(const sgk::CanonicalEvent& event,
                        bool useTerminalReserve = false);
bool checkpointTerminalEvent(const sgk::CanonicalEvent& event);

bool isSignedCommandTerminalCode(const char* code) {
    return code != nullptr &&
           (std::strcmp(code, "ACCESS_SIGNED_ARM_COMPLETED") == 0 ||
            std::strcmp(code, "ACCESS_SIGNED_ARM_TERMINATED") == 0 ||
            std::strcmp(code, "ACCESS_SIGNED_MANUAL_COMPLETED") == 0 ||
            std::strcmp(code, "ACCESS_SIGNED_MANUAL_TERMINATED") == 0);
}

bool isAccessTerminalCheckpointCode(const char* code) {
    return isSignedCommandTerminalCode(code) ||
           (code != nullptr &&
            (std::strcmp(code, "ACCESS_SESSION_COMPLETED") == 0 ||
             std::strcmp(code, "ACCESS_SESSION_TERMINATED") == 0));
}

void uuidText(const std::array<uint8_t, 16>& value, char output[37]) {
    std::snprintf(
        output, 37,
        "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-"
        "%02x%02x%02x%02x%02x%02x",
        value[0], value[1], value[2], value[3], value[4], value[5],
        value[6], value[7], value[8], value[9], value[10], value[11],
        value[12], value[13], value[14], value[15]);
}

bool enqueueSignedCommandTerminalEvent(
    const sgk::SignedCommandAccessTracker::Terminal& terminal,
    uint64_t sequence, const char* reasonCode) {
    if (!accessEvidenceReady || accessEvidenceBootCount > UINT32_MAX ||
        sequence == 0 || reasonCode == nullptr ||
        reasonCode[0] == '\0' ||
        terminal.mode == sgk::SignedCommandAccessTracker::Mode::kNone) {
        return false;
    }
    sgk::CanonicalEvent event{};
    const size_t targetIdLength = std::strlen(accessEvidenceTargetId);
    if (targetIdLength == 0 ||
        targetIdLength >= sizeof(event.target_ref)) {
        return false;
    }
    std::array<uint8_t, 16> sessionId{};
    if (!parseLowerUuid4(terminal.session_id, &sessionId)) return false;

    std::array<uint8_t, 16> eventId{};
    bool eventIdReady = false;
    for (size_t attempt = 0; attempt < 4; ++attempt) {
        esp_fill_random(eventId.data(), eventId.size());
        uint8_t aggregate = 0;
        for (uint8_t value : eventId) aggregate |= value;
        eventId[6] = static_cast<uint8_t>((eventId[6] & 0x0f) | 0x40);
        eventId[8] = static_cast<uint8_t>((eventId[8] & 0x3f) | 0x80);
        if (aggregate != 0) {
            eventIdReady = true;
            break;
        }
    }
    if (!eventIdReady) return false;

    const bool manual =
        terminal.mode == sgk::SignedCommandAccessTracker::Mode::kManualRemote;
    const char* eventCode = terminal.completed
        ? (manual ? "ACCESS_SIGNED_MANUAL_COMPLETED"
                  : "ACCESS_SIGNED_ARM_COMPLETED")
        : (manual ? "ACCESS_SIGNED_MANUAL_TERMINATED"
                  : "ACCESS_SIGNED_ARM_TERMINATED");
    const char* outcome = terminal.completed
        ? "SUCCEEDED"
        : (std::strcmp(reasonCode, "ARM_TIMEOUT") == 0 ? "TIMED_OUT"
                                                        : "FAILED");

    event.is_canonical = 1;
    event.code = manual ? 0x7f02 : 0x7f01;
    event.monotonic_ms = millis();
    event.sequence = sequence;
    event.boot_count = static_cast<uint32_t>(accessEvidenceBootCount);
    event.attempt = 1;
    uuidText(eventId, event.event_id);
    std::snprintf(event.session_id, sizeof(event.session_id), "%s",
                  terminal.session_id);
    std::snprintf(event.source_boot_id, sizeof(event.source_boot_id), "%s",
                  accessEvidenceBootIdText);
    std::memcpy(event.target_ref, accessEvidenceTargetId,
                targetIdLength + 1);
    std::snprintf(event.event_type, sizeof(event.event_type), "%s", eventCode);
    std::snprintf(event.stage_text, sizeof(event.stage_text), "COMPLETE");
    std::snprintf(event.outcome_text, sizeof(event.outcome_text), "%s",
                  outcome);

    sgk::AccessEventMacInput macInput{};
    macInput.key_id = accessEvidenceKeyId;
    macInput.topic_target_id = accessEvidenceTargetId;
    macInput.door_id = accessEvidenceDoorId;
    macInput.source_instance_id = accessEvidenceTargetId;
    macInput.source_boot_id = accessEvidenceBootId;
    macInput.source_boot_count = accessEvidenceBootCount;
    macInput.event_id = eventId;
    macInput.session_id = sessionId;
    macInput.sequence = sequence;
    macInput.attempt = 1;
    macInput.event_code = eventCode;
    macInput.stage = "COMPLETE";
    macInput.outcome = outcome;
    macInput.reason_code = reasonCode;
    macInput.has_causation = false;
    macInput.monotonic_ms = event.monotonic_ms;
    macInput.credential_ref = "";
    uint8_t eventTag[sgk::kAccessEvidenceTagSize] = {};
    if (!sgk::deriveAccessEventMac(accessEvidenceKey, macInput, eventTag) ||
        !sgk::setCanonicalV2Detail(&event, reasonCode, accessEvidenceKeyId,
                                   nullptr, eventTag)) {
        std::memset(eventTag, 0, sizeof(eventTag));
        return false;
    }
    std::memset(eventTag, 0, sizeof(eventTag));
    // A signed terminal is the one record the operator must not lose on a
    // reset between relay completion and the next MQTT update. The shared
    // checkpoint preserves older FIFO records first, then this exact terminal.
    return checkpointTerminalEvent(event);
}

bool enqueueEventOutbox(const sgk::CanonicalEvent& event,
                        bool useTerminalReserve) {
    const size_t limit = eventOutbox.size() - (useTerminalReserve ? 0 : 1);
    if (eventOutboxCount >= limit) {
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
    if (rtcEventRetention.frontRemoved()) {
        // The last record represented by the RTC image has now either been
        // published or durably migrated to NVS. Only this acknowledgement may
        // clear the cross-reset copy.
        RtcEventRetention::clearJournal(&rtcEventFallback);
    }
}

void clearRtcEventFallback() {
    RtcEventRetention::clearJournal(&rtcEventFallback);
    rtcEventRetention.reset();
}

bool rtcEventFallbackIsValid() {
    size_t newest = 0;
    return RtcEventRetention::newestValidIndex(
        rtcEventFallback, sgk::isValidCanonicalEventRecord, &newest);
}

bool saveEventOutboxToRtcFallback() {
    if (eventOutboxCount == 0) {
        clearRtcEventFallback();
        return true;
    }

    rtcEventRetention.reset();
    const bool saved = RtcEventRetention::saveJournal(
        eventOutbox, eventOutboxHead, eventOutboxCount,
        &rtcEventFallback, sgk::isValidCanonicalEventRecord);
    if (saved) rtcEventRetention.retain(eventOutboxCount);
    return saved;
}

void restoreEventOutboxFromRtcFallback() {
    rtcEventFallbackRestoredCount = 0;
    rtcEventFallbackInvalid = false;
    if (!RtcEventRetention::hasRecognizedMagic(rtcEventFallback)) {
        // RTC_NOINIT contents are unspecified after a cold power-on. Treat an
        // unrelated signature as absence, not corrupted SGK evidence.
        clearRtcEventFallback();
        return;
    }
    if (!rtcEventFallbackIsValid()) {
        rtcEventFallbackInvalid = true;
        LOGF("[MQTT-ERROR] rejected invalid RTC restart evidence fallback");
        clearRtcEventFallback();
        return;
    }

    // MqttManager::init() precedes OfflineEventQueue::begin(). Restore to the
    // empty volatile FIFO now; the existing update order drains the older NVS
    // FIFO first, then these exact remaining records, preserving global order.
    if (!RtcEventRetention::restoreNewest(
            rtcEventFallback, &eventOutbox, &eventOutboxHead,
            &eventOutboxCount, sgk::isValidCanonicalEventRecord)) {
        rtcEventFallbackInvalid = true;
        LOGF("[MQTT-ERROR] RTC restart evidence restore failed");
        clearRtcEventFallback();
        return;
    }
    rtcEventRetention.retain(eventOutboxCount);
    rtcEventFallbackRestoredCount =
        static_cast<uint32_t>(eventOutboxCount);
    LOGF("[MQTT-WARN] restored %lu restart evidence record(s) from RTC SRAM; "
         "retaining checkpoint until acknowledged",
         static_cast<unsigned long>(rtcEventFallbackRestoredCount));
}

void removeEventOutboxTail() {
    if (eventOutboxCount == 0) return;
    const size_t tail =
        (eventOutboxHead + eventOutboxCount - 1) % eventOutbox.size();
    eventOutbox[tail] = sgk::CanonicalEvent{};
    --eventOutboxCount;
}

bool checkpointTerminalEvent(const sgk::CanonicalEvent& event) {
    // Establish a durable FIFO prefix before accepting a terminal. This keeps
    // every older volatile record ahead of the terminal across a restart.
    while (eventOutboxCount != 0) {
        sgk::CanonicalEvent oldest{};
        if (!peekEventOutbox(&oldest) || !g_offline_queue.push(oldest)) break;
        popEventOutbox();
    }
    if (eventOutboxCount == 0 && g_offline_queue.push(event)) return true;

    // NVS is full/unavailable. The ordinary producer path reserves one slot
    // specifically for this terminal. Accept it only after checkpointing the
    // complete remaining FIFO (including the terminal) to RTC SRAM.
    DiagnosticsManager::markEvidencePersistenceFailure();
    if (!enqueueEventOutbox(event, true)) return false;
    if (saveEventOutboxToRtcFallback()) {
        LOGF("[MQTT-WARN] terminal evidence accepted through RTC fallback; "
             "NVS checkpoint unavailable records=%lu",
             static_cast<unsigned long>(eventOutboxCount));
        return true;
    }

    // Do not acknowledge a terminal whose restart checkpoint failed. Restore
    // the previous FIFO-only checkpoint when possible so the upstream GATT
    // deferred sink can retain and retry this terminal without duplicating it.
    removeEventOutboxTail();
    if (eventOutboxCount != 0 && !saveEventOutboxToRtcFallback()) {
        LOGF("[MQTT-ERROR] failed to restore RTC checkpoint after terminal "
             "acceptance rollback");
    }
    return false;
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
bool MqttManager::connected = false;

bool MqttManager::isConnected() { return connected; }

void MqttManager::deferForAccessCritical() {
    requestConnectWorkerCancellation();
}

bool MqttManager::connectionAttemptInProgress() {
    return connectWorkerIsRunning();
}

bool MqttManager::hasPendingRestartRequest() {
    return signedRestartPending;
}

void MqttManager::performPendingRestart() {
    if (!signedRestartPending) return;

    // main invokes this only after it has blocked new GATT authentication,
    // drained callback work, and re-proved an idle physical access path.
    const bool evidenceDurable =
        GattServer::persistPendingEventsForRestart();
    if (!evidenceDurable) {
        DiagnosticsManager::markEvidencePersistenceFailure();
    }
    signedRestartPending = false;
    DiagnosticsManager::markPlannedRestart("signed_mqtt_reboot");
    LOGF("[SYSTEM-WARN] signed MQTT reboot; evidence durable=%s",
         evidenceDurable ? "yes" : "no");
    delay(100);
    ESP.restart();
}

bool MqttManager::publishCommandAck(
    const sgk::SignedCommandEnvelope& envelope, sgk::CommandResult result) {
    if (!isConnected() || commandAckTopic.isEmpty()) return false;
    StaticJsonDocument<384> document;
    document["schema_version"] = 1;
    document["target_id"] = DiagnosticsManager::targetId();
    document["session_id"] = envelope.session_id;
    document["nonce"] = envelope.nonce;
    document["result"] = static_cast<uint8_t>(result);
    char buffer[384]{};
    const size_t length = serializeJson(document, buffer, sizeof(buffer));
    return !document.overflowed() && length > 0 && length < sizeof(buffer) &&
           client.publish(commandAckTopic.c_str(), buffer, false);
}

bool MqttManager::startConnectWorker(const IPAddress& brokerAddress,
                                     uint32_t wifiLinkGeneration) {
    auto* request = new (std::nothrow) MqttConnectRequest{};
    if (request == nullptr) return false;

    request->broker_address = brokerAddress;
    request->wifi_link_generation = wifiLinkGeneration;
    std::snprintf(request->client_id, sizeof(request->client_id),
                  "smart-gatekeeper-%s", DiagnosticsManager::targetId());
    std::snprintf(
        request->will_payload, sizeof(request->will_payload),
        "{\"status\":\"offline\",\"scope\":\"mqtt_transport\","
        "\"target_id\":\"%s\",\"boot_id\":\"%s\",\"boot_count\":%lu}",
        DiagnosticsManager::targetId(), DiagnosticsManager::bootId(),
        static_cast<unsigned long>(DiagnosticsManager::bootCount()));

    portENTER_CRITICAL(&mqttConnectWorkerMux);
    if (mqttConnectWorkerRunning || mqttConnectWorkerResultReady) {
        portEXIT_CRITICAL(&mqttConnectWorkerMux);
        delete request;
        return false;
    }
    ++mqttConnectWorkerRequestId;
    if (mqttConnectWorkerRequestId == 0) ++mqttConnectWorkerRequestId;
    request->request_id = mqttConnectWorkerRequestId;
    mqttConnectWorkerCancelRequested = false;
    mqttConnectWorkerRunning = true;
    portEXIT_CRITICAL(&mqttConnectWorkerMux);

    const BaseType_t created = xTaskCreate(
        connectWorkerEntry, "mqtt-connect", 12288, request,
        tskIDLE_PRIORITY + 1, nullptr);
    if (created == pdPASS) return true;

    portENTER_CRITICAL(&mqttConnectWorkerMux);
    if (mqttConnectWorkerRunning &&
        mqttConnectWorkerRequestId == request->request_id) {
        mqttConnectWorkerRunning = false;
        mqttConnectWorkerCancelRequested = false;
    }
    portEXIT_CRITICAL(&mqttConnectWorkerMux);
    delete request;
    return false;
}

void MqttManager::connectWorkerEntry(void* argument) {
    auto* allocated = static_cast<MqttConnectRequest*>(argument);
    if (allocated == nullptr) {
        vTaskDelete(nullptr);
        return;
    }
    const MqttConnectRequest request = *allocated;
    delete allocated;

    const uint32_t startedMs = millis();
    MqttConnectResult result{};
    result.request_id = request.request_id;
    result.wifi_link_generation = request.wifi_link_generation;

    bool watchdogFailureCounted = false;
    auto noteWatchdogFailure = [&](esp_err_t error, const char* phase) {
        if (error == ESP_OK) return;
        if (result.watchdog_error == ESP_OK) result.watchdog_error = error;
        if (!watchdogFailureCounted) {
            portENTER_CRITICAL(&mqttConnectWorkerMux);
            ++mqttConnectWorkerWatchdogFailures;
            portEXIT_CRITICAL(&mqttConnectWorkerMux);
            watchdogFailureCounted = true;
        }
        LOGF("[MQTT-ERROR] connect worker watchdog %s failed: %s",
             phase, esp_err_to_name(error));
    };
    const esp_err_t watchdogAddResult = esp_task_wdt_add(nullptr);
    const bool watchdogEnrolled = watchdogAddResult == ESP_OK;
    noteWatchdogFailure(watchdogAddResult, "add");
    auto feedWatchdog = [&]() {
        if (watchdogEnrolled) {
            noteWatchdogFailure(esp_task_wdt_reset(), "reset");
        }
    };

    auto finish = [&](MqttConnectOutcome outcome, int mqttError) {
        result.outcome = outcome;
        result.mqtt_error = mqttError;
        result.duration_ms = millis() - startedMs;
        if (outcome != MqttConnectOutcome::kSuccess) wifiClient.stop();
        if (watchdogEnrolled) {
            feedWatchdog();
            // Relinquish the task watchdog before handing ownership of the
            // transport/result back to loopTask. Every terminal path reaches
            // this lambda, including stale and transport failures.
            noteWatchdogFailure(esp_task_wdt_delete(nullptr), "delete");
        }
        completeConnectWorker(result);
    };
    auto stale = [&]() {
        return connectWorkerAttemptIsStale(
            request.request_id, request.wifi_link_generation);
    };

    if (stale()) {
        finish(MqttConnectOutcome::kStale, MQTT_CONNECT_FAILED);
        vTaskDelete(nullptr);
        return;
    }

    // DNS already completed on loopTask. This worker exclusively owns both
    // transport objects until it publishes a terminal result, so loopTask and
    // PubSubClient can never race the synchronous TCP/TLS/MQTT handshake.
    const bool tlsConnected = wifiClient.connect(
        request.broker_address, MQTT_PORT, MQTT_HOST, SECRET_ROOT_CA_CERT,
        nullptr, nullptr) == 1;
    if (!tlsConnected) {
        finish(stale() ? MqttConnectOutcome::kStale
                       : MqttConnectOutcome::kTlsFailed,
               MQTT_CONNECT_FAILED);
        vTaskDelete(nullptr);
        return;
    }
    feedWatchdog();
    if (stale()) {
        finish(MqttConnectOutcome::kStale, MQTT_CONNECT_FAILED);
        vTaskDelete(nullptr);
        return;
    }

    const bool sessionConnected = client.connect(
        request.client_id, MQTT_USER, MQTT_PASSWORD,
        availabilityTopic.c_str(), 1, true, request.will_payload);
    if (!sessionConnected) {
        const int state = client.state();
        finish(stale() ? MqttConnectOutcome::kStale
                       : MqttConnectOutcome::kMqttFailed,
               state);
        vTaskDelete(nullptr);
        return;
    }
    feedWatchdog();
    if (stale()) {
        finish(MqttConnectOutcome::kStale, MQTT_CONNECT_FAILED);
        vTaskDelete(nullptr);
        return;
    }

    const bool commandSubscribed = client.subscribe(commandTopic.c_str(), 1);
    feedWatchdog();
    const bool aclSubscribed = client.subscribe(aclTopic.c_str(), 1);
    feedWatchdog();
    if (!commandSubscribed || !aclSubscribed) {
        finish(stale() ? MqttConnectOutcome::kStale
                       : MqttConnectOutcome::kSubscribeFailed,
               MQTT_CONNECT_FAILED);
        vTaskDelete(nullptr);
        return;
    }
    // PubSubClient 2.8 confirms only that each SUBSCRIBE packet was written;
    // broker SUBACK is not observable. Retained availability therefore remains
    // a transport signal, while signed status freshness proves readiness.
    if (stale()) {
        finish(MqttConnectOutcome::kStale, MQTT_CONNECT_FAILED);
        vTaskDelete(nullptr);
        return;
    }

    char onlinePayload[192]{};
    std::snprintf(
        onlinePayload, sizeof(onlinePayload),
        "{\"status\":\"online\",\"scope\":\"mqtt_transport\","
        "\"target_id\":\"%s\",\"boot_id\":\"%s\",\"boot_count\":%lu}",
        DiagnosticsManager::targetId(), DiagnosticsManager::bootId(),
        static_cast<unsigned long>(DiagnosticsManager::bootCount()));
    if (!client.publish(availabilityTopic.c_str(), onlinePayload, true)) {
        finish(stale() ? MqttConnectOutcome::kStale
                       : MqttConnectOutcome::kAvailabilityFailed,
               MQTT_CONNECT_FAILED);
        vTaskDelete(nullptr);
        return;
    }
    feedWatchdog();
    if (stale()) {
        finish(MqttConnectOutcome::kStale, MQTT_CONNECT_FAILED);
        vTaskDelete(nullptr);
        return;
    }

    finish(MqttConnectOutcome::kSuccess, 0);
    vTaskDelete(nullptr);
}

void MqttManager::dispatchPendingAccessCommand() {
    if (!pendingSignedAccessCommand.ready) return;
    const PendingSignedAccessCommand pending = pendingSignedAccessCommand;
    pendingSignedAccessCommand = PendingSignedAccessCommand{};

    // client.loop() has returned, so PubSubClient has already emitted the
    // inbound QoS1 PUBACK. Complete the application ACK write before entering
    // ARMED/RELAY_HOLD; no TLS write is allowed after the physical transition.
    if (!publishCommandAck(pending.envelope,
                           sgk::CommandResult::kAccepted)) {
        // The signed command remains authorized. Preserve the prior at-most-
        // once physical behavior and leave queued audit evidence; exact-session
        // status/event evidence resolves the transport uncertainty.
        publishEvent(
            "signed_command_ack_write_failed",
            sgk::TargetCommandSecurity::actionName(pending.envelope.action));
    }

    bool effectCompleted = false;
    if (pending.envelope.action == sgk::CommandAction::kArm) {
        effectCompleted = triggerArm();
    } else if (pending.envelope.action ==
               sgk::CommandAction::kManualRemote) {
        effectCompleted = triggerManualDoorOpen();
    }

    if (effectCompleted) {
        accessActionStartedDuringLoop = true;
        pendingTelemetryValid = false;
    } else {
        signedCommandAccessTracker.cancel();
        publishEvent(
            "signed_command_effect_rejected",
            sgk::TargetCommandSecurity::actionName(pending.envelope.action));
    }

    // Authorization already committed replay state=1 before the application
    // ACK. Move it to completed only after the physical effect attempt. A
    // storage failure intentionally leaves DuplicateUncertain, preventing an
    // unsafe replay; reporting is queued and performs no socket I/O here.
    if (!commandSecurity.markCompleted(pending.envelope)) {
        publishEvent(
            "signed_command_completion_persist_failed",
            sgk::TargetCommandSecurity::actionName(pending.envelope.action));
    }
}

void MqttManager::init() {
    mqttSecurityReady = false;
    connected = false;
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
    pendingSignedAccessCommand = PendingSignedAccessCommand{};
    wifiAvailableLastUpdate = false;
    wifiLinkGenerationInitialized = false;
    wifiLinkGenerationLastUpdate = 0;
    accessActionStartedDuringLoop = false;
    signedRestartPending = false;
    portENTER_CRITICAL(&mqttConnectWorkerMux);
    mqttConnectWorkerRunning = false;
    mqttConnectWorkerResultReady = false;
    mqttConnectWorkerCancelRequested = false;
    mqttConnectWorkerResult = MqttConnectResult{};
    portEXIT_CRITICAL(&mqttConnectWorkerMux);
    resetMqttDnsResolution();
    eventOutboxHead = 0;
    eventOutboxCount = 0;
    eventOutboxOverflowCount = 0;
    restoreEventOutboxFromRtcFallback();
    pendingTelemetryValid = false;
    mqttConnectAttempts = 0;
    mqttConnectFailures = 0;
    mqttLastError = 0;
    mqttReconnectDelayMs = MQTT_RECONNECT_INITIAL_MS;
    mqttNextConnectAttemptMs = 0;
    mqttLastConnectDurationMs = 0;
    mqttMaxConnectDurationMs = 0;
    mqttConnectWorkerWatchdogFailures = 0;
    bootDiagnosticsPending = true;
    configStatePending = true;
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
    wifiClient.setConnectionTimeout(MQTT_TCP_CONNECT_TIMEOUT_MS);
    wifiClient.setHandshakeTimeout(MQTT_TLS_HANDSHAKE_TIMEOUT_SECONDS);
    client.setServer(MQTT_HOST, MQTT_PORT);
    if (!client.setBufferSize(8192)) {
        LOGF("[MQTT-SECURITY] MQTT buffer allocation failed; transport disabled");
        return;
    }
    client.setKeepAlive(MQTT_KEEP_ALIVE_SECONDS);
    // PubSubClient's timeout covers MQTT CONNACK/read, not TCP or TLS.
    client.setSocketTimeout(MQTT_PROTOCOL_SOCKET_TIMEOUT_SECONDS);
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

    const bool accessCommand =
        envelope.action == sgk::CommandAction::kArm ||
        envelope.action == sgk::CommandAction::kManualRemote;
    if (accessCommand) {
        const sgk::SignedCommandAccessTracker::Mode mode =
            envelope.action == sgk::CommandAction::kArm
                ? sgk::SignedCommandAccessTracker::Mode::kArm
                : sgk::SignedCommandAccessTracker::Mode::kManualRemote;
        // update() is entered only after main's access-critical guard observes
        // an idle control path. The single bounded slot closes the remaining
        // local preflight: no second command or lifecycle may be outstanding.
        const bool preflightAccepted =
            !pendingSignedAccessCommand.ready &&
            !signedCommandAccessTracker.active() &&
            signedCommandAccessTracker.begin(mode, envelope.session_id);
        if (!preflightAccepted) {
            const bool completionStored = commandSecurity.markCompleted(envelope);
            publishCommandAck(
                envelope,
                completionStored ? sgk::CommandResult::kEffectRejected
                                 : sgk::CommandResult::kReplayStorageFailure);
            publishEvent(
                "signed_command_effect_rejected",
                sgk::TargetCommandSecurity::actionName(envelope.action));
            return;
        }

        pendingSignedAccessCommand.ready = true;
        pendingSignedAccessCommand.envelope = envelope;
        // Return to PubSubClient. Its inbound QoS1 PUBACK is emitted after this
        // callback returns; update() sends the application ACK and dispatches
        // the physical effect only after client.loop() itself has returned.
        return;
    }

    bool effectCompleted = true;
    switch (envelope.action) {
      case sgk::CommandAction::kArm:
      case sgk::CommandAction::kManualRemote:
        // Handled by the bounded post-PUBACK dispatch path above.
        effectCompleted = false;
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
        OtaManager::requestCheck();
        break;
      case sgk::CommandAction::kReboot:
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
    if (effectCompleted &&
        envelope.action == sgk::CommandAction::kReboot) {
        signedRestartPending = true;
        publishEvent("signed_command_reboot",
                     "Authenticated reboot staged after MQTT PUBACK");
    }
    if (!effectCompleted) {
        publishEvent("signed_command_effect_rejected",
                     sgk::TargetCommandSecurity::actionName(envelope.action));
    }
    return;

}

void MqttManager::update() {
    if (!mqttSecurityReady) return;
    const uint32_t wifiLinkGeneration = WifiManager::linkGeneration();
    bool wifiLinkChanged = false;
    if (!wifiLinkGenerationInitialized) {
        wifiLinkGenerationInitialized = true;
        wifiLinkGenerationLastUpdate = wifiLinkGeneration;
    } else if (wifiLinkGeneration != wifiLinkGenerationLastUpdate) {
        wifiLinkGenerationLastUpdate = wifiLinkGeneration;
        wifiLinkChanged = true;
        connected = false;
        wifiAvailableLastUpdate = false;
        resetMqttDnsResolution();
        mqttReconnectDelayMs = MQTT_RECONNECT_INITIAL_MS;
        mqttNextConnectAttemptMs = millis();
        DiagnosticsManager::noteAction("mqtt_wifi_generation_changed");
    }

    // While the worker owns the TLS and PubSubClient objects, loopTask must not
    // call even connected()/stop(). Cancellation is cooperative and bounded by
    // the configured TCP/TLS/MQTT phase deadlines.
    if (connectWorkerIsRunning()) {
        if (wifiLinkChanged || !WifiManager::isConnected()) {
            requestConnectWorkerCancellation();
        }
        return;
    }

    MqttConnectResult workerResult{};
    if (takeConnectWorkerResult(&workerResult)) {
        mqttLastConnectDurationMs = workerResult.duration_ms;
        if (workerResult.watchdog_error != ESP_OK) {
            DiagnosticsManager::noteAction(
                "mqtt_connect_worker_wdt_degraded");
        }
        if (mqttLastConnectDurationMs > mqttMaxConnectDurationMs) {
            mqttMaxConnectDurationMs = mqttLastConnectDurationMs;
        }
        const uint32_t currentLinkGeneration = WifiManager::linkGeneration();
        const bool resultCurrent =
            workerResult.wifi_link_generation == currentLinkGeneration &&
            workerResult.wifi_link_generation == wifiLinkGeneration &&
            WifiManager::isConnected() && client.connected() &&
            wifiClient.connected();
        if (workerResult.outcome == MqttConnectOutcome::kSuccess &&
            resultCurrent) {
            connected = true;
            wifiAvailableLastUpdate = true;
            mqttLastError = 0;
            mqttReconnectDelayMs = MQTT_RECONNECT_INITIAL_MS;
            mqttNextConnectAttemptMs = 0;
            bootDiagnosticsPending = true;
            configStatePending = true;
            DiagnosticsManager::noteMqttConnected();
            DiagnosticsManager::noteAction("mqtt_connect_worker_adopted");
            LOGF("[MQTT-SSL] worker connection adopted (%lu ms)",
                 static_cast<unsigned long>(workerResult.duration_ms));
            publishEvent(
                "connected",
                "ESP32-C6 v2.1 Online (SSL) — AJ-SR04T Ultrasonic Sensor");
            return;
        }

        // The worker has published its terminal result and relinquished object
        // ownership, so loopTask can now tear down a stale or failed socket.
        wifiClient.stop();
        connected = false;
        resetMqttDnsResolution();
        mqttLastError = workerResult.mqtt_error;
        if (workerResult.outcome == MqttConnectOutcome::kStale ||
            !resultCurrent) {
            mqttReconnectDelayMs = MQTT_RECONNECT_INITIAL_MS;
            mqttNextConnectAttemptMs = millis();
            DiagnosticsManager::noteAction("mqtt_connect_worker_stale");
        } else {
            ++mqttConnectFailures;
            mqttNextConnectAttemptMs = millis() + mqttReconnectDelayMs;
            mqttReconnectDelayMs = std::min(
                mqttReconnectDelayMs * 2, MQTT_RECONNECT_MAX_MS);
            DiagnosticsManager::noteAction("mqtt_connect_worker_failed");
        }
        LOGF("[MQTT-ERROR] worker result=%s rc=%d duration=%lu ms",
             connectOutcomeName(workerResult.outcome), workerResult.mqtt_error,
             static_cast<unsigned long>(workerResult.duration_ms));
        return;
    }

    if (wifiLinkChanged) {
        // No worker owns the objects now. Close without MQTT DISCONNECT so a
        // broker-side session from the old link cannot remain falsely online.
        wifiClient.stop();
    }

    const bool wifiAvailable = WifiManager::isConnected();
    if (!wifiAvailable) {
        if (wifiAvailableLastUpdate || connected || client.connected()) {
            // Close the transport without MQTT DISCONNECT so the broker emits
            // the retained LWT instead of preserving a stale online snapshot.
            wifiClient.stop();
            resetMqttDnsResolution();
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
        mqttReconnectDelayMs = MQTT_RECONNECT_INITIAL_MS;
        mqttNextConnectAttemptMs = millis();
        wifiAvailableLastUpdate = true;
        DiagnosticsManager::noteAction("mqtt_wifi_recovered");
    }

    if (!client.connected()) {
        connected = false;
        const uint32_t now = millis();
        if (mqttNextConnectAttemptMs == 0 ||
            static_cast<int32_t>(now - mqttNextConnectAttemptMs) >= 0) {
            IPAddress brokerAddress;
            const MqttDnsPollResult dnsResult =
                pollMqttDns(&brokerAddress);
            if (dnsResult == MqttDnsPollResult::kPending) return;
            if (dnsResult == MqttDnsPollResult::kFailed) {
                ++mqttConnectAttempts;
                ++mqttConnectFailures;
                mqttLastError = MQTT_CONNECT_FAILED;
                mqttNextConnectAttemptMs = millis() + mqttReconnectDelayMs;
                mqttReconnectDelayMs = std::min(
                    mqttReconnectDelayMs * 2, MQTT_RECONNECT_MAX_MS);
                DiagnosticsManager::noteAction("mqtt_dns_failed");
                LOGF("[MQTT-ERROR] bounded DNS resolution failed; retry in "
                     "%lu ms",
                     static_cast<unsigned long>(mqttReconnectDelayMs));
                return;
            }

            ++mqttConnectAttempts;
            DiagnosticsManager::noteAction("mqtt_connect_start");
            if (!startConnectWorker(brokerAddress, wifiLinkGeneration)) {
                ++mqttConnectFailures;
                mqttLastError = MQTT_CONNECT_FAILED;
                mqttNextConnectAttemptMs = millis() + mqttReconnectDelayMs;
                mqttReconnectDelayMs = std::min(
                    mqttReconnectDelayMs * 2, MQTT_RECONNECT_MAX_MS);
                DiagnosticsManager::noteAction(
                    "mqtt_connect_worker_start_failed");
                LOGF("[MQTT-ERROR] connect worker allocation/start failed");
                return;
            }
            LOGF("[MQTT-SSL] background connect started (%s:%d link=%lu)",
                 MQTT_HOST, MQTT_PORT,
                 static_cast<unsigned long>(wifiLinkGeneration));
            return;
        }
        return;
    }

    connected = true;
    accessActionStartedDuringLoop = false;
    client.loop();
    connected = client.connected() && wifiClient.connected();
    dispatchPendingAccessCommand();
    if (accessActionStartedDuringLoop || !connected) {
        return;
    }
    if (signedRestartPending) {
        // PubSubClient has emitted its inbound PUBACK. Main now owns the GATT
        // quiesce/re-check gate and calls performPendingRestart() only after a
        // racing verified action is either absent or terminal.
        return;
    }

        // Deliver the newest signed terminal/IDLE snapshot before draining the
        // audit backlog so the mobile exact-session poll is not delayed behind
        // every QoS0 lifecycle event. A failed status publish does not block the
        // durable event queue from making its own bounded retry.
        if (pendingTelemetryValid &&
            client.publish(statusTopic.c_str(), pendingTelemetry, false)) {
            pendingTelemetryValid = false;
            return;
        }

        if (bootDiagnosticsPending) {
            publishBootDiagnostics();
            if (!bootDiagnosticsPending) return;
        }
        if (configStatePending) {
            extern int g_tx_power_dbm;
            extern uint16_t g_distance_threshold_cm;
            extern uint32_t g_pre_arm_duration_ms;
            extern uint32_t g_relay_cooldown_ms;
            publishConfigState(g_tx_power_dbm, g_distance_threshold_cm,
                               g_pre_arm_duration_ms,
                               g_relay_cooldown_ms);
            if (!configStatePending) return;
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
                    if (isSignedCommandTerminalCode(evt.event_type)) {
                        attributes["path"] =
                            std::strstr(evt.event_type, "_MANUAL_") != nullptr
                                ? "mqtt_manual_remote"
                                : "mqtt_prearm";
                        attributes["transport"] = "signed_mqtt";
                    } else {
                        attributes["path"] = "local_gatt";
                        attributes["transport"] = "ble_gatt";
                    }
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

void MqttManager::publishBootDiagnostics() {
    bootDiagnosticsPending = true;
    if (!isConnected()) return;

    static StaticJsonDocument<2560> doc;
    doc.clear();
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
    doc["previous_access_valid"] =
        DiagnosticsManager::previousAccessBreadcrumbValid();
    doc["previous_access_uptime_ms"] =
        DiagnosticsManager::previousAccessUptimeMs();
    doc["previous_access_stage"] =
        DiagnosticsManager::previousAccessStage();
    doc["previous_access_session_id"] =
        DiagnosticsManager::previousAccessSessionId();

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
    doc["wifi_channel"] = WiFi.channel();
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["free_heap"] = ESP.getFreeHeap();
    doc["min_free_heap"] = ESP.getMinFreeHeap();
    doc["largest_free_block"] = ESP.getMaxAllocHeap();
    doc["loop_stack_hwm"] = uxTaskGetStackHighWaterMark(nullptr);
    doc["mqtt_connect_attempts"] = mqttConnectAttempts;
    doc["mqtt_connect_failures"] = mqttConnectFailures;
    doc["mqtt_last_error"] = mqttLastError;
    doc["mqtt_last_connect_ms"] = mqttLastConnectDurationMs;
    doc["mqtt_max_connect_ms"] = mqttMaxConnectDurationMs;
    doc["mqtt_connect_worker_wdt_failures"] =
        connectWorkerWatchdogFailuresSnapshot();
    doc["mqtt_event_outbox_depth"] = eventOutboxCount;
    doc["mqtt_event_outbox_overflow_count"] = eventOutboxOverflowCount;
    doc["previous_evidence_persistence_failed"] =
        DiagnosticsManager::previousEvidencePersistenceFailed();
    doc["rtc_event_fallback_restored_count"] =
        rtcEventFallbackRestoredCount;
    doc["rtc_event_fallback_pending_count"] =
        rtcEventRetention.retainedCount();
    doc["rtc_event_fallback_invalid"] = rtcEventFallbackInvalid;
    doc["loop_watchdog_enabled"] =
        DiagnosticsManager::loopWatchdogEnabled();
    doc["wifi_link_generation"] = WifiManager::linkGeneration();
    doc["wifi_outage_count"] = WifiManager::outageCount();
    doc["wifi_recovery_escalations"] =
        WifiManager::recoveryEscalationCount();
    doc["wifi_recovery_ap_failures"] =
        WifiManager::recoveryApStartFailureCount();
    doc["wifi_recovery_successes"] = WifiManager::recoverySuccessCount();
    doc["wifi_recovery_phase"] = WifiManager::recoveryPhase();
    doc["wifi_last_unplanned_disconnect_reason"] =
        WifiManager::lastUnplannedDisconnectReason();
    doc["wifi_current_outage_ms"] = WifiManager::currentOutageMs();
    doc["wifi_last_outage_ms"] = WifiManager::lastOutageMs();

    static char buffer[2560];
    size_t length = serializeJson(doc, buffer, sizeof(buffer));
    bool ok = !doc.overflowed() && length > 0 &&
              length < sizeof(buffer) &&
              client.publish(bootTopic.c_str(), buffer, true);
    if (ok) {
        DiagnosticsManager::acknowledgePreviousEvidencePersistenceFailure();
    }
    bootDiagnosticsPending = !ok;
    LOGF("[MQTT-DIAG] retained boot diagnostics publish: %s (%u bytes)",
         ok ? "OK" : "FAIL", static_cast<unsigned int>(length));
}

void MqttManager::publishConfigState(int txPower, int distanceThresholdCm, uint32_t durationMs, uint32_t relayCooldownMs) {
    configStatePending = true;
    if (!isConnected()) return;

    StaticJsonDocument<256> doc;
    doc["tx_power"] = txPower;
    doc["distance_threshold_cm"] = distanceThresholdCm;
    doc["tof_distance_cm"] = distanceThresholdCm; // 호환용 하위 별칭
    doc["duration_ms"] = durationMs;
    doc["relay_cooldown_ms"] = relayCooldownMs;
    doc["status"] = "applied_nvs";

    char buffer[256];
    const size_t length = serializeJson(doc, buffer, sizeof(buffer));
    const bool ok = !doc.overflowed() && length > 0 &&
                    length < sizeof(buffer) &&
                    client.publish(configStateTopic.c_str(), buffer, true);
    configStatePending = !ok;
    LOGF("[MQTT-CONFIG] retained config state publish: %s (%u bytes)",
         ok ? "OK" : "FAIL", static_cast<unsigned int>(length));
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

    // Main-loop-only reusable storage keeps the expanded diagnostic snapshot
    // out of the loop task stack while TLS publication is still in scope.
    static StaticJsonDocument<4096> doc;
    doc.clear();
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
    doc["mqtt_last_connect_ms"] = mqttLastConnectDurationMs;
    doc["mqtt_max_connect_ms"] = mqttMaxConnectDurationMs;
    doc["mqtt_connect_worker_wdt_failures"] =
        connectWorkerWatchdogFailuresSnapshot();
    doc["mqtt_event_outbox_depth"] = eventOutboxCount;
    doc["mqtt_event_outbox_overflow_count"] = eventOutboxOverflowCount;
    doc["previous_evidence_persistence_failed"] =
        DiagnosticsManager::previousEvidencePersistenceFailed();
    doc["rtc_event_fallback_restored_count"] =
        rtcEventFallbackRestoredCount;
    doc["rtc_event_fallback_pending_count"] =
        rtcEventRetention.retainedCount();
    doc["rtc_event_fallback_invalid"] = rtcEventFallbackInvalid;
    doc["loop_watchdog_enabled"] =
        DiagnosticsManager::loopWatchdogEnabled();
    doc["wifi_link_generation"] = WifiManager::linkGeneration();
    doc["wifi_outage_count"] = WifiManager::outageCount();
    doc["wifi_recovery_escalations"] =
        WifiManager::recoveryEscalationCount();
    doc["wifi_recovery_ap_failures"] =
        WifiManager::recoveryApStartFailureCount();
    doc["wifi_recovery_successes"] = WifiManager::recoverySuccessCount();
    doc["wifi_recovery_phase"] = WifiManager::recoveryPhase();
    doc["wifi_last_unplanned_disconnect_reason"] =
        WifiManager::lastUnplannedDisconnectReason();
    doc["wifi_current_outage_ms"] = WifiManager::currentOutageMs();
    doc["wifi_last_outage_ms"] = WifiManager::lastOutageMs();
    const GattServer::Telemetry gattTelemetry = GattServer::getTelemetry();
    doc["ble_advertising_expected"] =
        gattTelemetry.advertising_expected;
    doc["ble_advertising_active"] = gattTelemetry.advertising_active;
    doc["ble_active_connections"] = gattTelemetry.active_connections;
    doc["ble_advertising_restart_attempts"] =
        gattTelemetry.advertising_restart_attempts;
    doc["ble_advertising_restart_successes"] =
        gattTelemetry.advertising_restart_successes;
    doc["ble_advertising_restart_failures"] =
        gattTelemetry.advertising_restart_failures;
    doc["ble_advertising_watchdog_recoveries"] =
        gattTelemetry.advertising_watchdog_recoveries;
    doc["gatt_accepted_connections"] = gattTelemetry.accepted_connections;
    doc["gatt_disconnects"] = gattTelemetry.disconnects;
    doc["gatt_challenges_issued"] = gattTelemetry.challenges_issued;
    doc["gatt_proof_frames_received"] = gattTelemetry.proofs_received;
    doc["gatt_proofs_verified"] = gattTelemetry.proofs_verified;
    doc["gatt_proofs_rejected"] = gattTelemetry.proofs_rejected;
    doc["gatt_results_indicated"] = gattTelemetry.results_indicated;
    doc["gatt_armed_entries"] = gattTelemetry.armed_entries;
    doc["gatt_sensor_detections"] = gattTelemetry.sensor_detections;
    doc["gatt_relay_on_count"] = gattTelemetry.relay_on_count;
    doc["gatt_relay_off_count"] = gattTelemetry.relay_off_count;
    doc["gatt_terminal_count"] = gattTelemetry.terminal_count;
    doc["gatt_last_stage_ms"] = gattTelemetry.last_stage_ms;
    doc["gatt_last_stage"] = gattTelemetry.last_stage;
    if (gattTelemetry.last_session_id[0] != '\0') {
      doc["gatt_last_session_id"] = gattTelemetry.last_session_id;
    } else {
      doc["gatt_last_session_id"] = nullptr;
    }
    doc["previous_access_valid"] =
        DiagnosticsManager::previousAccessBreadcrumbValid();
    doc["previous_access_uptime_ms"] =
        DiagnosticsManager::previousAccessUptimeMs();
    doc["previous_access_stage"] =
        DiagnosticsManager::previousAccessStage();
    doc["previous_access_session_id"] =
        DiagnosticsManager::previousAccessSessionId();
    extern sgk::TargetAclManager g_acl_manager;
    doc["acl_active"] = g_acl_manager.hasActiveAcl();
    doc["acl_version"] = g_acl_manager.activeAclVersion();
    if (g_acl_manager.hasActiveAcl()) {
        const sgk::TargetAclHeader& aclHeader =
            g_acl_manager.activeSnapshot().header;
        doc["acl_min_protocol"] = aclHeader.min_protocol;
        doc["acl_max_protocol"] = aclHeader.max_protocol;
    } else {
        doc["acl_min_protocol"] = nullptr;
        doc["acl_max_protocol"] = nullptr;
    }

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
    if (isAccessTerminalCheckpointCode(event.event_type)) {
        return checkpointTerminalEvent(event);
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
    const char* reasonCode = terminal.completed
        ? "ACCESS_GRANTED"
        : (failureReason == nullptr ? "INTERNAL_ERROR" : failureReason);
    noteAccessTerminal(
        terminal.session_id, sequence,
        terminal.completed ? "ACCESS_SESSION_COMPLETED"
                           : "ACCESS_SESSION_TERMINATED",
        reasonCode,
        nullptr, terminal.phase_mask);
    if (!enqueueSignedCommandTerminalEvent(terminal, sequence, reasonCode)) {
        DiagnosticsManager::markEvidencePersistenceFailure();
        LOGF("[ERROR] Signed MQTT terminal canonical enqueue failed");
    }
    return sequence;
}

bool MqttManager::persistPendingEventsForRestart() {
    extern sgk::OfflineEventQueue g_offline_queue;
    while (eventOutboxCount != 0) {
        sgk::CanonicalEvent event{};
        if (!peekEventOutbox(&event) || !g_offline_queue.push(event)) {
            const bool rtcSaved = saveEventOutboxToRtcFallback();
            LOGF("[MQTT-%s] NVS restart evidence spill failed; "
                 "RTC fallback=%s records=%lu",
                 rtcSaved ? "WARN" : "ERROR",
                 rtcSaved ? "saved" : "failed",
                 static_cast<unsigned long>(eventOutboxCount));
            // RTC SRAM is a software-reset recovery aid, not durable storage.
            // Report failure even when captured so the next boot diagnostic
            // exposes the degraded evidence path instead of claiming NVS
            // durability.
            DiagnosticsManager::markEvidencePersistenceFailure();
            return false;
        }
        popEventOutbox();
    }
    clearRtcEventFallback();
    return true;
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
