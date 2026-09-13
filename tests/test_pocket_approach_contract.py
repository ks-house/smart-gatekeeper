"""End-to-end source contracts for issue #134 pocket approach access."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PocketApproachContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receiver = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
            "gatekeeper_app/blewake/BleWakeScanReceiver.kt"
        ).read_text(encoding="utf-8")
        cls.entrypoint = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
            "gatekeeper_app/blewake/BleWakeNativeEntrypoint.kt"
        ).read_text(encoding="utf-8")
        cls.registrar = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
            "gatekeeper_app/blewake/BleWakeRegistrar.kt"
        ).read_text(encoding="utf-8")
        cls.worker = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
            "gatekeeper_app/gattworker/BleGattCredentialWorker.kt"
        ).read_text(encoding="utf-8")
        cls.main_activity = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
            "gatekeeper_app/MainActivity.kt"
        ).read_text(encoding="utf-8")
        cls.notifier = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
            "gatekeeper_app/gattworker/AccessResultNotifier.kt"
        ).read_text(encoding="utf-8")
        cls.home = (
            ROOT / "gatekeeper_app/lib/screens/smart_key_home_screen.dart"
        ).read_text(encoding="utf-8")
        cls.fsm_test = (ROOT / "tests/gatt_protocol_test.cpp").read_text(
            encoding="utf-8"
        )
        cls.target_main = (ROOT / "src/main.cpp").read_text(encoding="utf-8")

    def test_native_wake_routes_without_flutter_or_network_to_action_one(self):
        self.assertIn("BleWakeNativeEntrypoint.onWake(context, event)", self.receiver)
        presence = self.entrypoint.split("BleWakeDispatchAction.PRESENCE -> {", 1)[1].split(
            "BleWakeDispatchAction.IGNORE ->", 1
        )[0]
        fresh = presence.index("BleScanObservationPolicy.fresh(event.latencyMs)")
        observe = presence.index("ContinuousPresenceTracker.observe(")
        missing_hint = presence.index("BleGattWorkScheduler.onMissingReadyHint")
        ready_hint = presence.index("BleGattWorkScheduler.onContinuousPresence")
        self.assertLess(fresh, observe)
        self.assertLess(observe, missing_hint)
        self.assertLess(observe, ready_hint)
        self.assertLess(presence.index("event.readyHintMalformed"), missing_hint)
        self.assertIn("else if (hint.ready)", presence)
        self.assertNotIn(".resolve()", presence)
        dispatch = self.worker.split("private fun scheduleFreshPresence(", 1)[1].split(
            "private fun reconcilePreProofOrphan", 1
        )[0]
        self.assertLess(dispatch.index("ContinuousPresenceTracker.fresh("), dispatch.index("return onPresence("))
        self.assertIn("ContinuousPresencePolicy.missingHintBlockingReason(last, now)", dispatch)
        self.assertIn("ContinuousPresencePolicy.blockingReason(last, now)", dispatch)
        self.assertIn("requiresFreshPresence = true", dispatch)
        self.assertIn("requiresFastV2 = epoch == null", dispatch)
        self.assertNotIn("io.flutter", self.entrypoint)
        self.assertNotIn("MethodChannel", self.entrypoint)
        self.assertIn("HAS_NETWORK_CONSTRAINT = false", self.worker)
        self.assertIn("GattProtocol.ACTION_ARM_FOR_SENSOR", self.worker)
        self.assertNotIn("GattProtocol.ACTION_OPEN_IMMEDIATELY", self.worker)

    def test_native_match_lost_clears_ready_without_dispatching_access(self):
        self.assertIn("ScanSettings.CALLBACK_TYPE_FIRST_MATCH", self.registrar)
        self.assertIn("ScanSettings.CALLBACK_TYPE_MATCH_LOST", self.registrar)
        exit_branch = self.entrypoint.split("BleWakeDispatchAction.EXIT -> {", 1)[1].split(
            "BleWakeDispatchAction.PRESENCE -> {", 1
        )[0]
        self.assertIn("AccessResultNotifier.dismiss", exit_branch)
        self.assertIn("ContinuousPresenceTracker.exit(event.deviceAddress, lostAt)", exit_branch)
        self.assertNotIn("BleGattWorkScheduler.", exit_branch)

    def test_access_ready_notification_is_bounded_and_terminally_dismissed(self):
        self.assertIn("ACCESS_READY_TIMEOUT_MS = 65_000L", self.notifier)
        self.assertIn("builder::setTimeoutAfter", self.notifier)
        dismiss = self.notifier.split("fun dismiss(context: Context)", 1)[1]
        self.assertIn("ACCESS_READY_NOTIFICATION_ID", dismiss)
        self.assertNotIn("ATTENTION_NOTIFICATION_ID", dismiss)
        finish = self.home.split(
            "void _finishAccessSessionPolling(String targetSessionId)", 1
        )[1].split("void _stopAccessSessionPolling()", 1)[0]
        self.assertIn("dismissAccessReadyNotification", finish)

    def test_enablement_registers_os_wake_and_disable_stops_it(self):
        control = self.main_activity.split('"setLocalGattEnabled" -> {', 1)[1].split(
            '"prepareLocalGattEnrollment" -> {', 1
        )[0]
        self.assertIn("BleWakeRegistrar.register(applicationContext)", control)
        self.assertIn("BleWakeRegistrar.stop(applicationContext)", control)
        self.assertIn('"wakeRegistrationStatus"', control)
        self.assertIn('"wakeRegistered"', control)

    def test_initial_dispatch_is_expedited_and_stale_presence_fails_closed(self):
        self.assertIn("OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST", self.worker)
        self.assertIn("HandsFreeDispatchPolicy.shouldExpedite", self.worker)
        self.assertIn("HandsFreeDispatchPolicy.isFresh", self.worker)
        self.assertIn("AccessReasonCode.PRESENCE_EXPIRED", self.worker)
        self.assertIn('"PRESENCE_AGE_EXCEEDED"', self.worker)
        run = self.worker.split("private suspend fun runSession()", 1)[1]
        self.assertLess(
            run.index("initial.requiresFreshPresence && !ContinuousPresenceTracker.fresh("),
            run.index("transport = AndroidBleGattTransport("),
        )
        self.assertLess(
            run.index("!configuredCredential.contentEquals(secret.credentialId)"),
            run.index("transport = AndroidBleGattTransport("),
        )
        proof = run.split("override fun beforeProofWrite()", 1)[1].split(").run(", 1)[0]
        self.assertLess(proof.index("ContinuousPresenceTracker.fresh("), proof.index("ledgerUpdateUncertain("))
        self.assertLess(proof.index("decision().newWorkerEnabled"), proof.index("ledgerUpdateUncertain("))
        self.assertIn("requireFastV2 = initial.requiresFastV2", run)
        self.assertIn("outcome.proofMayHaveExecuted && outcome.targetReason == null", run)
        self.assertIn("DurableSessionState.PROOF_UNCERTAIN", run)

    def test_target_remains_relay_off_until_ultrasonic_trigger(self):
        flow = self.fsm_test.split(
            "// Auth proof flow: IDLE -> AUTH_PENDING -> ARMED -> SENSOR -> RELAY_HOLD",
            1,
        )[1].split("// Interlock check", 1)[0]
        armed = flow.index("CHECK(fsm.state() == GateState::ARMED);")
        relay_off = flow.index("CHECK(!fsm.isRelayOn());", armed)
        sensor = flow.index("CHECK(fsm.handleSensorTrigger", relay_off)
        relay_on = flow.index("CHECK(fsm.isRelayOn());", sensor)
        self.assertLess(armed, relay_off)
        self.assertLess(relay_off, sensor)
        self.assertLess(sensor, relay_on)
        armed_source = self.target_main.split(
            "if (g_access_fsm.state() == GateState::ARMED) {", 1
        )[1].split("} else if (g_access_fsm.state() == GateState::IDLE", 1)[0]
        self.assertIn("const uint16_t median_mm = measuredMillimeters(distCm)", armed_source)
        self.assertIn("const uint16_t threshold_mm = g_distance_threshold_cm * 10", armed_source)
        guard = "median_mm != sgk::kNoSensorMeasurement && median_mm <= threshold_mm && !blocked"
        self.assertLess(armed_source.index(guard), armed_source.index("g_access_fsm.handleSensorTrigger"))


if __name__ == "__main__":
    unittest.main()
