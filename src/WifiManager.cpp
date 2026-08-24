// src/WifiManager.cpp
// =============================================================
// smart-gatekeeper — Wi-Fi 매니저 구현 (STA/AP 모드 웹서버 상시 가동 & 주변 AP 스캔)
// =============================================================
#include "WifiManager.h"
#include "DiagnosticsManager.h"
#include "OtaManager.h"
#include "RecoveryRadioPolicy.h"
#include "config.h"

#include <cstring>
#include <esp_wifi.h>

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

WebServer WifiManager::webServer(80);
bool WifiManager::apModeActive = false;
bool WifiManager::connected = false;
String WifiManager::stationIp = "";
uint32_t WifiManager::recoveryApDeadlineMs = 0;
static bool webServerStarted = false;
static bool localUploadSucceeded = false;
static bool wifiEventsRegistered = false;
static bool recoveryOperationLeaseActive = false;
static uint32_t recoveryOperationLastActivityMs = 0;

namespace {
constexpr char kRecoveryApSsid[] = "SmartGatekeeper-Recovery";
constexpr uint32_t kRecoveryApQuietMs = 30000;
constexpr uint32_t kRecoveryStationAttemptMs = 10000;
constexpr uint32_t kRecoveryAuthenticatedHoldMs = 30000;
constexpr uint32_t kRecoveryOperationLeaseMs = 30000;
constexpr uint32_t kOperatorRecoveryWindowMs = 10UL * 60UL * 1000UL;
constexpr uint32_t kRecoveryApClientHoldMs = kOperatorRecoveryWindowMs;
constexpr uint32_t kRecoveryClientReleaseIntervalMs = 1000;

sgk::RecoveryRadioPolicy recoveryRadioPolicy(
    kRecoveryApQuietMs, kRecoveryStationAttemptMs,
    kRecoveryAuthenticatedHoldMs, kRecoveryApClientHoldMs,
    kRecoveryClientReleaseIntervalMs);

void registerWifiDiagnostics() {
    if (wifiEventsRegistered) return;
    wifiEventsRegistered = true;
    WiFi.onEvent(
        [](WiFiEvent_t, WiFiEventInfo_t info) {
            const auto reason = static_cast<wifi_err_reason_t>(
                info.wifi_sta_disconnected.reason);
            LOGF("[WIFI-DIAG] station disconnect reason=%u (%s)",
                 static_cast<unsigned int>(reason),
                 WiFi.disconnectReasonName(reason));
        },
        WiFiEvent_t::ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
}

void configureStationCompatibilityProfile() {
    // Complete the scan before choosing an AP so a shared SSID selects the
    // strongest BSSID instead of the first response. Keep the choice dynamic:
    // hard-pinning a BSSID or channel would break mesh/AP replacement recovery.
    WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
    WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);

    // A wall-powered access controller values a stable association, MQTT and
    // OTA path over modem-sleep savings. Limit only the STA interface to
    // b/g/n for compatibility with marginal 2.4 GHz infrastructure; the
    // recovery AP interface and its authenticated OTA path stay untouched.
    const bool sleepConfigured = WiFi.setSleep(WIFI_PS_NONE);
    constexpr uint8_t kLegacyStaProtocols =
        WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N;
    const esp_err_t protocolResult =
        esp_wifi_set_protocol(WIFI_IF_STA, kLegacyStaProtocols);

    if (!sleepConfigured || protocolResult != ESP_OK) {
        LOGF("[WIFI-WARN] STA compatibility profile partially unavailable "
             "(sleep=%s protocol_rc=%d); continuing with driver defaults",
             sleepConfigured ? "ok" : "failed",
             static_cast<int>(protocolResult));
        DiagnosticsManager::noteAction("wifi_sta_profile_degraded");
        return;
    }
    LOGF("[WIFI-INFO] STA compatibility profile enabled "
         "(all-channel/signal-sort, no-sleep, 11b/g/n)");
    DiagnosticsManager::noteAction("wifi_sta_profile_enabled");
}

bool stationCredentialsProvisioned() {
    const String ssid = ConfigManager::getWifiSsid();
    return ssid.length() > 0 && ssid != "YOUR_WIFI_SSID";
}

void startContinuousStationRecovery() {
    if (!stationCredentialsProvisioned()) return;
    WiFi.setAutoReconnect(true);
    WiFi.reconnect();
    DiagnosticsManager::noteAction("wifi_sta_continuous_recovery");
}

void beginRecoveryOperation() {
    recoveryOperationLeaseActive = true;
    recoveryOperationLastActivityMs = millis();
}

void touchRecoveryOperation() {
    recoveryOperationLeaseActive = true;
    recoveryOperationLastActivityMs = millis();
}

void endRecoveryOperation() {
    recoveryOperationLeaseActive = false;
    recoveryOperationLastActivityMs = 0;
}

bool isRecoveryOperationActive(uint32_t nowMs) {
    if (!recoveryOperationLeaseActive) return false;
    if (nowMs - recoveryOperationLastActivityMs < kRecoveryOperationLeaseMs) {
        return true;
    }
    endRecoveryOperation();
    DiagnosticsManager::noteAction("recovery_operation_lease_expired");
    return false;
}

void stopRecoveryStationAttemptForLocalWork(uint32_t nowMs) {
    if (recoveryRadioPolicy.phase() !=
        sgk::RecoveryRadioPhase::kStationAttempt) {
        return;
    }
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, false);
    recoveryRadioPolicy.pauseForLocalWork(nowMs);
    DiagnosticsManager::noteAction("wifi_sta_attempt_paused_for_local_work");
}

