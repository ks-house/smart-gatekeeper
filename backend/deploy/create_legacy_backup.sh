#!/usr/bin/env bash
# Create a consistent root-only NAS dump plus a temporary owner export bundle.
set -euo pipefail

readonly DEPLOY_BASE="/volume1/docker/smart-gatekeeper-backend"
readonly BACKUP_DIR="${DEPLOY_BASE}/migration_backups"
readonly LEGACY_API="gatekeeper-api"
readonly LEGACY_DB="gatekeeper-db"

INVENTORY_SCRIPT=""
EXPORT_DIR=""
EXPORT_OWNER=""
DOCKER_BIN=""
STAGING=""

die() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}

usage() {
  printf 'usage: sudo %s --inventory-script /ABSOLUTE/PATH --export-dir /ABSOLUTE/HOME --export-owner USER\n' "$0" >&2
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
    --inventory-script) (( $# >= 2 )) || usage; INVENTORY_SCRIPT="$2"; shift 2 ;;
    --export-dir) (( $# >= 2 )) || usage; EXPORT_DIR="$2"; shift 2 ;;
    --export-owner) (( $# >= 2 )) || usage; EXPORT_OWNER="$2"; shift 2 ;;
    *) usage ;;
  esac
done

(( EUID == 0 )) || die "run as root through owner-approved sudo"
[[ "$INVENTORY_SCRIPT" == /* && -f "$INVENTORY_SCRIPT" && ! -L "$INVENTORY_SCRIPT" ]] || \
  die "inventory script must be an absolute regular file"
[[ "$EXPORT_DIR" == /var/services/homes/* || "$EXPORT_DIR" == /volume1/homes/* ]] || \
  die "export directory must be the owner's Synology home"
[[ -d "$EXPORT_DIR" ]] || die "export directory is missing"
[[ "$EXPORT_OWNER" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || die "invalid export owner"
for command in install mktemp sha256sum stat awk tar date id chown chmod sync realpath cmp rm mv; do
  command -v "$command" >/dev/null 2>&1 || die "required command is missing: $command"
done
export_uid="$(id -u "$EXPORT_OWNER")" || die "export owner does not exist"
export_gid="$(id -g "$EXPORT_OWNER")" || die "export owner group does not exist"

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
  [[ -n "$DOCKER_BIN" ]] || die "Docker CLI was not found"
}
resolve_docker
readonly DOCKER_BIN

docker() {
  "$DOCKER_BIN" "$@"
}

resolved_export_dir="$(realpath "$EXPORT_DIR")" || die "cannot resolve export directory"
[[ "$resolved_export_dir" == /var/services/homes/* || "$resolved_export_dir" == /volume1/homes/* ]] || \
  die "resolved export directory is outside Synology homes"
[[ "$(stat -c '%u' "$resolved_export_dir")" == "$export_uid" ]] || \
  die "export directory owner does not match export owner"
EXPORT_DIR="$resolved_export_dir"

for container in "$LEGACY_API" "$LEGACY_DB"; do
  [[ "$(docker inspect --format '{{.State.Running}}' "$container")" == "true" ]] || \
    die "legacy container is not running: $container"
done

source_commit="$(
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$LEGACY_API" |
    awk -F= '$1 == "BUILD_SHA" { if (++found > 1) exit 42; print substr($0, 11) } END { if (found != 1) exit 43 }'
)" || die "legacy BUILD_SHA is missing or duplicated"
[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || die "legacy BUILD_SHA is not exact 40-hex"

install -d -o root -g root -m 700 "$BACKUP_DIR"
STAGING="$(mktemp -d "${BACKUP_DIR}/.backup.XXXXXX")"
chmod 700 "$STAGING"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_id="pre-cutover-${timestamp}-$$"
final_dir="${BACKUP_DIR}/${backup_id}"
[[ ! -e "$final_dir" ]] || die "backup identity already exists"

dump_path="${STAGING}/database.sql"
inventory_path="${STAGING}/source-inventory.json"
inventory_before="${STAGING}/source-inventory.before.json"
inventory_after="${STAGING}/source-inventory.after.json"
metadata_path="${STAGING}/metadata.env"

docker exec -i "$LEGACY_API" python - < "$INVENTORY_SCRIPT" > "$inventory_before"
[[ -s "$inventory_before" ]] || die "pre-dump source inventory is empty"
docker exec -i "$LEGACY_API" python -m json.tool >/dev/null < "$inventory_before" || \
  die "pre-dump source inventory is not valid JSON"

docker exec "$LEGACY_DB" sh -eu -c '
  : "${MYSQL_ROOT_PASSWORD:?}"
  export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
  exec mariadb-dump --user=root --single-transaction --quick \
    --routines --triggers --events --hex-blob --default-character-set=utf8mb4 \
    --skip-comments smart_gatekeeper
' > "$dump_path"
[[ -s "$dump_path" ]] || die "logical dump is empty"
chmod 400 "$dump_path"

docker exec -i "$LEGACY_API" python - < "$INVENTORY_SCRIPT" > "$inventory_after"
[[ -s "$inventory_after" ]] || die "post-dump source inventory is empty"
docker exec -i "$LEGACY_API" python -m json.tool >/dev/null < "$inventory_after" || \
  die "post-dump source inventory is not valid JSON"
cmp -s "$inventory_before" "$inventory_after" || \
  die "required database tables changed during backup; retry without accepting this dump"
mv "$inventory_before" "$inventory_path"
rm -f -- "$inventory_after"
chmod 400 "$inventory_path"

completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
dump_sha256="$(sha256sum "$dump_path" | awk '{print $1}')"
dump_bytes="$(stat -c '%s' "$dump_path")"
{
  printf 'BACKUP_ID=%s\n' "$backup_id"
  printf 'SOURCE_COMMIT=%s\n' "$source_commit"
  printf 'COMPLETED_AT=%s\n' "$completed_at"
  printf 'DUMP_SHA256=%s\n' "$dump_sha256"
  printf 'DUMP_BYTES=%s\n' "$dump_bytes"
} > "$metadata_path"
chmod 400 "$metadata_path"

mv "$STAGING" "$final_dir"
STAGING=""
chown -R root:root "$final_dir"
chmod 700 "$final_dir"
chmod 400 "$final_dir"/*
sync "$final_dir"/*

root_bundle="${BACKUP_DIR}/${backup_id}.tar.gz"
tar -C "$final_dir" -czf "$root_bundle" database.sql source-inventory.json metadata.env
chmod 400 "$root_bundle"
root_bundle_sha256="$(sha256sum "$root_bundle" | awk '{print $1}')"
printf '%s  %s\n' "$root_bundle_sha256" "$(basename "$root_bundle")" \
  > "${root_bundle}.sha256"
chmod 400 "${root_bundle}.sha256"
sync "$root_bundle" "${root_bundle}.sha256"

export_bundle="${EXPORT_DIR}/${backup_id}.tar.gz"
export_sidecar="${export_bundle}.sha256"
[[ ! -e "$export_bundle" && ! -e "$export_sidecar" ]] || die "owner export already exists"
install -o "$export_uid" -g "$export_gid" -m 600 "$root_bundle" "$export_bundle"
install -o "$export_uid" -g "$export_gid" -m 600 "${root_bundle}.sha256" "$export_sidecar"

printf '[PASS] consistent legacy backup and temporary owner export created\n'
printf 'backup_id=%s\n' "$backup_id"
printf 'source_commit=%s\n' "$source_commit"
printf 'completed_at=%s\n' "$completed_at"
printf 'dump_bytes=%s\n' "$dump_bytes"
printf 'bundle_sha256=%s\n' "$root_bundle_sha256"
printf 'owner_export_bundle=%s\n' "$export_bundle"
printf 'owner_export_sidecar=%s\n' "$export_sidecar"
printf 'legacy_containers=running_unchanged\n'
printf 'next_gate=authenticated transfer encryption and isolated WSL restore\n'
