"""Hardwareless RC ACL management plane.

The module deliberately owns only public device credentials and signed ACL state. Mobile
private keys and per-device shared secrets are neither accepted nor persisted. The storage
adapter is DB-API based so production can use PyMySQL while tests use an isolated SQLite DB.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional


P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (GX, GY)
ACL_DOMAIN = b"SGKACL01"
ENROLLMENT_DOMAIN = b"SGKENR01"
ACTIVE_STATUS = "ACTIVE"
KNOWN_CREDENTIAL_STATUSES = {"PENDING", "ACTIVE", "DISABLED", "REVOKED", "EXPIRED"}


def legacy_device_storage_id(device_id: str) -> str:
    """Return the bounded legacy-table locator for one validated app ID.

    Existing ``DEV-*`` installations that already fit keep their historical
    value. Fresh installs use a random UUID-shaped ``GK-*`` identifier, which
    cannot fit the legacy MariaDB ``VARCHAR(17)`` column. Store a deterministic
    70-bit digest locator for any longer accepted ID instead of truncating or
    persisting it.
    """

    normalized = device_id.strip().upper()
    if normalized.startswith(("DEV-", "GK-")) and len(normalized) <= 17:
        return normalized
    if not normalized.startswith(("DEV-", "GK-")):
        raise ValueError("invalid legacy device ID")
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    token = base64.b32encode(digest).decode("ascii").rstrip("=")[:14]
    return f"ID-{token}"


class MqttPublishError(RuntimeError):
    """Snapshot is durable for pull, but MQTT delivery did not complete."""


class CredentialConflictError(ValueError):
    """A client-selected credential identity conflicts with durable ACL state."""


def _u8(value: int) -> bytes:
    if not 0 <= value <= 0xFF:
        raise ValueError("u8 out of range")
    return value.to_bytes(1, "big")


def _u16(value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError("u16 out of range")
    return value.to_bytes(2, "big")


def _u32(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("u32 out of range")
    return value.to_bytes(4, "big")


def _u64(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("u64 out of range")
    return value.to_bytes(8, "big")


def _hex_bytes(value: str, size: int, field: str) -> bytes:
    if len(value) != size * 2 or value.lower() != value:
        raise ValueError(f"{field} must be {size} bytes of lowercase hexadecimal")
    try:
        result = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be lowercase hexadecimal") from exc
    if len(result) != size:
        raise ValueError(f"{field} must be {size} bytes")
    return result


def _point_add(
    left: tuple[int, int] | None, right: tuple[int, int] | None
) -> tuple[int, int] | None:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if left == right:
        slope = ((3 * x1 * x1 + A) * pow(2 * y1, -1, P)) % P
    else:
        slope = ((y2 - y1) * pow((x2 - x1) % P, -1, P)) % P
    x3 = (slope * slope - x1 - x2) % P
    y3 = (slope * (x1 - x3) - y1) % P
    return x3, y3


def _scalar_mult(
    scalar: int, point: tuple[int, int] | None = G
) -> tuple[int, int] | None:
    result = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def _parse_public_key(value: bytes) -> tuple[int, int]:
    if len(value) != 65 or value[0] != 4:
        raise ValueError("invalid uncompressed SEC1 public key")
    point = (int.from_bytes(value[1:33], "big"), int.from_bytes(value[33:], "big"))
    if not (0 <= point[0] < P and 0 <= point[1] < P):
        raise ValueError("public key coordinate out of range")
    if (point[1] * point[1] - (point[0] ** 3 + A * point[0] + B)) % P:
        raise ValueError("public key is not on P-256")
    return point


def _rfc6979_nonce(private_scalar: int, digest: bytes) -> int:
    scalar = private_scalar.to_bytes(32, "big")
    digest_octets = (int.from_bytes(digest, "big") % N).to_bytes(32, "big")
    key = b"\x00" * 32
    value = b"\x01" * 32
    key = hmac.new(key, value + b"\x00" + scalar + digest_octets, hashlib.sha256).digest()
    value = hmac.new(key, value, hashlib.sha256).digest()
    key = hmac.new(key, value + b"\x01" + scalar + digest_octets, hashlib.sha256).digest()
    value = hmac.new(key, value, hashlib.sha256).digest()
    while True:
        value = hmac.new(key, value, hashlib.sha256).digest()
        candidate = int.from_bytes(value, "big")
        if 1 <= candidate < N:
            return candidate
        key = hmac.new(key, value + b"\x00", hashlib.sha256).digest()
        value = hmac.new(key, value, hashlib.sha256).digest()


def verify_raw64(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if len(signature) != 64:
        return False
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    if not (1 <= r < N and 1 <= s <= N // 2):
        return False
    try:
        point = _parse_public_key(public_key)
    except ValueError:
        return False
    inverse = pow(s, -1, N)
    digest = int.from_bytes(hashlib.sha256(message).digest(), "big")
    candidate = _point_add(
        _scalar_mult((digest * inverse) % N), _scalar_mult((r * inverse) % N, point)
    )
    return candidate is not None and candidate[0] % N == r


@dataclass(frozen=True)
class DeterministicP256Signer:
    """RFC6979 signer used by the RC and shared deterministic vectors.

    Production deployments should inject an HSM/KMS signer implementing the same ``sign``
    and ``public_key_sec1`` interface; the scalar must never be logged or returned by APIs.
    """

    private_scalar: int
    signing_key_id: int

    def __post_init__(self) -> None:
        if not 1 <= self.private_scalar < N:
            raise ValueError("invalid P-256 private scalar")

    @property
    def public_key_sec1(self) -> bytes:
        point = _scalar_mult(self.private_scalar)
        if point is None:
            raise ValueError("invalid private scalar")
        return b"\x04" + point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")

    def sign(self, message: bytes) -> bytes:
        digest = hashlib.sha256(message).digest()
        nonce = _rfc6979_nonce(self.private_scalar, digest)
        point = _scalar_mult(nonce)
        if point is None:
            raise AssertionError("unexpected point at infinity")
        r = point[0] % N
        s = (
            pow(nonce, -1, N)
            * (int.from_bytes(digest, "big") + r * self.private_scalar)
        ) % N
        if s > N // 2:
            s = N - s
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def build_enrollment_input(
    tenant_id: str,
    enrollment_id: str,
    nonce_hex: str,
    public_key_hex: str,
    protocol_version: int = 1,
) -> bytes:
    public_key = _hex_bytes(public_key_hex, 65, "public_key")
    _parse_public_key(public_key)
    return b"".join(
        (
            ENROLLMENT_DOMAIN,
            _u16(protocol_version),
            _hex_bytes(tenant_id, 16, "tenant_id"),
            _hex_bytes(enrollment_id, 16, "enrollment_id"),
            _hex_bytes(nonce_hex, 32, "nonce"),
            public_key,
        )
    )


def validate_acl_fields(fields: dict[str, Any]) -> None:
    entries = fields["entries"]
    if fields["schema_version"] != 1:
        raise ValueError("unknown ACL schema_version")
    if fields["acl_version"] < 1:
        raise ValueError("ACL version must be positive")
    if not 1 <= fields["lease_duration_s"] <= 3600:
        raise ValueError("ACL lease out of range")
    if not (
        fields["issued_at_epoch_s"]
        <= fields["not_before_epoch_s"]
        < fields["expires_at_epoch_s"]
    ):
        raise ValueError("invalid ACL snapshot time range")
    if not 1 <= fields["min_protocol"] <= fields["max_protocol"]:
        raise ValueError("invalid ACL snapshot protocol range")
    if len(entries) > 64:
        raise ValueError("too many ACL entries")
    credential_ids = [
        _hex_bytes(entry["credential_id"], 16, "credential_id") for entry in entries
    ]
    if credential_ids != sorted(credential_ids) or len(set(credential_ids)) != len(entries):
        raise ValueError("ACL entries must be unique and sorted")
    for entry in entries:
        public_key = _hex_bytes(entry["public_key_sec1"], 65, "public_key_sec1")
        _parse_public_key(public_key)
        if entry["status"] not in (0, 1):
            raise ValueError("unknown ACL status")
        if entry["permissions"] & ~1:
            raise ValueError("unknown ACL permission bits")
        if not entry["not_before_epoch_s"] < entry["not_after_epoch_s"]:
            raise ValueError("invalid ACL entry time range")
        if not (
            fields["min_protocol"]
            <= entry["min_protocol"]
            <= entry["max_protocol"]
            <= fields["max_protocol"]
        ):
            raise ValueError("invalid ACL entry protocol range")


def encode_acl(fields: dict[str, Any]) -> bytes:
    validate_acl_fields(fields)
    encoded = bytearray(
        b"".join(
            (
                ACL_DOMAIN,
                _u16(fields["schema_version"]),
                _hex_bytes(fields["door_id"], 16, "door_id"),
                _u64(fields["acl_version"]),
                _u64(fields["issued_at_epoch_s"]),
                _u64(fields["not_before_epoch_s"]),
                _u64(fields["expires_at_epoch_s"]),
                _u32(fields["lease_duration_s"]),
                _u16(fields["min_protocol"]),
                _u16(fields["max_protocol"]),
                _u32(fields["signing_key_id"]),
                _u16(len(fields["entries"])),
            )
        )
    )
    for entry in fields["entries"]:
        encoded.extend(_hex_bytes(entry["credential_id"], 16, "credential_id"))
        encoded.extend(_hex_bytes(entry["public_key_sec1"], 65, "public_key_sec1"))
        encoded.extend(_u8(entry["status"]))
        encoded.extend(_u32(entry["permissions"]))
        encoded.extend(_u64(entry["not_before_epoch_s"]))
        encoded.extend(_u64(entry["not_after_epoch_s"]))
        encoded.extend(_u16(entry["min_protocol"]))
        encoded.extend(_u16(entry["max_protocol"]))
    return bytes(encoded)


def verify_snapshot_envelope(
    envelope: dict[str, Any],
    *,
    trusted_signing_keys: dict[int, bytes],
    expected_door_id: str,
    target_min_protocol: int,
    target_max_protocol: int,
    trusted_now_epoch_s: int,
    current_boot_id: str,
    receipt_boot_id: str,
    effective_high_watermark: int,
    current_digest: str,
) -> str:
    fields = envelope["fields"]
    canonical = encode_acl(fields)
    canonical_hex = canonical.hex()
    digest = hashlib.sha256(canonical).hexdigest()
    if not hmac.compare_digest(canonical_hex, envelope["canonical_hex"]):
        raise ValueError("ACL canonical bytes mismatch")
    if not hmac.compare_digest(digest, envelope["sha256"]):
        raise ValueError("ACL digest mismatch")
    _hex_bytes(expected_door_id, 16, "expected_door_id")
    if not hmac.compare_digest(fields["door_id"], expected_door_id):
        raise ValueError("ACL door boundary violation")
    if not 1 <= target_min_protocol <= target_max_protocol:
        raise ValueError("invalid Target protocol range")
    if (
        fields["max_protocol"] < target_min_protocol
        or fields["min_protocol"] > target_max_protocol
    ):
        raise ValueError("ACL protocol is incompatible with Target")
    if not (
        fields["not_before_epoch_s"]
        <= trusted_now_epoch_s
        < fields["expires_at_epoch_s"]
    ):
        raise ValueError("ACL trusted time validation failed")
    if not current_boot_id or not hmac.compare_digest(current_boot_id, receipt_boot_id):
        raise ValueError("ACL receipt boot identity mismatch")

    signatures = [
        {
            "signing_key_id": fields["signing_key_id"],
            "signature_raw64": envelope.get("signature_raw64"),
        },
        *envelope.get("signatures", []),
    ]
    trusted_candidate_seen = False
    valid_signature = False
    for signed in signatures:
        try:
            key_id = int(signed["signing_key_id"])
            signature = bytes.fromhex(signed["signature_raw64"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("invalid ACL signature encoding") from exc
        public_key = trusted_signing_keys.get(key_id)
        if public_key is None:
            continue
        trusted_candidate_seen = True
        if verify_raw64(public_key, canonical, signature):
            valid_signature = True
            break
    if not trusted_candidate_seen:
        raise ValueError("untrusted ACL signing key")
    if not valid_signature:
        raise ValueError("invalid ACL signature")

    version = fields["acl_version"]
    if version < effective_high_watermark:
        return "reject_stale"
    if version == effective_high_watermark:
        if hmac.compare_digest(digest, current_digest):
            return "idempotent_no_lease_refresh"
        return "reject_version_conflict"
    return "activate"


def acl_snapshot_is_usable(
    *,
    received_monotonic_s: int,
    now_monotonic_s: int,
    lease_seconds: int,
    receipt_boot_id: str,
    current_boot_id: str,
    not_before_epoch_s: int,
    expires_at_epoch_s: int,
    received_epoch_s: Optional[int],
    trusted_now_epoch_s: Optional[int],
) -> bool:
    """Local lease check that intentionally has no Backend/network dependency."""
    if not 1 <= lease_seconds <= 3600 or not receipt_boot_id or not current_boot_id:
        return False
    trusted_time_valid = False
    if trusted_now_epoch_s is not None:
        trusted_time_valid = (
            not_before_epoch_s <= trusted_now_epoch_s < expires_at_epoch_s
        )
        if received_epoch_s is not None:
            trusted_time_valid = trusted_time_valid and (
                received_epoch_s
                <= trusted_now_epoch_s
                < received_epoch_s + lease_seconds
            )
    if not hmac.compare_digest(receipt_boot_id, current_boot_id):
        return received_epoch_s is not None and trusted_time_valid
    if now_monotonic_s < received_monotonic_s:
        return False
    monotonic_valid = now_monotonic_s < received_monotonic_s + lease_seconds
    if trusted_now_epoch_s is not None and not trusted_time_valid:
        return False
    return monotonic_valid


def initialize_sqlite_test_schema(connection: sqlite3.Connection) -> None:
    """Create the expanded management schema in an isolated test database."""
    connection.executescript(
        """
        CREATE TABLE tenants (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          unit_number TEXT NOT NULL,
          ble_device_mac TEXT UNIQUE,
          is_active INTEGER NOT NULL DEFAULT 1,
          tenant_uuid TEXT UNIQUE,
          credential_mode TEXT NOT NULL DEFAULT 'legacy',
          credential_id TEXT UNIQUE,
          mobile_role TEXT NOT NULL DEFAULT 'USER'
        );
        CREATE TABLE acl_tenants (
          tenant_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')),
          updated_at INTEGER NOT NULL,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE enrollment_challenges (
          enrollment_id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          actor_ref TEXT NOT NULL,
          nonce_hash TEXT NOT NULL,
          expires_at INTEGER NOT NULL,
          used_at INTEGER,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE credentials (
          credential_id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          public_key_sec1 TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL,
          expires_at INTEGER,
          legacy_device_ref TEXT,
          min_protocol INTEGER NOT NULL,
          max_protocol INTEGER NOT NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE INDEX idx_credentials_tenant_status
          ON credentials(tenant_id, status, credential_id);
        CREATE TABLE credential_door_grants (
          tenant_id TEXT NOT NULL,
          door_id TEXT NOT NULL,
          credential_id TEXT NOT NULL,
          permissions INTEGER NOT NULL,
          granted_at INTEGER NOT NULL,
          revoked_at INTEGER,
          PRIMARY KEY (tenant_id, door_id, credential_id)
        );
        CREATE TABLE acl_door_state (
          tenant_id TEXT NOT NULL,
          door_id TEXT NOT NULL UNIQUE,
          last_version INTEGER NOT NULL,
          PRIMARY KEY (tenant_id, door_id)
        );
        CREATE TABLE acl_snapshots (
          tenant_id TEXT NOT NULL,
          door_id TEXT NOT NULL,
          acl_version INTEGER NOT NULL,
          sha256 TEXT NOT NULL,
          envelope_json TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          PRIMARY KEY (tenant_id, door_id, acl_version)
        );
        CREATE TABLE acl_snapshot_jobs (
          tenant_id TEXT NOT NULL,
          door_id TEXT NOT NULL,
          reason TEXT NOT NULL,
          requested_at INTEGER NOT NULL,
          generated_version INTEGER,
          revision INTEGER NOT NULL,
          PRIMARY KEY (tenant_id, door_id)
        );
        CREATE TABLE target_acl_acks (
          ack_id INTEGER PRIMARY KEY AUTOINCREMENT,
          tenant_id TEXT NOT NULL,
          target_id TEXT NOT NULL,
          door_id TEXT NOT NULL,
          acl_version INTEGER NOT NULL,
          sha256 TEXT NOT NULL,
          status TEXT NOT NULL,
          acked_at INTEGER NOT NULL,
          UNIQUE (tenant_id, target_id, door_id, acl_version, sha256)
        );
        CREATE TABLE management_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tenant_id TEXT NOT NULL,
          actor_ref TEXT NOT NULL,
          action TEXT NOT NULL,
          credential_id TEXT,
          metadata_json TEXT NOT NULL,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE ota_release_metadata (
          tenant_id TEXT NOT NULL,
          component TEXT NOT NULL,
          metadata_json TEXT NOT NULL,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY (tenant_id, component)
        );
        CREATE TABLE ota_health_confirmations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tenant_id TEXT NOT NULL,
          target_id TEXT NOT NULL,
          component TEXT NOT NULL,
          version TEXT NOT NULL,
          boot_id TEXT NOT NULL,
          artifact_sha256 TEXT NOT NULL,
          status TEXT NOT NULL,
          confirmed_at INTEGER NOT NULL
        );
        """
    )
    connection.commit()


class AclStore:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        dialect: str = "mysql",
        close_connections: bool = True,
    ) -> None:
        self.connection_factory = connection_factory
        self.dialect = dialect
        self.close_connections = close_connections

    def _sql(self, statement: str) -> str:
        return statement if self.dialect == "sqlite" else statement.replace("?", "%s")

    def _connection(self) -> Any:
        return self.connection_factory()

    @staticmethod
    def _dict(row: Any) -> Optional[dict[str, Any]]:
        return dict(row) if row is not None else None

    def _close(self, connection: Any) -> None:
        if self.close_connections:
            connection.close()

    def _write(self, statement: str, params: Iterable[Any] = ()) -> tuple[int, int]:
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute(self._sql(statement), tuple(params))
            lastrowid = int(cursor.lastrowid or 0)
            rowcount = int(cursor.rowcount)
            connection.commit()
            return lastrowid, rowcount
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)

    def _one(self, statement: str, params: Iterable[Any] = ()) -> Optional[dict[str, Any]]:
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute(self._sql(statement), tuple(params))
            return self._dict(cursor.fetchone())
        finally:
            self._close(connection)

    def _all(self, statement: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute(self._sql(statement), tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self._close(connection)

    def create_tenant(self, tenant_id: str, display_name: str) -> None:
        _hex_bytes(tenant_id, 16, "tenant_id")
        now = int(time.time())
        if self.dialect == "sqlite":
            statement = (
                "INSERT OR IGNORE INTO acl_tenants "
                "(tenant_id, display_name, status, updated_at, created_at) "
                "VALUES (?, ?, 'ACTIVE', ?, ?)"
            )
        else:
            statement = (
                "INSERT INTO acl_tenants "
                "(tenant_id, display_name, status, updated_at, created_at) "
                "VALUES (?, ?, 'ACTIVE', ?, ?) "
                "ON DUPLICATE KEY UPDATE display_name=VALUES(display_name)"
            )
        self._write(statement, (tenant_id, display_name, now, now))

    def register_legacy_tenant(
        self, legacy_tenant_id: int, tenant_id: str, display_name: str, now: int
    ) -> None:
        if self.dialect == "sqlite":
            self.create_tenant(tenant_id, display_name)
            return
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute("START TRANSACTION")
            cursor.execute(
                "SELECT tenant_uuid, is_active FROM tenants WHERE id=%s FOR UPDATE",
                (legacy_tenant_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise LookupError("legacy tenant not found")
            existing = row["tenant_uuid"] if isinstance(row, dict) else row[0]
            legacy_is_active = bool(row["is_active"] if isinstance(row, dict) else row[1])
            if existing is not None and not hmac.compare_digest(str(existing), tenant_id):
                raise ValueError("legacy tenant already has a different canonical ID")
            cursor.execute(
                "UPDATE tenants SET tenant_uuid=%s WHERE id=%s",
                (tenant_id, legacy_tenant_id),
            )
            cursor.execute(
                "INSERT INTO acl_tenants "
                "(tenant_id, display_name, status, updated_at, created_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE display_name=VALUES(display_name)",
                (
                    tenant_id,
                    display_name,
                    "ACTIVE" if legacy_is_active else "DISABLED",
                    now,
                    now,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)


    def tenant_exists(self, tenant_id: str) -> bool:
        return self._one("SELECT tenant_id FROM acl_tenants WHERE tenant_id=?", (tenant_id,)) is not None

    def tenant_status(self, tenant_id: str) -> Optional[str]:
        row = self._one(
            "SELECT status FROM acl_tenants WHERE tenant_id=?", (tenant_id,)
        )
        return str(row["status"]) if row else None

    def tenant_display_name(self, tenant_id: str) -> Optional[str]:
        row = self._one(
            "SELECT display_name FROM acl_tenants WHERE tenant_id=?", (tenant_id,)
        )
        return str(row["display_name"]) if row else None

    def legacy_personal_state(
        self, tenant_id: str, legacy_device_id: str
    ) -> Optional[dict[str, Any]]:
        """Migration-only lookup; never reports the local credential as ready."""

        if self.dialect == "sqlite":
            row = self._one(
                "SELECT name, unit_number, is_active, tenant_uuid FROM tenants "
                "WHERE UPPER(ble_device_mac)=?",
                (legacy_device_storage_id(legacy_device_id),),
            )
        else:
            row = self._one(
                "SELECT name, unit_number, is_active, tenant_uuid FROM tenants "
                "WHERE UPPER(ble_device_mac)=?",
                (legacy_device_storage_id(legacy_device_id),),
            )
        if row is None:
            return None
        mapped = row.get("tenant_uuid")
        if mapped is not None and not hmac.compare_digest(str(mapped), tenant_id):
            return None
        return {
            "is_active": bool(row["is_active"]),
            "tenant_label": str(row.get("unit_number") or "Smart Key"),
        }

    def legacy_tenant_is_active(self, tenant_id: str) -> Optional[bool]:
        """Return the mapped legacy state; SQLite has no legacy tenant table."""
        if self.dialect == "sqlite":
            return None
        row = self._one(
            "SELECT is_active FROM tenants WHERE tenant_uuid=?", (tenant_id,)
        )
        return bool(row["is_active"]) if row else None

    def insert_challenge(
        self,
        enrollment_id: str,
        tenant_id: str,
        actor_ref: str,
        nonce_hash: str,
        expires_at: int,
        now: int,
    ) -> None:
        self._write(
            "INSERT INTO enrollment_challenges "
            "(enrollment_id, tenant_id, actor_ref, nonce_hash, expires_at, used_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?)",
            (enrollment_id, tenant_id, actor_ref, nonce_hash, expires_at, now),
        )

    def get_challenge(self, tenant_id: str, enrollment_id: str) -> Optional[dict[str, Any]]:
        return self._one(
            "SELECT * FROM enrollment_challenges WHERE tenant_id=? AND enrollment_id=?",
            (tenant_id, enrollment_id),
        )

    def consume_challenge(self, tenant_id: str, enrollment_id: str, now: int) -> bool:
        _, count = self._write(
            "UPDATE enrollment_challenges SET used_at=? "
            "WHERE tenant_id=? AND enrollment_id=? AND used_at IS NULL",
            (now, tenant_id, enrollment_id),
        )
        return count == 1

    def insert_credential(self, values: dict[str, Any]) -> None:
        self._write(
            "INSERT INTO credentials "
            "(credential_id, tenant_id, public_key_sec1, status, expires_at, legacy_device_ref, "
            "min_protocol, max_protocol, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                values["credential_id"],
                values["tenant_id"],
                values["public_key_sec1"],
                values["status"],
                values.get("expires_at"),
                values.get("legacy_device_ref"),
                values["min_protocol"],
                values["max_protocol"],
                values["created_at"],
                values["updated_at"],
            ),
        )

    def consume_challenge_and_insert_credential(
        self,
        tenant_id: str,
        enrollment_id: str,
        actor_ref: str,
        now: int,
        values: dict[str, Any],
    ) -> bool:
        """Atomically consume a challenge and persist its public credential."""
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "BEGIN IMMEDIATE" if self.dialect == "sqlite" else "START TRANSACTION"
            )
            cursor.execute(
                self._sql(
                    "UPDATE enrollment_challenges SET used_at=? "
                    "WHERE tenant_id=? AND enrollment_id=? AND actor_ref=? "
                    "AND used_at IS NULL"
                ),
                (now, tenant_id, enrollment_id, actor_ref),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            cursor.execute(
                self._sql(
                    "INSERT INTO credentials "
                    "(credential_id, tenant_id, public_key_sec1, status, expires_at, "
                    "legacy_device_ref, min_protocol, max_protocol, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    values["credential_id"],
                    values["tenant_id"],
                    values["public_key_sec1"],
                    values["status"],
                    values.get("expires_at"),
                    values.get("legacy_device_ref"),
                    values["min_protocol"],
                    values["max_protocol"],
                    values["created_at"],
                    values["updated_at"],
                ),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)

    def get_credential(self, tenant_id: str, credential_id: str) -> Optional[dict[str, Any]]:
        return self._one(
            "SELECT * FROM credentials WHERE tenant_id=? AND credential_id=?",
            (tenant_id, credential_id),
        )

    def bind_personal_credential_to_legacy_row(
        self,
        tenant_id: str,
        legacy_device_id: str,
        credential_id: str,
        legacy_ref: str,
    ) -> None:
        """Idempotently bind a verified public credential to one legacy row.

        This is the deletion/revocation join.  It stores neither the original
        high-entropy app identifier nor private key material.
        """
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "BEGIN IMMEDIATE" if self.dialect == "sqlite" else "START TRANSACTION"
            )
            placeholder = "?" if self.dialect == "sqlite" else "%s"
            lock_suffix = "" if self.dialect == "sqlite" else " FOR UPDATE"
            locator = legacy_device_storage_id(legacy_device_id)
            cursor.execute(
                f"SELECT id, credential_id FROM tenants "
                f"WHERE UPPER(ble_device_mac)={placeholder}{lock_suffix}",
                (locator,),
            )
            legacy = cursor.fetchone()
            if legacy is None:
                raise PermissionError("legacy device is not registered")
            legacy_id = int(legacy["id"] if isinstance(legacy, dict) else legacy[0])
            linked = legacy["credential_id"] if isinstance(legacy, dict) else legacy[1]
            cursor.execute(
                f"SELECT tenant_id, legacy_device_ref FROM credentials "
                f"WHERE credential_id={placeholder}{lock_suffix}",
                (credential_id,),
            )
            credential = cursor.fetchone()
            if credential is None:
                raise PermissionError("public credential is unavailable")
            credential_tenant = str(
                credential["tenant_id"] if isinstance(credential, dict) else credential[0]
            )
            credential_ref = str(
                credential["legacy_device_ref"]
                if isinstance(credential, dict)
                else credential[1]
            )
            if not hmac.compare_digest(credential_tenant, tenant_id) or not hmac.compare_digest(
                credential_ref, legacy_ref
            ):
                raise PermissionError("credential does not belong to legacy device")
            if linked is not None and not hmac.compare_digest(str(linked), credential_id):
                raise CredentialConflictError("legacy account has another credential")
            cursor.execute(
                f"SELECT id FROM tenants WHERE credential_id={placeholder} "
                f"AND id<>{placeholder}{lock_suffix}",
                (credential_id, legacy_id),
            )
            if cursor.fetchone() is not None:
                raise CredentialConflictError("credential belongs to another legacy account")
            if linked is None:
                cursor.execute(
                    f"UPDATE tenants SET credential_id={placeholder} "
                    f"WHERE id={placeholder} AND credential_id IS NULL",
                    (credential_id, legacy_id),
                )
                if cursor.rowcount != 1:
                    raise CredentialConflictError("legacy credential binding lost its lock")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)

    def personal_account_profile(
        self, tenant_id: str, credential_id: str
    ) -> Optional[dict[str, str]]:
        """Return only the account linked to this verified phone credential.

        A personal ACL tenant may contain multiple residents.  Its shared
        display name is therefore never a valid per-phone identity label.
        """

        _hex_bytes(tenant_id, 16, "tenant_id")
        _hex_bytes(credential_id, 16, "credential_id")
        rows = self._all(
            "SELECT name, unit_number, tenant_uuid, mobile_role FROM tenants "
            "WHERE credential_id=? ORDER BY id ASC",
            (credential_id,),
        )
        if len(rows) != 1:
            return None
        row = rows[0]
        mapped_tenant = row.get("tenant_uuid")
        if mapped_tenant is not None and not hmac.compare_digest(
            str(mapped_tenant), tenant_id
        ):
            return None
        name = str(row.get("name") or "").strip()
        unit_number = str(row.get("unit_number") or "").strip()
        if not name or not unit_number:
            return None
        mobile_role = str(row.get("mobile_role") or "USER")
        if mobile_role not in {"USER", "TENANT_ADMIN"}:
            mobile_role = "USER"
        return {
            "name": name,
            "unit_number": unit_number,
            "mobile_role": mobile_role,
        }

    def list_credentials(
        self, tenant_id: str, *, statuses: tuple[str, ...] = ("ACTIVE",)
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in statuses)
        return self._all(
            f"SELECT * FROM credentials WHERE tenant_id=? AND status IN ({placeholders}) "
            "ORDER BY credential_id ASC",
            (tenant_id, *statuses),
        )

    def grant_credential(
        self,
        tenant_id: str,
        door_id: str,
        credential_id: str,
        permissions: int,
        now: int,
    ) -> None:
        if self.dialect == "sqlite":
            statement = (
                "INSERT INTO credential_door_grants "
                "(tenant_id, door_id, credential_id, permissions, granted_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, NULL) ON CONFLICT(tenant_id, door_id, credential_id) "
                "DO UPDATE SET permissions=excluded.permissions, granted_at=excluded.granted_at, "
                "revoked_at=NULL"
            )
        else:
            statement = (
                "INSERT INTO credential_door_grants "
                "(tenant_id, door_id, credential_id, permissions, granted_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, NULL) ON DUPLICATE KEY UPDATE "
                "permissions=VALUES(permissions), granted_at=VALUES(granted_at), revoked_at=NULL"
            )
        self._write(statement, (tenant_id, door_id, credential_id, permissions, now))

    def bootstrap_personal_credential_and_queue(
        self,
        tenant_id: str,
        door_id: str,
        legacy_device_id: str,
        credential: dict[str, Any],
        *,
        actor_ref: str,
        now: int,
    ) -> dict[str, Any]:
        """Atomically authorize one approved legacy device and queue its ACL.

        The raw legacy device identifier is used only for the locked legacy-row
        lookup and is never copied into the public credential or audit tables.
        One legacy row may remain the compatibility owner of the configured
        personal tenant while additional independently approved family devices
        join that same tenant with distinct public credentials. Existing
        revoked/disabled bindings are deliberately not resurrected.
        """
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "BEGIN IMMEDIATE" if self.dialect == "sqlite" else "START TRANSACTION"
            )
            placeholder = "?" if self.dialect == "sqlite" else "%s"
            lock_suffix = "" if self.dialect == "sqlite" else " FOR UPDATE"

            def row_value(row: Any, name: str, index: int) -> Any:
                return row[name] if isinstance(row, dict) else row[index]

            cursor.execute(
                "SELECT id, name, unit_number, tenant_uuid, is_active, credential_mode, credential_id "
                "FROM tenants "
                f"WHERE UPPER(ble_device_mac)={placeholder}{lock_suffix}",
                (legacy_device_storage_id(legacy_device_id),),
            )
            legacy_rows = cursor.fetchall()
            if len(legacy_rows) != 1:
                raise PermissionError("legacy device is not approved")
            legacy = legacy_rows[0]
            legacy_id = int(row_value(legacy, "id", 0))
            legacy_tenant_id = row_value(legacy, "tenant_uuid", 3)
            legacy_active = bool(row_value(legacy, "is_active", 4))
            legacy_credential_mode = str(row_value(legacy, "credential_mode", 5))
            linked_credential_id = row_value(legacy, "credential_id", 6)
            if not legacy_active:
                raise PermissionError("legacy device is not approved")
            if legacy_tenant_id is not None and (
                not isinstance(legacy_tenant_id, str)
                or not hmac.compare_digest(legacy_tenant_id, tenant_id)
            ):
                raise CredentialConflictError(
                    "legacy device is already mapped to another tenant"
                )

            cursor.execute(
                f"SELECT id FROM tenants WHERE tenant_uuid={placeholder}{lock_suffix}",
                (tenant_id,),
            )
            mapped_owner = cursor.fetchone()
            mapped_owner_id = (
                int(row_value(mapped_owner, "id", 0))
                if mapped_owner is not None
                else None
            )
            is_additional_personal_device = (
                mapped_owner_id is not None and mapped_owner_id != legacy_id
            )

            cursor.execute(
                f"SELECT status FROM acl_tenants WHERE tenant_id={placeholder}{lock_suffix}",
                (tenant_id,),
            )
            tenant_row = cursor.fetchone()
            if tenant_row is None:
                display_name = (
                    f"{row_value(legacy, 'name', 1)} "
                    f"{row_value(legacy, 'unit_number', 2)}"
                ).strip()[:100]
                cursor.execute(
                    self._sql(
                        "INSERT INTO acl_tenants "
                        "(tenant_id, display_name, status, updated_at, created_at) "
                        "VALUES (?, ?, 'ACTIVE', ?, ?)"
                    ),
                    (tenant_id, display_name or "personal", now, now),
                )
            else:
                tenant_status = str(row_value(tenant_row, "status", 0))
                if tenant_status != "ACTIVE":
                    raise PermissionError("personal ACL tenant is disabled")

            if legacy_tenant_id is None:
                if is_additional_personal_device:
                    if legacy_credential_mode == "legacy":
                        cursor.execute(
                            "UPDATE tenants SET credential_mode='dual' "
                            f"WHERE id={placeholder} AND tenant_uuid IS NULL "
                            "AND credential_mode='legacy'",
                            (legacy_id,),
                        )
                        if cursor.rowcount != 1:
                            raise CredentialConflictError(
                                "additional personal device lost its state lock"
                            )
                    elif legacy_credential_mode != "dual":
                        raise CredentialConflictError(
                            "additional personal device has incompatible credential mode"
                        )
                else:
                    cursor.execute(
                        f"UPDATE tenants SET tenant_uuid={placeholder}, "
                        "credential_mode='dual' "
                        f"WHERE id={placeholder} AND tenant_uuid IS NULL",
                        (tenant_id, legacy_id),
                    )
                    if cursor.rowcount != 1:
                        raise CredentialConflictError(
                            "legacy tenant bootstrap lost its state lock"
                        )
            else:
                cursor.execute(
                    f"UPDATE tenants SET credential_mode='dual' "
                    f"WHERE id={placeholder} AND credential_mode='legacy'",
                    (legacy_id,),
                )

            cursor.execute(
                f"SELECT tenant_id FROM acl_door_state WHERE door_id={placeholder}{lock_suffix}",
                (door_id,),
            )
            owner_row = cursor.fetchone()
            if owner_row is not None:
                owner = str(
                    owner_row["tenant_id"]
                    if isinstance(owner_row, dict)
                    else owner_row[0]
                )
                if not hmac.compare_digest(owner, tenant_id):
                    raise PermissionError("personal door is owned by another tenant")

            credential_id = credential["credential_id"]
            public_key = credential["public_key_sec1"]
            legacy_ref = credential["legacy_device_ref"]
            cursor.execute(
                f"SELECT * FROM credentials WHERE credential_id={placeholder}{lock_suffix}",
                (credential_id,),
            )
            existing = cursor.fetchone()
            cursor.execute(
                f"SELECT credential_id, tenant_id FROM credentials "
                f"WHERE public_key_sec1={placeholder}{lock_suffix}",
                (public_key,),
            )
            key_row = cursor.fetchone()
            cursor.execute(
                f"SELECT * FROM credentials WHERE tenant_id={placeholder} "
                f"AND legacy_device_ref={placeholder}{lock_suffix}",
                (tenant_id, legacy_ref),
            )
            legacy_credentials = cursor.fetchall()

            if key_row is not None and not hmac.compare_digest(
                str(row_value(key_row, "credential_id", 0)), credential_id
            ):
                raise CredentialConflictError("public key is already registered")
            for legacy_credential in legacy_credentials:
                if not hmac.compare_digest(
                    str(row_value(legacy_credential, "credential_id", 0)), credential_id
                ):
                    raise CredentialConflictError(
                        "legacy device already has another public credential"
                    )

            created = existing is None
            if existing is None:
                cursor.execute(
                    self._sql(
                        "INSERT INTO credentials "
                        "(credential_id, tenant_id, public_key_sec1, status, expires_at, "
                        "legacy_device_ref, min_protocol, max_protocol, created_at, updated_at) "
                        "VALUES (?, ?, ?, 'ACTIVE', NULL, ?, ?, ?, ?, ?)"
                    ),
                    (
                        credential_id,
                        tenant_id,
                        public_key,
                        legacy_ref,
                        credential["min_protocol"],
                        credential["max_protocol"],
                        now,
                        now,
                    ),
                )
            else:
                exact = (
                    hmac.compare_digest(str(row_value(existing, "tenant_id", 1)), tenant_id)
                    and hmac.compare_digest(
                        str(row_value(existing, "public_key_sec1", 2)), public_key
                    )
                    and str(row_value(existing, "status", 3)) == "ACTIVE"
                    and row_value(existing, "expires_at", 4) is None
                    and hmac.compare_digest(
                        str(row_value(existing, "legacy_device_ref", 5)), legacy_ref
                    )
                    and int(row_value(existing, "min_protocol", 6))
                    == int(credential["min_protocol"])
                    and int(row_value(existing, "max_protocol", 7))
                    == int(credential["max_protocol"])
                )
                if not exact:
                    raise CredentialConflictError(
                        "credential ID conflicts with existing registration"
                    )

            if linked_credential_id is not None and not hmac.compare_digest(
                str(linked_credential_id), credential_id
            ):
                raise CredentialConflictError(
                    "legacy account is already linked to another credential"
                )
            if linked_credential_id is None:
                cursor.execute(
                    f"SELECT id FROM tenants WHERE credential_id={placeholder} "
                    f"AND id<>{placeholder}{lock_suffix}",
                    (credential_id, legacy_id),
                )
                if cursor.fetchone() is not None:
                    raise CredentialConflictError(
                        "credential is already linked to another legacy account"
                    )
                cursor.execute(
                    f"UPDATE tenants SET credential_id={placeholder} "
                    f"WHERE id={placeholder} AND credential_id IS NULL",
                    (credential_id, legacy_id),
                )
                if cursor.rowcount != 1:
                    raise CredentialConflictError(
                        "legacy credential binding lost its state lock"
                    )

            cursor.execute(
                f"SELECT permissions, revoked_at FROM credential_door_grants "
                f"WHERE tenant_id={placeholder} AND door_id={placeholder} "
                f"AND credential_id={placeholder}{lock_suffix}",
                (tenant_id, door_id, credential_id),
            )
            grant = cursor.fetchone()
            if grant is None:
                cursor.execute(
                    self._sql(
                        "INSERT INTO credential_door_grants "
                        "(tenant_id, door_id, credential_id, permissions, granted_at, revoked_at) "
                        "VALUES (?, ?, ?, 1, ?, NULL)"
                    ),
                    (tenant_id, door_id, credential_id, now),
                )
            elif (
                int(row_value(grant, "permissions", 0)) != 1
                or row_value(grant, "revoked_at", 1) is not None
            ):
                raise CredentialConflictError("personal door grant was revoked or changed")

            cursor.execute(
                f"SELECT generated_version, revision FROM acl_snapshot_jobs "
                f"WHERE tenant_id={placeholder} AND door_id={placeholder}{lock_suffix}",
                (tenant_id, door_id),
            )
            pending_job = cursor.fetchone()
            current_version: Optional[int] = None
            if pending_job is None and not created:
                cursor.execute(
                    f"SELECT acl_version, envelope_json FROM acl_snapshots "
                    f"WHERE tenant_id={placeholder} AND door_id={placeholder} "
                    "ORDER BY acl_version DESC LIMIT 1"
                    + lock_suffix,
                    (tenant_id, door_id),
                )
                latest = cursor.fetchone()
                if latest is not None:
                    envelope = json.loads(
                        str(row_value(latest, "envelope_json", 1))
                    )
                    fields = envelope.get("fields", {})
                    entry = next(
                        (
                            item
                            for item in fields.get("entries", [])
                            if item.get("credential_id") == credential_id
                            and item.get("public_key_sec1") == public_key
                            and item.get("status") == 1
                            and item.get("permissions") == 1
                        ),
                        None,
                    )
                    if (
                        entry is not None
                        and int(fields.get("expires_at_epoch_s", 0)) > now
                    ):
                        current_version = int(
                            row_value(latest, "acl_version", 0)
                        )
            if pending_job is None and current_version is None:
                self._queue_snapshot_job_cursor(
                    cursor,
                    tenant_id,
                    door_id,
                    "PERSONAL_CREDENTIAL_BOOTSTRAP",
                    now,
                )

            if created:
                cursor.execute(
                    self._sql(
                        "INSERT INTO management_audit "
                        "(tenant_id, actor_ref, action, credential_id, metadata_json, created_at) "
                        "VALUES (?, ?, 'PERSONAL_CREDENTIAL_BOOTSTRAPPED', ?, ?, ?)"
                    ),
                    (
                        tenant_id,
                        actor_ref,
                        credential_id,
                        json.dumps(
                            {"door_id": door_id, "status": "ACTIVE"},
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
            connection.commit()
            return {
                "created": created,
                "acl_version": current_version,
                "snapshot_required": current_version is None,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)

    def revoke_grant(
        self, tenant_id: str, door_id: str, credential_id: str, now: int
    ) -> bool:
        _, count = self._write(
            "UPDATE credential_door_grants SET revoked_at=? "
            "WHERE tenant_id=? AND door_id=? AND credential_id=? AND revoked_at IS NULL",
            (now, tenant_id, door_id, credential_id),
        )
        return count == 1

    def _queue_snapshot_job_cursor(
        self, cursor: Any, tenant_id: str, door_id: str, reason: str, now: int
    ) -> None:
        if self.dialect == "sqlite":
            cursor.execute(
                "INSERT INTO acl_snapshot_jobs "
                "(tenant_id, door_id, reason, requested_at, generated_version, revision) "
                "VALUES (?, ?, ?, ?, NULL, 1) ON CONFLICT(tenant_id, door_id) DO UPDATE SET "
                "reason=excluded.reason, requested_at=excluded.requested_at, "
                "generated_version=NULL, revision=acl_snapshot_jobs.revision + 1",
                (tenant_id, door_id, reason, now),
            )
        else:
            cursor.execute(
                "INSERT INTO acl_snapshot_jobs "
                "(tenant_id, door_id, reason, requested_at, generated_version, revision) "
                "VALUES (%s, %s, %s, %s, NULL, 1) ON DUPLICATE KEY UPDATE "
                "reason=VALUES(reason), requested_at=VALUES(requested_at), "
                "generated_version=NULL, revision=revision + 1",
                (tenant_id, door_id, reason, now),
            )

    def set_credential_status_and_queue(
        self, tenant_id: str, credential_id: str, status: str, reason: str, now: int
    ) -> Optional[list[str]]:
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute("BEGIN IMMEDIATE" if self.dialect == "sqlite" else "START TRANSACTION")
            placeholder = "?" if self.dialect == "sqlite" else "%s"
            lock_suffix = "" if self.dialect == "sqlite" else " FOR UPDATE"
            cursor.execute(
                f"SELECT status FROM credentials WHERE tenant_id={placeholder} "
                f"AND credential_id={placeholder}{lock_suffix}",
                (tenant_id, credential_id),
            )
            credential = cursor.fetchone()
            if credential is None:
                connection.rollback()
                return None
            current_status = str(
                credential["status"] if isinstance(credential, dict) else credential[0]
            )
            cursor.execute(
                "SELECT door_id FROM credential_door_grants "
                f"WHERE tenant_id={placeholder} AND credential_id={placeholder} "
                "AND revoked_at IS NULL ORDER BY door_id",
                (tenant_id, credential_id),
            )
            rows = cursor.fetchall()
            door_ids = [str(row["door_id"] if isinstance(row, dict) else row[0]) for row in rows]
            if current_status != status:
                cursor.execute(
                    f"UPDATE credentials SET status={placeholder}, updated_at={placeholder} "
                    f"WHERE tenant_id={placeholder} AND credential_id={placeholder}",
                    (status, now, tenant_id, credential_id),
                )
                if cursor.rowcount != 1:
                    raise CredentialConflictError(
                        "credential status transition lost its state lock"
                    )
            for queued_door_id in door_ids:
                preserve_existing_job = False
                if current_status == status:
                    cursor.execute(
                        f"SELECT 1 FROM acl_snapshot_jobs WHERE tenant_id={placeholder} "
                        f"AND door_id={placeholder}",
                        (tenant_id, queued_door_id),
                    )
                    preserve_existing_job = cursor.fetchone() is not None
                if not preserve_existing_job:
                    self._queue_snapshot_job_cursor(
                        cursor, tenant_id, queued_door_id, reason, now
                    )
            connection.commit()
            return door_ids
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)

    def revoke_grant_and_queue(
        self, tenant_id: str, door_id: str, credential_id: str, reason: str, now: int
    ) -> bool:
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute("BEGIN IMMEDIATE" if self.dialect == "sqlite" else "START TRANSACTION")
            placeholder = "?" if self.dialect == "sqlite" else "%s"
            cursor.execute(
                f"UPDATE credential_door_grants SET revoked_at={placeholder} "
                f"WHERE tenant_id={placeholder} AND door_id={placeholder} "
                f"AND credential_id={placeholder} AND revoked_at IS NULL",
                (now, tenant_id, door_id, credential_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            self._queue_snapshot_job_cursor(cursor, tenant_id, door_id, reason, now)
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)

    def disable_tenant_and_queue(
        self,
        tenant_id: str,
        reason: str,
        now: int,
        *,
        actor_ref: str,
    ) -> Optional[dict[str, Any]]:
        """Persist one tenant-disable event and replacement jobs in one transaction."""
        connection = self._connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "BEGIN IMMEDIATE" if self.dialect == "sqlite" else "START TRANSACTION"
            )
            placeholder = "?" if self.dialect == "sqlite" else "%s"
            lock_suffix = "" if self.dialect == "sqlite" else " FOR UPDATE"
            cursor.execute(
                f"SELECT status FROM acl_tenants WHERE tenant_id={placeholder}{lock_suffix}",
                (tenant_id,),
            )
            row = cursor.fetchone()
            if row is None:
                connection.rollback()
                return None
            status = str(row["status"] if isinstance(row, dict) else row[0])
            if status not in {"ACTIVE", "DISABLED"}:
                raise ValueError("unknown tenant status")

            if self.dialect != "sqlite":
                # Compatibility is deliberately one-way. Public ACL disable also disables the
                # mapped legacy row, while a legacy re-enable never reactivates public grants.
                cursor.execute(
                    "UPDATE tenants SET is_active=FALSE "
                    "WHERE tenant_uuid=%s AND is_active<>FALSE",
                    (tenant_id,),
                )

            if status == "DISABLED":
                cursor.execute(
                    f"SELECT door_id FROM acl_snapshot_jobs WHERE tenant_id={placeholder} "
                    "ORDER BY door_id",
                    (tenant_id,),
                )
                pending_rows = cursor.fetchall()
                pending_doors = [
                    str(item["door_id"] if isinstance(item, dict) else item[0])
                    for item in pending_rows
                ]
                connection.commit()
                return {"changed": False, "door_ids": pending_doors}

            cursor.execute(
                "SELECT door_id FROM ("
                f"SELECT door_id FROM acl_door_state WHERE tenant_id={placeholder} UNION "
                f"SELECT door_id FROM credential_door_grants WHERE tenant_id={placeholder} UNION "
                f"SELECT door_id FROM acl_snapshot_jobs WHERE tenant_id={placeholder}"
                ") affected ORDER BY door_id",
                (tenant_id, tenant_id, tenant_id),
            )
            affected_rows = cursor.fetchall()
            door_ids = [
                str(item["door_id"] if isinstance(item, dict) else item[0])
                for item in affected_rows
            ]
            cursor.execute(
                f"UPDATE acl_tenants SET status='DISABLED', updated_at={placeholder} "
                f"WHERE tenant_id={placeholder} AND status='ACTIVE'",
                (now, tenant_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("tenant disable transition lost its state lock")
            for door_id in door_ids:
                self._queue_snapshot_job_cursor(cursor, tenant_id, door_id, reason, now)
            cursor.execute(
                self._sql(
                    "INSERT INTO management_audit "
                    "(tenant_id, actor_ref, action, credential_id, metadata_json, created_at) "
                    "VALUES (?, ?, 'TENANT_DISABLED', NULL, ?, ?)"
                ),
                (
                    tenant_id,
                    actor_ref,
                    json.dumps({"status": "DISABLED"}, sort_keys=True),
                    now,
                ),
            )
            connection.commit()
            return {"changed": True, "door_ids": door_ids}
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)

    def snapshot_job(self, tenant_id: str, door_id: str) -> Optional[dict[str, Any]]:
        return self._one(
            "SELECT * FROM acl_snapshot_jobs WHERE tenant_id=? AND door_id=?",
            (tenant_id, door_id),
        )

    def queue_snapshot_job_if_absent(
        self, tenant_id: str, door_id: str, reason: str, now: int
    ) -> None:
        """Coalesce a refresh with any stronger durable replacement job."""

        if self.dialect == "sqlite":
            statement = (
                "INSERT INTO acl_snapshot_jobs "
                "(tenant_id, door_id, reason, requested_at, generated_version, revision) "
                "VALUES (?, ?, ?, ?, NULL, 1) "
                "ON CONFLICT(tenant_id, door_id) DO NOTHING"
            )
        else:
            statement = (
                "INSERT INTO acl_snapshot_jobs "
                "(tenant_id, door_id, reason, requested_at, generated_version, revision) "
                "VALUES (?, ?, ?, ?, NULL, 1) "
                "ON DUPLICATE KEY UPDATE tenant_id=tenant_id"
            )
        self._write(statement, (tenant_id, door_id, reason, now))

    def supersede_snapshot_job(
        self, tenant_id: str, door_id: str, reason: str, now: int
    ) -> None:
        """Force the next publish to allocate a version above Target high-watermark.

        A Target reboot loses ``active_ready`` while retaining its anti-rollback
        high-watermark. Replaying an ACK-lost generated version would therefore
        be rejected forever; a boot refresh must invalidate that queued artifact.
        """

        if self.dialect == "sqlite":
            statement = (
                "INSERT INTO acl_snapshot_jobs "
                "(tenant_id, door_id, reason, requested_at, generated_version, revision) "
                "VALUES (?, ?, ?, ?, NULL, 1) "
                "ON CONFLICT(tenant_id, door_id) DO UPDATE SET "
                "reason=excluded.reason, requested_at=excluded.requested_at, "
                "generated_version=NULL, revision=acl_snapshot_jobs.revision + 1"
            )
        else:
            statement = (
                "INSERT INTO acl_snapshot_jobs "
                "(tenant_id, door_id, reason, requested_at, generated_version, revision) "
                "VALUES (?, ?, ?, ?, NULL, 1) ON DUPLICATE KEY UPDATE "
                "reason=VALUES(reason), requested_at=VALUES(requested_at), "
                "generated_version=NULL, revision=revision + 1"
            )
        self._write(statement, (tenant_id, door_id, reason, now))

    def mark_snapshot_job_generated(
        self, tenant_id: str, door_id: str, version: int, revision: int
    ) -> bool:
        _, count = self._write(
            "UPDATE acl_snapshot_jobs SET generated_version=? "
            "WHERE tenant_id=? AND door_id=? AND revision=?",
            (version, tenant_id, door_id, revision),
        )
        return count == 1

    def delete_snapshot_job(self, tenant_id: str, door_id: str, revision: int) -> bool:
        _, count = self._write(
            "DELETE FROM acl_snapshot_jobs "
            "WHERE tenant_id=? AND door_id=? AND revision=?",
            (tenant_id, door_id, revision),
        )
        return count == 1

    def list_granted_credentials(self, tenant_id: str, door_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT c.*, g.permissions FROM credentials c "
            "JOIN acl_tenants t ON t.tenant_id=c.tenant_id AND t.status='ACTIVE' "
            "JOIN credential_door_grants g ON g.tenant_id=c.tenant_id "
            "AND g.credential_id=c.credential_id "
            "WHERE c.tenant_id=? AND g.door_id=? AND g.revoked_at IS NULL "
            "AND c.status=? ORDER BY c.credential_id ASC",
            (tenant_id, door_id, ACTIVE_STATUS),
        )

    def active_grant_doors(self, tenant_id: str, credential_id: str) -> list[str]:
        rows = self._all(
            "SELECT door_id FROM credential_door_grants "
            "WHERE tenant_id=? AND credential_id=? AND revoked_at IS NULL ORDER BY door_id",
            (tenant_id, credential_id),
        )
        return [str(row["door_id"]) for row in rows]

    def set_credential_status(
        self, tenant_id: str, credential_id: str, status: str, now: int
    ) -> bool:
        _, count = self._write(
            "UPDATE credentials SET status=?, updated_at=? WHERE tenant_id=? AND credential_id=?",
            (status, now, tenant_id, credential_id),
        )
        return count == 1

    def find_by_legacy_ref(self, tenant_id: str, legacy_ref: str) -> Optional[dict[str, Any]]:
        return self._one(
            "SELECT * FROM credentials WHERE tenant_id=? AND legacy_device_ref=?",
            (tenant_id, legacy_ref),
        )

    def append_audit(
        self,
        tenant_id: str,
        actor_ref: str,
        action: str,
        credential_id: Optional[str],
        metadata: dict[str, Any],
        now: int,
    ) -> None:
        self._write(
            "INSERT INTO management_audit "
            "(tenant_id, actor_ref, action, credential_id, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, actor_ref, action, credential_id, json.dumps(metadata, sort_keys=True), now),
        )

    def list_audit(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM management_audit WHERE tenant_id=? ORDER BY id ASC", (tenant_id,)
        )

    def credential_audit(
        self, tenant_id: str, credential_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self._all(
            "SELECT id, action, created_at FROM management_audit "
            "WHERE tenant_id=? AND credential_id=? ORDER BY id DESC LIMIT ?",
            (tenant_id, credential_id, max(1, min(limit, 50))),
        )

    def latest_snapshot(self, tenant_id: str, door_id: str) -> Optional[dict[str, Any]]:
        row = self._one(
            "SELECT * FROM acl_snapshots WHERE tenant_id=? AND door_id=? "
            "ORDER BY acl_version DESC LIMIT 1",
            (tenant_id, door_id),
        )
        if row:
            row["envelope"] = json.loads(row.pop("envelope_json"))
        return row

    def allocate_snapshot_version(self, tenant_id: str, door_id: str) -> int:
        connection = self._connection()
        try:
            cursor = connection.cursor()
            if self.dialect == "sqlite":
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    "INSERT INTO acl_door_state (tenant_id, door_id, last_version) VALUES (?, ?, 0) "
                    "ON CONFLICT(tenant_id, door_id) DO NOTHING",
                    (tenant_id, door_id),
                )
                cursor.execute(
                    "UPDATE acl_door_state SET last_version=last_version+1 "
                    "WHERE tenant_id=? AND door_id=?",
                    (tenant_id, door_id),
                )
                cursor.execute(
                    "SELECT last_version FROM acl_door_state WHERE tenant_id=? AND door_id=?",
                    (tenant_id, door_id),
                )
            else:
                cursor.execute("START TRANSACTION")
                cursor.execute(
                    "INSERT INTO acl_door_state (tenant_id, door_id, last_version) VALUES (%s, %s, 0) "
                    "ON DUPLICATE KEY UPDATE last_version=last_version",
                    (tenant_id, door_id),
                )
                cursor.execute(
                    "UPDATE acl_door_state SET last_version=last_version+1 "
                    "WHERE tenant_id=%s AND door_id=%s",
                    (tenant_id, door_id),
                )
                cursor.execute(
                    "SELECT last_version FROM acl_door_state WHERE tenant_id=%s AND door_id=%s",
                    (tenant_id, door_id),
                )
            row = cursor.fetchone()
            connection.commit()
            return int(row["last_version"] if isinstance(row, dict) else row[0])
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)

    def door_owner(self, door_id: str) -> Optional[str]:
        row = self._one(
            "SELECT tenant_id FROM acl_door_state WHERE door_id=?", (door_id,)
        )
        return str(row["tenant_id"]) if row else None

    def snapshot_by_version(
        self, tenant_id: str, door_id: str, version: int
    ) -> Optional[dict[str, Any]]:
        row = self._one(
            "SELECT * FROM acl_snapshots WHERE tenant_id=? AND door_id=? AND acl_version=?",
            (tenant_id, door_id, version),
        )
        if row:
            row["envelope"] = json.loads(row.pop("envelope_json"))
        return row

    def insert_snapshot(
        self, tenant_id: str, door_id: str, version: int, envelope: dict[str, Any], now: int
    ) -> None:
        self._write(
            "INSERT INTO acl_snapshots "
            "(tenant_id, door_id, acl_version, sha256, envelope_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, door_id, version, envelope["sha256"], json.dumps(envelope, sort_keys=True), now),
        )

    def upsert_ack(
        self,
        tenant_id: str,
        target_id: str,
        door_id: str,
        version: int,
        digest: str,
        status: str,
        now: int,
    ) -> tuple[int, bool]:
        connection = self._connection()
        params = (tenant_id, target_id, door_id, version, digest, status, now)
        try:
            cursor = connection.cursor()
            if self.dialect == "sqlite":
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    "INSERT OR IGNORE INTO target_acl_acks "
                    "(tenant_id, target_id, door_id, acl_version, sha256, status, acked_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    params,
                )
                duplicate = cursor.rowcount == 0
                cursor.execute(
                    "SELECT ack_id, status FROM target_acl_acks WHERE tenant_id=? AND target_id=? "
                    "AND door_id=? AND acl_version=? AND sha256=?",
                    params[:5],
                )
            else:
                cursor.execute(
                    "INSERT INTO target_acl_acks "
                    "(tenant_id, target_id, door_id, acl_version, sha256, status, acked_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE ack_id=LAST_INSERT_ID(ack_id)",
                    params,
                )
                duplicate = cursor.rowcount != 1
                cursor.execute(
                    "SELECT ack_id, status FROM target_acl_acks WHERE tenant_id=%s AND target_id=%s "
                    "AND door_id=%s AND acl_version=%s AND sha256=%s",
                    params[:5],
                )
            row = cursor.fetchone()
            ack_id = int(row["ack_id"] if isinstance(row, dict) else row[0])
            persisted_status = str(row["status"] if isinstance(row, dict) else row[1])
            if not hmac.compare_digest(persisted_status, status):
                raise ValueError("conflicting ACK status for published snapshot")
            connection.commit()
            return ack_id, duplicate
        except Exception:
            connection.rollback()
            raise
        finally:
            self._close(connection)

    def latest_acks(self, tenant_id: str, door_id: str) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT * FROM target_acl_acks WHERE tenant_id=? AND door_id=? ORDER BY ack_id DESC",
            (tenant_id, door_id),
        )
        seen: set[str] = set()
        latest = []
        for row in rows:
            if row["target_id"] not in seen:
                seen.add(row["target_id"])
                latest.append(row)
        return latest

    def put_ota_metadata(self, tenant_id: str, component: str, metadata: dict[str, Any], now: int) -> None:
        payload = json.dumps(metadata, sort_keys=True)
        if self.dialect == "sqlite":
            statement = (
                "INSERT INTO ota_release_metadata VALUES (?, ?, ?, ?) "
                "ON CONFLICT(tenant_id, component) DO UPDATE SET "
                "metadata_json=excluded.metadata_json, updated_at=excluded.updated_at"
            )
        else:
            statement = (
                "INSERT INTO ota_release_metadata (tenant_id, component, metadata_json, updated_at) "
                "VALUES (?, ?, ?, ?) ON DUPLICATE KEY UPDATE "
                "metadata_json=VALUES(metadata_json), updated_at=VALUES(updated_at)"
            )
        self._write(statement, (tenant_id, component, payload, now))

    def get_ota_metadata(self, tenant_id: str, component: str) -> Optional[dict[str, Any]]:
        row = self._one(
            "SELECT metadata_json FROM ota_release_metadata WHERE tenant_id=? AND component=?",
            (tenant_id, component),
        )
        return json.loads(row["metadata_json"]) if row else None

    def insert_ota_health(self, values: dict[str, Any]) -> int:
        row_id, _ = self._write(
            "INSERT INTO ota_health_confirmations "
            "(tenant_id, target_id, component, version, boot_id, artifact_sha256, status, confirmed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                values["tenant_id"],
                values["target_id"],
                values["component"],
                values["version"],
                values["boot_id"],
                values["artifact_sha256"],
                values["status"],
                values["confirmed_at"],
            ),
        )
        return row_id


class RecordingPublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []

    def publish(self, topic: str, envelope: dict[str, Any]) -> bool:
        self.messages.append((topic, envelope))
        return True


class AclManagementService:
    def __init__(
        self,
        store: AclStore,
        signer: DeterministicP256Signer,
        publisher: Any,
        *,
        clock: Callable[[], int] = lambda: int(time.time()),
        lease_seconds: int = 900,
        legacy_lookup_enabled: bool = False,
        legacy_hmac_key: bytes = b"",
        transition_signers: Iterable[DeterministicP256Signer] = (),
    ) -> None:
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        if legacy_lookup_enabled and not legacy_hmac_key:
            raise ValueError("explicit legacy HMAC key is required")
        transition_signers = tuple(transition_signers)
        signing_key_ids = [
            signer.signing_key_id,
            *(item.signing_key_id for item in transition_signers),
        ]
        if len(signing_key_ids) != len(set(signing_key_ids)):
            raise ValueError("ACL signer key IDs must be unique")
        if any(item.signing_key_id <= signer.signing_key_id for item in transition_signers):
            raise ValueError(
                "N-1 signer must remain primary until the rollback trust window closes"
            )
        self.store = store
        self.signer = signer
        self.publisher = publisher
        self.clock = clock
        self.lease_seconds = lease_seconds
        self.legacy_lookup_enabled = legacy_lookup_enabled
        self.legacy_hmac_key = legacy_hmac_key
        self.transition_signers = transition_signers
        self._publish_lock = threading.RLock()

    def _tenant(self, tenant_id: str) -> None:
        _hex_bytes(tenant_id, 16, "tenant_id")
        if not self.store.tenant_exists(tenant_id):
            raise LookupError("tenant not found")

    def _active_tenant(self, tenant_id: str) -> None:
        self._tenant(tenant_id)
        self._reconcile_legacy_disable(tenant_id)
        if self.store.tenant_status(tenant_id) != "ACTIVE":
            raise PermissionError("tenant is disabled")

    def _reconcile_legacy_disable(self, tenant_id: str) -> None:
        """Map legacy inactive to ACL disabled; legacy active never re-enables ACL."""
        if self.store.legacy_tenant_is_active(tenant_id) is False:
            result = self.store.disable_tenant_and_queue(
                tenant_id,
                "LEGACY_TENANT_DISABLED",
                self.clock(),
                actor_ref="system:legacy-tenant-disable",
            )
            if result is None:
                raise LookupError("tenant not found")

    def register_tenant(
        self,
        tenant_id: str,
        display_name: str,
        legacy_tenant_id: int,
        *,
        actor_ref: str,
    ) -> dict[str, str]:
        _hex_bytes(tenant_id, 16, "tenant_id")
        if not display_name.strip():
            raise ValueError("tenant display name is required")
        if legacy_tenant_id < 1:
            raise ValueError("legacy_tenant_id must be positive")
        self.store.register_legacy_tenant(
            legacy_tenant_id, tenant_id, display_name.strip(), self.clock()
        )
        self._audit(tenant_id, actor_ref, "ACL_TENANT_REGISTERED")
        return {"tenant_id": tenant_id, "status": "registered"}


    @staticmethod
    def _authorize_tenant(tenant_id: str, actor_tenant_id: Optional[str]) -> None:
        if actor_tenant_id is not None and not hmac.compare_digest(tenant_id, actor_tenant_id):
            raise PermissionError("tenant boundary violation")

    def _audit(
        self,
        tenant_id: str,
        actor_ref: str,
        action: str,
        credential_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        allowed = {
            "legacy_device_ref",
            "acl_version",
            "door_id",
            "target_ref",
            "status",
            "component",
            "version",
            "artifact_sha256",
        }
        redacted = {key: value for key, value in (metadata or {}).items() if key in allowed}
        self.store.append_audit(
            tenant_id, actor_ref, action, credential_id, redacted, self.clock()
        )

    def issue_enrollment_challenge(
        self,
        tenant_id: str,
        *,
        actor_ref: str,
        actor_tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        self._active_tenant(tenant_id)
        self._authorize_tenant(tenant_id, actor_tenant_id)
        now = self.clock()
        enrollment_id = secrets.token_bytes(16).hex()
        nonce = secrets.token_bytes(32).hex()
        self.store.insert_challenge(
            enrollment_id,
            tenant_id,
            actor_ref,
            hashlib.sha256(bytes.fromhex(nonce)).hexdigest(),
            now + 300,
            now,
        )
        self._audit(tenant_id, actor_ref, "ENROLLMENT_CHALLENGE_ISSUED")
        return {"enrollment_id": enrollment_id, "nonce": nonce, "expires_at": now + 300}

    def submit_enrollment(
        self,
        tenant_id: str,
        enrollment_id: str,
        nonce_hex: str,
        public_key_hex: str,
        signature_hex: str,
        *,
        actor_ref: str,
        actor_tenant_id: Optional[str] = None,
        legacy_device_id: Optional[str] = None,
        expires_at: Optional[int] = None,
        min_protocol: int = 1,
        max_protocol: int = 1,
    ) -> dict[str, Any]:
        self._active_tenant(tenant_id)
        self._authorize_tenant(tenant_id, actor_tenant_id)
        now = self.clock()
        challenge = self.store.get_challenge(tenant_id, enrollment_id)
        if challenge is None:
            raise LookupError("enrollment challenge not found")
        if not hmac.compare_digest(str(challenge["actor_ref"]), actor_ref):
            raise PermissionError("enrollment actor boundary violation")
        if challenge["used_at"] is not None:
            raise ValueError("enrollment challenge already used")
        if int(challenge["expires_at"]) <= now:
            raise ValueError("enrollment challenge expired")
        nonce = _hex_bytes(nonce_hex, 32, "nonce")
        if not hmac.compare_digest(hashlib.sha256(nonce).hexdigest(), challenge["nonce_hash"]):
            raise ValueError("enrollment nonce mismatch")
        payload = build_enrollment_input(
            tenant_id, enrollment_id, nonce_hex, public_key_hex
        )
        public_key = _hex_bytes(public_key_hex, 65, "public_key")
        try:
            signature = bytes.fromhex(signature_hex)
        except ValueError as exc:
            raise ValueError("invalid enrollment signature") from exc
        if not verify_raw64(public_key, payload, signature):
            raise ValueError("invalid enrollment signature")
        if not 1 <= min_protocol <= max_protocol:
            raise ValueError("invalid credential protocol range")
        credential_id = secrets.token_bytes(16).hex()
        legacy_ref = self._legacy_ref(legacy_device_id) if legacy_device_id else None
        credential = {
                "credential_id": credential_id,
                "tenant_id": tenant_id,
                "public_key_sec1": public_key_hex,
                "status": "PENDING",
                "expires_at": expires_at,
                "legacy_device_ref": legacy_ref,
                "min_protocol": min_protocol,
                "max_protocol": max_protocol,
                "created_at": now,
                "updated_at": now,
            }
        if not self.store.consume_challenge_and_insert_credential(
            tenant_id, enrollment_id, actor_ref, now, credential
        ):
            raise ValueError("enrollment challenge already used")
        metadata = {"legacy_device_ref": legacy_ref} if legacy_ref else {}
        self._audit(
            tenant_id, actor_ref, "CREDENTIAL_ENROLLED", credential_id, metadata
        )
        return {"credential_id": credential_id, "status": "PENDING"}

    def bootstrap_personal_credential(
        self,
        tenant_id: str,
        door_id: str,
        legacy_device_id: str,
        credential_id: str,
        public_key_hex: str,
        *,
        actor_ref: str,
        min_protocol: int = 1,
        max_protocol: int = 1,
    ) -> dict[str, Any]:
        """Activate the app-selected public credential for one personal door.

        This narrow migration seam relies on both the existing API key at the
        HTTP boundary and an approved legacy-device row locked by the store.
        It accepts public material only; no private-key field exists.
        """
        _hex_bytes(tenant_id, 16, "tenant_id")
        _hex_bytes(door_id, 16, "door_id")
        _hex_bytes(credential_id, 16, "credential_id")
        public_key = _hex_bytes(public_key_hex, 65, "public_key_sec1")
        _parse_public_key(public_key)
        if not 1 <= min_protocol <= max_protocol <= 0xFFFF:
            raise ValueError("invalid credential protocol range")
        normalized_device_id = legacy_device_id.strip().upper()
        if (
            not 8 <= len(normalized_device_id) <= 128
            or not normalized_device_id.startswith(("DEV-", "GK-"))
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
                for character in normalized_device_id
            )
        ):
            raise ValueError("invalid legacy device ID")
        legacy_ref = self._legacy_ref(normalized_device_id)
        transition = self.store.bootstrap_personal_credential_and_queue(
            tenant_id,
            door_id,
            normalized_device_id,
            {
                "credential_id": credential_id,
                "public_key_sec1": public_key_hex,
                "legacy_device_ref": legacy_ref,
                "min_protocol": min_protocol,
                "max_protocol": max_protocol,
            },
            actor_ref=actor_ref,
            now=self.clock(),
        )
        acl_version = transition["acl_version"]
        if transition["snapshot_required"]:
            envelope = self._publish_replacement_snapshots(
                tenant_id,
                [door_id],
                actor_ref=actor_ref,
            )[0]
            acl_version = int(envelope["fields"]["acl_version"])
        if not isinstance(acl_version, int) or acl_version < 1:
            raise RuntimeError("signed ACL snapshot is unavailable")
        return {
            "accepted": True,
            "credential_id": credential_id,
            "acl_version": acl_version,
        }

    def personal_mobile_status(
        self,
        tenant_id: str,
        door_id: str,
        legacy_device_id: str,
        credential_id: Optional[str],
        public_key_hex: Optional[str],
    ) -> dict[str, Any]:
        """Return one truthful mobile status without treating legacy ID as access proof."""

        _hex_bytes(tenant_id, 16, "tenant_id")
        _hex_bytes(door_id, 16, "door_id")
        normalized_device_id = legacy_device_id.strip().upper()

        def legacy_registration_status() -> dict[str, Any]:
            legacy = self.store.legacy_personal_state(tenant_id, normalized_device_id)
            if legacy is None:
                return {
                    "enrollment_state": "unregistered",
                    "access_ready": False,
                    "next_action": "request_registration",
                    "door_count": 0,
                    "target_synced": False,
                }
            return {
                "enrollment_state": (
                    "ready_to_enroll" if legacy["is_active"] else "pending"
                ),
                "access_ready": False,
                "next_action": (
                    "enroll_credential" if legacy["is_active"] else "wait_for_approval"
                ),
                "tenant_label": legacy["tenant_label"],
                "door_count": 0,
                "target_synced": False,
            }

        if credential_id is None or public_key_hex is None:
            return legacy_registration_status()

        _hex_bytes(credential_id, 16, "credential_id")
        public_key = _hex_bytes(public_key_hex, 65, "public_key_sec1")
        _parse_public_key(public_key)
        credential = self.store.get_credential(tenant_id, credential_id)
        if credential is None:
            # Android prepares its non-exportable key before the first status
            # request. Until that key is enrolled, project the supervised
            # legacy registration state so the UI can expose onboarding.
            return legacy_registration_status()
        if not hmac.compare_digest(
            str(credential["public_key_sec1"]), public_key_hex
        ):
            raise PermissionError("credential identity mismatch")

        # Migration 009 backfills the account-to-public-credential join when
        # an already enrolled phone next proves its key identity. This keeps
        # account deletion fail-closed without storing the raw app identifier.
        self.store.bind_personal_credential_to_legacy_row(
            tenant_id,
            normalized_device_id,
            credential_id,
            self._legacy_ref(normalized_device_id),
        )
        account_profile = self.store.personal_account_profile(
            tenant_id, credential_id
        )
        account_name = account_profile["name"] if account_profile else None
        unit_number = account_profile["unit_number"] if account_profile else None
        mobile_role = account_profile["mobile_role"] if account_profile else "USER"
        account_label = (
            f"{account_name} {unit_number}" if account_name and unit_number else None
        )

        now = self.clock()
        tenant_status = self.store.tenant_status(tenant_id)
        credential_status = str(credential["status"])
        expires_at = credential.get("expires_at")
        expired = expires_at is not None and int(expires_at) <= now
        doors = self.store.active_grant_doors(tenant_id, credential_id)
        granted = door_id in doors
        snapshot = self.store.latest_snapshot(tenant_id, door_id) if granted else None
        acl_version = int(snapshot["acl_version"]) if snapshot else None
        snapshot_fields = snapshot["envelope"]["fields"] if snapshot else {}
        entry_active = any(
            item.get("credential_id") == credential_id
            and item.get("status") == 1
            and item.get("permissions") == 1
            for item in snapshot_fields.get("entries", [])
        ) and int(snapshot_fields.get("expires_at_epoch_s", 0)) > now
        latest_digest = str(snapshot.get("sha256", "")) if snapshot else ""
        target_synced = any(
            ack.get("status") == "APPLIED"
            and int(ack.get("acl_version", 0)) == (acl_version or 0)
            and hmac.compare_digest(str(ack.get("sha256", "")), latest_digest)
            for ack in (self.store.latest_acks(tenant_id, door_id) if snapshot else [])
        )

        if tenant_status != "ACTIVE" or credential_status in {"DISABLED", "REVOKED"}:
            enrollment_state = "revoked"
            next_action = "contact_administrator"
        elif expired:
            enrollment_state = "expired"
            next_action = "renew_credential"
        elif credential_status == "PENDING":
            enrollment_state = "pending"
            next_action = "wait_for_approval"
        else:
            enrollment_state = "approved"
            next_action = "none" if entry_active and target_synced else "wait_for_acl"

        return {
            "enrollment_state": enrollment_state,
            "access_ready": (
                enrollment_state == "approved" and entry_active and target_synced
            ),
            "next_action": next_action,
            # N-1 clients still render tenant_label as their user card.  Keep
            # that field per-account and never fall back to the household ACL
            # tenant display name, which may contain another resident's PII.
            "tenant_label": account_label,
            "account_name": account_name,
            "unit_number": unit_number,
            "mobile_role": mobile_role,
            "door_count": len(doors),
            "selected_door": "default" if granted else None,
            "credential_expires_at": expires_at,
            "acl_version": acl_version,
            "target_synced": target_synced,
        }

    def personal_mobile_activity(
        self,
        tenant_id: str,
        credential_id: str,
        public_key_hex: str,
    ) -> dict[str, Any]:
        """Return a bounded allow-listed credential lifecycle, never admin audit data."""

        _hex_bytes(credential_id, 16, "credential_id")
        _parse_public_key(_hex_bytes(public_key_hex, 65, "public_key_sec1"))
        credential = self.store.get_credential(tenant_id, credential_id)
        if credential is None or not hmac.compare_digest(
            str(credential["public_key_sec1"]), public_key_hex
        ):
            raise PermissionError("credential identity mismatch")
        allowed = {
            "PERSONAL_CREDENTIAL_BOOTSTRAPPED": "credential_registered",
            "CREDENTIAL_APPROVED": "credential_approved",
            "CREDENTIAL_DISABLED": "credential_disabled",
            "CREDENTIAL_REVOKED": "credential_revoked",
            "CREDENTIAL_DOOR_GRANTED": "door_granted",
            "CREDENTIAL_DOOR_REMOVED": "door_removed",
        }
        events = []
        for row in self.store.credential_audit(tenant_id, credential_id):
            event_type = allowed.get(str(row["action"]))
            if event_type is None:
                continue
            events.append(
                {
                    "event_ref": hashlib.sha256(
                        f"mobile-activity:{row['id']}".encode("utf-8")
                    ).hexdigest()[:24],
                    "type": event_type,
                    "created_at": int(row["created_at"]),
                }
            )
        return {"events": events[:20]}

    def _set_status(
        self, tenant_id: str, credential_id: str, status: str, actor_ref: str, action: str
    ) -> dict[str, Any]:
        self._tenant(tenant_id)
        if status not in KNOWN_CREDENTIAL_STATUSES:
            raise ValueError("unknown credential status")
        if not self.store.set_credential_status(
            tenant_id, credential_id, status, self.clock()
        ):
            raise LookupError("credential not found in tenant")
        self._audit(tenant_id, actor_ref, action, credential_id)
        return {"credential_id": credential_id, "status": status}

    def approve_credential(
        self, tenant_id: str, credential_id: str, *, actor_ref: str
    ) -> dict[str, Any]:
        self._active_tenant(tenant_id)
        row = self.store.get_credential(tenant_id, credential_id)
        if row is None:
            raise LookupError("credential not found in tenant")
        if row["status"] != "PENDING":
            raise ValueError("only pending credentials can be approved")
        return self._set_status(
            tenant_id, credential_id, "ACTIVE", actor_ref, "CREDENTIAL_APPROVED"
        )

    def grant_credential_to_door(
        self,
        tenant_id: str,
        door_id: str,
        credential_id: str,
        *,
        actor_ref: str,
        permissions: int = 1,
    ) -> dict[str, Any]:
        self._active_tenant(tenant_id)
        _hex_bytes(door_id, 16, "door_id")
        if permissions != 1:
            raise ValueError("only OPEN permission is defined in ACL v1")
        if self.store.get_credential(tenant_id, credential_id) is None:
            raise LookupError("credential not found in tenant")
        self.store.grant_credential(
            tenant_id, door_id, credential_id, permissions, self.clock()
        )
        self._audit(
            tenant_id,
            actor_ref,
            "CREDENTIAL_DOOR_GRANTED",
            credential_id,
            {"door_id": door_id},
        )
        return {"credential_id": credential_id, "door_id": door_id, "status": "GRANTED"}

    def remove_credential_from_door(
        self, tenant_id: str, door_id: str, credential_id: str, *, actor_ref: str
    ) -> dict[str, Any]:
        self._tenant(tenant_id)
        _hex_bytes(door_id, 16, "door_id")
        if not self.store.revoke_grant_and_queue(
            tenant_id,
            door_id,
            credential_id,
            "CREDENTIAL_DOOR_REMOVED",
            self.clock(),
        ):
            raise LookupError("active door grant not found")
        self._audit(
            tenant_id,
            actor_ref,
            "CREDENTIAL_DOOR_REMOVED",
            credential_id,
            {"door_id": door_id},
        )
        snapshot = self._publish_replacement_snapshots(
            tenant_id, [door_id], actor_ref=actor_ref
        )[0]
        return {
            "credential_id": credential_id,
            "door_id": door_id,
            "status": "REMOVED",
            "acl_version": snapshot["fields"]["acl_version"],
        }

    def _publish_replacement_snapshots(
        self,
        tenant_id: str,
        door_ids: list[str],
        *,
        actor_ref: str,
        raise_mqtt_failure: bool = True,
    ) -> list[dict[str, Any]]:
        with self._publish_lock:
            return self._publish_replacement_snapshots_locked(
                tenant_id,
                door_ids,
                actor_ref=actor_ref,
                raise_mqtt_failure=raise_mqtt_failure,
            )

    def _publish_replacement_snapshots_locked(
        self,
        tenant_id: str,
        door_ids: list[str],
        *,
        actor_ref: str,
        raise_mqtt_failure: bool = True,
    ) -> list[dict[str, Any]]:
        envelopes: list[dict[str, Any]] = []
        mqtt_failures = 0
        for door_id in door_ids:
            job = self.store.snapshot_job(tenant_id, door_id)
            job_revision = int(job["revision"]) if job else 0
            if job and job["generated_version"] is not None:
                generated = self.store.snapshot_by_version(
                    tenant_id, door_id, int(job["generated_version"])
                )
                if generated is None:
                    raise RuntimeError("queued ACL snapshot artifact is missing")
                envelope = generated["envelope"]
                topic = f"gatekeeper/acl/v1/{tenant_id}/{door_id}"
                if self.publisher.publish(topic, envelope):
                    self.store.delete_snapshot_job(tenant_id, door_id, job_revision)
                else:
                    mqtt_failures += 1
                envelopes.append(envelope)
                continue
            previous = self.store.latest_snapshot(tenant_id, door_id)
            fields = previous["envelope"]["fields"] if previous else {}
            try:
                envelope = self.publish_snapshot(
                    tenant_id,
                    door_id,
                    actor_ref=actor_ref,
                    min_protocol=int(fields.get("min_protocol", 1)),
                    max_protocol=int(fields.get("max_protocol", 1)),
                )
            except MqttPublishError:
                # publish_snapshot persists before push; continue so periodic pull is updated
                # for every affected door even when one MQTT delivery fails.
                mqtt_failures += 1
                row = self.store.latest_snapshot(tenant_id, door_id)
                if row is None:
                    raise
                envelope = row["envelope"]
                self.store.mark_snapshot_job_generated(
                    tenant_id, door_id, int(row["acl_version"]), job_revision
                )
            except Exception as exc:
                raise RuntimeError(
                    "ACL replacement generation failed; durable job remains queued"
                ) from exc
            else:
                self.store.delete_snapshot_job(tenant_id, door_id, job_revision)
            envelopes.append(envelope)
        if mqtt_failures and raise_mqtt_failure:
            raise RuntimeError(
                f"ACL MQTT push failed for {mqtt_failures} replacement snapshot(s); pull is current"
            )
        return envelopes

    def refresh_snapshot(
        self, tenant_id: str, door_id: str, *, actor_ref: str, reason: str
    ) -> dict[str, Any]:
        """Create a fresh version for reboot recovery or pre-expiry renewal."""

        if reason not in {"TARGET_BOOT_REFRESH", "ACL_LEASE_REFRESH"}:
            raise ValueError("unknown ACL refresh reason")
        with self._publish_lock:
            self._active_tenant(tenant_id)
            _hex_bytes(door_id, 16, "door_id")
            if reason == "TARGET_BOOT_REFRESH":
                self.store.supersede_snapshot_job(
                    tenant_id, door_id, reason, self.clock()
                )
            else:
                self.store.queue_snapshot_job_if_absent(
                    tenant_id, door_id, reason, self.clock()
                )
            return self._publish_replacement_snapshots_locked(
                tenant_id, [door_id], actor_ref=actor_ref
            )[0]

    def disable_tenant(
        self,
        tenant_id: str,
        *,
        actor_ref: str,
        actor_tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        self._tenant(tenant_id)
        self._authorize_tenant(tenant_id, actor_tenant_id)
        transition = self.store.disable_tenant_and_queue(
            tenant_id,
            "TENANT_DISABLED",
            self.clock(),
            actor_ref=actor_ref,
        )
        if transition is None:
            raise LookupError("tenant not found")
        result = {
            "tenant_id": tenant_id,
            "status": "DISABLED",
            "already_disabled": not transition["changed"],
        }
        result["replacement_snapshots"] = self._publish_replacement_snapshots(
            tenant_id, transition["door_ids"], actor_ref=actor_ref
        )
        return result

    def disable_credential(
        self, tenant_id: str, credential_id: str, *, actor_ref: str
    ) -> dict[str, Any]:
        self._tenant(tenant_id)
        doors = self.store.set_credential_status_and_queue(
            tenant_id,
            credential_id,
            "DISABLED",
            "CREDENTIAL_DISABLED",
            self.clock(),
        )
        if doors is None:
            raise LookupError("credential not found in tenant")
        self._audit(tenant_id, actor_ref, "CREDENTIAL_DISABLED", credential_id)
        result = {"credential_id": credential_id, "status": "DISABLED"}
        result["replacement_snapshots"] = self._publish_replacement_snapshots(
            tenant_id, doors, actor_ref=actor_ref
        )
        return result

    def revoke_credential(
        self, tenant_id: str, credential_id: str, *, actor_ref: str
    ) -> dict[str, Any]:
        self._tenant(tenant_id)
        doors = self.store.set_credential_status_and_queue(
            tenant_id,
            credential_id,
            "REVOKED",
            "CREDENTIAL_REVOKED",
            self.clock(),
        )
        if doors is None:
            raise LookupError("credential not found in tenant")
        self._audit(tenant_id, actor_ref, "CREDENTIAL_REVOKED", credential_id)
        result = {"credential_id": credential_id, "status": "REVOKED"}
        result["replacement_snapshots"] = self._publish_replacement_snapshots(
            tenant_id, doors, actor_ref=actor_ref
        )
        return result

    def sign_explicit_snapshot(self, fields: dict[str, Any]) -> dict[str, Any]:
        canonical = encode_acl(fields)
        signatures = [
            {
                "signing_key_id": signer.signing_key_id,
                "signing_public_key_sec1": signer.public_key_sec1.hex(),
                "signature_raw64": signer.sign(canonical).hex(),
            }
            for signer in (self.signer, *self.transition_signers)
        ]
        return {
            "schema": "sgk-acl-envelope-v1",
            "fields": fields,
            "canonical_hex": canonical.hex(),
            "sha256": hashlib.sha256(canonical).hexdigest(),
            "signing_public_key_sec1": self.signer.public_key_sec1.hex(),
            "signature_raw64": signatures[0]["signature_raw64"],
            "signatures": signatures,
        }

    def publish_snapshot(
        self,
        tenant_id: str,
        door_id: str,
        *,
        actor_ref: str,
        min_protocol: int = 1,
        max_protocol: int = 1,
    ) -> dict[str, Any]:
        with self._publish_lock:
            return self._publish_snapshot_locked(
                tenant_id,
                door_id,
                actor_ref=actor_ref,
                min_protocol=min_protocol,
                max_protocol=max_protocol,
            )

    def _publish_snapshot_locked(
        self,
        tenant_id: str,
        door_id: str,
        *,
        actor_ref: str,
        min_protocol: int = 1,
        max_protocol: int = 1,
    ) -> dict[str, Any]:
        self._tenant(tenant_id)
        self._reconcile_legacy_disable(tenant_id)
        _hex_bytes(door_id, 16, "door_id")
        if not 1 <= min_protocol <= max_protocol:
            raise ValueError("invalid snapshot protocol range")
        owner = self.store.door_owner(door_id)
        if owner is not None and not hmac.compare_digest(owner, tenant_id):
            raise PermissionError("door is already bound to another tenant")
        now = self.clock()
        version = self.store.allocate_snapshot_version(tenant_id, door_id)
        entries = []
        for row in self.store.list_granted_credentials(tenant_id, door_id):
            if row["expires_at"] is not None and int(row["expires_at"]) <= now:
                continue
            entry_min = max(min_protocol, int(row["min_protocol"]))
            entry_max = min(max_protocol, int(row["max_protocol"]))
            if entry_min > entry_max:
                continue
            entries.append(
                {
                    "credential_id": row["credential_id"],
                    "public_key_sec1": row["public_key_sec1"],
                    "status": 1,
                    "permissions": int(row["permissions"]),
                    "not_before_epoch_s": int(row["created_at"]),
                    "not_after_epoch_s": int(row["expires_at"] or now + 86400),
                    "min_protocol": entry_min,
                    "max_protocol": entry_max,
                }
            )
        entries.sort(key=lambda item: bytes.fromhex(item["credential_id"]))
        fields = {
            "schema_version": 1,
            "door_id": door_id,
            "acl_version": version,
            "issued_at_epoch_s": now,
            "not_before_epoch_s": now,
            "expires_at_epoch_s": now + self.lease_seconds,
            "lease_duration_s": self.lease_seconds,
            "min_protocol": min_protocol,
            "max_protocol": max_protocol,
            "signing_key_id": self.signer.signing_key_id,
            "entries": entries,
        }
        envelope = self.sign_explicit_snapshot(fields)
        self.store.insert_snapshot(tenant_id, door_id, version, envelope, now)
        self._audit(
            tenant_id,
            actor_ref,
            "ACL_SNAPSHOT_PUBLISHED",
            metadata={"acl_version": version, "door_id": door_id},
        )
        topic = f"gatekeeper/acl/v1/{tenant_id}/{door_id}"
        if not self.publisher.publish(topic, envelope):
            raise MqttPublishError(
                "ACL MQTT push failed; periodic pull artifact remains available"
            )
        return envelope

    def pull_snapshot(self, tenant_id: str, door_id: str) -> dict[str, Any]:
        self._tenant(tenant_id)
        self._reconcile_legacy_disable(tenant_id)
        if self.store.snapshot_job(tenant_id, door_id) is not None:
            self._publish_replacement_snapshots(
                tenant_id,
                [door_id],
                actor_ref="system:periodic-pull-recovery",
                raise_mqtt_failure=False,
            )
        row = self.store.latest_snapshot(tenant_id, door_id)
        if row is None:
            raise LookupError("ACL snapshot not found")
        return row["envelope"]

    def ack_snapshot(
        self,
        tenant_id: str,
        target_id: str,
        door_id: str,
        acl_version: int,
        digest: str,
        status: str,
    ) -> dict[str, Any]:
        self._tenant(tenant_id)
        if status not in {"APPLIED", "REJECTED"}:
            raise ValueError("unknown ACL ACK status")
        snapshot = self.store.snapshot_by_version(tenant_id, door_id, acl_version)
        if snapshot is None or not hmac.compare_digest(snapshot["sha256"], digest):
            raise ValueError("ACK does not identify a published snapshot")
        ack_id, duplicate = self.store.upsert_ack(
            tenant_id,
            target_id,
            door_id,
            acl_version,
            digest,
            status,
            self.clock(),
        )
        return {"ack_id": ack_id, "duplicate": duplicate, "status": status}

    def fleet_status(self, tenant_id: str, door_id: str) -> dict[str, Any]:
        self._tenant(tenant_id)
        snapshot = self.store.latest_snapshot(tenant_id, door_id)
        latest_version = int(snapshot["acl_version"]) if snapshot else 0
        latest_digest = snapshot["sha256"] if snapshot else ""
        targets = self.store.latest_acks(tenant_id, door_id)
        synced = sum(
            row["status"] == "APPLIED"
            and int(row["acl_version"]) == latest_version
            and hmac.compare_digest(row["sha256"], latest_digest)
            for row in targets
        )
        return {
            "latest_acl_version": latest_version,
            "target_count": len(targets),
            "synced_targets": synced,
            "targets": targets,
        }

    def _legacy_ref(self, device_id: Optional[str]) -> str:
        if not device_id:
            raise ValueError("legacy device ID required")
        return hmac.new(
            self.legacy_hmac_key, device_id.strip().encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def lookup_legacy_device(self, tenant_id: str, device_id: str) -> Optional[str]:
        if not self.legacy_lookup_enabled:
            return None
        row = self.store.find_by_legacy_ref(tenant_id, self._legacy_ref(device_id))
        return row["credential_id"] if row else None

    def put_ota_metadata(
        self, tenant_id: str, metadata: dict[str, Any], *, actor_ref: str
    ) -> None:
        self._tenant(tenant_id)
        required = {
            "component",
            "version",
            "primary_url",
            "fallback_url",
            "sha256",
            "signature",
            "protocol_min",
            "protocol_max",
        }
        if set(metadata) != required:
            raise ValueError("OTA metadata fields do not match v1 management contract")
        if metadata["primary_url"] == metadata["fallback_url"]:
            raise ValueError("OTA fallback must be independent from primary")
        _hex_bytes(metadata["sha256"], 32, "sha256")
        _hex_bytes(metadata["signature"], 64, "signature")
        if not 1 <= metadata["protocol_min"] <= metadata["protocol_max"]:
            raise ValueError("invalid OTA protocol range")
        self.store.put_ota_metadata(
            tenant_id, metadata["component"], metadata, self.clock()
        )
        self._audit(
            tenant_id,
            actor_ref,
            "OTA_METADATA_PUBLISHED",
            metadata={
                "component": metadata["component"],
                "version": metadata["version"],
                "artifact_sha256": metadata["sha256"],
            },
        )

    def get_ota_metadata(self, tenant_id: str, component: str) -> dict[str, Any]:
        self._tenant(tenant_id)
        result = self.store.get_ota_metadata(tenant_id, component)
        if result is None:
            raise LookupError("OTA metadata not found")
        return result

    def confirm_ota_health(
        self,
        tenant_id: str,
        target_id: str,
        *,
        component: str,
        version: str,
        boot_id: str,
        artifact_sha256: str,
        healthy: bool,
    ) -> dict[str, Any]:
        metadata = self.get_ota_metadata(tenant_id, component)
        if metadata["version"] != version or not hmac.compare_digest(
            metadata["sha256"], artifact_sha256
        ):
            raise ValueError("OTA health does not match published artifact")
        status = "HEALTH_CONFIRMED" if healthy else "HEALTH_FAILED"
        confirmation_id = self.store.insert_ota_health(
            {
                "tenant_id": tenant_id,
                "target_id": target_id,
                "component": component,
                "version": version,
                "boot_id": boot_id,
                "artifact_sha256": artifact_sha256,
                "status": status,
                "confirmed_at": self.clock(),
            }
        )
        return {"confirmation_id": confirmation_id, "status": status}
