// src/main.cpp
// =============================================================
// smart-gatekeeper v2.1 — BLE Beacon + MQTT Pre-arm + AJ-SR04T 방수 초음파 출입 통제
// (ESP32-C6 상시 비콘 발신 → 스마트폰 수신 → NAS 인증 → MQTT arm → 초음파 감지 → 릴레이)
// =============================================================
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <Ticker.h>

#include <cstring>

// BLE Beacon Advertiser — Arduino-ESP32 내장 Bluedroid BLE
#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <BLEUtils.h>
#include <BLEBeacon.h>

#include "config.h"
#include "ConfigManager.h"
#include "DiagnosticsManager.h"
#include "WifiManager.h"
#include "OtaManager.h"
#include "MqttManager.h"
#include "UltrasonicSensor.h"
#include "RelayController.h"
#include "GattServer.h"
#include "TargetState.h"
#include "TargetAclManager.h"
#include "TargetProofVerifier.h"
#include "TargetAccessFsm.h"
#include "OfflineEventQueue.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

class NvsAclStorage final : public sgk::TargetAclStorage {
 public:
  bool saveSlot(uint8_t slot, const uint8_t* blob, size_t length) override {
    Preferences prefs;
    if (!prefs.begin("sgk_acl", false)) return false;
    char key[16] = {};
    std::snprintf(key, sizeof(key), "slot_%u", slot);
    size_t written = prefs.putBytes(key, blob, length);
    prefs.end();
    return written == length;
  }

  bool readSlot(uint8_t slot, uint8_t* buffer, size_t capacity,
                size_t* read_bytes) override {
    Preferences prefs;
    if (!prefs.begin("sgk_acl", true)) return false;
    char key[16] = {};
    std::snprintf(key, sizeof(key), "slot_%u", slot);
    size_t len = prefs.getBytesLength(key);
    if (len == 0 || len > capacity) {
      prefs.end();
      return false;
    }
    size_t read_len = prefs.getBytes(key, buffer, capacity);
    prefs.end();
    if (read_bytes != nullptr) *read_bytes = read_len;
    return read_len == len;
  }

  bool saveGenerationRecord(uint8_t record_index,
                             const sgk::GenerationRecord& record) override {
    Preferences prefs;
    if (!prefs.begin("sgk_acl", false)) return false;
    char key[16] = {};
    std::snprintf(key, sizeof(key), "gen_%u", record_index);
    size_t written = prefs.putBytes(key, &record, sizeof(record));
    prefs.end();
    return written == sizeof(record);
  }

  bool readGenerationRecord(uint8_t record_index,
                             sgk::GenerationRecord* record) override {
    Preferences prefs;
    if (!prefs.begin("sgk_acl", true)) return false;
    char key[16] = {};
    std::snprintf(key, sizeof(key), "gen_%u", record_index);
    size_t len = prefs.getBytesLength(key);
    if (len != sizeof(sgk::GenerationRecord)) {
      prefs.end();
      return false;
    }
    size_t read_len = prefs.getBytes(key, record, sizeof(sgk::GenerationRecord));
    prefs.end();
    return read_len == sizeof(sgk::GenerationRecord);
  }

  bool saveHighWatermark(uint64_t version) override {
    Preferences prefs;
    if (!prefs.begin("sgk_acl", false)) return false;
    size_t written = prefs.putBytes("hw_ver", &version, sizeof(version));
    prefs.end();
    return written == sizeof(version);
  }

  uint64_t readHighWatermark() override {
    Preferences prefs;
    if (!prefs.begin("sgk_acl", true)) return 0;
    uint64_t version = 0;
    prefs.getBytes("hw_ver", &version, sizeof(version));
    prefs.end();
    return version;
  }
};

static NvsAclStorage g_nvs_acl_storage;
sgk::TargetAclManager g_acl_manager(&g_nvs_acl_storage);
static sgk::TargetProofVerifier g_proof_verifier(
    g_acl_manager, []() -> uint32_t { return millis(); }, nullptr);

