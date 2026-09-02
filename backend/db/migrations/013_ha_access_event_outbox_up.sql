-- Transactional Home Assistant projection outbox. A canonical Target access
-- event and its pending HA payload are committed together, so an API restart
-- cannot leave an authenticated database row permanently absent from HA.
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS ha_access_event_outbox (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  event_id CHAR(36) NOT NULL,
  target_id VARCHAR(64) NOT NULL,
  payload_json VARCHAR(512) NOT NULL,
  publish_attempts INT UNSIGNED NOT NULL DEFAULT 0,
  last_attempt_at DATETIME(3) NULL,
  published_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_ha_access_event_outbox_event (event_id),
  INDEX idx_ha_access_event_outbox_pending (published_at, id),
  CONSTRAINT chk_ha_access_event_outbox_payload CHECK (JSON_VALID(payload_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='Durable at-least-once Home Assistant access-event projection';
