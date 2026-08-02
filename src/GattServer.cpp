#include "GattServer.h"

#include <Arduino.h>
#include <array>

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

#if ENABLE_HARDWARELESS_RC
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
BLEServer* ble_server = nullptr;
BLEService* auth_service = nullptr;
BLECharacteristic* hello_characteristic = nullptr;
BLECharacteristic* challenge_characteristic = nullptr;
BLECharacteristic* proof_characteristic = nullptr;
BLECharacteristic* result_characteristic = nullptr;
portMUX_TYPE core_mux = portMUX_INITIALIZER_UNLOCKED;
uint16_t active_connection_id = 0;
struct PendingWrite {
  sgk::MessageType type = sgk::MessageType::kError;
  size_t length = 0;
  std::array<uint8_t, 512> bytes{};
};
std::array<PendingWrite, 4> pending_writes{};
size_t pending_head = 0;
size_t pending_count = 0;
bool pending_overflow = false;

class ServerCallbacks final : public BLEServerCallbacks {
 public:
#if defined(CONFIG_BLUEDROID_ENABLED)
  void onConnect(BLEServer* server,
                 esp_ble_gatts_cb_param_t* parameters) override {
    const uint16_t connection_id = parameters->connect.conn_id;
    GattServer::handleConnect(connection_id);
    if (GattServer::getActiveConnections() == 0) {
      server->disconnect(connection_id);
    }
  }

  void onDisconnect(BLEServer*,
                    esp_ble_gatts_cb_param_t* parameters) override {
    GattServer::handleDisconnect(parameters->disconnect.conn_id);
    if (GattServer::isEnabled()) BLEDevice::startAdvertising();
  }
#elif defined(CONFIG_NIMBLE_ENABLED)
  void onConnect(BLEServer* server, ble_gap_conn_desc* description) override {
    const uint16_t connection_id = description->conn_handle;
    GattServer::handleConnect(connection_id);
    if (GattServer::getActiveConnections() == 0) {
      server->disconnect(connection_id);
    }
  }

  void onDisconnect(BLEServer*, ble_gap_conn_desc* description) override {
    GattServer::handleDisconnect(description->conn_handle);
    if (GattServer::isEnabled()) BLEDevice::startAdvertising();
  }
#endif
};

class WriteCallbacks final : public BLECharacteristicCallbacks {
 public:
  explicit WriteCallbacks(sgk::MessageType type) : type_(type) {}

  void onWrite(BLECharacteristic* characteristic) override {
    GattServer::handleWrite(type_, characteristic->getData(),
                            characteristic->getLength());
  }

 private:
  sgk::MessageType type_;
};

ServerCallbacks server_callbacks;
WriteCallbacks hello_callbacks(sgk::MessageType::kClientHello);
WriteCallbacks proof_callbacks(sgk::MessageType::kProof);

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
  if (core != nullptr) {
    delete core;
    core = nullptr;
  }
  core = new sgk::ProtocolCore(random_source, *selected_verifier,
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
  if (core == nullptr || !core->enabled()) return;
  while (true) {
    PendingWrite pending;
    bool available = false;
    portENTER_CRITICAL(&core_mux);
    if (pending_count != 0) {
      pending = pending_writes[pending_head];
      pending_head = (pending_head + 1) % pending_writes.size();
      pending_count--;
      available = true;
    }
    portEXIT_CRITICAL(&core_mux);
    if (!available) break;
    portENTER_CRITICAL(&core_mux);
    core->receiveFrame(pending.type, active_connection_id,
                       pending.bytes.data(), pending.length, millis());
    portEXIT_CRITICAL(&core_mux);
  }
  portENTER_CRITICAL(&core_mux);
  if (pending_overflow) {
    pending_overflow = false;
    core->receiveFrame(sgk::MessageType::kProof, active_connection_id,
                       nullptr, 0, millis());
  }
  core->tick(millis());
  portEXIT_CRITICAL(&core_mux);
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
  core->setOtaBusy(busy, millis());
  portEXIT_CRITICAL(&core_mux);
  drainOutputs();
#else
  (void)busy;
#endif
}

