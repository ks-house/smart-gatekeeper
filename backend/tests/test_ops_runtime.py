import logging
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend.app.ops_runtime import (
    CircuitBreaker,
    IdempotencyLedger,
    OperationalMetrics,
    PersistentMqttPublisher,
    PrivacyLogFilter,
    SlidingWindowRateLimiter,
    opaque_ref,
    redact_text,
    redact_value,
    support_export,
)
from backend.app.admin_security import AdminSecurity


class _Result:
    def __init__(self, published=True):
        self.published = published

    def wait_for_publish(self, timeout):
        if timeout <= 0:
            raise TimeoutError

    def is_published(self):
        return self.published


class _Client:
    def __init__(self, *, fail=False, block=None):
        self.fail = fail
        self.block = block
        self.loop_starts = 0
        self.publishes = 0

    def loop_start(self):
        self.loop_starts += 1

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def publish(self, _topic, _payload, qos, retain):
        self.publishes += 1
        if self.block:
            self.block.wait(1)
        if self.fail:
            raise OSError("token=do-not-log")
        self.assert_publish_contract = (qos, retain)
        return _Result()


class OperationsRuntimeTest(unittest.TestCase):
    def test_redaction_removes_secret_mac_and_url_query_recursively(self):
        raw = (
            "device AA:BB:CC:DD:EE:FF token=abc123456789 "
            "https://example.test/artifact?tenant=raw"
        )
        redacted = redact_text(raw)
        self.assertNotIn("AA:BB", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("tenant=raw", redacted)
        structured = redact_value({"tenant_id": "raw", "nested": {"proof": "secret"}})
        self.assertEqual("<redacted>", structured["tenant_id"])
        self.assertEqual("<redacted>", structured["nested"]["proof"])

    def test_log_filter_never_formats_raw_exception_or_arguments(self):
        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "password=%s %s", ("hunter2", "AA:BB:CC:DD:EE:FF"), None
        )
        record.exc_info = (ValueError, ValueError("token=raw-secret"), None)
        self.assertTrue(PrivacyLogFilter().filter(record))
        rendered = record.getMessage()
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("AA:BB", rendered)
        self.assertIsNone(record.exc_info)

    def test_opaque_reference_is_stable_scoped_and_requires_strong_key(self):
        key = b"k" * 32
        value = opaque_ref("tenant-raw", key, "tenant")
        self.assertEqual(value, opaque_ref("tenant-raw", key, "tenant"))
        self.assertNotEqual(value, opaque_ref("tenant-raw", key, "device"))
        self.assertNotIn("tenant-raw", value)
        with self.assertRaises(ValueError):
            opaque_ref("tenant-raw", b"short")

    def test_rate_limiter_is_bounded_and_retry_is_deterministic(self):
        limiter = SlidingWindowRateLimiter(2, 10, max_keys=2)
        self.assertEqual((True, 0), limiter.allow("a", 0))
        self.assertEqual((True, 0), limiter.allow("a", 1))
        allowed, retry = limiter.allow("a", 2)
        self.assertFalse(allowed)
        self.assertEqual(8, retry)
        limiter.allow("b", 2)
        limiter.allow("c", 2)
        self.assertLessEqual(len(limiter._hits), 2)

    def test_idempotency_ledger_has_single_owner_and_cached_result(self):
        ledger = IdempotencyLedger(ttl_seconds=10, max_entries=2)
        self.assertEqual("owner", ledger.reserve("request", 0).state)
        self.assertEqual("reserved", ledger.reserve("request", 1).state)
        ledger.complete("request", {"status": "done"}, 2)
        duplicate = ledger.reserve("request", 3)
        self.assertEqual("completed", duplicate.state)
        self.assertEqual({"status": "done"}, duplicate.response)
        self.assertEqual("owner", ledger.reserve("request", 11).state)

    def test_circuit_breaker_opens_and_half_open_probe_recovers(self):
        breaker = CircuitBreaker(failure_threshold=2, reset_seconds=5)
        breaker.failure(0)
        self.assertTrue(breaker.permit(1))
        breaker.failure(1)
        self.assertFalse(breaker.permit(2))
        self.assertTrue(breaker.permit(6))
        self.assertFalse(breaker.permit(6.1))
        breaker.success()
        self.assertEqual("closed", breaker.state)

    def test_publisher_reuses_session_and_discards_it_after_failure(self):
        clients = [_Client(), _Client()]
        calls = []

        def factory():
            client = clients[len(calls)]
            calls.append(client)
            return client

        publisher = PersistentMqttPublisher(factory, lambda client: None)
        self.assertTrue(publisher.publish("topic", "one"))
        self.assertTrue(publisher.publish("topic", "two"))
        self.assertEqual(1, len(calls))
        calls[0].fail = True
        self.assertFalse(publisher.publish("topic", "three"))
        self.assertTrue(publisher.publish("topic", "four"))
        self.assertEqual(2, len(calls))

    def test_publisher_backpressure_rejects_without_unbounded_wait(self):
        release = threading.Event()
        client = _Client(block=release)
        publisher = PersistentMqttPublisher(
            lambda: client, lambda _client: None, max_inflight=1
        )
        result = []
        worker = threading.Thread(target=lambda: result.append(publisher.publish("t", "p")))
        worker.start()
        while client.publishes == 0:
            pass
        self.assertFalse(publisher.publish("t", "second"))
        release.set()
        worker.join(1)
        self.assertEqual([True], result)

    def test_dns_tcp_tls_connect_is_deadline_bounded_and_cancelled(self):
        release = threading.Event()
        cancelled = threading.Event()
        factory_calls = []

        def factory():
            client = _Client()
            factory_calls.append(client)
            return client

        def blocked_connect(_client):
            release.wait(5)

        publisher = PersistentMqttPublisher(
            factory,
            blocked_connect,
            publish_timeout=0.1,
            connect_timeout=0.05,
            cancel_connect=lambda _client: cancelled.set(),
        )
        started = time.monotonic()
        self.assertFalse(publisher.publish("topic", "payload"))
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertTrue(cancelled.is_set())
        started = time.monotonic()
        self.assertFalse(publisher.probe(timeout=0.05))
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(1, len(factory_calls), "a blocked resolver must not fan out threads")
        release.set()
        publisher.close()

    def test_support_export_requires_consent_is_bounded_and_redacted(self):
        result = support_export(
            [{"event_code": "ACCESS_GRANTED", "tenant_id": "raw", "detail": "token=secret123"}],
            "consent_" + "a" * 24,
            "tenant_" + "c" * 24,
        )
        self.assertNotIn("tenant_id", result["records"][0])
        self.assertNotIn("detail", result["records"][0])
        self.assertNotIn("secret123", str(result))
        self.assertRegex(result["sha256"], r"^[a-f0-9]{64}$")
        with self.assertRaises(ValueError):
            support_export([], "ticket-123", "tenant_" + "c" * 24)
        with self.assertRaises(ValueError):
            support_export([{}] * 501, "consent_" + "b" * 24, "tenant_" + "c" * 24)
        with self.assertRaises(ValueError):
            support_export([], "consent_" + "b" * 24, "legacy:1")

    def test_metrics_have_only_fixed_labels(self):
        metrics = OperationalMetrics()
        metrics.request("control", "2xx", 0.2)
        metrics.event("mqtt", "published")
        body = metrics.prometheus("a" * 40, "open")
        self.assertIn('component="mqtt",outcome="published"', body)
        self.assertIn("sgk_mqtt_circuit_open 1", body)
        self.assertNotIn("tenant", body)

    def test_admin_identity_secret_file_is_fail_closed_on_conflict_or_error(self):
        with tempfile.TemporaryDirectory() as directory:
            identity_file = Path(directory) / "identities.json"
            identity_file.write_text(
                '{"' + "a" * 64 + '":{"subject":"admin","roles":["AUDITOR"],"tenants":["*"]}}',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "ADMIN_MTLS_IDENTITIES_JSON_FILE": str(identity_file),
                "ADMIN_TRUSTED_PROXY_IPS": "127.0.0.1",
            }, clear=True):
                self.assertTrue(AdminSecurity.from_environment().enabled)
            with patch.dict(os.environ, {
                "ADMIN_MTLS_IDENTITIES_JSON": "{}",
                "ADMIN_MTLS_IDENTITIES_JSON_FILE": str(identity_file),
            }, clear=True):
                self.assertFalse(AdminSecurity.from_environment().enabled)


if __name__ == "__main__":
    unittest.main()
