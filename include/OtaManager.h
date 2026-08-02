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

#include "TargetState.h"

class OtaManager {
public:
    using SafeStateProvider = OtaSafeState (*)();

    enum class OtaStatus {
        IDLE,
        WAIT_SAFE_STATE,
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
    static SafeStateProvider safeStateProvider;

public:
    static void init();
    static void setSafeStateProvider(SafeStateProvider provider);
    static void checkAndUpdate(bool force = false);
    static OtaStatus getStatus() { return status; }
    static String getLastError() { return lastError; }
};
