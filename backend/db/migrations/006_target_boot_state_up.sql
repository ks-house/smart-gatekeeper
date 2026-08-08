-- Authenticated per-Target current-boot identity for signed command recovery.
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS target_boot_state (
  target_id VARCHAR(64) NOT NULL PRIMARY KEY,
  boot_id CHAR(32) NOT NULL,
  boot_count BIGINT UNSIGNED NOT NULL,
  updated_at BIGINT UNSIGNED NOT NULL,
  CONSTRAINT chk_target_boot_count CHECK (boot_count > 0),
  CONSTRAINT chk_target_boot_id CHECK (boot_id REGEXP '^[0-9a-f]{32}$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
