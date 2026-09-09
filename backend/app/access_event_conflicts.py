"""Durable custody of authenticated identity collisions, never an access verdict."""

import hashlib
import json


def preserve_conflict(conn, event):
    """Caller has authenticated the exact event and found a canonical DB collision.

    Persist the complete normalized event (including its MAC) before permitting
    the existing exact-event DB receipt. Byte-order/whitespace-only replay is
    idempotent. A failed/uncertain commit or a hash mismatch MUST NOT be ACKed.
    No canonical row or HA success projection is inserted/updated here.
    """
    preserved = {key: value for key, value in event.items()
                 if key != "integrity_tag_bytes"}
    payload = json.dumps(preserved, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    target = event["collector_target_id"]
    conn.begin()
    with conn.cursor() as cur:
        cur.execute("SELECT payload_json FROM access_event_conflicts "
                    "WHERE target_id=%s AND payload_sha256=%s", (target, digest))
        existing = cur.fetchone()
        if existing is not None:
            stored = existing["payload_json"]
            if isinstance(stored, str):
                stored = json.loads(stored)
            if stored != preserved:
                raise ValueError("conflict custody digest mismatch")
        else:
            cur.execute(
                "INSERT INTO access_event_conflicts "
                "(target_id,event_id,source_boot_id,source_boot_count,source_sequence,"
                "session_id,event_code,reason_code,payload_sha256,payload_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (target, event["event_id"], event["source_boot_id"],
                 event["source_boot_count"], event["source_sequence"],
                 event["session_id"], event["event_code"], "IDENTITY_CONFLICT", digest, payload),
            )
    conn.commit()
    return {"inserted": False, "quarantined": True, "event": event}
