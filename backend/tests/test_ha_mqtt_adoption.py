"""HA account adoption, privacy ordering, bounded rollback and reconnect evidence."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location("ha_adopt_test", ROOT/"ops/ha_mqtt_adoption.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document():
    return {"version": 1, "minor_version": 1, "key": "core.config_entries",
            "data": {"entries": [
                {"entry_id": "mqtt-example", "domain": "mqtt", "version": 2, "minor_version": 1,
                 "disabled_by": None, "data": {"broker": "localhost", "port": 1883,
                                               "protocol": "5"}, "options": {}},
                {"entry_id": "other", "domain": "example", "data": {"keep": "fixture-secret"}}]}}


IDENTITY = {"username": "ha-example", "password": "a"*64}


class ConfigurationTest(unittest.TestCase):
    def test_add_only_managed_identity_preserves_other_integrations(self):
        m = load();before = document()
        after = json.loads(m.candidate(json.dumps(before).encode(), IDENTITY))
        self.assertEqual(before["data"]["entries"][1], after["data"]["entries"][1])
        data = after["data"]["entries"][0]["data"]
        self.assertEqual({"username", "password", "client_id"}, set(data)-set(before["data"]["entries"][0]["data"]))
        self.assertEqual("localhost", data["broker"]);self.assertEqual(1883, data["port"])
        self.assertNotIn("a"*64, json.dumps(before))

    def test_existing_identity_or_shadow_options_refused(self):
        m = load()
        for location, key in (("data", "username"), ("data", "password"),
                              ("data", "client_id"), ("options", "username"),
                              ("options", "password"), ("options", "client_id")):
            value = document();value["data"]["entries"][0][location][key] = "already-set"
            with self.subTest(location=location, key=key), self.assertRaises(ValueError):
                m.candidate(json.dumps(value).encode(), IDENTITY)

    def test_disabled_duplicate_and_other_schema_refused(self):
        m = load()
        cases = []
        value = document();value["data"]["entries"][0]["disabled_by"] = "user";cases.append(value)
        value = document();value["data"]["entries"].append(copy.deepcopy(value["data"]["entries"][0]));cases.append(value)
        value = document();value["data"]["entries"][0]["version"] = 1;cases.append(value)
        value = document();value["data"]["entries"][0]["data"]["port"] = 8883;cases.append(value)
        for value in cases:
            with self.assertRaises(ValueError):m.candidate(json.dumps(value).encode(), IDENTITY)

    def test_rollback_exact_when_only_our_change_exists(self):
        m = load();raw = json.dumps(document(), indent=2).encode()
        proposed = m.candidate(raw, IDENTITY)
        self.assertEqual(raw, m.rollback_content(proposed, raw, proposed))
        self.assertEqual(raw, m.rollback_content(raw, raw, proposed))

    def test_rollback_preserves_unrelated_new_ha_changes(self):
        m = load();raw = json.dumps(document()).encode();proposed = m.candidate(raw, IDENTITY)
        changed = json.loads(proposed)
        changed["data"]["entries"][1]["data"]["new"] = "later-state"
        changed["data"]["entries"][0]["data"]["protocol"] = "3.1.1"
        result = json.loads(m.rollback_content(json.dumps(changed).encode(), raw, proposed))
        self.assertEqual("later-state", result["data"]["entries"][1]["data"]["new"])
        self.assertEqual("3.1.1", result["data"]["entries"][0]["data"]["protocol"])
        self.assertNotIn("password", result["data"]["entries"][0]["data"])

    def test_concurrent_identity_is_not_overwritten(self):
        m = load();raw = json.dumps(document()).encode();proposed = m.candidate(raw, IDENTITY)
        changed = json.loads(proposed);changed["data"]["entries"][0]["data"]["password"] = "different"
        with self.assertRaises(ValueError):
            m.rollback_content(json.dumps(changed).encode(), raw, proposed)

    def test_root_regular_and_private_directory_reject_symlinks(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);file = root/"value";file.write_text("{}")
            link = root/"link";link.symlink_to(file)
            with self.assertRaises(ValueError):m.regular(link)
            link.unlink();link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):m.private_directory(link)

    def test_named_log_requires_exact_id_username_and_fresh_time(self):
        m = load()
        line = "1792156000: New client connected from 127.0.0.1:3000 as "+m.CLIENT_ID+" (p5, c1, k60, u'ha-example').\n"
        self.assertTrue(m.named_connection(line, IDENTITY["username"], 1792155999.9))
        frame = b"\x01\x00\x00\x00"+len(line.encode()).to_bytes(4, "big")+line.encode()
        self.assertTrue(m.named_connection(m.docker_log_text(frame), IDENTITY["username"], 1792156000))
        with self.assertRaises(ValueError):m.docker_log_text(frame[:-1])
        for value in (line.replace(m.CLIENT_ID, "other"), line.replace("ha-example", "other"),
                      line.replace("1792156000", "1792155998")):
            self.assertFalse(m.named_connection(value, IDENTITY["username"], 1792155999.9))

    def test_log_file_scope_and_disabled_observation_are_checked(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"mosquitto.log";path.write_text("old\n")
            mounts = {"Mounts": [{"Destination": "/mosquitto/log", "Source": tmp}]}
            binding = m.log_binding("log_dest file /mosquitto/log/mosquitto.log\n", mounts)
            self.assertEqual(path.stat().st_size, binding["offset"])
            path.write_text("old\nnew\n")
            self.assertEqual("new\n", m.log_data(binding, 0))
            with self.assertRaises(ValueError):m.log_binding("connection_messages false\n", mounts)
            with self.assertRaises(ValueError):m.log_binding("log_dest file /unmapped/log\n", mounts)


class ContainerIdentityTest(unittest.TestCase):
    def test_auto_remove_or_wrong_binding_refused_before_stop(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)/"storage"/"core.config_entries";config.parent.mkdir()
            original = {"Id": "ha-id", "Image": "same-image", "Name": "/homeassistant",
                        "Mounts": [{"Destination": "/config", "Source": tmp, "RW": True}],
                        "HostConfig": {"NetworkMode": "host", "AutoRemove": False},
                        "Config": {"User": ""}}
            with patch.object(m, "CONFIG", config), patch.object(m.docker, "inspect") as inspect:
                inspect.return_value = original
                self.assertEqual("ha-id", m.container()["Id"])
                for field, value in (("AutoRemove", True), ("NetworkMode", "bridge")):
                    altered = copy.deepcopy(original);altered["HostConfig"][field] = value
                    inspect.return_value = altered
                    with self.assertRaises(ValueError):m.container()
                altered = copy.deepcopy(original);altered["Config"]["User"] = "1000"
                inspect.return_value = altered
                with self.assertRaises(ValueError):m.container()

    def test_changed_container_or_image_refused(self):
        m = load();original = {"Id": "same", "Image": "image"}
        for changed in ({"Id": "other", "Image": "image"}, {"Id": "same", "Image": "new"}):
            with patch.object(m, "container", return_value=changed):
                with self.assertRaises(ValueError):m.same_container(original)


class TransactionTest(unittest.TestCase):
    def setUp(self):
        self.m = load();self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name);self.storage = self.root/"storage";self.storage.mkdir()
        self.storage.chmod(0o777);self.config = self.storage/"core.config_entries"
        self.original_bytes = json.dumps(document(), indent=2).encode()
        self.config.write_bytes(self.original_bytes);self.config.chmod(0o644)
        self.work = self.root/"work";self.work.mkdir(mode=0o700)
        (self.work/"original.json").write_bytes(self.original_bytes)
        info = self.config.stat()
        (self.work/"journal.json").write_text(json.dumps({
            "phase": "prepared", "file_uid": info.st_uid, "file_gid": info.st_gid,
            "file_mode": 0o644, "directory_mode": 0o777}))
        self.original = {"Id": "same-container", "Image": "same-image", "State": {"Running": True}}
        self.events = [];self.notifications = [];self.running = True
        def atomic(path, raw, mode=0o600, uid=0, gid=0):
            if path == self.config and IDENTITY["password"].encode() in raw:
                self.assertEqual(0o700, stat.S_IMODE(self.storage.stat().st_mode))
                self.events.append("private-before-password")
            path.write_bytes(raw);path.chmod(mode)
        def stop(_):
            self.events.append("stop");self.running = False
        def start(_):
            self.events.append("start");self.running = True
        self.patches = [
            patch.object(self.m, "CONFIG", self.config),
            patch.object(self.m, "regular", side_effect=lambda p, *a: p.read_bytes()),
            patch.object(self.m, "atomic", side_effect=atomic),
            patch.object(self.m, "private_directory", side_effect=lambda p:self.assertEqual(0o700, stat.S_IMODE(p.stat().st_mode))),
            patch.object(self.m, "stopped", side_effect=stop),
            patch.object(self.m, "started", side_effect=start),
            patch.object(self.m, "same_container", side_effect=lambda _:self.original),
            patch.object(self.m, "log_data", return_value="safe-fixture"),
            patch.object(self.m, "named_connection", return_value=True),
            patch.object(self.m, "http_ready", return_value=True)]
        for item in self.patches:item.start()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def adopt(self):
        return self.m.adopt(self.work, self.original, IDENTITY, {}, "https://example.test:4123/",
                            self.notifications.append)

    def test_success_is_private_named_reconnect_not_broker_auth_claim(self):
        result = self.adopt()
        self.assertTrue(result["ha_named_connection_observed"])
        self.assertFalse(result["broker_authentication_proven"])
        self.assertEqual(["stop", "private-before-password", "start"], self.events)
        self.assertEqual(0o600, stat.S_IMODE(self.config.stat().st_mode))
        self.assertTrue(json.loads((self.work/"journal.json").read_text())["adoption_completed"])

    def test_start_failure_restores_exact_original_before_broad_permissions(self):
        initial = self.m.started
        calls = [0]
        def fail_once(value):
            calls[0] += 1
            if calls[0] == 1:raise RuntimeError("simulated start failure")
            self.running = True;self.events.append("restored-start")
        initial.side_effect = fail_once
        with self.assertRaises(RuntimeError):self.adopt()
        self.assertEqual(self.original_bytes, self.config.read_bytes())
        self.assertEqual(0o777, stat.S_IMODE(self.storage.stat().st_mode))
        self.assertEqual(0o644, stat.S_IMODE(self.config.stat().st_mode))
        self.assertTrue(self.running)
        self.assertTrue(self.notifications[-1]["rollback_confirmed"])

    def test_bad_final_snapshot_after_stop_restarts_without_overwrite(self):
        def stop_and_change(_):
            self.running = False
            value = document();value["data"]["entries"][0]["data"]["username"] = "concurrent"
            self.config.write_text(json.dumps(value))
        self.m.stopped.side_effect = stop_and_change
        with self.assertRaises(ValueError):self.adopt()
        self.assertTrue(self.running)
        self.assertEqual("concurrent", json.loads(self.config.read_text())["data"]["entries"][0]["data"]["username"])

    def test_postcheck_failure_has_bounded_rollback(self):
        self.m.named_connection.return_value = False
        with patch.object(self.m.time, "monotonic", side_effect=[0, 200]):
            with self.assertRaises(RuntimeError):self.adopt()
        self.assertEqual(self.original_bytes, self.config.read_bytes())
        self.assertTrue(self.running)
        self.assertTrue(self.notifications[-1]["rollback_confirmed"])

    def test_concurrent_credentials_keep_private_modes_and_ha_running(self):
        proposed = self.m.candidate(self.original_bytes, IDENTITY)
        (self.work/"candidate.json").write_bytes(proposed)
        value = json.loads(proposed);value["data"]["entries"][0]["data"]["password"] = "newer"
        self.config.write_text(json.dumps(value));self.storage.chmod(0o700);self.config.chmod(0o600)
        with self.assertRaises(ValueError):self.m.restore(self.work, self.original, IDENTITY)
        self.assertEqual("newer", json.loads(self.config.read_text())["data"]["entries"][0]["data"]["password"])
        self.assertEqual(0o700, stat.S_IMODE(self.storage.stat().st_mode))
        self.assertTrue(self.running)

    def test_watchdog_restores_interrupted_identity_before_reporting(self):
        from types import SimpleNamespace
        proposed = self.m.candidate(self.original_bytes, IDENTITY)
        (self.work/"candidate.json").write_bytes(proposed)
        self.config.write_bytes(proposed);self.storage.chmod(0o700);self.config.chmod(0o600)
        response = self.root/"receipt.json"
        with patch.object(self.m.os, "kill") as kill:
            result = self.m.watchdog_recover(
                self.work, self.original, IDENTITY, 999999, response,
                SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()), {})
        self.assertTrue(result);kill.assert_called_once_with(999999, self.m.signal.SIGKILL)
        self.assertEqual(self.original_bytes, self.config.read_bytes())
        self.assertTrue(json.loads(response.read_text())["rollback_confirmed"])
        self.assertEqual(0o777, stat.S_IMODE(self.storage.stat().st_mode))

    def test_watchdog_preserves_completed_adoption(self):
        saved = json.loads((self.work/"journal.json").read_text());saved["adoption_completed"] = True
        (self.work/"journal.json").write_text(json.dumps(saved))
        with patch.object(self.m.os, "kill") as kill:
            self.assertFalse(self.m.watchdog_recover(self.work, self.original, IDENTITY,
                                                    999999, self.root/"none", None, {}))
        kill.assert_not_called();self.assertEqual([], self.events)

    def test_drift_before_stop_never_restarts_or_changes_permissions(self):
        self.config.write_text("{}")
        with self.assertRaises(ValueError):self.adopt()
        self.assertEqual([], self.events)
        self.assertEqual(0o777, stat.S_IMODE(self.storage.stat().st_mode))


class CutoverEvidenceTest(unittest.TestCase):
    def test_cutover_needs_changed_broker_hash_stage_and_fresh_named_log(self):
        m = load()
        config = "allow_anonymous false\nallow_anonymous false\n"
        current = {"authenticated_policy_installed": True, "active_config_file": "/private/active.conf",
                   "current_config_sha256": m.digest(config.encode()), "stage_root": "/private/stage"}
        evidence = {"stage_root": "/private/stage", "input_sha256": "c"*64}
        files = {m.docker.STATE/"current.json": json.dumps(current).encode(),
                 m.docker.STATE/"stage-evidence.json": json.dumps(evidence).encode(),
                 Path("/private/active.conf"): config.encode()}
        broker = {"Id": "new-broker", "State": {"StartedAt": "2026-10-16T13:00:00.123456789Z"}}
        state = {"original_broker_id": "old-broker", "expected_input_sha256": "c"*64,
                 "ha_origin": "https://example.test:4123/"}
        with patch.object(m, "regular", side_effect=lambda p:files[p]), \
             patch.object(m.docker, "inspect", return_value=broker), \
             patch.object(m, "log_data", return_value="fixture"), \
             patch.object(m, "named_connection", return_value=True) as named, \
             patch.object(m, "http_ready", return_value=True):
            self.assertTrue(m.verify_cutover(state, {}, IDENTITY))
            self.assertGreater(named.call_args.args[2], 1792155599)
            broker["Id"] = "old-broker"
            with self.assertRaises(ValueError):m.verify_cutover(state, {}, IDENTITY)
            broker["Id"] = "new-broker";named.return_value = False
            self.assertFalse(m.verify_cutover(state, {}, IDENTITY))
            current["current_config_sha256"] = "d"*64
            files[m.docker.STATE/"current.json"] = json.dumps(current).encode()
            with self.assertRaises(ValueError):m.verify_cutover(state, {}, IDENTITY)



@unittest.skipUnless(os.getenv("RUN_MQTT_ACL_INTEGRATION") == "1",
                     "isolated real broker opt-in")
class ActualNamedConnectionTest(unittest.TestCase):
    def test_real_v5_named_connection_log_matches_adoption_verifier(self):
        import threading
        import time
        from tests.test_broker_acl_integration import BrokerFixture, PROFILE, PASSWORD
        from scripts.render_broker_acl import render_acl
        m = load();fixture = BrokerFixture(render_acl(PROFILE))
        try:
            since = time.time();ready = threading.Event();results = []
            client = fixture.mqtt.Client(client_id=m.CLIENT_ID, protocol=fixture.mqtt.MQTTv5)
            client.username_pw_set(PROFILE["ha_username"], PASSWORD)
            client.on_connect = lambda c, u, f, rc, *args:(results.append(rc), ready.set())
            fixture.clients.append(client);client.connect("127.0.0.1", fixture.port, keepalive=60)
            client.loop_start();self.assertTrue(ready.wait(3));self.assertEqual(0, results[0])
            until = time.monotonic()+3;found = False
            while time.monotonic()<until:
                if m.named_connection(fixture.docker("logs", "--tail", "100", fixture.name),
                                      PROFILE["ha_username"], since):
                    found = True;break
                time.sleep(0.1)
            self.assertTrue(found, "actual MQTTv5 named connection must qualify")
            self.assertNotEqual(0, fixture.connect(PROFILE["ha_username"], "wrong-password")[1])
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
