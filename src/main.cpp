// src/main.cpp
// =============================================================
// smart-gatekeeper v2.0 — BLE Beacon Advertiser + MQTT Pre-arm + ToF 출입 통제
// (ESP32-C6 상시 비콘 발신 → 스마트폰 비콘 수신 → NAS 인증 → MQTT arm → ToF 50cm → 릴레이)
// =============================================================
#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

// BLE Beacon Advertiser — Arduino-ESP32 내장 Bluedroid BLE (v2.0)
// NimBLE 교체 이유: NimBLE-Arduino 1.4.x가 pioarduino IDF5.x와 호환 불가 → 내장 Bluedroid 사용
// Advertiser 전용으로 Bluedroid이 충분하며 별도 라이브러리 불필요
#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include <BLEUtils.h>
// Note: ADV_TYPE_NONCONN_IND(=0x03) 은 esp_gap_ble_api.h 내부 상수이나
// 사용자 소스 파일에서 직접 include 불가(빌드 경로 제한) → 리터럴로 대체

#include "config.h"
#include "ConfigManager.h"
#include "WifiManager.h"
#include "OtaManager.h"
#include "MqttManager.h"

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
// FSM 상태 정의 (v2.0 — ARMED 상태 신규 도입)
// IDLE     : 대기 중 (ToF 측정 중단, 비콘 발신만 유지)
// ARMED    : MQTT Pre-arm 수신 후 ToF 활성화 (PRE_ARM_DURATION_MS 이내)
// RELAY_HOLD: 릴레이 1초 ON 유지 중
// COOLDOWN : 연속 요청 방지 쿨다운 (10초)
// ─────────────────────────────────────────────────────────────
enum class GateState {
  IDLE,
  ARMED,
  RELAY_HOLD,
  COOLDOWN
};

static VL53L0X sensor;
static GateState state       = GateState::IDLE;
static uint32_t  stateMs     = 0;
static uint32_t  lastMqttMs  = 0;

// Pre-arm 상태 변수
static bool     is_armed      = false;
static uint32_t arm_timestamp = 0;  // millis() 기준 arm 활성화 시각

// ─────────────────────────────────────────────────────────────
// 엔지니어 원격 튜닝용 동적 설정 변수 (기본값: config.h 설정치, NVS 복원)
// ─────────────────────────────────────────────────────────────
uint16_t g_distance_threshold_mm = DISTANCE_THRESHOLD_MM;
uint32_t g_pre_arm_duration_ms  = PRE_ARM_DURATION_MS;
int      g_tx_power_dbm          = 9;

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
  MqttManager::publishConfigState(g_tx_power_dbm, (int)(g_distance_threshold_mm / 10), g_pre_arm_duration_ms);
  LOGF("[CONFIG-TUNING] ⚙️ BLE Tx Power 동적 변경 & NVS 저장: %d dBm", powerDbm);
}

void setTofDistanceCm(int distanceCm) {
  if (distanceCm < 5) distanceCm = 5;
  if (distanceCm > 200) distanceCm = 200;
  g_distance_threshold_mm = (uint16_t)(distanceCm * 10);
  ConfigManager::setTofDistanceCm(distanceCm);
  MqttManager::publishConfigState(g_tx_power_dbm, distanceCm, g_pre_arm_duration_ms);
  LOGF("[CONFIG-TUNING] ⚙️ ToF 감지 거리 동적 변경 & NVS 저장: %d cm (%u mm)", distanceCm, g_distance_threshold_mm);
}

void setPreArmDurationMs(uint32_t durationMs) {
  if (durationMs < 1000) durationMs = 1000;
  g_pre_arm_duration_ms = durationMs;
  ConfigManager::setPreArmDurationMs(durationMs);
  MqttManager::publishConfigState(g_tx_power_dbm, (int)(g_distance_threshold_mm / 10), durationMs);
  LOGF("[CONFIG-TUNING] ⚙️ Pre-arm 유효 시간 동적 변경 & NVS 저장: %lu ms", (unsigned long)g_pre_arm_duration_ms);
}


