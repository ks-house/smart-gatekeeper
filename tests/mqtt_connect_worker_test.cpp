// Execute the production connect entrypoint and ownership helpers with closed,
// deterministic platform boundaries. This does not emulate a radio or TLS stack.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#define CHECK(condition, message) do { if (!(condition)) { \
  std::fprintf(stderr, "FAIL: %s (line %d)\n", message, __LINE__); \
  std::exit(1); } } while (0)
#define LOGF(...) do { std::printf(__VA_ARGS__); std::putchar(10); } while (0)
using esp_err_t = int;
constexpr esp_err_t ESP_OK = 0;
constexpr esp_err_t kWatchdogFailure = -17;
using portMUX_TYPE = int;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(mux) ((void)(mux))
#define portEXIT_CRITICAL(mux) ((void)(mux))

struct IPAddress { int fixture = 17; };
constexpr int MQTT_CONNECT_FAILED = -2;
constexpr int MQTT_PORT = 4883;
constexpr char MQTT_HOST[] = "broker.fixture.invalid";
constexpr char MQTT_USER[] = "fixture-user";
constexpr char MQTT_PASSWORD[] = "fixture-password";
constexpr char SECRET_ROOT_CA_CERT[] = "fixture-ca";
std::string commandTopic = "fixture/command";
std::string aclTopic = "fixture/acl";
std::string availabilityTopic = "fixture/availability";

uint32_t now_ms = 100;
uint32_t driver_generation = 7;
uint32_t mqttConnectWorkerWatchdogFailures = 0;
int add_result = ESP_OK, reset_failure_at = 0, delete_result = ESP_OK;
int adds = 0, resets = 0, deletes = 0, task_deletes = 0, stops = 0;
int tls_calls = 0, mqtt_calls = 0, subscribe_calls = 0, publish_calls = 0;
bool tls_ok = true, mqtt_ok = true;
std::string cancel_after, change_link_after;
std::vector<std::string> transport_calls;

uint32_t millis() { return ++now_ms; }
class WifiManager {
 public:
  static uint32_t linkGeneration() { return driver_generation; }
};
class DiagnosticsManager {
 public:
  static const char* targetId() { return "fixture-target"; }
  static const char* bootId() { return "fixture-boot"; }
  static uint32_t bootCount() { return 1; }
};
class FakeTls {
 public:
  int connect(const IPAddress&, int, const char*, const char*, void*, void*);
  void stop() { ++stops; }
};
class FakeMqtt {
 public:
  bool connect(const char*, const char*, const char*, const char*, int, bool, const char*);
  bool subscribe(const char*, int);
  bool publish(const char*, const char*, bool);
  int state() { return -4; }
};
class MqttManager {
 public:
  static FakeTls wifiClient;
  static FakeMqtt client;
  static void connectWorkerEntry(void*);
};
FakeTls MqttManager::wifiClient;
FakeMqtt MqttManager::client;

// Generated verbatim from the production state structs and handoff helpers.
#include "mqtt_connect_worker_state.inc"

void phaseCompleted(const char* phase) {
  if (cancel_after == phase) requestConnectWorkerCancellation();
  if (change_link_after == phase) ++driver_generation;
}
int FakeTls::connect(const IPAddress& address, int port, const char* host,
                     const char* ca, void*, void*) {
  CHECK(address.fixture == 17 && port == 4883, "TLS uses resolved address and configured port");
  CHECK(std::strcmp(host, MQTT_HOST) == 0 && std::strcmp(ca, SECRET_ROOT_CA_CERT) == 0,
        "TLS retains configured hostname and CA");
  ++tls_calls;
  transport_calls.push_back("tls");
  phaseCompleted("tls");
  return tls_ok ? 1 : 0;
}
bool FakeMqtt::connect(const char*, const char* user, const char* password,
                      const char* topic, int qos, bool retained, const char*) {
  CHECK(std::strcmp(user, MQTT_USER) == 0 && std::strcmp(password, MQTT_PASSWORD) == 0,
        "MQTT uses configured principal");
  CHECK(availabilityTopic == topic && qos == 1 && retained, "MQTT retains offline LWT");
  ++mqtt_calls;
  transport_calls.push_back("mqtt");
  phaseCompleted("mqtt");
  return mqtt_ok;
}
bool FakeMqtt::subscribe(const char* topic, int qos) {
  CHECK(qos == 1, "subscription qos retained");
  ++subscribe_calls;
  const char* phase = commandTopic == topic ? "command" : "acl";
  CHECK(commandTopic == topic || aclTopic == topic, "only exact Target topics subscribed");
  transport_calls.push_back(phase);
  phaseCompleted(phase);
  return true;
}
bool FakeMqtt::publish(const char* topic, const char* payload, bool retained) {
  CHECK(availabilityTopic == topic && retained, "only retained availability published");
  CHECK(std::strstr(payload, "mqtt_transport") != nullptr, "availability keeps transport-only scope");
  ++publish_calls;
  transport_calls.push_back("publish");
  phaseCompleted("publish");
  return true;
}
esp_err_t esp_task_wdt_add(void*) { ++adds; return add_result; }
esp_err_t esp_task_wdt_reset() {
  ++resets;
  return resets == reset_failure_at ? kWatchdogFailure : ESP_OK;
}
esp_err_t esp_task_wdt_delete(void*) { ++deletes; return delete_result; }
const char* esp_err_to_name(esp_err_t) { return "fixture-error"; }
void vTaskDelete(void*) {
  CHECK(!connectWorkerIsRunning(), "task exits only after relinquishing transport ownership");
  ++task_deletes;
}

// Generated verbatim from MqttManager::connectWorkerEntry.
#include "mqtt_connect_worker_entry.inc"

