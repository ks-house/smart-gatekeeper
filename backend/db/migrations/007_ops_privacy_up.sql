USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS privacy_deletion_jobs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tenant_scope VARCHAR(80) NOT NULL,
  actor_subject VARCHAR(160) NOT NULL,
  policy_version VARCHAR(64) NOT NULL,
  before_days INT UNSIGNED NOT NULL,
  idempotency_hash CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  state ENUM('PENDING', 'COMPLETED') NOT NULL DEFAULT 'PENDING',
  deleted_count BIGINT UNSIGNED NULL,
  created_at BIGINT UNSIGNED NOT NULL,
  completed_at BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_privacy_delete_idempotency (tenant_scope, idempotency_hash),
  CONSTRAINT chk_privacy_delete_policy CHECK (policy_version = 'sgk-retention-v1'),
  CONSTRAINT chk_privacy_delete_days CHECK (before_days BETWEEN 30 AND 3650),
  CONSTRAINT chk_privacy_delete_hash CHECK (idempotency_hash REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_privacy_delete_request_hash CHECK (request_hash REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_privacy_delete_completion CHECK (
    (state = 'PENDING' AND deleted_count IS NULL AND completed_at IS NULL) OR
    (state = 'COMPLETED' AND deleted_count IS NOT NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS support_export_consents (
  consent_ref_hash CHAR(64) NOT NULL,
  tenant_scope VARCHAR(80) NOT NULL,
  purpose VARCHAR(64) NOT NULL,
  granted_by VARCHAR(160) NOT NULL,
  expires_at BIGINT UNSIGNED NOT NULL,
  revoked_at BIGINT UNSIGNED NULL,
  created_at BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (consent_ref_hash),
  KEY idx_support_consent_scope (tenant_scope, purpose, expires_at),
  CONSTRAINT chk_support_consent_hash CHECK (consent_ref_hash REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_support_consent_purpose CHECK (purpose = 'support-diagnostics'),
  CONSTRAINT chk_support_consent_revocation CHECK (
    revoked_at IS NULL OR revoked_at >= created_at
  )
) ENGINE=InnoDB;

DROP TRIGGER IF EXISTS privacy_deletion_jobs_no_update;
DROP TRIGGER IF EXISTS privacy_deletion_jobs_no_delete;
DROP TRIGGER IF EXISTS support_export_consents_revoke_only;
DROP TRIGGER IF EXISTS support_export_consents_no_delete;
DELIMITER //
CREATE TRIGGER privacy_deletion_jobs_no_update
BEFORE UPDATE ON privacy_deletion_jobs FOR EACH ROW
BEGIN
  IF NOT (
    OLD.state = 'PENDING' AND NEW.state = 'COMPLETED' AND
    OLD.tenant_scope = NEW.tenant_scope AND
    OLD.actor_subject = NEW.actor_subject AND
    OLD.policy_version = NEW.policy_version AND
    OLD.before_days = NEW.before_days AND
    OLD.idempotency_hash = NEW.idempotency_hash AND
    OLD.request_hash = NEW.request_hash AND
    OLD.created_at = NEW.created_at AND
    NEW.deleted_count IS NOT NULL AND NEW.completed_at IS NOT NULL
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'privacy deletion evidence is immutable';
  END IF;
END//
CREATE TRIGGER privacy_deletion_jobs_no_delete
BEFORE DELETE ON privacy_deletion_jobs FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'privacy deletion evidence is immutable';
END//
CREATE TRIGGER support_export_consents_revoke_only
BEFORE UPDATE ON support_export_consents FOR EACH ROW
BEGIN
  IF NOT (
    OLD.consent_ref_hash = NEW.consent_ref_hash AND
    OLD.tenant_scope = NEW.tenant_scope AND
    OLD.purpose = NEW.purpose AND
    OLD.granted_by = NEW.granted_by AND
    OLD.expires_at = NEW.expires_at AND
    OLD.created_at = NEW.created_at AND
    OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'support consent is append-only and revoke-once';
  END IF;
END//
CREATE TRIGGER support_export_consents_no_delete
BEFORE DELETE ON support_export_consents FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'support consent evidence is immutable';
END//
DELIMITER ;
