"""Authenticated FastAPI surface for the issue #19 ACL management plane."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

try:
    from .acl_management import AclManagementService
except ImportError:  # Docker runs uvicorn with /app as the import root.
    from acl_management import AclManagementService


@dataclass(frozen=True)
class AclApiConfig:
    enabled: bool
    enrollment_credentials: dict[str, dict[str, str]]
    admin_key: str
    target_credentials: dict[str, dict[str, str]]


class TenantRequest(BaseModel):
    tenant_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class TenantBootstrapRequest(TenantRequest):
    display_name: str = Field(min_length=1, max_length=100)
    legacy_tenant_id: int = Field(ge=1)


class CredentialActionRequest(TenantRequest):
    credential_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class DoorGrantRequest(CredentialActionRequest):
    door_id: str = Field(pattern=r"^[0-9a-f]{32}$")



class EnrollmentSubmitRequest(TenantRequest):
    enrollment_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_key_sec1: str = Field(pattern=r"^[0-9a-f]{130}$")
    signature_raw64: str = Field(pattern=r"^[0-9a-f]{128}$")
    expires_at: Optional[int] = None
    min_protocol: int = Field(default=1, ge=1, le=65535)
    max_protocol: int = Field(default=1, ge=1, le=65535)
    legacy_device_id: Optional[str] = Field(default=None, max_length=256)


class SnapshotPublishRequest(TenantRequest):
    min_protocol: int = Field(default=1, ge=1, le=65535)
    max_protocol: int = Field(default=1, ge=1, le=65535)


class AckRequest(TenantRequest):
    target_id: str = Field(min_length=1, max_length=128)
    door_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    acl_version: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["APPLIED", "REJECTED"]


class OtaMetadataRequest(TenantRequest):
    component: Literal["target", "mobile"]
    version: str = Field(min_length=1, max_length=64)
    primary_url: str = Field(pattern=r"^https://")
    fallback_url: str = Field(pattern=r"^https://")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")
    protocol_min: int = Field(ge=1, le=65535)
    protocol_max: int = Field(ge=1, le=65535)


class OtaHealthRequest(TenantRequest):
    target_id: str = Field(min_length=1, max_length=128)
    component: Literal["target", "mobile"]
    version: str = Field(min_length=1, max_length=64)
    boot_id: str = Field(min_length=1, max_length=128)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    healthy: bool


def _actor_ref(role: str, key: str) -> str:
    return f"{role}:{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}"


def _invoke(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        # Never reflect DB/crypto exception strings; they can contain identifiers or values.
        raise HTTPException(status_code=500, detail="management operation failed") from exc


def create_acl_router(
    service: AclManagementService, config: AclApiConfig
) -> APIRouter:
    router = APIRouter(tags=["acl-management"])

    def require_enabled() -> None:
        if not config.enabled:
            raise HTTPException(status_code=503, detail="ACL management feature is disabled")

    def require_enrollment(
        x_enrollment_key: Optional[str] = Header(default=None, alias="X-Enrollment-Key"),
        x_enrollment_actor_id: Optional[str] = Header(
            default=None, alias="X-Enrollment-Actor-ID"
        ),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> tuple[str, str]:
        require_enabled()
        if not x_tenant_id or not x_enrollment_actor_id:
            raise HTTPException(status_code=401, detail="missing enrollment identity scope")
        credential = config.enrollment_credentials.get(x_enrollment_actor_id)
        expected_tenant = credential.get("tenant_id") if credential else None
        expected_key = credential.get("key") if credential else None
        if (
            not expected_tenant
            or not expected_key
            or not secrets.compare_digest(x_tenant_id, expected_tenant)
        ):
            raise HTTPException(status_code=403, detail="enrollment tenant boundary violation")
        if not x_enrollment_key or not secrets.compare_digest(x_enrollment_key, expected_key):
            raise HTTPException(status_code=401, detail="invalid enrollment authentication")
        # Bind a challenge to a stable, non-secret identity reference. The key proves
        # authentication but is deliberately excluded so key rotation cannot orphan an
        # actor's outstanding challenge or leak key-derived identity into persistence.
        identity_ref = hashlib.sha256(
            x_enrollment_actor_id.encode("utf-8")
        ).hexdigest()[:24]
        return x_tenant_id, f"enrollment:{identity_ref}"

    def require_admin(
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> tuple[str, str]:
        require_enabled()
        if not config.admin_key or not x_admin_key or not secrets.compare_digest(
            x_admin_key, config.admin_key
        ):
            raise HTTPException(status_code=401, detail="invalid admin authentication")
        if not x_tenant_id:
            raise HTTPException(status_code=401, detail="missing tenant scope")
        return x_tenant_id, _actor_ref("admin", x_admin_key)

    def require_target(
        x_target_key: Optional[str] = Header(default=None, alias="X-Target-Key"),
        x_target_id: Optional[str] = Header(default=None, alias="X-Target-ID"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> tuple[str, str, str, str]:
        require_enabled()
        if not x_tenant_id or not x_target_id:
            raise HTTPException(status_code=401, detail="missing target tenant scope")
        credential = config.target_credentials.get(x_target_id)
        expected_tenant = credential.get("tenant_id") if credential else None
        expected_door = credential.get("door_id") if credential else None
        expected_key = credential.get("key") if credential else None
        if (
            not expected_tenant
            or not expected_door
            or not expected_key
            or not secrets.compare_digest(x_tenant_id, expected_tenant)
        ):
            raise HTTPException(status_code=403, detail="target tenant boundary violation")
        if not x_target_key or not secrets.compare_digest(x_target_key, expected_key):
            raise HTTPException(status_code=401, detail="invalid target authentication")
        return (
            x_tenant_id,
            _actor_ref("target", x_target_key),
            x_target_id,
            expected_door,
        )

    def scoped(body_tenant_id: str, auth: tuple[str, str]) -> tuple[str, str]:
        tenant_id, actor = auth
        if not secrets.compare_digest(body_tenant_id, tenant_id):
            raise HTTPException(status_code=403, detail="tenant boundary violation")
        return tenant_id, actor

    @router.post("/api/v1/acl/enrollment/challenge")
    def enrollment_challenge(
        request: TenantRequest,
        x_enrollment_key: Optional[str] = Header(default=None, alias="X-Enrollment-Key"),
        x_enrollment_actor_id: Optional[str] = Header(
            default=None, alias="X-Enrollment-Actor-ID"
        ),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        auth = require_enrollment(x_enrollment_key, x_enrollment_actor_id, x_tenant_id)
        tenant_id, actor = scoped(request.tenant_id, auth)
        return _invoke(
            service.issue_enrollment_challenge,
            tenant_id,
            actor_ref=actor,
            actor_tenant_id=tenant_id,
        )

    @router.post("/api/v1/acl/enrollment/submit")
    def enrollment_submit(
        request: EnrollmentSubmitRequest,
        x_enrollment_key: Optional[str] = Header(default=None, alias="X-Enrollment-Key"),
        x_enrollment_actor_id: Optional[str] = Header(
            default=None, alias="X-Enrollment-Actor-ID"
        ),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        tenant_id, actor = scoped(
            request.tenant_id,
            require_enrollment(x_enrollment_key, x_enrollment_actor_id, x_tenant_id),
        )
        return _invoke(
            service.submit_enrollment,
            tenant_id,
            request.enrollment_id,
            request.nonce,
            request.public_key_sec1,
            request.signature_raw64,
            actor_ref=actor,
            actor_tenant_id=tenant_id,
            legacy_device_id=request.legacy_device_id,
            expires_at=request.expires_at,
            min_protocol=request.min_protocol,
            max_protocol=request.max_protocol,
        )

    def admin_status_change(
        request: CredentialActionRequest,
        action: Callable[..., dict[str, Any]],
        x_admin_key: Optional[str],
        x_tenant_id: Optional[str],
    ) -> dict[str, Any]:
        tenant_id, actor = scoped(
            request.tenant_id, require_admin(x_admin_key, x_tenant_id)
        )
        return _invoke(action, tenant_id, request.credential_id, actor_ref=actor)

    @router.post("/api/v1/admin/acl/tenants")
    def register_tenant(
        request: TenantBootstrapRequest,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, str]:
        tenant_id, actor = scoped(
            request.tenant_id, require_admin(x_admin_key, x_tenant_id)
        )
        return _invoke(
            service.register_tenant,
            tenant_id,
            request.display_name,
            request.legacy_tenant_id,
            actor_ref=actor,
        )

    @router.post("/api/v1/admin/acl/tenants/disable")
    def disable_tenant(
        request: TenantRequest,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        tenant_id, actor = scoped(
            request.tenant_id, require_admin(x_admin_key, x_tenant_id)
        )
        return _invoke(
            service.disable_tenant,
            tenant_id,
            actor_ref=actor,
            actor_tenant_id=tenant_id,
        )


    @router.post("/api/v1/admin/acl/credentials/approve")
    def approve(
        request: CredentialActionRequest,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        return admin_status_change(
            request, service.approve_credential, x_admin_key, x_tenant_id
        )

    @router.post("/api/v1/admin/acl/credentials/disable")
    def disable(
        request: CredentialActionRequest,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        return admin_status_change(
            request, service.disable_credential, x_admin_key, x_tenant_id
        )

    @router.post("/api/v1/admin/acl/credentials/revoke")
    def revoke(
        request: CredentialActionRequest,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        return admin_status_change(
            request, service.revoke_credential, x_admin_key, x_tenant_id
        )

    def admin_grant_change(
        request: DoorGrantRequest,
        action: Callable[..., dict[str, Any]],
        x_admin_key: Optional[str],
        x_tenant_id: Optional[str],
    ) -> dict[str, Any]:
        tenant_id, actor = scoped(
            request.tenant_id, require_admin(x_admin_key, x_tenant_id)
        )
        return _invoke(
            action,
            tenant_id,
            request.door_id,
            request.credential_id,
            actor_ref=actor,
        )

    @router.post("/api/v1/admin/acl/grants/grant")
    def grant_door(
        request: DoorGrantRequest,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        return admin_grant_change(
            request, service.grant_credential_to_door, x_admin_key, x_tenant_id
        )

    @router.post("/api/v1/admin/acl/grants/remove")
    def remove_door_grant(
        request: DoorGrantRequest,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        return admin_grant_change(
            request, service.remove_credential_from_door, x_admin_key, x_tenant_id
        )

    @router.post("/api/v1/admin/acl/snapshots/{door_id}")
    def publish_snapshot(
        door_id: str,
        request: SnapshotPublishRequest,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        tenant_id, actor = scoped(
            request.tenant_id, require_admin(x_admin_key, x_tenant_id)
        )
        return _invoke(
            service.publish_snapshot,
            tenant_id,
            door_id,
            actor_ref=actor,
            min_protocol=request.min_protocol,
            max_protocol=request.max_protocol,
        )

    @router.get("/api/v1/acl/snapshots/{door_id}")
    def pull_snapshot(
        door_id: str,
        x_target_key: Optional[str] = Header(default=None, alias="X-Target-Key"),
        x_target_id: Optional[str] = Header(default=None, alias="X-Target-ID"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        tenant_id, _, _, authorized_door = require_target(
            x_target_key, x_target_id, x_tenant_id
        )
        if not secrets.compare_digest(door_id, authorized_door):
            raise HTTPException(status_code=403, detail="target door boundary violation")
        return _invoke(service.pull_snapshot, tenant_id, door_id)

    @router.post("/api/v1/acl/acks")
    def acknowledge(
        request: AckRequest,
        x_target_key: Optional[str] = Header(default=None, alias="X-Target-Key"),
        x_target_id: Optional[str] = Header(default=None, alias="X-Target-ID"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        target_auth = require_target(x_target_key, x_target_id, x_tenant_id)
        tenant_id, _ = scoped(
            request.tenant_id, (target_auth[0], target_auth[1])
        )
        if not secrets.compare_digest(request.target_id, target_auth[2]):
            raise HTTPException(status_code=403, detail="target identity violation")
        if not secrets.compare_digest(request.door_id, target_auth[3]):
            raise HTTPException(status_code=403, detail="target door boundary violation")
        return _invoke(
            service.ack_snapshot,
            tenant_id,
            request.target_id,
            request.door_id,
            request.acl_version,
            request.sha256,
            request.status,
        )

    @router.get("/api/v1/admin/acl/fleet/{door_id}")
    def fleet(
        door_id: str,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        tenant_id, _ = require_admin(x_admin_key, x_tenant_id)
        return _invoke(service.fleet_status, tenant_id, door_id)

    @router.put("/api/v1/admin/ota/metadata")
    def put_ota_metadata(
        request: OtaMetadataRequest,
        x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, str]:
        tenant_id, actor = scoped(
            request.tenant_id, require_admin(x_admin_key, x_tenant_id)
        )
        metadata = request.model_dump(exclude={"tenant_id"})
        _invoke(service.put_ota_metadata, tenant_id, metadata, actor_ref=actor)
        return {"status": "published"}

    @router.get("/api/v1/ota/{component}/metadata")
    def get_ota_metadata(
        component: Literal["target", "mobile"],
        x_target_key: Optional[str] = Header(default=None, alias="X-Target-Key"),
        x_target_id: Optional[str] = Header(default=None, alias="X-Target-ID"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        tenant_id, _, _, _ = require_target(x_target_key, x_target_id, x_tenant_id)
        return _invoke(service.get_ota_metadata, tenant_id, component)

    @router.post("/api/v1/ota/health")
    def confirm_ota_health(
        request: OtaHealthRequest,
        x_target_key: Optional[str] = Header(default=None, alias="X-Target-Key"),
        x_target_id: Optional[str] = Header(default=None, alias="X-Target-ID"),
        x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    ) -> dict[str, Any]:
        target_auth = require_target(x_target_key, x_target_id, x_tenant_id)
        tenant_id, _ = scoped(
            request.tenant_id, (target_auth[0], target_auth[1])
        )
        if not secrets.compare_digest(request.target_id, target_auth[2]):
            raise HTTPException(status_code=403, detail="target identity violation")
        return _invoke(
            service.confirm_ota_health,
            tenant_id,
            request.target_id,
            component=request.component,
            version=request.version,
            boot_id=request.boot_id,
            artifact_sha256=request.artifact_sha256,
            healthy=request.healthy,
        )

    return router
