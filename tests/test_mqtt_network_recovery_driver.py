"""Execute the actual nested MQTT recovery driver against closed boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def extract_braced(source, marker, *, trailing_semicolon=False):
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                if trailing_semicolon:
                    if source[end:end + 1] != ";":
                        raise AssertionError("expected closed production declaration")
                    end += 1
                return source[start:end]
    raise AssertionError("unclosed production declaration")


class MqttNetworkRecoveryDriverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="sgk-network-driver-")
        temporary = Path(cls.directory.name)
        source = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")
        header = (ROOT / "include/OtaManager.h").read_text(encoding="utf-8")
        ota_enum = extract_braced(header, "enum class OtaStatus", trailing_semicolon=True)
        (temporary / "mqtt_network_driver_ota_enum.inc").write_text(ota_enum)
        # Every production state is exercised; new enum states must be blocked
        # unless they are one of the four explicitly quiescent outcomes.
        names = [value.strip().split("=")[0].strip()
                 for value in ota_enum.split("{", 1)[1].split("}", 1)[0].split(",")
                 if value.strip()]
        (temporary / "mqtt_network_driver_ota_cases.inc").write_text(
            "\n".join('{"%s", OtaManager::OtaStatus::%s},' % (name, name) for name in names))
        bodies = [
            extract_braced(source, "bool MqttManager::transportWorkersActive()"),
            extract_braced(source, "struct MqttManager::NetworkRecoveryDriver", trailing_semicolon=True),
            extract_braced(source, "bool MqttManager::serviceNetworkRecovery()"),
        ]
        (temporary / "mqtt_network_driver_actual.inc").write_text("\n\n".join(bodies))
        cls.executable = str(temporary / "mqtt-network-driver")
        result = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             "-I" + str(temporary), "-Iinclude", "tests/mqtt_network_recovery_driver_test.cpp",
             "-o", cls.executable], cwd=ROOT, capture_output=True, text=True, timeout=30)
        if result.returncode:
            cls.directory.cleanup()
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_scenario(self, scenario):
        result = subprocess.run([self.executable, scenario], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_update_observes_recovery_before_the_wifi_down_early_return(self):
        source = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")
        update = extract_braced(source, "void MqttManager::update()")
        self.assertLess(update.index("if (serviceNetworkRecovery()) return;"),
                        update.index("if (!wifiAvailable)"))
        service = extract_braced(source, "bool MqttManager::serviceNetworkRecovery()")
        self.assertLess(service.index("networkRecovery.observeLinkGeneration"),
                        service.index("networkRecoveryController.service"))

    def test_all_actual_ota_states_block_or_admit_as_explicitly_quiescent(self):
        self.run_scenario("ota")

    def test_each_safety_guard_and_post_reservation_race_prevents_mutation(self):
        self.run_scenario("guards")

    def test_pending_phase_takeover_and_busy_deferral_preserve_other_owners(self):
        self.run_scenario("waiting")

    def test_new_association_invalidates_old_failure_qualification_before_mutation(self):
        self.run_scenario("generation")

    def test_verbatim_driver_forwarding_teardown_order_and_stage_selection(self):
        self.run_scenario("forwarding")


if __name__ == "__main__":
    unittest.main()
