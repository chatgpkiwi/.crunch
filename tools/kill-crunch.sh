#!/usr/bin/env bash
set -u

# This script lives at <crunch-workspace>/tools/kill-crunch.sh.
crunch_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
UNIT_SUFFIX=$(printf '%s' "$crunch_ROOT" | sha256sum | cut -c1-12)
UNIT_NAME="crunch-worker-${UNIT_SUFFIX}"

# Write this before asking systemd to stop the unit.  The worker consults the
# same durable state before every claim and before accepting an agent result.
if [ -f "$crunch_ROOT/database/crunch.db" ]; then
    if ! sqlite3 "$crunch_ROOT/database/crunch.db" "CREATE TABLE IF NOT EXISTS worker_state (worker_id INTEGER PRIMARY KEY CHECK (worker_id = 1), stop_requested INTEGER NOT NULL DEFAULT 0 CHECK (stop_requested IN (0, 1)), active_task_id INTEGER, run_status TEXT NOT NULL DEFAULT 'idle' CHECK (run_status IN ('idle', 'running', 'interrupted')), updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP); INSERT INTO worker_state (worker_id, stop_requested, updated_at) VALUES (1, 1, CURRENT_TIMESTAMP) ON CONFLICT(worker_id) DO UPDATE SET stop_requested = 1, updated_at = CURRENT_TIMESTAMP;"; then
        echo "Unable to record the crunch stop request." >&2
        exit 1
    fi
else
    echo "Crunch database not found; no worker stop state was recorded." >&2
    exit 1
fi

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
        # The worker runs in Crunch and adapters run in one of its isolated
        # child repositories.
        { [ "$cwd" = "$crunch_ROOT" ] || [[ "$cwd" == "$crunch_ROOT/projects/"* ]]; } \
            && printf '%s\n' "$pid"
    done < <(pgrep -f "$pattern" 2>/dev/null || true)
}

codex_pids=$(find_project_processes 'codex\.py' || true)
qwen_pids=$(find_project_processes 'qwen(\.py| )' || true)
crunch_pids=$(find_project_processes 'crunch\.py' || true)

if [ -z "$codex_pids$qwen_pids$crunch_pids" ]; then
    echo "No crunch, Codex, or Qwen processes found for $crunch_ROOT."
    exit 0
fi

for pid in $codex_pids $qwen_pids $crunch_pids; do
    if kill "$pid" 2>/dev/null; then
        echo "Sent TERM to process $pid."
    fi
done
