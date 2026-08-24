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

TABLE_COUNT=$(sqlite3 "$DATABASE" "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN ('project', 'phases', 'tasks');")
if [ "$TABLE_COUNT" != '3' ]; then
    sqlite3 "$DATABASE" < "$SCHEMA"
    printf 'Initialized .crunch database: %s\n' "$DATABASE"
else
    printf '.crunch database already initialized: %s\n' "$DATABASE"
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
