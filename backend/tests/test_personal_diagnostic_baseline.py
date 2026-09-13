"""Authenticated diagnostic ACK baselines: read-only, scoped, and N-1 safe."""

import hashlib
import json
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import main
from backend.app.acl_api import AclApiConfig, create_acl_router
from backend.app.mobile_diagnostics import (
    MobileDiagnosticBundle, TargetDiagnosticBaseline, ingest_bundle_payload,
)
from backend.tests.test_mobile_diagnostics import FakeService, bundle
from backend.tests.test_mobile_evidence_windows import Database


TENANT, DOOR, CREDENTIAL, TARGET = "a" * 32, "b" * 32, "1" * 32, "field-target"
ABSENT = dict(fresh=False, observed_epoch_ms=None, state=None, relay_commanded_on=None)
FRESH = dict(fresh=True, observed_epoch_ms=1_789_300_000_000, state="IDLE", relay_commanded_on=False)


class PersonalDiagnosticAckTest(unittest.TestCase):
    def client(self, baseline=None, store=None):
        self.store = store or Mock(side_effect=lambda tenant, credential, payload: {
            "accepted": True, "bundle_ref": payload["bundle_ref"], "deduplicated": False,
        })
        app = FastAPI()
        app.include_router(create_acl_router(FakeService(), AclApiConfig(
            enabled=True, enrollment_credentials={}, admin_key="unused", target_credentials={},
            personal_enabled=True, personal_api_key="mobile-key", personal_tenant_id=TENANT,
            personal_door_id=DOOR, personal_diagnostics_ingest=self.store,
            personal_diagnostics_baseline=baseline,
        )))
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def upload(self, client, *, key="mobile-key", **changes):
        request = dict(device_id="DEV-TEST-1234", credential_id=CREDENTIAL,
                       public_key_sec1="04" + "2" * 128, bundle=bundle())
        request.update(changes)
        return client.post("/api/v1/acl/personal/diagnostics", json=request,
                           headers={"X-API-KEY": key} if key else {})

    def test_n_minus_one_ack_is_exactly_unchanged_without_optional_callback(self):
        response = self.upload(self.client())
        self.assertEqual(200, response.status_code)
        self.assertEqual(dict(accepted=True, bundle_ref="a" * 32, deduplicated=False), response.json())

    def test_new_capture_and_duplicate_ack_add_only_a_closed_baseline_after_storage(self):
        calls = []
        def store(tenant, credential, payload):
            calls.append("store")
            return dict(accepted=True, bundle_ref=payload["bundle_ref"], deduplicated=calls.count("store") > 1)
        def baseline(tenant, credential):
            self.assertEqual((TENANT, CREDENTIAL), (tenant, credential))
            calls.append("baseline")
            return FRESH
        client = self.client(baseline, store)
        for duplicate in (False, True):
            response = self.upload(client)
            self.assertEqual(200, response.status_code)
            self.assertEqual(dict(accepted=True, bundle_ref="a" * 32, deduplicated=duplicate,
                                  target_baseline=FRESH), response.json())
        self.assertEqual(["store", "baseline", "store", "baseline"], calls)

    def test_missing_wrong_api_key_or_credential_proof_cannot_query_baseline(self):
        baseline = Mock(return_value=FRESH)
        client = self.client(baseline)
        for args in (dict(key=None), dict(key="wrong"), dict(credential_id="2" * 32),
                     dict(public_key_sec1="04" + "3" * 128)):
            with self.subTest(args=list(args)):
                self.assertIn(self.upload(client, **args).status_code, (401, 403))
        baseline.assert_not_called()
        self.store.assert_not_called()

    def test_uncommitted_or_mismatched_ack_never_returns_baseline(self):
        for result in (dict(accepted=False, bundle_ref="a" * 32),
                       dict(accepted=True, bundle_ref="b" * 32)):
            with self.subTest(result=result):
                baseline = Mock(return_value=FRESH)
                response = self.upload(self.client(baseline, Mock(return_value=result)))
                self.assertEqual(result, response.json())
                baseline.assert_not_called()
        baseline = Mock(return_value=FRESH)
        response = self.upload(self.client(baseline, Mock(side_effect=ValueError("storage unavailable"))))
        self.assertNotEqual(200, response.status_code)
        baseline.assert_not_called()

    def test_lookup_or_strict_projection_failure_does_not_undo_storage_ack(self):
        invalid = [dict(FRESH, fresh="true"), dict(FRESH, fresh=1), dict(FRESH, observed_epoch_ms=True),
                   dict(FRESH, observed_epoch_ms=-1), dict(FRESH, state="READY"),
                   dict(FRESH, relay_commanded_on=0), dict(FRESH, raw="never expose"),
                   dict(fresh=True)]
        for raw in invalid + [ABSENT, dict(FRESH, fresh=False)]:
            with self.subTest(raw=raw):
                response = self.upload(self.client(Mock(return_value=raw)))
                self.assertEqual(200, response.status_code)
                self.assertTrue(response.json()["accepted"])
                self.assertEqual(ABSENT, response.json()["target_baseline"])
        response = self.upload(self.client(Mock(side_effect=RuntimeError("private detail"))))
        self.assertEqual(ABSENT, response.json()["target_baseline"])
        self.assertNotIn("private detail", response.text)

    def test_baseline_state_enum_matches_authoritative_signed_status(self):
        self.assertEqual({"IDLE", "AUTH_PENDING", "ARMED", "RELAY_HOLD", "COOLDOWN"}, main._ACCESS_GATE_STATES)
        for state in main._ACCESS_GATE_STATES:
            self.assertEqual(state, TargetDiagnosticBaseline.model_validate(dict(FRESH, state=state)).state)
        for state in ("BOOTING", "RELAY_ON", "FAULT", "READY", "ready", 1):
            with self.assertRaises(ValidationError):
                TargetDiagnosticBaseline.model_validate(dict(FRESH, state=state))


