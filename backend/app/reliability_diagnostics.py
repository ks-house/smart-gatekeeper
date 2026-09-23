"""Bounded diagnostic evidence; no authorization or actuator decisions."""

import hashlib
import hmac
import json
import re
import threading
import time
import uuid
from collections import OrderedDict


U64 = (1 << 64) - 1
U32 = (1 << 32) - 1
MQTT_REASONS = (
    "NONE", "CONNECT_TLS_FAILED", "CONNECT_MQTT_FAILED", "CONNECT_SUBSCRIBE_FAILED",
    "CONNECT_AVAILABILITY_FAILED", "CONNECT_ADOPTION_LOST", "TRANSPORT_LOST",
    "LOOP_FAILED", "WIFI_LOST", "OTA_SUSPEND", "STALE_RESULT", "DNS_FAILED",
    "WORKER_START_FAILED", "PUBLISH_FAILED",
)
MQTT_COUNTERS = (
    "generation", "disconnects", "planned_disconnects", "last_disconnect_ms",
    "last_connected_ms", "last_connection_duration_ms", "retry_in_ms",
    "loop_gap_max_ms", "edge_sequence", "edge_overwritten",
)
MQTT_EDGE_FIELDS = (
    "sequence", "occurred_ms", "reason_code", "last_error", "connection_duration_ms",
    "free_heap", "largest_block", "loop_gap_ms", "wifi_generation",
)


def mqtt_edge_projection(value):
    """Decode one bounded schema-1 wire edge; reject the whole malformed edge."""
    # Seven U32s, reason (2), error (4), and eight commas: at most 84 ASCII bytes.
    if not isinstance(value, str) or len(value) > 84:
        return None
    parts = value.split(",")
    if len(parts) != len(MQTT_EDGE_FIELDS):
        return None
    result = {}
    for key, part in zip(MQTT_EDGE_FIELDS, parts):
        pattern = r"(?:0|[1-9][0-9]{0,9})" if key != "last_error" else r"(?:0|-?[1-9][0-9]{0,2})"
        if re.fullmatch(pattern, part) is None:
            return None
        number = int(part)
        low, high = (-128, 255) if key == "last_error" else (1, 13) if key == "reason_code" else (0, U32)
        if not low <= number <= high:
            return None
        result[key] = number
    result["reason"] = MQTT_REASONS[result["reason_code"]]
    return result


def mqtt_connection_projection(value):
    """Closed unsigned wire view, idempotent through ingest, storage and reads."""
    if (not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1
            or type(value.get("flapping")) is not bool
            or not isinstance(value.get("last_reason"), str) or value["last_reason"] not in MQTT_REASONS
            or type(value.get("last_error")) is not int or not -128 <= value["last_error"] <= 255):
        return None
    if any(type(value.get(key)) is not int or not 0 <= value[key] <= U32 for key in MQTT_COUNTERS):
        return None
    edges = value.get("edges")
    if (not isinstance(edges, list) or len(edges) > 4
            or any(mqtt_edge_projection(edge) is None for edge in edges)):
        return None
    return {**{key: value[key] for key in ("schema", *MQTT_COUNTERS, "last_reason", "last_error", "flapping")},
            "edges": list(edges)}


UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
CORE_FIELDS = (
    "target_id", "source_boot_id", "source_boot_count", "status_revision", "state",
    "last_terminal_session_id", "last_terminal_event_sequence", "last_terminal_event_code",
    "last_terminal_reason_code", "last_terminal_credential_ref", "last_terminal_phase_mask",
    "relay_commanded_on", "relay_pin_level",
)
SENSOR_FIELDS = (
    "source_boot_id", "source_boot_count", "session_id", "terminal_sequence",
    "started_monotonic_ms", "ended_monotonic_ms", "threshold_mm", "samples",
    "valid_samples", "timeouts", "invalid_samples", "in_range_samples",
    "blocked_samples", "clear_samples", "min_raw_mm", "max_raw_mm", "last_raw_mm",
    "last_median_mm", "blocked_at_start", "blocked_at_end", "clearance_state",
)
MEASUREMENTS = ("min_raw_mm", "max_raw_mm", "last_raw_mm", "last_median_mm")
DECIMAL_FIELDS = ("source_boot_count", "terminal_sequence", "started_monotonic_ms", "ended_monotonic_ms")
RESET_REASONS = {"UNKNOWN", "POWERON", "EXTERNAL_PIN", "SOFTWARE", "PANIC", "INT_WDT", "TASK_WDT",
                 "OTHER_WDT", "DEEPSLEEP", "BROWNOUT", "SDIO", "USB", "JTAG", "EFUSE", "POWER_GLITCH", "CPU_LOCKUP"}
RESTART_REASONS = {"none", "unspecified", "signed_mqtt_reboot", "provisioning_save", "access_critical_timeout",
                   "ota_pending_verify", "local_ota_pending_verify", "ota_valid_mark_failed", "ota_health_timeout",
                   "ota_health_safe_timeout", "ota_health_network_timeout", "ota_health_heap_timeout", "ota_health_sample_gap"}
