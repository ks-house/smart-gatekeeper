-- Persist privacy-safe Target access lifecycle events independently from the
-- legacy boolean access_logs projection.  The event identity and source
-- position constraints make MQTT redelivery idempotent and expose conflicts.
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS access_event_history (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  event_id CHAR(36) NOT NULL,
  session_id CHAR(36) NOT NULL,
  source_component VARCHAR(16) NOT NULL,
  source_instance_id VARCHAR(64) NOT NULL,
  source_boot_id VARCHAR(64) NOT NULL,
  source_sequence BIGINT UNSIGNED NOT NULL,
  event_attempt INT UNSIGNED NOT NULL,
  event_code VARCHAR(64) NOT NULL,
  event_stage VARCHAR(24) NOT NULL,
  event_outcome VARCHAR(16) NOT NULL,
  reason_code VARCHAR(64) NOT NULL,
  causation_event_id CHAR(36) DEFAULT NULL,
  target_ref VARCHAR(64) NOT NULL,
  event_path VARCHAR(24) NOT NULL,
  event_transport VARCHAR(24) NOT NULL,
  distance_mm INT UNSIGNED DEFAULT NULL,
  duration_ms BIGINT UNSIGNED DEFAULT NULL,
  relay_hold_ms INT UNSIGNED DEFAULT NULL,
  monotonic_ms BIGINT UNSIGNED NOT NULL,
  clock_quality VARCHAR(16) NOT NULL,
  collector_target_ref VARCHAR(64) NOT NULL,
  received_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_access_event_id (event_id),
  UNIQUE KEY uq_access_event_source_position
    (collector_target_ref, source_boot_id, source_sequence),
  INDEX idx_access_event_session_received (session_id, received_at),
  INDEX idx_access_event_received (received_at),
  CONSTRAINT chk_access_event_source CHECK (source_component = 'target'),
  CONSTRAINT chk_access_event_outcome CHECK (
    event_outcome IN (
      'STARTED', 'PROGRESS', 'SUCCEEDED', 'DENIED', 'FAILED',
      'TIMED_OUT', 'CANCELLED'
    )
  ),
  CONSTRAINT chk_access_event_clock CHECK (clock_quality = 'UNSYNCED'),
  CONSTRAINT chk_access_event_distance CHECK (
    distance_mm IS NULL OR distance_mm <= 10000
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='Privacy-safe Target access lifecycle event history';

DROP TRIGGER IF EXISTS access_event_history_no_update;
DROP TRIGGER IF EXISTS access_event_history_no_delete;

DELIMITER //
CREATE TRIGGER access_event_history_no_update
BEFORE UPDATE ON access_event_history
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'access_event_history is append-only';
END//

CREATE TRIGGER access_event_history_no_delete
BEFORE DELETE ON access_event_history
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'access_event_history is append-only';
END//
DELIMITER ;
