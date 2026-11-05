// The driver, transport-owner expression and service wrapper are generated
// verbatim from MqttManager.cpp. Only platform/owner boundaries are stubbed.
#include "NetworkRecoveryController.h"
#include "NetworkRecoveryPolicy.h"
#include "TargetState.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <string>
#include <vector>

#define CHECK(condition, message) do { if (!(condition)) { \
  std::fprintf(stderr, "FAIL: %s (line %d)\n", message, __LINE__); std::exit(1); \
} } while (0)

using Policy = sgk::NetworkRecoveryPolicy;
using Action = Policy::Action;

struct Fixture {
  bool ap = false, local = false, gatt_ota = false, watchdog = true;
  bool connect_owner = false, telemetry_owner = false, ingress_owner = false;
  bool tracker = false, gatt_connected = false, gatt_ingress = false, gatt_output = false;
  bool associated = true, pending_repair = false, reservation_allowed = true, reserved = false;
  bool begin_ok = true, finish_ok = true;
  int ota_status = 0;
  OtaSafeState physical = OtaSafeState::SAFE;
  uint32_t now = 60000, generation = 1;
  unsigned reserve_calls = 0, release_calls = 0, dns_resets = 0, socket_stops = 0;
  unsigned begin_calls = 0, finish_calls = 0, cancel_true = 0, cancel_false = 0;
  std::vector<bool> restart_arguments;
  std::vector<std::string> events;
  std::function<void()> after_reserve;
} fixture;

uint32_t millis() { return fixture.now; }
bool otaTransportSuspended = false;
bool signedRestartPending = false;
bool wifiAvailableLastUpdate = true;
struct PendingSignedAccessCommand { bool ready = false; } pendingSignedAccessCommand;
struct SignedTracker { bool active() const { return fixture.tracker; } } signedCommandAccessTracker;
struct TransportOwner {
  bool* owns;
  bool ownsTransport() const { return *owns; }
};
TransportOwner telemetryWorker{&fixture.telemetry_owner};
TransportOwner ingressWorker{&fixture.ingress_owner};
bool connectWorkerIsRunning() { return fixture.connect_owner; }
sgk::NetworkRecoveryPolicy networkRecovery;
sgk::NetworkRecoveryController networkRecoveryController;

class OtaManager {
 public:
#include "mqtt_network_driver_ota_enum.inc"
  static OtaStatus getStatus() { return static_cast<OtaStatus>(fixture.ota_status); }
  static bool isSafeForOta() { return fixture.physical == OtaSafeState::SAFE; }
};

class DiagnosticsManager {
 public:
  static bool loopWatchdogEnabled() { return fixture.watchdog; }
};
class GattServer {
 public:
  static bool isOtaBusy() { return fixture.gatt_ota; }
  static bool isConnected() { return fixture.gatt_connected; }
  static bool hasPendingIngress() { return fixture.gatt_ingress; }
  static bool hasActiveOutput() { return fixture.gatt_output; }
  static bool tryReserveIdleRadio() {
    ++fixture.reserve_calls; fixture.events.push_back("reserve");
    if (!fixture.reservation_allowed) return false;
    CHECK(!fixture.reserved, "reservation has exactly one owner");
    fixture.reserved = true;
    if (fixture.after_reserve) {
      auto hook = fixture.after_reserve; fixture.after_reserve = {}; hook();
    }
    return true;
  }
  static void releaseIdleRadio() {
    CHECK(fixture.reserved, "only owned reservation released");
    fixture.reserved = false;
    ++fixture.release_calls; fixture.events.push_back("release");
  }
};
class WifiManager {
 public:
  static bool isAPMode() { return fixture.ap; }
  static bool isLocalRecoveryActive() { return fixture.local; }
  static bool isStationAssociated() { return fixture.associated; }
  static uint32_t linkGeneration() { return fixture.generation; }
  static bool isStationRepairPending() { return fixture.pending_repair; }
  static bool beginStationRepair() {
    CHECK(fixture.reserved, "disconnect forwarded under reservation");
    CHECK(fixture.events.size() >= 3 && fixture.events[fixture.events.size()-2] == "dns" &&
          fixture.events.back() == "stop", "DNS and socket invalidated before disconnect");
    ++fixture.begin_calls; fixture.events.push_back("disconnect");
    fixture.pending_repair = fixture.begin_ok;
    return fixture.begin_ok;
  }
  static bool finishStationRepair(bool restart) {
    CHECK(fixture.reserved, "reconnect forwarded under reservation");
    ++fixture.finish_calls; fixture.restart_arguments.push_back(restart);
    fixture.events.push_back(restart ? "restart-sta" : "reassociate");
    fixture.pending_repair = false;
    if (fixture.finish_ok) { fixture.associated = true; ++fixture.generation; }
    return fixture.finish_ok;
  }
  static void cancelStationRepair(bool restore_auto) {
    if (restore_auto) {
      CHECK(fixture.reserved, "auto policy restoration requires reservation");
      ++fixture.cancel_true; fixture.events.push_back("restore");
    } else {
      ++fixture.cancel_false; fixture.events.push_back("clear-own-flag");
    }
    fixture.pending_repair = false;
  }
};
class FakeSocket {
 public:
  void stop() {
    CHECK(fixture.reserved, "socket invalidation requires reservation");
    ++fixture.socket_stops; fixture.events.push_back("stop");
  }
};
class MqttManager {
 public:
  struct NetworkRecoveryDriver;
  static bool transportWorkersActive();
  static bool serviceNetworkRecovery();
  static FakeSocket wifiClient;
  static bool connected;
};
FakeSocket MqttManager::wifiClient;
bool MqttManager::connected = true;
void resetMqttDnsResolution() {
  CHECK(fixture.reserved, "DNS invalidation requires reservation");
  ++fixture.dns_resets; fixture.events.push_back("dns");
}

