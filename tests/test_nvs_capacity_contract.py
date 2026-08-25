import csv
import io
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NvsCapacityContractTest(unittest.TestCase):
    def test_durable_partition_preserves_both_ota_slots(self):
        partition_text = (ROOT / "partitions_16MB_ota.csv").read_text(
            encoding="utf-8"
        )
        rows = list(
            csv.reader(
                io.StringIO(
                    "\n".join(
                        line
                        for line in partition_text.splitlines()
                        if line.strip() and not line.lstrip().startswith("#")
                    )
                ),
                skipinitialspace=True,
            )
        )
        partitions = {row[0].strip(): [value.strip() for value in row] for row in rows}
        self.assertEqual(partitions["nvs"][3:5], ["0x9000", "0x5000"])
        self.assertEqual(partitions["app0"][3:5], ["0x10000", "0x700000"])
        self.assertEqual(partitions["app1"][3:5], ["0x710000", "0x700000"])
        self.assertEqual(partitions["sgkstate"][1:5], ["data", "nvs", "0xE10000", "0x1E0000"])

    def test_security_state_uses_durable_partition_with_legacy_read_fallback(self):
        helper = (ROOT / "include" / "DurablePreferences.h").read_text(
            encoding="utf-8"
        )
        main = (ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
        mqtt = (ROOT / "src" / "MqttManager.cpp").read_text(encoding="utf-8")

        self.assertIn('kDurableStatePartition[] = "sgkstate"', helper)
        self.assertIn('kLegacyDurableStatePartition[] = "spiffs"', helper)
        self.assertIn("esp_partition_find_first", helper)
        self.assertIn("nvs_get_stats", helper)
        self.assertIn("readDurableBlobWithLegacyFallback", helper)
        self.assertIn("readBlobFromPartition(nullptr", helper)
        self.assertNotIn("nvs_flash_erase", helper)

        for namespace in ("sgk_acl", "sgk_queue"):
            self.assertIn(f'writeDurableBlob("{namespace}"', main)
            self.assertIn(f'"{namespace}", key', main)
        self.assertIn('writeDurableBlob("sgk_cmd"', mqtt)
        self.assertIn('"sgk_cmd", key', mqtt)
        self.assertIn("[NVS] Durable security state partition", main)
        self.assertIn("[NVS-ERROR] Durable security state partition", main)

    def test_legacy_spiffs_region_is_not_mounted_as_a_filesystem(self):
        production_sources = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for directory in (ROOT / "src", ROOT / "include")
            for path in directory.glob("*.*")
        )
        self.assertNotIn("SPIFFS.begin", production_sources)
        self.assertNotIn("LittleFS.begin", production_sources)


if __name__ == "__main__":
    unittest.main()
