"""Execute actual GattServer reservation/admission with the real protocol core."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}\n", start) + 3]


class GattIdleRadioReservationTest(unittest.TestCase):
    def test_actual_atomic_admission_enabled_and_default_disabled(self):
        source = (ROOT / "src/GattServer.cpp").read_text()
        header = (ROOT / "include/GattServer.h").read_text()
        for declaration in ("static bool tryReserveIdleRadio();",
                            "static void releaseIdleRadio();",
                            "static bool hasIdleRadioReservation();"):
            self.assertIn(declaration, header,
                          "idle-radio admission needs an owned atomic reservation API")
        signatures = (
            "bool controllerHasActiveConnection()",
            "bool GattServer::tryReserveIdleRadio()",
            "void GattServer::releaseIdleRadio()",
            "bool GattServer::hasIdleRadioReservation()",
            "bool GattServer::isOtaBusy()",
            "void GattServer::setOtaBusy(bool busy)",
            "bool GattServer::hasPendingIngress()",
            "bool GattServer::hasActiveOutput()",
            "bool GattServer::handleConnect(uint16_t connection_id)",
        )
        for signature in signatures:
            self.assertIn(signature, source, "missing production reservation behavior")
        state = source.split("bool advertising_restart_requested_", 1)[1].split(
            "void incrementAdvertisingCounter", 1)[0]
        production = "bool advertising_restart_requested_" + state
        production += "\n".join(function(source, signature) for signature in signatures)
        with tempfile.TemporaryDirectory(prefix="sgk-gatt-radio-") as directory:
            temporary = Path(directory)
            (temporary / "gatt_radio_production.inc").write_text(production)
            (temporary / "gatt_radio_init.inc").write_text(
                function(source, "void GattServer::init()"))
            for enabled in (0, 1):
                with self.subTest(hardwareless=enabled):
                    executable = str(temporary / ("radio-" + str(enabled)))
                    result = subprocess.run([
                        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                        "-DENABLE_HARDWARELESS_RC=" + str(enabled),
                        "-I" + str(temporary), "-Iinclude",
                        "tests/gatt_idle_radio_reservation_test.cpp",
                        "src/GattProtocol.cpp", "src/SensorSessionDiagnostics.cpp",
                        "src/OfflineEventQueue.cpp",
                        "-o", executable,
                    ], cwd=ROOT, text=True, capture_output=True, timeout=45)
                    self.assertEqual(0, result.returncode, result.stderr)
                    result = subprocess.run([executable], text=True,
                                            capture_output=True, timeout=10)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertIn("idle radio reservation passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
