#include "PassageRearmPolicy.h"
#include "PresenceAdvertisementPolicy.h"
#include "SensorObservation.h"
#include "TargetAccessFsm.h"
#include "UltrasonicSensor.h"

#include <cassert>
#include <cstring>
#include <cstdio>

static unsigned long echo_us;
static uint32_t reads;
void pinMode(int, int) {}
void digitalWrite(int pin, int) { assert(pin == PIN_TRIG); }
void delayMicroseconds(unsigned int) {}
unsigned long pulseIn(int pin, int value, unsigned long timeout) {
  assert(pin == PIN_ECHO && value == HIGH && timeout == 30000);
  ++reads;
  return echo_us;
}

class Radio final : public sgk::PresenceAdvertisementDriver {
 public:
  bool present = true, running = true, apply_ok = true, stop_ok = true, start_ok = true;
  uint32_t applies = 0, starts = 0, stops = 0;
  bool ready = false;
  uint32_t epoch = 0;
  bool available() const override { return present; }
  bool active() const override { return running; }
  bool apply(bool value, uint32_t revision) override {
    ++applies;
    if (!apply_ok) return false;
    ready = value; epoch = revision; return true;
  }
  bool stop() override { ++stops; if (!stop_ok) return false; running = false; return true; }
  bool start() override { ++starts; if (!start_ok) return false; running = true; return true; }
};

static sgk::PassageRearmPolicy passage;
static sgk::PassagePulseSource source;
static uint32_t clock_ms, pulses;
static void relayDrive(bool on) {
  if (on) { ++pulses; passage.notePulse(clock_ms, source); }
}

static void testBoundedReauthentication() {
  for (auto first_source : {sgk::PassagePulseSource::kRemoteManual,
                            sgk::PassagePulseSource::kLocalManual,
                            sgk::PassagePulseSource::kSensor}) {
    passage = {};
    pulses = 0;
    sgk::TargetAccessFsm fsm(relayDrive, nullptr);
    sgk::PresenceReadyPolicy ready(40);
    fsm.begin(0);
    clock_ms = 100;
    source = first_source;
    if (first_source == sgk::PassagePulseSource::kRemoteManual) {
      assert(fsm.handleManualRemoteOpen(clock_ms, 1000, 3000));
    } else {
      assert(fsm.handleAuthPending(clock_ms));
      if (first_source == sgk::PassagePulseSource::kLocalManual) {
        assert(fsm.handleLocalManualOpen(clock_ms, 1000, 3000));
      } else {
        assert(fsm.handleAuthSuccess(clock_ms, 60000, 3000));
        ready.noteAutomaticArm();
        assert(fsm.handleSensorTrigger(clock_ms, 1000, 3000));
      }
    }
    assert(pulses == 1 && passage.blocked());
    assert(passage.pulseSource() == first_source);
    fsm.tick(1100);
    fsm.tick(4100);
    assert(fsm.state() == GateState::IDLE && fsm.otaSafeState() == OtaSafeState::SAFE);
    assert(!ready.update(4100, true));
    const uint32_t first_ready = first_source == sgk::PassagePulseSource::kSensor ? 34100 : 5100;
    for (uint32_t t = 4100; t < first_ready; t += 100) {
      passage.observeDistance(sgk::kNoSensorMeasurement, 500);
      assert(!ready.update(t, true));
    }
    assert(ready.update(first_ready, true));  // Auth readiness despite no echo.
    assert(passage.blocked() && passage.blockedAgeMs(first_ready) == first_ready - 100);
    assert(fsm.handleAuthPending(first_ready));
    const uint32_t duration = ready.armDurationMs(60000, passage.blocked());
    assert(duration == 5000 && ready.armDurationMs(1000, true) == 1000);
    assert(ready.armDurationMs(60000, false) == 60000);
    assert(fsm.handleAuthSuccess(first_ready, duration, 3000));
    ready.noteAutomaticArm();
    for (uint32_t t = first_ready; t < first_ready + duration; t += 100) {
      passage.observeDistance(t % 200 == 0 ? 400 : sgk::kNoSensorMeasurement, 500);
      assert(passage.blocked());  // Continued presence / missing echoes cannot pulse.
      assert(!ready.update(t, false));
    }
    fsm.tick(first_ready + duration);
    assert(fsm.state() == GateState::IDLE);
    assert(!ready.update(first_ready + duration, true));
    assert(!ready.update(first_ready + duration + 29999, true));
    assert(fsm.otaSafeState() == OtaSafeState::SAFE);
    assert(pulses == 1);
    // Invalid and hysteresis-band readings break a run of real clearance.
    passage.observeDistance(700, 500);
    passage.observeDistance(700, 500);
    assert(passage.clearSamples() == 2);
    passage.observeDistance(600, 500);
    assert(passage.clearSamples() == 0 && passage.blocked());
    for (int i = 0; i < 3; ++i) passage.observeDistance(700, 500);
    assert(!passage.blocked());
    ready.noteConfirmedClearance();
    assert(ready.update(first_ready + duration + 3000, true));
    assert(fsm.handleAuthPending(first_ready + duration + 3000));
    assert(fsm.handleAuthSuccess(first_ready + duration + 3000, 60000, 3000));
    source = sgk::PassagePulseSource::kSensor;
    clock_ms = first_ready + duration + 3100;
    assert(fsm.handleSensorTrigger(clock_ms, 1000, 3000));
    assert(pulses == 2 && passage.blocked());
  }
  // Monotonic wrap and repeated manual requests preserve original block age.
  passage = {};
  passage.notePulse(UINT32_MAX - 99, sgk::PassagePulseSource::kSensor);
  passage.notePulse(20, sgk::PassagePulseSource::kRemoteManual);
  assert(passage.blockedAgeMs(100) == 200 && passage.lastPulseMs() == 20);
  sgk::PresenceReadyPolicy wrapped(1);
  assert(!wrapped.update(UINT32_MAX - 499, true));
  assert(wrapped.update(500, true));
  sgk::TargetAccessFsm deadline(relayDrive, nullptr);
  deadline.begin(0);
  assert(deadline.handleAuthPending(100));
  assert(deadline.handleAuthSuccess(100, 5000, 3000));
  assert(deadline.armRemainingMs(100) == 5000 && deadline.armRemainingMs(5099) == 1);
  assert(deadline.armRemainingMs(5100) == 0);
  const auto before_deadline = pulses;
  // A 30ms pulseIn finishing beyond the short ARM deadline cannot pulse
  // before the next main-loop tick processes the timeout.
  assert(!deadline.handleSensorTrigger(5100, 1000, 3000));
  assert(pulses == before_deadline);
  deadline.tick(5100);
  assert(deadline.otaSafeState() == OtaSafeState::SAFE && deadline.armRemainingMs(5200) == 0);
}