// ─────────────────────────────────────────────────────────────
// triggerArm() — MqttManager 콜백에서 호출 (MQTT gatekeeper/arm 수신)
// ─────────────────────────────────────────────────────────────
void triggerArm() {
  is_armed      = true;
  arm_timestamp = millis();
  state         = GateState::ARMED;
  stateMs       = arm_timestamp;
  LOGF("[GATE] 🔑 PRE-ARMED 상태 진입! ToF 센서 활성화 (%lu ms 유효)", (unsigned long)g_pre_arm_duration_ms);
}


// ─────────────────────────────────────────────────────────────
// triggerManualDoorOpen() — MQTT 원격 수동 개방 명령 (기존 유지)
// ─────────────────────────────────────────────────────────────
void triggerManualDoorOpen() {
  LOGF("[GATE-MANUAL] *** 원격/MQTT 명령으로 출입문 개방 릴레이 ON *** (딸깍!)");
  relayOn();
  state   = GateState::RELAY_HOLD;
  stateMs = millis();
}

// ─────────────────────────────────────────────────────────────
// BLE Beacon Advertiser 초기화 (Arduino-ESP32 내장 Bluedroid BLE, v2.0)
// 목표: 실외 10~15m 도달 범위, Non-connectable 비콘 상시 발신
// 스마트폰 앱은 이 UUID를 수신하면 NAS 인증 절차를 개시한다
// ─────────────────────────────────────────────────────────────
static void initBleAdvertiser() {
  LOGF("[BLE-ADV] BLE Beacon Advertiser 초기화 시작... (Arduino-ESP32 내장 Bluedroid 스택)");

  // Bluedroid BLE 스택 초기화
  BLEDevice::init("SmartGatekeeper");

  // Tx Power 최대 설정 (+9 dBm) — 실외 10~15m 도달 목표
  // ESP_PWR_LVL_P9: +9 dBm (ESP32-C6 BLE 5.3 허용 범위 내)
  BLEDevice::setPower(ESP_PWR_LVL_P9, ESP_BLE_PWR_TYPE_ADV);
  LOGF("[BLE-ADV] Tx Power: +9 dBm (최대 출력, 실외 10~15m 도달)");

  BLEAdvertising* pAdv = BLEDevice::getAdvertising();

  // 광고 페이로드: 128-bit 서비스 UUID 포함
  // 스마트폰 앱이 이 UUID를 수신하면 NAS 인증 절차를 개시한다
  pAdv->addServiceUUID(GATEKEEPER_BEACON_UUID);

  // Scan Response에 장치 이름 실어 전송
  pAdv->setScanResponse(true);

  // Scannable 비연결형 광고 모드 설정 (연결 시도 차단 & Scan Response 수신으로 이름 노출)
  // ADV_TYPE_SCAN_IND = 0x02 (esp_gap_ble_api.h의 esp_ble_adv_type_t enum)
  // 0x03(NONCONN_IND)과 달리 스캔 요청(SCAN_REQ)에 응답하여 "SmartGatekeeper" 이름을 nRF Connect 등에 노출
  pAdv->setAdvertisementType(0x02);

  // 광고 인터벌: 100ms (0x00A0 = 160 x 0.625ms)
  pAdv->setMinInterval(0x00A0);
  pAdv->setMaxInterval(0x00A0);

  // 비콘 발신 시작 (무한 지속)
  pAdv->setMinPreferred(0x00);
  pAdv->start();

  LOGF("[BLE-ADV] ✅ 비콘 발신 시작! Name: SmartGatekeeper | UUID: %s | ADV_TYPE_SCAN_IND (0x02) | 무한 지속",
       GATEKEEPER_BEACON_UUID);
}

