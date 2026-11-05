"""Execute the real allocation-free recovery controller against driver faults."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NetworkRecoveryControllerTest(unittest.TestCase):
    def test_async_order_ownership_races_deadlines_and_policy_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "network-recovery-controller")
            result = subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                 "-Iinclude", "tests/network_recovery_controller_test.cpp", "-o", executable],
                cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([executable], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("18 scenarios", result.stdout)


if __name__ == "__main__":
    unittest.main()
