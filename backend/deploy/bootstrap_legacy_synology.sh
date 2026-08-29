#!/usr/bin/env bash
# One-time, non-cutover preparation for the observed DS423+ legacy deployment.
# This script never stops/restarts containers and never opens the MariaDB volume.
set -euo pipefail

readonly DEPLOY_BASE="/volume1/docker/smart-gatekeeper-backend"
readonly SECRET_DIR="${DEPLOY_BASE}/secrets"
readonly API_STATE_DIR="${DEPLOY_BASE}/api_state"
readonly MIGRATION_BACKUP_DIR="${DEPLOY_BASE}/migration_backups"
readonly LEGACY_PROJECT="smart_gatekeeper"
readonly LEGACY_API="gatekeeper-api"
readonly LEGACY_DB="gatekeeper-db"
readonly MARIADB_VOLUME="smart_gatekeeper_mariadb_data"
readonly APK_SOURCE="/volume1/docker/smartbox_ota/gatekeeper_apk"
readonly API_STATE_VOLUME="smart-gatekeeper-api-state"
readonly APK_VOLUME="smart-gatekeeper-apk-artifacts"
readonly MIGRATION_BACKUP_VOLUME="smart-gatekeeper-migration-backups"
readonly TARGET_CONFIG_SHA256="c5668365bd130ec42c7f49aafc53491b1a6ad3a3eb4858f3215b83de3505ece9"

PUBLIC_READY_URL=""
STAGING=""
DOCKER_BIN=""

die() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}

usage() {
  printf 'usage: sudo %s --public-ready-url https://HOST:PORT/ready\n' "$0" >&2
  exit 2
}

cleanup() {
  if [[ -n "$STAGING" && -d "$STAGING" ]]; then
    rm -rf -- "$STAGING"
  fi
}
trap cleanup EXIT INT TERM

