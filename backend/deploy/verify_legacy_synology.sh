#!/usr/bin/env bash
# Read-only verification after bootstrap_legacy_synology.sh.
set -euo pipefail

readonly DEPLOY_BASE="/volume1/docker/smart-gatekeeper-backend"
readonly SECRET_DIR="${DEPLOY_BASE}/secrets"
readonly API_STATE_DIR="${DEPLOY_BASE}/api_state"
readonly MIGRATION_BACKUP_DIR="${DEPLOY_BASE}/migration_backups"
readonly LEGACY_PROJECT="smart_gatekeeper"
readonly LEGACY_API="gatekeeper-api"
readonly LEGACY_DB="gatekeeper-db"
readonly MARIADB_VOLUME="smart_gatekeeper_mariadb_data"
readonly API_STATE_VOLUME="smart-gatekeeper-api-state"
readonly APK_VOLUME="smart-gatekeeper-apk-artifacts"
readonly APK_SOURCE="/volume1/docker/smartbox_ota/gatekeeper_apk"
readonly MIGRATION_BACKUP_VOLUME="smart-gatekeeper-migration-backups"
readonly TARGET_CONFIG_SHA256="c5668365bd130ec42c7f49aafc53491b1a6ad3a3eb4858f3215b83de3505ece9"

DOCKER_BIN=""

die() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}

(( EUID == 0 )) || die "run as root through owner-approved sudo"
for command in stat sha256sum awk sort; do
  command -v "$command" >/dev/null 2>&1 || die "required command is missing: $command"
done

resolve_docker() {
  local discovered candidate
  discovered="$(command -v docker 2>/dev/null || true)"
  for candidate in \
    "$discovered" \
    /usr/local/bin/docker \
    /var/packages/ContainerManager/target/usr/bin/docker \
    /var/packages/Docker/target/usr/bin/docker; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    DOCKER_BIN="$candidate"
    break
  done
  [[ -n "$DOCKER_BIN" ]] || die "Docker CLI was not found in PATH or a supported Synology package path"
}
resolve_docker
readonly DOCKER_BIN

docker() {
  "$DOCKER_BIN" "$@"
}

require_file_contract() {
  local path="$1" expected_uid="$2" expected_gid="$3" expected_mode="$4"
  [[ -f "$path" && ! -L "$path" && -s "$path" ]] || die "missing non-empty regular file: $path"
  [[ "$(stat -c '%u' "$path")" == "$expected_uid" ]] || die "file owner mismatch: $path"
  [[ "$(stat -c '%g' "$path")" == "$expected_gid" ]] || die "file group mismatch: $path"
  [[ "$(stat -c '%a' "$path")" == "$expected_mode" ]] || die "file mode mismatch: $path"
}

require_directory_contract() {
  local path="$1" expected_uid="$2" expected_gid="$3" expected_mode="$4"
  [[ -d "$path" && ! -L "$path" ]] || die "missing regular directory: $path"
  [[ "$(stat -c '%u' "$path")" == "$expected_uid" ]] || die "directory owner mismatch: $path"
  [[ "$(stat -c '%g' "$path")" == "$expected_gid" ]] || die "directory group mismatch: $path"
  [[ "$(stat -c '%a' "$path")" == "$expected_mode" ]] || die "directory mode mismatch: $path"
}

require_bind_volume() {
  local name="$1" expected_device="$2" driver type option device
  docker volume inspect "$name" >/dev/null 2>&1 || die "missing Docker volume: $name"
  driver="$(docker volume inspect --format '{{.Driver}}' "$name")"
  type="$(docker volume inspect --format '{{index .Options "type"}}' "$name")"
  option="$(docker volume inspect --format '{{index .Options "o"}}' "$name")"
  device="$(docker volume inspect --format '{{index .Options "device"}}' "$name")"
  [[ "$driver" == "local" && "$type" == "none" && "$option" == "bind" && \
     "$device" == "$expected_device" ]] || die "Docker bind-volume contract mismatch: $name"
}

