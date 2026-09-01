from __future__ import annotations

import json
import ssl
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.app import main
from backend.app.target_boot_registry import BootRefreshOutcome, TargetBootRegistry


TARGET = "target-a"
BOOT_1 = "1" * 32
BOOT_2 = "2" * 32
EVENT_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
SOURCE_REF = "target_0123456789abcdef"


def canonical_event_payload(
    *,
    event_code="ACCESS_PROOF_VERIFIED",
    stage="PROOF",
    outcome="SUCCEEDED",
    reason_code="PROOF_VALID",
    sequence=7,
    attributes=None,
):
    return json.dumps(
        {
            "schema_version": "1.0",
            "event_id": EVENT_ID,
            "session_id": SESSION_ID,
            "session_kind": "access",
            "source_component": "target",
            "source_instance_id": SOURCE_REF,
            "source_boot_id": BOOT_1,
            "sequence": sequence,
            "attempt": 1,
            "event_code": event_code,
            "stage": stage,
            "outcome": outcome,
            "reason_code": reason_code,
            "clock": {
                "wall_time": None,
                "monotonic_ms": 12345,
                "quality": "UNSYNCED",
            },
            "target": {"target_ref": SOURCE_REF, "boot_id": BOOT_1},
            "causation_event_id": None,
            "attributes": attributes or {
                "path": "local_gatt",
                "transport": "ble_gatt",
            },
        },
        separators=(",", ":"),
    ).encode()


def connection_with(row):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    return connection, cursor


