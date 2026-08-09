"""Portable source bindings for hardwareless manual walkthrough scenarios.

These tests intentionally import only the Python standard library.  They bind each
walkthrough to the executable dependency-backed test and production owner without
pretending that a source-only CI lane executed FastAPI, MariaDB, or MQTT integrations.
The full suites continue to execute in their dependency-provisioned hosted lanes.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def definition(path: str, name: str) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                return segment
    raise AssertionError(f"{path}: missing definition {name}")


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class ManualSourceContractTests(unittest.TestCase):
    def assert_tokens(self, text: str, *tokens: str) -> None:
        for token in tokens:
            self.assertIn(token, text)

    def test_user04_mobile_manifest_mutation_suite_binding(self) -> None:
        tests = source("tests/test_sign_mobile_manifest.py")
        self.assert_tokens(
            tests,
            "test_create_emits_exact_signed_schema_and_artifact_binding",
            "test_verify_rejects_tampered_artifact_and_certificate",
            "test_create_rejects_apk_internal_identity_and_commit_mismatches",
            "test_duplicate_or_missing_embedded_commit_is_rejected",
            '"exact APK bytes"',
            '"certificate digest"',
            '"embedded source commit"',
        )
        self.assert_tokens(
            source("scripts/ota_contract_gate.py"),
            "create_mobile_manifest",
            "verify_mobile_manifest",
            "signing_certificate_digest",
            "source_commit",
        )

    def test_admin01_auth_denial_suite_binding(self) -> None:
        test = definition(
            "backend/tests/test_admin_security.py",
            "test_anonymous_forged_role_stale_session_and_cross_tenant_are_denied",
        )
        self.assert_tokens(test, "401", "403", "rotate_sessions", "/tenants/2/approve")
        self.assert_tokens(
            source("backend/app/admin_security.py"),
            "authenticate_mtls",
            "can_access_tenant",
            "CSRF validation failed",
            "rotate_sessions",
        )

    def test_admin02_two_person_publish_suite_binding(self) -> None:
        test = definition(
            "backend/tests/test_admin_security.py",
            "test_two_person_approval_publishes_exactly_once",
        )
        self.assert_tokens(
            test,
            '"status": "PENDING"',
            '"status": "published"',
            'publish.assert_called_once_with("authorized-control-plane")',
            "FORCE_OPEN_RECONCILIATION_REQUIRED",
            "FORCE_OPEN_PUBLISHED",
        )
        self.assert_tokens(
            source("backend/app/main.py"),
            '"approval_required"',
            "RECONCILIATION_REQUIRED",
            'return {"status": "published", "approval_id": approval_id}',
        )

    def test_admin04_restore_integrity_suite_binding(self) -> None:
        test = definition(
            "backend/tests/test_ops_commercial_gate.py",
            "test_isolated_restore_checks_tables_integrity_and_measured_rto",
        )
        self.assert_tokens(
            test,
            '"sgk-backup-manifest-v2"',
            '"auth_hmac_sha256"',
            'self.assertEqual("PASS", result["status"])',
            'self.assertEqual(240, result["rto_seconds"])',
            "verify_restored_database",
        )
        self.assert_tokens(
            source("scripts/ops_commercial_gate.py"),
            "REQUIRED_RESTORE_TABLES",
            "capture_database_inventory",
            "verify_restored_database",
            "restore_and_verify_database",
        )

    def test_admin05_readiness_fail_closed_suite_binding(self) -> None:
        test = definition(
            "backend/tests/test_ops_api.py",
            "test_readiness_fails_closed_and_can_report_all_dependencies",
        )
        self.assert_tokens(
            test,
            'self.client.get("/ready")',
            "503",
            '"control_api_auth"',
            '"legacy_prearm_retired"',
            "self.assertTrue(all(ready.json()[\"checks\"].values()))",
        )
        self.assert_tokens(
            definition("backend/app/main.py", "_readiness_snapshot"),
            '"database"',
            '"mqtt"',
            '"admin_auth"',
            '"build_identity"',
        )

    def test_admin06_support_consent_suite_binding(self) -> None:
        test = definition(
            "backend/tests/test_ops_api.py",
            "test_support_export_rejects_invalid_consent_lifecycle",
        )
        self.assert_tokens(
            test,
            '"support-diagnostics"',
            '"legacy:2"',
            '"revoked_at": 2',
            "403",
        )
        self.assert_tokens(
            definition("backend/app/main.py", "create_support_export"),
            'consent["tenant_scope"] != x_tenant_id',
            'consent["purpose"] != "support-diagnostics"',
            'consent["revoked_at"] is not None',
            'int(consent["expires_at"]) <= now',
        )

    def test_admin07_retention_idempotency_suite_binding(self) -> None:
        test = definition(
            "backend/tests/test_ops_api.py",
            "test_retention_delete_rejects_idempotency_payload_or_actor_mismatch",
        )
        self.assert_tokens(
            test,
            "Idempotency-Key",
            '"sgk-retention-v1"',
            "different-admin",
            "409",
        )
        self.assert_tokens(
            definition("backend/app/main.py", "delete_expired_privacy_data"),
            "request_hash",
            "idempotency_key",
            "privacy_deletion_jobs",
            "status_code=409",
        )

    def test_support02_reconciliation_suite_binding(self) -> None:
        test = definition(
            "backend/tests/test_admin_security.py",
            "test_post_publish_audit_failure_keeps_precommitted_reconciliation_state",
        )
        self.assert_tokens(
            test,
            "post-publish audit unavailable",
            "503",
            'publish.assert_called_once_with("authorized-control-plane")',
            "FORCE_OPEN_RECONCILIATION_REQUIRED",
            "FORCE_OPEN_PUBLISHED",
        )
        self.assert_tokens(
            source("backend/app/main.py"),
            "RECONCILIATION_REQUIRED",
            "FORCE_OPEN_PUBLISHED",
            'return {"status": "published", "approval_id": approval_id}',
        )

    def test_support03_bounded_connect_suite_binding(self) -> None:
        test = definition(
            "backend/tests/test_ops_runtime.py",
            "test_dns_tcp_tls_connect_is_deadline_bounded_and_cancelled",
        )
        self.assert_tokens(
            test,
            "connect_timeout=0.05",
            "cancel_connect=lambda _client: cancelled.set()",
            "self.assertLess(time.monotonic() - started, 0.25)",
            '"a blocked resolver must not fan out threads"',
        )
        self.assert_tokens(
            source("backend/app/ops_runtime.py"),
            "class CircuitBreaker",
            "class PersistentMqttPublisher",
            "connect_timeout",
            "cancel_connect",
            "_connect_attempt",
        )


if __name__ == "__main__":
    unittest.main()
