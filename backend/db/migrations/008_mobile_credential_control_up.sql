-- AndroidKeyStore credential-signed manual_remote replay ledger.
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS mobile_credential_control_nonces (
  credential_id CHAR(32) NOT NULL,
  nonce_hash CHAR(64) NOT NULL,
  action VARCHAR(32) NOT NULL,
  expires_at BIGINT UNSIGNED NOT NULL,
  consumed_at BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (credential_id, nonce_hash, action),
  INDEX idx_mobile_credential_nonce_expiry (expires_at),
  CONSTRAINT fk_mobile_control_credential
    FOREIGN KEY (credential_id) REFERENCES credentials(credential_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
