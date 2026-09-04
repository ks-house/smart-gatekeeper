"""Native behavior tests for the cross-soft-reset evidence checkpoint."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]


class RestartEvidenceRetentionTests(unittest.TestCase):
    def test_repeated_reset_and_partial_drain_behavior(self) -> None:
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
                / f"restart_evidence_retention_{uuid.uuid4().hex}"
            )
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Iinclude",
                    "tests/restart_evidence_retention_test.cpp",
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


if __name__ == "__main__":
    unittest.main()
