// src/DiagnosticsManager.cpp
// =============================================================
// smart-gatekeeper — 원격 reset/boot 진단 정보 수집
// =============================================================
#include "DiagnosticsManager.h"

#include <esp_attr.h>
#include <esp_core_dump.h>
#include <esp_err.h>
#include <esp_system.h>

#include "ConfigManager.h"

namespace {

constexpr uint32_t kBreadcrumbMagic = 0x474B4458;  // "GKDX"
constexpr uint16_t kBreadcrumbVersion = 1;

struct RtcBreadcrumb {
  uint32_t magic;
  uint16_t version;
  uint16_t reserved;
  uint32_t checksum;
  uint32_t uptimeMs;
  uint8_t isArmed;
  uint8_t relayCommandedOn;
  int8_t relayPinLevel;
  uint8_t reserved2;
  char state[16];
  char action[32];
};

RTC_NOINIT_ATTR RtcBreadcrumb rtcBreadcrumb;

RtcBreadcrumb previousBreadcrumb = {};
bool previousBreadcrumbValid = false;

char targetIdValue[16] = "unknown";
char bootIdValue[20] = "unknown";
uint32_t bootCountValue = 0;
esp_reset_reason_t resetReasonValue = ESP_RST_UNKNOWN;
char plannedRestartValue[32] = "";
uint32_t mqttConnectCountValue = 0;

bool coreDumpValidValue = false;
char coreDumpStatusValue[32] = "not_checked";
size_t coreDumpSizeValue = 0;
char coreDumpPanicReasonValue[160] = "";
char coreDumpTaskValue[17] = "";
uint32_t coreDumpPcValue = 0;
uint32_t coreDumpMcauseValue = 0;
uint32_t coreDumpMtvalValue = 0;
char coreDumpElfSha256Value[65] = "";

uint32_t breadcrumbChecksum(const RtcBreadcrumb& value) {
  RtcBreadcrumb copy = value;
  copy.checksum = 0;

  const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&copy);
  uint32_t hash = 2166136261UL;
  for (size_t i = 0; i < sizeof(copy); ++i) {
    hash ^= bytes[i];
    hash *= 16777619UL;
  }
  return hash;
}

bool isBreadcrumbValid(const RtcBreadcrumb& value) {
  return value.magic == kBreadcrumbMagic &&
         value.version == kBreadcrumbVersion &&
         value.checksum == breadcrumbChecksum(value);
}

void commitBreadcrumb() {
  rtcBreadcrumb.magic = kBreadcrumbMagic;
  rtcBreadcrumb.version = kBreadcrumbVersion;
  rtcBreadcrumb.checksum = breadcrumbChecksum(rtcBreadcrumb);
}

const char* resetReasonName(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_POWERON:
      return "POWERON";
    case ESP_RST_EXT:
      return "EXTERNAL_PIN";
    case ESP_RST_SW:
      return "SOFTWARE";
    case ESP_RST_PANIC:
      return "PANIC";
    case ESP_RST_INT_WDT:
      return "INT_WDT";
    case ESP_RST_TASK_WDT:
      return "TASK_WDT";
    case ESP_RST_WDT:
      return "OTHER_WDT";
    case ESP_RST_DEEPSLEEP:
      return "DEEPSLEEP";
    case ESP_RST_BROWNOUT:
      return "BROWNOUT";
    case ESP_RST_SDIO:
      return "SDIO";
    case ESP_RST_USB:
      return "USB";
    case ESP_RST_JTAG:
      return "JTAG";
    case ESP_RST_EFUSE:
      return "EFUSE";
    case ESP_RST_PWR_GLITCH:
      return "POWER_GLITCH";
    case ESP_RST_CPU_LOCKUP:
      return "CPU_LOCKUP";
    case ESP_RST_UNKNOWN:
    default:
      return "UNKNOWN";
  }
}

