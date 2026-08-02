from __future__ import annotations

import os
import socket
import subprocess
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymysql

from backend.app.acl_management import (
    AclManagementService,
    AclStore,
    DeterministicP256Signer,
    RecordingPublisher,
    build_enrollment_input,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "backend" / "db" / "schema.sql"
UP = ROOT / "backend" / "db" / "migrations" / "002_acl_management_expand_up.sql"
DOWN = ROOT / "backend" / "db" / "migrations" / "002_acl_management_expand_down.sql"


class MigrationContractTest(unittest.TestCase):
    def test_expand_preserves_legacy_columns_and_down_drops_only_new_state(self) -> None:
        up = UP.read_text(encoding="utf-8")
        down = DOWN.read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS tenant_uuid", up)
        self.assertIn("credential_mode", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS credentials", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS credential_door_grants", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS acl_door_state", up)
        self.assertIn("CREATE TABLE IF NOT EXISTS acl_snapshot_jobs", up)
        self.assertIn("UNIQUE KEY uq_acl_door_global (door_id)", up)
        self.assertNotIn("DROP COLUMN ble_device_mac", up)
        self.assertNotIn("DROP COLUMN auth_key", up)
        self.assertNotIn("DROP TABLE IF EXISTS tenants", down)
        self.assertNotIn("DROP TABLE IF EXISTS access_logs", down)
        self.assertEqual(1, down.count("DROP TABLE IF EXISTS credentials;"))
        self.assertEqual(1, down.count("DROP TABLE IF EXISTS acl_snapshot_jobs;"))
        self.assertEqual(1, down.count("DROP TABLE IF EXISTS enrollment_challenges;"))

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
                    "INSERT INTO tenants (name, unit_number, ble_device_mac, auth_key, is_active) "
                    "VALUES ('N-1 client', '999', 'AA:BB:CC:DD:EE:99', 'legacy-only', TRUE);",
                    "INSERT INTO acl_tenants VALUES ('11111111111111111111111111111111', 'tenant', 1);",
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
            credential = service.submit_enrollment(
                tenant_id,
                challenge["enrollment_id"],
                challenge["nonce"],
                mobile.public_key_sec1.hex(),
                mobile.sign(
                    build_enrollment_input(
                        tenant_id,
                        challenge["enrollment_id"],
                        challenge["nonce"],
                        mobile.public_key_sec1.hex(),
                    )
                ).hex(),
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

            docker(
                "exec",
                "-i",
                name,
                "mariadb",
                "-uroot",
                f"-p{password}",
                input_text=DOWN.read_text(encoding="utf-8"),
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