while (( $# > 0 )); do
  case "$1" in
    --public-ready-url)
      (( $# == 2 )) || usage
      PUBLIC_READY_URL="$2"
      shift 2
      ;;
    *) usage ;;
  esac
done

(( EUID == 0 )) || die "run as root through owner-approved sudo"
[[ "$PUBLIC_READY_URL" =~ ^https://[^[:space:]]+/ready$ ]] || \
  die "public ready URL must be an HTTPS URL ending in /ready"

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

for command in install mktemp sha256sum stat awk cmp chown chmod; do
  command -v "$command" >/dev/null 2>&1 || die "required command is missing: $command"
done

container_project() {
  docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$1"
}

get_env() {
  local container="$1" key="$2" value
  value="$(
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container" |
      awk -v wanted="${key}=" '
        index($0, wanted) == 1 {
          if (++matches > 1) exit 42
          value = substr($0, length(wanted) + 1)
        }
        END {
          if (matches != 1) exit 43
          printf "%s", value
        }
      '
  )" || die "missing or duplicate legacy environment key: ${container}:${key}"
  printf '%s' "$value"
}

require_nonempty() {
  local label="$1" value="$2"
  [[ -n "$value" ]] || die "legacy value is empty: $label"
}

require_safe_runtime() {
  local label="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z0-9._,:/@+%-]*$ ]] || die "unsafe runtime value: $label"
}

stage_secret() {
  local name value staged
  name="$1"
  value="$2"
  staged="${STAGING}/${name}"
  require_nonempty "$name" "$value"
  (umask 077; printf '%s' "$value" > "$staged")
}

install_staged_file() {
  local staged="$1" destination="$2" owner="$3" group="$4" mode="$5"
  if [[ -e "$destination" ]]; then
    [[ -f "$destination" && ! -L "$destination" ]] || \
      die "refusing non-regular existing destination: $destination"
    cmp -s -- "$staged" "$destination" || \
      die "existing destination differs; refusing overwrite: $destination"
    chown "$owner:$group" "$destination"
    chmod "$mode" "$destination"
    return
  fi
  install -o "$owner" -g "$group" -m "$mode" "$staged" "$destination"
}

ensure_bind_volume() {
  local name="$1" device="$2" driver type option bound_device
  [[ -d "$device" ]] || die "bind source directory is missing: $device"
  if docker volume inspect "$name" >/dev/null 2>&1; then
    driver="$(docker volume inspect --format '{{.Driver}}' "$name")"
    type="$(docker volume inspect --format '{{index .Options "type"}}' "$name")"
    option="$(docker volume inspect --format '{{index .Options "o"}}' "$name")"
    bound_device="$(docker volume inspect --format '{{index .Options "device"}}' "$name")"
    [[ "$driver" == "local" && "$type" == "none" && "$option" == "bind" && \
       "$bound_device" == "$device" ]] || die "existing volume mapping mismatch: $name"
    return
  fi
  docker volume create --driver local --opt type=none --opt o=bind \
    --opt "device=$device" "$name" >/dev/null
}

docker inspect "$LEGACY_API" >/dev/null 2>&1 || die "legacy API container is missing"
docker inspect "$LEGACY_DB" >/dev/null 2>&1 || die "legacy DB container is missing"
[[ "$(container_project "$LEGACY_API")" == "$LEGACY_PROJECT" ]] || die "legacy API project mismatch"
[[ "$(container_project "$LEGACY_DB")" == "$LEGACY_PROJECT" ]] || die "legacy DB project mismatch"
docker volume inspect "$MARIADB_VOLUME" >/dev/null 2>&1 || die "existing MariaDB volume is missing"
[[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/mysql"}}{{.Name}}{{end}}{{end}}' "$LEGACY_DB")" == "$MARIADB_VOLUME" ]] || \
  die "legacy DB persistent-volume mapping changed"
[[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/gatekeeper_apk"}}{{.Source}}{{end}}{{end}}' "$LEGACY_API")" == "$APK_SOURCE" ]] || \
  die "legacy APK bind mapping changed"

install -d -o root -g root -m 711 "$DEPLOY_BASE"
install -d -o root -g root -m 700 "$SECRET_DIR" "$MIGRATION_BACKUP_DIR"
install -d -o 10001 -g 10001 -m 700 "$API_STATE_DIR"
STAGING="$(mktemp -d "${DEPLOY_BASE}/.bootstrap.XXXXXX")"
chmod 700 "$STAGING"

db_password="$(get_env "$LEGACY_API" DB_PASSWORD)"
db_container_password="$(get_env "$LEGACY_DB" MYSQL_PASSWORD)"
[[ -n "$db_password" && "$db_password" == "$db_container_password" ]] || \
  die "API and DB runtime passwords do not match"
unset db_container_password

stage_secret db_root_password "$(get_env "$LEGACY_DB" MYSQL_ROOT_PASSWORD)"
stage_secret db_password "$db_password"
unset db_password
stage_secret mqtt_password "$(get_env "$LEGACY_API" MQTT_PASSWORD)"
stage_secret api_key "$(get_env "$LEGACY_API" GATEKEEPER_API_KEY)"
stage_secret ops_hmac_key "$(get_env "$LEGACY_API" OPS_HMAC_KEY)"
command_scalar="$(get_env "$LEGACY_API" COMMAND_SIGNING_PRIVATE_SCALAR_HEX)"
[[ "$command_scalar" =~ ^[0-9A-Fa-f]{64}$ ]] || die "command signing scalar is not 64-hex"
stage_secret command_signing_scalar "$command_scalar"
unset command_scalar

admin_identities="$(get_env "$LEGACY_API" ADMIN_MTLS_IDENTITIES_JSON)"
if [[ -z "$admin_identities" ]]; then
  admin_identities='{}'
fi
stage_secret admin_identities.json "$admin_identities"
unset admin_identities
stage_secret personal_admin_password "$(get_env "$LEGACY_API" PERSONAL_ADMIN_PASSWORD)"
stage_secret acl_enrollment_auth.json "$(get_env "$LEGACY_API" ACL_ENROLLMENT_AUTH_JSON)"
stage_secret acl_legacy_ref_hmac_key "$(get_env "$LEGACY_API" ACL_LEGACY_REF_HMAC_KEY)"
stage_secret acl_admin_api_key "$(get_env "$LEGACY_API" ACL_ADMIN_API_KEY)"
stage_secret acl_target_auth.json "$(get_env "$LEGACY_API" ACL_TARGET_AUTH_JSON)"
acl_scalar="$(get_env "$LEGACY_API" ACL_SIGNING_PRIVATE_SCALAR_HEX)"
[[ "$acl_scalar" =~ ^[0-9A-Fa-f]{64}$ ]] || die "ACL signing scalar is not 64-hex"
stage_secret acl_signing_scalar "$acl_scalar"
unset acl_scalar

docker cp "${LEGACY_API}:/run/secrets/mqtt_ca.pem" "${STAGING}/mqtt_ca.pem" >/dev/null
[[ -s "${STAGING}/mqtt_ca.pem" ]] || die "legacy MQTT CA copy is empty"
chmod 600 "${STAGING}/mqtt_ca.pem"

docker cp "${LEGACY_API}:/app/target_config.json" "${STAGING}/target_config.json" >/dev/null
[[ "$(sha256sum "${STAGING}/target_config.json" | awk '{print $1}')" == "$TARGET_CONFIG_SHA256" ]] || \
  die "legacy target config digest changed"
[[ "$(stat -c '%s' "${STAGING}/target_config.json")" == "135" ]] || \
  die "legacy target config size changed"

for staged in "$STAGING"/*; do
  case "$(basename "$staged")" in
    target_config.json) ;;
    db_root_password)
      install_staged_file "$staged" "${SECRET_DIR}/$(basename "$staged")" \
        root root 600
      ;;
    *)
      # Local Compose file secrets are bind mounts. Keep the containing host
      # directory root-only while granting only the non-root API runtime group
      # read access to the exact files it consumes.
      install_staged_file "$staged" "${SECRET_DIR}/$(basename "$staged")" \
        root 10001 640
      ;;
  esac
done

target_destination="${API_STATE_DIR}/target_config.json"
if [[ -e "$target_destination" ]]; then
  cmp -s -- "${STAGING}/target_config.json" "$target_destination" || \
    die "existing API target config differs; refusing overwrite"
else
  install -o 10001 -g 10001 -m 600 "${STAGING}/target_config.json" "$target_destination"
fi
chown 10001:10001 "$target_destination"
chmod 600 "$target_destination"

ensure_bind_volume "$API_STATE_VOLUME" "$API_STATE_DIR"
ensure_bind_volume "$APK_VOLUME" "$APK_SOURCE"
ensure_bind_volume "$MIGRATION_BACKUP_VOLUME" "$MIGRATION_BACKUP_DIR"

runtime_keys=(
  MQTT_HOST MQTT_USER DB_USER COMMAND_TARGET_ID COMMAND_TENANT_ID COMMAND_DOOR_ID
  COMMAND_SIGNING_KEY_ID ADMIN_TRUSTED_PROXY_IPS ACL_SIGNING_KEY_ID
  HA_BRIDGE_ENABLED HA_BRIDGE_ALLOW_MANUAL_REMOTE HA_BRIDGE_STATUS_MAX_AGE_SECONDS
  ACL_PERSONAL_ENROLLMENT_ENABLED ACL_PERSONAL_TENANT_ID ACL_PERSONAL_DOOR_ID
)
declare -A runtime=()
for key in "${runtime_keys[@]}"; do
  runtime["$key"]="$(get_env "$LEGACY_API" "$key")"
  require_safe_runtime "$key" "${runtime[$key]}"
done
runtime[DB_RUNTIME_USER]="${runtime[DB_USER]}"
unset 'runtime[DB_USER]'
[[ "${runtime[DB_RUNTIME_USER]}" =~ ^[A-Za-z0-9_]{1,64}$ ]] || die "unsafe DB runtime user"
[[ -n "${runtime[MQTT_HOST]}" && -n "${runtime[MQTT_USER]}" ]] || die "MQTT identity is empty"
for key in COMMAND_TARGET_ID COMMAND_TENANT_ID COMMAND_DOOR_ID; do
  [[ -n "${runtime[$key]}" ]] || die "command identity is empty: $key"
done
for key in COMMAND_SIGNING_KEY_ID ACL_SIGNING_KEY_ID HA_BRIDGE_STATUS_MAX_AGE_SECONDS; do
  [[ "${runtime[$key]}" =~ ^[1-9][0-9]*$ ]] || die "runtime integer is invalid: $key"
done
for key in HA_BRIDGE_ENABLED HA_BRIDGE_ALLOW_MANUAL_REMOTE ACL_PERSONAL_ENROLLMENT_ENABLED; do
  [[ "${runtime[$key]}" == "true" || "${runtime[$key]}" == "false" ]] || \
    die "runtime boolean is invalid: $key"
done
if [[ -z "${runtime[ADMIN_TRUSTED_PROXY_IPS]}" ]]; then
  runtime[ADMIN_TRUSTED_PROXY_IPS]="127.0.0.1"
fi

runtime_staged="${STAGING}/runtime.env"
(
  umask 077
  {
    printf 'MQTT_HOST=%s\n' "${runtime[MQTT_HOST]}"
    printf 'MQTT_USER=%s\n' "${runtime[MQTT_USER]}"
    printf 'DB_RUNTIME_USER=%s\n' "${runtime[DB_RUNTIME_USER]}"
    printf 'COMMAND_TARGET_ID=%s\n' "${runtime[COMMAND_TARGET_ID]}"
    printf 'COMMAND_TENANT_ID=%s\n' "${runtime[COMMAND_TENANT_ID]}"
    printf 'COMMAND_DOOR_ID=%s\n' "${runtime[COMMAND_DOOR_ID]}"
    printf 'COMMAND_SIGNING_KEY_ID=%s\n' "${runtime[COMMAND_SIGNING_KEY_ID]}"
    printf 'ADMIN_TRUSTED_PROXY_IPS=%s\n' "${runtime[ADMIN_TRUSTED_PROXY_IPS]}"
    printf 'ACL_SIGNING_KEY_ID=%s\n' "${runtime[ACL_SIGNING_KEY_ID]}"
    printf 'HA_BRIDGE_ENABLED=%s\n' "${runtime[HA_BRIDGE_ENABLED]}"
    printf 'HA_BRIDGE_ALLOW_MANUAL_REMOTE=%s\n' "${runtime[HA_BRIDGE_ALLOW_MANUAL_REMOTE]}"
    printf 'HA_BRIDGE_STATUS_MAX_AGE_SECONDS=%s\n' "${runtime[HA_BRIDGE_STATUS_MAX_AGE_SECONDS]}"
    printf 'ACL_PERSONAL_ENROLLMENT_ENABLED=%s\n' "${runtime[ACL_PERSONAL_ENROLLMENT_ENABLED]}"
    printf 'ACL_PERSONAL_TENANT_ID=%s\n' "${runtime[ACL_PERSONAL_TENANT_ID]}"
    printf 'ACL_PERSONAL_DOOR_ID=%s\n' "${runtime[ACL_PERSONAL_DOOR_ID]}"
    printf 'SGK_API_LOOPBACK_PORT=8000\n'
    printf 'SGK_SECRET_DIR=%s\n' "$SECRET_DIR"
    printf 'SGK_PUBLIC_READY_URL=%s\n' "$PUBLIC_READY_URL"
    printf 'MARIADB_DATA_VOLUME=%s\n' "$MARIADB_VOLUME"
    printf 'API_STATE_VOLUME=%s\n' "$API_STATE_VOLUME"
    printf 'APK_ARTIFACTS_VOLUME=%s\n' "$APK_VOLUME"
    printf 'MIGRATION_BACKUPS_VOLUME=%s\n' "$MIGRATION_BACKUP_VOLUME"
  } > "$runtime_staged"
)
install_staged_file "$runtime_staged" "${DEPLOY_BASE}/runtime.env" 600

printf '[PASS] legacy runtime prepared without cutover\n'
printf 'legacy_containers=unchanged\n'
printf 'mariadb_volume=%s\n' "$MARIADB_VOLUME"
printf 'api_state_volume=%s\n' "$API_STATE_VOLUME"
printf 'apk_artifacts_volume=%s\n' "$APK_VOLUME"
printf 'migration_backups_volume=%s\n' "$MIGRATION_BACKUP_VOLUME"
printf 'target_config_sha256=%s\n' "$TARGET_CONFIG_SHA256"
printf 'next_gate=off-NAS backup restore and read-only DB/ACL preflight\n'
