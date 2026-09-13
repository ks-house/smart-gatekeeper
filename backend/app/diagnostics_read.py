"""Optional, read-only diagnostic capability. Never an administrator credential."""

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

try:
    from .mobile_diagnostics import MobileDiagnosticBundle, bundle_evidence_metadata
    from .ops_runtime import SlidingWindowRateLimiter
    from .reliability_diagnostics import CORE_FIELDS, advisory_projection, classify_incident, sensor_mac_input
except ImportError:
    from mobile_diagnostics import MobileDiagnosticBundle, bundle_evidence_metadata
    from ops_runtime import SlidingWindowRateLimiter
    from reliability_diagnostics import CORE_FIELDS, advisory_projection, classify_incident, sensor_mac_input


def _event_window(since: Optional[str], until: Optional[str]):
    def parse(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc)

    try:
        end = parse(until) if until is not None else datetime.now(timezone.utc)
        start = parse(since) if since is not None else end - timedelta(hours=24)
        if (start.year < 1970 or end.year > 9998 or start >= end
                or end - start > timedelta(days=31)):
            raise ValueError("invalid window")
        return start, end
    except (ValueError, OverflowError):
        raise HTTPException(422, "use timezone-aware since/until with a positive window of at most 31 days",
                            headers={"Cache-Control": "no-store"}) from None


def _utc_text(value: datetime) -> str:
    # Database DATETIME values are stored as UTC without tzinfo.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


MOBILE_REF_PATTERN = r"^mobile-diagnostic-credential_[0-9a-f]{24}$"


def _incident_windows(since, until, occurred_since, occurred_until, evidence_received_until):
    """Receipt defaults are unchanged; occurrence filtering is explicit opt-in."""
    if (occurred_since is None) != (occurred_until is None):
        raise HTTPException(422, "occurred_since and occurred_until must be supplied together",
                            headers={"Cache-Control": "no-store"})
    occurrence = _event_window(occurred_since, occurred_until) if occurred_since is not None else None
    # Without explicit receipt bounds, a new occurrence query uses that same
    # bounded window for Target receipt evidence. Target has no trusted wall clock.
    receipt = occurrence if occurrence and since is None and until is None else _event_window(since, until)
    occurrence = occurrence or receipt
    evidence_end = receipt[1]
    if evidence_received_until is not None:
        _, evidence_end = _event_window(_utc_text(min(receipt[0], occurrence[0])), evidence_received_until)
        if evidence_end < occurrence[1] or evidence_end < receipt[1]:
            raise HTTPException(422, "evidence_received_until must not precede the window end",
                                headers={"Cache-Control": "no-store"})
    return receipt, occurrence, evidence_end


def _mobile_where(evidence_end, mobile_ref, before_id, occurrence=None):
    where, args = ["received_at < %s"], [evidence_end.replace(tzinfo=None)]
    if mobile_ref is not None:
        where.append("credential_ref=%s")
        args.append(mobile_ref)
    if before_id is not None:
        where.append("id < %s")
        args.append(before_id)
    if occurrence is not None:
        start_ms, end_ms = (int(value.timestamp() * 1000) for value in occurrence)
        # Rows written before migration018 (or unindexable clocks) stay visible
        # through the independent cursor. NULL does not mean no evidence.
        where.append("(evidence_index_version IS NULL OR "
                     "(event_first_epoch_ms < %s AND event_last_epoch_ms >= %s) OR "
                     "(captured_epoch_ms >= %s AND captured_epoch_ms < %s))")
        args.extend((end_ms, start_ms, start_ms, end_ms))
    return where, args


