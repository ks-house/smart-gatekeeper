"""Durable current-boot registry fed only by per-Target authenticated MQTT topics."""

from __future__ import annotations

import json
import re
import secrets
import time
from enum import Enum
from typing import Callable


_TOPIC = re.compile(r"^gatekeeper/v1/targets/([A-Za-z0-9_-]{1,64})/boot$")
_STATUS_TOPIC = re.compile(
    r"^gatekeeper/v1/targets/([A-Za-z0-9_-]{1,64})/status$"
)
_BOOT_ID = re.compile(r"^[0-9a-f]{32}$")


class BootRefreshOutcome(str, Enum):
    REJECTED = "rejected"
    UNCHANGED = "unchanged"
    ADVANCED = "advanced"


class TargetBootRegistry:
    def __init__(self, connection_factory: Callable[[], object], clock=time.time):
        self._connection_factory = connection_factory
        self._clock = clock

    def refresh_from_authenticated_topic(self, topic: str, payload: bytes) -> bool:
        return (
            self.refresh_outcome_from_authenticated_topic(topic, payload)
            is not BootRefreshOutcome.REJECTED
        )

    def refresh_outcome_from_authenticated_topic(
        self, topic: str, payload: bytes
    ) -> BootRefreshOutcome:
        match = _TOPIC.fullmatch(topic or "")
        if match is None or not isinstance(payload, (bytes, bytearray)):
            return BootRefreshOutcome.REJECTED
        try:
            document = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return BootRefreshOutcome.REJECTED
        target_id = match.group(1)
        if not isinstance(document, dict):
            return BootRefreshOutcome.REJECTED
        payload_target_id = document.get("target_id")
        if not isinstance(payload_target_id, str) or not secrets.compare_digest(
            payload_target_id, target_id
        ):
            return BootRefreshOutcome.REJECTED
        boot_id = document.get("boot_id")
        boot_count = document.get("boot_count")
        if (
            not isinstance(boot_id, str)
            or _BOOT_ID.fullmatch(boot_id) is None
            or isinstance(boot_count, bool)
            or not isinstance(boot_count, int)
            or not 0 < boot_count <= 0xFFFFFFFF
        ):
            return BootRefreshOutcome.REJECTED

        connection = self._connection_factory()
        try:
            connection.begin()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT boot_id, boot_count FROM target_boot_state "
                    "WHERE target_id=%s FOR UPDATE",
                    (target_id,),
                )
                current = cursor.fetchone()
                if current is not None:
                    current_count = int(current["boot_count"])
                    current_id = str(current["boot_id"])
                    if boot_count < current_count or (
                        boot_count == current_count
                        and not secrets.compare_digest(boot_id, current_id)
                    ):
                        connection.rollback()
                        return BootRefreshOutcome.REJECTED
                    if boot_count == current_count:
                        connection.commit()
                        return BootRefreshOutcome.UNCHANGED
                    cursor.execute(
                        "UPDATE target_boot_state SET boot_id=%s, boot_count=%s, "
                        "updated_at=%s WHERE target_id=%s",
                        (boot_id, boot_count, int(self._clock()), target_id),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO target_boot_state "
                        "(target_id, boot_id, boot_count, updated_at) "
                        "VALUES (%s, %s, %s, %s)",
                        (target_id, boot_id, boot_count, int(self._clock())),
                    )
            connection.commit()
            return BootRefreshOutcome.ADVANCED
        except Exception:
            connection.rollback()
            return BootRefreshOutcome.REJECTED
        finally:
            connection.close()

    def refresh_from_authenticated_status_topic(
        self, topic: str, payload: bytes, *, retained: bool = False
    ) -> bool:
        """Use periodic exact Target status as non-retained boot continuity evidence."""

        return (
            self.refresh_outcome_from_authenticated_status_topic(
                topic, payload, retained=retained
            )
            is not BootRefreshOutcome.REJECTED
        )

    def refresh_outcome_from_authenticated_status_topic(
        self, topic: str, payload: bytes, *, retained: bool = False
    ) -> BootRefreshOutcome:
        """Preserve whether fresh status discovered a new physical boot."""

        if retained:
            return BootRefreshOutcome.REJECTED
        match = _STATUS_TOPIC.fullmatch(topic or "")
        if match is None:
            return BootRefreshOutcome.REJECTED
        return self.refresh_outcome_from_authenticated_topic(
            f"gatekeeper/v1/targets/{match.group(1)}/boot", payload
        )

    def current_boot_id(self, target_id: str) -> str | None:
        if _TOPIC.fullmatch(f"gatekeeper/v1/targets/{target_id}/boot") is None:
            return None
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT boot_id FROM target_boot_state WHERE target_id=%s",
                    (target_id,),
                )
                current = cursor.fetchone()
            if current is None or _BOOT_ID.fullmatch(str(current["boot_id"])) is None:
                return None
            return str(current["boot_id"])
        except Exception:
            return None
        finally:
            connection.close()
