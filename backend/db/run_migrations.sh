#!/bin/sh
set -eu

mode="${1:-up}"
target="${2:-}"
case "$mode:$target" in
  up:0[0-9][0-9]|down:001) ;;
  *) echo "[ERROR] migration mode/target is not admitted" >&2; exit 2 ;;
esac

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_MIGRATION_USER:?DB_MIGRATION_USER is required}"
: "${DB_MIGRATION_PASSWORD_FILE:?DB_MIGRATION_PASSWORD_FILE is required}"
: "${MIGRATION_SOURCE_COMMIT:?MIGRATION_SOURCE_COMMIT is required}"
: "${MIGRATION_BACKUP_DIR:?MIGRATION_BACKUP_DIR is required}"
[ "$DB_NAME" = "smart_gatekeeper" ] || {
  echo "[ERROR] migration database identity mismatch" >&2; exit 2;
}

case "$MIGRATION_SOURCE_COMMIT" in
  *[!0-9a-f]*|'') echo "[ERROR] source commit must be lowercase hex" >&2; exit 2 ;;
esac
[ "${#MIGRATION_SOURCE_COMMIT}" -eq 40 ] || {
  echo "[ERROR] source commit must be exact 40-hex" >&2; exit 2;
}
[ -r "$DB_MIGRATION_PASSWORD_FILE" ] || {
  echo "[ERROR] migration password secret is unreadable" >&2; exit 2;
}
mkdir -p "$MIGRATION_BACKUP_DIR"
[ -w "$MIGRATION_BACKUP_DIR" ] || {
  echo "[ERROR] migration backup directory is not writable" >&2; exit 2;
}

password=$(tr -d '\r\n' < "$DB_MIGRATION_PASSWORD_FILE")
[ -n "$password" ] || { echo "[ERROR] empty migration password" >&2; exit 2; }
case "$password" in *'"'*|*'\'*)
  echo "[ERROR] migration password contains unsupported option-file characters" >&2; exit 2;;
esac
option_file=$(mktemp /tmp/sgk-migrate.XXXXXX.cnf)
backup_tmp=""
lock_dir="$MIGRATION_BACKUP_DIR/.schema-migration-lock"
mkdir "$lock_dir" || {
  echo "[ERROR] migration filesystem lock is already held" >&2; exit 3;
}
cleanup() {
  rm -f "$option_file"
  [ -z "$backup_tmp" ] || rm -f "$backup_tmp"
  rmdir "$lock_dir" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
chmod 600 "$option_file"
printf '[client]\npassword="%s"\n' "$password" > "$option_file"
unset password

client() {
  mariadb --defaults-extra-file="$option_file" \
    --host="$DB_HOST" --port="$DB_PORT" --user="$DB_MIGRATION_USER" "$@" "$DB_NAME"
}

timestamp=$(date -u +%Y%m%dT%H%M%S%NZ)
backup_base="$MIGRATION_BACKUP_DIR/pre-migration-${MIGRATION_SOURCE_COMMIT}-${timestamp}-${mode}-${target}-$$.sql"
[ ! -e "$backup_base" ] && [ ! -e "${backup_base}.sha256" ] || {
  echo "[ERROR] pre-migration backup identity collision" >&2; exit 4;
}
backup_tmp="${backup_base}.tmp"
mariadb-dump --defaults-extra-file="$option_file" \
  --host="$DB_HOST" --port="$DB_PORT" --user="$DB_MIGRATION_USER" \
  --single-transaction --routines --triggers "$DB_NAME" > "$backup_tmp"
[ -s "$backup_tmp" ] || { echo "[ERROR] pre-migration backup is empty" >&2; exit 4; }
backup_digest=$(sha256sum "$backup_tmp" | awk '{print $1}')
printf '%s  %s\n' "$backup_digest" "$(basename "$backup_base")" \
  > "${backup_base}.sha256.tmp"
chmod 400 "$backup_tmp" "${backup_base}.sha256.tmp"
mv "$backup_tmp" "$backup_base"
backup_tmp=""
mv "${backup_base}.sha256.tmp" "${backup_base}.sha256"
sync "$backup_base" "${backup_base}.sha256"

client -e "CREATE TABLE IF NOT EXISTS schema_migrations (
  version CHAR(3) PRIMARY KEY,
  script_sha256 CHAR(64) NOT NULL,
  source_commit CHAR(40) NOT NULL,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;"

canonical_sha() {
  tr -d '\r' < "$1" | sha256sum | awk '{print $1}'
}

apply_up() {
  version="$1"; file="$2"; digest=$(canonical_sha "$file")
  existing=$(client --batch --skip-column-names -e \
    "SELECT script_sha256 FROM schema_migrations WHERE version='${version}';")
  if [ -n "$existing" ]; then
    [ "$existing" = "$digest" ] || {
      echo "[ERROR] applied migration ${version} digest mismatch" >&2; exit 5;
    }
    return
  fi
  client < "$file"
  client -e "INSERT INTO schema_migrations(version,script_sha256,source_commit)
    VALUES ('${version}','${digest}','${MIGRATION_SOURCE_COMMIT}');"
}

apply_down() {
  version="$1"; file="$2"
  existing=$(client --batch --skip-column-names -e \
    "SELECT COUNT(*) FROM schema_migrations WHERE version='${version}';")
  [ "$existing" = "0" ] && return
  client < "$file"
  client -e "DELETE FROM schema_migrations WHERE version='${version}';"
}

if [ "$mode" = "up" ]; then
  expected=2
  for file in /opt/smart-gatekeeper/migrations/[0-9][0-9][0-9]_up.sql; do
    [ -f "$file" ] || { echo "[ERROR] no migration scripts found" >&2; exit 2; }
    version=${file##*/}; version=${version%%_*}
    [ "$version" -le "$target" ] || continue
    [ "$version" -eq "$expected" ] || {
      echo "[ERROR] non-contiguous migration sequence at ${version}" >&2; exit 2;
    }
    apply_up "$version" "$file"
    expected=$((expected + 1))
  done
  [ $((expected - 1)) -eq "$target" ] || {
    echo "[ERROR] target migration ${target} is unavailable" >&2; exit 2;
  }
else
  current=$(client --batch --skip-column-names -e \
    "SELECT COALESCE(MAX(CAST(version AS UNSIGNED)),1) FROM schema_migrations;")
  while [ "$current" -ge 2 ]; do
    version=$(printf '%03d' "$current")
    file="/opt/smart-gatekeeper/migrations/${version}_down.sql"
    [ -f "$file" ] || { echo "[ERROR] rollback script ${version} is unavailable" >&2; exit 2; }
    apply_down "$version" "$file"
    current=$((current - 1))
  done
fi

echo "[PASS] schema migration mode=${mode} target=${target} backup=${backup_base}"