require_running_legacy_container() {
  local name="$1" running project
  running="$(docker inspect --format '{{.State.Running}}' "$name")" || die "missing legacy container: $name"
  project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$name")"
  [[ "$running" == "true" && "$project" == "$LEGACY_PROJECT" ]] || \
    die "legacy container is not running under the expected project: $name"
}

db_scalar() {
  local query="$1"
  docker exec "$LEGACY_DB" sh -eu -c '
    : "${MYSQL_ROOT_PASSWORD:?}"
    export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
    exec mariadb --batch --skip-column-names --user=root smart_gatekeeper -e "$1"
  ' sh "$query"
}

require_directory_contract "$DEPLOY_BASE" 0 0 711
require_directory_contract "$SECRET_DIR" 0 0 700
require_directory_contract "$API_STATE_DIR" 10001 10001 700
require_directory_contract "$MIGRATION_BACKUP_DIR" 0 0 700

required_secrets=(
  db_root_password db_password mqtt_password mqtt_ca.pem api_key ops_hmac_key
  access_event_ref_keys.json
  command_signing_scalar admin_identities.json personal_admin_password
  acl_enrollment_auth.json acl_legacy_ref_hmac_key acl_admin_api_key
  acl_target_auth.json acl_signing_scalar
)
for secret in "${required_secrets[@]}"; do
  if [[ "$secret" == "db_root_password" ]]; then
    require_file_contract "${SECRET_DIR}/${secret}" 0 0 600
  else
    require_file_contract "${SECRET_DIR}/${secret}" 0 10001 640
  fi
done
require_file_contract "${DEPLOY_BASE}/runtime.env" 0 0 600
require_file_contract "${API_STATE_DIR}/target_config.json" 10001 10001 600
[[ "$(stat -c '%s' "${API_STATE_DIR}/target_config.json")" == "135" ]] || die "target config size mismatch"
[[ "$(sha256sum "${API_STATE_DIR}/target_config.json" | awk '{print $1}')" == "$TARGET_CONFIG_SHA256" ]] || \
  die "target config digest mismatch"

expected_runtime_keys="$(printf '%s\n' \
  MQTT_HOST MQTT_PORT MQTT_USER DB_RUNTIME_USER COMMAND_TARGET_ID COMMAND_TENANT_ID COMMAND_DOOR_ID \
  COMMAND_SIGNING_KEY_ID ADMIN_TRUSTED_PROXY_IPS ACL_SIGNING_KEY_ID \
  HA_BRIDGE_ENABLED HA_BRIDGE_ALLOW_MANUAL_REMOTE HA_BRIDGE_STATUS_MAX_AGE_SECONDS \
  ACCESS_SIGNED_STATUS_READINESS_REQUIRED ACCESS_STATUS_MAX_AGE_SECONDS \
  TARGET_RELAY_OFF_PIN_LEVEL \
  ACL_PERSONAL_ENROLLMENT_ENABLED ACL_PERSONAL_TENANT_ID ACL_PERSONAL_DOOR_ID \
  SGK_API_LOOPBACK_PORT SGK_SECRET_DIR SGK_PUBLIC_READY_URL MARIADB_DATA_VOLUME \
  API_STATE_VOLUME APK_ARTIFACTS_VOLUME MIGRATION_BACKUPS_VOLUME | sort)"
actual_runtime_keys="$(
  awk -F= '
    /^[A-Z][A-Z0-9_]*=/ { print $1; next }
    { exit 42 }
  ' "${DEPLOY_BASE}/runtime.env" | sort
)" || die "runtime.env contains a malformed line"
[[ "$actual_runtime_keys" == "$expected_runtime_keys" ]] || die "runtime.env key set mismatch"