class NvsQueueStorage final : public sgk::OfflineQueueStorage {
 public:
  bool saveRecord(size_t slot, const sgk::CanonicalEvent& event) override {
    Preferences prefs;
    if (!prefs.begin("sgk_queue", false)) return false;
    char key[16] = {};
    std::snprintf(key, sizeof(key), "rec_%u", static_cast<unsigned int>(slot));
    size_t written = prefs.putBytes(key, &event, sizeof(event));
    prefs.end();
    return written == sizeof(event);
  }

  bool readRecord(size_t slot, sgk::CanonicalEvent* event) override {
    Preferences prefs;
    if (!prefs.begin("sgk_queue", true)) return false;
    char key[16] = {};
    std::snprintf(key, sizeof(key), "rec_%u", static_cast<unsigned int>(slot));
    size_t len = prefs.getBytesLength(key);
    if (len != sizeof(sgk::CanonicalEvent) || event == nullptr) {
      prefs.end();
      return false;
    }
    size_t read_len = prefs.getBytes(key, event, sizeof(sgk::CanonicalEvent));
    prefs.end();
    return read_len == sizeof(sgk::CanonicalEvent);
  }

  bool saveMetaRecord(uint8_t meta_slot, const sgk::QueueMetaRecord& meta) override {
    Preferences prefs;
    if (!prefs.begin("sgk_queue", false)) return false;
    char key[16] = {};
    std::snprintf(key, sizeof(key), "meta_%u", static_cast<unsigned int>(meta_slot));
    size_t written = prefs.putBytes(key, &meta, sizeof(meta));
    prefs.end();
    return written == sizeof(meta);
  }

  bool readMetaRecord(uint8_t meta_slot, sgk::QueueMetaRecord* meta) override {
    Preferences prefs;
    if (!prefs.begin("sgk_queue", true)) return false;
    char key[16] = {};
    std::snprintf(key, sizeof(key), "meta_%u", static_cast<unsigned int>(meta_slot));
    size_t len = prefs.getBytesLength(key);
    if (len != sizeof(sgk::QueueMetaRecord) || meta == nullptr) {
      prefs.end();
      return false;
    }
    size_t read_len = prefs.getBytes(key, meta, sizeof(sgk::QueueMetaRecord));
    prefs.end();
    return read_len == sizeof(sgk::QueueMetaRecord);
  }

  bool clearStorage() override {
    Preferences prefs;
    if (!prefs.begin("sgk_queue", false)) return false;
    bool ok = prefs.clear();
    prefs.end();
    return ok;
  }
};

static NvsQueueStorage g_nvs_queue_storage;

static inline void relayOn();
static inline void relayOff();

static sgk::TargetAccessFsm g_access_fsm(
    [](bool on) {
      if (on) relayOn();
      else relayOff();
    },
    [](const char* event, const char* message) {
      MqttManager::publishEvent(event, message);
      const uint64_t now_ms = millis();
      if (std::strcmp(event, "auth_verified_armed") == 0) {
        GattServer::notifyAccessArmed(now_ms);
      } else if (std::strcmp(event, "sensor_detected") == 0) {
        GattServer::notifySensorDetected(now_ms);
      } else if (std::strcmp(event, "relay_on_sensor") == 0) {
        GattServer::notifyRelayOn(now_ms);
      } else if (std::strcmp(event, "door_close") == 0) {
        GattServer::notifyRelayOff(now_ms, false);
      } else if (std::strcmp(event, "door_close_failsafe") == 0) {
        GattServer::notifyRelayOff(now_ms, true);
      } else if (std::strcmp(event, "session_completed") == 0) {
        GattServer::notifySessionCompleted(now_ms);
      } else if (std::strcmp(event, "session_terminated") == 0) {
        GattServer::notifySessionTerminated(now_ms,
                                            sgk::EventReason::kArmTimeout);
      }
    });

