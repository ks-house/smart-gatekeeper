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

    def test_nimble_callbacks_defer_large_event_and_fragment_work(self):
        adapter = (ROOT / "src" / "GattServer.cpp").read_text(encoding="utf-8")
        self.assertIn("class DeferredCanonicalEventSink", adapter)
        self.assertIn("class ProductionLifecycleEventSink", adapter)
        self.assertIn(
            "production_lifecycle_bridge(\n    &production_lifecycle_sink)", adapter
        )
        self.assertGreaterEqual(adapter.count("deferred_event_sink.drain();"), 2)
        self.assertGreaterEqual(
            adapter.count("production_lifecycle_sink.drainControls();"), 2
        )
        update_handler = adapter.split("void GattServer::update()", 1)[1].split(
            "bool GattServer::isEnabled()", 1
        )[0]
        self.assertLess(
            update_handler.rindex("deferred_event_sink.drain();"),
            update_handler.rindex("drainOutputs();"),
        )

        indication_handler = adapter.split(
            "void GattServer::handleIndicationStatus(const sgk::IndicationToken& token,",
            1,
        )[1].split("void GattServer::createService()", 1)[0]
        self.assertNotIn("drainOutputs();", indication_handler)
        self.assertIn("update() drains the next", indication_handler)

        callback_section = adapter.split(
            "class ServerCallbacks final", 1
        )[1].split("class WriteCallbacks final", 1)[0]
        self.assertNotIn("BLEDevice::startAdvertising();", callback_section)
        self.assertGreaterEqual(callback_section.count("requestAdvertisingRestart();"), 2)

        canonical_sink = adapter.split(
            "class CanonicalMqttEventSink final", 1
        )[1].split("CanonicalMqttEventSink production_event_sink", 1)[0]
        self.assertNotIn("s_auth_pending_callback", canonical_sink)
        self.assertNotIn("s_auth_grant_callback", canonical_sink)
        self.assertNotIn("s_auth_abort_callback", canonical_sink)
        lifecycle_sink = adapter.split(
            "class ProductionLifecycleEventSink final", 1
        )[1].split("ProductionLifecycleEventSink production_lifecycle_sink", 1)[0]
        self.assertIn("abort_pending_ = true", lifecycle_sink)
        control_gate = adapter.split(
            "class ProductionAuthControlGate final", 1
        )[1].split("ProductionAuthControlGate production_auth_control_gate", 1)[0]
        self.assertIn("s_auth_pending_callback", control_gate)
        self.assertIn("s_auth_grant_callback", control_gate)
        self.assertIn("production_lifecycle_sink.requestAbort", control_gate)

    def test_idle_advertiser_is_observed_restarted_and_reported(self):
        adapter = (ROOT / "src" / "GattServer.cpp").read_text(
            encoding="utf-8"
        )
        header = (ROOT / "include" / "GattServer.h").read_text(
            encoding="utf-8"
        )
        main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
        mqtt = (ROOT / "src" / "MqttManager.cpp").read_text(
            encoding="utf-8"
        )

        self.assertIn("advertising->isAdvertising()", adapter)
        self.assertIn('restartAdvertising("watchdog", true)', adapter)
        self.assertIn('restartAdvertising("disconnect", false)', adapter)
        self.assertIn("kAdvertisingHealthCheckIntervalMs = 2000", adapter)
        watchdog = adapter.split("void serviceAdvertisingHealth", 1)[1].split(
            "class ServerCallbacks", 1
        )[0]
        self.assertIn("controllerHasActiveConnection()", watchdog)
        self.assertIn("ble_server->getConnectedCount()", adapter)
        self.assertIn("advertising->start()", adapter)
        self.assertIn("advertising_restart_failures", header)
        self.assertIn("GattServer::setAdvertisingExpected(true);", main)
        for field in (
            "ble_advertising_expected",
            "ble_advertising_active",
            "ble_active_connections",
            "ble_advertising_restart_attempts",
            "ble_advertising_restart_successes",
            "ble_advertising_restart_failures",
            "ble_advertising_watchdog_recoveries",
            "acl_active",
            "acl_version",
            "acl_min_protocol",
            "acl_max_protocol",
        ):
            self.assertIn(f'doc["{field}"]', mqtt)

    def test_verified_lifecycle_isolated_from_interleaved_unverified_sessions(self):
        shared = (ROOT / "include" / "GattProtocol.h").read_text(
            encoding="utf-8"
        )
        protocol = (ROOT / "src" / "GattProtocol.cpp").read_text(
            encoding="utf-8"
        )
        adapter_header = (ROOT / "include" / "GattServer.h").read_text(
            encoding="utf-8"
        )
        adapter = (ROOT / "src" / "GattServer.cpp").read_text(
            encoding="utf-8"
        )
        main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")

        self.assertIn("sequence_high_water_", shared)
        self.assertIn("verified_causation_sequence_", shared)
        self.assertIn("VerifiedAccessPhaseTracker", shared)
        self.assertIn(
            "sequence_high_water_ = std::max(sequence_high_water_, event.sequence)",
            protocol,
        )
        clear = protocol.split(
            "void LocalGattLifecycleBridge::clearVerifiedSession()", 1
        )[1].split("bool VerifiedAccessPhaseTracker::observe", 1)[0]
        self.assertNotIn("sequence_high_water_ = 0", clear)
        self.assertIn("verified_causation_sequence_ = 0", clear)

        canonical_sink = adapter.split(
            "class CanonicalMqttEventSink final", 1
        )[1].split("CanonicalMqttEventSink production_event_sink", 1)[0]
        self.assertIn("phase_tracker_.observe(event", canonical_sink)
        self.assertIn("if (verified_terminal)", canonical_sink)
        self.assertNotIn("void updatePhase", canonical_sink)
        self.assertIn("SESSION_SUPERSEDED", canonical_sink)
        self.assertIn(
            "event.reason == sgk::EventReason::kRelayFailsafeCutoff",
            canonical_sink,
        )
        self.assertIn(
            'document["reason_code"] = "RELAY_CONTROL_ERROR"', canonical_sink
        )
        self.assertNotIn("supersedeVerifiedSession", adapter_header)
        self.assertNotIn("supersedeVerifiedSession", adapter)
        self.assertNotIn("supersedeVerifiedSession", main)
        for name, next_name in (
            ("notifyAccessArmed", "notifySensorDetected"),
            ("notifySensorDetected", "notifyRelayOn"),
            ("notifyRelayOn", "notifyRelayOff"),
            ("notifyRelayOff", "notifySessionCompleted"),
            ("notifySessionCompleted", "notifySessionTerminated"),
            ("notifySessionTerminated", "Telemetry GattServer::getTelemetry"),
        ):
            notification = adapter.split(
                f"void GattServer::{name}", 1
            )[1].split(f"GattServer::{next_name}", 1)[0]
            self.assertIn("core_mutex.lock();", notification)
            self.assertIn("core_mutex.unlock();", notification)

    def test_access_actor_ref_is_pseudonymous_durable_v2_only(self):
        shared = (ROOT / "include" / "GattProtocol.h").read_text(
            encoding="utf-8"
        )
        protocol = (ROOT / "src" / "GattProtocol.cpp").read_text(
            encoding="utf-8"
        )
        adapter = (ROOT / "src" / "GattServer.cpp").read_text(
            encoding="utf-8"
        )
        queue_header = (ROOT / "include" / "OfflineEventQueue.h").read_text(
            encoding="utf-8"
        )
        queue = (ROOT / "src" / "OfflineEventQueue.cpp").read_text(
            encoding="utf-8"
        )
        mqtt = (ROOT / "src" / "MqttManager.cpp").read_text(
            encoding="utf-8"
        )
        config = (ROOT / "include" / "config.h").read_text(encoding="utf-8")
        secret_template = (ROOT / "include" / "secrets.h.example").read_text(
            encoding="utf-8"
        )

        self.assertIn("std::array<uint8_t, 16> credential_id{}", shared)
        self.assertIn('"SGK-CREDENTIAL-REF-V1"', protocol)
        self.assertIn('"SGK-ACCESS-EVENT-MAC-V1"', protocol)
        self.assertIn('"SGK-ACCESS-STATUS-MAC-V1"', protocol)
        self.assertIn("sizeof(kAccessEventCredentialRefDomain)", protocol)
        self.assertIn("buildAccessEventMacInput", protocol)
        self.assertIn("buildAccessStatusMacInput", protocol)
        self.assertIn("deriveAccessEventMac", protocol)
        self.assertIn("deriveAccessStatusMac", protocol)
        self.assertIn("normalized_session[6]", protocol)
        self.assertIn("normalized_session[8]", protocol)
        self.assertIn('"c_%s_%s"', protocol)
        self.assertIn("&request.credential_id", protocol)
        self.assertIn("secureZeroBytes(credential_id_.data()", protocol)
        self.assertIn("void secureZeroBytes", protocol)
        self.assertIn("volatile uint8_t* cursor", protocol)
        self.assertIn("secureZeroBytes(&request, sizeof(request))", protocol)
        self.assertIn("secureZeroBytes(complete.data(), complete.size())", protocol)
        self.assertIn("secureZeroBytes(pending_writes_.data()", protocol)

        self.assertIn("SECRET_ACCESS_EVENT_REF_KEY_HEX", config)
        self.assertIn("SECRET_ACCESS_EVENT_REF_KEY_ID", config)
        self.assertIn("SECRET_ACCESS_EVENT_REF_KEY_HEX", secret_template)
        self.assertIn("SECRET_ACCESS_EVENT_REF_KEY_ID", secret_template)
        self.assertIn("parseAccessEvidenceProvisioning", adapter)
        self.assertIn("accessEventCodeAllowsCredentialRef(event.code)", adapter)
        self.assertIn("deriveAccessEventMac", adapter)
        self.assertIn("MqttManager::noteAccessTerminal", adapter)
        self.assertIn("setCanonicalV2Detail", adapter)
        self.assertIn("secureZeroEventCredential(&event)", adapter)
        self.assertIn("secureZeroPendingWrite(&pending)", adapter)
        self.assertNotIn('document["credential_id"]', adapter)
        self.assertNotIn('attributes["credential_id"]', adapter)

        self.assertIn("char detail[64]", queue_header)
        self.assertNotIn("credential_id", queue_header)
        self.assertIn("offsetof(CanonicalEvent, detail) == 297", queue_header)
        self.assertIn("offsetof(CanonicalEvent, padding) == 362", queue_header)
        self.assertIn("sizeof(CanonicalEvent) == 368", queue_header)
        self.assertIn("kCanonicalV2AuthTagOffset = 42", queue_header)
        self.assertIn("kCanonicalV2CredentialDigestOffset = 30", queue_header)
        self.assertIn("kCanonicalV2OverlayMarker", queue_header)
        self.assertIn("evt.schema_version == kCanonicalEventSchemaV1 ||", queue)
        self.assertIn("evt.schema_version == kCanonicalEventSchemaV2", queue)
        self.assertIn(
            "durable.schema_version = kCanonicalEventSchemaV1", queue
        )
        self.assertIn("durable.padding = kCanonicalV2OverlayMarker", queue)
        self.assertIn("runtime_evt.schema_version = kCanonicalEventSchemaV2", queue)

        self.assertIn("canonicalEventAccessAuth", mqtt)
        self.assertIn("isValidCanonicalEventRecord(event)", mqtt)
        self.assertIn('attributes["credential_ref"] = credential_ref', mqtt)
        self.assertIn('doc["schema_version"] = authenticated ? "1.1" : "1.0"', mqtt)
        self.assertIn('doc["access_status_revision"]', mqtt)
        self.assertIn('createNestedObject("access_auth")', mqtt)
        self.assertIn("deriveAccessStatusMac", mqtt)
        self.assertNotIn('attributes["credential_id"]', mqtt)

    def test_authenticated_action_commit_is_not_run_under_a_spinlock(self):
        adapter = (ROOT / "src" / "GattServer.cpp").read_text(encoding="utf-8")
        update_handler = adapter.split("void GattServer::update()", 1)[1].split(
            "bool GattServer::isEnabled()", 1
        )[0]

        # processProof synchronously commits the action to the application FSM.
        # That path reaches GPIO, esp_timer, diagnostics and LOGF, so a FreeRTOS
        # critical section here aborts newlib's recursive stdout lock on target.
        self.assertIn("std::recursive_mutex core_mutex;", adapter)
        self.assertNotIn("portENTER_CRITICAL(&core_mux)", adapter)
        self.assertIn("core_mutex.lock();", update_handler)
        self.assertIn("core->receiveFrame", update_handler)
        self.assertIn("core_mutex.unlock();", update_handler)

    def test_android_challenge_uses_only_the_subscribed_indication_stream(self):
        transport = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/AndroidBleGattTransport.kt"
        ).read_text(encoding="utf-8")
        challenge = transport.split(
            "override suspend fun readChallenge(): ByteArray {", 1
        )[1].split("override suspend fun writeProof", 1)[0]
        self.assertIn("GattProtocol.FAST_CHALLENGE", challenge)
        self.assertIn("GattProtocol.CHALLENGE", challenge)
        self.assertNotIn("readCharacteristic", challenge)

    def test_v2_fast_path_uses_one_cccd_and_never_falls_back_after_selection(self):
        transport = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/AndroidBleGattTransport.kt"
        ).read_text(encoding="utf-8")
        engine = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/GattSessionEngine.kt"
        ).read_text(encoding="utf-8")
        protocol = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/GattProtocol.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("enableIndication(GattProtocol.FAST_TX_UUID)", transport)
        self.assertIn("protocolMode == GattProtocolMode.FAST_V2", transport)
        self.assertIn("v1 negotiation is not available after v2 selection", transport)
        self.assertIn("selectGattProtocolMode(fastRxPresent, fastTxPresent)", transport)
        self.assertIn("partial v2 service is invalid", protocol)
        self.assertIn("transport.protocolMode == GattProtocolMode.FAST_V2", engine)
        self.assertIn("negotiationMs = 0", engine)

    def test_android_gatt_latency_hints_fall_back_and_remain_observable(self):
        transport = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/AndroidBleGattTransport.kt"
        ).read_text(encoding="utf-8")
        engine = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/gattworker/GattSessionEngine.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("requestConnectionPriority", transport)
        self.assertIn("BluetoothGatt.CONNECTION_PRIORITY_HIGH", transport)
        self.assertIn("requestMtu(DESIRED_MTU)", transport)
        self.assertIn("MTU_NEGOTIATION_WAIT_MS = 750L", transport)
        self.assertIn("DEFAULT_MTU = 23", transport)
        self.assertIn("GattSessionPerformance", engine)
        for phase in (
            "connectSetupMs",
            "negotiationMs",
            "challengeMs",
            "signingMs",
            "proofWriteMs",
            "resultWaitMs",
        ):
            self.assertIn(phase, engine)

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
            ota.index("WiFiClientSecure otaClient"),
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
        self.assertIn("queued_evt.sequence = event.sequence", adapter)
        self.assertIn("mac_input.sequence = event.sequence", adapter)
        self.assertIn("mac_input.has_causation = causal", adapter)
        self.assertIn("queued_evt.causation_event_id", adapter)
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
