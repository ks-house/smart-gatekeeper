-- Rollback is intentionally fail-closed while an ambiguous physical operation exists.
USE smart_gatekeeper;

ALTER TABLE force_open_approvals
  MODIFY status ENUM('PENDING','PUBLISHING','PUBLISHED','EXPIRED')
  NOT NULL DEFAULT 'PENDING';
