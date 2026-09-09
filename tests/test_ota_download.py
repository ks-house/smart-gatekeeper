from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OtaDownloadTest(unittest.TestCase):
    def test_real_download_pump_faults_and_fragmentation(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / 'ota-download')
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-Iinclude',
                            'tests/ota_download_test.cpp', '-o', exe], cwd=ROOT, check=True)
            subprocess.run([exe], check=True, timeout=30)


if __name__ == '__main__':
    unittest.main()
