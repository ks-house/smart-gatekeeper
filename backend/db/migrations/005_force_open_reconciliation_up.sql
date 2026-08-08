-- Issue #49: an ambiguous post-broker result must be durably reconciled.
USE smart_gatekeeper;

ALTER TABLE force_open_approvals
  MODIFY status ENUM('PENDING','PUBLISHING','PUBLISHED','EXPIRED','RECONCILIATION_REQUIRED')
  NOT NULL DEFAULT 'PENDING';
