// src/MqttManager.cpp
// =============================================================
// smart-gatekeeper — MqttManager 구현 (Home Assistant Auto-Discovery 포함)
// v2.0: gatekeeper/arm Pre-arm 토픽 구독 및 콜백 추가
// =============================================================
#include "MqttManager.h"
#include "config.h"
#include "DiagnosticsManager.h"
#include "WifiManager.h"
#include "OtaManager.h"
#include "TargetAclManager.h"

#include <esp_arduino_version.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

// main.cpp에서 정의된 외부 함수 참조
extern bool triggerManualDoorOpen(); // 원격/MQTT 수동 개방 명령
extern bool triggerArm();            // MQTT gatekeeper/arm 수신 시 Pre-arm 활성화
extern void setTxPower(int powerDbm);
extern void setDistanceThresholdCm(int distanceCm);
extern void setPreArmDurationMs(uint32_t durationMs);

namespace {
constexpr const char* kAvailabilityTopic = "smart-gatekeeper/availability";
uint32_t mqttConnectAttempts = 0;
uint32_t mqttConnectFailures = 0;
int mqttLastError = 0;
}  // namespace


WiFiClientSecure MqttManager::wifiClient;
PubSubClient MqttManager::client(wifiClient);
uint32_t MqttManager::lastPublishMs = 0;
bool MqttManager::connected = false;

void MqttManager::init() {
    wifiClient.setCACert(SECRET_ROOT_CA_CERT); // TLS Root CA 검증 (4883 MQTTS)
    client.setServer(MQTT_HOST, MQTT_PORT);
    client.setBufferSize(2048); // boot diagnostics와 HA discovery payload 수용
    client.setKeepAlive(30);
    client.setSocketTimeout(15); // TLS Handshake 대기 타임아웃 15초로 확장 (rc=-4 방지)
    client.setCallback(callback);
}