// ─────────────────────────────────────────────────────────────
// 릴레이 컨트롤러 인스턴스
// ─────────────────────────────────────────────────────────────
RelayController relay(PIN_RELAY, RELAY_ACTIVE_LOW);
static Ticker relayFailsafeTimer;
static volatile bool relayDeadlineActive = false;
static volatile bool relayFailsafeTriggered = false;
static uint32_t relayActivatedMs = 0;

static void forceRelayOffFromTimer() {
  // esp_timer task에서 실행된다. 네트워크 loop가 block되어도 물리 출력을 먼저 끈다.
  relay.off();
  DiagnosticsManager::noteRelayState(false, relay.pinLevel(),
                                     "relay_timer_off");
  relayDeadlineActive = false;
  relayFailsafeTriggered = true;
}

static inline void relayOn() {
  if (relay.isOn()) {
    DiagnosticsManager::noteAction("relay_on_duplicate");
    LOGF("[RELAY-WARN] 이미 ON 상태이므로 hold timer를 연장하지 않음");
    return;
  }

  LOGF("[RELAY] 릴레이 ON 상태로 변경 시도");
  relay.on();
  relayActivatedMs = millis();
  relayDeadlineActive = true;
  relayFailsafeTriggered = false;
  relayFailsafeTimer.once_ms(RELAY_HOLD_MS, forceRelayOffFromTimer);
  DiagnosticsManager::noteRelayState(true, relay.pinLevel(), "relay_on");
  LOGF("[RELAY] 릴레이 ON 상태로 변경 완료");
}

static inline void relayOff() {
  LOGF("[RELAY] 릴레이 OFF 상태로 변경 시도");
  relayFailsafeTimer.detach();
  relay.off();
  relayDeadlineActive = false;
  relayFailsafeTriggered = false;
  DiagnosticsManager::noteRelayState(false, relay.pinLevel(), "relay_off");
  LOGF("[RELAY] 릴레이 OFF 상태로 변경 완료");
}

// ─────────────────────────────────────────────────────────────
// I2C Bus Hang 복구 함수
// ─────────────────────────────────────────────────────────────
static void clearI2CBus(uint8_t sdaPin, uint8_t sclPin) {
  LOGF("[I2C] 버스 Hang 복구 시퀀스 시작 (SDA: %d, SCL: %d)", sdaPin, sclPin);
  pinMode(sdaPin, INPUT_PULLUP);
  pinMode(sclPin, INPUT_PULLUP);

  if (digitalRead(sdaPin) == LOW) {
    LOGF("[I2C] SDA 핀이 LOW 상태로 고정됨 감지! 클럭(SCL) 인가하여 해제 시도...");
    pinMode(sclPin, OUTPUT);
    for (int i = 0; i < 9; i++) {
      digitalWrite(sclPin, LOW);
      delayMicroseconds(5);
      digitalWrite(sclPin, HIGH);
      delayMicroseconds(5);
      if (digitalRead(sdaPin) == HIGH) {
        LOGF("[I2C] %d번째 클럭 펄스 후 SDA가 HIGH로 복구됨!", i + 1);
        break;
      }
    }
  }

  pinMode(sdaPin, OUTPUT);
  pinMode(sclPin, OUTPUT);
  digitalWrite(sdaPin, LOW);
  delayMicroseconds(5);
  digitalWrite(sclPin, HIGH);
  delayMicroseconds(5);
  digitalWrite(sdaPin, HIGH);
  delayMicroseconds(5);

  LOGF("[I2C] 버스 Hang 복구 시퀀스 종료");
}

// ─────────────────────────────────────────────────────────────
// FSM 상태 & Telemetry 보조 변수
// ─────────────────────────────────────────────────────────────
static uint32_t lastMqttMs = 0;

// ─────────────────────────────────────────────────────────────
// 엔지니어 원격 튜닝용 동적 설정 변수 (기본값: config.h 설정치, NVS 복원)
// ─────────────────────────────────────────────────────────────
uint16_t g_distance_threshold_cm = DEFAULT_DISTANCE_THRESHOLD_CM;
uint32_t g_pre_arm_duration_ms   = PRE_ARM_DURATION_MS;
uint32_t g_relay_cooldown_ms     = DEFAULT_RELAY_COOLDOWN_MS;
int      g_tx_power_dbm           = 9;

