-- Add an event-time lookup without changing immutable support payloads or ACK identity.
-- Old rows remain explicitly unindexed and are included by the bounded mobile cursor.
USE smart_gatekeeper;

ALTER TABLE mobile_diagnostic_bundles
  ADD COLUMN IF NOT EXISTS event_first_epoch_ms BIGINT UNSIGNED NULL,
  ADD COLUMN IF NOT EXISTS event_last_epoch_ms BIGINT UNSIGNED NULL,
  ADD COLUMN IF NOT EXISTS captured_epoch_ms BIGINT UNSIGNED NULL,
  ADD COLUMN IF NOT EXISTS evidence_index_version TINYINT UNSIGNED NULL,
  ADD INDEX IF NOT EXISTS idx_mobile_evidence_range (event_last_epoch_ms, event_first_epoch_ms),
  ADD INDEX IF NOT EXISTS idx_mobile_evidence_capture (captured_epoch_ms),
  ADD INDEX IF NOT EXISTS idx_mobile_evidence_phone_cursor (credential_ref, id),
  ADD INDEX IF NOT EXISTS idx_mobile_evidence_phone_range (credential_ref, event_last_epoch_ms, event_first_epoch_ms);
