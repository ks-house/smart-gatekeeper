#!/usr/bin/env python3
"""Restore a verified dump into a disposable localhost-only WSL MariaDB."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pymysql


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import ops_commercial_gate as ops  # noqa: E402


MARIADB_IMAGE = (
    "mariadb@sha256:"
    "be981e4113326ada8d6004174dd09eeaefc03094037f811182a52d4f2e737350"
)


class RestoreError(RuntimeError):
    pass


def docker(*arguments: str, input_file=None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *arguments],
        stdin=input_file,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=input_file is None,
        timeout=timeout,
        check=False,
    )


def require_private_file(path: Path, label: str) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RestoreError(f"{label} must be an absolute non-symlink regular file")
    if path.stat().st_mode & 0o077:
        raise RestoreError(f"{label} must not be accessible by group or other users")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-key-file", type=Path, required=True)
    parser.add_argument("--root-password-file", type=Path, required=True)
    parser.add_argument("--container-name", default="sgk-restore-lab")
    parser.add_argument("--result-output", type=Path, required=True)
    parser.add_argument("--max-rto-seconds", type=int, default=300)
    parser.add_argument("--max-backup-age-seconds", type=int, default=86400)
    args = parser.parse_args()

    try:
        if "microsoft" not in Path("/proc/sys/kernel/osrelease").read_text().lower():
            raise RestoreError("this restore harness must run inside WSL")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,62}", args.container_name):
            raise RestoreError("container name is invalid")
        for path, label in (
            (args.dump, "dump"),
            (args.manifest, "manifest"),
            (args.manifest_key_file, "manifest key"),
            (args.root_password_file, "root password"),
        ):
            require_private_file(path, label)
        password = args.root_password_file.read_text(encoding="utf-8").strip()
        if len(password) < 32 or any(character in password for character in "\r\n\0"):
            raise RestoreError("root password file is invalid")
        if docker("inspect", args.container_name).returncode == 0:
            raise RestoreError("restore container already exists; refusing to replace it")
        volume_name = f"{args.container_name}-data"
        if docker("volume", "inspect", volume_name).returncode == 0:
            raise RestoreError("restore data volume already exists; refusing to replace it")

        manifest_key = args.manifest_key_file.read_bytes().strip()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        verified = ops.verify_backup(
            args.dump,
            args.manifest,
            args.max_backup_age_seconds,
            now,
            manifest_key,
        )
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

        created = docker("volume", "create", volume_name)
        if created.returncode != 0:
            raise RestoreError("could not create isolated restore volume")
        started = docker(
            "run", "--detach", "--name", args.container_name,
            "--mount", f"type=volume,source={volume_name},target=/var/lib/mysql",
            "--mount", (
                f"type=bind,source={args.root_password_file},"
                "target=/run/secrets/root-password,readonly"
            ),
            "--publish", "127.0.0.1::3306",
            "--env", "MARIADB_ROOT_PASSWORD_FILE=/run/secrets/root-password",
            "--env", "MARIADB_DATABASE=smart_gatekeeper",
            MARIADB_IMAGE,
            timeout=180,
        )
        if started.returncode != 0:
            raise RestoreError("could not start isolated MariaDB container")

        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            ready = docker(
                "exec", args.container_name, "sh", "-eu", "-c",
                'export MYSQL_PWD="$(cat /run/secrets/root-password)"; '
                'test "$(mariadb --user=root --batch --skip-column-names '
                '--execute="SELECT @@port")" = "3306"',
                timeout=10,
            )
            if ready.returncode == 0:
                break
            state = docker("inspect", "--format", "{{.State.Running}}", args.container_name)
            if state.returncode != 0 or state.stdout.strip() != "true":
                raise RestoreError("isolated MariaDB exited before readiness")
            time.sleep(2)
        else:
            raise RestoreError("isolated MariaDB readiness timed out")

        port_result = docker("port", args.container_name, "3306/tcp")
        if port_result.returncode != 0:
            raise RestoreError("could not resolve localhost restore port")
        match = re.fullmatch(r"127\.0\.0\.1:([0-9]{1,5})", port_result.stdout.strip())
        if not match:
            raise RestoreError("restore database is not bound only to IPv4 localhost")
        port = int(match.group(1))

        def connection_factory():
            return pymysql.connect(
                host="127.0.0.1",
                port=port,
                user="root",
                password=password,
                database="smart_gatekeeper",
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5,
                read_timeout=30,
                write_timeout=30,
            )

        def restore_action(timeout_seconds: int) -> None:
            with args.dump.open("rb") as source:
                restored = docker(
                    "exec", "-i", args.container_name, "sh", "-eu", "-c",
                    'export MYSQL_PWD="$(cat /run/secrets/root-password)"; '
                    'exec mariadb --user=root --default-character-set=utf8mb4 smart_gatekeeper',
                    input_file=source,
                    timeout=timeout_seconds,
                )
            if restored.returncode != 0:
                raise ops.GateError("isolated MariaDB import failed")

        result = ops.restore_and_verify_database(
            restore_action,
            connection_factory,
            manifest,
            manifest_key,
            args.max_rto_seconds,
        )
        result.update(
            {
                "backup_age_seconds": verified["age_seconds"],
                "container_name": args.container_name,
                "database_bind": f"127.0.0.1:{port}",
                "data_volume": volume_name,
                "image": MARIADB_IMAGE,
                "scope": "isolated-wsl-restore-only",
                "source_commit": manifest["source_commit"],
            }
        )
        args.result_output.parent.mkdir(parents=True, exist_ok=True)
        args.result_output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(args.result_output, 0o600)
        print("[PASS] isolated WSL MariaDB restore matches the NAS source inventory")
        print(f"source_commit={manifest['source_commit']}")
        print(f"rto_seconds={result['rto_seconds']:.3f}")
        print(f"container_name={args.container_name}")
        print(f"database_bind=127.0.0.1:{port}")
        print(f"result_output={args.result_output}")
        print("production_database=unchanged")
        print("restore_lab_cleanup=owner_decision_required")
        return 0
    except (
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
        pymysql.MySQLError,
        ops.GateError,
        RestoreError,
    ) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        print("[INFO] any created restore container or volume was preserved for diagnosis", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
