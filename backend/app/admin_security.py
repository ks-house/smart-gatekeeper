"""Fail-closed administrator authentication and control-plane authorization.

The API process never accepts a browser supplied role, tenant, or device ID as
authority.  A TLS terminating proxy may forward a verified client certificate
only after it has completed mutual TLS; the certificate fingerprint is matched
to a configured identity.  That identity creates a short lived, server-side
session and every unsafe request additionally carries a same-origin CSRF token.

This module intentionally contains no development credential or mock-success
mode.  If mTLS identity configuration is absent or malformed, all admin and
control operations are unavailable (503) rather than anonymously available.
"""

from __future__ import annotations

import hashlib
import json
import os
import ipaddress
from pathlib import Path
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from fastapi import HTTPException, Request, status


ADMIN_SESSION_COOKIE = "sgk_admin_session"
CSRF_HEADER = "X-CSRF-Token"
TENANT_HEADER = "X-Tenant-ID"
REAUTH_HEADER = "X-Admin-Reauthenticate"
IDEMPOTENCY_HEADER = "Idempotency-Key"

ROLE_ADMIN = "TENANT_ADMIN"
ROLE_AUDITOR = "AUDITOR"
ROLE_OPERATOR = "SECURITY_OPERATOR"
ROLE_APPROVER = "SECURITY_APPROVER"


def _secret_text_from_environment(name: str) -> tuple[bool, str]:
    """Read one text secret without allowing ambiguous direct/file inputs."""
    direct = os.getenv(name)
    file_path = os.getenv(f"{name}_FILE", "").strip()
    if direct is not None and file_path:
        return False, ""
    if file_path:
        try:
            return True, Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            return False, ""
    return True, (direct or "").strip()


@dataclass(frozen=True)
class AdminPrincipal:
    subject: str
    roles: frozenset[str]
    tenants: frozenset[str]
    session_id: str
    csrf_token: str
    expires_at: int
    auth_method: str = "mtls"

    def can_access_tenant(self, tenant_id: str) -> bool:
        return "*" in self.tenants or tenant_id in self.tenants


@dataclass
class _Session:
    subject: str
    roles: frozenset[str]
    tenants: frozenset[str]
    csrf_token: str
    expires_at: int
    key_epoch: int
    issued_at: int
    auth_method: str


