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
    def test_real_hup_recovers_notices_without_evicting_existing_connection(self):
        import socket
        from tests.test_broker_acl_integration import BrokerFixture, PROFILE
        from scripts.render_broker_acl import render_acl
        m = load();fixture = BrokerFixture(render_acl(PROFILE))
        try:
            config = fixture.directory/"mosquitto.conf"
            config.write_text("listener 1883\nallow_anonymous true\npersistence false\n"
                              "connection_messages false\nlog_dest stdout\nlog_type notice\n"
                              "log_timestamp_format %Y-%m-%dT%H:%M:%S\n")
            fixture.docker("restart", fixture.name)
            fixture.port = int(fixture.docker("port", fixture.name, "1883/tcp").strip().rsplit(":", 1)[1])
            def field(value):
                raw = value.encode();return len(raw).to_bytes(2, "big")+raw
            body = field("MQTT")+bytes([5, 2, 0, 30, 0])+field("fixture-held-connection")
            with socket.create_connection(("127.0.0.1", fixture.port), timeout=3) as held:
                held.settimeout(3);held.sendall(bytes([16, len(body)])+body)
                self.assertEqual(0, held.recv(128)[3])
                before = m.docker.inspect(fixture.name)
                config.write_text(config.read_text().replace("connection_messages false", "connection_messages true"))
                m.docker.api("POST", "/containers/"+fixture.name+"/kill?signal=HUP")
                after = m.docker.inspect(fixture.name)
                self.assertEqual(before["Id"], after["Id"])
                self.assertEqual(before["State"]["StartedAt"], after["State"]["StartedAt"])
                held.sendall(bytes([192, 0]));self.assertEqual(bytes([208, 0]), held.recv(128))
                real_http = m.docker.DockerHTTP
                class FixtureHTTP(real_http):
                    def request(self, method, url, *args, **kwargs):
                        return super().request(method, url.replace("/containers/mosquitto/",
                            "/containers/"+fixture.name+"/", 1), *args, **kwargs)
                connect = socket.create_connection
                def isolated_connect(address, *args, **kwargs):
                    if address == ("fixture-nas", 1883):
                        address = ("127.0.0.1", fixture.port)
                    return connect(address, *args, **kwargs)
                with patch.object(m.docker, "DockerHTTP", FixtureHTTP), \
                     patch.object(m.socket, "create_connection", side_effect=isolated_connect):
                    m.verify_observation({"docker": True, "probe_host": "fixture-nas"})
                held.sendall(bytes([224, 0]))
        finally:
            fixture.close()


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




class FixedHaGatewayTest(unittest.TestCase):
    def load_gateway(self):
        spec = importlib.util.spec_from_file_location(
            "fixed_ha_gateway_test", ROOT/"scripts/nas_ha_ops/ha_ops.py")
        m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        return m

    def test_dispatch_rejects_shell_files_arguments_and_unknown_operations(self):
        import subprocess
        script = ROOT/"scripts/nas_ha_ops/ssh_dispatch.sh"
        for command in ("", "id", "sudo -n sh", "status; id", "adopt /tmp/plan",
                        "diagnose --all", "refresh-logging\nid", "$(id)"):
            env = dict(os.environ);env["SSH_ORIGINAL_COMMAND"] = command
            result = subprocess.run(["sh", str(script)], env=env, capture_output=True)
            self.assertEqual(126, result.returncode, command)

    def test_client_refuses_wrong_permissions_and_never_uses_password_fallback(self):
        spec = importlib.util.spec_from_file_location(
            "fixed_ha_client_test", ROOT/"scripts/nas_ha_ops/client.py")
        m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory/"connection.json").write_text(json.dumps(
                {"host": "100.95.243.92", "port": 8822, "username": "fixture"}))
            (directory/"connection.json").chmod(0o600)
            (directory/"nas-ha-ops-ed25519").write_text("fixture-not-a-real-key")
            (directory/"nas-ha-ops-ed25519").chmod(0o600)
            args = m.ssh_arguments(directory)
            self.assertIn("BatchMode=yes", args)
            self.assertIn("PasswordAuthentication=no", args)
            self.assertIn("IdentitiesOnly=yes", args)
            self.assertEqual(("status", "diagnose", "refresh-logging", "adopt", "verify", "rollback"), m.COMMANDS)
            (directory/"nas-ha-ops-ed25519").chmod(0o644)
            with self.assertRaises(ValueError):
                m.ssh_arguments(directory)

    def test_authenticated_broker_blocks_ha_credential_removal(self):
        m = self.load_gateway()
        helper = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            helper.docker.STATE = Path(tmp)
            (Path(tmp)/"current.json").write_text("{}")
            with patch.object(m, "bindings", return_value=({}, {}, {})), \
                 self.assertRaisesRegex(ValueError, "roll back the authenticated broker"):
                m.rollback({}, helper)
        helper.restore.assert_not_called()

    def test_unfinished_adoption_is_left_to_its_guarded_watchdog(self):
        m = self.load_gateway();helper = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            helper.docker.STATE = Path(tmp)
            with patch.object(m, "bindings", return_value=({}, {}, {})), \
                 patch.object(m, "session", return_value={"work": "/private/ha-adopt-fixture"}), \
                 patch.object(m, "journal", return_value={"phase": "identity_installed"}), \
                 self.assertRaisesRegex(ValueError, "existing watchdog"):
                m.rollback({}, helper)
        helper.restore.assert_not_called()

    def test_repeated_adoption_never_restarts_an_already_adopted_ha(self):
        m = self.load_gateway();helper = MagicMock()
        with patch.object(m, "bindings", return_value=({}, {}, {})), \
             patch.object(m, "session", return_value={"work": "/private/ha-adopt-fixture"}), \
             patch.object(m, "journal", return_value={"adoption_completed": True}):
            result = m.adopt({}, helper, "a"*32)
        self.assertEqual({"already_adopted": True, "no_restart": True}, result)
        helper.start_session.assert_not_called()

    def test_owner_report_alone_cannot_authorize_authenticated_verification(self):
        m = self.load_gateway();helper = MagicMock()
        with patch.object(m, "bindings", return_value=({}, {}, {})), \
             patch.object(m, "session", return_value={"work": "/private/ha-adopt-fixture"}), \
             patch.object(m, "journal", return_value={"phase": "prepared"}), \
             self.assertRaisesRegex(ValueError, "root-journaled"):
            m.verify({}, helper)
        helper.verify_cutover.assert_not_called()

    def test_wrong_operation_cannot_reach_any_docker_or_ha_method(self):
        m = self.load_gateway();helper = MagicMock()
        for operation in ("apply", "sh", "receive", "adopt /tmp/input"):
            with self.assertRaises(ValueError):
                m.perform(operation, "a"*32, {}, helper)
        helper.docker.api.assert_not_called()
        helper.start_session.assert_not_called()

    def test_failure_records_a_bounded_job_without_printing_staged_secrets(self):
        m = self.load_gateway()
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(m, "STATE", Path(tmp)), \
             patch.object(m, "perform", side_effect=ValueError("fixed refusal")), \
             patch.object(m.signal, "signal"), patch.object(m.signal, "alarm"):
            m.worker("adopt", "a"*32, {}, MagicMock())
            result = json.loads((Path(tmp)/"job.json").read_text())
            self.assertEqual("failed", result["state"])
            self.assertEqual("ValueError", result["error_type"])
            self.assertEqual(0o600, stat.S_IMODE((Path(tmp)/"job.json").stat().st_mode))

    def test_adoption_entrypoint_always_requires_fresh_observation(self):
        m = load()
        with patch.object(m, "preflight", side_effect=ValueError("fixture refusal")) as preflight:
            with self.assertRaises(ValueError):
                m.start_session({"fixture": True}, apply=True)
        preflight.assert_called_once_with({"fixture": True})


