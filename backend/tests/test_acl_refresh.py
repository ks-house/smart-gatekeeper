from __future__ import annotations

import threading
import time
import unittest

from backend.app.acl_refresh import AclRefreshWorker


TARGET = "target-a"
TENANT = "1" * 32
DOOR = "2" * 32


class AclRefreshWorkerTest(unittest.TestCase):
    def test_boot_callback_requests_coalesce_while_publish_wait_runs_off_thread(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        completed_twice = threading.Event()
        calls: list[tuple[str, str, str, str]] = []

        def refresh(
            target_id: str, tenant_id: str, door_id: str, reason: str
        ) -> bool:
            calls.append((target_id, tenant_id, door_id, reason))
            entered.set()
            if len(calls) == 1:
                release.wait(1.0)
            if len(calls) >= 2:
                completed_twice.set()
            return True

        worker = AclRefreshWorker(
            {TARGET: {"tenant_id": TENANT, "door_id": DOOR}},
            refresh,
            lease_seconds=900,
        )
        self.assertEqual(600.0, worker.refresh_interval_seconds)
        worker.start()
        self.assertTrue(entered.wait(0.5))
        started = time.monotonic()
        self.assertTrue(worker.request(TARGET, "target_boot"))
        self.assertTrue(worker.request(TARGET, "target_boot"))
        self.assertLess(time.monotonic() - started, 0.1)
        release.set()
        self.assertTrue(completed_twice.wait(0.5))
        worker.stop()
        self.assertEqual(2, len(calls))
        self.assertEqual("lease_refresh", calls[0][3])
        self.assertEqual("target_boot", calls[1][3])

    def test_unknown_target_and_reason_are_rejected_without_queue_growth(self) -> None:
        worker = AclRefreshWorker(
            {TARGET: {"tenant_id": TENANT, "door_id": DOOR}},
            lambda *_args: True,
            lease_seconds=900,
        )
        self.assertFalse(worker.request("other", "target_boot"))
        self.assertFalse(worker.request(TARGET, "unbounded"))


if __name__ == "__main__":
    unittest.main()
