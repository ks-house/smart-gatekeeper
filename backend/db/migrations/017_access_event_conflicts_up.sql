-- Preserve MAC-verified identity conflicts without weakening canonical uniqueness.
-- A DB-commit receipt acknowledges durable diagnostic custody, NOT access success.
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS access_event_conflicts (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  target_id VARCHAR(64) NOT NULL,
  event_id CHAR(36) NOT NULL,
  source_boot_id CHAR(32) NOT NULL,
  source_boot_count BIGINT UNSIGNED NOT NULL,
  source_sequence BIGINT UNSIGNED NOT NULL,
  session_id CHAR(36) NOT NULL,
  event_code VARCHAR(64) NOT NULL,
  reason_code VARCHAR(32) NOT NULL,
  payload_sha256 CHAR(64) NOT NULL,
  payload_json JSON NOT NULL,
  received_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_access_conflict_payload (target_id, payload_sha256),
  INDEX idx_access_conflict_target_id (target_id, id),
  INDEX idx_access_conflict_received (received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Like canonical access evidence, quarantine is append-only, not a transient log.
DROP TRIGGER IF EXISTS access_event_conflicts_no_update;
DROP TRIGGER IF EXISTS access_event_conflicts_no_delete;
DELIMITER //
CREATE TRIGGER access_event_conflicts_no_update BEFORE UPDATE ON access_event_conflicts
FOR EACH ROW BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'access event conflicts are immutable';
END//
CREATE TRIGGER access_event_conflicts_no_delete BEFORE DELETE ON access_event_conflicts
FOR EACH ROW BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'access event conflicts are immutable';
END//
DELIMITER ;