runtime_mqtt_port="$(awk -F= '
  $1 == "MQTT_PORT" {
    if (++matches > 1) exit 42
    value = substr($0, length($1) + 2)
  }
  END {
    if (matches != 1) exit 43
    printf "%s", value
  }
' "${DEPLOY_BASE}/runtime.env")" || die "runtime MQTT_PORT is missing or duplicated"
[[ "$runtime_mqtt_port" =~ ^[0-9]{1,5}$ ]] || die "runtime MQTT_PORT must be numeric"
(( 10#$runtime_mqtt_port >= 1 && 10#$runtime_mqtt_port <= 65535 )) || \
  die "runtime MQTT_PORT is outside 1-65535"
[[ "$runtime_mqtt_port" != "1883" ]] || die "runtime MQTT_PORT must use the TLS listener"

runtime_signed_status_cutover="$(awk -F= '
  $1 == "ACCESS_SIGNED_STATUS_READINESS_REQUIRED" {
    if (++matches > 1) exit 42
    value = substr($0, length($1) + 2)
  }
  END {
    if (matches != 1) exit 43
    printf "%s", value
  }
' "${DEPLOY_BASE}/runtime.env")" || \
  die "signed-status readiness cutover is missing or duplicated"
[[ "$runtime_signed_status_cutover" == "true" || \
   "$runtime_signed_status_cutover" == "false" ]] || \
  die "signed-status readiness cutover must be true or false"

runtime_access_status_max_age="$(awk -F= '
  $1 == "ACCESS_STATUS_MAX_AGE_SECONDS" {
    if (++matches > 1) exit 42
    value = substr($0, length($1) + 2)
  }
  END {
    if (matches != 1) exit 43
    printf "%s", value
  }
' "${DEPLOY_BASE}/runtime.env")" || \
  die "access status max age is missing or duplicated"
[[ "$runtime_access_status_max_age" =~ ^([1-9]|10)$ ]] || \
  die "access status max age must be an integer from 1 through 10"

runtime_relay_off_pin_level="$(awk -F= '
  $1 == "TARGET_RELAY_OFF_PIN_LEVEL" {
    if (++matches > 1) exit 42
    value = substr($0, length($1) + 2)
  }
  END {
    if (matches != 1) exit 43
    printf "%s", value
  }
' "${DEPLOY_BASE}/runtime.env")" || \
  die "Target relay OFF pin level is missing or duplicated"
[[ "$runtime_relay_off_pin_level" =~ ^[01]$ ]] || \
  die "Target relay OFF pin level must be 0 or 1"

legacy_mqtt_port="$(
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$LEGACY_API" |
    awk -F= '
      $1 == "MQTT_PORT" {
        if (++matches > 1) exit 42
        value = substr($0, length($1) + 2)
      }
      END {
        if (matches != 1) exit 43
        printf "%s", value
      }
    '
)" || die "legacy MQTT_PORT is missing or duplicated"
[[ "$runtime_mqtt_port" == "$legacy_mqtt_port" ]] || \
  die "runtime MQTT_PORT does not match the retained legacy endpoint"

require_running_legacy_container "$LEGACY_API"
require_running_legacy_container "$LEGACY_DB"
docker volume inspect "$MARIADB_VOLUME" >/dev/null 2>&1 || die "existing MariaDB volume is missing"
[[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/mysql"}}{{.Name}}{{end}}{{end}}' "$LEGACY_DB")" == "$MARIADB_VOLUME" ]] || \
  die "legacy DB volume mapping changed"
require_bind_volume "$API_STATE_VOLUME" "$API_STATE_DIR"
require_bind_volume "$APK_VOLUME" "$APK_SOURCE"
require_bind_volume "$MIGRATION_BACKUP_VOLUME" "$MIGRATION_BACKUP_DIR"

required_tables="$(db_scalar "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='smart_gatekeeper' AND table_name IN ('tenants','acl_tenants','credentials','credential_door_grants','acl_snapshots','target_acl_acks');")"
[[ "$required_tables" == "6" ]] || die "required legacy DB/ACL tables are incomplete: ${required_tables}/6"
tenant_columns="$(db_scalar "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='smart_gatekeeper' AND table_name='tenants' AND column_name IN ('is_active','tenant_uuid','credential_mode');")"
[[ "$tenant_columns" == "3" ]] || die "required tenant compatibility columns are incomplete: ${tenant_columns}/3"

schema_ledger_present="$(db_scalar "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='smart_gatekeeper' AND table_name='schema_migrations';")"
if [[ "$schema_ledger_present" == "1" ]]; then
  schema_versions="$(db_scalar "SELECT COALESCE(GROUP_CONCAT(version ORDER BY version SEPARATOR ','),'none') FROM schema_migrations;")"
else
  schema_versions="absent"
fi

tenants_total="$(db_scalar "SELECT COUNT(*) FROM tenants;")"
tenants_active="$(db_scalar "SELECT COUNT(*) FROM tenants WHERE is_active=1;")"
tenants_public_key="$(db_scalar "SELECT COUNT(*) FROM tenants WHERE credential_mode='public_key';")"
active_credentials="$(db_scalar "SELECT COUNT(*) FROM credentials WHERE status='ACTIVE';")"
active_grants="$(db_scalar "SELECT COUNT(*) FROM credential_door_grants WHERE revoked_at IS NULL;")"
acl_snapshots="$(db_scalar "SELECT COUNT(*) FROM acl_snapshots;")"
latest_acl_version="$(db_scalar "SELECT COALESCE(MAX(acl_version),0) FROM acl_snapshots;")"
applied_acks="$(db_scalar "SELECT COUNT(*) FROM target_acl_acks WHERE status='APPLIED';")"
latest_applied_ack="$(db_scalar "SELECT COALESCE(MAX(acl_version),0) FROM target_acl_acks WHERE status='APPLIED';")"

identity_report="$(
  docker exec -i "$LEGACY_API" python - <<'PY'
import hmac
import json
import os
import sys

import pymysql


def same(left, right):
    return isinstance(left, str) and isinstance(right, str) and hmac.compare_digest(left, right)


tenant_id = os.getenv("ACL_PERSONAL_TENANT_ID", "").strip() or os.getenv("COMMAND_TENANT_ID", "").strip()
door_id = os.getenv("ACL_PERSONAL_DOOR_ID", "").strip() or os.getenv("COMMAND_DOOR_ID", "").strip()
target_id = os.getenv("COMMAND_TARGET_ID", "").strip()
target_auth = json.loads(os.environ["ACL_TARGET_AUTH_JSON"])
authorization = target_auth.get(target_id, {})

connection = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    database=os.getenv("DB_NAME", "smart_gatekeeper"),
    cursorclass=pymysql.cursors.DictCursor,
)
try:
    with connection.cursor() as cursor:
        def one(statement, parameters):
            cursor.execute(statement, parameters)
            return cursor.fetchone()

        legacy_tenant = one(
            "SELECT credential_mode FROM tenants "
            "WHERE tenant_uuid=%s AND is_active=1",
            (tenant_id,),
        )
        acl_tenant = one(
            "SELECT status FROM acl_tenants WHERE tenant_id=%s",
            (tenant_id,),
        )
        active_credential = one(
            "SELECT credential_id FROM credentials "
            "WHERE tenant_id=%s AND status='ACTIVE' ORDER BY credential_id LIMIT 1",
            (tenant_id,),
        )
        active_grant = one(
            "SELECT g.credential_id FROM credential_door_grants g "
            "JOIN credentials c ON c.credential_id=g.credential_id "
            "WHERE g.tenant_id=%s AND g.door_id=%s AND g.revoked_at IS NULL "
            "AND g.permissions=1 AND c.tenant_id=%s AND c.status='ACTIVE' "
            "ORDER BY g.credential_id LIMIT 1",
            (tenant_id, door_id, tenant_id),
        )
        door_state = one(
            "SELECT last_version FROM acl_door_state "
            "WHERE tenant_id=%s AND door_id=%s",
            (tenant_id, door_id),
        )
        snapshot = one(
            "SELECT acl_version, sha256 FROM acl_snapshots "
            "WHERE tenant_id=%s AND door_id=%s "
            "ORDER BY acl_version DESC LIMIT 1",
            (tenant_id, door_id),
        )
        ack = one(
            "SELECT acl_version, sha256 FROM target_acl_acks "
            "WHERE tenant_id=%s AND door_id=%s AND target_id=%s AND status='APPLIED' "
            "ORDER BY acl_version DESC LIMIT 1",
            (tenant_id, door_id, target_id),
        )
