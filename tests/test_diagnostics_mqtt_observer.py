import contextlib
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import observe_diagnostics_mqtt as observer


def records(path):
    return [json.loads(line) for file in sorted(path.glob("*.jsonl")) for line in file.read_text().splitlines()]


class MqttObserverTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "recording"

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