# Closed diagnostic codes, not arbitrary firmware log strings. Unknown actions
# remain unreported rather than becoming a free-text or secret side channel.
ACTION_CODES = set("""unknown boot network_services_start mqtt_connected mqtt_dns_timeout mqtt_dns_started
    mqtt_status_worker_failed mqtt_wifi_generation_changed mqtt_connect_worker_wdt_degraded
    mqtt_connect_worker_adopted mqtt_connect_worker_stale mqtt_connect_worker_failed mqtt_wifi_lost
    mqtt_wifi_recovered mqtt_dns_failed mqtt_connect_start mqtt_connect_worker_start_failed
    https_date_clock_trusted ota_health_window ota_check_queued ota_mark_valid ota_manifest_get ota_artifact_get
    loop_watchdog_config_failed loop_watchdog_ready loop_watchdog_subscribe_failed relay_on relay_off relay_off_boot
    relay_on_duplicate pre_armed arm_rejected_not_idle relay_on_manual manual_open_rejected_not_idle
    gatt_armed_fresh_sensor_history relay_timer_off relay_failsafe_off
    wifi_sta_profile_degraded wifi_sta_profile_enabled wifi_sta_continuous_recovery recovery_operation_lease_expired
    wifi_sta_attempt_paused_for_local_work wifi_recovery_sta_attempt_started wifi_recovery_sta_attempt_start_failed
    wifi_connected provisioning_ap_start provisioning_ap_ready wifi_recovery_ap_quiet provisioning_ap_failed
    wifi_scan_sta_paused wifi_scan_failed wifi_scan_complete wifi_save_rejected wifi_credentials_invalid
    wifi_credentials_save wifi_credentials_write_failed web_config_save recovery_ap_window_closed
    wifi_recovered_from_ap wifi_autoreconnect_grace wifi_reconnected wifi_recovery_ap_escalation
    wifi_recovery_ap_escalation_failed wifi_recovery_sta_attempt_stopped wifi_recovery_idle_client_released
    wifi_recovery_idle_client_release_failed wifi_recovery_stale_client_attempt_forced
    gatt_unverified_lease_disconnected gatt_unverified_lease_expired
    recovery_ap_deadline_deferred_for_local_operation""".split()) | {"restart:" + value for value in RESTART_REASONS}
# DiagnosticsManager's RTC action buffer stores at most31 bytes. Preserve exact
# known truncations as advisory tokens, without interpreting them as full codes.
ACTION_CODES |= {value[:31] for value in ACTION_CODES}
ACTION_CODES |= {"mqtt_ota_suspend", "mqtt_ota_resume"}
ACCESS_STAGES = {"unknown", "UNKNOWN", "BOOTING", "GATT_CONNECTED", "GATT_FAILED", "CHALLENGE_ISSUED",
                 "PROOF_VERIFIED", "PROOF_REJECTED", "ARMED", "SENSOR_DETECTED", "RELAY_ON", "RELAY_OFF",
                 "COMPLETED", "TERMINATED", "CONNECTION_ACCEPTED", "DISCONNECTED", "PROOF_FRAME_RECEIVED", "RESULT_INDICATED"}