void setTxPower(int powerDbm) {
  g_tx_power_dbm = powerDbm;
  esp_power_level_t pwrLevel = ESP_PWR_LVL_P9;
  if (powerDbm <= -6)      pwrLevel = ESP_PWR_LVL_N6;
  else if (powerDbm <= 0)  pwrLevel = ESP_PWR_LVL_N0;
  else if (powerDbm <= 3)  pwrLevel = ESP_PWR_LVL_P3;
  else if (powerDbm <= 6)  pwrLevel = ESP_PWR_LVL_P6;
  else                     pwrLevel = ESP_PWR_LVL_P9;

  BLEDevice::setPower(pwrLevel, ESP_BLE_PWR_TYPE_ADV);
  ConfigManager::setTxPower(powerDbm);
  MqttManager::publishConfigState(g_tx_power_dbm, g_distance_threshold_cm, g_pre_arm_duration_ms, g_relay_cooldown_ms);
  LOGF("[CONFIG-TUNING] ⚙️ BLE Tx Power 동적 변경 & NVS 저장: %d dBm", powerDbm);

  // iBeacon payload needs to be updated with the new "Measured Power"
  BLEAdvertising* pAdv = BLEDevice::getAdvertising();
  pAdv->stop();

  BLEBeacon oBeacon = BLEBeacon();
  oBeacon.setManufacturerId(0x004C);
  BLEUUID bleUUID(GATEKEEPER_BEACON_UUID);

  // ─────────────────────────────────────────────────────────────
  // ⚠️ 검증 필요 (issue.md P2-13a) — 실측 전까지 이 블록을 고치지 말 것
  //
  // Apple iBeacon 은 UUID 를 MSB-first 로 광고한다. BLE 스택은 내부적으로
  // LSB-first 로 저장하므로 반전이 필요하다. 아래 조합
  //   (수동 16바이트 반전) + BLEUUID(..., msbFirst=false)
  // 은 내부 저장이 LSB-first 라는 전제에서 이론상 올바르다.
  //
  // 그러나 이 저장 순서는 BLE 스택(Bluedroid vs NimBLE)과 Arduino-ESP32
  // 버전에 따라 달라진다. 아래 getNative()->u128.value 는 NimBLE 타입
  // 필드인데(Bluedroid 는 ->uuid.uuid128) 주변 주석은 Bluedroid 라고 적고
  // 있어 실제 링크되는 스택이 불명확하다. (issue.md P2-13b)
  //
  // 틀리면 앱의 Region 필터가 절대 매칭되지 않아 RSSI 가 단 한 번도
  // 올라오지 않는다. 검증 방법은 하나뿐이다:
  //
  //   nRF Connect(또는 btmon)로 raw advertising 을 열어
  //   `4C 00 02 15` 다음 16바이트가 정확히 아래와 같은지 눈으로 확인한다.
  //     A1 B2 C3 D4 E5 F6 78 90 AB CD EF 12 34 56 78 90
  //   (UUID 가 회문이 아니므로 반전 여부가 즉시 구분된다)
  //
  //   역순으로 보이면 → 아래 반전 루프를 제거하거나 msbFirst 를 true 로.
  // ─────────────────────────────────────────────────────────────
  uint8_t uuid_bytes[16];
  memcpy(uuid_bytes, bleUUID.getNative()->u128.value, 16);
  for(int i=0; i<8; i++){
    uint8_t temp = uuid_bytes[i];
    uuid_bytes[i] = uuid_bytes[15-i];
    uuid_bytes[15-i] = temp;
  }

  oBeacon.setProximityUUID(BLEUUID(uuid_bytes, 16, false));
  // ⚠️ Arduino BLEBeacon 의 major/minor 는 엔디안 처리에 알려진 이슈가 있다.
  //    현재 앱은 major/minor 로 필터하지 않으므로 무해하지만, 나중에 필터를
  //    추가하면 ENDIAN_CHANGE_U16 처리가 필요하다. (issue.md P2-13e)
  oBeacon.setMajor(1);
  oBeacon.setMinor(1);
  // Approximate measured power (1m RSSI) based on TX power
  // A typical mapping: at 0 dBm, 1m RSSI is around -59 dBm.
  // ⚠️ 이 값은 추정치다. accuracy(거리) 값을 신뢰하려면 실제 1m RSSI 를
  //    측정해 보정해야 한다. 현재 앱은 RSSI 임계값만 쓰므로 영향은 없다.
  //    (issue.md P2-13d)
  int8_t measuredPower = -59 + powerDbm;
  oBeacon.setSignalPower(measuredPower);

  BLEAdvertisementData oAdvertisementData = BLEAdvertisementData();
  BLEAdvertisementData oScanResponseData = BLEAdvertisementData();

  // 표준 iBeacon 의 AD Flags 는 0x1A 다 (issue.md P2-13c):
  //   0x02 LE General Discoverable Mode
  //   0x18 BR/EDR Not Supported (0x04) + Simultaneous LE/BR-EDR (Controller/Host)
  // 기존 0x04 는 BR/EDR Not Supported 만 세팅해 non-discoverable 광고였다.
  // AltBeacon 은 manufacturer data 를 직접 파싱하므로 대개 동작하지만,
  // 일부 OEM BLE 스택이 non-discoverable 광고를 걸러낼 수 있다.
  // 페이로드 여유: flags 3B + manufacturer 27B = 30B ≤ 31B.
  oAdvertisementData.setFlags(0x1A);
  oAdvertisementData.setManufacturerData(oBeacon.getData());

  oScanResponseData.setName("SmartGatekeeper");
  if (GattServer::isEnabled()) {
    oScanResponseData.setCompleteServices(BLEUUID(HARDWARELESS_SERVICE_UUID));
  }

  pAdv->setMinInterval(160);
  pAdv->setMaxInterval(160);

  pAdv->setAdvertisementData(oAdvertisementData);
  pAdv->setScanResponseData(oScanResponseData);
  pAdv->start();
  LOGF("[CONFIG-TUNING] ⚙️ iBeacon 페이로드 (Measured Power %d) 업데이트 및 ADV 재시작 완료", measuredPower);
}

