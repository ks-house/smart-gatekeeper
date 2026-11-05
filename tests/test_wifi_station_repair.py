"""Execute actual WifiManager repair methods against a deterministic driver."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.find(signature)
    if start < 0:
        raise AssertionError("production function missing: " + signature)
    opening = source.index("{", start)
    depth = 0
    quoted = None
    comment = None
    escaped = False
    position = opening
    while position < len(source):
        character = source[position]
        pair = source[position:position + 2]
        if comment == "line":
            if character == chr(10):
                comment = None
        elif comment == "block":
            if pair == "*/":
                comment = None
                position += 1
        elif quoted:
            if escaped:
                escaped = False
            elif ord(character) == 92:
                escaped = True
            elif character == quoted:
                quoted = None
        elif pair == "//":
            comment = "line"
            position += 1
        elif pair == "/*":
            comment = "block"
            position += 1
        elif character in ("'", '"'):
            quoted = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[start:position + 1] + chr(10)
        position += 1
    raise AssertionError("unterminated production function: " + signature)

class WifiStationRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="sgk-station-repair-")
        temporary = Path(cls.directory.name)
        source = (ROOT / "src/WifiManager.cpp").read_text(encoding="utf-8")
        declarations = "\n".join(
            line for line in source.splitlines()
            if line.startswith(("static", "constexpr")) and ("stationRepair" in line or "kStationRepair" in line)
        )
        helpers = (
            "void clearIntentionalDisconnectMarker()", "void configureStationCompatibilityProfile()",
            "bool stationCredentialsProvisioned()", "void endRecoveryOperation()",
            "bool isRecoveryOperationActive(uint32_t nowMs)",
        )
        methods = (
            "bool WifiManager::isStationAssociated()", "bool WifiManager::isConnected()",
            "bool WifiManager::isLocalRecoveryActive()",
            "bool WifiManager::isStationRepairPending()", "void WifiManager::cancelStationRepair(",
            "bool WifiManager::beginStationRepair()", "bool WifiManager::finishStationRepair(",
            "void WifiManager::serviceRecovery(uint32_t nowMs)",
        )
        extracted = declarations + "\n" + "".join(function(source, signature) for signature in helpers + methods)
        (temporary / "wifi_station_repair_production.inc").write_text(extracted, encoding="utf-8")
        cls.executable = str(temporary / "wifi-station-repair")
        result = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
             "-I" + str(temporary), "tests/wifi_station_repair_test.cpp", "-o", cls.executable],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            cls.directory.cleanup()
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_scenario(self, scenario):
        result = subprocess.run([self.executable, scenario], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_guards_and_raw_driver_observation(self):
        for scenario in ("guard_reservation", "guard_ap", "guard_local", "guard_credentials",
                         "guard_placeholder", "guard_ota", "raw_association", "healthy_noop",
                         "ordinary_workers", "ordinary_reservation", "ordinary_recovery"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_asynchronous_disconnect_and_previous_policy_restoration(self):
        for scenario in ("disconnect_rejected_on", "disconnect_rejected_off", "pending_guard",
                         "finish_before_edge", "finish_guard_reservation", "finish_guard_ap",
                         "auto_disable_rejected"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_stage_order_and_terminal_failure_fallback(self):
        for scenario in ("stage_one", "short_disconnect_edge", "reconnect_rejected", "stage_two",
                         "mode_off_failed", "mode_sta_failed", "begin_failed"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_owned_cancel_and_independent_finite_lease(self):
        for scenario in ("cancel_false", "cancel_true", "cancel_true_without_reservation",
                         "lease_expiry", "lease_workers", "lease_reservation", "lease_local", "lease_wrap"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)


if __name__ == "__main__":
    unittest.main()