finally:
    connection.close()

checks = {
    "identity_feature_flags": (
        os.getenv("ACL_MANAGEMENT_ENABLED", "").lower() == "true"
        and os.getenv("ACL_PERSONAL_ENROLLMENT_ENABLED", "").lower() == "true"
    ),
    "identity_target_auth_exact": (
        bool(tenant_id and door_id and target_id)
        and same(authorization.get("tenant_id"), tenant_id)
        and same(authorization.get("door_id"), door_id)
        and bool(authorization.get("key"))
    ),
    "identity_legacy_tenant_dual_or_public": (
        legacy_tenant is not None
        and legacy_tenant.get("credential_mode") in {"dual", "public_key"}
    ),
    "identity_acl_tenant_active": (
        acl_tenant is not None and acl_tenant.get("status") == "ACTIVE"
    ),
    "identity_active_credential_grant_exact": (
        active_credential is not None
        and active_grant is not None
        and same(active_credential.get("credential_id"), active_grant.get("credential_id"))
    ),
    "identity_snapshot_ack_exact": (
        snapshot is not None
        and ack is not None
        and int(snapshot.get("acl_version", 0)) == int(ack.get("acl_version", -1))
        and same(snapshot.get("sha256"), ack.get("sha256"))
        and door_state is not None
        and int(door_state.get("last_version", 0)) == int(snapshot.get("acl_version", -1))
    ),
}
checks["identity_all_exact"] = all(checks.values())
for name, passed in checks.items():
    print(f"{name}={'yes' if passed else 'no'}")
