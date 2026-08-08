from __future__ import annotations

import os
import socket
import subprocess
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


class MigrationContractTest(unittest.TestCase):
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
            "mariadb:10.11",
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

            docker(
                "exec",
                "-i",
                name,
                "mariadb",
                "--default-character-set=utf8mb4",
                "-uroot",
                f"-p{password}",
                input_text="\n".join((RECONCILIATION_DOWN.read_text(encoding="utf-8"), CONTROL_V2_DOWN.read_text(encoding="utf-8"), ADMIN_DOWN.read_text(encoding="utf-8"), DOWN.read_text(encoding="utf-8"))),
            )
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
