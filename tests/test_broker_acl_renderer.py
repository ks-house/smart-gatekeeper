"""Exact principal scope, injection and candidate-file preservation regressions."""
import copy
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

from scripts.render_broker_acl import render_acl

ROOT = Path(__file__).resolve().parents[1]
PROFILE = dict(schema_version=1, targets=["target-a", "target-b"],
               backend_username="backend-user", ha_username="ha-user",
               diagnostic_usernames=["read-only"], discovery_device_id="gatekeeper-unit")


class BrokerAclRendererTest(unittest.TestCase):
    def test_expands_exact_targets_and_preserves_backend_and_ha_flows(self):
        acl = render_acl(PROFILE)
        self.assertFalse(any(line.startswith("pattern ") for line in acl.splitlines()))
        self.assertNotIn("/+/", acl.split("user ha-user")[0].split("user backend-user")[0])
        self.assertIn("topic read gatekeeper/v1/targets/target-a/acl", acl)
        self.assertIn("topic write gatekeeper/v1/targets/target-b/canonical-event", acl)
        self.assertIn("topic read gatekeeper/v1/targets/target-b/canonical-event",
                      acl.split("user backend-user")[1].split("user ha-user")[0])
        self.assertIn("topic write gatekeeper/v1/ha-bridge/target-a/request/+", acl)
        self.assertIn("homeassistant/sensor/gatekeeper-unit/+/config", acl)

    def test_diagnostic_principal_has_only_exact_observer_reads(self):
        acl = render_acl(PROFILE).split("user read-only", 1)[1]
        rules = [line for line in acl.splitlines() if line.startswith("topic ")]
        self.assertEqual(12, len(rules))
        self.assertTrue(all(line.startswith("topic read ") for line in rules))
        self.assertFalse(any(token in acl for token in ["/command", "/acl", "/canonical-event", "/+/"]))

    def test_principal_role_collisions_and_topic_injection_fail_closed(self):
        for value in ["target-a", "ha-user", "bad/name", "+", "#", "%u", "ok\nuser attacker", ""]:
            profile = copy.deepcopy(PROFILE)
            profile["backend_username"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                render_acl(profile)
        for field, value in [("targets", ["target-a", "target-a"]),
                             ("schema_version", True), ("diagnostic_usernames", ["ha-user"])]:
            profile = copy.deepcopy(PROFILE)
            profile[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                render_acl(profile)

    def test_password_fields_and_unexpected_template_global_rules_are_rejected(self):
        profile = {**PROFILE, "password": "not-a-production-secret"}
        with self.assertRaises(ValueError):
            render_acl(profile)
        template = (ROOT / "security/target-acl").read_text()
        with self.assertRaises(ValueError):
            render_acl(PROFILE, template + "\npattern write gatekeeper/#\n")
        with self.assertRaises(ValueError):
            render_acl(PROFILE, template + "\nuser unexpected\ntopic read #\n")

    def test_inventory_reordering_cannot_change_the_rendered_policy(self):
        reordered = copy.deepcopy(PROFILE)
        reordered["targets"].reverse()
        self.assertEqual(render_acl(PROFILE), render_acl(reordered))

    def test_cli_creates_private_candidate_and_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.json"
            candidate = Path(tmp) / "candidate.acl"
            inventory.write_text(json.dumps(PROFILE))
            command = [sys.executable, str(ROOT / "scripts/render_broker_acl.py"),
                       "--inventory", str(inventory), "--output", str(candidate)]
            completed = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertFalse(json.loads(completed.stdout)["production_installed"])
            self.assertNotIn("target-a", completed.stdout)
            self.assertEqual(0o600, stat.S_IMODE(candidate.stat().st_mode))
            original = candidate.read_bytes()
            refused = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(0, refused.returncode)
            self.assertEqual(original, candidate.read_bytes())


if __name__ == "__main__":
    unittest.main()