void MqttManager::callback(char* topic, byte* payload, unsigned int length) {
    char message[256];

    if (length >= sizeof(message)) length = sizeof(message) - 1;
    memcpy(message, payload, length);
    message[length] = '\0';

    LOGF("[MQTT] 수신 주제: %s | 메시지: %s", topic, message);

    // ─── smart-gatekeeper/target/acl/push — Signed ACL push ───────────────
    if (strcmp(topic, "smart-gatekeeper/target/acl/push") == 0 ||
        strncmp(topic, "gatekeeper/acl/v1/", 18) == 0) {
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
            client.publish("smart-gatekeeper/target/acl/ack", ackBuf);
        } else {
            LOGF("[MQTT-ACL] ⚠️ Signed ACL 적용 거부 (reason code: %u)",
                 static_cast<unsigned int>(res));
        }
        return;
    }

    // ─── gatekeeper/arm — Pre-arm 사전 승인 처리 (v2.0 핵심 신규) ───────
    if (strcmp(topic, MQTT_TOPIC_ARM) == 0) {
        // JSON 페이로드 파싱 시도 ({"action":"arm","user":"홍길동"})
        StaticJsonDocument<256> armDoc;
        bool isArmCommand = false;

        if (!deserializeJson(armDoc, message)) {
            const char* action = armDoc["action"] | "";
            if (strcmp(action, "arm") == 0) {
                const char* user = armDoc["user"] | "unknown";
                LOGF("[MQTT-ARM] ✅ NAS Pre-arm 승인 수신! 사용자: %s → 초음파 활성화 (%lu ms)", user, (unsigned long)PRE_ARM_DURATION_MS);
                isArmCommand = true;
            }
        } else {
            // JSON 파싱 실패 시 단순 문자열 "arm" fallback 처리
            if (strcasecmp(message, "arm") == 0) {
                LOGF("[MQTT-ARM] ✅ Pre-arm 수신 (단순 문자열 'arm') → 초음파 활성화");
                isArmCommand = true;
            }
        }

        if (isArmCommand) {
            DiagnosticsManager::noteAction("mqtt_arm");
            if (triggerArm()) {
                publishEvent("pre_armed", "Ultrasonic sensor activated via MQTT Pre-arm");
            } else {
                publishEvent("arm_rejected", "Target is not IDLE");
            }
        } else {
            LOGF("[MQTT-ARM] ⚠️ arm 토픽 수신되었으나 페이로드 형식 불일치: %s", message);
        }
        return;
    }

    // ─── gatekeeper/force_open — 수동 원격 강제 개방 처리 (v2.0) ─────────
    if (strcmp(topic, "gatekeeper/force_open") == 0) {
        LOGF("[MQTT-FORCE] ✅ 수동 원격 문 열기 수신 → 릴레이 개방 (딸깍!)");
        DiagnosticsManager::noteAction("mqtt_force_open");
        if (triggerManualDoorOpen()) {
            publishEvent("force_opened", "Gate opened via MQTT force_open");
        } else {
            publishEvent("force_open_rejected", "Target is not IDLE");
        }
        return;
    }

    // ─── gatekeeper/config/tx_power — BLE 발신 출력 동적 튜닝 ───────────────
    if (strcmp(topic, MQTT_TOPIC_CONFIG_TX_POWER) == 0) {
        DiagnosticsManager::noteAction("config_tx_power");
        int val = atoi(message);
        LOGF("[MQTT-CONFIG] ⚙️ Tx Power 설정 수신: %d dBm", val);
        setTxPower(val);
        publishEvent("config_tx_power", String(val).c_str());
        return;
    }

    // ─── gatekeeper/config/distance_threshold — 초음파 감지 기준 거리 동적 튜닝 ───
    if (strcmp(topic, MQTT_TOPIC_CONFIG_DISTANCE_THRESH) == 0 || strcmp(topic, MQTT_TOPIC_CONFIG_TOF_DIST) == 0) {
        DiagnosticsManager::noteAction("config_distance");
        int val = atoi(message);
        LOGF("[MQTT-CONFIG] ⚙️ 초음파 감지 기준 거리 설정 수신: %d cm", val);
        setDistanceThresholdCm(val);
        publishEvent("config_distance_threshold", String(val).c_str());
        return;
    }

    // ─── gatekeeper/config/duration — Pre-arm 유효 시간 동적 튜닝 ─────────────
    if (strcmp(topic, MQTT_TOPIC_CONFIG_DURATION) == 0) {
        DiagnosticsManager::noteAction("config_duration");
        int val = atoi(message);
        LOGF("[MQTT-CONFIG] ⚙️ Pre-arm 유효 시간 설정 수신: %d", val);
        uint32_t ms = (val < 1000) ? (uint32_t)(val * 1000) : (uint32_t)val;
        setPreArmDurationMs(ms);
        publishEvent("config_duration", String(ms).c_str());
        return;
    }

    // ─── gatekeeper/config/relay_cooldown — Target 릴레이 쿨다운 동적 튜닝 ─────────
    if (strcmp(topic, "gatekeeper/config/relay_cooldown") == 0) {
        DiagnosticsManager::noteAction("config_relay_cool");
        int val = atoi(message);
        LOGF("[MQTT-CONFIG] ⚙️ Target 릴레이 쿨다운 설정 수신: %d", val);
        uint32_t ms = (val < 100) ? (uint32_t)(val * 1000) : (uint32_t)val;
        extern void setRelayCooldownMs(uint32_t cooldownMs);
        setRelayCooldownMs(ms);
        publishEvent("config_relay_cooldown", String(ms).c_str());
        return;
    }

    // ─── gatekeeper/config/set — 일괄 JSON 설정 수신 ───────────────────────
    if (strcmp(topic, "gatekeeper/config/set") == 0) {
        DiagnosticsManager::noteAction("config_set");
        StaticJsonDocument<256> setDoc;
        if (!deserializeJson(setDoc, message)) {
            LOGF("[MQTT-CONFIG] ⚙️ 일괄 JSON 튜닝 설정 수신: %s", message);
            extern void setRelayCooldownMs(uint32_t cooldownMs);
            if (setDoc.containsKey("tx_power")) setTxPower(setDoc["tx_power"].as<int>());
            if (setDoc.containsKey("distance_threshold")) setDistanceThresholdCm(setDoc["distance_threshold"].as<int>());
            else if (setDoc.containsKey("target_distance")) setDistanceThresholdCm(setDoc["target_distance"].as<int>());
            else if (setDoc.containsKey("tof_distance")) setDistanceThresholdCm(setDoc["tof_distance"].as<int>());
            if (setDoc.containsKey("duration")) setPreArmDurationMs(setDoc["duration"].as<uint32_t>());
            if (setDoc.containsKey("relay_cooldown")) setRelayCooldownMs(setDoc["relay_cooldown"].as<uint32_t>());
        }
        return;
    }

    // ─── gatekeeper/config/get — 설정 상태 요청 수신 ───────────────────────
    if (strcmp(topic, "gatekeeper/config/get") == 0) {
        DiagnosticsManager::noteAction("config_get");
        LOGF("[MQTT-CONFIG] ⚙️ 설정 상태 요청(get) 수신 → 쿼리 응답 전송");
        extern int g_tx_power_dbm;
        extern uint16_t g_distance_threshold_cm;
        extern uint32_t g_pre_arm_duration_ms;
        extern uint32_t g_relay_cooldown_ms;
        publishConfigState(g_tx_power_dbm, g_distance_threshold_cm, g_pre_arm_duration_ms, g_relay_cooldown_ms);
        return;
    }


    // ─── smart-gatekeeper/cmd — 원격 명령 처리 ──────────────────────────
    StaticJsonDocument<256> doc;
    if (deserializeJson(doc, message)) {
        LOGF("[MQTT-ERROR] JSON 파싱 에러");
        return;
    }

    if (String(topic).endsWith("/cmd")) {
        const char* cmd = doc["command"] | "";
        if (strcmp(cmd, "open_gate") == 0 || strcmp(cmd, "force_open") == 0) {
            LOGF("[MQTT-CMD] 원격 출입문 개방 명령 수신!");
            DiagnosticsManager::noteAction("mqtt_cmd_open");
            if (triggerManualDoorOpen()) {
                publishEvent("force_opened", "Gate opened via command topic");
            } else {
                publishEvent("force_open_rejected", "Target is not IDLE");
            }
        } else if (strcmp(cmd, "ota_update") == 0 || strcmp(cmd, "trigger_ota") == 0) {
            LOGF("[MQTT-CMD] 원격 OTA 업데이트 명령 수신!");
            DiagnosticsManager::noteAction("mqtt_cmd_ota");
            OtaManager::checkAndUpdate(true);
        } else if (strcmp(cmd, "reboot") == 0) {
            LOGF("[MQTT-CMD] 원격 재부팅 명령 수신!");
            DiagnosticsManager::markPlannedRestart("mqtt_reboot");
            publishEvent("planned_restart", "mqtt_reboot");
            delay(100);
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
            String clientId =
                "smart-gatekeeper-" + String(DiagnosticsManager::targetId());
            
            static int failCount = 0;
            if (failCount >= 3) {
                LOGF("[MQTT-WARN] ⚠️ TLS 인증서 검증 3회 연속 실패! 보안 무시 모드(setInsecure)로 Fallback 합니다.");
                wifiClient.setInsecure(); // 인증서 만료 및 NTP 오류 무시하고 무조건 암호화 채널 강제 성립
            }

            LOGF("[MQTT-SSL] 브로커 연결 시도 중... (%s:%d)", MQTT_HOST, MQTT_PORT);

            char willPayload[192];
            snprintf(willPayload, sizeof(willPayload),
                     "{\"status\":\"offline\",\"target_id\":\"%s\","
                     "\"boot_id\":\"%s\"}",
                     DiagnosticsManager::targetId(),
                     DiagnosticsManager::bootId());
            mqttConnectAttempts++;

            if (client.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD,
                               kAvailabilityTopic, 1, true, willPayload)) {
                LOGF("[MQTT-SSL] 브로커 연결 성공!");
                failCount = 0; // 성공 시 카운트 초기화
                mqttLastError = 0;
                DiagnosticsManager::noteMqttConnected();

                char onlinePayload[192];
                snprintf(onlinePayload, sizeof(onlinePayload),
                         "{\"status\":\"online\",\"target_id\":\"%s\","
                         "\"boot_id\":\"%s\",\"boot_count\":%lu}",
                         DiagnosticsManager::targetId(),
                         DiagnosticsManager::bootId(),
                         static_cast<unsigned long>(
                             DiagnosticsManager::bootCount()));
                client.publish(kAvailabilityTopic, onlinePayload, true);

                // v2.0 핵심: gatekeeper/arm, gatekeeper/force_open 및 설정 튜닝 토픽 구독
                client.subscribe(MQTT_TOPIC_ARM);
                client.subscribe("gatekeeper/force_open");
                client.subscribe("smart-gatekeeper/cmd");
                client.subscribe("smart-gatekeeper/target/acl/push");
                client.subscribe("gatekeeper/acl/v1/#");
                client.subscribe(MQTT_TOPIC_CONFIG_TX_POWER);
                client.subscribe(MQTT_TOPIC_CONFIG_DISTANCE_THRESH);
                client.subscribe(MQTT_TOPIC_CONFIG_TOF_DIST);
                client.subscribe(MQTT_TOPIC_CONFIG_DURATION);
                client.subscribe("gatekeeper/config/relay_cooldown");
                client.subscribe("gatekeeper/config/set");
                client.subscribe("gatekeeper/config/get");
                LOGF("[MQTT] 토픽 구독 완료: %s, gatekeeper/force_open, gatekeeper/config/#", MQTT_TOPIC_ARM);

                publishBootDiagnostics();
                publishEvent("connected", "ESP32-C6 v2.1 Online (SSL) — AJ-SR04T Ultrasonic Sensor");
                publishAutoDiscovery();

                extern int g_tx_power_dbm;
                extern uint16_t g_distance_threshold_cm;
                extern uint32_t g_pre_arm_duration_ms;
                extern uint32_t g_relay_cooldown_ms;
                publishConfigState(g_tx_power_dbm, g_distance_threshold_cm, g_pre_arm_duration_ms, g_relay_cooldown_ms);
                return;
            } else {
                failCount++;
                mqttConnectFailures++;
                mqttLastError = client.state();
                LOGF("[MQTT-ERROR] 연결 실패 rc=%d (TLS 소켓 리셋, 누적 실패: %d회)", client.state(), failCount);
                wifiClient.stop(); // 이전 소켓 핸들 및 SSL 핸드셰이크 찌꺼기 강제 정돈
            }
        }
    } else {
        client.loop();
    }
}

