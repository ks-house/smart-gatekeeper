USE smart_gatekeeper;

DROP TRIGGER IF EXISTS privacy_deletion_jobs_no_update;
DROP TRIGGER IF EXISTS privacy_deletion_jobs_no_delete;
DROP TRIGGER IF EXISTS support_export_consents_revoke_only;
DROP TRIGGER IF EXISTS support_export_consents_no_delete;
DROP TABLE IF EXISTS support_export_consents;
DROP TABLE IF EXISTS privacy_deletion_jobs;
