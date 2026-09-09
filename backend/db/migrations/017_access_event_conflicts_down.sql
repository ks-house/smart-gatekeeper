-- Application rollback must not erase acknowledged diagnostic evidence.
USE smart_gatekeeper;
SELECT 'access_event_conflicts_preserved' AS rollback_policy;