void inspectCoreDump() {
  esp_err_t result = esp_core_dump_image_check();
  strlcpy(coreDumpStatusValue, esp_err_to_name(result),
          sizeof(coreDumpStatusValue));
  coreDumpValidValue = result == ESP_OK;
  if (!coreDumpValidValue) {
    return;
  }

  size_t address = 0;
  esp_core_dump_image_get(&address, &coreDumpSizeValue);

  char panicReason[sizeof(coreDumpPanicReasonValue)] = {};
  if (esp_core_dump_get_panic_reason(panicReason, sizeof(panicReason)) ==
      ESP_OK) {
    strlcpy(coreDumpPanicReasonValue, panicReason,
            sizeof(coreDumpPanicReasonValue));
  }

  esp_core_dump_summary_t summary = {};
  if (esp_core_dump_get_summary(&summary) != ESP_OK) {
    return;
  }

  strlcpy(coreDumpTaskValue, summary.exc_task, sizeof(coreDumpTaskValue));
  coreDumpPcValue = summary.exc_pc;
  coreDumpMcauseValue = summary.ex_info.mcause;
  coreDumpMtvalValue = summary.ex_info.mtval;
  snprintf(coreDumpElfSha256Value, sizeof(coreDumpElfSha256Value), "%.*s",
           static_cast<int>(sizeof(summary.app_elf_sha256)),
           reinterpret_cast<const char*>(summary.app_elf_sha256));
}

}  // namespace

void DiagnosticsManager::begin() {
  resetReasonValue = esp_reset_reason();

  previousBreadcrumbValid = isBreadcrumbValid(rtcBreadcrumb);
  if (previousBreadcrumbValid) {
    previousBreadcrumb = rtcBreadcrumb;
  }

  uint64_t mac = ESP.getEfuseMac();
  snprintf(targetIdValue, sizeof(targetIdValue), "%012llx",
           static_cast<unsigned long long>(mac & 0xFFFFFFFFFFFFULL));
  snprintf(bootIdValue, sizeof(bootIdValue), "%08lx%08lx",
           static_cast<unsigned long>(esp_random()),
           static_cast<unsigned long>(mac & 0xFFFFFFFFUL));

  bootCountValue = ConfigManager::incrementBootCount();
  String planned = ConfigManager::consumePlannedRestartReason();
  strlcpy(plannedRestartValue, planned.c_str(),
          sizeof(plannedRestartValue));

  memset(&rtcBreadcrumb, 0, sizeof(rtcBreadcrumb));
  rtcBreadcrumb.relayPinLevel = -1;
  strlcpy(rtcBreadcrumb.state, "BOOTING", sizeof(rtcBreadcrumb.state));
  strlcpy(rtcBreadcrumb.action, "boot", sizeof(rtcBreadcrumb.action));
  commitBreadcrumb();

  inspectCoreDump();

  Serial.printf(
      "[DIAG] boot_id=%s target_id=%s boot_count=%lu reset=%s(%d) "
      "planned=%s previous_valid=%s coredump=%s size=%u\n",
      bootIdValue, targetIdValue, static_cast<unsigned long>(bootCountValue),
      resetReason(), resetReasonCode(),
      plannedRestartValue[0] ? plannedRestartValue : "none",
      previousBreadcrumbValid ? "true" : "false", coreDumpStatusValue,
      static_cast<unsigned int>(coreDumpSizeValue));
}

void DiagnosticsManager::heartbeat(const char* state,
                                   bool isArmed,
                                   bool relayCommandedOn,
                                   int relayPinLevel) {
  rtcBreadcrumb.uptimeMs = millis();
  rtcBreadcrumb.isArmed = isArmed ? 1 : 0;
  rtcBreadcrumb.relayCommandedOn = relayCommandedOn ? 1 : 0;
  rtcBreadcrumb.relayPinLevel = static_cast<int8_t>(relayPinLevel);
  strlcpy(rtcBreadcrumb.state, state ? state : "UNKNOWN",
          sizeof(rtcBreadcrumb.state));
  commitBreadcrumb();
}

