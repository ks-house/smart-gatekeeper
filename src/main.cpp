// src/main.cpp
// =============================================================
// smart-gatekeeper — Step 4: BLE 5.0 스캔 & ToF 이중 검증 (Walk-through) 펌웨어
// (BLEDevice 비동기 스캔 + ToF 50cm 감지 + NAS HTTPS API + MQTTS + OTA + 릴레이)
// =============================================================
#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

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

// FSM 상태
enum class GateState {
  IDLE,         // 대기 중 (BLE & ToF 감시)
  VERIFYING,    // NAS HTTPS API 요청 및 인증 대기 중
  RELAY_HOLD,   // 인증 승인 -> 릴레이 1초 ON 유지 중
  COOLDOWN      // 연속 요청 방지 쿨다운 중 (10초)
};

static VL53L0X sensor;
static GateState state                  = GateState::IDLE;
static uint32_t  stateMs                = 0;
static uint32_t  lastMqttMs             = 0;
uint32_t         last_ble_detected_time = 0; // BLE 타겟 스마트폰 감지 최신 시각 (MqttManager에서도 참조)
static uint32_t  last_ble_log_time      = 0; // BLE 로그 출력 과도 스팸 방지 디바운싱 시각
static uint32_t  last_ble_mqtt_pub_time = 0; // BLE RSSI MQTT 실시간 발신 디바운싱 시각
int              last_target_ble_rssi   = 0; // 인증된 타겟 BLE 스마트폰 실시간 RSSI 값
static int       currentBleRssiThreshold = -80; // 동적 BLE RSSI 임계값 (NVS 및 MQTT로 제어)

void updateBleRssiThreshold(int newRssi) {
  currentBleRssiThreshold = newRssi;
  ConfigManager::setBleRssiThreshold(newRssi);
  LOGF("[BLE-CONFIG] ⚙️ BLE RSSI 임계값이 %d dBm 으로 동적 변경 & NVS 저장되었습니다!", newRssi);
}

// ─────────────────────────────────────────────────────────────
// ESP32 BLE 비동기 스캔 콜백 클래스 (NON-CONNECTABLE & 128-bit Raw Payload 완벽 대응)
// ─────────────────────────────────────────────────────────────
class BleScanCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) override {
    int rssi = advertisedDevice.getRSSI();

    bool uuidMatch = false;

    // 1. 표준 Service UUID 객체 검사
    if (advertisedDevice.haveServiceUUID()) {
      BLEUUID devUUID = advertisedDevice.getServiceUUID();
      String devUUIDStr = devUUID.toString().c_str();
      if (devUUID.equals(BLEUUID(BLE_TARGET_UUID)) || devUUIDStr.equalsIgnoreCase(BLE_TARGET_UUID)) {
        uuidMatch = true;
      }
    }

    // 2. NON-CONNECTABLE (ADV_NONCONN_IND) Raw Payload 128-bit UUID 바이트 매칭
    if (!uuidMatch && advertisedDevice.getPayloadLength() > 0) {
      uint8_t* payload = advertisedDevice.getPayload();
      size_t len = advertisedDevice.getPayloadLength();

      static const uint8_t targetUuidLittle[16] = {
        0xbc, 0x9a, 0x78, 0x56, 0x34, 0x12, 0x34, 0x12,
        0x34, 0x12, 0x34, 0x12, 0x78, 0x56, 0x34, 0x12
      };
      static const uint8_t targetUuidBig[16] = {
        0x12, 0x34, 0x56, 0x78, 0x12, 0x34, 0x12, 0x34,
        0x12, 0x34, 0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc
      };

      for (size_t i = 0; i <= len - 16; i++) {
        if (memcmp(payload + i, targetUuidLittle, 16) == 0 ||
            memcmp(payload + i, targetUuidBig, 16) == 0) {
          uuidMatch = true;
          break;
        }
      }
    }

    // 3. Name 또는 Address / MAC 검사
    String devName = advertisedDevice.getName().c_str();
    String devAddr = advertisedDevice.getAddress().toString().c_str();

