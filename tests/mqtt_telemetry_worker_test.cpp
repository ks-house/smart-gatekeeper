#include "MqttTelemetryWorker.h"

#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>

namespace {
std::thread task;
std::mutex socket_mutex;
std::condition_variable socket_cv;
bool entered = false;
bool release_write = false;
bool task_create_ok = true;
bool watchdog_ok = true;
bool publish_ok = true;
size_t free_heap = 100000;
size_t largest_block = 20000;
std::atomic<int> writes{0};
std::string written_payload;
std::string written_topic;
}  // namespace

uint32_t millis() { return 123; }
size_t heap_caps_get_free_size(unsigned) { return free_heap; }
size_t heap_caps_get_largest_free_block(unsigned) { return largest_block; }
int esp_task_wdt_add(void*) { return watchdog_ok ? 0 : -1; }
int esp_task_wdt_reset() { return 0; }
int esp_task_wdt_delete(void*) { return 0; }
int xTaskCreate(void (*entry)(void*), const char*, uint32_t, void* argument,
                 unsigned, void*) {
  if (!task_create_ok) return 0;
  task = std::thread(entry, argument);
  return 1;
}
void vTaskDelete(void*) {}
bool PubSubClient::publish(const char* topic, const char* payload, bool retained) {
  assert(!retained);
  std::unique_lock<std::mutex> lock(socket_mutex);
  entered = true;
  socket_cv.notify_all();
  socket_cv.wait(lock, [] { return release_write; });
  written_payload = payload;
  written_topic = topic;
  ++writes;
  return publish_ok;
}
bool PubSubClient::connected() { return publish_ok; }

int main() {
  sgk::MqttTelemetryWorker worker;
  PubSubClient client;
  char payload[] = "ARMED";
  char topic[] = "target/status";
  assert(worker.start(client, topic, payload, 42));
  {
    std::unique_lock<std::mutex> lock(socket_mutex);
    assert(socket_cv.wait_for(lock, std::chrono::seconds(2), [] { return entered; }));
  }
  // A blocked TLS write does not own the control-loop mutex or caller buffers.
  // Main can repeatedly progress, replace its telemetry, and refuse dual owners.
  std::strcpy(payload, "IDLE");
  std::strcpy(topic, "other/topic");
  sgk::MqttTelemetryWorker::Result result{};
  for (int control_ticks = 0; control_ticks < 1000; ++control_ticks) {
    assert(worker.ownsTransport());
    assert(!worker.takeResult(&result));
  }
  assert(!worker.start(client, topic, payload, 43));
  {
    std::lock_guard<std::mutex> lock(socket_mutex);
    release_write = true;
  }
  socket_cv.notify_all();
  task.join();
  assert(worker.ownsTransport());  // Main must explicitly adopt completion.
  assert(worker.takeResult(&result));
  assert(!worker.ownsTransport());
  assert(result.published && result.transport_connected && result.watchdog_healthy);
  assert(result.generation == 42);
  assert(written_payload == "ARMED" && written_topic == "target/status");
  assert(!worker.takeResult(&result));

  task_create_ok = false;
  assert(!worker.start(client, topic, payload, 44));
  assert(!worker.ownsTransport());
  task_create_ok = true;
  free_heap = 10000;
  assert(!worker.start(client, topic, payload, 44));
  free_heap = 100000;
  largest_block = 512;
  assert(!worker.start(client, topic, payload, 44));
  largest_block = 20000;
  assert(!worker.start(client, topic, payload, 0));

  watchdog_ok = false;
  assert(worker.start(client, topic, payload, 45));
  task.join();
  assert(worker.takeResult(&result));
  assert(!result.published && !result.watchdog_healthy);
  assert(writes == 1);  // Enrollment failure never starts socket I/O.
  watchdog_ok = true;
  publish_ok = false;
  assert(worker.start(client, topic, payload, 46));
  task.join();
  assert(worker.takeResult(&result));
  assert(!result.published && !result.transport_connected);
  assert(result.generation == 46);
  publish_ok = true;
  const std::string oversized(sgk::MqttTelemetryWorker::kMaxPayloadBytes, 'x');
  assert(!worker.start(client, topic, oversized.c_str(), 47));
  const std::string maximum(sgk::MqttTelemetryWorker::kMaxPayloadBytes - 1, 'x');
  assert(worker.start(client, topic, maximum.c_str(), 48));
  task.join();
  assert(worker.takeResult(&result) && result.published);
  assert(written_payload == maximum);
}
