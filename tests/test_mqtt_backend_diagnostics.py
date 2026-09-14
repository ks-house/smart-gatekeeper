"""Cross-layer MQTT wire, persistence, read API and local CLI contract tests."""

import contextlib
import hashlib
import hmac
import io
import importlib.util
import json
import sqlite3
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

if importlib.util.find_spec("fastapi") is None:
    raise unittest.SkipTest("Backend integration runs in backend CI with its locked dependencies")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.diagnostics_read import create_diagnostics_read_router
from backend.app.reliability_diagnostics import (
    CORE_FIELDS, MQTT_COUNTERS, MQTT_EDGE_FIELDS, MQTT_REASONS, U32,
    advisory_projection, mqtt_connection_projection, mqtt_edge_projection, record_verified_health,
)
from backend.tests.test_reliability_diagnostics import BOOT, KEY, TARGET, status_value
from scripts import read_diagnostics as cli


def mqtt_value():
    return dict(schema=1, generation=9, disconnects=8, planned_disconnects=1,
                last_disconnect_ms=12000, last_connected_ms=13000,
                last_connection_duration_ms=1000, retry_in_ms=5000, loop_gap_max_ms=60,
                edge_sequence=8, edge_overwritten=4, last_reason="TRANSPORT_LOST",
                last_error=-3, flapping=True,
                edges=["7,11000,9,0,60000,64000,32000,50,0",
                       "8,12000,6,-3,1000,63000,31000,60,0"])


def health_row(row_id=3, mqtt=None, *, boot=BOOT):
    return dict(id=row_id, received_at=datetime(2026, 9, 14, 4),
                verified_json=json.dumps({**status_value(), "source_boot_id": boot}),
                advisory_json=json.dumps({"mqtt_connection": mqtt}) if mqtt is not None else None)


def signed_document():
    core = status_value()
    core.update(last_terminal_session_id=None, last_terminal_event_sequence=None,
                last_terminal_event_code=None, last_terminal_reason_code=None,
                last_terminal_credential_ref=None, last_terminal_phase_mask=0)
    wire = main.build_access_status_mac_input(
        key_id="a1", topic_target_id=TARGET, door_id="a" * 32,
        source_boot_id=BOOT, source_boot_count=core["source_boot_count"], access_revision=1,
        **{key: core[key] for key in CORE_FIELDS if key not in
           ("target_id", "source_boot_id", "source_boot_count", "status_revision")})
    doc = {key: core[key] for key in CORE_FIELDS if key not in
           ("source_boot_id", "source_boot_count", "status_revision")}
    doc.update(boot_id=BOOT, boot_count=core["source_boot_count"], access_status_revision=1,
               access_auth=dict(version=1, key_id="a1",
                                tag=hmac.new(KEY, wire, hashlib.sha256).digest()[:16].hex()))
    return doc