def create_diagnostics_read_router(get_db: Callable, token_sha256: str) -> APIRouter:
    """Read-only reports and verified access history; never command authority."""
    digest = token_sha256 if re.fullmatch(r"[0-9a-f]{64}", token_sha256) else None
    limiter = SlidingWindowRateLimiter(limit=60, window_seconds=60, max_keys=1024)

    def authorize(request: Request, response: Response):
        headers = {"Cache-Control": "no-store"}
        if digest is None:
            raise HTTPException(503, "diagnostic read is not configured", headers=headers)
        # Ignore forwarded caller IDs and never retain a supplied credential as a key.
        allowed, retry = limiter.allow(request.client.host if request.client else "unknown")
        if not allowed:
            raise HTTPException(429, "diagnostic read rate limit", headers={
                **headers, "Retry-After": str(retry),
            })
        value = request.headers.get("Authorization", "")
        token = value[7:] if value.startswith("Bearer ") else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token) or not secrets.compare_digest(
            hashlib.sha256(token.encode("ascii")).hexdigest(), digest
        ):
            raise HTTPException(401, "diagnostic read credential required", headers=headers)
        response.headers["Cache-Control"] = "no-store"

    router = APIRouter(prefix="/api/v1/diagnostics", dependencies=[Depends(authorize)])

    def json_object(value):
        if isinstance(value, str):
            if len(value.encode("utf-8")) > 65536:
                raise ValueError("oversized diagnostic object")
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("invalid diagnostic object")
        return value

    def health_row(row):
        core = json_object(row["verified_json"])
        if set(core) != set(CORE_FIELDS):
            raise ValueError("invalid stored health schema")
        # Integers can exceed Javascript precision; booleans remain booleans.
        core = {key: str(value) if type(value) is int and key not in
                ("relay_pin_level", "last_terminal_phase_mask") else value for key, value in core.items()}
        return dict(id=str(row["id"]), received_at=_utc_text(row["received_at"]),
                    integrity_status="verified", verified=core,
                    # Legacy controller extras were never part of the status MAC.
                    unsigned_advisory=advisory_projection(json_object(row["advisory_json"]),
                                                         include_boot=True, expected=core) if row.get("advisory_json") else None,
                    advisory_available=row.get("advisory_json") is not None,
                    advisory_integrity="UNSIGNED_NOT_USED_FOR_CLASSIFICATION")

    @router.get("/health-history")
    def health_history(
        since: Optional[str] = Query(None, max_length=64),
        until: Optional[str] = Query(None, max_length=64),
        target_id: Optional[str] = Query(None, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
        boot_count: Optional[int] = Query(None, ge=1, le=18446744073709551615),
        limit: int = Query(100, ge=1, le=100),
        before_id: Optional[int] = Query(None, ge=1, le=18446744073709551615),
    ):
        start, end = _event_window(since, until)
        args = [start.replace(tzinfo=None), end.replace(tzinfo=None)]
        where = ["received_at >= %s", "received_at < %s"]
        for column, value in (("target_id", target_id), ("source_boot_count", boot_count), ("id", before_id)):
            if value is not None:
                where.append(column + (" < %s" if column == "id" else "=%s"))
                args.append(value)
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("SELECT id,verified_json,advisory_json,received_at FROM target_health_history WHERE "
                            + " AND ".join(where) + " ORDER BY id DESC LIMIT %s", (*args, limit + 1))
                rows = cur.fetchall()
            result = [health_row(row) for row in rows[:limit]]
            return dict(history=result, next_before_id=result[-1]["id"] if len(rows) > limit else None,
                        since=_utc_text(start), until=_utc_text(end), time_basis="received_at",
                        retention_days=31, steady_sample_seconds=30, edge_samples=True,
                        historical_coverage="SINCE_FEATURE_INSTALL_ONLY")
        except Exception:
            raise HTTPException(503, "health history unavailable", headers={"Cache-Control": "no-store"}) from None
        finally:
            if conn is not None:
                conn.close()

    @router.get("/incidents")
    def incidents(
        since: Optional[str] = Query(None, max_length=64),
        until: Optional[str] = Query(None, max_length=64),
        target_id: Optional[str] = Query(None, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
        session_id: Optional[str] = Query(None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
        limit: int = Query(20, ge=1, le=100),
        before_id: Optional[int] = Query(None, ge=1, le=18446744073709551615),
        occurred_since: Optional[str] = Query(None, max_length=64),
        occurred_until: Optional[str] = Query(None, max_length=64),
        evidence_received_until: Optional[str] = Query(None, max_length=64),
        mobile_ref: Optional[str] = Query(None, pattern=MOBILE_REF_PATTERN),
        mobile_limit: int = Query(20, ge=1, le=100),
        mobile_before_id: Optional[int] = Query(None, ge=1, le=18446744073709551615),
    ):
        (start, end), occurrence, evidence_end = _incident_windows(
            since, until, occurred_since, occurred_until, evidence_received_until)
        late_query = occurred_since is not None or evidence_received_until is not None
        since_db, until_db = start.replace(tzinfo=None), end.replace(tzinfo=None)
        where = ["integrity_status='verified'", "received_at >= %s", "received_at < %s"]
        args = [since_db, until_db]
        for column, value in (("collector_target_id", target_id), ("session_id", session_id)):
            if value is not None:
                where.append(column + "=%s")
                args.append(value)
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                having = " HAVING MAX(id) < %s" if before_id is not None else ""
                group_args = [*args, *([before_id] if before_id is not None else []), limit + 1]
                cur.execute("SELECT collector_target_id,source_boot_id,session_id,MAX(id) AS latest_id "
                            "FROM access_event_history WHERE " + " AND ".join(where)
                            + " GROUP BY collector_target_id,source_boot_id,session_id" + having
                            + " ORDER BY latest_id DESC LIMIT %s", tuple(group_args))
                groups = cur.fetchall()
                selected = groups[:limit]
                event_rows, summaries = [], []
                if selected:
                    positions = ",".join(["(%s,%s,%s)"] * len(selected))
                    keys = tuple(value for group in selected for value in
                                 (group["collector_target_id"], group["source_boot_id"], group["session_id"]))
                    cur.execute("SELECT id,collector_target_id,source_boot_id,source_boot_count,session_id,"
                                "event_code,event_path,event_outcome,reason_code,monotonic_ms,source_sequence,credential_ref,received_at "
                                "FROM access_event_history WHERE integrity_status='verified' AND "
                                "(collector_target_id,source_boot_id,session_id) IN (" + positions + ") "
                                "AND received_at >= %s AND received_at < %s ORDER BY id ASC LIMIT 5001",
                                (*keys, since_db, until_db))
                    event_rows = cur.fetchall()
                summary_where = ["received_at >= %s", "received_at < %s"]
                summary_args = [since_db, until_db]
                for column, value in (("target_id", target_id), ("session_id", session_id)):
                    if value is not None:
                        summary_where.append(column + "=%s")
                        summary_args.append(value)
                cur.execute("SELECT id,target_id,source_boot_id,session_id,summary_json,received_at "
                            "FROM target_sensor_session_history WHERE " + " AND ".join(summary_where)
                            + " ORDER BY id DESC LIMIT 101", tuple(summary_args))
                summaries = cur.fetchall()
                mobile_where, mobile_args = _mobile_where(
                    evidence_end, mobile_ref, mobile_before_id, occurrence if late_query else None)
                cur.execute("SELECT id,credential_ref,created_at_ms,payload_json,received_at "
                            "FROM mobile_diagnostic_bundles WHERE " + " AND ".join(mobile_where)
                            + " ORDER BY id DESC LIMIT %s", (*mobile_args, mobile_limit + 1))
                mobiles = cur.fetchall()
                cur.execute("SELECT id,verified_json,advisory_json,received_at FROM target_health_history "
                            "WHERE received_at >= %s AND received_at < %s"
                            + (" AND target_id=%s" if target_id else "") + " ORDER BY id DESC LIMIT 101",
                            (since_db, until_db, *([target_id] if target_id else [])))
                health = cur.fetchall()
            reports = []
            matches = {}
            manual_contexts = {}
            mobile_incidents = {}
            start_ms, end_ms = (int(value.timestamp() * 1000) for value in occurrence)
            as_of_ms = int(evidence_end.timestamp() * 1000)
            for row in mobiles[:mobile_limit]:
                if not isinstance(row["credential_ref"], str) or re.fullmatch(
                        r"mobile-diagnostic-credential_[0-9a-f]{24}", row["credential_ref"]) is None:
                    raise ValueError("invalid mobile reference")
                body = MobileDiagnosticBundle.model_validate(json_object(row["payload_json"])).model_dump(
                    by_alias=True, mode="json", exclude_unset=True)
                captured = row["created_at_ms"]
                runtime = body["native"].get("runtime")
                if runtime:
                    captured = runtime["captured_epoch_ms"]
                age = end_ms - int(captured)
                metadata = bundle_evidence_metadata(body, int(row["created_at_ms"]), row["received_at"], as_of_ms=as_of_ms)
                current = metadata["freshness"] == "RECENT_REPORT"
                valid_sessions = [s for s in body["sessions"] if
                                  start_ms <= (s.get("updated_epoch_ms") or s.get("created_epoch_ms") or -1) < end_ms]
                for session in valid_sessions:
                    if session.get("target_session_id"):
                        matches.setdefault(session["target_session_id"], []).append(str(row["id"]))
                lifecycle = [item for item in (runtime or {}).get("lifecycle", [])
                             if start_ms <= item["at_epoch_ms"] < end_ms]
                manual_contexts[str(row["id"])] = [item["at_epoch_ms"] for item in lifecycle
                                                    if item["event"] == "MANUAL_OPEN_CONTEXT"]
                wakes = [item for item in body["wake_events"] if
                         start_ms <= (item.get("received_epoch_ms") if item.get("received_epoch_ms") is not None else -1) < end_ms]
                scan_lifecycle = [item for item in (body["native"].get("scan") or {}).get("lifecycle", [])
                                  if start_ms <= item["at_epoch_ms"] < end_ms]
                for item in lifecycle:
                    if item["event"] not in ("DISPATCH_SKIPPED", "ENQUEUE_FAILED", "WORKER_STOPPED", "ORPHAN_RECOVERED",
                                             "MANUAL_OPEN_CONTEXT", "AUTH_FINAL_FAILURE", "SCAN_RECOVERY_FAILED", "INCIDENT_CAPTURE"):
                        continue
                    identity = json.dumps([row["credential_ref"], (runtime or {}).get("process_ref"), item],
                                          separators=(",", ":"), sort_keys=True)
                    key = hashlib.sha256(identity.encode()).hexdigest()[:32]
                    mobile_incidents.setdefault(key, dict(incident_ref=key, report_id=str(row["id"]),
                        mobile_ref=row["credential_ref"], source="mobile_runtime", event=item,
                        classification="MANUAL_OPEN_CONTEXT" if item["event"] == "MANUAL_OPEN_CONTEXT" else "DISPATCH_DECISION_OBSERVED",
                        target_correlation="NOT_REQUIRED", automatic_failure_inferred=False,
                        physical_door="NOT_OBSERVABLE", arrival="NOT_OBSERVABLE"))
                for item in valid_sessions:
                    if item.get("state") not in ("FAILED", "CANCELLED", "PROOF_UNCERTAIN"):
                        continue
                    identity = json.dumps([row["credential_ref"], item.get("event_ref"), item.get("updated_epoch_ms")],
                                          separators=(",", ":"))
                    key = hashlib.sha256(identity.encode()).hexdigest()[:32]
                    mobile_incidents.setdefault(key, dict(incident_ref=key, report_id=str(row["id"]),
                        mobile_ref=row["credential_ref"], source="mobile_session", session=item,
                        classification="MOBILE_FAILURE_OBSERVED", target_correlation="SESSION_ID" if item.get("target_session_id") else "NOT_OBSERVED",
                        physical_door="NOT_OBSERVABLE", arrival="NOT_OBSERVABLE"))
                evidence_count = len(valid_sessions) + len(lifecycle) + len(wakes) + len(scan_lifecycle)
                reports.append(dict(id=str(row["id"]), mobile_ref=row["credential_ref"], app=body["app"],
                                    **metadata, age_at_window_end_ms=age,
                                    sessions_in_window=valid_sessions[:20], runtime_lifecycle_in_window=lifecycle[-32:],
                                    wake_events_in_window=wakes[:20], scan_lifecycle_in_window=scan_lifecycle,
                                    evidence_count_in_window=evidence_count,
                                    evidence_status="EVENTS_OBSERVED" if evidence_count else "NO_EVENTS_IN_WINDOW",
                                    detail_truncated=len(valid_sessions) > 20 or len(lifecycle) > 32 or len(wakes) > 20,
                                    detail_bundle_id=str(row["id"]), incident_ref=(runtime or {}).get("incident_ref"),
                                    explicit_runtime_reasons=sorted({item["reason"] for item in lifecycle if item.get("reason")}),
                                    scan=body["native"].get("scan") if current else None,
                                    scan_snapshot=body["native"].get("scan"),
                                    scan_is_historical=not current,
                                    silence_classification="NO_ARRIVAL_OR_WAKE_INFERENCE"))
            result = []
            sensor_observations = []
            for row in summaries[:100]:
                sensor = json_object(row["summary_json"])
                sensor_mac_input(sensor, "a1", row["target_id"])
                sensor_observations.append(dict(id=str(row["id"]), target_id=row["target_id"],
                    source_boot_id=row["source_boot_id"], session_id=row["session_id"],
                    received_at=_utc_text(row["received_at"]), integrity_status="verified", summary=sensor))
            for group in selected:
                rows = [e for e in event_rows[:5000] if
                        (e["collector_target_id"], e["source_boot_id"], e["session_id"]) ==
                        (group["collector_target_id"], group["source_boot_id"], group["session_id"])]
                rows.sort(key=lambda e: int(e["source_sequence"]))
                sensor = next((json_object(s["summary_json"]) for s in summaries[:100] if
                               (s["target_id"], s["source_boot_id"], s["session_id"]) ==
                               (group["collector_target_id"], group["source_boot_id"], group["session_id"])), None)
                if sensor is not None:
                    sensor_mac_input(sensor, "a1", group["collector_target_id"])  # Strict stored projection.
                decision = classify_incident(rows, sensor)
                manual_context = any(e["event_code"] == "ACCESS_SIGNED_MANUAL_COMPLETED" for e in rows)
                # Time proximity provides context only. It never maps a family
                # member's completion to a different phone or implies a failure.
                manual_times = [int(e["received_at"].replace(tzinfo=timezone.utc).timestamp() * 1000)
                                for e in rows if e["event_code"] == "ACCESS_SIGNED_MANUAL_COMPLETED"]
                manual_candidates = [r["id"] for r in reports if any(
                    receipt_ms - 600000 <= at <= receipt_ms + 120000
                    for at in manual_contexts[r["id"]] for receipt_ms in manual_times)]
                missing_status = ("REPORTS_PENDING_PAGINATION" if len(mobiles) > mobile_limit else
                                  "NO_MATCH_ON_THIS_PAGE" if mobile_before_id is not None else
                                  "MANUAL_CONTEXT_NOT_OBSERVED" if reports else "DIAGNOSTIC_EVIDENCE_NOT_RECEIVED")
                result.append(dict(id=str(group["latest_id"]), target_id=group["collector_target_id"],
                                   source_boot_id=group["source_boot_id"], session_id=group["session_id"],
                                   event_count=len(rows), event_codes=[e["event_code"] for e in rows],
                                   first_received_at=_utc_text(min(e["received_at"] for e in rows)) if rows else None,
                                   last_received_at=_utc_text(max(e["received_at"] for e in rows)) if rows else None,
                                   sensor_summary=sensor, sensor_integrity="verified" if sensor else "NOT_OBSERVED",
                                   sensor_span_ms=(int(sensor["ended_monotonic_ms"])-int(sensor["started_monotonic_ms"])) & 0xffffffff if sensor else None,
                                   mobile_report_matches=list(dict.fromkeys(matches.get(group["session_id"], []))),
                                   manual_context_report_candidates=manual_candidates,
                                   manual_context_correlation="NEAR_RECEIPT_ONLY_OWNER_UNRESOLVED" if manual_candidates else "NOT_OBSERVED",
                                   mobile_evidence_status=missing_status if manual_context and not manual_candidates else "SEE_MOBILE_OBSERVATIONS",
                                   automatic_failure_inferred=False,
                                   time_basis="BACKEND_RECEIPT_WITH_BOOT_SEQUENCE_NO_TRUSTED_OCCURRENCE", **decision))
            health_result = [health_row(row) for row in health[:100]]
            targets = []
            for name in sorted({row["verified"]["target_id"] for row in health_result}):
                samples = [row for row in health_result if row["verified"]["target_id"] == name]
                newest = samples[0]
                newest_time = datetime.fromisoformat(newest["received_at"].replace("Z", "+00:00"))
                age = int((end - newest_time).total_seconds() * 1000)
                times = sorted(datetime.fromisoformat(row["received_at"].replace("Z", "+00:00")) for row in samples)
                gaps = [dict(since=_utc_text(a), until=_utc_text(b), duration_ms=int((b-a).total_seconds()*1000))
                        for a, b in zip(times, times[1:]) if (b-a).total_seconds() > 90]
                targets.append(dict(target_id=name, last_received_at=newest["received_at"],
                                    age_at_window_end_ms=age,
                                    freshness="RECENT_SIGNED_SAMPLE" if 0 <= age <= 90000 else "STALE_SIGNED_SAMPLE",
                                    boot_counts=sorted({row["verified"]["source_boot_count"] for row in samples}, key=int),
                                    observed_gaps=gaps, outage_cause="NOT_DETERMINED"))
            evidence_gaps = [dict(source="manual_context", target_id=item["target_id"], session_id=item["session_id"],
                                 mobile_ref=mobile_ref, classification=item["mobile_evidence_status"],
                                 automatic_failure_inferred=False, evidence_scope="THIS_QUERY_PAGE")
                             for item in result if item["mobile_evidence_status"] != "SEE_MOBILE_OBSERVATIONS"]
            if not reports:
                evidence_gaps.append(dict(source="mobile", mobile_ref=mobile_ref,
                    classification="NO_REPORTS_ON_THIS_PAGE" if mobile_before_id is not None else "DIAGNOSTIC_EVIDENCE_NOT_RECEIVED",
                    automatic_failure_inferred=False, evidence_scope="THIS_QUERY_PAGE"))
            return dict(incidents=result, mobile_incidents=list(mobile_incidents.values())[:100],
                        evidence_gaps=evidence_gaps,
                        mobile_observations=reports, target_observations=targets,
                        sensor_observations=sensor_observations,
                        health_history=health_result,
                        next_before_id=str(result[-1]["id"]) if len(groups) > limit else None,
                        next_mobile_before_id=str(mobiles[mobile_limit-1]["id"]) if len(mobiles) > mobile_limit else None,
                        mobile_ref=mobile_ref,
                        since=_utc_text(start), until=_utc_text(end), time_basis="backend_received_at",
                        occurred_since=_utc_text(occurrence[0]), occurred_until=_utc_text(occurrence[1]),
                        evidence_received_until=_utc_text(evidence_end), mobile_time_basis="PHONE_WALL_CLOCK_UNVERIFIED",
                        mobile_query_mode="OCCURRENCE_WITH_LATE_EVIDENCE" if late_query else "LEGACY_RECEIPT_CUTOFF",
                        mobile_evidence_status="REPORTS_OBSERVED" if reports else
                            "NO_REPORTS_ON_THIS_PAGE" if mobile_before_id is not None else "DIAGNOSTIC_EVIDENCE_NOT_RECEIVED",
                        source_order="boot_sequence", snapshot_atomic=False,
                        coverage=dict(events_truncated=len(event_rows) > 5000,
                                      mobile_reports_truncated=len(mobiles) > mobile_limit,
                                      mobile_pagination_independent=True, legacy_event_index="UNKNOWN_ROWS_INCLUDED",
                                      mobile_incidents_truncated=len(mobile_incidents) > 100,
                                      sensor_summaries_truncated=len(summaries) > 100,
                                      health_truncated=len(health) > 100,
                                      absence_is_not_success=True, arrival_observer_available=False,
                                      physical_door_observer_available=False))
        except Exception:
            raise HTTPException(503, "incident evidence unavailable", headers={"Cache-Control": "no-store"}) from None
        finally:
            if conn is not None:
                conn.close()

    @router.get("/audit-conflicts")
    def list_audit_conflicts(
        since: Optional[str] = Query(None, max_length=64),
        until: Optional[str] = Query(None, max_length=64),
        limit: int = Query(100, ge=1, le=100),
        before_id: Optional[int] = Query(None, ge=1, le=18446744073709551615),
        target_id: Optional[str] = Query(None, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
        session_id: Optional[str] = Query(None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
        boot_count: Optional[int] = Query(None, ge=1, le=18446744073709551615),
        event_code: Optional[str] = Query(None, pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
    ):
        start, end = _event_window(since, until)
        clauses = ["received_at >= %s", "received_at < %s"]
        args = [start.replace(tzinfo=None), end.replace(tzinfo=None)]
        for column, value in (("target_id", target_id), ("session_id", session_id),
                              ("source_boot_count", boot_count), ("event_code", event_code)):
            if value is not None:
                clauses.append(column + "=%s")
                args.append(value)
        if before_id is not None:
            clauses.append("id < %s")
            args.append(before_id)
        columns = ("id,target_id,event_id,source_boot_id,source_boot_count,"
                   "source_sequence,session_id,event_code,reason_code,received_at")
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("SELECT " + columns + " FROM access_event_conflicts WHERE "
                            + " AND ".join(clauses) + " ORDER BY id DESC LIMIT %s",
                            (*args, limit + 1))
                rows = cur.fetchall()
            conflicts = []
            for row in rows[:limit]:
                # Custody metadata only: never expose raw envelope/MAC/key material.
                item = {key: row[key] for key in columns.split(",")}
                for key in ("id", "source_boot_count", "source_sequence"):
                    item[key] = str(item[key])
                item["received_at"] = _utc_text(item["received_at"])
                item["disposition"] = "QUARANTINED"
                conflicts.append(item)
            return {"conflicts": conflicts,
                    "next_before_id": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
                    "time_basis": "server_received_at",
                    "access_success_confirmed": False}
        except Exception:
            raise HTTPException(503, "audit conflict evidence unavailable",
                                headers={"Cache-Control": "no-store"}) from None
        finally:
            if conn is not None:
                conn.close()

    @router.get("/access-events")
    def list_access_events(
        since: Optional[str] = Query(None, max_length=64),
        until: Optional[str] = Query(None, max_length=64),
        limit: int = Query(100, ge=1, le=100),
        before_id: Optional[int] = Query(None, ge=1, le=18446744073709551615),
        target_id: Optional[str] = Query(None, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
        session_id: Optional[str] = Query(None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
        boot_count: Optional[int] = Query(None, ge=1, le=18446744073709551615),
        event_code: Optional[str] = Query(None, pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
    ):
        start, end = _event_window(since, until)
        clauses = ["integrity_status='verified'", "received_at >= %s", "received_at < %s"]
        args = [start.replace(tzinfo=None), end.replace(tzinfo=None)]
        # Column names are constants, never caller-provided SQL.
        for column, value in (("collector_target_id", target_id), ("session_id", session_id),
                              ("source_boot_count", boot_count), ("event_code", event_code)):
            if value is not None:
                clauses.append(column + "=%s")
                args.append(value)
        if before_id is not None:
            clauses.append("id < %s")
            args.append(before_id)
        columns = (
            "id,event_id,session_id,source_boot_id,source_boot_count,source_sequence,"
            "event_attempt,event_code,event_stage,event_outcome,reason_code,event_path,"
            "event_transport,distance_mm,duration_ms,relay_hold_ms,monotonic_ms,clock_quality,"
            "collector_target_id,credential_ref,integrity_status,received_at"
        )
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("SELECT " + columns + " FROM access_event_history WHERE "
                            + " AND ".join(clauses) + " ORDER BY id DESC LIMIT %s",
                            (*args, limit + 1))
                rows = cur.fetchall()
            events = []
            for row in rows[:limit]:
                # Explicit projection: no identity names, raw payloads or MAC/key material.
                event = {key: row[key] for key in columns.split(",")}
                for key in ("id", "source_boot_count", "source_sequence", "monotonic_ms"):
                    if event[key] is not None:
                        event[key] = str(event[key])
                event["received_at"] = _utc_text(event["received_at"])
                event["target_id"] = event.pop("collector_target_id")
                events.append(event)
            return {
                "events": events,
                "next_before_id": events[-1]["id"] if len(rows) > limit else None,
                "since": _utc_text(start), "until": _utc_text(end),
                "time_basis": "received_at", "order": "id_desc",
                "integrity_status": "verified",
            }
        except Exception:
            raise HTTPException(503, "access event storage unavailable",
                                headers={"Cache-Control": "no-store"}) from None
        finally:
            if conn is not None:
                conn.close()

    @router.get("/bundles")
    def list_bundles(
        limit: int = Query(20, ge=1, le=100),
        before_id: Optional[int] = Query(None, ge=1, le=18446744073709551615),
        mobile_ref: Optional[str] = Query(None, pattern=MOBILE_REF_PATTERN),
        occurred_since: Optional[str] = Query(None, max_length=64),
        occurred_until: Optional[str] = Query(None, max_length=64),
        evidence_received_until: Optional[str] = Query(None, max_length=64),
    ):
        occurrence = None
        evidence_end = None
        if occurred_since is not None or occurred_until is not None or evidence_received_until is not None:
            _, occurrence, evidence_end = _incident_windows(
                None, evidence_received_until if occurred_since is None else None,
                occurred_since, occurred_until, evidence_received_until)
            if occurred_since is None:
                occurrence = None
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                sql = ("SELECT id,bundle_ref,credential_ref,created_at_ms,captured_epoch_ms,"
                       "event_first_epoch_ms,event_last_epoch_ms,evidence_index_version,received_at "
                       "FROM mobile_diagnostic_bundles")
                if evidence_end is not None:
                    where, args = _mobile_where(evidence_end, mobile_ref, before_id, occurrence)
                else:
                    where, args = [], []
                    for column, value in (("id", before_id), ("credential_ref", mobile_ref)):
                        if value is not None:
                            where.append(column + (" < %s" if column == "id" else "=%s"))
                            args.append(value)
                if where:
                    sql += " WHERE " + " AND ".join(where)
                cur.execute(sql + " ORDER BY id DESC LIMIT %s", (*args, limit + 1))
                rows = cur.fetchall()
                items = [{"id": str(row["id"]), "bundle_ref": row["bundle_ref"],
                          "created_at_ms": str(row["created_at_ms"]),
                          "received_at": _utc_text(row["received_at"]),
                          **({"mobile_ref": row["credential_ref"]} if row.get("credential_ref") else {}),
                          "captured_epoch_ms": str(row["captured_epoch_ms"]) if row.get("captured_epoch_ms") is not None else None,
                          "event_first_epoch_ms": str(row["event_first_epoch_ms"]) if row.get("event_first_epoch_ms") is not None else None,
                          "event_last_epoch_ms": str(row["event_last_epoch_ms"]) if row.get("event_last_epoch_ms") is not None else None,
                          "event_range_index": "INDEXED" if row.get("evidence_index_version") == 1 else "LEGACY_UNKNOWN_USE_DETAIL"}
                         for row in rows[:limit]]
                return {"bundles": items, "next_before_id":
                        items[-1]["id"] if len(rows) > limit else None,
                        "truncated": len(rows) > limit,
                        "evidence_received_until": _utc_text(evidence_end) if evidence_end else None,
                        "occurred_since": _utc_text(occurrence[0]) if occurrence else None,
                        "occurred_until": _utc_text(occurrence[1]) if occurrence else None}
        except Exception:
            raise HTTPException(503, "diagnostic storage unavailable", headers={"Cache-Control": "no-store"}) from None
        finally:
            if conn is not None:
                conn.close()

    @router.get("/bundles/{bundle_id}")
    def get_bundle(bundle_id: str):
        # Decimal row identity avoids ambiguity between equal content refs on different phones.
        if not re.fullmatch(r"[1-9][0-9]{0,19}", bundle_id) or int(bundle_id) > 18446744073709551615:
            raise HTTPException(422, "invalid diagnostic id")
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("SELECT id,payload_json,received_at FROM mobile_diagnostic_bundles WHERE id=%s",
                            (int(bundle_id),))
                row = cur.fetchone()
                if row is None:
                    raise HTTPException(404, "diagnostic bundle not found")
                payload = row["payload_json"]
                if isinstance(payload, str):
                    if len(payload.encode("utf-8")) > 65536:
                        raise ValueError("oversized stored bundle")
                    payload = json.loads(payload)
                # Revalidate and project a closed schema; never dump arbitrary DB contents.
                bundle = MobileDiagnosticBundle.model_validate(payload).model_dump(
                    by_alias=True, mode="json", exclude_unset=True,
                )
                session_ids = sorted({s["target_session_id"] for s in bundle["sessions"]
                                      if s.get("target_session_id")})
                target_events = []
                if session_ids:
                    placeholders = ",".join(["%s"] * len(session_ids))
                    cur.execute(
                        "SELECT session_id,event_code,reason_code,received_at FROM access_event_history "
                        "WHERE integrity_status='verified' AND session_id IN (" + placeholders + ") "
                        "ORDER BY received_at ASC,id ASC LIMIT 501", tuple(session_ids),
                    )
                    target_events = cur.fetchall()
                return {
                    "id": str(row["id"]), "received_at": _utc_text(row["received_at"]),
                    "bundle": bundle,
                    "evidence": bundle_evidence_metadata(bundle,
                        int(datetime.fromisoformat(bundle["created_at"].replace("Z", "+00:00")).timestamp() * 1000),
                        row["received_at"], as_of_ms=int(datetime.now(timezone.utc).timestamp() * 1000)),
                    "target_events": [{"session_id": e["session_id"], "event_code": e["event_code"],
                                       "reason_code": e["reason_code"],
                                       "received_at": e["received_at"].isoformat() + "Z"}
                                      for e in target_events[:500]],
                    "target_events_truncated": len(target_events) > 500,
                }
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "diagnostic storage unavailable", headers={"Cache-Control": "no-store"}) from None
        finally:
            if conn is not None:
                conn.close()

    return router
