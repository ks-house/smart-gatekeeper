"""Session-scoped, privacy-safe access actor reference helpers.

The Target emits only a truncated, domain-separated HMAC after a credential
proof succeeds.  Raw credential IDs remain inside the Target verifier and the
credential database; they never enter MQTT or the immutable event history.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Mapping


_DOMAIN = b"SGK-CREDENTIAL-REF-V1\x00"
_EVENT_MAC_DOMAIN = b"SGK-ACCESS-EVENT-MAC-V1\x00"
_STATUS_MAC_DOMAIN = b"SGK-ACCESS-STATUS-MAC-V1\x00"
_KEY_ID = re.compile(r"^[a-z0-9]{1,4}$")
_REF = re.compile(r"^c_([a-z0-9]{1,4})_([0-9a-f]{24})$")
_MAC = re.compile(r"^[0-9a-f]{32}$")


def parse_access_event_ref_keyring(raw: str) -> dict[str, bytes]:
    """Parse a strict JSON key-id to 32-byte lowercase-hex mapping."""

    if not raw.strip():
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict) or not value:
        raise ValueError("access event ref keyring must be a non-empty object")
    parsed: dict[str, bytes] = {}
    for key_id, key_hex in value.items():
        if not isinstance(key_id, str) or _KEY_ID.fullmatch(key_id) is None:
            raise ValueError("access event ref key id is invalid")
        if (
            not isinstance(key_hex, str)
            or len(key_hex) != 64
            or key_hex != key_hex.lower()
            or any(character not in "0123456789abcdef" for character in key_hex)
        ):
            raise ValueError("access event ref key must be 32-byte lowercase hex")
        key = bytes.fromhex(key_hex)
        if not any(key):
            raise ValueError("access event ref key must not be all zero")
        parsed[key_id] = key
    return parsed


def access_credential_ref(
    key_id: str,
    key: bytes,
    door_id: str,
    session_id: str,
    credential_id: str,
) -> str:
    """Build the cross-language Target/Backend credential pseudonym."""

    if _KEY_ID.fullmatch(key_id) is None or len(key) != 32 or not any(key):
        raise ValueError("access event ref key is invalid")
    try:
        door = bytes.fromhex(door_id)
        credential = bytes.fromhex(credential_id)
        session = uuid.UUID(session_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("access event ref input is invalid") from exc
    if (
        len(door) != 16
        or len(credential) != 16
        or len(door_id) != 32
        or len(credential_id) != 32
        or door_id != door_id.lower()
        or credential_id != credential_id.lower()
        or session.version != 4
        or str(session) != session_id
    ):
        raise ValueError("access event ref input is invalid")
    digest = hmac.new(
        key,
        _DOMAIN + door + session.bytes + credential,
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"c_{key_id}_{digest}"


def access_credential_ref_key_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _REF.fullmatch(value)
    return match.group(1) if match is not None else None


def access_credential_ref_is_valid(value: object) -> bool:
    return access_credential_ref_key_id(value) is not None


def matches_access_credential_ref(
    value: object,
    *,
    keyring: Mapping[str, bytes],
    door_id: str,
    session_id: str,
    credential_id: str,
) -> bool:
    key_id = access_credential_ref_key_id(value)
    key = keyring.get(key_id) if key_id is not None else None
    if key_id is None or key is None:
        return False
    try:
        expected = access_credential_ref(
            key_id, key, door_id, session_id, credential_id
        )
    except ValueError:
        return False
    return hmac.compare_digest(str(value), expected)


def _lp_ascii(value: object, field: str, *, allow_empty: bool = False) -> bytes:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ValueError(f"{field} is invalid")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if len(encoded) > 0xFFFF:
        raise ValueError(f"{field} is invalid")
    return len(encoded).to_bytes(2, "big") + encoded


def _uuid4_bytes(value: object, field: str) -> bytes:
    if not isinstance(value, str) or value != value.lower():
        raise ValueError(f"{field} is invalid")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{field} is invalid")
    return parsed.bytes


def _hex16_bytes(value: object, field: str) -> bytes:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} is invalid")
    return bytes.fromhex(value)


def _unsigned(value: object, bits: int, field: str, *, minimum: int = 0) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= (1 << bits) - 1
    ):
        raise ValueError(f"{field} is invalid")
    return value


def _optional_unsigned(value: object, bits: int, field: str) -> bytes:
    if value is None:
        return b"\x00"
    parsed = _unsigned(value, bits, field)
    return b"\x01" + parsed.to_bytes(bits // 8, "big")


def _optional_uuid4(value: object, field: str) -> bytes:
    return b"\x00" if value is None else b"\x01" + _uuid4_bytes(value, field)


def build_access_event_mac_input(
    *,
    key_id: str,
    topic_target_id: str,
    door_id: str,
    source_instance_id: str,
    source_boot_id: str,
    source_boot_count: int,
    event_id: str,
    session_id: str,
    sequence: int,
    attempt: int,
    event_code: str,
    stage: str,
    outcome: str,
    reason_code: str,
    causation_event_id: str | None,
    monotonic_ms: int,
    credential_ref: str | None,
    distance_mm: int | None,
    duration_ms: int | None,
    relay_hold_ms: int | None,
) -> bytes:
    """Build the language-neutral authenticated Target event evidence input."""

    if _KEY_ID.fullmatch(key_id) is None:
        raise ValueError("access evidence key id is invalid")
    if credential_ref is not None and not access_credential_ref_is_valid(
        credential_ref
    ):
        raise ValueError("credential_ref is invalid")
    return b"".join(
        (
            _EVENT_MAC_DOMAIN,
            _lp_ascii(key_id, "key_id"),
            _lp_ascii(topic_target_id, "topic_target_id"),
            _hex16_bytes(door_id, "door_id"),
            _lp_ascii(source_instance_id, "source_instance_id"),
            _hex16_bytes(source_boot_id, "source_boot_id"),
            _unsigned(
                source_boot_count, 64, "source_boot_count", minimum=1
            ).to_bytes(8, "big"),
            _uuid4_bytes(event_id, "event_id"),
            _uuid4_bytes(session_id, "session_id"),
            _unsigned(sequence, 64, "sequence").to_bytes(8, "big"),
            _unsigned(attempt, 32, "attempt", minimum=1).to_bytes(4, "big"),
            _lp_ascii(event_code, "event_code"),
            _lp_ascii(stage, "stage"),
            _lp_ascii(outcome, "outcome"),
            _lp_ascii(reason_code, "reason_code"),
            _optional_uuid4(causation_event_id, "causation_event_id"),
            _unsigned(monotonic_ms, 64, "monotonic_ms").to_bytes(8, "big"),
            _lp_ascii(
                credential_ref or "", "credential_ref", allow_empty=True
            ),
            _optional_unsigned(distance_mm, 32, "distance_mm"),
            _optional_unsigned(duration_ms, 64, "duration_ms"),
            _optional_unsigned(relay_hold_ms, 32, "relay_hold_ms"),
        )
    )


def access_evidence_mac(key: bytes, canonical: bytes) -> str:
    if len(key) != 32 or not any(key) or not canonical:
        raise ValueError("access evidence key or input is invalid")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()[:32]


def verify_access_evidence_mac(
    value: object, *, keyring: Mapping[str, bytes], key_id: object,
    canonical: bytes
) -> bool:
    if (
        not isinstance(value, str)
        or _MAC.fullmatch(value) is None
        or not isinstance(key_id, str)
        or _KEY_ID.fullmatch(key_id) is None
    ):
        return False
    key = keyring.get(key_id)
    if key is None:
        return False
    try:
        expected = access_evidence_mac(key, canonical)
    except ValueError:
        return False
    return hmac.compare_digest(value, expected)


def build_access_status_mac_input(
    *,
    key_id: str,
    topic_target_id: str,
    door_id: str,
    source_boot_id: str,
    source_boot_count: int,
    access_revision: int,
    state: str,
    last_terminal_session_id: str | None,
    last_terminal_event_sequence: int | None,
    last_terminal_event_code: str | None,
    last_terminal_credential_ref: str | None,
    last_terminal_reason_code: str | None,
    last_terminal_phase_mask: int,
    relay_commanded_on: bool,
    relay_pin_level: int,
) -> bytes:
    """Build one signed, replay-resistant Target access-status snapshot input."""

    if _KEY_ID.fullmatch(key_id) is None:
        raise ValueError("access evidence key id is invalid")
    if not isinstance(relay_commanded_on, bool):
        raise ValueError("relay_commanded_on is invalid")
    if relay_pin_level not in (0, 1) or isinstance(relay_pin_level, bool):
        raise ValueError("relay_pin_level is invalid")
    required_terminal_values = (
        last_terminal_session_id,
        last_terminal_event_sequence,
        last_terminal_event_code,
        last_terminal_reason_code,
    )
    if any(value is None for value in required_terminal_values) and not all(
        value is None for value in required_terminal_values
    ):
        raise ValueError("terminal status fields must be all present or all absent")
    if last_terminal_session_id is None:
        if last_terminal_credential_ref is not None or last_terminal_phase_mask != 0:
            raise ValueError("absent terminal status must have empty evidence")
    elif (
        last_terminal_credential_ref is not None
        and not access_credential_ref_is_valid(last_terminal_credential_ref)
    ):
        raise ValueError("last_terminal_credential_ref is invalid")
    return b"".join(
        (
            _STATUS_MAC_DOMAIN,
            _lp_ascii(key_id, "key_id"),
            _lp_ascii(topic_target_id, "topic_target_id"),
            _hex16_bytes(door_id, "door_id"),
            _hex16_bytes(source_boot_id, "source_boot_id"),
            _unsigned(
                source_boot_count, 64, "source_boot_count", minimum=1
            ).to_bytes(8, "big"),
            _unsigned(access_revision, 64, "access_revision", minimum=1).to_bytes(
                8, "big"
            ),
            _lp_ascii(state, "state"),
            _optional_uuid4(
                last_terminal_session_id, "last_terminal_session_id"
            ),
            _optional_unsigned(
                last_terminal_event_sequence,
                64,
                "last_terminal_event_sequence",
            ),
            _lp_ascii(
                last_terminal_event_code or "",
                "last_terminal_event_code",
                allow_empty=True,
            ),
            _lp_ascii(
                last_terminal_reason_code or "",
                "last_terminal_reason_code",
                allow_empty=True,
            ),
            _lp_ascii(
                last_terminal_credential_ref or "",
                "last_terminal_credential_ref",
                allow_empty=True,
            ),
            _unsigned(
                last_terminal_phase_mask, 16, "last_terminal_phase_mask"
            ).to_bytes(2, "big"),
            b"\x01" if relay_commanded_on else b"\x00",
            bytes((relay_pin_level,)),
        )
    )


def build_mobile_access_session_read_input(
    credential_id: str,
    session_id: str,
    nonce_hex: str,
    expires_at: int,
) -> bytes:
    """Build the fixed 80-byte AndroidKeyStore read-authorization input."""

    try:
        credential = bytes.fromhex(credential_id)
        session = uuid.UUID(session_id)
        nonce = bytes.fromhex(nonce_hex)
        expiry = int(expires_at)
    except (ValueError, AttributeError, TypeError, OverflowError) as exc:
        raise ValueError("mobile access read proof input is invalid") from exc
    if (
        len(credential_id) != 32
        or credential_id != credential_id.lower()
        or len(credential) != 16
        or session.version != 4
        or str(session) != session_id
        or len(nonce_hex) != 64
        or nonce_hex != nonce_hex.lower()
        or len(nonce) != 32
        or not 0 <= expiry <= (1 << 64) - 1
    ):
        raise ValueError("mobile access read proof input is invalid")
    canonical = (
        b"SGKASR01"
        + credential
        + session.bytes
        + nonce
        + expiry.to_bytes(8, "big")
    )
    if len(canonical) != 80:
        raise AssertionError("mobile access read proof length changed")
    return canonical
