from __future__ import annotations

import json
import ssl
import tempfile
import threading
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from backend.app import main
from backend.app.access_actor_ref import (
    access_credential_ref,
    access_evidence_mac,
    build_access_event_mac_input,
    build_access_status_mac_input,
    build_mobile_access_session_read_input,
)
from backend.app.acl_management import DeterministicP256Signer
from backend.app.target_boot_registry import BootRefreshOutcome, TargetBootRegistry


TARGET = "target-a"
BOOT_1 = "1" * 32
BOOT_2 = "2" * 32
EVENT_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
SOURCE_REF = "target_0123456789abcdef"
ACCESS_DOOR_ID = "00112233445566778899aabbccddeeff"
ACCESS_REF_KEY = bytes.fromhex("11" * 32)
ACCESS_CREDENTIAL_ID = "ffeeddccbbaa99887766554433221100"


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


def signed_canonical_event_payload(
    *,
    event_code="ACCESS_PROOF_VERIFIED",
    stage="PROOF",
    outcome="SUCCEEDED",
    reason_code="PROOF_VALID",
):
    credential_ref = access_credential_ref(
        "k1",
        ACCESS_REF_KEY,
        ACCESS_DOOR_ID,
        SESSION_ID,
        ACCESS_CREDENTIAL_ID,
    )
    document = json.loads(
        canonical_event_payload(
            event_code=event_code,
            stage=stage,
            outcome=outcome,
            reason_code=reason_code,
        )
    )
    document["schema_version"] = "1.1"
    document["target"]["boot_count"] = 8
    document["attributes"]["credential_ref"] = credential_ref
    canonical = build_access_event_mac_input(
        key_id="k1",
        topic_target_id=TARGET,
        door_id=ACCESS_DOOR_ID,
        source_instance_id=SOURCE_REF,
        source_boot_id=BOOT_1,
        source_boot_count=8,
        event_id=EVENT_ID,
        session_id=SESSION_ID,
        sequence=7,
        attempt=1,
        event_code=event_code,
        stage=stage,
        outcome=outcome,
        reason_code=reason_code,
        causation_event_id=None,
        monotonic_ms=12345,
        credential_ref=credential_ref,
        distance_mm=None,
        duration_ms=None,
        relay_hold_ms=None,
    )
    document["auth"] = {
        "version": 1,
        "key_id": "k1",
        "tag": access_evidence_mac(ACCESS_REF_KEY, canonical),
    }
    return json.dumps(document, separators=(",", ":")).encode()


def connection_with(row):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    return connection, cursor


