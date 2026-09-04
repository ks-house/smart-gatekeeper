from __future__ import annotations

import json
import unittest

from backend.app.home_assistant_bridge import (
    HomeAssistantCommandBridge,
    bridge_availability_topic,
    bridge_connectivity_diagnostic_payload,
    bridge_connectivity_diagnostic_topic,
    bridge_request_topic,
    bridge_verified_status_topic,
    build_discovery_plan,
    target_ack_topic,
    target_availability_topic,
    target_status_topic,
)


TARGET = "target-a"
BOOT = "1" * 32


class MutableClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class TokenFactory:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"{self.value:032x}"


class HomeAssistantCommandBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.bridge = HomeAssistantCommandBridge(
            TARGET,
            status_max_age_seconds=15,
            clock=self.clock,
            token_factory=TokenFactory(),
        )

    def note_status(self, boot_id: str = BOOT) -> bool:
        return self.bridge.note_status(
            target_status_topic(TARGET),
            json.dumps({"target_id": TARGET, "boot_id": boot_id}).encode(),
        )

    def test_discovery_controls_use_only_backend_ingress(self) -> None:
        default_plan = build_discovery_plan(TARGET)
        enabled_plan = build_discovery_plan(TARGET, allow_manual_remote=True)
        self.assertEqual(31, len(default_plan))
        self.assertEqual(32, len(enabled_plan))
        self.assertTrue(all(not item.payload for item in enabled_plan[:7]))

        updates = [item for item in enabled_plan if item.payload]
        controls = [
            item
            for item in updates
            if "/button/" in item.topic or "/number/" in item.topic
        ]
        read_only = [item for item in updates if item not in controls]
        self.assertEqual(7, len(controls))
        self.assertEqual(18, len(read_only))
        for publication in controls:
            config = json.loads(publication.payload)
            self.assertTrue(
                config["command_topic"].startswith(
                    f"gatekeeper/v1/ha-bridge/{TARGET}/request/"
                )
            )
            self.assertNotIn(f"gatekeeper/v1/targets/{TARGET}/command", publication.payload)
            self.assertEqual(bridge_availability_topic(TARGET), config["availability_topic"])
            self.assertFalse(config["retain"])
            self.assertEqual(1, config["qos"])
        connectivity = next(
            item
            for item in read_only
            if item.topic.endswith("/connectivity/config")
        )
        connectivity_config = json.loads(connectivity.payload)
        self.assertEqual(
            bridge_availability_topic(TARGET),
            connectivity_config["state_topic"],
        )
        self.assertEqual("connectivity", connectivity_config["device_class"])
        self.assertEqual("online", connectivity_config["payload_on"])
        self.assertEqual("offline", connectivity_config["payload_off"])
        self.assertEqual(
            bridge_connectivity_diagnostic_topic(TARGET),
            connectivity_config["json_attributes_topic"],
        )
        self.assertNotIn("availability_topic", connectivity_config)
        self.assertNotIn("entity_category", connectivity_config)
        self.assertNotIn("expire_after", connectivity_config)

        relay_status = next(
            item
            for item in read_only
            if item.topic.endswith("/door_binary/config")
        )
        relay_status_config = json.loads(relay_status.payload)
        self.assertEqual(
            "homeassistant/binary_sensor/smart_gatekeeper_01/door_binary/config",
            relay_status.topic,
        )
        self.assertEqual(
            "smart_gatekeeper_01_door_binary",
            relay_status_config["unique_id"],
        )
        self.assertEqual(
            "[Gatekeeper] 릴레이 구동 상태",
            relay_status_config["name"],
        )
        self.assertEqual(
            "{% if value_json.state == 'RELAY_HOLD' %}ON{% else %}OFF{% endif %}",
            relay_status_config["value_template"],
        )
        self.assertNotIn("device_class", relay_status_config)

        last_access = next(
            item
            for item in read_only
            if item.topic.endswith("/last_access_event/config")
        )
        last_access_config = json.loads(last_access.payload)
        self.assertEqual(
            "[Gatekeeper] 최근 출입 결과", last_access_config["name"]
        )
        self.assertIn(
            "value_json.last_access_event_marker",
            last_access_config["value_template"],
        )
        self.assertIn(
            "value_json.last_access_result",
            last_access_config["value_template"],
        )
        terminal_event = next(
            item
            for item in read_only
            if item.topic.endswith("/access_terminal_event/config")
        )
        terminal_event_config = json.loads(terminal_event.payload)
        self.assertEqual(
            "homeassistant/event/smart_gatekeeper_01/access_terminal_event/config",
            terminal_event.topic,
        )
        self.assertEqual(
            f"gatekeeper/v1/ha-bridge/{TARGET}/access-event",
            terminal_event_config["state_topic"],
        )
        self.assertEqual(
            ["succeeded", "terminated"],
            terminal_event_config["event_types"],
        )
        self.assertEqual(1, terminal_event_config["qos"])

        verified_access_ids = {
            "state",
            "last_access_event",
            "door_binary",
            "pre_armed",
        }
        live_access_ids = {"state", "door_binary", "pre_armed"}
        for publication in read_only:
            object_id = publication.topic.split("/")[-2]
            config = json.loads(publication.payload)
            if object_id in verified_access_ids:
                self.assertNotIn("expire_after", config)
            elif object_id not in {"connectivity", "access_terminal_event"}:
                self.assertEqual(30, config["expire_after"])
            if object_id in live_access_ids:
                self.assertEqual(
                    bridge_availability_topic(TARGET),
                    config["availability_topic"],
                )
            elif object_id not in {
                "connectivity",
            }:
                self.assertNotIn("availability_topic", config)

        for publication in read_only:
            config = json.loads(publication.payload)
            if publication is not connectivity:
                object_id = publication.topic.split("/")[-2]
                self.assertEqual(
                    (
                        bridge_verified_status_topic(TARGET)
                        if object_id in verified_access_ids
                        else (
                            f"gatekeeper/v1/ha-bridge/{TARGET}/access-event"
                            if object_id == "access_terminal_event"
                            else target_status_topic(TARGET)
                        )
                    ),
                    config["state_topic"],
                )
            self.assertNotIn("command_topic", config)

    def test_connectivity_diagnostic_is_bounded_backend_evidence(self) -> None:
        payload = bridge_connectivity_diagnostic_payload(
            "offline", "SIGNED_STATUS_STALE"
        )
        self.assertEqual(
            {
                "diagnostic_scope": "last_completed_backend_observation",
                "last_signed_status_observation": "SIGNED_STATUS_STALE",
                "schema_version": 1,
            },
            json.loads(payload),
        )
        with self.assertRaisesRegex(ValueError, "invalid"):
            bridge_connectivity_diagnostic_payload("offline", "TARGET_CRASHED")

    def test_request_requires_fresh_authenticated_status_and_safe_payload(self) -> None:
        topic = bridge_request_topic(TARGET, "config_duration_num")
        self.assertEqual(
            "target_status_stale",
            self.bridge.accept_request(topic, b"5000").reason,
        )
        self.assertTrue(self.note_status())
        self.assertEqual(
            "retained_request",
            self.bridge.accept_request(topic, b"5000", retained=True).reason,
        )
        self.assertEqual(
            "qos_duplicate",
            self.bridge.accept_request(topic, b"5000", duplicate=True).reason,
        )
        for invalid in (b"999", b"60001", b"5.0", b" 5000", b"5000 "):
            with self.subTest(payload=invalid):
                self.assertEqual(
                    "invalid_payload",
                    self.bridge.accept_request(topic, invalid).reason,
                )

        accepted = self.bridge.accept_request(topic, b"5000")
        self.assertTrue(accepted.accepted)
        self.assertEqual("set_duration", accepted.command.action)
        self.assertEqual(5000, accepted.command.value)
        self.assertEqual(BOOT, accepted.command.expected_boot_id)
        self.assertRegex(accepted.command.session_id, r"^[0-9a-f]{32}$")
        self.assertRegex(accepted.command.nonce, r"^[0-9a-f]{32}$")
        self.assertEqual(
            "duplicate_window",
            self.bridge.accept_request(topic, b"5000").reason,
        )

        self.clock.value += 16
        self.assertEqual(
            "target_status_stale",
            self.bridge.accept_request(topic, b"6000").reason,
        )

    def test_live_gate_state_requires_fresh_valid_status(self) -> None:
        payload = json.dumps(
            {"target_id": TARGET, "boot_id": BOOT, "state": "IDLE"}
        ).encode()
        self.assertTrue(
            self.bridge.note_status(target_status_topic(TARGET), payload)
        )
        self.assertEqual("IDLE", self.bridge.live_gate_state())
        self.clock.value += 16
        self.assertIsNone(self.bridge.live_gate_state())
        invalid = json.dumps(
            {"target_id": TARGET, "boot_id": BOOT, "state": "OPEN"}
        ).encode()
        self.assertFalse(
            self.bridge.note_status(target_status_topic(TARGET), invalid)
        )

    def test_unsigned_availability_is_advisory_and_cannot_clear_status(self) -> None:
        self.assertTrue(self.note_status())
        advisory = json.dumps(
            {"target_id": TARGET, "status": "offline"}
        ).encode()
        self.assertEqual(
            "offline",
            self.bridge.note_target_availability(
                target_availability_topic(TARGET), advisory
            ),
        )
        self.assertEqual(BOOT, self.bridge.live_boot_id())

    def test_manual_remote_is_independently_disabled(self) -> None:
        self.assertTrue(self.note_status())
        topic = bridge_request_topic(TARGET, "open_gate")
        self.assertEqual(
            "manual_remote_disabled",
            self.bridge.accept_request(topic, b"PRESS").reason,
        )
        enabled = HomeAssistantCommandBridge(
            TARGET,
            allow_manual_remote=True,
            clock=self.clock,
            token_factory=TokenFactory(),
        )
        self.assertTrue(
            enabled.note_status(
                target_status_topic(TARGET),
                json.dumps({"target_id": TARGET, "boot_id": BOOT}).encode(),
            )
        )
        self.assertTrue(enabled.accept_request(topic, b"PRESS").accepted)

    def test_broker_publish_failure_releases_retry_reservation(self) -> None:
        self.assertTrue(self.note_status())
        topic = bridge_request_topic(TARGET, "trigger_ota")
        first = self.bridge.accept_request(topic, b"PRESS")
        self.assertTrue(first.accepted)
        self.bridge.note_publish_failed(first.command)
        retry = self.bridge.accept_request(topic, b"PRESS")
        self.assertTrue(retry.accepted)

    def test_ack_must_match_published_session_nonce_and_live_boot(self) -> None:
        self.assertTrue(self.note_status())
        request = self.bridge.accept_request(
            bridge_request_topic(TARGET, "reboot"), b"PRESS"
        )
        command = request.command
        ack_payload = json.dumps(
            {
                "target_id": TARGET,
                "session_id": command.session_id,
                "nonce": command.nonce,
                "result": 0,
            }
        ).encode()
        self.assertEqual(
            "unmatched_ack",
            self.bridge.accept_ack(target_ack_topic(TARGET), ack_payload).reason,
        )
        self.bridge.note_published(command)
        wrong_nonce = json.dumps(
            {
                "target_id": TARGET,
                "session_id": command.session_id,
                "nonce": "f" * 32,
                "result": 0,
            }
        ).encode()
        self.assertEqual(
            "unmatched_ack",
            self.bridge.accept_ack(target_ack_topic(TARGET), wrong_nonce).reason,
        )
        accepted = self.bridge.accept_ack(target_ack_topic(TARGET), ack_payload)
        self.assertTrue(accepted.accepted)
        self.assertEqual("target_accepted", accepted.reason)
        self.assertEqual(0, accepted.result_code)
        self.assertEqual(
            "unmatched_ack",
            self.bridge.accept_ack(target_ack_topic(TARGET), ack_payload).reason,
        )

    def test_ack_is_rejected_after_status_expires(self) -> None:
        self.assertTrue(self.note_status())
        request = self.bridge.accept_request(
            bridge_request_topic(TARGET, "trigger_ota"), b"PRESS"
        )
        self.bridge.note_published(request.command)
        self.clock.value += 16
        ack = json.dumps(
            {
                "target_id": TARGET,
                "session_id": request.command.session_id,
                "nonce": request.command.nonce,
                "result": 0,
            }
        ).encode()
        self.assertEqual(
            "unmatched_ack",
            self.bridge.accept_ack(target_ack_topic(TARGET), ack).reason,
        )


if __name__ == "__main__":
    unittest.main()