void restoreContinuousStationMode() {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
}

void startBoundedRecoveryStationAttempt(uint32_t nowMs) {
    WiFi.setAutoReconnect(false);
    if (WiFi.reconnect()) {
        DiagnosticsManager::noteAction("wifi_recovery_sta_attempt_started");
        LOGF("[WIFI-AP] bounded STA recovery attempt started (%lu ms max)",
             static_cast<unsigned long>(kRecoveryStationAttemptMs));
        return;
    }
    WiFi.disconnect(false, false);
    recoveryRadioPolicy.stationAttemptFailed(nowMs);
    DiagnosticsManager::noteAction("wifi_recovery_sta_attempt_start_failed");
    LOGF("[WIFI-WARN] bounded STA recovery attempt did not start; "
         "returning to quiet AP");
}
}  // namespace

extern int g_tx_power_dbm;
extern uint16_t g_distance_threshold_cm;
extern uint32_t g_pre_arm_duration_ms;
extern uint32_t g_relay_cooldown_ms;

extern void setTxPower(int powerDbm);
extern void setDistanceThresholdCm(int distanceCm);
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
    webServer.on("/recovery/manifest", HTTP_POST, handleRecoveryManifest);
    webServer.on("/recovery/firmware", HTTP_POST,
                 handleRecoveryUploadComplete, handleRecoveryUpload);
    webServer.on("/recovery/enable-ap", HTTP_POST, handleRecoveryApEnable);
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

    registerWifiDiagnostics();
    LOGF("[WIFI] NVS 저장 Wi-Fi '%s' 접속 시도 중...", ssid.c_str());
    WiFi.mode(WIFI_STA);
    configureStationCompatibilityProfile();
    WiFi.setAutoReconnect(true);
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
        WiFi.softAPdisconnect(true);
        restoreContinuousStationMode();
        DiagnosticsManager::noteAction("wifi_connected");
        LOGF("[WIFI] 접속 성공! IP 주소: %s", stationIp.c_str());
        startWebServer(); // STA 접속 성공 시에도 로컬 IP 웹 접속을 위해 웹서버 구동!
        return true;
    } else {
        connected = false;
        LOGF("[WIFI] 접속 실패! (타임아웃) -> STA 연결 시도 중단");
        WiFi.disconnect(false, false);
        delay(100);
        return false;
    }
}

void WifiManager::startAP() {
    startRecoveryAP(false, 0);
}

