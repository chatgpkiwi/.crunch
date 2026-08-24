#!/usr/bin/env bash
set -euo pipefail

# Run the worker as a user service so it survives the command-runner process
# that launched it. `nohup ... &` alone is insufficient in hosts that clean up
# the launcher's child process group when a command finishes.
crunch_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT_ROOT=$(cd "$crunch_ROOT/.." && pwd)
UNIT_SUFFIX=$(printf '%s' "$PROJECT_ROOT" | sha256sum | cut -c1-12)
UNIT_NAME="crunch-worker-${UNIT_SUFFIX}"
SERVICE_PROPERTIES=("--property=KillMode=control-group")

# A user systemd manager starts services with its own environment rather than
# inheriting the shell that invoked systemd-run.  Provider CLIs installed by
# npm, pipx, mise, or similar user-level installers commonly live in a
# user-added PATH entry (for example ~/.npm-global/bin).  Pass the launcher's
# PATH to this unit so the adapters resolve the same provider CLIs that the
# user can run interactively.
SERVICE_ENVIRONMENT=("--setenv=PATH=$PATH")

# systemd's user manager does not inherit the caller's AppArmor profile.
# Preserve it so Codex's nested Bubblewrap sandbox retains permission to
# create the user/network namespaces required by workspace-write mode.
if [ -r /proc/self/attr/current ]; then
    CURRENT_APPARMOR_PROFILE=$(sed 's/ (.*$//' /proc/self/attr/current)
    if [ -n "$CURRENT_APPARMOR_PROFILE" ] && [ "$CURRENT_APPARMOR_PROFILE" != "unconfined" ]; then
        SERVICE_PROPERTIES+=("--property=AppArmorProfile=$CURRENT_APPARMOR_PROFILE")
    fi
fi

if ! command -v systemd-run >/dev/null 2>&1; then
    echo "systemd-run is required to start the crunch worker." >&2
    exit 1
fi

if systemctl --user is-active --quiet "$UNIT_NAME"; then
    echo "crunch worker is already running as ${UNIT_NAME}.service"
    exit 0
fi

systemd-run --user --no-block --collect --quiet \
    --unit="$UNIT_NAME" \
    --working-directory="$crunch_ROOT" \
    "${SERVICE_ENVIRONMENT[@]}" \
    "${SERVICE_PROPERTIES[@]}" \
    -- /usr/bin/python3 "$crunch_ROOT/tools/crunch.py" \
    --database "$crunch_ROOT/database/crunch.db"

echo "Started crunch worker as ${UNIT_NAME}.service"
