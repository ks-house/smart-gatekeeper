from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from backend.deploy import create_release_bundle, prepare_backup_in_wsl


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "backend" / "deploy" / "create_release_bundle.py"
BOOTSTRAP = ROOT / "backend" / "deploy" / "bootstrap_legacy_synology.sh"
LEGACY_VERIFY = ROOT / "backend" / "deploy" / "verify_legacy_synology.sh"
LEGACY_BACKUP = ROOT / "backend" / "deploy" / "create_legacy_backup.sh"
LEGACY_INVENTORY = ROOT / "backend" / "deploy" / "capture_legacy_inventory.py"
WSL_PREPARE = ROOT / "backend" / "deploy" / "prepare_backup_in_wsl.py"
WSL_RESTORE = ROOT / "backend" / "deploy" / "restore_backup_in_wsl.py"
WRAPPER = ROOT / "backend" / "deploy" / "sgk_backend_deploy.sh"
DISPATCHER = ROOT / "backend" / "deploy" / "sgk_backend_ssh_dispatch.sh"
PRODUCTION_COMPOSE = ROOT / "backend" / "compose.production.yml"
SYNOLOGY_COMPOSE = ROOT / "backend" / "compose.synology.yml"
RUNTIME_EXAMPLE = ROOT / "backend" / "deploy" / "runtime.env.example"