MqttConnectResult runWorker() {
  mqttConnectWorkerRunning = true;
  mqttConnectWorkerRequestId = 11;
  mqttConnectWorkerResultReady = false;
  auto* request = new MqttConnectRequest{};
  request->request_id = 11;
  request->wifi_link_generation = 7;
  std::strcpy(request->client_id, "fixture-client");
  std::strcpy(request->will_payload, "offline");
  MqttManager::connectWorkerEntry(request);
  CHECK(!connectWorkerIsRunning(), "terminal path releases exclusive transport owner");
  CHECK(task_deletes == 1, "worker task terminates once");
  MqttConnectResult result{};
  CHECK(takeConnectWorkerResult(&result), "terminal result is available for main adoption");
  CHECK(!takeConnectWorkerResult(&result), "terminal result can be consumed only once");
  CHECK(result.request_id == 11 && result.wifi_link_generation == 7,
        "terminal result preserves request and Wi-Fi generation identity");
  return result;
}
void checkWatchdogAbort(const MqttConnectResult& result) {
  CHECK(result.outcome != MqttConnectOutcome::kSuccess, "watchdog failure cannot be adopted as success");
  CHECK(result.watchdog_error == kWatchdogFailure, "first watchdog failure is retained");
  CHECK(connectWorkerWatchdogFailuresSnapshot() == 1, "watchdog failure counted once per attempt");
  CHECK(stops == 0, "unmonitored transport cleanup is returned to the monitored main owner");
}
int main(int argc, char** argv) {
  CHECK(argc == 2, "one fixture scenario required");
  const std::string scenario = argv[1];
  if (scenario == "watchdog_add_failed") {
    add_result = kWatchdogFailure;
    const auto result = runWorker();
    CHECK(tls_calls == 0 && mqtt_calls == 0 && subscribe_calls == 0 && publish_calls == 0,
          "watchdog enrollment failure must prevent all TLS/MQTT socket I/O");
    checkWatchdogAbort(result);
    CHECK(deletes == 0, "failed enrollment is not deleted as an owned watchdog entry");
  } else if (scenario.rfind("watchdog_reset_", 0) == 0) {
    reset_failure_at = std::atoi(scenario.substr(std::strlen("watchdog_reset_")).c_str());
    CHECK(reset_failure_at >= 1 && reset_failure_at <= 6, "known watchdog phase");
    const auto result = runWorker();
    CHECK(tls_calls == 1, "TLS phase reached once");
    CHECK(mqtt_calls == (reset_failure_at >= 2 ? 1 : 0), "reset failure must gate the next MQTT connect");
    CHECK(subscribe_calls == (reset_failure_at >= 4 ? 2 : reset_failure_at >= 3 ? 1 : 0),
          "reset failure must gate each subsequent subscription");
    CHECK(publish_calls == (reset_failure_at >= 5 ? 1 : 0), "reset failure must gate availability publication");
    checkWatchdogAbort(result);
    CHECK(deletes == 1, "watchdog enrollment released on a reset failure");
  } else if (scenario == "watchdog_delete_failed") {
    delete_result = kWatchdogFailure;
    const auto result = runWorker();
    checkWatchdogAbort(result);
    CHECK(deletes == 1, "watchdog release failure remains a terminal resource error");
  } else if (scenario.rfind("cancel_", 0) == 0 || scenario.rfind("link_", 0) == 0) {
    const bool cancellation = scenario.rfind("cancel_", 0) == 0;
    const std::string phase = scenario.substr(cancellation ? 7 : 5);
    if (phase == "before") {
      if (cancellation) mqttConnectWorkerCancelRequested = true;
      else ++driver_generation;
    } else {
      if (cancellation) cancel_after = phase;
      else change_link_after = phase;
    }
    const auto result = runWorker();
    CHECK(result.outcome == MqttConnectOutcome::kStale, "cancellation or old link result remains stale");
    CHECK(tls_calls == (phase == "before" ? 0 : 1), "stale entry cannot begin TLS");
    CHECK(mqtt_calls == (phase == "before" || phase == "tls" ? 0 : 1), "stale TLS cannot begin MQTT");
    CHECK(subscribe_calls == (phase == "command" ? 1 :
          phase == "acl" || phase == "publish" ? 2 : 0), "stale phase cannot write later subscriptions");
    CHECK(publish_calls == (phase == "publish" ? 1 : 0), "stale phase cannot publish online availability");
    CHECK(stops == 1 && deletes == 1, "stale terminal path closes socket and releases watchdog");
  } else if (scenario == "tls_failed" || scenario == "mqtt_failed") {
    tls_ok = scenario != "tls_failed";
    mqtt_ok = false;
    const auto result = runWorker();
    CHECK(result.outcome == (tls_ok ? MqttConnectOutcome::kMqttFailed : MqttConnectOutcome::kTlsFailed),
          "transport failure retains exact failed phase");
    CHECK(mqtt_calls == (tls_ok ? 1 : 0) && subscribe_calls == 0 && publish_calls == 0,
          "failed transport cannot reach subscriptions or availability");
    CHECK(stops == 1 && deletes == 1, "transport failure closes socket and releases watchdog");
  } else {
    CHECK(scenario == "success", "known fixture scenario");
    const auto result = runWorker();
    CHECK(result.outcome == MqttConnectOutcome::kSuccess && result.watchdog_error == ESP_OK,
          "healthy handshake returns adoptable success");
    CHECK(transport_calls == std::vector<std::string>({"tls", "mqtt", "command", "acl", "publish"}),
          "healthy handshake preserves exact connection and subscription ordering");
    CHECK(stops == 0 && adds == 1 && deletes == 1, "successful worker hands live socket back after watchdog cleanup");
  }
  std::printf("connect worker scenario %s PASS\n", scenario.c_str());
}
