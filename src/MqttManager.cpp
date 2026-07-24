// src/MqttManager.cpp
// =============================================================
// smart-gatekeeper — MqttManager 구현 (Home Assistant Auto-Discovery 포함)
// =============================================================
#include "MqttManager.h"
#include "config.h"
#include "WifiManager.h"
#include "OtaManager.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

extern void triggerManualDoorOpen(); // main.cpp 의 수동 개방 함수 참조

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
        if (String(cmd) == "open_gate" || String(cmd) == "force_open") {
            LOGF("[MQTT-CMD] 원격 출입문 개방 명령 수신!");
            triggerManualDoorOpen();
        } else if (String(cmd) == "ota_update" || String(cmd) == "trigger_ota") {
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

                // Home Assistant MQTT Auto-Discovery 설정 발행
                publishAutoDiscovery();
            } else {
                LOGF("[MQTT-ERROR] 연결 실패 rc=%d", client.state());
            }
        }
    } else {
        client.loop();
    }
}

void MqttManager::publishAutoDiscovery() {
    if (!client.connected()) return;

    LOGF("[MQTT-HA] Home Assistant MQTT Auto-Discovery 엔티티 설정 발행 중...");

    String deviceId = "smart_gatekeeper_01";

    auto createDiscoveryDoc = [&](const char* name, const char* objectId) -> StaticJsonDocument<512> {
        StaticJsonDocument<512> doc;
        doc["name"] = name;
        doc["unique_id"] = deviceId + "_" + objectId;

        JsonObject device = doc.createNestedObject("device");
        JsonArray ids = device.createNestedArray("identifiers");
        ids.add(deviceId);
        device["name"] = "Smart Gatekeeper";
        device["model"] = "ESP32-C6 Door Controller";
        device["manufacturer"] = "KS-House";
        device["sw_version"] = FIRMWARE_VERSION;

        return doc;
    };

    auto pubConfig = [&](const char* component, const char* objectId, StaticJsonDocument<512>& doc) {
        String topic = "homeassistant/" + String(component) + "/" + deviceId + "/" + String(objectId) + "/config";
        String payload;
        serializeJson(doc, payload);
        client.publish(topic.c_str(), payload.c_str(), true); // Retain flag true
    };

    // 1. Buttons (원격 개방, OTA, 재부팅)
    struct ButtonDef { const char* id; const char* name; const char* cmd; const char* icon; };
    ButtonDef buttons[] = {
        {"open_gate", "[Gatekeeper] 출입문 원격 개방", "{\"command\": \"open_gate\"}", "mdi:door-open"},
        {"trigger_ota", "[Gatekeeper] 펌웨어 무선 업데이트 (OTA)", "{\"command\": \"ota_update\"}", "mdi:cloud-download"},
        {"reboot", "[Gatekeeper] 장치 재부팅", "{\"command\": \"reboot\"}", "mdi:restart"}
    };

    for (const auto& b : buttons) {
        StaticJsonDocument<512> doc = createDiscoveryDoc(b.name, b.id);
        doc["command_topic"] = "smart-gatekeeper/cmd";
        doc["payload_press"] = b.cmd;
        doc["icon"]          = b.icon;
        pubConfig("button", b.id, doc);
    }

    // 2. Sensor: ToF 감지 거리
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] ToF 감지 거리", "distance");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.distance_mm }}";
        doc["unit_of_meas"]    = "mm";
        doc["icon"]            = "mdi:ruler";
        pubConfig("sensor", "distance", doc);
    }

    // 3. Sensor: 상태
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 게이트키퍼 동작 상태", "state");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.state }}";
        doc["icon"]            = "mdi:state-machine";
        pubConfig("sensor", "state", doc);
    }

    // 4. Sensor: IP 주소
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] IP 주소", "ip");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.ip }}";
        doc["icon"]            = "mdi:ip-network";
        pubConfig("sensor", "ip", doc);
    }

    // 5. Binary Sensor: 도어 개방 상태
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 도어 개방 여부", "door_binary");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{% if value_json.state == 'RELAY_HOLD' %}ON{% else %}OFF{% endif %}";
        doc["payload_on"]      = "ON";
        doc["payload_off"]     = "OFF";
        doc["device_class"]    = "door";
        pubConfig("binary_sensor", "door_binary", doc);
    }

    LOGF("[MQTT-HA] Auto-Discovery 엔티티 5개 등록 완료!");
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
