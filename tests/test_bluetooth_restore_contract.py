"""Source contract for issue #179 Bluetooth ON wake registration recovery."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BluetoothRestoreContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = (
            ROOT / "gatekeeper_app/android/app/src/main/AndroidManifest.xml"
        ).read_text(encoding="utf-8")
        cls.application = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
            "gatekeeper_app/GatekeeperApplication.kt"
        ).read_text(encoding="utf-8")
        cls.monitor = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
            "gatekeeper_app/blewake/BleWakeBluetoothStateMonitor.kt"
        ).read_text(encoding="utf-8")
        cls.registrar = (
            ROOT
            / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/"
            "gatekeeper_app/blewake/BleWakeRegistrar.kt"
        ).read_text(encoding="utf-8")

    def test_native_application_owns_process_lifetime_state_monitor(self):
        self.assertIn('android:name=".GatekeeperApplication"', self.manifest)
        self.assertNotIn("android.bluetooth.adapter.action.STATE_CHANGED", self.manifest)
        self.assertIn("BleWakeBluetoothStateMonitor.start(this)", self.application)
        self.assertNotIn("io.flutter", self.monitor)
        self.assertNotIn("MethodChannel", self.monitor)

    def test_state_on_restores_registration_without_dispatching_access(self):
        self.assertIn("BluetoothAdapter.ACTION_STATE_CHANGED", self.monitor)
        self.assertIn("newState == BluetoothAdapter.STATE_ON", self.monitor)
        self.assertIn("previousObservedState != BluetoothAdapter.STATE_ON", self.monitor)
        self.assertIn("BleWakeRegistrar.register(context)", self.monitor)
        self.assertNotIn("BleWakeNativeEntrypoint", self.monitor)
        self.assertNotIn("BleGattWorkScheduler", self.monitor)

    def test_requested_state_and_disable_semantics_are_durable(self):
        register = self.registrar.split("fun register", 1)[1].split("fun stop", 1)[0]
        stop = self.registrar.split("fun stop", 1)[1].split("fun isEnabled", 1)[0]
        self.assertLess(register.index("setEnabled(context, true)"), register.index("missingPermission"))
        self.assertLess(stop.index("setEnabled(context, false)"), stop.index("bluetoothLeScanner"))
        self.assertIn("scanner.stopScan(callbackIntent)", register)
        self.assertIn("scanner.startScan", register)


if __name__ == "__main__":
    unittest.main()