@unittest.skipUnless(os.getenv("RUN_HA_PREFLIGHT_DOCKER") == "1",
                     "root forced-key installation fixture opt-in")
class ActualHaKeyBootstrapTest(unittest.TestCase):
    def test_install_preserves_old_keys_and_rolls_back_failed_privilege_registration(self):
        import subprocess
        image = subprocess.check_output(
            ["docker", "image", "inspect", "python:3.12.13-slim-bookworm",
             "--format", "{{.Id}}"], text=True).strip()
        code = r"""
import hashlib,importlib.util,json,os,pathlib,pwd,subprocess,sys,tempfile,types
sys.path.insert(0,'/repo')
spec=importlib.util.spec_from_file_location('ha_boot','/repo/scripts/nas_ha_ops/bootstrap.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
real_pwd=pwd.getpwnam
with tempfile.TemporaryDirectory(prefix='ha-fixed-key-fixture-') as tmp:
 base=pathlib.Path(tmp);base.chmod(0o711)
 local=base/'usr/local/lib';local.mkdir(parents=True)
 for p in (base/'usr',base/'usr/local',local):p.chmod(0o755)
 home=base/'home';home.mkdir();home.chmod(0o755)
 user_home=home/'operator';user_home.mkdir(mode=0o700);os.chown(user_home,65534,65534)
 ssh=user_home/'.ssh';ssh.mkdir(mode=0o700);os.chown(ssh,65534,65534)
 auth=ssh/'authorized_keys';original=b'ssh-ed25519 existing-deploy-key\nssh-ed25519 existing-broker-key\n'
 auth.write_bytes(original);auth.chmod(0o600);os.chown(auth,65534,65534)
 etc=base/'etc';etc.mkdir();sudoers=etc/'sudoers';sudo_original=b'root ALL=(ALL) ALL\n';sudoers.write_bytes(sudo_original);sudoers.chmod(0o440)
 m.ROOT=local/'smart-gatekeeper-ha-ops';m.PROGRAM=m.ROOT/'bin/ha_ops.py';m.SUDOERS=sudoers;m.PYTHON=sys.executable
 m.DESTINATIONS={name:m.ROOT/relative for name,relative in {'ha_ops.py':'bin/ha_ops.py','ssh_dispatch.sh':'bin/ssh_dispatch.sh','activate.py':'lib/activate.py','ha_mqtt_adoption.py':'lib/ha_mqtt_adoption.py'}.items()}
 audit=pathlib.Path('/var/run/sgk-broker-audit');audit.mkdir(parents=True,exist_ok=True)
 user=types.SimpleNamespace(pw_uid=65534,pw_gid=65534,pw_dir=str(user_home))
 m.pwd.getpwnam=lambda name:user if name=='nobody' else real_pwd(name)
 package=base/'package';package.mkdir()
 payload={'ha_ops.py':b'print("{}")\n','ssh_dispatch.sh':b'#!/bin/sh\nexit 126\n','activate.py':b'# fixture\n','ha_mqtt_adoption.py':b'# fixture\n','config.json':json.dumps({'owner':'nobody'}).encode(),'ha-key.pub':b'ssh-ed25519 AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA fixture-key'}
 manifest={}
 for name,raw in payload.items():(package/name).write_bytes(raw);manifest[name]=hashlib.sha256(raw).hexdigest()
 raw=json.dumps(manifest).encode();(package/'manifest.json').write_bytes(raw);pin=hashlib.sha256(raw).hexdigest()
 fail={'enabled':True};seen=[]
 def run(args,**kw):
  seen.append(args)
  if fail['enabled'] and args[:3]==['/usr/bin/sudo','-n',str(m.PROGRAM)]:
   raise RuntimeError('injected no-password sudo refusal')
  return types.SimpleNamespace(stdout=b'{"schema_version":1}',stderr=b'',returncode=0)
 m.run=run
 try:m.install(package,pin)
 except RuntimeError as e:assert 'injected' in str(e)
 else:raise AssertionError('failed registration unexpectedly succeeded')
 assert sudoers.read_bytes()==sudo_original and auth.read_bytes()==original
 assert not (m.ROOT/'state/setup.json').exists()
 fail['enabled']=False;m.install(package,pin)
 contents=auth.read_bytes()
 assert contents.startswith(original) and contents.count(b'fixture-key')==1
 assert b'restrict,from="100.64.0.0/10,127.0.0.1",command="' in contents
 receipt=json.loads((m.ROOT/'state/setup.json').read_text())
 assert receipt['general_shell'] is False and receipt['existing_broker_key_preserved'] is True
 assert len(receipt['commands'])==6
 assert auth.stat().st_uid==65534 and (auth.stat().st_mode&0o777)==0o600
 assert sudoers.read_bytes().startswith(sudo_original)
 assert b'NOPASSWD:' in sudoers.read_bytes() and b' ha_ops.py *' not in sudoers.read_bytes()
 print('fixed_ha_install_preservation_and_registration_rollback_passed=true')
"""
        result = subprocess.run(
            ["docker", "run", "--rm", "-i", "--read-only", "--network", "none",
             "--user", "0:0", "--tmpfs", "/tmp:rw,nosuid,nodev",
             "--tmpfs", "/run:rw,nosuid,nodev", "-v", str(ROOT)+":/repo:ro",
             "--entrypoint", "python", image, "-B", "-I", "-"],
            input=code, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr[-2500:])
        self.assertIn("fixed_ha_install_preservation_and_registration_rollback_passed=true", result.stdout)




