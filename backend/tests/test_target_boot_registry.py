from __future__ import annotations

import json
import ssl
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app import main
from backend.app.target_boot_registry import TargetBootRegistry


TARGET = "target-a"
BOOT_1 = "1" * 32
BOOT_2 = "2" * 32


def connection_with(row):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    return connection, cursor


class TargetBootRegistryTest(unittest.TestCase):
    def test_authenticated_topic_refresh_is_atomic_and_monotonic(self) -> None:
        connection, cursor = connection_with(None)
        registry = TargetBootRegistry(lambda: connection, clock=lambda: 123)
        payload = json.dumps(
            {
                "target_id": TARGET,
                "boot_id": BOOT_1,
                "boot_count": 7,
                "firmware": "2.2.0",
                "reset_reason": "power_on",
            }
        ).encode()
        self.assertTrue(
            registry.refresh_from_authenticated_topic(
                f"gatekeeper/v1/targets/{TARGET}/boot", payload
            )
        )
        connection.begin.assert_called_once()
        self.assertIn("INSERT INTO target_boot_state", cursor.execute.call_args_list[1].args[0])
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

        current_connection, current_cursor = connection_with(
            {"boot_id": BOOT_1, "boot_count": 7}
        )
        current_registry = TargetBootRegistry(lambda: current_connection)
        self.assertTrue(
            current_registry.refresh_from_authenticated_topic(
                f"gatekeeper/v1/targets/{TARGET}/boot", payload
            )
        )
        self.assertEqual(1, current_cursor.execute.call_count)
        current_connection.commit.assert_called_once()

        newer_connection, newer_cursor = connection_with(
            {"boot_id": BOOT_1, "boot_count": 7}
        )
        newer_registry = TargetBootRegistry(lambda: newer_connection, clock=lambda: 456)
        newer_payload = json.dumps(
            {"target_id": TARGET, "boot_id": BOOT_2, "boot_count": 8}
        ).encode()
        self.assertTrue(
            newer_registry.refresh_from_authenticated_topic(
                f"gatekeeper/v1/targets/{TARGET}/boot", newer_payload
            )
        )
        self.assertIn("UPDATE target_boot_state", newer_cursor.execute.call_args_list[1].args[0])
        self.assertEqual((BOOT_2, 8, 456, TARGET), newer_cursor.execute.call_args_list[1].args[1])
        newer_connection.commit.assert_called_once()

    def test_forged_cross_target_stale_and_rollback_refreshes_reject(self) -> None:
        factory = MagicMock()
        registry = TargetBootRegistry(factory)
        for name, document in (
            (
                "cross-target",
                {"target_id": "target-b", "boot_id": BOOT_2, "boot_count": 9},
            ),
            (
                "non-string-target",
                {"target_id": 123, "boot_id": BOOT_2, "boot_count": 9},
            ),
            (
                "counter-overflow",
                {
                    "target_id": TARGET,
                    "boot_id": BOOT_2,
                    "boot_count": 0x100000000,
                },
            ),
        ):
            with self.subTest(name=name):
                self.assertFalse(
                    registry.refresh_from_authenticated_topic(
                        f"gatekeeper/v1/targets/{TARGET}/boot",
                        json.dumps(document).encode(),
                    )
                )
        factory.assert_not_called()

        for name, count, boot_id in (
            ("rollback", 6, BOOT_2),
            ("same-count-replacement", 7, BOOT_2),
        ):
            with self.subTest(name=name):
                connection, _ = connection_with(
                    {"boot_id": BOOT_1, "boot_count": 7}
                )
                candidate = TargetBootRegistry(lambda: connection)
                payload = json.dumps(
                    {"target_id": TARGET, "boot_id": boot_id, "boot_count": count}
                ).encode()
                self.assertFalse(
                    candidate.refresh_from_authenticated_topic(
                        f"gatekeeper/v1/targets/{TARGET}/boot", payload
                    )
                )
                connection.rollback.assert_called_once()
                connection.commit.assert_not_called()

    def test_current_boot_lookup_and_reboot_command_recovery(self) -> None:
        connection, _ = connection_with({"boot_id": BOOT_2})
        registry = TargetBootRegistry(lambda: connection)
        self.assertEqual(BOOT_2, registry.current_boot_id(TARGET))

        with tempfile.NamedTemporaryFile() as ca, ExitStack() as stack:
            values = {
                "MQTT_HOST": "mqtt.example.test",
                "MQTT_PORT": 8883,
                "MQTT_USER": "gatekeeper-backend",
                "MQTT_PASSWORD": "unique-backend-password",
                "MQTT_CA_FILE": ca.name,
                "COMMAND_TARGET_ID": TARGET,
                "COMMAND_TENANT_ID": "tenant-a",
                "COMMAND_DOOR_ID": "door-a",
                "COMMAND_SIGNING_KEY_ID": 7,
                "COMMAND_SIGNING_PRIVATE_SCALAR_HEX": "2" * 64,
            }
            stack.enter_context(patch.multiple(main, **values))
            stack.enter_context(
                patch.object(main._target_boot_registry, "current_boot_id", return_value=BOOT_2)
            )
            publish = stack.enter_context(patch.object(main, "_publish_mqtt_msg", return_value=True))
            self.assertTrue(main._signed_target_command("arm"))
            envelope = json.loads(publish.call_args.args[1])
            self.assertEqual(BOOT_2, envelope["boot_id"])

    def test_subscriber_uses_verified_backend_identity_and_authenticated_topic(self) -> None:
        with tempfile.NamedTemporaryFile() as ca, ExitStack() as stack:
            values = {
                "HAS_PAHO_MQTT": True,
                "MQTT_HOST": "mqtt.example.test",
                "MQTT_PORT": 8883,
                "MQTT_USER": "gatekeeper-backend",
                "MQTT_PASSWORD": "unique-backend-password",
                "MQTT_CA_FILE": ca.name,
                "COMMAND_TARGET_ID": TARGET,
                "COMMAND_TENANT_ID": "tenant-a",
                "COMMAND_DOOR_ID": "door-a",
                "COMMAND_SIGNING_KEY_ID": 7,
                "COMMAND_SIGNING_PRIVATE_SCALAR_HEX": "2" * 64,
            }
            stack.enter_context(patch.multiple(main, **values))
            client = MagicMock()
            stack.enter_context(patch.object(main, "_create_mqtt_client", return_value=client))
            refresh = stack.enter_context(
                patch.object(
                    main._target_boot_registry,
                    "refresh_from_authenticated_topic",
                    return_value=True,
                )
            )
            self.assertIs(client, main._start_target_boot_subscriber())
            client.username_pw_set.assert_called_once_with(
                "gatekeeper-backend", "unique-backend-password"
            )
            self.assertEqual(ssl.CERT_REQUIRED, client.tls_set.call_args.kwargs["cert_reqs"])
            client.tls_insecure_set.assert_called_once_with(False)
            client.connect.assert_called_once_with("mqtt.example.test", 8883, keepalive=30)
            client.loop_start.assert_called_once()

            client.on_connect(client, None, None, 0)
            client.subscribe.assert_called_once_with(
                "gatekeeper/v1/targets/+/boot", qos=1
            )
            payload = json.dumps(
                {"target_id": TARGET, "boot_id": BOOT_2, "boot_count": 8}
            ).encode()
            message = MagicMock(topic=f"gatekeeper/v1/targets/{TARGET}/boot", payload=payload)
            client.on_message(client, None, message)
            refresh.assert_called_once_with(message.topic, payload)

    def test_each_missing_or_invalid_provision_blocks_before_broker_client(self) -> None:
        with tempfile.NamedTemporaryFile() as ca:
            valid = {
                "MQTT_HOST": "mqtt.example.test",
                "MQTT_PORT": 8883,
                "MQTT_USER": "gatekeeper-backend",
                "MQTT_PASSWORD": "unique-backend-password",
                "MQTT_CA_FILE": ca.name,
                "COMMAND_TARGET_ID": TARGET,
                "COMMAND_TENANT_ID": "tenant-a",
                "COMMAND_DOOR_ID": "door-a",
                "COMMAND_SIGNING_KEY_ID": 7,
                "COMMAND_SIGNING_PRIVATE_SCALAR_HEX": "2" * 64,
            }
            mutations = {
                "host": {"MQTT_HOST": ""},
                "plaintext-port": {"MQTT_PORT": 1883},
                "zero-port": {"MQTT_PORT": 0},
                "out-of-range-port": {"MQTT_PORT": 65536},
                "broker-user": {"MQTT_USER": ""},
                "target-as-broker-user": {"MQTT_USER": TARGET},
                "broker-password": {"MQTT_PASSWORD": ""},
                "ca-file": {"MQTT_CA_FILE": ca.name + ".missing"},
                "target": {"COMMAND_TARGET_ID": ""},
                "tenant": {"COMMAND_TENANT_ID": ""},
                "door": {"COMMAND_DOOR_ID": ""},
                "key-id": {"COMMAND_SIGNING_KEY_ID": 0},
                "scalar-empty": {"COMMAND_SIGNING_PRIVATE_SCALAR_HEX": ""},
                "scalar-zero": {"COMMAND_SIGNING_PRIVATE_SCALAR_HEX": "0" * 64},
                "scalar-malformed": {"COMMAND_SIGNING_PRIVATE_SCALAR_HEX": "z" * 64},
                "scalar-out-of-range": {"COMMAND_SIGNING_PRIVATE_SCALAR_HEX": "f" * 64},
            }
            for name, mutation in mutations.items():
                with self.subTest(name=name), ExitStack() as stack:
                    stack.enter_context(patch.multiple(main, **dict(valid, **mutation)))
                    client = stack.enter_context(patch.object(main, "_create_mqtt_client"))
                    boot = stack.enter_context(
                        patch.object(main._target_boot_registry, "current_boot_id")
                    )
                    self.assertFalse(main._signed_target_command("arm"))
                    client.assert_not_called()
                    boot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
