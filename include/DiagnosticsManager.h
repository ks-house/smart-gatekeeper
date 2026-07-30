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
  static void markPlannedRestart(const char* reason);
  static void noteMqttConnected();

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