bool WifiManager::startRecoveryAP(bool preserveStation, uint32_t durationMs) {
    apModeActive = false;
    recoveryRadioPolicy.stop();
    endRecoveryOperation();
    DiagnosticsManager::noteAction("provisioning_ap_start");
    
    // AP+STA shares one ESP32-C6 radio/channel. Disable the Arduino core's
    // unbounded reconnect loop before starting the AP; the recovery timing
    // policy below grants only one bounded attempt after a stable AP window.
    if (preserveStation) {
        if (!isConnected()) return false;
        WiFi.setAutoReconnect(false);
        WiFi.mode(WIFI_AP_STA);
    } else {
        WiFi.setAutoReconnect(false);
        WiFi.disconnect(false, false);
        delay(100);
        WiFi.mode(WIFI_AP_STA);
    }
    
    IPAddress apIP(192, 168, 4, 1);
    WiFi.softAPConfig(apIP, apIP, IPAddress(255, 255, 255, 0));

    // Request channel 1 for AP-only recovery. In AP+STA mode the ESP32-C6 has
    // one radio, so the driver follows the associated station's channel.
    const bool recoveryProvisioned =
        std::strlen(LOCAL_RECOVERY_AP_PASSWORD) >= 16 &&
        std::strlen(LOCAL_RECOVERY_USER) >= 8 &&
        std::strlen(LOCAL_RECOVERY_PASSWORD) >= 16;
    bool apSuccess = recoveryProvisioned &&
        WiFi.softAP(kRecoveryApSsid,
                    LOCAL_RECOVERY_AP_PASSWORD, 1, 0, 2);

    if (apSuccess) {
        apModeActive = true;
        recoveryApDeadlineMs =
            sgk::MakeRecoveryDeadline(millis(), durationMs);
        startWebServer();
        DiagnosticsManager::noteAction("provisioning_ap_ready");
        LOGF("[WIFI-AP] ✅ 설정 AP 가동 완료: '%s' "
             "(requested channel 1, 192.168.4.1)",
             kRecoveryApSsid);
        LOGF("[WIFI-AP] Captive DNS disabled; open http://192.168.4.1 manually.");
        if (!preserveStation) {
            recoveryRadioPolicy.begin(millis());
            DiagnosticsManager::noteAction("wifi_recovery_ap_quiet");
            LOGF("[WIFI-AP] discovery quiet window started (%lu ms)",
                 static_cast<unsigned long>(kRecoveryApQuietMs));
        }
    } else {
        WiFi.softAPdisconnect(true);
        recoveryApDeadlineMs = 0;
        recoveryRadioPolicy.stop();
        restoreContinuousStationMode();
        if (!preserveStation) startContinuousStationRecovery();
        DiagnosticsManager::noteAction("provisioning_ap_failed");
        LOGF("[WIFI-AP] 🚨 설정 AP 가동 실패!");
    }
    return apSuccess;
}

