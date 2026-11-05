"""Execute generation/deadline DNS policy without network or platform services."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MqttDnsPolicyTests(unittest.TestCase):
    def test_executable_exactly_once_terminals_deadline_and_generation(self):
        with tempfile.TemporaryDirectory(prefix="sgk-dns-policy-") as directory:
            executable = str(Path(directory) / "mqtt-dns-policy")
            compile_result = subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
                 "tests/mqtt_dns_policy_test.cpp", "-o", executable],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run(
                [executable], capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