void MqttManager::publishBootDiagnostics() {
    if (!isConnected()) return;

    StaticJsonDocument<1536> doc;
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
    doc["wifi_bssid"] = WiFi.BSSIDstr();
    doc["wifi_channel"] = WiFi.channel();
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["free_heap"] = ESP.getFreeHeap();
    doc["min_free_heap"] = ESP.getMinFreeHeap();
    doc["largest_free_block"] = ESP.getMaxAllocHeap();
    doc["loop_stack_hwm"] = uxTaskGetStackHighWaterMark(nullptr);
    doc["mqtt_connect_attempts"] = mqttConnectAttempts;
    doc["mqtt_connect_failures"] = mqttConnectFailures;
    doc["mqtt_last_error"] = mqttLastError;

    char buffer[1536];
    size_t length = serializeJson(doc, buffer, sizeof(buffer));
    bool ok = length > 0 &&
              client.publish("smart-gatekeeper/boot", buffer, true);
    LOGF("[MQTT-DIAG] retained boot diagnostics publish: %s (%u bytes)",
         ok ? "OK" : "FAIL", static_cast<unsigned int>(length));
}

void MqttManager::publishConfigState(int txPower, int distanceThresholdCm, uint32_t durationMs, uint32_t relayCooldownMs) {
    if (!isConnected()) return;

    StaticJsonDocument<256> doc;
    doc["tx_power"] = txPower;
    doc["distance_threshold_cm"] = distanceThresholdCm;
    doc["tof_distance_cm"] = distanceThresholdCm; // 호환용 하위 별칭
    doc["duration_ms"] = durationMs;
    doc["relay_cooldown_ms"] = relayCooldownMs;
    doc["status"] = "applied_nvs";

    char buffer[256];
    serializeJson(doc, buffer);
    client.publish("gatekeeper/config/state", buffer, true); // Retained = true
    LOGF("[MQTT-CONFIG] 📡 Retained Config State 발행 완료: %s", buffer);
}




