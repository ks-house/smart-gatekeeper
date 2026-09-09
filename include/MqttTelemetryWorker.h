#pragma once

#include <PubSubClient.h>
#include <freertos/FreeRTOS.h>

#include <cstdint>
#include <cstddef>

namespace sgk {

// One immutable publish at a time, with explicit transport ownership handoff.
// The main loop must not access PubSubClient/TLS until takeResult succeeds.
// This worker never invokes client.loop(), command callbacks, or gate control.
class MqttTelemetryWorker {
 public:
  static constexpr size_t kMaxPayloadBytes = 6656;
  struct Result {
    uint32_t generation = 0;
    uint32_t duration_ms = 0;
    bool published = false;
    bool transport_connected = false;
    bool watchdog_healthy = false;
  };

  bool start(PubSubClient& client, const char* topic, const char* payload,
             uint32_t generation);
  bool ownsTransport();
  bool takeResult(Result* result);

 private:
  struct Request;
  static void run(void* argument);
  portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
  bool running_ = false;
  bool ready_ = false;
  Result result_{};
};

}  // namespace sgk
