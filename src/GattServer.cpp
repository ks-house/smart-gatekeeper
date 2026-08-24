#include "GattServer.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cstdio>
#include <cstring>

#include "ConfigManager.h"
#include "MqttManager.h"
#include "OfflineEventQueue.h"

extern sgk::OfflineEventQueue g_offline_queue;

#if ENABLE_HARDWARELESS_RC
#include <BLE2901.h>
#include <BLEAdvertising.h>
#include <BLECharacteristic.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEService.h>
#include <esp_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/portmacro.h>
#include <mbedtls/md.h>
#include <os/os_mbuf.h>
#endif

#define LOGF(fmt, ...)              \
  do {                              \
    printf(fmt "\n", ##__VA_ARGS__); \
    fflush(stdout);                 \
  } while (0)

namespace {

bool requested_enabled = false;
sgk::FailClosedProofVerifier fail_closed_verifier;
sgk::ProofVerifier* selected_verifier = &fail_closed_verifier;
sgk::EventSink* selected_event_sink = nullptr;
static void (*s_auth_pending_callback)(uint32_t now_ms) = nullptr;
static void (*s_auth_grant_callback)(uint32_t now_ms) = nullptr;
static void (*s_auth_abort_callback)(uint32_t now_ms) = nullptr;

#if ENABLE_HARDWARELESS_RC
constexpr uint16_t kNimbleSubscribeIndicate = 0x0002;

class EspRandomSource final : public sgk::RandomSource {
 public:
  bool fill(uint8_t* output, size_t length) override {
    if (output == nullptr) return false;
    esp_fill_random(output, length);
    return true;
  }
};

EspRandomSource random_source;
sgk::ProtocolCore* core = nullptr;
sgk::AdapterState adapter_state;
BLEServer* ble_server = nullptr;
BLEService* auth_service = nullptr;
BLECharacteristic* hello_characteristic = nullptr;
BLECharacteristic* challenge_characteristic = nullptr;
BLECharacteristic* proof_characteristic = nullptr;
BLECharacteristic* result_characteristic = nullptr;
std::array<uint8_t, sgk::kMaxMessageSize + sgk::kFrameHeaderSize>
    challenge_read_value{};
size_t challenge_read_length = 0;
portMUX_TYPE core_mux = portMUX_INITIALIZER_UNLOCKED;
sgk::IndicationToken in_flight_token_{};
sgk::MessageType in_flight_type_{sgk::MessageType::kError};
bool in_flight_valid_{false};

class CanonicalMqttEventSink final : public sgk::EventSink {
 public:
  bool configure(const std::array<uint8_t, 16>& door_id) {
    const mbedtls_md_info_t* info =
        mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    uint8_t digest[32] = {};
    if (info == nullptr || API_KEY == nullptr || API_KEY[0] == '\0' ||
        mbedtls_md_hmac(info, reinterpret_cast<const uint8_t*>(API_KEY),
                        std::strlen(API_KEY), door_id.data(), door_id.size(),
                        digest) != 0) {
      configured_ = false;
      return false;
    }
    char suffix[17] = {};
    bytesToHex(digest, 8, suffix, sizeof(suffix));
    std::snprintf(target_ref_, sizeof(target_ref_), "target_%s", suffix);
    configured_ = true;
    return true;
  }

  void emit(const sgk::Event& event) override {
    if (!configured_ || allZero(event.session_id.data(), event.session_id.size())) {
      return;
    }
    std::array<uint8_t, 16> event_id{};
    bool event_id_ready = false;
    for (size_t attempt = 0; attempt < 4; ++attempt) {
      esp_fill_random(event_id.data(), event_id.size());
      if (!allZero(event_id.data(), event_id.size()) &&
          event_id != last_event_id_bytes_) {
        event_id_ready = true;
        break;
      }
    }
    if (!event_id_ready) return;
    event_id[6] = static_cast<uint8_t>((event_id[6] & 0x0f) | 0x40);
    event_id[8] = static_cast<uint8_t>((event_id[8] & 0x3f) | 0x80);

    std::array<uint8_t, 16> schema_session = event.session_id;
    schema_session[6] = static_cast<uint8_t>((schema_session[6] & 0x0f) | 0x40);
    schema_session[8] = static_cast<uint8_t>((schema_session[8] & 0x3f) | 0x80);
    char event_id_text[37] = {};
    char session_id_text[37] = {};
    char boot_id_text[33] = {};
    uuidText(event_id, event_id_text);
    uuidText(schema_session, session_id_text);
    bytesToHex(event.boot_id.data(), event.boot_id.size(), boot_id_text,
               sizeof(boot_id_text));

    const bool same_session =
        std::memcmp(last_session_.data(), schema_session.data(),
                    schema_session.size()) == 0;
    const bool causal = same_session && event.has_causation &&
                        event.causation_sequence == last_sequence_ &&
                        last_event_id_[0] != '\0';

    StaticJsonDocument<1024> document;
    document["schema_version"] = "1.0";
    document["event_id"] = event_id_text;
    document["session_id"] = session_id_text;
    document["session_kind"] = "access";
    document["source_component"] = "target";
    document["source_instance_id"] = target_ref_;
    document["source_boot_id"] = boot_id_text;
    document["sequence"] = event.sequence;
    document["attempt"] = 1;
    if (!addCatalogFields(document, event)) return;
    JsonObject clock = document.createNestedObject("clock");
    clock["wall_time"] = nullptr;
    clock["monotonic_ms"] = event.monotonic_ms;
    clock["quality"] = "UNSYNCED";
    JsonObject target = document.createNestedObject("target");
    target["target_ref"] = target_ref_;
    target["boot_id"] = boot_id_text;
    if (causal) {
      document["causation_event_id"] = last_event_id_;
    } else {
      document["causation_event_id"] = nullptr;
    }
    JsonObject attributes = document.createNestedObject("attributes");
    attributes["path"] = "local_gatt";
    attributes["transport"] = "ble_gatt";

    char payload[1024] = {};
    if (measureJson(document) >= sizeof(payload) ||
        serializeJson(document, payload, sizeof(payload)) == 0) {
      return;
    }
    if (!MqttManager::publishCanonicalEvent(payload)) {
      sgk::CanonicalEvent queued_evt{};
      queued_evt.is_canonical = 1;
      queued_evt.code = static_cast<uint16_t>(event.code);
      queued_evt.transport_reason = static_cast<uint16_t>(event.transport_reason);
      queued_evt.monotonic_ms = event.monotonic_ms;
      queued_evt.sequence = event.sequence;
      queued_evt.attempt = 1;

      const char* ev_code_str = document["event_code"];
      const char* stage_str = document["stage"];
      const char* outcome_str = document["outcome"];
      const char* reason_str = document["reason_code"];

      if (ev_code_str && ev_code_str[0] != '\0' &&
          stage_str && stage_str[0] != '\0' &&
          outcome_str && outcome_str[0] != '\0' &&
          reason_str && reason_str[0] != '\0' &&
          event_id_text[0] != '\0' &&
          session_id_text[0] != '\0' &&
          boot_id_text[0] != '\0' &&
          target_ref_[0] != '\0') {
        std::strncpy(queued_evt.event_type, ev_code_str, sizeof(queued_evt.event_type) - 1);
        std::strncpy(queued_evt.stage_text, stage_str, sizeof(queued_evt.stage_text) - 1);
        std::strncpy(queued_evt.outcome_text, outcome_str, sizeof(queued_evt.outcome_text) - 1);
        std::strncpy(queued_evt.detail, reason_str, sizeof(queued_evt.detail) - 1);

        std::strncpy(queued_evt.event_id, event_id_text, sizeof(queued_evt.event_id) - 1);
        std::strncpy(queued_evt.session_id, session_id_text, sizeof(queued_evt.session_id) - 1);
        std::strncpy(queued_evt.source_boot_id, boot_id_text, sizeof(queued_evt.source_boot_id) - 1);
        std::strncpy(queued_evt.target_ref, target_ref_, sizeof(queued_evt.target_ref) - 1);
        if (causal) {
          queued_evt.has_causation = 1;
          std::strncpy(queued_evt.causation_event_id, last_event_id_, sizeof(queued_evt.causation_event_id) - 1);
        }
        if (!g_offline_queue.push(queued_evt)) {
          LOGF("[ERROR] CanonicalMqttEventSink: Offline queue enqueue failed for %s", ev_code_str);
        }
      }
    }

    last_session_ = schema_session;
    last_sequence_ = event.sequence;
    last_event_id_bytes_ = event_id;
    std::strncpy(last_event_id_, event_id_text, sizeof(last_event_id_) - 1);

    if (event.code == sgk::EventCode::kAccessProofRequested &&
        s_auth_pending_callback != nullptr) {
      s_auth_pending_callback(static_cast<uint32_t>(event.monotonic_ms));
    }
    if (event.code == sgk::EventCode::kAccessProofVerified &&
        s_auth_grant_callback != nullptr) {
      s_auth_grant_callback(static_cast<uint32_t>(event.monotonic_ms));
    }
    if ((event.code == sgk::EventCode::kAccessProofRejected ||
         event.code == sgk::EventCode::kAccessSessionTerminated) &&
        s_auth_abort_callback != nullptr) {
      s_auth_abort_callback(static_cast<uint32_t>(event.monotonic_ms));
    }
  }

 private:
  static bool allZero(const uint8_t* value, size_t length) {
    uint8_t aggregate = 0;
    for (size_t index = 0; index < length; ++index) aggregate |= value[index];
    return aggregate == 0;
  }

  static void bytesToHex(const uint8_t* value, size_t length, char* output,
                         size_t capacity) {
    static constexpr char kHex[] = "0123456789abcdef";
    if (output == nullptr || capacity < length * 2 + 1) return;
    for (size_t index = 0; index < length; ++index) {
      output[index * 2] = kHex[value[index] >> 4];
      output[index * 2 + 1] = kHex[value[index] & 0x0f];
    }
    output[length * 2] = '\0';
  }

  static void uuidText(const std::array<uint8_t, 16>& value, char output[37]) {
    std::snprintf(
        output, 37,
        "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        value[0], value[1], value[2], value[3], value[4], value[5], value[6],
        value[7], value[8], value[9], value[10], value[11], value[12],
        value[13], value[14], value[15]);
  }

  static const char* reasonCode(sgk::ResultReason reason) {
    switch (reason) {
      case sgk::ResultReason::kUnsupportedVersion:
        return "PROTOCOL_INCOMPATIBLE";
      case sgk::ResultReason::kMalformed:
        return "MALFORMED_PROOF";
      case sgk::ResultReason::kSessionInvalid:
        return "GATT_DISCONNECTED";
      case sgk::ResultReason::kExpiredOrReplay:
        return "PROOF_EXPIRED";
      case sgk::ResultReason::kAclUnavailable:
        return "ACL_NOT_FOUND";
      case sgk::ResultReason::kCredentialDenied:
        return "CREDENTIAL_INACTIVE";
      case sgk::ResultReason::kProofInvalid:
        return "SIGNATURE_INVALID";
      case sgk::ResultReason::kBusy:
        return "OTA_BUSY";
      case sgk::ResultReason::kRateLimited:
        return "SESSION_TIMEOUT";
      default:
        return "INTERNAL_ERROR";
    }
  }

  static bool addCatalogFields(JsonDocument& document,
                               const sgk::Event& event) {
    switch (event.code) {
      case sgk::EventCode::kAccessGattConnected:
        document["event_code"] = "ACCESS_GATT_CONNECTED";
        document["stage"] = "GATT_CONNECT";
        document["outcome"] = "SUCCEEDED";
        document["reason_code"] = "GATT_CONNECTED";
        return true;
      case sgk::EventCode::kAccessGattFailed:
        document["event_code"] = "ACCESS_GATT_FAILED";
        document["stage"] = "GATT_CONNECT";
        document["outcome"] = "FAILED";
        document["reason_code"] = "GATT_DISCONNECTED";
        return true;
      case sgk::EventCode::kAccessProofRequested:
        document["event_code"] = "ACCESS_PROOF_REQUESTED";
        document["stage"] = "PROOF";
        document["outcome"] = "STARTED";
        document["reason_code"] = "PROOF_CHALLENGE_ISSUED";
        return true;
      case sgk::EventCode::kAccessProofVerified:
        document["event_code"] = "ACCESS_PROOF_VERIFIED";
        document["stage"] = "PROOF";
        document["outcome"] = "SUCCEEDED";
        document["reason_code"] = "PROOF_VALID";
        return true;
      case sgk::EventCode::kAccessArmed:
        document["event_code"] = "ACCESS_ARMED";
        document["stage"] = "ARMED";
        document["outcome"] = "SUCCEEDED";
        document["reason_code"] = "ARM_ACCEPTED";
        return true;
      case sgk::EventCode::kAccessSensorDetected:
        document["event_code"] = "ACCESS_SENSOR_DETECTED";
        document["stage"] = "SENSOR";
        document["outcome"] = "SUCCEEDED";
        document["reason_code"] = "SENSOR_THRESHOLD_MET";
        return true;
      case sgk::EventCode::kAccessRelayOn:
        document["event_code"] = "ACCESS_RELAY_ON";
        document["stage"] = "RELAY_ON";
        document["outcome"] = "SUCCEEDED";
        document["reason_code"] = "RELAY_ACTIVATED";
        return true;
      case sgk::EventCode::kAccessRelayOff:
        document["event_code"] = "ACCESS_RELAY_OFF";
        document["stage"] = "RELAY_OFF";
        document["outcome"] = "SUCCEEDED";
        document["reason_code"] =
            event.reason == sgk::EventReason::kRelayFailsafeCutoff
                ? "RELAY_FAILSAFE_CUTOFF"
                : "RELAY_HOLD_COMPLETE";
        return true;
      case sgk::EventCode::kAccessSessionCompleted:
        document["event_code"] = "ACCESS_SESSION_COMPLETED";
        document["stage"] = "COMPLETE";
        document["outcome"] = "SUCCEEDED";
        document["reason_code"] = "ACCESS_GRANTED";
        return true;
      case sgk::EventCode::kAccessProofRejected:
        if (event.transport_reason == sgk::ResultReason::kAclUnavailable ||
            event.transport_reason == sgk::ResultReason::kCredentialDenied) {
          document["event_code"] = "ACCESS_ACL_REJECTED";
          document["stage"] = "ACL";
        } else {
          if (event.transport_reason != sgk::ResultReason::kUnsupportedVersion &&
              event.transport_reason != sgk::ResultReason::kMalformed &&
              event.transport_reason != sgk::ResultReason::kExpiredOrReplay &&
              event.transport_reason != sgk::ResultReason::kProofInvalid) {
            return false;
          }
          document["event_code"] = "ACCESS_PROOF_REJECTED";
          document["stage"] = "PROOF";
        }
        document["outcome"] = "DENIED";
        document["reason_code"] = reasonCode(event.transport_reason);
        return true;
      case sgk::EventCode::kAccessSessionTerminated:
        document["event_code"] = "ACCESS_SESSION_TERMINATED";
        document["stage"] = "COMPLETE";
        if (event.reason == sgk::EventReason::kArmTimeout) {
          document["outcome"] = "TIMED_OUT";
          document["reason_code"] = "ARM_TIMEOUT";
        } else {
          document["outcome"] = "FAILED";
          document["reason_code"] = reasonCode(event.transport_reason);
        }
        return true;
    }
    return false;
  }

  bool configured_ = false;
  char target_ref_[32] = {};
  std::array<uint8_t, 16> last_session_{};
  std::array<uint8_t, 16> last_event_id_bytes_{};
  uint64_t last_sequence_ = 0;
  char last_event_id_[37] = {};
};

CanonicalMqttEventSink production_event_sink;
// NimBLE invokes server/characteristic callbacks on its 5 KB host task.  The
// canonical sink builds JSON and publishes over MQTTS, so running it from a BLE
// callback can exhaust that stack (and did on the physical ESP32-C6 while a
// multi-fragment challenge was being acknowledged).  Keep callback work to a
// bounded event copy and publish from the 16 KB Arduino loop task instead.
class DeferredCanonicalEventSink final : public sgk::EventSink {
 public:
  explicit DeferredCanonicalEventSink(sgk::EventSink* downstream)
      : downstream_(downstream) {}

  void emit(const sgk::Event& event) override {
    portENTER_CRITICAL(&mux_);
    if (count_ == events_.size()) {
      overflowed_ = true;
    } else {
      const size_t tail = (head_ + count_) % events_.size();
      events_[tail] = event;
      ++count_;
    }
    portEXIT_CRITICAL(&mux_);
  }

  void drain() {
    bool reported_overflow = false;
    while (true) {
      sgk::Event event{};
      bool available = false;
      portENTER_CRITICAL(&mux_);
      if (overflowed_ && !reported_overflow) {
        overflowed_ = false;
        reported_overflow = true;
      }
      if (count_ != 0) {
        event = events_[head_];
        head_ = (head_ + 1) % events_.size();
        --count_;
        available = true;
      }
      portEXIT_CRITICAL(&mux_);
      if (reported_overflow) {
        LOGF("[ERROR] GATT canonical event queue overflow; audit event dropped");
        reported_overflow = false;
      }
      if (!available) return;
      if (downstream_ != nullptr) downstream_->emit(event);
    }
  }

  void clear() {
    portENTER_CRITICAL(&mux_);
    head_ = 0;
    count_ = 0;
    overflowed_ = false;
    portEXIT_CRITICAL(&mux_);
  }

 private:
  static constexpr size_t kCapacity = 16;
  sgk::EventSink* downstream_ = nullptr;
  std::array<sgk::Event, kCapacity> events_{};
  size_t head_ = 0;
  size_t count_ = 0;
  bool overflowed_ = false;
  portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
};

DeferredCanonicalEventSink deferred_event_sink(&production_event_sink);
sgk::LocalGattLifecycleBridge production_lifecycle_bridge(
    &deferred_event_sink);

class ServerCallbacks final : public BLEServerCallbacks {
 public:
#if defined(CONFIG_BLUEDROID_ENABLED)
  void onConnect(BLEServer* server,
                 esp_ble_gatts_cb_param_t* parameters) override {
    const uint16_t connection_id = parameters->connect.conn_id;
    if (!GattServer::handleConnect(connection_id)) {
      server->disconnect(connection_id);
    }
  }

  void onDisconnect(BLEServer*,
                    esp_ble_gatts_cb_param_t* parameters) override {
    GattServer::handleDisconnect(parameters->disconnect.conn_id);
    if (GattServer::isEnabled() &&
        GattServer::getActiveConnections() == 0) {
      BLEDevice::startAdvertising();
    }
  }
#elif defined(CONFIG_NIMBLE_ENABLED)
  void onConnect(BLEServer* server, ble_gap_conn_desc* description) override {
    const uint16_t connection_id = description->conn_handle;
    if (!GattServer::handleConnect(connection_id)) {
      server->disconnect(connection_id);
    }
  }

  void onDisconnect(BLEServer*, ble_gap_conn_desc* description) override {
    GattServer::handleDisconnect(description->conn_handle);
    if (GattServer::isEnabled() &&
        GattServer::getActiveConnections() == 0) {
      BLEDevice::startAdvertising();
    }
  }
#endif
};

class WriteCallbacks final : public BLECharacteristicCallbacks {
 public:
  WriteCallbacks(sgk::MessageType write_type,
                 sgk::MessageType indication_type)
      : write_type_(write_type), indication_type_(indication_type) {}

#if defined(CONFIG_BLUEDROID_ENABLED)
  void onWrite(BLECharacteristic* characteristic,
               esp_ble_gatts_cb_param_t* parameters) override {
    GattServer::handleWrite(parameters->write.conn_id, write_type_,
                            characteristic->getData(),
                            characteristic->getLength());
  }
#elif defined(CONFIG_NIMBLE_ENABLED)
  void onWrite(BLECharacteristic* characteristic,
               ble_gap_conn_desc* description) override {
    GattServer::handleWrite(description->conn_handle, write_type_,
                            characteristic->getData(),
                            characteristic->getLength());
  }

  void onSubscribe(BLECharacteristic*, ble_gap_conn_desc* description,
                   uint16_t sub_value) override {
    GattServer::handleSubscribe(description->conn_handle, indication_type_,
                                (sub_value & kNimbleSubscribeIndicate) != 0);
  }
#endif

  void onStatus(BLECharacteristic*, Status status, uint32_t) override {
    GattServer::handleIndicationStatus(
        indication_type_, status == Status::SUCCESS_INDICATE);
  }

 private:
  sgk::MessageType write_type_;
  sgk::MessageType indication_type_;
};

ServerCallbacks server_callbacks;
WriteCallbacks hello_callbacks(sgk::MessageType::kClientHello,
                               sgk::MessageType::kTargetHello);
WriteCallbacks proof_callbacks(sgk::MessageType::kProof,
                               sgk::MessageType::kError);
WriteCallbacks challenge_callbacks(sgk::MessageType::kError,
                                   sgk::MessageType::kChallenge);
WriteCallbacks result_callbacks(sgk::MessageType::kError,
                                sgk::MessageType::kResult);

void addDescriptors(BLECharacteristic* characteristic, const char* label,
                    bool indication) {
  auto* description = new BLE2901();
  description->setDescription(label);
  characteristic->addDescriptor(description);
  (void)indication;  // The stack creates CCCD 0x2902 for INDICATE properties.
}

BLECharacteristic* characteristicFor(sgk::MessageType type) {
  switch (type) {
    case sgk::MessageType::kTargetHello:
      return hello_characteristic;
    case sgk::MessageType::kChallenge:
      return challenge_characteristic;
    case sgk::MessageType::kResult:
    case sgk::MessageType::kError:
      return result_characteristic;
    default:
      return nullptr;
  }
}
#endif

}  // namespace

void GattServer::init() {
#if ENABLE_HARDWARELESS_RC
  deferred_event_sink.clear();
  if (core != nullptr) {
    delete core;
    core = nullptr;
  }
  std::array<uint8_t, 16> door_id{};
  if (!ConfigManager::getHardwarelessDoorId(&door_id)) {
    requested_enabled = false;
    LOGF("[FATAL] GATT door_id is absent/invalid; auth disabled");
    return;
  }
  const bool production_sink_selected =
      selected_event_sink == &production_event_sink ||
      selected_event_sink == &production_lifecycle_bridge;
  if (production_sink_selected && !production_event_sink.configure(door_id)) {
    requested_enabled = false;
    LOGF("[FATAL] GATT canonical event identity unavailable; auth disabled");
    return;
  }
  adapter_state.clear();
  core = new sgk::ProtocolCore(random_source, *selected_verifier, door_id,
                               selected_event_sink);
  if (!core->initialize()) {
    requested_enabled = false;
    LOGF("[FATAL] GATT CSPRNG boot ID initialization failed; auth disabled");
    return;
  }
  core->setEnabled(requested_enabled);
  if (core->enabled()) createService();
#else
  requested_enabled = false;
#endif
  LOGF("[INFO] GATT transport initialized: %s",
       isEnabled() ? "enabled" : "disabled");
}

void GattServer::update() {
#if ENABLE_HARDWARELESS_RC
  // Flush events produced by NimBLE callbacks before doing protocol work, then
  // flush again below for events produced during this update pass.
  deferred_event_sink.drain();
  if (core == nullptr || !core->enabled()) return;

  const uint32_t now_ms = millis();
  sgk::ConnectionToken overflow_owner;
  portENTER_CRITICAL(&core_mux);
  const bool overflow = adapter_state.consumeOverflow(&overflow_owner);
  if (overflow) {
    // Overflow wins before any queued proof can reach the verifier.
    core->receiveFrame(sgk::MessageType::kProof, overflow_owner, nullptr, 0,
                       now_ms);
  }
  portEXIT_CRITICAL(&core_mux);

  if (!overflow) {
    while (true) {
      sgk::PendingWrite pending;
      portENTER_CRITICAL(&core_mux);
      const bool available = adapter_state.popWrite(&pending);
      if (available) {
        core->receiveFrame(pending.type, pending.owner, pending.bytes.data(),
                           pending.length, millis());
      }
      portEXIT_CRITICAL(&core_mux);
      if (!available) break;
    }
  }

  sgk::ConnectionToken timeout_owner;
  bool indication_timeout = false;
  portENTER_CRITICAL(&core_mux);
  core->tick(millis());
  if (adapter_state.confirmationTimedOut(millis())) {
    timeout_owner = adapter_state.activeOwner();
    adapter_state.abortOutput();
    adapter_state.clearWrites();
    core->abortTransport(timeout_owner,
                         sgk::ResultReason::kInternalFailClosed, millis());
    indication_timeout = true;
  }
  portEXIT_CRITICAL(&core_mux);
  if (indication_timeout) {
    LOGF("[ERROR] GATT indication confirmation timed out; session aborted");
  }
  deferred_event_sink.drain();
  // Preserve the synchronous contract: authentication lifecycle callbacks
  // (including ARMED transition) run before the corresponding RESULT is sent.
  drainOutputs();
#endif
}

bool GattServer::isEnabled() {
#if ENABLE_HARDWARELESS_RC
  return core != nullptr && core->enabled() && auth_service != nullptr;
#else
  return false;
#endif
}

void GattServer::setEnabled(bool enabled) {
#if ENABLE_HARDWARELESS_RC
  requested_enabled = enabled;
  if (core == nullptr) return;
  portENTER_CRITICAL(&core_mux);
  core->setEnabled(enabled);
  portEXIT_CRITICAL(&core_mux);
  if (enabled) {
    createService();
  } else {
    destroyService();
  }
#else
  (void)enabled;
  requested_enabled = false;
#endif
}

bool GattServer::isConnected() { return getActiveConnections() != 0; }

uint32_t GattServer::getActiveConnections() {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return 0;
  portENTER_CRITICAL(&core_mux);
  const uint32_t count = core->connected() ? 1 : 0;
  portEXIT_CRITICAL(&core_mux);
  return count;
#else
  return 0;
#endif
}

bool GattServer::isOtaBusy() {
#if ENABLE_HARDWARELESS_RC
  return core != nullptr && core->otaBusy();
#else
  return false;
#endif
}

void GattServer::setOtaBusy(bool busy) {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return;
  portENTER_CRITICAL(&core_mux);
  in_flight_valid_ = false;
  if (busy) {
    adapter_state.abortOutput();
    adapter_state.clearWrites();
  }
  core->setOtaBusy(busy, millis());
  portEXIT_CRITICAL(&core_mux);
  drainOutputs();
#else
  (void)busy;
#endif
}

void GattServer::flushOtaBusy(uint32_t timeout_ms) {
#if ENABLE_HARDWARELESS_RC
  const uint32_t start_ms = millis();
  while (isOtaBusy() && isConnected() && hasActiveOutput()) {
    update();
    if (millis() - start_ms >= timeout_ms) {
      LOGF("[WARN] GATT OTA BUSY indication flush timed out after %lu ms",
           (unsigned long)timeout_ms);
      break;
    }
    delay(10);
  }
#else
  (void)timeout_ms;
#endif
}

bool GattServer::hasActiveOutput() {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return false;
  portENTER_CRITICAL(&core_mux);
  const bool active = adapter_state.outputActive() ||
                       adapter_state.confirmationPending() ||
                       core->hasOutput();
  portEXIT_CRITICAL(&core_mux);
  return active;
#else
  return false;
#endif
}

void GattServer::setProofVerifier(sgk::ProofVerifier* verifier) {
  selected_verifier = verifier == nullptr ? &fail_closed_verifier : verifier;
}

void GattServer::setEventSink(sgk::EventSink* sink) {
  selected_event_sink = sink;
}

void GattServer::setOnAuthPendingCallback(void (*callback)(uint32_t now_ms)) {
  s_auth_pending_callback = callback;
}

void GattServer::setOnAuthGrantCallback(void (*callback)(uint32_t now_ms)) {
  s_auth_grant_callback = callback;
}

void GattServer::setOnAuthAbortCallback(void (*callback)(uint32_t now_ms)) {
  s_auth_abort_callback = callback;
}

void GattServer::useProductionEventSink() {
#if ENABLE_HARDWARELESS_RC
  selected_event_sink = &production_lifecycle_bridge;
#endif
}

void GattServer::notifyAccessArmed(uint64_t now_ms) {
#if ENABLE_HARDWARELESS_RC
  if (production_lifecycle_bridge.emitArmed(now_ms) && core != nullptr) {
    core->advanceEventSequence(production_lifecycle_bridge.lastSequence());
  }
#endif
}

void GattServer::notifySensorDetected(uint64_t now_ms) {
#if ENABLE_HARDWARELESS_RC
  if (production_lifecycle_bridge.emitSensorDetected(now_ms) && core != nullptr) {
    core->advanceEventSequence(production_lifecycle_bridge.lastSequence());
  }
#endif
}

void GattServer::notifyRelayOn(uint64_t now_ms) {
#if ENABLE_HARDWARELESS_RC
  if (production_lifecycle_bridge.emitRelayOn(now_ms) && core != nullptr) {
    core->advanceEventSequence(production_lifecycle_bridge.lastSequence());
  }
#endif
}

void GattServer::notifyRelayOff(uint64_t now_ms, bool failsafe) {
#if ENABLE_HARDWARELESS_RC
  if (production_lifecycle_bridge.emitRelayOff(now_ms, failsafe) &&
      core != nullptr) {
    core->advanceEventSequence(production_lifecycle_bridge.lastSequence());
  }
#else
  (void)failsafe;
#endif
}

void GattServer::notifySessionCompleted(uint64_t now_ms) {
#if ENABLE_HARDWARELESS_RC
  const uint64_t completed_sequence =
      production_lifecycle_bridge.lastSequence() + 1;
  if (production_lifecycle_bridge.emitCompleted(now_ms) && core != nullptr) {
    core->advanceEventSequence(completed_sequence);
  }
#endif
}

void GattServer::notifySessionTerminated(uint64_t now_ms,
                                         sgk::EventReason reason) {
#if ENABLE_HARDWARELESS_RC
  const uint64_t terminal_sequence =
      production_lifecycle_bridge.lastSequence() + 1;
  if (production_lifecycle_bridge.emitTerminated(now_ms, reason) &&
      core != nullptr) {
    core->advanceEventSequence(terminal_sequence);
  }
#else
  (void)reason;
#endif
}

GattServer::Telemetry GattServer::getTelemetry() {
  Telemetry telemetry{0, 0, sgk::SessionState::kIdle, false};
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return telemetry;
  portENTER_CRITICAL(&core_mux);
  telemetry.active_connections = core->connected() ? 1 : 0;
  telemetry.failed_attempts = core->failedAttempts();
  telemetry.session_state = core->state();
  telemetry.ota_busy = core->otaBusy();
  portEXIT_CRITICAL(&core_mux);
#endif
  return telemetry;
}

bool GattServer::handleConnect(uint16_t connection_id) {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return false;
  portENTER_CRITICAL(&core_mux);
  sgk::ConnectionToken owner;
  const bool core_accepted = core->connect(connection_id, millis(), &owner);
  const bool accepted =
      core_accepted && adapter_state.acceptConnection(owner);
  if (core_accepted && !accepted) {
    core->disconnect(owner, millis());
  }
  portEXIT_CRITICAL(&core_mux);
  LOGF("[INFO] GATT connection %u %s", connection_id,
       accepted ? "accepted" : "rejected (single-connection limit)");
  return accepted;
#else
  (void)connection_id;
  return false;
#endif
}

void GattServer::handleDisconnect(uint16_t connection_id) {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return;
  portENTER_CRITICAL(&core_mux);
  sgk::ConnectionToken owner;
  if (adapter_state.ownerForHandle(connection_id, &owner)) {
    in_flight_valid_ = false;
    core->disconnect(owner, millis());
    adapter_state.disconnect(connection_id);
  }
  portEXIT_CRITICAL(&core_mux);
#else
  (void)connection_id;
#endif
}

void GattServer::handleWrite(uint16_t connection_id, sgk::MessageType type,
                             const uint8_t* value, size_t length) {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return;
  portENTER_CRITICAL(&core_mux);
  adapter_state.enqueueWrite(connection_id, type, value, length);
  portEXIT_CRITICAL(&core_mux);
#else
  (void)connection_id;
  (void)type;
  (void)value;
  (void)length;
#endif
}

void GattServer::handleSubscribe(uint16_t connection_id,
                                 sgk::MessageType type, bool subscribed) {
#if ENABLE_HARDWARELESS_RC
  portENTER_CRITICAL(&core_mux);
  adapter_state.setSubscribed(connection_id, type, subscribed);
  portEXIT_CRITICAL(&core_mux);
#else
  (void)connection_id;
  (void)type;
  (void)subscribed;
#endif
}

void GattServer::handleIndicationStatus(sgk::MessageType type, bool success) {
#if ENABLE_HARDWARELESS_RC
  sgk::IndicationToken token{};
  portENTER_CRITICAL(&core_mux);
  if (in_flight_valid_ && type == in_flight_type_) {
    token = in_flight_token_;
    in_flight_valid_ = false;
  }
  portEXIT_CRITICAL(&core_mux);
  handleIndicationStatus(token, type, success);
#else
  (void)type;
  (void)success;
#endif
}

void GattServer::handleIndicationStatus(const sgk::IndicationToken& token,
                                       sgk::MessageType type, bool success) {
#if ENABLE_HARDWARELESS_RC
  (void)type;
  sgk::ConnectionToken owner;
  sgk::IndicationResult result = sgk::IndicationResult::kIgnored;
  portENTER_CRITICAL(&core_mux);
  if (in_flight_valid_ && token == in_flight_token_) {
    in_flight_valid_ = false;
  }
  owner = adapter_state.activeOwner();
  result = adapter_state.confirmIndication(token, type, success);
  if (result == sgk::IndicationResult::kAborted && core != nullptr) {
    adapter_state.clearWrites();
    core->abortTransport(owner, sgk::ResultReason::kInternalFailClosed,
                         millis());
  }
  portEXIT_CRITICAL(&core_mux);
  if (result == sgk::IndicationResult::kAborted) {
    LOGF("[ERROR] GATT indication failed; session aborted");
  }
  // onStatus() runs on NimBLE's small host stack.  update() drains the next
  // fragment from the Arduino loop task, avoiding a 2.7 KB adapter frame there.
#else
  (void)token;
  (void)type;
  (void)success;
#endif
}

void GattServer::createService() {
#if ENABLE_HARDWARELESS_RC
  if (!requested_enabled || auth_service != nullptr || core == nullptr ||
      !core->enabled()) {
    return;
  }
  ble_server = BLEDevice::createServer();
  ble_server->setCallbacks(&server_callbacks);
  ble_server->advertiseOnDisconnect(false);
  auth_service = ble_server->createService(
      BLEUUID(String(HARDWARELESS_SERVICE_UUID)), 20);
  hello_characteristic = auth_service->createCharacteristic(
      HARDWARELESS_CHAR_HELLO_UUID,
      BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_INDICATE);
  challenge_characteristic = auth_service->createCharacteristic(
      HARDWARELESS_CHAR_CHAL_UUID,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_INDICATE);
  proof_characteristic = auth_service->createCharacteristic(
      HARDWARELESS_CHAR_PROOF_UUID, BLECharacteristic::PROPERTY_WRITE);
  result_characteristic = auth_service->createCharacteristic(
      HARDWARELESS_CHAR_RESULT_UUID, BLECharacteristic::PROPERTY_INDICATE);
  addDescriptors(hello_characteristic, "SGK target hello", true);
  addDescriptors(challenge_characteristic, "SGK challenge", true);
  addDescriptors(proof_characteristic, "SGK proof", false);
  addDescriptors(result_characteristic, "SGK result", true);
  hello_characteristic->setCallbacks(&hello_callbacks);
  challenge_characteristic->setCallbacks(&challenge_callbacks);
  proof_characteristic->setCallbacks(&proof_callbacks);
  result_characteristic->setCallbacks(&result_callbacks);
  auth_service->start();
  BLEAdvertisementData scan_response;
  scan_response.setName("SmartGatekeeper");
  scan_response.setCompleteServices(BLEUUID(String(HARDWARELESS_SERVICE_UUID)));
  BLEDevice::getAdvertising()->setScanResponseData(scan_response);
  BLEDevice::startAdvertising();
  LOGF("[INFO] GATT primary auth service started");
#endif
}

void GattServer::destroyService() {
#if ENABLE_HARDWARELESS_RC
  if (auth_service == nullptr) return;
  BLEDevice::getAdvertising()->stop();
  if (ble_server != nullptr) {
    for (const auto& peer : ble_server->getPeerDevices(false)) {
      ble_server->disconnect(peer.first);
    }
  }
  auth_service->stop();
  if (ble_server != nullptr) ble_server->removeService(auth_service);
  auth_service = nullptr;
  hello_characteristic = nullptr;
  challenge_characteristic = nullptr;
  proof_characteristic = nullptr;
  result_characteristic = nullptr;
  in_flight_valid_ = false;
  adapter_state.clear();
  // Keep the legacy iBeacon advertisement running, but remove the unavailable
  // GATT service UUID from the scan response.
  BLEAdvertisementData scan_response;
  scan_response.setName("SmartGatekeeper");
  BLEDevice::getAdvertising()->setScanResponseData(scan_response);
  BLEDevice::startAdvertising();
  LOGF("[INFO] GATT auth service disabled and session reset");
#endif
}

void GattServer::drainOutputs() {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr || !core->connected()) return;
  if (ble_server == nullptr) return;

  sgk::OutputMessage newly_staged;
  bool staged = false;
  bool stage_failed = false;
  bool begin_failed = false;
  sgk::ConnectionToken owner;
  sgk::IndicationToken token{};
  uint8_t frame[sgk::kAdapterFrameCapacity] = {};
  size_t frame_length = 0;
  sgk::MessageType type = sgk::MessageType::kError;

  portENTER_CRITICAL(&core_mux);
  if (!adapter_state.outputActive() && core->popOutput(&newly_staged)) {
    staged = adapter_state.stageOutput(newly_staged);
    if (!staged) {
      owner = adapter_state.activeOwner();
      adapter_state.clearWrites();
      core->abortTransport(owner, sgk::ResultReason::kInternalFailClosed,
                           millis());
      stage_failed = true;
    }
  }
  if (staged && newly_staged.type == sgk::MessageType::kChallenge) {
    challenge_read_length = sgk::ProtocolCore::buildFrame(
        newly_staged.type, newly_staged.message_id, newly_staged.bytes.data(),
        newly_staged.length, newly_staged.length, 0,
        challenge_read_value.data(), challenge_read_value.size());
  }
  if (adapter_state.outputActive() &&
      !adapter_state.confirmationPending()) {
    owner = adapter_state.activeOwner();
    const uint16_t mtu = ble_server->getPeerMTU(owner.handle);
    if (!adapter_state.beginNextIndication(
            mtu, millis(), frame, sizeof(frame), &frame_length, &type,
            &token)) {
      owner = adapter_state.activeOwner();
      adapter_state.abortOutput();
      adapter_state.clearWrites();
      core->abortTransport(owner, sgk::ResultReason::kInternalFailClosed,
                           millis());
      begin_failed = true;
    } else {
      in_flight_token_ = token;
      in_flight_type_ = type;
      in_flight_valid_ = true;
    }
  }
  portEXIT_CRITICAL(&core_mux);

  if (stage_failed || begin_failed) {
    LOGF("[ERROR] GATT output owner/subscription mismatch; session aborted");
    return;
  }
  if (staged && challenge_read_length != 0 &&
      challenge_characteristic != nullptr) {
    challenge_characteristic->setValue(challenge_read_value.data(),
                                       challenge_read_length);
  }
  if (frame_length == 0) return;

  BLECharacteristic* characteristic = characteristicFor(type);
  if (characteristic == nullptr) {
    handleIndicationStatus(token, type, false);
    return;
  }
  characteristic->setValue(frame, frame_length);
#if defined(CONFIG_NIMBLE_ENABLED)
  os_mbuf* packet = ble_hs_mbuf_from_flat(frame, frame_length);
  if (packet == nullptr ||
      ble_gatts_indicate_custom(owner.handle, characteristic->getHandle(),
                                packet) != 0) {
    if (packet != nullptr) os_mbuf_free_chain(packet);
    handleIndicationStatus(token, type, false);
  }
#else
  // Bluedroid has no conn_handle overload. Rejected peers are disconnected in
  // onConnect before they can become accepted/subscribed adapter owners.
  characteristic->indicate();
#endif
  if (type == sgk::MessageType::kChallenge && challenge_read_length != 0) {
    challenge_characteristic->setValue(challenge_read_value.data(),
                                       challenge_read_length);
  }
#endif
}
