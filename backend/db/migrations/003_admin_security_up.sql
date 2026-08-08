-- Issue #49: durable, append-only control-plane actor audit.
-- Apply after 002.  No API path may treat a missing table as permission to
-- continue: management/control writes fail closed until this migration exists.
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS admin_audit (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  actor_subject VARCHAR(128) NOT NULL,
  tenant_scope VARCHAR(64) NOT NULL,
  action VARCHAR(64) NOT NULL,
  object_ref VARCHAR(128) NOT NULL,
  idempotency_hash CHAR(64) NULL,
  created_at BIGINT UNSIGNED NOT NULL,
  INDEX idx_admin_audit_tenant_time (tenant_scope, created_at),
  INDEX idx_admin_audit_actor_time (actor_subject, created_at),
  UNIQUE KEY uq_admin_audit_idempotency (actor_subject, tenant_scope, action, idempotency_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DELIMITER //
DROP TRIGGER IF EXISTS admin_audit_no_update//
CREATE TRIGGER admin_audit_no_update
BEFORE UPDATE ON admin_audit
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'admin_audit is immutable';
END//
DROP TRIGGER IF EXISTS admin_audit_no_delete//
CREATE TRIGGER admin_audit_no_delete
BEFORE DELETE ON admin_audit
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'admin_audit is immutable';
END//
DELIMITER ;

-- Deploy the runtime account with INSERT/SELECT only; migration ownership and
-- trigger-management privileges are intentionally outside the API account.
