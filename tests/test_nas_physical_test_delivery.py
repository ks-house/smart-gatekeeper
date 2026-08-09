import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NasPhysicalTestDeliveryContractTest(unittest.TestCase):
  def test_delivery_guide_is_indexed_and_preserves_evidence_boundary(self):
    index = (ROOT / "wiki/index.md").read_text(encoding="utf-8")
    guide = (ROOT / "wiki/nas_physical_test_delivery.md").read_text(
        encoding="utf-8"
    )
    self.assertIn("nas_physical_test_delivery.md", index)
    for fragment in (
        "physical_validation_status: pending",
        "production_authorized: false",
        "release_evidence: false",
        "No workflow was dispatched and no NAS byte was written",
        "/docker/smart-gatekeeper-physical-test/firmware-public-canary",
        "/docker/smart-gatekeeper-physical-test/mobile-public-canary",
        "repository-secret-pinned",
        "Runtime `ssh-keyscan`, TOFU, `accept-new`",
    ):
      self.assertIn(fragment, guide)

  def test_connected_secret_contract_is_completely_documented(self):
    from scripts import ota_contract_gate as gate

    guide = (ROOT / "wiki/nas_physical_test_delivery.md").read_text(
        encoding="utf-8"
    )
    for names in gate.PHYSICAL_TEST_CONNECTED_SECRET_NAMES.values():
      for name in names:
        with self.subTest(secret=name):
          self.assertIn(f"`{name}`", guide)

  def test_production_workflow_conditions_and_directories_remain_present(self):
    for relative, production_root in (
        (".github/workflows/deploy.yml", "/docker/smart-gatekeeper-ota/"),
        (
            ".github/workflows/build_app.yml",
            "/docker/smartbox_ota/gatekeeper_apk/",
        ),
    ):
      with self.subTest(workflow=relative):
        source = (ROOT / relative).read_text(encoding="utf-8")
        self.assertIn("inputs.release_target == 'production'", source)
        self.assertIn("environment: production", source)
        self.assertIn(production_root, source)
        self.assertNotIn("StrictHostKeyChecking=no", source)
        self.assertNotIn("ssh-keyscan", source)


if __name__ == "__main__":
  unittest.main()