class HaLoggingRecoveryTest(unittest.TestCase):
    load_gateway = FixedHaGatewayTest.load_gateway
    def fixture(self, tmp):
        import hashlib
        m = self.load_gateway();helper = MagicMock()
        root = Path(tmp);state = root/"broker-state";state.mkdir()
        config_dir = root/"broker-config";config_dir.mkdir()
        text = b"connection_messages true\nlog_dest stdout\nlistener 1883\nallow_anonymous true\nlistener 8883\nallow_anonymous true\n"
        files = {"mosquitto.conf": text, "cert.pem": b"fixture-cert",
                 "chain.pem": b"fixture-chain", "privkey.pem": b"fixture-key"}
        evidence = {"broker_uid": 1883, "broker_gid": 1883, "originals": {}}
        for name, raw in files.items():
            path = config_dir/name;path.write_bytes(raw)
            evidence["originals"][str(path)] = {"uid": 1000, "sha256": hashlib.sha256(raw).hexdigest()}
        (state/"stage-evidence.json").write_text(json.dumps(evidence))
        helper.BROKER_CONFIG = config_dir/"mosquitto.conf";helper.docker.STATE = state
        helper.regular.side_effect = lambda path, **kw:Path(path).read_bytes()
        helper.digest.side_effect = lambda raw:hashlib.sha256(raw).hexdigest()
        helper.atomic.side_effect = lambda path, raw, **kw:Path(path).write_bytes(raw)
        helper.preflight.return_value = ({}, {}, {"docker": True, "probe_host": "fixture-nas"}, b"{}")
        helper.docker.DOCKER = "/fixture/docker"
        broker = {"Id": "broker-fixture", "Image": "sha256:"+"b"*64,
                  "State": {"Running": True, "StartedAt": "fixture-start"}}
        helper.docker.inspect.return_value = broker
        return m, helper, broker, evidence, files

    def test_same_config_hup_has_no_ha_stop_and_uses_isolated_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            m, helper, broker, evidence, files = self.fixture(tmp)
            before = {name:(helper.BROKER_CONFIG.parent/name).read_bytes() for name in files}
            with patch.object(m, "STATE", Path(tmp)), \
                 patch.object(m, "bindings", return_value=({}, broker, {})), \
                 patch.object(m.os, "chown"), patch.object(m.time, "sleep"), \
                 patch.object(m.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
                result = m.refresh_logging({"plan": {"fixture": True}}, helper)
            helper.preflight.assert_called_once_with({"fixture": True}, prove_observation=False)
            helper.docker.api.assert_called_once_with("POST", "/containers/broker-fixture/kill?signal=HUP")
            helper.stopped.assert_not_called()
            args = run.call_args.args[0]
            self.assertIn("--read-only", args);self.assertIn("none", args)
            self.assertIn("--test-config", args);self.assertIn(broker["Image"], args)
            self.assertFalse(result["ha_stopped"]);self.assertFalse(result["credentials_changed"])
            self.assertEqual(before, {name:(helper.BROKER_CONFIG.parent/name).read_bytes() for name in files})

    def test_tls_drift_blocks_validation_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            m, helper, broker, evidence, files = self.fixture(tmp)
            (helper.BROKER_CONFIG.parent/"privkey.pem").write_bytes(b"changed")
            with patch.object(m, "bindings", return_value=({}, broker, {})), \
                 self.assertRaisesRegex(ValueError, "broker/TLS file changed"):
                m.refresh_logging({"plan": {}}, helper)
            helper.docker.api.assert_not_called()

    def test_invalid_configuration_never_sends_hup(self):
        with tempfile.TemporaryDirectory() as tmp:
            m, helper, broker, evidence, files = self.fixture(tmp)
            with patch.object(m, "STATE", Path(tmp)), \
                 patch.object(m, "bindings", return_value=({}, broker, {})), \
                 patch.object(m.os, "chown"), \
                 patch.object(m.subprocess, "run", return_value=MagicMock(returncode=1)), \
                 self.assertRaisesRegex(ValueError, "did not validate"):
                m.refresh_logging({"plan": {}}, helper)
            helper.docker.api.assert_not_called()



class SignedMaintenanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp)/"signer.pem"
            subprocess.run(["openssl", "genpkey", "-algorithm", "RSA",
                "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(key)],
                check=True, capture_output=True, timeout=30)
            cls.private_bytes = key.read_bytes()
            cls.public_bytes = subprocess.check_output(
                ["openssl", "pkey", "-in", str(key), "-pubout"], timeout=15)

    def setUp(self):
        import shutil
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name);self.state = self.root/"state";self.state.mkdir(mode=0o700)
        (self.root/"security").mkdir()
        (self.root/"security/signer-public.pem").write_bytes(self.public_bytes)
        (self.root/"signer-private.pem").write_bytes(self.private_bytes)
        (self.root/"signer-private.pem").chmod(0o600)
        self.openssl = shutil.which("openssl")
        self.assertTrue(self.openssl)
        spec = importlib.util.spec_from_file_location(
            "signed_gateway_test", ROOT/"scripts/nas_maintenance/gateway.py")
        self.g = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.g)
        self.g.ROOT = self.root;self.g.STATE = self.state
        spec = importlib.util.spec_from_file_location(
            "signed_client_test", ROOT/"scripts/nas_maintenance/client.py")
        self.c = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.c)
        self.config = {"openssl_path": self.openssl}

    def tearDown(self):
        self.tmp.cleanup()

    def packet(self, code=b'import json\nprint(json.dumps({"fixture":True}))\n', identifier=None):
        return self.c.envelope(code, "readonly-fixture", 5, self.root, identifier)

    def test_real_rsa_signature_accepts_only_exact_manifest_and_script(self):
        raw = self.packet();manifest, script = self.g.validate(raw, self.config)
        self.assertEqual("readonly-fixture", manifest["operation"])
        value = json.loads(raw);value["manifest"]["operation"] = "different-action"
        with self.assertRaisesRegex(ValueError, "signature rejected"):
            self.g.validate(json.dumps(value).encode(), self.config)
        value = json.loads(raw);value["script"] = __import__("base64").b64encode(b"print('changed')").decode()
        with self.assertRaisesRegex(ValueError, "content mismatch"):
            self.g.validate(json.dumps(value).encode(), self.config)

    def test_expiry_future_clock_and_unbounded_deadline_refused(self):
        value = json.loads(self.packet())
        epoch = value["manifest"]["issued_at"]
        with self.assertRaises(ValueError):
            self.g.validate(json.dumps(value).encode(), self.config, now=epoch+901)
        with self.assertRaises(ValueError):
            self.g.validate(json.dumps(value).encode(), self.config, now=epoch-61)
        value["manifest"]["timeout_seconds"] = 901
        with self.assertRaises(ValueError):
            self.g.validate(json.dumps(value).encode(), self.config, now=epoch)

    def test_unknown_fields_base64_and_signature_fail_closed(self):
        value = json.loads(self.packet());value["path"] = "/etc/sudoers"
        with self.assertRaises(ValueError):
            self.g.validate(json.dumps(value).encode(), self.config)
        value = json.loads(self.packet());value["signature"] = __import__("base64").b64encode(bytes(384)).decode()
        with self.assertRaisesRegex(ValueError, "signature rejected"):
            self.g.validate(json.dumps(value).encode(), self.config)
        value["script"] = "!invalid-base64!"
        with self.assertRaises(ValueError):
            self.g.validate(json.dumps(value).encode(), self.config)

    def test_same_request_replay_never_spawns_another_worker(self):
        (self.state/"requests").mkdir()
        raw = self.packet(identifier="a"*32)
        with patch.object(self.g, "control", side_effect=lambda p, limit=524288:p.read_bytes()), \
             patch.object(self.g, "launch_worker", return_value=MagicMock(pid=987654)) as spawn:
            first = self.g.submit(raw, self.config)
            second = self.g.submit(raw, self.config)
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["idempotent"]);self.assertEqual(1, spawn.call_count)

    def test_cached_client_retry_preserves_signed_bytes(self):
        first = self.packet(identifier="b"*32)
        second = self.packet(identifier="b"*32)
        self.assertEqual(first, second)
        with self.assertRaisesRegex(ValueError, "differs"):
            self.packet(code=b"print('other')\n", identifier="b"*32)

    def test_invalid_signature_cannot_create_a_request_directory(self):
        (self.state/"requests").mkdir()
        value = json.loads(self.packet());value["manifest"]["operation"] = "tampered"
        with self.assertRaises(ValueError):
            self.g.submit(json.dumps(value).encode(), self.config)
        self.assertEqual([], list((self.state/"requests").iterdir()))

    def test_result_receipt_does_not_publish_stderr(self):
        directory = self.state/"execution";directory.mkdir()
        (directory/"script.py").write_text(
            'import json,sys\nprint("fixture-private-stderr",file=sys.stderr)\nprint(json.dumps({"ok":True}))\n')
        result = self.g.execute(directory, {"timeout_seconds": 5})
        self.assertEqual(0, result["returncode"])
        self.assertTrue(result["json_result_available"])
        self.assertNotIn("fixture-private-stderr", json.dumps(result))
        self.assertEqual({"ok": True}, json.loads((directory/"result.json").read_text()))
        self.assertEqual(0o600, stat.S_IMODE((directory/"stderr.private").stat().st_mode))

    def test_execution_timeout_is_terminal_without_a_result(self):
        directory = self.state/"timeout";directory.mkdir()
        (directory/"script.py").write_text('import time\ntime.sleep(10)\n')
        result = self.g.execute(directory, {"timeout_seconds": 1})
        self.assertTrue(result["timed_out"]);self.assertFalse((directory/"result.json").exists())

    def test_ordinary_shell_and_file_requests_are_refused(self):
        import subprocess
        script = ROOT/"scripts/nas_maintenance/ssh_dispatch.sh"
        for command in ("id", "submit /tmp/code", "status; id", "result ../other", "sh"):
            env = dict(os.environ);env["SSH_ORIGINAL_COMMAND"] = command
            result = subprocess.run(["sh", str(script)], env=env, capture_output=True)
            self.assertEqual(126, result.returncode)

    def test_untrusted_control_owner_and_symlink_are_refused(self):
        path = self.root/"other";path.write_text("fixture")
        link = self.root/"link";link.symlink_to(path)
        with self.assertRaises(ValueError):
            self.g.control(link)
        fake = MagicMock()
        fake.lstat.return_value.st_mode = stat.S_IFREG|0o600
        fake.lstat.return_value.st_uid = 12345
        with self.assertRaises(ValueError):
            self.g.control(fake)


