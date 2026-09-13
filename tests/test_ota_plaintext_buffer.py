"""OTA-only workspace lifetime without relaxing health or flash safety."""

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OtaPlaintextBufferTest(unittest.TestCase):
    def test_allocation_failure_zeroization_and_repeated_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "ota-buffer")
            subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                 "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                 "-Iinclude", "tests/ota_plaintext_buffer_test.cpp",
                 "-o", executable],
                cwd=ROOT, check=True, capture_output=True,
            )
            subprocess.run([executable], check=True, capture_output=True, timeout=10)

    def test_workspace_exists_only_for_inactive_image_write(self):
        source = (ROOT / "src/OtaManager.cpp").read_text()
        begin = source.split("bool beginImageWrite()", 1)[1].split(
            "bool writeImageChunk", 1)[0]
        self.assertLess(begin.index("updatePlaintextBuffer.allocate()"),
                        begin.index("esp_ota_begin("))
        before_flash = begin.split("esp_ota_begin(", 1)[0]
        self.assertIn("ESP_ERR_NO_MEM", before_flash)
        self.assertIn("return false;", before_flash)
        self.assertIn("updatePlaintextBuffer.release();", begin)
        reset = source.split("void resetUpdateState()", 1)[1].split(
            "void abortImageWrite()", 1)[0]
        self.assertIn("updatePlaintextBuffer.release();", reset)
        finish = source.split("bool finishImageWrite()", 1)[1].split(
            "void OtaManager::init()", 1)[0]
        self.assertIn("abortImageWrite();", finish)
        self.assertIn("resetUpdateState();", finish)
        self.assertIn("!updatePlaintextBuffer", source)
        self.assertNotIn("sizeof(updatePlaintextBuffer)", source)
        self.assertIn("OtaPlaintextBuffer<kDecryptInputChunkSize + 15>", source)


if __name__ == "__main__":
    unittest.main()
