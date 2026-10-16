"""HA account adoption, privacy ordering, bounded rollback and reconnect evidence."""
import copy
import io
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import tarfile
import unittest
from unittest.mock import patch, MagicMock

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



class ContainerViewTest(unittest.TestCase):
    def archive(self, name="core.config_entries", uid=0, link=False, duplicate=False):
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w") as archive:
            info = tarfile.TarInfo(name);info.uid = uid
            info.size = 2
            if link:
                info.type = tarfile.SYMTYPE;info.linkname = "/unreviewed";info.size = 0
            archive.addfile(info, None if link else io.BytesIO(b"{}"))
            if duplicate:
                archive.addfile(info, io.BytesIO(b"{}"))
        return out.getvalue()

    def response(self, m, raw):
        conn = MagicMock()
        conn.getresponse.return_value.status = 200
        conn.getresponse.return_value.read.return_value = raw
        return patch.object(m.docker, "DockerHTTP", return_value=conn)

    def test_actual_view_is_hashed_and_drift_refused(self):
        m = load()
        with self.response(m, self.archive()):
            m.require_container_view("ha", "/config/.storage/core.config_entries", b"{}", 0)
            with self.assertRaisesRegex(ValueError, "configuration views differ"):
                m.require_container_view("ha", "/config/.storage/core.config_entries", b"other", 0)

    def test_wrong_owner_link_path_and_duplicate_refused_without_extraction(self):
        m = load()
        for raw in (self.archive(uid=1026), self.archive(link=True),
                    self.archive(name="../core.config_entries"), self.archive(duplicate=True)):
            with self.subTest(), self.response(m, raw), self.assertRaises(ValueError):
                m.container_file("ha", "/config/.storage/core.config_entries", 0)


