// src/OtaManager.cpp
// =============================================================
// smart-gatekeeper — OtaManager 구현
// =============================================================
#include "OtaManager.h"
#include "config.h"
#include "WifiManager.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

OtaManager::OtaStatus OtaManager::status = OtaManager::OtaStatus::IDLE;
String OtaManager::lastError = "";
uint32_t OtaManager::lastCheckMs = 0;

void OtaManager::init() {
    status = OtaStatus::IDLE;
}

void OtaManager::checkAndUpdate(bool force) {
    if (!WifiManager::isConnected()) {
        LOGF("[OTA] Wi-Fi 미연결로 OTA 확인 취소");
        return;
    }

    status = OtaStatus::CHECKING;
    LOGF("[OTA] 펌웨어 버전 체크 중... (%s)", OTA_VERSION_URL);

    WiFiClientSecure client;
    client.setInsecure();

    HTTPClient http;
    if (!http.begin(client, OTA_VERSION_URL)) {
        status = OtaStatus::FAILED;
        lastError = "URL begin failed";
        LOGF("[OTA-ERROR] %s", lastError.c_str());
        return;
    }

    http.setTimeout(6000);
    int httpCode = http.GET();

    if (httpCode != HTTP_CODE_OK) {
        status = OtaStatus::FAILED;
        lastError = "HTTP error: " + String(httpCode);
        LOGF("[OTA-ERROR] version.json GET 실패 Code: %d", httpCode);
        http.end();
        return;
    }

    String payload = http.getString();
    http.end();

    LOGF("[OTA] version.json: %s", payload.c_str());

    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, payload);
    if (err) {
        status = OtaStatus::FAILED;
        lastError = "JSON parse error";
        LOGF("[OTA-ERROR] JSON 파싱 에러: %s", err.c_str());
        return;
    }

    const char* serverVersion = doc["version"] | "";
    const char* firmwareUrl   = doc["firmware_url"] | OTA_FIRMWARE_URL;

    LOGF("[OTA] 현재 버젼: %s | 서버 버젼: %s", FIRMWARE_VERSION, serverVersion);

    if (!force && String(serverVersion) == String(FIRMWARE_VERSION)) {
        status = OtaStatus::UP_TO_DATE;
        LOGF("[OTA] 이미 최신 버전입니다.");
        return;
    }

    // OTA 업데이트 진행
    status = OtaStatus::UPDATING;
    LOGF("[OTA] 새 펌웨어 다운로드 및 업데이트 시작! URL: %s", firmwareUrl);

    // HTTPUpdate callback
    httpUpdate.onStart([]() { LOGF("[OTA-UPDATE] 시작..."); });
    httpUpdate.onEnd([]() { LOGF("[OTA-UPDATE] 완료!"); });
    httpUpdate.onProgress([](int cur, int total) {
        printf("[OTA-PROGRESS] %d / %d bytes (%.1f%%)\r", cur, total, (float)cur / total * 100);
        fflush(stdout);
    });
    httpUpdate.onError([](int err) {
        LOGF("\n[OTA-ERROR] 코드 %d: %s", err, httpUpdate.getLastErrorString().c_str());
    });

    t_httpUpdate_return ret = httpUpdate.update(client, firmwareUrl);

    switch (ret) {
        case HTTP_UPDATE_FAILED:
            status = OtaStatus::FAILED;
            lastError = httpUpdate.getLastErrorString();
            LOGF("\n[OTA-FAILED] 업데이트 실패: %s", lastError.c_str());
            break;

        case HTTP_UPDATE_NO_UPDATES:
            status = OtaStatus::UP_TO_DATE;
            LOGF("\n[OTA] 업데이트 없음.");
            break;

        case HTTP_UPDATE_OK:
            status = OtaStatus::SUCCESS;
            LOGF("\n[OTA-SUCCESS] 업데이트 성공! 디바이스를 재부팅합니다.");
            delay(1000);
            ESP.restart();
            break;
    }
}
