import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConnectivityRecoveryContractTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.wifi = (ROOT / "src" / "WifiManager.cpp").read_text(encoding="utf-8")
    cls.policy = (ROOT / "include" / "RecoveryRadioPolicy.h").read_text(
        encoding="utf-8"
    )
    cls.mqtt = (ROOT / "src" / "MqttManager.cpp").read_text(encoding="utf-8")
    cls.main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
    cls.ota = (ROOT / "src" / "OtaManager.cpp").read_text(encoding="utf-8")

  def test_provisioning_ap_uses_bounded_radio_policy(self):
    self.assertIn("WiFi.mode(WIFI_AP_STA)", self.wifi)
    self.assertIn("kRecoveryApQuietMs = 30000", self.wifi)
    self.assertIn("kRecoveryStationAttemptMs = 10000", self.wifi)
    self.assertIn("recoveryRadioPolicy.begin(millis());", self.wifi)
    self.assertIn("RecoveryRadioAction::kStartStationAttempt", self.wifi)
    self.assertIn("RecoveryRadioAction::kStopStationAttempt", self.wifi)
    self.assertNotIn("kStationRetryIntervalMs", self.wifi)
    self.assertNotIn("startNonBlockingStationAttempt", self.wifi)
    self.assertEqual(self.wifi.count("WiFi.begin(ssid.c_str(), pass.c_str());"), 1)
    self.assertIn("[WIFI-DIAG] station disconnect reason=%u", self.wifi)
    self.assertIn('noteAction("wifi_recovered_from_ap")', self.wifi)

  def test_idle_ap_client_hold_is_bounded_without_interrupting_active_work(self):
    self.assertIn(
        "kRecoveryApClientHoldMs = kOperatorRecoveryWindowMs", self.wifi
    )
    self.assertIn("RecoveryRadioAction::kReleaseStaleApClients", self.wifi)
    self.assertIn(
        "RecoveryRadioAction::\n"
        "                              kReleaseStaleClientsAndStartStationAttempt",
        self.wifi,
    )
    self.assertIn("esp_wifi_deauth_sta(0)", self.wifi)
    self.assertIn(
        "ap_client_connected && !local_operation_active &&\n"
        "        !authenticated_hold_active",
        self.policy,
    )
    self.assertIn("client_release_interval_ms_", self.policy)
    combined = self.wifi.split(
        "kReleaseStaleClientsAndStartStationAttempt", 1
    )[1]
    self.assertLess(
        combined.index("esp_wifi_deauth_sta(0)"),
        combined.index("startBoundedRecoveryStationAttempt(nowMs);"),
    )

  def test_web_server_is_serviced_once_before_radio_transition(self):
    handle = self.wifi.split("void WifiManager::handleClient()", 1)[1]
    handle = handle.split("bool WifiManager::isConnected()", 1)[0]
    self.assertEqual(self.wifi.count("webServer.handleClient();"), 1)
    self.assertEqual(handle.count("webServer.handleClient();"), 1)
    self.assertLess(
        handle.index("webServer.handleClient();"),
        handle.index("recoveryRadioPolicy.update("),
    )

  def test_ap_exit_paths_restore_continuous_station_mode(self):
    helper = self.wifi.split("void restoreContinuousStationMode()", 1)[1]
    helper = helper.split("}  // namespace", 1)[0]
    self.assertIn("WiFi.mode(WIFI_STA);", helper)
    self.assertIn("WiFi.setAutoReconnect(true);", helper)

    start = self.wifi.split("bool WifiManager::startRecoveryAP", 1)[1]
    start = start.split("void WifiManager::handleRoot()", 1)[0]
    self.assertIn("restoreContinuousStationMode();", start)

    handle = self.wifi.split("void WifiManager::handleClient()", 1)[1]
    handle = handle.split("bool WifiManager::isConnected()", 1)[0]
    self.assertEqual(handle.count("restoreContinuousStationMode();"), 2)
    deadline = handle.split("RecoveryDeadlineReached(nowMs", 1)[1]
    deadline = deadline.split("if (apModeActive && recoveryApDeadlineMs == 0", 1)[0]
    self.assertLess(
        deadline.index("stationWasConnected"),
        deadline.index("WiFi.softAPdisconnect(true);"),
    )

  def test_timed_operator_window_cannot_collide_with_zero_sentinel(self):
    self.assertIn("MakeRecoveryDeadline(millis(), durationMs)", self.wifi)
    self.assertIn(
        "RecoveryDeadlineReached(nowMs, recoveryApDeadlineMs)", self.wifi
    )
    self.assertIn("return deadline_ms == 0 ? 1 : deadline_ms;", self.policy)

  def test_operator_deadline_defers_only_for_active_local_operation(self):
    handle = self.wifi.split("void WifiManager::handleClient()", 1)[1]
    handle = handle.split("bool WifiManager::isConnected()", 1)[0]
    reached = handle.index("const bool operatorDeadlineReached")
    lease = handle.index(
        "operatorDeadlineReached && isRecoveryOperationActive(nowMs)"
    )
    extend = handle.index(
        "nowMs, kRecoveryOperationLeaseMs", lease
    )
    close = handle.index("WiFi.softAPdisconnect(true);", extend)
    self.assertLess(reached, lease)
    self.assertLess(lease, extend)
    self.assertLess(extend, close)
    deferred = handle[lease:close]
    self.assertIn(
        "recovery_ap_deadline_deferred_for_local_operation", deferred
    )
    self.assertIn("return;", deferred)

  def test_sta_compatibility_profile_precedes_the_only_begin(self):
    connect = self.wifi.split("bool WifiManager::connectSTA", 1)[1]
    connect = connect.split("void WifiManager::startAP", 1)[0]
    station_mode = connect.index("WiFi.mode(WIFI_STA);")
    profile = connect.index("configureStationCompatibilityProfile();")
    auto_reconnect = connect.index("WiFi.setAutoReconnect(true);")
    begin = connect.index("WiFi.begin(ssid.c_str(), pass.c_str());")
    self.assertLess(station_mode, profile)
    self.assertLess(profile, auto_reconnect)
    self.assertLess(auto_reconnect, begin)
    self.assertEqual(self.wifi.count("WiFi.begin(ssid.c_str(), pass.c_str());"), 1)

  def test_sta_profile_preserves_dynamic_ap_and_recovery_interfaces(self):
    profile = self.wifi.split(
        "void configureStationCompatibilityProfile()", 1
    )[1]
    profile = profile.split("bool stationCredentialsProvisioned()", 1)[0]
    self.assertIn("WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);", profile)
    self.assertIn(
        "WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);", profile
    )
    self.assertIn("WiFi.setSleep(WIFI_PS_NONE);", profile)
    self.assertIn("esp_wifi_set_protocol(WIFI_IF_STA", profile)
    self.assertNotIn("WIFI_IF_AP", profile)
    self.assertNotIn("BSSID", connect := self.wifi.split(
        "bool WifiManager::connectSTA", 1
    )[1].split("void WifiManager::startAP", 1)[0])
    self.assertNotIn("WiFi.begin(ssid.c_str(), pass.c_str(),", connect)
    self.assertIn('noteAction("wifi_sta_profile_degraded")', profile)

  def test_disconnect_diagnostics_include_reason_name(self):
    self.assertIn("WiFi.disconnectReasonName(reason)", self.wifi)
    self.assertIn(
        "[WIFI-DIAG] station disconnect reason=%u (%s)", self.wifi
    )

  def test_recovery_ap_identity_is_single_sourced(self):
    self.assertIn(
        'constexpr char kRecoveryApSsid[] = "SmartGatekeeper-Recovery";',
        self.wifi,
    )
    self.assertEqual(self.wifi.count('"SmartGatekeeper-Recovery"'), 1)
    self.assertNotIn("SmartGatekeeper-Setup", self.wifi)
    self.assertIn("WiFi.softAP(kRecoveryApSsid,", self.wifi)
    self.assertIn("설정 AP 가동 완료: '%s'", self.wifi)
    self.assertIn(
        "webServer.requestAuthentication(BASIC_AUTH, kRecoveryApSsid);",
        self.wifi,
    )

  def test_wifi_credentials_are_not_erased_on_connection_failure(self):
    self.assertNotIn("WiFi.disconnect(true, true)", self.wifi)
    self.assertIn("WiFi.disconnect(false, false)", self.wifi)

  def test_recovery_scan_pauses_disconnected_sta_and_retries_once(self):
    scan = self.wifi.split("void WifiManager::handleScan()", 1)[1]
    scan = scan.split("void WifiManager::handleSave()", 1)[0]
    pause = scan.index("WiFi.setAutoReconnect(false);")
    disconnect = scan.index("WiFi.disconnect(false, false);")
    first_scan = scan.index("WiFi.scanNetworks(false, false, false, 150)")
    retry_scan = scan.index("WiFi.scanNetworks(false, false, false, 250)")
    self.assertLess(pause, disconnect)
    self.assertLess(disconnect, first_scan)
    self.assertLess(first_scan, retry_scan)
    self.assertEqual(scan.count("WiFi.scanNetworks("), 2)
    self.assertNotIn("WiFi.setAutoReconnect(true);", scan)
    self.assertNotIn("WiFi.reconnect();", scan)
    self.assertIn("recoveryRadioPolicy.pauseForLocalWork(millis());", scan)
    self.assertIn("beginRecoveryOperation();", scan)
    self.assertIn("endRecoveryOperation();", scan)
    self.assertIn('noteAction("wifi_scan_sta_paused")', scan)
    self.assertIn('noteAction("wifi_scan_complete")', scan)
    self.assertIn('webServer.send(503, "application/json"', scan)

  def test_recovery_ui_keeps_scan_and_manual_ssid_fallback(self):
    self.assertIn("id='ssid-options'", self.wifi)
    self.assertIn("class='network-list'", self.wifi)
    self.assertIn("button.className = 'network-item'", self.wifi)
    self.assertIn("button.addEventListener('click'", self.wifi)
    self.assertIn("document.getElementById('ssid').value = item.ssid", self.wifi)
    self.assertIn("fetch('/scan', {cache:'no-store'", self.wifi)
    self.assertIn('webServer.sendHeader("Cache-Control", "no-store")', self.wifi)
    self.assertIn("Tap a network above or enter SSID manually", self.wifi)

  def test_recovery_save_validates_and_reads_back_credentials(self):
    save = self.wifi.split("void WifiManager::handleSave()", 1)[1]
    save = save.split("void WifiManager::handleConfigSave()", 1)[0]
    self.assertIn("ssid.length() == 0", save)
    self.assertIn("ssid.length() > 32", save)
    self.assertIn("pass.length() > 63", save)
    self.assertIn("pass.length() > 0 && pass.length() < 8", save)
    self.assertIn("ConfigManager::getWifiSsid() != ssid", save)
    self.assertIn("ConfigManager::getWifiPassword() != pass", save)
    self.assertIn("beginRecoveryOperation();", save)
    self.assertGreaterEqual(save.count("endRecoveryOperation();"), 2)

  def test_authenticated_requests_pause_attempt_and_local_ota_renews_lease(self):
    auth = self.wifi.split("bool WifiManager::requireLocalAuthentication()", 1)[1]
    auth = auth.split("void WifiManager::handleRecoveryManifest()", 1)[0]
    note = auth.index("recoveryRadioPolicy.noteAuthenticatedActivity(nowMs);")
    pause = auth.index("stopRecoveryStationAttemptForLocalWork(nowMs);")
    self.assertLess(note, pause)

    manifest = self.wifi.split("void WifiManager::handleRecoveryManifest()", 1)[1]
    manifest = manifest.split("void WifiManager::handleRecoveryUpload()", 1)[0]
    self.assertIn("beginRecoveryOperation();", manifest)
    self.assertEqual(manifest.count("endRecoveryOperation();"), 2)

    upload = self.wifi.split("void WifiManager::handleRecoveryUpload()", 1)[1]
    upload = upload.split(
        "void WifiManager::handleRecoveryUploadComplete()", 1
    )[0]
    self.assertIn("UPLOAD_FILE_START", upload)
    self.assertIn("beginRecoveryOperation();", upload)
    self.assertGreaterEqual(upload.count("touchRecoveryOperation();"), 2)
    self.assertGreaterEqual(upload.count("endRecoveryOperation();"), 2)
    self.assertIn("UPLOAD_FILE_ABORTED", upload)

  def test_mqtt_is_initialized_even_when_boot_wifi_is_late(self):
    mqtt_init = self.main.index("MqttManager::init();")
    wifi_branch = self.main.index("if (WifiManager::connectSTA(10000))")
    self.assertLess(mqtt_init, wifi_branch)

  def test_provisioned_broker_principal_can_differ_from_target_id(self):
    self.assertNotIn("targetId == MQTT_USER", self.mqtt)
    self.assertIn("std::strlen(MQTT_USER) > 0", self.mqtt)

  def test_mqtt_tls_socket_is_recreated_after_wifi_recovers(self):
    self.assertIn('noteAction("mqtt_wifi_lost")', self.mqtt)
    self.assertIn('noteAction("mqtt_wifi_recovered")', self.mqtt)
    self.assertIn("wifiClient.stop();", self.mqtt)
    self.assertIn("lastPublishMs = millis() - 5001", self.mqtt)

  def test_pending_ota_is_valid_only_with_wifi_and_mqtt(self):
    self.assertIn(
        "WifiManager::isConnected() && MqttManager::isConnected()", self.ota
    )
    health_block = self.ota.split("if (status == OtaStatus::HEALTH_WINDOW)", 1)[1]
    health_block = health_block.split("return;", 1)[0]
    self.assertNotIn("WifiManager::isAPMode()", health_block)


if __name__ == "__main__":
  unittest.main()