void setDistanceThresholdCm(int distanceCm) {
  if (distanceCm < 20) distanceCm = 20;
  if (distanceCm > 200) distanceCm = 200;
  g_distance_threshold_cm = (uint16_t)distanceCm;
  ConfigManager::setDistanceThresholdCm(distanceCm);
  MqttManager::publishConfigState(g_tx_power_dbm, distanceCm, g_pre_arm_duration_ms, g_relay_cooldown_ms);
  LOGF("[CONFIG-TUNING] ⚙️ 초음파 감지 기준 거리 동적 변경 & NVS 저장: %d cm", distanceCm);
}

void setTofDistanceCm(int distanceCm) {
  setDistanceThresholdCm(distanceCm);
}

void setPreArmDurationMs(uint32_t durationMs) {
  if (durationMs < 1000) durationMs = 1000;
  g_pre_arm_duration_ms = durationMs;
  ConfigManager::setPreArmDurationMs(durationMs);
  MqttManager::publishConfigState(g_tx_power_dbm, g_distance_threshold_cm, durationMs, g_relay_cooldown_ms);
  LOGF("[CONFIG-TUNING] ⚙️ Pre-arm 유효 시간 동적 변경 & NVS 저장: %lu ms", (unsigned long)durationMs);
}

void setRelayCooldownMs(uint32_t cooldownMs) {
  if (cooldownMs < 1000) cooldownMs = 1000;
  if (cooldownMs > 30000) cooldownMs = 30000;
  g_relay_cooldown_ms = cooldownMs;
  ConfigManager::setRelayCooldownMs(cooldownMs);
  MqttManager::publishConfigState(g_tx_power_dbm, g_distance_threshold_cm, g_pre_arm_duration_ms, cooldownMs);
  LOGF("[CONFIG-TUNING] ⚙️ Target 릴레이 쿨다운 동적 변경 & NVS 저장: %lu ms", (unsigned long)cooldownMs);
}