static void testActualSensorAndObservation() {
  sgk::SensorObservation observation;
  assert(!observation.sampled() && !observation.validNow());
  assert(observation.raw_mm == sgk::kNoSensorMeasurement);
  sgk::SensorSamplingCadence cadence;
  assert(cadence.take(UINT32_MAX - 49, 1000));
  assert(!cadence.take(49, 100));
  assert(cadence.take(50, 100));
  // 60 seconds at a 1ms loop with 100ms minimum gives exactly 600 raw reads.
  sgk::SensorSamplingCadence bounded;
  uint32_t taken = 0;
  for (uint32_t ms = 0; ms < 60000; ++ms) if (bounded.take(ms, 100)) ++taken;
  assert(taken == 600);
  UltrasonicSensor::init();
  echo_us = 0;
  unsigned long duration;
  assert(UltrasonicSensor::readDistanceCmRaw(&duration) == 999.0f && duration == 0);
  observation.observe(100, sgk::SensorSamplePhase::kIdle, duration, sgk::kNoSensorMeasurement, 500);
  assert(observation.kind == sgk::SensorSampleKind::kNoEcho && observation.no_echo == 1);
  echo_us = 500;  // Physical echo inside blind zone, not NO_ECHO.
  assert(UltrasonicSensor::readDistanceCmRaw(&duration) == 999.0f && duration == 500);
  observation.observe(200, sgk::SensorSamplePhase::kCooldown, duration, sgk::kNoSensorMeasurement, 500);
  assert(observation.kind == sgk::SensorSampleKind::kOutOfRange && observation.raw_mm == 85);
  echo_us = 25000;  // >4m guard remains unchanged.
  assert(UltrasonicSensor::readDistanceCmRaw(&duration) == 999.0f);
  observation.observe(300, sgk::SensorSamplePhase::kIdle, duration, sgk::kNoSensorMeasurement, 500);
  assert(observation.out_of_range == 2 && observation.invalid_streak == 3);
  echo_us = 2333;  // About 40cm, three fresh samples required by production median.
  const float raw = UltrasonicSensor::readDistanceCmRaw(&duration);
  assert(raw >= 39.9f && raw < 40.1f);
  observation.observe(400, sgk::SensorSamplePhase::kIdle, duration, 400, 500);
  assert(observation.validNow() && observation.invalid_streak == 0 && observation.last_valid_mm == 400);
  UltrasonicSensor::resetHistory();
  sgk::SensorQualification q;
  q.begin(500);
  for (int i = 0; i < 3; ++i) {
    const float median = UltrasonicSensor::readDistanceCm(&duration);
    const uint16_t mm = median == 999.0f ? sgk::kNoSensorMeasurement : static_cast<uint16_t>(median * 10);
    assert((i < 2) == (mm == sgk::kNoSensorMeasurement));
    q.observe(500 + i * 100, 400, mm, 500, i == 2, false);
    observation.observe(500 + i * 100, sgk::SensorSamplePhase::kArmed, duration, 400, 500);
  }
  assert(q.median_rejects == 2 && q.candidates == 1 && q.rearm_rejects == 1);
  assert(q.max_valid_streak == 3 && q.max_near_streak == 3);
  q.observe(800, sgk::kNoSensorMeasurement, 400, 500, false, false);
  assert(q.fsm_rejects == 1 && q.valid_streak == 0);
  q.observe(900, 400, 400, 500, false, true);
  assert(q.triggers == 1);
  q.finish(1000);
  q.observe(1100, 400, 400, 500, false, true);
  assert(q.triggers == 1 && q.ended_ms == 1000 && !q.active);
  assert(q.first_valid_after_ms == 0 && q.first_near_after_ms == 0);
  assert(q.first_candidate_after_ms == 200 && q.trigger_after_ms == 400);
  assert(q.near_streak_started_after_ms == 400);  // Gap resets the streak, not first-near.
  q.begin(UINT32_MAX - 99);
  assert(q.first_near_after_ms == UINT32_MAX && q.trigger_after_ms == UINT32_MAX);
  q.observe(0, sgk::kNoSensorMeasurement, sgk::kNoSensorMeasurement, 500, false, false);
  assert(q.first_valid_after_ms == UINT32_MAX);
  q.observe(100, 900, 900, 500, false, false);
  q.observe(12000, 400, 900, 500, false, false);
  q.observe(12200, 400, 400, 500, false, true);
  assert(q.first_valid_after_ms == 200);
  assert(q.first_near_after_ms == 12100);
  assert(q.trigger_after_ms - q.first_near_after_ms == 200);
  q.finish(12300);
  q.begin(20000);
  q.finish(80000);  // No samples does not invent zero latency.
  assert(q.first_valid_after_ms == UINT32_MAX && q.trigger_after_ms == UINT32_MAX);
  const auto observed_before_reset = observation;
  UltrasonicSensor::resetHistory();
  echo_us = 0;
  assert(UltrasonicSensor::readDistanceCm() == 999.0f);
  assert(UltrasonicSensor::lastMedianDistanceCm() == 999.0f);
  assert(observation.armed_samples == observed_before_reset.armed_samples);
  assert(observation.idle_samples == 3 && observation.cooldown_samples == 1 && observation.armed_samples == 3);
  assert(UltrasonicSensor::diagnostics.samples == 1 && UltrasonicSensor::diagnostics.timeouts == 1);
}

