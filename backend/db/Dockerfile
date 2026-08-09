FROM mariadb@sha256:be981e4113326ada8d6004174dd09eeaefc03094037f811182a52d4f2e737350

COPY schema.sql /docker-entrypoint-initdb.d/01_schema.sql
COPY migrations/002_acl_management_expand_up.sql /docker-entrypoint-initdb.d/02_acl.sql
COPY migrations/003_admin_security_up.sql /docker-entrypoint-initdb.d/03_admin.sql
COPY migrations/004_admin_control_v2_up.sql /docker-entrypoint-initdb.d/04_admin_v2.sql
COPY migrations/005_force_open_reconciliation_up.sql /docker-entrypoint-initdb.d/05_reconciliation.sql
COPY migrations/006_target_boot_state_up.sql /docker-entrypoint-initdb.d/06_boot.sql
COPY migrations/007_ops_privacy_up.sql /docker-entrypoint-initdb.d/07_privacy.sql
