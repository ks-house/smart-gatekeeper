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
    static uint32_t lastPublishMs;
    static bool connected;

    static void callback(char* topic, byte* payload, unsigned int length);
    static void publishCommandAck(const sgk::SignedCommandEnvelope& envelope,
                                  sgk::CommandResult result);

public:
    static void init();
    static void update();
    static bool isConnected() { return wifiClient.connected() && client.connected(); }
    static void publishTelemetry(uint16_t distance_mm, const char* stateStr,
                                 bool is_armed, uint32_t armRemainingMs,
                                 bool relayCommandedOn, int relayPinLevel);
    static void publishEvent(const char* eventType, const char* detail);
    // Queue typed access evidence without touching the TLS socket. The Arduino
    // loop remains the sole PubSubClient owner and drains this outbox only after
    // the access-critical GATT/sensor/relay phase has finished.
    static bool enqueueCanonicalEvent(const sgk::CanonicalEvent& event);
    // Update the signed heartbeat fallback without touching the TLS socket.
    static void noteAccessTerminal(const char* sessionId,
                                   uint64_t eventSequence,
                                   const char* eventCode,
                                   const char* reasonCode,
                                   const char* credentialRef,
                                   uint16_t phaseMask);
    static bool publishCanonicalEvent(const char* payload);
    static void publishConfigState(int txPower, int distanceThresholdCm, uint32_t durationMs, uint32_t relayCooldownMs);
    static void publishSensorInfo(unsigned long duration_us, float distance_cm);
    static void publishBootDiagnostics();

};
