FROM mariadb@sha256:be981e4113326ada8d6004174dd09eeaefc03094037f811182a52d4f2e737350

COPY production_schema.sql /docker-entrypoint-initdb.d/01_production_schema.sql
COPY migrations/002_acl_management_expand_up.sql /opt/smart-gatekeeper/migrations/002_up.sql
COPY migrations/002_acl_management_expand_down.sql /opt/smart-gatekeeper/migrations/002_down.sql
COPY migrations/003_admin_security_up.sql /opt/smart-gatekeeper/migrations/003_up.sql
COPY migrations/003_admin_security_down.sql /opt/smart-gatekeeper/migrations/003_down.sql
COPY migrations/004_admin_control_v2_up.sql /opt/smart-gatekeeper/migrations/004_up.sql
COPY migrations/004_admin_control_v2_down.sql /opt/smart-gatekeeper/migrations/004_down.sql
COPY migrations/005_force_open_reconciliation_up.sql /opt/smart-gatekeeper/migrations/005_up.sql
COPY migrations/005_force_open_reconciliation_down.sql /opt/smart-gatekeeper/migrations/005_down.sql
COPY migrations/006_target_boot_state_up.sql /opt/smart-gatekeeper/migrations/006_up.sql
COPY migrations/006_target_boot_state_down.sql /opt/smart-gatekeeper/migrations/006_down.sql
COPY migrations/007_ops_privacy_up.sql /opt/smart-gatekeeper/migrations/007_up.sql
COPY migrations/007_ops_privacy_down.sql /opt/smart-gatekeeper/migrations/007_down.sql
COPY run_migrations.sh /usr/local/bin/sgk-migrate
RUN chmod 0555 /usr/local/bin/sgk-migrate \
    && chmod 0444 /opt/smart-gatekeeper/migrations/*.sql \
    && chmod 0444 /docker-entrypoint-initdb.d/01_production_schema.sql