@unittest.skipUnless(os.getenv("RUN_HA_PREFLIGHT_DOCKER") == "1", "root signed-maintenance install fixture opt-in")
class ActualSignedMaintenanceBootstrapTest(unittest.TestCase):
    def test_install_preserves_old_keys_and_rolls_back_failed_privilege_registration(self):
        import subprocess
        image = subprocess.check_output(
            ["docker", "image", "inspect", "python:3.12.13-slim-bookworm",
             "--format", "{{.Id}}"], text=True).strip()
        code = r"""
import hashlib,importlib.util,json,os,pathlib,pwd,subprocess,sys,tempfile,types
sys.path.insert(0,'/repo')
spec=importlib.util.spec_from_file_location('ha_boot','/repo/scripts/nas_maintenance/bootstrap.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
real_pwd=pwd.getpwnam
with tempfile.TemporaryDirectory(prefix='ha-fixed-key-fixture-') as tmp:
 base=pathlib.Path(tmp);base.chmod(0o711)
 local=base/'usr/local/lib';local.mkdir(parents=True)
 for p in (base/'usr',base/'usr/local',local):p.chmod(0o755)
 home=base/'home';home.mkdir();home.chmod(0o755)
 user_home=home/'operator';user_home.mkdir(mode=0o700);os.chown(user_home,65534,65534)
 ssh=user_home/'.ssh';ssh.mkdir(mode=0o700);os.chown(ssh,65534,65534)
 auth=ssh/'authorized_keys';original=b'ssh-ed25519 existing-deploy-key\nssh-ed25519 existing-broker-key\n'
 auth.write_bytes(original);auth.chmod(0o600);os.chown(auth,65534,65534)
 etc=base/'etc';etc.mkdir();sudoers=etc/'sudoers';sudo_original=b'root ALL=(ALL) ALL\n';sudoers.write_bytes(sudo_original);sudoers.chmod(0o440)
 m.ROOT=local/'smart-gatekeeper-maintenance';m.PROGRAM=m.ROOT/'bin/gateway.py';m.SUDOERS=sudoers;m.PYTHON=sys.executable
 m.DESTINATIONS={name:m.ROOT/relative for name,relative in {'gateway.py':'bin/gateway.py','ssh_dispatch.sh':'bin/ssh_dispatch.sh','signer-public.pem':'security/signer-public.pem'}.items()}
 audit=pathlib.Path('/var/run/sgk-broker-audit');audit.mkdir(parents=True,exist_ok=True)
 user=types.SimpleNamespace(pw_uid=65534,pw_gid=65534,pw_dir=str(user_home))
 m.pwd.getpwnam=lambda name:user if name=='nobody' else real_pwd(name)
 package=base/'package';package.mkdir()
 payload={'gateway.py':b'print("{}")\n','ssh_dispatch.sh':b'#!/bin/sh\nexit 126\n','signer-public.pem':b'fixture-public-only\n','config.json':json.dumps({'owner':'nobody'}).encode(),'maintenance-key.pub':b'ssh-ed25519 AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA fixture-key'}
 manifest={}
 for name,raw in payload.items():(package/name).write_bytes(raw);manifest[name]=hashlib.sha256(raw).hexdigest()
 raw=json.dumps(manifest).encode();(package/'manifest.json').write_bytes(raw);pin=hashlib.sha256(raw).hexdigest()
 fail={'enabled':True};seen=[]
 def run(args,**kw):
  seen.append(args)
  if fail['enabled'] and args[:3]==['/usr/bin/sudo','-n',str(m.PROGRAM)]:
   raise RuntimeError('injected no-password sudo refusal')
  return types.SimpleNamespace(stdout=b'{"schema_version":1}',stderr=b'',returncode=0)
 m.run=run
 m.shutil.which=lambda name:sys.executable
 try:m.install(package,pin)
 except RuntimeError as e:assert 'injected' in str(e)
 else:raise AssertionError('failed registration unexpectedly succeeded')
 assert sudoers.read_bytes()==sudo_original and auth.read_bytes()==original
 assert not (m.ROOT/'state/setup.json').exists()
 fail['enabled']=False;m.install(package,pin)
 contents=auth.read_bytes()
 assert contents.startswith(original) and contents.count(b'fixture-key')==1
 assert b'restrict,from="100.64.0.0/10,127.0.0.1",command="' in contents
 receipt=json.loads((m.ROOT/'state/setup.json').read_text())
 assert receipt['interactive_shell'] is False and receipt['signed_root_code_execution'] is True and receipt['existing_broker_key_preserved'] is True
 assert len(receipt['commands'])==3
 assert auth.stat().st_uid==65534 and (auth.stat().st_mode&0o777)==0o600
 assert sudoers.read_bytes().startswith(sudo_original)
 assert b'NOPASSWD:' in sudoers.read_bytes() and b' gateway.py *' not in sudoers.read_bytes()
 print('signed_maintenance_install_preservation_and_registration_rollback_passed=true')
"""
        result = subprocess.run(
            ["docker", "run", "--rm", "-i", "--read-only", "--network", "none",
             "--user", "0:0", "--tmpfs", "/tmp:rw,nosuid,nodev",
             "--tmpfs", "/run:rw,nosuid,nodev", "-v", str(ROOT)+":/repo:ro",
             "--entrypoint", "python", image, "-B", "-I", "-"],
            input=code, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr[-2500:])
        self.assertIn("signed_maintenance_install_preservation_and_registration_rollback_passed=true", result.stdout)