PY
)" || die "exact legacy personal tenant/door/Target correlation query failed"
if [[ "$identity_report" != *"identity_all_exact=yes"* ]]; then
  printf '%s\n' "$identity_report"
  die "exact legacy personal tenant/door/Target correlation is incomplete"
fi

printf '[PASS] bootstrapped NAS layout and legacy DB/ACL read-only preflight\n'
printf 'legacy_containers=running_unchanged\n'
printf 'secret_file_contracts=%s_passed\n' "${#required_secrets[@]}"
printf 'runtime_env_key_contract=passed\n'
printf 'external_volume_contracts=3_passed\n'
printf 'target_config_sha256=%s\n' "$TARGET_CONFIG_SHA256"
printf 'schema_migrations=%s\n' "$schema_versions"
printf 'tenants_total=%s tenants_active=%s tenants_public_key=%s\n' \
  "$tenants_total" "$tenants_active" "$tenants_public_key"
printf 'active_credentials=%s active_grants=%s\n' "$active_credentials" "$active_grants"
printf 'acl_snapshots=%s latest_acl_version=%s\n' "$acl_snapshots" "$latest_acl_version"
printf 'applied_acl_acks=%s latest_applied_ack=%s\n' "$applied_acks" "$latest_applied_ack"
printf '%s\n' "$identity_report"
printf 'legacy_lookup_disable_gate=exact_identity_path_present_owner_decision_required\n'
printf 'next_gate=off-NAS backup restore before migration/cutover\n'
