-- Store only strict, redacted mobile diagnostic bundles. The credential is
-- represented by a purpose-scoped server HMAC and payloads are append-only.
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS mobile_diagnostic_bundles (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id CHAR(32) NOT NULL,
  credential_ref VARCHAR(64) NOT NULL,
  bundle_ref CHAR(32) NOT NULL,
  created_at_ms BIGINT UNSIGNED NOT NULL,
  payload_json JSON NOT NULL,
  payload_sha256 CHAR(64) NOT NULL,
  received_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_mobile_diagnostic_bundle (tenant_id, credential_ref, bundle_ref),
  INDEX idx_mobile_diagnostic_received (received_at),
  INDEX idx_mobile_diagnostic_credential_received (credential_ref, received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='Strict redacted opt-in mobile field diagnostics';

DROP TRIGGER IF EXISTS mobile_diagnostic_bundles_no_update;
DROP TRIGGER IF EXISTS mobile_diagnostic_bundles_no_delete;

DELIMITER //
CREATE TRIGGER mobile_diagnostic_bundles_no_update
BEFORE UPDATE ON mobile_diagnostic_bundles
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'mobile_diagnostic_bundles is append-only';
END//

CREATE TRIGGER mobile_diagnostic_bundles_no_delete
BEFORE DELETE ON mobile_diagnostic_bundles
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'mobile_diagnostic_bundles is append-only';
END//
DELIMITER ;
