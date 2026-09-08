-- Preserve observed history when rolling back application code.
USE smart_gatekeeper;
SELECT 'target_reliability_history_preserved' AS rollback_policy;
