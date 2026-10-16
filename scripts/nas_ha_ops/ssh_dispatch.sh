#!/bin/sh
set -eu
case "$SSH_ORIGINAL_COMMAND" in
  status|diagnose|refresh-logging|adopt|verify|rollback)
    exec /usr/bin/sudo -n /usr/local/lib/smart-gatekeeper-ha-ops/bin/ha_ops.py "$SSH_ORIGINAL_COMMAND"
    ;;
  *) printf "%s\n" "Unsupported HA maintenance command" >&2; exit 126 ;;
esac