void WifiManager::handleRoot() {
    if (!requireLocalAuthentication()) return;
    String currentSsid = ConfigManager::getWifiSsid();
    int distCm = (int)g_distance_threshold_cm;


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
                    ".network-list{max-height:220px;overflow-y:auto;border:1px solid #30363d;border-radius:6px;background:#0d1117;padding:4px;margin-bottom:8px;}"
                    ".network-item{display:block;width:100%;padding:10px;margin:0 0 4px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;text-align:left;font-weight:normal;}"
                    ".network-item:last-child{margin-bottom:0;}"
                    ".network-item:hover,.network-item.selected{background:#1f6feb;border-color:#58a6ff;}"
                    ".network-empty{padding:12px;color:#8b949e;text-align:center;font-size:13px;}"
                    ".param-row{display:flex;justify-content:space-between;align-items:center;background:#0d1117;padding:10px;border-radius:6px;margin-bottom:8px;border:1px solid #21262d;font-size:13px;}"
                    "</style></head><body><div class='card'>"
                    "<h2>🛡️ SmartGatekeeper Target</h2>");

    if (isConnected()) {
        html += "<div class='status-badge status-connected'>🟢 Wi-Fi 연결됨: " + currentSsid + " (IP: " + stationIp + ")</div>";
    } else {
        html += "<div class='status-badge status-ap'>🟡 와이파이 설정 모드 (AP: 192.168.4.1)</div>";
    }

    html += F("<div class='section-title'>📡 주변 Wi-Fi 스캔 및 설정 변경</div>"
              "<button class='btn-scan' onclick='scanWifi()'>🔍 주변 Wi-Fi 다시 검색</button>"
              "<label style='font-size:12px;color:#8b949e;'>검색된 Wi-Fi 목록</label>"
              "<div id='ssid-options' class='network-list'><div class='network-empty'>Scanning...</div></div>"
              "<div id='scan-status' style='font-size:12px;color:#8b949e;margin:0 0 12px;'>Scanning...</div>"
              "<form action='/save' method='POST'>"
              "<label style='font-size:12px;color:#8b949e;'>선택된 Wi-Fi SSID (직접 입력 가능)</label>"
              "<input id='ssid' name='ssid' maxlength='32' required placeholder='Tap a network above or enter SSID manually'>"
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
              "<label style='font-size:12px;color:#8b949e;'>초음파 감지 기준 거리 (cm) [20~200]</label>"
              "<input type='number' name='distance_threshold' min='20' max='200' value='");
    html += String(distCm);
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
              "  let list = document.getElementById('ssid-options');"
              "  let status = document.getElementById('scan-status');"
              "  list.innerHTML = '<div class=\"network-empty\">Scanning...</div>'; status.textContent = 'Scanning...';"
              "  fetch('/scan', {cache:'no-store', credentials:'same-origin'}).then(r=>{ if(!r.ok) throw new Error('scan failed'); return r.json(); }).then(data=>{"
              "    if(!Array.isArray(data)){ throw new Error('invalid scan response'); }"
              "    let seen = new Set();"
              "    let networks = data.filter(item=>{"
              "      if(!item || typeof item.ssid !== 'string' || !item.ssid.length || seen.has(item.ssid)) return false;"
              "      seen.add(item.ssid); return true;"
              "    });"
              "    list.innerHTML = '';"
              "    status.textContent = networks.length ? networks.length + ' network(s) found - tap one to select' : 'No network found; retry or enter SSID manually';"
              "    if(!networks.length){ list.innerHTML = '<div class=\"network-empty\">No visible network found</div>'; return; }"
              "    networks.forEach(item=>{"
              "      let button = document.createElement('button');"
              "      button.type = 'button'; button.className = 'network-item';"
              "      button.textContent = item.ssid + '  (' + item.rssi + ' dBm)';"
              "      button.addEventListener('click', ()=>{"
              "        document.getElementById('ssid').value = item.ssid;"
              "        document.querySelectorAll('.network-item').forEach(node=>node.classList.remove('selected'));"
              "        button.classList.add('selected');"
              "        status.textContent = 'Selected: ' + item.ssid;"
              "      });"
              "      list.appendChild(button);"
              "    });"
              "  }).catch(e=>{"
              "    list.innerHTML = '<div class=\"network-empty\">Scan failed</div>';"
              "    status.textContent = 'Scan failed; wait a moment and retry';"
              "  });"
              "}"
              "window.onload = scanWifi;"
              "</script></body></html>");

    webServer.sendHeader("Cache-Control", "no-store");
    webServer.send(200, "text/html", html);
}

void WifiManager::handleScan() {
    if (!requireLocalAuthentication()) return;
    beginRecoveryOperation();

    // A recovery STA attempt and a scan cannot own the single radio together.
    // Pause only the disconnected STA side and leave credentials/NVS intact.
    // The recovery policy grants a new attempt only after another quiet window;
    // it is deliberately not resumed at the end of this HTTP response.
    const bool pauseDisconnectedStation =
        apModeActive && WiFi.status() != WL_CONNECTED &&
        stationCredentialsProvisioned();
    if (pauseDisconnectedStation) {
        WiFi.setAutoReconnect(false);
        WiFi.disconnect(false, false);
        recoveryRadioPolicy.pauseForLocalWork(millis());
        delay(200);
        DiagnosticsManager::noteAction("wifi_scan_sta_paused");
    }

    WiFi.scanDelete();
    int n = WiFi.scanNetworks(false, false, false, 150);
    if (n < 0 && pauseDisconnectedStation) {
        LOGF("[WIFI-SCAN] first scan failed code=%d; retrying once", n);
        WiFi.scanDelete();
        delay(200);
        n = WiFi.scanNetworks(false, false, false, 250);
    }

    String json = "[";
    for (int i = 0; i < n && n > 0; ++i) {
        if (i > 0) json += ",";
        String ssid = WiFi.SSID(i);
        ssid.replace("\"", "\\\"");
        json += "{\"ssid\":\"" + ssid + "\",\"rssi\":" + String(WiFi.RSSI(i)) + "}";
    }
    json += "]";
    WiFi.scanDelete();
    if (n < 0) {
        LOGF("[WIFI-SCAN] scan failed code=%d", n);
        DiagnosticsManager::noteAction("wifi_scan_failed");
        webServer.sendHeader("Cache-Control", "no-store");
        webServer.send(503, "application/json",
                       "{\"error\":\"scan_failed\"}");
    } else {
        LOGF("[WIFI-SCAN] nearby Wi-Fi scan complete: %d found", n);
        DiagnosticsManager::noteAction("wifi_scan_complete");
        webServer.sendHeader("Cache-Control", "no-store");
        webServer.send(200, "application/json", json);
    }
    endRecoveryOperation();
}

