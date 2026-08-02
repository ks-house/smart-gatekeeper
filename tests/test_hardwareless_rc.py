"""Build and execute the same C++ protocol core used by the ESP32 BLE adapter."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HardwarelessRcProductionCoreTest(unittest.TestCase):
    def test_production_cpp_core(self):
        compiler = shutil.which("g++")
        if compiler is None:
            compiler = str(
                Path.home()
                / ".platformio/packages/toolchain-gccmingw32/bin/g++.exe"
            )
        self.assertTrue(Path(compiler).is_file(), "native g++ compiler is required")
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "gatt_protocol_test.exe"
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
                    "src/GattProtocol.cpp",
                    "tests/gatt_protocol_test.cpp",
                    "-o",
                    str(executable),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            run_result = subprocess.run(
                [str(executable)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(run_result.returncode, 0, run_result.stderr)
            self.assertIn("GattProtocol host tests passed", run_result.stdout)

    def test_transport_has_no_relay_integration(self):
        core = (ROOT / "src" / "GattProtocol.cpp").read_text(encoding="utf-8")
        adapter = (ROOT / "src" / "GattServer.cpp").read_text(encoding="utf-8")
        self.assertNotIn("RelayController", core)
        self.assertNotIn("RelayController", adapter)
        self.assertNotIn("triggerManualDoorOpen", core + adapter)

    def test_adapter_owns_connections_and_ack_gates_targeted_indications(self):
        adapter = (ROOT / "src" / "GattServer.cpp").read_text(encoding="utf-8")
        shared = (ROOT / "include" / "GattProtocol.h").read_text(
            encoding="utf-8"
        )
        self.assertIn("if (!GattServer::handleConnect(connection_id))", adapter)
        self.assertIn("server->disconnect(connection_id);", adapter)
        self.assertIn("description->conn_handle, write_type_", adapter)
        self.assertIn("ConnectionToken owner", shared)
        self.assertIn("connection_generation", shared)
        self.assertLess(
            adapter.index("adapter_state.consumeOverflow"),
            adapter.index("adapter_state.popWrite"),
        )
        self.assertIn("ble_gatts_indicate_custom(owner.handle", adapter)
        self.assertIn("void onStatus(", adapter)
        self.assertIn("confirmationTimedOut", adapter)

    def test_ota_waits_on_real_target_state_before_network(self):
        ota = (ROOT / "src" / "OtaManager.cpp").read_text(encoding="utf-8")
        main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
        self.assertIn("safeStateProvider() != OtaSafeState::SAFE", ota)
        self.assertLess(
            ota.index("status = OtaStatus::WAIT_SAFE_STATE"),
            ota.index("if (!WifiManager::isConnected())"),
        )
        self.assertLess(
            ota.index("if (!WifiManager::isConnected())"),
            ota.index("WiFiClientSecure client"),
        )
        self.assertIn(
            "classifyOtaSafeState(state, is_armed, relay.isOn())", main
        )
        self.assertIn("OtaManager::setSafeStateProvider(currentOtaSafeState)", main)

    def test_provisioned_door_and_production_event_sink_are_wired(self):
        header = (ROOT / "include" / "GattProtocol.h").read_text(encoding="utf-8")
        config = (ROOT / "src" / "ConfigManager.cpp").read_text(encoding="utf-8")
        adapter = (ROOT / "src" / "GattServer.cpp").read_text(encoding="utf-8")
        main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
        example = (ROOT / "include" / "secrets.h.example").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("0x00, 0x11, 0x22, 0x33", header)
        self.assertIn('preferences.getString(\n        "hwless_door"', config)
        self.assertIn('SECRET_HARDWARELESS_DOOR_ID_HEX ""', example)
        self.assertIn("class CanonicalMqttEventSink", adapter)
        self.assertIn('document["sequence"] = event.sequence', adapter)
        self.assertIn('document["causation_event_id"]', adapter)
        self.assertIn("GattServer::useProductionEventSink()", main)

    def test_android_filter_and_target_prefix_share_exact_bytes(self):
        android = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/blewake/BleWakeContract.kt"
        ).read_text(encoding="utf-8")
        header = (ROOT / "include" / "GattProtocol.h").read_text(encoding="utf-8")
        self.assertIn('TARGET_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"', android)
        for token in ("0x02", "0x15", "0xA1", "0xB2", "0x90"):
            self.assertIn(token, header)


if __name__ == "__main__":
    unittest.main()
