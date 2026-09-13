#pragma once

#include <cstdint>
#include "SensorSessionDiagnostics.h"

namespace sgk {

inline void incrementSensorCounter(uint32_t& value) {
  if (value != UINT32_MAX) ++value;
}

enum class SensorSamplePhase : uint8_t { kIdle, kArmed, kCooldown };
inline const char* sensorSamplePhaseName(SensorSamplePhase phase) {
  switch (phase) {
    case SensorSamplePhase::kArmed: return "ARMED";
    case SensorSamplePhase::kCooldown: return "COOLDOWN";
    default: return "IDLE";
  }
}

enum class SensorSampleKind : uint8_t {
  kNotSampled, kNoEcho, kOutOfRange, kNear, kClear, kBand
};
inline const char* sensorSampleKindName(SensorSampleKind kind) {
  switch (kind) {
    case SensorSampleKind::kNoEcho: return "NO_ECHO";
    case SensorSampleKind::kOutOfRange: return "OUT_OF_RANGE";
    case SensorSampleKind::kNear: return "VALID_NEAR";
    case SensorSampleKind::kClear: return "VALID_CLEAR";
    case SensorSampleKind::kBand: return "VALID_BAND";
    default: return "NOT_SAMPLED";
  }
}

// One schedule across state changes. Changing IDLE -> ARMED or becoming
// blocked never generates a second trigger inside the minimum interval.
class SensorSamplingCadence {
 public:
  bool take(uint32_t now_ms, uint32_t interval_ms) {
    if (sampled_ && now_ms - last_ms_ < interval_ms) return false;
    sampled_ = true;
    last_ms_ = now_ms;
    return true;
  }
 private:
  bool sampled_ = false;
  uint32_t last_ms_ = 0;
};

// Boot-scoped, unsigned observations. Invalid echoes retain their raw pulse
// width; absent echoes and never-sampled state have no invented distance.
// These fields deliberately do not change the durable signed V1 summary ABI.
struct SensorObservation {
  SensorSampleKind kind = SensorSampleKind::kNotSampled;
  SensorSamplePhase phase = SensorSamplePhase::kIdle;
  uint32_t sampled_ms = 0;
  uint32_t echo_us = 0;
  uint16_t raw_mm = kNoSensorMeasurement;
  uint16_t last_valid_mm = kNoSensorMeasurement;
  uint32_t last_valid_ms = 0;
  uint32_t idle_samples = 0;
  uint32_t armed_samples = 0;
  uint32_t cooldown_samples = 0;
  uint32_t no_echo = 0;
  uint32_t out_of_range = 0;
  uint32_t valid = 0;
  uint32_t invalid_streak = 0;

  bool sampled() const { return kind != SensorSampleKind::kNotSampled; }
  bool validNow() const {
    return kind == SensorSampleKind::kNear || kind == SensorSampleKind::kClear ||
           kind == SensorSampleKind::kBand;
  }
  void observe(uint32_t now_ms, SensorSamplePhase sample_phase,
               uint32_t duration_us, uint16_t validated_mm, uint16_t threshold_mm) {
    sampled_ms = now_ms;
    phase = sample_phase;
    echo_us = duration_us;
    raw_mm = duration_us == 0 ? kNoSensorMeasurement :
        static_cast<uint16_t>((static_cast<uint64_t>(duration_us) * 343) / 2000);
    if (phase == SensorSamplePhase::kArmed) incrementSensorCounter(armed_samples);
    else if (phase == SensorSamplePhase::kCooldown) incrementSensorCounter(cooldown_samples);
    else incrementSensorCounter(idle_samples);
    if (duration_us == 0) {
      kind = SensorSampleKind::kNoEcho;
      incrementSensorCounter(no_echo);
    } else if (validated_mm == kNoSensorMeasurement) {
      kind = SensorSampleKind::kOutOfRange;
      incrementSensorCounter(out_of_range);
    } else {
      kind = validated_mm <= threshold_mm ? SensorSampleKind::kNear :
          (validated_mm > threshold_mm + 100 ? SensorSampleKind::kClear : SensorSampleKind::kBand);
      incrementSensorCounter(valid);
      last_valid_mm = validated_mm;
      last_valid_ms = now_ms;
    }
    if (validNow()) invalid_streak = 0;
    else incrementSensorCounter(invalid_streak);
  }
};

// Latest ARMED window only, retained until the next arm. No socket/NVS work,
// per-sample log or access decision is performed by this recorder.
struct SensorQualification {
  bool active = false;
  uint32_t started_ms = 0;
  uint32_t ended_ms = 0;
  uint16_t median_mm = kNoSensorMeasurement;
  uint32_t median_ms = 0;
  uint32_t samples = 0;
  uint32_t valid_streak = 0;
  uint32_t max_valid_streak = 0;
  uint32_t near_streak = 0;
  uint32_t max_near_streak = 0;
  uint32_t median_rejects = 0;
  uint32_t candidates = 0;
  uint32_t rearm_rejects = 0;
  uint32_t fsm_rejects = 0;
  uint32_t triggers = 0;

  void begin(uint32_t now_ms) { *this = {}; started_ms = now_ms; active = true; }
  void finish(uint32_t now_ms) { if (active) { ended_ms = now_ms; active = false; } }
  void observe(uint32_t now_ms, uint16_t raw, uint16_t median, uint16_t threshold,
               bool blocked, bool triggered) {
    if (!active) return;
    incrementSensorCounter(samples);
    median_mm = median;
    median_ms = now_ms;
    if (raw != kNoSensorMeasurement) incrementSensorCounter(valid_streak);
    else valid_streak = 0;
    const bool raw_near = raw != kNoSensorMeasurement && raw <= threshold;
    if (raw_near) incrementSensorCounter(near_streak);
    else near_streak = 0;
    if (valid_streak > max_valid_streak) max_valid_streak = valid_streak;
    if (near_streak > max_near_streak) max_near_streak = near_streak;
    const bool candidate = median != kNoSensorMeasurement && median <= threshold;
    if (raw_near && !candidate) incrementSensorCounter(median_rejects);
    if (candidate) {
      incrementSensorCounter(candidates);
      if (blocked) incrementSensorCounter(rearm_rejects);
      else if (!triggered) incrementSensorCounter(fsm_rejects);
      else incrementSensorCounter(triggers);
    }
  }
};

}  // namespace sgk
