from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCANNER = (
    ROOT / "gatekeeper_app" / "lib" / "services" / "ble_scanner.dart"
).read_text(encoding="utf-8")
RECOVERY = (
    ROOT / "gatekeeper_app" / "lib" / "services" / "ranging_recovery.dart"
).read_text(encoding="utf-8")
PLUGIN = (
    ROOT
    / "gatekeeper_app/android/app/libs/flutter_beacon_local/android/src/main/java/"
    "com/flutterbeacon/FlutterBeaconPlugin.java"
).read_text(encoding="utf-8")
WORKER_STATE = (
    ROOT
    / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
    "gatekeeper_app/gattworker/BleGattWorkerState.kt"
).read_text(encoding="utf-8")
MAIN = (ROOT / "gatekeeper_app/lib/main.dart").read_text(encoding="utf-8")


class MobileRangingOwnerRecoveryContractTest(unittest.TestCase):
    def test_active_generation_is_cleared_before_exact_subscription_cancel(self) -> None:
        handler = SCANNER.split(
            "Future<void> _handleRangingStreamError(", 1
        )[1].split("Future<void> _enterActiveMode", 1)[0]
        identity = handler.index(
            "if (!identical(_streamRanging, failedSubscription)) return;"
        )
        clear = handler.index("_streamRanging = null;")
        cancel = handler.index("await failedSubscription.cancel();")
        schedule = handler.index("_rangingRecovery.schedule(")
        self.assertLess(identity, clear)
        self.assertLess(clear, cancel)
        self.assertLess(cancel, schedule)

    def test_stream_error_delegates_to_bounded_recovery_not_direct_restart(self) -> None:
        subscription = SCANNER.split(
            "void _subscribeRangingLocked()", 1
        )[1].split("Future<void> _handleRangingStreamError", 1)[0]
        self.assertIn(
            "_handleRangingStreamError(subscription, error, stack);",
            subscription,
        )
        self.assertNotIn("_restartRanging(", subscription)

    def test_native_owner_retry_is_positive_and_single_flight(self) -> None:
        self.assertIn(
            "nativeGattLeaseRetryDelay = Duration(seconds: 1)", RECOVERY
        )
        self.assertIn("if (_timer != null) return;", RECOVERY)
        self.assertIn("_timer?.cancel();", RECOVERY)

    def test_native_mode_is_structured_before_legacy_initialization(self) -> None:
        start = SCANNER.split(
            "Future<void> startScanning({bool forceRestart = false})", 1
        )[1].split("Future<void> stopScanning()", 1)[0]
        read_owner = start.index("final ownership = await _readBleOwnershipState();")
        native_gate = start.index("if (ownership.nativeWakeAuthoritative)")
        recovery_gate = start.index(
            "if (ownership.requiresNativeWakeReconciliation)"
        )
        release_gate = start.index("if (ownership.requiresNativeWakeRelease)")
        legacy_init = start.index("await flutterBeacon.initializeScanning;")
        self.assertLess(read_owner, native_gate)
        self.assertLess(native_gate, release_gate)
        self.assertLess(release_gate, recovery_gate)
        self.assertLess(recovery_gate, legacy_init)
        self.assertIn("_enterNativeWakeIdleLocked();", start)
        self.assertIn("_enterNativeWakeRecoveryLocked(ownership);", start)

    def test_native_idle_replaces_failure_notification_without_legacy_scan(self) -> None:
        transition = SCANNER.split(
            "void _enterNativeWakeIdleLocked()", 1
        )[1].split("void _syncToUi()", 1)[0]
        notification = SCANNER.split(
            "void _syncStateAndNotify()", 1
        )[1].split("List<Region> get _rangingRegions", 1)[0]
        self.assertIn("AppErrorLogger().clearError();", transition)
        self.assertIn("_setMode(ScanMode.nativeWake);", transition)
        self.assertIn("스마트키 감지 대기", notification)
        self.assertIn("force = true;", notification)

    def test_plugin_exposes_privacy_safe_owner_state(self) -> None:
        method = PLUGIN.split('call.method.equals("getBleOwnershipState")', 1)[1]
        method = method.split('call.method.equals("initialize")', 1)[0]
        self.assertIn('"native_wake"', method)
        self.assertIn('"native_wake_recovery"', method)
        self.assertIn('"legacy_scanner"', method)
        self.assertIn('"nativeRequested"', method)
        self.assertIn('"registrationRequested"', method)
        self.assertIn('"registrationReconciled"', method)
        self.assertIn('"registrationStatus"', method)
        self.assertIn('"nativeExclusionRequired"', method)
        self.assertNotIn("credential", method.lower())
        self.assertNotIn("address", method.lower())

    def test_unreconciled_native_owner_never_starts_legacy_or_action_one(self) -> None:
        start = SCANNER.split(
            "Future<void> startScanning({bool forceRestart = false})", 1
        )[1].split("Future<void> stopScanning()", 1)[0]
        recovery = SCANNER.split(
            "Future<bool> _attemptNativeWakeReconciliationLocked()", 1
        )[1].split("void _recordNativeWakeReconciliationFailure", 1)[0]
        self.assertLess(
            start.index("if (ownership.requiresNativeWakeReconciliation)"),
            start.index("await flutterBeacon.initializeScanning;"),
        )
        self.assertIn("NativeWakeRegistrationBridge().register()", recovery)
        self.assertNotIn("_triggerPrearm", recovery)

    def test_policy_downgrade_releases_native_registration_before_legacy_owner(self):
        decision = WORKER_STATE.split("fun decision(nowEpochMs", 1)[1].split(
            "fun setLocalManualEnabled", 1
        )[0]
        release = decision.index("BleWakeRegistrar.stop(context)")
        publish_owner = decision.index(
            "coordinator.setNativeRequested(decision.newWorkerEnabled)"
        )
        self.assertLess(release, publish_owner)
        self.assertIn("nativeRequested || registrationRequested", PLUGIN)
        self.assertIn("nativeWakeRegistrationRequested()", PLUGIN)
        self.assertIn("requiresNativeWakeRelease", SCANNER)
        self.assertIn("NativeWakeRegistrationBridge().stop()", SCANNER)

    def test_fresh_start_publishes_native_registration_before_service_legacy_lease(self):
        ready = MAIN.split("if (ready) {", 1)[1].split("} else {", 1)[0]
        register = ready.index("NativeWakeRegistrationBridge().register()")
        service = ready.index("ForegroundServiceManager.startService()")
        self.assertLess(register, service)


if __name__ == "__main__":
    unittest.main()
