-- Issue #19 expand migration: public credentials, signed ACL, ACK/audit, OTA management.
-- Safe order: deploy this nullable/additive schema, dual-write/migrate, then contract only
-- after N/N-1 rollback windows. Existing ble_device_mac/auth_key reads remain valid.

USE smart_gatekeeper;

ALTER TABLE tenants
  ADD COLUMN IF NOT EXISTS tenant_uuid CHAR(32) NULL COMMENT 'Canonical 16-byte tenant ID as lowercase hex',
  ADD COLUMN IF NOT EXISTS credential_mode VARCHAR(16) NOT NULL DEFAULT 'legacy' COMMENT 'legacy|dual|public_key',
  ADD UNIQUE INDEX IF NOT EXISTS uq_tenants_tenant_uuid (tenant_uuid);

CREATE TABLE IF NOT EXISTS acl_tenants (
  tenant_id CHAR(32) PRIMARY KEY,
  display_name VARCHAR(100) NOT NULL,
  created_at BIGINT UNSIGNED NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS enrollment_challenges (
  enrollment_id CHAR(32) PRIMARY KEY,
  tenant_id CHAR(32) NOT NULL,
  actor_ref VARCHAR(128) NOT NULL COMMENT 'Stable one-way authenticated enrollment identity',
  nonce_hash CHAR(64) NOT NULL COMMENT 'SHA-256 only; raw nonce is not persisted',
  expires_at BIGINT UNSIGNED NOT NULL,
  used_at BIGINT UNSIGNED NULL,
  created_at BIGINT UNSIGNED NOT NULL,
  CONSTRAINT fk_enrollment_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id),
  INDEX idx_enrollment_tenant_expiry (tenant_id, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS credentials (
  credential_id CHAR(32) PRIMARY KEY,
  tenant_id CHAR(32) NOT NULL,
  public_key_sec1 CHAR(130) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  expires_at BIGINT UNSIGNED NULL,
  legacy_device_ref CHAR(64) NULL COMMENT 'Keyed HMAC migration lookup; never raw device_id',
  min_protocol SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  max_protocol SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  created_at BIGINT UNSIGNED NOT NULL,
  updated_at BIGINT UNSIGNED NOT NULL,
  CONSTRAINT fk_credentials_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id),
  CONSTRAINT chk_credentials_status CHECK (status IN ('PENDING','ACTIVE','DISABLED','REVOKED','EXPIRED')),
  CONSTRAINT chk_credentials_protocol CHECK (min_protocol >= 1 AND min_protocol <= max_protocol),
  UNIQUE KEY uq_credentials_public_key (public_key_sec1),
  INDEX idx_credentials_tenant_status (tenant_id, status, credential_id),
  INDEX idx_credentials_legacy_ref (tenant_id, legacy_device_ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS credential_door_grants (
  tenant_id CHAR(32) NOT NULL,
  door_id CHAR(32) NOT NULL,
  credential_id CHAR(32) NOT NULL,
  permissions INT UNSIGNED NOT NULL DEFAULT 1,
  granted_at BIGINT UNSIGNED NOT NULL,
  revoked_at BIGINT UNSIGNED NULL,
  PRIMARY KEY (tenant_id, door_id, credential_id),
  CONSTRAINT fk_grant_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id),
  CONSTRAINT fk_grant_credential FOREIGN KEY (credential_id) REFERENCES credentials(credential_id),
  INDEX idx_grants_active (tenant_id, door_id, revoked_at, credential_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS acl_door_state (
  tenant_id CHAR(32) NOT NULL,
  door_id CHAR(32) NOT NULL,
  last_version BIGINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, door_id),
  UNIQUE KEY uq_acl_door_global (door_id),
  CONSTRAINT fk_acl_state_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS acl_snapshots (
  tenant_id CHAR(32) NOT NULL,
  door_id CHAR(32) NOT NULL,
  acl_version BIGINT UNSIGNED NOT NULL,
  sha256 CHAR(64) NOT NULL,
  envelope_json LONGTEXT NOT NULL,
  created_at BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (tenant_id, door_id, acl_version),
  CONSTRAINT fk_acl_snapshot_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id),
  INDEX idx_acl_snapshot_latest (tenant_id, door_id, acl_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS acl_snapshot_jobs (
  tenant_id CHAR(32) NOT NULL,
  door_id CHAR(32) NOT NULL,
  reason VARCHAR(64) NOT NULL,
  requested_at BIGINT UNSIGNED NOT NULL,
  generated_version BIGINT UNSIGNED NULL,
  revision BIGINT UNSIGNED NOT NULL DEFAULT 1,
  PRIMARY KEY (tenant_id, door_id),
  CONSTRAINT fk_acl_job_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id),
  INDEX idx_acl_job_pending (requested_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS target_acl_acks (
  ack_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id CHAR(32) NOT NULL,
  target_id VARCHAR(128) NOT NULL,
  door_id CHAR(32) NOT NULL,
  acl_version BIGINT UNSIGNED NOT NULL,
  sha256 CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL,
  acked_at BIGINT UNSIGNED NOT NULL,
  CONSTRAINT fk_acl_ack_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id),
  CONSTRAINT chk_acl_ack_status CHECK (status IN ('APPLIED','REJECTED')),
  UNIQUE KEY uq_acl_ack_idempotency (tenant_id, target_id, door_id, acl_version, sha256),
  INDEX idx_acl_ack_fleet (tenant_id, door_id, target_id, acked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS management_audit (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id CHAR(32) NOT NULL,
  actor_ref VARCHAR(128) NOT NULL,
  action VARCHAR(64) NOT NULL,
  credential_id CHAR(32) NULL,
  metadata_json TEXT NOT NULL,
  created_at BIGINT UNSIGNED NOT NULL,
  CONSTRAINT fk_management_audit_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id),
  INDEX idx_management_audit_tenant (tenant_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ota_release_metadata (
  tenant_id CHAR(32) NOT NULL,
  component VARCHAR(16) NOT NULL,
  metadata_json LONGTEXT NOT NULL,
  updated_at BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (tenant_id, component),
  CONSTRAINT fk_ota_metadata_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ota_health_confirmations (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id CHAR(32) NOT NULL,
  target_id VARCHAR(128) NOT NULL,
  component VARCHAR(16) NOT NULL,
  version VARCHAR(64) NOT NULL,
  boot_id VARCHAR(128) NOT NULL,
  artifact_sha256 CHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  confirmed_at BIGINT UNSIGNED NOT NULL,
  CONSTRAINT fk_ota_health_tenant FOREIGN KEY (tenant_id) REFERENCES acl_tenants(tenant_id),
  CONSTRAINT chk_ota_health_status CHECK (status IN ('HEALTH_CONFIRMED','HEALTH_FAILED')),
  INDEX idx_ota_health_lookup (tenant_id, component, target_id, confirmed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
