"""Diagnostic scratch ownership; no firmware, radio, or external dependencies."""

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MqttDiagnosticScratchTest(unittest.TestCase):
    def test_exclusive_lifetimes_alignment_and_queued_payload_independence(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "mqtt-diagnostic-scratch")
            compile_result = subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                 "-Iinclude", "tests/mqtt_diagnostic_scratch_test.cpp",
                 "-o", executable],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run(
                [executable], capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
