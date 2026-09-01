from __future__ import annotations

import unittest
import hashlib

from backend.app.access_actor_ref import (
    access_credential_ref,
    access_credential_ref_is_valid,
    access_evidence_mac,
    build_access_event_mac_input,
    build_access_status_mac_input,
    build_mobile_access_session_read_input,
    matches_access_credential_ref,
    parse_access_event_ref_keyring,
)


class AccessActorRefTest(unittest.TestCase):
    def test_cross_language_vector_is_session_and_door_bound(self) -> None:
        key = bytes.fromhex("11" * 32)
        door = "00112233445566778899aabbccddeeff"
        session = "22222222-2222-4222-8222-222222222222"
        credential = "ffeeddccbbaa99887766554433221100"
        value = access_credential_ref("k1", key, door, session, credential)
        self.assertEqual("c_k1_8e1681bdeb8f7c5f392c48ef", value)
        self.assertTrue(access_credential_ref_is_valid(value))
        self.assertTrue(
            matches_access_credential_ref(
                value,
                keyring={"k1": key},
                door_id=door,
                session_id=session,
                credential_id=credential,
            )
        )
        self.assertNotEqual(
            value,
            access_credential_ref(
                "k1",
                key,
                door,
                "33333333-3333-4333-8333-333333333333",
                credential,
            ),
        )

    def test_keyring_and_reference_contract_reject_malformed_values(self) -> None:
        self.assertEqual(
            {"k1": bytes.fromhex("ab" * 32)},
            parse_access_event_ref_keyring('{"k1":"' + "ab" * 32 + '"}'),
        )
        for raw in (
            "[]",
            "{}",
            '{"TOO-LONG":"' + "ab" * 32 + '"}',
            '{"k1":"' + "AB" * 32 + '"}',
            '{"k1":"' + "ab" * 31 + '"}',
            '{"k1":"' + "00" * 32 + '"}',
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_access_event_ref_keyring(raw)
        for value in (None, "", "cred_k1_" + "0" * 24, "c_k1_" + "0" * 23):
            self.assertFalse(access_credential_ref_is_valid(value))

    def test_mobile_access_read_proof_has_fixed_cross_language_layout(self) -> None:
        canonical = build_mobile_access_session_read_input(
            "00112233445566778899aabbccddeeff",
            "10213243-5465-4687-98a9-bacbdcedfe0f",
            "55" * 32,
            0x0102030405060708,
        )
        self.assertEqual(80, len(canonical))
        self.assertEqual(b"SGKASR01", canonical[:8])
        self.assertEqual(
            "53474b4153523031"
            "00112233445566778899aabbccddeeff"
            "102132435465468798a9bacbdcedfe0f"
            + "55" * 32
            + "0102030405060708",
            canonical.hex(),
        )

    def test_authenticated_event_and_status_cross_language_vectors(self) -> None:
        key = bytes.fromhex("11" * 32)
        credential_ref = "c_k1_8e1681bdeb8f7c5f392c48ef"
        event_input = build_access_event_mac_input(
            key_id="k1",
            topic_target_id="sgk-personal-01",
            door_id="00112233445566778899aabbccddeeff",
            source_instance_id="target_0123456789abcdef",
            source_boot_id="aa" * 16,
            source_boot_count=686,
            event_id="11111111-1111-4111-8111-111111111111",
            session_id="22222222-2222-4222-8222-222222222222",
            sequence=7,
            attempt=1,
            event_code="ACCESS_SENSOR_DETECTED",
            stage="SENSOR",
            outcome="SUCCEEDED",
            reason_code="SENSOR_THRESHOLD_MET",
            causation_event_id="33333333-3333-4333-8333-333333333333",
            monotonic_ms=123456789,
            credential_ref=credential_ref,
            distance_mm=420,
            duration_ms=None,
            relay_hold_ms=None,
        )
        self.assertEqual(282, len(event_input))
        self.assertEqual(
            "fd208a51ceca2a76017b06234befd077d9302c4507a504bf0c896939aeffe3fc",
            hashlib.sha256(event_input).hexdigest(),
        )
        self.assertEqual(
            "ee82880739ce2d2ae3a726c641a6dd08",
            access_evidence_mac(key, event_input),
        )

        status_input = build_access_status_mac_input(
            key_id="k1",
            topic_target_id="sgk-personal-01",
            door_id="00112233445566778899aabbccddeeff",
            source_boot_id="aa" * 16,
            source_boot_count=686,
            access_revision=42,
            state="IDLE",
            last_terminal_session_id=(
                "22222222-2222-4222-8222-222222222222"
            ),
            last_terminal_event_sequence=11,
            last_terminal_event_code="ACCESS_SESSION_COMPLETED",
            last_terminal_reason_code="ACCESS_GRANTED",
            last_terminal_credential_ref=credential_ref,
            last_terminal_phase_mask=0x001F,
            relay_commanded_on=False,
            relay_pin_level=1,
        )
        self.assertEqual(203, len(status_input))
        self.assertEqual(
            "4d171b5fdb6d1de6539dcc966e1c22d8a46f7cf9672bd47e0d4adcbcb9a46c86",
            hashlib.sha256(status_input).hexdigest(),
        )
        self.assertEqual(
            "ee13d37c543d4a8e5a046a7fc4cb7a86",
            access_evidence_mac(key, status_input),
        )


if __name__ == "__main__":
    unittest.main()
