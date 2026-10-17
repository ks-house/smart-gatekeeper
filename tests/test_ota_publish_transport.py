import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
JOBS = [
    ("build_app.yml", "publish_personal_mobile_ota"),
    ("deploy.yml", "publish_personal_target_ota"),
]


def job(filename, name):
    return yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())["jobs"][name]


def step_named(config, name):
    return next(s for s in config["steps"] if s.get("name") == name)


def outputs(path):
    result = {}
    if not path.exists():
        return result
    lines = iter(path.read_text().splitlines())
    for line in lines:
        key, marker = line.split("<<", 1)
        value = []
        for current in lines:
            if current == marker:
                break
            value.append(current)
        result[key] = "\n".join(value)
    return result


class OtaPublishTransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        key = Path(cls.fixture.name) / "host"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                       check=True, capture_output=True)
        cls.public_key = key.with_suffix(".pub").read_text().split()
        cls.public_pin = "[nas.example.test]:4222 " + " ".join(cls.public_key[:2]) + "\n"

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def environment(self, work, **changes):
        env = {
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            "OTA_PUBLISH_TRANSPORT": "public",
            "PUBLIC_NAS_HOST": "nas.example.test",
            "PUBLIC_NAS_PORT": "4222",
            "PUBLIC_NAS_KNOWN_HOSTS": self.public_pin,
            "TAILNET_NAS_HOST": "100.95.243.92",
            "TAILNET_NAS_PORT": "8822",
            "TS_OIDC_CLIENT_ID": "test-identity-never-log",
            "TS_OIDC_AUDIENCE": "test-audience-never-log",
            "GITHUB_OUTPUT": str(work / "output"),
        }
        env.update(changes)
        return env

    def execute(self, changes, success=True):
        results = []
        for filename, name in JOBS:
            config = job(filename, name)
            shell = step_named(config, "Select OTA publication transport without fallback")["run"]
            with tempfile.TemporaryDirectory() as temp:
                work = Path(temp)
                run = subprocess.run(["bash", "-euc", shell], env=self.environment(work, **changes),
                                     capture_output=True, text=True, timeout=15)
                self.assertEqual(run.returncode == 0, success, run.stderr)
                self.assertNotIn("test-identity-never-log", run.stdout + run.stderr)
                self.assertNotIn("test-audience-never-log", run.stdout + run.stderr)
                found = outputs(work / "output")
                if not success:
                    self.assertEqual(found, {})
                results.append(found)
        return results

    def test_default_preserves_public_endpoint_and_pin(self):
        for result in self.execute({}):
            self.assertEqual(result["mode"], "public")
            self.assertEqual(result["host"], "nas.example.test")
            self.assertEqual(result["port"], "4222")
            self.assertEqual(result["known_hosts"], self.public_pin)

    def test_empty_mode_is_legacy_default(self):
        self.execute({"OTA_PUBLISH_TRANSPORT": ""})

    def test_private_rebinds_same_server_key_without_new_trust(self):
        for result in self.execute({"OTA_PUBLISH_TRANSPORT": "tailscale"}):
            self.assertEqual(result["mode"], "tailscale")
            self.assertEqual(result["host"], "100.95.243.92")
            self.assertEqual(result["port"], "8822")
            parts = result["known_hosts"].split()
            self.assertEqual(parts[0], "[100.95.243.92]:8822")
            self.assertEqual(parts[1:], self.public_key[:2])

    def test_private_port_22_uses_normal_host_label(self):
        for result in self.execute({"OTA_PUBLISH_TRANSPORT": "tailscale", "TAILNET_NAS_PORT": "22"}):
            self.assertEqual(result["known_hosts"].split()[0], "100.95.243.92")

    def test_private_missing_identity_never_falls_back(self):
        for key in ["TS_OIDC_CLIENT_ID", "TS_OIDC_AUDIENCE"]:
            self.execute({"OTA_PUBLISH_TRANSPORT": "tailscale", key: ""}, success=False)

    def test_private_rejects_public_dns_loopback_and_outside_shared_range(self):
        for host in ["nas.example.test", "127.0.0.1", "192.168.1.1", "100.63.255.255", "100.128.0.1", "8.8.8.8"]:
            self.execute({"OTA_PUBLISH_TRANSPORT": "tailscale", "TAILNET_NAS_HOST": host}, success=False)

    def test_private_rejects_wrong_original_host_pin(self):
        self.execute({"OTA_PUBLISH_TRANSPORT": "tailscale",
                      "PUBLIC_NAS_KNOWN_HOSTS": self.public_pin.replace("nas.example.test", "wrong.example.test")},
                     success=False)

    def test_private_rejects_invalid_original_key(self):
        self.execute({"OTA_PUBLISH_TRANSPORT": "tailscale",
                      "PUBLIC_NAS_KNOWN_HOSTS": "[nas.example.test]:4222 ssh-ed25519 invalid-key\n"},
                     success=False)

    def test_rejects_unknown_mode_and_invalid_ports_before_output(self):
        self.execute({"OTA_PUBLISH_TRANSPORT": "private-typo"}, success=False)
        for port in ["0", "65536", "8822\nmode=public", "+8822", "not-a-port"]:
            self.execute({"OTA_PUBLISH_TRANSPORT": "tailscale", "TAILNET_NAS_PORT": port}, success=False)

    def test_empty_pins_and_injected_host_are_rejected(self):
        self.execute({"PUBLIC_NAS_KNOWN_HOSTS": ""}, success=False)
        self.execute({"PUBLIC_NAS_HOST": "nas.example.test\nmode=tailscale"}, success=False)

    def test_both_workflows_share_exact_selector_and_pinned_join(self):
        selectors = []
        for filename, name in JOBS:
            config = job(filename, name)
            self.assertEqual(config["environment"], "personal-auto-ota")
            self.assertEqual(config["permissions"], {"contents": "read", "id-token": "write"})
            selector = step_named(config, "Select OTA publication transport without fallback")
            selectors.append(selector["run"])
            self.assertIn("|| 'public'", selector["env"]["OTA_PUBLISH_TRANSPORT"])
            join = step_named(config, "Join private OTA publisher network")
            self.assertEqual(join["if"], "steps.ota_transport.outputs.mode == 'tailscale'")
            self.assertEqual(join["uses"], "tailscale/github-action@306e68a486fd2350f2bfc3b19fcd143891a4a2d8")
            self.assertEqual(join["with"]["version"], "1.94.2")
            self.assertEqual(config["concurrency"]["cancel-in-progress"], False)
            steps = config["steps"]
            after = steps[steps.index(join) + 1:]
            envs = [s["env"] for s in after if "NAS_HOST" in s.get("env", {})]
            self.assertTrue(envs)
            for env in envs:
                self.assertEqual(env["NAS_HOST"], "${{ steps.ota_transport.outputs.host }}")
                self.assertEqual(env["NAS_PORT"], "${{ steps.ota_transport.outputs.port }}")
            self.assertNotIn("ssh-keyscan", selector["run"])
        self.assertEqual(selectors[0], selectors[1])

    def preflight(self, host="100.95.243.92", sftp_success=True, directory="/docker/smartbox_ota/firmware/"):
        config = job("backend_security.yml", "nas_private_status_preflight")
        step = step_named(config, "Verify existing OTA publisher identity over private SFTP without publishing")
        self.assertEqual(step["if"], "inputs.verify_ota_sftp")
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            (work / "sgk-ssh").mkdir()
            (work / "build").mkdir()
            (work / "sgk-ssh/known_hosts").write_text(
                "[100.95.243.92]:8822 " + " ".join(self.public_key[:2]) + "\n")
            fake = work / "sshpass"
            fake.write_text("#!/bin/sh\nprintf called > \"$RUNNER_TEMP/called\"\nexit " + ("0" if sftp_success else "42") + "\n")
            fake.chmod(0o700)
            env = {
                **os.environ,
                "PATH": str(work) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
                "RUNNER_TEMP": str(work), "NAS_HOST": host, "NAS_PORT": "8822",
                "NAS_USER": "test-publisher", "NAS_PASSWORD": "never-log-password",
                "NAS_TARGET_DIR": directory, "NAS_APK_TARGET_DIR": "/docker/smartbox_ota/gatekeeper_apk",
            }
            run = subprocess.run(["bash", "-euc", step["run"]], cwd=work, env=env,
                                 capture_output=True, text=True, timeout=15)
            evidence = work / "build/nas-private-status.evidence"
            captured = evidence.read_text() if evidence.exists() else ""
            batch = work / "sgk-private-sftp-readonly.batch"
            commands = batch.read_text().splitlines() if batch.exists() else []
            self.assertNotIn("never-log-password", run.stdout + run.stderr + captured)
            return run.returncode, captured, commands, (work / "called").exists()

    def test_manual_preflight_records_only_successful_readonly_session(self):
        rc, evidence, commands, called = self.preflight()
        self.assertEqual(rc, 0)
        self.assertTrue(called)
        self.assertEqual(evidence, "private_sftp_readonly_ok=true\n")
        self.assertEqual([c.split()[0] for c in commands], ["cd", "pwd", "cd", "pwd"])

    def test_manual_preflight_failure_produces_no_success_evidence(self):
        rc, evidence, commands, called = self.preflight(sftp_success=False)
        self.assertNotEqual(rc, 0)
        self.assertTrue(called)
        self.assertEqual(evidence, "")

    def test_manual_preflight_rejects_non_tailnet_and_traversal_before_auth(self):
        for changes in [{"host": "100.1.2.3"}, {"directory": "/docker/../private"}]:
            rc, evidence, commands, called = self.preflight(**changes)
            self.assertNotEqual(rc, 0)
            self.assertFalse(called)
            self.assertEqual(evidence, "")


    def test_gate_rejects_selector_or_join_policy_mutations(self):
        from scripts import ota_contract_gate as gate
        import copy
        for filename, name in JOBS:
            original = job(filename, name)
            anchor = ("Prepare strict NAS host identity for personal mobile OTA"
                      if filename == "build_app.yml" else
                      "Stage read back and atomically publish Target OTA")
            count = 2 if filename == "build_app.yml" else 1
            for mutation in ["unconditional", "unpinned_action", "broader_permissions",
                             "selector_bypass", "skip_selector", "public_fallback"]:
                config = copy.deepcopy(original)
                selector = step_named(config, "Select OTA publication transport without fallback")
                join = step_named(config, "Join private OTA publisher network")
                if mutation == "unconditional":
                    join["if"] = "always()"
                elif mutation == "unpinned_action":
                    join["uses"] = "tailscale/github-action@main"
                elif mutation == "broader_permissions":
                    config["permissions"]["contents"] = "write"
                elif mutation == "selector_bypass":
                    selector["run"] += "\necho bypass\n"
                elif mutation == "skip_selector":
                    selector["continue-on-error"] = True
                elif mutation == "public_fallback":
                    consumer = next(s for s in config["steps"][config["steps"].index(join) + 1:]
                                    if "NAS_HOST" in s.get("env", {}))
                    consumer["env"]["NAS_HOST"] = "${{ secrets.NAS_HOST }}"
                with self.subTest(filename=filename, mutation=mutation):
                    with self.assertRaises(gate.GateError):
                        gate._validated_ota_transport_job(filename, config, anchor, count)

    def test_exact_extension_preserves_legacy_validation_surface(self):
        from scripts import ota_contract_gate as gate
        for filename, name in JOBS:
            config = job(filename, name)
            anchor = ("Prepare strict NAS host identity for personal mobile OTA"
                      if filename == "build_app.yml" else
                      "Stage read back and atomically publish Target OTA")
            count = 2 if filename == "build_app.yml" else 1
            canonical = gate._validated_ota_transport_job(filename, config, anchor, count)
            self.assertNotIn("permissions", canonical)
            self.assertFalse(any(s.get("id") == "ota_transport" for s in canonical["steps"]))
            self.assertEqual(
                gate._validated_ota_transport_job(filename, canonical, anchor, count),
                canonical,
            )



if __name__ == "__main__":
    unittest.main()
