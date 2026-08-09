from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from scripts import ops_commercial_gate as gate


class OpsCommercialGateTest(unittest.TestCase):
    def test_repository_contract_and_license_complete_sbom(self):
        self.assertEqual("PASS", gate.contract()["status"])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sbom.json"
            sbom = gate.generate_sbom(output)
            self.assertEqual("CycloneDX", sbom["bomFormat"])
            self.assertGreaterEqual(len(sbom["components"]), 20)
            self.assertEqual(sbom, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(
                sbom,
                json.loads((gate.ROOT / "backend/sbom.cdx.json").read_text(encoding="utf-8")),
            )

    def test_backup_manifest_detects_tampering_missing_tables_and_stale_rpo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump = root / "backup.sql"
            dump.write_text(
                "\n".join(f"CREATE TABLE `{table}` (id INT);" for table in sorted(gate.REQUIRED_RESTORE_TABLES)),
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            gate.create_backup_manifest(
                dump, manifest, "a" * 40, "2026-08-09T00:00:00Z"
            )
            self.assertEqual(
                "PASS",
                gate.verify_backup(
                    dump, manifest, 3600, "2026-08-09T00:30:00Z"
                )["status"],
            )
            dump.write_text(dump.read_text() + "-- tampered", encoding="utf-8")
            with self.assertRaises(gate.GateError):
                gate.verify_backup(dump, manifest, 3600, "2026-08-09T00:30:00Z")
            missing = root / "missing.sql"
            missing.write_text("CREATE TABLE tenants (id INT);", encoding="utf-8")
            with self.assertRaises(gate.GateError):
                gate.create_backup_manifest(
                    missing, manifest, "a" * 40, "2026-08-09T00:00:00Z"
                )

    def test_nominal_slo_passes_and_fault_mutation_fails(self):
        policy = gate.ROOT / "ops/slo_policy.json"
        nominal = gate.ROOT / "ops/fixtures/load_nominal.jsonl"
        self.assertEqual("PASS", gate.evaluate_slo(nominal, policy)["status"])
        with tempfile.TemporaryDirectory() as directory:
            mutated = Path(directory) / "bad.jsonl"
            rows = [json.loads(line) for line in nominal.read_text().splitlines()]
            for row in rows:
                row["latency_ms"] = 9999
            mutated.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            with self.assertRaises(gate.GateError):
                gate.evaluate_slo(mutated, policy)

    def test_isolated_restore_checks_tables_integrity_and_measured_rto(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            {"table_name": table} for table in gate.REQUIRED_RESTORE_TABLES
        ]
        cursor.fetchone.side_effect = [
            {"count": 0}, {"count": 0}, {"count": 0},
            {"count": 10}, {"count": 8}, {"count": 20}, {"count": 1},
        ]
        result = gate.verify_restored_database(
            connection, "2026-08-09T00:00:00Z", "2026-08-09T00:04:00Z", 300
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(240, result["rto_seconds"])
        with self.assertRaises(gate.GateError):
            gate.verify_restored_database(
                connection, "2026-08-09T00:00:00Z", "2026-08-09T00:06:00Z", 300
            )

    def test_evidence_register_rejects_unreviewed_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            output = root / "register.json"
            source.write_text(json.dumps({"evidence": [{
                "id": "bad", "state": "passed", "artifact_sha256": None,
                "reviewer": None, "expires_at": None,
            }]}), encoding="utf-8")
            with self.assertRaises(gate.GateError):
                gate.evidence_register(source, output, "a" * 40)
            result = gate.evidence_register(
                gate.ROOT / "ops/evidence_sources.json", output, "a" * 40
            )
            self.assertEqual("a" * 40, result["source_commit"])


if __name__ == "__main__":
    unittest.main()
