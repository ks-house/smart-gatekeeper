// src/WifiManager.h
// =============================================================
// smart-gatekeeper — Wi-Fi 매니저 헤더
// 캡티브 포털(Captive Portal) 및 주변 AP 스캔/웹 등록 모듈
// =============================================================
#pragma once

#include <WiFi.h>
#include <DNSServer.h>
#include <WebServer.h>
#include "ConfigManager.h"

class WifiManager {
private:
    static DNSServer dnsServer;
    static WebServer webServer;
    static bool apModeActive;
    static bool connected;
    static String stationIp;

    static void handleRoot();
    static void handleScan();
    static void handleSave();
    static void handleNotFound();

public:
    static void init();
    static bool connectSTA(uint32_t timeoutMs = 12000);
    static void startAP();
    static void handleClient();
    static bool isConnected();
    static bool isAPMode();
    static String getIP();
};
