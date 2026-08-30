#!/usr/bin/env python3
"""Create a signed, exact-digest Synology backend deployment bundle."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_COMPOSE = ROOT / "backend" / "compose.production.yml"
SYNOLOGY_COMPOSE = ROOT / "backend" / "compose.synology.yml"
SOURCE_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
RUN_PATTERN = re.compile(r"[1-9][0-9]*")
CREATED_PATTERN = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
EXPECTED_REPOSITORIES = {
    "api": "ghcr.io/ks-house/smart-gatekeeper-backend",
    "db": "ghcr.io/ks-house/smart-gatekeeper-db",
}
SCHEMA_MANIFEST = ROOT / "backend" / "db" / "schema.env"
BUNDLE_MEMBERS = (
    "release.env",
    "release.env.sig",
    "compose.production.yml",
    "compose.synology.yml",
)


class BundleError(ValueError):
    """Raised when release inputs do not satisfy the deployment contract."""


def schema_identity() -> tuple[str, str]:
    """Read and verify the repository-owned latest migration identity."""
    try:
        lines = SCHEMA_MANIFEST.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BundleError("schema manifest is unavailable") from exc
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in values:
            raise BundleError("schema manifest is malformed")
        values[key] = value
    if set(values) != {"SCHEMA_VERSION", "SCHEMA_SHA256"}:
        raise BundleError("schema manifest keys are invalid")
    version = values["SCHEMA_VERSION"]
    digest = values["SCHEMA_SHA256"]
    if not re.fullmatch(r"[0-9]{3}", version) or int(version) < 2:
        raise BundleError("schema version is invalid")
    if not DIGEST_PATTERN.fullmatch(digest):
        raise BundleError("schema digest is invalid")
    migration = ROOT / "backend" / "db" / "migrations" / f"{version}_mobile_account_roles_up.sql"
    candidates = sorted((ROOT / "backend" / "db" / "migrations").glob(f"{version}_*_up.sql"))
    if len(candidates) != 1:
        raise BundleError("latest schema migration is missing or ambiguous")
    migration = candidates[0]
    if sha256_file(migration) != digest:
        raise BundleError("schema manifest does not match latest migration")
    return version, digest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_image(value: str, expected_repository: str) -> tuple[str, str]:
    prefix = f"{expected_repository}@sha256:"
    if not value.startswith(prefix):
        raise BundleError(f"image must use {prefix}<64 lowercase hex>")
    digest = value[len(prefix):]
    if not DIGEST_PATTERN.fullmatch(digest):
        raise BundleError("image digest must be exactly 64 lowercase hex")
    return expected_repository, digest


def validated_created_at(value: str | None) -> str:
    if value is None:
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    if not CREATED_PATTERN.fullmatch(value):
        raise BundleError("created-at must be UTC YYYY-MM-DDTHH:MM:SSZ")
    return value


def create_bundle(args: argparse.Namespace) -> dict[str, str]:
    if not SOURCE_PATTERN.fullmatch(args.source_sha):
        raise BundleError("source-sha must be exactly 40 lowercase hex")
    if not RUN_PATTERN.fullmatch(args.github_run_id):
        raise BundleError("github-run-id must be a positive integer")
    if not RUN_PATTERN.fullmatch(args.github_run_attempt):
        raise BundleError("github-run-attempt must be a positive integer")
    api_repository, api_digest = split_image(
        args.api_image, EXPECTED_REPOSITORIES["api"]
    )
    db_repository, db_digest = split_image(
        args.db_image, EXPECTED_REPOSITORIES["db"]
    )
    signing_key = args.signing_key.resolve()
    if not signing_key.is_file():
        raise BundleError("signing key file does not exist")
    for compose in (PRODUCTION_COMPOSE, SYNOLOGY_COMPOSE):
        if not compose.is_file():
            raise BundleError(f"missing deployment input: {compose.name}")
    output = args.output.resolve()
    if output.exists():
        raise BundleError("output bundle already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    created_at = validated_created_at(args.created_at)
    schema_version, schema_sha256 = schema_identity()
    release_id = (
        f"{args.source_sha}-run{args.github_run_id}-attempt{args.github_run_attempt}"
    )

    old_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="sgk-backend-release-") as raw_temp:
            temp = Path(raw_temp)
            production_copy = temp / "compose.production.yml"
            synology_copy = temp / "compose.synology.yml"
            shutil.copyfile(PRODUCTION_COMPOSE, production_copy)
            shutil.copyfile(SYNOLOGY_COMPOSE, synology_copy)
            values = (
                ("FORMAT", "sgk-backend-release-v1"),
                ("RELEASE_ID", release_id),
                ("SOURCE_SHA", args.source_sha),
                ("API_IMAGE_REPOSITORY", api_repository),
                ("API_IMAGE_DIGEST", api_digest),
                ("DB_IMAGE_REPOSITORY", db_repository),
                ("DB_IMAGE_DIGEST", db_digest),
                ("COMPOSE_PRODUCTION_SHA256", sha256_file(production_copy)),
                ("COMPOSE_SYNOLOGY_SHA256", sha256_file(synology_copy)),
                ("SCHEMA_VERSION", schema_version),
                ("SCHEMA_SHA256", schema_sha256),
                ("CREATED_AT_UTC", created_at),
                ("GITHUB_RUN_ID", args.github_run_id),
                ("GITHUB_RUN_ATTEMPT", args.github_run_attempt),
            )
            release_env = temp / "release.env"
            release_env.write_text(
                "".join(f"{key}={value}\n" for key, value in values),
                encoding="utf-8",
                newline="\n",
            )
            signature = temp / "release.env.sig"
            try:
                subprocess.run(
                    [
                        "openssl", "dgst", "-sha256", "-sign", str(signing_key),
                        "-out", str(signature), str(release_env),
                    ],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                raise BundleError("OpenSSL could not sign the release descriptor") from exc
            with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
                for member in BUNDLE_MEMBERS:
                    archive.add(temp / member, arcname=member, recursive=False)
    finally:
        os.umask(old_umask)
    return {
        "release_id": release_id,
        "source_sha": args.source_sha,
        "api_image": args.api_image,
        "db_image": args.db_image,
        "bundle_sha256": sha256_file(output),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--db-image", required=True)
    parser.add_argument("--github-run-id", required=True)
    parser.add_argument("--github-run-attempt", required=True)
    parser.add_argument("--created-at")
    parser.add_argument("--signing-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    try:
        result = create_bundle(parse_args())
    except BundleError as exc:
        print(f"release bundle rejected: {exc}", file=os.sys.stderr)
        return 2
    for key in ("release_id", "source_sha", "api_image", "db_image", "bundle_sha256"):
        print(f"{key}={result[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
