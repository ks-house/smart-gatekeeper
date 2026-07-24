// include/OtaManager.h
// =============================================================
// smart-gatekeeper — OTA (Over-The-Air) 업데이트 매니저
// 시놀로지 NAS에 GitHub CI로 배포된 version.json 및 firmware.bin 수신/업데이트
// =============================================================
#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <HTTPUpdate.h>
#include <ArduinoJson.h>

class OtaManager {
public:
    enum class OtaStatus {
        IDLE,
        CHECKING,
        UP_TO_DATE,
        UPDATING,
        SUCCESS,
        FAILED
    };

private:
    static OtaStatus status;
    static String lastError;
    static uint32_t lastCheckMs;

public:
    static void init();
    static void checkAndUpdate(bool force = false);
    static OtaStatus getStatus() { return status; }
    static String getLastError() { return lastError; }
};
