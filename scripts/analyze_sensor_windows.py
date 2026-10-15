#!/usr/bin/env python3
"""Correlate saved diagnostic windows without network or device access.

Signed sensor-summary provenance and unsigned qualification observations stay
separate. Matching a window never establishes physical arrival or passage.
"""
import argparse
import json
from pathlib import Path

U32 = (1 << 32) - 1
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_HEALTH_ROWS = 10000
TIMING_FIELDS = (
    "first_valid_after_ms", "first_near_after_ms",
    "near_streak_started_after_ms", "first_candidate_after_ms", "trigger_after_ms",
)


def uint(value, decimal=False, maximum=U32):
    if (decimal and isinstance(value, str) and len(value) <= 20
            and value.isascii() and value.isdecimal()):
        value = int(value)
    return value if type(value) is int and 0 <= value <= maximum else None


def window_key(target, boot, count, start, end):
    count = uint(count, True, (1 << 64) - 1)
    start, end = uint(start, True), uint(end, True)
    if not isinstance(target, str) or not target or not isinstance(boot, str) or not boot:
        return None
    return None if count is None or start is None or end is None else (target, boot, count, start, end)


def timing_projection(q, duration):
    if type(q.get("timing_schema")) is not int or q["timing_schema"] != 1:
        return None
    values = []
    for name in TIMING_FIELDS:
        value = q.get(name)
        if name not in q or value is not None and (uint(value) is None or value > duration):
            return None
        values.append(value)
    valid, near, streak, candidate, trigger = values
    ordered = (
        (near is None or valid is not None and valid <= near)
        and (streak is None or near is not None and near <= streak)
        and (candidate is None or valid is not None and valid <= candidate)
        and (trigger is None or near is not None and candidate is not None
             and near <= trigger and candidate <= trigger
             and (streak is None or streak <= trigger))
    )
    return dict(zip(TIMING_FIELDS, values)) if ordered else None


def analyze(incidents, health_pages):
    if not isinstance(incidents, dict) or not isinstance(incidents.get("incidents"), list):
        raise ValueError("expected an incidents API response")
    if len(incidents["incidents"]) > 100:
        raise ValueError("incident bound exceeded")
    index = {}
    row_count = 0
    for page in health_pages:
        if not isinstance(page, dict) or not isinstance(page.get("history"), list):
            raise ValueError("expected health-history API responses")
        row_count += len(page["history"])
        if row_count > MAX_HEALTH_ROWS:
            raise ValueError("health row bound exceeded")
        for row in page["history"]:
            if not isinstance(row, dict) or row.get("integrity_status") != "verified":
                continue
            verified, advisory = row.get("verified"), row.get("unsigned_advisory")
            if not isinstance(verified, dict) or not isinstance(advisory, dict):
                continue
            sensor = advisory.get("sensor_observation")
            q = sensor.get("qualification") if isinstance(sensor, dict) else None
            if not isinstance(q, dict) or q.get("active") is not False:
                continue
            key = window_key(verified.get("target_id"), verified.get("source_boot_id"),
                             verified.get("source_boot_count"), q.get("started_ms"), q.get("ended_ms"))
            if key is not None:
                duration = (key[4] - key[3]) & U32
                timing = timing_projection(q, duration)
                if timing is not None:
                    index.setdefault(key, set()).add(json.dumps(timing, sort_keys=True))
    windows = []
    patterns = {}
    for ordinal, incident in enumerate(incidents["incidents"], 1):
        if not isinstance(incident, dict):
            raise ValueError("expected incident objects")
        summary = incident.get("sensor_summary")
        reasons = incident.get("explicit_reasons", [])
        pattern = "OTHER"
        if "ARM_TIMEOUT" in reasons:
            pattern = "SENSOR_SUMMARY_UNAVAILABLE"
            if incident.get("sensor_integrity") == "verified" and isinstance(summary, dict):
                pattern = ("REARM_BLOCK_OBSERVED" if summary.get("blocked_at_end") is True
                           or uint(summary.get("blocked_samples")) not in (None, 0) else
                           "NO_SAMPLES" if summary.get("samples") == 0 else
                           "NO_VALID_SAMPLE" if summary.get("valid_samples") == 0 else
                           "NO_IN_RANGE_SAMPLE" if summary.get("in_range_samples") == 0 else
                           "QUALIFICATION_NOT_OBSERVED")
        elif incident.get("classification") == "FLOW_REPORTED_COMPLETE":
            pattern = "FLOW_REPORTED_COMPLETE"
        elif "GATT_DISCONNECTED" in reasons:
            pattern = "GATT_DISCONNECTED"
        patterns[pattern] = patterns.get(pattern, 0) + 1
        item = dict(ordinal=ordinal, pattern=pattern, source_reported_sensor_integrity=
                    incident.get("sensor_integrity", "NOT_OBSERVED"),
                    timing_status="UNAVAILABLE", qualification_evidence="UNSIGNED_OBSERVATION",
                    arm_window_ms=None, arm_to_first_near_ms=None, first_near_to_trigger_ms=None)
        if incident.get("sensor_integrity") == "verified" and isinstance(summary, dict):
            # Match both identities in the signed source and incident; never a
            # different Target/boot or a merely adjacent/latest window.
            boot = incident.get("source_boot_id")
            key = window_key(incident.get("target_id"), boot,
                             summary.get("source_boot_count"), summary.get("started_monotonic_ms"),
                             summary.get("ended_monotonic_ms"))
            if summary.get("source_boot_id") == boot and key is not None:
                item["arm_window_ms"] = (key[4] - key[3]) & U32
                candidates = index.get(key, set())
                if len(candidates) > 1:
                    item["timing_status"] = "CONFLICTING_OBSERVATIONS"
                elif len(candidates) == 1:
                    timing = json.loads(next(iter(candidates)))
                    near, trigger = timing["first_near_after_ms"], timing["trigger_after_ms"]
                    item.update(timing_status="EXACT_WINDOW_MATCH",
                                arm_to_first_near_ms=near,
                                first_near_to_trigger_ms=(trigger - near if near is not None
                                                         and trigger is not None else None))
        windows.append(item)
    coverage = incidents.get("coverage") or {}
    return dict(schema_version=1, incident_count=len(windows), supplied_health_rows=row_count,
                timing_matched=sum(x["timing_status"] == "EXACT_WINDOW_MATCH" for x in windows),
                event_list_truncated=coverage.get("events_truncated"),
                sensor_list_truncated=coverage.get("sensor_summaries_truncated"),
                health_coverage="SUPPLIED_PAGES_ONLY", patterns=patterns, windows=windows,
                physical_arrival="NOT_OBSERVED", physical_passage="NOT_OBSERVED",
                hardware_fault="UNDETERMINED",
                limitations=["COUNTS_ARE_SESSIONS_NOT_HUMAN_SUCCESS_RATES",
                             "ARM_WAIT_INCLUDES_UNOBSERVED_APPROACH_TIME",
                             "QUALIFICATION_TIMING_IS_UNSIGNED",
                             "NO_ECHO_DOES_NOT_PROVE_HARDWARE_FAILURE"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incidents", type=Path, required=True)
    parser.add_argument("--health", type=Path, nargs="+", required=True)
    args = parser.parse_args(argv)
    paths = [args.incidents, *args.health]
    if len(paths) > 65:
        parser.error("file count bound exceeded")
    documents, total = [], 0
    for path in paths:
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        total += len(raw)
        if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            parser.error("input size bound exceeded")
        documents.append(json.loads(raw))
    print(json.dumps(analyze(documents[0], documents[1:]), ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
