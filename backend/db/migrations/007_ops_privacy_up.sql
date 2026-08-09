USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS privacy_deletion_jobs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  tenant_scope VARCHAR(80) NOT NULL,
  actor_subject VARCHAR(160) NOT NULL,
  policy_version VARCHAR(64) NOT NULL,
  before_days INT UNSIGNED NOT NULL,
  idempotency_hash CHAR(64) NOT NULL,
  deleted_count BIGINT UNSIGNED NOT NULL,
  created_at BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_privacy_delete_idempotency (tenant_scope, idempotency_hash),
  CONSTRAINT chk_privacy_delete_policy CHECK (policy_version = 'sgk-retention-v1'),
  CONSTRAINT chk_privacy_delete_days CHECK (before_days BETWEEN 30 AND 3650),
  CONSTRAINT chk_privacy_delete_hash CHECK (idempotency_hash REGEXP '^[0-9a-f]{64}$')
) ENGINE=InnoDB;

DROP TRIGGER IF EXISTS privacy_deletion_jobs_no_update;
DROP TRIGGER IF EXISTS privacy_deletion_jobs_no_delete;
DELIMITER //
CREATE TRIGGER privacy_deletion_jobs_no_update
BEFORE UPDATE ON privacy_deletion_jobs FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'privacy deletion evidence is immutable';
END//
CREATE TRIGGER privacy_deletion_jobs_no_delete
BEFORE DELETE ON privacy_deletion_jobs FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'privacy deletion evidence is immutable';
END//
DELIMITER ;
