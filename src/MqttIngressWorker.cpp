#include "MqttIngressWorker.h"

#include <Arduino.h>
#include <esp_heap_caps.h>
#include <esp_task_wdt.h>
#include <freertos/task.h>
#include <cstring>
#include <new>

namespace sgk {
namespace {
constexpr uint32_t kStackBytes = 6144;
constexpr size_t kRetainedHeapReserve = 49152;
}
struct MqttIngressWorker::Request {
  MqttIngressWorker* owner = nullptr;
  PubSubClient* client = nullptr;
  bool poll_inbound = true;
  char topic[kTopicBytes]{};
  char reply[kReplyBytes]{};
};

bool MqttIngressWorker::ownsTransport() {
  portENTER_CRITICAL(&mux_);
  const bool owned = running_ || ready_;
  portEXIT_CRITICAL(&mux_);
  return owned;
}

bool MqttIngressWorker::takeResult(Result* result) {
  if (result == nullptr) return false;
  portENTER_CRITICAL(&mux_);
  const bool ready = ready_ && !running_;
  if (ready) {
    *result = result_;
    ready_ = false;
    result_ = Result{};
  }
  portEXIT_CRITICAL(&mux_);
  return ready;
}

bool MqttIngressWorker::capture(const char* topic, const uint8_t* payload,
                                size_t length) {
  // Only the leased worker can call client.loop(). Main cannot touch these
  // bytes until takeResult; the completion mutex provides the memory handoff.
  portENTER_CRITICAL(&mux_);
  const bool capturing = capturing_;
  portEXIT_CRITICAL(&mux_);
  if (!capturing) return false;
  if (captured_ || topic == nullptr || payload == nullptr ||
      strnlen(topic, kTopicBytes) >= kTopicBytes) return true;
  std::strcpy(packet_.topic, topic);
  packet_.truncated = length == 0 || length >= kPayloadBytes;
  packet_.length = packet_.truncated ? 0 : length;
  if (!packet_.truncated) std::memcpy(packet_.payload, payload, length);
  packet_.payload[packet_.length] = 0;
  captured_ = true;
  return true;
}

bool MqttIngressWorker::start(PubSubClient& client, const char* reply_topic,
                              const char* reply_payload, bool poll_inbound) {
  if (ownsTransport() || (!poll_inbound && reply_topic == nullptr) ||
      (reply_topic == nullptr) != (reply_payload == nullptr) ||
      heap_caps_get_free_size(MALLOC_CAP_8BIT) <
          kRetainedHeapReserve + sizeof(Request) + kStackBytes ||
      heap_caps_get_largest_free_block(MALLOC_CAP_8BIT) < kStackBytes + 1024) {
    return false;
  }
  if (reply_topic != nullptr &&
      (strnlen(reply_topic, kTopicBytes) == 0 ||
       strnlen(reply_topic, kTopicBytes) >= kTopicBytes ||
       strnlen(reply_payload, kReplyBytes) == 0 ||
       strnlen(reply_payload, kReplyBytes) >= kReplyBytes)) return false;
  auto* request = new (std::nothrow) Request{};
  if (request == nullptr) return false;
  request->owner = this;
  request->client = &client;
  request->poll_inbound = poll_inbound;
  if (reply_topic != nullptr) {
    std::strcpy(request->topic, reply_topic);
    std::strcpy(request->reply, reply_payload);
  }
  packet_.length = 0;
  packet_.truncated = false;
  captured_ = false;
  portENTER_CRITICAL(&mux_);
  running_ = true;
  portEXIT_CRITICAL(&mux_);
  if (xTaskCreate(run, "mqtt-ingress", kStackBytes, request,
                  tskIDLE_PRIORITY + 1, nullptr) == pdPASS) return true;
  portENTER_CRITICAL(&mux_);
  running_ = false;
  portEXIT_CRITICAL(&mux_);
  delete request;
  return false;
}

void MqttIngressWorker::run(void* argument) {
  auto* request = static_cast<Request*>(argument);
  auto* owner = request->owner;
  Result result{};
  const uint32_t started = millis();
  if (esp_task_wdt_add(nullptr) == ESP_OK) {
    bool may_read = true;
    if (request->reply[0]) {
      result.reply_attempted = true;
      result.reply_published = request->client->publish(
          request->topic, request->reply, false);
      // Never append/read another MQTT packet after an uncertain TLS write.
      may_read = result.reply_published;
    }
    if (may_read && request->poll_inbound) {
      portENTER_CRITICAL(&owner->mux_);
      owner->capturing_ = true;
      portEXIT_CRITICAL(&owner->mux_);
      result.serviced = request->client->loop();
      portENTER_CRITICAL(&owner->mux_);
      owner->capturing_ = false;
      portEXIT_CRITICAL(&owner->mux_);
      result.received = owner->captured_;
    } else if (may_read) {
      result.serviced = true;  // Reply-only lease; idle receive stays on main.
    }
    result.connected = request->client->connected();
    const bool reset = esp_task_wdt_reset() == ESP_OK;
    const bool removed = esp_task_wdt_delete(nullptr) == ESP_OK;
    result.watchdog_healthy = reset && removed;
  }
  result.duration_ms = millis() - started;
  delete request;
  portENTER_CRITICAL(&owner->mux_);
  owner->result_ = result;
  owner->ready_ = true;
  owner->running_ = false;
  portEXIT_CRITICAL(&owner->mux_);
  vTaskDelete(nullptr);
}
}  // namespace sgk
