"""Bounded, privacy-safe operational primitives for Smart Gatekeeper.

The module deliberately has no FastAPI or database dependency so the same
contracts can be fault-tested without a broker, database, or physical Target.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit


_MAC = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret|private[_-]?key|proof|signature)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_QUERY_URL = re.compile(r"https?://[^\s\]\[()<>\"']+")


def opaque_ref(value: str, key: bytes, namespace: str = "identity") -> str:
    """Return a non-reversible, namespace-bound reference suitable for logs."""
    if not value or len(key) < 32:
        raise ValueError("opaque references require a value and a 32-byte key")
    digest = hmac.new(key, f"{namespace}\0{value}".encode(), hashlib.sha256).hexdigest()
    return f"{namespace}_{digest[:24]}"


def redact_text(value: str) -> str:
    """Best-effort final safety net; producers must still use an allow-list."""
    text = _MAC.sub("<redacted-mac>", str(value))
    text = _BEARER.sub("Bearer <redacted>", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", text)

    def strip_query(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            parts = urlsplit(raw)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except ValueError:
            return "<redacted-url>"

    return _QUERY_URL.sub(strip_query, text)


def redact_value(value: Any) -> Any:
    """Recursively redact structured support/log values with a deny-list."""
    forbidden = {
        "tenant_id", "tenant_name", "unit", "unit_number", "device_id",
        "target_id", "ble_mac", "mac", "credential", "credential_id",
        "password", "token", "api_key", "secret", "private_key", "proof",
        "signature", "nonce", "raw_payload", "request_body", "stack_trace",
    }
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            result[str(key)] = "<redacted>" if normalized in forbidden else redact_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class PrivacyLogFilter(logging.Filter):
    """Redact every message/argument and suppress exception payloads by default."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except (TypeError, ValueError):
            rendered = str(record.msg)
        record.msg = redact_text(rendered)
        record.args = ()
        if record.exc_info:
            record.exc_info = None
            record.exc_text = "<exception-redacted>"
        return True