#include "mqtt_network_driver_actual.inc"

void resetFixture() {
  fixture = Fixture{};
  otaTransportSuspended = false;
  signedRestartPending = false;
  pendingSignedAccessCommand.ready = false;
  wifiAvailableLastUpdate = true;
  MqttManager::connected = true;
  networkRecovery = Policy{};
  networkRecoveryController = sgk::NetworkRecoveryController{};
}
void qualify(uint32_t start = 0, uint32_t generation = 1) {
  networkRecovery.failure(Policy::FailureKind::kDns, start, generation);
  networkRecovery.failure(Policy::FailureKind::kDns, start + 30000, generation);
  networkRecovery.failure(Policy::FailureKind::kDns, start + 60000, generation);
}
void checkNoMutation(const char* name) {
  CHECK(fixture.dns_resets == 0 && fixture.socket_stops == 0 && fixture.begin_calls == 0 &&
        fixture.finish_calls == 0 && fixture.cancel_true == 0 && fixture.cancel_false == 0,
        name);
  CHECK(!fixture.reserved && fixture.reserve_calls == fixture.release_calls,
        "all acquired admission tokens released");
}

struct OtaCase { const char* name; OtaManager::OtaStatus value; };
const OtaCase ota_cases[] = {
#include "mqtt_network_driver_ota_cases.inc"
};
bool quiescent(OtaManager::OtaStatus state) {
  using State = OtaManager::OtaStatus;
  return state == State::IDLE || state == State::UP_TO_DATE ||
         state == State::SUCCESS || state == State::FAILED;
}

struct GuardCase { const char* name; void (*set)(bool); bool external; };
const GuardCase guards[] = {
  {"AP", [](bool on) { fixture.ap = on; }, true},
  {"local recovery", [](bool on) { fixture.local = on; }, true},
  {"suspended MQTT for OTA", [](bool on) { otaTransportSuspended = on; }, true},
  {"GATT OTA busy", [](bool on) { fixture.gatt_ota = on; }, true},
  {"missing loop watchdog", [](bool on) { fixture.watchdog = !on; }, false},
  {"connect worker", [](bool on) { fixture.connect_owner = on; }, false},
  {"telemetry worker", [](bool on) { fixture.telemetry_owner = on; }, false},
  {"ingress worker", [](bool on) { fixture.ingress_owner = on; }, false},
  {"signed restart", [](bool on) { signedRestartPending = on; }, false},
  {"pending signed command", [](bool on) { pendingSignedAccessCommand.ready = on; }, false},
  {"active signed tracker", [](bool on) { fixture.tracker = on; }, false},
  {"physical access session", [](bool on) { fixture.physical = on ? OtaSafeState::ACCESS_SESSION_ACTIVE : OtaSafeState::SAFE; }, false},
  {"physical relay", [](bool on) { fixture.physical = on ? OtaSafeState::RELAY_ACTIVE : OtaSafeState::SAFE; }, false},
  {"GATT connection", [](bool on) { fixture.gatt_connected = on; }, false},
  {"GATT ingress", [](bool on) { fixture.gatt_ingress = on; }, false},
  {"GATT output", [](bool on) { fixture.gatt_output = on; }, false},
};

