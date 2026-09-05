// include/DiagnosticsManager.h
// =============================================================
// smart-gatekeeper — 원격 reset/boot 진단 정보 수집
// =============================================================
#pragma once

#include <Arduino.h>

class DiagnosticsManager {
 public:
  static void begin();
  static void heartbeat(const char* state,
                        bool isArmed,
                        bool relayCommandedOn,
                        int relayPinLevel);
  static void noteAction(const char* action);
  static void noteRelayState(bool relayCommandedOn,
                             int relayPinLevel,
                             const char* action);
  // Separate access breadcrumb so Wi-Fi/MQTT actions cannot overwrite the
  // last local authentication stage before an unexpected reset.
  static void noteAccessStage(const char* stage, const char* sessionId);
  // Preserve a restart-surviving, non-overwritable signal when exact access
  // evidence could not be copied to NVS/RTC before a fail-closed restart.
  static void markEvidencePersistenceFailure();
  // Clear only a failure carried from the previous boot, and only after its
  // boot diagnostics were accepted by the MQTT transport. A failure raised in
  // this boot remains latched for the next reset.
  static void acknowledgePreviousEvidencePersistenceFailure();
  static void markPlannedRestart(const char* reason);
  static void noteMqttConnected();
  static bool enableLoopWatchdog();
  static void feedLoopWatchdog();
  static bool loopWatchdogEnabled();

  static const char* targetId();
  static const char* bootId();
  static uint32_t bootCount();
  static int resetReasonCode();
  static const char* resetReason();
  static const char* plannedRestartReason();

  static bool previousBreadcrumbValid();
  static uint32_t previousUptimeMs();
  static const char* previousState();
  static const char* previousAction();
  static bool previousArmed();
  static bool previousRelayCommandedOn();
  static int previousRelayPinLevel();
  static bool previousEvidencePersistenceFailed();
  static bool previousAccessBreadcrumbValid();
  static uint32_t previousAccessUptimeMs();
  static const char* previousAccessStage();
  static const char* previousAccessSessionId();

  static uint32_t mqttConnectCount();

  static bool coreDumpValid();
  static const char* coreDumpStatus();
  static size_t coreDumpSize();
  static const char* coreDumpPanicReason();
  static const char* coreDumpTask();
  static uint32_t coreDumpPc();
  static uint32_t coreDumpMcause();
  static uint32_t coreDumpMtval();
  static const char* coreDumpElfSha256();

 private:
  DiagnosticsManager() = delete;
};
