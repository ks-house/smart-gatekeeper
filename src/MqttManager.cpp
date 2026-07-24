// src/MqttManager.cpp
// =============================================================
// smart-gatekeeper — MqttManager 구현 (SSL/TLS 4883 포트 지원)
// =============================================================
#include "MqttManager.h"
#include "config.h"
#include "WifiManager.h"
#include "OtaManager.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

WiFiClientSecure MqttManager::wifiClient;
PubSubClient MqttManager::client(wifiClient);
uint32_t MqttManager::lastPublishMs = 0;
bool MqttManager::connected = false;

void MqttManager::init() {
    wifiClient.setCACert(SECRET_ROOT_CA_CERT); // TLS Root CA 검증 (4883 MQTTS)
    client.setServer(MQTT_HOST, MQTT_PORT);
    client.setCallback(callback);
}

void MqttManager::callback(char* topic, byte* payload, unsigned int length) {
    char message[256];
    if (length >= sizeof(message)) length = sizeof(message) - 1;
    memcpy(message, payload, length);
    message[length] = '\0';

    LOGF("[MQTT] 수신 주제: %s | 메시지: %s", topic, message);

    StaticJsonDocument<256> doc;
    if (deserializeJson(doc, message)) {
        LOGF("[MQTT-ERROR] JSON 파싱 에러");
        return;
    }

    if (String(topic).endsWith("/cmd")) {
        const char* cmd = doc["command"] | "";
        if (String(cmd) == "ota_update") {
            LOGF("[MQTT-CMD] 원격 OTA 업데이트 명령 수신!");
            OtaManager::checkAndUpdate(true);
        } else if (String(cmd) == "reboot") {
            LOGF("[MQTT-CMD] 원격 재부팅 명령 수신!");
            ESP.restart();
        }
    }
}

void MqttManager::update() {
    if (!WifiManager::isConnected()) return;

    if (!client.connected()) {
        uint32_t now = millis();
        if (now - lastPublishMs > 5000) {
            lastPublishMs = now;
            String clientId = "smart-gatekeeper-" + String((uint32_t)ESP.getEfuseMac(), HEX);
            LOGF("[MQTT-SSL] 브로커 연결 시도 중... (%s:%d)", MQTT_HOST, MQTT_PORT);

            if (client.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD)) {
                LOGF("[MQTT-SSL] 브로커 연결 성공!");
                client.subscribe("smart-gatekeeper/cmd");
                publishEvent("connected", "ESP32-C6 Online (SSL)");
            } else {
                LOGF("[MQTT-ERROR] 연결 실패 rc=%d", client.state());
            }
        }
    } else {
        client.loop();
    }
}

void MqttManager::publishTelemetry(uint16_t distance_mm, const char* stateStr) {
    if (!client.connected()) return;

    StaticJsonDocument<256> doc;
    doc["distance_mm"] = distance_mm;
    doc["state"]       = stateStr;
    doc["ip"]          = WifiManager::getIP();
    doc["free_heap"]   = ESP.getFreeHeap();

    String jsonStr;
    serializeJson(doc, jsonStr);

    client.publish("smart-gatekeeper/status", jsonStr.c_str());
}

void MqttManager::publishEvent(const char* eventType, const char* detail) {
    if (!client.connected()) return;

    StaticJsonDocument<256> doc;
    doc["event"]  = eventType;
    doc["detail"] = detail;
    doc["time"]   = millis();

    String jsonStr;
    serializeJson(doc, jsonStr);

    client.publish("smart-gatekeeper/event", jsonStr.c_str());
}