class AdminSecurity:
    """Small server-side session store suitable for one API process.

    Production deployments must run one API replica or provide a shared session
    implementation before scaling.  The security property is fail-closed:
    missing session state never degrades to an identity header or API key.
    """

    def __init__(
        self,
        identities: Optional[dict[str, dict[str, Any]]] = None,
        *,
        session_seconds: int = 900,
        reauth_seconds: int = 120,
        auth_attempts: int = 5,
        auth_window_seconds: int = 60,
        trusted_proxy_ips: Optional[set[str]] = None,
        personal_password: str = "",
    ) -> None:
        self.identities = identities or {}
        self.session_seconds = session_seconds
        self.reauth_seconds = reauth_seconds
        self.auth_attempts = auth_attempts
        self.auth_window_seconds = auth_window_seconds
        self.key_epoch = 1
        self.trusted_proxy_ips = trusted_proxy_ips or set()
        self.personal_password = personal_password if len(personal_password) >= 20 else ""
        self._sessions: dict[str, _Session] = {}
        self._attempts: dict[str, list[int]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "AdminSecurity":
        raw = os.getenv("ADMIN_MTLS_IDENTITIES_JSON", "").strip()
        identity_file = os.getenv("ADMIN_MTLS_IDENTITIES_JSON_FILE", "").strip()
        if raw and identity_file:
            return cls({})
        if identity_file:
            try:
                raw = Path(identity_file).read_text(encoding="utf-8").strip()
            except OSError:
                return cls({})
        try:
            identities = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            identities = {}
        if not isinstance(identities, dict):
            identities = {}
        trusted_proxies: set[str] = set()
        for item in os.getenv("ADMIN_TRUSTED_PROXY_IPS", "").split(","):
            item = item.strip()
            if not item:
                continue
            try:
                trusted_proxies.add(str(ipaddress.ip_address(item)))
            except ValueError:
                # Bad proxy configuration must make the mTLS boundary unusable.
                return cls({})
        password_ok, personal_password = _secret_text_from_environment(
            "PERSONAL_ADMIN_PASSWORD"
        )
        if not password_ok:
            return cls({})
        return cls(
            identities,
            session_seconds=_positive_env("ADMIN_SESSION_SECONDS", 900, 60, 3600),
            # Personal administration is typically performed from one trusted
            # household console. Keep the risky-action proof bounded by the
            # server-side session, but do not expire it while the operator is
            # reviewing a short tenant list.
            reauth_seconds=_positive_env("ADMIN_REAUTH_SECONDS", 900, 300, 3600),
            auth_attempts=_positive_env("ADMIN_AUTH_RATE_LIMIT", 5, 1, 100),
            auth_window_seconds=_positive_env("ADMIN_AUTH_RATE_WINDOW_SECONDS", 60, 1, 3600),
            trusted_proxy_ips=trusted_proxies,
            personal_password=personal_password,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.identities) or bool(self.personal_password)

    @property
    def browser_login_ready(self) -> bool:
        return bool(self.personal_password) or bool(self.identities and self.trusted_proxy_ips)

    def rotate_sessions(self) -> None:
        """Invalidate every existing session after identity/key rotation."""
        with self._lock:
            self.key_epoch += 1
            self._sessions.clear()

    def authenticate_personal_password(self, request: Request, candidate: str) -> dict[str, Any]:
        if not self.personal_password:
            raise HTTPException(status_code=503, detail="personal administrator login is not configured")
        client_key = request.client.host if request.client else "unknown"
        now = int(time.time())
        with self._lock:
            attempts = [stamp for stamp in self._attempts.get(client_key, []) if stamp > now - self.auth_window_seconds]
            if len(attempts) >= self.auth_attempts:
                self._attempts[client_key] = attempts
                raise HTTPException(status_code=429, detail="administrator authentication temporarily rate limited")
        if not candidate or not secrets.compare_digest(candidate, self.personal_password):
            self._failed_attempt(client_key, now)
            raise HTTPException(status_code=401, detail="invalid administrator password")
        with self._lock:
            self._attempts.pop(client_key, None)
        return {
            "subject": "personal-admin",
            "roles": frozenset((ROLE_ADMIN, ROLE_AUDITOR, ROLE_OPERATOR)),
            "tenants": frozenset(("*",)),
            "auth_method": "personal-session",
        }

    def authenticate_mtls(self, request: Request) -> dict[str, Any]:
        if not self.identities:
            raise HTTPException(status_code=503, detail="admin authentication is not configured")
        client_key = request.client.host if request.client else "unknown"
        now = int(time.time())
        with self._lock:
            attempts = [stamp for stamp in self._attempts.get(client_key, []) if stamp > now - self.auth_window_seconds]
            if len(attempts) >= self.auth_attempts:
                self._attempts[client_key] = attempts
                raise HTTPException(status_code=429, detail="administrator authentication temporarily rate limited")

        # Headers are accepted only from an explicit TLS proxy peer.  The API
        # service is not host-published in Compose, so external clients cannot
        # bypass that peer check and manufacture an mTLS success header.
        if client_key not in self.trusted_proxy_ips:
            self._failed_attempt(client_key, now)
            raise HTTPException(status_code=401, detail="untrusted client-certificate proxy")
        # A proxy must set this only after a successful TLS client-certificate
        # verification.  A raw subject/fingerprint header alone is never enough.
        if request.headers.get("X-SSL-Client-Verify") != "SUCCESS":
            self._failed_attempt(client_key, now)
            raise HTTPException(status_code=401, detail="verified mTLS client certificate required")
        fingerprint = request.headers.get("X-SSL-Client-SHA256", "").lower().replace(":", "")
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            self._failed_attempt(client_key, now)
            raise HTTPException(status_code=401, detail="verified client certificate fingerprint required")
        identity = self.identities.get(fingerprint)
        if not isinstance(identity, dict):
            self._failed_attempt(client_key, now)
            raise HTTPException(status_code=401, detail="unrecognized administrator certificate")
        subject = identity.get("subject")
        roles = identity.get("roles")
        tenants = identity.get("tenants")
        if not isinstance(subject, str) or not subject or not _valid_strings(roles) or not _valid_strings(tenants):
            self._failed_attempt(client_key, now)
            raise HTTPException(status_code=503, detail="administrator identity configuration is invalid")
        return {"subject": subject, "roles": frozenset(roles), "tenants": frozenset(tenants)}

    def issue_session(self, identity: dict[str, Any]) -> tuple[str, AdminPrincipal]:
        now = int(time.time())
        token = secrets.token_urlsafe(48)
        session_id = hashlib.sha256(token.encode("utf-8")).hexdigest()
        principal = AdminPrincipal(
            subject=identity["subject"],
            roles=identity["roles"],
            tenants=identity["tenants"],
            session_id=session_id,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=now + self.session_seconds,
            auth_method=str(identity.get("auth_method", "mtls")),
        )
        with self._lock:
            self._sessions[session_id] = _Session(
                subject=principal.subject,
                roles=principal.roles,
                tenants=principal.tenants,
                csrf_token=principal.csrf_token,
                expires_at=principal.expires_at,
                key_epoch=self.key_epoch,
                issued_at=now,
                auth_method=principal.auth_method,
            )
        return token, principal

    def principal(self, request: Request, *, unsafe: bool = False, roles: Iterable[str] = (), tenant_id: Optional[str] = None, reauthenticate: bool = False) -> AdminPrincipal:
        token = request.cookies.get(ADMIN_SESSION_COOKIE)
        if not token:
            raise HTTPException(status_code=401, detail="administrator session required")
        session_id = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = int(time.time())
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None or session.expires_at <= now or session.key_epoch != self.key_epoch:
            raise HTTPException(status_code=401, detail="administrator session expired or revoked")
        principal = AdminPrincipal(session.subject, session.roles, session.tenants, session_id, session.csrf_token, session.expires_at, session.auth_method)
        if unsafe:
            supplied = request.headers.get(CSRF_HEADER, "")
            if not supplied or not secrets.compare_digest(supplied, session.csrf_token):
                raise HTTPException(status_code=403, detail="CSRF validation failed")
        required = set(roles)
        if required and not required.intersection(principal.roles):
            raise HTTPException(status_code=403, detail="administrator role is not authorized")
        if tenant_id and not principal.can_access_tenant(tenant_id):
            raise HTTPException(status_code=403, detail="tenant scope violation")
        if reauthenticate:
            marker = request.headers.get(REAUTH_HEADER, "")
            if session.auth_method == "personal-session":
                if marker != "personal-session" or now - session.issued_at > self.reauth_seconds:
                    raise HTTPException(status_code=403, detail="personal administrator re-login required")
                return principal
            # Fresh mTLS proof binds the risky action to a current certificate.
            identity = self.authenticate_mtls(request)
            if identity["subject"] != principal.subject:
                raise HTTPException(status_code=403, detail="re-authentication actor mismatch")
            if marker != "mtls":
                raise HTTPException(status_code=403, detail="explicit re-authentication acknowledgement required")
        return principal

    def _failed_attempt(self, client_key: str, now: int) -> None:
        with self._lock:
            attempts = [stamp for stamp in self._attempts.get(client_key, []) if stamp > now - self.auth_window_seconds]
            attempts.append(now)
            self._attempts[client_key] = attempts


def _positive_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


def _valid_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item for item in value)
