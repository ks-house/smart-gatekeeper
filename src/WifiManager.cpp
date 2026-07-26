// src/WifiManager.cpp
// =============================================================
// smart-gatekeeper — Wi-Fi 매니저 구현 (STA/AP 모드 웹서버 상시 가동 & 주변 AP 스캔)
// =============================================================
#include "WifiManager.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

DNSServer WifiManager::dnsServer;
WebServer WifiManager::webServer(80);
bool WifiManager::apModeActive = false;
bool WifiManager::connected = false;
String WifiManager::stationIp = "";
static bool webServerStarted = false;

extern int g_tx_power_dbm;
extern uint16_t g_distance_threshold_mm;
extern uint32_t g_pre_arm_duration_ms;
extern uint32_t g_relay_cooldown_ms;

extern void setTxPower(int powerDbm);
extern void setTofDistanceCm(int distanceCm);
extern void setPreArmDurationMs(uint32_t durationMs);
extern void setRelayCooldownMs(uint32_t cooldownMs);


void WifiManager::init() {
    ConfigManager::begin();
}

void WifiManager::startWebServer() {
    if (webServerStarted) return;
    webServerStarted = true;

    webServer.on("/", handleRoot);
    webServer.on("/scan", handleScan);
    webServer.on("/save", HTTP_POST, handleSave);
    webServer.on("/config", HTTP_POST, handleConfigSave);
    webServer.onNotFound(handleNotFound);
    webServer.begin();

    LOGF("[WIFI-WEB] 🌐 Target WebServer 상시 가동 완료 (Port: 80)");
}

bool WifiManager::connectSTA(uint32_t timeoutMs) {
    String ssid = ConfigManager::getWifiSsid();
    String pass = ConfigManager::getWifiPassword();

    if (ssid.length() == 0 || ssid == "YOUR_WIFI_SSID") {
        LOGF("[WIFI] 저장된 Wi-Fi 정보가 없습니다. AP 설정을 준비합니다.");
        return false;
    }

    LOGF("[WIFI] NVS 저장 Wi-Fi '%s' 접속 시도 중...", ssid.c_str());
    WiFi.mode(WIFI_AP_STA); // STA 모드와 AP 조회를 겸용할 수 있도록 AP_STA 모드 활성화
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
        startWebServer(); // STA 접속 성공 시에도 로컬 IP 웹 접속을 위해 웹서버 구동!
        return true;
    } else {
        connected = false;
        LOGF("[WIFI] 접속 실패! (타임아웃) -> STA 연결 시도 중단");
        WiFi.disconnect(true, true);
        delay(100);
        return false;
    }
}

void WifiManager::startAP() {
    apModeActive = true;
    
    // 이전 STA 접속 시도로 인한 채널 호핑/비콘 브로드캐스트 블로킹 완정 방지
    WiFi.disconnect(true, true);
    delay(100);
    WiFi.mode(WIFI_AP_STA);
    
    IPAddress apIP(192, 168, 4, 1);
    WiFi.softAPConfig(apIP, apIP, IPAddress(255, 255, 255, 0));

    // 채널 1, 비숨김(0), 최대 4대 접속 설정하여 브로드캐스트 비콘 프레임 고정
    bool apSuccess = WiFi.softAP("SmartGatekeeper-Setup", NULL, 1, 0, 4);

    dnsServer.setErrorReplyCode(DNSReplyCode::NoError);
    dnsServer.start(53, "*", apIP);

    startWebServer();
    if (apSuccess) {
        LOGF("[WIFI-AP] ✅ 설정 AP 가동 완료: 'SmartGatekeeper-Setup' (채널 1, 192.168.4.1)");
    } else {
        LOGF("[WIFI-AP] 🚨 설정 AP 가동 실패!");
    }
}


