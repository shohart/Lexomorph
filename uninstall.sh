#!/bin/bash

set -euo pipefail

# Usage: uninstall.sh [--legacy]
#   (no flag)  remove Lexomorph (app + LaunchAgent); data is kept.
#   --legacy   additionally remove a pre-0.10 SuperDictate installation
#              (app + LaunchAgent). Its data, defaults and Keychain item are
#              never touched: they are the rollback path.

APP_PATH="/Applications/Lexomorph.app"
AGENT_LABEL="com.local.lexomorph.agent"
AGENT_PLIST="$HOME/Library/LaunchAgents/$AGENT_LABEL.plist"
LEGACY_APP_PATH="/Applications/SuperDictate.app"
LEGACY_AGENT_LABEL="com.local.superdictate.agent"
LEGACY_AGENT_PLIST="$HOME/Library/LaunchAgents/$LEGACY_AGENT_LABEL.plist"

remove_legacy=0
for argument in "$@"; do
    case "$argument" in
        --legacy) remove_legacy=1 ;;
        *) printf 'Usage: %s [--legacy]\n' "$0" >&2; exit 2 ;;
    esac
done

remove_app() {
    if [[ -w /Applications ]]; then
        rm -rf "$1"
    else
        sudo rm -rf "$1"
    fi
}

/bin/launchctl bootout "gui/$UID/$AGENT_LABEL" >/dev/null 2>&1 || true
/usr/bin/pkill -f "$APP_PATH/Contents/MacOS/" >/dev/null 2>&1 || true
rm -f "$AGENT_PLIST"
remove_app "$APP_PATH"
printf 'Lexomorph удалён. История и локальная модель сохранены.\n'

if [[ "$remove_legacy" == "1" ]]; then
    /bin/launchctl bootout "gui/$UID/$LEGACY_AGENT_LABEL" >/dev/null 2>&1 || true
    /usr/bin/pkill -f "$LEGACY_APP_PATH/Contents/MacOS/" >/dev/null 2>&1 || true
    rm -f "$LEGACY_AGENT_PLIST"
    remove_app "$LEGACY_APP_PATH"
    printf 'Прежняя установка SuperDictate удалена (её данные не тронуты).\n'
fi
