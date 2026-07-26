// src/ConfigManager.cpp
// =============================================================
// smart-gatekeeper — ConfigManager 구현
// v2.0: BLE RSSI 임계값 관련 함수 제거 (BLE Advertiser 모드로 전환)
// =============================================================
#include "ConfigManager.h"
#include "config.h"

Preferences ConfigManager::preferences;

void ConfigManager::begin() {
    preferences.begin("gatekeeper", false);

    // 기본값이 NVS에 없는 경우 기본 상수로 초기 세팅
    if (!preferences.isKey("api_url")) {
        preferences.putString("api_url", API_URL);
    }
    if (!preferences.isKey("api_key")) {
        preferences.putString("api_key", API_KEY);
    }
}

String ConfigManager::getWifiSsid() {
    return preferences.getString("ssid", WIFI_SSID);
}

String ConfigManager::getWifiPassword() {
    return preferences.getString("pass", WIFI_PASSWORD);
}

String ConfigManager::getApiUrl() {
    return preferences.getString("api_url", API_URL);
}

String ConfigManager::getApiKey() {
    return preferences.getString("api_key", API_KEY);
}

int ConfigManager::getTxPower(int defaultVal) {
    return preferences.getInt("tx_pwr", defaultVal);
}

int ConfigManager::getTofDistanceCm(int defaultVal) {
    return preferences.getInt("tof_dist", defaultVal);
}

uint32_t ConfigManager::getPreArmDurationMs(uint32_t defaultVal) {
    return preferences.getUInt("prearm_dur", defaultVal);
}


void ConfigManager::setWifiCredentials(const String& ssid, const String& password) {
    preferences.putString("ssid", ssid);
    preferences.putString("pass", password);
}

void ConfigManager::setApiCredentials(const String& url, const String& key) {
    preferences.putString("api_url", url);
    preferences.putString("api_key", key);
}

void ConfigManager::setTxPower(int powerDbm) {
    preferences.putInt("tx_pwr", powerDbm);
}

void ConfigManager::setTofDistanceCm(int distanceCm) {
    preferences.putInt("tof_dist", distanceCm);
}

void ConfigManager::setPreArmDurationMs(uint32_t durationMs) {
    preferences.putUInt("prearm_dur", durationMs);
}

void ConfigManager::clearConfig() {
    preferences.clear();
}