void testOtaStates() {
  unsigned checked = 0;
  for (const auto& test : ota_cases) {
    resetFixture(); qualify(); fixture.ota_status = static_cast<int>(test.value);
    MqttManager::NetworkRecoveryDriver driver;
    CHECK(driver.externalRecoveryActive() == !quiescent(test.value), test.name);
    CHECK(driver.safeForRepair() == quiescent(test.value), test.name);
    const bool active = MqttManager::serviceNetworkRecovery();
    if (quiescent(test.value)) CHECK(active && fixture.begin_calls == 1, test.name);
    else { CHECK(!active, test.name); checkNoMutation(test.name); }
    ++checked;
  }
  std::printf("actual nested driver OTA enum PASS (%u states)\n", checked);
}

void testGuards() {
  unsigned checked = 0;
  for (const auto& test : guards) {
    resetFixture(); qualify(); test.set(true);
    MqttManager::NetworkRecoveryDriver driver;
    CHECK(!driver.safeForRepair(), test.name);
    CHECK(driver.externalRecoveryActive() == test.external, test.name);
    CHECK(!MqttManager::serviceNetworkRecovery(), test.name);
    checkNoMutation(test.name);
    ++checked;
    resetFixture(); qualify();
    fixture.after_reserve = [&] { test.set(true); };
    CHECK(!MqttManager::serviceNetworkRecovery(), test.name);
    CHECK(fixture.reserve_calls == 1 && fixture.release_calls == 1, test.name);
    checkNoMutation(test.name);
    ++checked;
  }
  for (const auto& test : ota_cases) {
    if (quiescent(test.value)) continue;
    resetFixture(); qualify();
    fixture.after_reserve = [&] { fixture.ota_status = static_cast<int>(test.value); };
    CHECK(!MqttManager::serviceNetworkRecovery(), test.name);
    checkNoMutation(test.name);
    ++checked;
  }
  // The production physical-state classifier drives both session and relay
  // boundaries; none of its unsafe combinations may admit station mutation.
  for (const auto state : {GateState::IDLE, GateState::AUTH_PENDING, GateState::ARMED,
                           GateState::RELAY_HOLD, GateState::COOLDOWN}) {
    for (const bool armed : {false, true}) {
      for (const bool relay : {false, true}) {
        resetFixture(); qualify(); fixture.physical = classifyOtaSafeState(state, armed, relay);
        if (fixture.physical == OtaSafeState::SAFE) continue;
        CHECK(!MqttManager::serviceNetworkRecovery(), "unsafe physical combination");
        checkNoMutation("unsafe physical combination");
        ++checked;
      }
    }
  }
  std::printf("actual nested driver guard/race PASS (%u cases)\n", checked);
}

void testWaiting() {
  unsigned checked = 0;
  for (const auto& test : guards) {
    resetFixture(); qualify();
    CHECK(MqttManager::serviceNetworkRecovery(), "enter actual-driver pending phase");
    test.set(true); fixture.associated = false; ++fixture.now;
    const bool active = MqttManager::serviceNetworkRecovery();
    CHECK(fixture.finish_calls == 0 && fixture.cancel_true == 0, test.name);
    if (test.external) {
      CHECK(!active && !networkRecoveryController.active() && fixture.cancel_false == 1,
            "external owner receives no radio-authority restoration");
    } else {
      CHECK(active && networkRecoveryController.active() && fixture.cancel_false == 0, test.name);
      test.set(false);
      CHECK(!MqttManager::serviceNetworkRecovery(), "safe pending phase resumes once");
      CHECK(fixture.finish_calls == 1, "one reconnect after safe resumption");
    }
    CHECK(!fixture.reserved && fixture.reserve_calls == fixture.release_calls, test.name);
    ++checked;
  }
  for (const auto& test : ota_cases) {
    if (quiescent(test.value)) continue;
    resetFixture(); qualify(); CHECK(MqttManager::serviceNetworkRecovery(), "begin OTA takeover fixture");
    fixture.ota_status = static_cast<int>(test.value); fixture.associated = false; ++fixture.now;
    CHECK(!MqttManager::serviceNetworkRecovery(), test.name);
    CHECK(fixture.finish_calls == 0 && fixture.cancel_true == 0 && fixture.cancel_false == 1,
          "active OTA only clears the repair's own pending flag");
    ++checked;
  }
  std::printf("actual nested driver waiting guards PASS (%u cases)\n", checked);
}

