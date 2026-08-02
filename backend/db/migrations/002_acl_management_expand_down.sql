-- Issue #19 rollback migration.
-- Run only while legacy ble_device_mac/auth_key columns and legacy application remain deployed.
-- This removes only additive management-plane state; it never rewrites legacy tenant rows.

USE smart_gatekeeper;

DROP TABLE IF EXISTS ota_health_confirmations;
DROP TABLE IF EXISTS ota_release_metadata;
DROP TABLE IF EXISTS management_audit;
DROP TABLE IF EXISTS acl_snapshot_jobs;
DROP TABLE IF EXISTS target_acl_acks;
DROP TABLE IF EXISTS acl_snapshots;
DROP TABLE IF EXISTS acl_door_state;
DROP TABLE IF EXISTS credential_door_grants;
DROP TABLE IF EXISTS enrollment_challenges;
DROP TABLE IF EXISTS credentials;
DROP TABLE IF EXISTS acl_tenants;

ALTER TABLE tenants
  DROP INDEX IF EXISTS uq_tenants_tenant_uuid,
  DROP COLUMN IF EXISTS credential_mode,
  DROP COLUMN IF EXISTS tenant_uuid;
