from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OtaDiagnosticsTest(unittest.TestCase):
    def test_persistent_record_corruption_and_stage_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "ota-diagnostic")
            subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-Iinclude", "tests/ota_diagnostic_record_test.cpp", "-o", executable],
                           cwd=ROOT, check=True, capture_output=True)
            subprocess.run([executable], check=True, capture_output=True)

    def test_resource_handoff_is_guarded_and_automatically_restored(self):
        mqtt = (ROOT / "src/MqttManager.cpp").read_text()
        suspend = mqtt.split("bool MqttManager::suspendForOta()", 1)[1].split("void MqttManager::resumeAfterOta", 1)[0]
        self.assertLess(suspend.index("connectionAttemptInProgress()"), suspend.index("wifiClient.stop()"))
        self.assertIn("!OtaManager::isSafeForOta()", suspend)
        self.assertIn("takeConnectWorkerResult(&discarded)", suspend)
        ota = (ROOT / "src/OtaManager.cpp").read_text()
        check = ota.split("void OtaManager::checkAndUpdate", 1)[1].split("bool OtaManager::stageLocalManifest", 1)[0]
        self.assertLess(check.index("if (!waitForSafeState())"), check.index("transportLease.acquire()"))
        self.assertLess(check.index("struct BusyGuard"), check.index("WiFiClientSecure otaClient"))
        self.assertLess(check.index("OtaTransportLease<MqttManager>"), check.index("WiFiClientSecure otaClient"))
        self.assertIn("otaClient.lastError", check)
        self.assertNotIn("setInsecure", check)
        self.assertIn('error = "image begin"', check)
        self.assertIn("noteOtaStage(OtaStage::kPendingBoot)", check)
        self.assertIn('doc.createNestedObject("ota")', mqtt)
        self.assertIn("runningImageValid = imageStateKnown && state == ESP_OTA_IMG_VALID", ota)
        self.assertIn('destination["running_image_valid"] = runningImageValid', ota)


if __name__ == "__main__":
    unittest.main()
