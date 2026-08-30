-- Add a server-authoritative mobile role.  The default keeps every existing
-- resident in the least-privileged user experience.
USE smart_gatekeeper;

ALTER TABLE tenants
  ADD COLUMN IF NOT EXISTS mobile_role VARCHAR(24) NOT NULL DEFAULT 'USER'
    COMMENT 'Server-authoritative mobile application role';

ALTER TABLE tenants
  ADD CONSTRAINT chk_tenants_mobile_role
    CHECK (mobile_role IN ('USER', 'TENANT_ADMIN'));
