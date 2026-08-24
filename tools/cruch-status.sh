#!/usr/bin/env bash
set -euo pipefail

CRUNCH_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT_ROOT=$(cd "$CRUNCH_ROOT/.." && pwd)
UNIT_SUFFIX=$(printf '%s' "$PROJECT_ROOT" | sha256sum | cut -c1-12)
UNIT_NAME="crunch-worker-${UNIT_SUFFIX}.service"
LOCK_PATH="$CRUNCH_ROOT/logs/crunch.lock"

# The systemd unit is the authoritative runtime boundary used by
# start-crunch.sh. Avoid treating the persistent lock-file's existence as
# evidence that a worker is running.
if command -v systemctl >/dev/null 2>&1 \
    && systemctl --user is-active --quiet "$UNIT_NAME" 2>/dev/null; then
    printf '%s\n' 'cruch is running'
    exit 0
fi

# Fallback for environments without a reachable user systemd manager. Check
# for a live project worker while also requiring ownership of the flock.
if [ -r "$LOCK_PATH" ] && ! flock -n "$LOCK_PATH" -c ':' 2>/dev/null; then
    if ps -eo args= | awk -v root="$CRUNCH_ROOT" \
        'index($0, "python") && index($0, root "/tools/crunch.py") { found=1 } END { exit(found ? 0 : 1) }'; then
        printf '%s\n' 'cruch is running'
        exit 0
    fi
fi

printf '%s\n' 'cruch is stopped'
