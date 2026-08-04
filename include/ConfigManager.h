// include/ConfigManager.h
// =============================================================
// smart-gatekeeper — NVS (Preferences) 설정 관리 모듈
// Wi-Fi 접속 정보 및 API 설정을 ESP32-C6 NVS 플래시에 영구 저장
// =============================================================
#pragma once

#include <array>
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

    // NVS 영구 저장 튜닝 파라미터 (Tx Power, 초음파 감지 기준 거리, Pre-arm 유효시간, 릴레이 쿨다운)
    static int getTxPower(int defaultVal = 9);
    static int getDistanceThresholdCm(int defaultVal = 50);
    static int getTofDistanceCm(int defaultVal = 50); // 하위 호환용 별칭
    static uint32_t getPreArmDurationMs(uint32_t defaultVal = 60000);
    static uint32_t getRelayCooldownMs(uint32_t defaultVal = 3000);
    static bool getHardwarelessRcEnabled(bool defaultVal = false);
    static bool getHardwarelessDoorId(std::array<uint8_t, 16>* doorId);
    static String getAclSignerPublicKeyHex();
    static uint32_t getAclSigningKeyId(uint32_t defaultVal = 0);
    static uint32_t incrementBootCount();
    static String consumePlannedRestartReason();

    static void setWifiCredentials(const String& ssid, const String& password);
    static void setApiCredentials(const String& url, const String& key);
    static void setTxPower(int powerDbm);
    static void setDistanceThresholdCm(int distanceCm);
    static void setTofDistanceCm(int distanceCm); // 하위 호환용 별칭
    static void setPreArmDurationMs(uint32_t durationMs);
    static void setRelayCooldownMs(uint32_t cooldownMs);
    static void setHardwarelessRcEnabled(bool enabled);
    static bool setHardwarelessDoorIdHex(const String& doorIdHex);
    static void setPlannedRestartReason(const char* reason);
    static void clearConfig();


};
