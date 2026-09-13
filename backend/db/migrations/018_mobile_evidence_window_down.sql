-- Evidence and its additive index survive application rollback; old writers
-- omit these nullable columns and old readers continue using receipt semantics.
USE smart_gatekeeper;
SELECT 'mobile_evidence_window_preserved' AS rollback_notice;