// ─────────────────────────────────────────────────────────────
// triggerArm() — MqttManager 콜백에서 호출 (MQTT gatekeeper/arm 수신)
// ─────────────────────────────────────────────────────────────
static OtaSafeState currentOtaSafeState() {
  // OtaManager is invoked from the MQTT callback and therefore temporarily
  // owns loopTask. Advance only already-authorized/physical session expiry so
  // manual_remote or legacy relay one-shots finish independently before OTA.
  g_access_fsm.tick(millis());
  return g_access_fsm.otaSafeState();
}

bool triggerArm() {
  if (g_access_fsm.handlePreArm(millis(), g_pre_arm_duration_ms)) {
    UltrasonicSensor::resetHistory();
    DiagnosticsManager::noteAction("pre_armed");
    LOGF("[GATE] 🔑 PRE-ARMED 상태 진입! AJ-SR04T 초음파 센서 활성화 (%lu ms 유효)",
         (unsigned long)g_pre_arm_duration_ms);
    return true;
  }
  DiagnosticsManager::noteAction("arm_rejected_not_idle");
  LOGF("[GATE-WARN] Pre-arm rejected: Target is not IDLE");
  return false;
}

// ─────────────────────────────────────────────────────────────
// triggerManualDoorOpen() — MQTT 원격 수동 개방 명령
// ─────────────────────────────────────────────────────────────
bool triggerManualDoorOpen() {
  if (g_access_fsm.handleManualRemoteOpen(millis(), RELAY_HOLD_MS, g_relay_cooldown_ms)) {
    DiagnosticsManager::noteAction("relay_on_manual");
    LOGF("[GATE-MANUAL] *** 원격/MQTT 명령으로 출입문 개방 릴레이 ON *** (딸깍!)");
    return true;
  }
  DiagnosticsManager::noteAction("manual_open_rejected_not_idle");
  LOGF("[GATE-MANUAL-WARN] manual open rejected: Target is not IDLE");
  return false;
}

// ─────────────────────────────────────────────────────────────
// BLE Beacon Advertiser 초기화 (Arduino-ESP32 내장 Bluedroid BLE)
// ─────────────────────────────────────────────────────────────
static void initBleAdvertiser() {
  LOGF("[BLE-ADV] iBeacon Advertiser 초기화 시작... (Arduino-ESP32 BLE 스택)");

  BLEDevice::init("SmartGatekeeper");

  bool hwlessEnable = sgk::effectiveFeatureEnabled(
      ConfigManager::getHardwarelessRcEnabled(false));
  GattServer::setEnabled(hwlessEnable);
  GattServer::useProductionEventSink();
  GattServer::setProofVerifier(&g_proof_verifier);
  GattServer::setOnAuthPendingCallback([](uint32_t now_ms) {
    g_access_fsm.handleAuthPending(now_ms, 5000);
  });
  GattServer::setOnAuthGrantCallback([](uint32_t now_ms) {
    g_access_fsm.handleAuthSuccess(now_ms, g_pre_arm_duration_ms, g_relay_cooldown_ms);
  });
  GattServer::setOnAuthAbortCallback([](uint32_t now_ms) {
    g_access_fsm.handleAuthAbort(now_ms, "gatt_auth_aborted");
  });
  GattServer::init();

  setTxPower(g_tx_power_dbm);

  LOGF("[BLE-ADV] ✅ iBeacon 발신 시작! UUID: %s (GATT Hardwareless RC: %s)",
       GATEKEEPER_BEACON_UUID, hwlessEnable ? "ENABLED" : "DISABLED");
}

