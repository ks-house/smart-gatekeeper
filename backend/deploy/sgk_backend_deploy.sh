#!/usr/bin/env bash
# Restricted Synology deployment endpoint for signed backend release bundles.
# Install root-owned and invoke through a forced authorized_keys command.

set -Eeuo pipefail
umask 077

readonly DEPLOY_BASE="${SGK_DEPLOY_BASE:-/volume1/docker/smart-gatekeeper-backend}"
readonly BIN_DIR="${DEPLOY_BASE}/bin"
readonly RUNTIME_ENV="${DEPLOY_BASE}/runtime.env"
readonly TRUST_KEY="${DEPLOY_BASE}/trust/release-signing-public.pem"
readonly RELEASES_DIR="${DEPLOY_BASE}/releases"
readonly INCOMING_DIR="${DEPLOY_BASE}/incoming"
readonly LOCK_DIR="${DEPLOY_BASE}/deploy.lock"
readonly CURRENT_RELEASE="${DEPLOY_BASE}/current.release.env"
readonly PROJECT_NAME="smart-gatekeeper-production"
readonly EXPECTED_API_REPOSITORY="ghcr.io/ks-house/smart-gatekeeper-backend"
readonly EXPECTED_DB_REPOSITORY="ghcr.io/ks-house/smart-gatekeeper-db"
readonly EXPECTED_SCHEMA_VERSION="007"
readonly EXPECTED_SCHEMA_SHA256="edde5662c42e65dda82b2e0a9145d64dc4ebfc9fe7a5e5bd44b0b3aae0fe1d79"
readonly MAX_BUNDLE_MIB=8
DOCKER_BIN=""

