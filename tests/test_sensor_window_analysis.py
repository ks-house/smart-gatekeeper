"""Behavioral regressions for offline diagnostic attribution boundaries."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.analyze_sensor_windows import analyze

ROOT = Path(__file__).resolve().parents[1]


def fixtures(start=100, end=60100, near=54641, trigger=54872):
    summary = dict(source_boot_id="boot-a", source_boot_count="7", started_monotonic_ms=str(start),
                   ended_monotonic_ms=str(end), samples=419, valid_samples=3,
                   in_range_samples=3, blocked_samples=0, blocked_at_end=True)
    incident = dict(target_id="target-a", source_boot_id="boot-a",
                    classification="FLOW_REPORTED_COMPLETE", explicit_reasons=[],
                    sensor_integrity="verified", sensor_summary=summary)
    q = dict(active=False, started_ms=start, ended_ms=end, timing_schema=1,
             first_valid_after_ms=near, first_near_after_ms=near,
             near_streak_started_after_ms=near, first_candidate_after_ms=trigger,
             trigger_after_ms=trigger)
    row = dict(integrity_status="verified",
               verified=dict(target_id="target-a", source_boot_id="boot-a", source_boot_count="7"),
               unsigned_advisory=dict(sensor_observation=dict(qualification=q)))
    return dict(incidents=[incident], coverage=dict(events_truncated=False,
                sensor_summaries_truncated=False)), dict(history=[row])


class SensorWindowAnalysisTest(unittest.TestCase):
    def test_separates_long_wait_from_short_near_to_trigger_without_promoting_trust(self):
        incidents, health = fixtures()
        result = analyze(incidents, [health])
        self.assertEqual(1, result["timing_matched"])
        window = result["windows"][0]
        self.assertEqual(54641, window["arm_to_first_near_ms"])
        self.assertEqual(231, window["first_near_to_trigger_ms"])
        self.assertEqual("UNSIGNED_OBSERVATION", window["qualification_evidence"])
        self.assertEqual("NOT_OBSERVED", result["physical_passage"])
        self.assertEqual("SUPPLIED_PAGES_ONLY", result["health_coverage"])

    def test_wrong_target_boot_bounds_active_or_integrity_cannot_match(self):
        for field, value in [("target_id", "other"), ("source_boot_id", "other"), ("source_boot_count", "8"),
                             ("started_ms", 101), ("ended_ms", 60101),
                             ("active", True), ("integrity_status", "unverified")]:
            incidents, health = fixtures()
            row = health["history"][0]
            if field in ("target_id", "source_boot_id", "source_boot_count"):
                row["verified"][field] = value
            elif field == "integrity_status":
                row[field] = value
            else:
                row["unsigned_advisory"]["sensor_observation"]["qualification"][field] = value
            with self.subTest(field=field):
                self.assertEqual(0, analyze(incidents, [health])["timing_matched"])

    def test_duplicate_snapshots_agree_but_conflicting_timing_is_not_selected(self):
        incidents, health = fixtures()
        duplicated = copy.deepcopy(health)
        self.assertEqual(1, analyze(incidents, [health, duplicated])["timing_matched"])
        duplicated["history"][0]["unsigned_advisory"]["sensor_observation"]["qualification"].update(
            first_valid_after_ms=54000, first_near_after_ms=54000)
        window = analyze(incidents, [health, duplicated])["windows"][0]
        self.assertEqual("CONFLICTING_OBSERVATIONS", window["timing_status"])
        self.assertIsNone(window["first_near_to_trigger_ms"])

    def test_zero_offsets_and_rollover_are_valid_but_impossible_offsets_are_not(self):
        incidents, health = fixtures(start=(1 << 32) - 100, end=300, near=0, trigger=231)
        self.assertEqual(231, analyze(incidents, [health])["windows"][0]["first_near_to_trigger_ms"])
        for value in [True, -1, 401, "1"]:
            modified = copy.deepcopy(health)
            modified["history"][0]["unsigned_advisory"]["sensor_observation"]["qualification"][
                "trigger_after_ms"] = value
            with self.subTest(value=value):
                self.assertEqual(0, analyze(incidents, [modified])["timing_matched"])

    def test_unsigned_or_mismatched_summary_never_gains_signed_window_attribution(self):
        for mode in ["unsigned", "wrong_boot"]:
            incidents, health = fixtures()
            if mode == "unsigned":
                incidents["incidents"][0]["sensor_integrity"] = "unsigned"
            else:
                incidents["incidents"][0]["sensor_summary"]["source_boot_id"] = "other"
            self.assertEqual(0, analyze(incidents, [health])["timing_matched"])

    def test_timeout_patterns_do_not_become_person_or_hardware_failure_counts(self):
        incidents, health = fixtures()
        rows = []
        for valid, near, blocked in [(0, 0, False), (8, 0, False), (11, 3, False), (3, 3, True)]:
            row = copy.deepcopy(incidents["incidents"][0])
            row.update(classification="EXPLICIT_FAILURE", explicit_reasons=["ARM_TIMEOUT"])
            row["sensor_summary"].update(valid_samples=valid, in_range_samples=near,
                                         blocked_at_end=blocked)
            rows.append(row)
        incidents["incidents"] = rows
        result = analyze(incidents, [health])
        self.assertEqual({"NO_VALID_SAMPLE": 1, "NO_IN_RANGE_SAMPLE": 1,
                          "QUALIFICATION_NOT_OBSERVED": 1, "REARM_BLOCK_OBSERVED": 1},
                         result["patterns"])
        self.assertEqual("UNDETERMINED", result["hardware_fault"])

    def test_cli_uses_saved_files_and_omits_identities(self):
        incidents, health = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            inc, hist = Path(tmp) / "incidents.json", Path(tmp) / "health.json"
            inc.write_text(json.dumps(incidents))
            hist.write_text(json.dumps(health))
            proc = subprocess.run([sys.executable, str(ROOT / "scripts/analyze_sensor_windows.py"),
                                   "--incidents", str(inc), "--health", str(hist)],
                                  capture_output=True, text=True, check=True)
        self.assertEqual(231, json.loads(proc.stdout)["windows"][0]["first_near_to_trigger_ms"])
        self.assertNotIn("target-a", proc.stdout)
        self.assertNotIn("boot-a", proc.stdout)


if __name__ == "__main__":
    unittest.main()
