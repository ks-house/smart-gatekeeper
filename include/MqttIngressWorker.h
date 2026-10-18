#pragma once

#include <PubSubClient.h>
#include <freertos/FreeRTOS.h>
#include <cstddef>
#include <cstdint>

namespace sgk {

// One bounded MQTT receive pass on the existing socket. The callback only
// copies a packet; authorization, replay storage and effects remain on main.
// Ownership includes the ready result until main explicitly takes it.
class MqttIngressWorker {
 public:
  static constexpr size_t kTopicBytes = 160;
  static constexpr size_t kPayloadBytes = 1536;
  static constexpr size_t kReplyBytes = 384;
  struct Packet {
    char topic[kTopicBytes]{};
    uint8_t payload[kPayloadBytes]{};
    size_t length = 0;
    bool truncated = false;
  };
  struct Result {
    bool received = false;
    bool serviced = false;
    bool connected = false;
    bool watchdog_healthy = false;
    bool reply_attempted = false;
    bool reply_published = false;
    uint32_t duration_ms = 0;
  };

  static bool pollDue(uint32_t now, uint32_t last, uint32_t delay) {
    return static_cast<uint32_t>(now - last) >= delay;
  }

  bool start(PubSubClient& client, const char* reply_topic = nullptr,
             const char* reply_payload = nullptr, bool poll_inbound = true);
  // Called only from the PubSubClient callback. True means the callback was
  // intercepted, including an invalid/oversized frame; it must not do effects.
  bool capture(const char* topic, const uint8_t* payload, size_t length);
  bool ownsTransport();
  bool takeResult(Result* result);
  Packet& packet() { return packet_; }

 private:
  struct Request;
  static void run(void* argument);
  portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
  bool running_ = false;
  bool ready_ = false;
  bool capturing_ = false;
  bool captured_ = false;
  Packet packet_{};
  Result result_{};
};

}  // namespace sgk
