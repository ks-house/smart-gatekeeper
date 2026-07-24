-- smart-gatekeeper Database Schema
-- Last updated: 2026-07-24 (Step 2 Backend Initial Schema)

CREATE DATABASE IF NOT EXISTS smart_gatekeeper CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE smart_gatekeeper;

-- 1. Tenants (세입자 정보) 테이블
CREATE TABLE IF NOT EXISTS tenants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL COMMENT '세입자 이름',
    unit_number VARCHAR(20) NOT NULL COMMENT '동/호수 (예: 101동 202호)',
    phone VARCHAR(20) DEFAULT NULL COMMENT '전화번호',
    ble_device_mac VARCHAR(17) DEFAULT NULL UNIQUE COMMENT '등록 스마트폰/태그 BLE MAC 주소',
    auth_key VARCHAR(64) DEFAULT NULL COMMENT '자격 검증용 보안 토큰 / 암호화 키',
    is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT '출입 허가 활성화 여부',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_ble_mac (ble_device_mac),
    INDEX idx_unit (unit_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='세입자 정보 테이블';

-- 2. AccessLogs (출입 기록) 테이블
CREATE TABLE IF NOT EXISTS access_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    tenant_id INT DEFAULT NULL COMMENT '인증 성공 시 세입자 ID (없으면 NULL)',
    auth_method VARCHAR(20) NOT NULL DEFAULT 'BLE' COMMENT '인증 방식 (BLE, TOF_AUTO, MANUAL, PASSCODE)',
    is_success BOOLEAN NOT NULL COMMENT '출입 성공 여부',
    distance_mm INT DEFAULT NULL COMMENT 'ToF 센서 측정 거리 (mm)',
    failure_reason VARCHAR(255) DEFAULT NULL COMMENT '실패 사유 (등록되지 않은 MAC, 신호 약함 등)',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_access_logs_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE SET NULL,
    INDEX idx_created_at (created_at),
    INDEX idx_tenant_access (tenant_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='출입 기록 데이터';

-- 3. 초기 더미 샘플 세입자 데이터 삽입 (테스트용)
INSERT INTO tenants (name, unit_number, phone, ble_device_mac, auth_key, is_active)
VALUES 
    ('홍길동', '101호', '010-1234-5678', 'AA:BB:CC:DD:EE:01', 'secret_key_101', TRUE),
    ('김철수', '102호', '010-9876-5432', 'AA:BB:CC:DD:EE:02', 'secret_key_102', TRUE)
ON DUPLICATE KEY UPDATE updated_at=CURRENT_TIMESTAMP;
