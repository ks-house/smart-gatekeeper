// Execute the actual station repair methods against a closed Wi-Fi driver.
#include "RecoveryRadioPolicy.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <string>
#include <vector>

#define CHECK(condition, message) do { if (!(condition)) { \
  std::fprintf(stderr, "station repair FAIL line %d: %s\n", __LINE__, message); std::exit(1); } } while (0)
#define LOGF(...) do { std::printf(__VA_ARGS__); std::putchar(10); } while (0)
using String = std::string;
using esp_err_t = int;
constexpr int ESP_OK = 0, WIFI_IF_STA = 0, WIFI_PS_NONE = 0;
constexpr uint8_t WIFI_PROTOCOL_11B = 1, WIFI_PROTOCOL_11G = 2, WIFI_PROTOCOL_11N = 4;
constexpr int WIFI_ALL_CHANNEL_SCAN = 0, WIFI_CONNECT_AP_BY_SIGNAL = 0;
constexpr int WIFI_OFF = 0, WIFI_STA = 1, WL_CONNECTED = 3, WL_CONNECT_FAILED = 4, WL_DISCONNECTED = 6, WL_IDLE_STATUS = 0;
constexpr uint32_t WIFI_STA_RECOVERY_GRACE_MS = 30000, WIFI_RECOVERY_AP_RETRY_MS = 60000;
using wl_status_t = int;
uint32_t now_ms = 100, driver_generation = 7;
uint32_t millis() { return now_ms; }
bool reservation = true, reservation_allowed = true, workers_active = false, ota_busy = false;
int reserve_calls = 0, release_calls = 0, ap_starts = 0;
String configured_ssid = "fixture-ssid", configured_password = "fixture-password";
std::vector<String> radio;
class ConfigManager {
 public:
  static String getWifiSsid() { return configured_ssid; }
  static String getWifiPassword() { return configured_password; }
};
class GattServer {
 public:
  static bool hasIdleRadioReservation() { return reservation; }
  static bool tryReserveIdleRadio() {
    ++reserve_calls;
    if (!reservation_allowed || reservation || ota_busy) return false;
    reservation = true; return true;
  }
  static void releaseIdleRadio() { CHECK(reservation, "only owned reservation released"); reservation = false; ++release_calls; }
  static bool isOtaBusy() { return ota_busy; }
};
class MqttManager {
 public:
  static bool transportWorkersActive() { return workers_active; }
};
class DiagnosticsManager {
 public:
  static void noteAction(const char*) {}
};
class FakeWiFi {
 public:
  int associated = WL_CONNECTED;
  bool autoreconnect = true, disconnect_ok = true, reconnect_ok = true, auto_ok = true;
  bool off_ok = true;
  int sta_failures = 0, sta_calls = 0;
  wl_status_t begin_status = WL_IDLE_STATUS;
  int status() { return associated; }
  bool getAutoReconnect() { return autoreconnect; }
  bool setAutoReconnect(bool value) {
    radio.push_back(value ? "auto:on" : "auto:off");
    if (!auto_ok) return false;
    autoreconnect = value; return true;
  }
  bool disconnect(bool off, bool erase, unsigned long wait) {
    CHECK(!off && !erase && wait == 0, "repair disconnect is asynchronous and preserves credentials");
    radio.push_back("disconnect"); return disconnect_ok;
  }
  bool reconnect() { radio.push_back("reconnect"); return reconnect_ok; }
  bool mode(int value) {
    radio.push_back(value == WIFI_OFF ? "mode:off" : "mode:sta");
    if (value == WIFI_OFF) return off_ok;
    return ++sta_calls > sta_failures;
  }
  wl_status_t begin(const char* ssid, const char* password) {
    CHECK(configured_ssid == ssid && configured_password == password, "stage two reuses saved credentials");
    radio.push_back("begin"); return begin_status;
  }
  void setScanMethod(int) { radio.push_back("profile:scan"); }
  void setSortMethod(int) { radio.push_back("profile:sort"); }
  bool setSleep(int) { radio.push_back("profile:sleep"); return true; }
} WiFi;
esp_err_t esp_wifi_set_protocol(int, uint8_t) { radio.push_back("profile:protocol"); return ESP_OK; }
class WifiManager {
 public:
  static bool apModeActive, connected;
  static String stationIp;
  static bool beginStationRepair();
  static bool finishStationRepair(bool restartInterface);
  static void cancelStationRepair(bool restoreAutoReconnect);
  static bool isStationRepairPending();
  static bool isStationAssociated();
  static bool isConnected();
  static bool isLocalRecoveryActive();
  static void serviceRecovery(uint32_t);
  static uint32_t linkGeneration() { return driver_generation; }
  static bool startRecoveryAP(bool, uint32_t) { ++ap_starts; return true; }
};
bool WifiManager::apModeActive = false, WifiManager::connected = true;
String WifiManager::stationIp = "fixture-ip";
bool recoveryOperationLeaseActive = false;
uint32_t recoveryOperationLastActivityMs = 0;
bool wifiIntentionalDisconnectPending = false;
uint32_t wifiIntentionalDisconnectMarkedAtMs = 0;
bool wifiOutageNoticePending = false, wifiRecoveryNoticePending = false;
uint32_t wifiRecoveryEscalationCount = 0, wifiRecoveryApStartFailureCount = 0;
constexpr uint32_t kRecoveryOperationLeaseMs = 30000;
sgk::StationRecoveryEscalationPolicy stationRecoveryPolicy(30000, 60000);

