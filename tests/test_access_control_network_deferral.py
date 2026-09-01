"""Source contracts for keeping TLS/MQTT outside access-critical control."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AccessControlNetworkDeferralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = (ROOT / "src/main.cpp").read_text(encoding="utf-8")
        cls.mqtt = (ROOT / "src/MqttManager.cpp").read_text(encoding="utf-8")
        cls.gatt = (ROOT / "src/GattServer.cpp").read_text(encoding="utf-8")
        cls.fsm = (ROOT / "src/TargetAccessFsm.cpp").read_text(
            encoding="utf-8"
        )
        cls.config = (ROOT / "include/config.h").read_text(encoding="utf-8")
        cls.config_manager = (ROOT / "src/ConfigManager.cpp").read_text(
            encoding="utf-8"
        )
        cls.backend = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")

    def test_gatt_event_sink_only_enqueues_canonical_evidence(self) -> None:
        sink = self.gatt.split("class CanonicalMqttEventSink final", 1)[1]
        sink = sink.split("CanonicalMqttEventSink production_event_sink", 1)[0]
        self.assertIn("MqttManager::enqueueCanonicalEvent(queued_evt)", sink)
        self.assertNotIn("MqttManager::publishCanonicalEvent", sink)
        self.assertNotIn("client.publish", sink)
        self.assertIn("deriveAccessEventCredentialRef", sink)
        self.assertIn("MqttManager::enqueueCanonicalEvent(queued_evt)", sink)

    def test_legacy_events_and_telemetry_do_not_write_socket(self) -> None:
        event = self.mqtt.split("void MqttManager::publishEvent(", 1)[1]
        event = event.split("bool MqttManager::enqueueCanonicalEvent", 1)[0]
        self.assertIn("enqueueEventWithDurableSpill(event)", event)
        self.assertNotIn("client.publish", event)

        telemetry = self.mqtt.split("void MqttManager::publishTelemetry(", 1)[1]
        telemetry = telemetry.split("void MqttManager::publishEvent(", 1)[0]
        self.assertIn("pendingTelemetry", telemetry)
        self.assertNotIn("client.publish", telemetry)

    def test_main_orders_local_control_before_network(self) -> None:
        loop = self.main.split("void loop()", 1)[1]
        gatt = loop.index("GattServer::update();")
        sensor = loop.index("UltrasonicSensor::readDistanceCm")
        critical = loop.index("const bool accessCritical")
        safe_guard = loop.index("if (!accessCritical)")
        wifi = loop.index("WifiManager::handleClient();", safe_guard)
        mqtt = loop.index("MqttManager::update();", safe_guard)
        ota = loop.index("OtaManager::update();", safe_guard)
        self.assertLess(gatt, sensor)
        self.assertLess(sensor, critical)
        self.assertLess(critical, safe_guard)
        self.assertLess(safe_guard, wifi)
        self.assertLess(wifi, mqtt)
        self.assertLess(mqtt, ota)

    def test_relay_timer_is_normal_and_late_cutoff_is_failsafe(self) -> None:
        loop = self.main.split("void loop()", 1)[1]
        timer_guard = loop.index("if (relayTimerTriggered)")
        timer_transition = loop.index(
            "g_access_fsm.handleRelayTimerOff", timer_guard
        )
        deadline_guard = loop.index("if (relayDeadlineActive")
        deadline_transition = loop.index(
            "g_access_fsm.handleRelayFailsafeOff", deadline_guard
        )
        normal_tick = loop.index("g_access_fsm.tick(now);")
        gatt = loop.index("GattServer::update();")

        self.assertLess(timer_guard, timer_transition)
        self.assertLess(timer_transition, deadline_guard)
        self.assertLess(deadline_guard, deadline_transition)
        self.assertLess(deadline_transition, normal_tick)
        self.assertLess(normal_tick, gatt)
        self.assertIn(
            "RELAY_HOLD_MS + RELAY_FAILSAFE_GRACE_MS", loop
        )
        self.assertIn("session_terminated_failsafe", self.main)
        self.assertIn("sgk::EventReason::kRelayFailsafeCutoff", self.main)

    def test_access_guard_covers_auth_sensor_relay_and_live_gatt(self) -> None:
        loop = self.main.split("const bool accessCritical", 1)[1]
        loop = loop.split("if (!accessCritical)", 1)[0]
        self.assertIn("GateState::AUTH_PENDING", loop)
        self.assertIn("GateState::ARMED", loop)
        self.assertIn("GateState::RELAY_HOLD", loop)
        self.assertIn("GateState::COOLDOWN", loop)
        self.assertIn("gattProtocolCritical", loop)
        self.assertIn("GattServer::hasActiveOutput()", self.main)
        self.assertIn("sgk::SessionState::kCompleted", self.main)

    def test_new_auth_is_idle_only_until_terminal_cooldown(self) -> None:
        pending = self.fsm.split(
            "bool TargetAccessFsm::handleAuthPending", 1
        )[1].split("bool TargetAccessFsm::handleAuthSuccess", 1)[0]
        self.assertIn("state_ != GateState::IDLE || relay_on_", pending)
        self.assertNotIn("replacing_armed", pending)
        self.assertNotIn("replacement", pending.lower())

        callback = self.main.split(
            "GattServer::setOnAuthPendingCallback", 1
        )[1].split("GattServer::setOnAuthGrantCallback", 1)[0]
        self.assertIn("g_access_fsm.handleAuthPending", callback)
        self.assertNotIn("GateState::ARMED", callback)
        self.assertNotIn("supersedeVerifiedSession", callback)

    def test_outbox_is_bounded_and_has_durable_overflow_fallback(self) -> None:
        self.assertIn("kEventOutboxCapacity = 16", self.mqtt)
        self.assertIn("eventOutboxCount == eventOutbox.size()", self.mqtt)
        self.assertIn("eventOutboxOverflowCount", self.mqtt)
        canonical = self.mqtt.split(
            "bool MqttManager::enqueueCanonicalEvent", 1
        )[1].split("bool MqttManager::publishCanonicalEvent", 1)[0]
        self.assertIn("enqueueEventWithDurableSpill(event)", canonical)
        self.assertIn("g_offline_queue.push(oldest)", self.mqtt)
        self.assertLess(
            self.mqtt.index("g_offline_queue.push(oldest)"),
            self.mqtt.index("popEventOutbox();", self.mqtt.index("g_offline_queue.push(oldest)")),
        )

    def test_recovery_flush_is_one_event_per_update(self) -> None:
        update = self.mqtt.split("void MqttManager::update()", 1)[1]
        update = update.split("void MqttManager::publishBootDiagnostics", 1)[0]
        self.assertNotIn("while (client.connected()", update)
        self.assertIn("if (g_offline_queue.peekFront(&evt))", update)
        self.assertIn("if (peekEventOutbox(&evt))", update)
        self.assertLess(
            update.index("g_offline_queue.peekFront(&evt)"),
            update.index("peekEventOutbox(&evt)"),
        )

    def test_deferred_telemetry_is_refreshed_on_every_fsm_transition(self) -> None:
        loop = self.main.split("void loop()", 1)[1]
        self.assertIn("telemetryState != lastTelemetryState", loop)
        self.assertIn("lastTelemetryState = telemetryState", loop)
        self.assertLess(
            loop.index("lastTelemetryState = telemetryState"),
            loop.index("if (!accessCritical)"),
        )

    def test_bounded_access_timing_outlives_keepalive_and_ha_grace(self) -> None:
        self.assertIn("PRE_ARM_MAX_DURATION_MS = 60000", self.config)
        self.assertIn("RELAY_COOLDOWN_MAX_MS = 10000", self.config)
        self.assertIn("ACCESS_CRITICAL_STATUS_GRACE_MS = 90000", self.config)
        self.assertIn("GATT_AUTH_PENDING_TIMEOUT_MS = 5000", self.config)
        self.assertIn("RELAY_FAILSAFE_GRACE_MS = 250", self.config)
        self.assertIn("MQTT_KEEP_ALIVE_SECONDS = 120", self.config)
        self.assertIn(
            "client.setKeepAlive(MQTT_KEEP_ALIVE_SECONDS)", self.mqtt
        )
        self.assertIn(
            "static_assert(2 * GATT_AUTH_PENDING_TIMEOUT_MS", self.config
        )
        self.assertIn("clampAccessTiming(", self.config_manager)
        self.assertIn("PRE_ARM_MAX_DURATION_MS", self.config_manager)
        self.assertIn("RELAY_COOLDOWN_MAX_MS", self.config_manager)
        self.assertIn(
            "HA_BRIDGE_AVAILABILITY_EXPIRY_SECONDS = 90.25", self.backend
        )


if __name__ == "__main__":
    unittest.main()
