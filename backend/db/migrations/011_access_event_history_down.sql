-- N-1 application rollback is compatible with this additive table.  Preserve
-- collected audit evidence instead of deleting it during a software rollback;
-- a separately reviewed retention procedure must own any future erasure.
USE smart_gatekeeper;

SELECT 1 AS access_event_history_preserved;