// New fields, existing helper functions, and repair/service methods are copied
// verbatim by the Python extractor, so this fixture executes production branches.
#include "wifi_station_repair_production.inc"

void beginAccepted() {
  CHECK(WifiManager::beginStationRepair(), "driver accepted asynchronous disconnect");
  CHECK(WifiManager::isStationRepairPending(), "accepted repair holds a finite pending lease");
  CHECK(radio == std::vector<String>({"auto:off", "disconnect"}), "begin disables auto reconnect before one nonblocking disconnect");
}
int main(int argc, char** argv) {
  CHECK(argc == 2, "one scenario");
  const String scenario = argv[1];
  if (scenario.rfind("guard_", 0) == 0) {
    if (scenario == "guard_reservation") reservation = false;
    else if (scenario == "guard_ap") WifiManager::apModeActive = true;
    else if (scenario == "guard_local") { recoveryOperationLeaseActive = true; recoveryOperationLastActivityMs = now_ms; }
    else if (scenario == "guard_credentials") configured_ssid.clear();
    else if (scenario == "guard_placeholder") configured_ssid = "YOUR_WIFI_SSID";
    else if (scenario == "guard_ota") ota_busy = true;
    CHECK(!WifiManager::beginStationRepair(), "guarded begin is refused");
    CHECK(!WifiManager::isStationRepairPending() && radio.empty(), "guard refusal performs no radio mutation");
  } else if (scenario == "disconnect_rejected_on" || scenario == "disconnect_rejected_off") {
    WiFi.autoreconnect = scenario == "disconnect_rejected_on";
    WiFi.disconnect_ok = false;
    CHECK(!WifiManager::beginStationRepair() && !WifiManager::isStationRepairPending(), "rejected disconnect leaves no pending ownership");
    CHECK(WiFi.autoreconnect == (scenario == "disconnect_rejected_on"), "rejected begin restores exact previous auto reconnect policy");
    CHECK(!wifiIntentionalDisconnectPending, "rejected disconnect clears attribution marker");
  } else if (scenario == "auto_disable_rejected") {
    WiFi.auto_ok = false;
    CHECK(!WifiManager::beginStationRepair() && !WifiManager::isStationRepairPending(),
          "rejected auto policy change cannot start repair");
    CHECK(radio == std::vector<String>({"auto:off", "auto:on"}), "failed policy change never requests driver disconnect");
  } else if (scenario == "healthy_noop") {
    reservation = false;
    WifiManager::serviceRecovery(now_ms);
    CHECK(radio.empty() && reserve_calls == 0 && ap_starts == 0, "healthy service tick does not acquire admission or mutate radio");
  } else if (scenario.rfind("ordinary_", 0) == 0) {
    reservation = false;
    WiFi.associated = WL_DISCONNECTED;
    stationRecoveryPolicy.observe(0, false);
    wifiOutageNoticePending = true;
    now_ms = 30000;
    if (scenario == "ordinary_workers") workers_active = true;
    if (scenario == "ordinary_reservation") reservation_allowed = false;
    WifiManager::serviceRecovery(now_ms);
    if (scenario == "ordinary_recovery") {
      CHECK(radio == std::vector<String>({"auto:on"}) && ap_starts == 1 && release_calls == 1,
            "ordinary outage mutation uses and releases one reservation");
    } else {
      CHECK(radio.empty() && ap_starts == 0 && wifiOutageNoticePending,
            "ordinary outage preserves queued work until owners and admission are clear");
    }
  } else if (scenario == "raw_association") {
    WifiManager::connected = false;
    CHECK(WifiManager::isStationAssociated(), "raw association ignores stale cached connected flag");
    WiFi.associated = WL_DISCONNECTED;
    CHECK(!WifiManager::isStationAssociated(), "raw driver disconnect is visible");
  } else {
    if (scenario == "lease_wrap") now_ms = std::numeric_limits<uint32_t>::max() - 10000;
    beginAccepted();
    if (scenario == "pending_guard") {
      radio.clear();
      CHECK(!WifiManager::beginStationRepair() && radio.empty(), "pending repair cannot begin a second disconnect");
    } else if (scenario == "finish_before_edge") {
      radio.clear();
      CHECK(!WifiManager::finishStationRepair(false), "finish waits for disconnect observation or driver generation");
      CHECK(WifiManager::isStationRepairPending() && radio.empty(), "waiting is not a terminal or a second mutation");
    } else if (scenario == "finish_guard_reservation") {
      reservation = false; WiFi.associated = WL_DISCONNECTED; radio.clear();
      CHECK(!WifiManager::finishStationRepair(false) && radio.empty(), "finish mutation needs the owned reservation");
    } else if (scenario == "finish_guard_ap") {
      WifiManager::apModeActive = true; radio.clear();
      CHECK(!WifiManager::finishStationRepair(true) && radio.empty(), "operator AP wins over repair");
      CHECK(!WifiManager::isStationRepairPending(), "AP takeover releases owned repair state only");
    } else if (scenario == "stage_one" || scenario == "reconnect_rejected" || scenario == "short_disconnect_edge") {
      if (scenario == "short_disconnect_edge") ++driver_generation;
      else WiFi.associated = WL_DISCONNECTED;
      WiFi.reconnect_ok = scenario != "reconnect_rejected"; radio.clear();
      CHECK(WifiManager::finishStationRepair(false) == WiFi.reconnect_ok, "stage one reports request acceptance");
      CHECK(!WifiManager::isStationRepairPending(), "stage one clears pending on accepted or rejected request");
      CHECK(radio == std::vector<String>({"auto:on", "reconnect"}), "stage one only restores auto policy and requests reconnect once");
      if (scenario == "short_disconnect_edge")
        CHECK(WifiManager::isConnected(), "a short driver edge missed by loop polling cannot strand the cached connected flag");
    } else if (scenario == "cancel_false") {
      reservation = false; radio.clear();
      WifiManager::cancelStationRepair(false);
      CHECK(!WifiManager::isStationRepairPending() && radio.empty(), "AP/OTA cancellation changes owned repair state only");
    } else if (scenario == "cancel_true") {
      radio.clear(); WifiManager::cancelStationRepair(true);
      CHECK(!WifiManager::isStationRepairPending() && radio == std::vector<String>({"auto:on"}), "owned cancellation restores normal auto reconnect");
    } else if (scenario == "cancel_true_without_reservation") {
      reservation = false; radio.clear(); WifiManager::cancelStationRepair(true);
      CHECK(radio.empty() && WifiManager::isStationRepairPending(), "unreserved restore is deferred for finite lease recovery");
    } else if (scenario.rfind("lease_", 0) == 0) {
      WiFi.associated = WL_DISCONNECTED;
      stationRecoveryPolicy.observe(0, false);
      wifiOutageNoticePending = true;
      now_ms += 14999; radio.clear(); reservation = false;
      WifiManager::serviceRecovery(now_ms);
      CHECK(WifiManager::isStationRepairPending() && radio.empty() && ap_starts == 0, "pending lease suppresses ordinary auto/AP mutation");
      ++now_ms;
      if (scenario == "lease_workers") workers_active = true;
      if (scenario == "lease_reservation") reservation_allowed = false;
      if (scenario == "lease_local") { recoveryOperationLeaseActive = true; recoveryOperationLastActivityMs = now_ms; }
      WifiManager::serviceRecovery(now_ms);
      if (scenario == "lease_workers" || scenario == "lease_reservation") {
        CHECK(WifiManager::isStationRepairPending() && radio.empty(), "busy expiry keeps finite repair ownership for next safe call");
      } else if (scenario == "lease_local") {
        CHECK(!WifiManager::isStationRepairPending() && radio.empty(), "local takeover clears lease without restoring radio policy");
      } else {
        CHECK(!WifiManager::isStationRepairPending() && radio == std::vector<String>({"auto:on"}), "safe expiry restores only auto reconnect");
        CHECK(release_calls == 1 && !reservation && ap_starts == 0, "expiry releases admission and defers ordinary recovery to a later tick");
      }
    } else {
      WiFi.associated = WL_DISCONNECTED; radio.clear();
      if (scenario == "mode_off_failed") WiFi.off_ok = false;
      if (scenario == "mode_sta_failed") WiFi.sta_failures = 1;
      if (scenario == "begin_failed") WiFi.begin_status = WL_CONNECT_FAILED;
      const bool accepted = WifiManager::finishStationRepair(true);
      CHECK(!WifiManager::isStationRepairPending(), "stage two always releases pending state on a terminal result");
      if (scenario == "stage_two") {
        CHECK(accepted, "asynchronous idle begin is accepted");
        CHECK(radio == std::vector<String>({"mode:off", "mode:sta", "profile:scan", "profile:sort", "profile:sleep", "profile:protocol", "auto:on", "begin"}),
              "stage two restarts STA, reapplies compatibility, enables policy, then uses saved credentials");
      } else {
        CHECK(!accepted && WiFi.autoreconnect, "failed stage two restores normal recovery fallback");
        if (scenario == "mode_off_failed")
          CHECK(radio == std::vector<String>({"mode:off", "mode:sta", "auto:on"}), "OFF rejection gets one STA fallback and no begin");
        else if (scenario == "mode_sta_failed")
          CHECK(radio == std::vector<String>({"mode:off", "mode:sta", "mode:sta", "auto:on"}), "STA rejection gets only one bounded fallback");
        else
          CHECK(radio.size() == 8 && radio.back() == "begin", "begin rejection adds no extra radio retry");
      }
      CHECK(ap_starts == 0, "station repair does not tear down or replace recovery AP");
    }
  }
  std::printf("station repair %s PASS\n", scenario.c_str());
}
