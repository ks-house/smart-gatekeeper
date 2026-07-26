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

    // NVS 영구 저장 튜닝 파라미터 (Tx Power, ToF 거리, Pre-arm 유효시간, 릴레이 쿨다운)
    static int getTxPower(int defaultVal = 9);
    static int getTofDistanceCm(int defaultVal = 50);
    static uint32_t getPreArmDurationMs(uint32_t defaultVal = 60000);
    static uint32_t getRelayCooldownMs(uint32_t defaultVal = 3000);

    static void setWifiCredentials(const String& ssid, const String& password);
    static void setApiCredentials(const String& url, const String& key);
    static void setTxPower(int powerDbm);
    static void setTofDistanceCm(int distanceCm);
    static void setPreArmDurationMs(uint32_t durationMs);
    static void setRelayCooldownMs(uint32_t cooldownMs);
    static void clearConfig();

};

