USE smart_gatekeeper;

DROP TRIGGER IF EXISTS privacy_deletion_jobs_no_update;
DROP TRIGGER IF EXISTS privacy_deletion_jobs_no_delete;
DROP TABLE IF EXISTS privacy_deletion_jobs;
