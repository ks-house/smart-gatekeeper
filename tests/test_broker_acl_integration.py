"""Opt-in real Mosquitto authorization checks; isolated loopback only."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "eclipse-mosquitto@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797"
PASSWORD = "isolated-fixture-only"
PROFILE = dict(schema_version=1, targets=["target-a", "target-b"],
               backend_username="gatekeeper-backend", ha_username="homeassistant",
               diagnostic_usernames=["diag-read"], discovery_device_id="smart_gatekeeper_01")


class BrokerFixture:
    def __init__(self, acl):
        import paho.mqtt.client as mqtt
        self.mqtt = mqtt
        self.clients = []
        self.messages = []
        self.temp = tempfile.TemporaryDirectory(prefix="sgk-broker-acl-")
        self.directory = Path(self.temp.name)
        self.name = "sgk-broker-acl-" + uuid.uuid4().hex[:10]
        self.started = False
        self.uid = str(os.getuid()) + ":" + str(os.getgid())
        try:
            # Test-only observer/barrier permissions never cover production topics.
            fixture_users = [*PROFILE["targets"], PROFILE["backend_username"],
                             PROFILE["ha_username"], "diag-read"]
            barriers = "".join("\nuser " + user + "\ntopic readwrite fixture/barrier/#\n"
                               for user in fixture_users)
            (self.directory / "acl").write_text(
                acl + barriers + "\nuser fixture-observer\ntopic read #\n")
            (self.directory / "mosquitto.conf").write_text(
                "listener 1883 0.0.0.0\nallow_anonymous false\n"
                "password_file /fixtures/passwords\nacl_file /fixtures/acl\n"
                "persistence false\nlog_dest stdout\n")
            users = [*PROFILE["targets"], PROFILE["backend_username"],
                     PROFILE["ha_username"], "diag-read", "fixture-observer"]
            for index, user in enumerate(users):
                args = ["run", "--rm", "--user", self.uid, "-v", str(self.directory)+":/fixtures",
                        "--entrypoint", "mosquitto_passwd", IMAGE]
                self.docker(*args, *(["-c"] if index == 0 else []),
                            "-b", "/fixtures/passwords", user, PASSWORD)
            self.docker("run", "--rm", "-d", "--name", self.name, "--user", self.uid,
                        "--entrypoint", "mosquitto", "-p", "127.0.0.1::1883",
                        "-v", str(self.directory)+":/fixtures:ro", IMAGE,
                        "-c", "/fixtures/mosquitto.conf")
            self.started = True
            mapping = self.docker("port", self.name, "1883/tcp").strip()
            host, port = mapping.rsplit(":", 1)
            if host != "127.0.0.1" or not port.isdecimal():
                raise RuntimeError("fixture broker must bind only loopback")
            self.port = int(port)
            deadline = time.monotonic() + 6
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("isolated broker did not listen")
                    time.sleep(0.05)
            observer, rc = self.connect("fixture-observer")
            if rc != 0:
                raise RuntimeError("fixture observer authentication failed")
            self.subscribe(observer, "#")
            observer.on_message = lambda c, u, message: self.messages.append(
                (message.topic, bytes(message.payload)))
        except Exception:
            self.close()
            raise

    def docker(self, *args):
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError("isolated Docker fixture failed: " + result.stderr[-2000:])
        return result.stdout

    def connect(self, username, password=PASSWORD):
        ready = threading.Event()
        result = []
        client = self.mqtt.Client(client_id="fixture-" + uuid.uuid4().hex[:12],
                                  clean_session=True, protocol=self.mqtt.MQTTv311)
        if username is not None:
            client.username_pw_set(username, password)
        client.on_connect = lambda c, u, flags, rc: (result.append(rc), ready.set())
        client.connect("127.0.0.1", self.port, keepalive=10)
        client.loop_start()
        self.clients.append(client)
        if not ready.wait(3):
            raise RuntimeError("fixture CONNECT deadline")
        return client, result[0]

    def subscribe(self, client, topic):
        ready = threading.Event()
        client.on_subscribe = lambda *args: ready.set()
        client.subscribe(topic, qos=1)
        if not ready.wait(3):
            raise RuntimeError("fixture SUBACK deadline")
        # Some broker versions grant a subscription but enforce its read ACL
        # on delivery. Tests verify actual delivery, not SUBACK alone.

    def delivered(self, username, topic):
        client, rc = self.connect(username)
        if rc != 0:
            raise RuntimeError("fixture principal rejected")
        token = uuid.uuid4().hex.encode()
        message = client.publish(topic, token, qos=1, retain=False)
        message.wait_for_publish(timeout=3)
        marker_topic = "fixture/barrier/" + uuid.uuid4().hex
        marker = uuid.uuid4().hex.encode()
        client.publish(marker_topic, marker, qos=1).wait_for_publish(timeout=3)
        deadline = time.monotonic() + 3
        while (marker_topic, marker) not in self.messages:
            if time.monotonic() >= deadline:
                raise RuntimeError("fixture delivery barrier deadline")
            time.sleep(0.01)
        client.disconnect()
        return (topic, token) in self.messages

    def readable(self, username, topic, writer):
        client, rc = self.connect(username)
        if rc != 0:
            raise RuntimeError("fixture principal rejected")
        received = []
        client.on_message = lambda c, u, message: received.append(bytes(message.payload))
        self.subscribe(client, topic)
        marker_topic = "fixture/barrier/" + uuid.uuid4().hex
        self.subscribe(client, marker_topic)
        publisher, rc = self.connect(writer)
        if rc != 0:
            raise RuntimeError("fixture publisher rejected")
        token = uuid.uuid4().hex.encode()
        message = publisher.publish(topic, token, qos=1, retain=False)
        message.wait_for_publish(timeout=3)
        marker = uuid.uuid4().hex.encode()
        publisher.publish(marker_topic, marker, qos=1).wait_for_publish(timeout=3)
        deadline = time.monotonic() + 3
        while marker not in received:
            if time.monotonic() >= deadline:
                raise RuntimeError("fixture subscription barrier deadline")
            time.sleep(0.01)
        client.disconnect()
        publisher.disconnect()
        return token in received

    def close(self):
        for client in self.clients:
            client.disconnect()
            client.loop_stop()
        if self.started:
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=10)
        self.temp.cleanup()


@unittest.skipUnless(os.getenv("RUN_MQTT_ACL_INTEGRATION") == "1",
                     "set RUN_MQTT_ACL_INTEGRATION=1 for isolated real broker")
class BrokerAclIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.render_broker_acl import render_acl
        cls.broker = BrokerFixture(render_acl(PROFILE))

    @classmethod
    def tearDownClass(cls):
        cls.broker.close()

    def test_anonymous_and_wrong_password_rejected(self):
        for username, password in [(None, PASSWORD), ("target-a", "wrong-fixture-password")]:
            with self.subTest(username=username):
                client, rc = self.broker.connect(username, password)
                self.assertNotEqual(0, rc)
                client.disconnect()

    def test_own_target_writes_and_cross_target_rejections(self):
        for suffix in ["status", "availability", "boot", "canonical-event", "acl/ack", "command-ack"]:
            with self.subTest(suffix=suffix):
                self.assertTrue(self.broker.delivered("target-a", "gatekeeper/v1/targets/target-a/"+suffix))
                self.assertFalse(self.broker.delivered("target-b", "gatekeeper/v1/targets/target-a/"+suffix))

    def test_backend_effect_and_ha_bridge_permissions(self):
        for suffix in ["command", "acl"]:
            topic = "gatekeeper/v1/targets/target-a/"+suffix
            self.assertTrue(self.broker.delivered("gatekeeper-backend", topic))
            self.assertFalse(self.broker.delivered("homeassistant", topic))
        self.assertTrue(self.broker.delivered("homeassistant",
                        "gatekeeper/v1/ha-bridge/target-a/request/open"))
        self.assertTrue(self.broker.delivered("gatekeeper-backend",
                        "gatekeeper/v1/ha-bridge/target-a/verified-status"))
        self.assertTrue(self.broker.delivered("gatekeeper-backend",
                        "homeassistant/sensor/smart_gatekeeper_01/online/config"))
        self.assertFalse(self.broker.delivered("target-a",
                         "gatekeeper/v1/ha-bridge/target-a/request/open"))

    def test_role_names_do_not_inherit_target_pattern_writes(self):
        for user in ["homeassistant", "gatekeeper-backend", "diag-read"]:
            for suffix in ["status", "canonical-event"]:
                with self.subTest(user=user, suffix=suffix):
                    self.assertFalse(self.broker.delivered(
                        user, "gatekeeper/v1/targets/"+user+"/"+suffix))
        self.assertFalse(self.broker.delivered("homeassistant",
                         "gatekeeper/v1/targets/target-a/canonical-event"))
        self.assertFalse(self.broker.delivered("diag-read",
                         "gatekeeper/v1/targets/target-a/status"))

    def test_retained_discovery_is_delivered_to_late_home_assistant(self):
        broker = self.broker
        topic = "homeassistant/sensor/smart_gatekeeper_01/retained-fixture/config"
        publisher, rc = broker.connect("gatekeeper-backend")
        self.assertEqual(0, rc)
        token = uuid.uuid4().hex.encode()
        publisher.publish(topic, token, qos=1, retain=True).wait_for_publish(timeout=3)
        reader, rc = broker.connect("homeassistant")
        self.assertEqual(0, rc)
        received = []
        reader.on_message = lambda c, u, message: received.append(
            (bytes(message.payload), message.retain))
        broker.subscribe(reader, topic)
        marker_topic = "fixture/barrier/" + uuid.uuid4().hex
        broker.subscribe(reader, marker_topic)
        marker = uuid.uuid4().hex.encode()
        publisher.publish(marker_topic, marker, qos=1).wait_for_publish(timeout=3)
        deadline = time.monotonic() + 3
        while not any(payload == marker for payload, retained in received):
            if time.monotonic() >= deadline:
                raise RuntimeError("retained discovery barrier deadline")
            time.sleep(0.01)
        self.assertIn((token, True), received)
        publisher.publish(topic, b"", qos=1, retain=True).wait_for_publish(timeout=3)
        reader.disconnect()
        publisher.disconnect()

    def test_actual_read_delivery_for_targets_backend_ha_and_diagnostics(self):
        self.assertTrue(self.broker.readable("target-a",
                        "gatekeeper/v1/targets/target-a/command", "gatekeeper-backend"))
        self.assertTrue(self.broker.readable("target-a",
                        "gatekeeper/v1/targets/target-a/acl", "gatekeeper-backend"))
        self.assertFalse(self.broker.readable("target-b",
                         "gatekeeper/v1/targets/target-a/command", "gatekeeper-backend"))
        self.assertTrue(self.broker.readable("gatekeeper-backend",
                        "gatekeeper/v1/targets/target-a/canonical-event", "target-a"))
        self.assertTrue(self.broker.readable("homeassistant",
                        "gatekeeper/v1/targets/target-a/status", "target-a"))
        self.assertFalse(self.broker.readable("homeassistant",
                         "gatekeeper/v1/targets/target-a/canonical-event", "target-a"))
        self.assertTrue(self.broker.readable("diag-read",
                        "gatekeeper/v1/targets/target-a/status", "target-a"))
        self.assertFalse(self.broker.readable("diag-read",
                         "gatekeeper/v1/targets/target-a/command", "gatekeeper-backend"))
        self.assertFalse(self.broker.readable("target-a",
                         "gatekeeper/v1/targets/target-b/acl", "gatekeeper-backend"))


if __name__ == "__main__":
    unittest.main()
