import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConnectivityRecoveryContractTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.wifi = (ROOT / "src" / "WifiManager.cpp").read_text(encoding="utf-8")
    cls.mqtt = (ROOT / "src" / "MqttManager.cpp").read_text(encoding="utf-8")
    cls.main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
    cls.ota = (ROOT / "src" / "OtaManager.cpp").read_text(encoding="utf-8")

  def test_provisioning_ap_keeps_retrying_station(self):
    self.assertIn("WiFi.mode(WIFI_AP_STA)", self.wifi)
    self.assertIn("kStationRetryIntervalMs = 15000", self.wifi)
    self.assertIn("startNonBlockingStationAttempt();", self.wifi)
    self.assertIn("WiFi.reconnect();", self.wifi)
    self.assertEqual(self.wifi.count("WiFi.reconnect();"), 2)
    self.assertEqual(self.wifi.count("WiFi.begin(ssid.c_str(), pass.c_str());"), 1)
    self.assertIn('noteAction("wifi_sta_autoreconnect_watch")', self.wifi)
    self.assertIn("[WIFI-DIAG] station disconnect reason=%u", self.wifi)
    self.assertIn('noteAction("wifi_recovered_from_ap")', self.wifi)

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
    resume = scan.index("WiFi.setAutoReconnect(true);")
    reconnect = scan.index("WiFi.reconnect();")
    self.assertLess(pause, disconnect)
    self.assertLess(disconnect, first_scan)
    self.assertLess(first_scan, retry_scan)
    self.assertLess(retry_scan, resume)
    self.assertLess(resume, reconnect)
    self.assertEqual(scan.count("WiFi.scanNetworks("), 2)
    self.assertIn('noteAction("wifi_scan_sta_paused")', scan)
    self.assertIn('noteAction("wifi_scan_complete")', scan)
    self.assertIn('noteAction("wifi_sta_retry_after_scan")', scan)
    self.assertIn('webServer.send(503, "application/json"', scan)

  def test_recovery_ui_keeps_scan_and_manual_ssid_fallback(self):
    self.assertIn("id='ssid-options'", self.wifi)
    self.assertIn("class='network-list'", self.wifi)
    self.assertIn("button.className = 'network-item'", self.wifi)
    self.assertIn("button.addEventListener('click'", self.wifi)
    self.assertIn("document.getElementById('ssid').value = item.ssid", self.wifi)
    self.assertIn("fetch('/scan')", self.wifi)
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
