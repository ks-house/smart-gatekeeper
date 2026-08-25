from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCANNER = (
    ROOT / "gatekeeper_app" / "lib" / "services" / "ble_scanner.dart"
).read_text(encoding="utf-8")
RECOVERY = (
    ROOT / "gatekeeper_app" / "lib" / "services" / "ranging_recovery.dart"
).read_text(encoding="utf-8")


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


if __name__ == "__main__":
    unittest.main()
