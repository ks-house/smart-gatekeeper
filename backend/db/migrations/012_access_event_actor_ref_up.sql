-- Add authenticated, privacy-safe Target access evidence. Existing rows remain
-- legacy_unsigned and must never be promoted or attributed by time correlation.
USE smart_gatekeeper;

SET @has_credential_ref := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'access_event_history'
    AND COLUMN_NAME = 'credential_ref'
);
SET @add_credential_ref := IF(
  @has_credential_ref = 0,
  'ALTER TABLE access_event_history ADD COLUMN credential_ref VARCHAR(32) NULL AFTER collector_target_ref',
  'SELECT 1'
);
PREPARE add_credential_ref_stmt FROM @add_credential_ref;
EXECUTE add_credential_ref_stmt;
DEALLOCATE PREPARE add_credential_ref_stmt;

SET @has_collector_target_id := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'access_event_history'
    AND COLUMN_NAME = 'collector_target_id'
);
SET @add_collector_target_id := IF(
  @has_collector_target_id = 0,
  'ALTER TABLE access_event_history ADD COLUMN collector_target_id VARCHAR(64) NULL AFTER collector_target_ref',
  'SELECT 1'
);
PREPARE add_collector_target_id_stmt FROM @add_collector_target_id;
EXECUTE add_collector_target_id_stmt;
DEALLOCATE PREPARE add_collector_target_id_stmt;

SET @has_source_boot_count := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'access_event_history'
    AND COLUMN_NAME = 'source_boot_count'
);
SET @add_source_boot_count := IF(
  @has_source_boot_count = 0,
  'ALTER TABLE access_event_history ADD COLUMN source_boot_count BIGINT UNSIGNED NULL AFTER source_boot_id',
  'SELECT 1'
);
PREPARE add_source_boot_count_stmt FROM @add_source_boot_count;
EXECUTE add_source_boot_count_stmt;
DEALLOCATE PREPARE add_source_boot_count_stmt;

SET @has_integrity_key_id := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'access_event_history'
    AND COLUMN_NAME = 'integrity_key_id'
);
SET @add_integrity_key_id := IF(
  @has_integrity_key_id = 0,
  'ALTER TABLE access_event_history ADD COLUMN integrity_key_id VARCHAR(4) NULL AFTER credential_ref',
  'SELECT 1'
);
PREPARE add_integrity_key_id_stmt FROM @add_integrity_key_id;
EXECUTE add_integrity_key_id_stmt;
DEALLOCATE PREPARE add_integrity_key_id_stmt;

SET @has_integrity_tag := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'access_event_history'
    AND COLUMN_NAME = 'integrity_tag'
);
SET @add_integrity_tag := IF(
  @has_integrity_tag = 0,
  'ALTER TABLE access_event_history ADD COLUMN integrity_tag BINARY(16) NULL AFTER integrity_key_id',
  'SELECT 1'
);
PREPARE add_integrity_tag_stmt FROM @add_integrity_tag;
EXECUTE add_integrity_tag_stmt;
DEALLOCATE PREPARE add_integrity_tag_stmt;

SET @has_integrity_status := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'access_event_history'
    AND COLUMN_NAME = 'integrity_status'
);
SET @add_integrity_status := IF(
  @has_integrity_status = 0,
  'ALTER TABLE access_event_history ADD COLUMN integrity_status VARCHAR(16) NOT NULL DEFAULT ''legacy_unsigned'' AFTER integrity_tag',
  'SELECT 1'
);
PREPARE add_integrity_status_stmt FROM @add_integrity_status;
EXECUTE add_integrity_status_stmt;
DEALLOCATE PREPARE add_integrity_status_stmt;

SET @has_credential_ref_index := (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'access_event_history'
    AND INDEX_NAME = 'idx_access_event_credential_received'
);
SET @add_credential_ref_index := IF(
  @has_credential_ref_index = 0,
  'ALTER TABLE access_event_history ADD INDEX idx_access_event_credential_received (credential_ref, received_at)',
  'SELECT 1'
);
PREPARE add_credential_ref_index_stmt FROM @add_credential_ref_index;
EXECUTE add_credential_ref_index_stmt;
DEALLOCATE PREPARE add_credential_ref_index_stmt;