// ─────────────────────────────────────────────────────────────
// setup()
// ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  uint32_t serialStart = millis();
  while (!Serial && (millis() - serialStart < 1500)) {
    delay(10);
  }
  delay(100);

  relay.begin();

  ConfigManager::begin();
  DiagnosticsManager::begin();

  clearI2CBus(6, 7);

  relayOff();

  LOGF("\n============================================");
  LOGF(" smart-gatekeeper v%s — BLE Beacon + MQTT Pre-arm + AJ-SR04T", FIRMWARE_VERSION);
  LOGF("============================================");

  // 3. NVS 설정 복원
  int savedTx = ConfigManager::getTxPower(9);
  int savedDist = ConfigManager::getDistanceThresholdCm(DEFAULT_DISTANCE_THRESHOLD_CM);
  uint32_t savedDur = ConfigManager::getPreArmDurationMs(PRE_ARM_DURATION_MS);
  uint32_t savedCool = ConfigManager::getRelayCooldownMs(DEFAULT_RELAY_COOLDOWN_MS);

  g_tx_power_dbm = savedTx;
  g_distance_threshold_cm = (uint16_t)savedDist;
  g_pre_arm_duration_ms = savedDur;
  g_relay_cooldown_ms = savedCool;

  LOGF("[CONFIG-NVS] ✅ NVS 플래시 저장 설정 복원 완료 -> Tx: %d dBm | 초음파 기준거리: %d cm | Duration: %lu ms | Relay Cooldown: %lu ms",
       g_tx_power_dbm, savedDist, (unsigned long)g_pre_arm_duration_ms, (unsigned long)g_relay_cooldown_ms);

  // 4. Wi-Fi 초기화
  WifiManager::init();

  if (WifiManager::connectSTA(10000)) {
    // Wall-clock time is not used by the Target. Avoid initializing lwIP's raw
    // UDP SNTP client from loopTask; reset diagnostics previously captured a
    // udp_new_ip_type core-lock assertion in this task.
    DiagnosticsManager::noteAction("network_services_start");
    MqttManager::init();
    OtaManager::setSafeStateProvider(currentOtaSafeState);
    OtaManager::init();
  } else {
    LOGF("[WIFI] 접속 실패 -> AP 설정 모드로 전환합니다.");
    WifiManager::startAP();
  }

  UltrasonicSensor::init();

  // 6. Target Access FSM & Offline Queue & ACL Manager 초기화
  g_offline_queue.setStorage(&g_nvs_queue_storage);
  g_offline_queue.begin();
  g_access_fsm.begin(millis());

  // Provision expected signing key ID
  uint32_t expectedKeyId = ConfigManager::getAclSigningKeyId();
  g_acl_manager.setExpectedSigningKeyId(expectedKeyId);

  // Provision production signer public key from configuration / NVS
  String signerHex = ConfigManager::getAclSignerPublicKeyHex();
  if (signerHex.length() == 130 && signerHex.startsWith("04")) {
    std::array<uint8_t, 65> signer_pubkey{};
    bool parse_ok = true;
    for (size_t i = 0; i < 65; ++i) {
      char byteStr[3] = {signerHex[i * 2], signerHex[i * 2 + 1], 0};
      char* endPtr = nullptr;
      signer_pubkey[i] = static_cast<uint8_t>(std::strtoul(byteStr, &endPtr, 16));
      if (endPtr != byteStr + 2) { parse_ok = false; break; }
    }
    if (parse_ok && g_acl_manager.setSignerPublicKey(signer_pubkey)) {
      LOGF("[ACL] ✅ Provisioned production ACL signer public key");
    } else {
      LOGF("[ACL-WARN] ⚠️ Malformed ACL signer public key; failing closed");
    }
  } else {
    LOGF("[ACL-INFO] ACL signer public key absent; ACL signature verification will fail closed");
  }

  std::array<uint8_t, 16> door_id{};
  if (ConfigManager::getHardwarelessDoorId(&door_id)) {
    g_acl_manager.begin(door_id, millis());
  }

  // 7. BLE Beacon Advertiser 시작
  initBleAdvertiser();

  LOGF("============================================");
  LOGF(" [SYSTEM] setup() 초기화 완료! 메인 루프 진입");
  LOGF(" [SYSTEM] FSM 초기 상태: IDLE (MQTT Pre-arm 대기)");
  LOGF("============================================");
}

