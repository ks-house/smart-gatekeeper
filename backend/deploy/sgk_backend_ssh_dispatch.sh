#!/usr/bin/env bash
# Forced-command bridge from the unprivileged SSH deploy account to two exact
# root deployment wrapper invocations admitted by sudoers.

set -euo pipefail

readonly WRAPPER="/volume1/docker/smart-gatekeeper-backend/bin/sgk_backend_deploy.sh"
readonly REQUESTED="${SSH_ORIGINAL_COMMAND:-}"

case "$REQUESTED" in
  apply|status)
    exec sudo -n "$WRAPPER" "$REQUESTED"
    ;;
  *)
    printf 'allowed commands: apply or status\n' >&2
    exit 126
    ;;
esac
