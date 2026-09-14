from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MqttConnectionPolicyTests(unittest.TestCase):
    def test_executable_outcome_backoff_ring_and_wraparound(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "mqtt-policy")
            result = subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
                 "tests/mqtt_connection_policy_test.cpp", "-o", executable],
                cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([executable], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_integration_preserves_socket_ownership_and_failure_classification(self):
        source = (ROOT / "src/MqttManager.cpp").read_text()
        adoption = source.split("const bool sameLink =", 1)[1].split("// The worker has published", 1)[0]
        self.assertIn("sgk::classifyMqttResult", adoption)
        self.assertIn("const bool socketAlive = successful && sameLink && wifiUp", adoption)
        self.assertNotIn("mqttLastError = 0", source.split("void recordMqttLoss", 1)[1].split("uint32_t mqttLastConnect", 1)[0])
        self.assertIn("sgk::appendMqttConnectionJson(doc, mqttConnection", source)
        teardown = source.split("// The worker has published its terminal", 1)[1]
        self.assertLess(teardown.index("const int terminalError"), teardown.index("wifiClient.stop();"))
        self.assertIn("? client.state() : workerResult.mqtt_error", teardown)
        suspend = source.split("bool MqttManager::suspendForOta()", 1)[1].split("void MqttManager::resumeAfterOta", 1)[0]
        self.assertLess(suspend.index("connectionAttemptInProgress()"), suspend.index("const bool transportAlive"))
        self.assertIn("sgk::MqttLossReason::kTransportLost", suspend)

    def test_json_pool_and_wire_budget_preserve_signed_status(self):
        include = os.environ.get("SGK_ARDUINOJSON_INCLUDE")
        if not include:
            candidates = list((ROOT / ".pio/libdeps").glob("*/ArduinoJson/src/ArduinoJson.h"))
            if candidates:
                include = str(candidates[0].parent)
        if not include:
            self.skipTest("ArduinoJson host headers unavailable; set SGK_ARDUINOJSON_INCLUDE")
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "mqtt-json")
            result = subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
                 "-I" + include, "tests/mqtt_connection_json_test.cpp", "-o", executable],
                cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([executable], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
