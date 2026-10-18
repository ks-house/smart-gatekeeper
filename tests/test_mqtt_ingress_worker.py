"""Exercise the production receive worker with blocked/partial transport failures."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MqttIngressWorkerTest(unittest.TestCase):
    def test_blocked_receive_exclusive_handoff_and_failure_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "mqtt-ingress")
            subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                 "-Itests/mqtt_telemetry_worker_stubs", "-Iinclude",
                 "src/MqttIngressWorker.cpp", "tests/mqtt_ingress_worker_test.cpp",
                 "-o", executable],
                cwd=ROOT, check=True, capture_output=True,
            )
            subprocess.run([executable], check=True, capture_output=True, timeout=10)

    def test_production_routing_keeps_authority_and_transport_on_separate_owners(self):
        source = (ROOT / "src/MqttManager.cpp").read_text()
        callback = source.split("void MqttManager::callback(", 1)[1]
        self.assertLess(callback.index("ingressWorker.capture("),
                        callback.index("applySignedAcl("))
        critical = callback.split("if (criticalIngressDispatch)", 1)[1].split(
            "const sgk::CommandResult authorization =", 1)[0]
        self.assertIn("commandSecurity.dispatchPriorityManual(", critical)
        self.assertNotIn("triggerManualDoorOpen", critical)
        update = source.split("void MqttManager::update()", 1)[1]
        self.assertLess(update.index("if (ingressWorker.ownsTransport()) return;"),
                        update.index("client.connected()"))
        service = source.split("void MqttManager::serviceAccessCriticalIngress()", 1)[1].split(
            "bool MqttManager::connectionAttemptInProgress()", 1)[0]
        self.assertNotIn("client.loop()", service)
        self.assertNotIn("client.publish(", service)
        self.assertIn("deferredAclRefresh = true", service)
        self.assertNotIn("pendingTelemetryValid &&", service)
        main = (ROOT / "src/main.cpp").read_text().split("void loop()", 1)[1]
        self.assertLess(main.index("MqttManager::deferForAccessCritical();"),
                        main.index("MqttManager::serviceAccessCriticalIngress();"))
        self.assertIn('client.subscribe(aclTopic.c_str(), 1)', update)
        self.assertIn("ingressWorker.ownsTransport()", source.split(
            "bool MqttManager::connectionAttemptInProgress()", 1)[1].split("}", 1)[0])
        dispatch = source.split("bool MqttManager::dispatchCriticalManual", 1)[1].split(
            "void MqttManager::dispatchPendingAccessCommand", 1)[0]
        self.assertLess(dispatch.index("signedCommandAccessTracker.begin("),
                        dispatch.index("!prepareManualRemoteOverride()"))
        gatt = (ROOT / "src/GattServer.cpp").read_text()
        control = gatt.split("bool GattServer::runExclusiveControl", 1)[1].split(
            "void GattServer::notifySessionTerminated", 1)[0]
        self.assertLess(control.index("lock(core_mutex)"), control.index("operation(context)"))

if __name__ == "__main__":
    unittest.main()