void MqttManager::publishAutoDiscovery() {
    if (!isConnected()) return;

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
        device["model"] = "ESP32-C6 Door Controller v2.1";
        device["manufacturer"] = "KS-House";
        device["sw_version"] = FIRMWARE_VERSION;

        return doc;
    };

    auto pubConfig = [&](const char* component, const char* objectId, StaticJsonDocument<512>& doc) {
        if (!isConnected()) return;
        char topic[128];
        snprintf(topic, sizeof(topic), "homeassistant/%s/%s/%s/config", component, deviceId.c_str(), objectId);
        
        char payload[512];
        serializeJson(doc, payload, sizeof(payload));
        
        bool ok = client.publish(topic, payload, true); // Retain flag true
        LOGF("[MQTT-HA] Auto-Discovery [%s] %s -> %s", component, objectId, ok ? "성공(OK)" : "실패(FAIL)");

        // ESP32-C6 TLS 소켓 버퍼 폭발 방지를 위한 딜레이
        vTaskDelay(pdMS_TO_TICKS(50)); 
    };

    // ─── 1. Buttons (원격 개방, OTA, 재부팅) ───────────────────────
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

    // ─── 2. Sensors: 실시간 측정 및 진단 센서 ────────────────────────
    // 2-1. Sensor: ToF/초음파 감지 거리 (mm)
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 초음파 감지 거리 (mm)", "distance");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.distance_mm }}";
        doc["unit_of_meas"]    = "mm";
        doc["icon"]            = "mdi:ruler";
        pubConfig("sensor", "distance", doc);
    }

    // 2-2. Sensor: ToF/초음파 감지 거리 (cm)
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 초음파 감지 거리 (cm)", "distance_cm");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.distance_cm }}";
        doc["unit_of_meas"]    = "cm";
        doc["icon"]            = "mdi:ruler-square";
        pubConfig("sensor", "distance_cm", doc);
    }

    // 2-3. Sensor: 동작 상태
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 게이트키퍼 동작 상태", "state");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.state }}";
        doc["icon"]            = "mdi:state-machine";
        pubConfig("sensor", "state", doc);
    }

    // 2-4. Sensor: IP 주소
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] IP 주소", "ip");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.ip }}";
        doc["icon"]            = "mdi:ip-network";
        pubConfig("sensor", "ip", doc);
    }

    // 2-5. Sensor: Pre-arm 잔여 유효 시간
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] Pre-arm 잔여 시간", "arm_remaining_s");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.arm_remaining_s }}";
        doc["unit_of_meas"]    = "s";
        doc["icon"]            = "mdi:timer-outline";
        pubConfig("sensor", "arm_remaining_s", doc);
    }

    // 2-6. Sensor [진단]: Wi-Fi RSSI
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] Wi-Fi 신호 강도 (RSSI)", "wifi_rssi");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.wifi_rssi }}";
        doc["unit_of_meas"]    = "dBm";
        doc["device_class"]    = "signal_strength";
        doc["entity_category"] = "diagnostic";
        doc["icon"]            = "mdi:wifi";
        pubConfig("sensor", "wifi_rssi", doc);
    }

    // 2-7. Sensor [진단]: Free Heap 메모리
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] Free Heap 메모리", "free_heap");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.free_heap }}";
        doc["unit_of_meas"]    = "B";
        doc["entity_category"] = "diagnostic";
        doc["icon"]            = "mdi:memory";
        pubConfig("sensor", "free_heap", doc);
    }

    // 2-8. Sensor [진단]: 시스템 업타임
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 시스템 가동 시간", "uptime_s");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.uptime_s }}";
        doc["unit_of_meas"]    = "s";
        doc["device_class"]    = "duration";
        doc["entity_category"] = "diagnostic";
        doc["icon"]            = "mdi:clock-outline";
        pubConfig("sensor", "uptime_s", doc);
    }

    // 2-9. Sensor [진단]: 펌웨어 버전
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 펌웨어 버전", "firmware");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{{ value_json.firmware }}";
        doc["entity_category"] = "diagnostic";
        doc["icon"]            = "mdi:information-outline";
        pubConfig("sensor", "firmware", doc);
    }

    // ─── 3. Binary Sensors ─────────────────────────────────────────
    // 3-1. Binary Sensor: 도어 개방 상태
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 도어 개방 여부", "door_binary");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{% if value_json.state == 'RELAY_HOLD' %}ON{% else %}OFF{% endif %}";
        doc["payload_on"]      = "ON";
        doc["payload_off"]     = "OFF";
        doc["device_class"]    = "door";
        pubConfig("binary_sensor", "door_binary", doc);
    }

    // 3-2. Binary Sensor: Pre-arm 활성화 여부
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] Pre-arm 활성화 상태", "pre_armed");
        doc["state_topic"]     = "smart-gatekeeper/status";
        doc["value_template"]  = "{% if value_json.is_armed %}ON{% else %}OFF{% endif %}";
        doc["payload_on"]      = "ON";
        doc["payload_off"]     = "OFF";
        doc["device_class"]    = "lock";
        doc["icon"]            = "mdi:shield-check";
        pubConfig("binary_sensor", "pre_armed", doc);
    }

    // ─── 4. Numbers: 동적 설정값 제어 엔티티 (HA 대시보드 조작) ─────────────
    // 4-1. Number: BLE Tx Power (-6 ~ 9 dBm)
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] BLE Tx Power 설정", "config_tx_power_num");
        doc["command_topic"]   = MQTT_TOPIC_CONFIG_TX_POWER;
        doc["state_topic"]     = "gatekeeper/config/state";
        doc["value_template"]  = "{{ value_json.tx_power }}";
        doc["min"]             = -6;
        doc["max"]             = 9;
        doc["step"]            = 3;
        doc["unit_of_meas"]    = "dBm";
        doc["icon"]            = "mdi:bluetooth";
        pubConfig("number", "config_tx_power_num", doc);
    }

    // 4-2. Number: 초음파 감지 기준 거리 (20 ~ 200 cm)
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 초음파 감지 기준 거리", "config_dist_thresh_num");
        doc["command_topic"]   = MQTT_TOPIC_CONFIG_DISTANCE_THRESH;
        doc["state_topic"]     = "gatekeeper/config/state";
        doc["value_template"]  = "{{ value_json.distance_threshold_cm }}";
        doc["min"]             = 20;
        doc["max"]             = 200;
        doc["step"]            = 1;
        doc["unit_of_meas"]    = "cm";
        doc["icon"]            = "mdi:ruler-square";
        pubConfig("number", "config_dist_thresh_num", doc);
    }

    // 4-3. Number: Pre-arm 유효 시간 (5 ~ 300 초)
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] Pre-arm 유효 시간", "config_duration_num");
        doc["command_topic"]   = MQTT_TOPIC_CONFIG_DURATION;
        doc["state_topic"]     = "gatekeeper/config/state";
        doc["value_template"]  = "{{ (value_json.duration_ms / 1000) | int }}";
        doc["min"]             = 5;
        doc["max"]             = 300;
        doc["step"]            = 5;
        doc["unit_of_meas"]    = "s";
        doc["icon"]            = "mdi:timer-sand";
        pubConfig("number", "config_duration_num", doc);
    }

    // 4-4. Number: Target 릴레이 쿨다운 시간 (1 ~ 30 초)
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] 릴레이 쿨다운 시간", "config_relay_cooldown_num");
        doc["command_topic"]   = "gatekeeper/config/relay_cooldown";
        doc["state_topic"]     = "gatekeeper/config/state";
        doc["value_template"]  = "{{ (value_json.relay_cooldown_ms / 1000) | int }}";
        doc["min"]             = 1;
        doc["max"]             = 30;
        doc["step"]            = 1;
        doc["unit_of_meas"]    = "s";
        doc["icon"]            = "mdi:snowflake-alert";
        pubConfig("number", "config_relay_cooldown_num", doc);
    }

    // ─── 5. Configuration State Sensors: 저장된 설정값 조회 ─────────────
    // 5-1. Config Sensor: BLE Tx Power
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] [설정] BLE Tx Power", "cfg_tx_power");
        doc["state_topic"]     = "gatekeeper/config/state";
        doc["value_template"]  = "{{ value_json.tx_power }}";
        doc["unit_of_meas"]    = "dBm";
        doc["entity_category"] = "diagnostic";
        doc["icon"]            = "mdi:bluetooth-settings";
        pubConfig("sensor", "cfg_tx_power", doc);
    }

    // 5-2. Config Sensor: 초음파 감지 기준 거리
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] [설정] 초음파 감지 기준 거리", "cfg_distance_thresh");
        doc["state_topic"]     = "gatekeeper/config/state";
        doc["value_template"]  = "{{ value_json.distance_threshold_cm }}";
        doc["unit_of_meas"]    = "cm";
        doc["entity_category"] = "diagnostic";
        doc["icon"]            = "mdi:tune-vertical";
        pubConfig("sensor", "cfg_distance_thresh", doc);
    }

    // 5-3. Config Sensor: Pre-arm 유효 시간
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] [설정] Pre-arm 유효 시간", "cfg_prearm_duration");
        doc["state_topic"]     = "gatekeeper/config/state";
        doc["value_template"]  = "{{ (value_json.duration_ms / 1000) | int }}";
        doc["unit_of_meas"]    = "s";
        doc["entity_category"] = "diagnostic";
        doc["icon"]            = "mdi:clock-edit-outline";
        pubConfig("sensor", "cfg_prearm_duration", doc);
    }

    // 5-4. Config Sensor: 릴레이 쿨다운 시간
    {
        StaticJsonDocument<512> doc = createDiscoveryDoc("[Gatekeeper] [설정] 릴레이 쿨다운 시간", "cfg_relay_cooldown");
        doc["state_topic"]     = "gatekeeper/config/state";
        doc["value_template"]  = "{{ (value_json.relay_cooldown_ms / 1000) | int }}";
        doc["unit_of_meas"]    = "s";
        doc["entity_category"] = "diagnostic";
        doc["icon"]            = "mdi:timer-cog-outline";
        pubConfig("sensor", "cfg_relay_cooldown", doc);
    }

    LOGF("[MQTT-HA] Auto-Discovery 엔티티 22개 자동 등록 완료!");
    
    // Auto-Discovery 발행 직후 TLS SSL 송신 버퍼 안정화를 위한 소켓 플러시
    for (int i = 0; i < 3; i++) {
        if (isConnected()) client.loop();
        delay(10);
    }
}

