"""Execute firmware policies and the real ultrasonic driver with fake IO/time."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TargetFieldRecoveryTest(unittest.TestCase):
    def test_field_recovery_host_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            includes = Path(directory) / "include"
            includes.mkdir()
            # Isolate config from installed credentials, including on CI where
            # include/secrets.h does not exist. Production driver code is real.
            for name in ("UltrasonicSensor.h", "config.h"):
                shutil.copyfile(ROOT / "include" / name, includes / name)
            shutil.copyfile(ROOT / "include/secrets.h.example", includes / "secrets.h")
            executable = str(Path(directory) / "field-recovery")
            result = subprocess.run([
                "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-I" + str(includes), "-Itests/ultrasonic_stubs", "-Iinclude",
                "tests/field_recovery_test.cpp", "src/TargetAccessFsm.cpp",
                "src/UltrasonicSensor.cpp", "-o", executable,
            ], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([executable], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
