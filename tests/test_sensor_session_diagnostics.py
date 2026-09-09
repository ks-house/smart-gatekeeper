"""Session sensor evidence is frozen, signed, and independently durable."""
import hashlib
import hmac
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SensorSessionDiagnosticsTest(unittest.TestCase):
    def test_host_tracker_storage_and_cross_language_mac(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "sensor-session")
            result = subprocess.run([
                "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
                "tests/sensor_session_diagnostics_test.cpp", "src/SensorSessionDiagnostics.cpp",
                "src/OfflineEventQueue.cpp", "src/GattProtocol.cpp", "-o", executable,
            ], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([executable], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        fields = [
            "SGK-SENSOR-SESSION-MAC-V1", "a1", "target-1",
            "00112233445566778899aabbccddeeff", "782",
            "00000000-0000-4000-8000-000000000002", "9",
            "1000", "61000", "500", "4", "2", "1", "1", "1", "3", "1",
            "300", "900", "900", "700", "1", "0", "CLEAR",
        ]
        expected = hmac.new(bytes(range(1, 33)), "\n".join(fields).encode(), hashlib.sha256).hexdigest()[:32]
        self.assertIn("tag=" + expected, result.stdout)

    def test_sensor_summary_outbox_and_receipts_do_not_authorize_door(self):
        source = (ROOT / "src/MqttManager.cpp").read_text()
        receiver = source.split("bool consumeDiagnosticReceipt(", 1)[1].split(
            "class NvsCommandReplayStorage", 1)[0]
        self.assertIn("verifySensorSessionReceipt", receiver)
        self.assertIn("sensorSummaryQueue.pop()", receiver)
        self.assertIn("hasExactUniqueFlatJsonFields", receiver)
        self.assertNotIn("triggerArm", receiver)
        self.assertNotIn("triggerManualDoorOpen", receiver)
        self.assertNotIn("commandSecurity.", receiver)
        self.assertIn('"sgk_sense"', source)
        self.assertIn('"sensor_session_summary"', source)

    def test_status_payload_budget_with_full_sensor_summary(self):
        """Conservative wire-size envelope, not a physical runtime heap claim."""
        source = (ROOT / "src/MqttManager.cpp").read_text()
        body = source.split("void MqttManager::publishTelemetry(", 1)[1].split(
            "void MqttManager::publishEvent(", 1)[0]
        # Every counter (including bools/small enums) takes ten digits here.
        # Closed identifier/reason strings use their bounded maximum lengths.
        status = {key: 0xFFFFFFFF for key in re.findall(r'doc\["([^"]+)"\]', body)}
        strings = {
            "state": 12, "ip": 15, "firmware": 64, "target_id": 48,
            "boot_id": 32, "reset_reason": 24, "last_terminal_session_id": 36,
            "last_terminal_event_code": 32, "last_terminal_reason_code": 32,
            "last_terminal_credential_ref": 31, "wifi_bssid": 17,
            "wifi_recovery_phase": 32, "gatt_last_stage": 23,
            "gatt_last_session_id": 36, "previous_access_stage": 23,
            "previous_access_session_id": 36, "sensor_clearance_state": 8,
        }
        for key, length in strings.items():
            self.assertIn(key, status)
            status[key] = "x" * length
        for key in ("boot_count", "access_status_revision", "last_terminal_event_sequence", "acl_version"):
            status[key] = 0xFFFFFFFFFFFFFFFF
        status["access_auth"] = {"version": 1, "key_id": "aaaa", "tag": "a" * 32}
        summary = {key: 0xFFFFFFFF for key in re.findall(r'summary\["([^"]+)"\]', body)}
        summary.update(
            session_id="a" * 36, source_boot_id="a" * 32,
            source_boot_count=str(0xFFFFFFFFFFFFFFFF), terminal_sequence=str(0xFFFFFFFFFFFFFFFF),
            started_monotonic_ms=str(0xFFFFFFFF), ended_monotonic_ms=str(0xFFFFFFFF),
            clearance_state="OCCUPIED",
        )
        for key in ("min_raw_mm", "max_raw_mm", "last_raw_mm", "last_median_mm"):
            summary[key] = 4000
        status["sensor_session_summary"] = summary
        status["sensor_summary_auth"] = {"version": 1, "key_id": "aaaa", "tag": "a" * 32}
        ota = (ROOT / "src/OtaManager.cpp").read_text().split(
            "void OtaManager::appendDiagnostics", 1)[1].split(
            "void OtaManager::setSafeStateProvider", 1)[0]
        status["ota"] = {key: 0xFFFFFFFF for key in re.findall(r'destination\["([^"]+)"\]', ota)}
        status["ota"]["target_version"] = "x" * 63
        for key in ("transport_code", "http_code", "flash_code"):
            status["ota"][key] = -2147483648
        payload_bytes = len(json.dumps(status, separators=(",", ":")).encode())
        worker_header = (ROOT / "include/MqttTelemetryWorker.h").read_text()
        buffer_capacity = int(re.search(r'kMaxPayloadBytes = (\d+)', worker_header).group(1))
        self.assertIn("pendingTelemetry[sgk::MqttTelemetryWorker::kMaxPayloadBytes]", source)
        worker_source = (ROOT / "src/MqttTelemetryWorker.cpp").read_text()
        self.assertNotRegex(worker_source, r'kMaxPayloadBytes\s*=')
        worker_capacity = buffer_capacity
        self.assertLess(payload_bytes, buffer_capacity)
        self.assertLess(payload_bytes, worker_capacity)
        self.assertLess(buffer_capacity + 160 + 5, 8192)  # Topic/header included.


if __name__ == "__main__":
    unittest.main()
