"""Build and execute the same C++ protocol core used by the ESP32 BLE adapter."""

import sys
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HardwarelessRcProductionCoreTest(unittest.TestCase):
    def test_personal_production_enables_transport_with_fail_closed_default(self):
        platformio = (ROOT / "platformio.ini").read_text(encoding="utf-8")
        commercial = platformio.split("[env:esp32c6_production]", 1)[1].split(
            "[env:esp32c6_personal_production]", 1
        )[0]
        production = platformio.split(
            "[env:esp32c6_personal_production]", 1
        )[1].split(
            "[env:esp32c6_hwless_rc]", 1
        )[0]
        config = (ROOT / "include" / "config.h").read_text(encoding="utf-8")
        protocol = (ROOT / "include" / "GattProtocol.h").read_text(
            encoding="utf-8"
        )
        main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")

        self.assertNotIn("-DENABLE_HARDWARELESS_RC=1", commercial)
        self.assertIn("-DSGK_PRODUCTION_BUILD=1", production)
        self.assertIn("-DENABLE_HARDWARELESS_RC=0", production)
        self.assertIn("-DENABLE_HARDWARELESS_RC=1", production)
        self.assertIn("-DSGK_PERSONAL_INSTALLATION_BUILD=1", production)
        self.assertIn("Commercial production firmware must compile", config)
        self.assertIn("hardwarelessRuntimeDefaultEnabled", protocol)
        self.assertIn(
            "shouldInitializePersonalHardwarelessState", protocol
        )
        self.assertIn("(SGK_PRODUCTION_BUILD != 0)", protocol)
        self.assertIn("(SGK_PERSONAL_INSTALLATION_BUILD != 0)", protocol)
        self.assertIn("sgk::hardwarelessRuntimeDefaultEnabled()", main)
        self.assertIn("const bool hwlessActive = GattServer::isEnabled()", main)
        self.assertIn("hwlessActive ? \"ENABLED\" : \"DISABLED\"", main)

    def test_personal_profile_migrates_stale_compile_off_false_once(self):
        config = (ROOT / "src" / "ConfigManager.cpp").read_text(
            encoding="utf-8"
        )
        protocol = (ROOT / "include" / "GattProtocol.h").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "personal_runtime_default && !migration_complete &&",
            protocol,
        )
        self.assertIn('preferences.getBool("hwless_p1", false)', config)
        self.assertIn("getHardwarelessDoorId(&doorId)", config)
        self.assertIn("isValidAclSignerPublicKeyHex", config)
        self.assertIn("getAclSigningKeyId() != 0", config)
        enable_write = config.index('preferences.putBool("hwless_rc", true)')
        marker_write = config.index('preferences.putBool("hwless_p1", true)')
        self.assertLess(enable_write, marker_write)
        self.assertIn('preferences.remove("hwless_p1")', config)
        self.assertIn('preferences.putBool("hwless_rc", false)', config)

    def test_production_enablement_preserves_fail_closed_authorization(self):
        adapter = (ROOT / "src" / "GattServer.cpp").read_text(encoding="utf-8")
        verifier = (ROOT / "src" / "TargetProofVerifier.cpp").read_text(
            encoding="utf-8"
        )
        acl = (ROOT / "src" / "TargetAclManager.cpp").read_text(
            encoding="utf-8"
        )
        main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")

        self.assertIn(
            "sgk::FailClosedProofVerifier fail_closed_verifier", adapter
        )
        self.assertIn(
            "if (!ConfigManager::getHardwarelessDoorId(&door_id))", adapter
        )
        self.assertIn("requested_enabled = false", adapter)
        self.assertIn("if (!acl_manager_.hasActiveAcl())", verifier)
        self.assertIn("ResultReason::kAclUnavailable", verifier)
        self.assertIn("!signer_set_", acl)
        self.assertIn("expected_signing_key_id_ == 0", acl)
        self.assertIn(
            "g_acl_manager.setExpectedSigningKeyId(expectedKeyId)", main
        )
        self.assertIn("g_acl_manager.setSignerPublicKey(signer_pubkey)", main)

    def test_production_cpp_core(self):
        compiler = shutil.which("g++")
        if compiler is None:
            compiler = str(
                Path.home()
                / ".platformio/packages/toolchain-gccmingw32/bin/g++.exe"
            )
        self.assertTrue(Path(compiler).is_file(), "native g++ compiler is required")
        import uuid
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / f"gatt_protocol_test_{uuid.uuid4().hex}.exe"
            cmd = [
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
                "src/TargetAclManager.cpp",
                "src/TargetProofVerifier.cpp",
                "src/TargetAccessFsm.cpp",
                "src/OfflineEventQueue.cpp",
                "src/TargetCommandSecurity.cpp",
                "src/OtaVersionPolicy.cpp",
                "tests/gatt_protocol_test.cpp",
                "-o",
                str(executable),
            ]
            compile_result = subprocess.run(
                cmd,
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
        self.assertIn("IndicationToken", shared)
        self.assertIn("output_generation", shared)
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
        self.assertIn("!OtaManager::isSafeForOta()", ota)
        self.assertIn("bool waitForSafeState()", ota)
        self.assertIn("GattServer::flushOtaBusy", ota)
        self.assertLess(
            ota.index("status = OtaStatus::WAIT_SAFE_STATE"),
            ota.index("if (!waitForSafeState())"),
        )
        self.assertLess(
            ota.index("if (!waitForSafeState())"),
            ota.index("if (!WifiManager::isConnected())"),
        )
        self.assertLess(
            ota.index("if (!WifiManager::isConnected())"),
            ota.index("WiFiClientSecure manifestClient"),
        )
        self.assertTrue(
            "g_access_fsm.otaSafeState()" in main or
            "classifyOtaSafeState(state, is_armed, relay.isOn())" in main
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
        self.assertIn(
            "selected_event_sink == &production_lifecycle_bridge", adapter
        )
        self.assertIn("production_event_sink.configure(door_id)", adapter)
        self.assertIn("GattServer::useProductionEventSink()", main)

    def test_android_filter_and_target_prefix_share_exact_bytes(self):
        android = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/blewake/BleWakeContract.kt"
        ).read_text(encoding="utf-8")
        header = (ROOT / "include" / "GattProtocol.h").read_text(encoding="utf-8")
        main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
        self.assertIn('TARGET_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"', android)
        # The pinned pioarduino BLEBeacon setter swaps this argument before
        # serializing its packed struct.  0x4C00 therefore emits the standard
        # little-endian Apple company bytes 4C 00 consumed by Android's
        # manufacturer ID 0x004C filter.  Passing 0x004C emits 00 4C instead.
        self.assertIn("setManufacturerId(0x4C00)", main)
        self.assertNotIn("setManufacturerId(0x004C)", main)
        for token in ("0x02", "0x15", "0xA1", "0xB2", "0x90"):
            self.assertIn(token, header)


if __name__ == "__main__":
    unittest.main()
