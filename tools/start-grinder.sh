#!/usr/bin/env bash
set -euo pipefail

# Run the worker as a user service so it survives the command-runner process
# that launched it. `nohup ... &` alone is insufficient in hosts that clean up
# the launcher's child process group when a command finishes.
GRINDR_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT_ROOT=$(cd "$GRINDR_ROOT/.." && pwd)
UNIT_SUFFIX=$(printf '%s' "$PROJECT_ROOT" | sha256sum | cut -c1-12)
UNIT_NAME="grindr-worker-${UNIT_SUFFIX}"
SERVICE_PROPERTIES=("--property=KillMode=control-group")
CONFIG_PATH="$GRINDR_ROOT/config/config.yaml"

ACTIVE_PROVIDER=$(awk '
    /^  default:[[:space:]]*(#.*)?$/ { in_default = 1; next }
    in_default && !/^    / { exit }
    in_default {
        line = $0
        sub(/#.*/, "", line)
        if (line ~ /^[[:space:]]+provider:[[:space:]]*/) {
            sub(/^[[:space:]]+provider:[[:space:]]*/, "", line)
            gsub(/"/, "", line)
            gsub(/\047/, "", line)
            print line
            exit
        }
    }
' "$CONFIG_PATH")

if [ -z "$ACTIVE_PROVIDER" ]; then
    echo "Unable to read coding_agents.default.provider from $CONFIG_PATH" >&2
    exit 1
fi

case "$ACTIVE_PROVIDER" in
    aider|codex) ;;
    *)
        echo "Unsupported coding-agent provider: $ACTIVE_PROVIDER" >&2
        exit 1
        ;;
esac

# systemd's user manager does not inherit the caller's AppArmor profile.
# Preserve it only for the Codex adapter, whose nested Bubblewrap sandbox needs
# the profile's namespace permissions. Aider must run under the user manager's
# normal profile so it can reach a model provider on the host loopback address.
if [ "$ACTIVE_PROVIDER" = "codex" ] && [ -r /proc/self/attr/current ]; then
    CURRENT_APPARMOR_CONTEXT=$(< /proc/self/attr/current)
    CURRENT_APPARMOR_PROFILE=$(sed 's/ (.*$//' <<< "$CURRENT_APPARMOR_CONTEXT")
    if [ -n "$CURRENT_APPARMOR_PROFILE" ] \
        && [ "$CURRENT_APPARMOR_PROFILE" != "unconfined" ] \
        && [[ "$CURRENT_APPARMOR_CONTEXT" != *"(unconfined)"* ]]; then
        SERVICE_PROPERTIES+=("--property=AppArmorProfile=$CURRENT_APPARMOR_PROFILE")
    fi
fi

if ! command -v systemd-run >/dev/null 2>&1; then
    echo "systemd-run is required to start the grinder worker." >&2
    exit 1
fi

if systemctl --user is-active --quiet "$UNIT_NAME"; then
    echo "Grinder worker is already running as ${UNIT_NAME}.service"
    exit 0
fi

systemd-run --user --no-block --collect --quiet \
    --unit="$UNIT_NAME" \
    --working-directory="$GRINDR_ROOT" \
    "${SERVICE_PROPERTIES[@]}" \
    -- /usr/bin/python3 "$GRINDR_ROOT/tools/grinder.py" \
    --database "$GRINDR_ROOT/database/grindr.db"

echo "Started grinder worker as ${UNIT_NAME}.service using $ACTIVE_PROVIDER"
