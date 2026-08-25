#pragma once

#include <Preferences.h>
#include <esp_partition.h>
#include <nvs.h>
#include <nvs_flash.h>

#include <cstddef>

namespace sgk {

constexpr char kDurableStatePartition[] = "sgkstate";
constexpr char kLegacyDurableStatePartition[] = "spiffs";

// The first production table shipped this region as an unused SPIFFS
// partition. Existing Targets retain that table during application-only OTA,
// while new full flashes name the same fixed region sgkstate. Select by label
// so neither OTA app slot nor its offsets ever need to move.
inline const char* durableStatePartitionLabel() {
  if (esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                               ESP_PARTITION_SUBTYPE_ANY,
                               kDurableStatePartition) != nullptr) {
    return kDurableStatePartition;
  }
  if (esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                               ESP_PARTITION_SUBTYPE_ANY,
                               kLegacyDurableStatePartition) != nullptr) {
    return kLegacyDurableStatePartition;
  }
  return kDurableStatePartition;
}

inline bool durableStateStats(nvs_stats_t* stats) {
  if (stats == nullptr) return false;
  const char* partition_label = durableStatePartitionLabel();
  if (nvs_flash_init_partition(partition_label) != ESP_OK) return false;
  return nvs_get_stats(partition_label, stats) == ESP_OK;
}

inline bool writeDurableBlob(const char* name_space, const char* key,
                             const void* data, size_t length) {
  if (name_space == nullptr || key == nullptr || data == nullptr || length == 0) {
    return false;
  }
  Preferences preferences;
  if (!preferences.begin(name_space, false, durableStatePartitionLabel())) {
    return false;
  }
  const size_t written = preferences.putBytes(key, data, length);
  preferences.end();
  return written == length;
}

inline size_t readBlobFromPartition(const char* partition_label,
                                    const char* name_space, const char* key,
                                    void* buffer, size_t capacity) {
  if (name_space == nullptr || key == nullptr || buffer == nullptr ||
      capacity == 0) {
    return 0;
  }
  Preferences preferences;
  const bool opened = partition_label == nullptr
                          ? preferences.begin(name_space, true)
                          : preferences.begin(name_space, true, partition_label);
  if (!opened) return 0;
  const size_t length = preferences.getBytesLength(key);
  if (length == 0 || length > capacity) {
    preferences.end();
    return 0;
  }
  const size_t read = preferences.getBytes(key, buffer, capacity);
  preferences.end();
  return read == length ? read : 0;
}

// Read the expanded durable partition first, then the original 20 KiB NVS.
// This preserves the last ACL/replay/queue state across an application-only
// OTA; the next successful write migrates that individual record.
inline size_t readDurableBlobWithLegacyFallback(const char* name_space,
                                                const char* key, void* buffer,
                                                size_t capacity) {
  const size_t durable_read = readBlobFromPartition(
      durableStatePartitionLabel(), name_space, key, buffer, capacity);
  if (durable_read != 0) return durable_read;
  return readBlobFromPartition(nullptr, name_space, key, buffer, capacity);
}

inline bool clearDurableAndLegacyNamespace(const char* name_space) {
  if (name_space == nullptr) return false;

  bool durable_ok = false;
  Preferences durable;
  if (durable.begin(name_space, false, durableStatePartitionLabel())) {
    durable_ok = durable.clear();
    durable.end();
  }

  // Queue clearing is explicitly destructive. Clear the legacy copy as well
  // so fallback reads cannot resurrect already-consumed events.
  bool legacy_ok = true;
  Preferences legacy;
  if (legacy.begin(name_space, false)) {
    legacy_ok = legacy.clear();
    legacy.end();
  }
  return durable_ok && legacy_ok;
}

}  // namespace sgk
