"""Execute the actual connect worker against deterministic platform boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MqttConnectWorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="sgk-connect-worker-")
        temporary = Path(cls.directory.name)
        source = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")
        state = source.split("enum class MqttConnectOutcome", 1)[1].split(
            "struct PendingSignedAccessCommand", 1
        )[0]
        helpers = source.split("bool connectWorkerIsRunning()", 1)[1].split(
            "const char* connectOutcomeName", 1
        )[0]
        entry = source.split("void MqttManager::connectWorkerEntry(void* argument)", 1)[1].split(
            "bool MqttManager::dispatchCriticalManual(", 1
        )[0]
        (temporary / "mqtt_connect_worker_state.inc").write_text(
            "enum class MqttConnectOutcome" + state
            + "bool connectWorkerIsRunning()" + helpers, encoding="utf-8"
        )
        (temporary / "mqtt_connect_worker_entry.inc").write_text(
            "void MqttManager::connectWorkerEntry(void* argument)" + entry,
            encoding="utf-8",
        )
        cls.executable = str(temporary / "mqtt-connect-worker")
        result = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             "-I" + str(temporary), "tests/mqtt_connect_worker_test.cpp",
             "-o", cls.executable],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            cls.directory.cleanup()
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_scenario(self, scenario):
        result = subprocess.run(
            [self.executable, scenario], capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_watchdog_enrollment_failure_prevents_all_transport_io(self):
        self.run_scenario("watchdog_add_failed")

    def test_watchdog_reset_failure_prevents_each_subsequent_phase(self):
        for phase in range(1, 7):
            with self.subTest(failed_reset=phase):
                self.run_scenario(f"watchdog_reset_{phase}")

    def test_watchdog_cleanup_failure_cannot_be_adopted(self):
        self.run_scenario("watchdog_delete_failed")

    def test_external_cancellation_and_wifi_generation_change_release_owner(self):
        for kind in ("cancel", "link"):
            for phase in ("before", "tls", "mqtt", "command", "acl", "publish"):
                with self.subTest(kind=kind, after_phase=phase):
                    self.run_scenario(f"{kind}_{phase}")

    def test_transport_failure_and_success_preserve_handoff(self):
        for scenario in ("tls_failed", "mqtt_failed", "success"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)


if __name__ == "__main__":
    unittest.main()