static void testAdvertisementApplyRecovery() {
  sgk::PresenceAdvertisementPolicy policy;
  Radio radio;
  policy.request(false, 0, true);
  policy.service(0, true, false, false, radio);
  assert(policy.applied_valid && policy.applied_epoch == 0 && radio.applies == 1);
  assert(!policy.pending && policy.attempts == 1);
  policy.request(true, 42);
  policy.service(100, true, true, false, radio);
  assert(policy.pending && radio.applies == 1 && !policy.applied_ready);
  policy.service(200, true, false, true, radio);
  assert(policy.pending && radio.applies == 1 && radio.starts == 0 && radio.stops == 0);
  radio.apply_ok = false;
  policy.service(300, true, false, false, radio);
  assert(policy.failures == 1 && policy.pending && !policy.applied_valid);
  // A new desired epoch cannot bypass the backoff or be relabeled applied.
  policy.request(true, 43);
  policy.service(799, true, false, false, radio);
  assert(radio.applies == 2 && policy.applied_epoch == 0);
  radio.apply_ok = true;
  policy.service(800, true, false, false, radio);
  assert(policy.applied_valid && policy.applied_epoch == 43 && policy.applied_ready);
  assert(policy.retries == 1 && policy.stops == 1 && radio.starts == 1 && !policy.pending);
  // Force after external payload overwrite must apply identical ready/epoch.
  policy.request(true, 43, true);
  assert(!policy.applied_valid && policy.pending);
  policy.service(900, true, false, false, radio);
  assert(policy.applied_valid && radio.applies == 4);
  // Stopped advertiser with accepted data but rejected start remains pending.
  radio.running = false; radio.start_ok = false;
  policy.request(false, 44);
  policy.service(1000, true, false, false, radio);
  assert(!policy.applied_valid && policy.pending);
  assert(std::strcmp(policy.last_result, "START_FAILED") == 0);
  const uint32_t mutations = radio.applies + radio.starts + radio.stops;
  policy.service(2000, true, true, false, radio);
  policy.service(3000, true, false, true, radio);
  assert(mutations == radio.applies + radio.starts + radio.stops);
  radio.start_ok = true;
  policy.service(4000, true, false, false, radio);
  assert(!policy.pending && radio.running);
  // Repeated permanent apply errors remain bounded with no silent success.
  sgk::PresenceAdvertisementPolicy broken;
  Radio failed;
  failed.apply_ok = false;
  broken.request(true, 1);
  for (uint32_t ms = 0; ms < 60000; ++ms) {
    broken.request(true, ms / 50);
    broken.service(ms, true, false, false, failed);
  }
  assert(broken.pending && !broken.applied_valid && broken.failures <= 16);
  assert(broken.retries + 1 == broken.attempts);
  assert(failed.starts == 0 && failed.stops == 1 && !failed.running);
  // No controller access when disabled, missing advertiser or stop failure.
  sgk::PresenceAdvertisementPolicy absent;
  Radio unavailable;
  unavailable.present = false;
  absent.request(false, 7);
  absent.service(0, false, false, false, unavailable);
  assert(absent.attempts == 0);
  absent.service(1, true, false, false, unavailable);
  assert(absent.failures == 1 && unavailable.applies == 0);
  unavailable.present = true; unavailable.stop_ok = false;
  absent.service(501, true, false, false, unavailable);
  assert(absent.failures == 2 && unavailable.applies == 0);
  assert(std::strcmp(absent.last_result, "STOP_FAILED") == 0);
  sgk::PresenceAdvertisementPolicy gap;
  gap.observeController(UINT32_MAX - 99, false, true);
  assert(gap.gapMs(100) == 200 && gap.gap_count == 1);
  gap.observeController(100, true, true);
  assert(gap.last_gap_ms == 200 && gap.gapMs(200) == 0);
  gap.observeController(300, false, false);
  gap.observeController(5000, true, true);
  assert(gap.gap_count == 1);  // Connected/OTA exclusion is not a radio gap.
}