void MqttManager::publishTelemetry(uint16_t distance_mm,
                                   const char* stateStr,
                                   bool is_armed,
                                   uint32_t armRemainingMs,
                                   bool relayCommandedOn,
                                   int relayPinLevel) {
    if (!isConnected()) return;

    StaticJsonDocument<1536> doc;
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
    doc["target_id"]       = DiagnosticsManager::targetId();
    doc["boot_id"]         = DiagnosticsManager::bootId();
    doc["boot_count"]      = DiagnosticsManager::bootCount();
    doc["reset_reason"]    = DiagnosticsManager::resetReason();
    doc["relay_commanded_on"] = relayCommandedOn;
    doc["relay_pin_level"] = relayPinLevel;
    doc["min_free_heap"]   = ESP.getMinFreeHeap();
    doc["largest_free_block"] = ESP.getMaxAllocHeap();
    doc["loop_stack_hwm"]  = uxTaskGetStackHighWaterMark(nullptr);
    doc["wifi_bssid"]      = WiFi.BSSIDstr();
    doc["wifi_channel"]    = WiFi.channel();
    doc["mqtt_connect_count"] =
        DiagnosticsManager::mqttConnectCount();
    doc["mqtt_connect_attempts"] = mqttConnectAttempts;
    doc["mqtt_connect_failures"] = mqttConnectFailures;

    char buf[1536];
    serializeJson(doc, buf, sizeof(buf));

    if (isConnected()) {
        client.publish("smart-gatekeeper/status", buf);
    }
}

