#!/usr/bin/env bash
# Bootstrap .crunch on this machine. Run from any directory:
#   /path/to/project/.crunch/setup.sh

set -euo pipefail

CRUNCH_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DATABASE_DIR="$CRUNCH_ROOT/database"
DATABASE="$DATABASE_DIR/crunch.db"
SCHEMA="$DATABASE_DIR/schema.sql"
CURRENT_USER=$(id -un)

require_command() {
    local command_name=$1

    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Error: required command not found on PATH: %s\n' "$command_name" >&2
        exit 1
    fi
}

require_command python3
require_command sqlite3
require_command git
require_command systemctl
require_command loginctl

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)'; then
    printf 'Error: Python 3.8 or newer is required.\n' >&2
    exit 1
fi

if [ ! -f "$SCHEMA" ]; then
    printf 'Error: .crunch schema not found: %s\n' "$SCHEMA" >&2
    exit 1
fi

mkdir -p "$DATABASE_DIR"
mkdir -p "$CRUNCH_ROOT/projects"

TABLE_COUNT=$(sqlite3 "$DATABASE" "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN ('project', 'phases', 'tasks');")
if [ "$TABLE_COUNT" != '3' ]; then
    sqlite3 "$DATABASE" < "$SCHEMA"
    printf 'Initialized .crunch database: %s\n' "$DATABASE"
else
    printf '.crunch database already initialized: %s\n' "$DATABASE"
fi

# Upgrade databases created by pre-workspace versions. Keep the legacy column
# in place for compatibility, but make every current tool use workspace_path.
if ! sqlite3 "$DATABASE" "PRAGMA table_info(project);" | awk -F'|' '$2 == "workspace_path" { found = 1 } END { exit(found ? 0 : 1) }'; then
    sqlite3 "$DATABASE" "ALTER TABLE project ADD COLUMN workspace_path TEXT; UPDATE project SET workspace_path = root_path WHERE workspace_path IS NULL;"
    printf 'Migrated project records to include workspace_path.\n'
fi

# Store the deterministic runtime and dependency guidance included in every
# coding-agent prompt. Existing projects start empty and should be filled in
# through create_project.py before new work is dispatched.
if ! sqlite3 "$DATABASE" "PRAGMA table_info(project);" | awk -F'|' '$2 == "toolchain" { found = 1 } END { exit(found ? 0 : 1) }'; then
    sqlite3 "$DATABASE" "ALTER TABLE project ADD COLUMN toolchain TEXT NOT NULL DEFAULT '';"
    printf 'Migrated project records to include toolchain.\n'
fi

# Track whether a task has been deliberately reset after failure so the worker
# can dispatch it to the configured retry agent.
if ! sqlite3 "$DATABASE" "PRAGMA table_info(tasks);" | awk -F'|' '$2 == "retry_count" { found = 1 } END { exit(found ? 0 : 1) }'; then
    sqlite3 "$DATABASE" "ALTER TABLE tasks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0);"
    printf 'Migrated task records to include retry_count.\n'
fi

# Keep concise implementation handoffs for completed tasks and phases. These
# fields are nullable so existing completed work remains valid after upgrade.
if ! sqlite3 "$DATABASE" "PRAGMA table_info(tasks);" | awk -F'|' '$2 == "completion_summary" { found = 1 } END { exit(found ? 0 : 1) }'; then
    sqlite3 "$DATABASE" "ALTER TABLE tasks ADD COLUMN completion_summary TEXT;"
    printf 'Migrated task records to include completion_summary.\n'
fi

if ! sqlite3 "$DATABASE" "PRAGMA table_info(phases);" | awk -F'|' '$2 == "completion_summary" { found = 1 } END { exit(found ? 0 : 1) }'; then
    sqlite3 "$DATABASE" "ALTER TABLE phases ADD COLUMN completion_summary TEXT;"
    printf 'Migrated phase records to include completion_summary.\n'
fi

# Coordinate stop requests with the worker through durable database state.
if ! sqlite3 "$DATABASE" "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'worker_state';" | grep -qx '1'; then
    sqlite3 "$DATABASE" "CREATE TABLE worker_state (worker_id INTEGER PRIMARY KEY CHECK (worker_id = 1), stop_requested INTEGER NOT NULL DEFAULT 0 CHECK (stop_requested IN (0, 1)), active_task_id INTEGER, run_status TEXT NOT NULL DEFAULT 'idle' CHECK (run_status IN ('idle', 'running', 'interrupted')), updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (active_task_id) REFERENCES tasks(task_id) ON UPDATE CASCADE ON DELETE SET NULL); INSERT INTO worker_state (worker_id) VALUES (1);"
    printf 'Migrated database to include durable worker stop state.\n'
fi

if ! systemctl --user show-environment >/dev/null; then
    printf 'Error: cannot reach the user systemd manager. Run this from a normal logged-in shell with a user systemd session.\n' >&2
    exit 1
fi

if ! loginctl enable-linger "$CURRENT_USER"; then
    printf 'Error: could not enable lingering for %s. Run: sudo loginctl enable-linger %s\n' "$CURRENT_USER" "$CURRENT_USER" >&2
    exit 1
fi

printf 'Enabled user lingering for %s. .crunch workers can now survive logout.\n' "$CURRENT_USER"
