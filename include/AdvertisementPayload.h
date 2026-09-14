#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include "GattProtocol.h"

namespace sgk {

// Explicit wire bytes, independent of BLEUUID/BLEBeacon internal byte order.
// Equivalent to Arduino BLE 3.3.9 BLEBeacon with manufacturer 0x4c00,
// manually reversed UUID, major/minor 1 and flags 0x1a. APK44801 compatible.
struct AdvertisementPayload {
  std::array<uint8_t, 31> bytes{};
  size_t length = 0;
};

inline AdvertisementPayload primaryAdvertisement(int power_dbm) {
  AdvertisementPayload payload;
  payload.bytes = {{2, 1, 0x1a, 26, 0xff, 0x4c, 0x00}};
  for (size_t i = 0; i < kIBeaconFilterPrefix.size(); ++i)
    payload.bytes[7 + i] = kIBeaconFilterPrefix[i];
  payload.bytes[25] = 0; payload.bytes[26] = 1;
  payload.bytes[27] = 0; payload.bytes[28] = 1;
  // Same legacy estimated 1m RSSI; this is not measured RF calibration.
  payload.bytes[29] = static_cast<uint8_t>(static_cast<int64_t>(power_dbm) - 59);
  payload.length = 30;
  return payload;
}

inline AdvertisementPayload responseAdvertisement(bool enabled, bool ready,
                                                   uint32_t epoch) {
  AdvertisementPayload payload;
  if (!enabled) {
    constexpr char name[] = "SmartGatekeeper";
    payload.bytes[0] = sizeof(name);
    payload.bytes[1] = 0x09;
    for (size_t i = 0; i < sizeof(name) - 1; ++i)
      payload.bytes[2 + i] = name[i];
    payload.length = sizeof(name) + 1;
    return payload;
  }
  // Existing SGK name + V1 readiness service data, not a primary migration.
  payload.bytes = {{4, 0x09, 'S', 'G', 'K', 23, 0x21,
      0x31, 0x4b, 0x47, 0x53, 0x4d, 0x6f, 0x54, 0x9c,
      0xb1, 0x4f, 0x9e, 0x7d, 0x00, 0x10, 0x4d, 0x9f,
      1, static_cast<uint8_t>(ready)}};
  for (size_t i = 0; i < 4; ++i)
    payload.bytes[25 + i] = static_cast<uint8_t>(epoch >> (8 * i));
  payload.length = 29;
  return payload;
}

}  // namespace sgk