void DiagnosticsManager::noteAction(const char* action) {
  strlcpy(rtcBreadcrumb.action, action ? action : "unknown",
          sizeof(rtcBreadcrumb.action));
  rtcBreadcrumb.uptimeMs = millis();
  commitBreadcrumb();
}

void DiagnosticsManager::noteRelayState(bool relayCommandedOn,
                                        int relayPinLevel,
                                        const char* action) {
  rtcBreadcrumb.relayCommandedOn = relayCommandedOn ? 1 : 0;
  rtcBreadcrumb.relayPinLevel = static_cast<int8_t>(relayPinLevel);
  noteAction(action);
}

void DiagnosticsManager::markPlannedRestart(const char* reason) {
  const char* value = reason ? reason : "unspecified";
  ConfigManager::setPlannedRestartReason(value);

  char action[sizeof(rtcBreadcrumb.action)] = {};
  snprintf(action, sizeof(action), "restart:%s", value);
  noteAction(action);
}

void DiagnosticsManager::noteMqttConnected() {
  mqttConnectCountValue++;
  noteAction("mqtt_connected");
}

const char* DiagnosticsManager::targetId() {
  return targetIdValue;
}

const char* DiagnosticsManager::bootId() {
  return bootIdValue;
}

uint32_t DiagnosticsManager::bootCount() {
  return bootCountValue;
}

int DiagnosticsManager::resetReasonCode() {
  return static_cast<int>(resetReasonValue);
}

const char* DiagnosticsManager::resetReason() {
  return resetReasonName(resetReasonValue);
}

const char* DiagnosticsManager::plannedRestartReason() {
  return plannedRestartValue[0] ? plannedRestartValue : "none";
}

bool DiagnosticsManager::previousBreadcrumbValid() {
  return previousBreadcrumbValid;
}

uint32_t DiagnosticsManager::previousUptimeMs() {
  return previousBreadcrumbValid ? previousBreadcrumb.uptimeMs : 0;
}

const char* DiagnosticsManager::previousState() {
  return previousBreadcrumbValid ? previousBreadcrumb.state : "unknown";
}

const char* DiagnosticsManager::previousAction() {
  return previousBreadcrumbValid ? previousBreadcrumb.action : "unknown";
}

bool DiagnosticsManager::previousArmed() {
  return previousBreadcrumbValid && previousBreadcrumb.isArmed != 0;
}

bool DiagnosticsManager::previousRelayCommandedOn() {
  return previousBreadcrumbValid &&
         previousBreadcrumb.relayCommandedOn != 0;
}

int DiagnosticsManager::previousRelayPinLevel() {
  return previousBreadcrumbValid ? previousBreadcrumb.relayPinLevel : -1;
}

uint32_t DiagnosticsManager::mqttConnectCount() {
  return mqttConnectCountValue;
}

bool DiagnosticsManager::coreDumpValid() {
  return coreDumpValidValue;
}

const char* DiagnosticsManager::coreDumpStatus() {
  return coreDumpStatusValue;
}

size_t DiagnosticsManager::coreDumpSize() {
  return coreDumpSizeValue;
}

const char* DiagnosticsManager::coreDumpPanicReason() {
  return coreDumpPanicReasonValue[0] ? coreDumpPanicReasonValue : "none";
}

const char* DiagnosticsManager::coreDumpTask() {
  return coreDumpTaskValue[0] ? coreDumpTaskValue : "unknown";
}

uint32_t DiagnosticsManager::coreDumpPc() {
  return coreDumpPcValue;
}

uint32_t DiagnosticsManager::coreDumpMcause() {
  return coreDumpMcauseValue;
}

uint32_t DiagnosticsManager::coreDumpMtval() {
  return coreDumpMtvalValue;
}

const char* DiagnosticsManager::coreDumpElfSha256() {
  return coreDumpElfSha256Value[0] ? coreDumpElfSha256Value : "unknown";
}
