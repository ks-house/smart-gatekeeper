"""Execute production canonical conversion with platform/outbox seams."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GattEvidenceDeliveryTest(unittest.TestCase):
    def test_actual_sink_retries_identical_signed_record_and_correlates_sensor(self):
        include = os.environ.get("SGK_ARDUINOJSON_INCLUDE")
        if not include:
            candidates = list((ROOT / ".pio/libdeps").glob("*/ArduinoJson/src/ArduinoJson.h"))
            if candidates:
                include = str(candidates[0].parent)
        if not include:
            self.skipTest("ArduinoJson host headers unavailable")
        source = (ROOT / "src/GattServer.cpp").read_text()
        production = "class CanonicalMqttEventSink" + source.split(
            "class CanonicalMqttEventSink", 1)[1].split(
            "CanonicalMqttEventSink production_event_sink;", 1)[0]
        fixture = (ROOT / "tests/gatt_evidence_delivery_test.cpp").read_text()
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "sink.cpp"
            harness.write_text(fixture.replace("// PRODUCTION_SINK", production))
            binary = str(Path(directory) / "sink")
            result = subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-Iinclude", "-I" + include, str(harness), "src/GattProtocol.cpp",
                "src/OfflineEventQueue.cpp", "src/SensorSessionDiagnostics.cpp", "-o", binary],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(0, result.returncode, result.stderr)
            result = subprocess.run([binary], capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("production sink retry identity", result.stdout)
