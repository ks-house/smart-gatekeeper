-- Align every stored mobile credential and queued signed ACL with the v2-only
-- GATT fast path. Existing 1/1 rows otherwise disappear from a 2/2 snapshot.
USE smart_gatekeeper;

ALTER TABLE credentials
  MODIFY min_protocol SMALLINT UNSIGNED NOT NULL DEFAULT 2,
  MODIFY max_protocol SMALLINT UNSIGNED NOT NULL DEFAULT 2;

UPDATE credentials
SET min_protocol = 2,
    max_protocol = 2,
    updated_at = UNIX_TIMESTAMP()
WHERE min_protocol <> 2 OR max_protocol <> 2;

INSERT INTO acl_snapshot_jobs (
  tenant_id, door_id, reason, requested_at, generated_version, revision
)
SELECT DISTINCT
  grant_row.tenant_id,
  grant_row.door_id,
  'GATT_V2_CONTRACT',
  UNIX_TIMESTAMP(),
  NULL,
  1
FROM credential_door_grants AS grant_row
JOIN credentials AS credential_row
  ON credential_row.credential_id = grant_row.credential_id
 AND credential_row.tenant_id = grant_row.tenant_id
WHERE grant_row.revoked_at IS NULL
  AND credential_row.status = 'ACTIVE'
ON DUPLICATE KEY UPDATE
  reason = VALUES(reason),
  requested_at = VALUES(requested_at),
  generated_version = NULL,
  revision = revision + 1;
