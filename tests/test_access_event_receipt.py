"""Exercise firmware commit receipts with independent Python HMAC vectors."""

import hashlib
import hmac
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


class AccessEventReceiptTest(unittest.TestCase):
    def test_exact_event_binding_and_independent_wire_vector(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "access-receipt")
            subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Iinclude",
                 "src/GattProtocol.cpp", "src/OfflineEventQueue.cpp",
                 "src/AccessEventReceipt.cpp", "tests/access_event_receipt_test.cpp",
                 "-o", executable],
                cwd=ROOT, check=True, capture_output=True,
            )
            result = subprocess.run(
                [executable], check=True, capture_output=True, text=True,
            )
        canonical_hex, tag_hex, sensor_tag_hex = result.stdout.strip().splitlines()
        canonical = (
            b"SGK-ACCESS-RECEIPT-V1\x00"
            + b"\x02a1\x0btest-target"
            + uuid.UUID("00000000-0000-4000-8000-000000000001").bytes
            + bytes.fromhex("00112233445566778899aabbccddeeff")
            + struct.pack(">QQ", 782, 9007199254740993)
            + bytes(range(0xa0, 0xb0))
        )
        self.assertEqual(canonical_hex, canonical.hex())
        self.assertEqual(
            tag_hex,
            hmac.new(bytes(range(1, 33)), canonical, hashlib.sha256).hexdigest()[:32],
        )
        self.assertEqual(
            sensor_tag_hex,
            hmac.new(
                bytes(range(1, 33)),
                canonical.replace(b"SGK-ACCESS-RECEIPT-V1", b"SGK-SENSOR-RECEIPT-V1", 1),
                hashlib.sha256,
            ).hexdigest()[:32],
        )


if __name__ == "__main__":
    unittest.main()