def boot_observation_projection(value, expected=None):
    """Revalidate persisted nested advisory; never promote it to signed evidence."""
    keys = {"provenance", "integrity_status", "target_id", "source_boot_id", "source_boot_count",
            "received_epoch_ms", "retained", "generation_time", "fields"}
    if (not isinstance(value, dict) or set(value) != keys
            or value.get("provenance") != "MQTT_BOOT_ADVISORY" or value.get("integrity_status") != "UNSIGNED"
            or value.get("generation_time") != "NOT_OBSERVED" or type(value.get("retained")) is not bool
            or not isinstance(value.get("target_id"), str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value["target_id"]) is None
            or not isinstance(value.get("source_boot_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", value["source_boot_id"]) is None
            or not isinstance(value.get("fields"), dict)):
        return None
    try:
        count = _decimal(value["source_boot_count"], 1)
        _decimal(value["received_epoch_ms"], 0)
        if expected is not None and (value["target_id"], value["source_boot_id"], count) != (
                expected["target_id"], expected["source_boot_id"], int(expected["source_boot_count"])):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    return {**value, "fields": advisory_projection(value["fields"])}


class BootAdvisoryCache:
    """Bounded untrusted boot notes; no DB, registry, freshness or control methods."""
    def __init__(self, max_entries=32, clock=time.time):
        if type(max_entries) is not int or not 1 <= max_entries <= 128:
            raise ValueError("invalid advisory cache limit")
        self._limit, self._clock = max_entries, clock
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def observe(self, topic, payload, *, retained, configured_targets):
        if (not isinstance(topic, str) or not isinstance(payload, bytes)
                or not 1 <= len(payload) <= 4096 or type(retained) is not bool):
            return False
        match = re.fullmatch(r"gatekeeper/v1/targets/([A-Za-z0-9_-]{1,64})/boot", topic)
        if match is None or match[1] not in configured_targets:
            return False
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("duplicate boot field")
                result[key] = item
            return result
        def invalid_number(_value):
            raise ValueError("invalid number")
        try:
            doc = json.loads(payload.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_number)
            if (not isinstance(doc, dict) or doc.get("target_id") != match[1]
                    or not isinstance(doc.get("boot_id"), str)
                    or re.fullmatch(r"[0-9a-f]{32}", doc["boot_id"]) is None
                    or type(doc.get("boot_count")) is not int or not 1 <= doc["boot_count"] <= U64):
                return False
            value = dict(provenance="MQTT_BOOT_ADVISORY", integrity_status="UNSIGNED", target_id=match[1],
                source_boot_id=doc["boot_id"], source_boot_count=str(doc["boot_count"]),
                received_epoch_ms=str(int(self._clock()*1000)), retained=retained,
                generation_time="NOT_OBSERVED", fields=advisory_projection(doc))
            value = boot_observation_projection(value)
            if value is None:
                return False
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            return False
        identity = (value["target_id"], value["source_boot_id"], doc["boot_count"])
        with self._lock:
            self._entries[identity] = value
            self._entries.move_to_end(identity)
            while len(self._entries) > self._limit:
                self._entries.popitem(last=False)
        return True

    def match_verified(self, status):
        # Caller has already verified MAC and accepted high-water. Matching does
        # not update the observation receipt time or the status registry.
        identity = (status["target_id"], status["source_boot_id"], status["source_boot_count"])
        with self._lock:
            value = self._entries.get(identity)
            return boot_observation_projection(value, status) if value is not None else None


def ota_advisory_projection(value):
    """Versioned closed diagnostics, never image/command/health authority."""
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1:
        return None
    result = {"schema": 1}
    for key in ("attempt", "boot_count", "updated_uptime_ms", "bytes", "total",
                "heap_before", "heap_after", "largest_after"):
        item = value.get(key)
        if type(item) is not int or not 0 <= item <= U32:
            return None
        result[key] = item
    for key, upper in (("stage", 15), ("failed_stage", 15), ("error", 19), ("runtime_status", 11), ("rejection", 9)):
        item = value.get(key)
        if type(item) is not int or not 0 <= item <= upper:
            return None
        result[key] = item
    for key in ("http_code", "transport_code", "flash_code"):
        item = value.get(key)
        if type(item) is not int or not -(2**31) <= item < 2**31:
            return None
        result[key] = item
    for key in ("persisted", "restored", "request_pending", "running_image_valid"):
        if type(value.get(key)) is not bool:
            return None
        result[key] = value[key]
    version = value.get("target_version")
    if not isinstance(version, str) or re.fullmatch(r"[A-Za-z0-9_.+-]{0,63}", version) is None:
        return None
    result["target_version"] = version
    if result["bytes"] > result["total"]:
        return None
    return result


def _closed_observation(value, *, booleans=(), counters=(), nullable_counters=(), distances=(), codes=None):
    """Exact typed fields only; reject a malformed group without rejecting signed core."""
    if not isinstance(value, dict):
        return None
    result = {}
    for key in booleans:
        if type(value.get(key)) is not bool:
            return None
        result[key] = value[key]
    for keys, nullable, maximum in ((counters, False, U32), (nullable_counters, True, U32), (distances, True, 65534)):
        for key in keys:
            if key not in value:
                return None
            item = value[key]
            if not (nullable and item is None) and (type(item) is not int or not 0 <= item <= maximum):
                return None
            result[key] = item
    for key, allowed in (codes or {}).items():
        item = value.get(key)
        if not isinstance(item, str) or item not in allowed:
            return None
        result[key] = item
    return result


def rearm_history_projection(value):
    """Bounded, unsigned boot-local edges, not a durable/session-correlated log."""
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1:
        return None
    result = _closed_observation(value, counters=("sequence", "overwritten"),
                                 nullable_counters=("last_clear_ms",))
    edges = value.get("edges")
    if result is None or not isinstance(edges, list) or len(edges) != min(result["sequence"], 4):
        return None
    if result["overwritten"] != result["sequence"] - len(edges):
        return None
    for edge in edges:
        if not isinstance(edge, str) or len(edge) > 16 or not re.fullmatch(r"[0-9]+,[123],[12345],[0123]", edge):
            return None
        at, kind, reason, prior = map(int, edge.split(","))
        if at > U32 or str(at) != edge.split(",")[0]:
            return None
        if not ((kind == 1 and reason == 1 and prior == 0)
                or (kind == 2 and reason in (1, 2, 3, 4) and prior in (1, 2))
                or (kind == 3 and reason == 5 and prior == 3)):
            return None
    return dict(result, schema=1, edges=list(edges))


def field_recovery_advisory_projection(document):
    """September13 Target observations are unsigned, with uint32 uptime clocks.

    auth_ready permits a fresh authentication attempt; pulse_ready describes the
    separate sensor/rearm decision. Neither means the door physically moved.
    """
    if not isinstance(document, dict):
        return {}
    result = {}
    rearm = _closed_observation(document.get("passage_rearm"),
        booleans=("auth_ready", "pulse_ready", "blocked"),
        counters=("blocked_age_ms", "clear_samples", "retry_after_ms"),
        nullable_counters=("blocked_since_ms", "last_pulse_ms"),
        codes=dict(auth_reason={"BOOTING", "GATT_DISABLED", "OTA_BUSY", "ACL_UNAVAILABLE", "FSM_BUSY", "CONNECTION_ACTIVE", "REAUTH_QUIET", "READY"},
                   pulse_reason={"AUTH_REQUIRED", "SENSOR_CLEARANCE_UNCONFIRMED", "READY"},
                   pulse_source={"NONE", "SENSOR", "LOCAL_MANUAL", "REMOTE_MANUAL"}))
    if rearm is not None:
        history = rearm_history_projection(document["passage_rearm"].get("history"))
        if history is not None:
            rearm["history"] = history
        result["passage_rearm"] = rearm
    sample = document.get("sensor_observation")
    sensor = _closed_observation(sample, booleans=("valid",),
        counters=("idle_samples", "armed_samples", "cooldown_samples", "no_echo", "out_of_range", "valid_samples", "invalid_streak"),
        nullable_counters=("sampled_ms", "sample_age_ms", "echo_us", "last_valid_age_ms"),
        distances=("raw_mm", "last_valid_mm"),
        codes=dict(kind={"NOT_SAMPLED", "NO_ECHO", "OUT_OF_RANGE", "VALID_NEAR", "VALID_CLEAR", "VALID_BAND"},
                   phase={"NOT_SAMPLED", "IDLE", "ARMED", "COOLDOWN"}))
    qualification = _closed_observation(sample.get("qualification") if isinstance(sample, dict) else None,
        booleans=("active",), nullable_counters=("started_ms", "ended_ms", "median_age_ms"), distances=("median_mm",),
        counters=("samples", "valid_streak", "max_valid_streak", "near_streak", "max_near_streak", "median_rejects",
                  "candidates", "rearm_rejects", "fsm_rejects", "triggers"))
    if sensor is not None and qualification is not None:
        source = sample["qualification"]
        timing_keys = ("first_valid_after_ms", "first_near_after_ms", "near_streak_started_after_ms",
                       "first_candidate_after_ms", "trigger_after_ms")
        timing = _closed_observation(source, nullable_counters=timing_keys)
        if type(source.get("timing_schema")) is int and source["timing_schema"] == 1 and timing is not None:
            valid, near, streak, candidate, trigger = (timing[key] for key in timing_keys)
            # Invalid optional evidence must not erase the older valid counters.
            ordered = ((near is None or valid is not None and valid <= near)
                       and (streak is None or near is not None and near <= streak)
                       and (candidate is None or valid is not None and valid <= candidate)
                       and (trigger is None or candidate is not None and candidate <= trigger))
            if ordered:
                qualification.update(timing_schema=1, **timing)
        result["sensor_observation"] = dict(sensor, qualification=qualification)
    presence = _closed_observation(document.get("ble_presence"),
        booleans=("requested_ready", "applied_ready", "applied_valid", "pending"),
        counters=("requested_epoch", "applied_epoch", "attempts", "failures", "retries", "stops", "gap_count", "gap_ms", "last_gap_ms"),
        nullable_counters=("last_attempt_ms", "applied_age_ms"),
        codes=dict(status={"NOT_REQUESTED", "PENDING", "APPLIED", "DISABLED", "DEFERRED_CONNECTION", "DEFERRED_OTA", "RETRY_WAIT",
                           "UNAVAILABLE", "STOP_FAILED", "APPLY_FAILED", "START_FAILED", "INACTIVE_AFTER_START"},
                   last_result={"NONE", "APPLIED", "UNAVAILABLE", "STOP_FAILED", "APPLY_FAILED", "APPLY_START_FAILED", "START_FAILED", "INACTIVE_AFTER_START"},
                   restart_reason={"NONE", "PRESENCE_APPLY", "CHECKED_REFRESH", "watchdog", "disconnect"}))
    if presence is not None:
        result["ble_presence"] = presence
    advertisement_source = document.get("ble_advertisement")
    advertisement = _closed_observation(advertisement_source,
        booleans=("primary_applied", "response_applied"),
        counters=("payload_generation", "applied_generation", "refresh_count",
                  "primary_apply_failures", "response_apply_failures", "primary_length",
                  "response_length", "refresh_interval_ms"), nullable_counters=("last_apply_age_ms",),
        codes=dict(last_error={"NONE", "UNAVAILABLE", "STOP_FAILED", "START_FAILED", "APPLY_FAILED", "INACTIVE_AFTER_START",
                               "PRIMARY_ENCODING_FAILED", "RESPONSE_ENCODING_FAILED",
                               "PRIMARY_APPLY_FAILED", "RESPONSE_APPLY_FAILED"}))
    if (advertisement is not None and type(advertisement_source.get("schema")) is int
            and advertisement_source["schema"] == 1
            and advertisement["primary_length"] <= 31 and advertisement["response_length"] <= 31):
        result["ble_advertisement"] = dict(schema=1, **advertisement)
    return result


def advisory_projection(document, *, include_boot=False, expected=None):
    """Closed, explicitly unsigned fields useful for comparison, not authority."""
    if not isinstance(document, dict):
        return {}
    result = field_recovery_advisory_projection(document)
    mqtt = mqtt_connection_projection(document.get("mqtt_connection"))
    if mqtt is not None:
        result["mqtt_connection"] = mqtt
    ota = ota_advisory_projection(document.get("ota"))
    if ota is not None:
        result["ota"] = ota
    for key in ("firmware", "arduino_core", "idf_version"):
        value = document.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", value):
            result[key] = value
    for key in ("uptime_s", "free_heap", "min_free_heap", "reset_reason_code",
                "sensor_samples", "sensor_valid_samples", "sensor_timeouts", "sensor_invalid_samples",
                "mqtt_status_worker_published", "mqtt_status_worker_failures", "mqtt_status_worker_deferred",
                "mqtt_status_worker_max_duration_ms", "mqtt_publish_failures",
                "mqtt_last_failed_payload_bytes", "mqtt_status_payload_bytes",
                "mqtt_max_status_payload_bytes", "mqtt_audit_receipts_accepted", "mqtt_audit_receipts_rejected",
                "mqtt_audit_backpressure_count", "mqtt_audit_durable_depth", "mqtt_audit_pending_depth",
                "mqtt_audit_head_wait_ms", "mqtt_audit_head_publish_attempts", "mqtt_audit_head_boot_count",
                "sensor_summary_capture_pending", "sensor_summary_capture_dropped",
                "sensor_summary_pending", "sensor_summary_dropped", "sensor_summary_persistence_failures",
                "sensor_summary_invalid_journals", "largest_free_block", "loop_stack_hwm",
                "mqtt_connect_count", "mqtt_connect_attempts", "mqtt_connect_failures", "mqtt_last_connect_ms",
                "mqtt_max_connect_ms", "mqtt_connect_worker_wdt_failures", "mqtt_event_outbox_depth",
                "mqtt_event_outbox_overflow_count", "mqtt_legacy_outbox_depth", "mqtt_legacy_outbox_dropped",
                "rtc_event_fallback_restored_count", "rtc_event_fallback_pending_count", "wifi_link_generation",
                "wifi_outage_count", "wifi_recovery_escalations", "wifi_recovery_ap_failures", "wifi_recovery_successes",
                "wifi_last_unplanned_disconnect_reason", "wifi_current_outage_ms", "wifi_last_outage_ms",
                "ble_active_connections", "ble_advertising_restart_attempts", "ble_advertising_restart_successes",
                "ble_advertising_restart_failures", "ble_advertising_watchdog_recoveries", "gatt_accepted_connections",
                "gatt_disconnects", "gatt_challenges_issued", "gatt_proof_frames_received", "gatt_proofs_verified",
                "gatt_proofs_rejected", "gatt_results_indicated", "gatt_armed_entries", "gatt_sensor_detections",
                "gatt_relay_on_count", "gatt_relay_off_count", "gatt_terminal_count", "gatt_last_stage_ms",
                "previous_uptime_ms", "previous_access_uptime_ms"):
        value = document.get(key)
        if type(value) is int and 0 <= value <= U32:
            result[key] = value
    for key in ("mqtt_audit_stalled", "ble_advertising_active", "ble_advertising_expected", "sensor_rearm_blocked", "previous_valid",
                "previous_armed", "previous_relay_on", "previous_access_valid", "previous_evidence_persistence_failed",
                "rtc_event_fallback_invalid", "loop_watchdog_enabled"):
        if type(document.get(key)) is bool:
            result[key] = document[key]
    if type(document.get("wifi_rssi")) is int and -127 <= document["wifi_rssi"] <= 20:
        result["wifi_rssi"] = document["wifi_rssi"]
    if type(document.get("mqtt_last_error")) is int and -128 <= document["mqtt_last_error"] <= 255:
        result["mqtt_last_error"] = document["mqtt_last_error"]
    if type(document.get("previous_relay_pin")) is int and document["previous_relay_pin"] in (-1, 0, 1):
        result["previous_relay_pin"] = document["previous_relay_pin"]
    for key, values in (("reset_reason", RESET_REASONS), ("planned_restart", RESTART_REASONS),
                        ("previous_action", ACTION_CODES),
                        ("previous_state", {"unknown", "UNKNOWN", "BOOTING", "IDLE", "AUTH_PENDING", "ARMED", "RELAY_HOLD", "RELAY_ON", "COOLDOWN"}),
                        ("wifi_recovery_phase", {"CONNECTED", "AUTO_RECONNECT_GRACE", "AP_RETRY_BACKOFF", "RECOVERY_AP", "UNKNOWN"}),
                        ("sensor_clearance_state", {"UNKNOWN", "CLEAR", "OCCUPIED", "FAULT"})):
        value = document.get(key)
        if isinstance(value, str) and value in values:
            result[key] = value
    for key in ("gatt_last_stage", "previous_access_stage"):
        value = document.get(key)
        if isinstance(value, str) and value in ACCESS_STAGES:
            result[key] = value
    for key in ("gatt_last_session_id", "previous_access_session_id"):
        value = document.get(key)
        if value is None or value == "none":
            if key in document:
                result[key] = None
        elif isinstance(value, str) and UUID4.fullmatch(value):
            result[key] = value
    if include_boot:
        boot = boot_observation_projection(document.get("boot_observation"), expected)
        if boot is not None:
            result["boot_observation"] = boot
    return result


def _decimal(value, minimum=0):
    if not isinstance(value, str) or re.fullmatch(r"0|[1-9][0-9]{0,19}", value) is None:
        raise ValueError("invalid decimal")
    number = int(value)
    if not minimum <= number <= U64:
        raise ValueError("invalid decimal")
    return number


def interpret_sensor_observation(advisory: dict | None) -> dict:
    """Historical unsigned measurement interpretation, never a hardware verdict.

    No physical-arrival clock exists. Even first-near to trigger can include
    interrupted presence. Call with the closed advisory projection only.
    """
    sensor = (advisory or {}).get("sensor_observation") or {}
    q = sensor.get("qualification") or {}
    near = q.get("first_near_after_ms")
    trigger = q.get("trigger_after_ms")
    streak = q.get("near_streak_started_after_ms")
    has_timing = q.get("timing_schema") == 1
    return dict(
        evidence="UNSIGNED_OBSERVATION", scope="LATEST_ARM_WINDOW_IN_REPORTED_BOOT",
        started_ms=q.get("started_ms"), ended_ms=q.get("ended_ms"),
        current_observation=sensor.get("kind", "NOT_SAMPLED"),
        hardware_fault="UNDETERMINED", physical_arrival="NOT_OBSERVED",
        arm_window=("TRIGGER_OBSERVED" if q.get("triggers", 0) > 0 else
                    "WAITING_FOR_TRIGGER" if q.get("active") else
                    "ENDED_WITHOUT_TRIGGER" if q.get("samples", 0) > 0 else "NOT_OBSERVED"),
        timing_available=has_timing,
        arm_to_first_near_ms=near if has_timing else None,
        first_near_to_trigger_ms=(trigger - near if has_timing and near is not None
                                  and trigger is not None and trigger >= near else None),
        triggering_streak_to_trigger_ms=(trigger - streak if has_timing and streak is not None
                                         and trigger is not None and trigger >= streak else None),
        limitations=["ARM_WAIT_INCLUDES_APPROACH_TIME", "NO_ECHO_DOES_NOT_PROVE_HARDWARE_FAILURE",
                     "TIMEOUT_DOES_NOT_PROVE_ATTEMPTED_PASSAGE", "NEAR_INTERVAL_MAY_INCLUDE_INTERRUPTED_PRESENCE"],
    )


def _receipt(event: dict, keyring: dict, domain: bytes) -> dict:
    """Call only after a committed insert or byte-exact stored duplicate."""
    target = event["collector_target_id"]
    key_id = event["integrity_key_id"]
    key = keyring.get(key_id)
    if (event.get("integrity_status") != "verified"
            or not isinstance(key, bytes) or len(key) != 32 or not any(key)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", target) is None
            or re.fullmatch(r"[a-z0-9]{1,4}", key_id) is None
            or UUID4.fullmatch(event["event_id"]) is None
            or re.fullmatch(r"[0-9a-f]{32}", event["source_boot_id"]) is None
            or re.fullmatch(r"[0-9a-f]{32}", event["integrity_tag"]) is None):
        raise ValueError("invalid committed event")
    numbers = [event[k] for k in ("source_boot_count", "source_sequence")]
    if any(type(v) is not int or not 1 <= v <= U64 for v in numbers):
        raise ValueError("invalid event position")
    canonical = (domain + bytes([len(key_id)]) + key_id.encode("ascii")
                 + bytes([len(target)]) + target.encode("ascii") + uuid.UUID(event["event_id"]).bytes
                 + bytes.fromhex(event["source_boot_id"]) + numbers[0].to_bytes(8, "big")
                 + numbers[1].to_bytes(8, "big") + bytes.fromhex(event["integrity_tag"]))
    result = dict(type="access_event_receipt", version=1, target_id=target,
                  event_id=event["event_id"], source_boot_id=event["source_boot_id"],
                  source_boot_count=str(numbers[0]), source_sequence=str(numbers[1]),
                  event_tag=event["integrity_tag"], key_id=key_id,
                  tag=hmac.new(key, canonical, hashlib.sha256).digest()[:16].hex())
    return result


def build_access_receipt(event: dict, keyring: dict) -> bytes:
    result = _receipt(event, keyring, b"SGK-ACCESS-RECEIPT-V1\x00")
    return json.dumps(result, separators=(",", ":"), sort_keys=True).encode("ascii")


def build_sensor_receipt(status: dict, keyring: dict) -> bytes:
    summary, auth = status["sensor_session_summary"], status["sensor_summary_auth"]
    result = _receipt(dict(collector_target_id=status["target_id"], event_id=summary["session_id"],
                           source_boot_id=summary["source_boot_id"], source_boot_count=int(summary["source_boot_count"]),
                           source_sequence=int(summary["terminal_sequence"]), integrity_status="verified",
                           integrity_key_id=auth["key_id"], integrity_tag=auth["tag"]),
                      keyring, b"SGK-SENSOR-RECEIPT-V1\x00")
    result["type"] = "sensor_session_receipt"
    result["session_id"] = result.pop("event_id")
    result["terminal_sequence"] = result.pop("source_sequence")
    result["summary_tag"] = result.pop("event_tag")
    return json.dumps(result, separators=(",", ":"), sort_keys=True).encode("ascii")


def sensor_mac_input(summary: dict, key_id: str, target_id: str) -> bytes:
    if (not isinstance(summary, dict) or set(summary) != {"schema_version", *SENSOR_FIELDS}
            or type(summary.get("schema_version")) is not int or summary["schema_version"] != 1
            or re.fullmatch(r"[a-z0-9]{1,4}", key_id) is None
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", target_id) is None
            or not isinstance(summary["source_boot_id"], str)
            or re.fullmatch(r"[0-9a-f]{32}", summary["source_boot_id"]) is None
            or not isinstance(summary["session_id"], str)
            or UUID4.fullmatch(summary["session_id"]) is None):
        raise ValueError("invalid sensor identity")
    for key in DECIMAL_FIELDS:
        _decimal(summary[key], 1 if key in ("source_boot_count", "terminal_sequence") else 0)
    if any(int(summary[k]) > U32 for k in ("started_monotonic_ms", "ended_monotonic_ms")):
        raise ValueError("invalid sensor window")
    for key in ("samples", "valid_samples", "timeouts", "invalid_samples", "in_range_samples",
                "blocked_samples", "clear_samples"):
        if type(summary[key]) is not int or not 0 <= summary[key] <= U32:
            raise ValueError("invalid sensor count")
    if (summary["samples"] != sum(summary[k] for k in ("valid_samples", "timeouts", "invalid_samples"))
            or any(summary[k] > summary["samples"] for k in ("in_range_samples", "blocked_samples", "clear_samples"))
            or summary["in_range_samples"] > summary["valid_samples"]
            or summary["clear_samples"] > summary["valid_samples"]):
        raise ValueError("inconsistent sensor counts")
    if type(summary["threshold_mm"]) is not int or not 200 <= summary["threshold_mm"] <= 4000:
        raise ValueError("invalid sensor threshold")
    for key in MEASUREMENTS:
        value = summary[key]
        if value is not None and (type(value) is not int or not 200 <= value <= 4000):
            raise ValueError("invalid sensor measurement")
    if (any((summary[k] is None) != (summary["valid_samples"] == 0) for k in ("min_raw_mm", "max_raw_mm"))
            or (summary["valid_samples"] and summary["min_raw_mm"] > summary["max_raw_mm"])):
        raise ValueError("invalid sensor range")
    if (any(type(summary[k]) is not bool for k in ("blocked_at_start", "blocked_at_end"))
            or summary["clearance_state"] not in ("UNKNOWN", "CLEAR", "OCCUPIED", "FAULT")):
        raise ValueError("invalid sensor clearance")
    def token(value):
        if value is None:
            return "-"
        if type(value) is bool:
            return "1" if value else "0"
        return str(value)
    return "\n".join(["SGK-SENSOR-SESSION-MAC-V1", key_id, target_id]
                      + [token(summary[k]) for k in SENSOR_FIELDS]).encode("ascii")


def verified_sensor_summary(document: dict, status: dict, keyring: dict) -> dict | None:
    summary, auth = document.get("sensor_session_summary"), document.get("sensor_summary_auth")
    try:
        if (not isinstance(auth, dict) or set(auth) != {"version", "key_id", "tag"}
                or type(auth["version"]) is not int or auth["version"] != 1
                or not isinstance(auth["tag"], str) or re.fullmatch(r"[0-9a-f]{32}", auth["tag"]) is None):
            return None
        canonical = sensor_mac_input(summary, auth["key_id"], status["target_id"])
        key = keyring.get(auth["key_id"])
        if not isinstance(key, bytes) or len(key) != 32 or not any(key):
            return None
        if not hmac.compare_digest(auth["tag"], hmac.new(key, canonical, hashlib.sha256).digest()[:16].hex()):
            return None
        if (int(summary["source_boot_count"]) > status["source_boot_count"]
                or (int(summary["source_boot_count"]) == status["source_boot_count"]
                    and summary["source_boot_id"] != status["source_boot_id"])):
            return None
        return dict(summary)
    except (KeyError, ValueError, TypeError):
        return None


def record_verified_health(cur, status: dict):
    """Sample health after authenticated highwater advances, in its transaction.

    Existing signed boot/state/terminal/relay transitions always insert. Otherwise
    unchanged health is sampled every 30s; a new MQTT edge may insert after 5s
    since this Target's latest persisted health row. Only a validated edge whose
    sequence matches the advertised head can request that bypass. Other changing
    unsigned counters, edge contents and flapping cannot create extra writes.

    The committed health row is the checkpoint, not the last observed message.
    Suppression and transaction rollback do not consume an edge: a subsequent
    advancing signed status carrying it retries once the gate elapses. This is
    bounded snapshot capture, not a durable edge queue or an edge ACK guarantee.
    Callers serialize per Target with the existing signed highwater row lock.
    """
    core = {key: status[key] for key in CORE_FIELDS}
    # Explicitly not authenticated by the access-status MAC. Never use for control.
    advisory = advisory_projection(status.get("advisory_diagnostics") or status.get("controller_diagnostics"),
                                   include_boot=True, expected=status)
    mqtt = advisory.get("mqtt_connection")
    edge_sequence = 0
    if mqtt is not None and any(mqtt_edge_projection(edge)["sequence"] == mqtt["edge_sequence"]
                                for edge in mqtt["edges"]):
        edge_sequence = mqtt["edge_sequence"]
    cur.execute(
        "INSERT INTO target_health_history (target_id,source_boot_id,source_boot_count,"
        "status_revision,gate_state,terminal_session_id,relay_commanded_on,verified_json,advisory_json,received_at) "
        "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(3) FROM DUAL WHERE NOT EXISTS ("
        "SELECT 1 FROM (SELECT source_boot_id,gate_state,terminal_session_id,relay_commanded_on,received_at,advisory_json "
        "FROM target_health_history WHERE target_id=%s ORDER BY id DESC LIMIT 1) AS recent "
        "WHERE source_boot_id=%s AND gate_state=%s AND terminal_session_id <=> %s "
        "AND relay_commanded_on=%s AND received_at > UTC_TIMESTAMP(3) - INTERVAL 30 SECOND "
        "AND (received_at > UTC_TIMESTAMP(3) - INTERVAL 5 SECOND OR %s <= "
        "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(advisory_json, '$.mqtt_connection.edge_sequence')) "
        "AS UNSIGNED), 0)))",
        (status["target_id"], status["source_boot_id"], status["source_boot_count"], status["status_revision"],
         status["state"], status["last_terminal_session_id"], status["relay_commanded_on"],
         json.dumps(core, separators=(",", ":")), json.dumps(advisory, separators=(",", ":")) if advisory else None,
         status["target_id"], status["source_boot_id"], status["state"], status["last_terminal_session_id"],
         status["relay_commanded_on"], edge_sequence),
    )
    # Bounded maintenance of operational tables only. Security/access/mobile history is untouched.
    if isinstance(cur.rowcount, int) and cur.rowcount > 0:
        for table in ("target_health_history", "target_sensor_session_history"):
            cur.execute("DELETE FROM " + table + " WHERE received_at < UTC_TIMESTAMP(3) - INTERVAL 31 DAY LIMIT 100")


def record_sensor_summary(cur, status: dict):
    summary = status.get("sensor_session_summary")
    if summary is not None:
        encoded = json.dumps(summary, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        cur.execute("SELECT summary_sha256 FROM target_sensor_session_history "
                    "WHERE target_id=%s AND source_boot_id=%s AND terminal_sequence=%s",
                    (status["target_id"], summary["source_boot_id"], int(summary["terminal_sequence"])))
        existing = cur.fetchone()
        if existing is not None:
            if existing["summary_sha256"] != digest:
                raise ValueError("sensor summary identity conflict")
            return
        cur.execute("INSERT INTO target_sensor_session_history "
                    "(target_id,source_boot_id,source_boot_count,session_id,terminal_sequence,summary_json,summary_sha256,received_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(3))",
                    (status["target_id"], summary["source_boot_id"], int(summary["source_boot_count"]),
                     summary["session_id"], int(summary["terminal_sequence"]), encoded, digest))


def classify_incident(events: list[dict], sensor: dict | None = None) -> dict:
    """A session failure boundary, never proof of arrival/phone identity/door travel."""
    local_stages = [
        ("GATT", "ACCESS_GATT_CONNECTED"), ("CHALLENGE", "ACCESS_PROOF_REQUESTED"),
        ("PROOF", "ACCESS_PROOF_VERIFIED"),
    ]
    codes = {e["event_code"] for e in events}
    paths = {e.get("event_path") for e in events if e.get("event_path")}
    manual = paths == {"mqtt_manual_remote"}
    prearm = paths == {"mqtt_prearm"}
    terminal_codes = {"ACCESS_SESSION_COMPLETED", "ACCESS_SIGNED_ARM_COMPLETED", "ACCESS_SIGNED_MANUAL_COMPLETED"}
    termination_codes = {"ACCESS_SESSION_TERMINATED", "ACCESS_SIGNED_ARM_TERMINATED", "ACCESS_SIGNED_MANUAL_TERMINATED"}
    stages = ([] if manual or prearm else local_stages) + (
        [("MANUAL_COMMAND", "ACCESS_MANUAL_OPEN_RECEIVED")] if manual else
        [("ARM", "ACCESS_ARMED"), ("SENSOR", "ACCESS_SENSOR_DETECTED")]
    ) + [("RELAY_ON", "ACCESS_RELAY_ON"), ("RELAY_OFF", "ACCESS_RELAY_OFF")]
    # Signed MQTT summary terminal codes are different from local-GATT codes.
    # A remote open is not missing GATT or sensor evidence: those stages do not apply.
    if terminal_codes & codes:
        stages.append(("COMPLETE", next(iter(terminal_codes & codes))))
    else:
        stages.append(("COMPLETE", "ACCESS_SESSION_COMPLETED"))
    observed = [name for name, code in stages if code in codes]
    reasons = [e["reason_code"] for e in events if e.get("reason_code") and
               e.get("event_outcome") in ("FAILED", "TIMED_OUT", "DENIED", "CANCELLED")]
    terminal = next((e for e in reversed(events) if e["event_code"] in terminal_codes | termination_codes), None)
    first_missing = next((name for name, code in stages if code not in codes), "DOOR_CONTACT")
    sensor_boundary = None
    timeout_detail = None
    timeout_window_ms = None
    # Only the matching verified terminal summary can explain this timeout.
    # Latest unsigned telemetry and summaries for another window are not causes.
    if (sensor is not None and terminal is not None
            and terminal.get("reason_code") == "ARM_TIMEOUT"
            and "ACCESS_SENSOR_DETECTED" not in codes
            and all(terminal.get(event_key) is not None and
                    str(terminal[event_key]) == str(sensor.get(summary_key))
                    for event_key, summary_key in (("session_id", "session_id"),
                        ("source_boot_id", "source_boot_id"), ("source_sequence", "terminal_sequence")))):
        timeout_detail = ("REARM_CLEARANCE_UNCONFIRMED" if sensor["blocked_at_end"] else
                          "SENSOR_SAMPLING_NOT_OBSERVED" if sensor["samples"] == 0 else
                          "SENSOR_VALID_SAMPLE_NOT_OBSERVED" if sensor["valid_samples"] == 0 else
                          "SENSOR_IN_RANGE_NOT_OBSERVED" if sensor["in_range_samples"] == 0 else
                          "SENSOR_QUALIFICATION_NOT_OBSERVED")
        timeout_window_ms = (int(sensor["ended_monotonic_ms"]) - int(sensor["started_monotonic_ms"])) & U32
    if sensor is not None and "ARM_TIMEOUT" in reasons:
        if sensor["blocked_at_end"]:
            sensor_boundary = "SENSOR_REARM_BLOCK_OBSERVED"
        elif sensor["samples"] == 0:
            sensor_boundary = "SENSOR_SAMPLING_NOT_OBSERVED"
        elif sensor["valid_samples"] == 0:
            sensor_boundary = "SENSOR_VALID_SAMPLE_NOT_OBSERVED"
        elif sensor["blocked_samples"] > 0:
            sensor_boundary = "SENSOR_REARM_BLOCK_OBSERVED"
        elif sensor["in_range_samples"] == 0:
            sensor_boundary = "SENSOR_IN_RANGE_NOT_OBSERVED"
        else:
            sensor_boundary = "SENSOR_QUALIFICATION_NOT_OBSERVED"
    monotonic = [int(e["monotonic_ms"]) for e in events if e.get("monotonic_ms") is not None]
    deltas = [b-a if b >= a else (b-a) & U32 if max(a, b) <= U32 else None
              for a, b in zip(monotonic, monotonic[1:])]
    span = sum(deltas) if monotonic and None not in deltas else None
    return dict(observed_stages=observed, first_missing_stage=first_missing,
                access_path=next(iter(paths)) if len(paths) == 1 else "UNKNOWN",
                explicit_reasons=sorted(set(reasons)), sensor_boundary=sensor_boundary,
                arm_timeout_detail=timeout_detail, arm_timeout_window_ms=timeout_window_ms,
                arm_timeout_detail_source="MATCHED_VERIFIED_SENSOR_SUMMARY" if timeout_detail else "NOT_OBSERVED",
                classification="EXPLICIT_FAILURE" if reasons else "FLOW_REPORTED_COMPLETE" if terminal and terminal_codes & codes else "INCOMPLETE_EVIDENCE",
                interpretation=("ARM_WINDOW_EXPIRED_WITHOUT_SENSOR_TRIGGER" if set(reasons) == {"ARM_TIMEOUT"}
                                and "ACCESS_SENSOR_DETECTED" not in codes else
                                "FLOW_COMPLETION_REPORTED" if terminal_codes & codes else "SEE_OBSERVED_STAGES"),
                physical_failure="UNDETERMINED",
                source_span_meaning="RECORDED_STAGE_SPAN_NOT_USER_WAIT",
                missing_events_possible=True, source_span_ms=span,
                physical_door="NOT_OBSERVABLE", arrival="NOT_OBSERVABLE", owner_attribution="UNRESOLVED")
