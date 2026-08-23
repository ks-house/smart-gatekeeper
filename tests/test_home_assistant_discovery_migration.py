import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "migrate_home_assistant_discovery",
    ROOT / "scripts" / "migrate_home_assistant_discovery.py")
MIGRATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MIGRATION
SPEC.loader.exec_module(MIGRATION)


class HomeAssistantDiscoveryMigrationTests(unittest.TestCase):
  def setUp(self):
    self.target_id = "target_test"
    self.prefix = f"gatekeeper/v1/targets/{self.target_id}"
    self.plan = MIGRATION.build_plan(self.target_id)

  def test_plan_updates_exactly_15_read_only_entities(self):
    updates = [item for item in self.plan if item.payload]
    self.assertEqual(len(updates), 15)
    self.assertEqual(
        sum("/binary_sensor/" in item.topic for item in updates), 2)
    self.assertEqual(sum("/sensor/" in item.topic for item in updates), 13)

    object_ids = {item.topic.split("/")[-2] for item in updates}
    self.assertEqual(object_ids, {
        "distance", "distance_cm", "state", "ip", "arm_remaining_s",
        "wifi_rssi", "free_heap", "uptime_s", "firmware",
        "door_binary", "pre_armed", "cfg_tx_power",
        "cfg_distance_thresh", "cfg_prearm_duration",
        "cfg_relay_cooldown",
    })
    for publication in updates:
      config = json.loads(publication.payload)
      self.assertEqual(
          config["device"]["identifiers"], ["smart_gatekeeper_01"])
      self.assertTrue(
          config["unique_id"].startswith("smart_gatekeeper_01_"))
      self.assertNotIn("availability_topic", config)
      self.assertNotIn("availability_template", config)
      self.assertNotIn("command_topic", config)
      self.assertNotIn("payload_press", config)
      self.assertTrue(publication.retain)
      self.assertEqual(publication.qos, 1)

  def test_state_topics_use_only_secure_target_namespace(self):
    updates = [json.loads(item.payload) for item in self.plan if item.payload]
    for config in updates:
      self.assertEqual(config["state_topic"], f"{self.prefix}/status")
      self.assertEqual(config["expire_after"], 30)
      self.assertNotIn("smart-gatekeeper/", config["state_topic"])
      self.assertNotIn("gatekeeper/config/", config["state_topic"])

  def test_periodic_target_status_contains_all_config_values(self):
    source = (ROOT / "src" / "MqttManager.cpp").read_text(encoding="utf-8")
    start = source.index("void MqttManager::publishTelemetry(")
    end = source.index("void MqttManager::publishEvent(", start)
    body = source[start:end]
    for assignment in (
        'doc["tx_power"] = g_tx_power_dbm;',
        'doc["distance_threshold_cm"] = g_distance_threshold_cm;',
        'doc["duration_ms"] = g_pre_arm_duration_ms;',
        'doc["relay_cooldown_ms"] = g_relay_cooldown_ms;',
    ):
      self.assertIn(assignment, body)
    self.assertIn("client.publish(statusTopic.c_str(), buf, false)", body)

  def test_plan_removes_all_seven_legacy_plaintext_controls(self):
    removals = [item for item in self.plan if not item.payload]
    self.assertEqual(len(removals), 7)
    self.assertTrue(all(not item.payload for item in self.plan[:7]))
    self.assertTrue(all(item.payload for item in self.plan[7:]))
    self.assertEqual({item.topic for item in removals}, {
        "homeassistant/button/smart_gatekeeper_01/open_gate/config",
        "homeassistant/button/smart_gatekeeper_01/trigger_ota/config",
        "homeassistant/button/smart_gatekeeper_01/reboot/config",
        "homeassistant/number/smart_gatekeeper_01/config_tx_power_num/config",
        "homeassistant/number/smart_gatekeeper_01/config_dist_thresh_num/config",
        "homeassistant/number/smart_gatekeeper_01/config_duration_num/config",
        "homeassistant/number/smart_gatekeeper_01/config_relay_cooldown_num/config",
    })
    for publication in removals:
      self.assertTrue(publication.retain)
      self.assertEqual(publication.qos, 1)

  def test_default_dry_run_is_network_free_and_redacts_environment(self):
    stdout = io.StringIO()
    secret_user = "do-not-print-user"
    secret_password = "do-not-print-password"
    with mock.patch.dict(os.environ, {
        MIGRATION.USERNAME_ENV: secret_user,
        MIGRATION.PASSWORD_ENV: secret_password,
    }, clear=False), contextlib.redirect_stdout(stdout):
      result = MIGRATION.main([
          "--broker-host", "example.invalid",
          "--broker-port", "8883",
          "--target-id", self.target_id,
      ])
    output = stdout.getvalue()
    self.assertEqual(result, 0)
    self.assertIn("DRY_RUN discovery_updates=15", output)
    self.assertIn("No network connection", output)
    self.assertNotIn(secret_user, output)
    self.assertNotIn(secret_password, output)

  def test_cli_has_no_direct_credential_value_options(self):
    options = {
        option
        for action in MIGRATION.build_parser()._actions
        for option in action.option_strings
    }
    self.assertNotIn("--username", options)
    self.assertNotIn("--password", options)
    self.assertIn("--username-file", options)
    self.assertIn("--password-file", options)

  def test_credentialed_apply_requires_tls_before_network_import(self):
    with mock.patch.dict(os.environ, {
        MIGRATION.USERNAME_ENV: "hidden-user",
        MIGRATION.PASSWORD_ENV: "hidden-password",
    }, clear=True):
      with self.assertRaisesRegex(ValueError, "requires TLS"):
        MIGRATION.main([
            "--broker-host", "example.invalid",
            "--broker-port", "8883",
            "--target-id", self.target_id,
            "--apply",
        ])

  def test_target_id_rejects_topic_injection(self):
    for invalid in ("", "target/command", "target+#", "target space"):
      with self.subTest(invalid=invalid):
        with self.assertRaisesRegex(ValueError, "target ID"):
          MIGRATION.build_plan(invalid)

  def test_secret_files_strip_only_line_endings_and_conflict_with_env(self):
    with tempfile.TemporaryDirectory() as directory:
      secret_file = Path(directory) / "credential.txt"
      secret_file.write_text("  preserved spaces  \r\n", encoding="utf-8")
      with mock.patch.dict(os.environ, {}, clear=True):
        self.assertEqual(
            MIGRATION._read_secret(secret_file, "TEST_SECRET", "test"),
            "  preserved spaces  ")
      with mock.patch.dict(os.environ, {"TEST_SECRET": "hidden"}, clear=True):
        with self.assertRaisesRegex(ValueError, "not both"):
          MIGRATION._read_secret(secret_file, "TEST_SECRET", "test")

  def test_apply_publishes_every_action_as_qos1_retained(self):
    calls = []

    class FakeInfo:
      rc = 0

      def wait_for_publish(self, timeout):
        self.timeout = timeout

      def is_published(self):
        return True

    class FakeClient:
      def __init__(self, **_kwargs):
        self.credentials = None

      def username_pw_set(self, username, password):
        self.credentials = (username, password)

      def connect(self, _host, _port, keepalive):
        self.keepalive = keepalive
        return 0

      def loop_start(self):
        pass

      def publish(self, topic, payload, qos, retain):
        calls.append((topic, payload, qos, retain))
        return FakeInfo()

      def disconnect(self):
        pass

      def loop_stop(self):
        pass

    client_module = types.ModuleType("paho.mqtt.client")
    client_module.Client = FakeClient
    client_module.MQTTv311 = 4
    client_module.MQTT_ERR_SUCCESS = 0
    mqtt_module = types.ModuleType("paho.mqtt")
    mqtt_module.client = client_module
    paho_module = types.ModuleType("paho")
    paho_module.mqtt = mqtt_module
    with mock.patch.dict(sys.modules, {
        "paho": paho_module,
        "paho.mqtt": mqtt_module,
        "paho.mqtt.client": client_module,
    }):
      MIGRATION.publish_plan(
          "example.invalid", 8883, self.plan,
          username="hidden-user", password="hidden-password")

    self.assertEqual(len(calls), 22)
    self.assertTrue(all(qos == 1 and retain for _, _, qos, retain in calls))


if __name__ == "__main__":
  unittest.main()