class TargetBootRegistryTest(unittest.TestCase):
    def test_bridge_availability_expiry_replaces_stale_timers(self) -> None:
        timers = []

        class FakeTimer:
            def __init__(self, delay, callback):
                self.delay = delay
                self.callback = callback
                self.cancelled = False
                self.started = False
                self.daemon = False
                timers.append(self)

            def start(self):
                self.started = True

            def cancel(self):
                self.cancelled = True

            def fire(self):
                # Exercise the generation check even if a cancelled timer had
                # already entered its callback on another thread.
                self.callback()

        publish_offline = MagicMock()
        expiry = main._BridgeAvailabilityExpiry(
            main.HA_BRIDGE_AVAILABILITY_EXPIRY_SECONDS,
            publish_offline,
            timer_factory=FakeTimer,
        )
        self.assertTrue(expiry.arm())
        first = timers[-1]
        self.assertEqual(90.25, first.delay)
        self.assertTrue(first.daemon)
        self.assertTrue(first.started)

        self.assertTrue(expiry.arm())
        second = timers[-1]
        self.assertTrue(first.cancelled)
        first.fire()
        publish_offline.assert_not_called()
        second.fire()
        publish_offline.assert_called_once_with()

        self.assertTrue(expiry.arm())
        third = timers[-1]
        expiry.reset()
        self.assertTrue(third.cancelled)
        third.fire()
        publish_offline.assert_called_once_with()

        self.assertTrue(expiry.arm())
        fourth = timers[-1]
        expiry.stop()
        self.assertTrue(fourth.cancelled)
        fourth.fire()
        self.assertFalse(expiry.arm())
        publish_offline.assert_called_once_with()

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

    def test_signed_session_superseded_is_accepted_only_as_failure(self) -> None:
        payload = signed_canonical_event_payload(
            event_code="ACCESS_SESSION_TERMINATED",
            stage="COMPLETE",
            outcome="FAILED",
            reason_code="SESSION_SUPERSEDED",
        )
        parsed = main._parse_canonical_target_access_event(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual("ACCESS_SESSION_TERMINATED", parsed["event_code"])
        self.assertEqual("FAILED", parsed["event_outcome"])
        self.assertEqual("SESSION_SUPERSEDED", parsed["reason_code"])
        with patch.multiple(
            main,
            COMMAND_TARGET_ID=TARGET,
            COMMAND_DOOR_ID=ACCESS_DOOR_ID,
            ACL_PERSONAL_DOOR_ID=ACCESS_DOOR_ID,
            ACCESS_EVENT_REF_KEYS={"k1": ACCESS_REF_KEY},
            _acl_target_credentials={},
        ):
            self.assertTrue(
                main._authenticate_canonical_target_access_event(TARGET, parsed)
            )

        self.assertIsNone(
            main._parse_canonical_target_access_event(
                canonical_event_payload(
                    event_code="ACCESS_SESSION_TERMINATED",
                    stage="COMPLETE",
                    outcome="SUCCEEDED",
                    reason_code="SESSION_SUPERSEDED",
                )
            )
        )

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

        actor_ref = access_credential_ref(
            "k1",
            bytes.fromhex("11" * 32),
            "00112233445566778899aabbccddeeff",
            SESSION_ID,
            "ffeeddccbbaa99887766554433221100",
        )
        attributed = main._parse_canonical_target_access_event(
            canonical_event_payload(
                attributes={
                    "path": "local_gatt",
                    "transport": "ble_gatt",
                    "credential_ref": actor_ref,
                }
            )
        )
        self.assertEqual(actor_ref, attributed["credential_ref"])
        self.assertIsNone(
            main._parse_canonical_target_access_event(
                canonical_event_payload(
                    event_code="ACCESS_PROOF_REQUESTED",
                    stage="PROOF",
                    outcome="STARTED",
                    reason_code="PROOF_CHALLENGE_ISSUED",
                    attributes={
                        "path": "local_gatt",
                        "transport": "ble_gatt",
                        "credential_ref": actor_ref,
                    },
                )
            )
        )

    def test_signed_event_and_status_require_exact_cross_language_mac(self) -> None:
        key = bytes.fromhex("11" * 32)
        door = "00112233445566778899aabbccddeeff"
        boot = "aa" * 16
        credential_ref = "c_k1_8e1681bdeb8f7c5f392c48ef"
        event_document = json.loads(
            canonical_event_payload(
                event_code="ACCESS_SENSOR_DETECTED",
                stage="SENSOR",
                reason_code="SENSOR_THRESHOLD_MET",
                attributes={
                    "path": "local_gatt",
                    "transport": "ble_gatt",
                    "distance_mm": 420,
                    "credential_ref": credential_ref,
                },
            )
        )
        event_document["schema_version"] = "1.1"
        event_document["source_boot_id"] = boot
        event_document["target"]["boot_id"] = boot
        event_document["target"]["boot_count"] = 686
        event_input = build_access_event_mac_input(
            key_id="k1",
            topic_target_id=TARGET,
            door_id=door,
            source_instance_id=SOURCE_REF,
            source_boot_id=boot,
            source_boot_count=686,
            event_id=EVENT_ID,
            session_id=SESSION_ID,
            sequence=7,
            attempt=1,
            event_code="ACCESS_SENSOR_DETECTED",
            stage="SENSOR",
            outcome="SUCCEEDED",
            reason_code="SENSOR_THRESHOLD_MET",
            causation_event_id=None,
            monotonic_ms=12345,
            credential_ref=credential_ref,
            distance_mm=420,
            duration_ms=None,
            relay_hold_ms=None,
        )
        event_document["auth"] = {
            "version": 1,
            "key_id": "k1",
            "tag": access_evidence_mac(key, event_input),
        }
        parsed_event = main._parse_canonical_target_access_event(
            json.dumps(event_document, separators=(",", ":")).encode()
        )
        with patch.multiple(
            main,
            ACCESS_EVENT_REF_KEYS={"k1": key},
            COMMAND_TARGET_ID=TARGET,
            COMMAND_DOOR_ID=door,
            ACL_PERSONAL_DOOR_ID=door,
            _acl_target_credentials={},
            _ops_hmac_key=b"o" * 32,
        ):
            self.assertTrue(
                main._authenticate_canonical_target_access_event(
                    TARGET, parsed_event
                )
            )
            tampered_event = dict(parsed_event, monotonic_ms=12346)
            self.assertFalse(
                main._authenticate_canonical_target_access_event(
                    TARGET, tampered_event
                )
            )

            status_document = {
                "target_id": TARGET,
                "boot_id": boot,
                "boot_count": 686,
                "state": "IDLE",
                "access_status_revision": 42,
                "last_terminal_session_id": SESSION_ID,
                "last_terminal_event_sequence": 11,
                "last_terminal_event_code": "ACCESS_SESSION_COMPLETED",
                "last_terminal_reason_code": "ACCESS_GRANTED",
                "last_terminal_credential_ref": credential_ref,
                "last_terminal_phase_mask": 0x1F,
                "relay_commanded_on": False,
                "relay_pin_level": 1,
            }
            status_input = build_access_status_mac_input(
                key_id="k1",
                topic_target_id=TARGET,
                door_id=door,
                source_boot_id=boot,
                source_boot_count=686,
                access_revision=42,
                state="IDLE",
                last_terminal_session_id=SESSION_ID,
                last_terminal_event_sequence=11,
                last_terminal_event_code="ACCESS_SESSION_COMPLETED",
                last_terminal_reason_code="ACCESS_GRANTED",
                last_terminal_credential_ref=credential_ref,
                last_terminal_phase_mask=0x1F,
                relay_commanded_on=False,
                relay_pin_level=1,
            )
            status_document["access_auth"] = {
                "version": 1,
                "key_id": "k1",
                "tag": access_evidence_mac(key, status_input),
            }
            status_payload = json.dumps(
                status_document, separators=(",", ":")
            ).encode()
            self.assertIsNotNone(
                main._parse_authenticated_target_status(TARGET, status_payload)
            )
            parsed_status = main._parse_authenticated_target_status(
                TARGET, status_payload
            )
            status_connection = MagicMock()
            status_cursor = (
                status_connection.cursor.return_value.__enter__.return_value
            )
            status_cursor.fetchone.side_effect = [None, None]
            with patch.object(main, "get_db", return_value=status_connection):
                persisted = main._persist_authenticated_target_status(
                    TARGET, status_payload, retained=False
                )
            self.assertTrue(persisted["advanced"])
            self.assertEqual(
                (TARGET,), status_cursor.execute.call_args_list[0].args[1]
            )
            status_connection.begin.assert_called_once()
            status_connection.commit.assert_called_once()
            statements = [call.args[0] for call in status_cursor.execute.call_args_list]
            self.assertTrue(
                any("INSERT INTO access_terminal_summary" in sql for sql in statements)
            )
            self.assertTrue(
                any(
                    "INSERT INTO target_access_status_highwater" in sql
                    for sql in statements
                )
            )

            replay_connection = MagicMock()
            replay_cursor = (
                replay_connection.cursor.return_value.__enter__.return_value
            )
            replay_cursor.fetchone.return_value = {
                "source_boot_id": boot,
                "source_boot_count": 686,
                "status_revision": 42,
                "integrity_key_id": "k1",
                "integrity_tag": parsed_status["integrity_tag"],
            }
            with patch.object(
                main, "get_db", return_value=replay_connection
            ), patch.object(main, "_ops_hmac_key", b"n" * 32):
                replay = main._persist_authenticated_target_status(
                    TARGET, status_payload, retained=False
                )
            self.assertFalse(replay["advanced"])
            replay_connection.commit.assert_called_once()
            replay_connection.rollback.assert_not_called()
            self.assertEqual(
                (TARGET,), replay_cursor.execute.call_args_list[0].args[1]
            )
            self.assertIn(
                "WHERE target_id=%s",
                replay_cursor.execute.call_args_list[0].args[0],
            )
            self.assertNotIn(
                main.opaque_ref(TARGET, b"n" * 32, "target"),
                replay_cursor.execute.call_args_list[0].args[1],
            )
            self.assertIn(
                "INSERT INTO target_boot_state",
                replay_cursor.execute.call_args_list[1].args[0],
            )

            status_document["state"] = "COOLDOWN"
            self.assertIsNone(
                main._parse_authenticated_target_status(
                    TARGET,
                    json.dumps(status_document, separators=(",", ":")).encode(),
                )
            )
        self.assertIsNone(
            main._parse_canonical_target_access_event(
                canonical_event_payload(
                    attributes={
                        "path": "local_gatt",
                        "transport": "ble_gatt",
                        "credential_ref": "raw-credential-must-not-pass",
                    }
                )
            )
        )

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
        unsigned_db = MagicMock()
        with patch.object(main, "get_db", unsigned_db):
            self.assertIsNone(
                main._persist_canonical_target_access_event(
                    topic, canonical_event_payload(), retained=False
                )
            )
        unsigned_db.assert_not_called()

        payload = signed_canonical_event_payload()
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        with patch.multiple(
            main,
            COMMAND_TARGET_ID=TARGET,
            COMMAND_DOOR_ID=ACCESS_DOOR_ID,
            ACCESS_EVENT_REF_KEYS={"k1": ACCESS_REF_KEY},
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
            "source_boot_count": parsed["source_boot_count"],
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
            "collector_target_id": TARGET,
            "credential_ref": parsed["credential_ref"],
            "integrity_key_id": parsed["integrity_key_id"],
            "integrity_tag": bytes.fromhex(parsed["integrity_tag"]),
            "integrity_status": "verified",
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
            COMMAND_DOOR_ID=ACCESS_DOOR_ID,
            ACCESS_EVENT_REF_KEYS={"k1": ACCESS_REF_KEY},
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
            COMMAND_DOOR_ID=ACCESS_DOOR_ID,
            ACCESS_EVENT_REF_KEYS={"k1": ACCESS_REF_KEY},
            _acl_target_credentials={},
            _ops_hmac_key=b"k" * 32,
        ), patch.object(main, "get_db", return_value=conflict_connection):
            self.assertFalse(
                main._persist_canonical_target_access_event(
                    topic, payload, retained=False
                )
            )

    def test_personal_access_session_requires_exact_credential_ref_and_idle(self) -> None:
        key = bytes.fromhex("11" * 32)
        door = "00112233445566778899aabbccddeeff"
        credential = "ffeeddccbbaa99887766554433221100"
        actor_ref = access_credential_ref("k1", key, door, SESSION_ID, credential)
        signer = DeterministicP256Signer(18, signing_key_id=0)
        nonce = "44" * 32
        expires_at = 120
        canonical = build_mobile_access_session_read_input(
            credential, SESSION_ID, nonce, expires_at
        )
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            {
                "id": 1,
                "event_id": EVENT_ID,
                "event_code": "ACCESS_SENSOR_DETECTED",
                "event_outcome": "SUCCEEDED",
                "reason_code": "SENSOR_THRESHOLD_MET",
                "credential_ref": actor_ref,
                "received_at": datetime(2026, 9, 2, 0, 12, 10),
                "source_sequence": 7,
                "source_boot_id": BOOT_1,
                "source_boot_count": 8,
            },
            {
                "id": 2,
                "event_id": "33333333-3333-4333-8333-333333333333",
                "event_code": "ACCESS_SESSION_COMPLETED",
                "event_outcome": "SUCCEEDED",
                "reason_code": "ACCESS_GRANTED",
                "credential_ref": actor_ref,
                "received_at": datetime(2026, 9, 2, 0, 12, 11),
                "source_sequence": 8,
                "source_boot_id": BOOT_1,
                "source_boot_count": 8,
            },
        ]
        with patch.multiple(
            main,
            ACCESS_EVENT_REF_KEYS={"k1": key},
            ACL_PERSONAL_DOOR_ID=door,
            COMMAND_TARGET_ID=TARGET,
            _ops_hmac_key=b"o" * 32,
        ), patch.object(main, "get_db", return_value=connection), patch.object(
            main._target_gate_states,
            "live_evidence",
            return_value={
                "target_id": TARGET,
                "source_boot_id": BOOT_1,
                "source_boot_count": 8,
                "status_revision": 42,
                "state": "IDLE",
                "last_terminal_session_id": SESSION_ID,
                "last_terminal_event_sequence": 8,
                "last_terminal_event_code": "ACCESS_SESSION_COMPLETED",
                "last_terminal_reason_code": "ACCESS_GRANTED",
                "last_terminal_credential_ref": actor_ref,
                "last_terminal_phase_mask": 0x1F,
                "relay_commanded_on": False,
                "relay_pin_level": 1,
            },
        ), patch.object(main.time, "time", return_value=100):
            status = main._personal_access_session(
                credential,
                signer.public_key_sec1.hex(),
                SESSION_ID,
                nonce,
                expires_at,
                signer.sign(canonical).hex(),
            )
        self.assertEqual("complete", status["status"])
        self.assertTrue(status["next_auth_ready"])
        self.assertTrue(status["terminal"])
        self.assertEqual(
            "target_signed_event_and_status", status["evidence_source"]
        )
        self.assertNotIn(credential, json.dumps(status))
        self.assertNotIn(SESSION_ID, json.dumps(status))
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(
            any("mobile_credential_control_nonces" in sql for sql in statements)
        )

        other_session_id = "33333333-3333-4333-8333-333333333333"
        other_session_actor_ref = access_credential_ref(
            "k1", key, door, other_session_id, credential
        )
        with patch.multiple(
            main,
            ACCESS_EVENT_REF_KEYS={"k1": key},
            ACL_PERSONAL_DOOR_ID=door,
            COMMAND_TARGET_ID=TARGET,
            TARGET_RELAY_OFF_PIN_LEVEL=1,
        ), patch.object(main, "get_db", return_value=connection), patch.object(
            main._target_gate_states,
            "live_evidence",
            return_value={
                "target_id": TARGET,
                "source_boot_id": BOOT_1,
                "source_boot_count": 8,
                "status_revision": 43,
                "state": "IDLE",
                "last_terminal_session_id": other_session_id,
                "last_terminal_event_sequence": 8,
                "last_terminal_event_code": "ACCESS_SESSION_COMPLETED",
                "last_terminal_reason_code": "ACCESS_GRANTED",
                "last_terminal_credential_ref": other_session_actor_ref,
                "last_terminal_phase_mask": 0x1F,
                "relay_commanded_on": False,
                "relay_pin_level": 1,
            },
        ), patch.object(main.time, "time", return_value=100):
            cross_session = main._personal_access_session(
                credential,
                signer.public_key_sec1.hex(),
                SESSION_ID,
                nonce,
                expires_at,
                signer.sign(canonical).hex(),
            )
        self.assertEqual("sensor_detected", cross_session["status"])
        self.assertFalse(cross_session["next_auth_ready"])
        self.assertFalse(cross_session["terminal"])
        self.assertIsNone(cross_session["target_state"])
        self.assertFalse(cross_session["target_fresh"])
        self.assertEqual(
            "target_signed_event", cross_session["evidence_source"]
        )

        with patch.multiple(
            main,
            ACCESS_EVENT_REF_KEYS={"k1": key},
            ACL_PERSONAL_DOOR_ID=door,
            COMMAND_TARGET_ID=TARGET,
            TARGET_RELAY_OFF_PIN_LEVEL=1,
        ), patch.object(main, "get_db", return_value=connection), patch.object(
            main._target_gate_states,
            "live_evidence",
            return_value={
                "target_id": TARGET,
                "source_boot_id": BOOT_1,
                "source_boot_count": 8,
                "status_revision": 43,
                "state": "COOLDOWN",
                "last_terminal_session_id": SESSION_ID,
                "last_terminal_event_sequence": 8,
                "last_terminal_event_code": "ACCESS_SESSION_COMPLETED",
                "last_terminal_reason_code": "ACCESS_GRANTED",
                "last_terminal_credential_ref": actor_ref,
                "last_terminal_phase_mask": 0x1F,
                "relay_commanded_on": False,
                "relay_pin_level": 1,
            },
        ), patch.object(main.time, "time", return_value=100):
            other_credential = "00" * 16
            other_canonical = build_mobile_access_session_read_input(
                other_credential, SESSION_ID, nonce, expires_at
            )
            other = main._personal_access_session(
                other_credential,
                signer.public_key_sec1.hex(),
                SESSION_ID,
                nonce,
                expires_at,
                signer.sign(other_canonical).hex(),
            )
        self.assertEqual("pending", other["status"])
        self.assertFalse(other["next_auth_ready"])
        self.assertIsNone(other["target_state"])
        self.assertFalse(other["target_fresh"])

        denied_db = MagicMock()
        with patch.multiple(
            main,
            ACCESS_EVENT_REF_KEYS={"k1": key},
            ACL_PERSONAL_DOOR_ID=door,
            COMMAND_TARGET_ID=TARGET,
        ), patch.object(main, "get_db", denied_db), patch.object(
            main.time, "time", return_value=100
        ):
            with self.assertRaises(PermissionError):
                main._personal_access_session(
                    credential,
                    signer.public_key_sec1.hex(),
                    SESSION_ID,
                    nonce,
                    expires_at,
                    "00" * 64,
                )
        denied_db.assert_not_called()

        replay_connection = MagicMock()
        replay_cursor = (
            replay_connection.cursor.return_value.__enter__.return_value
        )
        replay_cursor.execute.side_effect = main.pymysql.err.IntegrityError(
            1062, "duplicate"
        )
        with patch.multiple(
            main,
            ACCESS_EVENT_REF_KEYS={"k1": key},
            ACL_PERSONAL_DOOR_ID=door,
            COMMAND_TARGET_ID=TARGET,
        ), patch.object(
            main, "get_db", return_value=replay_connection
        ), patch.object(main.time, "time", return_value=100):
            with self.assertRaisesRegex(PermissionError, "already consumed"):
                main._personal_access_session(
                    credential,
                    signer.public_key_sec1.hex(),
                    SESSION_ID,
                    nonce,
                    expires_at,
                    signer.sign(canonical).hex(),
                )
        replay_connection.close.assert_called_once_with()

    def test_personal_access_session_treats_failsafe_summary_as_failure(self) -> None:
        key = bytes.fromhex("11" * 32)
        door = "00112233445566778899aabbccddeeff"
        credential = "ffeeddccbbaa99887766554433221100"
        actor_ref = access_credential_ref(
            "k1", key, door, SESSION_ID, credential
        )
        signer = DeterministicP256Signer(19, signing_key_id=0)
        expires_at = 120
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            {
                "id": 1,
                "event_id": EVENT_ID,
                "event_code": "ACCESS_RELAY_OFF",
                "event_outcome": "FAILED",
                "reason_code": "RELAY_FAILSAFE_CUTOFF",
                "credential_ref": actor_ref,
                "received_at": datetime(2026, 9, 2, 0, 12, 10),
                "source_sequence": 8,
                "source_boot_id": BOOT_1,
                "source_boot_count": 8,
            },
            {
                "id": 2,
                "event_id": "33333333-3333-4333-8333-333333333333",
                "event_code": "ACCESS_SESSION_COMPLETED",
                "event_outcome": "SUCCEEDED",
                "reason_code": "ACCESS_GRANTED",
                "credential_ref": actor_ref,
                "received_at": datetime(2026, 9, 2, 0, 12, 11),
                "source_sequence": 9,
                "source_boot_id": BOOT_1,
                "source_boot_count": 8,
            },
        ]
        terminal = {
            "target_id": TARGET,
            "source_boot_id": BOOT_1,
            "source_boot_count": 8,
            "last_terminal_session_id": SESSION_ID,
            "last_terminal_event_sequence": 9,
            "last_terminal_event_code": "ACCESS_SESSION_COMPLETED",
            "last_terminal_reason_code": "ACCESS_GRANTED",
            "last_terminal_credential_ref": actor_ref,
            "last_terminal_phase_mask": 0x3F,
            "relay_commanded_on": False,
            "relay_pin_level": 1,
        }
        live_evidence = [
            dict(terminal, status_revision=42, state="COOLDOWN"),
            dict(terminal, status_revision=43, state="IDLE"),
        ]

        results = []
        with patch.multiple(
            main,
            ACCESS_EVENT_REF_KEYS={"k1": key},
            ACL_PERSONAL_DOOR_ID=door,
            COMMAND_TARGET_ID=TARGET,
            TARGET_RELAY_OFF_PIN_LEVEL=1,
            _ops_hmac_key=b"o" * 32,
        ), patch.object(main, "get_db", return_value=connection), patch.object(
            main._target_gate_states,
            "live_evidence",
            side_effect=live_evidence,
        ), patch.object(main.time, "time", return_value=100):
            for nonce_byte in ("44", "55"):
                nonce = nonce_byte * 32
                canonical = build_mobile_access_session_read_input(
                    credential, SESSION_ID, nonce, expires_at
                )
                results.append(
                    main._personal_access_session(
                        credential,
                        signer.public_key_sec1.hex(),
                        SESSION_ID,
                        nonce,
                        expires_at,
                        signer.sign(canonical).hex(),
                    )
                )

        cooldown, idle = results
        # The signed failsafe terminal is surfaced immediately, while the
        # independent next-auth gate remains closed until fresh IDLE/OFF.
        self.assertEqual("terminated", cooldown["status"])
        self.assertFalse(cooldown["next_auth_ready"])
        self.assertFalse(cooldown["terminal"])
        self.assertEqual("terminated", idle["status"])
        self.assertTrue(idle["next_auth_ready"])
        self.assertTrue(idle["terminal"])
        self.assertNotEqual("complete", idle["status"])

    def test_personal_access_session_projects_superseded_after_summary_overwrite(self) -> None:
        key = bytes.fromhex("11" * 32)
        door = "00112233445566778899aabbccddeeff"
        credential = "ffeeddccbbaa99887766554433221100"
        actor_ref = access_credential_ref(
            "k1", key, door, SESSION_ID, credential
        )
        signer = DeterministicP256Signer(20, signing_key_id=0)
        expires_at = 120
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            {
                "id": 1,
                "event_id": EVENT_ID,
                "event_code": "ACCESS_SESSION_TERMINATED",
                "event_outcome": "FAILED",
                "reason_code": "SESSION_SUPERSEDED",
                "credential_ref": actor_ref,
                "received_at": datetime(2026, 9, 2, 0, 12, 11),
                "source_sequence": 9,
                "source_boot_id": BOOT_1,
                "source_boot_count": 8,
            }
        ]
        overwritten_terminal = {
            "target_id": TARGET,
            "source_boot_id": BOOT_1,
            "source_boot_count": 8,
            "last_terminal_session_id": (
                "44444444-4444-4444-8444-444444444444"
            ),
            "last_terminal_event_sequence": 18,
            "last_terminal_event_code": "ACCESS_SESSION_COMPLETED",
            "last_terminal_reason_code": "ACCESS_GRANTED",
            "last_terminal_credential_ref": "c_k1_0123456789abcdef01234567",
            "last_terminal_phase_mask": 0x1F,
            "relay_commanded_on": False,
            "relay_pin_level": 1,
        }
        live_evidence = [
            dict(overwritten_terminal, status_revision=44, state="COOLDOWN"),
            dict(overwritten_terminal, status_revision=45, state="IDLE"),
        ]
        results = []
        with patch.multiple(
            main,
            ACCESS_EVENT_REF_KEYS={"k1": key},
            ACL_PERSONAL_DOOR_ID=door,
            COMMAND_TARGET_ID=TARGET,
            TARGET_RELAY_OFF_PIN_LEVEL=1,
            _ops_hmac_key=b"o" * 32,
        ), patch.object(main, "get_db", return_value=connection), patch.object(
            main._target_gate_states,
            "live_evidence",
            side_effect=live_evidence,
        ), patch.object(main.time, "time", return_value=100):
            for nonce_byte in ("66", "77"):
                nonce = nonce_byte * 32
                canonical = build_mobile_access_session_read_input(
                    credential, SESSION_ID, nonce, expires_at
                )
                results.append(
                    main._personal_access_session(
                        credential,
                        signer.public_key_sec1.hex(),
                        SESSION_ID,
                        nonce,
                        expires_at,
                        signer.sign(canonical).hex(),
                    )
                )

        busy, idle = results
        self.assertEqual("terminated", busy["status"])
        self.assertFalse(busy["next_auth_ready"])
        self.assertFalse(busy["terminal"])
        self.assertFalse(busy["target_fresh"])
        self.assertEqual("terminated", idle["status"])
        self.assertTrue(idle["next_auth_ready"])
        self.assertTrue(idle["terminal"])
        self.assertTrue(idle["target_fresh"])
        self.assertEqual("IDLE", idle["target_state"])
        self.assertEqual(
            "target_signed_termination_and_status",
            idle["evidence_source"],
        )
        self.assertNotEqual("complete", idle["status"])

    def test_home_assistant_verified_projection_is_an_allow_list(self) -> None:
        stored = {
            "target_id": TARGET,
            "source_boot_id": BOOT_1,
            "source_boot_count": 8,
            "status_revision": 42,
            "state": "ARMED",
            "relay_commanded_on": False,
            "relay_pin_level": 1,
            "last_terminal_session_id": SESSION_ID,
            "last_terminal_credential_ref": "c_k1_secret-ref",
            "last_terminal_reason_code": "ACCESS_GRANTED",
            "access_auth": {"tag": "must-not-leak"},
            "distance_mm": 420,
            "ip": "192.0.2.1",
        }
        projection = main._verified_home_assistant_status_projection(
            TARGET, stored
        )
        self.assertIsNotNone(projection)
        document = json.loads(projection)
        self.assertEqual(
            {
                "access_status_revision": 42,
                "boot_count": 8,
                "boot_id": BOOT_1,
                "is_armed": True,
                "relay_commanded_on": False,
                "relay_pin_level": 1,
                "state": "ARMED",
                "target_id": TARGET,
            },
            document,
        )
        serialized = projection.decode("utf-8")
        for private_value in (
            SESSION_ID,
            "c_k1_secret-ref",
            "ACCESS_GRANTED",
            "must-not-leak",
            "192.0.2.1",
            "420",
        ):
            self.assertNotIn(private_value, serialized)

    def test_target_gate_state_can_be_cleared_on_explicit_offline(self) -> None:
        registry = main._TargetGateStateRegistry()
        self.assertTrue(
            registry.note_verified(
                TARGET,
                {
                    "advanced": True,
                    "target_id": TARGET,
                    "source_boot_id": BOOT_1,
                    "state": "IDLE",
                },
            )
        )
        self.assertEqual(("IDLE", BOOT_1), registry.live_snapshot(TARGET))
        registry.clear_target(TARGET)
        self.assertIsNone(registry.live_snapshot(TARGET))

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

    def test_status_collector_requires_verified_evidence_each_connection(self) -> None:
        topic = main.target_status_topic(TARGET)
        health = main._CanonicalAccessCollectorHealth()
        worker = MagicMock(healthy=True)
        health.configure({topic}, require_verified_evidence=True)
        health.begin_connection()
        health.track_subscription(topic, (0, 51))
        health.acknowledge(51, [1])
        self.assertFalse(health.ready(worker))

        # A successfully persisted, MAC-verified status proves that the NAS
        # keyring and the Target's embedded key agree for this connection.
        health.note_verified_evidence()
        self.assertTrue(health.ready(worker))

        health.disconnect()
        health.begin_connection()
        health.track_subscription(topic, (0, 52))
        health.acknowledge(52, [1])
        self.assertFalse(health.ready(worker))

    def test_signed_status_readiness_cutover_preserves_target_n_minus_1(self) -> None:
        topic = main.target_status_topic(TARGET)
        for required in (False, True):
            with self.subTest(required=required), ExitStack() as stack:
                stack.enter_context(
                    patch.object(
                        main,
                        "ACCESS_SIGNED_STATUS_READINESS_REQUIRED",
                        required,
                    )
                )
                stack.enter_context(
                    patch.object(
                        main,
                        "_configured_target_ids",
                        return_value={TARGET},
                    )
                )
                stack.enter_context(
                    patch.object(
                        main,
                        "_command_provisioning_error",
                        return_value="test stop before broker",
                    )
                )
                configure = stack.enter_context(
                    patch.object(
                        main._authenticated_status_collector_health,
                        "configure",
                    )
                )
                self.assertIsNone(main._start_target_boot_subscriber())
                configure.assert_called_once_with(
                    {topic},
                    require_verified_evidence=required,
                )

    def test_untrusted_rejections_do_not_poison_writer_health(self) -> None:
        event_health = MagicMock()
        event_worker = main._CanonicalAccessEventWorker(
            persist=lambda *_args, **_kwargs: None,
            health=event_health,
        )
        self.assertTrue(event_worker.request("topic", b"{}", False))
        event_worker._queue.join()
        event_health.note_writer_result.assert_not_called()
        event_worker.stop()

        outcomes = iter(
            (
                None,
                False,
                {
                    "advanced": False,
                    "target_id": TARGET,
                    "source_boot_id": BOOT_2,
                    "state": "IDLE",
                },
            )
        )
        status_health = MagicMock()
        status_worker = main._AuthenticatedTargetStatusWorker(
            persist=lambda *_args, **_kwargs: next(outcomes),
            registry=MagicMock(),
            health=status_health,
        )
        status_worker.connect_transport()
        for _ in range(3):
            self.assertTrue(status_worker.request(TARGET, b"{}", False))
        status_worker._queue.join()
        self.assertEqual(
            [call(False), call(True)],
            status_health.note_writer_result.call_args_list,
        )
        status_worker.stop()

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

    def test_subscriber_uses_verified_backend_identity_and_treats_boot_as_advisory(self) -> None:
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
            persist = stack.enter_context(
                patch.object(main, "_persist_authenticated_target_status")
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
            persist.assert_not_called()
            request_refresh.assert_not_called()
            client._sgk_authenticated_status_worker.stop()

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
                    main,
                    "_persist_authenticated_target_status",
                    return_value={
                        "advanced": True,
                        "target_id": TARGET,
                        "source_boot_id": BOOT_2,
                        "source_boot_count": 9,
                        "status_revision": 14,
                        "state": "IDLE",
                        "relay_commanded_on": False,
                        "relay_pin_level": 1,
                        "boot_refresh_outcome": BootRefreshOutcome.UNCHANGED,
                    },
                )
            )
            signed = stack.enter_context(
                patch.object(main, "_signed_target_command", return_value=True)
            )
            status_applied = threading.Event()

            def publish_side_effect(topic, payload, **_kwargs):
                if (
                    topic
                    == f"gatekeeper/v1/ha-bridge/{TARGET}/availability"
                    and payload == "online"
                ):
                    status_applied.set()
                return MagicMock()

            client.publish.side_effect = publish_side_effect
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
            self.assertTrue(status_applied.wait(timeout=1.0))
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
            client._sgk_ha_availability_expiry.stop()
            client._sgk_authenticated_status_worker.stop()
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

    def test_subscriber_advances_boot_only_after_verified_status_worker(self) -> None:
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
            persist = stack.enter_context(
                patch.object(
                    main,
                    "_persist_authenticated_target_status",
                    side_effect=lambda *_args, **_kwargs: {
                        "advanced": True,
                        "target_id": TARGET,
                        "source_boot_id": BOOT_2,
                        "state": "IDLE",
                        "boot_refresh_outcome": BootRefreshOutcome.ADVANCED,
                    },
                )
            )
            refreshed = threading.Event()
            request_refresh = stack.enter_context(
                patch.object(
                    main,
                    "_request_target_acl_refresh",
                    side_effect=lambda *_args: refreshed.set() or True,
                )
            )
            main._start_target_boot_subscriber()
            client.on_connect(client, None, None, 0)

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
            client.on_message(client, None, boot_message)
            persist.assert_not_called()
            request_refresh.assert_not_called()

            client.on_message(client, None, status_message)
            self.assertTrue(refreshed.wait(timeout=1.0))
            persist.assert_called_once_with(
                TARGET, status_message.payload, retained=False
            )
            request_refresh.assert_called_once_with(TARGET, "target_boot")

            persist.reset_mock()
            status_message.retain = True
            client.on_message(client, None, status_message)
            persist.assert_not_called()
            client._sgk_authenticated_status_worker.stop()

    def test_status_worker_generation_blocks_late_live_effects(self) -> None:
        for invalidation in ("disconnect_transport", "invalidate_live_effects"):
            with self.subTest(invalidation=invalidation):
                started = threading.Event()
                release = threading.Event()
                registry = MagicMock()
                on_verified = MagicMock()

                def persist(*_args, **_kwargs):
                    started.set()
                    self.assertTrue(release.wait(timeout=1.0))
                    return {
                        "advanced": True,
                        "target_id": TARGET,
                        "source_boot_id": BOOT_2,
                        "state": "IDLE",
                        "boot_refresh_outcome": BootRefreshOutcome.ADVANCED,
                    }

                worker = main._AuthenticatedTargetStatusWorker(
                    persist=persist,
                    registry=registry,
                    on_verified=on_verified,
                    capacity=2,
                )
                worker.connect_transport()
                self.assertTrue(worker.request(TARGET, b"{}", False))
                self.assertTrue(started.wait(timeout=1.0))
                getattr(worker, invalidation)()
                release.set()
                worker._queue.join()
                registry.note_verified.assert_not_called()
                on_verified.assert_not_called()
                worker.stop()

    def test_old_status_generation_cannot_satisfy_new_connection_readiness(self) -> None:
        topic = main.target_status_topic(TARGET)
        health = main._CanonicalAccessCollectorHealth()
        health.configure({topic}, require_verified_evidence=True)
        health.begin_connection()
        health.track_subscription(topic, (0, 61))
        health.acknowledge(61, [1])

        started = threading.Event()
        release = threading.Event()
        persist_count = 0

        def persist(*_args, **_kwargs):
            nonlocal persist_count
            persist_count += 1
            if persist_count == 1:
                started.set()
                self.assertTrue(release.wait(timeout=1.0))
            return {
                "advanced": False,
                "target_id": TARGET,
                "source_boot_id": BOOT_2,
                "state": "IDLE",
            }

        worker = main._AuthenticatedTargetStatusWorker(
            persist=persist,
            registry=MagicMock(),
            health=health,
            capacity=2,
        )
        worker.connect_transport()
        self.assertTrue(worker.request(TARGET, b"old", False))
        self.assertTrue(started.wait(timeout=1.0))

        health.disconnect()
        worker.disconnect_transport()
        health.begin_connection()
        health.track_subscription(topic, (0, 62))
        health.acknowledge(62, [1])
        worker.connect_transport()
        release.set()
        worker._queue.join()
        self.assertFalse(health.ready(worker))

        self.assertTrue(worker.request(TARGET, b"new", False))
        worker._queue.join()
        self.assertTrue(health.ready(worker))
        worker.stop()

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
