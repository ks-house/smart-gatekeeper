from __future__ import annotations

from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts import ops_commercial_gate as gate


class OpsCommercialGateTest(unittest.TestCase):
    @staticmethod
    def inventory(row_count=1):
        return {
            table: {
                "row_count": row_count,
                "content_sha256": "a" * 64,
                "schema_sha256": "b" * 64,
                "primary_key": ["id"],
            }
            for table in gate.REQUIRED_RESTORE_TABLES
        }

    def test_sbom_identity_is_stable_across_git_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lf = root / "lf.lock"
            crlf = root / "crlf.lock"
            lf.write_bytes(b"alpha==1.0 \\\n    --hash=sha256:" + b"a" * 64 + b"\n")
            crlf.write_bytes(lf.read_bytes().replace(b"\n", b"\r\n"))
            self.assertEqual(
                gate._canonical_text_sha256(lf),
                gate._canonical_text_sha256(crlf),
            )

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
        self.assertEqual(
            "PASS",
            gate.validate_production_images(
                "ghcr.io/ks-house/api@sha256:" + "a" * 64,
                "ghcr.io/ks-house/db@sha256:" + "b" * 64,
            )["status"],
        )
        for mutable in ("nginx:latest", "nginx", "repo@sha256:short"):
            with self.assertRaises(gate.GateError):
                gate.validate_production_images(
                    mutable, "ghcr.io/ks-house/db@sha256:" + "b" * 64
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
                dump, manifest, "a" * 40, "2026-08-09T00:00:00Z",
                self.inventory(), b"k" * 32,
            )
            self.assertEqual(
                "PASS",
                gate.verify_backup(
                    dump, manifest, 3600, "2026-08-09T00:30:00Z", b"k" * 32
                )["status"],
            )
            dump.write_text(dump.read_text() + "-- tampered", encoding="utf-8")
            with self.assertRaises(gate.GateError):
                gate.verify_backup(
                    dump, manifest, 3600, "2026-08-09T00:30:00Z", b"k" * 32
                )
            dump.write_text(
                "\n".join(
                    f"CREATE TABLE `{table}` (id INT);"
                    for table in sorted(gate.REQUIRED_RESTORE_TABLES)
                ),
                encoding="utf-8",
            )
            forged = json.loads(manifest.read_text(encoding="utf-8"))
            forged["source_inventory"]["tenants"]["row_count"] = 0
            manifest.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(gate.GateError, "authentication failed"):
                gate.verify_backup(
                    dump, manifest, 3600, "2026-08-09T00:30:00Z", b"k" * 32
                )
            missing = root / "missing.sql"
            missing.write_text("CREATE TABLE tenants (id INT);", encoding="utf-8")
            with self.assertRaises(gate.GateError):
                gate.create_backup_manifest(
                    missing, manifest, "a" * 40, "2026-08-09T00:00:00Z",
                    self.inventory(), b"k" * 32,
                )
            comments = root / "comments.sql"
            comments.write_text(
                "\n".join(
                    f"-- CREATE TABLE `{table}` (id INT);"
                    for table in sorted(gate.REQUIRED_RESTORE_TABLES)
                ),
                encoding="utf-8",
            )
            with self.assertRaises(gate.GateError):
                gate.create_backup_manifest(
                    comments, manifest, "a" * 40, "2026-08-09T00:00:00Z",
                    self.inventory(), b"k" * 32,
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
        cursor.fetchone.side_effect = [{"count": 0}, {"count": 0}, {"count": 0}]
        manifest = {
            "schema": "sgk-backup-manifest-v2",
            "source_inventory": self.inventory(),
            "migration_set_sha256": gate.migration_set_sha256(),
        }
        unsigned = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        import hashlib, hmac
        manifest["auth_hmac_sha256"] = hmac.new(b"k" * 32, unsigned, hashlib.sha256).hexdigest()
        with patch.object(
            gate, "capture_database_inventory", return_value=self.inventory()
        ):
            result = gate.verify_restored_database(connection, manifest, b"k" * 32, 240, 300)
        self.assertEqual("PASS", result["status"])
        self.assertEqual(240, result["rto_seconds"])
        with self.assertRaises(gate.GateError):
            gate.verify_restored_database(connection, manifest, b"k" * 32, 360, 300)
        with patch.object(
            gate, "capture_database_inventory", return_value=self.inventory(row_count=0)
        ), self.assertRaises(gate.GateError):
            cursor.fetchone.side_effect = [{"count": 0}, {"count": 0}, {"count": 0}]
            gate.verify_restored_database(connection, manifest, b"k" * 32, 10, 300)

    def test_evidence_register_is_commit_hosted_reviewer_and_expiry_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            output = root / "register.json"
            commit = "a" * 40
            template = json.loads(
                (gate.ROOT / "ops/evidence_sources.json").read_text(encoding="utf-8")
            )
            passed = copy.deepcopy(template)
            item = passed["evidence"][0]
            item.update({
                "state": "passed",
                "source_commit": commit,
                "artifact_sha256": "d" * 64,
                "reviewer": "independent-reviewer",
                "expires_at": "2026-08-10T00:00:00Z",
                "provenance": {
                    "provider": "github-actions",
                    "repository": "ks-house/smart-gatekeeper",
                    "commit": commit,
                    "run_id": 123,
                    "artifact_name": "ops-evidence",
                    "artifact_sha256": "d" * 64,
                },
            })
            env = {
                "GITHUB_ACTIONS": "true",
                "GITHUB_SHA": commit,
                "GITHUB_REPOSITORY": "ks-house/smart-gatekeeper",
                "GITHUB_RUN_ID": "123",
                "EVIDENCE_REVIEWER": "independent-reviewer",
            }
            source.write_text(json.dumps(passed), encoding="utf-8")
            with patch.object(gate, "checked_out_commit", return_value=commit):
                result = gate.evidence_register(
                    source, output, commit,
                    now=datetime(2026, 8, 9, tzinfo=timezone.utc),
                    environment=env,
                )
                self.assertEqual(commit, result["source_commit"])
                mutations = []
                for field, value in (
                    ("source_commit", "0" * 40),
                    ("artifact_sha256", "x"),
                    ("reviewer", "tworimpa"),
                    ("expires_at", "not-a-date"),
                    ("expires_at", "2026-08-08T00:00:00Z"),
                ):
                    mutated = copy.deepcopy(passed)
                    mutated["evidence"][0][field] = value
                    mutations.append(mutated)
                duplicate = copy.deepcopy(passed)
                duplicate["evidence"][1] = copy.deepcopy(duplicate["evidence"][0])
                mutations.append(duplicate)
                for index, mutated in enumerate(mutations):
                    with self.subTest(index=index):
                        source.write_text(json.dumps(mutated), encoding="utf-8")
                        with self.assertRaises(gate.GateError):
                            gate.evidence_register(
                                source, output, commit,
                                now=datetime(2026, 8, 9, tzinfo=timezone.utc),
                                environment=env,
                            )
                source.write_text(json.dumps(passed), encoding="utf-8")
                with self.assertRaises(gate.GateError):
                    gate.evidence_register(
                        source, output, commit,
                        now=datetime(2026, 8, 9, tzinfo=timezone.utc),
                        environment={},
                    )


if __name__ == "__main__":
    unittest.main()