class MqttWireTest(unittest.TestCase):
    def test_wire_projection_is_closed_idempotent_and_copies_edges(self):
        value = mqtt_value()
        noisy = {**value, "secret": "must-not-escape", "authority": True}
        result = advisory_projection({"mqtt_connection": noisy})
        self.assertEqual({"mqtt_connection": value}, result)
        self.assertEqual(result, advisory_projection(result))
        result["mqtt_connection"]["edges"].clear()
        self.assertEqual(2, len(value["edges"]))
        self.assertEqual({}, advisory_projection({}))

    def test_schema_types_all_counter_bounds_and_required_fields(self):
        value = mqtt_value()
        for key in MQTT_COUNTERS:
            for bad in (-1, U32 + 1, True, 1.0, "1", None):
                with self.subTest(key=key, bad=bad):
                    self.assertIsNone(mqtt_connection_projection({**value, key: bad}))
            for good in (0, U32):
                self.assertIsNotNone(mqtt_connection_projection({**value, key: good}))
        for key, bad in (("schema", True), ("schema", 2), ("schema", 1.0),
                         ("last_reason", "BROKER_DUPLICATE_CLIENT"), ("last_reason", []),
                         ("last_error", -129), ("last_error", 256), ("last_error", True),
                         ("last_error", 0.0), ("flapping", 1), ("flapping", "false"),
                         ("edges", None), ("edges", ()), ("edges", [value["edges"][0]] * 5)):
            with self.subTest(key=key, bad=bad):
                self.assertIsNone(mqtt_connection_projection({**value, key: bad}))
        for key in value:
            missing = dict(value)
            del missing[key]
            self.assertIsNone(mqtt_connection_projection(missing), key)
        for reason in MQTT_REASONS:
            self.assertIsNotNone(mqtt_connection_projection({**value, "last_reason": reason}))
        self.assertIsNotNone(mqtt_connection_projection({**value, "edges": []}))

    def test_exact_nine_ascii_decimal_fields_and_reason_mapping(self):
        for reason in range(1, 14):
            parts = [U32, U32, reason, -128, U32, U32, U32, U32, U32]
            edge = mqtt_edge_projection(",".join(map(str, parts)))
            self.assertEqual(parts, [edge[key] for key in MQTT_EDGE_FIELDS])
            self.assertEqual(MQTT_REASONS[reason], edge["reason"])
        self.assertEqual(255, mqtt_edge_projection("0,0,1,255,0,0,0,0,0")["last_error"])
        valid = "1,2,6,-3,4,5,6,7,8"
        for bad in (valid + ",0", valid.rsplit(",", 1)[0], valid + "\n", " " + valid,
                    valid.replace("-3", "-0"), valid.replace("-3", "+3"),
                    valid.replace("-3", "-129"), valid.replace("-3", "256"),
                    valid.replace("-3", "3.0"), valid.replace("-3", "0x01"),
                    "01" + valid[1:], "١" + valid[1:], valid.replace("1,2", "1e0,2"),
                    "9" * 100000, None, {}, 1):
            with self.subTest(bad=str(bad)[:70]):
                self.assertIsNone(mqtt_edge_projection(bad))
        for index, key in enumerate(MQTT_EDGE_FIELDS):
            invalid = (-129, 256) if key == "last_error" else (0, 14) if key == "reason_code" else (-1, U32 + 1)
            for bad in invalid:
                parts = valid.split(",")
                parts[index] = str(bad)
                self.assertIsNone(mqtt_edge_projection(",".join(parts)))

    def test_one_invalid_edge_discards_group_but_preserves_other_advisory(self):
        value = mqtt_value()
        value["edges"].append("must-not-escape")
        self.assertEqual({"free_heap": 60000}, advisory_projection(
            {"mqtt_connection": value, "free_heap": 60000}))

    def test_actual_status_parser_and_storage_never_authenticate_mqtt(self):
        doc = signed_document()
        with patch.object(main, "_configured_target_door_id", return_value="a" * 32), \
                patch.object(main, "ACCESS_EVENT_REF_KEYS", {"a1": KEY}):
            original = main._parse_authenticated_target_status(TARGET, json.dumps(doc).encode())
            self.assertIsNotNone(original)
            doc["mqtt_connection"] = mqtt_value()
            parsed = main._parse_authenticated_target_status(TARGET, json.dumps(doc).encode())
            self.assertEqual(mqtt_value(), parsed["advisory_diagnostics"]["mqtt_connection"])
            self.assertEqual({k: original[k] for k in CORE_FIELDS}, {k: parsed[k] for k in CORE_FIELDS})
            cur = MagicMock()
            cur.rowcount = 1
            record_verified_health(cur, parsed)
            sql, args = cur.execute.call_args_list[0].args
            self.assertIn("INSERT INTO target_health_history", sql)
            self.assertNotIn("mqtt_connection", json.loads(args[7]))
            self.assertEqual(mqtt_value(), json.loads(args[8])["mqtt_connection"])
            # A changed/invalid advisory neither changes the MAC nor rejects good signed state.
            doc["mqtt_connection"]["flapping"] = False
            changed = main._parse_authenticated_target_status(TARGET, json.dumps(doc).encode())
            self.assertEqual(parsed["integrity_tag"], changed["integrity_tag"])
            doc["mqtt_connection"]["edges"] = ["malformed"]
            malformed = main._parse_authenticated_target_status(TARGET, json.dumps(doc).encode())
            self.assertIsNotNone(malformed)
            self.assertNotIn("mqtt_connection", malformed.get("advisory_diagnostics", {}))
            doc["state"] = "ARMED"
            self.assertIsNone(main._parse_authenticated_target_status(TARGET, json.dumps(doc).encode()))

    def test_ingress_rejects_duplicate_nested_keys(self):
        doc = signed_document()
        doc["mqtt_connection"] = mqtt_value()
        wire = json.dumps(doc).replace('"schema": 1', '"schema": 1, "schema": 1')
        with patch.object(main, "_configured_target_door_id", return_value="a" * 32), \
                patch.object(main, "ACCESS_EVENT_REF_KEYS", {"a1": KEY}):
            self.assertIsNone(main._parse_authenticated_target_status(TARGET, wire.encode()))


