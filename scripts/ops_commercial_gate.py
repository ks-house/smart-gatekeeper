#!/usr/bin/env python3
"""Repository-side Issue #52 commercial operations gate.

All commands are deterministic and hardwareless. They never contact production
infrastructure and never convert software evidence into physical acceptance.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


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
EVIDENCE_POLICIES = {
    "ops-contract": {
        "pass_allowed": True,
        "workflow_path": ".github/workflows/backend_security.yml",
        "workflow_ref": "refs/heads/main",
        "event": "push",
        "head_branch": "main",
        "producer_job": "backend-security",
        "producer_step": "Upload operations contract evidence claim",
        "attestor_job": "attest-backend-evidence",
        "attestor_step": "Attest operations contract claim",
        "environment": "github-hosted-main",
        "artifact_name": "ops-contract-{commit}",
        "artifact_path": "ops-contract.json",
        "subject_path": "build/evidence/ops-contract.json",
        "claim_type": "repository-operations-contract",
        "payload_path": "build/ops-contract-result.json",
        "payload_schema": "sgk-ops-contract-result-v1",
        "predicate_type": "https://slsa.dev/provenance/v1",
        "allow_digest_reuse": False,
    },
    "hosted-sbom-attestation": {
        "pass_allowed": True,
        "workflow_path": ".github/workflows/backend_security.yml",
        "workflow_ref": "refs/heads/main",
        "event": "push",
        "head_branch": "main",
        "producer_job": "backend-security",
        "producer_step": "Upload hosted SBOM evidence claim",
        "attestor_job": "attest-backend-evidence",
        "attestor_step": "Attest hosted SBOM claim",
        "environment": "github-hosted-main",
        "artifact_name": "hosted-sbom-attestation-{commit}",
        "artifact_path": "hosted-sbom-attestation.json",
        "subject_path": "build/evidence/hosted-sbom-attestation.json",
        "claim_type": "cyclonedx-sbom-attestation",
        "payload_path": "build/backend-sbom.cdx.json",
        "payload_schema": "cyclonedx-1.5",
        "predicate_type": "https://slsa.dev/provenance/v1",
        "allow_digest_reuse": False,
    },
    "isolated-mariadb-restore": {
        "pass_allowed": False,
        "workflow_path": ".github/workflows/operations_restore_evidence.yml",
        "workflow_ref": "refs/heads/main",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "producer_job": "isolated-mariadb-restore",
        "producer_step": "Upload isolated restore evidence claim",
        "attestor_job": "attest-restore-evidence",
        "attestor_step": "Attest isolated restore claim",
        "environment": "operator-restore-evidence",
        "artifact_name": "isolated-mariadb-restore-{commit}",
        "artifact_path": "isolated-mariadb-restore.json",
        "subject_path": "build/evidence/isolated-mariadb-restore.json",
        "claim_type": "isolated-mariadb-restore",
        "payload_path": "build/restore-result.json",
        "payload_schema": "sgk-restore-result-v1",
        "predicate_type": "https://slsa.dev/provenance/v1",
        "allow_digest_reuse": False,
    },
    "24h-load-soak": {
        "pass_allowed": False,
        "workflow_path": ".github/workflows/operations_physical_evidence.yml",
        "workflow_ref": "refs/heads/main",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "producer_job": "physical-24h-load-soak",
        "producer_step": "Upload physical soak evidence claim",
        "attestor_job": "attest-physical-evidence",
        "attestor_step": "Attest physical soak claim",
        "environment": "physical-live-like-evidence",
        "artifact_name": "24h-load-soak-{commit}",
        "artifact_path": "24h-load-soak.json",
        "subject_path": "build/evidence/24h-load-soak.json",
        "claim_type": "physical-24h-load-soak",
        "payload_path": "build/24h-load-soak-result.json",
        "payload_schema": "sgk-physical-soak-result-v1",
        "predicate_type": "https://slsa.dev/provenance/v1",
        "allow_digest_reuse": False,
    },
    "production-deployment": {
        "pass_allowed": False,
        "workflow_path": ".github/workflows/deploy.yml",
        "workflow_ref": "refs/heads/main",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "producer_job": "production-deployment-evidence",
        "producer_step": "Upload production deployment evidence claim",
        "attestor_job": "attest-production-evidence",
        "attestor_step": "Attest production deployment claim",
        "environment": "production",
        "artifact_name": "production-deployment-{commit}",
        "artifact_path": "production-deployment.json",
        "subject_path": "build/evidence/production-deployment.json",
        "claim_type": "production-deployment",
        "payload_path": "build/production-deployment-result.json",
        "payload_schema": "sgk-production-deployment-result-v1",
        "predicate_type": "https://slsa.dev/provenance/v1",
        "allow_digest_reuse": False,
    },
}


class GateError(RuntimeError):
    pass


class HTTPSOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject downgrade redirects and remove credentials on full-origin change."""

    @staticmethod
    def origin(url: str) -> tuple[str, str, int]:
        try:
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port if parsed.port is not None else 443
        except ValueError as exc:
            raise GateError("GitHub artifact URL has an invalid HTTPS origin") from exc
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise GateError("GitHub artifact URL must use an authenticated-free HTTPS origin")
        return ("https", parsed.hostname.rstrip(".").casefold(), port)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old_origin = self.origin(req.full_url)
        new_origin = self.origin(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and old_origin != new_origin:
            redirected.remove_header("Authorization")
        return redirected


class GitHubEvidenceVerifier:
    """Verify evidence against GitHub API state, never caller-asserted env."""

    API_URL = "https://api.github.com"
    def __init__(self, token: str):
        if not token:
            raise GateError("GitHub API token is required for passed evidence")
        self._token = token

    def _get(self, path: str):
        request = urllib.request.Request(
            f"{self.API_URL}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "smart-gatekeeper-evidence-verifier",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, urllib.error.URLError) as exc:
            raise GateError("GitHub evidence API verification failed") from exc
        if not isinstance(payload, (dict, list)):
            raise GateError("GitHub evidence API returned an invalid document")
        return payload

    def _download(self, url: str) -> bytes:
        HTTPSOriginRedirectHandler.origin(url)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "smart-gatekeeper-evidence-verifier",
            },
        )
        try:
            opener = urllib.request.build_opener(HTTPSOriginRedirectHandler())
            with opener.open(request, timeout=30) as response:
                data = response.read(100 * 1024 * 1024 + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise GateError("GitHub artifact download failed") from exc
        if len(data) > 100 * 1024 * 1024:
            raise GateError("GitHub artifact archive exceeds verification limit")
        return data

    @staticmethod
    def _attestation_statement(attestation: dict) -> dict:
        try:
            encoded = attestation["bundle"]["dsseEnvelope"]["payload"]
            statement = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise GateError("GitHub attestation bundle is malformed") from exc
        if not isinstance(statement, dict):
            raise GateError("GitHub attestation statement is malformed")
        return statement

    def verify(
        self,
        *,
        evidence_id: str,
        scope: str,
        repository: str,
        commit: str,
        candidate_author: str,
        reviewer: str,
        digest: str,
        provenance: dict,
    ) -> dict:
        policy = EVIDENCE_POLICIES[evidence_id]
        if scope != EVIDENCE_SCOPES[evidence_id] or not policy["pass_allowed"]:
            raise GateError(f"evidence producer is not admitted: {evidence_id}")
        quoted_repository = "/".join(
            urllib.parse.quote(part, safe="") for part in repository.split("/")
        )
        run_id = provenance["run_id"]
        commit_record = self._get(
            f"/repos/{quoted_repository}/commits/{urllib.parse.quote(commit, safe='')}"
        )
        if (
            commit_record.get("sha") != commit
            or commit_record.get("author", {}).get("login", "").casefold()
            != candidate_author.casefold()
        ):
            raise GateError("GitHub commit does not bind the candidate author")
        run = self._get(f"/repos/{quoted_repository}/actions/runs/{run_id}")
        if (
            run.get("id") != run_id
            or run.get("head_sha") != commit
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("run_attempt") != provenance["run_attempt"]
            or run.get("repository", {}).get("full_name") != repository
            or run.get("event") != policy["event"]
            or run.get("head_branch") != policy["head_branch"]
            or run.get("path") != policy["workflow_path"]
        ):
            raise GateError("GitHub run is not the trusted exact-main workflow execution")

        jobs_document = self._get(
            f"/repos/{quoted_repository}/actions/runs/{run_id}/attempts/"
            f"{provenance['run_attempt']}/jobs?per_page=100"
        )
        jobs = jobs_document.get("jobs") if isinstance(jobs_document, dict) else None
        for job_name, step_name in (
            (policy["producer_job"], policy["producer_step"]),
            (policy["attestor_job"], policy["attestor_step"]),
        ):
            matching_jobs = [job for job in jobs or [] if job.get("name") == job_name]
            if len(matching_jobs) != 1:
                raise GateError("GitHub evidence producer job is absent or ambiguous")
            job = matching_jobs[0]
            matching_steps = [
                step for step in job.get("steps", []) if step.get("name") == step_name
            ]
            if not (
                job.get("status") == "completed"
                and job.get("conclusion") == "success"
                and job.get("head_sha") == commit
                and job.get("run_attempt") == provenance["run_attempt"]
                and job.get("labels") == ["ubuntu-latest"]
                and len(matching_steps) == 1
                and matching_steps[0].get("conclusion") == "success"
            ):
                raise GateError("GitHub evidence producer job/step is not authoritative")

        artifacts = self._get(
            f"/repos/{quoted_repository}/actions/runs/{run_id}/artifacts?per_page=100"
        ).get("artifacts")
        matching = [
            artifact for artifact in artifacts or []
            if artifact.get("name") == policy["artifact_name"].format(commit=commit)
            and provenance["artifact_name"]
            == policy["artifact_name"].format(commit=commit)
            and artifact.get("digest")
            == f"sha256:{provenance['artifact_archive_sha256']}"
            and artifact.get("expired") is False
            and artifact.get("workflow_run", {}).get("id") == run_id
            and artifact.get("workflow_run", {}).get("head_sha") == commit
            and artifact.get("workflow_run", {}).get("head_branch")
            == policy["head_branch"]
        ]
        if len(matching) != 1:
            raise GateError("GitHub artifact name/digest is absent, ambiguous, or expired")
        archive = self._download(matching[0].get("archive_download_url", ""))
        if hashlib.sha256(archive).hexdigest() != provenance["artifact_archive_sha256"]:
            raise GateError("downloaded GitHub artifact archive digest mismatch")
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                artifact_path = policy["artifact_path"]
                if provenance["artifact_path"] != artifact_path:
                    raise GateError("GitHub artifact subject path is not admitted for evidence ID")
                entries = [item for item in bundle.infolist() if item.filename == artifact_path]
                if (
                    len(entries) != 1
                    or entries[0].is_dir()
                    or entries[0].file_size > 50 * 1024 * 1024
                    or ".." in Path(artifact_path).parts
                    or artifact_path.startswith(("/", "\\"))
                    or "\\" in artifact_path
                ):
                    raise GateError("GitHub artifact subject path is unsafe or ambiguous")
                subject_bytes = bundle.read(entries[0])
        except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
            raise GateError("GitHub artifact archive is invalid") from exc
        if hashlib.sha256(subject_bytes).hexdigest() != digest:
            raise GateError("GitHub artifact subject digest mismatch")

        try:
            claim = json.loads(subject_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GateError("GitHub evidence claim is not canonical JSON") from exc
        expected_producer = {
            "workflow_path": policy["workflow_path"],
            "workflow_ref": policy["workflow_ref"],
            "event": policy["event"],
            "job": policy["producer_job"],
            "environment": policy["environment"],
        }
        if not isinstance(claim, dict) or set(claim) != {
            "schema", "evidence_id", "scope", "claim_type", "result",
            "source_commit", "producer", "payload",
        }:
            raise GateError("GitHub evidence claim schema is invalid")
        payload = claim.get("payload")
        if not (
            claim.get("schema") == "sgk-evidence-claim-v1"
            and claim.get("evidence_id") == evidence_id
            and claim.get("scope") == scope
            and claim.get("claim_type") == policy["claim_type"]
            and claim.get("result") == "PASS"
            and claim.get("source_commit") == commit
            and claim.get("producer") == expected_producer
            and isinstance(payload, dict)
            and set(payload) == {"path", "schema", "sha256"}
            and payload.get("path") == policy["payload_path"]
            and payload.get("schema") == policy["payload_schema"]
            and re.fullmatch(r"[a-f0-9]{64}", payload.get("sha256", ""))
        ):
            raise GateError("GitHub evidence claim does not match its fixed ID policy")

        pull_number = provenance["pull_request"]
        pull = self._get(f"/repos/{quoted_repository}/pulls/{pull_number}")
        if not isinstance(pull, dict) or not (
            pull.get("number") == pull_number
            and pull.get("state") == "closed"
            and pull.get("merged") is True
            and pull.get("merged_at")
            and pull.get("merge_commit_sha") == commit
            and pull.get("base", {}).get("ref") == "main"
            and pull.get("base", {}).get("repo", {}).get("full_name") == repository
            and pull.get("head", {}).get("sha") == provenance["reviewed_head_sha"]
            and pull.get("head", {}).get("repo", {}).get("full_name") == repository
        ):
            raise GateError("GitHub pull request does not bind exact main merge and reviewed head")
        review = self._get(
            f"/repos/{quoted_repository}/pulls/{pull_number}/reviews/{provenance['review_id']}"
        )
        reviewer_identity = self._get(
            f"/users/{urllib.parse.quote(reviewer, safe='')}"
        )
        if not isinstance(review, dict) or not (
            review.get("id") == provenance["review_id"]
            and review.get("user", {}).get("id") == provenance["reviewer_id"]
            and review.get("user", {}).get("login", "").casefold() == reviewer.casefold()
            and review.get("user", {}).get("type") == "User"
            and review.get("state") == "APPROVED"
            and review.get("commit_id") == provenance["reviewed_head_sha"]
            and isinstance(reviewer_identity, dict)
            and reviewer_identity.get("id") == provenance["reviewer_id"]
            and reviewer_identity.get("login", "").casefold() == reviewer.casefold()
            and reviewer_identity.get("type") == "User"
        ):
            raise GateError("GitHub review is not an authoritative exact-PR approval")

        subject = urllib.parse.quote(f"sha256:{digest}", safe="")
        attestations = self._get(
            f"/repos/{quoted_repository}/attestations/{subject}?per_page=100"
        ).get("attestations")
        verified = False
        for attestation in attestations or []:
            statement = self._attestation_statement(attestation)
            subjects = statement.get("subject")
            predicate = statement.get("predicate", {})
            build = predicate.get("buildDefinition", {})
            workflow = build.get("externalParameters", {}).get("workflow", {})
            dependencies = build.get("resolvedDependencies", [])
            builder = predicate.get("runDetails", {}).get("builder", {})
            metadata = predicate.get("runDetails", {}).get("metadata", {})
            if (
                statement.get("_type") == "https://in-toto.io/Statement/v1"
                and statement.get("predicateType") == policy["predicate_type"]
                and any(
                    item.get("name") == provenance["subject_path"]
                    and item.get("digest", {}).get("sha256") == digest
                    for item in subjects or []
                )
                and workflow.get("repository") == f"https://github.com/{repository}"
                and workflow.get("ref") == policy["workflow_ref"]
                and workflow.get("path") == f"/{policy['workflow_path']}"
                and any(
                    dependency.get("digest", {}).get("gitCommit") == commit
                    for dependency in dependencies
                )
                and builder.get("id")
                == "https://github.com/actions/runner/github-hosted"
                and metadata.get("invocationId")
                == (
                    f"https://github.com/{repository}/actions/runs/{run_id}/attempts/"
                    f"{provenance['run_attempt']}"
                )
            ):
                verified = True
                break
        if not verified:
            raise GateError("GitHub attestation does not bind artifact, repository, and run")
        return {
            "evidence_id": evidence_id,
            "subject_sha256": digest,
            "payload_sha256": payload["sha256"],
        }


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
    production_schema = (ROOT / "backend/db/production_schema.sql").read_text(encoding="utf-8")
    migration_runner = (ROOT / "backend/db/run_migrations.sh").read_text(encoding="utf-8")
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
        "127.0.0.1:8000/ready", "service_completed_successfully",
        "EXPECTED_DB_SCHEMA_VERSION: \"007\"", "migration_backups:",
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
    status_job_match = re.search(
        r"(?ms)^  nas_private_status_preflight:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
        workflow,
    )
    if "workflow_dispatch:" not in workflow.split("jobs:", 1)[0]:
        errors.append("backend workflow omits manual NAS status preflight trigger")
    if status_job_match is None:
        errors.append("backend workflow omits manual NAS status preflight job")
    else:
        status_job = status_job_match.group(1)
        for required in (
            "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'",
            "name: production",
            "id-token: write",
            "tailscale/github-action@306e68a486fd2350f2bfc3b19fcd143891a4a2d8",
            "oauth-client-id: ${{ secrets.TS_OIDC_CLIENT_ID }}",
            "audience: ${{ secrets.TS_OIDC_AUDIENCE }}",
            "tags: tag:sgk-github-deploy",
            "NAS_HOST: ${{ vars.NAS_TAILSCALE_HOST }}",
            "StrictHostKeyChecking=yes",
            '"$NAS_USER@$NAS_HOST" status',
            "^status=(not-deployed|deployed)$",
        ):
            if required not in status_job:
                errors.append(f"NAS status preflight missing {required}")
        for forbidden in (
            " apply",
            "NAS_BACKEND_RELEASE_SIGNING_KEY_PEM",
            "backend-release.tar.gz",
            "docker pull",
        ):
            if forbidden in status_job:
                errors.append(f"NAS status preflight contains forbidden token {forbidden}")
    for required_path in (
        "'ops/**'", "'scripts/ops_commercial_gate.py'",
        "'.orca/scripts/setup_worktree.ps1'",
        "'protocol/test_vectors/v1.json'",
    ):
        if workflow.count(required_path) != 2:
            errors.append(f"backend workflow trigger coverage missing {required_path}")
    admitted_evidence = {
        evidence_id for evidence_id, policy in EVIDENCE_POLICIES.items()
        if policy["pass_allowed"]
    }
    if admitted_evidence != {"ops-contract", "hosted-sbom-attestation"}:
        errors.append("only repository software evidence producers may currently pass")
    for blocked_id in (
        "isolated-mariadb-restore", "24h-load-soak", "production-deployment",
    ):
        if EVIDENCE_POLICIES[blocked_id]["pass_allowed"]:
            errors.append(f"live/operator producer is not trusted yet: {blocked_id}")
    for required in (
        "Upload operations contract evidence claim",
        "Upload hosted SBOM evidence claim",
        "Attest operations contract claim",
        "Attest hosted SBOM claim",
        "build/evidence/ops-contract.json",
        "build/evidence/hosted-sbom-attestation.json",
    ):
        if required not in workflow:
            errors.append(f"backend workflow omits fixed evidence producer token: {required}")
    if not re.search(r"^FROM mariadb@sha256:[a-f0-9]{64}$", db_dockerfile, re.MULTILINE):
        errors.append("migration database image base is not digest-pinned")
    if "COPY migrations/007_ops_privacy_up.sql /opt/smart-gatekeeper/migrations/007_up.sql" not in db_dockerfile:
        errors.append("migration database artifact omits the current privacy migration")
    if "production_schema.sql" not in db_dockerfile or re.search(
        r"(?m)^COPY\s+schema\.sql\s+/docker-entrypoint", db_dockerfile
    ):
        errors.append("migration database artifact does not isolate the seed-free schema")
    if re.search(r"(?im)^\s*(INSERT|REPLACE)\s+INTO\s+tenants", production_schema):
        errors.append("production schema contains tenant seed data")
    for forbidden_seed in ("secret_key_101", "010-1234", "AA:BB:CC:DD:EE:01"):
        if forbidden_seed in production_schema or forbidden_seed in db_dockerfile:
            errors.append("production database artifact contains demo credentials or PII")
    for required in (
        "mariadb-dump", "pre-migration-", "schema_migrations", "canonical_sha",
        "up:007|down:001", ".schema-migration-lock",
    ):
        if required not in migration_runner:
            errors.append(f"migration runner missing {required}")
    expected_trusted = {
        ".github/workflows/backend_security.yml",
        ".orca/scripts/setup_worktree.ps1",
        "scripts/ops_commercial_gate.py",
        "protocol/test_vectors/v1.json",
        *(
            path.relative_to(ROOT).as_posix()
            for root in (ROOT / "backend", ROOT / "ops")
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        ),
    }
    declared_paths = trusted_inputs.get("paths", [])
    if (
        trusted_inputs.get("schema") != "sgk-backend-trusted-inputs-v1"
        or not isinstance(declared_paths, list)
        or len(declared_paths) != len(set(declared_paths))
        or set(declared_paths) != expected_trusted
    ):
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
        "status": "PASS", "checks": 35, "scope": "repository-software-only",
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


def generate_ops_contract_result(output: Path, commit: str) -> dict:
    if commit != checked_out_commit():
        raise GateError("operations contract claim must equal checked-out Git commit")
    result = {
        "schema": "sgk-ops-contract-result-v1",
        "source_commit": commit,
        **contract(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def generate_evidence_claim(
    evidence_id: str,
    payload_path: Path,
    output: Path,
    commit: str,
) -> dict:
    if commit != checked_out_commit():
        raise GateError("evidence claim must equal checked-out Git commit")
    if evidence_id not in EVIDENCE_POLICIES:
        raise GateError("evidence claim ID is unknown")
    policy = EVIDENCE_POLICIES[evidence_id]
    if not policy["pass_allowed"]:
        raise GateError(f"evidence producer is not admitted: {evidence_id}")
    payload_bytes = payload_path.read_bytes()
    try:
        payload_document = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GateError("evidence payload is not valid JSON") from exc
    if evidence_id == "ops-contract":
        if not isinstance(payload_document, dict) or not (
            payload_document.get("schema") == policy["payload_schema"]
            and payload_document.get("source_commit") == commit
            and payload_document.get("status") == "PASS"
            and payload_document.get("scope") == "repository-software-only"
            and payload_document.get("trusted_base_rotation") == "required-before-merge"
        ):
            raise GateError("operations contract payload is not authoritative")
    elif evidence_id == "hosted-sbom-attestation":
        if not isinstance(payload_document, dict) or not (
            payload_document.get("bomFormat") == "CycloneDX"
            and payload_document.get("specVersion") == "1.5"
            and payload_document.get("version") == 1
            and payload_document.get("metadata", {}).get("component", {}).get("name")
            == "smart-gatekeeper-backend"
            and isinstance(payload_document.get("components"), list)
            and payload_document["components"]
        ):
            raise GateError("hosted SBOM payload is not authoritative CycloneDX")
    claim = {
        "schema": "sgk-evidence-claim-v1",
        "evidence_id": evidence_id,
        "scope": EVIDENCE_SCOPES[evidence_id],
        "claim_type": policy["claim_type"],
        "result": "PASS",
        "source_commit": commit,
        "producer": {
            "workflow_path": policy["workflow_path"],
            "workflow_ref": policy["workflow_ref"],
            "event": policy["event"],
            "job": policy["producer_job"],
            "environment": policy["environment"],
        },
        "payload": {
            "path": policy["payload_path"],
            "schema": policy["payload_schema"],
            "sha256": hashlib.sha256(payload_bytes).hexdigest(),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(claim, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return claim


def migration_set_sha256() -> str:
    paths = [
        ROOT / "backend/db/production_schema.sql",
        ROOT / "backend/db/run_migrations.sh",
        *sorted((ROOT / "backend/db/migrations").glob("*.sql")),
    ]
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
) -> dict:
    """Read-only integrity check against an isolated restored database."""
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
        "integrity_counts": {
            table: actual[table]["row_count"] for table in sorted(actual)
        },
        "migration_set_sha256": manifest["migration_set_sha256"],
    }


def restore_and_verify_database(
    restore_action,
    connection_factory,
    manifest: dict,
    manifest_key: bytes,
    max_rto_seconds: int,
    *,
    monotonic=time.monotonic,
) -> dict:
    """Measure the actual import through verified integrity inside one harness."""
    if max_rto_seconds <= 0:
        raise GateError("maximum RTO must be positive")
    before = connection_factory()
    try:
        with before.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS count FROM information_schema.tables "
                "WHERE table_schema=DATABASE()"
            )
            if int(cursor.fetchone()["count"]) != 0:
                raise GateError("isolated restore target must be an empty database")
    finally:
        before.close()

    started = monotonic()
    restore_action(max_rto_seconds)
    restored = connection_factory()
    try:
        result = verify_restored_database(restored, manifest, manifest_key)
    finally:
        restored.close()
    measured = monotonic() - started
    if measured < 0 or measured > max_rto_seconds:
        raise GateError("isolated import plus integrity verification violates RTO")
    return {**result, "rto_seconds": measured}


def restore_with_mariadb_client(
    dump: Path,
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password_file: Path,
    timeout_seconds: int,
) -> None:
    """Run the real import with a secret option file and a hard timeout."""
    password = password_file.read_text(encoding="utf-8").rstrip("\r\n")
    if not password or any(char in password for char in ("\r", "\n", "\0")):
        raise GateError("restore password file is empty or contains control characters")
    escaped = password.replace("\\", "\\\\").replace('"', '\\"')
    option_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", delete=False,
            prefix="sgk-mariadb-", suffix=".cnf",
        ) as option_file:
            option_file.write(f'[client]\npassword="{escaped}"\n')
            option_path = Path(option_file.name)
        os.chmod(option_path, 0o600)
        command = [
            "mariadb", f"--defaults-extra-file={option_path}",
            f"--host={host}", f"--port={port}", f"--user={user}",
            "--default-character-set=utf8mb4", database,
        ]
        with dump.open("rb") as source:
            completed = subprocess.run(
                command, stdin=source, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=timeout_seconds, check=False,
            )
        if completed.returncode != 0:
            raise GateError("isolated MariaDB restore client failed")
    except subprocess.TimeoutExpired as exc:
        raise GateError("isolated MariaDB restore client exceeded RTO deadline") from exc
    finally:
        if option_path is not None:
            try:
                option_path.unlink()
            except OSError:
                pass


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
    verifier: GitHubEvidenceVerifier | None = None,
) -> dict:
    if commit != checked_out_commit():
        raise GateError("evidence commit must equal the checked-out Git commit")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise GateError("evidence validation time must be timezone-aware")
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
    seen_subject_digests = {}
    seen_payload_digests = {}
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
        policy = EVIDENCE_POLICIES[evidence_id]
        if not policy["pass_allowed"]:
            raise GateError(f"evidence producer is not admitted: {evidence_id}")
        if item["source_commit"] != commit:
            raise GateError(f"passed evidence commit mismatch: {evidence_id}")
        digest = item["artifact_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise GateError(f"passed evidence digest is invalid: {evidence_id}")
        if digest in seen_subject_digests and not policy["allow_digest_reuse"]:
            raise GateError(
                f"evidence subject digest reused across IDs: {seen_subject_digests[digest]}"
            )
        seen_subject_digests[digest] = evidence_id
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
            "provider", "repository", "commit", "run_id", "run_attempt",
            "artifact_name", "artifact_archive_sha256", "subject_path",
            "artifact_path", "artifact_sha256", "pull_request", "review_id", "reviewer_id",
            "reviewed_head_sha",
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
            or not isinstance(provenance["run_attempt"], int)
            or provenance["run_attempt"] <= 0
            or not isinstance(provenance["artifact_name"], str)
            or provenance["artifact_name"]
            != policy["artifact_name"].format(commit=commit)
            or not isinstance(provenance["subject_path"], str)
            or provenance["subject_path"] != policy["subject_path"]
            or not isinstance(provenance["artifact_path"], str)
            or provenance["artifact_path"] != policy["artifact_path"]
            or not re.fullmatch(r"[a-f0-9]{64}", provenance["artifact_archive_sha256"])
            or not isinstance(provenance["pull_request"], int)
            or provenance["pull_request"] <= 0
            or not isinstance(provenance["review_id"], int)
            or provenance["review_id"] <= 0
            or not isinstance(provenance["reviewer_id"], int)
            or provenance["reviewer_id"] <= 0
            or not re.fullmatch(r"[a-f0-9]{40}", provenance["reviewed_head_sha"])
        ):
            raise GateError(f"passed evidence provenance does not bind the artifact: {evidence_id}")
        if verifier is None:
            raise GateError(f"passed evidence requires live GitHub API verification: {evidence_id}")
        verified_claim = verifier.verify(
            evidence_id=evidence_id, scope=item["scope"],
            repository=source_doc["repository"], commit=commit,
            candidate_author=candidate_author, reviewer=reviewer,
            digest=digest, provenance=provenance,
        )
        if not isinstance(verified_claim, dict) or not (
            verified_claim.get("evidence_id") == evidence_id
            and verified_claim.get("subject_sha256") == digest
            and re.fullmatch(
                r"[a-f0-9]{64}", verified_claim.get("payload_sha256", "")
            )
        ):
            raise GateError(f"trusted verifier returned an invalid claim: {evidence_id}")
        payload_digest = verified_claim["payload_sha256"]
        if payload_digest in seen_payload_digests and not policy["allow_digest_reuse"]:
            raise GateError(
                f"evidence payload digest reused across IDs: "
                f"{seen_payload_digests[payload_digest]}"
            )
        seen_payload_digests[payload_digest] = evidence_id
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
    contract_evidence = sub.add_parser("ops-contract-evidence")
    contract_evidence.add_argument("--result-output", type=Path, required=True)
    contract_evidence.add_argument("--claim-output", type=Path, required=True)
    contract_evidence.add_argument("--commit", required=True)
    claim = sub.add_parser("evidence-claim")
    claim.add_argument("--id", choices=sorted(EVIDENCE_POLICIES), required=True)
    claim.add_argument("--payload", type=Path, required=True)
    claim.add_argument("--output", type=Path, required=True)
    claim.add_argument("--commit", required=True)
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
    restore.add_argument("--dump", type=Path, required=True)
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--manifest-key-file", type=Path, required=True)
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
        elif args.command == "ops-contract-evidence":
            generate_ops_contract_result(args.result_output, args.commit)
            result = generate_evidence_claim(
                "ops-contract", args.result_output, args.claim_output, args.commit,
            )
        elif args.command == "evidence-claim":
            result = generate_evidence_claim(
                args.id, args.payload, args.output, args.commit,
            )
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
            def connection_factory():
                return pymysql.connect(
                    host=args.host, port=args.port, user=args.user, password=password,
                    database=args.database, cursorclass=pymysql.cursors.DictCursor,
                    connect_timeout=5, read_timeout=5, write_timeout=5,
                )

            if args.command == "inventory":
                connection = connection_factory()
                try:
                    result = capture_database_inventory(connection)
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(
                        json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                finally:
                    connection.close()
            else:
                manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
                result = restore_and_verify_database(
                    lambda timeout: restore_with_mariadb_client(
                        args.dump, host=args.host, port=args.port,
                        database=args.database, user=args.user,
                        password_file=args.password_file, timeout_seconds=timeout,
                    ),
                    connection_factory,
                    manifest,
                    args.manifest_key_file.read_bytes().strip(),
                    args.max_rto_seconds,
                )
        elif args.command == "slo":
            result = evaluate_slo(args.samples, args.policy)
        else:
            source_doc = json.loads(args.source.read_text(encoding="utf-8"))
            has_passed = any(
                item.get("state") == "passed"
                for item in source_doc.get("evidence", [])
                if isinstance(item, dict)
            )
            verifier = (
                GitHubEvidenceVerifier(
                    os.getenv("GITHUB_TOKEN", ""),
                ) if has_passed else None
            )
            result = evidence_register(
                args.source, args.output, args.commit, verifier=verifier,
            )
    except (GateError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"OPS-GATE FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
