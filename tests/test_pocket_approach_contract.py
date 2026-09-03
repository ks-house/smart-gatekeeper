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
        self.assertIn("BleGattWorkScheduler.onPresence", self.entrypoint)
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
        self.assertNotIn("BleGattWorkScheduler.onPresence", exit_branch)

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
        self.assertIn("if (g_access_fsm.state() == GateState::ARMED)", self.target_main)
        self.assertIn("distCm <= (float)g_distance_threshold_cm", self.target_main)
        self.assertIn("g_access_fsm.handleSensorTrigger", self.target_main)


if __name__ == "__main__":
    unittest.main()
