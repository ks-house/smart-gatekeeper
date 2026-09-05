from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FieldDiagnosticsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gatt = (ROOT / "src" / "GattServer.cpp").read_text(encoding="utf-8")
        cls.mqtt = (ROOT / "src" / "MqttManager.cpp").read_text(encoding="utf-8")
        cls.diag = (ROOT / "src" / "DiagnosticsManager.cpp").read_text(
            encoding="utf-8"
        )

    def test_gatt_callbacks_only_update_local_diagnostics(self) -> None:
        for function in ("handleConnect", "handleDisconnect", "handleWrite"):
            body = self.gatt.split(f"GattServer::{function}", 1)[1].split("\n}\n", 1)[0]
            self.assertNotIn("client.publish", body)
            self.assertNotIn("MqttManager::publish", body)
        self.assertIn('noteDiagnosticStage("PROOF_FRAME_RECEIVED"', self.gatt)

    def test_retained_status_has_bounded_stage_highwater(self) -> None:
        for field in (
            'doc["gatt_accepted_connections"]',
            'doc["gatt_challenges_issued"]',
            'doc["gatt_proofs_verified"]',
            'doc["gatt_results_indicated"]',
            'doc["gatt_armed_entries"]',
            'doc["gatt_sensor_detections"]',
            'doc["gatt_relay_on_count"]',
            'doc["gatt_terminal_count"]',
            'doc["gatt_last_stage"]',
        ):
            self.assertIn(field, self.mqtt)

    def test_access_reset_breadcrumb_is_separate_from_existing_version_one(self) -> None:
        self.assertIn("struct RtcAccessBreadcrumb", self.diag)
        self.assertIn("RTC_NOINIT_ATTR RtcAccessBreadcrumb", self.diag)
        self.assertIn("constexpr uint16_t kBreadcrumbVersion = 1", self.diag)
        self.assertIn("previous_access_stage", self.mqtt)


if __name__ == "__main__":
    unittest.main()
