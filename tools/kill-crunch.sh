#!/usr/bin/env bash
set -u

# This script lives at <project>/.crunch/tools/kill-crunch.sh.
crunch_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT_ROOT=$(cd "$crunch_ROOT/.." && pwd)
UNIT_SUFFIX=$(printf '%s' "$PROJECT_ROOT" | sha256sum | cut -c1-12)
UNIT_NAME="crunch-worker-${UNIT_SUFFIX}"

if systemctl --user is-active --quiet "$UNIT_NAME"; then
    systemctl --user stop "$UNIT_NAME"
    echo "Stopped ${UNIT_NAME}.service."
fi

find_project_processes() {
    local pattern="$1"
    local pid cwd
    while read -r pid; do
        [ -n "$pid" ] || continue
        [ "$pid" -eq "$$" ] 2>/dev/null && continue
        cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
        # crunch may inherit .crunch as its cwd; codex.py runs from the
        # containing project. Both locations identify this worker instance.
        { [ "$cwd" = "$PROJECT_ROOT" ] || [ "$cwd" = "$crunch_ROOT" ]; } \
            && printf '%s\n' "$pid"
    done < <(pgrep -f "$pattern" 2>/dev/null || true)
}

codex_pids=$(find_project_processes 'codex\.py' || true)
crunch_pids=$(find_project_processes 'crunch\.py' || true)

if [ -z "$codex_pids$crunch_pids" ]; then
    echo "No crunch or Codex processes found for $PROJECT_ROOT."
    exit 0
fi

for pid in $codex_pids $crunch_pids; do
    if kill "$pid" 2>/dev/null; then
        echo "Sent TERM to process $pid."
    fi
done
