#!/usr/bin/env bash
set -u

# This script lives at <project>/.grindr/tools/kill-grinder.sh.
GRINDR_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT_ROOT=$(cd "$GRINDR_ROOT/.." && pwd)

find_project_processes() {
    local pattern="$1"
    local pid cwd
    while read -r pid; do
        [ -n "$pid" ] || continue
        [ "$pid" -eq "$$" ] 2>/dev/null && continue
        cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
        # grinder may inherit .grindr as its cwd; codex.py runs from the
        # containing project. Both locations identify this worker instance.
        { [ "$cwd" = "$PROJECT_ROOT" ] || [ "$cwd" = "$GRINDR_ROOT" ]; } \
            && printf '%s\n' "$pid"
    done < <(pgrep -f "$pattern" 2>/dev/null || true)
}

codex_pids=$(find_project_processes 'codex\.py' || true)
grinder_pids=$(find_project_processes 'grinder\.py' || true)

if [ -z "$codex_pids$grinder_pids" ]; then
    echo "No grinder or Codex processes found for $PROJECT_ROOT."
    exit 0
fi

for pid in $codex_pids $grinder_pids; do
    if kill "$pid" 2>/dev/null; then
        echo "Sent TERM to process $pid."
    fi
done
