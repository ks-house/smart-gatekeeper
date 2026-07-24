// include/OtaManager.h
// include/MqttManager.h
// =============================================================
// smart-gatekeeper — MQTT 통신 매니저
// 시놀로지 NAS MQTT 브로커(Mosquitto) 연동 및 텔레메트리/원격 제어
// =============================================================
#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

class MqttManager {
private:
    static WiFiClient wifiClient;
    static PubSubClient client;
    static uint32_t lastPublishMs;
    static bool connected;

    static void callback(char* topic, byte* payload, unsigned int length);

public:
    static void init();
    static void update();
    static bool isConnected() { return client.connected(); }
    static void publishTelemetry(uint16_t distance_mm, const char* stateStr);
    static void publishEvent(const char* eventType, const char* detail);
};