void GattServer::setProofVerifier(sgk::ProofVerifier* verifier) {
  selected_verifier = verifier == nullptr ? &fail_closed_verifier : verifier;
}

void GattServer::setEventSink(sgk::EventSink* sink) {
  selected_event_sink = sink;
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

void GattServer::handleConnect(uint16_t connection_id) {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return;
  portENTER_CRITICAL(&core_mux);
  const bool accepted = core->connect(connection_id, millis());
  if (accepted) active_connection_id = connection_id;
  portEXIT_CRITICAL(&core_mux);
  LOGF("[INFO] GATT connection %u %s", connection_id,
       accepted ? "accepted" : "rejected (single-connection limit)");
#else
  (void)connection_id;
#endif
}

void GattServer::handleDisconnect(uint16_t connection_id) {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return;
  portENTER_CRITICAL(&core_mux);
  core->disconnect(connection_id, millis());
  if (!core->connected()) {
    active_connection_id = 0;
    pending_head = 0;
    pending_count = 0;
    pending_overflow = false;
  }
  portEXIT_CRITICAL(&core_mux);
#else
  (void)connection_id;
#endif
}

void GattServer::handleWrite(sgk::MessageType type, const uint8_t* value,
                             size_t length) {
#if ENABLE_HARDWARELESS_RC
  if (core == nullptr) return;
  portENTER_CRITICAL(&core_mux);
  if (!core->connected()) {
    portEXIT_CRITICAL(&core_mux);
    return;
  }
  if (value == nullptr || length == 0 || length > pending_writes[0].bytes.size() ||
      pending_count == pending_writes.size()) {
    pending_overflow = true;
  } else {
    const size_t slot = (pending_head + pending_count) % pending_writes.size();
    pending_writes[slot].type = type;
    pending_writes[slot].length = length;
    memcpy(pending_writes[slot].bytes.data(), value, length);
    pending_count++;
  }
  portEXIT_CRITICAL(&core_mux);
#else
  (void)type;
  (void)value;
  (void)length;
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
  proof_characteristic->setCallbacks(&proof_callbacks);
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
  active_connection_id = 0;
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
  sgk::OutputMessage message;
  while (true) {
    portENTER_CRITICAL(&core_mux);
    const bool available = core->popOutput(&message);
    portEXIT_CRITICAL(&core_mux);
    if (!available) break;
    BLECharacteristic* characteristic = characteristicFor(message.type);
    if (characteristic == nullptr || ble_server == nullptr) continue;
    uint8_t read_value[sgk::kMaxMessageSize + sgk::kFrameHeaderSize] = {};
    size_t read_value_length = 0;
    if (message.type == sgk::MessageType::kChallenge) {
      // A GATT long read returns this complete, single framed value through
      // ATT Read Blob operations; indications below remain MTU-fragmented.
      read_value_length = sgk::ProtocolCore::buildFrame(
          message.type, message.message_id, message.bytes.data(), message.length,
          message.length, 0, read_value, sizeof(read_value));
      challenge_characteristic->setValue(read_value, read_value_length);
    }
    const uint16_t mtu = ble_server->getPeerMTU(active_connection_id);
    const size_t payload_capacity =
        mtu > sgk::kFrameHeaderSize + 3 ? mtu - 3 - sgk::kFrameHeaderSize : 1;
    const size_t fragment_count =
        (message.length + payload_capacity - 1) / payload_capacity;
    for (size_t index = 0; index < fragment_count; ++index) {
      uint8_t frame[512] = {};
      const size_t frame_length = sgk::ProtocolCore::buildFrame(
          message.type, message.message_id, message.bytes.data(), message.length,
          payload_capacity, static_cast<uint8_t>(index), frame, sizeof(frame));
      if (frame_length == 0) break;
      characteristic->setValue(frame, frame_length);
      // Arduino BLE indicate() blocks for the peer confirmation before the
      // next fragment, providing bounded ACK backpressure.
      characteristic->indicate();
    }
    if (read_value_length != 0) {
      challenge_characteristic->setValue(read_value, read_value_length);
    }
  }
#endif
}
