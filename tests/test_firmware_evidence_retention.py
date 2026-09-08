"""Real durable queue regressions for the September 8 mixed-event loss."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FirmwareEvidenceRetentionTest(unittest.TestCase):
    def test_actual_queue_retains_complete_mixed_session_and_applies_backpressure(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "evidence-retention")
            subprocess.run([
                "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
                "tests/firmware_evidence_retention_test.cpp", "src/OfflineEventQueue.cpp",
                "-o", executable,
            ], cwd=ROOT, check=True, capture_output=True)
            subprocess.run([executable], check=True, capture_output=True)

    def test_producers_route_legacy_away_from_signed_checkpoint(self):
        source = (ROOT / "src/MqttManager.cpp").read_text()
        legacy = source.split("void MqttManager::publishEvent(", 1)[1].split(
            "bool MqttManager::enqueueCanonicalEvent", 1)[0]
        self.assertIn("legacyEventOutbox.push(event)", legacy)
        self.assertNotIn("enqueueEventWithDurableSpill", legacy)
        self.assertNotIn("g_offline_queue", legacy)
        self.assertIn("backpressureCount()", source)
        # Both restored durable and RAM records discriminate authenticated audit
        # from unsigned N-1 records, which cannot receive a commit receipt.
        self.assertEqual(2, source.count("const bool requiresReceipt = sgk::canonicalEventRequiresCommitReceipt(evt);"))


if __name__ == "__main__":
    unittest.main()