// ─────────────────────────────────────────────────────────────
// setup()
// ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // Native USB CDC 연결 안정화 대기 (재부팅 시 초반 OTA / Wifi 시리얼 로그 유실 완전 방지)
  uint32_t serialStart = millis();
  while (!Serial && (millis() - serialStart < 1500)) {
    delay(10);
  }
  delay(100);

  // 1. 릴레이 초기화 (안전 상태: OFF)
  relayOff();

  // 2. VL53L0X XSHUT 핀 HIGH 구동
  pinMode(PIN_TOF_XSHUT, OUTPUT);
  digitalWrite(PIN_TOF_XSHUT, HIGH);
  delay(10);

  // 3. I2C 버스 초기화 (400kHz 명시 필수 — raw/ST_VL53L0X_Specs.md 참조)
  Wire.begin(PIN_SDA, PIN_SCL, 400000UL);
  delay(20);

  // 4. 배너 출력
  LOGF("\n============================================");
  LOGF(" smart-gatekeeper v%s — BLE Beacon + MQTT Pre-arm", FIRMWARE_VERSION);
  LOGF("============================================");

  // 5. WiFi 초기화 및 NVS Wi-Fi 접속 시도
  ConfigManager::begin();
  int savedTx = ConfigManager::getTxPower(9);
  int savedTof = ConfigManager::getTofDistanceCm(50);
  uint32_t savedDur = ConfigManager::getPreArmDurationMs(60000);

  g_tx_power_dbm = savedTx;
  g_distance_threshold_mm = (uint16_t)(savedTof * 10);
  g_pre_arm_duration_ms = savedDur;

  LOGF("[CONFIG-NVS] ✅ NVS 플래시 저장 설정 복원 완료 -> Tx: %d dBm | ToF: %d cm (%u mm) | Duration: %lu ms",
       g_tx_power_dbm, savedTof, g_distance_threshold_mm, (unsigned long)g_pre_arm_duration_ms);

  WifiManager::init();

  if (WifiManager::connectSTA(10000)) {
    // Wi-Fi 연결 성공 시 NTP 시간 동기화 (TLS 안정성 보장)
    configTime(9 * 3600, 0, "pool.ntp.org", "time.nist.gov");
    LOGF("[TIME] NTP 시간 동기화 요청 (KST UTC+9)");
    
    // TLS Root CA 인증서 검증(유효기간)을 위해 시간 동기화가 완료될 때까지 확실히 대기
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
      LOGF("[TIME-ERROR] ❌ NTP 동기화 타임아웃! (인증서 검증에 실패할 수 있습니다)");
    }

    // MQTT 및 OTA 관리자 초기화
    MqttManager::init();
    OtaManager::init();

    LOGF("[OTA] 부팅 시 자동 OTA 체크 비활성화 상태. (MQTT/HA 수동 OTA 트리거만 유지)");
  } else {
    LOGF("[WIFI] 접속 실패 -> AP 설정 모드로 전환합니다.");
    WifiManager::startAP();
  }

  // 6. VL53L0X 센서 초기화 (항상 초기화, 측정은 ARMED 상태에서만 수행)
  sensor.setTimeout(500); // init() 전 반드시 설정 (I2C 단선 시 무한 블로킹 방지)
  LOGF("[INFO] ToF 센서 초기화 중...");
  if (!sensor.init()) {
    LOGF("[WARN] VL53L0X init 실패 (센서 연결 상태 점검 필요)");
  } else {
    // 연속 측정 모드 시작 (항상 준비 상태 유지, ARMED 여부는 FSM이 판단)
    sensor.startContinuous(TOF_POLL_INTERVAL_MS);
    LOGF("[INFO] ToF 센서 초기화 성공! (연속 측정 모드, ARMED 상태에서만 활용)");
  }

  // 7. BLE Beacon Advertiser 시작 (v2.0 핵심 — 스캐너 완전 대체)
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
  // AP 모드일 때 웹 서버 및 Captive Portal 요청 처리
  if (WifiManager::isAPMode()) {
    WifiManager::handleClient();
    delay(10);
    return;
  }

  // MQTT 루프 처리 (이 안에서 triggerArm, triggerManualDoorOpen 호출 가능)
  MqttManager::update();

  uint32_t now = millis();

  // ─── ToF 거리 측정 (ARMED 상태에서만 실질적으로 활용) ───────────────
  uint16_t mm = sensor.readRangeContinuousMillimeters();
  bool validReading = !(sensor.timeoutOccurred() || mm == 65535);

  // ─── Pre-arm 만료 체크 (ARMED 상태에서만 수행) ──────────────────────
  if (is_armed && (now - arm_timestamp >= g_pre_arm_duration_ms)) {
    LOGF("[GATE] ⏱️ Pre-arm 유효 시간 만료 (%lu ms 경과). IDLE 복귀.", (unsigned long)g_pre_arm_duration_ms);
    is_armed = false;
    state    = GateState::IDLE;
    MqttManager::publishEvent("arm_expired", "Pre-arm timeout, returning to IDLE");
  }

  // ─── Pre-arm 잔여 시간 계산 (텔레메트리용) ──────────────────────────
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
    MqttManager::publishTelemetry(validReading ? mm : 0, stateStr, is_armed);

    // Pre-arm 잔여 시간을 별도 이벤트로 발행 (ARMED 상태일 때만)
    if (is_armed) {
      LOGF("[GATE] PRE-ARMED 상태 유지 중. 잔여 유효 시간: %lu 초", (unsigned long)(armRemainingMs / 1000));
    }
  }

  // ─────────────────────────────────────────────────────────────
  // FSM (Finite State Machine) — v2.0
  // ─────────────────────────────────────────────────────────────
  switch (state) {

    // ──────────────────────────────────────────────────────────
    // IDLE: MQTT Pre-arm 대기 상태
    // ToF 측정 결과는 무시 (is_armed == false)
    // BLE Beacon만 상시 발신 중
    // ──────────────────────────────────────────────────────────
    case GateState::IDLE:
      // IDLE 상태에서 ToF 감지는 완전히 무시 (미인증 접근자 차단)
      // triggerArm() 호출 시 ARMED 상태로 전이 (MqttManager 콜백 경로)
      break;

    // ──────────────────────────────────────────────────────────
    // ARMED: MQTT Pre-arm 수신 후 ToF 활성 상태 (최대 PRE_ARM_DURATION_MS)
    // 50cm 이내 감지 시 릴레이 1초 ON → RELAY_HOLD → COOLDOWN
    // ──────────────────────────────────────────────────────────
    case GateState::ARMED:
      if (validReading && mm <= g_distance_threshold_mm) {

        LOGF("[GATE] ✅ ARMED 상태에서 ToF %u mm 감지! (PRE-ARM 유효 — arm 경과: %lu ms)",
             mm, (unsigned long)(now - arm_timestamp));
        LOGF("[GATE] *** 출입 승인! 릴레이 %lu ms ON *** (딸깍!)", (unsigned long)RELAY_HOLD_MS);

        relayOn();

        is_armed = false; // Pre-arm 소비 (단발 사용)
        MqttManager::publishEvent("door_open", "Access Granted via MQTT Pre-arm + ToF");

        state   = GateState::RELAY_HOLD;
        stateMs = millis();

      } else if (!validReading) {
        // ToF 읽기 오류 — 실외 태양광 간섭 가능성 (로그만 남김)
        static uint32_t lastTofErrMs = 0;
        if (now - lastTofErrMs >= 3000) {
          lastTofErrMs = now;
          LOGF("[WARN] ARMED 상태에서 ToF 유효하지 않은 읽기 (태양광 IR 간섭 또는 센서 오류 의심)");
        }
      }
      break;

    // ──────────────────────────────────────────────────────────
    // RELAY_HOLD: 릴레이 1초 ON 유지
    // ──────────────────────────────────────────────────────────
    case GateState::RELAY_HOLD:
      if (millis() - stateMs >= RELAY_HOLD_MS) {
        relayOff();
        LOGF("[GATE] 릴레이 OFF (%lu ms 경과). 쿨다운 진입.", (unsigned long)RELAY_HOLD_MS);
        MqttManager::publishEvent("door_close", "Relay Timeout OFF");
        state   = GateState::COOLDOWN;
        stateMs = millis();
      }
      break;

    // ──────────────────────────────────────────────────────────
    // COOLDOWN: 연속 개방 방지 (COOLDOWN_MS = 10초)
    // 쿨다운 종료 시 IDLE 복귀 (다음 Pre-arm 준비)
    // ──────────────────────────────────────────────────────────
    case GateState::COOLDOWN:
      if (millis() - stateMs >= COOLDOWN_MS) {
        LOGF("[GATE] 🚪 쿨다운 완료 -> IDLE 대기 상태 복귀 (다음 MQTT Pre-arm 승인 대기)");
        state = GateState::IDLE;
        MqttManager::publishEvent("gate_idle", "Cooldown complete, ready for next Pre-arm");
      }
      break;
  }

  delay(TOF_POLL_INTERVAL_MS);
}
