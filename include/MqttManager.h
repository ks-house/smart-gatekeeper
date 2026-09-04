// include/MqttManager.h
// =============================================================
// smart-gatekeeper verified MQTTS manager
// Verified per-Target MQTTS and signed command dispatch.
// =============================================================
#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "TargetCommandSecurity.h"

namespace sgk {
struct CanonicalEvent;
}

class MqttManager {
private:
    static WiFiClientSecure wifiClient;
    static PubSubClient client;
    static bool connected;

    static void callback(char* topic, byte* payload, unsigned int length);
    static bool publishCommandAck(const sgk::SignedCommandEnvelope& envelope,
                                  sgk::CommandResult result);
    static void dispatchPendingAccessCommand();
    static bool startConnectWorker(const IPAddress& brokerAddress,
                                   uint32_t wifiLinkGeneration);
    static void connectWorkerEntry(void* argument);

public:
    static void init();
    static void update();
    // These coordination hooks never inspect or mutate the transport objects.
    // main can request cooperative cancellation as soon as local access owns
    // the control path; OTA can avoid starting a second TLS client while the
    // MQTT worker is inside a bounded connect phase.
    static void deferForAccessCritical();
    static bool connectionAttemptInProgress();
    // Signed reboot is staged until main has blocked new GATT auth, drained
    // callback work, and re-proved that the physical access path is idle.
    static bool hasPendingRestartRequest();
    static void performPendingRestart();
    // Returns the loop-task-owned, adopted session state. It deliberately does
    // not inspect the TLS/PubSubClient objects while a connect worker owns them.
    static bool isConnected();
    static void publishTelemetry(uint16_t distance_mm, const char* stateStr,
                                 bool is_armed, uint32_t armRemainingMs,
                                 bool relayCommandedOn, int relayPinLevel);
    static void publishEvent(const char* eventType, const char* detail);
    // Queue typed access evidence without touching the TLS socket. The Arduino
    // loop drains this outbox only after the access-critical GATT/sensor/relay
    // phase has finished and no connection worker owns the client.
    static bool enqueueCanonicalEvent(const sgk::CanonicalEvent& event);
    // Update the signed heartbeat fallback without touching the TLS socket.
    static void noteAccessTerminal(const char* sessionId,
                                   uint64_t eventSequence,
                                   const char* eventCode,
                                   const char* reasonCode,
                                   const char* credentialRef,
                                   uint16_t phaseMask);
    // Record only in-memory phase evidence for an already-authorized signed
    // arm/manual command. These methods never touch the MQTT/TLS socket.
    static void noteSignedCommandArmed();
    static void noteSignedCommandSensorDetected();
    static void noteSignedCommandRelayOn();
    static void noteSignedCommandRelayOff(bool failsafe);
    // Returns the allocated terminal sequence, or zero when no signed-command
    // access lifecycle was active. Publication remains deferred to update().
    static uint64_t finishSignedCommandAccess(
        bool failsafe, const char* failureReason = "INTERNAL_ERROR");
    // Persist every volatile access/event record before a controlled restart.
    // This never touches MQTT/TLS and preserves FIFO order relative to records
    // already present in the durable queue. False means at least one RAM
    // record could not be made durable and remains volatile.
    static bool persistPendingEventsForRestart();
    static bool publishCanonicalEvent(const char* payload);
    static void publishConfigState(int txPower, int distanceThresholdCm, uint32_t durationMs, uint32_t relayCooldownMs);
    static void publishSensorInfo(unsigned long duration_us, float distance_cm);
    static void publishBootDiagnostics();

};