class ObservationPreflightTest(unittest.TestCase):
    def fixture(self, m):
        sock = MagicMock()
        sock.recv.return_value = b"\x20\x03\x00\x00\x00"
        sock.__enter__.return_value = sock
        return sock

    def test_delayed_fresh_notice_qualifies_without_publish_subscribe_or_ha_identity(self):
        m = load();sock = self.fixture(m)
        with patch.object(m.socket, "create_connection", return_value=sock), \
             patch.object(m.time, "time", return_value=1000), \
             patch.object(m.time, "monotonic", side_effect=[0, 0, 1]), \
             patch.object(m.time, "sleep"), \
             patch.object(m, "log_data", side_effect=["", "fresh"]), \
             patch.object(m, "named_connection", side_effect=[False, True]) as match:
            m.verify_observation({"docker": True})
        packets = [call.args[0] for call in sock.sendall.call_args_list]
        self.assertEqual([16, 224], [packet[0] for packet in packets])
        self.assertNotIn(m.CLIENT_ID.encode(), packets[0])
        self.assertTrue(match.call_args.args[3].startswith("ha-log-probe-"))
        self.assertEqual(1000, match.call_args.args[2])

    def test_missing_notice_stops_before_ha_adoption(self):
        m = load();sock = self.fixture(m)
        with patch.object(m.socket, "create_connection", return_value=sock), \
             patch.object(m.time, "monotonic", side_effect=[0, 0, 16]), \
             patch.object(m.time, "sleep"), patch.object(m, "log_data", return_value=""), \
             patch.object(m, "named_connection", return_value=False), \
             patch.object(m, "stopped") as stop, \
             self.assertRaisesRegex(ValueError, "HA was not stopped"):
            m.verify_observation({"docker": True})
        stop.assert_not_called()

    def test_refused_connection_never_reaches_log_or_stop(self):
        m = load();sock = self.fixture(m)
        sock.recv.return_value = b"\x20\x03\x00\x87\x00"
        with patch.object(m.socket, "create_connection", return_value=sock), \
             patch.object(m, "log_data") as logs, \
             self.assertRaisesRegex(ValueError, "probe was refused"):
            m.verify_observation({"docker": True})
        logs.assert_not_called()


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
        formatted = "2026-10-16T13:00:01.123456789Z 2026-10-16T22:00:01: New client connected from 127.0.0.1:3000 as "+m.CLIENT_ID+" (p5, c1, k60, u'ha-example')."
        self.assertTrue(m.named_connection(formatted, IDENTITY["username"], 1792155600.5))
        self.assertFalse(m.named_connection(formatted, IDENTITY["username"], 1792155602))
        self.assertFalse(m.named_connection(formatted.split(" ", 1)[1], IDENTITY["username"], 1792155600))
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
            patch.object(self.m, "regular", side_effect=lambda p, *a, **kw: p.read_bytes()),
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
        evidence = {"stage_root": "/private/stage", "input_sha256": "c"*64, "broker_uid": 1883}
        files = {m.docker.STATE/"current.json": json.dumps(current).encode(),
                 m.docker.STATE/"stage-evidence.json": json.dumps(evidence).encode(),
                 Path("/private/active.conf"): config.encode()}
        broker = {"Id": "new-broker", "State": {"StartedAt": "2026-10-16T13:00:00.123456789Z"}}
        state = {"original_broker_id": "old-broker", "expected_input_sha256": "c"*64,
                 "ha_origin": "https://example.test:4123/"}
        with patch.object(m, "regular", side_effect=lambda p, **kw:files[p]), \
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
    def test_real_legacy_connect_only_marker_proves_transport_before_ha_stop(self):
        import socket
        from tests.test_broker_acl_integration import BrokerFixture, PROFILE
        from scripts.render_broker_acl import render_acl
        m = load();fixture = BrokerFixture(render_acl(PROFILE))
        try:
            config = fixture.directory/"mosquitto.conf"
            config.write_text("listener 1883\nallow_anonymous true\npersistence false\n"
                              "connection_messages true\nlog_dest stdout\nlog_type notice\n"
                              "log_timestamp_format %Y-%m-%dT%H:%M:%S\n")
            fixture.docker("restart", fixture.name)
            fixture.port = int(fixture.docker("port", fixture.name, "1883/tcp").strip().rsplit(":", 1)[1])
            real_http = m.docker.DockerHTTP
            class FixtureHTTP(real_http):
                def request(self, method, url, *args, **kwargs):
                    return super().request(method, url.replace("/containers/mosquitto/",
                        "/containers/"+fixture.name+"/", 1), *args, **kwargs)
            connect = socket.create_connection
            def isolated_connect(address, *args, **kwargs):
                if address == ("127.0.0.1", 1883):
                    address = ("127.0.0.1", fixture.port)
                return connect(address, *args, **kwargs)
            with patch.object(m.docker, "DockerHTTP", FixtureHTTP), \
                 patch.object(m.socket, "create_connection", side_effect=isolated_connect), \
                 patch.object(m, "stopped") as stop:
                m.verify_observation({"docker": True})
            stop.assert_not_called()
        finally:
            fixture.close()

    def test_real_v5_named_connection_log_matches_adoption_verifier(self):
        import threading
        import time
        from tests.test_broker_acl_integration import BrokerFixture, PROFILE, PASSWORD
        from scripts.render_broker_acl import render_acl
        m = load();fixture = BrokerFixture(render_acl(PROFILE))
        try:
            config = fixture.directory/"mosquitto.conf"
            with config.open("a") as stream:stream.write("log_timestamp_format %Y-%m-%dT%H:%M:%S\n")
            fixture.docker("restart", fixture.name)
            fixture.port = int(fixture.docker("port", fixture.name, "1883/tcp").strip().rsplit(":", 1)[1])
            since = time.time();ready = threading.Event();results = []
            client = fixture.mqtt.Client(client_id=m.CLIENT_ID, protocol=fixture.mqtt.MQTTv5)
            client.username_pw_set(PROFILE["ha_username"], PASSWORD)
            client.on_connect = lambda c, u, f, rc, *args:(results.append(rc), ready.set())
            fixture.clients.append(client);client.connect("127.0.0.1", fixture.port, keepalive=60)
            client.loop_start();self.assertTrue(ready.wait(3));self.assertEqual(0, results[0])
            real_http = m.docker.DockerHTTP
            class FixtureHTTP(real_http):
                def request(self, method, url, *args, **kwargs):
                    self_test.assertTrue(url.startswith("/containers/mosquitto/logs?"))
                    self_test.assertIn("timestamps=1", url)
                    return super().request(method, url.replace("/containers/mosquitto/",
                        "/containers/"+fixture.name+"/", 1), *args, **kwargs)
            self_test = self
            until = time.monotonic()+3;found = False
            with patch.object(m.docker, "DockerHTTP", FixtureHTTP):
                while time.monotonic()<until:
                    if m.named_connection(m.log_data({"docker": True}, since),
                                          PROFILE["ha_username"], since):
                        found = True;break
                    time.sleep(0.1)
            self.assertTrue(found, "actual MQTTv5 named connection must qualify")
            m.require_container_view(fixture.name, "/fixtures/mosquitto.conf",
                                     config.read_bytes(), os.getuid())
            self.assertNotEqual(0, fixture.connect(PROFILE["ha_username"], "wrong-password")[1])
        finally:
            fixture.close()



