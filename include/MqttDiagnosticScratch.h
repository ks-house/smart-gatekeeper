#pragma once

#include <cstddef>
#include <new>

namespace sgk {

// Main-task-only scratch for two non-overlapping diagnostic builders. Neither
// object nor any reference into it may escape its lease. In particular, MQTT
// pending/worker payloads must keep their separate immutable storage.
template <typename Status, typename Boot>
class MqttDiagnosticScratch {
 public:
  static constexpr size_t kStorageBytes =
      sizeof(Status) > sizeof(Boot) ? sizeof(Status) : sizeof(Boot);

  template <typename T>
  class Lease {
   public:
    Lease(const Lease&) = delete;
    Lease& operator=(const Lease&) = delete;
    ~Lease() {
      if (value_ != nullptr) {
        value_->~T();
        owner_->leased_ = false;
      }
    }

    explicit operator bool() const { return value_ != nullptr; }
    T& operator*() const { return *value_; }
    T* operator->() const { return value_; }

   private:
    friend class MqttDiagnosticScratch;
    explicit Lease(MqttDiagnosticScratch* owner) {
      if (owner->leased_) return;
      owner_ = owner;
      owner_->leased_ = true;
      value_ = ::new (static_cast<void*>(owner_->storage_)) T{};
    }

    MqttDiagnosticScratch* owner_ = nullptr;
    T* value_ = nullptr;
  };

  MqttDiagnosticScratch() = default;
  MqttDiagnosticScratch(const MqttDiagnosticScratch&) = delete;
  MqttDiagnosticScratch& operator=(const MqttDiagnosticScratch&) = delete;

  Lease<Status> status() { return Lease<Status>(this); }
  Lease<Boot> boot() { return Lease<Boot>(this); }

 private:
  alignas(Status) alignas(Boot) unsigned char storage_[kStorageBytes] = {};
  bool leased_ = false;
};

}  // namespace sgk
