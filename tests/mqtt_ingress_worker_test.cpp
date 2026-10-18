#include "MqttIngressWorker.h"
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>

namespace {
std::thread task;
std::mutex transport_mutex;
std::condition_variable cv;
bool entered = false;
bool release_read = false;
bool task_ok = true;
bool watchdog_ok = true;
bool write_ok = true;
bool loop_ok = true;
bool transport_connected = true;
size_t available_heap = 100000;
size_t largest_block = 20000;
int reads = 0;
int writes = 0;
sgk::MqttIngressWorker* active_worker = nullptr;
std::string inbound = "{\"action\":\"manual_remote\"}";
std::string inbound_topic = "target/command";
std::string reply_seen;
}
uint32_t millis() { return 250; }
size_t heap_caps_get_free_size(unsigned) { return available_heap; }
size_t heap_caps_get_largest_free_block(unsigned) { return largest_block; }
int esp_task_wdt_add(void*) { return watchdog_ok ? 0 : -1; }
int esp_task_wdt_reset() { return 0; }
int esp_task_wdt_delete(void*) { return 0; }
int xTaskCreate(void (*entry)(void*), const char*, uint32_t, void* argument,
                unsigned priority, void*) {
  assert(priority == tskIDLE_PRIORITY);  // Lower than the sensor/control loop.
  if (!task_ok) return 0;
  task = std::thread(entry, argument);
  return 1;
}
void vTaskDelete(void*) {}
bool PubSubClient::publish(const char*, const char* payload, bool retained) {
  assert(!retained);
  ++writes;
  reply_seen = payload;
  return write_ok;
}
bool PubSubClient::connected() { return transport_connected; }
bool PubSubClient::loop() {
  ++reads;
  std::unique_lock<std::mutex> lock(transport_mutex);
  entered = true;
  cv.notify_all();
  cv.wait(lock, [] { return release_read; });
  assert(active_worker->capture(inbound_topic.c_str(),
      reinterpret_cast<const uint8_t*>(inbound.data()), inbound.size()));
  return loop_ok;
}
void reset_socket() {
  entered = false;
  release_read = false;
}
int main() {
  assert(sgk::MqttIngressWorker::pollDue(0x90000000u, 1, 250));
  assert(!sgk::MqttIngressWorker::pollDue(0x20u, 0xfffffff0u, 250));
  assert(sgk::MqttIngressWorker::pollDue(0x100u, 0xfffffff0u, 250));
  sgk::MqttIngressWorker worker;
  active_worker = &worker;
  PubSubClient client;
  sgk::MqttIngressWorker::Result result{};
  const uint8_t outside[] = {'x'};
  assert(!worker.capture("outside", outside, 1));
  char ack[] = "accepted";
  assert(worker.start(client, "target/command-ack", ack));
  {
    std::unique_lock<std::mutex> lock(transport_mutex);
    assert(cv.wait_for(lock, std::chrono::seconds(2), [] { return entered; }));
  }
  std::strcpy(ack, "changed");
  // A blocked network read cannot execute controls or expose partial payloads.
  // Sensor/relay main can keep ticking; no second socket owner may be created.
  for (int tick = 0; tick < 1000; ++tick) {
    assert(worker.ownsTransport());
    assert(!worker.takeResult(&result));
  }
  assert(!worker.start(client));
  {
    std::lock_guard<std::mutex> lock(transport_mutex);
    release_read = true;
  }
  cv.notify_all();
  task.join();
  assert(worker.ownsTransport());
  assert(worker.takeResult(&result));
  assert(!worker.ownsTransport());
  assert(result.received && result.serviced && result.connected);
  assert(result.watchdog_healthy && result.reply_published);
  assert(reply_seen == "accepted");
  assert(worker.packet().length == inbound.size());
  assert(!worker.packet().truncated);
  assert(std::memcmp(worker.packet().payload, inbound.data(), inbound.size()) == 0);

  // An ACL-sized payload does not consume another 8KB of proof/relay headroom:
  // return the topic/truncation marker; main requests retained ACL again at idle.
  inbound.assign(6000, 'a');
  inbound_topic = "target/acl";
  reset_socket();
  release_read = true;
  assert(worker.start(client));
  task.join();
  assert(worker.takeResult(&result));
  assert(result.received && worker.packet().truncated);
  assert(std::strcmp(worker.packet().topic, "target/acl") == 0);
  assert(worker.packet().length == 0);

  // A partial ACK write cannot be followed by a read on a corrupt stream.
  const int reads_before_failed_write = reads;
  write_ok = false;
  assert(worker.start(client, "target/command-ack", "reply"));
  task.join();
  assert(worker.takeResult(&result));
  assert(result.reply_attempted && !result.reply_published);
  assert(reads == reads_before_failed_write && !result.received);
  write_ok = true;

  const int before_reply_only = reads;
  assert(worker.start(client, "target/command-ack", "reply", false));
  task.join();
  assert(worker.takeResult(&result));
  assert(result.serviced && result.reply_published && !result.received);
  assert(reads == before_reply_only);

  watchdog_ok = false;
  const int before_watchdog_reads = reads;
  const int before_watchdog_writes = writes;
  assert(worker.start(client, "target/command-ack", "reply"));
  task.join();
  assert(worker.takeResult(&result));
  assert(!result.watchdog_healthy && !result.reply_attempted);
  assert(reads == before_watchdog_reads && writes == before_watchdog_writes);
  watchdog_ok = true;

  task_ok = false;
  assert(!worker.start(client));
  assert(!worker.ownsTransport());
  task_ok = true;
  available_heap = 10000;
  assert(!worker.start(client));
  available_heap = 100000;
  largest_block = 500;
  assert(!worker.start(client));
  largest_block = 20000;
  assert(!worker.start(client, nullptr, "unexpected"));
  assert(!worker.start(client, "target/command-ack", nullptr));
  assert(!worker.start(client, "target/command-ack", ""));
  assert(!worker.takeResult(nullptr));
}