log() {
  printf '[sgk-backend-deploy] %s\n' "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

resolve_docker() {
  local discovered candidate
  discovered="$(type -P docker 2>/dev/null || true)"
  for candidate in \
    /var/packages/ContainerManager/target/usr/bin/docker \
    /var/packages/Docker/target/usr/bin/docker \
    /usr/local/bin/docker \
    "$discovered"; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    DOCKER_BIN="$candidate"
    break
  done
  [[ -n "$DOCKER_BIN" ]] || \
    die "Docker CLI was not found in a supported Synology package path or PATH"
}

docker() {
  [[ -n "$DOCKER_BIN" ]] || die "Docker CLI was not resolved"
  "$DOCKER_BIN" "$@"
}

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

validate_common_host() {
  for tool in awk chmod cp curl date dd env grep id mkdir mktemp mv \
    openssl rm rmdir sha256sum sleep stat tar; do
    require_command "$tool"
  done
  resolve_docker
  [[ "$(id -u)" == "0" ]] || die "deployment wrapper must run as root through sudo"
  [[ -d "$DEPLOY_BASE" && ! -L "$DEPLOY_BASE" ]] || \
    die "deployment base must be a regular directory"
  [[ "$(stat -c '%u' "$DEPLOY_BASE")" == "0" ]] || \
    die "deployment base must be owned by root"
  local base_mode
  base_mode="$(stat -c '%a' "$DEPLOY_BASE")"
  [[ "$base_mode" == "711" ]] || \
    die "deployment base must be mode 0711 for forced-command traversal"
  [[ -d "$BIN_DIR" && ! -L "$BIN_DIR" ]] || \
    die "deployment bin must be a regular directory"
  [[ "$(stat -c '%u:%g:%a' "$BIN_DIR")" == "0:0:755" ]] || \
    die "deployment bin must be root-owned mode 0755"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is unavailable"
}

validate_root_controlled_file() {
  local path="$1"
  local label="$2"
  [[ -f "$path" && ! -L "$path" ]] || die "$label is missing"
  [[ "$(stat -c '%u' "$path")" == "0" ]] || die "$label must be owned by root"
  local mode
  mode="$(stat -c '%a' "$path")"
  (( (8#$mode & 022) == 0 )) || die "$label must not be group/other writable"
}

declare -A RUNTIME=()
declare -A RELEASE=()

parse_env_file() {
  local path="$1"
  local destination_name="$2"
  local line key value
  local -n destination="$destination_name"

  [[ -f "$path" && ! -L "$path" ]] || die "required regular file is missing: $path"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" != *$'\r'* ]] || die "CR characters are forbidden in $path"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == *=* ]] || die "invalid KEY=VALUE line in $path"
    key="${line%%=*}"
    value="${line#*=}"
    [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "invalid key in $path: $key"
    [[ -z "${destination[$key]+present}" ]] || die "duplicate key in $path: $key"
    [[ "$value" != *[$'\n\t']* ]] || die "control characters are forbidden in $path"
    destination["$key"]="$value"
  done < "$path"
}

require_exact_keys() {
  local destination_name="$1"
  shift
  local -n destination="$destination_name"
  local expected key
  declare -A allowed=()
  for expected in "$@"; do
    allowed["$expected"]=1
    [[ -n "${destination[$expected]+present}" ]] || die "missing key: $expected"
  done
  for key in "${!destination[@]}"; do
    [[ -n "${allowed[$key]+present}" ]] || die "unexpected key: $key"
  done
}

validate_runtime() {
  RUNTIME=()
  validate_root_controlled_file "$RUNTIME_ENV" "runtime environment file"
  parse_env_file "$RUNTIME_ENV" RUNTIME
  require_exact_keys RUNTIME \
    MQTT_HOST MQTT_USER DB_RUNTIME_USER COMMAND_TARGET_ID COMMAND_TENANT_ID COMMAND_DOOR_ID \
    COMMAND_SIGNING_KEY_ID ADMIN_TRUSTED_PROXY_IPS ACL_SIGNING_KEY_ID \
    HA_BRIDGE_ENABLED HA_BRIDGE_ALLOW_MANUAL_REMOTE \
    HA_BRIDGE_STATUS_MAX_AGE_SECONDS ACL_PERSONAL_ENROLLMENT_ENABLED \
    ACL_PERSONAL_TENANT_ID ACL_PERSONAL_DOOR_ID SGK_API_LOOPBACK_PORT \
    SGK_SECRET_DIR SGK_PUBLIC_READY_URL MARIADB_DATA_VOLUME API_STATE_VOLUME \
    APK_ARTIFACTS_VOLUME MIGRATION_BACKUPS_VOLUME

  local key value
  for key in MQTT_HOST MQTT_USER DB_RUNTIME_USER COMMAND_TARGET_ID COMMAND_TENANT_ID COMMAND_DOOR_ID \
    COMMAND_SIGNING_KEY_ID ADMIN_TRUSTED_PROXY_IPS ACL_SIGNING_KEY_ID \
    HA_BRIDGE_STATUS_MAX_AGE_SECONDS ACL_PERSONAL_TENANT_ID ACL_PERSONAL_DOOR_ID; do
    value="${RUNTIME[$key]}"
    [[ "$value" =~ ^[A-Za-z0-9._,:/@+%-]*$ ]] || die "unsafe runtime value: $key"
  done
  [[ -n "${RUNTIME[MQTT_HOST]}" && -n "${RUNTIME[MQTT_USER]}" ]] || \
    die "MQTT_HOST and MQTT_USER must not be empty"
  [[ "${RUNTIME[DB_RUNTIME_USER]}" =~ ^[A-Za-z0-9_]{1,64}$ ]] || \
    die "DB_RUNTIME_USER must be an explicit safe MariaDB account name"
  [[ -n "${RUNTIME[COMMAND_TARGET_ID]}" && -n "${RUNTIME[COMMAND_TENANT_ID]}" && \
     -n "${RUNTIME[COMMAND_DOOR_ID]}" ]] || die "command identity values must not be empty"
  [[ "${RUNTIME[COMMAND_SIGNING_KEY_ID]}" =~ ^[1-9][0-9]*$ ]] || \
    die "COMMAND_SIGNING_KEY_ID must be a positive integer"
  [[ "${RUNTIME[ACL_SIGNING_KEY_ID]}" =~ ^[1-9][0-9]*$ ]] || \
    die "ACL_SIGNING_KEY_ID must be a positive integer"
  [[ "${RUNTIME[HA_BRIDGE_STATUS_MAX_AGE_SECONDS]}" =~ ^[1-9][0-9]*$ ]] || \
    die "HA_BRIDGE_STATUS_MAX_AGE_SECONDS must be a positive integer"
  for key in HA_BRIDGE_ENABLED HA_BRIDGE_ALLOW_MANUAL_REMOTE ACL_PERSONAL_ENROLLMENT_ENABLED; do
    [[ "${RUNTIME[$key]}" == "true" || "${RUNTIME[$key]}" == "false" ]] || \
      die "$key must be true or false"
  done
  [[ "${RUNTIME[SGK_API_LOOPBACK_PORT]}" =~ ^[0-9]{1,5}$ ]] || \
    die "SGK_API_LOOPBACK_PORT must be numeric"
  (( 10#${RUNTIME[SGK_API_LOOPBACK_PORT]} >= 1 && \
     10#${RUNTIME[SGK_API_LOOPBACK_PORT]} <= 65535 )) || \
    die "SGK_API_LOOPBACK_PORT is outside 1-65535"
  [[ "${RUNTIME[SGK_SECRET_DIR]}" == "${DEPLOY_BASE}/secrets" ]] || \
    die "SGK_SECRET_DIR must be ${DEPLOY_BASE}/secrets"
  [[ "${RUNTIME[SGK_PUBLIC_READY_URL]}" =~ ^https://[^[:space:]]+/ready$ ]] || \
    die "SGK_PUBLIC_READY_URL must be an HTTPS /ready URL"
  for key in MARIADB_DATA_VOLUME API_STATE_VOLUME APK_ARTIFACTS_VOLUME MIGRATION_BACKUPS_VOLUME; do
    [[ "${RUNTIME[$key]}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] || \
      die "invalid Docker volume name in $key"
    docker volume inspect "${RUNTIME[$key]}" >/dev/null 2>&1 || \
      die "required Docker volume does not exist: ${RUNTIME[$key]}"
  done

  local secret
  for secret in db_root_password db_password mqtt_password mqtt_ca.pem api_key \
    ops_hmac_key command_signing_scalar admin_identities.json personal_admin_password \
    acl_enrollment_auth.json acl_legacy_ref_hmac_key acl_admin_api_key \
    acl_target_auth.json acl_signing_scalar; do
    local secret_path="${RUNTIME[SGK_SECRET_DIR]}/${secret}"
    [[ -f "$secret_path" && ! -L "$secret_path" && -s "$secret_path" ]] || \
      die "required non-empty regular secret file is missing: $secret"
    local secret_mode
    secret_mode="$(stat -c '%a' "$secret_path")"
    (( (8#$secret_mode & 077) == 0 )) || die "secret file must not grant group/other access: $secret"
  done

  local container project
  while IFS= read -r container; do
    [[ -z "$container" ]] && continue
    project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container")"
    [[ "$project" == "$PROJECT_NAME" ]] || \
      die "MariaDB volume is held by another running project; stop it during first adoption"
  done < <(docker ps -q --filter "volume=${RUNTIME[MARIADB_DATA_VOLUME]}")
  while IFS= read -r container; do
    [[ -z "$container" ]] && continue
    project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container")"
    [[ "$project" == "$PROJECT_NAME" ]] || \
      die "API loopback port is held by another running project; stop it during first adoption"
  done < <(docker ps -q --filter "publish=${RUNTIME[SGK_API_LOOPBACK_PORT]}")
}

validate_release() {
  local release_env="$1"
  local production_compose="$2"
  local synology_compose="$3"

  RELEASE=()
  parse_env_file "$release_env" RELEASE
  require_exact_keys RELEASE FORMAT RELEASE_ID SOURCE_SHA API_IMAGE_REPOSITORY \
    API_IMAGE_DIGEST DB_IMAGE_REPOSITORY DB_IMAGE_DIGEST \
    COMPOSE_PRODUCTION_SHA256 COMPOSE_SYNOLOGY_SHA256 SCHEMA_VERSION \
    SCHEMA_SHA256 CREATED_AT_UTC GITHUB_RUN_ID GITHUB_RUN_ATTEMPT
  [[ "${RELEASE[FORMAT]}" == "sgk-backend-release-v1" ]] || die "unsupported release format"
  [[ "${RELEASE[SOURCE_SHA]}" =~ ^[0-9a-f]{40}$ ]] || die "invalid source SHA"
  [[ "${RELEASE[GITHUB_RUN_ID]}" =~ ^[1-9][0-9]*$ ]] || die "invalid GitHub run ID"
  [[ "${RELEASE[GITHUB_RUN_ATTEMPT]}" =~ ^[1-9][0-9]*$ ]] || die "invalid GitHub run attempt"
  [[ "${RELEASE[RELEASE_ID]}" == \
    "${RELEASE[SOURCE_SHA]}-run${RELEASE[GITHUB_RUN_ID]}-attempt${RELEASE[GITHUB_RUN_ATTEMPT]}" ]] || \
    die "release ID does not match signed provenance"
  [[ "${RELEASE[API_IMAGE_REPOSITORY]}" == "$EXPECTED_API_REPOSITORY" ]] || \
    die "unexpected API repository"
  [[ "${RELEASE[DB_IMAGE_REPOSITORY]}" == "$EXPECTED_DB_REPOSITORY" ]] || \
    die "unexpected DB repository"
  [[ "${RELEASE[API_IMAGE_DIGEST]}" =~ ^[0-9a-f]{64}$ ]] || die "invalid API digest"
  [[ "${RELEASE[DB_IMAGE_DIGEST]}" =~ ^[0-9a-f]{64}$ ]] || die "invalid DB digest"
  [[ "${RELEASE[COMPOSE_PRODUCTION_SHA256]}" =~ ^[0-9a-f]{64}$ ]] || \
    die "invalid production Compose digest"
  [[ "${RELEASE[COMPOSE_SYNOLOGY_SHA256]}" =~ ^[0-9a-f]{64}$ ]] || \
    die "invalid Synology Compose digest"
  [[ "${RELEASE[SCHEMA_VERSION]}" == "$EXPECTED_SCHEMA_VERSION" ]] || \
    die "unexpected schema version"
  [[ "${RELEASE[SCHEMA_SHA256]}" == "$EXPECTED_SCHEMA_SHA256" ]] || \
    die "unexpected schema digest"
  [[ "${RELEASE[CREATED_AT_UTC]}" =~ \
    ^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || \
    die "invalid release timestamp"
  [[ "$(sha256_file "$production_compose")" == "${RELEASE[COMPOSE_PRODUCTION_SHA256]}" ]] || \
    die "production Compose digest mismatch"
  [[ "$(sha256_file "$synology_compose")" == "${RELEASE[COMPOSE_SYNOLOGY_SHA256]}" ]] || \
    die "Synology Compose digest mismatch"
}

compose_for_release() {
  local release_dir="$1"
  shift
  env \
    API_IMAGE_REPOSITORY="${RELEASE[API_IMAGE_REPOSITORY]}" \
    API_IMAGE_DIGEST="${RELEASE[API_IMAGE_DIGEST]}" \
    DB_IMAGE_REPOSITORY="${RELEASE[DB_IMAGE_REPOSITORY]}" \
    DB_IMAGE_DIGEST="${RELEASE[DB_IMAGE_DIGEST]}" \
    BUILD_SHA="${RELEASE[SOURCE_SHA]}" \
    "$DOCKER_BIN" compose --project-name "$PROJECT_NAME" --env-file "$RUNTIME_ENV" \
      -f "${release_dir}/compose.production.yml" \
      -f "${release_dir}/compose.synology.yml" "$@"
}

wait_ready() {
  local url="$1"
  local label="$2"
  local attempts="${3:-30}"
  local count
  for (( count = 1; count <= attempts; count++ )); do
    if curl --fail --silent --show-error --max-time 5 "$url" >/dev/null 2>&1; then
      log "$label readiness passed"
      return 0
    fi
    sleep 2
  done
  die "$label readiness failed: $url"
}

verify_running_image() {
  local release_dir="$1"
  local service="$2"
  local expected_reference="$3"
  local container expected_image_id running_image_id
  container="$(compose_for_release "$release_dir" ps -q "$service")"
  [[ -n "$container" ]] || die "running container is missing for service: $service"
  expected_image_id="$(docker image inspect --format '{{.Id}}' "$expected_reference")"
  running_image_id="$(docker inspect --format '{{.Image}}' "$container")"
  [[ -n "$expected_image_id" && "$running_image_id" == "$expected_image_id" ]] || \
    die "running image identity mismatch for service: $service"
}

record_failure() {
  local stage_dir="${1:-}"
  local status="${2:-1}"
  local failed_at
  failed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local failure_file="${DEPLOY_BASE}/last-failure.evidence"
  {
    printf 'status=failed\n'
    printf 'failed_at_utc=%s\n' "$failed_at"
    printf 'exit_code=%s\n' "$status"
    printf 'release_id=%s\n' "${RELEASE[RELEASE_ID]:-unverified}"
    if [[ -n "$stage_dir" && -f "${stage_dir}/release.tar.gz" ]]; then
      printf 'received_bundle_sha256=%s\n' "$(sha256_file "${stage_dir}/release.tar.gz")"
    fi
  } > "$failure_file"
  if [[ "${RELEASE[RELEASE_ID]:-}" =~ \
    ^[0-9a-f]{40}-run[1-9][0-9]*-attempt[1-9][0-9]*$ && \
    -d "${RELEASES_DIR}/${RELEASE[RELEASE_ID]}" ]]; then
    cp "$failure_file" "${RELEASES_DIR}/${RELEASE[RELEASE_ID]}/deployment.evidence"
  fi
  log "deployment failed; database rollback was not attempted"
}

cleanup_apply() {
  local stage_dir="$1"
  local status="$2"
  trap - EXIT
  if (( status != 0 )); then
    record_failure "$stage_dir" "$status"
  fi
  rm -rf -- "$stage_dir"
  rmdir -- "$LOCK_DIR" 2>/dev/null || true
  exit "$status"
}

apply_release() {
  validate_common_host
  validate_root_controlled_file "$TRUST_KEY" "release trust key"
  validate_runtime
  mkdir -p "$RELEASES_DIR" "$INCOMING_DIR"
  chmod 711 "$DEPLOY_BASE"
  chmod 700 "$RELEASES_DIR" "$INCOMING_DIR"
  mkdir "$LOCK_DIR" 2>/dev/null || die "another deployment is active; inspect $LOCK_DIR"

  local stage_dir
  stage_dir="$(mktemp -d "${INCOMING_DIR}/release.XXXXXXXX")"
  trap 'cleanup_apply "'"$stage_dir"'" "$?"' EXIT
  local bundle="${stage_dir}/release.tar.gz"
  dd bs=1048576 count=$((MAX_BUNDLE_MIB + 1)) of="$bundle" 2>/dev/null
  (( $(stat -c '%s' "$bundle") > 0 )) || die "release bundle is empty"
  (( $(stat -c '%s' "$bundle") <= MAX_BUNDLE_MIB * 1048576 )) || \
    die "release bundle exceeds ${MAX_BUNDLE_MIB} MiB"

  local -a members=()
  mapfile -t members < <(tar -tzf "$bundle")
  [[ "${#members[@]}" == "4" ]] || die "release bundle must contain exactly four files"
  local expected
  for expected in release.env release.env.sig compose.production.yml compose.synology.yml; do
    printf '%s\n' "${members[@]}" | grep -Fqx -- "$expected" || \
      die "release bundle member is missing: $expected"
  done
  while IFS= read -r listing; do
    [[ "${listing:0:1}" == "-" ]] || die "release bundle may contain regular files only"
  done < <(tar -tvzf "$bundle")

  local extracted="${stage_dir}/extracted"
  mkdir "$extracted"
  tar -xzf "$bundle" -C "$extracted" --no-same-owner --no-same-permissions \
    release.env release.env.sig compose.production.yml compose.synology.yml
  openssl dgst -sha256 -verify "$TRUST_KEY" -signature "${extracted}/release.env.sig" \
    "${extracted}/release.env" >/dev/null 2>&1 || die "release signature verification failed"
  validate_release "${extracted}/release.env" "${extracted}/compose.production.yml" \
    "${extracted}/compose.synology.yml"

  local release_dir="${RELEASES_DIR}/${RELEASE[RELEASE_ID]}"
  [[ ! -e "$release_dir" ]] || die "release ID already exists: ${RELEASE[RELEASE_ID]}"
  mkdir "$release_dir"
  cp "${extracted}/release.env" "${extracted}/release.env.sig" \
    "${extracted}/compose.production.yml" "${extracted}/compose.synology.yml" "$release_dir/"
  chmod 600 "$release_dir"/*

  compose_for_release "$release_dir" config --quiet
  local api_image="${RELEASE[API_IMAGE_REPOSITORY]}@sha256:${RELEASE[API_IMAGE_DIGEST]}"
  local db_image="${RELEASE[DB_IMAGE_REPOSITORY]}@sha256:${RELEASE[DB_IMAGE_DIGEST]}"
  docker pull "$api_image"
  docker pull "$db_image"
  compose_for_release "$release_dir" up -d db
  compose_for_release "$release_dir" run --rm migrate
  compose_for_release "$release_dir" up -d --no-deps api
  verify_running_image "$release_dir" db "$db_image"
  verify_running_image "$release_dir" api "$api_image"
  wait_ready "http://127.0.0.1:${RUNTIME[SGK_API_LOOPBACK_PORT]}/ready" "loopback API"
  wait_ready "${RUNTIME[SGK_PUBLIC_READY_URL]}" "public reverse proxy"

  local bundle_sha
  bundle_sha="$(sha256_file "$bundle")"
  {
    printf 'status=deployed\n'
    printf 'release_id=%s\n' "${RELEASE[RELEASE_ID]}"
    printf 'source_sha=%s\n' "${RELEASE[SOURCE_SHA]}"
    printf 'api_image=%s\n' "$api_image"
    printf 'db_image=%s\n' "$db_image"
    printf 'bundle_sha256=%s\n' "$bundle_sha"
    printf 'deployed_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'loopback_ready=passed\n'
    printf 'public_ready=passed\n'
  } > "${release_dir}/deployment.evidence"
  cp "${release_dir}/release.env" "${CURRENT_RELEASE}.tmp"
  mv "${CURRENT_RELEASE}.tmp" "$CURRENT_RELEASE"
  log "deployment passed: ${RELEASE[RELEASE_ID]}"
  cat "${release_dir}/deployment.evidence"
}

show_status() {
  validate_common_host
  if [[ ! -f "$CURRENT_RELEASE" ]]; then
    printf 'status=not-deployed\n'
    return 0
  fi
  RELEASE=()
  parse_env_file "$CURRENT_RELEASE" RELEASE
  local release_id="${RELEASE[RELEASE_ID]:-invalid}"
  [[ "$release_id" =~ ^[0-9a-f]{40}-run[1-9][0-9]*-attempt[1-9][0-9]*$ ]] || \
    die "current release descriptor is invalid"
  local evidence="${RELEASES_DIR}/${release_id}/deployment.evidence"
  [[ -f "$evidence" && ! -L "$evidence" ]] || die "current deployment evidence is missing"
  cat "$evidence"
}

main() {
  local requested
  if (( $# > 1 )); then
    die "exactly one deployment command is allowed"
  fi
  requested="${1:-${SSH_ORIGINAL_COMMAND:-}}"
  case "$requested" in
    apply) apply_release ;;
    status) show_status ;;
    *) die "allowed commands: apply or status" ;;
  esac
}

main "$@"