class SlidingWindowRateLimiter:
    """Thread-safe bounded-cardinality limiter using opaque caller keys."""

    def __init__(self, limit: int, window_seconds: float, max_keys: int = 4096):
        if limit <= 0 or window_seconds <= 0 or max_keys <= 0:
            raise ValueError("rate-limit values must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._hits: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str, now: Optional[float] = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            hits = [hit for hit in self._hits.pop(key, []) if hit > cutoff]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                retry = max(1, int(hits[0] + self.window_seconds - current + 0.999))
                return False, retry
            hits.append(current)
            self._hits[key] = hits
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            return True, 0


class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 3, reset_seconds: float = 15.0):
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._failures = 0
        self._opened_at = 0.0
        self._state = self.CLOSED
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def permit(self, now: Optional[float] = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            if self._state == self.OPEN and current - self._opened_at >= self.reset_seconds:
                self._state = self.HALF_OPEN
                return True
            return self._state == self.CLOSED

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = self.CLOSED

    def failure(self, now: Optional[float] = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold or self._state == self.HALF_OPEN:
                self._state = self.OPEN
                self._opened_at = current


@dataclass(frozen=True)
class LedgerResult:
    state: str
    response: Any = None


class IdempotencyLedger:
    """Bounded TTL ledger: only one owner may perform an irreversible effect."""

    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 4096):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def reserve(self, key: str, now: Optional[float] = None) -> LedgerResult:
        current = time.monotonic() if now is None else now
        with self._lock:
            while self._entries:
                first_key, (created, _, _) = next(iter(self._entries.items()))
                if created + self.ttl_seconds > current:
                    break
                self._entries.pop(first_key)
            existing = self._entries.get(key)
            if existing:
                _, state, response = existing
                return LedgerResult(state, response)
            self._entries[key] = (current, "reserved", None)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return LedgerResult("owner")

    def complete(self, key: str, response: Any, now: Optional[float] = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            if key not in self._entries:
                raise KeyError("idempotency key was not reserved")
            created = self._entries[key][0]
            self._entries[key] = (created if created <= current else current, "completed", response)


class OperationalMetrics:
    """Low-cardinality counters and fixed latency buckets in Prometheus text."""

    LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)

    def __init__(self):
        self._counters: dict[tuple[str, str], int] = defaultdict(int)
        self._latency: dict[str, list[int]] = defaultdict(
            lambda: [0 for _ in self.LATENCY_BUCKETS]
        )
        self._lock = threading.Lock()

    def request(self, route_group: str, status_class: str, seconds: float) -> None:
        with self._lock:
            self._counters[(route_group, status_class)] += 1
            buckets = self._latency[route_group]
            for index, upper in enumerate(self.LATENCY_BUCKETS):
                if seconds <= upper:
                    buckets[index] += 1

    def event(self, component: str, outcome: str) -> None:
        with self._lock:
            self._counters[(component, outcome)] += 1

    def prometheus(self, build_sha: str, breaker_state: str) -> str:
        lines = [
            "# HELP sgk_build_info Repository build identity.",
            "# TYPE sgk_build_info gauge",
            f'sgk_build_info{{sha="{build_sha}"}} 1',
            "# TYPE sgk_operations_total counter",
        ]
        with self._lock:
            for (component, outcome), value in sorted(self._counters.items()):
                lines.append(
                    f'sgk_operations_total{{component="{component}",outcome="{outcome}"}} {value}'
                )
            lines.append("# TYPE sgk_http_latency_seconds histogram")
            for group, buckets in sorted(self._latency.items()):
                for upper, value in zip(self.LATENCY_BUCKETS, buckets):
                    lines.append(
                        f'sgk_http_latency_seconds_bucket{{route_group="{group}",le="{upper}"}} {value}'
                    )
        lines.extend(
            (
                "# TYPE sgk_mqtt_circuit_open gauge",
                f"sgk_mqtt_circuit_open {1 if breaker_state == CircuitBreaker.OPEN else 0}",
            )
        )
        return "\n".join(lines) + "\n"


class PersistentMqttPublisher:
    """Single persistent MQTTS session with bounded inflight and breaker."""

    def __init__(
        self,
        client_factory: Callable[[], Any],
        connect: Callable[[Any], None],
        *,
        max_inflight: int = 16,
        publish_timeout: float = 2.0,
        breaker: Optional[CircuitBreaker] = None,
    ):
        self._client_factory = client_factory
        self._connect = connect
        self._capacity = threading.BoundedSemaphore(max_inflight)
        self._publish_timeout = publish_timeout
        self.breaker = breaker or CircuitBreaker()
        self._client: Any = None
        self._lock = threading.Lock()

    def _connected_client(self) -> Any:
        with self._lock:
            if self._client is None:
                client = self._client_factory()
                self._connect(client)
                client.loop_start()
                self._client = client
            return self._client

    def _discard(self) -> None:
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

    def publish(self, topic: str, payload: str) -> bool:
        if not self.breaker.permit() or not self._capacity.acquire(blocking=False):
            return False
        try:
            client = self._connected_client()
            result = client.publish(topic, payload, qos=1, retain=False)
            result.wait_for_publish(timeout=self._publish_timeout)
            if not result.is_published():
                raise TimeoutError("MQTT publish confirmation unavailable")
            self.breaker.success()
            return True
        except Exception:
            self.breaker.failure()
            self._discard()
            return False
        finally:
            self._capacity.release()

    def probe(self, timeout: float = 1.0) -> bool:
        """Establish/reuse the session and require a broker CONNACK when exposed."""
        if not self.breaker.permit():
            return False
        try:
            client = self._connected_client()
            is_connected = getattr(client, "is_connected", None)
            if not callable(is_connected):
                return True
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if is_connected():
                    self.breaker.success()
                    return True
                time.sleep(0.01)
            raise TimeoutError("MQTT CONNACK unavailable")
        except Exception:
            self.breaker.failure()
            self._discard()
            return False

    def close(self) -> None:
        self._discard()


def support_export(
    records: list[Mapping[str, Any]],
    consent_id: str,
    scope_ref: str,
    max_records: int = 500,
) -> dict:
    """Build a bounded redacted export and bind its canonical SHA-256."""
    if not re.fullmatch(r"consent_[a-f0-9]{32}", consent_id):
        raise ValueError("a current opaque consent reference is required")
    if not re.fullmatch(r"tenant_[a-f0-9]{24}", scope_ref):
        raise ValueError("an opaque tenant scope reference is required")
    if len(records) > max_records:
        raise ValueError("support export exceeds the bounded record limit")
    allowed_fields = {
        "event_code", "reason_code", "auth_method", "is_success",
        "distance_mm", "created_at", "outcome", "stage", "attempt",
    }
    code_fields = {"event_code", "reason_code", "auth_method", "outcome", "stage"}
    safe_records = []
    for record in records:
        safe = {}
        for key, value in record.items():
            normalized = str(key).lower()
            if normalized not in allowed_fields:
                continue
            if normalized in code_fields and (
                not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value)
            ):
                safe[normalized] = "<redacted>"
            else:
                safe[normalized] = redact_value(value)
        safe_records.append(safe)
    payload = {
        "schema": "sgk-support-export-v1",
        "consent_ref": consent_id,
        "scope_ref": scope_ref,
        "records": safe_records,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload
