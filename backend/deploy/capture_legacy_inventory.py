#!/usr/bin/env python3
"""Emit identifier-free integrity inventory for the running legacy DB."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import pymysql


REQUIRED_TABLES = {
    "tenants",
    "access_logs",
    "admin_audit",
    "credentials",
    "acl_snapshots",
    "target_boot_state",
    "privacy_deletion_jobs",
    "support_export_consents",
}


def inventory_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def main() -> None:
    connection = pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "smart_gatekeeper"),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=30,
        write_timeout=5,
    )
    try:
        result: dict[str, dict[str, Any]] = {}
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            for table in sorted(REQUIRED_TABLES):
                cursor.execute(
                    "SELECT column_name,column_type,is_nullable,column_default,"
                    "extra,ordinal_position FROM information_schema.columns "
                    "WHERE table_schema=DATABASE() AND table_name=%s "
                    "ORDER BY ordinal_position",
                    (table,),
                )
                columns = cursor.fetchall()
                if not columns:
                    raise RuntimeError("required inventory table is missing")
                schema_bytes = json.dumps(
                    [
                        {
                            key: inventory_value(value)
                            for key, value in row.items()
                        }
                        for row in columns
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                cursor.execute(
                    "SELECT column_name FROM information_schema.statistics "
                    "WHERE table_schema=DATABASE() AND table_name=%s "
                    "AND index_name='PRIMARY' ORDER BY seq_in_index",
                    (table,),
                )
                primary_key = [row["column_name"] for row in cursor.fetchall()]
                if not primary_key:
                    raise RuntimeError("required inventory table has no primary key")
                order = ",".join(f"`{column}`" for column in primary_key)
                cursor.execute(f"SELECT * FROM `{table}` ORDER BY {order}")
                content = hashlib.sha256()
                row_count = 0
                while True:
                    rows = cursor.fetchmany(500)
                    if not rows:
                        break
                    for row in rows:
                        canonical = json.dumps(
                            {
                                key: inventory_value(value)
                                for key, value in row.items()
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode("utf-8")
                        content.update(canonical + b"\n")
                        row_count += 1
                result[table] = {
                    "row_count": row_count,
                    "content_sha256": content.hexdigest(),
                    "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
                    "primary_key": primary_key,
                }
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    main()
