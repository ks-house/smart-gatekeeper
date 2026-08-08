-- Authorized rollback removes only the issue #50 current-boot registry.
USE smart_gatekeeper;
DROP TABLE IF EXISTS target_boot_state;
