// src/main.cpp
// =============================================================
// smart-gatekeeper v2.1 — BLE Beacon + MQTT Pre-arm + AJ-SR04T 방수 초음파 출입 통제
// (ESP32-C6 상시 비콘 발신 → 스마트폰 수신 → NAS 인증 → MQTT arm → 초음파 감지 → 릴레이)
// =============================================================
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

// BLE Beacon Advertiser — Arduino-ESP32 내장 Bluedroid BLE
#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <BLEUtils.h>

#include "config.h"
#include "ConfigManager.h"
#include "WifiManager.h"
#include "OtaManager.h"
#include "MqttManager.h"
#include "UltrasonicSensor.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

// ─────────────────────────────────────────────────────────────
// 릴레이 제어 — INPUT 모드 트릭 (3.3V ↔ 5V 릴레이 상시 ON 우회)
// ─────────────────────────────────────────────────────────────
static inline void relayOn() {
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, LOW);   // Active-LOW: LOW = 코일 통전 = ON
}

static inline void relayOff() {
  pinMode(PIN_RELAY, INPUT);      // 고임피던스: 전류 차단 = 확실한 OFF
}

// ─────────────────────────────────────────────────────────────
// FSM 상태 정의 (IDLE / ARMED / RELAY_HOLD / COOLDOWN)
// ─────────────────────────────────────────────────────────────
enum class GateState {
  IDLE,
  ARMED,
  RELAY_HOLD,
  COOLDOWN
};

static GateState state       = GateState::IDLE;
static uint32_t  stateMs     = 0;
static uint32_t  lastMqttMs  = 0;

// Pre-arm 상태 변수
static bool     is_armed      = false;
static uint32_t arm_timestamp = 0;  // millis() 기준 arm 활성화 시각

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
}

void setDistanceThresholdCm(int distanceCm) {
  if (distanceCm < 20) distanceCm = 20; // 초음파 맹점 하한선
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
  LOGF("[CONFIG-TUNING] ⚙️ Pre-arm 유효 시간 동적 변경 & NVS 저장: %lu ms", (unsigned long)g_pre_arm_duration_ms);
}

void setRelayCooldownMs(uint32_t cooldownMs) {
  if (cooldownMs < 1000) cooldownMs = 1000;
  if (cooldownMs > 30000) cooldownMs = 30000;
  g_relay_cooldown_ms = cooldownMs;
  ConfigManager::setRelayCooldownMs(cooldownMs);
  MqttManager::publishConfigState(g_tx_power_dbm, g_distance_threshold_cm, g_pre_arm_duration_ms, cooldownMs);
  LOGF("[CONFIG-TUNING] ⚙️ Target 릴레이 쿨다운 동적 변경 & NVS 저장: %lu ms", (unsigned long)g_relay_cooldown_ms);
}

// ─────────────────────────────────────────────────────────────
// triggerArm() — MqttManager 콜백에서 호출 (MQTT gatekeeper/arm 수신)
// ─────────────────────────────────────────────────────────────
void triggerArm() {
  is_armed      = true;
  arm_timestamp = millis();
  state         = GateState::ARMED;
  stateMs       = arm_timestamp;
  LOGF("[GATE] 🔑 PRE-ARMED 상태 진입! AJ-SR04T 초음파 센서 활성화 (%lu ms 유효)", (unsigned long)g_pre_arm_duration_ms);
}

// ─────────────────────────────────────────────────────────────
// triggerManualDoorOpen() — MQTT 원격 수동 개방 명령
// ─────────────────────────────────────────────────────────────
void triggerManualDoorOpen() {
  LOGF("[GATE-MANUAL] *** 원격/MQTT 명령으로 출입문 개방 릴레이 ON *** (딸깍!)");
  relayOn();
  state   = GateState::RELAY_HOLD;
  stateMs = millis();
}

