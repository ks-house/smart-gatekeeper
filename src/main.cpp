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
#include <BLEBeacon.h>

#include "config.h"
#include "ConfigManager.h"
#include "WifiManager.h"
#include "OtaManager.h"
#include "MqttManager.h"
#include "UltrasonicSensor.h"
#include "RelayController.h"

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

// ─────────────────────────────────────────────────────────────
// 릴레이 컨트롤러 인스턴스
// ─────────────────────────────────────────────────────────────
RelayController relay(PIN_RELAY, RELAY_ACTIVE_LOW);

static inline void relayOn() {
  LOGF("[RELAY] 릴레이 ON 상태로 변경 시도");
  relay.on();
  LOGF("[RELAY] 릴레이 ON 상태로 변경 완료");
}

static inline void relayOff() {
  LOGF("[RELAY] 릴레이 OFF 상태로 변경 시도");
  relay.off();
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

  pAdv->setMinInterval(160); // 100ms (160 * 0.625ms) — Apple iBeacon 표준 추천 인터벌
  pAdv->setMaxInterval(160); // 100ms

  pAdv->setAdvertisementData(oAdvertisementData);
  pAdv->setScanResponseData(oScanResponseData);
  pAdv->start();
  LOGF("[CONFIG-TUNING] ⚙️ iBeacon 페이로드 (Measured Power %d) 업데이트 및 ADV 재시작 완료", measuredPower);
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
  LOGF("[BLE-ADV] iBeacon Advertiser 초기화 시작... (Arduino-ESP32 내장 Bluedroid 스택)");

  BLEDevice::init("SmartGatekeeper");

  // NVS에서 불러온 송신 출력을 기준으로 초기화
  setTxPower(g_tx_power_dbm);

  LOGF("[BLE-ADV] ✅ iBeacon 발신 시작! UUID: %s", GATEKEEPER_BEACON_UUID);
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

  // 0. I2C Bus Hang 현상 대비 (소프트 리셋 시 I2C 슬레이브 먹통 방지)
  // 현재 I2C 센서를 직접적으로 사용하고 있지 않지만, VL53L0X와 같은 센서 연결에 대비하여 복구 코드 삽입.
  // C6 보드의 I2C 핀: SDA=6, SCL=7 (GPIO 21, 22 사용 금지)
  clearI2CBus(6, 7);

  // 1. 릴레이 초기화 (안전 상태: OFF)
  relay.begin();
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

  // ─── 초음파 거리 측정 (실시간 모니터링을 위해 상시 작동) ───
  unsigned long durationUs = 0;
  float distCm = UltrasonicSensor::readDistanceCm(&durationUs);
  bool validReading = false;

  if (is_armed && state == GateState::ARMED) {
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

  // ─── 1초 주기 MQTT 텔레메트리 발행 (실시간 센서값 모니터링) ────────────────────────────────
  if (now - lastMqttMs >= 1000) {
    lastMqttMs = now;
    const char* stateStr = (state == GateState::IDLE)      ? "IDLE" :
                           (state == GateState::ARMED)      ? "ARMED" :
                           (state == GateState::RELAY_HOLD) ? "RELAY_HOLD" : "COOLDOWN";
    uint16_t distance_mm = (distCm > 0.0f && distCm < 900.0f) ? (uint16_t)(distCm * 10.0f) : 9990;
    MqttManager::publishTelemetry(distance_mm, stateStr, is_armed, armRemainingMs);
    MqttManager::publishSensorInfo(durationUs, distCm);

    LOGF("[SENSOR] 초음파 raw duration: %lu us, calculated distance: %.1f cm", durationUs, distCm);

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