class NasBackendDeployContractTest(unittest.TestCase):
    def signing_key(self, directory: Path) -> tuple[Path, Path]:
        private_key = directory / "release-private.pem"
        public_key = directory / "release-public.pem"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "EC",
                "-pkeyopt",
                "ec_paramgen_curve:P-256",
                "-out",
                str(private_key),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "openssl",
                "pkey",
                "-in",
                str(private_key),
                "-pubout",
                "-out",
                str(public_key),
            ],
            check=True,
            capture_output=True,
        )
        return private_key, public_key

    def bundle_args(self, directory: Path, signing_key: Path) -> argparse.Namespace:
        return argparse.Namespace(
            source_sha="a" * 40,
            api_image=(
                "ghcr.io/ks-house/smart-gatekeeper-backend@sha256:" + "b" * 64
            ),
            db_image="ghcr.io/ks-house/smart-gatekeeper-db@sha256:" + "c" * 64,
            github_run_id="12345",
            github_run_attempt="2",
            created_at="2026-08-28T14:00:00Z",
            signing_key=signing_key,
            output=directory / "backend-release.tar.gz",
        )

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
    def test_signed_bundle_has_exact_members_hashes_and_verifiable_descriptor(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            private_key, public_key = self.signing_key(directory)
            args = self.bundle_args(directory, private_key)
            result = create_release_bundle.create_bundle(args)

            self.assertEqual("a" * 40 + "-run12345-attempt2", result["release_id"])
            self.assertRegex(result["bundle_sha256"], r"^[0-9a-f]{64}$")
            extracted = directory / "extracted"
            extracted.mkdir()
            with tarfile.open(args.output, "r:gz") as archive:
                self.assertEqual(
                    list(create_release_bundle.BUNDLE_MEMBERS), archive.getnames()
                )
                archive.extractall(extracted, filter="data")
            verified = subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(public_key),
                    "-signature",
                    str(extracted / "release.env.sig"),
                    str(extracted / "release.env"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, verified.returncode, verified.stderr)
            descriptor = (extracted / "release.env").read_text(encoding="utf-8")
            self.assertIn(
                "COMPOSE_PRODUCTION_SHA256="
                + create_release_bundle.sha256_file(PRODUCTION_COMPOSE),
                descriptor,
            )
            self.assertIn(
                "COMPOSE_SYNOLOGY_SHA256="
                + create_release_bundle.sha256_file(SYNOLOGY_COMPOSE),
                descriptor,
            )
            (extracted / "release.env").write_text(
                descriptor.replace("SOURCE_SHA=" + "a" * 40, "SOURCE_SHA=" + "d" * 40),
                encoding="utf-8",
            )
            tampered = subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(public_key),
                    "-signature",
                    str(extracted / "release.env.sig"),
                    str(extracted / "release.env"),
                ],
                capture_output=True,
            )
            self.assertNotEqual(0, tampered.returncode)

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
    def test_bundle_rejects_wrong_repository_mutable_identity_and_overwrite(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            private_key, _ = self.signing_key(directory)
            args = self.bundle_args(directory, private_key)
            args.api_image = "ghcr.io/attacker/api@sha256:" + "b" * 64
            with self.assertRaises(create_release_bundle.BundleError):
                create_release_bundle.create_bundle(args)
            args = self.bundle_args(directory, private_key)
            create_release_bundle.create_bundle(args)
            with self.assertRaisesRegex(create_release_bundle.BundleError, "already exists"):
                create_release_bundle.create_bundle(args)

    def test_synology_overlay_is_loopback_only_and_requires_named_external_volumes(self):
        overlay = SYNOLOGY_COMPOSE.read_text(encoding="utf-8")
        self.assertIn("host_ip: 127.0.0.1", overlay)
        self.assertIn('published: "${SGK_API_LOOPBACK_PORT:-8000}"', overlay)
        for variable in (
            "MARIADB_DATA_VOLUME",
            "API_STATE_VOLUME",
            "APK_ARTIFACTS_VOLUME",
            "MIGRATION_BACKUPS_VOLUME",
        ):
            self.assertIn(f"name: ${{{variable}:?", overlay)
        self.assertNotIn("0.0.0.0", overlay)
        self.assertNotIn("3306", overlay)
        production = PRODUCTION_COMPOSE.read_text(encoding="utf-8")
        self.assertNotIn("ports:", production)

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose is required")
    def test_synology_overlay_renders_with_exact_images_and_file_secrets(self):
        environment = os.environ.copy()
        environment.update(
            {
                "API_IMAGE_REPOSITORY": "ghcr.io/ks-house/smart-gatekeeper-backend",
                "API_IMAGE_DIGEST": "a" * 64,
                "DB_IMAGE_REPOSITORY": "ghcr.io/ks-house/smart-gatekeeper-db",
                "DB_IMAGE_DIGEST": "b" * 64,
                "MQTT_HOST": "broker.invalid",
                "MQTT_USER": "ci",
                "DB_RUNTIME_USER": "gatekeeper_runtime",
                "COMMAND_TARGET_ID": "target",
                "COMMAND_TENANT_ID": "tenant",
                "COMMAND_DOOR_ID": "door",
                "COMMAND_SIGNING_KEY_ID": "1",
                "ADMIN_TRUSTED_PROXY_IPS": "127.0.0.1",
                "ACL_SIGNING_KEY_ID": "1",
                "BUILD_SHA": "c" * 40,
                "SGK_SECRET_DIR": "/tmp/sgk-ci-secrets",
                "MARIADB_DATA_VOLUME": "existing-db",
                "API_STATE_VOLUME": "api-state",
                "APK_ARTIFACTS_VOLUME": "apk-artifacts",
                "MIGRATION_BACKUPS_VOLUME": "migration-backups",
            }
        )
        rendered = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(PRODUCTION_COMPOSE),
                "-f",
                str(SYNOLOGY_COMPOSE),
                "config",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
        )
        if "compose" in rendered.stderr.lower() and rendered.returncode == 125:
            self.skipTest("Docker Compose plugin is unavailable")
        self.assertEqual(0, rendered.returncode, rendered.stderr)
        self.assertIn("host_ip: 127.0.0.1", rendered.stdout)
        self.assertIn("file: /tmp/sgk-ci-secrets/db_password", rendered.stdout)
        self.assertIn(
            "file: /tmp/sgk-ci-secrets/personal_admin_password", rendered.stdout
        )
        self.assertIn(
            "image: ghcr.io/ks-house/smart-gatekeeper-backend@sha256:" + "a" * 64,
            rendered.stdout,
        )

    def test_restricted_wrapper_has_fail_closed_command_and_release_contract(self):
        syntax = subprocess.run(
            ["bash", "-n", str(WRAPPER)], text=True, capture_output=True
        )
        self.assertEqual(0, syntax.returncode, syntax.stderr)
        rejected = subprocess.run(
            ["bash", str(WRAPPER), "sh -c id"], text=True, capture_output=True
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("allowed commands: apply or status", rejected.stderr)
        wrapper = WRAPPER.read_text(encoding="utf-8")
        for required in (
            "SSH_ORIGINAL_COMMAND",
            '[[ "$base_mode" == "711" ]]',
            '"0:0:755"',
            'chmod 711 "$DEPLOY_BASE"',
            "/var/packages/ContainerManager/target/usr/bin/docker",
            "/var/packages/Docker/target/usr/bin/docker",
            '"$DOCKER_BIN" "$@"',
            'openssl dgst -sha256 -verify "$TRUST_KEY"',
            'docker volume inspect "${RUNTIME[$key]}"',
            'docker pull "$api_image"',
            'docker pull "$db_image"',
            'verify_running_image "$release_dir" db "$db_image"',
            'verify_running_image "$release_dir" api "$api_image"',
            "database rollback was not attempted",
            "http://127.0.0.1:",
            "SGK_PUBLIC_READY_URL",
        ):
            self.assertIn(required, wrapper)
        self.assertNotRegex(wrapper, r"(?m)^\s*eval\s+")
        self.assertNotRegex(wrapper, r"(?m)^\s*(source|\.)\s+")
        self.assertNotIn('chmod 700 "$DEPLOY_BASE"', wrapper)
        self.assertNotIn("required command is missing: docker", wrapper)

        dispatcher_syntax = subprocess.run(
            ["bash", "-n", str(DISPATCHER)], text=True, capture_output=True
        )
        self.assertEqual(0, dispatcher_syntax.returncode, dispatcher_syntax.stderr)
        dispatcher = DISPATCHER.read_text(encoding="utf-8")
        self.assertIn('case "$REQUESTED" in', dispatcher)
        self.assertIn("apply|status)", dispatcher)
        self.assertIn('exec sudo -n "$WRAPPER" "$REQUESTED"', dispatcher)

    def test_legacy_bootstrap_is_no_cutover_and_preserves_exact_observed_state(self):
        syntax = subprocess.run(
            ["bash", "-n", str(BOOTSTRAP)], text=True, capture_output=True
        )
        self.assertEqual(0, syntax.returncode, syntax.stderr)
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        for required in (
            'readonly LEGACY_API="gatekeeper-api"',
            'readonly LEGACY_DB="gatekeeper-db"',
            'readonly MARIADB_VOLUME="smart_gatekeeper_mariadb_data"',
            'readonly APK_SOURCE="/volume1/docker/smartbox_ota/gatekeeper_apk"',
            "/var/packages/ContainerManager/target/usr/bin/docker",
            "c5668365bd130ec42c7f49aafc53491b1a6ad3a3eb4858f3215b83de3505ece9",
            "personal_admin_password",
            "API and DB runtime passwords do not match",
            "legacy_containers=unchanged",
            'install -d -o root -g root -m 711 "$DEPLOY_BASE"',
            'install -d -o root -g root -m 700 "$SECRET_DIR" "$MIGRATION_BACKUP_DIR"',
        ):
            self.assertIn(required, bootstrap)
        self.assertNotIn(
            'install -d -o root -g root -m 700 "$DEPLOY_BASE"', bootstrap
        )
        self.assertNotRegex(
            bootstrap,
            r'(?m)^\s*local\s+.*\b([A-Za-z_][A-Za-z0-9_]*)="\$[0-9]+".*\$\{\1\}',
        )
        self.assertNotRegex(bootstrap, r"docker\s+(stop|restart|rm)\b")
        self.assertNotIn("docker compose down", bootstrap)

    def test_legacy_verify_is_read_only_and_reports_only_aggregate_acl_state(self):
        syntax = subprocess.run(
            ["bash", "-n", str(LEGACY_VERIFY)], text=True, capture_output=True
        )
        self.assertEqual(0, syntax.returncode, syntax.stderr)
        verifier = LEGACY_VERIFY.read_text(encoding="utf-8")
        for required in (
            "secret_file_contracts=",
            "external_volume_contracts=3_passed",
            "active_credentials=",
            "acl_snapshots=",
            "applied_acl_acks=",
            "identity_all_exact",
            "exact_identity_path_present_owner_decision_required",
            "off-NAS backup restore before migration/cutover",
        ):
            self.assertIn(required, verifier)
        self.assertNotRegex(
            verifier,
            r"docker\s+(stop|restart|rm|create|run|pull|start)\b",
        )
        self.assertNotRegex(verifier, r"(?i)\b(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE)\b")
        self.assertIn(
            'require_directory_contract "$DEPLOY_BASE" 0 0 711', verifier
        )

    def test_legacy_backup_is_consistent_no_cutover_and_identifier_free(self):
        syntax = subprocess.run(
            ["bash", "-n", str(LEGACY_BACKUP)], text=True, capture_output=True
        )
        self.assertEqual(0, syntax.returncode, syntax.stderr)
        backup = LEGACY_BACKUP.read_text(encoding="utf-8")
        for required in (
            "--single-transaction",
            "--quick",
            "--routines --triggers --events --hex-blob",
            "required database tables changed during backup",
            'cmp -s "$inventory_before" "$inventory_after"',
            'readonly LEGACY_API="gatekeeper-api"',
            'readonly LEGACY_DB="gatekeeper-db"',
            "export directory owner does not match export owner",
            "legacy_containers=running_unchanged",
            "authenticated transfer encryption and isolated WSL restore",
        ):
            self.assertIn(required, backup)
        self.assertNotRegex(backup, r"docker\s+(stop|restart|rm|pull|run|start)\b")
        self.assertNotRegex(backup, r"(?i)\b(INSERT|UPDATE|DELETE|ALTER|DROP)\b")
        self.assertNotIn("getent", backup)

        inventory = LEGACY_INVENTORY.read_text(encoding="utf-8")
        for table in (
            "tenants",
            "access_logs",
            "admin_audit",
            "credentials",
            "acl_snapshots",
            "target_boot_state",
            "privacy_deletion_jobs",
            "support_export_consents",
        ):
            self.assertIn(f'"{table}"', inventory)
        self.assertIn('{"bytes_hex": value.hex()}', inventory)
        self.assertIn('cursor.execute("SET TRANSACTION READ ONLY")', inventory)
        self.assertIn(
            'cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")', inventory
        )
        self.assertNotRegex(
            inventory,
            r"(?i)cursor\.execute\(\s*f?['\"]\s*(INSERT|UPDATE|DELETE|ALTER|DROP)\b",
        )

    def test_wsl_backup_path_is_authenticated_encrypted_and_localhost_only(self):
        prepare = WSL_PREPARE.read_text(encoding="utf-8")
        for required in (
            "bundle digest does not match its sidecar",
            "ops.create_backup_manifest(",
            "ops.verify_backup(",
            '"--cipher-algo", "AES256"',
            '"--passphrase-file", str(encryption_key)',
            "plaintext_cleanup=deferred_until_isolated_restore_passes",
        ):
            self.assertIn(required, prepare)

        restore = WSL_RESTORE.read_text(encoding="utf-8")
        for required in (
            "be981e4113326ada8d6004174dd09eeaefc03094037f811182a52d4f2e737350",
            '"--publish", "127.0.0.1::3306"',
            '--execute="SELECT @@port"',
            "ops.restore_and_verify_database(",
            "isolated-wsl-restore-only",
            "production_database=unchanged",
            "restore_lab_cleanup=owner_decision_required",
        ):
            self.assertIn(required, restore)
        self.assertNotRegex(restore, r'docker\([^\n]*"(rm|stop)"')
        self.assertNotIn('"volume", "rm"', restore)

    def test_wsl_backup_metadata_accepts_digest_key_digits(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            metadata = Path(raw_directory) / "metadata.env"
            metadata.write_text(
                "BACKUP_ID=pre-cutover-20260828T155308Z-9349\n"
                "SOURCE_COMMIT=7c2764a1a16492ec1620079c8211b47287b1b3fd\n"
                "COMPLETED_AT=2026-08-28T15:53:09Z\n"
                "DUMP_SHA256=" + "a" * 64 + "\n"
                "DUMP_BYTES=792678\n",
                encoding="utf-8",
            )
            parsed = prepare_backup_in_wsl.read_metadata(metadata)
            self.assertEqual("a" * 64, parsed["DUMP_SHA256"])
            self.assertEqual("792678", parsed["DUMP_BYTES"])

    def test_runtime_example_contains_no_secret_values(self):
        runtime = RUNTIME_EXAMPLE.read_text(encoding="utf-8")
        for forbidden in (
            "DB_PASSWORD=",
            "DB_ROOT_PASSWORD=",
            "MQTT_PASSWORD=",
            "API_KEY=",
            "PERSONAL_ADMIN_PASSWORD=",
            "PRIVATE_SCALAR",
        ):
            self.assertNotIn(forbidden, runtime)
        self.assertIn("MARIADB_DATA_VOLUME=replace-existing-mariadb-volume", runtime)
        self.assertIn("DB_RUNTIME_USER=replace-with-existing-db-user", runtime)


if __name__ == "__main__":
    unittest.main()
