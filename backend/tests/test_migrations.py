from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymysql
from fastapi import HTTPException

from backend.app import main as admin_main
from backend.app.acl_management import (
    AclManagementService,
    AclStore,
    DeterministicP256Signer,
    RecordingPublisher,
    build_enrollment_input,
)
from backend.app.admin_security import AdminPrincipal
from scripts import ops_commercial_gate


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "backend" / "db" / "schema.sql"
UP = ROOT / "backend" / "db" / "migrations" / "002_acl_management_expand_up.sql"
DOWN = ROOT / "backend" / "db" / "migrations" / "002_acl_management_expand_down.sql"
ADMIN_UP = ROOT / "backend" / "db" / "migrations" / "003_admin_security_up.sql"
ADMIN_DOWN = ROOT / "backend" / "db" / "migrations" / "003_admin_security_down.sql"
CONTROL_V2_UP = ROOT / "backend" / "db" / "migrations" / "004_admin_control_v2_up.sql"
CONTROL_V2_DOWN = ROOT / "backend" / "db" / "migrations" / "004_admin_control_v2_down.sql"
RECONCILIATION_UP = ROOT / "backend" / "db" / "migrations" / "005_force_open_reconciliation_up.sql"
RECONCILIATION_DOWN = ROOT / "backend" / "db" / "migrations" / "005_force_open_reconciliation_down.sql"
BOOT_STATE_UP = ROOT / "backend" / "db" / "migrations" / "006_target_boot_state_up.sql"
BOOT_STATE_DOWN = ROOT / "backend" / "db" / "migrations" / "006_target_boot_state_down.sql"
OPS_PRIVACY_UP = ROOT / "backend" / "db" / "migrations" / "007_ops_privacy_up.sql"
OPS_PRIVACY_DOWN = ROOT / "backend" / "db" / "migrations" / "007_ops_privacy_down.sql"
MOBILE_CONTROL_UP = ROOT / "backend" / "db" / "migrations" / "008_mobile_credential_control_up.sql"
MOBILE_CONTROL_DOWN = ROOT / "backend" / "db" / "migrations" / "008_mobile_credential_control_down.sql"
ADMIN_ACCOUNT_UP = ROOT / "backend" / "db" / "migrations" / "009_admin_account_management_up.sql"
ADMIN_ACCOUNT_DOWN = ROOT / "backend" / "db" / "migrations" / "009_admin_account_management_down.sql"
MOBILE_ROLE_UP = ROOT / "backend" / "db" / "migrations" / "010_mobile_account_roles_up.sql"
MOBILE_ROLE_DOWN = ROOT / "backend" / "db" / "migrations" / "010_mobile_account_roles_down.sql"
PRODUCTION_SCHEMA = ROOT / "backend" / "db" / "production_schema.sql"
MIGRATION_RUNNER = ROOT / "backend" / "db" / "run_migrations.sh"
DB_DOCKERFILE = ROOT / "backend" / "db" / "Dockerfile"
DEVELOPMENT_COMPOSE = ROOT / "backend" / "docker-compose.yml"
BACKEND_SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "backend_security.yml"


