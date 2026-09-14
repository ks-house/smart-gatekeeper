"""Executable advertisement controller faults, wire contract and owner wiring."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AdvertisementRecoveryTest(unittest.TestCase):
    def test_controller_fault_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "advertisement-recovery")
            result = subprocess.run([
                "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
                "tests/advertisement_recovery_test.cpp", "-o", executable,
            ], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([executable], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_lifecycle_owner_mutates_advertisements(self):
        config = (ROOT / "include/config.h").read_text()
        self.assertIn('"9f4d1000-7d9e-4fb1-9c54-6f4d53474b31"', config)
        self.assertIn('"a1b2c3d4-e5f6-7890-abcd-ef1234567890"', config.lower())
        main = (ROOT / "src/main.cpp").read_text()
        tuning = main.split("void setTxPower(", 1)[1].split("\n}", 1)[0]
        self.assertIn("GattServer::requestAdvertisingTxPower", tuning)
        self.assertNotIn("BLEDevice::", tuning)
        adapter = (ROOT / "src/GattServer.cpp").read_text()
        self.assertEqual(adapter.count("->setAdvertisementData("), 1)
        self.assertEqual(adapter.count("->setScanResponseData("), 1)
        self.assertIn("if (!diagnostics.primary_applied)", adapter)
        self.assertIn("if (!diagnostics.response_applied)", adapter)
        self.assertNotIn("ble_hs_cfg.", adapter)
        self.assertNotIn("setCustomGapHandler", adapter)
        service = adapter.split("void servicePresenceAdvertisement", 1)[1].split(
            "#if ENABLE_HARDWARELESS_RC", 1)[0]
        self.assertIn("lock(core_mutex)", service)
        self.assertIn("controllerHasActiveConnection()", service)
        self.assertIn("connected, advertising_ota_busy_, driver", service)


if __name__ == "__main__":
    unittest.main()
