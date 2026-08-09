#!/usr/bin/env python3
"""Repository-side Issue #52 commercial operations gate.

All commands are deterministic and hardwareless. They never contact production
infrastructure and never convert software evidence into physical acceptance.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_RESTORE_TABLES = {
    "tenants", "access_logs", "admin_audit", "credentials",
    "acl_snapshots", "target_boot_state", "privacy_deletion_jobs",
    "support_export_consents",
}
IMAGE_DIGEST_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$"
)
EVIDENCE_SCOPES = {
    "ops-contract": "local-software",
    "hosted-sbom-attestation": "hosted-ci",
    "isolated-mariadb-restore": "operator-software",
    "24h-load-soak": "physical-live-like",
    "production-deployment": "production",
}
EVIDENCE_STATES = {"pending", "blocked", "passed"}


class GateError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_text_sha256(path: Path) -> str:
    """Hash semantic text identically across LF/CRLF Git checkouts."""
    text = path.read_text(encoding="utf-8")
    canonical = ("\n".join(text.splitlines()) + "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def checked_out_commit() -> str:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise GateError("cannot bind evidence to the checked-out commit") from exc
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise GateError("checked-out commit is not exact 40-hex")
    return commit


def validate_production_images(api_image: str, db_image: str) -> dict:
    for label, value in (("API_IMAGE", api_image), ("DB_IMAGE", db_image)):
        if not IMAGE_DIGEST_PATTERN.fullmatch(value):
            raise GateError(f"{label} must be repository@sha256:<64 lowercase hex>")
    if api_image == db_image:
        raise GateError("API_IMAGE and DB_IMAGE must be distinct immutable artifacts")
    return {"status": "PASS", "api_image": api_image, "db_image": db_image}


def locked_dependencies(lock_path: Path) -> list[tuple[str, str]]:
    dependencies = []
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^ \\]+)\s*\\?$", line)
        if match:
            dependencies.append((match.group(1).lower(), match.group(2)))
    if not dependencies:
        raise GateError("requirements.lock has no exact dependencies")
    content = lock_path.read_text(encoding="utf-8")
    if "--hash=sha256:" not in content:
        raise GateError("requirements.lock is not hash-locked")
    return dependencies


def contract() -> dict:
    dockerfile = (ROOT / "backend/app/Dockerfile").read_text(encoding="utf-8")
    runtime = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    compose = (ROOT / "backend/compose.production.yml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/backend_security.yml").read_text(encoding="utf-8")
    alert_rules = (ROOT / "ops/prometheus_rules.yml").read_text(encoding="utf-8")
    setup_script = (ROOT / ".orca/scripts/setup_worktree.ps1").read_text(encoding="utf-8")
    db_dockerfile = (ROOT / "backend/db/Dockerfile").read_text(encoding="utf-8")
    trusted_inputs = json.loads(
        (ROOT / "ops/backend_trusted_bundle_paths.json").read_text(encoding="utf-8")
    )
    errors = []
    if not re.search(r"^FROM [^\s]+@sha256:[a-f0-9]{64}$", dockerfile, re.MULTILINE):
        errors.append("backend base image is not digest-pinned")
    for required in ("--require-hashes", "USER 10001:10001", "requirements.lock"):
        if required not in dockerfile:
            errors.append(f"Dockerfile missing {required}")
    if re.search(r"subprocess|pip\s*[\"']?,\s*[\"']install", runtime):
        errors.append("runtime package installation remains reachable")
    if "image: mariadb@sha256:" not in compose:
        if "image: ${DB_IMAGE_REPOSITORY:" not in compose or "@sha256:${DB_IMAGE_DIGEST:" not in compose:
            errors.append("production database image does not require an immutable variable")
    if "image: ${API_IMAGE_REPOSITORY:" not in compose or "@sha256:${API_IMAGE_DIGEST:" not in compose:
        errors.append("production API image does not structurally require a digest")
    forbidden_compose = (
        "DB_PASSWORD:-", "DB_ROOT_PASSWORD:-", "MYSQL_PASSWORD:",
        "./app:/app", "./db/", "docker-entrypoint-initdb.d", "build:",
        "ports:", "network_mode: host",
    )
    for forbidden in forbidden_compose:
        if forbidden in compose:
            errors.append(f"production Compose contains forbidden token {forbidden}")
    for required in (
        "read_only: true", "no-new-privileges:true", "cap_drop:",
        "DB_PASSWORD_FILE:", "OPS_HMAC_KEY_FILE:", "internal: true",
        "ACL_MANAGEMENT_ENABLED: \"true\"", "ACL_LEGACY_DEVICE_LOOKUP_ENABLED: \"false\"",
        "127.0.0.1:8000/ready",
    ):
        if required not in compose:
            errors.append(f"production Compose missing {required}")
    action_uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)
    if not action_uses or any(not re.fullmatch(r"[^@]+@[a-f0-9]{40}", use) for use in action_uses):
        errors.append("backend workflow actions are not exact-commit pinned")
    if "python-version: '3.12.13'" not in workflow:
        errors.append("backend workflow Python patch version is not locked")
    if re.search(r"image:\s*[^\s@]+:[^\s]+", workflow):
        errors.append("backend workflow contains a mutable service image")
    for required_path in (
        "'ops/**'", "'scripts/ops_commercial_gate.py'",
        "'.orca/scripts/setup_worktree.ps1'",
    ):
        if workflow.count(required_path) != 2:
            errors.append(f"backend workflow trigger coverage missing {required_path}")
    if not re.search(r"^FROM mariadb@sha256:[a-f0-9]{64}$", db_dockerfile, re.MULTILINE):
        errors.append("migration database image base is not digest-pinned")
    if "COPY migrations/007_ops_privacy_up.sql" not in db_dockerfile:
        errors.append("migration database artifact omits the current privacy migration")
    expected_trusted = {
        ".github/workflows/backend_security.yml",
        ".orca/scripts/setup_worktree.ps1",
        "scripts/ops_commercial_gate.py",
        "ops/backend_trusted_bundle_paths.json",
        "ops/evidence_sources.json",
        "ops/fixtures/load_nominal.jsonl",
        "ops/prometheus_rules.yml",
        "ops/slo_policy.json",
        "backend/app/requirements.lock",
        "backend/compose.production.yml",
        "backend/db/Dockerfile",
        "backend/sbom.cdx.json",
        "backend/supply_chain_policy.json",
        "backend/tests/test_migrations.py",
        "backend/tests/test_ops_api.py",
        "backend/tests/test_ops_commercial_gate.py",
        "backend/tests/test_ops_runtime.py",
    }
    if trusted_inputs.get("schema") != "sgk-backend-trusted-inputs-v1" or set(
        trusted_inputs.get("paths", [])
    ) != expected_trusted:
        errors.append("trusted backend executable/input bundle is incomplete")
    locked_dependencies(ROOT / "backend/app/requirements.lock")
    if "backend\\app\\requirements.lock" not in setup_script or "--require-hashes" not in setup_script:
        errors.append("Orca setup does not install the hash-locked backend environment")
    for alert in (
        "SmartGatekeeperMqttCircuitOpen", "SmartGatekeeperDependencyFailure",
        "SmartGatekeeperControlServerErrors", "SmartGatekeeperSustainedRateLimit",
        "SmartGatekeeperMetricsAbsent",
    ):
        if alert_rules.count(f"alert: {alert}") != 1:
            errors.append(f"missing or duplicate fixed alert {alert}")
    if errors:
        raise GateError("; ".join(errors))
    return {
        "status": "PASS", "checks": 23, "scope": "repository-software-only",
        "trusted_base_rotation": "required-before-merge",
    }


def generate_sbom(output: Path) -> dict:
    lock_path = ROOT / "backend/app/requirements.lock"
    dependencies = locked_dependencies(lock_path)
    policy = json.loads((ROOT / "backend/supply_chain_policy.json").read_text(encoding="utf-8"))
    licenses = policy["dependency_licenses"]
    allowed = set(policy["allowed_licenses"])
    missing = sorted(name for name, _ in dependencies if name not in licenses)
    disallowed = sorted(
        name for name, _ in dependencies if name in licenses and licenses[name] not in allowed
    )
    if missing or disallowed:
        raise GateError(f"license policy incomplete: missing={missing}, disallowed={disallowed}")
    components = [
        {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
            "licenses": [{"license": {"id": licenses[name]}}],
        }
        for name, version in dependencies
    ]
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": (
            f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, _canonical_text_sha256(lock_path))}"
        ),
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "smart-gatekeeper-backend"}},
        "components": components,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sbom


def migration_set_sha256() -> str:
    paths = [ROOT / "backend/db/schema.sql", *sorted(
        (ROOT / "backend/db/migrations").glob("*_up.sql")
    )]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(_canonical_text_sha256(path)))
    return digest.hexdigest()


def _inventory_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def capture_database_inventory(connection) -> dict:
    """Capture schema, PK-ordered row counts and content hashes from one DB."""
    inventory = {}
    with connection.cursor() as cursor:
        for table in sorted(REQUIRED_RESTORE_TABLES):
            cursor.execute(
                "SELECT column_name,column_type,is_nullable,column_default,extra,ordinal_position "
                "FROM information_schema.columns WHERE table_schema=DATABASE() "
                "AND table_name=%s ORDER BY ordinal_position",
                (table,),
            )
            columns = cursor.fetchall()
            if not columns:
                raise GateError(f"source inventory missing table: {table}")
            schema_bytes = json.dumps(
                [{key: _inventory_value(value) for key, value in row.items()} for row in columns],
                sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")
            cursor.execute(
                "SELECT column_name FROM information_schema.statistics "
                "WHERE table_schema=DATABASE() AND table_name=%s AND index_name='PRIMARY' "
                "ORDER BY seq_in_index",
                (table,),
            )
            primary_key = [row["column_name"] for row in cursor.fetchall()]
            if not primary_key:
                raise GateError(f"source inventory table has no primary key: {table}")
            order = ",".join(f"`{column}`" for column in primary_key)
            cursor.execute(f"SELECT * FROM `{table}` ORDER BY {order}")
            content = hashlib.sha256()
            count = 0
            while True:
                rows = cursor.fetchmany(500)
                if not rows:
                    break
                for row in rows:
                    canonical = json.dumps(
                        {key: _inventory_value(value) for key, value in row.items()},
                        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                    ).encode("utf-8")
                    content.update(canonical + b"\n")
                    count += 1
            inventory[table] = {
                "row_count": count,
                "content_sha256": content.hexdigest(),
                "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
                "primary_key": primary_key,
            }
    return inventory


def create_backup_manifest(
    dump: Path,
    output: Path,
    source_commit: str,
    completed_at: str,
    source_inventory: dict,
    manifest_key: bytes,
) -> dict:
    if len(manifest_key) < 32:
        raise GateError("backup manifest authentication key must be at least 32 bytes")
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise GateError("source commit must be exact 40-hex")
    sql = dump.read_text(encoding="utf-8", errors="strict")
    missing = sorted(
        table for table in REQUIRED_RESTORE_TABLES
        if not re.search(
            rf"(?im)^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`{re.escape(table)}`\s*\(",
            sql,
        )
    )
    if missing:
        raise GateError(f"backup is missing required tables: {missing}")
    if set(source_inventory) != REQUIRED_RESTORE_TABLES:
        raise GateError("source database inventory table set is incomplete")
    for table, item in source_inventory.items():
        if set(item) != {"row_count", "content_sha256", "schema_sha256", "primary_key"}:
            raise GateError(f"source inventory schema is invalid: {table}")
        if not isinstance(item["row_count"], int) or item["row_count"] < 0:
            raise GateError(f"source inventory row count is invalid: {table}")
        for digest_key in ("content_sha256", "schema_sha256"):
            if not re.fullmatch(r"[a-f0-9]{64}", item[digest_key]):
                raise GateError(f"source inventory digest is invalid: {table}")
        if not item["primary_key"]:
            raise GateError(f"source inventory primary key is empty: {table}")
    completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    if completed.tzinfo is None:
        raise GateError("backup completion must be timezone-aware")
    manifest = {
        "schema": "sgk-backup-manifest-v2",
        "source_commit": source_commit,
        "completed_at": completed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dump_sha256": _sha256(dump),
        "dump_bytes": dump.stat().st_size,
        "required_tables": sorted(REQUIRED_RESTORE_TABLES),
        "migration_set_sha256": migration_set_sha256(),
        "source_inventory": source_inventory,
    }
    canonical = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    manifest["auth_hmac_sha256"] = hmac.new(
        manifest_key, canonical, hashlib.sha256
    ).hexdigest()
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _verify_manifest_auth(manifest: dict, manifest_key: bytes) -> None:
    if len(manifest_key) < 32:
        raise GateError("backup manifest authentication key must be at least 32 bytes")
    supplied = manifest.get("auth_hmac_sha256")
    if not isinstance(supplied, str) or not re.fullmatch(r"[a-f0-9]{64}", supplied):
        raise GateError("backup manifest authentication is missing")
    unsigned = {key: value for key, value in manifest.items() if key != "auth_hmac_sha256"}
    expected = hmac.new(
        manifest_key,
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise GateError("backup manifest authentication failed")


def verify_backup(
    dump: Path,
    manifest_path: Path,
    max_age_seconds: int,
    now: str,
    manifest_key: bytes,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _verify_manifest_auth(manifest, manifest_key)
    if manifest.get("schema") != "sgk-backup-manifest-v2":
        raise GateError("unsupported backup manifest")
    if _sha256(dump) != manifest.get("dump_sha256") or dump.stat().st_size != manifest.get("dump_bytes"):
        raise GateError("backup bytes do not match the manifest")
    if set(manifest.get("required_tables", [])) != REQUIRED_RESTORE_TABLES:
        raise GateError("backup manifest integrity table set is incomplete")
    if manifest.get("migration_set_sha256") != migration_set_sha256():
        raise GateError("backup migration/schema identity does not match this release")
    if set(manifest.get("source_inventory", {})) != REQUIRED_RESTORE_TABLES:
        raise GateError("backup source inventory is incomplete")
    completed = datetime.fromisoformat(manifest["completed_at"].replace("Z", "+00:00"))
    current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    age = (current - completed).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise GateError("backup violates the configured RPO age")
    return {"status": "PASS", "age_seconds": age, "sha256": manifest["dump_sha256"]}


def verify_restored_database(
    connection,
    manifest: dict,
    manifest_key: bytes,
    measured_rto_seconds: float,
    max_rto_seconds: int,
) -> dict:
    """Read-only integrity and measured-RTO check against an isolated restore."""
    if measured_rto_seconds < 0 or measured_rto_seconds > max_rto_seconds:
        raise GateError("isolated restore violates the configured RTO")
    _verify_manifest_auth(manifest, manifest_key)
    if manifest.get("schema") != "sgk-backup-manifest-v2":
        raise GateError("isolated restore requires a verified v2 backup manifest")
    expected = manifest.get("source_inventory")
    if not isinstance(expected, dict) or set(expected) != REQUIRED_RESTORE_TABLES:
        raise GateError("isolated restore expected inventory is incomplete")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()"
        )
        tables = {row["table_name"] for row in cursor.fetchall()}
        missing = sorted(REQUIRED_RESTORE_TABLES - tables)
        if missing:
            raise GateError(f"isolated restore missing tables: {missing}")
        invariant_queries = {
            "access_log_orphans": (
                "SELECT COUNT(*) AS count FROM access_logs l LEFT JOIN tenants t "
                "ON t.id=l.tenant_id WHERE l.tenant_id IS NOT NULL AND t.id IS NULL"
            ),
            "credential_orphans": (
                "SELECT COUNT(*) AS count FROM credentials c LEFT JOIN acl_tenants t "
                "ON t.tenant_id=c.tenant_id WHERE t.tenant_id IS NULL"
            ),
            "snapshot_orphans": (
                "SELECT COUNT(*) AS count FROM acl_snapshots s LEFT JOIN acl_tenants t "
                "ON t.tenant_id=s.tenant_id WHERE t.tenant_id IS NULL"
            ),
        }
        for name, query in invariant_queries.items():
            cursor.execute(query)
            if int(cursor.fetchone()["count"]) != 0:
                raise GateError(f"isolated restore integrity violation: {name}")
    actual = capture_database_inventory(connection)
    if actual != expected:
        mismatches = sorted(table for table in REQUIRED_RESTORE_TABLES if actual[table] != expected[table])
        raise GateError(f"isolated restore source/target inventory mismatch: {mismatches}")
    return {
        "status": "PASS",
        "rto_seconds": measured_rto_seconds,
        "integrity_counts": {
            table: actual[table]["row_count"] for table in sorted(actual)
        },
        "migration_set_sha256": manifest["migration_set_sha256"],
    }


def evaluate_slo(samples_path: Path, policy_path: Path) -> dict:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    samples = [json.loads(line) for line in samples_path.read_text(encoding="utf-8").splitlines() if line]
    if len(samples) < policy["minimum_samples"]:
        raise GateError("insufficient load samples")
    latencies = sorted(float(row["latency_ms"]) for row in samples)
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
    error_rate = sum(not bool(row["success"]) for row in samples) / len(samples)
    observed = {
        "p95_latency_ms": p95,
        "error_rate": error_rate,
        "max_queue_depth": max(int(row["queue_depth"]) for row in samples),
        "max_reconnect_seconds": max(float(row["reconnect_seconds"]) for row in samples),
        "min_heap_bytes": min(int(row["heap_bytes"]) for row in samples),
    }
    violations = [
        name for name, value in observed.items()
        if (
            name == "min_heap_bytes" and value < policy[name]
        ) or (
            name != "min_heap_bytes" and value > policy[name]
        )
    ]
    if violations:
        raise GateError(f"SLO violations: {violations}")
    return {"status": "PASS", "samples": len(samples), **observed}


def evidence_register(
    source: Path,
    output: Path,
    commit: str,
    *,
    now: datetime | None = None,
    environment: dict[str, str] | None = None,
) -> dict:
    if commit != checked_out_commit():
        raise GateError("evidence commit must equal the checked-out Git commit")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise GateError("evidence validation time must be timezone-aware")
    env = os.environ if environment is None else environment
    source_doc = json.loads(source.read_text(encoding="utf-8"))
    if set(source_doc) != {"schema", "repository", "candidate_author", "evidence"}:
        raise GateError("evidence source has unknown or missing top-level fields")
    if source_doc["schema"] != "sgk-evidence-source-v2":
        raise GateError("unsupported evidence source schema")
    if source_doc["repository"] != "ks-house/smart-gatekeeper":
        raise GateError("evidence repository is not authoritative")
    candidate_author = source_doc["candidate_author"]
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", candidate_author):
        raise GateError("candidate author identity is invalid")
    evidence = source_doc["evidence"]
    if not isinstance(evidence, list) or len(evidence) != len(EVIDENCE_SCOPES):
        raise GateError("evidence source must contain every fixed evidence ID exactly once")
    seen = set()
    expected_keys = {
        "id", "scope", "state", "source_commit", "artifact_sha256",
        "reviewer", "expires_at", "provenance",
    }
    for item in evidence:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise GateError("evidence item has unknown or missing fields")
        evidence_id = item["id"]
        if evidence_id in seen or evidence_id not in EVIDENCE_SCOPES:
            raise GateError(f"unknown or duplicate evidence ID: {evidence_id}")
        seen.add(evidence_id)
        if item["scope"] != EVIDENCE_SCOPES[evidence_id]:
            raise GateError(f"evidence scope mismatch: {evidence_id}")
        if item["state"] not in EVIDENCE_STATES:
            raise GateError(f"unknown evidence state: {evidence_id}")
        proof_fields = (
            item["source_commit"], item["artifact_sha256"], item["reviewer"],
            item["expires_at"], item["provenance"],
        )
        if item["state"] != "passed":
            if any(value is not None for value in proof_fields):
                raise GateError(f"non-passed evidence cannot assert proof: {evidence_id}")
            continue
        if item["source_commit"] != commit:
            raise GateError(f"passed evidence commit mismatch: {evidence_id}")
        digest = item["artifact_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise GateError(f"passed evidence digest is invalid: {evidence_id}")
        reviewer = item["reviewer"]
        if (
            not isinstance(reviewer, str)
            or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", reviewer)
            or reviewer.casefold() == candidate_author.casefold()
        ):
            raise GateError(f"passed evidence reviewer is not independent: {evidence_id}")
        try:
            expiry = datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise GateError(f"passed evidence expiry is not ISO-8601: {evidence_id}") from exc
        if expiry.tzinfo is None or expiry <= current:
            raise GateError(f"passed evidence is expired or unzoned: {evidence_id}")
        provenance = item["provenance"]
        provenance_keys = {
            "provider", "repository", "commit", "run_id", "artifact_name",
            "artifact_sha256",
        }
        if not isinstance(provenance, dict) or set(provenance) != provenance_keys:
            raise GateError(f"passed evidence provenance is incomplete: {evidence_id}")
        if (
            provenance["provider"] != "github-actions"
            or provenance["repository"] != source_doc["repository"]
            or provenance["commit"] != commit
            or provenance["artifact_sha256"] != digest
            or not isinstance(provenance["run_id"], int)
            or provenance["run_id"] <= 0
            or not isinstance(provenance["artifact_name"], str)
            or not provenance["artifact_name"]
        ):
            raise GateError(f"passed evidence provenance does not bind the artifact: {evidence_id}")
        if (
            env.get("GITHUB_ACTIONS") != "true"
            or env.get("GITHUB_SHA") != commit
            or env.get("GITHUB_REPOSITORY") != source_doc["repository"]
            or env.get("GITHUB_RUN_ID") != str(provenance["run_id"])
            or env.get("EVIDENCE_REVIEWER", "").casefold() != reviewer.casefold()
        ):
            raise GateError(f"passed evidence lacks authoritative hosted context: {evidence_id}")
    register = {
        "schema": "sgk-evidence-register-v2",
        "source_commit": commit,
        "generated_at": current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository": source_doc["repository"],
        "candidate_author": candidate_author,
        "evidence": evidence,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(register, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return register


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("contract")
    production = sub.add_parser("production-compose")
    production.add_argument("--api-image", required=True)
    production.add_argument("--db-image", required=True)
    sbom = sub.add_parser("sbom")
    sbom.add_argument("--output", type=Path, required=True)
    backup = sub.add_parser("backup-manifest")
    backup.add_argument("--dump", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--source-commit", required=True)
    backup.add_argument("--completed-at", required=True)
    backup.add_argument("--inventory", type=Path, required=True)
    backup.add_argument("--manifest-key-file", type=Path, required=True)
    verify = sub.add_parser("verify-backup")
    verify.add_argument("--dump", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--max-age-seconds", type=int, required=True)
    verify.add_argument("--now", required=True)
    verify.add_argument("--manifest-key-file", type=Path, required=True)
    restore = sub.add_parser("restore-check")
    restore.add_argument("--host", required=True)
    restore.add_argument("--port", type=int, default=3306)
    restore.add_argument("--database", required=True)
    restore.add_argument("--user", required=True)
    restore.add_argument("--password-file", type=Path, required=True)
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--manifest-key-file", type=Path, required=True)
    restore.add_argument("--measured-rto-seconds", type=float, required=True)
    restore.add_argument("--max-rto-seconds", type=int, required=True)
    inventory = sub.add_parser("inventory")
    inventory.add_argument("--host", required=True)
    inventory.add_argument("--port", type=int, default=3306)
    inventory.add_argument("--database", required=True)
    inventory.add_argument("--user", required=True)
    inventory.add_argument("--password-file", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)
    slo = sub.add_parser("slo")
    slo.add_argument("--samples", type=Path, required=True)
    slo.add_argument("--policy", type=Path, required=True)
    evidence = sub.add_parser("evidence")
    evidence.add_argument("--source", type=Path, required=True)
    evidence.add_argument("--output", type=Path, required=True)
    evidence.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "contract":
            result = contract()
        elif args.command == "production-compose":
            result = validate_production_images(args.api_image, args.db_image)
        elif args.command == "sbom":
            result = {"status": "PASS", "components": len(generate_sbom(args.output)["components"])}
        elif args.command == "backup-manifest":
            source_inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
            result = create_backup_manifest(
                args.dump, args.output, args.source_commit, args.completed_at,
                source_inventory,
                args.manifest_key_file.read_bytes().strip(),
            )
        elif args.command == "verify-backup":
            result = verify_backup(
                args.dump, args.manifest, args.max_age_seconds, args.now,
                args.manifest_key_file.read_bytes().strip(),
            )
        elif args.command in {"restore-check", "inventory"}:
            import pymysql
            password = args.password_file.read_text(encoding="utf-8").strip()
            connection = pymysql.connect(
                host=args.host, port=args.port, user=args.user, password=password,
                database=args.database, cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5, read_timeout=5, write_timeout=5,
            )
            try:
                if args.command == "inventory":
                    result = capture_database_inventory(connection)
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(
                        json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                else:
                    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
                    result = verify_restored_database(
                        connection, manifest,
                        args.manifest_key_file.read_bytes().strip(),
                        args.measured_rto_seconds,
                        args.max_rto_seconds,
                    )
            finally:
                connection.close()
        elif args.command == "slo":
            result = evaluate_slo(args.samples, args.policy)
        else:
            result = evidence_register(args.source, args.output, args.commit)
    except (GateError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"OPS-GATE FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