    if (uuidMatch || devName.indexOf("SmartKey") >= 0 || devAddr.equalsIgnoreCase(TEST_BLE_MAC)) {
      uint32_t nowMs = millis();
      last_ble_detected_time = nowMs; // 백그라운드 BLE 감지 시각은 매 250ms마다 즉시 갱신 (ToF 검증용)
      last_target_ble_rssi = rssi;     // 실시간 감도 RSSI 값 저장

      // 인증된 BLE 타겟 감지 시 1초마다 MQTT 실시간 전파 (스마트폰 신호 세기 실시간 모니터링)
      if (nowMs - last_ble_mqtt_pub_time >= 1000) {
        last_ble_mqtt_pub_time = nowMs;
        MqttManager::publishBleRssi(rssi);
      }

      // 로그 시리얼 출력 스팸 억제 (3초에 1번만 조용하게 출력)
      if (nowMs - last_ble_log_time >= 3000) {
        last_ble_log_time = nowMs;
        if (rssi >= currentBleRssiThreshold) {
          LOGF("[BLE-SCAN] 📱 Target BLE (128-bit UUID) 감지 중! RSSI: %d dBm (임계값: %d dBm)", rssi, currentBleRssiThreshold);
        } else {
          LOGF("[BLE-SCAN] Target BLE 감지되었으나 신호 약함 (RSSI: %d dBm < %d dBm)", rssi, currentBleRssiThreshold);
        }
      }
    }
  }
};

// MQTT 원격 명령 수신 시 호출되는 수동 문 열기 함수
void triggerManualDoorOpen() {
  LOGF("[GATE-MANUAL] *** 원격/MQTT 명령으로 출입문 개방 릴레이 ON *** (딸깍!)");
  relayOn();
  state = GateState::RELAY_HOLD;
  stateMs = millis();
}

