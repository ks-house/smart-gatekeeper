-- Issue #49 rollback.  This is intentionally a schema-only rollback and must
-- be authorized by incident/change control because it removes audit evidence.
USE smart_gatekeeper;
DROP TRIGGER IF EXISTS admin_audit_no_update;
DROP TRIGGER IF EXISTS admin_audit_no_delete;
DROP TABLE IF EXISTS admin_audit;
