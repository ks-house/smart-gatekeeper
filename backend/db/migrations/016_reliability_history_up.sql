-- Operational evidence is immutable within its explicit 31-day retention.
-- This does not alter retention of access/security/mobile evidence.
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS target_health_history (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  target_id VARCHAR(64) NOT NULL,
  source_boot_id CHAR(32) NOT NULL,
  source_boot_count BIGINT UNSIGNED NOT NULL,
  status_revision BIGINT UNSIGNED NOT NULL,
  gate_state VARCHAR(24) NOT NULL,
  terminal_session_id CHAR(36) NULL,
  relay_commanded_on BOOLEAN NOT NULL,
  verified_json JSON NOT NULL,
  advisory_json JSON NULL,
  received_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_target_health_position (target_id, source_boot_id, status_revision),
  INDEX idx_target_health_target_received (target_id, received_at),
  INDEX idx_target_health_target_id (target_id, id),
  INDEX idx_target_health_received (received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS target_sensor_session_history (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  target_id VARCHAR(64) NOT NULL,
  source_boot_id CHAR(32) NOT NULL,
  source_boot_count BIGINT UNSIGNED NOT NULL,
  session_id CHAR(36) NOT NULL,
  terminal_sequence BIGINT UNSIGNED NOT NULL,
  summary_json JSON NOT NULL,
  summary_sha256 CHAR(64) NOT NULL,
  received_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_target_sensor_position (target_id, source_boot_id, terminal_sequence),
  INDEX idx_target_sensor_session (target_id, session_id),
  INDEX idx_target_sensor_received (received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

DROP TRIGGER IF EXISTS target_health_history_no_update;
DROP TRIGGER IF EXISTS target_health_history_retention;
DROP TRIGGER IF EXISTS target_sensor_session_history_no_update;
DROP TRIGGER IF EXISTS target_sensor_session_history_retention;
DELIMITER //
CREATE TRIGGER target_health_history_no_update BEFORE UPDATE ON target_health_history
FOR EACH ROW BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'target health history is immutable';
END//
CREATE TRIGGER target_health_history_retention BEFORE DELETE ON target_health_history
FOR EACH ROW BEGIN
  IF OLD.received_at >= UTC_TIMESTAMP(3) - INTERVAL 31 DAY THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'target health retention is 31 days';
  END IF;
END//
CREATE TRIGGER target_sensor_session_history_no_update BEFORE UPDATE ON target_sensor_session_history
FOR EACH ROW BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'target sensor history is immutable';
END//
CREATE TRIGGER target_sensor_session_history_retention BEFORE DELETE ON target_sensor_session_history
FOR EACH ROW BEGIN
  IF OLD.received_at >= UTC_TIMESTAMP(3) - INTERVAL 31 DAY THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'target sensor retention is 31 days';
  END IF;
END//
DELIMITER ;
