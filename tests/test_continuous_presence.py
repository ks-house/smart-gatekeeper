import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ContinuousPresenceTest(unittest.TestCase):
    def test_verified_terminal_reauthentication_and_passage_interlock(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(pathlib.Path(directory) / "continuous-presence")
            subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
                 "tests/continuous_presence_test.cpp", "src/TargetAccessFsm.cpp",
                 "-o", executable], cwd=ROOT, check=True, capture_output=True,
            )
            subprocess.run([executable], check=True, capture_output=True)