void WifiManager::handleRoot() {
    String currentSsid = ConfigManager::getWifiSsid();
    int tofCm = (int)(g_distance_threshold_mm / 10);


    String html = F("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                    "<title>SmartGatekeeper Target Controller</title>"
                    "<style>"
                    "body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:16px;display:flex;justify-content:center;}"
                    ".card{background:#161b22;width:100%;max-width:440px;border:1px solid #30363d;border-radius:12px;padding:20px;box-sizing:border-box;box-shadow:0 8px 24px rgba(0,0,0,0.5);}"
                    "h2{color:#58a6ff;margin-top:0;text-align:center;font-size:20px;border-bottom:1px solid #30363d;padding-bottom:12px;}"
                    ".status-badge{padding:8px 12px;border-radius:6px;font-size:13px;font-weight:bold;margin-bottom:16px;text-align:center;}"
                    ".status-connected{background:rgba(46,160,67,0.2);color:#3fb950;border:1px solid #2ea043;}"
                    ".status-ap{background:rgba(210,153,34,0.2);color:#d29922;border:1px solid #d29922;}"
                    ".section-title{font-size:14px;color:#8b949e;margin:16px 0 8px;font-weight:bold;text-transform:uppercase;}"
                    "select,input{width:100%;padding:10px;margin-bottom:12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;box-sizing:border-box;}"
                    "button{width:100%;padding:12px;background:#238636;color:#fff;border:none;border-radius:6px;font-size:14px;font-weight:bold;cursor:pointer;margin-top:4px;}"
                    "button:hover{background:#2ea043;}"
                    ".btn-scan{background:#1f6feb;margin-bottom:12px;}"
                    ".btn-scan:hover{background:#388bfd;}"
                    ".param-row{display:flex;justify-content:space-between;align-items:center;background:#0d1117;padding:10px;border-radius:6px;margin-bottom:8px;border:1px solid #21262d;font-size:13px;}"
                    "</style></head><body><div class='card'>"
                    "<h2>🛡️ SmartGatekeeper Target</h2>");

    if (connected) {
        html += "<div class='status-badge status-connected'>🟢 Wi-Fi 연결됨: " + currentSsid + " (IP: " + stationIp + ")</div>";
    } else {
        html += "<div class='status-badge status-ap'>🟡 와이파이 설정 모드 (AP: 192.168.4.1)</div>";
    }

    html += F("<div class='section-title'>📡 주변 Wi-Fi 스캔 및 설정 변경</div>"
              "<button class='btn-scan' onclick='scanWifi()'>🔍 주변 Wi-Fi 다시 검색</button>"
              "<form action='/save' method='POST'>"
              "<label style='font-size:12px;color:#8b949e;'>Wi-Fi SSID 선택</label>"
              "<select id='ssid' name='ssid'><option value=''>검색 중...</option></select>"
              "<label style='font-size:12px;color:#8b949e;'>Wi-Fi 비밀번호</label>"
              "<input type='password' name='password' placeholder='비밀번호 입력'>"
              "<button type='submit'>💾 Wi-Fi 저장 및 재접속</button>"
              "</form>"
              "<div class='section-title' style='margin-top:24px;'>⚙️ Target NVS 튜닝 파라미터</div>"
              "<form action='/config' method='POST'>"
              "<label style='font-size:12px;color:#8b949e;'>BLE Tx Power (dBm)</label>"
              "<select name='tx_power'>");

    int powers[] = {-6, 0, 3, 9};
    for (int p : powers) {
        html += "<option value='" + String(p) + "'";
        if (p == g_tx_power_dbm) html += " selected";
        html += ">" + String(p) + " dBm</option>";
    }

    html += F("</select>"
              "<label style='font-size:12px;color:#8b949e;'>ToF 감지 거리 (cm)</label>"
              "<input type='number' name='tof_distance' min='5' max='200' value='");
    html += String(tofCm);
    html += F("'>"
              "<label style='font-size:12px;color:#8b949e;'>Pre-arm 유지 시간 (초)</label>"
              "<input type='number' name='duration' min='1000' max='60000' step='1000' value='");
    html += String((int)g_pre_arm_duration_ms);
    html += F("'>"
              "<label style='font-size:12px;color:#8b949e;'>Target 릴레이 쿨다운 (초)</label>"
              "<input type='number' name='relay_cooldown' min='1000' max='10000' step='500' value='");
    html += String((int)g_relay_cooldown_ms);
    html += F("'>"
              "<button type='submit' style='background:#8957e5;'>⚙️ 튜닝 파라미터 NVS 저장</button>"
              "</form>"
              "</div>"
              "<script>"
              "function scanWifi(){"
              "  let s = document.getElementById('ssid');"
              "  s.innerHTML = '<option>스캔 중...</option>';"
              "  fetch('/scan').then(r=>r.json()).then(data=>{"
              "    s.innerHTML = '';"
              "    if(!data || data.length===0){ s.innerHTML='<option>Wi-Fi 검색 실패</option>'; return; }"
              "    data.forEach(item=>{"
              "      let opt = document.createElement('option');"
              "      opt.value = item.ssid;"
              "      opt.innerHTML = item.ssid + ' (' + item.rssi + ' dBm)'; "
              "      s.appendChild(opt);"
              "    });"
              "  }).catch(e=>{"
              "    s.innerHTML = '<option>스캔 에러 발생</option>';"
              "  });"
              "}"
              "window.onload = scanWifi;"
              "</script></body></html>");

    webServer.send(200, "text/html", html);
}

