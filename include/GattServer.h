#pragma once

#include <cstddef>
#include <cstdint>

#include "GattProtocol.h"
#include "config.h"

// Thin Arduino BLE adapter. All parsing and session decisions live in the
// host-testable sgk::ProtocolCore used by this production adapter.
class GattServer {
 public:
  struct Telemetry {
    uint32_t active_connections;
    uint32_t failed_attempts;
    sgk::SessionState session_state;
    bool ota_busy;
  };

  static void init();
  static void update();
  static bool isEnabled();
  static void setEnabled(bool enabled);
  static bool isConnected();
  static uint32_t getActiveConnections();
  static bool isOtaBusy();
  static void setOtaBusy(bool busy);
  static void flushOtaBusy(uint32_t timeout_ms = 3000);
  static bool hasActiveOutput();
  static void setProofVerifier(sgk::ProofVerifier* verifier);
  static void setEventSink(sgk::EventSink* sink);
  static void setOnAuthPendingCallback(bool (*callback)(uint32_t now_ms));
  static void setOnAuthGrantCallback(
      bool (*callback)(sgk::LocalAccessAction action, uint32_t now_ms));
  static void setOnAuthAbortCallback(void (*callback)(uint32_t now_ms));
  static void useProductionEventSink();
  static void notifyAccessArmed(uint64_t now_ms);
  static void notifySensorDetected(uint64_t now_ms);
  static void notifyRelayOn(uint64_t now_ms);
  static void notifyRelayOff(uint64_t now_ms, bool failsafe);
  static void notifySessionCompleted(uint64_t now_ms);
  static void notifySessionTerminated(uint64_t now_ms,
                                      sgk::EventReason reason);
  // Keep local GATT canonical sequencing above a terminal position allocated
  // by the independent signed-command access path.
  static void advanceEventSequence(uint64_t used_sequence);
  static Telemetry getTelemetry();

  // Callback entrypoints are public only so the BLE callback shims can remain
  // allocation-free. Application code must not bypass the GATT characteristics.
  static bool handleConnect(uint16_t connection_id);
  static void handleDisconnect(uint16_t connection_id);
  static void handleWrite(uint16_t connection_id, sgk::MessageType type,
                          const uint8_t* value, size_t length);
  static void handleSubscribe(uint16_t connection_id, sgk::MessageType type,
                              bool subscribed);
  static void handleFastSubscribe(uint16_t connection_id, bool subscribed);
  static void handleCurrentIndicationStatus(bool success);
  static void handleIndicationStatus(const sgk::IndicationToken& token,
                                     sgk::MessageType type, bool success);
  static void handleIndicationStatus(sgk::MessageType type, bool success);

 private:
  static void createService();
  static void destroyService();
  static void drainOutputs();
};
