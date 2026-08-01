import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "protocol" / "tools" / "verify_vectors.py"
SPEC = importlib.util.spec_from_file_location("verify_vectors", MODULE_PATH)
vectors = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(vectors)


class CanonicalVectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / "protocol" / "test_vectors" / "v1.json").open(encoding="utf-8") as handle:
            cls.document = json.load(handle)

    def test_complete_document(self):
        vectors.verify_document(self.document, emit_expected=False)

    def test_cross_door_reuse_changes_signed_input(self):
        original_challenge = vectors.challenge_bytes(self.document["challenge"]["fields"])
        changed = copy.deepcopy(self.document["challenge"]["fields"])
        changed["door_id"] = "10112233445566778899aabbccddeeff"
        changed_challenge = vectors.challenge_bytes(changed)
        proof = vectors.proof_input_bytes(original_challenge, self.document["proof"]["fields"])
        signature = bytes.fromhex(self.document["proof"]["expected"]["signature_raw64"])
        public_key = bytes.fromhex(self.document["proof"]["expected"]["public_key_sec1"])
        self.assertTrue(vectors.verify_raw64(public_key, proof, signature))
        self.assertFalse(
            vectors.verify_raw64(
                public_key,
                vectors.proof_input_bytes(changed_challenge, self.document["proof"]["fields"]),
                signature,
            )
        )

    def test_cross_boot_reuse_changes_signed_input(self):
        changed = copy.deepcopy(self.document["challenge"]["fields"])
        changed["target_boot_id"] = "00eeddccbbaa99887766554433221100"
        changed_proof = vectors.proof_input_bytes(
            vectors.challenge_bytes(changed), self.document["proof"]["fields"]
        )
        signature = bytes.fromhex(self.document["proof"]["expected"]["signature_raw64"])
        public_key = bytes.fromhex(self.document["proof"]["expected"]["public_key_sec1"])
        self.assertFalse(vectors.verify_raw64(public_key, changed_proof, signature))

    def test_cross_session_reuse_changes_signed_input(self):
        changed = copy.deepcopy(self.document["challenge"]["fields"])
        changed["session_id"] = "002132435465768798a9bacbdcedfe0f"
        changed_proof = vectors.proof_input_bytes(
            vectors.challenge_bytes(changed), self.document["proof"]["fields"]
        )
        signature = bytes.fromhex(self.document["proof"]["expected"]["signature_raw64"])
        public_key = bytes.fromhex(self.document["proof"]["expected"]["public_key_sec1"])
        self.assertFalse(vectors.verify_raw64(public_key, changed_proof, signature))

    def test_high_s_signature_is_rejected(self):
        signature = bytes.fromhex(self.document["proof"]["expected"]["signature_raw64"])
        high_s = signature[:32] + (
            vectors.N - int.from_bytes(signature[32:], "big")
        ).to_bytes(32, "big")
        challenge = vectors.challenge_bytes(self.document["challenge"]["fields"])
        proof = vectors.proof_input_bytes(challenge, self.document["proof"]["fields"])
        public_key = bytes.fromhex(self.document["proof"]["expected"]["public_key_sec1"])
        self.assertFalse(vectors.verify_raw64(public_key, proof, high_s))

    def test_default_mtu_frames_reassemble_exactly(self):
        challenge = vectors.challenge_bytes(self.document["challenge"]["fields"])
        frames = vectors.fragment_message(challenge, mtu=23, msg_type=16, message_id=4660)
        self.assertEqual(14, len(frames))
        self.assertEqual(challenge, b"".join(frame[vectors.FRAME_HEADER_SIZE :] for frame in frames))

    def test_unsorted_acl_is_rejected(self):
        acl = copy.deepcopy(self.document["acl"]["fields"])
        second = copy.deepcopy(acl["entries"][0])
        second["credential_id"] = "00000000000000000000000000000000"
        acl["entries"].append(second)
        with self.assertRaisesRegex(ValueError, "sorted"):
            vectors.acl_bytes(acl)

    def test_downgrade_below_floor_has_no_selection(self):
        self.assertIsNone(vectors.negotiate(1, 1, 1, 2, 2))

    def test_rollback_to_supported_previous_version(self):
        self.assertEqual(1, vectors.negotiate(1, 1, 1, 2, 1))

    def test_stale_acl_is_rejected(self):
        self.assertEqual(
            "reject_stale",
            vectors.acl_activation_decision(42, "aa", 41, "bb"),
        )

    def test_equal_acl_does_not_refresh_lease(self):
        self.assertEqual(
            "idempotent_no_lease_refresh",
            vectors.acl_activation_decision(42, "aa", 42, "aa"),
        )


if __name__ == "__main__":
    unittest.main()
