-- Roll back only the additive account-to-credential link. Existing tenant,
-- credential, ACL and access/audit records remain intact.
USE smart_gatekeeper;

ALTER TABLE tenants
  DROP INDEX IF EXISTS uq_tenants_credential_id,
  DROP COLUMN IF EXISTS credential_id;
