"""Optional, read-only diagnostic capability. Never an administrator credential."""

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

try:
    from .mobile_diagnostics import MobileDiagnosticBundle
    from .ops_runtime import SlidingWindowRateLimiter
    from .reliability_diagnostics import CORE_FIELDS, advisory_projection, classify_incident, sensor_mac_input
except ImportError:
    from mobile_diagnostics import MobileDiagnosticBundle
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
    ):
        start, end = _event_window(since, until)
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
                # The newest available report is visible even if stale. It never proves today's wake.
                cur.execute("SELECT id,credential_ref,created_at_ms,payload_json,received_at "
                            "FROM mobile_diagnostic_bundles WHERE received_at < %s ORDER BY id DESC LIMIT 21",
                            (until_db,))
                mobiles = cur.fetchall()
                cur.execute("SELECT id,verified_json,advisory_json,received_at FROM target_health_history "
                            "WHERE received_at >= %s AND received_at < %s"
                            + (" AND target_id=%s" if target_id else "") + " ORDER BY id DESC LIMIT 101",
                            (since_db, until_db, *([target_id] if target_id else [])))
                health = cur.fetchall()
            reports = []
            matches = {}
            mobile_incidents = {}
            start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
            for row in mobiles[:20]:
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
                current = 0 <= age <= 300000
                valid_sessions = [s for s in body["sessions"] if
                                  start_ms <= (s.get("updated_epoch_ms") or s.get("created_epoch_ms") or -1) < end_ms]
                for session in valid_sessions:
                    if session.get("target_session_id"):
                        matches.setdefault(session["target_session_id"], []).append(str(row["id"]))
                lifecycle = [item for item in (runtime or {}).get("lifecycle", [])
                             if start_ms <= item["at_epoch_ms"] < end_ms]
                for item in lifecycle:
                    if item["event"] not in ("DISPATCH_SKIPPED", "ENQUEUE_FAILED", "WORKER_STOPPED", "ORPHAN_RECOVERED"):
                        continue
                    identity = json.dumps([row["credential_ref"], (runtime or {}).get("process_ref"), item],
                                          separators=(",", ":"), sort_keys=True)
                    key = hashlib.sha256(identity.encode()).hexdigest()[:32]
                    mobile_incidents[key] = dict(incident_ref=key, report_id=str(row["id"]),
                        mobile_ref=row["credential_ref"], source="mobile_runtime", event=item,
                        classification="DISPATCH_DECISION_OBSERVED", target_correlation="NOT_REQUIRED",
                        physical_door="NOT_OBSERVABLE", arrival="NOT_OBSERVABLE")
                for item in valid_sessions:
                    if item.get("state") not in ("FAILED", "CANCELLED", "PROOF_UNCERTAIN"):
                        continue
                    identity = json.dumps([row["credential_ref"], item.get("event_ref"), item.get("updated_epoch_ms")],
                                          separators=(",", ":"))
                    key = hashlib.sha256(identity.encode()).hexdigest()[:32]
                    mobile_incidents[key] = dict(incident_ref=key, report_id=str(row["id"]),
                        mobile_ref=row["credential_ref"], source="mobile_session", session=item,
                        classification="MOBILE_FAILURE_OBSERVED", target_correlation="SESSION_ID" if item.get("target_session_id") else "NOT_OBSERVED",
                        physical_door="NOT_OBSERVABLE", arrival="NOT_OBSERVABLE")
                reports.append(dict(id=str(row["id"]), mobile_ref=row["credential_ref"], app=body["app"],
                                    received_at=_utc_text(row["received_at"]), captured_epoch_ms=str(captured),
                                    age_at_window_end_ms=age, freshness="RECENT_REPORT" if current else
                                    "CLOCK_UNCERTAIN" if age < 0 else "STALE_REPORT",
                                    sessions_in_window=valid_sessions[:20], runtime_lifecycle_in_window=lifecycle[-32:],
                                    detail_truncated=len(valid_sessions) > 20 or len(lifecycle) > 32,
                                    explicit_runtime_reasons=sorted({item["reason"] for item in lifecycle if item.get("reason")}),
                                    scan=body["native"].get("scan") if current else None,
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
                result.append(dict(id=str(group["latest_id"]), target_id=group["collector_target_id"],
                                   source_boot_id=group["source_boot_id"], session_id=group["session_id"],
                                   event_count=len(rows), event_codes=[e["event_code"] for e in rows],
                                   first_received_at=_utc_text(min(e["received_at"] for e in rows)) if rows else None,
                                   last_received_at=_utc_text(max(e["received_at"] for e in rows)) if rows else None,
                                   sensor_summary=sensor, sensor_integrity="verified" if sensor else "NOT_OBSERVED",
                                   sensor_span_ms=(int(sensor["ended_monotonic_ms"])-int(sensor["started_monotonic_ms"])) & 0xffffffff if sensor else None,
                                   mobile_report_matches=matches.get(group["session_id"], []), **decision))
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
            return dict(incidents=result, mobile_incidents=list(mobile_incidents.values())[:100],
                        mobile_observations=reports, target_observations=targets,
                        sensor_observations=sensor_observations,
                        health_history=health_result,
                        next_before_id=str(result[-1]["id"]) if len(groups) > limit else None,
                        since=_utc_text(start), until=_utc_text(end), time_basis="backend_received_at",
                        source_order="boot_sequence", snapshot_atomic=False,
                        coverage=dict(events_truncated=len(event_rows) > 5000,
                                      mobile_reports_truncated=len(mobiles) > 20,
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
    ):
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                sql = "SELECT id,bundle_ref,created_at_ms,received_at FROM mobile_diagnostic_bundles"
                args = []
                if before_id is not None:
                    sql += " WHERE id < %s"
                    args.append(before_id)
                cur.execute(sql + " ORDER BY id DESC LIMIT %s", (*args, limit + 1))
                rows = cur.fetchall()
                items = [{"id": str(row["id"]), "bundle_ref": row["bundle_ref"],
                          "created_at_ms": str(row["created_at_ms"]),
                          "received_at": row["received_at"].isoformat() + "Z"}
                         for row in rows[:limit]]
                return {"bundles": items, "next_before_id":
                        items[-1]["id"] if len(rows) > limit else None}
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
                    "id": str(row["id"]), "received_at": row["received_at"].isoformat() + "Z",
                    "bundle": bundle,
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
