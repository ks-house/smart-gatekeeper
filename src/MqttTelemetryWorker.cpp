#include "MqttTelemetryWorker.h"

#include <Arduino.h>
#include <esp_heap_caps.h>
#include <esp_task_wdt.h>
#include <freertos/task.h>

#include <cstring>
#include <new>

namespace sgk {
namespace {
constexpr size_t kMaxTopicBytes = 160;
constexpr size_t kMaxPayloadBytes = 6144;
constexpr uint32_t kStackBytes = 6144;
// Do not consume the headroom needed by proof verification/relay control.
constexpr size_t kRetainedHeapReserve = 49152;
}  // namespace

struct MqttTelemetryWorker::Request {
  MqttTelemetryWorker* owner = nullptr;
  PubSubClient* client = nullptr;
  char topic[kMaxTopicBytes] = {};
  char* payload = nullptr;
  uint32_t generation = 0;
};

bool MqttTelemetryWorker::ownsTransport() {
  portENTER_CRITICAL(&mux_);
  const bool owned = running_ || ready_;
  portEXIT_CRITICAL(&mux_);
  return owned;
}

bool MqttTelemetryWorker::takeResult(Result* result) {
  if (result == nullptr) return false;
  portENTER_CRITICAL(&mux_);
  const bool ready = ready_ && !running_;
  if (ready) {
    *result = result_;
    result_ = Result{};
    ready_ = false;
  }
  portEXIT_CRITICAL(&mux_);
  return ready;
}

bool MqttTelemetryWorker::start(PubSubClient& client, const char* topic,
                                const char* payload, uint32_t generation) {
  if (topic == nullptr || payload == nullptr || generation == 0 || ownsTransport()) {
    return false;
  }
  const size_t topic_length = strnlen(topic, kMaxTopicBytes);
  const size_t payload_length = strnlen(payload, kMaxPayloadBytes);
  if (topic_length == 0 || topic_length >= kMaxTopicBytes ||
      payload_length == 0 || payload_length >= kMaxPayloadBytes ||
      heap_caps_get_free_size(MALLOC_CAP_8BIT) <
          kRetainedHeapReserve + payload_length + sizeof(Request) + kStackBytes ||
      heap_caps_get_largest_free_block(MALLOC_CAP_8BIT) < kStackBytes + 1024) {
    return false;
  }
  auto* request = new (std::nothrow) Request{};
  if (request == nullptr) return false;
  request->payload = new (std::nothrow) char[payload_length + 1];
  if (request->payload == nullptr) {
    delete request;
    return false;
  }
  request->owner = this;
  request->client = &client;
  request->generation = generation;
  std::memcpy(request->topic, topic, topic_length + 1);
  std::memcpy(request->payload, payload, payload_length + 1);
  // start() has one main-loop producer; only the completion writer is concurrent.
  portENTER_CRITICAL(&mux_);
  running_ = true;
  portEXIT_CRITICAL(&mux_);
  if (xTaskCreate(run, "mqtt-status", kStackBytes, request,
                  tskIDLE_PRIORITY + 1, nullptr) == pdPASS) return true;
  portENTER_CRITICAL(&mux_);
  running_ = false;
  portEXIT_CRITICAL(&mux_);
  delete[] request->payload;
  delete request;
  return false;
}

void MqttTelemetryWorker::run(void* argument) {
  auto* request = static_cast<Request*>(argument);
  MqttTelemetryWorker* owner = request->owner;
  Result result{};
  result.generation = request->generation;
  const uint32_t started = millis();
  const bool enrolled = esp_task_wdt_add(nullptr) == ESP_OK;
  // Socket deadlines are configured by MqttManager; watchdog is a second bound.
  // If watchdog enrollment fails, do not begin an unmonitored TLS write.
  if (enrolled) {
    result.published = request->client->publish(request->topic, request->payload, false);
    result.transport_connected = request->client->connected();
    const bool reset_ok = esp_task_wdt_reset() == ESP_OK;
    const bool remove_ok = esp_task_wdt_delete(nullptr) == ESP_OK;
    result.watchdog_healthy = reset_ok && remove_ok;
  }
  result.duration_ms = millis() - started;
  delete[] request->payload;
  delete request;
  // No socket access, pointer ownership, or shared payload remains after handoff.
  portENTER_CRITICAL(&owner->mux_);
  owner->result_ = result;
  owner->ready_ = true;
  owner->running_ = false;
  portEXIT_CRITICAL(&owner->mux_);
  vTaskDelete(nullptr);
}

}  // namespace sgk