class BrokerPrivateLogFileTest(unittest.TestCase):
    load_gateway = FixedHaGatewayTest.load_gateway

    def test_existing_private_log_is_preserved_and_unsafe_files_refused(self):
        m = self.load_gateway()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp);directory.chmod(0o555)
            path = directory/"mosquitto.log"
            directory.chmod(0o755);path.write_bytes(b"existing-evidence");path.chmod(0o600)
            directory.chmod(0o555)
            broker = {"Mounts": [{"Destination": "/mosquitto/log", "Source": str(directory), "RW": True}]}
            text = "log_dest file /mosquitto/log/mosquitto.log\n"
            try:
                with patch.object(m, "BROKER_LOG", path):
                    result = m.ensure_broker_log(text, broker, os.getuid(), os.getgid())
                    self.assertFalse(result["created"]);self.assertEqual(b"existing-evidence", path.read_bytes())
                    path.chmod(0o644)
                    with self.assertRaisesRegex(ValueError, "private broker-owned"):
                        m.ensure_broker_log(text, broker, os.getuid(), os.getgid())
                    path.chmod(0o600)
                    with self.assertRaisesRegex(ValueError, "bound broker log mount"):
                        m.ensure_broker_log(text, {"Mounts": []}, os.getuid(), os.getgid())
                    self.assertEqual(0o555, stat.S_IMODE(directory.stat().st_mode))
            finally:
                directory.chmod(0o755)

@unittest.skipUnless(os.getenv("RUN_HA_PREFLIGHT_DOCKER") == "1", "real read-only log directory recovery opt-in")
class ActualReadOnlyBrokerLogRecoveryTest(unittest.TestCase):
    def test_missing_file_suppresses_stdout_notice_until_private_file_and_hup(self):
        import subprocess,time,socket,uuid
        from tests.test_broker_acl_integration import IMAGE
        m = load()
        name = "sgk-log-recovery-"+uuid.uuid4().hex[:10]
        def docker(*args):
            return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.STDOUT, timeout=25)
        with tempfile.TemporaryDirectory(prefix="sgk-log-recovery-") as tmp:
            directory = Path(tmp);logs = directory/"log";logs.mkdir();logs.chmod(0o555)
            config = directory/"mosquitto.conf"
            text = ("listener 1883\nallow_anonymous true\npersistence false\nconnection_messages true\n"
                    "log_dest stdout\nlog_dest file /mosquitto/log/mosquitto.log\n"
                    "log_type error\nlog_type warning\nlog_type notice\n"
                    "log_timestamp_format %Y-%m-%dT%H:%M:%S\n")
            config.write_text(text)
            held = None
            try:
                docker("run", "--rm", "-d", "-t", "--name", name, "--user",
                       str(os.getuid())+":"+str(os.getgid()), "--entrypoint", "mosquitto",
                       "-p", "127.0.0.1::1883", "-v", str(directory)+":/fixtures:ro",
                       "-v", str(logs)+":/mosquitto/log", IMAGE, "-c", "/fixtures/mosquitto.conf")
                time.sleep(.5)
                before = json.loads(docker("inspect", name))[0]
                self.assertTrue(before["State"]["Running"])
                port = int(docker("port", name, "1883/tcp").strip().rsplit(":", 1)[1])
                def connect():
                    identifier = "fixture-log-"+uuid.uuid4().hex[:12]
                    def field(value):
                        raw = value.encode();return len(raw).to_bytes(2,"big")+raw
                    body = field("MQTT")+bytes([5,130,0,10,0])+field(identifier)+field(identifier)
                    since = time.time();sock = socket.create_connection(("127.0.0.1",port),timeout=3)
                    sock.sendall(bytes([16,len(body)])+body)
                    reply = b""
                    while len(reply)<5:reply += sock.recv(128)
                    self.assertEqual(0, reply[3])
                    return sock,identifier,since
                held, identifier, since = connect()
                time.sleep(.2)
                self.assertFalse(m.named_connection(docker("logs","--timestamps",name),identifier,since,identifier))
                image = docker("image","inspect","python:3.12.13-slim-bookworm","--format","{{.Id}}").strip()
                code = (
                    "import importlib.util,json,os,pathlib\n"
                    "s=importlib.util.spec_from_file_location('g','/repo/scripts/nas_ha_ops/ha_ops.py')\n"
                    "g=importlib.util.module_from_spec(s);s.loader.exec_module(g)\n"
                    "g.BROKER_LOG=pathlib.Path('/fixtures/log/mosquitto.log')\n"
                    "b={'Mounts':[{'Destination':'/mosquitto/log','Source':'/fixtures/log','RW':True}]}\n"
                    "r=g.ensure_broker_log("+repr(text)+",b,"+str(os.getuid())+","+str(os.getgid())+")\n"
                    "assert r['created'] and (g.BROKER_LOG.stat().st_mode&0o777)==0o600\n"
                    "print(json.dumps(r))\n")
                result = subprocess.run(["docker","run","--rm","-i","--read-only","--network","none",
                    "--user","0:0","-v",str(directory)+":/fixtures","-v",str(ROOT)+":/repo:ro",
                    "--entrypoint","python",image,"-B","-I","-"],input=code,capture_output=True,text=True,timeout=25)
                self.assertEqual(0,result.returncode,result.stderr[-2000:])
                self.assertEqual(0o555,stat.S_IMODE(logs.stat().st_mode))
                self.assertEqual(text,config.read_text())
                docker("kill","--signal","HUP",name);time.sleep(.4)
                after = json.loads(docker("inspect",name))[0]
                self.assertEqual(before["Id"],after["Id"])
                self.assertEqual(before["State"]["StartedAt"],after["State"]["StartedAt"])
                held.sendall(bytes([192,0]));self.assertEqual(bytes([208,0]),held.recv(2))
                with_socket, identifier, since = connect()
                with_socket.sendall(bytes([224,0]));with_socket.close();time.sleep(.2)
                self.assertTrue(m.named_connection(docker("logs","--timestamps",name),identifier,since,identifier))
                self.assertGreater((logs/"mosquitto.log").stat().st_size,0)
            finally:
                if held:held.close()
                subprocess.run(["docker","rm","-f",name],capture_output=True)
                logs.chmod(0o755)