void testForwarding() {
  resetFixture(); qualify();
  CHECK(MqttManager::serviceNetworkRecovery(), "actual wrapper starts controller");
  CHECK(fixture.events == std::vector<std::string>({"reserve", "dns", "stop", "disconnect", "release"}),
        "actual driver resets DNS and socket before asynchronous disconnect");
  CHECK(!MqttManager::connected && !wifiAvailableLastUpdate, "both adopted transport flags invalidated");
  fixture.associated = false; ++fixture.now;
  CHECK(!MqttManager::serviceNetworkRecovery(), "raw disassociation permits stage one");
  CHECK(fixture.finish_calls == 1 && fixture.restart_arguments == std::vector<bool>({false}),
        "stage one forwards restartInterface=false");
  qualify(60002, fixture.generation); fixture.now = 180000;
  CHECK(MqttManager::serviceNetworkRecovery(), "continued failures start stage two");
  ++fixture.generation; ++fixture.now; fixture.associated = true;
  CHECK(!MqttManager::serviceNetworkRecovery(), "changed associated generation still executes stage two");
  CHECK(fixture.restart_arguments == std::vector<bool>({false, true}),
        "stage two forwards restartInterface=true");

  resetFixture(); MqttManager::NetworkRecoveryDriver driver;
  fixture.generation = 99; fixture.associated = false; fixture.pending_repair = true;
  CHECK(driver.nowMillis() == fixture.now && driver.linkGeneration() == 99 &&
        !driver.stationAssociated() && driver.ownsStationRepair(), "raw driver snapshots forwarded");
  driver.cancelRepair(false);
  CHECK(fixture.cancel_false == 1 && fixture.cancel_true == 0 && fixture.reserve_calls == 0,
        "false cancellation grants no radio authority");
  fixture.reservation_allowed = false;
  CHECK(!driver.tryReserve() && fixture.release_calls == 0, "reservation refusal forwarded");
  fixture.reservation_allowed = true;
  CHECK(driver.tryReserve(), "reservation acceptance forwarded");
  fixture.finish_ok = false; fixture.pending_repair = true;
  CHECK(!driver.finishReconnect(Action::kRestartStationInterface), "finish failure forwarded");
  fixture.begin_ok = false;
  driver.invalidateTransport();
  CHECK(!driver.beginDisconnect(), "disconnect failure forwarded");
  driver.release();
  CHECK(!fixture.reserved && fixture.reserve_calls == fixture.release_calls + 1,
        "only accepted reservations are released");
  std::puts("actual nested driver forwarding/order/stage PASS");
}


void testObservedGeneration() {
  resetFixture(); qualify();
  ++fixture.generation;
  CHECK(!MqttManager::serviceNetworkRecovery(),
        "new associated Wi-Fi generation cannot spend old failure qualification");
  checkNoMutation("no repair manufactured on a naturally recovered link");
  qualify(60001, fixture.generation); fixture.now = 120001;
  CHECK(MqttManager::serviceNetworkRecovery(), "fresh same-link evidence can repair new generation");
  resetFixture(); qualify();
  fixture.after_reserve = [] { ++fixture.generation; };
  CHECK(!MqttManager::serviceNetworkRecovery(),
        "generation changing during admission cannot consume old selection");
  checkNoMutation("post-reservation new link has no socket/radio mutation");
  CHECK(fixture.reserve_calls == 1 && fixture.release_calls == 1,
        "generation race releases admission without committing budget");
  CHECK(!networkRecovery.commitAction(fixture.now), "stale generation selection invalidated");
  std::puts("actual nested driver generation observation PASS");
}

int main(int argc, char** argv) {
  CHECK(argc == 2, "one closed fixture scenario required");
  const std::string scenario(argv[1]);
  if (scenario == "ota") testOtaStates();
  else if (scenario == "guards") testGuards();
  else if (scenario == "waiting") testWaiting();
  else if (scenario == "forwarding") testForwarding();
  else if (scenario == "generation") testObservedGeneration();
  else CHECK(false, "unknown fixture scenario");
}
