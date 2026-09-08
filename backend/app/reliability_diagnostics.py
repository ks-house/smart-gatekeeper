"""Bounded diagnostic evidence; no authorization or actuator decisions."""

import hashlib
import hmac
import json
import re
import uuid


U64 = (1 << 64) - 1
U32 = (1 << 32) - 1
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


def advisory_projection(document):
    """Closed, explicitly unsigned fields useful for comparison, not authority."""
    if not isinstance(document, dict):
        return {}
    result = {}
    for key in ("firmware", "reset_reason", "planned_restart"):
        value = document.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", value):
            result[key] = value
    for key in ("uptime_s", "free_heap", "min_free_heap", "reset_reason_code",
                "sensor_samples", "sensor_valid_samples", "sensor_timeouts", "sensor_invalid_samples",
                "mqtt_status_worker_published", "mqtt_status_worker_failures", "mqtt_status_worker_deferred",
                "mqtt_status_worker_max_duration_ms", "mqtt_audit_receipts_accepted", "mqtt_audit_receipts_rejected",
                "mqtt_audit_backpressure_count", "sensor_summary_capture_pending", "sensor_summary_capture_dropped",
                "sensor_summary_pending", "sensor_summary_dropped", "sensor_summary_persistence_failures",
                "sensor_summary_invalid_journals"):
        value = document.get(key)
        if type(value) is int and 0 <= value <= U32:
            result[key] = value
    for key in ("ble_advertising_active", "ble_advertising_expected", "sensor_rearm_blocked"):
        if type(document.get(key)) is bool:
            result[key] = document[key]
    if type(document.get("wifi_rssi")) is int and -127 <= document["wifi_rssi"] <= 20:
        result["wifi_rssi"] = document["wifi_rssi"]
    return result


def _decimal(value, minimum=0):
    if not isinstance(value, str) or re.fullmatch(r"0|[1-9][0-9]{0,19}", value) is None:
        raise ValueError("invalid decimal")
    number = int(value)
    if not minimum <= number <= U64:
        raise ValueError("invalid decimal")
    return number


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
    """Called in the same transaction after authenticated highwater advances."""
    core = {key: status[key] for key in CORE_FIELDS}
    # Explicitly not authenticated by the access-status MAC. Never use for control.
    advisory = status.get("advisory_diagnostics") or advisory_projection(status.get("controller_diagnostics"))
    cur.execute(
        "INSERT INTO target_health_history (target_id,source_boot_id,source_boot_count,"
        "status_revision,gate_state,terminal_session_id,relay_commanded_on,verified_json,advisory_json,received_at) "
        "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(3) FROM DUAL WHERE NOT EXISTS ("
        "SELECT 1 FROM (SELECT source_boot_id,gate_state,terminal_session_id,relay_commanded_on,received_at "
        "FROM target_health_history WHERE target_id=%s ORDER BY id DESC LIMIT 1) AS recent "
        "WHERE source_boot_id=%s AND gate_state=%s AND terminal_session_id <=> %s "
        "AND relay_commanded_on=%s AND received_at > UTC_TIMESTAMP(3) - INTERVAL 30 SECOND)",
        (status["target_id"], status["source_boot_id"], status["source_boot_count"], status["status_revision"],
         status["state"], status["last_terminal_session_id"], status["relay_commanded_on"],
         json.dumps(core, separators=(",", ":")), json.dumps(advisory, separators=(",", ":")) if advisory else None,
         status["target_id"], status["source_boot_id"], status["state"], status["last_terminal_session_id"],
         status["relay_commanded_on"]),
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
    if sensor is not None and "ARM_TIMEOUT" in reasons:
        if sensor["samples"] == 0:
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
                classification="EXPLICIT_FAILURE" if reasons else "FLOW_REPORTED_COMPLETE" if terminal and terminal_codes & codes else "INCOMPLETE_EVIDENCE",
                missing_events_possible=True, source_span_ms=span,
                physical_door="NOT_OBSERVABLE", arrival="NOT_OBSERVABLE", owner_attribution="UNRESOLVED")