class DockerDatabaseLogTest(unittest.TestCase):
    def fixture(self, directory):
        import sqlite3,types
        m = load();identifier = "a"*64
        m.DOCKER_LOG_ROOT = Path(directory)
        root = Path(directory)/identifier;root.mkdir();path = root/"log.db"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE log_content(docid INTEGER PRIMARY KEY,c0text,c2created)")
        connection.commit();connection.close()
        original = Path.lstat
        def lstat(p, *args, **kwargs):
            value = original(p, *args, **kwargs)
            if p == path:
                return types.SimpleNamespace(st_uid=0,st_mode=value.st_mode)
            return value
        return m,identifier,path,lstat

    def test_real_readonly_sqlite_tail_preserves_utc_identity_and_database(self):
        import sqlite3,hashlib
        with tempfile.TemporaryDirectory() as tmp:
            m,identifier,path,lstat = self.fixture(tmp)
            connection = sqlite3.connect(path)
            for i in range(205):
                text = "1792198000: fixture unrelated"
                if i == 204:
                    text = "2026-10-17T00:46:40: New client connected from 127.0.0.1:1234 as "+m.CLIENT_ID+" (p5, c1, k60, u'ha-fixture')."
                connection.execute("INSERT INTO log_content VALUES(?,?,?)",(i+1,text,"2026-10-17T00:46:40.100000000Z"))
            connection.commit();connection.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.object(Path,"lstat",lstat), patch.object(m.docker,"DockerHTTP") as http:
                text = m.log_data({"docker":True,"driver":"db","container_id":identifier},1792198000)
            http.assert_not_called()
            self.assertEqual(200,len(text.splitlines()))
            self.assertTrue(m.named_connection(text,"ha-fixture",1792198000))
            self.assertFalse(m.named_connection(text,"wrong-user",1792198000))
            self.assertFalse(m.named_connection(text,"ha-fixture",1792198001))
            self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())
            ro = sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True)
            with self.assertRaises(sqlite3.OperationalError):
                ro.execute("DELETE FROM log_content")
            ro.close()

    def test_invalid_container_owner_and_truncated_rows_never_qualify(self):
        import sqlite3,types
        with tempfile.TemporaryDirectory() as tmp:
            m,identifier,path,lstat = self.fixture(tmp)
            connection=sqlite3.connect(path)
            connection.execute("INSERT INTO log_content VALUES(1,?,?)",
                ("1792198000: New client connected from x as "+m.CLIENT_ID+
                 " (p5, c1, k60, u'ha-fixture')."+"x"*1100,"2026-10-17T00:46:40Z"))
            connection.commit();connection.close()
            with patch.object(Path,"lstat",lstat):
                self.assertEqual("",m.database_log_text(identifier))
            with self.assertRaisesRegex(ValueError,"bound Docker"):
                m.database_log_text("../other")
            with self.assertRaisesRegex(ValueError,"root-owned regular"):
                m.database_log_text(identifier)


