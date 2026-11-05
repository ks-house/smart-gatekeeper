// Compile the actual DNS adapter against deterministic Arduino/lwIP boundaries.
#include "MqttDnsPolicy.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#define CHECK(condition, message) do { if (!(condition)) { \
  std::fprintf(stderr, "DNS adapter FAIL line %d: %s\n", __LINE__, message); \
  std::exit(1); } } while (0)

using portMUX_TYPE = int;
#define portMUX_INITIALIZER_UNLOCKED 0
int mux_depth = 0, core_depth = 0, core_enters = 0, core_exits = 0;
void enterMux(void*) { CHECK(++mux_depth == 1, "DNS mux is not recursively owned"); }
void leaveMux(void*) { CHECK(--mux_depth == 0, "DNS mux release is balanced"); }
void lockCore() { CHECK(++core_depth == 1 && mux_depth == 0, "resolver owns TCP/IP core outside DNS mux"); ++core_enters; }
void unlockCore() { CHECK(--core_depth == 0, "TCP/IP core release is balanced"); ++core_exits; }
#define portENTER_CRITICAL(mux) enterMux(mux)
#define portEXIT_CRITICAL(mux) leaveMux(mux)
#define LOCK_TCPIP_CORE() lockCore()
#define UNLOCK_TCPIP_CORE() unlockCore()

uint32_t now_ms = 100;
uint32_t millis() { return now_ms; }
constexpr uint32_t MQTT_DNS_RESOLVE_TIMEOUT_MS = 5000;
constexpr char MQTT_HOST[] = "broker.fixture.invalid";
struct ip_addr_t { uint32_t value = 0; };
void ip_addr_set_zero(ip_addr_t* address) { address->value = 0; }
bool ip_addr_isany(const ip_addr_t* address) { return address->value == 0; }
#define ip_addr_copy(destination, source) ((destination) = (source))

class IPAddress {
 public:
  IPAddress() = default;
  explicit IPAddress(const ip_addr_t* address) : value(address->value) {}
  bool fromString(const char* host) {
    CHECK(std::strcmp(host, MQTT_HOST) == 0, "configured hostname is unchanged");
    return false;
  }
  uint32_t value = 0;
};
class DiagnosticsManager {
 public:
  static void noteAction(const char*) {}
};
using err_t = int;
constexpr err_t ERR_OK = 0, ERR_INPROGRESS = 1, ERR_VAL = -6;
constexpr int LWIP_DNS_ADDRTYPE_DEFAULT = 0;
using DnsCallback = void (*)(const char*, const ip_addr_t*, void*);
struct Query { DnsCallback callback; void* argument; };
std::vector<Query> queries;
err_t resolver_result = ERR_INPROGRESS;
constexpr uint32_t kImmediateAddress = 17;

err_t dns_gethostbyname_addrtype(const char* host, ip_addr_t* immediate,
                               DnsCallback callback, void* argument, int type) {
  CHECK(core_depth == 1 && mux_depth == 0, "query runs under TCP/IP core only");
  CHECK(std::strcmp(host, MQTT_HOST) == 0 && type == 0, "resolver retains configured host and address family");
  queries.push_back({callback, argument});
  if (resolver_result == ERR_OK) immediate->value = kImmediateAddress;
  return resolver_result;
}

// These declarations and functions are extracted verbatim from MqttManager.cpp.
#include "mqtt_dns_adapter_production.inc"

void deliver(size_t query, uint32_t address) {
  CHECK(query < queries.size(), "callback belongs to an issued query");
  const ip_addr_t resolved{address};
  queries[query].callback(MQTT_HOST, address == 0 ? nullptr : &resolved, queries[query].argument);
  CHECK(mux_depth == 0 && core_depth == 0, "callback returns with all locks released");
}
void checkLocks() {
  CHECK(mux_depth == 0 && core_depth == 0, "main returns with all locks released");
  CHECK(core_enters == core_exits && core_enters == static_cast<int>(queries.size()),
        "each resolver call balances one core lock and unlock");
}
int main(int argc, char** argv) {
  CHECK(argc == 2, "one closed fixture scenario required");
  const std::string scenario = argv[1];
  IPAddress output;
  output.value = 999;
  resetMqttDnsResolution();
  if (scenario == "immediate_error_once") {
    resolver_result = ERR_VAL;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kFailed, "immediate error reports one failure");
    CHECK(queries.size() == 1 && output.value == 999, "failed query cannot write an address");
    resolver_result = ERR_INPROGRESS;
    ++now_ms;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending,
          "next attempt starts a query instead of returning the same immediate error twice");
    CHECK(queries.size() == 2, "immediate failure was consumed before a new query");
  } else if (scenario == "callback_at_deadline" || scenario == "callback_after_deadline") {
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending, "initial asynchronous query is pending");
    now_ms = scenario == "callback_at_deadline" ? 5100 : 5101;
    deliver(0, 23); // Arrives before main gets its first opportunity to poll timeout.
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kFailed,
          "a callback at/after the five-second deadline must not become Ready");
    CHECK(output.value == 999, "late callback must not copy a broker address");
    ++now_ms;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending && queries.size() == 2,
          "deadline failure is consumed once before a new query");
  } else if (scenario == "stale_after_reset") {
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending, "first query starts");
    resetMqttDnsResolution();
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending && queries.size() == 2, "reset permits a new query");
    ++now_ms;
    deliver(0, 99);
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending && output.value == 999,
          "old-generation callback cannot complete or overwrite the new query");
    deliver(1, 23);
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kReady && output.value == 23,
          "current-generation callback supplies the address");
  } else if (scenario == "stale_after_timeout") {
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending, "first query starts");
    now_ms = 5100;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kFailed, "pending deadline reports failure");
    ++now_ms;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending && queries.size() == 2, "timeout is consumed once");
    deliver(0, 99);
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending && output.value == 999,
          "old timeout callback cannot become the new broker address");
    deliver(1, 23);
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kReady && output.value == 23, "new callback succeeds");
  } else if (scenario == "async_failure_once") {
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending, "query starts");
    ++now_ms;
    deliver(0, 0);
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kFailed, "null result reports one failure");
    ++now_ms;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending && queries.size() == 2,
          "null callback failure is consumed once");
  } else if (scenario == "ready_cache") {
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending, "query starts");
    now_ms = 5099;
    deliver(0, 23);
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kReady && output.value == 23, "fresh callback succeeds");
    now_ms = 500000;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kReady && queries.size() == 1,
          "ready address is retained until explicit reset");
  } else if (scenario == "immediate_success") {
    resolver_result = ERR_OK;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kReady && output.value == kImmediateAddress,
          "synchronous cache success retains address");
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kReady && queries.size() == 1,
          "synchronous success does not trigger duplicate lookup");
  } else if (scenario == "millis_wrap") {
    now_ms = std::numeric_limits<uint32_t>::max() - 2499;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending, "query starts before millis wraps");
    now_ms = 2499;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kPending, "one millisecond before wrapped deadline remains pending");
    now_ms = 2500;
    CHECK(pollMqttDns(&output) == MqttDnsPollResult::kFailed, "wrapped deadline is real");
    deliver(0, 99);
    CHECK(output.value == 999, "wrapped timeout cannot publish an address");
  } else {
    CHECK(scenario == "null_output", "known scenario");
    CHECK(pollMqttDns(nullptr) == MqttDnsPollResult::kFailed && queries.empty(),
          "null output cannot start a resolver query");
  }
  checkLocks();
  std::printf("MQTT DNS adapter %s PASS\n", scenario.c_str());
}
