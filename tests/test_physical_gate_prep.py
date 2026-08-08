"""Host-only regression tests for Issue #54 pending-only artifacts."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_physical_gate_prep.py"


class PhysicalGatePrepTest(unittest.TestCase):

  def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
    )

  def test_pending_template_is_valid(self) -> None:
    result = self.run_validator("--require-pending")
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("PASS", result.stdout)

  def test_forged_pass_fixture_is_rejected(self) -> None:
    result = self.run_validator("--self-test")
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("forged-pass rejection", result.stdout)


if __name__ == "__main__":
  unittest.main()
