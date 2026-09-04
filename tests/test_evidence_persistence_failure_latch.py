"""Behavior and wiring regressions for restart persistence diagnostics."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]


class EvidencePersistenceFailureLatchTests(unittest.TestCase):
    def test_native_repeated_reset_and_current_boot_failure_behavior(self) -> None:
        compiler = shutil.which("g++")
        if compiler is None:
            compiler = str(
                Path.home()
                / ".platformio/packages/toolchain-gccmingw32/bin/g++.exe"
            )
        self.assertTrue(Path(compiler).is_file(), "native g++ is required")

        with tempfile.TemporaryDirectory() as directory:
            executable = (
                Path(directory)
                / f"evidence_persistence_latch_{uuid.uuid4().hex}"
            )
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Iinclude",
                    "tests/evidence_persistence_failure_latch_test.cpp",
                    "-o",
                    str(executable),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            run_result = subprocess.run(
                [str(executable)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run_result.returncode, 0, run_result.stderr)

    def test_boot_diagnostic_acknowledges_only_after_publish_success(self) -> None:
        diagnostics = (ROOT / "src/DiagnosticsManager.cpp").read_text(
            encoding="utf-8"
        )
        diagnostics_header = (ROOT / "include/DiagnosticsManager.h").read_text(
            encoding="utf-8"
        )
        mqtt = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")

        begin = diagnostics.split("void DiagnosticsManager::begin()", 1)[1]
        begin = begin.split("void DiagnosticsManager::heartbeat", 1)[0]
        self.assertIn("evidencePersistenceFailureLatch.begin(", begin)
        self.assertIn("previousBreadcrumb.evidencePersistenceFailed != 0", begin)
        self.assertIn(
            "evidencePersistenceFailureLatch.active() ? 1 : 0", begin
        )

        acknowledge = diagnostics.split(
            "void DiagnosticsManager::acknowledgePreviousEvidencePersistenceFailure()",
            1,
        )[1].split("void DiagnosticsManager::markPlannedRestart", 1)[0]
        self.assertIn("carriedFailurePending()", acknowledge)
        self.assertIn("acknowledgeCarriedFailure()", acknowledge)
        self.assertIn("evidencePersistenceFailureLatch.active() ? 1 : 0", acknowledge)
        self.assertIn(
            "acknowledgePreviousEvidencePersistenceFailure", diagnostics_header
        )

        publish = mqtt.split("void MqttManager::publishBootDiagnostics()", 1)[1]
        publish = publish.split("void MqttManager::publishConfigState", 1)[0]
        socket_publish = publish.index("client.publish(bootTopic.c_str()")
        success_guard = publish.index("if (ok)", socket_publish)
        acknowledge_call = publish.index(
            "DiagnosticsManager::acknowledgePreviousEvidencePersistenceFailure()",
            success_guard,
        )
        self.assertLess(socket_publish, success_guard)
        self.assertLess(success_guard, acknowledge_call)


if __name__ == "__main__":
    unittest.main()
