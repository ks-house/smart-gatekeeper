-- Roll back only the additive mobile-role projection.
USE smart_gatekeeper;

ALTER TABLE tenants
  DROP CONSTRAINT IF EXISTS chk_tenants_mobile_role,
  DROP COLUMN IF EXISTS mobile_role;
