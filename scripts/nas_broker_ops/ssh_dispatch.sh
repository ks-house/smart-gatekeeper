#!/bin/sh
set -eu
case "$SSH_ORIGINAL_COMMAND" in
  status|receive|stage|apply|rollback|diagnose)
    exec /usr/bin/sudo -n /usr/local/lib/smart-gatekeeper-broker-ops/bin/broker_ops.py "$SSH_ORIGINAL_COMMAND"
    ;;
  *) printf '%s\n' 'Unsupported broker maintenance command' >&2; exit 126 ;;
esac
