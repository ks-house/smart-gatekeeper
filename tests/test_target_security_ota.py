from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.acl_management import DeterministicP256Signer, verify_raw64
from backend.app.command_security import build_signed_command, canonical_command


ROOT = Path(__file__).resolve().parents[1]


class TargetSecurityAndOtaTest(unittest.TestCase):
    def test_signed_command_is_target_boot_and_freshness_bound(self) -> None:
        signer = DeterministicP256Signer(2, 7)
        envelope = build_signed_command(
            signer=signer,
            target_id="target-a",
            tenant_id="tenant-a",
            door_id="door-a",
            boot_id="boot-a",
            action="manual_remote",
            value=0,
            now=1_800_000_000,
            session_id="session-a",
            nonce="nonce-a",
        )
        signature = bytes.fromhex(envelope.pop("signature"))
        self.assertTrue(
            verify_raw64(signer.public_key_sec1, canonical_command(envelope), signature)
        )
        for field, mutation in (
            ("target_id", "target-b"),
            ("tenant_id", "tenant-b"),
            ("door_id", "door-b"),
            ("boot_id", "boot-old"),
            ("action", "reboot"),
            ("nonce", "nonce-b"),
            ("expires_at", 1_800_000_121),
            ("value", 1),
        ):
            changed = dict(envelope)
            changed[field] = mutation
            self.assertFalse(
                verify_raw64(
                    signer.public_key_sec1, canonical_command(changed), signature
                ),
                field,
            )

    def test_plaintext_and_insecure_tls_paths_are_absent(self) -> None:
        backend = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
        target = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")
        compose = (ROOT / "backend/docker-compose.yml").read_text(encoding="utf-8")
        combined = backend + target + compose
        self.assertNotIn("CERT_NONE", combined)
        self.assertNotIn("tls_insecure_set(True)", combined)
        self.assertNotIn("setInsecure", combined)
        self.assertNotIn("host.docker.internal", combined)
        self.assertIn("ssl.CERT_REQUIRED", backend)
        self.assertIn("targetId == MQTT_USER", target)
        self.assertIn("CommandResult::kEffectRejected", target)

    def test_broker_rejects_retained_and_credential_crossover(self) -> None:
        config = (ROOT / "security/mosquitto.conf").read_text(encoding="utf-8")
        acl = (ROOT / "security/target-acl").read_text(encoding="utf-8")
        self.assertIn("retain_available false", config)
        self.assertIn("allow_anonymous false", config)
        self.assertIn("pattern read gatekeeper/v1/targets/%u/command", acl)
        self.assertNotIn("pattern readwrite gatekeeper/#", acl)

    def test_ota_runtime_uses_one_verified_inactive_slot_engine(self) -> None:
        ota = (ROOT / "src/OtaManager.cpp").read_text(encoding="utf-8")
        wifi = (ROOT / "src/WifiManager.cpp").read_text(encoding="utf-8")
        for required in (
            "PSA_ALG_PURE_EDDSA",
            "esp_ota_get_next_update_partition",
            "esp_ota_write",
            "esp_ota_set_boot_partition",
            "esp_ota_mark_app_valid_cancel_rollback",
            "esp_ota_mark_app_invalid_rollback_and_reboot",
            "kPeriodicCheckMs",
            "compareVersion",
        ):
            self.assertIn(required, ota)
        self.assertNotIn("HTTPUpdate", ota)
        self.assertIn("/recovery/manifest", wifi)
        self.assertIn("/recovery/firmware", wifi)
        self.assertIn("requireLocalAuthentication()", wifi)
        self.assertIn("LOCAL_RECOVERY_AP_PASSWORD", wifi)
        self.assertLess(
            wifi.index("if (apSuccess)"),
            wifi.index("apModeActive = true", wifi.index("if (apSuccess)")),
        )

    def test_production_policy_remains_disabled_and_evidence_gated(self) -> None:
        with (ROOT / "security/target-production-policy.json").open(
            encoding="utf-8"
        ) as handle:
            policy = json.load(handle)
        self.assertFalse(policy["production_enabled"])
        self.assertEqual("must_be_0", policy["compile_time"]["hardwareless_rc"])
        for value in policy["release_gates"].values():
            self.assertIn(value, {"implemented", "pending"})
        platformio = (ROOT / "platformio.ini").read_text(encoding="utf-8")
        common = platformio.split("[env:esp32c6]", 1)[0]
        self.assertIn("-DENABLE_HARDWARELESS_RC=0", common)


if __name__ == "__main__":
    unittest.main()