class TargetBootRegistryTest(unittest.TestCase):
    def test_canonical_target_access_contract_matches_authoritative_catalog(self) -> None:
        catalog = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "observability"
                / "event_codes_v1.json"
            ).read_text(encoding="utf-8")
        )["event_codes"]
        for event_code, (stage, outcomes, reasons) in (
            main._CANONICAL_TARGET_ACCESS_CODES.items()
        ):
            with self.subTest(event_code=event_code):
                authoritative = catalog[event_code]
                self.assertEqual("access", authoritative["session_kind"])
                self.assertEqual(stage, authoritative["stage"])
                self.assertEqual(outcomes, set(authoritative["allowed_outcomes"]))
                self.assertEqual(reasons, set(authoritative["allowed_reason_codes"]))

    def test_canonical_target_access_parser_is_strict_and_privacy_safe(self) -> None:
        parsed = main._parse_canonical_target_access_event(
            canonical_event_payload(
                event_code="ACCESS_SENSOR_DETECTED",
                stage="SENSOR",
                reason_code="SENSOR_THRESHOLD_MET",
                attributes={
                    "path": "local_gatt",
                    "transport": "ble_gatt",
                    "distance_mm": 0,
                },
            )
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(0, parsed["distance_mm"])
        self.assertEqual("ACCESS_SENSOR_DETECTED", parsed["event_code"])

        malformed = json.loads(canonical_event_payload())
        malformed["stage"] = "RELAY_ON"
        self.assertIsNone(
            main._parse_canonical_target_access_event(json.dumps(malformed).encode())
        )
        malformed = json.loads(canonical_event_payload())
        malformed["proof"] = "must-never-be-stored"
        self.assertIsNone(
            main._parse_canonical_target_access_event(json.dumps(malformed).encode())
        )
        too_far = canonical_event_payload(
            event_code="ACCESS_SENSOR_DETECTED",
            stage="SENSOR",
            reason_code="SENSOR_THRESHOLD_MET",
            attributes={
                "path": "local_gatt",
                "transport": "ble_gatt",
                "distance_mm": 10001,
            },
        )
        self.assertIsNone(main._parse_canonical_target_access_event(too_far))
        duplicate_key = canonical_event_payload().replace(
            b'"schema_version":"1.0",',
            b'"schema_version":"1.0","schema_version":"1.0",',
        )
        self.assertIsNone(main._parse_canonical_target_access_event(duplicate_key))

    def test_canonical_target_access_persistence_binds_topic_and_deduplicates(self) -> None:
        topic = main._canonical_target_event_topic(TARGET)
        payload = canonical_event_payload()
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        with patch.multiple(
            main,
            COMMAND_TARGET_ID=TARGET,
            _acl_target_credentials={},
            _ops_hmac_key=b"k" * 32,
        ), patch.object(main, "get_db", return_value=connection):
            self.assertTrue(
                main._persist_canonical_target_access_event(
                    topic, payload, retained=False
                )
            )
        self.assertIn("INSERT INTO access_event_history", cursor.execute.call_args.args[0])
        collector_ref = main.opaque_ref(TARGET, b"k" * 32, "target")
        self.assertIn(collector_ref, cursor.execute.call_args.args[1])
        connection.close.assert_called_once()

        parsed = main._parse_canonical_target_access_event(payload)
        self.assertIsNotNone(parsed)
        expected = {
            "event_id": parsed["event_id"],
            "session_id": parsed["session_id"],
            "source_component": parsed["source_component"],
            "source_instance_id": parsed["source_instance_id"],
            "source_boot_id": parsed["source_boot_id"],
            "source_sequence": parsed["source_sequence"],
            "event_attempt": parsed["attempt"],
            "event_code": parsed["event_code"],
            "event_stage": parsed["event_stage"],
            "event_outcome": parsed["event_outcome"],
            "reason_code": parsed["reason_code"],
            "causation_event_id": parsed["causation_event_id"],
            "target_ref": parsed["target_ref"],
            "event_path": parsed["event_path"],
            "event_transport": parsed["event_transport"],
            "distance_mm": parsed["distance_mm"],
            "duration_ms": parsed["duration_ms"],
            "relay_hold_ms": parsed["relay_hold_ms"],
            "monotonic_ms": parsed["monotonic_ms"],
            "clock_quality": parsed["clock_quality"],
            "collector_target_ref": collector_ref,
        }
        duplicate_connection = MagicMock()
        duplicate_cursor = (
            duplicate_connection.cursor.return_value.__enter__.return_value
        )
        duplicate_cursor.execute.side_effect = [
            main.pymysql.err.IntegrityError(1062, "duplicate"),
            None,
        ]
        duplicate_cursor.fetchall.return_value = [expected]
        with patch.multiple(
            main,
            COMMAND_TARGET_ID=TARGET,
            _acl_target_credentials={},
            _ops_hmac_key=b"k" * 32,
        ), patch.object(main, "get_db", return_value=duplicate_connection):
            self.assertTrue(
                main._persist_canonical_target_access_event(
                    topic, payload, retained=False
                )
            )

        conflicting = dict(expected, reason_code="SIGNATURE_INVALID")
        conflict_connection = MagicMock()
        conflict_cursor = conflict_connection.cursor.return_value.__enter__.return_value
        conflict_cursor.execute.side_effect = [
            main.pymysql.err.IntegrityError(1062, "duplicate"),
            None,
        ]
        conflict_cursor.fetchall.return_value = [conflicting]
        with patch.multiple(
            main,
            COMMAND_TARGET_ID=TARGET,
            _acl_target_credentials={},
            _ops_hmac_key=b"k" * 32,
        ), patch.object(main, "get_db", return_value=conflict_connection):
            self.assertFalse(
                main._persist_canonical_target_access_event(
                    topic, payload, retained=False
                )
            )

    def test_canonical_event_callback_is_bounded_and_offloads_database_work(self) -> None:
        with tempfile.NamedTemporaryFile() as ca, ExitStack() as stack:
            stack.enter_context(
                patch.multiple(
                    main,
                    HAS_PAHO_MQTT=True,
                    MQTT_HOST="mqtt.example.test",
                    MQTT_PORT=8883,
                    MQTT_USER="gatekeeper-backend",
                    MQTT_PASSWORD="unique-backend-password",
                    MQTT_CA_FILE=ca.name,
                    COMMAND_TARGET_ID=TARGET,
                    COMMAND_TENANT_ID="tenant-a",
                    COMMAND_DOOR_ID="door-a",
                    COMMAND_SIGNING_KEY_ID=7,
                    COMMAND_SIGNING_PRIVATE_SCALAR_HEX="2" * 64,
                    HA_BRIDGE_ENABLED=False,
                )
            )
            client = MagicMock()
            stack.enter_context(
                patch.object(main, "_create_mqtt_client", return_value=client)
            )
            persisted = threading.Event()
            persist = stack.enter_context(
                patch.object(
                    main,
                    "_persist_canonical_target_access_event",
                    side_effect=lambda *_args, **_kwargs: persisted.set() or True,
                )
            )
            main._start_target_boot_subscriber()
            client.on_connect(client, None, None, 0)
            topic = main._canonical_target_event_topic(TARGET)
            self.assertIn(
                topic, {call.args[0] for call in client.subscribe.call_args_list}
            )
            client.on_message(
                client,
                None,
                SimpleNamespace(
                    topic=topic,
                    payload=canonical_event_payload(),
                    retain=False,
                    dup=False,
                ),
            )
            self.assertTrue(persisted.wait(timeout=1.0))
            persist.assert_called_once()
            client._sgk_access_event_worker.stop()

            persist.reset_mock()
            client.on_message(
                client,
                None,
                SimpleNamespace(
                    topic=topic,
                    payload=b"x" * 8193,
                    retain=False,
                    dup=False,
                ),
            )
            persist.assert_not_called()

    def test_canonical_collector_requires_successful_suback_and_live_writer(self) -> None:
        topic = main._canonical_target_event_topic(TARGET)
        health = main._CanonicalAccessCollectorHealth()
        worker = MagicMock(healthy=True)
        health.configure({topic})
        health.begin_connection()
        health.track_subscription(topic, (0, 41))
        self.assertFalse(health.ready(worker))
        health.acknowledge(41, [1])
        self.assertTrue(health.ready(worker))
        health.note_writer_result(False)
        self.assertFalse(health.ready(worker))
        health.note_writer_result(True)
        self.assertTrue(health.ready(worker))
        health.disconnect()
        self.assertFalse(health.ready(worker))

        health.configure({topic})
        health.begin_connection()
        health.track_subscription(topic, (0, 42))
        health.acknowledge(42, [128])
        self.assertFalse(health.ready(worker))

    def test_acl_delivery_resolves_only_exact_authorized_target_topics(self) -> None:
        tenant = "1" * 32
        door = "2" * 32
        credentials = {
            "target-b": {"tenant_id": tenant, "door_id": door, "key": "b"},
            "target-a": {"tenant_id": tenant, "door_id": door, "key": "a"},
            "other": {"tenant_id": "3" * 32, "door_id": "4" * 32, "key": "c"},
        }
        self.assertEqual(
            [
                "gatekeeper/v1/targets/target-a/acl",
                "gatekeeper/v1/targets/target-b/acl",
            ],
            main._acl_target_topics(
                f"gatekeeper/acl/v1/{tenant}/{door}",
                {"fields": {"door_id": door}},
                credentials,
            ),
        )
        self.assertEqual(
            [],
            main._acl_target_topics(
                f"gatekeeper/acl/v1/{tenant}/{door}",
                {"fields": {"door_id": "f" * 32}},
                credentials,
            ),
        )
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
        self.assertEqual(
            BootRefreshOutcome.UNCHANGED,
            TargetBootRegistry(
                lambda: connection_with(
                    {"boot_id": BOOT_1, "boot_count": 7}
                )[0]
            ).refresh_outcome_from_authenticated_topic(
                f"gatekeeper/v1/targets/{TARGET}/boot", payload
            ),
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
                "HA_BRIDGE_ENABLED": False,
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
                "HA_BRIDGE_ENABLED": False,
            }
            stack.enter_context(patch.multiple(main, **values))
            client = MagicMock()
            stack.enter_context(patch.object(main, "_create_mqtt_client", return_value=client))
            refresh = stack.enter_context(
                patch.object(
                    main._target_boot_registry,
                    "refresh_outcome_from_authenticated_topic",
                    return_value=BootRefreshOutcome.ADVANCED,
                )
            )
            request_refresh = stack.enter_context(
                patch.object(main, "_request_target_acl_refresh", return_value=True)
            )
            self.assertIs(client, main._start_target_boot_subscriber())
            client.username_pw_set.assert_called_once_with(
                "gatekeeper-backend", "unique-backend-password"
            )
            self.assertEqual(ssl.CERT_REQUIRED, client.tls_set.call_args.kwargs["cert_reqs"])
            client.tls_insecure_set.assert_called_once_with(False)
            client.connect.assert_called_once_with("mqtt.example.test", 8883, keepalive=30)
            client.loop_start.assert_called_once()

            class MqttV5SuccessReason:
                value = 0

                def __eq__(self, other):
                    return self.value == other

            client.on_connect(client, None, None, MqttV5SuccessReason())
            self.assertIn(
                f"gatekeeper/v1/targets/{TARGET}/boot",
                {call.args[0] for call in client.subscribe.call_args_list},
            )
            self.assertIn(
                f"gatekeeper/v1/targets/{TARGET}/status",
                {call.args[0] for call in client.subscribe.call_args_list},
            )
            payload = json.dumps(
                {"target_id": TARGET, "boot_id": BOOT_2, "boot_count": 8}
            ).encode()
            message = MagicMock(topic=f"gatekeeper/v1/targets/{TARGET}/boot", payload=payload)
            message.retain = False
            client.on_message(client, None, message)
            refresh.assert_called_once_with(message.topic, payload)
            request_refresh.assert_called_once_with(TARGET, "target_boot")

            refresh.return_value = BootRefreshOutcome.UNCHANGED
            client.on_message(client, None, message)
            self.assertEqual(2, refresh.call_count)
            request_refresh.assert_called_once_with(TARGET, "target_boot")

    def test_signed_command_rejects_changed_expected_boot(self) -> None:
        with tempfile.NamedTemporaryFile() as ca, ExitStack() as stack:
            stack.enter_context(
                patch.multiple(
                    main,
                    MQTT_HOST="mqtt.example.test",
                    MQTT_PORT=8883,
                    MQTT_USER="gatekeeper-backend",
                    MQTT_PASSWORD="unique-backend-password",
                    MQTT_CA_FILE=ca.name,
                    COMMAND_TARGET_ID=TARGET,
                    COMMAND_TENANT_ID="tenant-a",
                    COMMAND_DOOR_ID="door-a",
                    COMMAND_SIGNING_KEY_ID=7,
                    COMMAND_SIGNING_PRIVATE_SCALAR_HEX="2" * 64,
                )
            )
            stack.enter_context(
                patch.object(
                    main._target_boot_registry,
                    "current_boot_id",
                    return_value=BOOT_2,
                )
            )
            stack.enter_context(
                patch.object(
                    main._target_boot_registry,
                    "refresh_outcome_from_authenticated_status_topic",
                    return_value=BootRefreshOutcome.UNCHANGED,
                )
            )
            publish = stack.enter_context(
                patch.object(main, "_publish_mqtt_msg", return_value=True)
            )
            self.assertFalse(
                main._signed_target_command("arm", expected_boot_id=BOOT_1)
            )
            publish.assert_not_called()

    def test_ha_bridge_subscribes_ingress_and_reuses_signed_command_path(self) -> None:
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
                "HA_BRIDGE_ENABLED": True,
                "HA_BRIDGE_ALLOW_MANUAL_REMOTE": False,
                "HA_BRIDGE_STATUS_MAX_AGE_SECONDS": 15.0,
            }
            stack.enter_context(patch.multiple(main, **values))
            client = MagicMock()
            stack.enter_context(
                patch.object(main, "_create_mqtt_client", return_value=client)
            )
            stack.enter_context(
                patch.object(
                    main._target_boot_registry,
                    "current_boot_id",
                    return_value=BOOT_2,
                )
            )
            stack.enter_context(
                patch.object(
                    main._target_boot_registry,
                    "refresh_outcome_from_authenticated_status_topic",
                    return_value=BootRefreshOutcome.UNCHANGED,
                )
            )
            signed = stack.enter_context(
                patch.object(main, "_signed_target_command", return_value=True)
            )
            self.assertIs(client, main._start_target_boot_subscriber())
            client.will_set.assert_called_once_with(
                f"gatekeeper/v1/ha-bridge/{TARGET}/availability",
                payload="offline",
                qos=1,
                retain=True,
            )
            client.on_connect(client, None, None, 0)
            subscribed = {
                call.args[0] for call in client.subscribe.call_args_list
            }
            self.assertIn(
                f"gatekeeper/v1/ha-bridge/{TARGET}/request/+", subscribed
            )
            self.assertIn(f"gatekeeper/v1/targets/{TARGET}/status", subscribed)
            self.assertIn(
                f"gatekeeper/v1/targets/{TARGET}/command-ack", subscribed
            )
            published_topics = {
                call.args[0] for call in client.publish.call_args_list
            }
            self.assertNotIn(
                f"gatekeeper/v1/targets/{TARGET}/command", published_topics
            )

            client.on_message(
                client,
                None,
                SimpleNamespace(
                    topic=f"gatekeeper/v1/targets/{TARGET}/status",
                    payload=json.dumps(
                        {"target_id": TARGET, "boot_id": BOOT_2}
                    ).encode(),
                    retain=False,
                    dup=False,
                ),
            )
            client.on_message(
                client,
                None,
                SimpleNamespace(
                    topic=(
                        f"gatekeeper/v1/ha-bridge/{TARGET}/request/"
                        "config_duration_num"
                    ),
                    payload=b"5000",
                    retain=False,
                    dup=False,
                ),
            )
            signed.assert_called_once()
            self.assertEqual(("set_duration", 5000), signed.call_args.args)
            self.assertEqual(BOOT_2, signed.call_args.kwargs["expected_boot_id"])
            self.assertEqual(15, signed.call_args.kwargs["ttl_seconds"])
            self.assertRegex(
                signed.call_args.kwargs["session_id"], r"^[0-9a-f]{32}$"
            )
            self.assertRegex(signed.call_args.kwargs["nonce"], r"^[0-9a-f]{32}$")

            client.on_message(
                client,
                None,
                SimpleNamespace(
                    topic=f"gatekeeper/v1/ha-bridge/{TARGET}/request/reboot",
                    payload=b"PRESS",
                    retain=True,
                    dup=False,
                ),
            )
            signed.assert_called_once()

    def test_fresh_status_recovers_nonretained_boot_registry_but_retained_rejects(self) -> None:
        connection, cursor = connection_with(None)
        registry = TargetBootRegistry(lambda: connection, clock=lambda: 789)
        payload = json.dumps(
            {
                "target_id": TARGET,
                "boot_id": BOOT_2,
                "boot_count": 9,
                "firmware": "2.2.0",
            }
        ).encode()
        status_topic = f"gatekeeper/v1/targets/{TARGET}/status"
        self.assertEqual(
            BootRefreshOutcome.ADVANCED,
            registry.refresh_outcome_from_authenticated_status_topic(
                status_topic, payload
            ),
        )
        self.assertIn(
            "INSERT INTO target_boot_state", cursor.execute.call_args_list[1].args[0]
        )

        rejected_factory = MagicMock()
        rejected = TargetBootRegistry(rejected_factory)
        self.assertFalse(
            rejected.refresh_from_authenticated_status_topic(
                status_topic, payload, retained=True
            )
        )
        rejected_factory.assert_not_called()

        rollback_connection, _ = connection_with(
            {"boot_id": BOOT_2, "boot_count": 10}
        )
        rollback = TargetBootRegistry(lambda: rollback_connection)
        self.assertFalse(
            rollback.refresh_from_authenticated_status_topic(status_topic, payload)
        )
        rollback_connection.rollback.assert_called_once()

    def test_subscriber_queues_exactly_once_whichever_boot_evidence_arrives_first(self) -> None:
        with tempfile.NamedTemporaryFile() as ca, ExitStack() as stack:
            stack.enter_context(
                patch.multiple(
                    main,
                    HAS_PAHO_MQTT=True,
                    MQTT_HOST="mqtt.example.test",
                    MQTT_PORT=8883,
                    MQTT_USER="gatekeeper-backend",
                    MQTT_PASSWORD="unique-backend-password",
                    MQTT_CA_FILE=ca.name,
                    COMMAND_TARGET_ID=TARGET,
                    COMMAND_TENANT_ID="tenant-a",
                    COMMAND_DOOR_ID="door-a",
                    COMMAND_SIGNING_KEY_ID=7,
                    COMMAND_SIGNING_PRIVATE_SCALAR_HEX="2" * 64,
                    HA_BRIDGE_ENABLED=False,
                )
            )
            client = MagicMock()
            stack.enter_context(
                patch.object(main, "_create_mqtt_client", return_value=client)
            )
            boot_refresh = stack.enter_context(
                patch.object(
                    main._target_boot_registry,
                    "refresh_outcome_from_authenticated_topic",
                )
            )
            status_refresh = stack.enter_context(
                patch.object(
                    main._target_boot_registry,
                    "refresh_outcome_from_authenticated_status_topic",
                )
            )
            request_refresh = stack.enter_context(
                patch.object(main, "_request_target_acl_refresh", return_value=True)
            )
            main._start_target_boot_subscriber()

            boot_message = SimpleNamespace(
                topic=f"gatekeeper/v1/targets/{TARGET}/boot",
                payload=json.dumps(
                    {"target_id": TARGET, "boot_id": BOOT_2, "boot_count": 8}
                ).encode(),
                retain=False,
                dup=False,
            )
            status_message = SimpleNamespace(
                topic=f"gatekeeper/v1/targets/{TARGET}/status",
                payload=boot_message.payload,
                retain=False,
                dup=False,
            )

            for name, first, second, first_result, second_result in (
                (
                    "status-first",
                    status_message,
                    boot_message,
                    BootRefreshOutcome.ADVANCED,
                    BootRefreshOutcome.UNCHANGED,
                ),
                (
                    "boot-first",
                    boot_message,
                    status_message,
                    BootRefreshOutcome.ADVANCED,
                    BootRefreshOutcome.UNCHANGED,
                ),
            ):
                with self.subTest(name=name):
                    request_refresh.reset_mock()
                    boot_refresh.return_value = (
                        first_result if first is boot_message else second_result
                    )
                    status_refresh.return_value = (
                        first_result if first is status_message else second_result
                    )
                    client.on_message(client, None, first)
                    client.on_message(client, None, second)
                    request_refresh.assert_called_once_with(TARGET, "target_boot")

            request_refresh.reset_mock()
            boot_refresh.return_value = BootRefreshOutcome.UNCHANGED
            status_refresh.return_value = BootRefreshOutcome.UNCHANGED
            client.on_message(client, None, status_message)
            client.on_message(client, None, boot_message)
            request_refresh.assert_not_called()

            status_refresh.reset_mock()
            status_refresh.return_value = BootRefreshOutcome.REJECTED
            status_message.retain = True
            client.on_message(client, None, status_message)
            status_refresh.assert_called_once_with(
                status_message.topic, status_message.payload, retained=True
            )
            request_refresh.assert_not_called()

    def test_subscriber_persists_exact_target_acl_ack_before_delivery_signal(self) -> None:
        tenant = "1" * 32
        door = "2" * 32
        with tempfile.NamedTemporaryFile() as ca, ExitStack() as stack:
            stack.enter_context(
                patch.multiple(
                    main,
                    HAS_PAHO_MQTT=True,
                    MQTT_HOST="mqtt.example.test",
                    MQTT_PORT=8883,
                    MQTT_USER="gatekeeper-backend",
                    MQTT_PASSWORD="unique-backend-password",
                    MQTT_CA_FILE=ca.name,
                    COMMAND_TARGET_ID=TARGET,
                    COMMAND_TENANT_ID=tenant,
                    COMMAND_DOOR_ID=door,
                    COMMAND_SIGNING_KEY_ID=7,
                    COMMAND_SIGNING_PRIVATE_SCALAR_HEX="2" * 64,
                    HA_BRIDGE_ENABLED=False,
                    _acl_runtime_ready=True,
                )
            )
            stack.enter_context(
                patch.object(
                    main,
                    "_acl_target_credentials",
                    {
                        TARGET: {
                            "tenant_id": tenant,
                            "door_id": door,
                            "key": "target-key",
                        }
                    },
                    create=True,
                )
            )
            client = MagicMock()
            stack.enter_context(
                patch.object(main, "_create_mqtt_client", return_value=client)
            )
            service = MagicMock()
            service.store.snapshot_by_version.return_value = {
                "sha256": "a" * 64
            }
            stack.enter_context(patch.object(main, "_acl_service", service, create=True))
            tracker = main.TargetAclDeliveryTracker()
            stack.enter_context(
                patch.object(main, "_target_acl_delivery_tracker", tracker)
            )

            main._start_target_boot_subscriber()
            client.on_connect(client, None, None, 0)
            self.assertIn(
                f"gatekeeper/v1/targets/{TARGET}/acl/ack",
                {call.args[0] for call in client.subscribe.call_args_list},
            )
            client.on_message(
                client,
                None,
                SimpleNamespace(
                    topic=f"gatekeeper/v1/targets/{TARGET}/acl/ack",
                    payload=json.dumps(
                        {
                            "status": "applied",
                            "acl_version": 7,
                            "high_watermark": 7,
                        }
                    ).encode(),
                    retain=False,
                    dup=False,
                ),
            )
            service.ack_snapshot.assert_called_once_with(
                tenant, TARGET, door, 7, "a" * 64, "APPLIED"
            )
            self.assertTrue(
                tracker.wait_for([TARGET], 7, timeout_seconds=0.01)
            )

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
