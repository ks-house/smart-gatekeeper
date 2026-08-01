// src/ConfigManager.cpp
// =============================================================
// smart-gatekeeper — ConfigManager 구현
// v2.0: BLE RSSI 임계값 관련 함수 제거 (BLE Advertiser 모드로 전환)
// =============================================================
#include "ConfigManager.h"
#include "config.h"

Preferences ConfigManager::preferences;
static bool configManagerInitialized = false;

void ConfigManager::begin() {
    if (configManagerInitialized) {
        return;
    }

    preferences.begin("gatekeeper", false);
    configManagerInitialized = true;

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

int ConfigManager::getDistanceThresholdCm(int defaultVal) {
    if (preferences.isKey("dist_thresh")) {
        return preferences.getInt("dist_thresh", defaultVal);
    }
    return preferences.getInt("tof_dist", defaultVal);
}

int ConfigManager::getTofDistanceCm(int defaultVal) {
    return getDistanceThresholdCm(defaultVal);
}

uint32_t ConfigManager::getPreArmDurationMs(uint32_t defaultVal) {
    return preferences.getUInt("prearm_dur", defaultVal);
}

uint32_t ConfigManager::getRelayCooldownMs(uint32_t defaultVal) {
    return preferences.getUInt("relay_cool", defaultVal);
}

bool ConfigManager::getHardwarelessRcEnabled(bool defaultVal) {
    return preferences.getBool("hwless_rc", defaultVal);
}

uint32_t ConfigManager::incrementBootCount() {
    uint32_t count = preferences.getUInt("boot_count", 0) + 1;
    preferences.putUInt("boot_count", count);
    return count;
}

String ConfigManager::consumePlannedRestartReason() {
    String reason = preferences.getString("next_restart", "");
    if (preferences.isKey("next_restart")) {
        preferences.remove("next_restart");
    }
    return reason;
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

void ConfigManager::setDistanceThresholdCm(int distanceCm) {
    preferences.putInt("dist_thresh", distanceCm);
    preferences.putInt("tof_dist", distanceCm);
}

void ConfigManager::setTofDistanceCm(int distanceCm) {
    setDistanceThresholdCm(distanceCm);
}


void ConfigManager::setPreArmDurationMs(uint32_t durationMs) {
    preferences.putUInt("prearm_dur", durationMs);
}

void ConfigManager::setRelayCooldownMs(uint32_t cooldownMs) {
    preferences.putUInt("relay_cool", cooldownMs);
}

void ConfigManager::setHardwarelessRcEnabled(bool enabled) {
    preferences.putBool("hwless_rc", enabled);
}

void ConfigManager::setPlannedRestartReason(const char* reason) {
    preferences.putString("next_restart", reason ? reason : "unspecified");
}

void ConfigManager::clearConfig() {

    preferences.clear();
}
