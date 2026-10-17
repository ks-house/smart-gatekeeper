#!/bin/sh
set -eu
case "$SSH_ORIGINAL_COMMAND" in
 status|submit|result) exec /usr/bin/sudo -n /usr/local/lib/smart-gatekeeper-maintenance/bin/gateway.py "$SSH_ORIGINAL_COMMAND" ;;
 *) printf "%s\n" "Unsupported signed maintenance operation" >&2; exit 126 ;;
esac
