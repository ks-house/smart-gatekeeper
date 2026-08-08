import importlib.util
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_release_signing.py"
spec = importlib.util.spec_from_file_location("verify_release_signing", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class ReleaseSigningTest(TestCase):
  def test_missing_apk_fails_closed(self):
    with self.assertRaisesRegex(SystemExit, "missing"):
        module.verify(Path(self.id().replace(".", "_") + "-missing.apk"), "aa" * 32)


  def test_debug_certificate_fails_closed(self):
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
      apk = Path(directory) / "app.apk"
      apk.write_bytes(b"apk")
      class Result:
          returncode = 0
          stdout = "Signer #1 certificate DN: CN=Android Debug, O=Android, C=US\nCertificate sha-256 digest: " + ":".join(["aa"] * 32)
          stderr = ""
      with patch.object(module.subprocess, "run", return_value=Result()):
        with self.assertRaisesRegex(SystemExit, "debug"):
          module.verify(apk, "aa" * 32, "apksigner")
