import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ota_contract_gate as gate  # noqa: E402


class OtaContractGateTest(unittest.TestCase):
  def test_contract_assets_and_dual_slot_pass(self):
    gate.validate_contract()

  def test_target_tamper_is_rejected(self):
    manifest = gate.load_json(gate.OTA / "test-vectors" / "target-valid.json")
    tampered = copy.deepcopy(manifest)
    tampered["sha256"] = "f" * 64
    with self.assertRaisesRegex(gate.GateError, "signature"):
      gate.validate_manifest(
          tampered, "target-manifest.schema.json", gate.TEST_PUBLIC_KEY_HEX
      )

  def test_mobile_fallback_must_be_independent(self):
    manifest = gate.load_json(gate.OTA / "test-vectors" / "mobile-valid.json")
    manifest["fallback_url"] = manifest["apk_url"]
    with self.assertRaisesRegex(gate.GateError, "fallback_url"):
      gate.validate_manifest(
          manifest, "mobile-manifest.schema.json", gate.TEST_PUBLIC_KEY_HEX
      )

  def test_pending_hardware_evidence_blocks_release(self):
    with self.assertRaisesRegex(gate.GateError, "incomplete gates"):
      gate.validate_release_evidence(gate.OTA / "release-evidence.json")

  def test_release_manifest_requires_matching_pinned_key(self):
    vector = gate.OTA / "test-vectors" / "target-valid.json"
    gate.validate_release_manifests([vector], gate.TEST_PUBLIC_KEY_HEX)
    with self.assertRaisesRegex(gate.GateError, "signature"):
      gate.validate_release_manifests([vector], "00" * 32)


if __name__ == "__main__":
  unittest.main()