class DockerDaemonRecoveryTest(unittest.TestCase):
    @staticmethod
    def module():
        spec=importlib.util.spec_from_file_location("docker_recovery_test",ROOT/"scripts/nas_maintenance/recover_dockerd.py")
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

    class Runtime:
        def __init__(self):
            self.raw=b'{"log-driver":"db","bip":"fixture-only","data-root":"fixture-only"}'
            self.original=self.raw;self.clock=0;self.enabled=False;self.restarts=0;self.forced=0
            self.reload_failure=False;self.activation_failure=False;self.hang_stop=False
            self.after_changed=False;self.never_recovers=False
            self.values={str(i):{"pid":1000+i,"started_at":"fixture-start","image":"fixture-image",
                "process_start_ticks":"fixture-ticks","name":"fixture"} for i in range(8)}
        def configuration(self):
            return self.raw,{"path":"/fixture/daemon.json","uid":0,"gid":0,"mode":0o600}
        def service(self):
            pid=100 if not self.restarts or self.hang_stop and not self.forced or self.never_recovers else 200
            return {"MainPID":str(pid),"KillMode":"process","Restart":"always","ActiveState":"active",
                    "ExecStart":"/var/packages/ContainerManager/target/usr/bin/dockerd"}
        def daemon_identity(self):return {"pid":100,"start_ticks":"fixture","executable":"fixture"}
        def info(self):
            return {"ServerVersion":"24.0.2","Swarm":{"LocalNodeState":"inactive"},
                    "ContainersRunning":8,"LiveRestoreEnabled":self.enabled}
        def containers(self):
            import copy
            result=copy.deepcopy(self.values)
            if self.restarts and self.after_changed:result["0"]["pid"]=99999
            return result
        def validate(self,raw):
            assert __import__("json").loads(raw)["live-restore"] is True
        def install(self,raw):self.raw=raw
        def reload(self):
            if self.reload_failure:
                self.reload_failure=False;raise RuntimeError("injected reload refusal")
            self.enabled=json.loads(self.raw).get("live-restore",False) and not self.activation_failure
        def restart(self):self.restarts+=1
        def monotonic(self):return self.clock
        def sleep(self,seconds):self.clock+=seconds
        def old_daemon_stopping(self,p):return self.hang_stop and not self.forced
        def force_stopping_daemon(self,p):self.forced+=1
        def services(self):return {"ha_http_200":True,"backend_readiness":True}
        def fresh_notice(self):pass

    def test_live_restore_precedes_single_daemon_restart_and_all_processes_survive(self):
        m=self.module();runtime=self.Runtime();prepared=m.plan(runtime);events=[]
        result=m.recover(runtime,prepared,events.append)
        self.assertEqual(1,runtime.restarts)
        self.assertEqual(8,result["preserved_container_count"])
        self.assertTrue(result["fresh_connect_only_notice_verified"])
        self.assertEqual("live_restore_verified",events[1]["phase"])
        self.assertEqual("restart_requested",events[2]["phase"])

    def test_reload_or_activation_failure_restores_exact_config_without_restart(self):
        m=self.module()
        for fault in ["reload_failure","activation_failure"]:
            runtime=self.Runtime();prepared=m.plan(runtime);setattr(runtime,fault,True)
            with self.assertRaises((ValueError,RuntimeError)):
                m.recover(runtime,prepared,lambda value:None)
            self.assertEqual(runtime.original,runtime.raw);self.assertEqual(0,runtime.restarts)

    def test_configuration_drift_and_process_changes_are_refused(self):
        m=self.module();runtime=self.Runtime();prepared=m.plan(runtime)
        runtime.raw=b'{"changed":true}'
        with self.assertRaisesRegex(ValueError,"configuration drift"):
            m.recover(runtime,prepared,lambda value:None)
        self.assertEqual(0,runtime.restarts)
        runtime=self.Runtime();prepared=m.plan(runtime);runtime.after_changed=True
        with self.assertRaisesRegex(ValueError,"container process"):
            m.recover(runtime,prepared,lambda value:None)
        self.assertEqual(1,runtime.restarts)

    def test_stalled_daemon_only_has_one_bounded_force_and_no_container_restart(self):
        m=self.module();runtime=self.Runtime();runtime.hang_stop=True;prepared=m.plan(runtime)
        result=m.recover(runtime,prepared,lambda value:None)
        self.assertEqual(1,runtime.restarts);self.assertEqual(1,runtime.forced)
        self.assertTrue(result["old_daemon_force_required"])

    def test_observation_timeout_does_not_trigger_another_restart(self):
        m=self.module();runtime=self.Runtime();runtime.never_recovers=True;prepared=m.plan(runtime)
        with self.assertRaises(TimeoutError):
            m.recover(runtime,prepared,lambda value:None)
        self.assertEqual(1,runtime.restarts);self.assertEqual(0,runtime.forced)


class LocalNasVerifiedHttpsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        cls.tmp=tempfile.TemporaryDirectory()
        cls.certificates={}
        for hostname in ["tworimpa.synology.me","wrong.example"]:
            base=Path(cls.tmp.name)/hostname
            cert=base.with_suffix(".crt");key=base.with_suffix(".key")
            subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes",
                "-days","1","-subj","/CN="+hostname,"-addext","subjectAltName=DNS:"+hostname,
                "-keyout",str(key),"-out",str(cert)],check=True,capture_output=True,timeout=20)
            cls.certificates[hostname]=(cert,key)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def serve(self,hostname="tworimpa.synology.me",payload=b'{"status":"ready"}'):
        import ssl,threading,http.server
        seen=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(("host",self.headers.get("Host")))
                self.send_response(200);self.send_header("Content-Length",str(len(payload)))
                self.end_headers();self.wfile.write(payload)
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cert,key=self.certificates[hostname];context.load_cert_chain(str(cert),str(key))
        context.set_servername_callback(lambda socket,name,ctx:seen.append(("sni",name)))
        server.socket=context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server,seen,cert

    def test_real_https_uses_loopback_with_original_sni_host_and_certificate_verification(self):
        import ssl
        m=load().docker;server,seen,cert=self.serve()
        context=ssl.create_default_context(cafile=str(cert))
        with patch.object(m,"NAS_SELF_HTTPS_PORTS",(server.server_port,)), \
             patch.object(m.ssl,"create_default_context",return_value=context):
            status,raw=m.https_response("https://tworimpa.synology.me:"+str(server.server_port)+"/ready")
        self.assertEqual(200,status);self.assertEqual({"status":"ready"},json.loads(raw))
        self.assertIn(("sni","tworimpa.synology.me"),seen)
        self.assertIn(("host","tworimpa.synology.me:"+str(server.server_port)),seen)
        self.assertTrue(context.check_hostname);self.assertEqual(ssl.CERT_REQUIRED,context.verify_mode)

    def test_trusted_wrong_hostname_and_untrusted_certificate_are_refused(self):
        import ssl
        m=load().docker
        for hostname,trusted in [("wrong.example",True),("tworimpa.synology.me",False)]:
            server,seen,cert=self.serve(hostname)
            context=ssl.create_default_context(cafile=str(cert)) if trusted else ssl.create_default_context()
            with patch.object(m,"NAS_SELF_HTTPS_PORTS",(server.server_port,)), \
                 patch.object(m.ssl,"create_default_context",return_value=context), \
                 self.assertRaises(ssl.SSLCertVerificationError):
                m.https_response("https://tworimpa.synology.me:"+str(server.server_port)+"/ready")
            self.assertFalse(any(x[0]=="host" for x in seen))

    def test_oversized_response_is_refused(self):
        import ssl
        m=load().docker;server,seen,cert=self.serve(payload=b"x"*1024)
        context=ssl.create_default_context(cafile=str(cert))
        with patch.object(m,"NAS_SELF_HTTPS_PORTS",(server.server_port,)), \
             patch.object(m.ssl,"create_default_context",return_value=context), \
             self.assertRaisesRegex(RuntimeError,"bounded HTTPS"):
            m.https_response("https://tworimpa.synology.me:"+str(server.server_port)+"/",limit=128)

    def test_other_origins_keep_normal_https_and_plaintext_is_refused(self):
        m=load().docker;response=MagicMock()
        response.__enter__.return_value=response;response.status=200;response.read.return_value=b"{}"
        with patch.object(m.urllib.request,"urlopen",return_value=response) as request:
            self.assertEqual((200,b"{}"),m.https_response("https://external.example:4442/ready"))
            self.assertEqual("https://external.example:4442/ready",request.call_args.args[0].full_url)
        with self.assertRaisesRegex(ValueError,"verified HTTPS"):
            m.https_response("http://tworimpa.synology.me:4442/ready")


