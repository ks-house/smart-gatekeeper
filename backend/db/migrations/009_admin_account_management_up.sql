-- Bind one legacy registration row to its public mobile credential so an
-- administrator can revoke access before deleting personal account data.
USE smart_gatekeeper;

ALTER TABLE tenants
  ADD COLUMN IF NOT EXISTS credential_id CHAR(32) NULL
    COMMENT 'Public credential linked to this supervised mobile registration',
  ADD UNIQUE INDEX IF NOT EXISTS uq_tenants_credential_id (credential_id);