void WifiManager::handleSave() {
    if (!requireLocalAuthentication()) return;
    if (!apModeActive) {
        DiagnosticsManager::noteAction("wifi_save_rejected");
        webServer.send(
            403, "text/plain",
            "Wi-Fi credential changes are allowed only in provisioning AP mode.");
        return;
    }
    beginRecoveryOperation();

    String ssid = webServer.arg("ssid");
    String pass = webServer.arg("password");

    if (ssid.length() == 0 || ssid.length() > 32 || pass.length() > 63 ||
        (pass.length() > 0 && pass.length() < 8)) {
        DiagnosticsManager::noteAction("wifi_credentials_invalid");
        webServer.send(400, "text/plain", "Invalid Wi-Fi credentials");
        endRecoveryOperation();
        return;
    }

    DiagnosticsManager::noteAction("wifi_credentials_save");
    LOGF("[WIFI-AP] 신규 Wi-Fi 설정 수신: SSID='%s'", ssid.c_str());
    ConfigManager::setWifiCredentials(ssid, pass);
    if (ConfigManager::getWifiSsid() != ssid ||
        ConfigManager::getWifiPassword() != pass) {
        DiagnosticsManager::noteAction("wifi_credentials_write_failed");
        webServer.send(500, "text/plain", "Wi-Fi credential storage failed");
        endRecoveryOperation();
        return;
    }

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
    DiagnosticsManager::markPlannedRestart("provisioning_save");
    ESP.restart();
}

