-- N-1 Backend code ignores these additive columns/tables. Preserve immutable
-- evidence and replay high-water during software rollback; retention owns any
-- later erasure.
USE smart_gatekeeper;

SELECT 1 AS authenticated_access_evidence_preserved;