@unittest.skipUnless(os.getenv("RUN_HA_PREFLIGHT_DOCKER") == "1",
                     "root filesystem preflight fixture opt-in")
class ActualStorageOwnershipPreflightTest(unittest.TestCase):
    def test_root_storage_in_operator_owned_share_and_refusal_cases(self):
        import subprocess
        image = subprocess.check_output(
            ["docker", "image", "inspect", "python:3.12.13-slim-bookworm",
             "--format", "{{.Id}}"], text=True).strip()
        self.assertRegex(image, r"^sha256:[a-f0-9]{64}$")
        code = r"""
import hashlib,json,os,pathlib,sys,tempfile
sys.path.insert(0,'/repo')
from ops import ha_mqtt_adoption as m
def write(path,data):
 path.write_bytes(data);path.chmod(0o600)
with tempfile.TemporaryDirectory(prefix='ha-owner-preflight-') as tmp:
 root=pathlib.Path(tmp);mounted=root/'homeassistant';mounted.mkdir();os.chown(mounted,1026,0);mounted.chmod(0o777)
 storage=mounted/'.storage';storage.mkdir();storage.chmod(0o777)
 m.CONFIG=storage/'core.config_entries'
 doc={'data':{'entries':[{'domain':'mqtt','entry_id':'fixture','version':2,'minor_version':1,'disabled_by':None,'data':{'broker':'localhost','port':1883,'protocol':'5'},'options':{}}]}}
 raw=json.dumps(doc).encode();write(m.CONFIG,raw);m.CONFIG.chmod(0o644)
 m.PRIVATE=root/'private';m.PRIVATE.mkdir(mode=0o700)
 ops=root/'ops';ops.mkdir();incoming=ops/'incoming';incoming.mkdir();state=ops/'state';state.mkdir()
 m.docker.OPS=ops;m.docker.INCOMING=incoming;m.docker.STATE=state
 contents={'inventory.json':json.dumps({'ha_username':'ha-fixture'}).encode(),'credentials-new.json':json.dumps({'ha-fixture':'a'*64}).encode(),'acl.candidate':b'fixture-only','expected.json':b'null'}
 for name,value in contents.items():write(incoming/name,value)
 digest=hashlib.sha256(b'\0'.join(contents[name] for name in ('inventory.json','credentials-new.json','acl.candidate','expected.json'))).hexdigest()
 write(state/'stage-evidence.json',json.dumps({'input_sha256':digest,'validation':{'isolated_auth_cases':16}}).encode())
 write(ops/'config.json',json.dumps({'owner':'root','readiness_url':'https://fixture.test:4442/ready'}).encode())
 m.BROKER_CONFIG=root/'mosquitto.conf';conf=b'allow_anonymous true\nlog_dest stdout\n';write(m.BROKER_CONFIG,conf)
 os.chown(m.BROKER_CONFIG,1026,0);m.BROKER_CONFIG.chmod(0o777)
 evidence=json.loads((state/'stage-evidence.json').read_bytes())
 evidence.update(originals={str(m.BROKER_CONFIG):{'uid':1026}},broker_uid=1883,stage_root=str(m.PRIVATE/'stage'))
 write(state/'stage-evidence.json',json.dumps(evidence).encode())
 ha={'Name':'/homeassistant','Id':'ha-fixture','Image':'fixture-image','State':{'Running':True},'Config':{'User':''},'HostConfig':{'AutoRemove':False,'NetworkMode':'host'},'Mounts':[{'Destination':'/config','Source':str(mounted),'RW':True}]}
 m.docker.inspect=lambda name:ha if name=='homeassistant' else {'Id':'fixture-broker','Mounts':[]}
 def top(method,path,*args):
  assert method=='GET' and path.endswith('/top?ps_args=-eo%20pid,uid,comm')
  return {'Processes':[['4321','0','python3']]}
 m.docker.api=top
 m.log_data=lambda *args:''
 m.require_container_view=lambda *args:None
 m.verify_observation=lambda *args:None
 plan={'expected_config_sha256':m.digest(raw),'expected_input_sha256':digest,'expected_broker_config_sha256':m.digest(conf),'report_key':'ha-mqtt-adopt-fixture-01','report_owner':'root','ha_origin':'https://fixture.test:4123/'}
 assert m.preflight(plan)[0]['Id']=='ha-fixture'
 os.chown(m.BROKER_CONFIG,1033,0)
 try:m.preflight(plan)
 except ValueError:pass
 else:raise AssertionError('unexpected legacy broker owner accepted')
 os.chown(m.BROKER_CONFIG,1026,0)
 secured=b'allow_anonymous false\nallow_anonymous false\n'
 active=m.PRIVATE/'active.conf';write(active,secured);os.chown(active,1883,1883)
 current={'authenticated_policy_installed':True,'active_config_file':str(active),'current_config_sha256':m.digest(secured),'stage_root':evidence['stage_root']}
 write(state/'current.json',json.dumps(current).encode())
 m.docker.inspect=lambda name:ha if name=='homeassistant' else {'Id':'new-broker','State':{'StartedAt':'2026-10-16T13:00:00.000000000Z'}}
 m.log_data=lambda *args:'1792155601: New client connected from 127.0.0.1:3000 as '+m.CLIENT_ID+" (p5, c1, k60, u'ha-fixture').\n"
 m.http_ready=lambda *args:True
 verify_state={'original_broker_id':'old-broker','expected_input_sha256':digest,'ha_origin':plan['ha_origin']}
 assert m.verify_cutover(verify_state,{}, {'username':'ha-fixture'})
 os.chown(active,1026,0)
 try:m.verify_cutover(verify_state,{}, {'username':'ha-fixture'})
 except ValueError:pass
 else:raise AssertionError('unexpected active broker owner accepted')
 (state/'current.json').unlink()
 m.docker.inspect=lambda name:ha if name=='homeassistant' else {'Id':'fixture-broker','Mounts':[]}
 assert mounted.stat().st_uid==1026 and storage.stat().st_uid==0
 os.chown(storage,1026,0)
 try:m.preflight(plan)
 except ValueError:pass
 else:raise AssertionError('operator-owned credential storage accepted')
 os.chown(storage,0,0);storage.rename(mounted/'saved-storage');storage.symlink_to(mounted/'saved-storage',target_is_directory=True)
 try:m.preflight(plan)
 except ValueError:pass
 else:raise AssertionError('symlink storage accepted')
 print('mixed_owner_full_preflight_and_refusals_verified=true')
"""
        result = subprocess.run(
            ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
             "--user", "0:0", "--tmpfs", "/tmp:rw,nosuid,nodev",
             "-v", str(ROOT)+":/repo:ro", "--entrypoint", "python", image,
             "-B", "-I", "-"], input=code, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr[-1600:])
        self.assertIn("mixed_owner_full_preflight_and_refusals_verified=true", result.stdout)


if __name__ == "__main__":
    unittest.main()
