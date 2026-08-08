-- Issue #49 v2 control protocol: durable approval and mobile proof replay state.
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS force_open_approvals (
  approval_id CHAR(48) PRIMARY KEY,
  tenant_scope VARCHAR(64) NOT NULL,
  proposer_subject VARCHAR(128) NOT NULL,
  approver_subject VARCHAR(128) NULL,
  reason VARCHAR(256) NOT NULL,
  idempotency_hash CHAR(64) NOT NULL,
  status ENUM('PENDING','PUBLISHING','PUBLISHED','EXPIRED') NOT NULL DEFAULT 'PENDING',
  expires_at BIGINT UNSIGNED NOT NULL,
  created_at BIGINT UNSIGNED NOT NULL,
  published_at BIGINT UNSIGNED NULL,
  UNIQUE KEY uq_force_open_request (proposer_subject, tenant_scope, idempotency_hash),
  INDEX idx_force_open_pending (tenant_scope, status, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mobile_control_nonces (
  tenant_id BIGINT NOT NULL,
  nonce_hash CHAR(64) NOT NULL,
  action VARCHAR(32) NOT NULL,
  expires_at BIGINT UNSIGNED NOT NULL,
  consumed_at BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (tenant_id, nonce_hash, action),
  INDEX idx_mobile_nonce_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