// ─────────────────────────────────────────────────────────────
// loop()
// ─────────────────────────────────────────────────────────────
void loop() {
  uint32_t now = millis();
  g_access_fsm.tick(now);

  if (relayFailsafeTriggered) {
    relayFailsafeTriggered = false;
    DiagnosticsManager::noteAction("relay_timer_off");
    LOGF("[GATE] 독립 esp_timer가 릴레이를 OFF 처리함");
    MqttManager::publishEvent("door_close", "Independent timer relay OFF");
    g_access_fsm.handleRelayFailsafeOff(now, g_relay_cooldown_ms);
  }

  // 네트워크/TLS/WebServer보다 먼저 실행되는 독립 fail-safe.
  // FSM state가 잘못 덮여도 물리 릴레이는 RELAY_HOLD_MS 이후 반드시 OFF.
  if (relayDeadlineActive && (now - relayActivatedMs >= RELAY_HOLD_MS)) {
    relayOff();
    DiagnosticsManager::noteAction("relay_failsafe_off");
    LOGF("[GATE] 릴레이 독립 fail-safe OFF (%lu ms 경과)",
         (unsigned long)RELAY_HOLD_MS);
    MqttManager::publishEvent("door_close", "Independent relay fail-safe OFF");
    g_access_fsm.handleRelayFailsafeOff(now, g_relay_cooldown_ms);
  }

  WifiManager::handleClient();
  MqttManager::update();
  GattServer::update();

  now = millis();

  // ─── 초음파 거리 측정 (ARMED 상태에서만 동작) ───
  unsigned long durationUs = 0;
  float distCm = 999.0f;

  if (g_access_fsm.state() == GateState::ARMED) {
    distCm = UltrasonicSensor::readDistanceCm(&durationUs);
    // 20cm 미만 맹점은 -1.0f 반환되므로, 20cm ~ g_distance_threshold_cm 범위만 유효
    bool validReading = (distCm >= ULTRASONIC_MIN_DISTANCE_CM &&
                         distCm <= (float)g_distance_threshold_cm);
    if (validReading) {
      LOGF("[GATE] ✅ ARMED 상태에서 초음파 %.1f cm 감지!", distCm);
      g_access_fsm.handleSensorTrigger(now, RELAY_HOLD_MS, g_relay_cooldown_ms);
    }
  }

  // ─── 1초 주기 MQTT 텔레메트리 발행 (실시간 센서값 모니터링) ────────────────────────────────
  if (now - lastMqttMs >= 1000) {
    lastMqttMs = now;
    const char* stateStr =
        (g_access_fsm.state() == GateState::IDLE) ? "IDLE" :
        (g_access_fsm.state() == GateState::AUTH_PENDING) ? "AUTH_PENDING" :
        (g_access_fsm.state() == GateState::ARMED) ? "ARMED" :
        (g_access_fsm.state() == GateState::RELAY_HOLD) ? "RELAY_HOLD" : "COOLDOWN";
    uint16_t distance_mm = (distCm > 0.0f && distCm < 900.0f) ? (uint16_t)(distCm * 10.0f) : 9990;
    DiagnosticsManager::heartbeat(stateStr, g_access_fsm.isArmed(), relay.isOn(),
                                  relay.pinLevel());
    MqttManager::publishTelemetry(distance_mm, stateStr, g_access_fsm.isArmed(),
                                  0, relay.isOn(), relay.pinLevel());
  }

  delay(ULTRASONIC_POLL_INTERVAL_MS);
}