class PersonalDiagnosticBaselineScopeTest(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.addCleanup(self.db.conn.close)
        self.db.conn.executescript("""
            CREATE TABLE credentials (tenant_id TEXT, credential_id TEXT, status TEXT, expires_at INTEGER);
            CREATE TABLE acl_tenants (tenant_id TEXT, status TEXT);
            CREATE TABLE credential_door_grants (
                tenant_id TEXT, credential_id TEXT, door_id TEXT, permissions INTEGER, revoked_at INTEGER);
        """)
        self.db.conn.execute("INSERT INTO credentials VALUES (?,?,?,NULL)", (TENANT, CREDENTIAL, "ACTIVE"))
        self.db.conn.execute("INSERT INTO acl_tenants VALUES (?,?)", (TENANT, "ACTIVE"))
        self.db.conn.execute("INSERT INTO credential_door_grants VALUES (?,?,?,1,NULL)", (TENANT, CREDENTIAL, DOOR))
        self.stack = self.enterContext(ExitStack())
        for key, value in dict(COMMAND_TARGET_ID=TARGET, ACL_PERSONAL_TENANT_ID=TENANT,
                               ACL_PERSONAL_DOOR_ID=DOOR).items():
            self.stack.enter_context(patch.object(main, key, value))
        self.stack.enter_context(patch.object(main, "_acl_target_credentials", {
            TARGET: dict(tenant_id=TENANT, door_id=DOOR)}, create=True))
        self.door = self.stack.enter_context(patch.object(main, "_configured_target_door_id", return_value=DOOR))
        self.get_db = self.stack.enter_context(patch.object(main, "get_db", return_value=self.db))
        self.registry = main._TargetGateStateRegistry()
        self.stack.enter_context(patch.object(main, "_target_gate_states", self.registry))
        self.wall = self.stack.enter_context(patch.object(main.time, "time", return_value=FRESH["observed_epoch_ms"] / 1000))
        self.monotonic = self.stack.enter_context(patch.object(main.time, "monotonic", return_value=100.0))

    def observe(self, **changes):
        status = dict(advanced=True, target_id=TARGET, source_boot_id="c" * 32, state="IDLE",
                      relay_commanded_on=False, integrity_tag="not-returned", integrity_key_id=7,
                      advisory_diagnostics={"state": "READY"}, _server_observed_epoch_ms=1)
        status.update(changes)
        return self.registry.note_verified(TARGET, status)

    def baseline(self, tenant=TENANT, credential=CREDENTIAL):
        return main._personal_diagnostic_target_baseline(tenant, credential)

    def test_only_server_observed_signed_state_is_returned_and_lookup_is_select_only(self):
        self.assertTrue(self.observe())
        self.assertEqual(FRESH, self.baseline())
        self.assertTrue(all(sql.startswith("SELECT ") for sql, args in self.db.calls))
        self.assertEqual(1, len(self.db.calls))
        self.assertEqual((TENANT, CREDENTIAL, int(self.wall.return_value), DOOR), self.db.calls[0][1])

    def test_no_observation_stale_clock_rollback_offline_or_incomplete_never_fresh(self):
        self.assertEqual(ABSENT, self.baseline())
        self.observe()
        self.monotonic.return_value += main.ACCESS_STATUS_MAX_AGE_SECONDS + 0.001
        self.assertEqual(ABSENT, self.baseline())
        self.monotonic.return_value = 99
        self.assertEqual(ABSENT, self.baseline())
        self.monotonic.return_value = 100
        self.wall.return_value -= 1
        self.assertEqual(ABSENT, self.baseline())
        self.wall.return_value += 1
        self.registry.clear_target(TARGET)
        self.assertEqual(ABSENT, self.baseline())
        for value in (None, "false", 0, 1):
            self.observe(relay_commanded_on=value)
            self.assertEqual(ABSENT, self.baseline())

    def test_nonadvanced_or_wrong_target_cannot_refresh_expired_baseline(self):
        self.observe()
        self.monotonic.return_value += main.ACCESS_STATUS_MAX_AGE_SECONDS + 1
        for changes in (dict(advanced=False), dict(target_id="other-target"),
                        dict(state="READY"), dict(source_boot_id="bad")):
            self.assertFalse(self.observe(**changes))
        self.assertEqual(ABSENT, self.baseline())

    def test_wrong_tenant_target_door_or_missing_config_never_queries_database(self):
        self.observe()
        self.assertEqual(ABSENT, self.baseline(tenant="d" * 32))
        self.door.return_value = "e" * 32
        self.assertEqual(ABSENT, self.baseline())
        self.door.return_value = DOOR
        with patch.object(main, "_acl_target_credentials", {}):
            self.assertEqual(ABSENT, self.baseline())
        self.get_db.assert_not_called()

    def test_inactive_expired_revoked_other_phone_or_no_grant_is_denied_read_only(self):
        self.observe()
        mutations = [
            ("UPDATE credentials SET status=?", ("PENDING",)),
            ("UPDATE credentials SET status=?", ("REVOKED",)),
            ("UPDATE credentials SET expires_at=?", (int(self.wall.return_value),)),
            ("UPDATE acl_tenants SET status=?", ("DISABLED",)),
            ("UPDATE credential_door_grants SET permissions=?", (0,)),
            ("UPDATE credential_door_grants SET revoked_at=?", (1,)),
            ("UPDATE credential_door_grants SET door_id=?", ("e" * 32,)),
        ]
        self.db.conn.commit()
        with patch.object(self.registry, "live_evidence", wraps=self.registry.live_evidence) as live:
            self.assertEqual(ABSENT, self.baseline(credential="f" * 32))
            for sql, args in mutations:
                with self.subTest(sql=sql, args=args):
                    self.db.conn.execute(sql, args)
                    self.assertEqual(ABSENT, self.baseline())
                    self.db.conn.rollback()
            live.assert_not_called()
        self.assertTrue(all(sql.startswith("SELECT ") for sql, args in self.db.calls))

    def test_database_failure_returns_no_baseline_without_refresh_or_command(self):
        self.get_db.side_effect = RuntimeError("private connection detail")
        with patch.object(self.registry, "live_evidence") as live:
            self.assertEqual(ABSENT, self.baseline())
            live.assert_not_called()


class LegacyCanonicalBundleTest(unittest.TestCase):
    @staticmethod
    def legacy():
        value = bundle()
        value["native"]["scan"] = dict(observation="NO_RECENT_PACKET", last_packet_at_epoch_ms=1,
                                         lifecycle=[dict(event="REGISTER_ACCEPTED", at_epoch_ms=2)])
        value["native"]["runtime"] = dict(captured_epoch_ms=100, captured_elapsed_ms=50,
            process_ref="b" * 16, pending_uploads=1, dropped_events=0,
            lifecycle=[dict(event="PROCESS_STARTED", at_epoch_ms=50, elapsed_ms=0)])
        return value

    def test_n_minus_one_optional_defaults_and_immutable_hash_are_preserved(self):
        normalized = ingest_bundle_payload(MobileDiagnosticBundle.model_validate(self.legacy()))
        self.assertEqual({"observation", "last_packet_at_epoch_ms", "lifecycle"}, set(normalized["native"]["scan"]))
        runtime = normalized["native"]["runtime"]
        self.assertEqual({"captured_epoch_ms", "captured_elapsed_ms", "process_ref", "pending_uploads",
            "oldest_pending_epoch_ms", "last_upload_success_epoch_ms", "last_upload_code", "dropped_events",
            "lifecycle", "background_restricted", "battery_optimization_exempt", "device_idle", "app_standby_bucket",
            "previous_exit_reason", "previous_exit_epoch_ms", "last_start_was_force_stopped"}, set(runtime))
        self.assertNotIn("sequence", runtime["lifecycle"][0])
        self.assertNotIn("incident_ref", runtime["lifecycle"][0])
        self.assertIsNone(runtime["lifecycle"][0]["reason"])
        self.assertIsNone(normalized["native"]["scan"]["lifecycle"][0]["error_code"])
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        # Frozen output of the schema17 ingester for legacy(), before extension.
        self.assertEqual("269732973aac6f733aa17c4a367cb11abfc796254589bb0928cb83d04f347688", digest)

    def test_absent_and_explicit_null_extensions_remain_distinct(self):
        value = self.legacy()
        value["native"]["scan"]["callback_count"] = None
        value["native"]["runtime"]["pending_events"] = None
        value["native"]["runtime"]["lifecycle"][0].update(sequence=0, incident_ref=None)
        normalized = ingest_bundle_payload(MobileDiagnosticBundle.model_validate(value))
        self.assertIn("callback_count", normalized["native"]["scan"])
        self.assertIn("pending_events", normalized["native"]["runtime"])
        self.assertEqual(0, normalized["native"]["runtime"]["lifecycle"][0]["sequence"])
        self.assertIn("incident_ref", normalized["native"]["runtime"]["lifecycle"][0])
        minimal = ingest_bundle_payload(MobileDiagnosticBundle.model_validate(bundle()))
        self.assertNotIn("scan", minimal["native"])
        self.assertIn("runtime", minimal["native"])
        self.assertIsNone(minimal["native"]["runtime"])
