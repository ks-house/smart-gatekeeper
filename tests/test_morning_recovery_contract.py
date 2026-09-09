"""Cross-layer compatibility and independent scan recovery wiring."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BLE = ROOT / "gatekeeper_app/android/app/src/main/kotlin/com/kshouse/gatekeeper_app/blewake"


class MorningRecoveryContractTest(unittest.TestCase):
    def test_busy_reasons_are_supported_by_existing_event_receiver(self):
        catalog = json.loads((ROOT / "observability/event_codes_v1.json").read_text())
        text = json.dumps(catalog)
        self.assertIn('"TARGET_BUSY"', text)
        self.assertIn('"OTA_BUSY"', text)
        source = (ROOT / "src/GattServer.cpp").read_text()
        self.assertIn('event.reason == sgk::EventReason::kOtaBusy', source)
        self.assertIn('? "OTA_BUSY" : reasonCode(event.transport_reason)', source)
        self.assertIn('case sgk::ResultReason::kBusy:\n        return "TARGET_BUSY";', source)

    def test_watchdog_does_not_restore_disabled_or_active_proof(self):
        source = (BLE / "BleWakeReconciliationWorker.kt").read_text()
        watchdog = source.split('class BleScanWatchdogWorker', 1)[1].split('/**', 1)[0]
        self.assertIn('BleWakeRegistrar.isEnabled', watchdog)
        self.assertIn('decision().newWorkerEnabled', watchdog)
        for state in ('QUEUED', 'RUNNING', 'RETRY_PENDING', 'PROOF_UNCERTAIN'):
            self.assertIn('DurableSessionState.' + state, watchdog)
        self.assertNotIn('NativeDiagnostics', watchdog)
        self.assertIn('ExistingPeriodicWorkPolicy.KEEP', source)
        self.assertIn('setInitialDelay(15, TimeUnit.MINUTES)', source)
        registrar = (BLE / "BleWakeRegistrar.kt").read_text()
        self.assertIn('BleScanRecoveryPolicy.shouldRefresh', registrar)
        self.assertIn('BleWakeReconciliationScheduler.cancelWatchdog(context)', registrar)


if __name__ == '__main__':
    unittest.main()
