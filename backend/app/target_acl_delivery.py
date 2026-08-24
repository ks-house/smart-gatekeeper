"""Correlation for authenticated per-Target signed ACL application ACKs."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

try:
    from .acl_management import encode_acl
except ImportError:  # Docker runs uvicorn with /app as the import root.
    from acl_management import encode_acl


_ACK_TOPIC = re.compile(
    r"^gatekeeper/v1/targets/([A-Za-z0-9_-]{1,64})/acl/ack$"
)


@dataclass(frozen=True)
class TargetAclAppliedAck:
    target_id: str
    acl_version: int
    high_watermark: int


def target_acl_ack_topic(target_id: str) -> str:
    topic = f"gatekeeper/v1/targets/{target_id}/acl/ack"
    if _ACK_TOPIC.fullmatch(topic) is None:
        raise ValueError("invalid Target ID")
    return topic


def build_target_acl_wire_payload(envelope: dict[str, Any]) -> bytes:
    """Return the exact bytes consumed by TargetAclManager::applySignedAcl.

    The Target MQTT callback does not decode the Backend JSON envelope. Its wire
    contract is the canonical ``SGKACL01`` snapshot immediately followed by the
    primary 64-byte raw P-256 signature.
    """

    if not isinstance(envelope, dict) or not isinstance(envelope.get("fields"), dict):
        raise ValueError("invalid ACL envelope")
    canonical = encode_acl(envelope["fields"])
    canonical_hex = envelope.get("canonical_hex")
    signature_hex = envelope.get("signature_raw64")
    digest_hex = envelope.get("sha256")
    if not all(isinstance(value, str) for value in (canonical_hex, signature_hex, digest_hex)):
        raise ValueError("ACL envelope is missing canonical signature material")
    if (
        re.fullmatch(r"[0-9a-f]+", canonical_hex) is None
        or re.fullmatch(r"[0-9a-f]{128}", signature_hex) is None
        or re.fullmatch(r"[0-9a-f]{64}", digest_hex) is None
    ):
        raise ValueError("ACL envelope hexadecimal must be strict lowercase")
    try:
        persisted_canonical = bytes.fromhex(canonical_hex)
        signature = bytes.fromhex(signature_hex)
    except ValueError as exc:
        raise ValueError("invalid ACL envelope hexadecimal") from exc
    if (
        not hmac.compare_digest(persisted_canonical, canonical)
        or len(signature) != 64
        or not hmac.compare_digest(hashlib.sha256(canonical).hexdigest(), digest_hex)
    ):
        raise ValueError("ACL envelope does not match its canonical wire payload")
    return canonical + signature


def parse_target_acl_ack(
    topic: str, payload: bytes, *, retained: bool = False
) -> Optional[TargetAclAppliedAck]:
    if retained or not isinstance(payload, (bytes, bytearray)):
        return None
    match = _ACK_TOPIC.fullmatch(topic or "")
    if match is None or not 0 < len(payload) <= 256:
        return None
    try:
        document = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict) or set(document) != {
        "status",
        "acl_version",
        "high_watermark",
    }:
        return None
    version = document.get("acl_version")
    high_watermark = document.get("high_watermark")
    if (
        document.get("status") != "applied"
        or isinstance(version, bool)
        or not isinstance(version, int)
        or isinstance(high_watermark, bool)
        or not isinstance(high_watermark, int)
        or not 1 <= version <= 0xFFFFFFFFFFFFFFFF
        or high_watermark != version
    ):
        return None
    return TargetAclAppliedAck(match.group(1), version, high_watermark)


class TargetAclDeliveryTracker:
    """Wait for exact Target application ACKs without treating PUBACK as apply."""

    def __init__(
        self,
        *,
        clock=time.monotonic,
        maximum_records: int = 128,
        record_ttl_seconds: float = 30.0,
    ) -> None:
        if maximum_records < 1 or not 0 < record_ttl_seconds <= 300:
            raise ValueError("maximum_records must be positive")
        self._clock = clock
        self._maximum_records = maximum_records
        self._record_ttl_seconds = record_ttl_seconds
        self._condition = threading.Condition()
        self._applied: dict[tuple[str, int], float] = {}

    def _prune_locked(self, now: float) -> None:
        stale = [
            key
            for key, received_at in self._applied.items()
            if received_at + self._record_ttl_seconds <= now
        ]
        for key in stale:
            self._applied.pop(key, None)

    def begin_delivery(self, target_ids: Iterable[str], acl_version: int) -> bool:
        """Forget pre-publication ACKs and reserve one exact version attempt."""

        expected = {(target_id, acl_version) for target_id in target_ids}
        if not expected or not 1 <= acl_version <= 0xFFFFFFFFFFFFFFFF:
            return False
        try:
            for target_id, _version in expected:
                target_acl_ack_topic(target_id)
        except ValueError:
            return False
        with self._condition:
            self._prune_locked(self._clock())
            for key in expected:
                self._applied.pop(key, None)
        return True

    def reset_transport(self) -> None:
        """Discard ACK observations across MQTT subscriber reconnects."""

        with self._condition:
            self._applied.clear()
            self._condition.notify_all()

    def mark_applied(self, target_id: str, acl_version: int) -> None:
        target_acl_ack_topic(target_id)
        if not 1 <= acl_version <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("ACL version out of range")
        with self._condition:
            now = self._clock()
            self._prune_locked(now)
            self._applied[(target_id, acl_version)] = now
            while len(self._applied) > self._maximum_records:
                oldest = min(self._applied, key=self._applied.get)
                self._applied.pop(oldest, None)
            self._condition.notify_all()

    def wait_for(
        self,
        target_ids: Iterable[str],
        acl_version: int,
        *,
        timeout_seconds: float,
    ) -> bool:
        expected = {(target_id, acl_version) for target_id in target_ids}
        if not expected or not 0 < timeout_seconds <= 30:
            return False
        deadline = self._clock() + timeout_seconds
        with self._condition:
            while True:
                now = self._clock()
                self._prune_locked(now)
                if expected.issubset(self._applied):
                    return True
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
