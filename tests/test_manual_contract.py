import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANUALS = ROOT / "manuals"
FIXTURE = MANUALS / "walkthrough-fixtures-v1.json"
PRODUCT_BASE = "e42d1f417a555b17d7476522aa48f7e4d72306b7"

CORE_MANUALS = (
    "general_user_manual_ko.md",
    "administrator_manual_ko.md",
    "installer_service_manual_ko.md",
    "privacy_notice_ko.md",
    "support_incident_handbook_ko.md",
    "product_gap_register_v1.md",
    "hardwareless_walkthrough_ko.md",
)

REQUIRED_FIELDS = {
    "id",
    "actor",
    "manual",
    "precondition",
    "input",
    "observable_output",
    "code_api_owner",
    "evidence",
    "command",
    "expected",
    "expected_exit_code",
    "timeout",
    "bounded_retry",
    "escalation",
    "remaining_gate",
}

EXPECTED_SCENARIO_EXECUTION = {
    "HWL-USER-01": (
        "python -S -m unittest tests.test_manual_contract.ManualContractTests."
        "test_user01_consent_disclosure_flutter_contract_source -v",
        "test_user01_consent_disclosure_flutter_contract_source",
    ),
    "HWL-USER-02": (
        "python -S -m unittest tests.test_manual_contract.ManualContractTests."
        "test_user02_recovery_shell_flutter_contract_source -v",
        "test_user02_recovery_shell_flutter_contract_source",
    ),
    "HWL-USER-03": (
        "python -S -m unittest tests.test_hardwareless_rc."
        "HardwarelessRcProductionCoreTest.test_production_cpp_core -v",
        "test_production_cpp_core",
    ),
    "HWL-USER-04": (
        "python -S -m unittest tests.test_manual_source_contract."
        "ManualSourceContractTests.test_user04_mobile_manifest_mutation_suite_binding -v",
        "test_user04_mobile_manifest_mutation_suite_binding",
    ),
    "HWL-ADMIN-01": (
        "python -S -m unittest tests.test_manual_source_contract."
        "ManualSourceContractTests.test_admin01_auth_denial_suite_binding -v",
        "test_admin01_auth_denial_suite_binding",
    ),
    "HWL-ADMIN-02": (
        "python -S -m unittest tests.test_manual_source_contract."
        "ManualSourceContractTests.test_admin02_two_person_publish_suite_binding -v",
        "test_admin02_two_person_publish_suite_binding",
    ),
    "HWL-ADMIN-03": (
        "python -S -m unittest tests.test_target_security_ota -v",
        "test_signed_command_is_target_boot_and_freshness_bound",
    ),
    "HWL-ADMIN-04": (
        "python -S -m unittest tests.test_manual_source_contract."
        "ManualSourceContractTests.test_admin04_restore_integrity_suite_binding -v",
        "test_admin04_restore_integrity_suite_binding",
    ),
    "HWL-ADMIN-05": (
        "python -S -m unittest tests.test_manual_source_contract."
        "ManualSourceContractTests.test_admin05_readiness_fail_closed_suite_binding -v",
        "test_admin05_readiness_fail_closed_suite_binding",
    ),
    "HWL-ADMIN-06": (
        "python -S -m unittest tests.test_manual_source_contract."
        "ManualSourceContractTests.test_admin06_support_consent_suite_binding -v",
        "test_admin06_support_consent_suite_binding",
    ),
    "HWL-ADMIN-07": (
        "python -S -m unittest tests.test_manual_source_contract."
        "ManualSourceContractTests.test_admin07_retention_idempotency_suite_binding -v",
        "test_admin07_retention_idempotency_suite_binding",
    ),
    "HWL-INSTALL-01": (
        "python -S -m unittest tests.test_manual_contract.ManualContractTests."
        "test_installation_tokens_match_current_config -v",
        "test_installation_tokens_match_current_config",
    ),
    "HWL-INSTALL-02": (
        "python -S -m unittest tests.test_target_security_ota.TargetSecurityAndOtaTest."
        "test_ota_runtime_uses_one_verified_inactive_slot_engine -v",
        "test_ota_runtime_uses_one_verified_inactive_slot_engine",
    ),
    "HWL-SUPPORT-01": (
        "python -S -m unittest tests.test_manual_contract.ManualContractTests."
        "test_support01_app_error_logger_flutter_contract_source -v",
        "test_support01_app_error_logger_flutter_contract_source",
    ),
    "HWL-SUPPORT-02": (
        "python -S -m unittest tests.test_manual_source_contract."
        "ManualSourceContractTests.test_support02_reconciliation_suite_binding -v",
        "test_support02_reconciliation_suite_binding",
    ),
    "HWL-SUPPORT-03": (
        "python -S -m unittest tests.test_manual_source_contract."
        "ManualSourceContractTests.test_support03_bounded_connect_suite_binding -v",
        "test_support03_bounded_connect_suite_binding",
    ),
}


class ManualContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_is_hardwareless_and_cannot_claim_physical_completion(self) -> None:
        self.assertEqual("sgk-manual-walkthrough-v1", self.fixture["schema_version"])
        self.assertEqual(PRODUCT_BASE, self.fixture["product_base"])
        self.assertEqual("hardwareless", self.fixture["evidence_level"])
        self.assertIs(False, self.fixture["physical_completion_allowed"])

    def test_sixteen_unique_complete_scenarios_cover_every_operational_actor(self) -> None:
        scenarios = self.fixture["scenarios"]
        self.assertEqual(16, len(scenarios))
        self.assertEqual(len(scenarios), len({item["id"] for item in scenarios}))
        self.assertEqual(set(EXPECTED_SCENARIO_EXECUTION), {item["id"] for item in scenarios})
        for item in scenarios:
            self.assertEqual(REQUIRED_FIELDS, set(item))
            for key, value in item.items():
                if key == "expected_exit_code":
                    self.assertIsInstance(value, int)
                    self.assertEqual(0, value)
                else:
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip(), f"{item['id']} has empty {key}")
            self.assertIn(item["manual"], CORE_MANUALS)
            expected_command, expected_token = EXPECTED_SCENARIO_EXECUTION[item["id"]]
            self.assertEqual(expected_command, item["command"], item["id"])
            self.assertEqual(expected_token, item["expected"], item["id"])
        prefixes = {item["id"].split("-")[1] for item in scenarios}
        self.assertEqual({"USER", "ADMIN", "INSTALL", "SUPPORT"}, prefixes)
        self.assertEqual(
            {
                "HWL-ADMIN-04",
                "HWL-ADMIN-05",
                "HWL-ADMIN-06",
                "HWL-ADMIN-07",
                "HWL-SUPPORT-03",
            },
            {
                item["id"]
                for item in scenarios
                if item["id"] in {
                    "HWL-ADMIN-04",
                    "HWL-ADMIN-05",
                    "HWL-ADMIN-06",
                    "HWL-ADMIN-07",
                    "HWL-SUPPORT-03",
                }
            },
        )

    def test_core_manuals_are_utf8_lf_without_stale_product_baseline(self) -> None:
        for name in ("README.md", *CORE_MANUALS):
            raw = (MANUALS / name).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), name)
            self.assertNotIn(b"\r\n", raw, name)
            text = raw.decode("utf-8")
            self.assertIn("0.3.0-rc.1", text, name)
            self.assertIn(PRODUCT_BASE, text, name)
            self.assertNotIn("c654a18f0fa278e4530229bb881fe88286d25c2e", text, name)
            self.assertNotIn("제품 기준: `1ce7f16", text, name)

        for path in (FIXTURE, Path(__file__)):
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), str(path))
            self.assertNotIn(b"\r\n", raw, str(path))

    def test_markdown_relative_links_resolve(self) -> None:
        link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
        for path in MANUALS.glob("*.md"):
            for target in link_pattern.findall(path.read_text(encoding="utf-8")):
                target = target.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved = (path.parent / target).resolve()
                self.assertTrue(resolved.exists(), f"{path.name}: missing {target}")

    def test_manuals_preserve_fail_closed_state_and_evidence_boundaries(self) -> None:
        corpus = "\n".join(
            (MANUALS / name).read_text(encoding="utf-8") for name in CORE_MANUALS
        )
        for token in (
            "RECONCILIATION_REQUIRED",
            "EFFECT_UNKNOWN",
            "duplicate_uncertain",
            "PHYSICAL PENDING",
            "PRODUCTION PENDING",
            "bounded retry",
            "Observable output",
            "Escalation",
        ):
            self.assertIn(token, corpus)
        self.assertNotIn("setInsecure()로 우회", corpus)
        self.assertNotIn("CI가 통과하면 물리", corpus)

    def test_every_procedure_table_exposes_the_nine_required_fields(self) -> None:
        required_headers = (
            "Actor",
            "Preconditions",
            "Input",
            "Observable output",
            "Code/API owner",
            "Evidence artifact",
            "Timeout",
            "Bounded retry",
            "Escalation",
        )
        procedure_manuals = (
            "general_user_manual_ko.md",
            "administrator_manual_ko.md",
            "installer_service_manual_ko.md",
            "privacy_notice_ko.md",
            "support_incident_handbook_ko.md",
        )
        count = 0
        for name in procedure_manuals:
            for line in (MANUALS / name).read_text(encoding="utf-8").splitlines():
                if not line.startswith("|") or "Actor" not in line:
                    continue
                count += 1
                for header in required_headers:
                    self.assertIn(header, line, f"{name}: incomplete procedure header")
        self.assertGreaterEqual(count, 20)

    def test_installation_tokens_match_current_config(self) -> None:
        installer = (MANUALS / "installer_service_manual_ko.md").read_text(
            encoding="utf-8"
        )
        config = (ROOT / "include" / "config.h").read_text(encoding="utf-8")
        for token in ("GPIO3", "GPIO10", "GPIO11", "3.3V", "High-Z", "flyback"):
            self.assertIn(token, installer)
        self.assertRegex(config, r"PIN_TRIG\s*=\s*10")
        self.assertRegex(config, r"PIN_ECHO\s*=\s*11")
        self.assertRegex(config, r"PIN_RELAY\s*=\s*3")
        self.assertRegex(config, r"RELAY_ACTIVE_LOW\s*=\s*true")

    def test_fixture_contains_no_secret_material_or_production_claim(self) -> None:
        raw = FIXTURE.read_text(encoding="utf-8")
        for forbidden in (
            "BEGIN PRIVATE KEY",
            "SECRET_",
            "mqtt://",
            "production_completed",
            '"physical_completion_allowed": true',
        ):
            self.assertNotIn(forbidden, raw)

    def test_user01_consent_disclosure_flutter_contract_source(self) -> None:
        test_source = (
            ROOT / "gatekeeper_app" / "test" / "background_setup_test.dart"
        ).read_text(encoding="utf-8")
        production_source = (
            ROOT
            / "gatekeeper_app"
            / "lib"
            / "screens"
            / "background_disclosure_screen.dart"
        ).read_text(encoding="utf-8")
        for token in (
            "consent gate performs zero requests before explicit consent",
            "disclosure requires an explicit action and supports deferral",
            "expect(gateway.foregroundRequests, 0)",
            "expect(gateway.alwaysRequests, 0)",
            "expect(gateway.batteryRequests, 0)",
            "background-consent-defer",
            "background-consent-accept",
        ):
            self.assertIn(token, test_source)
        self.assertIn("BackgroundDisclosureScreen", production_source)

    def test_user02_recovery_shell_flutter_contract_source(self) -> None:
        test_source = (
            ROOT / "gatekeeper_app" / "test" / "background_setup_test.dart"
        ).read_text(encoding="utf-8")
        production_source = (
            ROOT
            / "gatekeeper_app"
            / "lib"
            / "screens"
            / "recovery_shell_screen.dart"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "recovery shell keeps manual update diagnostics settings and retry reachable",
            test_source,
        )
        for token in (
            "Manual local / remote recovery",
            "Privacy-redacted diagnostics",
            "Check verified app update",
            "Open Android settings",
            "retry-background-setup",
        ):
            self.assertIn(token, test_source)
            self.assertIn(token, production_source)

    def test_support01_app_error_logger_flutter_contract_source(self) -> None:
        test_source = (
            ROOT / "gatekeeper_app" / "test" / "error_logger_test.dart"
        ).read_text(encoding="utf-8")
        production_source = (
            ROOT / "gatekeeper_app" / "lib" / "services" / "error_logger.dart"
        ).read_text(encoding="utf-8")
        for test_title in (
            "normal and error sinks redact PII, credentials, MACs, and URL queries",
            "service IPC is redacted again before UI and support storage",
        ):
            self.assertIn(test_title, test_source)
        for token in (
            "AppErrorLogger",
            "syncFromService",
            "[SENSITIVE_REDACTED]",
            "[DEVICE_REDACTED]",
            "[URL_REDACTED]",
        ):
            self.assertIn(token, test_source)
            self.assertIn(token, production_source)

    def test_walkthrough_commands_are_bounded_read_only_and_reproducible(self) -> None:
        command_pattern = re.compile(
            r"^python -S -m unittest [A-Za-z0-9_.]+(?: [A-Za-z0-9_.]+)* -v$"
        )
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        for item in self.fixture["scenarios"]:
            command = item["command"]
            self.assertRegex(command, command_pattern, item["id"])
            self.assertTrue(
                command.startswith("python -S -m unittest tests."), item["id"]
            )
            for forbidden in (";", "&&", "||", "|", ">", "<", "--failfast"):
                self.assertNotIn(forbidden, command, item["id"])
            argv = command.split()
            argv[0] = sys.executable
            completed = subprocess.run(
                argv,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                env=environment,
                check=False,
            )
            combined = completed.stdout + completed.stderr
            self.assertEqual(
                item["expected_exit_code"],
                completed.returncode,
                f"{item['id']} failed:\n{combined}",
            )
            self.assertIn(item["expected"], combined, item["id"])

    def test_issue52_operations_contract_is_exactly_traced(self) -> None:
        main_source = (ROOT / "backend" / "app" / "main.py").read_text(
            encoding="utf-8"
        )
        for token in (
            '@app.get("/live", status_code=status.HTTP_200_OK)',
            '"scope": "process_liveness_only"',
            '@app.get("/ready")',
            '@app.get("/api/v1/admin/metrics"',
            '@app.get("/api/v1/admin/privacy/support-export")',
            '@app.post("/api/v1/admin/privacy/delete")',
            '"support-diagnostics"',
            "sgk-retention-v1",
        ):
            self.assertIn(token, main_source)

        corpus = "\n".join(
            (MANUALS / name).read_text(encoding="utf-8")
            for name in (
                "administrator_manual_ko.md",
                "privacy_notice_ko.md",
                "support_incident_handbook_ko.md",
                "hardwareless_walkthrough_ko.md",
                "product_gap_register_v1.md",
            )
        )
        for token in (
            "/live",
            "/ready",
            "process_liveness_only",
            "/api/v1/admin/metrics",
            "/api/v1/admin/privacy/support-export",
            "/api/v1/admin/privacy/delete",
            "support-diagnostics",
            "sgk-retention-v1",
            "OPS PENDING",
        ):
            self.assertIn(token, corpus)
        self.assertNotIn(
            "독립 restore, measured RPO/RTO, key/ACL/audit 검증을 실행하는 production runbook이 아직 없다",
            corpus,
        )

    def test_nas_staging_never_promotes_physical_or_production_gates(self) -> None:
        corpus = "\n".join(
            path.read_text(encoding="utf-8") for path in MANUALS.glob("*.md")
        )
        for token in (
            "NAS 검증 배포",
            "PHYSICAL PENDING",
            "PRODUCTION PENDING",
            "OTA-G1..G4",
            "GPIO3-RELAY-100",
            "SAMSUNG-WAKE-100",
        ):
            self.assertIn(token, corpus)


if __name__ == "__main__":
    unittest.main()