class HealthSqliteCursor:
    """Execute the production INSERT predicate; adapt dialect and test time only.

    Real MariaDB coverage also exercises this predicate. Retention is covered by
    the existing reliability integration tests, not by this sampling fixture.
    """
    def __init__(self, connection):
        self.connection = connection
        self.now = 0
        self.rowcount = 0

    def execute(self, sql, args=None):
        if sql.startswith("DELETE FROM"):
            return
        for seconds in (30, 5):
            sql = sql.replace(f"UTC_TIMESTAMP(3) - INTERVAL {seconds} SECOND", str(self.now - seconds))
        sql = sql.replace("UTC_TIMESTAMP(3)", str(self.now))
        sql = sql.replace("FROM DUAL WHERE", "WHERE").replace("<=>", "IS").replace("%s", "?")
        self.rowcount = self.connection.execute(sql, args or ()).rowcount


class MqttHealthStorageTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.create_function("JSON_UNQUOTE", 1, lambda value: value)
        self.db.execute("""CREATE TABLE target_health_history (
            id INTEGER PRIMARY KEY, target_id TEXT, source_boot_id TEXT, source_boot_count INTEGER,
            status_revision INTEGER, gate_state TEXT, terminal_session_id TEXT, relay_commanded_on INTEGER,
            verified_json TEXT, advisory_json TEXT, received_at REAL)""")
        self.cur = HealthSqliteCursor(self.db)
        self.revision = 0

    def observe(self, now, sequence=1, *, mqtt_patch=None, legacy=False, commit=True, **core):
        self.revision += 1
        status = {**status_value(), "status_revision": self.revision, **core}
        if not legacy:
            mqtt = mqtt_value()
            mqtt.update(edge_sequence=sequence, edge_overwritten=max(0, sequence - 4),
                        edges=[f"{i},1000,6,-3,1000,63000,31000,60,0"
                               for i in range(max(1, sequence - 3), sequence + 1)])
            mqtt.update(mqtt_patch or {})
            status["advisory_diagnostics"] = {"mqtt_connection": mqtt}
        self.cur.now = now
        record_verified_health(self.cur, status)
        inserted = self.cur.rowcount > 0
        if commit:
            self.db.commit()
        return inserted

    def test_same_edge_repeats_keep_steady_30_second_sampling(self):
        self.assertTrue(self.observe(0))
        for now in (1, 5, 10, 29.999):
            self.assertFalse(self.observe(now))
        self.assertTrue(self.observe(30))
        self.assertFalse(self.observe(35))
        self.assertTrue(self.observe(60))

    def test_unique_edges_are_bounded_to_one_row_per_five_seconds(self):
        inserted_at = []
        for i in range(101):
            if self.observe(i / 10, sequence=i):
                inserted_at.append(i / 10)
        self.assertEqual([0, 5, 10], inserted_at)

    def test_suppressed_edge_retries_against_persisted_not_observed_checkpoint(self):
        self.assertTrue(self.observe(0, sequence=0))
        for now in (1, 2, 4.999):
            self.assertFalse(self.observe(now, sequence=1))
        self.assertTrue(self.observe(5, sequence=1))
        self.assertFalse(self.observe(5.001, sequence=1))
        self.assertFalse(self.observe(9.999, sequence=2))
        self.assertTrue(self.observe(10, sequence=2))

    def test_unsigned_counters_flapping_and_same_identity_contents_do_not_bypass(self):
        self.assertTrue(self.observe(0))
        for i in range(1, 300):
            counters = {key: i for key in MQTT_COUNTERS if key != "edge_sequence"}
            self.assertFalse(self.observe(i / 10, mqtt_patch={**counters, "flapping": bool(i % 2),
                "last_reason": "WIFI_LOST", "last_error": 0,
                "edges": [f"1,{i},8,0,0,0,0,0,0"]}))
        self.assertTrue(self.observe(30))

    def test_head_counter_without_matching_edge_and_invalid_group_cannot_bypass(self):
        self.assertTrue(self.observe(0, sequence=0))
        for patch_value in ({"edges": []}, {"edges": ["1,0,6,0,0,0,0,0,0"]},
                            {"edges": ["malformed"]}, {"edge_sequence": True}):
            self.assertFalse(self.observe(5, sequence=2, mqtt_patch=patch_value))
        self.assertTrue(self.observe(5, sequence=2))
        self.assertFalse(self.observe(10, sequence=1))

    def test_each_existing_signed_transition_bypasses_five_second_gate(self):
        for index, patch_value in enumerate(({"state": "ARMED"}, {"last_terminal_session_id": None},
                                            {"relay_commanded_on": True})):
            with self.subTest(core=patch_value):
                target = f"transition-{index}"
                self.assertTrue(self.observe(0, target_id=target))
                self.assertTrue(self.observe(1, target_id=target, **patch_value))
                self.assertFalse(self.observe(2, sequence=2, target_id=target, **patch_value))
                self.assertTrue(self.observe(6, sequence=2, target_id=target, **patch_value))

    def test_boot_change_is_immediate_and_resets_sequence_context(self):
        self.assertTrue(self.observe(0, sequence=100))
        boot = {"source_boot_id": "f" * 32, "source_boot_count": 783}
        self.assertTrue(self.observe(1, sequence=0, **boot))
        self.assertFalse(self.observe(2, sequence=1, **boot))
        self.assertTrue(self.observe(6, sequence=1, **boot))

    def test_targets_have_independent_persisted_gates(self):
        self.assertTrue(self.observe(0, target_id="first"))
        self.assertTrue(self.observe(1, target_id="second"))
        self.assertTrue(self.observe(5, sequence=2, target_id="first"))
        self.assertFalse(self.observe(5, sequence=2, target_id="second"))
        self.assertTrue(self.observe(6, sequence=2, target_id="second"))

    def test_rollback_does_not_advance_checkpoint(self):
        self.assertTrue(self.observe(0))
        self.assertTrue(self.observe(5, sequence=2, commit=False))
        self.db.rollback()
        self.assertTrue(self.observe(5, sequence=2))
        self.assertFalse(self.observe(6, sequence=2))

    def test_legacy_rows_keep_sampling_and_allow_later_valid_edges(self):
        self.assertTrue(self.observe(0, legacy=True))
        self.assertFalse(self.observe(5, legacy=True))
        self.assertTrue(self.observe(30, legacy=True))
        self.assertFalse(self.observe(31))
        self.assertTrue(self.observe(35))


