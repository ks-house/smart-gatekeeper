"""Real worker state with a blocked fake socket, not a physical radio test."""

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MqttTelemetryWorkerTest(unittest.TestCase):
    def test_control_and_ota_respect_exclusive_worker_lease(self):
        source = (ROOT / "src/MqttManager.cpp").read_text()
        update = source.split("void MqttManager::update()", 1)[1].split(
            "void MqttManager::publishBootDiagnostics", 1,
        )[0]
        self.assertLess(update.index("pollTelemetryWorker();"), update.index("client.connected()"))
        self.assertLess(update.index("if (telemetryWorker.ownsTransport()) return;"),
                        update.index("client.connected()"))
        defer = source.split("void MqttManager::deferForAccessCritical()", 1)[1].split(
            "bool MqttManager::connectionAttemptInProgress()", 1,
        )[0]
        self.assertIn("telemetryWorker.start(client, statusTopic.c_str(), pendingTelemetry,", defer)
        self.assertNotIn("client.loop()", defer)
        self.assertNotIn("client.publish", defer)
        self.assertIn("connectWorkerIsRunning() || telemetryWorker.ownsTransport()", source)
        self.assertIn("result.generation == pendingTelemetryGeneration", source)
        self.assertIn("pendingTelemetry[sgk::MqttTelemetryWorker::kMaxPayloadBytes]", source)
        worker = (ROOT / "src/MqttTelemetryWorker.cpp").read_text()
        self.assertNotIn("client->loop", worker)
        self.assertNotIn("GattServer", worker)
        self.assertNotIn("triggerArm", worker)

    def test_blocked_socket_keeps_control_free_and_payload_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "mqtt-worker")
            subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                 "-Itests/mqtt_telemetry_worker_stubs", "-Iinclude",
                 "src/MqttTelemetryWorker.cpp", "tests/mqtt_telemetry_worker_test.cpp",
                 "-o", executable],
                cwd=ROOT, check=True, capture_output=True,
            )
            subprocess.run([executable], check=True, capture_output=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
