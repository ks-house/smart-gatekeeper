// include/ConfigManager.h
// =============================================================
// smart-gatekeeper — NVS (Preferences) 설정 관리 모듈
// Wi-Fi 접속 정보 및 API 설정을 ESP32-C6 NVS 플래시에 영구 저장
// =============================================================
#pragma once

#include <Arduino.h>
#include <Preferences.h>

class ConfigManager {
private:
    static Preferences preferences;

public:
    static void begin();
    static String getWifiSsid();
    static String getWifiPassword();
    static String getApiUrl();
    static String getApiKey();

    static int getBleRssiThreshold();
    static void setBleRssiThreshold(int rssi);

    static void setWifiCredentials(const String& ssid, const String& password);
    static void setApiCredentials(const String& url, const String& key);
    static void clearConfig();
};
