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
except ImportError:
    from mobile_diagnostics import MobileDiagnosticBundle
    from ops_runtime import SlidingWindowRateLimiter


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
