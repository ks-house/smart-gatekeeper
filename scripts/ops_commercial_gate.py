#!/usr/bin/env python3
"""Repository-side Issue #52 commercial operations gate.

All commands are deterministic and hardwareless. They never contact production
infrastructure and never convert software evidence into physical acceptance.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_RESTORE_TABLES = {
    "tenants", "access_logs", "admin_audit", "credentials",
    "acl_snapshots", "target_boot_state", "privacy_deletion_jobs",
}


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
    errors = []
    if not re.search(r"^FROM [^\s]+@sha256:[a-f0-9]{64}$", dockerfile, re.MULTILINE):
        errors.append("backend base image is not digest-pinned")
    for required in ("--require-hashes", "USER 10001:10001", "requirements.lock"):
        if required not in dockerfile:
            errors.append(f"Dockerfile missing {required}")
    if re.search(r"subprocess|pip\s*[\"']?,\s*[\"']install", runtime):
        errors.append("runtime package installation remains reachable")
    if "image: mariadb@sha256:" not in compose:
        errors.append("production database image is not digest-pinned")
    forbidden_compose = (
        "DB_PASSWORD:-", "DB_ROOT_PASSWORD:-", "MYSQL_PASSWORD:",
        "./app:/app", "build:", "ports:", "network_mode: host",
    )
    for forbidden in forbidden_compose:
        if forbidden in compose:
            errors.append(f"production Compose contains forbidden token {forbidden}")
    for required in (
        "read_only: true", "no-new-privileges:true", "cap_drop:",
        "DB_PASSWORD_FILE:", "OPS_HMAC_KEY_FILE:", "internal: true",
    ):
        if required not in compose:
            errors.append(f"production Compose missing {required}")
    action_uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)
    if not action_uses or any(not re.fullmatch(r"[^@]+@[a-f0-9]{40}", use) for use in action_uses):
        errors.append("backend workflow actions are not exact-commit pinned")
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
    return {"status": "PASS", "checks": 13, "scope": "repository-software-only"}


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


def create_backup_manifest(dump: Path, output: Path, source_commit: str, completed_at: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise GateError("source commit must be exact 40-hex")
    sql = dump.read_text(encoding="utf-8", errors="strict")
    missing = sorted(table for table in REQUIRED_RESTORE_TABLES if table not in sql)
    if missing:
        raise GateError(f"backup is missing required tables: {missing}")
    completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    if completed.tzinfo is None:
        raise GateError("backup completion must be timezone-aware")
    manifest = {
        "schema": "sgk-backup-manifest-v1",
        "source_commit": source_commit,
        "completed_at": completed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dump_sha256": _sha256(dump),
        "dump_bytes": dump.stat().st_size,
        "required_tables": sorted(REQUIRED_RESTORE_TABLES),
    }
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_backup(dump: Path, manifest_path: Path, max_age_seconds: int, now: str) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "sgk-backup-manifest-v1":
        raise GateError("unsupported backup manifest")
    if _sha256(dump) != manifest.get("dump_sha256") or dump.stat().st_size != manifest.get("dump_bytes"):
        raise GateError("backup bytes do not match the manifest")
    if set(manifest.get("required_tables", [])) != REQUIRED_RESTORE_TABLES:
        raise GateError("backup manifest integrity table set is incomplete")
    completed = datetime.fromisoformat(manifest["completed_at"].replace("Z", "+00:00"))
    current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    age = (current - completed).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise GateError("backup violates the configured RPO age")
    return {"status": "PASS", "age_seconds": age, "sha256": manifest["dump_sha256"]}


def verify_restored_database(connection, restore_started_at: str, now: str, max_rto_seconds: int) -> dict:
    """Read-only integrity and measured-RTO check against an isolated restore."""
    started = datetime.fromisoformat(restore_started_at.replace("Z", "+00:00"))
    current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    rto = (current - started).total_seconds()
    if rto < 0 or rto > max_rto_seconds:
        raise GateError("isolated restore violates the configured RTO")
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
        counts = {}
        for table in ("tenants", "credentials", "admin_audit", "privacy_deletion_jobs"):
            cursor.execute(f"SELECT COUNT(*) AS count FROM {table}")
            counts[table] = int(cursor.fetchone()["count"])
    return {"status": "PASS", "rto_seconds": rto, "integrity_counts": counts}


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


def evidence_register(source: Path, output: Path, commit: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise GateError("evidence commit must be exact 40-hex")
    source_doc = json.loads(source.read_text(encoding="utf-8"))
    register = {
        "schema": "sgk-evidence-register-v1",
        "source_commit": commit,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence": source_doc["evidence"],
    }
    for item in register["evidence"]:
        if item["state"] == "passed" and (
            not item.get("artifact_sha256") or not item.get("reviewer") or not item.get("expires_at")
        ):
            raise GateError(f"passed evidence is incomplete: {item['id']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(register, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return register


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("contract")
    sbom = sub.add_parser("sbom")
    sbom.add_argument("--output", type=Path, required=True)
    backup = sub.add_parser("backup-manifest")
    backup.add_argument("--dump", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--source-commit", required=True)
    backup.add_argument("--completed-at", required=True)
    verify = sub.add_parser("verify-backup")
    verify.add_argument("--dump", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--max-age-seconds", type=int, required=True)
    verify.add_argument("--now", required=True)
    restore = sub.add_parser("restore-check")
    restore.add_argument("--host", required=True)
    restore.add_argument("--port", type=int, default=3306)
    restore.add_argument("--database", required=True)
    restore.add_argument("--user", required=True)
    restore.add_argument("--password-file", type=Path, required=True)
    restore.add_argument("--restore-started-at", required=True)
    restore.add_argument("--now", required=True)
    restore.add_argument("--max-rto-seconds", type=int, required=True)
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
        elif args.command == "sbom":
            result = {"status": "PASS", "components": len(generate_sbom(args.output)["components"])}
        elif args.command == "backup-manifest":
            result = create_backup_manifest(args.dump, args.output, args.source_commit, args.completed_at)
        elif args.command == "verify-backup":
            result = verify_backup(args.dump, args.manifest, args.max_age_seconds, args.now)
        elif args.command == "restore-check":
            import pymysql
            password = args.password_file.read_text(encoding="utf-8").strip()
            connection = pymysql.connect(
                host=args.host, port=args.port, user=args.user, password=password,
                database=args.database, cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5, read_timeout=5, write_timeout=5,
            )
            try:
                result = verify_restored_database(
                    connection, args.restore_started_at, args.now, args.max_rto_seconds
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
