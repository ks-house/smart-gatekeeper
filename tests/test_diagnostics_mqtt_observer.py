import contextlib
import io
import json
import os
from pathlib import Path
import re
import ssl
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import observe_diagnostics_mqtt as observer
from backend.app.home_assistant_bridge import bridge_connectivity_diagnostic_payload


# Wire-shaped fixtures from MqttManager's online snprintf and offline will.
# Identities are synthetic; no captured device/credential data is embedded.
TARGET_ONLINE = (b'{"status":"online","scope":"mqtt_transport",'
                 b'"target_id":"target-a","boot_id":"0123456789abcdef0123456789abcdef","boot_count":904}')
TARGET_OFFLINE = TARGET_ONLINE.replace(b'"online"', b'"offline"')
BRIDGE_FRESH = (b'{"diagnostic_scope":"last_completed_backend_observation",'
                b'"last_signed_status_observation":"SIGNED_STATUS_FRESH","schema_version":1}')


def records(path):
    return [json.loads(line) for file in sorted(path.glob("*.jsonl")) for line in file.read_text().splitlines()]


class MqttObserverTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "recording"

    def test_target_fixtures_match_actual_firmware_format_strings(self):
        source = (observer.ROOT / "src/MqttManager.cpp").read_text()
        # Execute the actual adjacent C string formats, not another hand-built
        # dictionary, so producer changes invalidate these protocol fixtures.
        formats = re.findall(r'"\{\\"status\\":.*?(?=,\s*\n)', source, re.DOTALL)
        emitted = set()
        for value in formats:
            parts = re.findall(r'"(?:\\.|[^"\\])*"', value)
            template = "".join(json.loads(part) for part in parts)
            if template.count("%s") == 2 and "%lu" in template:
                emitted.add((template.replace("%lu", "%d") %
                    ("target-a", "0123456789abcdef0123456789abcdef", 904)).encode())
        self.assertIn(TARGET_ONLINE, emitted)
        self.assertIn(TARGET_OFFLINE, emitted)

    def test_real_target_json_and_explicit_legacy_transport_contract(self):
        for payload, status in ((TARGET_ONLINE, "online"), (TARGET_OFFLINE, "offline")):
            with self.subTest(status=status):
                result = observer.project_message("target_availability", payload, target_id="target-a")
                self.assertEqual(dict(availability=status, scope="mqtt_transport", target_id="target-a",
                    boot_id="0123456789abcdef0123456789abcdef", boot_count="904",
                    payload_format="target_json"), result)
        for payload in (b"online", b"offline"):
            result = observer.project_message("target_availability", payload, target_id="target-a")
            self.assertEqual(dict(availability=payload.decode(), scope="mqtt_transport",
                                  payload_format="legacy_plain"), result)
            self.assertEqual({"availability": payload.decode()},
                             observer.project_message("bridge_availability", payload))

    def test_target_availability_rejects_bad_identity_types_size_and_unknown_fields(self):
        base = json.loads(TARGET_ONLINE)
        bad_documents = [{key: value for key, value in base.items() if key != missing} for missing in base]
        invalid = {
            "target_id": ["target-b", "target-a/other", "target-a\n", "target-a+", "", 1, None, [], {}],
            "boot_id": ["unknown", "A" * 32, "a" * 31, "a" * 33, "a" * 32 + "\n", 1, None, []],
            "boot_count": [0, -1, 1 << 32, True, False, 904.0, "904", None, [], {}],
            "status": ["unknown", "ONLINE", "online\n", True, None, [], {}],
            "scope": ["readiness", "mqtt_transport\n", True, None, [], {}],
        }
        bad_documents.extend({**base, key: value} for key, values in invalid.items() for value in values)
        bad_documents.extend({**base, key: value} for key, value in
                             (("private_key", "do-not-save"), ("source_boot_count", 904), ("ready", True)))
        invalid_bytes = [json.dumps(doc).encode() for doc in bad_documents]
        invalid_bytes += [b"", b"online\n", b'"online"', b"[]", b"null", b"{", b"\xff",
                          TARGET_ONLINE + b" trailing", b"[" * 2000,
                          TARGET_ONLINE.replace(b"904", b"NaN"),
                          TARGET_ONLINE.replace(b"904", b"Infinity"),
                          TARGET_ONLINE + b" " * observer.MAX_AVAILABILITY_PAYLOAD]
        invalid_bytes.extend(TARGET_ONLINE[:-1] + b"," + json.dumps(key).encode() + b":" +
                             json.dumps(value).encode() + b"}" for key, value in base.items())
        for payload in invalid_bytes:
            with self.subTest(payload=payload[:200]):
                with self.assertRaises(ValueError):
                    observer.project_message("target_availability", payload, target_id="target-a")
        for count in (1, (1 << 32) - 1):
            result = observer.project_message("target_availability",
                json.dumps({**base, "boot_count": count}).encode(), target_id="target-a")
            self.assertEqual(str(count), result["boot_count"])
        with self.assertRaises(ValueError):
            observer.project_message("target_availability", TARGET_ONLINE)
        with self.assertRaises(ValueError):
            observer.project_message("target_availability", TARGET_ONLINE, target_id="target-b")

    def test_bridge_connectivity_accepts_actual_emitter_without_promoting_assertions(self):
        self.assertEqual(BRIDGE_FRESH, bridge_connectivity_diagnostic_payload("online", "SIGNED_STATUS_FRESH").encode())
        for status, reason in (("online", "SIGNED_STATUS_FRESH"),
                               ("offline", "SIGNED_STATUS_STALE"),
                               ("offline", "WAITING_FOR_SIGNED_STATUS")):
            payload = bridge_connectivity_diagnostic_payload(status, reason).encode()
            result = observer.project_message("bridge_connectivity", payload)
            self.assertEqual(json.loads(payload), result)
            for key in ("availability", "status", "ready", "boot_id", "boot_count"):
                self.assertNotIn(key, result)
        base = json.loads(BRIDGE_FRESH)
        invalid = [{key: value for key, value in base.items() if key != missing} for missing in base]
        invalid += [{**base, "schema_version": value} for value in (True, 1.0, "1", 2, None)]
        invalid += [{**base, "last_signed_status_observation": value}
                    for value in ("UNKNOWN", "TARGET_CRASHED", "SIGNED_STATUS_FRESH\n", [], None)]
        invalid += [{**base, "diagnostic_scope": "current_readiness"}, {**base, "ready": True},
                    {"status": "online", "reason": "SIGNED_STATUS_FRESH"}]
        for payload in [json.dumps(doc).encode() for doc in invalid] + [
                BRIDGE_FRESH[:-1] + b',"schema_version":1}', b'{}', b'online']:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    observer.project_message("bridge_connectivity", payload)

    def test_cross_channel_payloads_and_mismatched_targets_are_rejected(self):
        writer = observer.BoundedJsonl(self.output)
        self.addCleanup(writer.close)
        recording = observer.Observer(writer, "target-a")
        invalid = [(channel, payload) for channel in observer.CHANNELS
                   for payload, owner in ((TARGET_ONLINE, "target_availability"),
                                          (BRIDGE_FRESH, "bridge_connectivity")) if channel != owner]
        invalid += [(channel, b'{"target_id":"target-b","state":"IDLE","boot_count":904}')
                    for channel in ("target_status", "target_boot", "bridge_status")]
        for channel, payload in invalid:
            with self.subTest(channel=channel, payload=payload):
                topic = next(topic for topic, name in recording.channels.items() if name == channel)
                self.assertFalse(recording.message(topic, payload, False))
        self.assertEqual({}, recording.state)
        self.assertEqual(len(invalid), recording.rejected)
        self.assertEqual(recording.rejected, sum(recording.snapshot()["rejected_messages_by_channel"].values()))
        for channel in ("unknown", "other_availability"):
            with self.assertRaises(ValueError):
                observer.project_message(channel, b"online")

    def test_retained_replay_cannot_inherit_prior_live_boot_freshness(self):
        clock = [10.0]
        writer = observer.BoundedJsonl(self.output)
        self.addCleanup(writer.close)
        recording = observer.Observer(writer, "target-a", monotonic=lambda: clock[0])
        topic = "gatekeeper/v1/targets/target-a/availability"
        recording.connection(True)
        recording.subscription(True)
        self.assertTrue(recording.message(topic, TARGET_ONLINE, False))
        self.assertEqual("RECENT_MESSAGE", recording.snapshot()["observations"]["target_availability"]["freshness"])
        recording.disconnect()
        clock[0] = 15
        recording.connection(True)
        recording.subscription(True)
        old_boot = TARGET_OFFLINE.replace(b"904", b"903").replace(b"0123456789abcdef" * 2, b"a" * 32)
        self.assertTrue(recording.message(topic, old_boot, True))
        for _ in range(3):
            self.assertTrue(recording.message(topic, old_boot, True))
        value = recording.snapshot()["observations"]["target_availability"]
        self.assertEqual("903", value["fields"]["boot_count"])
        self.assertEqual("RETAINED_ONLY", value["freshness"])
        self.assertEqual(5000, value["live_receipt_age_ms"])
        self.assertTrue(value["snapshot_only"])
        self.assertEqual(3, value["duplicates_suppressed"])
        clock[0] = 16
        self.assertTrue(recording.message(topic, b"online", False))
        value = recording.snapshot()["observations"]["target_availability"]
        self.assertEqual("RECENT_MESSAGE", value["freshness"])
        self.assertNotIn("boot_id", value["fields"])
        self.assertNotIn("boot_count", value["fields"])
        recording.finish("DURATION_COMPLETE")
        for record in records(self.output):
            if record["kind"] == "observation":
                self.assertEqual("UNVERIFIED_MQTT_OBSERVATION", record["evidence_integrity"])

    def test_invalid_availability_cannot_replace_or_refresh_accepted_evidence(self):
        clock = [10.0]
        writer = observer.BoundedJsonl(self.output)
        self.addCleanup(writer.close)
        recording = observer.Observer(writer, "target-a", monotonic=lambda: clock[0])
        topic = "gatekeeper/v1/targets/target-a/availability"
        self.assertTrue(recording.message(topic, TARGET_ONLINE, True))
        clock[0] = 200
        self.assertFalse(recording.message(topic, TARGET_OFFLINE.replace(b"target-a", b"target-b"), False))
        for wrong_topic in (topic + "/extra", topic.replace("target-a", "target-a-other"),
                            topic.replace("/targets/", "/other/")):
            self.assertFalse(recording.message(wrong_topic, TARGET_OFFLINE, False))
        value = recording.snapshot()["observations"]["target_availability"]
        self.assertEqual("online", value["fields"]["availability"])
        self.assertEqual("RETAINED_ONLY", value["freshness"])
        self.assertEqual(190000, value["receipt_age_ms"])
        self.assertIsNone(value["live_receipt_age_ms"])

    def test_exact_namespaces_exclude_commands_wildcards_and_other_targets(self):
        topics = observer.topics("target-a")
        self.assertEqual(6, len(topics))
        self.assertTrue(all("/target-a/" in topic for topic in topics))
        self.assertFalse(any(any(part in topic for part in ("#", "+", "command", "request")) for topic in topics))
        for target in ("+", "#", "../a", "other/target", "", "a" * 65):
            with self.assertRaises(ValueError):
                observer.topics(target)
        writer = observer.BoundedJsonl(self.output)
        recording = observer.Observer(writer, "target-a")
        recording.start()
        self.assertFalse(recording.message("gatekeeper/v1/targets/other/status", b'{"state":"IDLE"}', False))
        recording.finish("OPERATOR_STOP")
        self.assertNotIn("other", json.dumps(records(self.output)))

    def test_closed_projection_rejects_raw_secrets_invalid_json_and_counters(self):
        payload = dict(state="IDLE", source_boot_count="901", status_revision="2", relay_commanded_on=False,
                       private_key="private-secret", signature="raw-sig", token="raw-token", command="open",
                       ble_advertising_active=True, free_heap=True, mqtt_connect_count=-1)
        value = observer.project_message("target_status", json.dumps(payload).encode())
        self.assertEqual("IDLE", value["state"])
        self.assertEqual("901", value["source_boot_count"])
        for key in ("private_key", "signature", "token", "command", "free_heap", "mqtt_connect_count"):
            self.assertNotIn(key, value)
        for payload in (b'{"state":"IDLE","state":"ARMED"}', b'{"free_heap":NaN}',
                        b'{"private_key":"secret"}', b'[]', b'x' * (observer.MAX_PAYLOAD + 1)):
            with self.assertRaises(ValueError):
                observer.project_message("target_status", payload)

    def test_dedupe_retained_receipts_live_freshness_and_disconnect_gaps(self):
        clock = [10.0]
        writer = observer.BoundedJsonl(self.output)
        recording = observer.Observer(writer, "target", cursors={"mobile_before_id": "1017"}, monotonic=lambda: clock[0])
        recording.start()
        recording.connection(True)
        recording.subscription(True)
        topic = "gatekeeper/v1/targets/target/availability"
        recording.message(topic, b'online', True)
        self.assertEqual("RETAINED_ONLY", recording.snapshot()["observations"]["target_availability"]["freshness"])
        for _ in range(1000):
            recording.message(topic, b'online', True)
        clock[0] = 20
        recording.message(topic, b'online', False)
        recording.disconnect()
        clock[0] = 40
        recording.connection(True)
        recording.subscription(True)
        clock[0] = 140
        self.assertEqual("NO_RECENT_MESSAGE", recording.snapshot()["observations"]["target_availability"]["freshness"])
        recording.checkpoint()
        recording.finish("DURATION_COMPLETE")
        saved = records(self.output)
        observations = [item for item in saved if item["kind"] == "observation"]
        self.assertEqual(2, len(observations))
        self.assertTrue(observations[0]["retained"])
        self.assertFalse(observations[1]["retained"])
        self.assertEqual("UNVERIFIED_MQTT_OBSERVATION", observations[1]["evidence_integrity"])
        snapshot = saved[-1]["snapshot"]
        self.assertEqual(1000, snapshot["observations"]["target_availability"]["duplicates_suppressed"])
        self.assertEqual("1017", snapshot["api_cursors"]["mobile_before_id"])
        self.assertFalse(snapshot["api_cursors_advanced"])
        self.assertFalse(snapshot["silence_is_failure"])
        restored = [item for item in saved if item["kind"] == "subscription"][-1]
        self.assertEqual(20000, restored["preceding_gap_ms"])
        self.assertFalse(restored["replay_recovers_gap"])

    def test_rotation_is_bounded_private_and_describes_eviction_and_snapshot(self):
        writer = observer.BoundedJsonl(self.output, max_bytes=4096, max_files=2)
        recording = observer.Observer(writer, "target")
        recording.start()
        topic = "gatekeeper/v1/targets/target/status"
        for index in range(100):
            recording.message(topic, json.dumps(dict(state="IDLE", status_revision=str(index))).encode(), False)
        recording.finish("DURATION_COMPLETE")
        files = list(self.output.glob("*.jsonl"))
        self.assertEqual(2, len(files))
        self.assertTrue(all(file.stat().st_size <= 4096 for file in files))
        if os.name != "nt":
            self.assertEqual(0o700, self.output.stat().st_mode & 0o777)
            self.assertTrue(all(file.stat().st_mode & 0o777 == 0o600 for file in files))
        saved = records(self.output)
        self.assertGreater(saved[0]["history_evicted_through_sequence"], 0)
        self.assertIsNotNone(saved[0]["snapshot"])
        self.assertEqual(list(range(saved[0]["sequence"], saved[-1]["sequence"] + 1)), [item["sequence"] for item in saved])
        self.assertEqual("collection_end", saved[-1]["kind"])
        with self.assertRaises(FileExistsError):
            observer.BoundedJsonl(self.output)

    def test_oversized_projected_record_records_a_gap_without_exceeding_budget(self):
        writer = observer.BoundedJsonl(self.output, max_bytes=4096)
        writer.write("observation", {"field": "x" * 9000}, snapshot={"field": "y" * 9000})
        writer.close()
        saved = records(self.output)
        self.assertEqual("RECORD_SIZE_LIMIT", saved[0]["snapshot_omitted"])
        self.assertEqual("PROJECTED_RECORD_TOO_LARGE", saved[1]["reason"])
        self.assertLess(next(self.output.glob("*.jsonl")).stat().st_size, 4096)

    def test_mocked_runtime_requires_tls_and_never_publishes_or_reads_api(self):
        args = observer.parser().parse_args(["--target-id", "target", "--host", "broker.test", "--port", "4883",
            "--output-dir", str(self.output), "--duration-seconds", "2", "--snapshot-seconds", "1",
            "--mobile-before-id", "1017", "--evidence-received-until", "2026-09-13T13:10:00Z"])
        client = MagicMock()
        client.subscribe.return_value = (0, 1)
        clock = [0.0]
        def loop_start():
            client.on_connect(client, None, None, 0)
            client.on_subscribe(client, None, 1, [1] * 6)
            client.on_message(client, None, SimpleNamespace(topic="gatekeeper/v1/targets/target/status",
                payload=b'{"state":"IDLE","token":"must-not-leak"}', retain=False))
            client.on_message(client, None, SimpleNamespace(topic="gatekeeper/v1/targets/target/availability",
                payload=TARGET_ONLINE.replace(b"target-a", b"target"), retain=True))
            client.on_message(client, None, SimpleNamespace(topic="gatekeeper/v1/ha-bridge/target/connectivity-diagnostic",
                payload=BRIDGE_FRESH, retain=False))
            client.on_message(client, None, SimpleNamespace(topic="gatekeeper/v1/ha-bridge/target/availability",
                payload=b"online", retain=True))
            client.on_message(client, None, SimpleNamespace(topic="gatekeeper/v1/targets/target/availability",
                payload=TARGET_ONLINE, retain=False))
            return 0
        client.loop_start.side_effect = loop_start
        mqtt = SimpleNamespace(Client=MagicMock(return_value=client), MQTTv311=4, MQTT_ERR_SUCCESS=0)
        with patch.dict(os.environ, {"SGK_MQTT_USERNAME": "test-user", "SGK_MQTT_PASSWORD": "test-secret"}, clear=True):
            result = observer.run(args, mqtt, monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        context = client.tls_set_context.call_args.args[0]
        self.assertTrue(context.check_hostname)
        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        client.publish.assert_not_called()
        client.will_set.assert_not_called()
        client.tls_insecure_set.assert_not_called()
        client.connect_async.assert_called_once_with("broker.test", 4883, keepalive=30)
        client.username_pw_set.assert_called_once_with("test-user", "test-secret")
        self.assertTrue(result["subscription_ever_accepted"])
        self.assertEqual(4, result["observed_channels"])
        self.assertEqual(1, result["rejected_messages"])
        self.assertEqual(1, result["rejected_messages_by_channel"]["target_availability"])
        self.assertEqual("UNVERIFIED_MQTT_OBSERVATION", result["evidence_integrity"])
        for record in records(self.output):
            if record["kind"] == "observation":
                self.assertEqual("UNVERIFIED_MQTT_OBSERVATION", record["evidence_integrity"])
                self.assertNotIn("ready", record["fields"])
        saved = json.dumps(records(self.output))
        for secret in ("test-user", "test-secret", "must-not-leak", "broker.test"):
            self.assertNotIn(secret, saved)

    def test_secret_file_exclusivity_and_errors_do_not_print_credentials(self):
        with patch.dict(os.environ, {"SGK_MQTT_PASSWORD": "private-secret", "SGK_MQTT_PASSWORD_FILE": "private-path"}, clear=True):
            with self.assertRaises(ValueError) as error:
                observer._secret("SGK_MQTT_PASSWORD")
        self.assertNotIn("private", str(error.exception))
        output = io.StringIO()
        with patch.object(observer, "run", side_effect=RuntimeError("private-secret")), contextlib.redirect_stderr(output):
            self.assertEqual(1, observer.main(["--target-id", "target", "--output-dir", str(self.output)]))
        self.assertNotIn("private-secret", output.getvalue())
