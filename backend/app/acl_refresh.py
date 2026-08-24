"""Bounded asynchronous Target ACL reboot recovery and lease renewal."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping


class AclRefreshWorker:
    """Coalesce refresh requests and keep every configured Target lease fresh.

    MQTT callbacks only add a target to a bounded dictionary. A single daemon
    worker performs the potentially blocking signed publish/application-ACK wait.
    """

    def __init__(
        self,
        targets: Mapping[str, Mapping[str, str]],
        refresh: Callable[[str, str, str, str], bool],
        *,
        lease_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 1 <= lease_seconds <= 3600 or not targets:
            raise ValueError("ACL refresh requires targets and a bounded lease")
        normalized: dict[str, dict[str, str]] = {}
        for target_id, scope in targets.items():
            tenant_id = scope.get("tenant_id")
            door_id = scope.get("door_id")
            if (
                not isinstance(target_id, str)
                or not target_id
                or not isinstance(tenant_id, str)
                or not isinstance(door_id, str)
            ):
                raise ValueError("invalid ACL refresh Target scope")
            normalized[target_id] = {"tenant_id": tenant_id, "door_id": door_id}
        self._targets = normalized
        self._refresh = refresh
        self._clock = clock
        margin = max(0.1, min(300.0, lease_seconds / 3.0))
        self.refresh_interval_seconds = max(0.1, lease_seconds - margin)
        self.retry_interval_seconds = max(
            0.1, min(30.0, self.refresh_interval_seconds / 4.0)
        )
        self._condition = threading.Condition()
        self._pending: dict[str, str] = {}
        now = self._clock()
        # An immediate asynchronous pass covers Backend restarts that occurred
        # after the Target's non-retained boot publication.
        self._next_due = {target_id: now for target_id in self._targets}
        self._stopping = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run,
                name="sgk-acl-refresh",
                daemon=True,
            )
            self._thread.start()

    def request(self, target_id: str, reason: str) -> bool:
        if reason not in {"target_boot", "lease_refresh"}:
            return False
        with self._condition:
            if self._stopping or target_id not in self._targets:
                return False
            # One entry per configured Target bounds callback-side memory.
            self._pending[target_id] = reason
            self._condition.notify_all()
            return True

    def stop(self, *, timeout_seconds: float = 6.0) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout_seconds))

    def _select_locked(self, now: float) -> tuple[str, str] | None:
        if self._pending:
            target_id = sorted(self._pending)[0]
            return target_id, self._pending.pop(target_id)
        due = [
            target_id
            for target_id, deadline in self._next_due.items()
            if deadline <= now
        ]
        if due:
            return sorted(due)[0], "lease_refresh"
        return None

    def _run(self) -> None:
        while True:
            with self._condition:
                while True:
                    if self._stopping:
                        return
                    now = self._clock()
                    selected = self._select_locked(now)
                    if selected is not None:
                        break
                    delay = max(0.0, min(self._next_due.values()) - now)
                    self._condition.wait(delay)
            target_id, reason = selected
            scope = self._targets[target_id]
            try:
                succeeded = bool(
                    self._refresh(
                        target_id,
                        scope["tenant_id"],
                        scope["door_id"],
                        reason,
                    )
                )
            except Exception:
                succeeded = False
            with self._condition:
                interval = (
                    self.refresh_interval_seconds
                    if succeeded
                    else self.retry_interval_seconds
                )
                self._next_due[target_id] = self._clock() + interval
