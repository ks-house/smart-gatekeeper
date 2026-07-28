// include/MqttManager.h
// =============================================================
// smart-gatekeeper — MQTT 통신 매니저 (HA Auto-Discovery 지원)
// v2.0: gatekeeper/arm Pre-arm 토픽 구독 추가
// =============================================================
#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

class MqttManager {
private:
    static WiFiClientSecure wifiClient;
    static PubSubClient client;
    static uint32_t lastPublishMs;
    static bool connected;

    static void callback(char* topic, byte* payload, unsigned int length);

public:
    static void init();
    static void update();
    static bool isConnected() { return wifiClient.connected() && client.connected(); }
    static void publishTelemetry(uint16_t distance_mm, const char* stateStr, bool is_armed);
    static void publishEvent(const char* eventType, const char* detail);
    static void publishConfigState(int txPower, int distanceThresholdCm, uint32_t durationMs, uint32_t relayCooldownMs);
    static void publishSensorInfo(unsigned long duration_us, float distance_cm);

    static void publishAutoDiscovery(); // Home Assistant MQTT Auto-Discovery
};

