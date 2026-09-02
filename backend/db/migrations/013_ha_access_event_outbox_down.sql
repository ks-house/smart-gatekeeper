-- Preserve delivery evidence and any pending HA projections across an N-1
-- Backend rollback. Older code ignores this additive table; a later N restart
-- resumes the ordered outbox without silently discarding access history.
USE smart_gatekeeper;

SELECT 1 AS ha_access_event_outbox_preserved;
