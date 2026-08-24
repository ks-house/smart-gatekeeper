"""Build and execute the recovery radio timing policy used by WifiManager."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]


class RecoveryRadioPolicyTests(unittest.TestCase):
  def test_production_policy_transitions(self):
    compiler = shutil.which("g++")
    if compiler is None:
      compiler = str(
          Path.home() / ".platformio/packages/toolchain-gccmingw32/bin/g++.exe"
      )
    self.assertTrue(Path(compiler).is_file(), "native g++ compiler is required")

    with tempfile.TemporaryDirectory() as directory:
      executable = (
          Path(directory) / f"recovery_radio_policy_{uuid.uuid4().hex}.exe"
      )
      compile_result = subprocess.run(
          [
              compiler,
              "-std=c++17",
              "-Wall",
              "-Wextra",
              "-Werror",
              "-static",
              "-static-libgcc",
              "-static-libstdc++",
              "-Iinclude",
              "tests/recovery_radio_policy_test.cpp",
              "-o",
              str(executable),
          ],
          cwd=ROOT,
          text=True,
          capture_output=True,
          check=False,
          shell=False,
      )
      self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
      run_result = subprocess.run(
          [str(executable)],
          cwd=ROOT,
          text=True,
          capture_output=True,
          check=False,
          shell=False,
      )
      self.assertEqual(run_result.returncode, 0, run_result.stderr)
      self.assertIn("RecoveryRadioPolicy host tests passed", run_result.stdout)


if __name__ == "__main__":
  unittest.main()
