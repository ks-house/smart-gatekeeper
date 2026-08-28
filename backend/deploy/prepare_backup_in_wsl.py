#!/usr/bin/env python3
"""Verify a NAS export, authenticate its manifest, and encrypt it in WSL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import ops_commercial_gate as ops  # noqa: E402


MEMBERS = ("database.sql", "source-inventory.json", "metadata.env")
METADATA_KEYS = {
    "BACKUP_ID",
    "SOURCE_COMMIT",
    "COMPLETED_AT",
    "DUMP_SHA256",
    "DUMP_BYTES",
}


class PrepareError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_private_regular_file(path: Path, label: str) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PrepareError(f"{label} must be an absolute non-symlink regular file")
    if path.stat().st_mode & 0o077:
        raise PrepareError(f"{label} must not be accessible by group or other users")


def write_new_secret(path: Path) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, (secrets.token_hex(32) + "\n").encode("ascii"))
    finally:
        os.close(descriptor)


def read_metadata(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([A-Za-z0-9:._-]+)", line)
        if not match or match.group(1) in result:
            raise PrepareError("backup metadata is malformed")
        result[match.group(1)] = match.group(2)
    if set(result) != METADATA_KEYS:
        raise PrepareError("backup metadata key set is invalid")
    if not re.fullmatch(r"pre-cutover-[0-9]{8}T[0-9]{6}Z-[0-9]+", result["BACKUP_ID"]):
        raise PrepareError("backup identity is invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", result["SOURCE_COMMIT"]):
        raise PrepareError("source commit is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", result["DUMP_SHA256"]):
        raise PrepareError("dump digest is invalid")
    if not result["DUMP_BYTES"].isdigit() or int(result["DUMP_BYTES"]) <= 0:
        raise PrepareError("dump size is invalid")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--key-dir", type=Path, required=True)
    parser.add_argument("--max-age-seconds", type=int, default=3600)
    args = parser.parse_args()

    try:
        if "microsoft" not in Path("/proc/sys/kernel/osrelease").read_text().lower():
            raise PrepareError("this preparation path must run inside WSL")
        require_private_regular_file(args.bundle, "bundle")
        require_private_regular_file(args.sidecar, "sidecar")
        sidecar = args.sidecar.read_text(encoding="ascii").strip()
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", sidecar)
        if not match or match.group(2) != args.bundle.name:
            raise PrepareError("bundle sidecar identity is invalid")
        if not secrets.compare_digest(match.group(1), sha256_file(args.bundle)):
            raise PrepareError("bundle digest does not match its sidecar")

        for directory, label in (
            (args.work_dir, "work directory"),
            (args.key_dir, "key directory"),
        ):
            if not directory.is_absolute() or directory.is_symlink():
                raise PrepareError(f"{label} must be an absolute non-symlink path")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not directory.is_dir():
                raise PrepareError(f"{label} is not a directory")
            os.chmod(directory, 0o700)

        with tarfile.open(args.bundle, "r:gz") as archive:
            members = archive.getmembers()
            if tuple(member.name for member in members) != MEMBERS:
                raise PrepareError("backup bundle member set or order is invalid")
            if any(not member.isfile() or member.name != Path(member.name).name for member in members):
                raise PrepareError("backup bundle contains a non-regular or nested member")
            metadata_member = archive.extractfile("metadata.env")
            if metadata_member is None:
                raise PrepareError("backup metadata is unavailable")
            metadata_bytes = metadata_member.read()

        staging_metadata = args.work_dir / ".metadata.env"
        if staging_metadata.exists():
            raise PrepareError("temporary metadata path already exists")
        staging_metadata.write_bytes(metadata_bytes)
        try:
            metadata = read_metadata(staging_metadata)
        finally:
            staging_metadata.unlink(missing_ok=True)

        extract_dir = args.work_dir / metadata["BACKUP_ID"]
        if extract_dir.exists():
            raise PrepareError("backup extraction directory already exists")
        extract_dir.mkdir(mode=0o700)
        with tarfile.open(args.bundle, "r:gz") as archive:
            for name in MEMBERS:
                source = archive.extractfile(name)
                if source is None:
                    raise PrepareError("backup member is unavailable")
                destination = extract_dir / name
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)

        dump = extract_dir / "database.sql"
        inventory = extract_dir / "source-inventory.json"
        metadata_path = extract_dir / "metadata.env"
        if sha256_file(dump) != metadata["DUMP_SHA256"] or dump.stat().st_size != int(metadata["DUMP_BYTES"]):
            raise PrepareError("dump bytes do not match NAS metadata")

        manifest_key = args.key_dir / "backup-manifest-hmac.key"
        encryption_key = args.key_dir / "backup-encryption-passphrase.key"
        restore_root_password = args.key_dir / "restore-mariadb-root-password.key"
        for key in (manifest_key, encryption_key, restore_root_password):
            if not key.exists():
                write_new_secret(key)
            require_private_regular_file(key, "backup key")

        manifest = extract_dir / "backup-manifest.json"
        ops.create_backup_manifest(
            dump,
            manifest,
            metadata["SOURCE_COMMIT"],
            metadata["COMPLETED_AT"],
            json.loads(inventory.read_text(encoding="utf-8")),
            manifest_key.read_bytes().strip(),
        )
        os.chmod(manifest, 0o600)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        verified = ops.verify_backup(
            dump,
            manifest,
            args.max_age_seconds,
            now,
            manifest_key.read_bytes().strip(),
        )

        encrypted = args.bundle.with_suffix(args.bundle.suffix + ".gpg")
        if encrypted.exists():
            raise PrepareError("encrypted backup output already exists")
        completed = subprocess.run(
            [
                "gpg", "--batch", "--yes", "--no-symkey-cache",
                "--pinentry-mode", "loopback", "--cipher-algo", "AES256",
                "--passphrase-file", str(encryption_key),
                "--symmetric", "--output", str(encrypted), str(args.bundle),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            encrypted.unlink(missing_ok=True)
            raise PrepareError("GPG backup encryption failed")
        os.chmod(encrypted, 0o600)
        print("[PASS] authenticated manifest and encrypted WSL backup created")
        print(f"backup_id={metadata['BACKUP_ID']}")
        print(f"source_commit={metadata['SOURCE_COMMIT']}")
        print(f"dump_bytes={dump.stat().st_size}")
        print(f"backup_age_seconds={verified['age_seconds']:.0f}")
        print(f"extract_dir={extract_dir}")
        print(f"manifest={manifest}")
        print(f"encrypted_bundle={encrypted}")
        print(f"restore_root_password_file={restore_root_password}")
        print("plaintext_cleanup=deferred_until_isolated_restore_passes")
        print("next_gate=isolated WSL MariaDB restore and exact inventory verification")
        return 0
    except (OSError, ValueError, tarfile.TarError, ops.GateError, PrepareError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
