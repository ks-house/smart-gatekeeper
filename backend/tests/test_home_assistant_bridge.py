from __future__ import annotations

import json
import unittest

from backend.app.home_assistant_bridge import (
    HomeAssistantCommandBridge,
    bridge_availability_topic,
    bridge_request_topic,
    build_discovery_plan,
    target_ack_topic,
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
        self.assertEqual(28, len(default_plan))
        self.assertEqual(29, len(enabled_plan))
        self.assertTrue(all(not item.payload for item in enabled_plan[:7]))

        updates = [item for item in enabled_plan if item.payload]
        controls = [
            item
            for item in updates
            if "/button/" in item.topic or "/number/" in item.topic
        ]
        read_only = [item for item in updates if item not in controls]
        self.assertEqual(7, len(controls))
        self.assertEqual(15, len(read_only))
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
        for publication in read_only:
            config = json.loads(publication.payload)
            self.assertEqual(target_status_topic(TARGET), config["state_topic"])
            self.assertNotIn("command_topic", config)

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
