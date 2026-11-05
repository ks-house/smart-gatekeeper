"""Execute Target station-recovery fault policies without radio or device effects."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NetworkRecoveryPolicyTest(unittest.TestCase):
    def test_fault_thresholds_budget_stability_cancellation_and_clock_wrap(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "network-recovery-policy")
            result = subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                 "-Iinclude", "tests/network_recovery_policy_test.cpp", "-o", executable],
                cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([executable], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("19 scenarios, no reboot action", result.stdout)


if __name__ == "__main__":
    unittest.main()
