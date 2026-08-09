-- Production baseline schema. Test/demo records belong only in test fixtures.
CREATE DATABASE IF NOT EXISTS smart_gatekeeper
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE smart_gatekeeper;

CREATE TABLE IF NOT EXISTS tenants (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(50) NOT NULL,
  unit_number VARCHAR(20) NOT NULL,
  phone VARCHAR(20) DEFAULT NULL,
  ble_device_mac VARCHAR(17) DEFAULT NULL UNIQUE,
  auth_key VARCHAR(64) DEFAULT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_ble_mac (ble_device_mac),
  INDEX idx_unit (unit_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS access_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  tenant_id INT DEFAULT NULL,
  auth_method VARCHAR(20) NOT NULL DEFAULT 'BLE',
  is_success BOOLEAN NOT NULL,
  distance_mm INT DEFAULT NULL,
  failure_reason VARCHAR(255) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_access_logs_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE SET NULL,
  INDEX idx_created_at (created_at),
  INDEX idx_tenant_access (tenant_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
