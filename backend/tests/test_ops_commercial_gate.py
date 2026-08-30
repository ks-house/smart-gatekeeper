from __future__ import annotations

import base64
from datetime import datetime, timezone
import copy
import hashlib
import hmac
import io
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.request
import zipfile

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
        declared = set(json.loads(
            (gate.ROOT / "ops/backend_trusted_bundle_paths.json").read_text(encoding="utf-8")
        )["paths"])
        actual_inputs = {
            path.relative_to(gate.ROOT).as_posix()
            for root in (gate.ROOT / "backend", gate.ROOT / "ops")
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        } | {
            ".github/workflows/backend_security.yml",
            ".orca/scripts/setup_worktree.ps1",
            "scripts/ops_commercial_gate.py",
            "protocol/test_vectors/v1.json",
        }
        self.assertEqual(actual_inputs, declared)
        for review_omission in (
            "backend/app/Dockerfile", "backend/app/main.py",
            "backend/docker-compose.yml", "backend/db/schema.sql",
            "backend/db/migrations/007_ops_privacy_up.sql",
            "backend/db/migrations/008_mobile_credential_control_up.sql",
            "backend/db/migrations/009_admin_account_management_up.sql",
            "backend/tests/test_target_boot_registry.py",
            "protocol/test_vectors/v1.json",
        ):
            self.assertIn(review_omission, declared)
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
        manifest["auth_hmac_sha256"] = hmac.new(b"k" * 32, unsigned, hashlib.sha256).hexdigest()
        with patch.object(
            gate, "capture_database_inventory", return_value=self.inventory()
        ):
            empty = MagicMock()
            empty.cursor.return_value.__enter__.return_value.fetchone.return_value = {"count": 0}
            restore = MagicMock()
            result = gate.restore_and_verify_database(
                restore, MagicMock(side_effect=[empty, connection]),
                manifest, b"k" * 32, 300,
                monotonic=MagicMock(side_effect=[100.0, 340.0]),
            )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(240, result["rto_seconds"])
        restore.assert_called_once_with(300)
        with patch.object(
            gate, "capture_database_inventory", return_value=self.inventory()
        ), self.assertRaises(gate.GateError):
            empty = MagicMock()
            empty.cursor.return_value.__enter__.return_value.fetchone.return_value = {"count": 0}
            cursor.fetchone.side_effect = [{"count": 0}, {"count": 0}, {"count": 0}]
            gate.restore_and_verify_database(
                MagicMock(), MagicMock(side_effect=[empty, connection]),
                manifest, b"k" * 32, 300,
                monotonic=MagicMock(side_effect=[100.0, 460.0]),
            )
        with patch.object(
            gate, "capture_database_inventory", return_value=self.inventory(row_count=0)
        ), self.assertRaises(gate.GateError):
            cursor.fetchone.side_effect = [{"count": 0}, {"count": 0}, {"count": 0}]
            gate.verify_restored_database(connection, manifest, b"k" * 32)

    def test_restore_target_must_be_empty_and_cli_has_no_caller_rto_argument(self):
        occupied = MagicMock()
        occupied.cursor.return_value.__enter__.return_value.fetchone.return_value = {"count": 1}
        with self.assertRaises(gate.GateError):
            gate.restore_and_verify_database(
                MagicMock(), MagicMock(return_value=occupied), {}, b"k" * 32, 300
            )
        source = (gate.ROOT / "scripts/ops_commercial_gate.py").read_text(encoding="utf-8")
        self.assertNotIn("--measured-rto-seconds", source)

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
                    "run_attempt": 2,
                    "artifact_name": f"ops-contract-{commit}",
                    "artifact_archive_sha256": "e" * 64,
                    "artifact_path": "ops-contract.json",
                    "subject_path": "build/evidence/ops-contract.json",
                    "artifact_sha256": "d" * 64,
                    "pull_request": 67,
                    "review_id": 456,
                    "reviewer_id": 987,
                    "reviewed_head_sha": "b" * 40,
                },
            })
            verifier = MagicMock()
            verifier.verify.return_value = {
                "evidence_id": "ops-contract",
                "subject_sha256": "d" * 64,
                "payload_sha256": "f" * 64,
            }
            source.write_text(json.dumps(passed), encoding="utf-8")
            with patch.object(gate, "checked_out_commit", return_value=commit):
                result = gate.evidence_register(
                    source, output, commit,
                    now=datetime(2026, 8, 9, tzinfo=timezone.utc),
                    verifier=verifier,
                )
                self.assertEqual(commit, result["source_commit"])
                verifier.verify.assert_called_once()
                self.assertEqual(
                    "ops-contract", verifier.verify.call_args.kwargs["evidence_id"]
                )
                self.assertEqual(
                    "local-software", verifier.verify.call_args.kwargs["scope"]
                )
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
                                verifier=verifier,
                            )
                source.write_text(json.dumps(passed), encoding="utf-8")
                with self.assertRaises(gate.GateError):
                    gate.evidence_register(
                        source, output, commit,
                        now=datetime(2026, 8, 9, tzinfo=timezone.utc),
                    )

    def test_evidence_claims_are_id_scoped_and_same_payload_reuse_fails(self):
        commit = "a" * 40
        fixtures = json.loads(
            (gate.ROOT / "ops/fixtures/evidence_adversarial_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("sgk-evidence-adversarial-fixtures-v1", fixtures["schema"])
        for source_id, target_id in fixtures["cross_id_swaps"]:
            source_policy = gate.EVIDENCE_POLICIES[source_id]
            target_policy = gate.EVIDENCE_POLICIES[target_id]
            self.assertTrue(
                source_policy["artifact_name"] != target_policy["artifact_name"]
                or source_policy["artifact_path"] != target_policy["artifact_path"]
                or source_policy["subject_path"] != target_policy["subject_path"]
                or source_policy["claim_type"] != target_policy["claim_type"]
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "ops-result.json"
            ops_claim_path = root / "ops-claim.json"
            sbom_path = root / "sbom.json"
            sbom_claim_path = root / "sbom-claim.json"
            with patch.object(gate, "checked_out_commit", return_value=commit):
                gate.generate_ops_contract_result(result_path, commit)
                ops_claim = gate.generate_evidence_claim(
                    "ops-contract", result_path, ops_claim_path, commit,
                )
                gate.generate_sbom(sbom_path)
                sbom_claim = gate.generate_evidence_claim(
                    "hosted-sbom-attestation", sbom_path, sbom_claim_path, commit,
                )
                with self.assertRaises(gate.GateError):
                    gate.generate_evidence_claim(
                        "24h-load-soak", sbom_path, root / "soak.json", commit,
                    )
            self.assertEqual("ops-contract", ops_claim["evidence_id"])
            self.assertEqual("repository-operations-contract", ops_claim["claim_type"])
            self.assertEqual("hosted-sbom-attestation", sbom_claim["evidence_id"])
            self.assertNotEqual(
                hashlib.sha256(ops_claim_path.read_bytes()).hexdigest(),
                hashlib.sha256(sbom_claim_path.read_bytes()).hexdigest(),
            )

            template = json.loads(
                (gate.ROOT / "ops/evidence_sources.json").read_text(encoding="utf-8")
            )

            def mark_passed(item, digest):
                policy = gate.EVIDENCE_POLICIES[item["id"]]
                item.update({
                    "state": "passed", "source_commit": commit,
                    "artifact_sha256": digest,
                    "reviewer": "independent-reviewer",
                    "expires_at": "2026-08-10T00:00:00Z",
                    "provenance": {
                        "provider": "github-actions",
                        "repository": "ks-house/smart-gatekeeper",
                        "commit": commit, "run_id": 123, "run_attempt": 1,
                        "artifact_name": policy["artifact_name"].format(commit=commit),
                        "artifact_archive_sha256": "e" * 64,
                        "artifact_path": policy["artifact_path"],
                        "subject_path": policy["subject_path"],
                        "artifact_sha256": digest,
                        "pull_request": 67, "review_id": 456, "reviewer_id": 987,
                        "reviewed_head_sha": "b" * 40,
                    },
                })

            same_sbom = copy.deepcopy(template)
            for item in same_sbom["evidence"]:
                mark_passed(item, fixtures["same_sbom_for_all"]["subject_sha256"])
            source = root / "source.json"
            output = root / "register.json"
            source.write_text(json.dumps(same_sbom), encoding="utf-8")
            verifier = MagicMock()
            verifier.verify.return_value = {
                "evidence_id": "ops-contract", "subject_sha256": "d" * 64,
                "payload_sha256": fixtures["same_sbom_for_all"]["payload_sha256"],
            }
            with patch.object(gate, "checked_out_commit", return_value=commit):
                with self.assertRaises(gate.GateError):
                    gate.evidence_register(
                        source, output, commit,
                        now=datetime(2026, 8, 9, tzinfo=timezone.utc), verifier=verifier,
                    )
            self.assertEqual(1, verifier.verify.call_count)

            reused_payload = copy.deepcopy(template)
            mark_passed(reused_payload["evidence"][0], "c" * 64)
            mark_passed(reused_payload["evidence"][1], "d" * 64)
            source.write_text(json.dumps(reused_payload), encoding="utf-8")
            verifier = MagicMock()
            verifier.verify.side_effect = lambda **kwargs: {
                "evidence_id": kwargs["evidence_id"],
                "subject_sha256": kwargs["digest"],
                "payload_sha256": "f" * 64,
            }
            with patch.object(gate, "checked_out_commit", return_value=commit):
                with self.assertRaises(gate.GateError):
                    gate.evidence_register(
                        source, output, commit,
                        now=datetime(2026, 8, 9, tzinfo=timezone.utc), verifier=verifier,
                    )
            self.assertEqual(2, verifier.verify.call_count)

    def test_redirects_require_https_and_strip_authorization_on_full_origin_change(self):
        handler = gate.HTTPSOriginRedirectHandler()
        fixtures = json.loads(
            (gate.ROOT / "ops/fixtures/evidence_adversarial_v1.json").read_text(
                encoding="utf-8"
            )
        )["redirects"]

        def redirected(source, target):
            request = urllib.request.Request(
                source,
                headers={"Authorization": "Bearer redacted-test-token"},
            )
            return handler.redirect_request(request, None, 302, "Found", {}, target)

        for fixture in fixtures:
            with self.subTest(target=fixture["to"]):
                if not fixture["admitted"]:
                    with self.assertRaises(gate.GateError):
                        redirected(fixture["from"], fixture["to"])
                    continue
                result = redirected(fixture["from"], fixture["to"])
                self.assertEqual(
                    fixture["authorization_forwarded"],
                    result.get_header("Authorization") is not None,
                )
        with self.assertRaises(gate.GateError):
            redirected(
                "https://api.github.com/artifact",
                "https://user:password@api.github.com/download",
            )

    def test_github_evidence_verifier_rejects_forged_run_artifact_review_attestation(self):
        commit = "a" * 40
        reviewed_head = "b" * 40
        policy = gate.EVIDENCE_POLICIES["hosted-sbom-attestation"]
        claim = {
            "schema": "sgk-evidence-claim-v1",
            "evidence_id": "hosted-sbom-attestation",
            "scope": "hosted-ci",
            "claim_type": "cyclonedx-sbom-attestation",
            "result": "PASS",
            "source_commit": commit,
            "producer": {
                "workflow_path": ".github/workflows/backend_security.yml",
                "workflow_ref": "refs/heads/main",
                "event": "push",
                "job": "backend-security",
                "environment": "github-hosted-main",
            },
            "payload": {
                "path": "build/backend-sbom.cdx.json",
                "schema": "cyclonedx-1.5",
                "sha256": "f" * 64,
            },
        }
        subject_bytes = (json.dumps(claim, indent=2, sort_keys=True) + "\n").encode()
        digest = hashlib.sha256(subject_bytes).hexdigest()
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as bundle:
            bundle.writestr(policy["artifact_path"], subject_bytes)
        archive = archive_buffer.getvalue()
        archive_digest = hashlib.sha256(archive).hexdigest()
        provenance = {
            "provider": "github-actions",
            "repository": "ks-house/smart-gatekeeper",
            "commit": commit,
            "run_id": 123,
            "run_attempt": 2,
            "artifact_name": policy["artifact_name"].format(commit=commit),
            "artifact_archive_sha256": archive_digest,
            "artifact_path": policy["artifact_path"],
            "subject_path": policy["subject_path"],
            "artifact_sha256": digest,
            "pull_request": 67,
            "review_id": 456,
            "reviewer_id": 987,
            "reviewed_head_sha": reviewed_head,
        }
        statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [{"name": policy["subject_path"], "digest": {"sha256": digest}}],
            "predicate": {
                "buildDefinition": {
                    "externalParameters": {
                        "workflow": {
                            "repository": "https://github.com/ks-house/smart-gatekeeper",
                            "ref": "refs/heads/main",
                            "path": "/.github/workflows/backend_security.yml",
                        }
                    },
                    "resolvedDependencies": [{"digest": {"gitCommit": commit}}],
                },
                "runDetails": {
                    "builder": {"id": "https://github.com/actions/runner/github-hosted"},
                    "metadata": {
                        "invocationId": (
                            "https://github.com/ks-house/smart-gatekeeper/"
                            "actions/runs/123/attempts/2"
                        )
                    }
                },
            },
        }
        documents = {
            "commit": {"sha": commit, "author": {"login": "tworimpa"}},
            "run": {
                "id": 123, "head_sha": commit, "status": "completed",
                "conclusion": "success", "event": "push", "head_branch": "main",
                "path": ".github/workflows/backend_security.yml",
                "run_attempt": 2,
                "repository": {"full_name": "ks-house/smart-gatekeeper"},
            },
            "jobs": {"jobs": [
                {
                    "name": "backend-security", "status": "completed",
                    "conclusion": "success", "head_sha": commit, "run_attempt": 2,
                    "labels": ["ubuntu-latest"],
                    "steps": [{
                        "name": "Upload hosted SBOM evidence claim",
                        "conclusion": "success",
                    }],
                },
                {
                    "name": "attest-backend-evidence", "status": "completed",
                    "conclusion": "success", "head_sha": commit, "run_attempt": 2,
                    "labels": ["ubuntu-latest"],
                    "steps": [{
                        "name": "Attest hosted SBOM claim", "conclusion": "success",
                    }],
                },
            ]},
            "artifacts": {
                "artifacts": [{
                    "name": policy["artifact_name"].format(commit=commit),
                    "digest": f"sha256:{digest}",
                    "expired": False, "archive_download_url": "https://api.github.com/archive.zip",
                    "workflow_run": {
                        "id": 123, "head_sha": commit, "head_branch": "main",
                    },
                }]
            },
            "pull": {
                "number": 67, "state": "closed", "merged": True,
                "merged_at": "2026-08-09T00:00:00Z", "merge_commit_sha": commit,
                "base": {"ref": "main", "repo": {"full_name": "ks-house/smart-gatekeeper"}},
                "head": {"sha": reviewed_head, "repo": {"full_name": "ks-house/smart-gatekeeper"}},
            },
            "review": {
                "id": 456, "user": {
                    "id": 987, "login": "independent-reviewer", "type": "User",
                },
                "state": "APPROVED", "commit_id": reviewed_head,
            },
            "reviewer": {"id": 987, "login": "independent-reviewer", "type": "User"},
            "attestations": {
                "attestations": [{
                    "bundle": {"dsseEnvelope": {"payload": base64.b64encode(
                        json.dumps(statement).encode()
                    ).decode()}}
                }]
            },
        }

        def api_document(path):
            if "/commits/" in path:
                return documents["commit"]
            if "/actions/runs/123/artifacts" in path:
                return documents["artifacts"]
            if "/actions/runs/123/attempts/2/jobs" in path:
                return documents["jobs"]
            if "/actions/runs/123" in path:
                return documents["run"]
            if "/reviews/456" in path:
                return documents["review"]
            if path.endswith("/pulls/67"):
                return documents["pull"]
            if path.endswith("/users/independent-reviewer"):
                return documents["reviewer"]
            if "/attestations/" in path:
                return documents["attestations"]
            raise AssertionError(path)

        verifier = gate.GitHubEvidenceVerifier("test-token")
        self.assertEqual(verifier.API_URL, "https://api.github.com")
        self.assertNotIn("GITHUB_API_URL", inspect.getsource(gate.main))
        documents["artifacts"]["artifacts"][0]["digest"] = f"sha256:{archive_digest}"
        with patch.object(verifier, "_get", side_effect=api_document), patch.object(
            verifier, "_download", return_value=archive
        ):
            verified = verifier.verify(
                evidence_id="hosted-sbom-attestation", scope="hosted-ci",
                repository="ks-house/smart-gatekeeper", commit=commit,
                candidate_author="tworimpa", reviewer="independent-reviewer", digest=digest,
                provenance=provenance,
            )
            self.assertEqual("f" * 64, verified["payload_sha256"])
            with self.assertRaises(gate.GateError):
                verifier.verify(
                    evidence_id="ops-contract", scope="local-software",
                    repository="ks-house/smart-gatekeeper", commit=commit,
                    candidate_author="tworimpa", reviewer="independent-reviewer",
                    digest=digest, provenance=provenance,
                )
            mutations = (
                ("commit", "author", {"login": "forged-author"}),
                ("run", "conclusion", "failure"),
                ("run", "path", ".github/workflows/untrusted.yml"),
                ("jobs", "jobs", []),
                ("artifacts", "artifacts", []),
                ("pull", "merge_commit_sha", "0" * 40),
                ("review", "state", "COMMENTED"),
                ("reviewer", "id", 1234),
                ("attestations", "attestations", []),
            )
            for document, field, value in mutations:
                with self.subTest(document=document):
                    original = documents[document][field]
                    documents[document][field] = value
                    try:
                        with self.assertRaises(gate.GateError):
                            verifier.verify(
                                evidence_id="hosted-sbom-attestation", scope="hosted-ci",
                                repository="ks-house/smart-gatekeeper", commit=commit,
                                candidate_author="tworimpa",
                                reviewer="independent-reviewer", digest=digest,
                                provenance=provenance,
                            )
                    finally:
                        documents[document][field] = original


if __name__ == "__main__":
    unittest.main()
