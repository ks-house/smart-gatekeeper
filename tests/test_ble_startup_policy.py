"""Build and execute the ACL-gated BLE startup policy for issue #175."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]


class BleStartupPolicyTests(unittest.TestCase):
  def test_acl_gated_one_shot_startup(self):
    compiler = shutil.which("g++")
    if compiler is None:
      compiler = str(
          Path.home() / ".platformio/packages/toolchain-gccmingw32/bin/g++.exe"
      )
    self.assertTrue(Path(compiler).is_file(), "native g++ compiler is required")

    with tempfile.TemporaryDirectory() as directory:
      executable = Path(directory) / f"ble_startup_policy_{uuid.uuid4().hex}.exe"
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
              "tests/ble_startup_policy_test.cpp",
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
      self.assertIn("BleStartupPolicy host tests passed", run_result.stdout)

  def test_main_checks_after_mqtt_update(self):
    main = (ROOT / "src/main.cpp").read_text(encoding="utf-8")
    update = main.index("MqttManager::update();")
    decision = main.index("g_ble_startup_policy.shouldStart", update)
    gatt = main.index("GattServer::update();", decision)
    self.assertLess(update, decision)
    self.assertLess(decision, gatt)
    self.assertIn("g_acl_manager.hasActiveAcl()", main[decision:gatt])


if __name__ == "__main__":
  unittest.main()