// ─────────────────────────────────────────────────────────────
// BLE Beacon Advertiser 초기화 (Arduino-ESP32 내장 Bluedroid BLE)
// ─────────────────────────────────────────────────────────────
static void initBleAdvertiser() {
  LOGF("[BLE-ADV] BLE Beacon Advertiser 초기화 시작... (Arduino-ESP32 내장 Bluedroid 스택)");

  BLEDevice::init("SmartGatekeeper");
  BLEDevice::setPower(ESP_PWR_LVL_P9, ESP_BLE_PWR_TYPE_ADV);
  LOGF("[BLE-ADV] Tx Power: +9 dBm (최대 출력, 실외 10~15m 도달)");

  BLEAdvertising* pAdv = BLEDevice::getAdvertising();
  pAdv->addServiceUUID(GATEKEEPER_BEACON_UUID);
  pAdv->setScanResponse(true);
  pAdv->setAdvertisementType(0x02);
  pAdv->setMinInterval(0x00A0);
  pAdv->setMaxInterval(0x00A0);
  pAdv->setMinPreferred(0x00);
  pAdv->start();

  LOGF("[BLE-ADV] ✅ 비콘 발신 시작! Name: SmartGatekeeper | UUID: %s | ADV_TYPE_SCAN_IND (0x02)",
       GATEKEEPER_BEACON_UUID);
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

  // 1. 릴레이 초기화 (안전 상태: OFF)
  relayOff();

  // 2. 배너 출력
  LOGF("\n============================================");
  LOGF(" smart-gatekeeper v%s — BLE Beacon + MQTT Pre-arm + AJ-SR04T", FIRMWARE_VERSION);
  LOGF("============================================");

  // 3. NVS 설정 복원
  ConfigManager::begin();
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
    configTime(9 * 3600, 0, "pool.ntp.org", "time.nist.gov");
    LOGF("[TIME] NTP 시간 동기화 요청 (KST UTC+9)");
    
    struct tm timeinfo;
    uint32_t startMs = millis();
    LOGF("[TIME] 시간 동기화 대기 중...");
    while (!getLocalTime(&timeinfo, 1000) && (millis() - startMs < 10000)) {
      printf(".");
      fflush(stdout);
    }
    printf("\n");
    if (getLocalTime(&timeinfo, 0)) {
      LOGF("[TIME] 🕒 동기화 성공: %04d-%02d-%02d %02d:%02d:%02d", 
           timeinfo.tm_year + 1900, timeinfo.tm_mon + 1, timeinfo.tm_mday,
           timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);
    } else {
      LOGF("[TIME-ERROR] ❌ NTP 동기화 타임아웃!");
    }

    MqttManager::init();
    OtaManager::init();
  } else {
    LOGF("[WIFI] 접속 실패 -> AP 설정 모드로 전환합니다.");
    WifiManager::startAP();
  }

  // 5. AJ-SR04T 방수 초음파 센서 초기화
  UltrasonicSensor::init();

  // 6. BLE Beacon Advertiser 시작
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
  WifiManager::handleClient();
  MqttManager::update();

  uint32_t now = millis();

  // ─── 초음파 거리 측정 (is_armed == true 무장 상태일 때만 센서 작동) ───
  float distCm = -1.0f;
  bool validReading = false;

  if (is_armed && state == GateState::ARMED) {
    distCm = UltrasonicSensor::readDistanceCm();
    // 20cm 미만 맹점은 -1.0f 반환되므로, 20cm ~ g_distance_threshold_cm 범위만 유효
    validReading = (distCm >= ULTRASONIC_MIN_DISTANCE_CM && distCm <= (float)g_distance_threshold_cm);
  }

  // ─── Pre-arm 만료 체크 (ARMED 상태에서만 수행) ──────────────────────
  if (is_armed && (now - arm_timestamp >= g_pre_arm_duration_ms)) {
    LOGF("[GATE] ⏱️ Pre-arm 유효 시간 만료 (%lu ms 경과). IDLE 복귀.", (unsigned long)g_pre_arm_duration_ms);
    is_armed = false;
    state    = GateState::IDLE;
    MqttManager::publishEvent("arm_expired", "Pre-arm timeout, returning to IDLE");
  }

  // ─── Pre-arm 잔여 시간 계산 ─────────────────────────────────────
  uint32_t armRemainingMs = 0;
  if (is_armed && arm_timestamp > 0) {
    uint32_t elapsed = now - arm_timestamp;
    armRemainingMs = (elapsed < g_pre_arm_duration_ms) ? (g_pre_arm_duration_ms - elapsed) : 0;
  }

  // ─── 10초 주기 MQTT 텔레메트리 발행 ────────────────────────────────
  if (now - lastMqttMs >= 10000) {
    lastMqttMs = now;
    const char* stateStr = (state == GateState::IDLE)      ? "IDLE" :
                           (state == GateState::ARMED)      ? "ARMED" :
                           (state == GateState::RELAY_HOLD) ? "RELAY_HOLD" : "COOLDOWN";
    MqttManager::publishTelemetry(validReading ? (uint16_t)(distCm * 10.0f) : 0, stateStr, is_armed);

    if (is_armed) {
      LOGF("[GATE] PRE-ARMED 상태 유지 중. 잔여 유효 시간: %lu 초", (unsigned long)(armRemainingMs / 1000));
    }
  }

  // ─────────────────────────────────────────────────────────────
  // FSM (Finite State Machine)
  // ─────────────────────────────────────────────────────────────
  switch (state) {
    case GateState::IDLE:
      break;

    case GateState::ARMED:
      if (validReading) {
        LOGF("[GATE] ✅ ARMED 상태에서 초음파 %.1f cm 감지! (PRE-ARM 유효 — arm 경과: %lu ms)",
             distCm, (unsigned long)(now - arm_timestamp));
        LOGF("[GATE] *** 출입 승인! 릴레이 %lu ms ON *** (딸깍!)", (unsigned long)RELAY_HOLD_MS);

        relayOn();

        is_armed = false; // Pre-arm 소비 (단발 사용 & 즉시 무장 해제)
        MqttManager::publishEvent("door_open", "Access Granted via MQTT Pre-arm + Ultrasonic");

        state   = GateState::RELAY_HOLD;
        stateMs = millis();
      }
      break;

    case GateState::RELAY_HOLD:
      if (millis() - stateMs >= RELAY_HOLD_MS) {
        relayOff();
        LOGF("[GATE] 릴레이 OFF (%lu ms 경과). 쿨다운 진입.", (unsigned long)RELAY_HOLD_MS);
        MqttManager::publishEvent("door_close", "Relay Timeout OFF");
        state   = GateState::COOLDOWN;
        stateMs = millis();
      }
      break;

    case GateState::COOLDOWN:
      if (millis() - stateMs >= g_relay_cooldown_ms) {
        LOGF("[GATE] 🚪 릴레이 쿨다운 완료 (%lu ms) -> IDLE 대기 상태 복귀", (unsigned long)g_relay_cooldown_ms);
        state = GateState::IDLE;
        MqttManager::publishEvent("gate_idle", "Cooldown complete, ready for next Pre-arm");
      }
      break;
  }

  delay(ULTRASONIC_POLL_INTERVAL_MS);
}
