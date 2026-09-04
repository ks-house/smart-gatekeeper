// src/DiagnosticsManager.cpp
// =============================================================
// smart-gatekeeper — 원격 reset/boot 진단 정보 수집
// =============================================================
#include "DiagnosticsManager.h"

#include <esp_attr.h>
#include <esp_core_dump.h>
#include <esp_err.h>
#include <esp_system.h>
#include <esp_task_wdt.h>

#include "ConfigManager.h"
#include "EvidencePersistenceFailureLatch.h"
#include "config.h"

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
  uint8_t evidencePersistenceFailed;
  char state[16];
  char action[32];
};

RTC_NOINIT_ATTR RtcBreadcrumb rtcBreadcrumb;

RtcBreadcrumb previousBreadcrumb = {};
bool previousBreadcrumbIsValid = false;
sgk::EvidencePersistenceFailureLatch evidencePersistenceFailureLatch;

char targetIdValue[16] = "unknown";
char bootIdValue[33] = "unknown";
uint32_t bootCountValue = 0;
esp_reset_reason_t resetReasonValue = ESP_RST_UNKNOWN;
char plannedRestartValue[32] = "";
uint32_t mqttConnectCountValue = 0;
bool loopWatchdogEnabledValue = false;

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

  previousBreadcrumbIsValid = isBreadcrumbValid(rtcBreadcrumb);
  if (previousBreadcrumbIsValid) {
    previousBreadcrumb = rtcBreadcrumb;
  }
  evidencePersistenceFailureLatch.begin(
      previousBreadcrumbIsValid &&
      previousBreadcrumb.evidencePersistenceFailed != 0);

  uint64_t mac = ESP.getEfuseMac();
  snprintf(targetIdValue, sizeof(targetIdValue), "%012llx",
           static_cast<unsigned long long>(mac & 0xFFFFFFFFFFFFULL));
  bootCountValue = ConfigManager::incrementBootCount();
  snprintf(bootIdValue, sizeof(bootIdValue), "%08lx%08lx%08lx%08lx",
           static_cast<unsigned long>(esp_random()),
           static_cast<unsigned long>(esp_random()),
           static_cast<unsigned long>(esp_random()),
           static_cast<unsigned long>(esp_random()));
  String planned = ConfigManager::consumePlannedRestartReason();
  strlcpy(plannedRestartValue, planned.c_str(),
          sizeof(plannedRestartValue));

  memset(&rtcBreadcrumb, 0, sizeof(rtcBreadcrumb));
  rtcBreadcrumb.relayPinLevel = -1;
  rtcBreadcrumb.evidencePersistenceFailed =
      evidencePersistenceFailureLatch.active() ? 1 : 0;
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
      previousBreadcrumbIsValid ? "true" : "false", coreDumpStatusValue,
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

void DiagnosticsManager::markEvidencePersistenceFailure() {
  // This field is deliberately independent of action. markPlannedRestart()
  // updates the action string immediately afterward, but must not erase the
  // evidence-loss diagnostic consumed on the next boot.
  evidencePersistenceFailureLatch.mark();
  rtcBreadcrumb.evidencePersistenceFailed =
      evidencePersistenceFailureLatch.active() ? 1 : 0;
  rtcBreadcrumb.uptimeMs = millis();
  commitBreadcrumb();
}

void DiagnosticsManager::acknowledgePreviousEvidencePersistenceFailure() {
  if (!evidencePersistenceFailureLatch.carriedFailurePending()) return;
  evidencePersistenceFailureLatch.acknowledgeCarriedFailure();
  rtcBreadcrumb.evidencePersistenceFailed =
      evidencePersistenceFailureLatch.active() ? 1 : 0;
  rtcBreadcrumb.uptimeMs = millis();
  commitBreadcrumb();
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

bool DiagnosticsManager::enableLoopWatchdog() {
  esp_task_wdt_config_t watchdogConfig{};
  watchdogConfig.timeout_ms = LOOP_TASK_WATCHDOG_TIMEOUT_MS;
  watchdogConfig.idle_core_mask = 0;
#if defined(CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU0) && \
    CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU0
  watchdogConfig.idle_core_mask |= 1U << 0;
#endif
#if defined(CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU1) && \
    CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU1
  watchdogConfig.idle_core_mask |= 1U << 1;
#endif
  watchdogConfig.trigger_panic = true;

  esp_err_t result = esp_task_wdt_reconfigure(&watchdogConfig);
  if (result == ESP_ERR_INVALID_STATE) {
    result = esp_task_wdt_init(&watchdogConfig);
  }
  if (result != ESP_OK) {
    loopWatchdogEnabledValue = false;
    noteAction("loop_watchdog_config_failed");
    Serial.printf("[DIAG-ERROR] loop watchdog configure failed: %s\n",
                  esp_err_to_name(result));
    return false;
  }

  // Arduino keeps its own loopTaskWDTEnabled flag and feeds at the top of
  // every completed loop iteration. Use that supported adapter only after the
  // SDK timeout has been widened from its unsafe five-second default.
  enableLoopWDT();
  loopWatchdogEnabledValue = esp_task_wdt_status(nullptr) == ESP_OK;
  noteAction(loopWatchdogEnabledValue ? "loop_watchdog_ready"
                                     : "loop_watchdog_subscribe_failed");
  Serial.printf("[DIAG] loop watchdog %s (timeout=%lu ms panic=true)\n",
                loopWatchdogEnabledValue ? "enabled" : "unavailable",
                static_cast<unsigned long>(LOOP_TASK_WATCHDOG_TIMEOUT_MS));
  return loopWatchdogEnabledValue;
}

void DiagnosticsManager::feedLoopWatchdog() {
  if (loopWatchdogEnabledValue) {
    feedLoopWDT();
  }
}

bool DiagnosticsManager::loopWatchdogEnabled() {
  return loopWatchdogEnabledValue;
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
  return previousBreadcrumbIsValid;
}

uint32_t DiagnosticsManager::previousUptimeMs() {
  return previousBreadcrumbIsValid ? previousBreadcrumb.uptimeMs : 0;
}

const char* DiagnosticsManager::previousState() {
  return previousBreadcrumbIsValid ? previousBreadcrumb.state : "unknown";
}

const char* DiagnosticsManager::previousAction() {
  return previousBreadcrumbIsValid ? previousBreadcrumb.action : "unknown";
}

bool DiagnosticsManager::previousArmed() {
  return previousBreadcrumbIsValid && previousBreadcrumb.isArmed != 0;
}

bool DiagnosticsManager::previousRelayCommandedOn() {
  return previousBreadcrumbIsValid &&
         previousBreadcrumb.relayCommandedOn != 0;
}

int DiagnosticsManager::previousRelayPinLevel() {
  return previousBreadcrumbIsValid ? previousBreadcrumb.relayPinLevel : -1;
}

bool DiagnosticsManager::previousEvidencePersistenceFailed() {
  return previousBreadcrumbIsValid &&
         previousBreadcrumb.evidencePersistenceFailed != 0;
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