SET @has_collector_target_index := (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'access_event_history'
    AND INDEX_NAME = 'idx_access_event_target_session'
);
SET @add_collector_target_index := IF(
  @has_collector_target_index = 0,
  'ALTER TABLE access_event_history ADD INDEX idx_access_event_target_session (collector_target_id, session_id)',
  'SELECT 1'
);
PREPARE add_collector_target_index_stmt FROM @add_collector_target_index;
EXECUTE add_collector_target_index_stmt;
DEALLOCATE PREPARE add_collector_target_index_stmt;

-- One mutable row per Target rejects replay even after Backend restart.
CREATE TABLE IF NOT EXISTS target_access_status_highwater (
  target_id VARCHAR(64) PRIMARY KEY,
  collector_target_ref VARCHAR(64) NOT NULL,
  source_boot_id VARCHAR(64) NOT NULL,
  source_boot_count BIGINT UNSIGNED NOT NULL,
  status_revision BIGINT UNSIGNED NOT NULL,
  gate_state VARCHAR(16) NOT NULL,
  last_terminal_session_id CHAR(36) NULL,
  last_terminal_event_sequence BIGINT UNSIGNED NULL,
  last_terminal_event_code VARCHAR(64) NULL,
  last_terminal_reason_code VARCHAR(64) NULL,
  last_terminal_credential_ref VARCHAR(32) NULL,
  last_terminal_phase_mask SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  relay_commanded_on TINYINT(1) NOT NULL,
  relay_pin_level TINYINT UNSIGNED NOT NULL,
  integrity_key_id VARCHAR(4) NOT NULL,
  integrity_tag BINARY(16) NOT NULL,
  received_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT chk_target_access_gate_state CHECK (
    gate_state IN ('IDLE','AUTH_PENDING','ARMED','RELAY_HOLD','COOLDOWN')
  ),
  CONSTRAINT chk_target_access_relay_level CHECK (relay_pin_level IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='Authenticated Target status anti-replay high-water';

-- A status heartbeat may recover a terminal result whose individual QoS0
-- canonical event was lost. Keep that summary separate; never synthesize a
-- missing sensor/relay event or timestamp.
CREATE TABLE IF NOT EXISTS access_terminal_summary (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  target_id VARCHAR(64) NOT NULL,
  collector_target_ref VARCHAR(64) NOT NULL,
  source_boot_id VARCHAR(64) NOT NULL,
  source_boot_count BIGINT UNSIGNED NOT NULL,
  terminal_event_sequence BIGINT UNSIGNED NOT NULL,
  session_id CHAR(36) NOT NULL,
  event_code VARCHAR(64) NOT NULL,
  reason_code VARCHAR(64) NOT NULL,
  credential_ref VARCHAR(32) NULL,
  phase_mask SMALLINT UNSIGNED NOT NULL,
  first_status_revision BIGINT UNSIGNED NOT NULL,
  integrity_key_id VARCHAR(4) NOT NULL,
  integrity_tag BINARY(16) NOT NULL,
  received_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_access_terminal_source_position
    (target_id, source_boot_id, terminal_event_sequence),
  INDEX idx_access_terminal_session_received (session_id, received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='Immutable Target-signed terminal summaries for QoS0 recovery';

DROP TRIGGER IF EXISTS access_terminal_summary_no_update;
DROP TRIGGER IF EXISTS access_terminal_summary_no_delete;

DELIMITER //
CREATE TRIGGER access_terminal_summary_no_update
BEFORE UPDATE ON access_terminal_summary
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'access_terminal_summary is append-only';
END//

CREATE TRIGGER access_terminal_summary_no_delete
BEFORE DELETE ON access_terminal_summary
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'access_terminal_summary is append-only';
END//
DELIMITER ;
