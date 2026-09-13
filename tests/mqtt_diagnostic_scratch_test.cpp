#include "MqttDiagnosticScratch.h"

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <type_traits>

#if defined(SGK_SCRATCH_REAL_JSON)
#include <ArduinoJson.h>
#endif

namespace {
struct alignas(16) StatusFixture {
  inline static int constructed = 0;
  inline static int destroyed = 0;
  char bytes[7168] = {};
  StatusFixture() { ++constructed; }
  ~StatusFixture() { ++destroyed; }
};

struct alignas(32) BootFixture {
  inline static int constructed = 0;
  inline static int destroyed = 0;
  char document[2560] = {};
  char output[2560] = {};
  BootFixture() { ++constructed; }
  ~BootFixture() { ++destroyed; }
};

using Scratch = sgk::MqttDiagnosticScratch<StatusFixture, BootFixture>;
static_assert(!std::is_copy_constructible<Scratch>::value);
static_assert(!std::is_move_constructible<Scratch>::value);
static_assert(!std::is_copy_constructible<Scratch::Lease<StatusFixture>>::value);
static_assert(!std::is_move_constructible<Scratch::Lease<StatusFixture>>::value);
static_assert(Scratch::kStorageBytes == sizeof(StatusFixture));

void earlyReturn(Scratch& scratch) {
  auto status = scratch.status();
  assert(status);
  status->bytes[0] = 'x';
  return;
}

void checkLifetimesAndAlignment() {
  Scratch scratch;
  assert(StatusFixture::constructed == 0 && BootFixture::constructed == 0);
  void* reused_address = nullptr;
  char queued_payload[32] = {};
  {
    auto status = scratch.status();
    assert(status);
    assert(reinterpret_cast<uintptr_t>(&*status) % alignof(StatusFixture) == 0);
    reused_address = &*status;
    std::strcpy(status->bytes, "signed-status-generation-1");
    std::strcpy(queued_payload, status->bytes);
    {
      auto nested_boot = scratch.boot();
      auto nested_status = scratch.status();
      assert(!nested_boot && !nested_status);
      assert(BootFixture::constructed == 0);
    }
    // Destruction of a failed lease must not release the original owner.
    assert(!scratch.boot());
    assert(std::strcmp(status->bytes, queued_payload) == 0);
  }
  assert(StatusFixture::destroyed == 1);
  {
    auto boot = scratch.boot();
    assert(boot);
    assert(reinterpret_cast<uintptr_t>(&*boot) % alignof(BootFixture) == 0);
    assert(static_cast<void*>(&*boot) == reused_address);
    assert(boot->document[0] == 0 && boot->output[0] == 0);
    std::memset(boot->document, 'b', sizeof(boot->document));
    std::memset(boot->output, 'o', sizeof(boot->output));
    assert(!scratch.status());
  }
  assert(BootFixture::destroyed == 1);
  assert(std::strcmp(queued_payload, "signed-status-generation-1") == 0);
  earlyReturn(scratch);
  assert(StatusFixture::constructed == StatusFixture::destroyed);
  for (int i = 0; i < 1000; ++i) {
    {
      auto status = scratch.status();
      assert(status && status->bytes[0] == 0);
      status->bytes[sizeof(status->bytes) - 1] = 's';
    }
    {
      auto boot = scratch.boot();
      assert(boot && boot->output[sizeof(boot->output) - 1] == 0);
    }
  }
  assert(StatusFixture::constructed == StatusFixture::destroyed);
  assert(BootFixture::constructed == BootFixture::destroyed);
}

#if defined(SGK_SCRATCH_REAL_JSON)
using JsonStatus = StaticJsonDocument<7168>;
struct JsonBoot {
  StaticJsonDocument<2560> document;
  char buffer[2560];
};
using JsonScratch = sgk::MqttDiagnosticScratch<JsonStatus, JsonBoot>;
static_assert(sizeof(JsonStatus) + sizeof(JsonBoot) >= sizeof(JsonScratch) + 5120);

void checkRealJsonSerialization() {
  JsonScratch scratch;
  char pending[7936] = {};
  for (int generation = 1; generation <= 100; ++generation) {
    {
      auto status = scratch.status();
      assert(status && status->capacity() == 7168 && status->memoryUsage() == 0);
      (*status)["generation"] = generation;
      (*status)["state"] = "IDLE";
      (*status)["access_auth"]["tag"] = "0123456789abcdef0123456789abcdef";
      assert(!status->overflowed());
      assert(serializeJson(*status, pending, sizeof(pending)) == measureJson(*status));
    }
    char immutable_worker_copy[7936];
    std::strcpy(immutable_worker_copy, pending);
    {
      auto boot = scratch.boot();
      assert(boot && boot->document.capacity() == 2560);
      assert(boot->document.memoryUsage() == 0);
      boot->document["boot_count"] = 903;
      assert(serializeJson(boot->document, boot->buffer, sizeof(boot->buffer)) == 18);
      assert(std::strcmp(boot->buffer, "{\"boot_count\":903}") == 0);
      assert(std::strcmp(pending, immutable_worker_copy) == 0);
      StaticJsonDocument<512> parsed;
      assert(!deserializeJson(parsed, pending));
      assert(parsed["generation"].as<int>() == generation);
      assert(std::strcmp(parsed["state"], "IDLE") == 0);
    }
    {
      auto status = scratch.status();
      auto values = status->to<JsonArray>();
      for (int i = 0; i < 10000 && !status->overflowed(); ++i) values.add(i);
      assert(status->overflowed());
    }
    // Even an overflowed document is destroyed and a new boot lease is clean.
    auto boot = scratch.boot();
    assert(boot && !boot->document.overflowed() && boot->document.memoryUsage() == 0);
  }
  std::printf("json storage: old=%zu shared=%zu saved=%zu bytes\n",
      sizeof(JsonStatus) + sizeof(JsonBoot), sizeof(JsonScratch),
      sizeof(JsonStatus) + sizeof(JsonBoot) - sizeof(JsonScratch));
}
#endif
}  // namespace

int main() {
  checkLifetimesAndAlignment();
#if defined(SGK_SCRATCH_REAL_JSON)
  checkRealJsonSerialization();
#endif
}