void WifiManager::handleConfigSave() {
    if (!requireLocalAuthentication()) return;
    DiagnosticsManager::noteAction("web_config_save");
    if (webServer.hasArg("tx_power")) {
        setTxPower(webServer.arg("tx_power").toInt());
    }
    if (webServer.hasArg("distance_threshold")) {
        setDistanceThresholdCm(webServer.arg("distance_threshold").toInt());
    }
    if (webServer.hasArg("tof_distance")) {
        setDistanceThresholdCm(webServer.arg("tof_distance").toInt());
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

bool WifiManager::requireLocalAuthentication() {
    if (std::strlen(LOCAL_RECOVERY_USER) < 8 ||
        std::strlen(LOCAL_RECOVERY_PASSWORD) < 16) {
        webServer.send(503, "text/plain", "Local recovery is not provisioned.");
        return false;
    }
    if (!webServer.authenticate(LOCAL_RECOVERY_USER,
                                LOCAL_RECOVERY_PASSWORD)) {
        webServer.requestAuthentication(BASIC_AUTH, kRecoveryApSsid);
        return false;
    }
    if (apModeActive) {
        const uint32_t nowMs = millis();
        recoveryRadioPolicy.noteAuthenticatedActivity(nowMs);
        stopRecoveryStationAttemptForLocalWork(nowMs);
    }
    return true;
}

void WifiManager::handleRecoveryManifest() {
    if (!apModeActive || !requireLocalAuthentication()) {
        if (!apModeActive) webServer.send(403, "text/plain", "AP recovery only");
        return;
    }
    beginRecoveryOperation();
    const String manifest = webServer.arg("plain");
    if (!OtaManager::stageLocalManifest(manifest)) {
        webServer.send(400, "text/plain",
                       "Signed manifest rejected: " +
                           OtaManager::getLastError());
        endRecoveryOperation();
        return;
    }
    webServer.send(204, "text/plain", "");
    endRecoveryOperation();
}

void WifiManager::handleRecoveryUpload() {
    if (!apModeActive || !requireLocalAuthentication()) return;
    HTTPUpload& upload = webServer.upload();
    if (upload.status == UPLOAD_FILE_START) {
        beginRecoveryOperation();
        localUploadSucceeded = false;
        if (!OtaManager::localManifestReady() || !OtaManager::beginLocalUpload()) {
            OtaManager::abortLocalUpload("local upload start rejected");
        }
    } else if (upload.status == UPLOAD_FILE_WRITE) {
        touchRecoveryOperation();
        if (!OtaManager::writeLocalUploadChunk(upload.buf, upload.currentSize)) {
            OtaManager::abortLocalUpload("local upload write rejected");
        }
    } else if (upload.status == UPLOAD_FILE_END) {
        touchRecoveryOperation();
        localUploadSucceeded = OtaManager::finishLocalUpload();
        endRecoveryOperation();
    } else if (upload.status == UPLOAD_FILE_ABORTED) {
        OtaManager::abortLocalUpload("local upload aborted");
        endRecoveryOperation();
    }
}

void WifiManager::handleRecoveryUploadComplete() {
    if (!apModeActive || !requireLocalAuthentication()) {
        if (!apModeActive) webServer.send(403, "text/plain", "AP recovery only");
        return;
    }
    beginRecoveryOperation();
    if (!localUploadSucceeded) {
        webServer.send(400, "text/plain", "Firmware rejected");
        endRecoveryOperation();
        return;
    }
    webServer.send(202, "text/plain", "Verified; rebooting into pending slot");
    delay(250);
    ESP.restart();
}

void WifiManager::handleRecoveryApEnable() {
    if (!requireLocalAuthentication()) return;
    if (!isConnected()) {
        webServer.send(409, "text/plain", "Station link is not available");
        return;
    }
    if (!startRecoveryAP(true, kOperatorRecoveryWindowMs)) {
        webServer.send(503, "text/plain", "Recovery AP unavailable");
        return;
    }
    webServer.send(202, "text/plain",
                   "Authenticated recovery AP enabled for 10 minutes");
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
    // Process an already-arrived authenticated request before granting a STA
    // attempt. Authentication and operation handlers extend/pause the policy,
    // so a queued save, scan or signed local OTA request wins radio ownership.
    webServer.handleClient();
    const uint32_t nowMs = millis();

    const bool operatorDeadlineReached =
        apModeActive &&
        sgk::RecoveryDeadlineReached(nowMs, recoveryApDeadlineMs);
    if (operatorDeadlineReached && isRecoveryOperationActive(nowMs)) {
        // Do not cut an authenticated scan/save/signed local OTA operation at
        // the ten-minute boundary. Each active lease receives only another
        // bounded lease interval; a stalled or idle client cannot renew it.
        recoveryApDeadlineMs = sgk::MakeRecoveryDeadline(
            nowMs, kRecoveryOperationLeaseMs);
        DiagnosticsManager::noteAction(
            "recovery_ap_deadline_deferred_for_local_operation");
        return;
    }

    if (operatorDeadlineReached) {
        const bool stationWasConnected = WiFi.status() == WL_CONNECTED;
        const String stationIpBeforeApClose =
            stationWasConnected ? WiFi.localIP().toString() : String();
        WiFi.softAPdisconnect(true);
        recoveryApDeadlineMs = 0;
        apModeActive = false;
        recoveryRadioPolicy.stop();
        endRecoveryOperation();
        if (stationWasConnected) {
            connected = true;
            stationIp = stationIpBeforeApClose;
            restoreContinuousStationMode();
        } else {
            connected = false;
            startAP();
            DiagnosticsManager::noteAction("recovery_ap_window_closed");
            return;
        }
        DiagnosticsManager::noteAction("recovery_ap_window_closed");
    }

    if (apModeActive && recoveryApDeadlineMs == 0 &&
        WiFi.status() == WL_CONNECTED) {
        const String recoveredStationIp = WiFi.localIP().toString();
        WiFi.softAPdisconnect(true);
        apModeActive = false;
        connected = true;
        stationIp = recoveredStationIp;
        recoveryRadioPolicy.stop();
        endRecoveryOperation();
        restoreContinuousStationMode();
        DiagnosticsManager::noteAction("wifi_recovered_from_ap");
        LOGF("[WIFI-INFO] provisioning AP station recovery succeeded! IP: %s",
             stationIp.c_str());
    } else if (apModeActive && WiFi.status() == WL_CONNECTED) {
        // The authenticated ten-minute operator window intentionally keeps the
        // AP up while the healthy STA continues MQTT and periodic HTTPS OTA.
        connected = true;
        stationIp = WiFi.localIP().toString();
        recoveryRadioPolicy.stop();
    } else if (apModeActive) {
        connected = false;
        if (recoveryRadioPolicy.phase() ==
            sgk::RecoveryRadioPhase::kInactive) {
            WiFi.setAutoReconnect(false);
            WiFi.disconnect(false, false);
            recoveryRadioPolicy.begin(nowMs);
            DiagnosticsManager::noteAction("wifi_recovery_ap_quiet");
            LOGF("[WIFI-AP] station lost; discovery quiet window restarted");
        }

        if (stationCredentialsProvisioned()) {
            const sgk::RecoveryRadioAction action = recoveryRadioPolicy.update(
                nowMs, false, WiFi.softAPgetStationNum() > 0,
                isRecoveryOperationActive(nowMs));
            if (action ==
                sgk::RecoveryRadioAction::kStartStationAttempt) {
                startBoundedRecoveryStationAttempt(nowMs);
            } else if (action ==
                       sgk::RecoveryRadioAction::kStopStationAttempt) {
                WiFi.setAutoReconnect(false);
                WiFi.disconnect(false, false);
                DiagnosticsManager::noteAction(
                    "wifi_recovery_sta_attempt_stopped");
                LOGF("[WIFI-AP] bounded STA recovery attempt stopped; "
                     "returning to quiet AP");
            } else if (action ==
                       sgk::RecoveryRadioAction::kReleaseStaleApClients) {
                const esp_err_t deauthResult = esp_wifi_deauth_sta(0);
                if (deauthResult == ESP_OK) {
                    DiagnosticsManager::noteAction(
                        "wifi_recovery_idle_client_released");
                    LOGF("[WIFI-AP] idle AP client hold expired; "
                         "client released before a fresh quiet window");
                } else {
                    DiagnosticsManager::noteAction(
                        "wifi_recovery_idle_client_release_failed");
                    LOGF("[WIFI-WARN] unable to release idle AP clients "
                         "(rc=%d); STA attempt remains blocked",
                         static_cast<int>(deauthResult));
                }
            } else if (
                action == sgk::RecoveryRadioAction::
                              kReleaseStaleClientsAndStartStationAttempt) {
                const esp_err_t deauthResult = esp_wifi_deauth_sta(0);
                if (deauthResult == ESP_OK) {
                    DiagnosticsManager::noteAction(
                        "wifi_recovery_stale_client_attempt_forced");
                    LOGF("[WIFI-AP] stale AP clients released; starting "
                         "bounded STA availability attempt");
                    startBoundedRecoveryStationAttempt(nowMs);
                } else {
                    recoveryRadioPolicy.stationAttemptFailed(nowMs);
                    DiagnosticsManager::noteAction(
                        "wifi_recovery_idle_client_release_failed");
                    LOGF("[WIFI-WARN] unable to release stale AP clients "
                         "(rc=%d); returning to quiet AP",
                         static_cast<int>(deauthResult));
                }
            }
        }
    }

    if (!apModeActive) {
        // STA 모드 - Wi-Fi 연결 워치독 (Auto-Reconnect)
        static uint32_t lastWifiCheckMs = 0;
        if (nowMs - lastWifiCheckMs > 15000) {
            lastWifiCheckMs = nowMs;
            if (WiFi.status() != WL_CONNECTED) {
                if (connected) {
                    LOGF("[WIFI-WARN] ⚠️ 와이파이 연결 단절 감지! Auto-Reconnect 작동 시작...");
                    connected = false;
                }
                // The Arduino core owns reconnect timing. Calling reconnect()
                // here can race an in-flight attempt and return WIFI_STATE.
                WiFi.setAutoReconnect(true);
                DiagnosticsManager::noteAction("wifi_autoreconnect_watch");
            } else {
                if (!connected) {
                    connected = true;
                    stationIp = WiFi.localIP().toString();
                    DiagnosticsManager::noteAction("wifi_reconnected");
                    LOGF("[WIFI-INFO] ✅ 와이파이 자동 재접속 성공! IP: %s", stationIp.c_str());
                }
            }
        }
    }
}

bool WifiManager::isConnected() {
    return connected && (WiFi.status() == WL_CONNECTED);
}

bool WifiManager::isAPMode() {
    return apModeActive;
}

String WifiManager::getIP() {
    return stationIp;
}