class BrokerCollectorDependencyTest(unittest.TestCase):
    def test_broker_authentication_precedes_collector_and_failure_blocks_collector_start(self):
        m=load().docker;events=[]
        def replace(name,*args):events.append(name)
        def ready(*args):events.append("authenticated-ready");return {"prepared_principal_connect_only_verified":True}
        stage={"policy_root":"/fixture/policy","broker_uid":1883,"broker_gid":1883}
        with patch.object(m,"replace_container",side_effect=replace),patch.object(m,"wait_broker_principal",side_effect=ready):
            result=m.replace_broker_and_collector(stage,Path("/fixture/active"),Path("/fixture/collector"),{}, {},lambda x:None)
        self.assertEqual(["mosquitto","authenticated-ready","telegraf"],events)
        self.assertTrue(result["prepared_principal_connect_only_verified"])
        events.clear()
        with patch.object(m,"replace_container",side_effect=replace), \
             patch.object(m,"wait_broker_principal",side_effect=RuntimeError("not ready")),self.assertRaises(RuntimeError):
            m.replace_broker_and_collector(stage,Path("/fixture/a"),Path("/fixture/c"),{}, {},lambda x:None)
        self.assertEqual(["mosquitto"],events)

    def test_rollback_restores_broker_before_collector_and_captures_before_deletion(self):
        m=load().docker;events=[]
        with patch.object(m,"restore_container",side_effect=lambda item:events.append(item["original"])):
            m.restore_transaction([{"original":"telegraf"},{"original":"mosquitto"}])
        self.assertEqual(["mosquitto","telegraf"],events)
        events.clear()
        item={"original":"telegraf","backup":"telegraf_sgk_previous_"+"a"*10,
              "original_id":"old","original_image":"image","restart_policy":{"Name":"no"}}
        with patch.object(m,"inspect",return_value={"Id":"old","Image":"image"}), \
             patch.object(m,"preserve_replacement_diagnostics",side_effect=lambda *a:events.append("capture")), \
             patch.object(m,"api",side_effect=lambda method,path,*a:events.append(method)):
            m.restore_container(item)
        self.assertEqual(["capture","DELETE","POST","POST","POST"],events)

    def test_connection_deadline_is_bounded_and_auth_refusal_is_not_retried(self):
        m=load().docker
        with patch.object(m.socket,"create_connection",side_effect=OSError()), \
             patch.object(m.time,"monotonic",side_effect=[0,31]),self.assertRaisesRegex(RuntimeError,"readiness deadline"):
            m.wait_broker_principal({"ha_username":"fixture"},{"fixture":"a"*64})
        stream=MagicMock();stream.__enter__.return_value=stream
        stream.recv.side_effect=[bytes([32]),bytes([3]),bytes([0,135,0])]
        with patch.object(m.socket,"create_connection",return_value=stream) as connect, \
             self.assertRaisesRegex(RuntimeError,"principal was refused"):
            m.wait_broker_principal({"ha_username":"fixture"},{"fixture":"a"*64})
        self.assertEqual(1,connect.call_count)

    def test_failed_container_evidence_is_private_and_capture_errors_do_not_block_rollback(self):
        import sqlite3,types
        m=load().docker
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);m.STATE=directory/"state";m.STATE.mkdir()
            m.DOCKER_LOG_ROOT=directory/"containers";identifier="a"*64
            folder=m.DOCKER_LOG_ROOT/identifier;folder.mkdir(parents=True)
            db=folder/"log.db";connection=sqlite3.connect(db)
            connection.execute("CREATE TABLE log_content(docid INTEGER PRIMARY KEY,c0text,c2created)")
            connection.execute("INSERT INTO log_content VALUES(1,?,?)",("fixture-private-failure","2026-10-17T01:00:00Z"))
            connection.commit();connection.close()
            current={"Id":identifier,"Image":"fixture-image","State":{"Status":"exited","ExitCode":1},
                     "RestartCount":1,"HostConfig":{"LogConfig":{"Type":"db"}}}
            real_stat=Path.stat
            def stat_value(path,*args,**kwargs):
                value=real_stat(path,*args,**kwargs)
                return types.SimpleNamespace(st_uid=0,st_mode=value.st_mode) if path==db else value
            with patch.object(m,"inspect",return_value=current),patch.object(Path,"stat",stat_value),patch.object(m.os,"fchown"):
                m.preserve_replacement_diagnostics("telegraf","old")
            pointer=json.loads((m.STATE/"last-activation-diagnostic.json").read_text())
            private=Path(pointer["private_directory"])/"container.json"
            self.assertEqual(0o700,private.parent.stat().st_mode&0o777)
            self.assertEqual(0o600,private.stat().st_mode&0o777)
            self.assertIn("fixture-private-failure",private.read_text())
            self.assertNotIn("fixture-private-failure",json.dumps(pointer))
            with patch.object(m,"inspect",return_value=current),patch.object(m,"atomic",side_effect=OSError("full")):
                m.preserve_replacement_diagnostics("telegraf","old")


@unittest.skipUnless(os.getenv("RUN_MQTT_ACL_INTEGRATION")=="1","real prepared-principal MQTT readiness opt-in")
class ActualBrokerPrincipalReadinessTest(unittest.TestCase):
    def test_real_mqtt5_long_principal_and_password_use_complete_connect_only_packet(self):
        from tests.test_broker_acl_integration import BrokerFixture,PROFILE,IMAGE
        from scripts.render_broker_acl import render_acl
        m=load().docker;fixture=BrokerFixture(render_acl(PROFILE))
        username="u"*64;password="f"*64
        try:
            fixture.docker("run","--rm","--user",fixture.uid,"-v",str(fixture.directory)+":/fixtures",
                "--entrypoint","mosquitto_passwd",IMAGE,"-b","/fixtures/passwords",username,password)
            fixture.docker("kill","--signal","HUP",fixture.name)
            result=m.wait_broker_principal({"ha_username":username},{username:password},
                                           endpoint=("127.0.0.1",fixture.port))
            self.assertTrue(result["prepared_principal_connect_only_verified"])
            with self.assertRaisesRegex(RuntimeError,"principal was refused"):
                m.wait_broker_principal({"ha_username":username},{username:"a"*64},
                                       endpoint=("127.0.0.1",fixture.port))
        finally:
            fixture.close()

if __name__ == "__main__":
    unittest.main()