// ─────────────────────────────────────────────────────────────
// 시놀로지 NAS HTTPS POST 자격 검증 API 호출 함수
// ─────────────────────────────────────────────────────────────
static bool requestNASVerification(uint16_t distance_mm) {
  if (!WifiManager::isConnected()) {
    LOGF("[WARN] Wi-Fi 미연결 상태 — 자격 검증 요청 건너뜀");
    return false;
  }

  String apiUrl = ConfigManager::getApiUrl();
  String apiKey = ConfigManager::getApiKey();

  LOGF("[HTTPS] NAS API 인증 요청 중... (%s)", apiUrl.c_str());

  WiFiClientSecure client;
  client.setCACert(SECRET_ROOT_CA_CERT);  // TLS Root CA 검증 (Let's Encrypt ISRG Root X1)

  HTTPClient http;
  if (!http.begin(client, apiUrl)) {
    LOGF("[ERROR] HTTPS 연결 실패: URL 파싱 에러");
    return false;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-KEY", apiKey);
  http.setTimeout(8000);  // 8초 타임아웃

  StaticJsonDocument<256> doc;
  doc["ble_mac"]     = TEST_BLE_MAC;
  doc["auth_key"]    = apiKey;
  doc["distance_mm"] = distance_mm;

  String requestBody;
  serializeJson(doc, requestBody);

  LOGF("[HTTPS] Request Body: %s", requestBody.c_str());

  int httpCode = http.POST(requestBody);
  bool isAuthorized = false;

  if (httpCode > 0) {
    String responseBody = http.getString();
    LOGF("[HTTPS] HTTP Status: %d | Response: %s", httpCode, responseBody.c_str());

    if (httpCode == HTTP_CODE_OK || httpCode == 201) {
      StaticJsonDocument<512> respDoc;
      DeserializationError err = deserializeJson(respDoc, responseBody);

      if (!err) {
        bool granted = respDoc["granted"] | respDoc["authorized"] | false;
        const char* msg = respDoc["message"] | "응답 메시지 없음";
        const char* tenant = respDoc["tenant_name"] | "알 수 없음";

        LOGF("[HTTPS] 파싱 결과: granted=%s | 세입자: %s | 메시지: %s",
             granted ? "TRUE" : "FALSE", tenant, msg);

        isAuthorized = granted;
      } else {
        LOGF("[ERROR] JSON 파싱 실패: %s", err.c_str());
      }
    } else {
      LOGF("[ERROR] 서버 응답 오류 HTTP Code: %d", httpCode);
    }
  } else {
    LOGF("[ERROR] HTTPS POST 실패, 에러: %s", http.errorToString(httpCode).c_str());
  }

  http.end();
  return isAuthorized;
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

  // 1. 릴레이 초기화
  relayOff();

  // 2. VL53L0X XSHUT 핀 HIGH 구동
  pinMode(PIN_TOF_XSHUT, OUTPUT);
  digitalWrite(PIN_TOF_XSHUT, HIGH);
  delay(10);

  // 3. I2C 버스 초기화
  Wire.begin(PIN_SDA, PIN_SCL, 400000UL);
  delay(20);

  // 4. 배너 출력
  LOGF("\n============================================");
  LOGF(" smart-gatekeeper v%s — BLE 5.0 & ToF 이중 검증 펌웨어", FIRMWARE_VERSION);
  LOGF("============================================");

  // 5. WifiManager 초기화 및 NVS Wi-Fi 접속 시도
  WifiManager::init();
  if (WifiManager::connectSTA(10000)) {
    // Wi-Fi 연결 성공 시 NTP 시간 동기화 (TLS 안정성 보장)
    configTime(9 * 3600, 0, "pool.ntp.org", "time.nist.gov");
    LOGF("[TIME] NTP 시간 동기화 요청 (KST UTC+9)");

    // MQTT 및 OTA 관리자 초기화
    MqttManager::init();
    OtaManager::init();

    // 부팅 시 시놀로지 NAS version.json 기반 자동 OTA 체크 (사용자 요청으로 잠시 Disable, 수동 OTA만 유지)
    // LOGF("[OTA] 부팅 시 펌웨어 업데이트 확인 시작...");
    // OtaManager::checkAndUpdate(false);
    LOGF("[OTA] 부팅 시 자동 OTA 체크가 비활성화 상태입니다. (MQTT/HA 수동 OTA 트리거만 유지)");
  } else {
    LOGF("[WIFI] 접속 실패 -> AP 설정 모드로 전환합니다.");
    WifiManager::startAP();
  }

  // 6. VL53L0X 센서 초기화
  sensor.setTimeout(500);
  LOGF("[INFO] ToF 센서 초기화 중...");
  if (!sensor.init()) {
    LOGF("[WARN] VL53L0X init 실패 (센서 연결 상태 점검 필요)");
  } else {
    sensor.startContinuous(TOF_POLL_INTERVAL_MS);
    LOGF("[INFO] ToF 센서 초기화 성공!");
  }

  // NVS 저장소에서 동적 BLE RSSI 임계값 불러오기
  currentBleRssiThreshold = ConfigManager::getBleRssiThreshold();

  // 7. BLE 5.0 비동기 스캐너 시작 (setup의 맨 마지막 단계에서 비동기 구동)
  LOGF("[BLE] 7. BLE 5.0 비동기 스캐너 시작 (Active Scan 활성화)");
  BLEDevice::init("SmartGatekeeper-Scan");
  BLEScan* pScan = BLEDevice::getScan();
  pScan->setAdvertisedDeviceCallbacks(new BleScanCallbacks(), true); // duplicates 수신 허용
  pScan->setActiveScan(true); // Active Scan: Scan Response 데이터 요청 (휴대폰 128bit UUID 수신 필수!)
  pScan->setInterval(100);
  pScan->setWindow(99);
  pScan->start(0, nullptr, false); // 0, nullptr: 메인 스레드 멈춤 없는 순수 백그라운드 비동기 스캔
  LOGF("[BLE] 타겟 UUID: %s | RSSI 임계값: %d dBm | 유효 시간: %lu ms",
       BLE_TARGET_UUID, currentBleRssiThreshold, (unsigned long)BLE_VALID_MS);

  LOGF("============================================");
  LOGF(" [SYSTEM] setup() 초기화 완료! 메인 루프 진입");
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

  // MQTT 루프 처리 (이 안에서 triggerManualDoorOpen이 호출될 수 있음)
  MqttManager::update();

  uint32_t now = millis(); // MQTT 수신 후 최신 시각으로 갱신

  // ToF 거리 측정
  uint16_t mm = sensor.readRangeContinuousMillimeters();
  bool validReading = !(sensor.timeoutOccurred() || mm == 65535);

  // 10초 주기 MQTT 텔레메트리 발행 및 BLE 스캔 결과 메모리 청소 (RAM Out-Of-Memory 누수 방지)
  if (now - lastMqttMs >= 10000) {
    lastMqttMs = now;
    const char* stateStr = (state == GateState::IDLE) ? "IDLE" :
                           (state == GateState::VERIFYING) ? "VERIFYING" :
                           (state == GateState::RELAY_HOLD) ? "RELAY_HOLD" : "COOLDOWN";
    MqttManager::publishTelemetry(validReading ? mm : 0, stateStr);

    // BLE 스캔 결과 맵/벡터 메모리 주기적 초기화 (Failed to allocate / reallocate 누수 방지)
    BLEScan* pScan = BLEDevice::getScan();
    if (pScan) {
      pScan->clearResults();
    }
  }

  uint32_t bleAge = (last_ble_detected_time > 0) ? (now - last_ble_detected_time) : 999999;
  bool isBleValid = (last_ble_detected_time > 0) && (bleAge < BLE_VALID_MS);

  switch (state) {

    case GateState::IDLE:
      // 1. BLE 인증 신호가 10초 이내에 수신된 유효 사용자 상태인가?
      if (isBleValid && validReading && mm <= DISTANCE_THRESHOLD_MM) {
        LOGF("[GATE] 📱 BLE 인증 신호 수신 상태에서 ToF %u mm 감지! (BLE 경과: %lu ms)", mm, (unsigned long)bleAge);
        LOGF("[GATE] ✅ BLE + ToF 이중 검증 성공! NAS 자격 검증 요청...");
        
        state = GateState::VERIFYING;
        stateMs = now;
        MqttManager::publishEvent("gate_trigger", "BLE + ToF Validation Passed");

        bool authorized = requestNASVerification(mm);

        if (authorized) {
          LOGF("[GATE] *** 출입 승인! 릴레이 %lu ms ON *** (딸깍!)", (unsigned long)RELAY_HOLD_MS);
          relayOn();
          MqttManager::publishEvent("door_open", "Access Granted");
          state = GateState::RELAY_HOLD;
          stateMs = millis();
        } else {
          LOGF("[GATE] *** 출입 거부 (NAS 미승인) ***. 쿨다운 진입.");
          MqttManager::publishEvent("door_deny", "Access Denied");
          state = GateState::COOLDOWN;
          stateMs = millis();
        }
      } else if (!isBleValid && validReading && mm <= DISTANCE_THRESHOLD_MM) {
        // BLE 없이 ToF 센서만 감지된 경우 (외부인 진입)
        static uint32_t lastWarnMs = 0;
        if (now - lastWarnMs >= 3000) {
          lastWarnMs = now;
          LOGF("[GATE-WARN] ❌ ToF %u mm 감지되었으나, 유효한 BLE 스마트폰 신호가 없음 (외부인/미인증)", mm);
          MqttManager::publishEvent("ble_missing", "BLE Signal Missing");
        }
      }
      break;

    case GateState::VERIFYING:
      break;

    case GateState::RELAY_HOLD:
      if (millis() - stateMs >= RELAY_HOLD_MS) {
        relayOff();
        LOGF("[GATE] 릴레이 OFF (%lu ms 경과). 문 주변 상주 여부 감시 쿨다운 시작.", (unsigned long)RELAY_HOLD_MS);
        MqttManager::publishEvent("door_close", "Relay Timeout OFF");
        state = GateState::COOLDOWN;
        stateMs = millis();
      }
      break;

    case GateState::COOLDOWN:
      // 쿨다운 스마트 리셋: 인증된 BLE 신호가 계속 잡히거나 ToF 50cm 이내에 사람이 계속 머무르면 쿨다운 타임 리셋!
      if (isBleValid || (validReading && mm <= DISTANCE_THRESHOLD_MM)) {
        stateMs = now; // 문 주변에 상주하는 동안 쿨다운 타이머를 지속 리셋 (재오픈 차단)
      } else if (millis() - stateMs >= 3000) { // 문 주변(BLE 및 ToF)을 완전히 벗어나고 3초 경과 시 복귀
        LOGF("[GATE] 🚪 문 주변 이탈 확인 -> IDLE 대기 상태 복귀 (다음 출입 승인 준비 완료)");
        state = GateState::IDLE;
      }
      break;
  }

  delay(TOF_POLL_INTERVAL_MS);
}