class MqttHistoryTest(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.cur = self.db.return_value.cursor.return_value.__enter__.return_value
        self.cur.fetchall.return_value = []
        self.token = "x" * 43
        self.headers = {"Authorization": "Bearer " + self.token}
        app = FastAPI()
        app.include_router(create_diagnostics_read_router(self.db, hashlib.sha256(self.token.encode()).hexdigest()))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def get(self, query=""):
        return self.client.get("/api/v1/diagnostics/mqtt-history" + query, headers=self.headers)

    def test_same_capability_read_only_and_no_store(self):
        for headers in ({}, {"Authorization": "Bearer " + "z" * 43}, {"X-API-KEY": self.token}):
            response = self.client.get("/api/v1/diagnostics/mqtt-history", headers=headers)
            self.assertEqual(401, response.status_code)
            self.assertEqual("no-store", response.headers["cache-control"])
        for method in ("post", "put", "delete"):
            self.assertEqual(405, getattr(self.client, method)("/api/v1/diagnostics/mqtt-history", headers=self.headers).status_code)
        self.db.assert_not_called()
        app = FastAPI()
        app.include_router(create_diagnostics_read_router(self.db, ""))
        with TestClient(app) as client:
            self.assertEqual(503, client.get("/api/v1/diagnostics/mqtt-history", headers=self.headers).status_code)
        self.db.assert_not_called()

    def test_parameterized_health_pagination_receipt_filters_and_typed_edges(self):
        self.cur.fetchall.return_value = [health_row(7, mqtt_value()), health_row(6)]
        response = self.get("?limit=1&before_id=9007199254740995&target_id=test-target&boot_count=782"
                            "&since=2026-09-14T00:00:00%2B09:00&until=2026-09-15T00:00:00%2B09:00")
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("no-store", response.headers["cache-control"])
        page = response.json()
        self.assertEqual("7", page["next_before_id"])
        self.assertEqual("2026-09-13T15:00:00Z", page["since"])
        sql, args = self.cur.execute.call_args.args
        self.assertIn("FROM target_health_history", sql)
        self.assertIn("target_id=%s AND source_boot_count=%s AND id < %s ORDER BY id DESC LIMIT %s", sql)
        self.assertEqual((TARGET, 782, 9007199254740995, 2), args[2:])
        sample = page["history"][0]
        self.assertEqual(mqtt_value(), sample["mqtt_connection"])
        self.assertEqual("UNSIGNED", sample["integrity_status"])
        self.assertTrue(sample["flapping"])
        self.assertNotIn("verified", sample)
        self.assertNotIn("state", sample)
        edge = sample["edges"][1]
        self.assertEqual(-3, edge["last_error"])
        self.assertEqual("TRANSPORT_LOST", edge["reason"])
        self.assertEqual(dict(target_id=TARGET, source_boot_id=BOOT, source_boot_count="782", sequence=8), edge["identity"])
        self.assertEqual("UNSIGNED", edge["integrity_status"])
        self.assertEqual("NOT_OBSERVED", sample["broker_cause"])
        self.assertEqual("NOT_IMPLEMENTED", sample["edge_ack"])
        self.assertEqual(4, sample["edge_overwritten"])
        self.assertTrue(sample["missing_edges_possible"])
        self.assertEqual("NOT_CONFIGURED", page["broker_history"]["operation_status"])
        self.assertFalse(page["broker_history"]["source_available"])
        self.db.return_value.close.assert_called_once()
        self.assertTrue(all(call.args[0].startswith("SELECT ") for call in self.cur.execute.call_args_list))

    def test_empty_legacy_and_invalid_sources_stay_visible_without_false_healthy(self):
        page = self.get().json()
        self.assertEqual("SOURCE_UNAVAILABLE", page["source_status"])
        self.assertEqual([], page["history"])
        self.assertEqual("NOT_CONFIGURED", page["broker_history"]["operation_status"])
        invalid = mqtt_value()
        invalid["edges"] = ["must-not-escape"]
        self.cur.fetchall.return_value = [health_row(3), health_row(2, invalid), health_row(1)]
        page = self.get("?limit=2").json()
        self.assertEqual("2", page["next_before_id"])
        for row in page["history"]:
            self.assertEqual("SOURCE_UNAVAILABLE", row["source_status"])
            self.assertIsNone(row["flapping"])
            self.assertIsNone(row["edge_overwritten"])
            self.assertEqual([], row["edges"])
        self.assertNotIn("must-not-escape", json.dumps(page))

    def test_read_revalidates_storage_and_existing_health_keeps_wire(self):
        value = mqtt_value()
        value["secret"] = "must-not-escape"
        self.cur.fetchall.return_value = [health_row(3, value)]
        response = self.client.get("/api/v1/diagnostics/health-history", headers=self.headers)
        sample = response.json()["history"][0]
        self.assertEqual(mqtt_value(), sample["unsigned_advisory"]["mqtt_connection"])
        self.assertEqual("UNSIGNED_NOT_USED_FOR_CLASSIFICATION", sample["advisory_integrity"])
        self.assertNotIn("mqtt_connection", sample["verified"])
        self.assertNotIn("must-not-escape", self.get().text)

    def test_maximum_page_and_repeated_edge_identities_are_bounded(self):
        value = mqtt_value()
        value.update({key: U32 for key in MQTT_COUNTERS})
        value["edges"] = [f"{U32 - offset},{U32},12,-128,{U32},{U32},{U32},{U32},{U32}"
                          for offset in range(4)]
        self.cur.fetchall.return_value = [health_row(i, value) for i in range(101, 0, -1)]
        response = self.get("?limit=100")
        self.assertEqual(200, response.status_code)
        page = response.json()
        self.assertEqual(100, len(page["history"]))
        self.assertEqual("2", page["next_before_id"])
        self.assertEqual(400, sum(len(row["edges"]) for row in page["history"]))
        self.assertLess(len(response.content), 1024 * 1024)
        self.assertEqual(page["history"][0]["edges"][0]["identity"], page["history"][1]["edges"][0]["identity"])

    def test_registered_main_route_keeps_middleware_no_store(self):
        def routes(router):
            for route in router.routes:
                included = getattr(route, "original_router", None)
                if included is not None:
                    yield from routes(included)
                else:
                    yield route
        configured = create_diagnostics_read_router(self.db, hashlib.sha256(self.token.encode()).hexdigest())
        overrides = {dependency.dependency: configured.dependencies[0].dependency
                     for route in routes(main.app)
                     if getattr(route, "path", "") == "/api/v1/diagnostics/mqtt-history"
                     for dependency in route.dependencies}
        self.assertTrue(overrides)
        # No lifespan: no real MQTT/DB connections during this middleware test.
        client = TestClient(main.app)
        self.addCleanup(client.close)
        with patch.dict(main.app.dependency_overrides, overrides), patch.object(main, "get_db", self.db):
            for suffix, headers, expected in (("", self.headers, 200), ("", {}, 401),
                                              ("?limit=101", self.headers, 422)):
                response = client.get("/api/v1/diagnostics/mqtt-history" + suffix, headers=headers)
                self.assertEqual(expected, response.status_code)
                self.assertEqual("no-store", response.headers["cache-control"])

    def test_sequence_holes_wrap_duplicates_and_boot_identity(self):
        def row_for(sequences, head=8, boot=BOOT):
            value = mqtt_value()
            value.update(edge_sequence=head, edges=[f"{n},0,1,0,0,0,0,0,0" for n in sequences])
            return health_row(3, value, boot=boot)
        self.cur.fetchall.return_value = [row_for([7, 4])]
        sample = self.get().json()["history"][0]
        self.assertEqual([dict(first_sequence=5, last_sequence=6, count=2),
                          dict(first_sequence=8, last_sequence=8, count=1)], sample["sequence_gaps"])
        self.cur.fetchall.return_value = [row_for([U32, 0], head=0), row_for([0], head=0, boot="f" * 32)]
        samples = self.get().json()["history"]
        self.assertEqual([], samples[0]["sequence_gaps"])
        self.assertNotEqual(samples[0]["edges"][1]["identity"], samples[1]["edges"][0]["identity"])
        for sequences in ([8, 8], [9]):
            self.cur.fetchall.return_value = [row_for(sequences)]
            sample = self.get().json()["history"][0]
            self.assertEqual("SEQUENCE_ORDER_AMBIGUOUS", sample["sequence_coverage"])
            self.assertEqual([], sample["sequence_gaps"])
        self.cur.fetchall.return_value = [row_for([])]
        self.assertEqual("REPORTED_EDGES_UNAVAILABLE", self.get().json()["history"][0]["sequence_coverage"])

    def test_query_bounds_and_failure_redaction(self):
        for query in ("?limit=101", "?limit=0", "?before_id=0", "?boot_count=0", "?target_id=a%27",
                      "?since=2026-09-14T00:00:00", "?since=2026-01-01T00:00:00Z&until=2026-03-01T00:00:00Z",
                      "?since=2026-09-15T00:00:00Z&until=2026-09-14T00:00:00Z"):
            self.assertEqual(422, self.get(query).status_code, query)
        self.db.assert_not_called()
        self.cur.execute.side_effect = RuntimeError("secret db path")
        response = self.get()
        self.assertEqual(503, response.status_code)
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertNotIn("secret", response.text)
        self.db.return_value.close.assert_called_once()


class MqttCliTest(unittest.TestCase):
    def test_routing_token_and_health_filters(self):
        output = io.StringIO()
        with patch.object(cli, "load_token", return_value="x" * 43), \
                patch.object(cli, "fetch", return_value={"history": []}) as fetch, \
                contextlib.redirect_stdout(output):
            self.assertEqual(0, cli.main(["--mqtt-history", "--target-id", TARGET, "--boot-count", "782",
                "--before-id", "9007199254740995", "--limit", "100",
                "--since", "2026-09-14T00:00:00+09:00", "--until", "2026-09-15T00:00:00+09:00"]))
        url, token = fetch.call_args.args
        self.assertEqual("x" * 43, token)
        self.assertEqual("/api/v1/diagnostics/mqtt-history", urlsplit(url).path)
        self.assertEqual({"target_id": [TARGET], "boot_count": ["782"], "before_id": ["9007199254740995"],
            "limit": ["100"], "since": ["2026-09-14T00:00:00+09:00"],
            "until": ["2026-09-15T00:00:00+09:00"]}, parse_qs(urlsplit(url).query))
        self.assertNotIn(token, output.getvalue())

    def test_incompatible_filters_and_modes_fail_before_loading_token(self):
        for extra in (["--health-history"], ["--bundle-id", "1"], ["--check-token"], ["--init-token"],
                      ["--session-id", "anything"], ["--event-code", "anything"],
                      ["--mobile-ref", "mobile-diagnostic-credential_" + "a" * 24],
                      ["--evidence-received-until", "2026-09-15T00:00:00Z"]):
            with self.subTest(extra=extra), patch.object(cli, "load_token") as load, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.main(["--mqtt-history", *extra])
            load.assert_not_called()

    def test_mqtt_history_keeps_https_origin_guard(self):
        for origin in ("http://example.test", "https://user:secret@example.test", "https://example.test/path"):
            with self.assertRaises(ValueError):
                cli.history_endpoint(origin, "mqtt-history", 20, None)