void WifiManager::handleScan() {
    WiFi.scanDelete();
    int n = WiFi.scanNetworks(false, false, false, 150);
    LOGF("[WIFI-SCAN] 주변 Wi-Fi 스캔 완료: %d개 발견", n);

    String json = "[";
    for (int i = 0; i < n; ++i) {
        if (i > 0) json += ",";
        String ssid = WiFi.SSID(i);
        ssid.replace("\"", "\\\"");
        json += "{\"ssid\":\"" + ssid + "\",\"rssi\":" + String(WiFi.RSSI(i)) + "}";
    }
    json += "]";
    WiFi.scanDelete();
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
                    "<style>body{font-family:sans-serif;text-align:center;padding:50px;background:#0d1117;color:#c9d1d9;}"
                    ".card{background:#161b22;max-width:350px;margin:0 auto;padding:30px;border-radius:12px;border:1px solid #30363d;}"
                    "h2{color:#3fb950;}</style></head><body><div class='card'>"
                    "<h2>✅ Wi-Fi 저장 완료</h2>"
                    "<p>입력한 Wi-Fi로 접속을 시도합니다.<br>약 3초 후 장치가 재부팅됩니다.</p>"
                    "</div></body></html>");
    webServer.send(200, "text/html", html);
    delay(2000);
    ESP.restart();
}

void WifiManager::handleConfigSave() {
    if (webServer.hasArg("tx_power")) {
        setTxPower(webServer.arg("tx_power").toInt());
    }
    if (webServer.hasArg("tof_distance")) {
        setTofDistanceCm(webServer.arg("tof_distance").toInt());
    }
    if (webServer.hasArg("duration")) {
        setPreArmDurationMs(webServer.arg("duration").toInt());
    }
    if (webServer.hasArg("relay_cooldown")) {
        extern void setRelayCooldownMs(uint32_t cooldownMs);
        setRelayCooldownMs(webServer.arg("relay_cooldown").toInt());
    }
    webServer.sendHeader("Location", "/", true);
    webServer.send(302, "text/plain", "Updated");
}


void WifiManager::handleNotFound() {
    if (apModeActive) {
        webServer.sendHeader("Location", String("http://192.168.4.1/"), true);
        webServer.send(302, "text/plain", "");
    } else {
        webServer.sendHeader("Location", String("/"), true);
        webServer.send(302, "text/plain", "");
    }
}

void WifiManager::handleClient() {
    if (apModeActive) {
        dnsServer.processNextRequest();
    }
    webServer.handleClient();
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