void MqttManager::publishEvent(const char* eventType, const char* detail) {
    if (!isConnected()) return;
    if (!eventType) return;

    StaticJsonDocument<384> doc;
    doc["event"]  = eventType;
    doc["detail"] = detail ? detail : "";
    doc["time"]   = millis();
    doc["target_id"] = DiagnosticsManager::targetId();
    doc["boot_id"] = DiagnosticsManager::bootId();
    doc["boot_count"] = DiagnosticsManager::bootCount();

    char buf[384];
    serializeJson(doc, buf, sizeof(buf));

    if (isConnected()) {
        client.publish("smart-gatekeeper/event", buf);
    }
}

bool MqttManager::publishCanonicalEvent(const char* payload) {
    if (payload == nullptr || !client.connected()) return false;
    return client.publish("smart-gatekeeper/canonical-event", payload, false);
}

void MqttManager::publishSensorInfo(unsigned long duration_us, float distance_cm) {
    if (!isConnected()) return;

    StaticJsonDocument<256> doc;
    doc["duration_us"] = duration_us;
    doc["distance_cm"] = distance_cm;

    char buf[256];
    serializeJson(doc, buf, sizeof(buf));

    if (isConnected()) {
        client.publish("smart-gatekeeper/sensor/ultrasonic", buf);
    }
}
