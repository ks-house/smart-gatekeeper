"""Signed, freshness-bound Target command envelope helpers."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .acl_management import DeterministicP256Signer


ALLOWED_ACTIONS = {
    "arm",
    "manual_remote",
    "set_tx_power",
    "set_distance_threshold",
    "set_duration",
    "set_relay_cooldown",
    "ota_check",
    "reboot",
}


def canonical_command(envelope: dict[str, Any]) -> bytes:
    action = str(envelope["action"])
    if action not in ALLOWED_ACTIONS:
        raise ValueError("unsupported command action")
    fields = (
        ("action", action),
        ("boot_id", str(envelope["boot_id"])),
        ("door_id", str(envelope["door_id"])),
        ("expires_at", int(envelope["expires_at"])),
        ("issued_at", int(envelope["issued_at"])),
        ("key_id", int(envelope["key_id"])),
        ("nonce", str(envelope["nonce"])),
        ("schema_version", int(envelope["schema_version"])),
        ("session_id", str(envelope["session_id"])),
        ("target_id", str(envelope["target_id"])),
        ("tenant_id", str(envelope["tenant_id"])),
        ("value", int(envelope["value"])),
    )
    for name, value in fields:
        if isinstance(value, str) and (
            not value
            or len(value) > 48
            or any(not (character.isalnum() or character in "-_.:") for character in value)
        ):
            raise ValueError(f"invalid {name}")
    return (
        "sgk-command-v1\n"
        + "".join(f"{name}={value}\n" for name, value in fields)
    ).encode("ascii")


def build_signed_command(
    *,
    signer: DeterministicP256Signer,
    target_id: str,
    tenant_id: str,
    door_id: str,
    boot_id: str,
    action: str,
    value: int = 0,
    now: int | None = None,
    ttl_seconds: int = 60,
    session_id: str | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    if not 1 <= ttl_seconds <= 120:
        raise ValueError("command TTL must be 1..120 seconds")
    issued_at = int(time.time() if now is None else now)
    envelope: dict[str, Any] = {
        "schema_version": 1,
        "target_id": target_id,
        "tenant_id": tenant_id,
        "door_id": door_id,
        "boot_id": boot_id,
        "action": action,
        "session_id": session_id or uuid.uuid4().hex,
        "nonce": nonce or uuid.uuid4().hex,
        "issued_at": issued_at,
        "expires_at": issued_at + ttl_seconds,
        "key_id": signer.signing_key_id,
        "value": int(value),
    }
    envelope["signature"] = signer.sign(canonical_command(envelope)).hex()
    return envelope
