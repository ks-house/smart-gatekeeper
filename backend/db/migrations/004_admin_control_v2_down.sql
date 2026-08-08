-- Authorized rollback only after all N-1 clients have left the v2 control path.
USE smart_gatekeeper;
DROP TABLE IF EXISTS mobile_control_nonces;
DROP TABLE IF EXISTS force_open_approvals;
