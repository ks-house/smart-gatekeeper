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
        cls.access_lease = (
            ROOT / "include/AccessCriticalLeasePolicy.h"
        ).read_text(encoding="utf-8")
        cls.restart_retention = (
            ROOT / "include/RestartEvidenceRetention.h"
        ).read_text(encoding="utf-8")
        cls.diagnostics = (ROOT / "src/DiagnosticsManager.cpp").read_text(
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
        critical = loop.index("bool accessCritical = isAccessPathCritical()")
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
        helper = self.main.split("static bool isAccessPathCritical()", 1)[1]
        helper = helper.split(
            "static bool enforceAccessCriticalLease", 1
        )[0]
        self.assertIn("GateState::AUTH_PENDING", helper)
        self.assertIn("GateState::ARMED", helper)
        self.assertIn("GateState::RELAY_HOLD", helper)
        self.assertIn("GateState::COOLDOWN", helper)
        self.assertIn("protocolCritical", helper)
        self.assertIn("GattServer::hasActiveOutput()", helper)
        self.assertIn("GattServer::hasPendingIngress()", helper)
        self.assertIn("sgk::SessionState::kCompleted", self.main)

    def test_network_stages_recheck_gatt_and_post_puback_access(self) -> None:
        loop = self.main.split("void loop()", 1)[1]
        mqtt = loop.index("MqttManager::update();")
        post_mqtt_gatt = loop.index("GattServer::update();", mqtt)
        post_mqtt_snapshot = loop.index(
            "accessCritical = isAccessPathCritical();", post_mqtt_gatt
        )
        ota = loop.index("OtaManager::update();", post_mqtt_snapshot)
        self.assertLess(mqtt, post_mqtt_gatt)
        self.assertLess(post_mqtt_gatt, post_mqtt_snapshot)
        self.assertLess(post_mqtt_snapshot, ota)

        update = self.mqtt.split("void MqttManager::update()", 1)[1]
        update = update.split("void MqttManager::publishBootDiagnostics", 1)[0]
        client_loop = update.index("client.loop();")
        dispatch = update.index(
            "dispatchPendingAccessCommand();", client_loop
        )
        action_guard = update.index(
            "if (accessActionStartedDuringLoop || !connected)", dispatch
        )
        telemetry_flush = update.index("if (pendingTelemetryValid", action_guard)
        self.assertLess(client_loop, dispatch)
        self.assertLess(dispatch, action_guard)
        self.assertLess(action_guard, telemetry_flush)

        callback = self.mqtt.split("void MqttManager::callback", 1)[1]
        callback = callback.split("void MqttManager::update()", 1)[0]
        self.assertIn("pendingSignedAccessCommand.ready = true", callback)
        self.assertNotIn("triggerArm()", callback)
        self.assertNotIn("triggerManualDoorOpen()", callback)

        deferred = self.mqtt.split(
            "void MqttManager::dispatchPendingAccessCommand()", 1
        )[1].split("void MqttManager::init()", 1)[0]
        self.assertIn("triggerArm();", deferred)
        self.assertIn("triggerManualDoorOpen();", deferred)
        self.assertIn("accessActionStartedDuringLoop = true", deferred)
        self.assertIn("pendingTelemetryValid = false", deferred)
        app_ack = deferred.index("publishCommandAck(pending.envelope")
        arm = deferred.index("triggerArm();")
        manual = deferred.index("triggerManualDoorOpen();")
        completion = deferred.index("commandSecurity.markCompleted")
        self.assertLess(app_ack, arm)
        self.assertLess(app_ack, manual)
        self.assertLess(arm, completion)
        self.assertLess(manual, completion)

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
        self.assertIn("eventOutboxCount >= limit", self.mqtt)
        self.assertIn("useTerminalReserve ? 0 : 1", self.mqtt)
        self.assertIn("eventOutboxOverflowCount", self.mqtt)
        canonical = self.mqtt.split(
            "bool MqttManager::enqueueCanonicalEvent", 1
        )[1].split("bool MqttManager::publishCanonicalEvent", 1)[0]
        self.assertIn("enqueueEventWithDurableSpill(event)", canonical)
        self.assertIn("isAccessTerminalCheckpointCode(event.event_type)", canonical)
        self.assertIn("return checkpointTerminalEvent(event)", canonical)
        self.assertIn("g_offline_queue.push(oldest)", self.mqtt)
        self.assertLess(
            self.mqtt.index("g_offline_queue.push(oldest)"),
            self.mqtt.index("popEventOutbox();", self.mqtt.index("g_offline_queue.push(oldest)")),
        )

    def test_restart_evidence_has_checked_rtc_fallback(self) -> None:
        carrier = self.restart_retention.split("struct Image", 1)[1].split(
            "using Validator", 1
        )[0]
        self.assertIn("uint32_t magic", carrier)
        self.assertIn("uint16_t version", carrier)
        self.assertIn("uint16_t count", carrier)
        self.assertIn("uint32_t checksum", carrier)
        self.assertIn("uint8_t records[", carrier)
        self.assertNotIn("std::array<sgk::CanonicalEvent", carrier)
        self.assertIn("struct Journal", self.restart_retention)
        self.assertIn(
            "RTC_NOINIT_ATTR RtcEventFallbackJournal rtcEventFallback",
            self.mqtt,
        )
        self.assertIn("sizeof(RtcEventFallbackJournal) <= 12288", self.mqtt)

        save = self.mqtt.split("bool saveEventOutboxToRtcFallback()", 1)[1]
        save = save.split("void restoreEventOutboxFromRtcFallback()", 1)[0]
        self.assertIn(
            "eventOutbox, eventOutboxHead, eventOutboxCount", save
        )
        self.assertIn("RtcEventRetention::saveJournal", save)
        self.assertIn("rtcEventRetention.retain(eventOutboxCount)", save)
        self.assertIn("(head + index) % Capacity", self.restart_retention)

        restore = self.mqtt.split(
            "void restoreEventOutboxFromRtcFallback()", 1
        )[1].split("void removeEventOutboxTail", 1)[0]
        validate = restore.index("if (!rtcEventFallbackIsValid())")
        copy = restore.index("RtcEventRetention::restoreNewest", validate)
        retain = restore.index("rtcEventRetention.retain", copy)
        self.assertLess(validate, copy)
        self.assertLess(copy, retain)
        self.assertNotIn("clearRtcEventFallback();", restore[retain:])

        pop = self.mqtt.split("void popEventOutbox()", 1)[1].split(
            "void clearRtcEventFallback()", 1
        )[0]
        self.assertIn("rtcEventRetention.frontRemoved()", pop)
        self.assertIn("RtcEventRetention::clearJournal(&rtcEventFallback)", pop)

        init = self.mqtt.split("void MqttManager::init()", 1)[1].split(
            "void MqttManager::callback", 1
        )[0]
        reset = init.index("eventOutboxCount = 0")
        restore_call = init.index("restoreEventOutboxFromRtcFallback()", reset)
        self.assertLess(reset, restore_call)

        persist = self.mqtt.split(
            "bool MqttManager::persistPendingEventsForRestart()", 1
        )[1].split("bool MqttManager::publishCanonicalEvent", 1)[0]
        nvs_failure = persist.index("!g_offline_queue.push(event)")
        rtc_save = persist.index("saveEventOutboxToRtcFallback()", nvs_failure)
        failure_return = persist.index("return false;", rtc_save)
        self.assertLess(nvs_failure, rtc_save)
        self.assertLess(rtc_save, failure_return)
        checkpoint = self.mqtt.rsplit("bool checkpointTerminalEvent", 1)[1]
        checkpoint = checkpoint.split(
            "bool enqueueEventWithDurableSpill", 1
        )[0]
        flush = checkpoint.index("while (eventOutboxCount != 0)")
        terminal_nvs = checkpoint.index("g_offline_queue.push(event)", flush)
        terminal_ram = checkpoint.index("enqueueEventOutbox(event, true)")
        snapshot = checkpoint.index("saveEventOutboxToRtcFallback()")
        self.assertLess(flush, terminal_nvs)
        self.assertLess(terminal_nvs, terminal_ram)
        self.assertLess(terminal_ram, snapshot)
        self.assertGreaterEqual(
            self.mqtt.count(
                'doc["previous_evidence_persistence_failed"] ='
            ),
            2,
        )
        self.assertGreaterEqual(
            self.mqtt.count('doc["rtc_event_fallback_restored_count"] ='),
            2,
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

    def test_signed_command_terminal_tracking_never_writes_mqtt_in_control_path(self) -> None:
        tracker = self.mqtt.split(
            "void MqttManager::noteSignedCommandArmed", 1
        )[1].split("bool MqttManager::publishCanonicalEvent", 1)[0]
        self.assertIn("signedCommandAccessTracker.noteRelayOn()", tracker)
        self.assertIn("signedCommandAccessTracker.noteRelayOff", tracker)
        self.assertIn("MqttManager::finishSignedCommandAccess", tracker)
        self.assertIn("noteAccessTerminal(", tracker)
        self.assertIn("enqueueSignedCommandTerminalEvent", tracker)
        self.assertNotIn("client.publish", tracker)

        deferred = self.mqtt.split(
            "bool enqueueSignedCommandTerminalEvent", 1
        )[1].split("bool enqueueEventOutbox", 1)[0]
        self.assertIn("deriveAccessEventMac", deferred)
        self.assertIn("setCanonicalV2Detail", deferred)
        self.assertIn("return checkpointTerminalEvent(event)", deferred)
        checkpoint = self.mqtt.rsplit(
            "bool checkpointTerminalEvent", 1
        )[1].split("bool enqueueEventWithDurableSpill", 1)[0]
        self.assertIn("g_offline_queue.push(oldest)", checkpoint)
        self.assertIn("g_offline_queue.push(event)", checkpoint)
        self.assertIn("saveEventOutboxToRtcFallback()", checkpoint)
        self.assertNotIn("client.publish", deferred)

        update = self.mqtt.split("void MqttManager::update()", 1)[1]
        update = update.split("void MqttManager::publishBootDiagnostics", 1)[0]
        self.assertIn('attributes["transport"] = "signed_mqtt"', update)
        self.assertIn('"mqtt_manual_remote"', update)
        self.assertIn('"mqtt_prearm"', update)

        callback = self.main.split(
            "static sgk::TargetAccessFsm g_access_fsm", 1
        )[1].split("// ─────────────────────────────────────────────────────────────", 1)[0]
        for event in (
            '"pre_armed"',
            '"relay_on_manual"',
            '"door_close"',
            '"session_completed"',
            '"session_terminated_failsafe"',
        ):
            self.assertIn(event, callback)
        self.assertNotIn("MqttManager::update()", callback)

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

    def test_continuous_access_critical_lease_fails_closed(self) -> None:
        self.assertIn("ACCESS_CRITICAL_HARD_TIMEOUT_MS = 85000", self.config)
        self.assertIn(
            "GATT_UNVERIFIED_CRITICAL_TIMEOUT_MS =", self.config
        )
        self.assertIn("ACCESS_CRITICAL_REARM_QUIET_MS = 30000", self.config)
        self.assertIn(
            "ACCESS_CRITICAL_HARD_TIMEOUT_MS,\n"
            "              \"normal access timing must remain below the hard lease\"",
            self.config,
        )
        lease = self.main.split(
            "static bool enforceAccessCriticalLease", 1
        )[1].split("// ─────────────────────────────────────────────────────────────", 1)[0]
        timeout = lease.index("accessCriticalLease.expired(")
        cleanup = lease.index("g_access_fsm.cleanupToIdle(now);", timeout)
        terminal = lease.index("GattServer::notifySessionTerminated", cleanup)
        persist = lease.index(
            "GattServer::persistPendingEventsForRestart()", terminal
        )
        mark = lease.index(
            'DiagnosticsManager::markPlannedRestart("access_critical_timeout")',
            persist,
        )
        restart = lease.index("ESP.restart();", mark)
        self.assertLess(timeout, cleanup)
        self.assertLess(cleanup, terminal)
        self.assertLess(terminal, persist)
        self.assertLess(cleanup, mark)
        self.assertLess(mark, restart)
        self.assertIn("accessCriticalLease.expired(", lease)
        self.assertIn("accessSessionGeneration", lease)
        self.assertNotIn("accessCriticalStartedMs = 0", lease)
        unverified = lease.split("if (!verifiedPhysicalSession)", 1)[1].split(
            "// A wedged access path", 1
        )[0]
        self.assertIn("GattServer::abortUnverifiedIngress(now)", unverified)
        self.assertNotIn("ESP.restart()", unverified)
        self.assertIn("GATT_UNVERIFIED_CRITICAL_TIMEOUT_MS", lease)
        self.assertIn("elapsed(now_ms, quiet_started_ms_) >= quiet_rearm_ms_", self.access_lease)
        self.assertIn("generation_ != verified_action_generation", self.access_lease)
        self.assertIn(
            "DiagnosticsManager::markEvidencePersistenceFailure();", lease
        )
        persistence_failure = lease.index(
            "DiagnosticsManager::markEvidencePersistenceFailure();"
        )
        self.assertLess(persistence_failure, mark)
        pending_callback = self.main.split(
            "GattServer::setOnAuthPendingCallback", 1
        )[1].split("GattServer::setOnAuthGrantCallback", 1)[0]
        grant_callback = self.main.split(
            "GattServer::setOnAuthGrantCallback", 1
        )[1].split("GattServer::setOnAuthAbortCallback", 1)[0]
        self.assertNotIn("noteAccessSessionStarted();", pending_callback)
        self.assertIn("noteAccessSessionStarted();", grant_callback)

    def test_deferred_gatt_evidence_is_removed_only_after_outbox_accepts_it(self) -> None:
        deferred = self.gatt.split(
            "class DeferredCanonicalEventSink final", 1
        )[1].split("DeferredCanonicalEventSink deferred_event_sink", 1)[0]
        delivery = deferred.index("downstream_->tryEmit(event)")
        removal = deferred.index("events_[head_] = sgk::Event{};", delivery)
        decrement = deferred.index("--count_;", removal)
        self.assertLess(delivery, removal)
        self.assertLess(removal, decrement)
        self.assertIn("evidence_gap_ = true", deferred)
        self.assertIn("return false;", deferred[delivery:removal])

        canonical = self.gatt.split(
            "bool tryEmit(const sgk::Event& event)", 1
        )[1].split("private:", 1)[0]
        enqueue = canonical.index("MqttManager::enqueueCanonicalEvent(queued_evt)")
        terminal = canonical.index("phase_tracker_.observe", enqueue)
        causal = canonical.index("last_session_ = schema_session", terminal)
        self.assertLess(enqueue, terminal)
        self.assertLess(terminal, causal)

    def test_persistence_failure_flag_survives_planned_restart_breadcrumb(self) -> None:
        marker = self.diagnostics.split(
            "void DiagnosticsManager::markEvidencePersistenceFailure()", 1
        )[1].split("void DiagnosticsManager::markPlannedRestart", 1)[0]
        planned = self.diagnostics.split(
            "void DiagnosticsManager::markPlannedRestart", 1
        )[1].split("void DiagnosticsManager::noteMqttConnected", 1)[0]
        getter = self.diagnostics.split(
            "bool DiagnosticsManager::previousEvidencePersistenceFailed()", 1
        )[1].split("uint32_t DiagnosticsManager::mqttConnectCount", 1)[0]
        self.assertIn("evidencePersistenceFailureLatch.mark()", marker)
        self.assertIn(
            "evidencePersistenceFailureLatch.active() ? 1 : 0", marker
        )
        self.assertNotIn("evidencePersistenceFailed", planned)
        self.assertIn("previousBreadcrumb.evidencePersistenceFailed != 0", getter)

    def test_forced_ota_command_is_queued_not_run_in_mqtt_callback(self) -> None:
        callback = self.mqtt.split("void MqttManager::callback", 1)[1]
        callback = callback.split("void MqttManager::update()", 1)[0]
        self.assertIn("OtaManager::requestCheck();", callback)
        self.assertNotIn("OtaManager::checkAndUpdate", callback)

    def test_signed_reboot_waits_for_puback_and_persists_evidence(self) -> None:
        callback = self.mqtt.split("void MqttManager::callback", 1)[1]
        callback = callback.split("void MqttManager::update()", 1)[0]
        completion = callback.index("commandSecurity.markCompleted(envelope)")
        app_ack = callback.index("publishCommandAck(\n        envelope", completion)
        pending = callback.index("signedRestartPending = true", app_ack)
        self.assertLess(completion, app_ack)
        self.assertLess(app_ack, pending)
        self.assertNotIn("ESP.restart()", callback)

        update = self.mqtt.split("void MqttManager::update()", 1)[1]
        update = update.split("void MqttManager::publishBootDiagnostics", 1)[0]
        protocol = update.index("client.loop();")
        restart_pending = update.index("if (signedRestartPending)", protocol)
        self.assertLess(protocol, restart_pending)
        self.assertNotIn("ESP.restart();", update)

        perform = self.mqtt.split(
            "void MqttManager::performPendingRestart()", 1
        )[1].split("bool MqttManager::publishCommandAck", 1)[0]
        persist = perform.index("GattServer::persistPendingEventsForRestart()")
        diagnostic = perform.index(
            "DiagnosticsManager::markEvidencePersistenceFailure()", persist
        )
        restart = perform.index("ESP.restart();", diagnostic)
        self.assertLess(persist, diagnostic)
        self.assertLess(diagnostic, restart)

        service = self.main.split(
            "static bool servicePendingSignedRestart()", 1
        )[1].split("static bool enforceAccessCriticalLease", 1)[0]
        busy = service.index("GattServer::setOtaBusy(true)")
        first_safe = service.index("isVerifiedPhysicalAccessActive()", busy)
        drain = service.index("GattServer::update();", first_safe)
        abort = service.index("GattServer::abortUnverifiedIngress", drain)
        second_safe = service.index(
            "isVerifiedPhysicalAccessActive()", abort
        )
        perform_call = service.index(
            "MqttManager::performPendingRestart()", second_safe
        )
        self.assertLess(busy, first_safe)
        self.assertLess(first_safe, drain)
        self.assertLess(drain, abort)
        self.assertLess(abort, second_safe)
        self.assertLess(second_safe, perform_call)


if __name__ == "__main__":
    unittest.main()
