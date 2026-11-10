#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PATH="/Applications/Lexomorph.app"
AGENT_LABEL="com.local.lexomorph.agent"
AGENT_PLIST="$HOME/Library/LaunchAgents/$AGENT_LABEL.plist"
# Pre-0.10 installation (SuperDictate). Removed only after the new bundle is
# in place; its data, defaults and Keychain item are never touched.
LEGACY_APP_PATH="/Applications/SuperDictate.app"
LEGACY_AGENT_LABEL="com.local.superdictate.agent"
LEGACY_AGENT_PLIST="$HOME/Library/LaunchAgents/$LEGACY_AGENT_LABEL.plist"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lexomorph-local-install.XXXXXX")"
STAGED_APP="$WORK_DIR/Lexomorph.app"
INCOMING="/Applications/.Lexomorph.incoming.$$"
BACKUP="/Applications/.Lexomorph.previous.$$"

cleanup() {
    rm -rf "$WORK_DIR" "$INCOMING"
}
trap cleanup EXIT

# The signing identity is never changed by a rename: reuse the one that signed
# the installed app (the new bundle, or the legacy one on the first install).
installed_for_identity=""
for candidate in "$APP_PATH" "$LEGACY_APP_PATH"; do
    if [[ -d "$candidate" ]]; then installed_for_identity="$candidate"; break; fi
done
# The one stable signing identity: a self-signed local code-signing
# certificate (default CN "Aleksei Bykov"). It must not change between
# installs without the owner's decision, or macOS resets every permission.
SIGN_NAME="${LEXOMORPH_SIGN_IDENTITY:-Aleksei Bykov}"
# Resolve by SHA-1 hash: the name can be listed twice (login + System keychain).
identity="$(security find-identity -v -p codesigning 2>/dev/null \
    | awk -v n="\"$SIGN_NAME\"" 'index($0, n) && $0 !~ /\(Invalid/ { print $2; exit }')"
if [[ -z "$identity" ]]; then
    printf 'Lexomorph: no valid code-signing identity named "%s" was found.\n' "$SIGN_NAME" >&2
    printf 'Set LEXOMORPH_SIGN_IDENTITY explicitly; ad-hoc local installs are disabled because they reset macOS permissions.\n' >&2
    exit 1
fi

SIGN_IDENTITY="$identity" "$ROOT_DIR/scripts/build-app.sh" "$STAGED_APP"

codesign --verify --deep --strict "$STAGED_APP"
identifier="$(codesign -d --verbose=4 "$STAGED_APP" 2>&1 \
    | sed -n 's/^Identifier=//p')"
[[ "$identifier" == "com.local.lexomorph" ]] || {
    printf 'Lexomorph: unexpected bundle identifier: %s\n' "$identifier" >&2
    exit 1
}
# The designated requirement embeds the bundle identifier, so after the
# rename it legitimately differs from the legacy app's. What must not change
# is WHO signs: compare the leaf signing authority and the team.
signer_of() {
    local info
    info="$(codesign -dv --verbose=4 "$1" 2>&1)"
    printf '%s|%s' "$(sed -n 's/^Authority=//p' <<<"$info" | head -n 1)" \
        "$(sed -n 's/^TeamIdentifier=//p' <<<"$info" | head -n 1)"
}
# A deliberate, owner-approved signer change (e.g. the one-time move from
# "PolterType Dev" to "Aleksei Bykov") needs LEXOMORPH_ALLOW_SIGNER_CHANGE=1;
# macOS permissions are then granted again by hand.
if [[ -n "$installed_for_identity" && "${LEXOMORPH_ALLOW_SIGNER_CHANGE:-0}" != "1" ]]; then
    installed_signer="$(signer_of "$installed_for_identity")"
    staged_signer="$(signer_of "$STAGED_APP")"
    [[ "$installed_signer" == "$staged_signer" ]] || {
        printf 'Lexomorph: refusing to change the signing identity (installed: %s, new: %s). Set LEXOMORPH_ALLOW_SIGNER_CHANGE=1 only on the owner's decision.\n' \
            "$installed_signer" "$staged_signer" >&2
        exit 1
    }
    if [[ "$installed_for_identity" == "$APP_PATH" ]]; then
        installed_requirement="$(codesign -d -r- "$APP_PATH" 2>&1 | tail -n 1)"
        staged_requirement="$(codesign -d -r- "$STAGED_APP" 2>&1 | tail -n 1)"
        [[ "$installed_requirement" == "$staged_requirement" ]] || {
            printf 'Lexomorph: refusing to change the installed designated requirement because that would reset macOS permissions.\n' >&2
            exit 1
        }
    fi
fi

uid="$(id -u)"
launchctl bootout "gui/$uid/$AGENT_LABEL" >/dev/null 2>&1 || true
pkill -f "$APP_PATH/Contents/MacOS/Lexomorph" >/dev/null 2>&1 || true

ditto "$STAGED_APP" "$INCOMING"
codesign --verify --deep --strict "$INCOMING"

if [[ -e "$APP_PATH" ]]; then
    mv "$APP_PATH" "$BACKUP"
fi
if ! mv "$INCOMING" "$APP_PATH"; then
    if [[ -e "$BACKUP" ]]; then
        mv "$BACKUP" "$APP_PATH"
    fi
    exit 1
fi
rm -rf "$BACKUP"

# The agent plist may not exist yet (first Lexomorph install). Write it the
# same way the app does (LexomorphAgentService.writeLaunchAgentPlist).
mkdir -p "$(dirname "$AGENT_PLIST")"
cat > "$AGENT_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>KeepAlive</key>
	<dict>
		<key>SuccessfulExit</key>
		<false/>
	</dict>
	<key>Label</key>
	<string>$AGENT_LABEL</string>
	<key>ProcessType</key>
	<string>Interactive</string>
	<key>ProgramArguments</key>
	<array>
		<string>$APP_PATH/Contents/MacOS/Lexomorph</string>
		<string>--agent</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>StandardErrorPath</key>
	<string>$HOME/Library/Logs/Lexomorph-agent.launchd.log</string>
	<key>StandardOutPath</key>
	<string>$HOME/Library/Logs/Lexomorph-agent.launchd.log</string>
</dict>
</plist>
PLIST
plutil -lint "$AGENT_PLIST" >/dev/null

# The new bundle is installed: retire the legacy SuperDictate installation
# BEFORE the new agent starts, so two agents never fight over the hotkey.
# Data, defaults and the Keychain item of the legacy app stay untouched (they
# are the rollback path).
if [[ -e "$LEGACY_APP_PATH" || -e "$LEGACY_AGENT_PLIST" ]]; then
    launchctl bootout "gui/$uid/$LEGACY_AGENT_LABEL" >/dev/null 2>&1 || true
    pkill -f "$LEGACY_APP_PATH/Contents/MacOS/" >/dev/null 2>&1 || true
    rm -f "$LEGACY_AGENT_PLIST"
    rm -rf "$LEGACY_APP_PATH"
    printf 'Lexomorph: removed the legacy SuperDictate app and its LaunchAgent (its data was left untouched).\n'
fi

launchctl bootstrap "gui/$uid" "$AGENT_PLIST" >/dev/null 2>&1 || true
launchctl kickstart -k "gui/$uid/$AGENT_LABEL"

printf 'Lexomorph: installed one signed app at %s and restarted the background agent.\n' "$APP_PATH"