class MigrationContractTest(unittest.TestCase):
    def test_hosted_compose_validation_loads_signed_schema_metadata(self) -> None:
        workflow = BACKEND_SECURITY_WORKFLOW.read_text(encoding="utf-8")
        validation = workflow.split(
            "      - name: Validate Compose is private by default", 1
        )[1]
        self.assertIn("set -a\n          . backend/db/schema.env\n          set +a", validation)
        self.assertLess(
            validation.index(". backend/db/schema.env"),
            validation.index("docker compose -f backend/compose.production.yml"),
        )

    def test_personal_nas_compose_runs_backup_first_existing_volume_migration(self) -> None:
        compose = DEVELOPMENT_COMPOSE.read_text(encoding="utf-8")
        migrate_start = compose.index("  migrate:")
        api_start = compose.index("  api:")
        migrate = compose[migrate_start:api_start]
        api = compose[api_start:]
        for required in (
            'command: ["/usr/local/bin/sgk-migrate", "up", "${SCHEMA_VERSION:-010}"]',
            "DB_MIGRATION_PASSWORD_FILE: /run/secrets/db_root_password",
            "MIGRATION_SOURCE_COMMIT: ${BUILD_SHA:?exact 40-hex BUILD_SHA is required}",
            "MIGRATION_BACKUP_DIR: /var/backups/smart-gatekeeper",
            "./secrets/db_root_password",
            "./migration_backups",
            "condition: service_healthy",
        ):
            self.assertIn(required, migrate)
        self.assertIn("migrate:", api)
        self.assertIn("condition: service_completed_successfully", api)
        self.assertIn("EXPECTED_DB_SCHEMA_VERSION", api)
        self.assertIn("EXPECTED_DB_SCHEMA_SHA256", api)

    def test_expand_preserves_legacy_columns_and_down_drops_only_new_state(self) -> None:
        up = UP.read_text(encoding="utf-8")
        down = DOWN.read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS tenant_uuid", up)
        self.assertIn("credential_mode", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS credentials", up)
        self.assertIn("actor_ref VARCHAR(128) NOT NULL", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS credential_door_grants", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS acl_door_state", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS acl_snapshot_jobs", up)
        self.assertIn("status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'", up)
        self.assertIn("chk_acl_tenant_status", up)
        self.assertIn("ADD COLUMN IF NOT EXISTS status", up)
        self.assertIn("UNIQUE KEY uq_acl_door_global (door_id)", up)
        self.assertNotIn("DROP COLUMN ble_device_mac", up)
        self.assertNotIn("DROP COLUMN auth_key", up)
        self.assertNotIn("DROP TABLE IF EXISTS tenants", down)
        self.assertNotIn("DROP TABLE IF EXISTS access_logs", down)
        self.assertEqual(1, down.count("DROP TABLE IF EXISTS credentials;"))
        self.assertEqual(1, down.count("DROP TABLE IF EXISTS acl_snapshot_jobs;"))
        self.assertEqual(1, down.count("DROP TABLE IF EXISTS enrollment_challenges;"))

    def test_admin_account_link_is_additive_and_rollback_preserves_accounts(self) -> None:
        up = ADMIN_ACCOUNT_UP.read_text(encoding="utf-8")
        down = ADMIN_ACCOUNT_DOWN.read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS credential_id", up)
        self.assertIn("ADD UNIQUE INDEX IF NOT EXISTS uq_tenants_credential_id", up)
        self.assertIn("DROP COLUMN IF EXISTS credential_id", down)
        self.assertNotIn("DROP TABLE", down)
        self.assertNotIn("DELETE FROM", down)

    def test_mobile_role_is_least_privilege_and_additive(self) -> None:
        up = MOBILE_ROLE_UP.read_text(encoding="utf-8")
        down = MOBILE_ROLE_DOWN.read_text(encoding="utf-8")
        self.assertIn("mobile_role VARCHAR(24) NOT NULL DEFAULT 'USER'", up)
        self.assertIn("'TENANT_ADMIN'", up)
        self.assertIn("DROP COLUMN IF EXISTS mobile_role", down)
        self.assertNotIn("DROP TABLE", down)

    def test_admin_audit_migration_is_append_only_and_has_explicit_rollback(self) -> None:
        up = ADMIN_UP.read_text(encoding="utf-8")
        down = ADMIN_DOWN.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS admin_audit", up)
        self.assertIn("CREATE TRIGGER admin_audit_no_update", up)
        self.assertIn("CREATE TRIGGER admin_audit_no_delete", up)
        self.assertIn("admin_audit is immutable", up)
        self.assertIn("DROP TRIGGER IF EXISTS admin_audit_no_update", down)
        self.assertIn("DROP TABLE IF EXISTS admin_audit", down)

    def test_v2_control_migration_has_durable_replay_and_approval_state(self) -> None:
        up = CONTROL_V2_UP.read_text(encoding="utf-8")
        down = CONTROL_V2_DOWN.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS force_open_approvals", up)
        self.assertIn("UNIQUE KEY uq_force_open_request", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS mobile_control_nonces", up)
        self.assertIn("PRIMARY KEY (tenant_id, nonce_hash, action)", up)
        self.assertIn("DROP TABLE IF EXISTS mobile_control_nonces", down)

    def test_reconciliation_migration_preserves_ambiguous_publish_state(self) -> None:
        up = RECONCILIATION_UP.read_text(encoding="utf-8")
        down = RECONCILIATION_DOWN.read_text(encoding="utf-8")
        self.assertIn("RECONCILIATION_REQUIRED", up)
        self.assertIn("ALTER TABLE force_open_approvals", up)
        self.assertIn("ALTER TABLE force_open_approvals", down)

    def test_target_boot_state_is_monotonic_and_has_explicit_rollback(self) -> None:
        up = BOOT_STATE_UP.read_text(encoding="utf-8")
        down = BOOT_STATE_DOWN.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS target_boot_state", up)
        self.assertIn("boot_count BIGINT UNSIGNED NOT NULL", up)
        self.assertIn("boot_id REGEXP", up)
        self.assertIn("DROP TABLE IF EXISTS target_boot_state", down)

    def test_privacy_deletion_evidence_is_bounded_immutable_and_reversible(self) -> None:
        up = OPS_PRIVACY_UP.read_text(encoding="utf-8")
        down = OPS_PRIVACY_DOWN.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS privacy_deletion_jobs", up)
        self.assertIn("UNIQUE KEY uq_privacy_delete_idempotency", up)
        self.assertIn("before_days BETWEEN 30 AND 3650", up)
        self.assertIn("request_hash CHAR(64) NOT NULL", up)
        self.assertIn("state ENUM('PENDING', 'COMPLETED')", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS support_export_consents", up)
        self.assertIn("purpose = 'support-diagnostics'", up)
        self.assertIn("CREATE TRIGGER support_export_consents_revoke_only", up)
        self.assertIn("CREATE TRIGGER support_export_consents_no_delete", up)
        self.assertIn("CREATE TRIGGER privacy_deletion_jobs_no_update", up)
        self.assertIn("CREATE TRIGGER privacy_deletion_jobs_no_delete", up)
        self.assertIn("DROP TABLE IF EXISTS privacy_deletion_jobs", down)
        self.assertIn("DROP TABLE IF EXISTS support_export_consents", down)

    def test_mobile_credential_control_has_durable_replay_state(self) -> None:
        up = MOBILE_CONTROL_UP.read_text(encoding="utf-8")
        down = MOBILE_CONTROL_DOWN.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS mobile_credential_control_nonces", up)
        self.assertIn("PRIMARY KEY (credential_id, nonce_hash, action)", up)
        self.assertIn("FOREIGN KEY (credential_id) REFERENCES credentials", up)
        self.assertIn("DROP TABLE IF EXISTS mobile_credential_control_nonces", down)

    def test_production_schema_is_seed_free_and_existing_volume_migration_is_admitted(self) -> None:
        schema = PRODUCTION_SCHEMA.read_text(encoding="utf-8")
        dockerfile = DB_DOCKERFILE.read_text(encoding="utf-8")
        runner = MIGRATION_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("INSERT INTO TENANTS", schema.upper())
        for forbidden in ("secret_key_101", "010-1234", "AA:BB:CC:DD:EE:01"):
            self.assertNotIn(forbidden, schema)
            self.assertNotIn(forbidden, dockerfile)
        self.assertIn("production_schema.sql", dockerfile)
        self.assertNotIn("COPY schema.sql /docker-entrypoint-initdb.d", dockerfile)
        for required in (
            "mariadb-dump", "pre-migration-", "schema_migrations",
            "canonical_sha", "up:0[0-9][0-9]|down:001", ".schema-migration-lock",
            "non-contiguous migration sequence", "target migration ${target} is unavailable",
            "%Y%m%dT%H%M%S%NZ", "pre-migration backup identity collision",
        ):
            self.assertIn(required, runner)
        self.assertLess(runner.index("mariadb-dump"), runner.index("apply_up"))

    @unittest.skipUnless(
        os.getenv("RUN_MARIADB_INTEGRATION") == "1",
        "set RUN_MARIADB_INTEGRATION=1 for production DB image migration test",
    )
    def test_production_db_image_is_seed_free_and_upgrades_existing_volume(self) -> None:
        name = f"sgk-prod-db-{uuid.uuid4().hex[:10]}"
        image = f"sgk-prod-db-test:{uuid.uuid4().hex[:10]}"
        password = "migration-test-only"

        def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["docker", *args], text=True, encoding="utf-8", errors="strict",
                capture_output=True, check=check,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / "root-password"
            backup = root / "backups"
            secret.write_text(password + "\n", encoding="utf-8")
            backup.mkdir()
            docker(
                "build", "-t", image, "-f", str(DB_DOCKERFILE),
                str(ROOT / "backend" / "db"),
            )
            docker(
                "run", "--rm", "-d", "--name", name,
                "-e", f"MARIADB_ROOT_PASSWORD={password}",
                "-v", f"{secret.resolve()}:/run/secrets/db_root_password:ro",
                "-v", f"{backup.resolve()}:/var/backups/smart-gatekeeper",
                image,
            )
            try:
                for _ in range(60):
                    ready = docker(
                        "exec", name, "mariadb", "-N", "-uroot", f"-p{password}",
                        "smart_gatekeeper", "-e",
                        "SELECT COUNT(*),@@port FROM tenants;",
                        check=False,
                    )
                    if ready.returncode == 0 and ready.stdout.strip() == "0\t3306":
                        break
                    time.sleep(1)
                else:
                    self.fail("production database image did not become ready")

                empty = docker(
                    "exec", name, "mariadb", "-N", "-uroot", f"-p{password}",
                    "smart_gatekeeper", "-e", "SELECT COUNT(*) FROM tenants;",
                )
                self.assertEqual("0", empty.stdout.strip())
                docker(
                    "exec", name, "mariadb", "-uroot", f"-p{password}",
                    "smart_gatekeeper", "-e",
                    "INSERT INTO tenants(name,unit_number,is_active) "
                    "VALUES ('existing-volume','E-1',TRUE);",
                )

                migration_env = [
                    "-e", "DB_HOST=127.0.0.1", "-e", "DB_PORT=3306",
                    "-e", "DB_NAME=smart_gatekeeper", "-e", "DB_MIGRATION_USER=root",
                    "-e", "DB_MIGRATION_PASSWORD_FILE=/run/secrets/db_root_password",
                    "-e", f"MIGRATION_SOURCE_COMMIT={'a' * 40}",
                    "-e", "MIGRATION_BACKUP_DIR=/var/backups/smart-gatekeeper",
                ]
                for _ in range(2):
                    migrated = docker(
                        "exec", *migration_env, name,
                        "/usr/local/bin/sgk-migrate", "up", "010", check=False,
                    )
                    self.assertEqual(0, migrated.returncode, migrated.stderr)
                state = docker(
                    "exec", name, "mariadb", "-N", "-uroot", f"-p{password}",
                    "smart_gatekeeper", "-e",
                    "SELECT (SELECT COUNT(*) FROM tenants WHERE unit_number='E-1'),"
                    "(SELECT COUNT(*) FROM schema_migrations),"
                    "(SELECT script_sha256 FROM schema_migrations WHERE version='010');",
                ).stdout.strip().split("\t")
                expected_010 = subprocess.run(
                    ["sha256sum", str(MOBILE_ROLE_UP)],
                    text=True,
                    capture_output=True,
                    check=True,
                ).stdout.split()[0]
                self.assertEqual(["1", "9", expected_010], state)
                self.assertGreaterEqual(len(list(backup.glob("*.sql"))), 2)
                self.assertEqual(len(list(backup.glob("*.sql"))), len(list(backup.glob("*.sha256"))))

                rolled_back = docker(
                    "exec", *migration_env, name,
                    "/usr/local/bin/sgk-migrate", "down", "001", check=False,
                )
                self.assertEqual(0, rolled_back.returncode, rolled_back.stderr)
                legacy = docker(
                    "exec", name, "mariadb", "-N", "-uroot", f"-p{password}",
                    "smart_gatekeeper", "-e",
                    "SELECT unit_number FROM tenants WHERE unit_number='E-1';",
                )
                self.assertEqual("E-1", legacy.stdout.strip())
            finally:
                docker("rm", "-f", name, check=False)
                docker("image", "rm", image, check=False)

    @unittest.skipUnless(
        os.getenv("RUN_MARIADB_INTEGRATION") == "1",
        "set RUN_MARIADB_INTEGRATION=1 for isolated MariaDB migration test",
    )
    def test_real_mariadb_up_legacy_write_down_legacy_read(self) -> None:
        name = f"sgk-acl-migration-{uuid.uuid4().hex[:10]}"
        password = "migration-test-only"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            host_port = probe.getsockname()[1]

        def docker(*args: str, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["docker", *args],
                input=input_text,
                text=True,
                encoding="utf-8",
                errors="strict",
                capture_output=True,
                check=check,
            )

        docker(
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "-e",
            f"MARIADB_ROOT_PASSWORD={password}",
            "-p",
            f"127.0.0.1:{host_port}:3306",
            "mariadb@sha256:be981e4113326ada8d6004174dd09eeaefc03094037f811182a52d4f2e737350",
        )
        try:
            consecutive_ready = 0
            for _ in range(60):
                ready = docker(
                    "exec",
                    name,
                    "mariadb",
                    "-N",
                    "-uroot",
                    f"-p{password}",
                    "-e",
                    "SELECT 1;",
                    check=False,
                )
                if ready.returncode == 0:
                    consecutive_ready += 1
                    if consecutive_ready == 3:
                        break
                else:
                    consecutive_ready = 0
                time.sleep(1)
            else:
                self.fail("isolated MariaDB did not become ready")

            combined = "\n".join(
                (
                    SCHEMA.read_text(encoding="utf-8"),
                    UP.read_text(encoding="utf-8"),
                    UP.read_text(encoding="utf-8"),
                    ADMIN_UP.read_text(encoding="utf-8"),
                    CONTROL_V2_UP.read_text(encoding="utf-8"),
                    RECONCILIATION_UP.read_text(encoding="utf-8"),
                    BOOT_STATE_UP.read_text(encoding="utf-8"),
                    OPS_PRIVACY_UP.read_text(encoding="utf-8"),
                    "INSERT INTO tenants (name, unit_number, ble_device_mac, auth_key, is_active) "
                    "VALUES ('N-1 client', '999', 'AA:BB:CC:DD:EE:99', 'legacy-only', TRUE);",
                    "INSERT INTO acl_tenants VALUES "
                    "('11111111111111111111111111111111', 'tenant', 'ACTIVE', 1, 1);",
                    "INSERT INTO credentials VALUES "
                    "('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','11111111111111111111111111111111',"
                    "'046b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c2964fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5',"
                    "'PENDING',NULL,NULL,1,1,1,1);",
                )
            )
            applied = docker(
                "exec",
                "-i",
                name,
                "mariadb",
                "--default-character-set=utf8mb4",
                "-uroot",
                f"-p{password}",
                input_text=combined,
                check=False,
            )
            if applied.returncode != 0:
                self.fail(f"migration apply failed: {applied.stderr}")
            self.assertEqual("", applied.stderr)

            legacy = docker(
                "exec",
                name,
                "mariadb",
                "-N",
                "-uroot",
                f"-p{password}",
                "smart_gatekeeper",
                "-e",
                "SELECT auth_key FROM tenants WHERE ble_device_mac='AA:BB:CC:DD:EE:99';",
            )
            self.assertEqual("legacy-only", legacy.stdout.strip())

            audit_immutable = docker(
                "exec", name, "mariadb", "-N", "-uroot", f"-p{password}", "smart_gatekeeper", "-e",
                "INSERT INTO admin_audit (actor_subject,tenant_scope,action,object_ref,created_at) "
                "VALUES ('admin:a','legacy:1','TEST','object',1); "
                "UPDATE admin_audit SET action='MUTATED' WHERE actor_subject='admin:a';",
                check=False,
            )
            self.assertNotEqual(0, audit_immutable.returncode)
            self.assertIn("admin_audit is immutable", audit_immutable.stderr)

            def connection() -> pymysql.Connection:
                return pymysql.connect(
                    host="127.0.0.1",
                    port=host_port,
                    user="root",
                    password=password,
                    database="smart_gatekeeper",
                    cursorclass=pymysql.cursors.DictCursor,
                    autocommit=False,
                )

            tenant_id = "00112233445566778899aabbccddeeff"
            door_id = "ffeeddccbbaa99887766554433221100"
            store = AclStore(connection, dialect="mysql", close_connections=True)
            service = AclManagementService(
                store,
                DeterministicP256Signer(2, 7),
                RecordingPublisher(),
                clock=lambda: 1_700_000_000,
                legacy_hmac_key=b"isolated-mariadb-test-key",
            )
            service.register_tenant(
                tenant_id,
                "MariaDB Integration",
                1,
                actor_ref="admin:test",
            )
            challenge = service.issue_enrollment_challenge(
                tenant_id, actor_ref="user:test", actor_tenant_id=tenant_id
            )
            mobile = DeterministicP256Signer(3, 9)
            enrollment_input = build_enrollment_input(
                tenant_id,
                challenge["enrollment_id"],
                challenge["nonce"],
                mobile.public_key_sec1.hex(),
            )
            with self.assertRaisesRegex(PermissionError, "actor boundary"):
                service.submit_enrollment(
                    tenant_id,
                    challenge["enrollment_id"],
                    challenge["nonce"],
                    mobile.public_key_sec1.hex(),
                    mobile.sign(enrollment_input).hex(),
                    actor_ref="user:same-tenant-peer",
                    actor_tenant_id=tenant_id,
                )
            with connection() as challenge_connection:
                with challenge_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT used_at FROM enrollment_challenges "
                        "WHERE tenant_id=%s AND enrollment_id=%s",
                        (tenant_id, challenge["enrollment_id"]),
                    )
                    self.assertIsNone(cursor.fetchone()["used_at"])
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM credentials WHERE tenant_id=%s",
                        (tenant_id,),
                    )
                    self.assertEqual(0, cursor.fetchone()["count"])
            credential = service.submit_enrollment(
                tenant_id,
                challenge["enrollment_id"],
                challenge["nonce"],
                mobile.public_key_sec1.hex(),
                mobile.sign(enrollment_input).hex(),
                actor_ref="user:test",
                actor_tenant_id=tenant_id,
            )
            service.approve_credential(
                tenant_id, credential["credential_id"], actor_ref="admin:test"
            )
            service.grant_credential_to_door(
                tenant_id,
                door_id,
                credential["credential_id"],
                actor_ref="admin:test",
            )
            envelope = service.publish_snapshot(
                tenant_id, door_id, actor_ref="admin:test"
            )
            self.assertEqual(
                envelope["sha256"], service.pull_snapshot(tenant_id, door_id)["sha256"]
            )
            ack = service.ack_snapshot(
                tenant_id,
                "target-mariadb",
                door_id,
                envelope["fields"]["acl_version"],
                envelope["sha256"],
                "APPLIED",
            )
            self.assertFalse(ack["duplicate"])
            with connection() as check_connection:
                with check_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT tenant_uuid, credential_mode FROM tenants WHERE id=1"
                    )
                    legacy_mapping = cursor.fetchone()
            self.assertEqual(tenant_id, legacy_mapping["tenant_uuid"])
            self.assertEqual("legacy", legacy_mapping["credential_mode"])
            with ThreadPoolExecutor(max_workers=4) as pool:
                concurrent_snapshots = list(
                    pool.map(
                        lambda _: service.publish_snapshot(
                            tenant_id, door_id, actor_ref="admin:concurrent"
                        ),
                        range(4),
                    )
                )
            self.assertEqual(
                [2, 3, 4, 5],
                sorted(item["fields"]["acl_version"] for item in concurrent_snapshots),
            )
            latest = max(
                concurrent_snapshots, key=lambda item: item["fields"]["acl_version"]
            )
            with ThreadPoolExecutor(max_workers=4) as pool:
                concurrent_acks = list(
                    pool.map(
                        lambda _: service.ack_snapshot(
                            tenant_id,
                            "target-concurrent",
                            door_id,
                            latest["fields"]["acl_version"],
                            latest["sha256"],
                            "APPLIED",
                        ),
                        range(4),
                    )
                )
            self.assertEqual(1, sum(not item["duplicate"] for item in concurrent_acks))
            self.assertEqual(1, len({item["ack_id"] for item in concurrent_acks}))

            def conflicting_ack(status: str) -> tuple[str, str]:
                try:
                    service.ack_snapshot(
                        tenant_id,
                        "target-conflict",
                        door_id,
                        latest["fields"]["acl_version"],
                        latest["sha256"],
                        status,
                    )
                    return "accepted", status
                except ValueError:
                    return "conflict", status

            with ThreadPoolExecutor(max_workers=4) as pool:
                conflict_results = list(
                    pool.map(
                        conflicting_ack,
                        ("APPLIED", "REJECTED", "APPLIED", "REJECTED"),
                    )
                )
            accepted_statuses = {
                status for result, status in conflict_results if result == "accepted"
            }
            self.assertEqual(1, len(accepted_statuses))
            self.assertEqual(2, sum(result == "conflict" for result, _ in conflict_results))

            other_door_id = "0123456789abcdef0123456789abcdef"
            service.grant_credential_to_door(
                tenant_id,
                other_door_id,
                credential["credential_id"],
                actor_ref="admin:test",
            )
            other_active = service.publish_snapshot(
                tenant_id, other_door_id, actor_ref="admin:test"
            )
            self.assertEqual(1, other_active["fields"]["acl_version"])
            self.assertEqual(1, len(other_active["fields"]["entries"]))

            working_signer = service.signer

            class FailingSigner:
                signing_key_id = working_signer.signing_key_id
                public_key_sec1 = working_signer.public_key_sec1

                def sign(self, payload: bytes) -> bytes:
                    raise RuntimeError("isolated signer unavailable")

            service.signer = FailingSigner()
            with self.assertRaisesRegex(RuntimeError, "durable job remains queued"):
                service.disable_tenant(
                    tenant_id,
                    actor_ref="admin:test",
                    actor_tenant_id=tenant_id,
                )
            with connection() as disabled_connection:
                with disabled_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT a.status, t.is_active FROM acl_tenants a "
                        "JOIN tenants t ON t.tenant_uuid=a.tenant_id "
                        "WHERE a.tenant_id=%s",
                        (tenant_id,),
                    )
                    disabled_state = cursor.fetchone()
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM acl_snapshot_jobs "
                        "WHERE tenant_id=%s AND generated_version IS NULL",
                        (tenant_id,),
                    )
                    pending_count = cursor.fetchone()["count"]
                    cursor.execute(
                        "SELECT status FROM credentials WHERE credential_id=%s",
                        (credential["credential_id"],),
                    )
                    credential_status = cursor.fetchone()["status"]
            self.assertEqual("DISABLED", disabled_state["status"])
            self.assertFalse(disabled_state["is_active"])
            self.assertEqual(2, pending_count)
            self.assertEqual("ACTIVE", credential_status)

            class FailingPublisher:
                def publish(self, topic: str, envelope: dict) -> bool:
                    return False

            service.signer = working_signer
            service.publisher = FailingPublisher()
            with self.assertRaisesRegex(RuntimeError, "pull is current"):
                service.disable_tenant(
                    tenant_id,
                    actor_ref="admin:test",
                    actor_tenant_id=tenant_id,
                )
            with connection() as generated_connection:
                with generated_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT door_id, generated_version FROM acl_snapshot_jobs "
                        "WHERE tenant_id=%s ORDER BY door_id",
                        (tenant_id,),
                    )
                    generated_jobs = cursor.fetchall()
            self.assertEqual(2, len(generated_jobs))
            generated_versions = {
                row["door_id"]: int(row["generated_version"])
                for row in generated_jobs
            }
            self.assertTrue(all(version >= 2 for version in generated_versions.values()))

            recovered_publisher = RecordingPublisher()
            service.publisher = recovered_publisher
            recovered = service.disable_tenant(
                tenant_id,
                actor_ref="admin:test",
                actor_tenant_id=tenant_id,
            )
            self.assertTrue(recovered["already_disabled"])
            self.assertEqual(
                sorted(generated_versions.values()),
                sorted(
                    item["fields"]["acl_version"]
                    for item in recovered["replacement_snapshots"]
                ),
            )
            for affected_door_id in (door_id, other_door_id):
                replacement = service.pull_snapshot(tenant_id, affected_door_id)
                self.assertEqual([], replacement["fields"]["entries"])
                self.assertEqual(
                    generated_versions[affected_door_id],
                    replacement["fields"]["acl_version"],
                )
            final_retry = service.disable_tenant(
                tenant_id,
                actor_ref="admin:test",
                actor_tenant_id=tenant_id,
            )
            self.assertTrue(final_retry["already_disabled"])
            self.assertEqual([], final_retry["replacement_snapshots"])
            with connection() as audit_connection:
                with audit_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM management_audit "
                        "WHERE tenant_id=%s AND action='TENANT_DISABLED'",
                        (tenant_id,),
                    )
                    self.assertEqual(1, cursor.fetchone()["count"])
            with self.assertRaisesRegex(PermissionError, "tenant is disabled"):
                service.issue_enrollment_challenge(
                    tenant_id, actor_ref="user:test", actor_tenant_id=tenant_id
                )

            no_grant_tenant_id = "8899aabbccddeeff0011223344556677"
            with connection() as legacy_connection:
                with legacy_connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO tenants "
                        "(name, unit_number, ble_device_mac, auth_key, is_active) "
                        "VALUES (%s, %s, %s, %s, TRUE)",
                        ("No Grant", "998", "AA:BB:CC:DD:EE:98", "legacy-two"),
                    )
                    no_grant_legacy_id = cursor.lastrowid
                legacy_connection.commit()
            service.register_tenant(
                no_grant_tenant_id,
                "No Grant",
                int(no_grant_legacy_id),
                actor_ref="admin:test",
            )
            with connection() as legacy_disable_connection:
                with legacy_disable_connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE tenants SET is_active=FALSE WHERE id=%s",
                        (no_grant_legacy_id,),
                    )
                legacy_disable_connection.commit()
            with self.assertRaisesRegex(PermissionError, "tenant is disabled"):
                service.issue_enrollment_challenge(
                    no_grant_tenant_id,
                    actor_ref="user:no-grant",
                    actor_tenant_id=no_grant_tenant_id,
                )
            self.assertEqual("DISABLED", store.tenant_status(no_grant_tenant_id))
            with connection() as legacy_reenable_connection:
                with legacy_reenable_connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE tenants SET is_active=TRUE WHERE id=%s",
                        (no_grant_legacy_id,),
                    )
                legacy_reenable_connection.commit()
            service.register_tenant(
                no_grant_tenant_id,
                "No Grant Renamed",
                int(no_grant_legacy_id),
                actor_ref="admin:test",
            )
            self.assertEqual("DISABLED", store.tenant_status(no_grant_tenant_id))

            approval_id = "c" * 48
            with connection() as control_connection:
                with control_connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO force_open_approvals "
                        "(approval_id,tenant_scope,proposer_subject,reason,idempotency_hash,expires_at,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (approval_id, "legacy:1", "operator-a", "integration approval", "d" * 64, 4_102_444_800, 1),
                    )
                control_connection.commit()

            principal = AdminPrincipal(
                subject="approver-b",
                roles=frozenset({"SECURITY_APPROVER"}),
                tenants=frozenset({"legacy:1"}),
                session_id="integration",
                csrf_token="integration",
                expires_at=4_102_444_800,
            )
            publish_calls: list[str] = []

            def publish_once(label: str) -> bool:
                publish_calls.append(label)
                return True

            def approve_once() -> int:
                try:
                    admin_main.approve_force_open(
                        approval_id,
                        SimpleNamespace(headers={"Idempotency-Key": "mariadb-concurrent"}),
                    )
                    return 200
                except HTTPException as exc:
                    return exc.status_code

            with patch.object(admin_main, "get_db", side_effect=connection), patch.object(
                admin_main, "_admin_principal", return_value=principal
            ), patch.object(admin_main, "publish_force_open_to_mqtt", side_effect=publish_once):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: approve_once(), range(2)))
            self.assertEqual([200, 404], sorted(results))
            self.assertEqual(["authorized-control-plane"], publish_calls)
            with connection() as verification_connection:
                with verification_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM force_open_approvals WHERE approval_id=%s",
                        (approval_id,),
                    )
                    self.assertEqual("PUBLISHED", cursor.fetchone()["status"])
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM admin_audit "
                        "WHERE object_ref=%s AND action='FORCE_OPEN_PUBLISHED'",
                        (approval_id,),
                    )
                    self.assertEqual(1, cursor.fetchone()["count"])
                verification_connection.begin()
                with verification_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT approval_id FROM force_open_approvals WHERE approval_id=%s FOR UPDATE",
                        (approval_id,),
                    )
                    self.assertEqual(approval_id, cursor.fetchone()["approval_id"])
                verification_connection.rollback()

            failed_audit_id = "f" * 48
            with connection() as control_connection:
                with control_connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO force_open_approvals "
                        "(approval_id,tenant_scope,proposer_subject,reason,idempotency_hash,expires_at,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (failed_audit_id, "legacy:1", "operator-a", "audit failure proof", "e" * 64, 4_102_444_800, 1),
                    )
                control_connection.commit()

            real_audit = admin_main._audit_admin

            def fail_only_post_publish(*args: object, **kwargs: object) -> None:
                if args[3] == "FORCE_OPEN_PUBLISHED":
                    raise RuntimeError("injected post-publish audit failure")
                real_audit(*args, **kwargs)

            with patch.object(admin_main, "get_db", side_effect=connection), patch.object(
                admin_main, "_admin_principal", return_value=principal
            ), patch.object(admin_main, "publish_force_open_to_mqtt", return_value=True), patch.object(
                admin_main, "_audit_admin", side_effect=fail_only_post_publish
            ):
                with self.assertRaises(HTTPException) as failed_publish:
                    admin_main.approve_force_open(
                        failed_audit_id,
                        SimpleNamespace(headers={"Idempotency-Key": "mariadb-post-publish-failure"}),
                    )
            self.assertEqual(503, failed_publish.exception.status_code)
            with connection() as verification_connection:
                with verification_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM force_open_approvals WHERE approval_id=%s",
                        (failed_audit_id,),
                    )
                    self.assertEqual("RECONCILIATION_REQUIRED", cursor.fetchone()["status"])
                    cursor.execute(
                        "SELECT action FROM admin_audit WHERE object_ref=%s ORDER BY id",
                        (failed_audit_id,),
                    )
                    self.assertEqual(
                        ["FORCE_OPEN_RECONCILIATION_REQUIRED"],
                        [row["action"] for row in cursor.fetchall()],
                    )
                verification_connection.begin()
                with verification_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT approval_id FROM force_open_approvals WHERE approval_id=%s FOR UPDATE",
                        (failed_audit_id,),
                    )
                    self.assertEqual(failed_audit_id, cursor.fetchone()["approval_id"])
                verification_connection.rollback()

            privacy_principal = AdminPrincipal(
                subject="privacy-admin",
                roles=frozenset({"TENANT_ADMIN"}),
                tenants=frozenset({"legacy:1"}),
                session_id="privacy-integration",
                csrf_token="privacy-integration",
                expires_at=4_102_444_800,
            )

            def delete_once() -> dict:
                return admin_main.delete_expired_privacy_data(
                    admin_main.PrivacyDeletionRequest(
                        policy_version="sgk-retention-v1", before_days=365,
                    ),
                    SimpleNamespace(headers={}),
                    x_tenant_id="legacy:1",
                    idempotency_key="mariadb-privacy-concurrent",
                )

            with patch.object(
                admin_main, "get_db", side_effect=connection
            ), patch.object(
                admin_main, "_admin_principal", return_value=privacy_principal
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    privacy_results = list(pool.map(lambda _: delete_once(), range(2)))
            self.assertEqual(
                ["already_completed", "completed"],
                sorted(item["status"] for item in privacy_results),
            )
            with connection() as privacy_connection:
                with privacy_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT state,request_hash,actor_subject,COUNT(*) AS count "
                        "FROM privacy_deletion_jobs WHERE tenant_scope='legacy:1' "
                        "GROUP BY state,request_hash,actor_subject"
                    )
                    privacy_row = cursor.fetchone()
            self.assertEqual("COMPLETED", privacy_row["state"])
            self.assertRegex(privacy_row["request_hash"], r"^[a-f0-9]{64}$")
            self.assertEqual("privacy-admin", privacy_row["actor_subject"])
            self.assertEqual(1, privacy_row["count"])

            with connection() as consent_connection:
                with consent_connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO support_export_consents "
                        "(consent_ref_hash,tenant_scope,purpose,granted_by,expires_at,created_at) "
                        "VALUES (%s,'legacy:1','support-diagnostics','subject-flow',%s,%s)",
                        ("c" * 64, 4_102_444_800, 1_700_000_000),
                    )
                consent_connection.commit()
                with consent_connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE support_export_consents SET revoked_at=%s "
                        "WHERE consent_ref_hash=%s",
                        (1_700_000_001, "c" * 64),
                    )
                consent_connection.commit()
                with self.assertRaises(pymysql.err.OperationalError):
                    with consent_connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE support_export_consents SET expires_at=%s "
                            "WHERE consent_ref_hash=%s",
                            (4_102_444_801, "c" * 64),
                        )
                consent_connection.rollback()
                with self.assertRaises(pymysql.err.OperationalError):
                    with consent_connection.cursor() as cursor:
                        cursor.execute(
                            "DELETE FROM support_export_consents WHERE consent_ref_hash=%s",
                            ("c" * 64,),
                        )
                consent_connection.rollback()

            # Create an actual logical backup, bind it to the exact software
            # source, restore it into a separate schema, and verify integrity
            # without writing to the restored data.
            dumped = docker(
                "exec", name, "mariadb-dump", "--single-transaction",
                "--routines", "--triggers", "-uroot", f"-p{password}",
                "smart_gatekeeper",
            )
            with tempfile.TemporaryDirectory() as backup_directory:
                dump_path = Path(backup_directory) / "smart_gatekeeper.sql"
                manifest_path = Path(backup_directory) / "manifest.json"
                dump_path.write_text(dumped.stdout, encoding="utf-8")
                with connection() as source_connection:
                    source_inventory = ops_commercial_gate.capture_database_inventory(
                        source_connection
                    )
                ops_commercial_gate.create_backup_manifest(
                    dump_path, manifest_path, "a" * 40, "2026-08-09T00:00:00Z",
                    source_inventory, b"mariadb-backup-manifest-test-key",
                )
                self.assertEqual(
                    "PASS",
                    ops_commercial_gate.verify_backup(
                        dump_path, manifest_path, 900, "2026-08-09T00:10:00Z"
                        , b"mariadb-backup-manifest-test-key"
                    )["status"],
                )
                docker(
                    "exec", name, "mariadb", "-uroot", f"-p{password}",
                    "-e", "DROP DATABASE IF EXISTS smart_gatekeeper_restore; "
                    "CREATE DATABASE smart_gatekeeper_restore CHARACTER SET utf8mb4;",
                )
                def restore_action(timeout_seconds):
                    self.assertEqual(300, timeout_seconds)
                    restored = docker(
                        "exec", "-i", name, "mariadb", "--default-character-set=utf8mb4",
                        "-uroot", f"-p{password}", "smart_gatekeeper_restore",
                        input_text=dumped.stdout, check=False,
                    )
                    if restored.returncode != 0:
                        self.fail(f"isolated logical restore failed: {restored.stderr}")

                def restore_connection():
                    return pymysql.connect(
                        host="127.0.0.1", port=host_port, user="root", password=password,
                        database="smart_gatekeeper_restore",
                        cursorclass=pymysql.cursors.DictCursor, autocommit=False,
                    )

                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                restored_result = ops_commercial_gate.restore_and_verify_database(
                    restore_action, restore_connection, manifest,
                    b"mariadb-backup-manifest-test-key", 300,
                )
                self.assertEqual("PASS", restored_result["status"])
                self.assertGreater(restored_result["rto_seconds"], 0)
                docker(
                    "exec", name, "mariadb", "-uroot", f"-p{password}",
                    "-e", "DROP DATABASE smart_gatekeeper_restore;",
                )

            # The down migration intentionally rejects a live ambiguous state.
            # Remove this disposable fixture only after its durable evidence was
            # asserted so the legacy rollback compatibility proof can proceed.
            with connection() as cleanup_connection:
                with cleanup_connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM force_open_approvals WHERE approval_id=%s",
                        (failed_audit_id,),
                    )
                cleanup_connection.commit()

            rolled_back = docker(
                "exec",
                "-i",
                name,
                "mariadb",
                "--default-character-set=utf8mb4",
                "-uroot",
                f"-p{password}",
                input_text="\n".join((OPS_PRIVACY_DOWN.read_text(encoding="utf-8"), BOOT_STATE_DOWN.read_text(encoding="utf-8"), RECONCILIATION_DOWN.read_text(encoding="utf-8"), CONTROL_V2_DOWN.read_text(encoding="utf-8"), ADMIN_DOWN.read_text(encoding="utf-8"), DOWN.read_text(encoding="utf-8"))),
                check=False,
            )
            if rolled_back.returncode != 0:
                self.fail(f"migration rollback failed: {rolled_back.stderr}")
            after_down = docker(
                "exec",
                name,
                "mariadb",
                "-N",
                "-uroot",
                f"-p{password}",
                "smart_gatekeeper",
                "-e",
                "SELECT auth_key FROM tenants WHERE ble_device_mac='AA:BB:CC:DD:EE:99';",
            )
            self.assertEqual("legacy-only", after_down.stdout.strip())
        finally:
            docker("rm", "-f", name, check=False)


if __name__ == "__main__":
    unittest.main()
