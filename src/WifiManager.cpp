// src/WifiManager.cpp
// =============================================================
// smart-gatekeeper — Wi-Fi 매니저 구현
// =============================================================
#include "WifiManager.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

DNSServer WifiManager::dnsServer;
WebServer WifiManager::webServer(80);
bool WifiManager::apModeActive = false;
bool WifiManager::connected = false;
String WifiManager::stationIp = "";

void WifiManager::init() {
    ConfigManager::begin();
}

bool WifiManager::connectSTA(uint32_t timeoutMs) {
    String ssid = ConfigManager::getWifiSsid();
    String pass = ConfigManager::getWifiPassword();

    if (ssid.length() == 0 || ssid == "YOUR_WIFI_SSID") {
        LOGF("[WIFI] 저장된 Wi-Fi 정보가 없습니다. AP 설정을 준비합니다.");
        return false;
    }

    LOGF("[WIFI] NVS 저장 Wi-Fi '%s' 접속 시도 중...", ssid.c_str());
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), pass.c_str());

    uint32_t startMs = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - startMs < timeoutMs)) {
        delay(500);
        printf(".");
        fflush(stdout);
    }
    printf("\n");

    if (WiFi.status() == WL_CONNECTED) {
        connected = true;
        apModeActive = false;
        stationIp = WiFi.localIP().toString();
        LOGF("[WIFI] 접속 성공! IP 주소: %s", stationIp.c_str());
        return true;
    } else {
        connected = false;
        LOGF("[WIFI] 접속 실패! (타임아웃)");
        return false;
    }
}

void WifiManager::startAP() {
    apModeActive = true;
    WiFi.mode(WIFI_AP_STA);
    
    IPAddress apIP(192, 168, 4, 1);
    WiFi.softAPConfig(apIP, apIP, IPAddress(255, 255, 255, 0));
    WiFi.softAP("SmartGatekeeper-Setup");

    dnsServer.setErrorReplyCode(DNSReplyCode::NoError);
    dnsServer.start(53, "*", apIP);

    webServer.on("/", handleRoot);
    webServer.on("/scan", handleScan);
    webServer.on("/save", HTTP_POST, handleSave);
    webServer.onNotFound(handleNotFound);
    webServer.begin();

    LOGF("[WIFI-AP] 설정 AP 가동: 'SmartGatekeeper-Setup' (192.168.4.1)");
}

void WifiManager::handleRoot() {
    String html = F("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                    "<title>SmartGatekeeper Wi-Fi Setup</title>"
                    "<style>"
                    "body{font-family:sans-serif;background:#f0f2f5;padding:20px;text-align:center;color:#333;}"
                    ".card{background:#fff;max-width:400px;margin:0 auto;padding:24px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.1);}"
                    "h2{color:#1a73e8;margin-bottom:16px;}"
                    "select,input{width:100%;padding:12px;margin:8px 0 16px;border:1px solid #ccc;border-radius:6px;box-sizing:border-box;font-size:15px;}"
                    "button{width:100%;padding:12px;background:#1a73e8;color:#fff;border:none;border-radius:6px;font-size:16px;font-weight:bold;cursor:pointer;}"
                    "button:hover{background:#1557b0;}"
                    ".btn-scan{background:#34a853;margin-bottom:12px;}"
                    "</style></head><body><div class='card'>"
                    "<h2>🚪 SmartGatekeeper</h2>"
                    "<p>주변 Wi-Fi를 선택하고 비밀번호를 입력하세요.</p>"
                    "<button class='btn-scan' onclick='scanWifi()'>🔍 주변 Wi-Fi 다시 검색</button>"
                    "<form action='/save' method='POST'>"
                    "<label><b>Wi-Fi SSID</b></label>"
                    "<select id='ssid' name='ssid'><option value=''>검색 중...</option></select>"
                    "<label><b>Wi-Fi 비밀번호</b></label>"
                    "<input type='password' name='password' placeholder='비밀번호 입력'>"
                    "<button type='submit'>💾 저장 및 연결하기</button>"
                    "</form></div>"
                    "<script>"
                    "function scanWifi(){"
                    "  fetch('/scan').then(r=>r.json()).then(data=>{"
                    "    let s = document.getElementById('ssid');"
                    "    s.innerHTML = '';"
                    "    if(data.length===0){ s.innerHTML='<option>Wi-Fi 없음</option>'; return; }"
                    "    data.forEach(item=>{"
                    "      let opt = document.createElement('option');"
                    "      opt.value = item.ssid;"
                    "      opt.innerHTML = item.ssid + ' (' + item.rssi + 'dBm)'; "
                    "      s.appendChild(opt);"
                    "    });"
                    "  });"
                    "}"
                    "window.onload = scanWifi;"
                    "</script></body></html>");
    webServer.send(200, "text/html", html);
}

void WifiManager::handleScan() {
    int n = WiFi.scanNetworks();
    String json = "[";
    for (int i = 0; i < n; ++i) {
        if (i > 0) json += ",";
        json += "{\"ssid\":\"" + WiFi.SSID(i) + "\",\"rssi\":" + String(WiFi.RSSI(i)) + "}";
    }
    json += "]";
    webServer.send(200, "application/json", json);
}

void WifiManager::handleSave() {
    String ssid = webServer.arg("ssid");
    String pass = webServer.arg("password");

    LOGF("[WIFI-AP] 신규 Wi-Fi 설정 수신: SSID='%s'", ssid.c_str());
    ConfigManager::setWifiCredentials(ssid, pass);

    String html = F("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                    "<title>저장 완료</title>"
                    "<style>body{font-family:sans-serif;text-align:center;padding:50px;background:#f0f2f5;}"
                    ".card{background:#fff;max-width:350px;margin:0 auto;padding:30px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.1);}"
                    "h2{color:#34a853;}</style></head><body><div class='card'>"
                    "<h2>✅ 저장 완료</h2>"
                    "<p>입력한 Wi-Fi로 재접속을 시도합니다.<br>약 5초 후 장치가 재부팅됩니다.</p>"
                    "</div></body></html>");
    webServer.send(200, "text/html", html);
    delay(2000);
    ESP.restart();
}

void WifiManager::handleNotFound() {
    // Captive Portal 리다이렉트
    webServer.sendHeader("Location", String("http://192.168.4.1/"), true);
    webServer.send(302, "text/plain", "");
}

void WifiManager::handleClient() {
    if (apModeActive) {
        dnsServer.processNextRequest();
        webServer.handleClient();
    }
}

bool WifiManager::isConnected() {
    return WiFi.status() == WL_CONNECTED;
}

bool WifiManager::isAPMode() {
    return apModeActive;
}

String WifiManager::getIP() {
    return stationIp;
}
