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
    cls.config = (ROOT / "include" / "config.h").read_text(encoding="utf-8")
    cls.diagnostics = (ROOT / "src" / "DiagnosticsManager.cpp").read_text(
        encoding="utf-8"
    )

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
    self.assertIn(
        "[WIFI-DIAG] unplanned station disconnect reason=%u", self.wifi
    )
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

  def test_disconnect_diagnostics_preserve_last_unplanned_reason(self):
    self.assertIn("WiFi.disconnectReasonName(reason)", self.wifi)
    self.assertIn(
        "[WIFI-DIAG] unplanned station disconnect reason=%u (%s)",
        self.wifi,
    )
    self.assertIn(
        "[WIFI-DIAG] intentional station disconnect ", self.wifi
    )
    self.assertIn(
        "wifiLastUnplannedDisconnectReason =", self.wifi
    )
    callback = self.wifi.split(
        "ARDUINO_EVENT_WIFI_STA_DISCONNECTED", 1
    )[0].rsplit("WiFi.onEvent(", 1)[1]
    intentional = callback.split(
        "if (intentional)", 1
    )[1].split("wifiLastUnplannedDisconnectReason =", 1)[0]
    self.assertIn("reason == WIFI_REASON_ASSOC_LEAVE", callback)
    self.assertIn("clearIntentionalDisconnectMarker();", intentional)
    self.assertIn("return;", intentional)
    self.assertNotIn("wifiLastUnplannedDisconnectReason =", intentional)
    self.assertIn(
        "lastUnplannedDisconnectReason()", self.wifi
    )

  def test_every_internal_station_disconnect_uses_attribution_wrapper(self):
    wrapper = self.wifi.split(
        "void disconnectStationIntentionally", 1
    )[1].split("void registerWifiDiagnostics", 1)[0]
    self.assertEqual(self.wifi.count("WiFi.disconnect(false, false)"), 1)
    self.assertIn("WiFi.disconnect(false, false)", wrapper)
    self.assertEqual(
        self.wifi.count("disconnectStationIntentionally("), 8
    )
    self.assertIn(
        "kIntentionalDisconnectEventWindowMs = 2000", self.wifi
    )
    self.assertIn("recentIntentionalRequest", self.wifi)

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
    disconnect = scan.index('disconnectStationIntentionally("recovery_scan");')
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
    self.assertIn("mqttNextConnectAttemptMs = millis();", self.mqtt)
    self.assertIn(
        "mqttReconnectDelayMs = MQTT_RECONNECT_INITIAL_MS", self.mqtt
    )
    self.assertIn("WifiManager::linkGeneration()", self.mqtt)
    self.assertIn('noteAction("mqtt_wifi_generation_changed")', self.mqtt)
    generation = self.mqtt.split(
        "wifiLinkGeneration != wifiLinkGenerationLastUpdate", 1
    )[1].split("const bool wifiAvailable", 1)[0]
    self.assertIn("requestConnectWorkerCancellation();", generation)
    self.assertIn("resetMqttDnsResolution();", generation)
    self.assertIn("workerResult.wifi_link_generation", generation)
    self.assertIn("wifiClient.stop();", generation)

  def test_pending_ota_is_valid_only_with_wifi_and_mqtt(self):
    self.assertIn(
        "WifiManager::isConnected() && MqttManager::isConnected()", self.ota
    )
    health_block = self.ota.split("if (status == OtaStatus::HEALTH_WINDOW)", 1)[1]
    health_block = health_block.split("return;", 1)[0]
    self.assertNotIn("WifiManager::isAPMode()", health_block)

  def test_normal_sta_outage_escalates_only_from_safe_service(self):
    self.assertIn("StationRecoveryEscalationPolicy", self.policy)
    self.assertIn("WIFI_STA_RECOVERY_GRACE_MS = 30000", self.config)
    self.assertIn("WIFI_RECOVERY_AP_RETRY_MS = 60000", self.config)
    observe = self.wifi.split(
        "void WifiManager::observeConnectivity", 1
    )[1].split("void WifiManager::serviceRecovery", 1)[0]
    service = self.wifi.split(
        "void WifiManager::serviceRecovery", 1
    )[1].split("bool WifiManager::isConnected", 1)[0]
    self.assertNotIn("WiFi.disconnect", observe)
    self.assertNotIn("WiFi.mode", observe)
    self.assertIn("stationRecoveryPolicy.actionDue(nowMs)", service)
    self.assertIn("startRecoveryAP(false, 0)", service)
    self.assertIn("stationRecoveryPolicy.escalationFailed(nowMs)", service)

    loop = self.main.split("void loop()", 1)[1]
    critical = loop.index("bool accessCritical = isAccessPathCritical()")
    observe_call = loop.index("WifiManager::observeConnectivity(now)")
    safe_guard = loop.index("if (!accessCritical)")
    service_call = loop.index("WifiManager::serviceRecovery(now)")
    self.assertLess(critical, observe_call)
    self.assertLess(observe_call, safe_guard)
    self.assertLess(safe_guard, service_call)

  def test_mqtt_connect_has_layered_timeouts_and_capped_backoff(self):
    for contract in (
        "wifiClient.setConnectionTimeout(MQTT_TCP_CONNECT_TIMEOUT_MS)",
        "wifiClient.setHandshakeTimeout(MQTT_TLS_HANDSHAKE_TIMEOUT_SECONDS)",
        "client.setSocketTimeout(MQTT_PROTOCOL_SOCKET_TIMEOUT_SECONDS)",
        "MQTT_RECONNECT_INITIAL_MS = 5000",
        "MQTT_RECONNECT_MAX_MS = 30000",
        "mqttReconnectDelayMs * 2",
    ):
      self.assertIn(contract, self.mqtt + self.config)
    self.assertIn('noteAction("mqtt_connect_start")', self.mqtt)
    self.assertIn('xTaskCreate(\n        connectWorkerEntry, "mqtt-connect"', self.mqtt)
    self.assertIn("connectWorkerIsRunning()", self.mqtt)

  def test_mqtt_dns_is_polled_with_a_real_deadline_before_tls(self):
    self.assertIn("MQTT_DNS_RESOLVE_TIMEOUT_MS = 5000", self.config)
    dns = self.mqtt.split("MqttDnsPollResult pollMqttDns", 1)[1]
    dns = dns.split("bool parseLowerHex16", 1)[0]
    self.assertIn("dns_gethostbyname_addrtype", dns)
    self.assertIn("MQTT_DNS_RESOLVE_TIMEOUT_MS", dns)
    self.assertIn("mqttDnsGeneration", dns)
    self.assertNotIn("Network.hostByName", dns)
    update = self.mqtt.split("void MqttManager::update()", 1)[1]
    resolve = update.index("pollMqttDns(&brokerAddress)")
    start = update.index("startConnectWorker(brokerAddress", resolve)
    self.assertLess(resolve, start)
    self.assertNotIn("wifiClient.connect(", update)
    self.assertNotIn("client.connect(", update)

    worker = self.mqtt.split(
        "void MqttManager::connectWorkerEntry", 1
    )[1].split("void MqttManager::dispatchPendingAccessCommand", 1)[0]
    tls = worker.index("wifiClient.connect(")
    mqtt = worker.index("client.connect(", tls)
    self.assertLess(tls, mqtt)
    self.assertIn(
        "request.broker_address, MQTT_PORT, MQTT_HOST, SECRET_ROOT_CA_CERT",
        worker,
    )

  def test_connect_worker_has_exclusive_generation_checked_handoff(self):
    update = self.mqtt.split("void MqttManager::update()", 1)[1]
    update = update.split("void MqttManager::publishBootDiagnostics", 1)[0]
    running = update.index("if (connectWorkerIsRunning())")
    cancel = update.index("requestConnectWorkerCancellation();", running)
    take = update.index("takeConnectWorkerResult(&workerResult)", cancel)
    first_client_access = update.index("client.connected()", take)
    self.assertLess(running, cancel)
    self.assertLess(cancel, take)
    self.assertLess(take, first_client_access)
    self.assertIn(
        "workerResult.wifi_link_generation == currentLinkGeneration", update
    )
    self.assertIn("MqttConnectOutcome::kSuccess", update)
    self.assertIn("mqtt_connect_worker_stale", update)

    header = (ROOT / "include" / "MqttManager.h").read_text(
        encoding="utf-8"
    )
    connected = header.split("static bool isConnected();", 1)[0]
    self.assertNotIn("wifiClient.connected() && client.connected()", connected)
    self.assertGreaterEqual(
        self.mqtt.count('doc["wifi_link_generation"] = '
                        'WifiManager::linkGeneration()'),
        2,
    )
    self.assertGreaterEqual(
        self.mqtt.count('doc["wifi_outage_count"] = '
                        'WifiManager::outageCount()'),
        2,
    )

  def test_connect_worker_has_hard_stall_watchdog_and_tls_coordination(self):
    worker = self.mqtt.split(
        "void MqttManager::connectWorkerEntry", 1
    )[1].split("void MqttManager::dispatchPendingAccessCommand", 1)[0]
    enroll = worker.index("esp_task_wdt_add(nullptr)")
    tls = worker.index("wifiClient.connect(", enroll)
    mqtt = worker.index("client.connect(", tls)
    first_feed = worker.index("feedWatchdog();", tls)
    self.assertLess(enroll, tls)
    self.assertLess(tls, first_feed)
    self.assertLess(first_feed, mqtt)

    finish = worker.split("auto finish =", 1)[1].split("auto stale =", 1)[0]
    delete = finish.index("esp_task_wdt_delete(nullptr)")
    handoff = finish.index("completeConnectWorker(result)", delete)
    self.assertLess(delete, handoff)
    self.assertIn("watchdog_error", worker)

  def test_connect_worker_watchdog_diagnostics_are_race_free(self):
    snapshot = self.mqtt.split(
        "uint32_t connectWorkerWatchdogFailuresSnapshot()", 1
    )[1].split("void requestConnectWorkerCancellation", 1)[0]
    self.assertIn("portENTER_CRITICAL(&mqttConnectWorkerMux)", snapshot)
    self.assertIn("mqttConnectWorkerWatchdogFailures", snapshot)
    self.assertIn("portEXIT_CRITICAL(&mqttConnectWorkerMux)", snapshot)
    self.assertEqual(
        self.mqtt.count("connectWorkerWatchdogFailuresSnapshot();"), 2
    )
    self.assertGreaterEqual(
        self.mqtt.count('doc["mqtt_connect_worker_wdt_failures"] ='),
        2,
    )

    self.assertIn("MqttManager::deferForAccessCritical();", self.main)
    self.assertIn(
        "bool MqttManager::connectionAttemptInProgress()", self.mqtt
    )
    self.assertGreaterEqual(
        self.ota.count("MqttManager::connectionAttemptInProgress()"),
        3,
    )

  def test_loop_watchdog_is_reconfigured_before_subscription(self):
    reconfigure = self.diagnostics.index("esp_task_wdt_reconfigure")
    enable = self.diagnostics.index("enableLoopWDT();")
    status = self.diagnostics.index("esp_task_wdt_status(nullptr)")
    self.assertLess(reconfigure, enable)
    self.assertLess(enable, status)
    self.assertIn("LOOP_TASK_WATCHDOG_TIMEOUT_MS = 45000", self.config)
    self.assertIn("watchdogConfig.trigger_panic = true", self.diagnostics)
    self.assertIn("DiagnosticsManager::enableLoopWatchdog();", self.main)
    self.assertNotIn("disableLoopWDT", self.diagnostics + self.main + self.ota)

  def test_ota_services_gatt_and_watchdog_under_bounded_deadlines(self):
    self.assertIn(
        "otaHttp.setConnectTimeout(OTA_TCP_CONNECT_TIMEOUT_MS)", self.ota
    )
    self.assertIn(
        "otaClient.setHandshakeTimeout(OTA_TLS_HANDSHAKE_TIMEOUT_SECONDS)",
        self.ota,
    )
    wait = self.ota.split("bool waitForSafeState()", 1)[1].split(
        "}  // namespace", 1
    )[0]
    self.assertLess(
        wait.index("kOtaSafeStateTimeoutMs"),
        wait.index("DiagnosticsManager::feedLoopWatchdog();"),
    )
    download = self.ota.split(
        "while (updateBytes < stagedManifest.artifact_size)", 1
    )[1].split("otaHttp.end();", 1)[0]
    gatt = download.index("GattServer::update();")
    watchdog = download.index("DiagnosticsManager::feedLoopWatchdog();", gatt)
    total_deadline = download.index("kArtifactDownloadTimeoutMs", watchdog)
    idle_deadline = download.index("kArtifactIdleTimeoutMs", total_deadline)
    no_data = download.index("if (available == 0)", idle_deadline)
    write = download.index("writeImageChunk", no_data)
    progress = download.index("lastProgressMs = millis();", write)
    self.assertLess(gatt, watchdog)
    self.assertLess(watchdog, total_deadline)
    self.assertLess(total_deadline, idle_deadline)
    self.assertLess(idle_deadline, no_data)
    self.assertLess(no_data, write)
    self.assertLess(write, progress)

  def test_target_snapshots_are_retained_but_live_evidence_is_not(self):
    worker = self.mqtt.split(
        "void MqttManager::connectWorkerEntry", 1
    )[1].split("void MqttManager::dispatchPendingAccessCommand", 1)[0]
    self.assertIn(
        "client.publish(availabilityTopic.c_str(), onlinePayload, true)",
        worker,
    )
    self.assertIn(
        "availabilityTopic.c_str(), 1, true, request.will_payload",
        self.mqtt,
    )
    self.assertGreaterEqual(
        self.mqtt.count('\\"scope\\":\\"mqtt_transport\\"'), 2
    )
    self.assertIn("SUBACK is not observable", self.mqtt)
    self.assertIn("client.publish(bootTopic.c_str(), buffer, true)", self.mqtt)
    self.assertIn(
        "client.publish(configStateTopic.c_str(), buffer, true)", self.mqtt
    )
    self.assertIn(
        "client.publish(statusTopic.c_str(), pendingTelemetry, false)",
        self.mqtt,
    )
    self.assertIn(
        "client.publish(canonicalEventTopic.c_str(), payload, false)",
        self.mqtt,
    )


if __name__ == "__main__":
  unittest.main()
