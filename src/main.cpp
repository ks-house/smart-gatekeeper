// src/main.cpp
// =============================================================
// smart-gatekeeper — OTA 및 MQTT 연동 통합 펌웨어
// (ToF 50cm 감지 + Captive Portal WiFi + 시놀로지 NAS HTTPS POST + MQTT 텔레메트리 + OTA)
// =============================================================
#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

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
  IDLE,         // 대기 중 (50cm 진입 감시)
  VERIFYING,    // NAS HTTPS API 요청 및 인증 대기 중
  RELAY_HOLD,   // 인증 승인 -> 릴레이 1초 ON 유지 중
  COOLDOWN      // 연속 요청 방지 쿨다운 중 (2초)
};

static VL53L0X sensor;
static GateState state       = GateState::IDLE;
static uint32_t  stateMs     = 0;
static uint32_t  lastMqttMs  = 0;

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
  LOGF(" smart-gatekeeper v%s — OTA & MQTT 통합 펌웨어", FIRMWARE_VERSION);
  LOGF("============================================");

  // 5. WifiManager 초기화 및 NVS Wi-Fi 접속 시도
  WifiManager::init();
  if (WifiManager::connectSTA(10000)) {
    // Wi-Fi 연결 성공 시 NTP 시간 동기화 (TLS 안정성 보장)
    configTime(9 * 3600, 0, "pool.ntp.org", "time.nist.gov");
    LOGF("[TIME] NTP 시간 동기화 요청 (KST UTC+9)");

    // 6. MQTT 및 OTA 관리자 초기화
    MqttManager::init();
    OtaManager::init();

    // 부팅 시 시놀로지 NAS version.json 기반 자동 OTA 체크
    LOGF("[OTA] 부팅 시 펌웨어 업데이트 확인 시작...");
    OtaManager::checkAndUpdate(false);
  } else {
    LOGF("[WIFI] 접속 실패 -> AP 설정 모드로 전환합니다.");
    WifiManager::startAP();
  }

  // 7. VL53L0X 센서 초기화
  sensor.setTimeout(500);
  LOGF("[INFO] ToF 센서 초기화 중...");
  if (!sensor.init()) {
    LOGF("[WARN] VL53L0X init 실패 (센서 연결 상태 점검 필요)");
  } else {
    sensor.startContinuous(TOF_POLL_INTERVAL_MS);
    LOGF("[INFO] ToF 센서 초기화 성공!");
  }
  LOGF("--------------------------------------------");
}

// ─────────────────────────────────────────────────────────────
// loop()
// ─────────────────────────────────────────────────────────────
void loop() {
  uint32_t now = millis();

  // AP 모드일 때 웹 서버 및 Captive Portal 요청 처리
  if (WifiManager::isAPMode()) {
    WifiManager::handleClient();
    delay(10);
    return;
  }

  // MQTT 루프 처리
  MqttManager::update();

  // ToF 거리 측정
  uint16_t mm = sensor.readRangeContinuousMillimeters();
  bool validReading = !(sensor.timeoutOccurred() || mm == 65535);

  // 10초 주기 MQTT 텔레메트리 발행
  if (now - lastMqttMs >= 10000) {
    lastMqttMs = now;
    const char* stateStr = (state == GateState::IDLE) ? "IDLE" :
                           (state == GateState::VERIFYING) ? "VERIFYING" :
                           (state == GateState::RELAY_HOLD) ? "RELAY_HOLD" : "COOLDOWN";
    MqttManager::publishTelemetry(validReading ? mm : 0, stateStr);
  }

  switch (state) {

    case GateState::IDLE:
      if (validReading) {
        LOGF("[ToF] %4u mm  |  State: IDLE", mm);
      }

      // 감지 임계값 (50cm) 이내 진입 시 NAS 자격 검증 트리거
      if (validReading && mm <= DISTANCE_THRESHOLD_MM) {
        LOGF("[GATE] *** %u mm 감지! NAS 자격 검증 요청 시작 ***", mm);
        state = GateState::VERIFYING;
        stateMs = now;

        MqttManager::publishEvent("gate_trigger", "ToF Threshold Detected");

        bool authorized = requestNASVerification(mm);

        if (authorized) {
          LOGF("[GATE] *** 출입 승인! 릴레이 %lu ms ON *** (딸깍!)",
               (unsigned long)RELAY_HOLD_MS);
          relayOn();
          MqttManager::publishEvent("door_open", "Access Granted");
          state = GateState::RELAY_HOLD;
          stateMs = millis();
        } else {
          LOGF("[GATE] *** 출입 거부! 릴레이 미작동 ***. 쿨다운 진입.");
          MqttManager::publishEvent("door_deny", "Access Denied");
          state = GateState::COOLDOWN;
          stateMs = millis();
        }
      }
      break;

    case GateState::VERIFYING:
      break;

    case GateState::RELAY_HOLD:
      if (now - stateMs >= RELAY_HOLD_MS) {
        relayOff();
        LOGF("[GATE] 릴레이 OFF (%lu ms 경과). 쿨다운 시작.", (unsigned long)RELAY_HOLD_MS);
        MqttManager::publishEvent("door_close", "Relay Timeout OFF");
        state = GateState::COOLDOWN;
        stateMs = now;
      }
      break;

    case GateState::COOLDOWN:
      if (now - stateMs >= RELAY_COOLDOWN_MS) {
        LOGF("[GATE] 쿨다운 완료 -> IDLE 대기 상태 복귀.");
        state = GateState::IDLE;
      }
      break;
  }

  delay(TOF_POLL_INTERVAL_MS);
}
