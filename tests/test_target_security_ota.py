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
        self.assertIn("std::strlen(MQTT_USER) > 0", target)
        self.assertIn(
            'const String prefix = "gatekeeper/v1/targets/" + targetId;', target
        )
        self.assertNotIn("targetId == MQTT_USER", target)
        self.assertIn("CommandResult::kEffectRejected", target)
        self.assertEqual(compose.count(":?"), 1)
        self.assertIn(
            "MIGRATION_SOURCE_COMMIT: ${BUILD_SHA:?exact 40-hex BUILD_SHA is required}",
            compose,
        )
        self.assertIn("COMMAND_SIGNING_KEY_ID: ${COMMAND_SIGNING_KEY_ID:-0}", compose)
        self.assertIn("_command_provisioning_error()", backend)
        self.assertIn("_target_boot_registry.current_boot_id", backend)
        self.assertIn("MQTT_PORT == 1883", backend)
        self.assertIn("not MQTT_USER", backend)
        self.assertIn("not MQTT_PASSWORD", backend)
        self.assertIn("not os.path.isfile(MQTT_CA_FILE)", backend)

    def test_broker_separates_retained_discovery_from_effect_writers(self) -> None:
        config = (ROOT / "security/mosquitto.conf").read_text(encoding="utf-8")
        acl = (ROOT / "security/target-acl").read_text(encoding="utf-8")
        self.assertIn("retain_available true", config)
        self.assertIn("allow_anonymous false", config)
        self.assertIn("pattern read gatekeeper/v1/targets/%u/command", acl)
        self.assertIn(
            "topic read gatekeeper/v1/targets/+/canonical-event", acl
        )
        self.assertIn("user homeassistant", acl)
        self.assertIn("topic write gatekeeper/v1/ha-bridge/+/request/+", acl)
        self.assertIn(
            "topic write gatekeeper/v1/ha-bridge/+/verified-status", acl
        )
        home_assistant_acl = acl.split("user homeassistant", 1)[1]
        self.assertIn(
            "topic read gatekeeper/v1/ha-bridge/+/verified-status",
            home_assistant_acl,
        )
        self.assertIn(
            "topic read gatekeeper/v1/targets/+/status", home_assistant_acl
        )
        self.assertNotIn("/command", home_assistant_acl)
        self.assertNotIn("/acl", home_assistant_acl)
        self.assertNotIn("/canonical-event", home_assistant_acl)
        self.assertNotIn("pattern readwrite gatekeeper/#", acl)

    def test_ota_runtime_uses_one_verified_inactive_slot_engine(self) -> None:
        ota = (ROOT / "src/OtaManager.cpp").read_text(encoding="utf-8")
        wifi = (ROOT / "src/WifiManager.cpp").read_text(encoding="utf-8")
        for required in (
            "#include <sodium.h>",
            "#ifndef CONFIG_APP_ROLLBACK_ENABLE",
            'extern "C" bool verifyRollbackLater()',
            "sodium_init()",
            "crypto_sign_verify_detached",
            "crypto_sign_PUBLICKEYBYTES == 32U",
            "crypto_sign_BYTES == 64U",
            "esp_ota_get_next_update_partition",
            "esp_ota_write",
            "esp_ota_set_boot_partition",
            "esp_ota_mark_app_valid_cancel_rollback",
            "esp_ota_mark_app_invalid_rollback_and_reboot",
            "kPeriodicCheckMs",
            "versionPolicy.evaluate",
            "healthPolicy.update",
        ):
            self.assertIn(required, ota)
        deferred_hook = ota.split(
            'extern "C" bool verifyRollbackLater()', 1
        )[1].split("}", 1)[0]
        self.assertIn("return true;", deferred_hook)
        self.assertNotIn('extern "C" bool verifyOta()', ota)
        self.assertNotIn("PSA_ALG_PURE_EDDSA", ota)
        self.assertNotIn("psa_verify_message", ota)
        self.assertNotIn("#include <psa/crypto.h>", ota)
        self.assertNotIn("HTTPUpdate", ota)
        self.assertIn("/recovery/manifest", wifi)
        self.assertIn("/recovery/firmware", wifi)
        self.assertIn("requireLocalAuthentication()", wifi)
        self.assertIn("LOCAL_RECOVERY_AP_PASSWORD", wifi)
        self.assertIn("/recovery/enable-ap", wifi)
        self.assertIn("WiFi.mode(WIFI_AP_STA)", wifi)
        self.assertIn("recoveryApDeadlineMs", wifi)
        self.assertIn("setClockFromAuthenticatedHttpDate", ota)
        self.assertIn("current version reflash denied", ota)
        self.assertIn("[OTA-ERROR] manifest rejected: %s", ota)
        self.assertIn("[OTA] running image marked VALID", ota)
        self.assertIn("OtaManager::getLastError()", wifi)
        self.assertEqual(ota.count("WiFiClientSecure otaClient"), 1)
        self.assertEqual(ota.count("HTTPClient otaHttp"), 1)
        self.assertIn("otaClient.setCACert(SECRET_ROOT_CA_CERT)", ota)
        self.assertIn("otaHttp.setReuse(true)", ota)
        self.assertIn(
            "sameHttpsAuthority(OTA_VERSION_URL, stagedManifest.artifact_url)",
            ota,
        )
        self.assertIn("otaHttp.connected()", ota)
        self.assertIn("otaHttp.setURL(stagedManifest.artifact_url)", ota)
        self.assertNotIn("WiFiClientSecure artifactClient", ota)
        self.assertNotIn("setInsecure", ota)
        safe_state_failure = ota.split("if (!waitForSafeState())", 1)[1].split(
            "}", 1
        )[0]
        self.assertIn("status = OtaStatus::FAILED", safe_state_failure)
        self.assertIn('lastError = "WAIT_SAFE_STATE timeout"', safe_state_failure)
        self.assertIn(
            "nextPeriodicCheckMs = millis() + kFailureRetryMs",
            safe_state_failure,
        )
        self.assertIn("return;", safe_state_failure)

        download_loop = ota.split(
            "while (updateBytes < stagedManifest.artifact_size)", 1
        )[1].split("otaHttp.end()", 1)[0]
        self.assertIn("kArtifactIdleTimeoutMs", download_loop)
        self.assertIn("kArtifactDownloadTimeoutMs", download_loop)
        self.assertIn("GattServer::update();", download_loop)
        self.assertIn("DiagnosticsManager::feedLoopWatchdog();", download_loop)
        self.assertIn("observedMs - downloadStartedMs", download_loop)
        self.assertIn("observedMs - lastProgressMs", download_loop)
        self.assertIn("lastProgressMs = millis()", download_loop)
        download_failure = ota.split("if (!downloadOk || !finishImageWrite())", 1)[
            1
        ].split("}", 1)[0]
        self.assertIn("abortImageWrite()", download_failure)
        self.assertIn('"artifact download timeout"', download_failure)
        self.assertIn(
            "nextPeriodicCheckMs = millis() + kFailureRetryMs",
            download_failure,
        )
        self.assertLess(
            wifi.index("if (apSuccess)"),
            wifi.index("apModeActive = true", wifi.index("if (apSuccess)")),
        )

    def test_every_controlled_restart_preserves_access_evidence(self) -> None:
        ota = (ROOT / "src/OtaManager.cpp").read_text(encoding="utf-8")
        wifi = (ROOT / "src/WifiManager.cpp").read_text(encoding="utf-8")
        mqtt = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")
        main = (ROOT / "src/main.cpp").read_text(encoding="utf-8")

        for marker in (
            'preserveAccessEvidenceBeforeRestart("valid_mark_failed")',
            "preserveAccessEvidenceBeforeRestart(rollbackReason)",
            'preserveAccessEvidenceBeforeRestart("pending_verify")',
        ):
            self.assertIn(marker, ota)
        self.assertEqual(ota.count("ESP.restart();"), 3)
        self.assertEqual(
            ota.count("esp_ota_mark_app_invalid_rollback_and_reboot()"), 2
        )

        for marker in (
            'preserveAccessEvidenceBeforeRestart("provisioning_save")',
            'preserveAccessEvidenceBeforeRestart("local_ota_pending_verify")',
        ):
            self.assertIn(marker, wifi)
        self.assertEqual(wifi.count("ESP.restart();"), 2)

        mqtt_restart = mqtt.split(
            "void MqttManager::performPendingRestart()", 1
        )[1].split("bool MqttManager::publishCommandAck", 1)[0]
        self.assertLess(
            mqtt_restart.index("GattServer::persistPendingEventsForRestart()"),
            mqtt_restart.index("ESP.restart();"),
        )

        lease_restart = main.split(
            "static bool enforceAccessCriticalLease", 1
        )[1].split(
            "// ─────────────────────────────────────────────────────────────", 1
        )[0]
        self.assertLess(
            lease_restart.index("GattServer::persistPendingEventsForRestart()"),
            lease_restart.index("ESP.restart();"),
        )

    def test_signed_reboot_quiesces_gatt_and_rechecks_physical_state(self) -> None:
        main = (ROOT / "src/main.cpp").read_text(encoding="utf-8")
        mqtt = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")
        helper = main.split("static bool servicePendingSignedRestart()", 1)[1]
        helper = helper.split("static bool enforceAccessCriticalLease", 1)[0]

        block_new_auth = helper.index("GattServer::setOtaBusy(true);")
        first_physical_check = helper.index(
            "isVerifiedPhysicalAccessActive()", block_new_auth
        )
        flush_busy = helper.index("GattServer::flushOtaBusy", first_physical_check)
        disconnect_raw = helper.index(
            "GattServer::abortUnverifiedIngress", flush_busy
        )
        final_physical_check = helper.index(
            "isVerifiedPhysicalAccessActive()", disconnect_raw
        )
        perform = helper.index(
            "MqttManager::performPendingRestart()", final_physical_check
        )
        self.assertLess(block_new_auth, first_physical_check)
        self.assertLess(first_physical_check, flush_busy)
        self.assertLess(flush_busy, disconnect_raw)
        self.assertLess(disconnect_raw, final_physical_check)
        self.assertLess(final_physical_check, perform)

        update = mqtt.split("void MqttManager::update()", 1)[1]
        update = update.split("void MqttManager::publishBootDiagnostics", 1)[0]
        self.assertIn("if (signedRestartPending)", update)
        self.assertNotIn("ESP.restart();", update)
        self.assertGreaterEqual(
            main.split("void loop()", 1)[1].count(
                "MqttManager::hasPendingRestartRequest()"
            ),
            2,
        )

    def test_ota_runtime_decrypts_only_authenticated_envelopes(self) -> None:
        ota = (ROOT / "src/OtaManager.cpp").read_text(encoding="utf-8")
        for required in (
            "kEnvelopeMagic",
            "kEnvelopeHeaderSize",
            "kEnvelopeTagSize",
            "kGcmBlockSize",
            '"smart-gatekeeper-target-content-v1\\n"',
            '"AES-256-GCM"',
            "SECRET_OTA_CONTENT_KEY_HEX",
            "SECRET_OTA_CONTENT_KEY_ID",
            "stagedManifest.commit",
            'endsWith(".sgkenc")',
            "schemaVersion != 2",
            "plaintext_sha256",
            "mbedtls_gcm_update",
            "mbedtls_gcm_finish",
            "constantTimeEqual(actualTag, updateTag",
            "constantTimeEqual(actualPlaintextDigest",
            "updateCiphertextBytes != stagedManifest.plaintext_size",
            "updateCiphertextCarryBytes",
            "stagedManifest.plaintext_size > updatePartition->size",
        ):
            self.assertIn(required, ota)
        self.assertNotIn("MQTT_PASSWORD", ota)

        write_chunk = ota.split("bool writeImageChunk", 1)[1].split(
            "bool finishImageWrite", 1
        )[0]
        self.assertLess(
            write_chunk.index("mbedtls_sha256_update"),
            write_chunk.index("consumeEnvelopePayload"),
        )
        self.assertNotIn("esp_ota_write(updateHandle, data", write_chunk)

        aligned_stream = ota.split(
            "bool writeDecryptedCiphertext", 1
        )[1].split("bool consumeEnvelopePayload", 1)[0]
        self.assertIn(
            "((length - offset) / kGcmBlockSize) * kGcmBlockSize",
            aligned_stream,
        )
        self.assertIn(
            "decryptAndWriteCiphertext(updateCiphertextCarry,\n"
            "                                     kGcmBlockSize)",
            aligned_stream,
        )
        self.assertIn(
            "std::min(alignedLength - alignedOffset, kDecryptInputChunkSize)",
            aligned_stream,
        )
        self.assertIn(
            "decryptAndWriteCiphertext(data + offset + alignedOffset,\n"
            "                                   alignedChunkLength)",
            aligned_stream,
        )
        self.assertLess(
            aligned_stream.index("updateCiphertextCarryBytes == kGcmBlockSize"),
            aligned_stream.index("const size_t alignedLength"),
        )

        finish = ota.split("bool finishImageWrite", 1)[1].split(
            "bool waitForSafeState", 1
        )[0]
        self.assertLess(finish.index("constantTimeEqual(actualTag"),
                        finish.index("esp_ota_end"))
        self.assertLess(finish.index("constantTimeEqual(actualDigest"),
                        finish.index("esp_ota_end"))
        self.assertLess(finish.index("constantTimeEqual(actualPlaintextDigest"),
                        finish.index("esp_ota_end"))
        self.assertLess(finish.index("mbedtls_gcm_finish"),
                        finish.index("esp_ota_end"))
        self.assertLess(
            finish.index("const size_t finalCiphertextLength"),
            finish.index("mbedtls_gcm_finish"),
        )
        self.assertIn("abortImageWrite()", finish)

    def test_ota_gcm_alt_transport_chunks_are_block_aligned(self) -> None:
        header_size = 20
        tag_size = 16
        block_size = 16
        plaintext_size = 1_795_248
        artifact_size = header_size + plaintext_size + tag_size
        transport_chunks = [3_841] + [4_096] * 437 + [1_491]
        self.assertEqual(sum(transport_chunks), artifact_size)

        envelope = bytes(index % 251 for index in range(artifact_size))
        held_tag = bytearray()
        block_carry = bytearray()
        gcm_calls: list[bytes] = []

        def feed_ciphertext(value: bytes) -> None:
            nonlocal block_carry
            combined = bytes(block_carry) + value
            aligned = len(combined) // block_size * block_size
            if aligned:
                for offset in range(0, aligned, 4_096):
                    gcm_calls.append(combined[offset:min(offset + 4_096, aligned)])
            block_carry = bytearray(combined[aligned:])

        cursor = 0
        header_remaining = header_size
        for chunk_size in transport_chunks:
            chunk = envelope[cursor:cursor + chunk_size]
            cursor += chunk_size
            if header_remaining:
                consumed = min(header_remaining, len(chunk))
                header_remaining -= consumed
                chunk = chunk[consumed:]
            if not chunk:
                continue
            combined = bytes(held_tag) + chunk
            if len(combined) <= tag_size:
                held_tag = bytearray(combined)
                continue
            feed_ciphertext(combined[:-tag_size])
            held_tag = bytearray(combined[-tag_size:])

        if block_carry:
            gcm_calls.append(bytes(block_carry))
            block_carry.clear()

        self.assertEqual(cursor, artifact_size)
        self.assertEqual(bytes(held_tag), envelope[-tag_size:])
        self.assertEqual(b"".join(gcm_calls), envelope[header_size:-tag_size])
        self.assertEqual(sum(map(len, gcm_calls)), plaintext_size)
        self.assertTrue(all(len(call) <= 4_096 for call in gcm_calls))
        self.assertTrue(all(len(call) % block_size == 0 for call in gcm_calls[:-1]))
        self.assertEqual(len(gcm_calls[-1]) % block_size,
                         plaintext_size % block_size)

    def test_clock_untrusted_and_outage_recovery_mutations_fail_closed(self) -> None:
        mqtt = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")
        raw_command_policy = (ROOT / "include/FlatJsonObjectPolicy.h").read_text(
            encoding="utf-8"
        )
        health_policy = (ROOT / "include/OtaHealthPolicy.h").read_text(
            encoding="utf-8"
        )
        wifi = (ROOT / "src/WifiManager.cpp").read_text(encoding="utf-8")
        diagnostics = (ROOT / "src/DiagnosticsManager.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("systemClockTrusted", mqtt)
        self.assertIn("kCommandFields", mqtt)
        self.assertIn("secureDoc.size()", mqtt)
        self.assertIn("hasExactUniqueFlatJsonFields", mqtt)
        self.assertIn("seen & (1UL << field)", raw_command_policy)
        self.assertIn("elapsed_ms > timeout_ms_", health_policy)
        self.assertIn("max_sample_gap_ms_", health_policy)
        ota = (ROOT / "src/OtaManager.cpp").read_text(encoding="utf-8")
        self.assertIn("kHealthMaxSampleGapMs = 5000", ota)
        self.assertIn("healthSampleGapResetCount", ota)
        self.assertIn("healthMaxObservedSampleGapMs", ota)
        self.assertIn('rollbackReason = "ota_health_sample_gap"', ota)
        self.assertIn("envelope, verificationTime, systemClockTrusted", mqtt)
        self.assertNotIn(": envelope.issued_at", mqtt)
        operator_transition = wifi.split("bool WifiManager::startRecoveryAP", 1)[1]
        preserve_branch = operator_transition.split("} else {", 1)[0]
        self.assertIn("WIFI_AP_STA", preserve_branch)
        self.assertNotIn("WiFi.disconnect", preserve_branch)
        self.assertNotIn("MQTT", preserve_branch)
        self.assertNotIn("DNS", preserve_branch)
        self.assertIn("char bootIdValue[33]", diagnostics)
        self.assertEqual(4, diagnostics.count("static_cast<unsigned long>(esp_random())"))

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
