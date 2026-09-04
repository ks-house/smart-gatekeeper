// src/WifiManager.h
// =============================================================
// smart-gatekeeper — Wi-Fi 매니저 헤더
// 캡티브 포털(Captive Portal) 및 주변 AP 스캔/웹 등록 모듈
// =============================================================
#pragma once

#include <WiFi.h>
#include <WebServer.h>
#include "ConfigManager.h"

class WifiManager {
private:
    static WebServer webServer;
    static bool apModeActive;
    static bool connected;
    static String stationIp;
    static uint32_t recoveryApDeadlineMs;

    static void handleRoot();
    static void handleScan();
    static void handleSave();
    static void handleConfigSave();
    static void handleRecoveryManifest();
    static void handleRecoveryUpload();
    static void handleRecoveryUploadComplete();
    static void handleRecoveryApEnable();
    static void handleNotFound();
    static bool requireLocalAuthentication();
    static bool startRecoveryAP(bool preserveStation, uint32_t durationMs);

public:
    static void init();
    static bool connectSTA(uint32_t timeoutMs = 12000);
    static void startAP();
    static void startWebServer();
    // Observation is side-effect free with respect to the Wi-Fi radio and is
    // safe during GATT/sensor/relay work. Recovery mutation is serviced only
    // by the caller after the access-critical guard has cleared.
    static void observeConnectivity(uint32_t nowMs);
    static void serviceRecovery(uint32_t nowMs);
    static void handleClient();
    static bool isConnected();
    static bool isAPMode();
    static String getIP();
    // Monotonic driver-edge generation. Unlike the loop-observed outage
    // counter, this advances even when STA disconnect+reconnect completes
    // while loopTask is busy in another bounded operation.
    static uint32_t linkGeneration();
    static uint32_t outageCount();
    static uint32_t recoveryEscalationCount();
    static uint32_t recoveryApStartFailureCount();
    static uint32_t recoverySuccessCount();
    static uint32_t currentOutageMs();
    static uint32_t lastOutageMs();
    // Internal recovery-radio transitions never replace this value; it is the
    // most recent driver disconnect not initiated by WifiManager itself.
    static uint32_t lastUnplannedDisconnectReason();
    static const char* recoveryPhase();
};
