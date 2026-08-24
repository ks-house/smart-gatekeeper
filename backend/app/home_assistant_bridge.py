"""Fail-closed Home Assistant MQTT bridge for signed Target commands.

Home Assistant publishes only to a backend-owned ingress namespace.  This
module never accepts a Target command envelope from Home Assistant; the
backend creates a fresh boot-bound envelope with its protected signing key.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


DEVICE_ID = "smart_gatekeeper_01"
TARGET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BOOT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
INTEGER_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)$")


@dataclass(frozen=True)
class Publication:
    topic: str
    payload: str
    qos: int = 1
    retain: bool = True


@dataclass(frozen=True)
class BridgeCommand:
    object_id: str
    action: str
    value: int
    expected_boot_id: str
    session_id: str
    nonce: str


@dataclass(frozen=True)
class BridgeDecision:
    accepted: bool
    reason: str
    command: Optional[BridgeCommand] = None


@dataclass(frozen=True)
class AckDecision:
    accepted: bool
    reason: str
    action: Optional[str] = None
    session_id: Optional[str] = None
    result_code: Optional[int] = None


@dataclass(frozen=True)
class _ControlDefinition:
    object_id: str
    action: str
    minimum: Optional[int]
    maximum: Optional[int]
    minimum_interval_seconds: float


_CONTROLS = {
    "open_gate": _ControlDefinition(
        "open_gate", "manual_remote", None, None, 5.0
    ),
    "trigger_ota": _ControlDefinition(
        "trigger_ota", "ota_check", None, None, 60.0
    ),
    "reboot": _ControlDefinition("reboot", "reboot", None, None, 60.0),
    "config_tx_power_num": _ControlDefinition(
        "config_tx_power_num", "set_tx_power", -6, 9, 0.5
    ),
    "config_dist_thresh_num": _ControlDefinition(
        "config_dist_thresh_num", "set_distance_threshold", 20, 200, 0.5
    ),
    "config_duration_num": _ControlDefinition(
        "config_duration_num", "set_duration", 1000, 60000, 0.5
    ),
    "config_relay_cooldown_num": _ControlDefinition(
        "config_relay_cooldown_num", "set_relay_cooldown", 1000, 10000, 0.5
    ),
}


def _validate_target_id(target_id: str) -> None:
    if TARGET_ID_PATTERN.fullmatch(target_id) is None:
        raise ValueError("target ID must match [A-Za-z0-9_-]{1,64}")


def bridge_prefix(target_id: str) -> str:
    _validate_target_id(target_id)
    return f"gatekeeper/v1/ha-bridge/{target_id}"


def bridge_request_topic(target_id: str, object_id: str = "+") -> str:
    if object_id != "+" and object_id not in _CONTROLS:
        raise ValueError("unknown Home Assistant control")
    return f"{bridge_prefix(target_id)}/request/{object_id}"


def bridge_availability_topic(target_id: str) -> str:
    return f"{bridge_prefix(target_id)}/availability"


def bridge_result_topic(target_id: str) -> str:
    return f"{bridge_prefix(target_id)}/result"


def target_status_topic(target_id: str) -> str:
    _validate_target_id(target_id)
    return f"gatekeeper/v1/targets/{target_id}/status"


def target_availability_topic(target_id: str) -> str:
    _validate_target_id(target_id)
    return f"gatekeeper/v1/targets/{target_id}/availability"


def target_ack_topic(target_id: str) -> str:
    _validate_target_id(target_id)
    return f"gatekeeper/v1/targets/{target_id}/command-ack"


def _device() -> dict:
    return {
        "identifiers": [DEVICE_ID],
        "manufacturer": "KS-House",
        "model": "ESP32-C6 Door Controller",
        "name": "Smart Gatekeeper",
    }


def _base_config(name: str, object_id: str) -> dict:
    return {
        "device": _device(),
        "name": name,
        "unique_id": f"{DEVICE_ID}_{object_id}",
    }


def _discovery_publication(component: str, object_id: str, config: dict) -> Publication:
    return Publication(
        topic=f"homeassistant/{component}/{DEVICE_ID}/{object_id}/config",
        payload=json.dumps(
            config, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ),
    )


def _availability_config(target_id: str) -> dict:
    return {
        "availability_topic": bridge_availability_topic(target_id),
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def build_discovery_plan(
    target_id: str, *, allow_manual_remote: bool = False
) -> list[Publication]:
    """Return legacy tombstones followed by secure controls and read-only state."""
    _validate_target_id(target_id)
    status_topic = target_status_topic(target_id)

    # Deleting every historical direct-Target control first makes a partial
    # migration fail closed.  Secure controls are published only afterwards.
    tombstones = []
    for component, object_ids in {
        "button": ("open_gate", "trigger_ota", "reboot"),
        "number": (
            "config_tx_power_num",
            "config_dist_thresh_num",
            "config_duration_num",
            "config_relay_cooldown_num",
        ),
    }.items():
        for object_id in object_ids:
            tombstones.append(
                Publication(
                    topic=(
                        f"homeassistant/{component}/{DEVICE_ID}/"
                        f"{object_id}/config"
                    ),
                    payload="",
                )
            )

    controls = []
    buttons = (
        (
            "open_gate",
            "[Gatekeeper] 출입문 원격 개방",
            "mdi:door-open",
            None,
        ),
        (
            "trigger_ota",
            "[Gatekeeper] 펌웨어 무선 업데이트 (OTA)",
            "mdi:cloud-download",
            "config",
        ),
        (
            "reboot",
            "[Gatekeeper] 장치 재부팅",
            "mdi:restart",
            "config",
        ),
    )
    for object_id, name, icon, entity_category in buttons:
        if object_id == "open_gate" and not allow_manual_remote:
            continue
        config = _base_config(name, object_id)
        config.update(
            {
                **_availability_config(target_id),
                "command_topic": bridge_request_topic(target_id, object_id),
                "icon": icon,
                "payload_press": "PRESS",
                "qos": 1,
                "retain": False,
            }
        )
        if entity_category is not None:
            config["entity_category"] = entity_category
        controls.append(_discovery_publication("button", object_id, config))

    numbers = (
        (
            "config_tx_power_num",
            "[Gatekeeper] BLE Tx Power 설정",
            -6,
            9,
            3,
            "dBm",
            "mdi:bluetooth",
            "{{ value_json.tx_power }}",
            "{{ value | int }}",
        ),
        (
            "config_dist_thresh_num",
            "[Gatekeeper] 초음파 감지 기준 거리",
            20,
            200,
            1,
            "cm",
            "mdi:ruler-square",
            "{{ value_json.distance_threshold_cm }}",
            "{{ value | int }}",
        ),
        (
            "config_duration_num",
            "[Gatekeeper] Pre-arm 유효 시간",
            1,
            60,
            1,
            "s",
            "mdi:timer-sand",
            "{{ (value_json.duration_ms / 1000) | int }}",
            "{{ (value | int) * 1000 }}",
        ),
        (
            "config_relay_cooldown_num",
            "[Gatekeeper] 릴레이 쿨다운 시간",
            1,
            10,
            1,
            "s",
            "mdi:snowflake-alert",
            "{{ (value_json.relay_cooldown_ms / 1000) | int }}",
            "{{ (value | int) * 1000 }}",
        ),
    )
    for (
        object_id,
        name,
        minimum,
        maximum,
        step,
        unit,
        icon,
        value_template,
        command_template,
    ) in numbers:
        config = _base_config(name, object_id)
        config.update(
            {
                **_availability_config(target_id),
                "command_template": command_template,
                "command_topic": bridge_request_topic(target_id, object_id),
                "entity_category": "config",
                "icon": icon,
                "max": maximum,
                "min": minimum,
                "mode": "slider",
                "qos": 1,
                "retain": False,
                "state_topic": status_topic,
                "step": step,
                "unit_of_measurement": unit,
                "value_template": value_template,
            }
        )
        controls.append(_discovery_publication("number", object_id, config))

    read_only = []
    status_sensors = (
        (
            "distance",
            "[Gatekeeper] 초음파 감지 거리 (mm)",
            "{{ value_json.distance_mm }}",
            "mm",
            "mdi:ruler",
            None,
            None,
        ),
        (
            "distance_cm",
            "[Gatekeeper] 초음파 감지 거리 (cm)",
            "{{ value_json.distance_cm }}",
            "cm",
            "mdi:ruler-square",
            None,
            None,
        ),
        (
            "state",
            "[Gatekeeper] 게이트키퍼 동작 상태",
            "{{ value_json.state }}",
            None,
            "mdi:state-machine",
            None,
            None,
        ),
        (
            "ip",
            "[Gatekeeper] IP 주소",
            "{{ value_json.ip }}",
            None,
            "mdi:ip-network",
            None,
            None,
        ),
        (
            "arm_remaining_s",
            "[Gatekeeper] Pre-arm 잔여 시간",
            "{{ value_json.arm_remaining_s }}",
            "s",
            "mdi:timer-outline",
            None,
            None,
        ),
        (
            "wifi_rssi",
            "[Gatekeeper] Wi-Fi 신호 강도 (RSSI)",
            "{{ value_json.wifi_rssi }}",
            "dBm",
            "mdi:wifi",
            "signal_strength",
            "diagnostic",
        ),
        (
            "free_heap",
            "[Gatekeeper] Free Heap 메모리",
            "{{ value_json.free_heap }}",
            "B",
            "mdi:memory",
            None,
            "diagnostic",
        ),
        (
            "uptime_s",
            "[Gatekeeper] 시스템 가동 시간",
            "{{ value_json.uptime_s }}",
            "s",
            "mdi:clock-outline",
            "duration",
            "diagnostic",
        ),
        (
            "firmware",
            "[Gatekeeper] 펌웨어 버전",
            "{{ value_json.firmware }}",
            None,
            "mdi:information-outline",
            None,
            "diagnostic",
        ),
    )
    for (
        object_id,
        name,
        value_template,
        unit,
        icon,
        device_class,
        entity_category,
    ) in status_sensors:
        config = _base_config(name, object_id)
        config.update(
            {
                "expire_after": 30,
                "icon": icon,
                "state_topic": status_topic,
                "value_template": value_template,
            }
        )
        if unit is not None:
            config["unit_of_measurement"] = unit
        if device_class is not None:
            config["device_class"] = device_class
        if entity_category is not None:
            config["entity_category"] = entity_category
        read_only.append(_discovery_publication("sensor", object_id, config))

    binary_sensors = (
        (
            "door_binary",
            "[Gatekeeper] 도어 개방 여부",
            "{% if value_json.state == 'RELAY_HOLD' %}ON{% else %}OFF{% endif %}",
            "door",
            None,
        ),
        (
            "pre_armed",
            "[Gatekeeper] Pre-arm 활성화 상태",
            "{% if value_json.is_armed %}ON{% else %}OFF{% endif %}",
            "lock",
            "mdi:shield-check",
        ),
    )
    for object_id, name, value_template, device_class, icon in binary_sensors:
        config = _base_config(name, object_id)
        config.update(
            {
                "device_class": device_class,
                "expire_after": 30,
                "payload_off": "OFF",
                "payload_on": "ON",
                "state_topic": status_topic,
                "value_template": value_template,
            }
        )
        if icon is not None:
            config["icon"] = icon
        read_only.append(_discovery_publication("binary_sensor", object_id, config))

    config_sensors = (
        (
            "cfg_tx_power",
            "[Gatekeeper] [설정] BLE Tx Power",
            "{{ value_json.tx_power }}",
            "dBm",
            "mdi:bluetooth-settings",
        ),
        (
            "cfg_distance_thresh",
            "[Gatekeeper] [설정] 초음파 감지 기준 거리",
            "{{ value_json.distance_threshold_cm }}",
            "cm",
            "mdi:tune-vertical",
        ),
        (
            "cfg_prearm_duration",
            "[Gatekeeper] [설정] Pre-arm 유효 시간",
            "{{ (value_json.duration_ms / 1000) | int }}",
            "s",
            "mdi:clock-edit-outline",
        ),
        (
            "cfg_relay_cooldown",
            "[Gatekeeper] [설정] 릴레이 쿨다운 시간",
            "{{ (value_json.relay_cooldown_ms / 1000) | int }}",
            "s",
            "mdi:timer-cog-outline",
        ),
    )
    for object_id, name, value_template, unit, icon in config_sensors:
        config = _base_config(name, object_id)
        config.update(
            {
                "entity_category": "diagnostic",
                "expire_after": 30,
                "icon": icon,
                "state_topic": status_topic,
                "unit_of_measurement": unit,
                "value_template": value_template,
            }
        )
        read_only.append(_discovery_publication("sensor", object_id, config))

    return tombstones + controls + read_only


class HomeAssistantCommandBridge:
    """Validate HA ingress and bind accepted requests to fresh Target status."""

    def __init__(
        self,
        target_id: str,
        *,
        allow_manual_remote: bool = False,
        status_max_age_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    ):
        _validate_target_id(target_id)
        if not 1.0 <= status_max_age_seconds <= 60.0:
            raise ValueError("status max age must be 1..60 seconds")
        self.target_id = target_id
        self.allow_manual_remote = allow_manual_remote
        self.status_max_age_seconds = status_max_age_seconds
        self._clock = clock
        self._token_factory = token_factory
        self._lock = threading.Lock()
        self._boot_id: Optional[str] = None
        self._status_seen_at: Optional[float] = None
        self._last_action_at: dict[str, float] = {}
        self._last_fingerprint: Optional[tuple[str, bytes, float]] = None
        self._pending: dict[str, tuple[str, str, str]] = {}

    def reset_transport(self) -> None:
        with self._lock:
            self._boot_id = None
            self._status_seen_at = None
            self._last_fingerprint = None
            self._pending.clear()

    def note_status(self, topic: str, payload: bytes) -> bool:
        if topic != target_status_topic(self.target_id):
            return False
        document = self._decode_document(payload, 4096)
        if document is None:
            return False
        target_id = document.get("target_id")
        boot_id = document.get("boot_id")
        if (
            not isinstance(target_id, str)
            or not secrets.compare_digest(target_id, self.target_id)
            or not isinstance(boot_id, str)
            or BOOT_ID_PATTERN.fullmatch(boot_id) is None
        ):
            return False
        with self._lock:
            self._boot_id = boot_id
            self._status_seen_at = self._clock()
        return True

    def note_target_availability(self, topic: str, payload: bytes) -> Optional[str]:
        if topic != target_availability_topic(self.target_id):
            return None
        document = self._decode_document(payload, 512)
        if document is None:
            return None
        target_id = document.get("target_id")
        state = document.get("status")
        if (
            not isinstance(target_id, str)
            or not secrets.compare_digest(target_id, self.target_id)
            or state not in ("online", "offline")
        ):
            return None
        if state == "offline":
            with self._lock:
                self._boot_id = None
                self._status_seen_at = None
        return state

    def live_boot_id(self) -> Optional[str]:
        with self._lock:
            return self._live_boot_locked(self._clock())

    def is_live(self) -> bool:
        return self.live_boot_id() is not None

    def accept_request(
        self,
        topic: str,
        payload: bytes,
        *,
        retained: bool = False,
        duplicate: bool = False,
    ) -> BridgeDecision:
        if retained:
            return BridgeDecision(False, "retained_request")
        if duplicate:
            return BridgeDecision(False, "qos_duplicate")
        prefix = bridge_request_topic(self.target_id, "+")[:-1]
        if not topic.startswith(prefix):
            return BridgeDecision(False, "outside_ingress_namespace")
        object_id = topic[len(prefix) :]
        definition = _CONTROLS.get(object_id)
        if definition is None or "/" in object_id:
            return BridgeDecision(False, "unsupported_control")
        if definition.action == "manual_remote" and not self.allow_manual_remote:
            return BridgeDecision(False, "manual_remote_disabled")
        value = self._parse_value(definition, payload)
        if value is None:
            return BridgeDecision(False, "invalid_payload")

        now = self._clock()
        with self._lock:
            boot_id = self._live_boot_locked(now)
            if boot_id is None:
                return BridgeDecision(False, "target_status_stale")
            if self._last_fingerprint is not None:
                last_topic, last_payload, last_time = self._last_fingerprint
                if (
                    secrets.compare_digest(last_topic, topic)
                    and secrets.compare_digest(last_payload, bytes(payload))
                    and now - last_time < 2.0
                ):
                    return BridgeDecision(False, "duplicate_window")
            last_action_at = self._last_action_at.get(definition.action)
            if (
                last_action_at is not None
                and now - last_action_at < definition.minimum_interval_seconds
            ):
                return BridgeDecision(False, "rate_limited")
            session_id = self._token_factory()
            nonce = self._token_factory()
            if (
                not isinstance(session_id, str)
                or not isinstance(nonce, str)
                or not re.fullmatch(r"[0-9a-f]{32}", session_id)
                or not re.fullmatch(r"[0-9a-f]{32}", nonce)
            ):
                return BridgeDecision(False, "token_generation_failed")
            self._last_fingerprint = (topic, bytes(payload), now)
            self._last_action_at[definition.action] = now

        return BridgeDecision(
            True,
            "accepted",
            BridgeCommand(
                object_id=object_id,
                action=definition.action,
                value=value,
                expected_boot_id=boot_id,
                session_id=session_id,
                nonce=nonce,
            ),
        )

    def note_published(self, command: BridgeCommand) -> None:
        with self._lock:
            self._pending[command.session_id] = (
                command.action,
                command.nonce,
                command.expected_boot_id,
            )
            if len(self._pending) > 32:
                oldest = next(iter(self._pending))
                self._pending.pop(oldest, None)

    def note_publish_failed(self, command: BridgeCommand) -> None:
        """Release the synchronous ingress reservation after broker failure."""
        with self._lock:
            self._last_action_at.pop(command.action, None)
            self._last_fingerprint = None

    def accept_ack(self, topic: str, payload: bytes) -> AckDecision:
        if topic != target_ack_topic(self.target_id):
            return AckDecision(False, "outside_ack_namespace")
        document = self._decode_document(payload, 1024)
        if document is None:
            return AckDecision(False, "invalid_ack")
        target_id = document.get("target_id")
        session_id = document.get("session_id")
        nonce = document.get("nonce")
        result = document.get("result")
        if (
            not isinstance(target_id, str)
            or not secrets.compare_digest(target_id, self.target_id)
            or not isinstance(session_id, str)
            or not isinstance(nonce, str)
            or isinstance(result, bool)
            or not isinstance(result, int)
            or not 0 <= result <= 13
        ):
            return AckDecision(False, "invalid_ack")
        with self._lock:
            pending = self._pending.get(session_id)
            live_boot_id = self._live_boot_locked(self._clock())
            if (
                pending is None
                or live_boot_id is None
                or not secrets.compare_digest(pending[1], nonce)
                or not secrets.compare_digest(pending[2], live_boot_id)
            ):
                return AckDecision(False, "unmatched_ack")
            self._pending.pop(session_id, None)
        return AckDecision(
            True,
            "target_accepted" if result == 0 else "target_rejected",
            action=pending[0],
            session_id=session_id,
            result_code=result,
        )

    def _live_boot_locked(self, now: float) -> Optional[str]:
        if (
            self._boot_id is None
            or self._status_seen_at is None
            or now < self._status_seen_at
            or now - self._status_seen_at > self.status_max_age_seconds
        ):
            return None
        return self._boot_id

    @staticmethod
    def _decode_document(payload: bytes, maximum: int) -> Optional[dict]:
        if not isinstance(payload, (bytes, bytearray)) or not 0 < len(payload) <= maximum:
            return None
        try:
            document = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return document if isinstance(document, dict) else None

    @staticmethod
    def _parse_value(
        definition: _ControlDefinition, payload: bytes
    ) -> Optional[int]:
        if not isinstance(payload, (bytes, bytearray)) or not 0 < len(payload) <= 32:
            return None
        try:
            raw = bytes(payload).decode("ascii")
        except UnicodeDecodeError:
            return None
        if definition.minimum is None:
            return 0 if raw == "PRESS" else None
        if INTEGER_PATTERN.fullmatch(raw) is None:
            return None
        value = int(raw)
        if not definition.minimum <= value <= definition.maximum:
            return None
        return value
