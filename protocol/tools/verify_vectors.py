#!/usr/bin/env python3
"""Verify Smart Gatekeeper protocol v1 canonical vectors with stdlib only."""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import math
from pathlib import Path
from typing import Any


P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (GX, GY)

CHALLENGE_DOMAIN = b"SGKCHAL1"
PROOF_DOMAIN = b"SGKPRF01"
ACL_DOMAIN = b"SGKACL01"
FRAME_MAGIC = b"SG"
FRAME_HEADER_SIZE = 10
MAX_MESSAGE_SIZE = 2048
ACL_SCHEMA_VERSION = 1
ACL_MAX_ENTRIES = 64
ACL_MAX_LEASE_SECONDS = 3600
ACL_KNOWN_STATUSES = {0, 1}
ACL_KNOWN_PERMISSION_MASK = 0x00000001


def u8(value: int) -> bytes:
    if not 0 <= value <= 0xFF:
        raise ValueError("u8 out of range")
    return value.to_bytes(1, "big")


def u16(value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError("u16 out of range")
    return value.to_bytes(2, "big")


def u32(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("u32 out of range")
    return value.to_bytes(4, "big")


def u64(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("u64 out of range")
    return value.to_bytes(8, "big")


def hx(value: str, size: int, field: str) -> bytes:
    if len(value) != size * 2 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be {size} bytes of lowercase hexadecimal")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not lowercase hexadecimal") from exc
    if len(decoded) != size:
        raise ValueError(f"{field} must be {size} bytes of lowercase hexadecimal")
    return decoded


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def client_hello_bytes(fields: dict[str, Any]) -> bytes:
    return b"".join(
        (
            u16(fields["protocol_min"]),
            u16(fields["protocol_max"]),
            u8(fields["framing_min"]),
            u8(fields["framing_max"]),
            u16(fields["max_rx_message"]),
            u32(fields["capabilities"]),
            u32(fields["mobile_build"]),
        )
    )


def target_hello_bytes(fields: dict[str, Any]) -> bytes:
    return b"".join(
        (
            u16(fields["selected_protocol"]),
            u16(fields["protocol_min"]),
            u16(fields["protocol_max"]),
            u8(fields["selected_framing"]),
            u8(fields["status"]),
            u16(fields["max_rx_message"]),
            u32(fields["capabilities"]),
            u32(fields["firmware_build"]),
            u16(fields["security_floor"]),
        )
    )


def challenge_bytes(fields: dict[str, Any]) -> bytes:
    return b"".join(
        (
            CHALLENGE_DOMAIN,
            u16(fields["protocol_version"]),
            hx(fields["door_id"], 16, "door_id"),
            hx(fields["session_id"], 16, "session_id"),
            hx(fields["nonce"], 32, "nonce"),
            hx(fields["target_boot_id"], 16, "target_boot_id"),
            u64(fields["expiry_monotonic_ms"]),
            u64(fields["acl_version"]),
            hx(fields["negotiation_hash"], 32, "negotiation_hash"),
        )
    )


def proof_input_bytes(challenge: bytes, fields: dict[str, Any]) -> bytes:
    return b"".join(
        (
            PROOF_DOMAIN,
            sha256(challenge),
            hx(fields["credential_id"], 16, "credential_id"),
            u8(fields["action"]),
            u32(fields["client_capabilities"]),
        )
    )


def validate_acl_semantics(fields: dict[str, Any]) -> None:
    entries = fields["entries"]
    if fields["schema_version"] != ACL_SCHEMA_VERSION:
        raise ValueError("unknown ACL schema_version")
    if fields["acl_version"] < 1:
        raise ValueError("ACL acl_version must be positive")
    if not 1 <= fields["lease_duration_s"] <= ACL_MAX_LEASE_SECONDS:
        raise ValueError("ACL lease_duration_s out of range")
    if not (
        fields["issued_at_epoch_s"]
        <= fields["not_before_epoch_s"]
        < fields["expires_at_epoch_s"]
    ):
        raise ValueError("invalid ACL snapshot time range")
    if not 1 <= fields["min_protocol"] <= fields["max_protocol"]:
        raise ValueError("invalid ACL snapshot protocol range")
    if len(entries) > ACL_MAX_ENTRIES:
        raise ValueError(f"ACL entry_count exceeds {ACL_MAX_ENTRIES}")

    credential_ids = [hx(entry["credential_id"], 16, "credential_id") for entry in entries]
    if credential_ids != sorted(credential_ids) or len(set(credential_ids)) != len(entries):
        raise ValueError("ACL entries must be unique and sorted by credential_id")
    for entry in entries:
        public_key = hx(entry["public_key_sec1"], 65, "public_key_sec1")
        parse_public_key(public_key)
        if entry["status"] not in ACL_KNOWN_STATUSES:
            raise ValueError("unknown ACL status")
        permissions = entry["permissions"]
        if not 0 <= permissions <= 0xFFFFFFFF:
            raise ValueError("ACL permissions out of range")
        if permissions & ~ACL_KNOWN_PERMISSION_MASK:
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


def acl_bytes(fields: dict[str, Any]) -> bytes:
    validate_acl_semantics(fields)
    entries = fields["entries"]
    encoded = bytearray(
        b"".join(
            (
                ACL_DOMAIN,
                u16(fields["schema_version"]),
                hx(fields["door_id"], 16, "door_id"),
                u64(fields["acl_version"]),
                u64(fields["issued_at_epoch_s"]),
                u64(fields["not_before_epoch_s"]),
                u64(fields["expires_at_epoch_s"]),
                u32(fields["lease_duration_s"]),
                u16(fields["min_protocol"]),
                u16(fields["max_protocol"]),
                u32(fields["signing_key_id"]),
                u16(len(entries)),
            )
        )
    )
    for entry in entries:
        encoded.extend(hx(entry["credential_id"], 16, "credential_id"))
        public_key = hx(entry["public_key_sec1"], 65, "public_key_sec1")
        encoded.extend(public_key)
        encoded.extend(u8(entry["status"]))
        encoded.extend(u32(entry["permissions"]))
        encoded.extend(u64(entry["not_before_epoch_s"]))
        encoded.extend(u64(entry["not_after_epoch_s"]))
        encoded.extend(u16(entry["min_protocol"]))
        encoded.extend(u16(entry["max_protocol"]))
    return bytes(encoded)


def point_add(left: tuple[int, int] | None, right: tuple[int, int] | None) -> tuple[int, int] | None:
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


def scalar_mult(scalar: int, point: tuple[int, int] | None = G) -> tuple[int, int] | None:
    result = None
    addend = point
    while scalar:
        if scalar & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        scalar >>= 1
    return result


def public_key_sec1(private_scalar: int) -> bytes:
    point = scalar_mult(private_scalar)
    if point is None:
        raise ValueError("invalid private scalar")
    return b"\x04" + point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")


def parse_public_key(value: bytes) -> tuple[int, int]:
    if len(value) != 65 or value[0] != 0x04:
        raise ValueError("invalid uncompressed SEC1 public key")
    point = (int.from_bytes(value[1:33], "big"), int.from_bytes(value[33:], "big"))
    if not (0 <= point[0] < P and 0 <= point[1] < P):
        raise ValueError("public key coordinate out of range")
    if (point[1] * point[1] - (point[0] ** 3 + A * point[0] + B)) % P != 0:
        raise ValueError("public key is not on P-256")
    return point


def rfc6979_nonce(private_scalar: int, digest: bytes) -> int:
    x = private_scalar.to_bytes(32, "big")
    digest_octets = (int.from_bytes(digest, "big") % N).to_bytes(32, "big")
    key = b"\x00" * 32
    value = b"\x01" * 32
    key = hmac.new(key, value + b"\x00" + x + digest_octets, hashlib.sha256).digest()
    value = hmac.new(key, value, hashlib.sha256).digest()
    key = hmac.new(key, value + b"\x01" + x + digest_octets, hashlib.sha256).digest()
    value = hmac.new(key, value, hashlib.sha256).digest()
    while True:
        value = hmac.new(key, value, hashlib.sha256).digest()
        candidate = int.from_bytes(value, "big")
        if 1 <= candidate < N:
            return candidate
        key = hmac.new(key, value + b"\x00", hashlib.sha256).digest()
        value = hmac.new(key, value, hashlib.sha256).digest()


def sign_raw64(private_scalar: int, message: bytes) -> bytes:
    if not 1 <= private_scalar < N:
        raise ValueError("invalid private scalar")
    digest = sha256(message)
    nonce = rfc6979_nonce(private_scalar, digest)
    point = scalar_mult(nonce)
    if point is None:
        raise AssertionError("unexpected point at infinity")
    r = point[0] % N
    s = (pow(nonce, -1, N) * (int.from_bytes(digest, "big") + r * private_scalar)) % N
    if s > N // 2:
        s = N - s
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verify_raw64(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if len(signature) != 64:
        return False
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    if not (1 <= r < N and 1 <= s <= N // 2):
        return False
    try:
        point = parse_public_key(public_key)
    except ValueError:
        return False
    z = int.from_bytes(sha256(message), "big")
    inverse = pow(s, -1, N)
    candidate = point_add(scalar_mult((z * inverse) % N), scalar_mult((r * inverse) % N, point))
    return candidate is not None and candidate[0] % N == r


def fragment_message(message: bytes, *, mtu: int, msg_type: int, message_id: int) -> list[bytes]:
    if not 23 <= mtu <= 517:
        raise ValueError("ATT_MTU must be between 23 and 517")
    if not message or len(message) > MAX_MESSAGE_SIZE:
        raise ValueError("message length out of range")
    chunk_size = mtu - 3 - FRAME_HEADER_SIZE
    count = math.ceil(len(message) / chunk_size)
    if count > 255:
        raise ValueError("too many fragments")
    frames = []
    for index in range(count):
        chunk = message[index * chunk_size : (index + 1) * chunk_size]
        frames.append(
            FRAME_MAGIC
            + u8(1)
            + u8(msg_type)
            + u16(message_id)
            + u8(index)
            + u8(count)
            + u16(len(message))
            + chunk
        )
    return frames


def negotiate(client_min: int, client_max: int, target_min: int, target_max: int, floor: int) -> int | None:
    lower = max(client_min, target_min, floor)
    upper = min(client_max, target_max)
    return upper if lower <= upper else None


def acl_activation_decision(
    effective_high_watermark: int,
    current_digest: str,
    candidate_version: int,
    candidate_digest: str,
) -> str:
    if candidate_version < effective_high_watermark:
        return "reject_stale"
    if candidate_version == effective_high_watermark:
        if hmac.compare_digest(candidate_digest, current_digest):
            return "idempotent_no_lease_refresh"
        return "reject_version_conflict"
    return "activate"


def acl_boot_recovery(case: dict[str, Any]) -> dict[str, Any]:
    legacy_active = case.get("legacy_active")
    valid_legacy_active_version = 0
    if legacy_active is not None and legacy_active["snapshot_valid"]:
        valid_legacy_active_version = legacy_active["version"]

    records = [record for record in case["activation_records"] if record["record_valid"]]
    record_floor = max((record["version"] for record in records), default=0)
    effective = max(
        case["persisted_legacy_high_watermark"],
        valid_legacy_active_version,
        record_floor,
    )

    active_version = None
    if records:
        newest = max(records, key=lambda record: record["generation"])
        if newest["slot_valid"] and newest["version"] == effective:
            active_version = newest["version"]
    elif valid_legacy_active_version == effective and legacy_active is not None:
        active_version = valid_legacy_active_version

    candidate_decision = (
        "activate" if case["candidate_version"] > effective else "reject_stale_or_equal"
    )
    return {
        "effective_high_watermark": effective,
        "active_version": active_version,
        "authorization_mode": "ready" if active_version is not None else "fail_closed",
        "candidate_decision": candidate_decision,
        "repair_legacy_floor_before_candidates": (
            effective > case["persisted_legacy_high_watermark"] and not records
        ),
    }


def ble_relay_assessment(case: dict[str, Any]) -> dict[str, bool]:
    wormhole_succeeds = (
        case["fresh_proof"]
        and case["relay_delay_ms"] < case["challenge_lifetime_ms"]
        and not case["relay_resistant_channel"]
    )

    relay_g0 = case.get("relay_g0")
    relay_g1 = case.get("relay_g1")
    relay_g2 = case.get("relay_g2")

    relay_g0_valid = isinstance(relay_g0, dict) and (
        relay_g0.get("threat_model_reviewed") is True
        and relay_g0.get("proxy_test_complete") is True
        and relay_g0.get("risk_owner_approved") is True
        and isinstance(relay_g0.get("evidence_id"), str)
        and bool(relay_g0["evidence_id"])
        and relay_g0.get("expected_wormhole_succeeds") is wormhole_succeeds
        and relay_g0.get("observed_wormhole_succeeds") is wormhole_succeeds
    )

    selected_path = relay_g1.get("selected_path") if isinstance(relay_g1, dict) else None
    path_control_valid = {
        "relay_resistant_channel": case["relay_resistant_channel"],
        "interactive_user_presence": case["user_presence_each_use"],
        "low_consequence_acceptance": (
            case["explicit_non_proximity_acceptance"] and case["low_consequence_door"]
        ),
    }.get(selected_path, False)
    relay_g1_valid = isinstance(relay_g1, dict) and (
        relay_g1.get("control_verified") is True
        and isinstance(relay_g1.get("evidence_id"), str)
        and bool(relay_g1["evidence_id"])
        and relay_g1.get("evidence_path") == selected_path
        and path_control_valid
    )

    operational_runs = relay_g2.get("operational_runs") if isinstance(relay_g2, dict) else None
    relay_g2_valid = isinstance(relay_g2, dict) and (
        relay_g2.get("regression_complete") is True
        and relay_g2.get("selected_path") == selected_path
        and isinstance(operational_runs, int)
        and not isinstance(operational_runs, bool)
        and operational_runs >= 100
        and relay_g2.get("successful_runs") == operational_runs
        and relay_g2.get("ota_rollback_verified") is True
        and isinstance(relay_g2.get("evidence_id"), str)
        and bool(relay_g2["evidence_id"])
    )

    deployment_allowed = relay_g0_valid and relay_g1_valid and relay_g2_valid
    return {
        "wormhole_succeeds": wormhole_succeeds,
        "relay_g0_valid": relay_g0_valid,
        "relay_g1_valid": relay_g1_valid,
        "relay_g2_valid": relay_g2_valid,
        "deployment_allowed": deployment_allowed,
    }


def acl_lease_usable(case: dict[str, Any]) -> bool:
    duration = case["lease_duration_s"]
    if not 1 <= duration <= 3600:
        return False
    if case["trusted_utc"]:
        if not case["not_before_epoch_s"] <= case["now_epoch_s"] < case["expires_at_epoch_s"]:
            return False
    elif not case["received_current_boot"]:
        return False
    if case["now_monotonic_ms"] < case["receipt_monotonic_ms"]:
        return False
    return case["now_monotonic_ms"] < case["receipt_monotonic_ms"] + duration * 1000


def expect(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def verify_document(document: dict[str, Any], emit_expected: bool) -> dict[str, Any]:
    hello = document["hello"]
    client = client_hello_bytes(hello["client"])
    target = target_hello_bytes(hello["target"])
    negotiation_hash = sha256(client + target)
    challenge_fields = document["challenge"]["fields"]
    expect("challenge negotiation_hash", challenge_fields["negotiation_hash"], negotiation_hash.hex())
    challenge = challenge_bytes(challenge_fields)
    proof_fields = document["proof"]["fields"]
    proof_input = proof_input_bytes(challenge, proof_fields)
    proof_private = int(document["proof"]["fixture_private_scalar_hex"], 16)
    proof_public = public_key_sec1(proof_private)
    proof_signature = sign_raw64(proof_private, proof_input)

    acl = acl_bytes(document["acl"]["fields"])
    acl_private = int(document["acl"]["fixture_signing_private_scalar_hex"], 16)
    acl_public = public_key_sec1(acl_private)
    acl_signature = sign_raw64(acl_private, acl)

    frames = fragment_message(
        challenge,
        mtu=document["framing"]["att_mtu"],
        msg_type=document["framing"]["message_type"],
        message_id=document["framing"]["message_id"],
    )

    generated = {
        "hello": {
            "client_hex": client.hex(),
            "target_hex": target.hex(),
            "negotiation_hash": negotiation_hash.hex(),
        },
        "challenge": {"canonical_hex": challenge.hex(), "sha256": sha256(challenge).hex()},
        "proof": {
            "input_hex": proof_input.hex(),
            "sha256": sha256(proof_input).hex(),
            "public_key_sec1": proof_public.hex(),
            "signature_raw64": proof_signature.hex(),
        },
        "acl": {
            "canonical_hex": acl.hex(),
            "sha256": sha256(acl).hex(),
            "signing_public_key_sec1": acl_public.hex(),
            "signature_raw64": acl_signature.hex(),
        },
        "framing": {"fragment_count": len(frames), "frames_hex": [frame.hex() for frame in frames]},
    }
    if emit_expected:
        return generated

    for section, values in generated.items():
        for key, actual in values.items():
            expect(f"{section}.{key}", actual, document[section]["expected"][key])

    expect("proof signature verify", verify_raw64(proof_public, proof_input, proof_signature), True)
    expect("ACL signature verify", verify_raw64(acl_public, acl, acl_signature), True)

    mutated = bytearray(proof_input)
    mutated[12] ^= 0x01
    expect("mutated proof", verify_raw64(proof_public, bytes(mutated), proof_signature), False)
    high_s = proof_signature[:32] + (N - int.from_bytes(proof_signature[32:], "big")).to_bytes(32, "big")
    expect("high-S proof", verify_raw64(proof_public, proof_input, high_s), False)
    expect("wrong key", verify_raw64(acl_public, proof_input, proof_signature), False)

    for case in document["negotiation_cases"]:
        selected = negotiate(
            case["client_min"], case["client_max"], case["target_min"], case["target_max"], case["security_floor"]
        )
        expect(f"negotiation {case['name']}", selected, case["expected_selected"])

    for case in document["acl_activation_cases"]:
        decision = acl_activation_decision(
            case["current_version"],
            case["current_digest"],
            case["candidate_version"],
            case["candidate_digest"],
        )
        expect(f"ACL activation {case['name']}", decision, case["expected_decision"])

    for case in document["acl_crash_recovery_cases"]:
        expect(
            f"ACL crash recovery {case['name']}",
            acl_boot_recovery(case),
            case["expected"],
        )

    for case in document["acl_semantic_rejection_cases"]:
        mutated_acl = copy.deepcopy(document["acl"]["fields"])
        for field, value in case.get("snapshot_overrides", {}).items():
            mutated_acl[field] = value
        for field, value in case.get("entry_overrides", {}).items():
            mutated_acl["entries"][0][field] = value
        try:
            acl_bytes(mutated_acl)
        except ValueError as exc:
            if case["expected_error"] not in str(exc):
                raise AssertionError(
                    f"ACL semantic rejection {case['name']}: unexpected error {exc!r}"
                ) from exc
        else:
            raise AssertionError(f"ACL semantic rejection {case['name']}: accepted")

    for case in document["ble_relay_cases"]:
        expect(
            f"BLE relay {case['name']}",
            ble_relay_assessment(case),
            case["expected"],
        )

    for case in document["lease_cases"]:
        expect(f"ACL lease {case['name']}", acl_lease_usable(case), case["expected_usable"])

    sessions: set[tuple[str, str, str, str]] = set()
    session_key = (
        challenge_fields["door_id"],
        challenge_fields["session_id"],
        challenge_fields["nonce"],
        challenge_fields["target_boot_id"],
    )
    expect("first proof is unused", session_key in sessions, False)
    sessions.add(session_key)
    expect("captured proof replay is consumed", session_key in sessions, True)
    return generated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "vector",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "test_vectors" / "v1.json",
    )
    parser.add_argument("--emit-expected", action="store_true")
    args = parser.parse_args()
    with args.vector.open(encoding="utf-8") as handle:
        document = json.load(handle)
    generated = verify_document(document, args.emit_expected)
    if args.emit_expected:
        print(json.dumps(generated, indent=2, sort_keys=True))
    else:
        print(f"PASS: {args.vector} ({document['schema']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
