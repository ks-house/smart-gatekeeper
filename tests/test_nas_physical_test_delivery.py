import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NasPhysicalTestDeliveryContractTest(unittest.TestCase):
  def test_contract_test_path_triggers_both_producer_workflows(self):
    from scripts import ota_contract_gate as gate

    contract_path = "tests/test_nas_physical_test_delivery.py"
    for relative in (
        ".github/workflows/deploy.yml",
        ".github/workflows/build_app.yml",
    ):
      with self.subTest(workflow=relative, trigger="pull_request"):
        workflow = gate.load_workflow_yaml(
            relative, (ROOT / relative).read_text(encoding="utf-8")
        )
        self.assertIn(contract_path, workflow["on"]["pull_request"]["paths"])
      if relative.endswith("build_app.yml"):
        with self.subTest(workflow=relative, trigger="push"):
          self.assertIn(contract_path, workflow["on"]["push"]["paths"])

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
        "runtime-keyscan-unpinned",
        "bounded runtime `ssh-keyscan`",
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
        self.assertIn("StrictHostKeyChecking=yes", source)
        self.assertIn("timeout 10s ssh-keyscan -T 5", source)
        self.assertIn('2>/dev/null', source)
        self.assertIn('test "${{ inputs.allow_unpinned_host_key }}" = "true"', source)


if __name__ == "__main__":
  unittest.main()