static void testRearmHistory() {
  using namespace sgk;
  PassageRearmPolicy p;
  assert(p.history().sequence == 0 && !p.history().has_clear);
  p.notePulse(UINT32_MAX - 100, PassagePulseSource::kSensor);
  for (int i = 0; i < 39; ++i) p.observeDistance(322, 800, i);
  assert(p.blocked() && p.history().sequence == 1); // Near samples cannot reopen.
  assert(p.blockedAgeMs(20) == 121);
  uint32_t now = 100;
  for (auto raw : {kNoSensorMeasurement, uint16_t(800), uint16_t(900)}) {
    p.observeDistance(901, 800, now++);
    p.observeDistance(1200, 800, now++);
    assert(p.clearSamples() == 2 && p.blocked());
    p.observeDistance(raw, 800, now++);
    assert(p.clearSamples() == 0 && p.blocked());
    assert(p.history().edges[p.history().count - 1].prior_clear_samples == 2);
  }
  assert(p.history().edges[1].reason == RearmEdgeReason::kInvalid);
  assert(p.history().edges[2].reason == RearmEdgeReason::kNear);
  assert(p.history().edges[3].reason == RearmEdgeReason::kBand);
  p.observeDistance(901, 800, now++);
  p.notePulse(now++, PassagePulseSource::kRemoteManual);
  assert(p.history().sequence == 5 && p.history().count == 4);
  assert(p.history().edges[3].reason == RearmEdgeReason::kPulse);
  p.observeDistance(901, 800, now++);
  p.observeDistance(901, 800, now++);
  p.observeDistance(901, 800, now);
  assert(!p.blocked() && p.history().has_clear && p.history().last_clear_ms == now);
  assert(p.history().edges[3].kind == RearmEdgeKind::kCleared);
  assert(p.history().edges[3].prior_clear_samples == 3);
  for (int i = 0; i < 8; ++i) {
    p.notePulse(++now);
    p.observe(true); p.observe(true); p.observe(true, ++now);
  }
  assert(p.history().sequence == 22 && p.history().count == 4);
  RearmHistory saturated = p.history();
  saturated.sequence = UINT32_MAX;
  saturated.record(0, RearmEdgeKind::kCleared, RearmEdgeReason::kClear, 3);
  assert(saturated.sequence == UINT32_MAX && saturated.count == 4);
  assert(saturated.has_clear && saturated.last_clear_ms == 0); // zero is observed
  p = {};
  assert(p.history().sequence == 0 && !p.history().has_clear); // boot-local only
}

int main() {
  testRearmHistory();
  testBoundedReauthentication();
  testActualSensorAndObservation();
  testAdvertisementApplyRecovery();
  std::puts("field recovery: reauth/pulse isolation, real ultrasonic median, cadence, diagnostics and bounded advertising recovery passed");
}
