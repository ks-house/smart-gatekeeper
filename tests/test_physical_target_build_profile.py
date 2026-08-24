import csv
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_target_flash_layout",
    ROOT / "scripts" / "verify_target_flash_layout.py")
FLASH_LAYOUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FLASH_LAYOUT)


class PhysicalTargetBuildProfileTests(unittest.TestCase):
  def test_every_8mb_partition_stays_inside_physical_flash(self):
    rows = []
    with (ROOT / "partitions_8MB_ota.csv").open(encoding="utf-8") as source:
      for row in csv.reader(line for line in source if not line.startswith("#")):
        if row:
          rows.append(row)
    for name, _kind, _subtype, offset, size, *_rest in rows:
      end = int(offset.strip(), 0) + int(size.strip(), 0)
      self.assertLessEqual(end, 0x800000, name.strip())

  def test_n16_flash_size_and_loop_stack_are_explicit(self):
    config = (ROOT / "platformio.ini").read_text(encoding="utf-8")
    self.assertIn("board_upload.flash_size = 16MB", config)
    self.assertIn("board_upload.maximum_size = 16777216", config)
    self.assertIn("board_build.partitions = partitions_16MB_ota.csv", config)
    self.assertIn("-DARDUINO_LOOP_STACK_SIZE=16384", config)
    self.assertIn("[env:esp32c6_production]", config)
    self.assertIn("build_unflags          = -DSGK_PRODUCTION_BUILD=0", config)
    self.assertIn("-DSGK_PRODUCTION_BUILD=1", config)
    self.assertIn("[env:esp32c6_personal_production]", config)

  def test_n16_dual_ota_layout_and_release_headroom(self):
    slot_size, usage = FLASH_LAYOUT.verify_layout(
        ROOT / "partitions_16MB_ota.csv",
        0x1000000,
        1724320,
        80.0,
    )
    self.assertEqual(slot_size, 0x700000)
    self.assertLess(usage, 25.0)

  def test_release_headroom_gate_rejects_oversized_image(self):
    with self.assertRaisesRegex(ValueError, "limit is 80.00%"):
      FLASH_LAYOUT.verify_layout(
          ROOT / "partitions_16MB_ota.csv",
          0x1000000,
          int(0x700000 * 0.81),
          80.0,
      )

  def test_personal_installation_builds_physical_target_profile(self):
    workflow = (ROOT / ".github" / "workflows" /
                "personal_installation_firmware.yml").read_text(encoding="utf-8")
    self.assertIn("pio run -e esp32c6_personal_production", workflow)
    self.assertIn("ESP32-C6-WROOM-1-N16 16MB dual OTA", workflow)
    self.assertIn("verify_target_flash_layout.py", workflow)
    self.assertIn("--max-slot-usage-percent 80", workflow)


if __name__ == "__main__":
  unittest.main()
