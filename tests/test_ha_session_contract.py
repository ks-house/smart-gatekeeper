"""HA-generated sessions must pass the real Target access-session parser."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from backend.app.home_assistant_bridge import (
    HomeAssistantCommandBridge, bridge_request_topic, target_status_topic,
)

ROOT = Path(__file__).resolve().parents[1]


class HaTargetSessionContractTest(unittest.TestCase):
    def test_generated_sessions_and_observed_failure_on_target_core(self):
        compiler = shutil.which("g++")
        self.assertIsNotNone(compiler, "native g++ is required for Target contract test")
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "ha-session-contract"
            subprocess.run([
                compiler, "-std=c++17", "-ffunction-sections", "-fdata-sections",
                "-I", str(ROOT / "include"), str(ROOT / "src/TargetCommandSecurity.cpp"),
                str(ROOT / "tests/ha_session_contract_test.cpp"), "-Wl,--gc-sections",
                "-o", str(executable),
            ], check=True, capture_output=True, timeout=60)
            observed = subprocess.run([str(executable), "4928b7ca412dd60e8b614b0e22394f08"],
                                      timeout=5)
            self.assertEqual(1, observed.returncode)
            for _ in range(32):
                bridge = HomeAssistantCommandBridge("target-a", allow_manual_remote=True)
                bridge.note_status(target_status_topic("target-a"), json.dumps(
                    {"target_id": "target-a", "boot_id": "1" * 32}).encode())
                decision = bridge.accept_request(bridge_request_topic("target-a", "open_gate"),
                                                 b"PRESS")
                self.assertTrue(decision.accepted)
                result = subprocess.run([str(executable), decision.command.session_id], timeout=5)
                self.assertEqual(0, result.returncode)
