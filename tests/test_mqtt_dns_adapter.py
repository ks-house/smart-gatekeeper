"""Execute MqttManager's DNS adapter, not a copied lifecycle implementation."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MqttDnsAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="sgk-dns-adapter-")
        temporary = Path(cls.directory.name)
        source = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")
        starts = [
            match.start() for match in re.finditer(
                r"enum class MqttDns(?:State|PollResult)|sgk::MqttDnsPolicy\s+", source
            )
        ]
        if not starts:
            raise AssertionError("production DNS adapter declaration missing")
        declarations = source[min(starts):source.index("enum class MqttConnectOutcome")]
        functions = source.split("void resetMqttDnsResolution()", 1)[1].split(
            "bool parseLowerHex16(", 1
        )[0]
        (temporary / "mqtt_dns_adapter_production.inc").write_text(
            declarations + "void resetMqttDnsResolution()" + functions,
            encoding="utf-8",
        )
        cls.executable = str(temporary / "mqtt-dns-adapter")
        result = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
             "-I" + str(temporary), "tests/mqtt_dns_adapter_test.cpp",
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

    def test_immediate_error_is_not_reported_twice(self):
        self.run_scenario("immediate_error_once")

    def test_callback_deadline_is_enforced_before_main_polls(self):
        for scenario in ("callback_at_deadline", "callback_after_deadline"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_generation_timeout_and_core_locks_preserve_adapter_contract(self):
        for scenario in ("stale_after_reset", "stale_after_timeout", "async_failure_once",
                         "ready_cache", "immediate_success", "millis_wrap", "null_output"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)


if __name__ == "__main__":
    unittest.main()
