import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "ota" / "hardwareless-implementation-gates.json"


class HardwarelessImplementationGateTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    with CONTRACT_PATH.open(encoding="utf-8") as handle:
      cls.contract = json.load(handle)

  def test_contract_has_exact_two_tier_authorization(self):
    self.assertEqual(self.contract["schema_version"], 1)
    self.assertEqual(set(self.contract["gates"]), {"G0-SW", "G0-HW"})

    software = self.contract["gates"]["G0-SW"]
    self.assertEqual(software["status"], "passed")
    self.assertEqual(software["authorization"], "hardwareless_rc_only")
    self.assertEqual(software["issues_authorized"], [17, 18, 19, 20, 21, 22])
    self.assertEqual(software["requires_wave0_contracts"], [14, 15, 16, 23])
    self.assertTrue(software["implementation_review_merge_allowed"])
    self.assertTrue(software["automated_unit_integration_virtual_e2e_allowed"])
    self.assertTrue(software["feature_flag_required"])
    self.assertFalse(software["production_enable_allowed"])
    self.assertFalse(software["physical_completion_claim_allowed"])

    production = self.contract["gates"]["G0-HW"]
    self.assertEqual(production["status"], "pending")
    self.assertEqual(production["authorization"], "production")
    self.assertFalse(production["production_enable_allowed"])
    self.assertFalse(production["legacy_retirement_allowed"])
    self.assertFalse(production["epic_closure_allowed"])

  def test_production_requires_physical_and_ota_evidence(self):
    production = self.contract["gates"]["G0-HW"]
    required = set(production["required_evidence"])
    self.assertEqual(
        required,
        {
            "samsung_oem_ble_wake",
            "esp32_c6_real_ble_gatt_radio_coexistence",
            "relay_one_shot_and_fail_safe",
            "sensor_real_passage_detection",
            "bootloader_dual_slot_health_rollback_power_loss",
            "ota_g1_through_g4",
            "mobile_target_n_n_minus_1",
            "periodic_https_and_authenticated_local_recovery",
            "manual_updater_independence_and_mobile_fallback",
            "relay_g0_through_g2",
            "physical_e2e_and_staged_rollout",
        },
    )
    self.assertEqual(production["ota_gates_required"], ["OTA-G1", "OTA-G2", "OTA-G3", "OTA-G4"])
    self.assertEqual(production["issues_must_remain_open"], [13, 14, 18, 22, 23])

  def test_manual_remote_legacy_and_release_invariants_are_non_negotiable(self):
    invariants = self.contract["invariants"]
    self.assertEqual(
        invariants,
        {
            "authenticated_mobile_manual_remote_preserved": True,
            "legacy_rollback_path_preserved": True,
            "production_release_fail_closed": True,
            "target_dual_slot_health_rollback_preserved": True,
            "target_periodic_https_preserved": True,
            "target_authenticated_local_recovery_preserved": True,
            "mobile_manual_updater_independent": True,
            "mobile_target_n_n_minus_1_preserved": True,
        },
    )

  def test_current_release_evidence_still_blocks_production(self):
    evidence_path = ROOT / self.contract["production_release_evidence"]
    with evidence_path.open(encoding="utf-8") as handle:
      evidence = json.load(handle)
    self.assertTrue(evidence["release_blocked"])
    self.assertEqual(evidence["physical_tests"], "pending")
    gates = {gate["id"]: gate["status"] for gate in evidence["gates"]}
    self.assertEqual(gates["OTA-G0"], "passed")
    for gate_id in ("OTA-G1", "OTA-G2", "OTA-G3", "OTA-G4"):
      self.assertEqual(gates[gate_id], "pending")


if __name__ == "__main__":
  unittest.main()
