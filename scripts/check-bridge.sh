#!/bin/bash
# Repeats, on a finished bridge archive, every check the 0.9.7 in-app updater performs, plus bridge-specific ones.
#
#   scripts/check-bridge.sh <SuperDictate.zip> <version> <expected-sha256> <Lexomorph.zip|lexomorph-sha256>
#
# CHECK_BRIDGE_NO_EXEC=1 skips running the bridge binary (self-test and --dry-run on temp directories).
set -euo pipefail

ZIP="${1:-}"; VERSION="${2:-}"; EXPECTED_SHA="${3:-}"; LEXO="${4:-}"
fail() { printf 'check-bridge: FAIL: %s\n' "$*" >&2; exit 1; }
ok() { printf 'check-bridge: ok   %s\n' "$*"; }
[[ -f "$ZIP" && -n "$VERSION" && -n "$EXPECTED_SHA" && -n "$LEXO" ]] \
    || fail "usage: check-bridge.sh <SuperDictate.zip> <version> <sha256> <Lexomorph.zip|sha256>"

actual="$(shasum -a 256 "$ZIP" | awk '{print $1}')"
[[ "$actual" == "$EXPECTED_SHA" ]] || fail "SHA-256 of the archive is $actual, expected $EXPECTED_SHA"
ok "SHA-256 of SuperDictate.zip matches"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/lexomorph-bridge-check.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
ditto -x -k "$ZIP" "$WORK/release"
APP="$WORK/release/SuperDictate.app"
[[ -d "$APP" ]] || fail "the archive has no SuperDictate.app"
ok "extracts with ditto to SuperDictate.app"

INFO="$APP/Contents/Info.plist"
[[ "$(plutil -extract CFBundleIdentifier raw -o - "$INFO")" == "com.local.superdictate" ]] || fail "bundle id is not com.local.superdictate"
ok "bundle id com.local.superdictate"
[[ "$(plutil -extract CFBundleShortVersionString raw -o - "$INFO")" == "$VERSION" ]] || fail "version is not $VERSION"
ok "CFBundleShortVersionString == $VERSION"
[[ "$(plutil -extract CFBundleExecutable raw -o - "$INFO")" == "SuperDictate" ]] || fail "CFBundleExecutable is not SuperDictate"
[[ -x "$APP/Contents/MacOS/SuperDictate" ]] || fail "Contents/MacOS/SuperDictate is not executable"
ok "executable Contents/MacOS/SuperDictate"
[[ "$(plutil -extract LSUIElement raw -o - "$INFO")" == "false" ]] || fail "LSUIElement must be false"
[[ -z "$(find "$APP" -type l)" ]] || fail "the bundle contains symbolic links"
ok "no symbolic links"
codesign --verify --deep --strict "$APP" || fail "codesign --verify --deep --strict failed"
ok "codesign --verify --deep --strict"
bridge_sig="$(codesign -dv --verbose=4 "$APP" 2>&1 | sed -n 's/^Authority=//p' | head -n 1)"
[[ -n "$bridge_sig" ]] || printf 'check-bridge: warn: the bridge has no certificate authority (ad-hoc build)\n'
ok "bridge authority: ${bridge_sig:-<none>}"

# The embedded Lexomorph.zip must be the release one.
EMBEDDED="$APP/Contents/Resources/Lexomorph.zip"
[[ -f "$EMBEDDED" ]] || fail "Contents/Resources/Lexomorph.zip is missing"
if [[ -f "$LEXO" ]]; then lexo_sha="$(shasum -a 256 "$LEXO" | awk '{print $1}')"; else lexo_sha="$LEXO"; fi
[[ "$(shasum -a 256 "$EMBEDDED" | awk '{print $1}')" == "$lexo_sha" ]] || fail "the embedded Lexomorph.zip differs from the release one"
ok "embedded Lexomorph.zip SHA-256 == $lexo_sha"

# Authority of the embedded Lexomorph.app must equal the bridge's (the bridge refuses otherwise).
ditto -x -k "$EMBEDDED" "$WORK/lexo"
LAPP="$WORK/lexo/Lexomorph.app"
[[ "$(plutil -extract CFBundleIdentifier raw -o - "$LAPP/Contents/Info.plist")" == "com.local.lexomorph" ]] || fail "embedded bundle id is not com.local.lexomorph"
[[ "$(plutil -extract CFBundleShortVersionString raw -o - "$LAPP/Contents/Info.plist")" == "$VERSION" ]] || fail "embedded Lexomorph version is not $VERSION"
codesign --verify --deep --strict "$LAPP" || fail "embedded Lexomorph.app signature is invalid"
lexo_sig="$(codesign -dv --verbose=4 "$LAPP" 2>&1 | sed -n 's/^Authority=//p' | head -n 1)"
[[ "$lexo_sig" == "$bridge_sig" ]] || fail "authority differs: bridge '$bridge_sig' vs Lexomorph '$lexo_sig'"
ok "embedded Lexomorph: com.local.lexomorph $VERSION, valid, same authority as the bridge"

if [[ "${CHECK_BRIDGE_NO_EXEC:-0}" == "1" ]]; then
    printf 'check-bridge: skipped running the bridge binary (CHECK_BRIDGE_NO_EXEC=1)\n'
else
    BIN="$APP/Contents/MacOS/SuperDictate"
    "$BIN" --self-test >"$WORK/selftest.log" 2>&1 || { tail -20 "$WORK/selftest.log"; fail "bridge --self-test failed"; }
    ok "bridge --self-test: $(tail -1 "$WORK/selftest.log")"
    mkdir -p "$WORK/dry/apps" "$WORK/dry/agents" "$WORK/dry/logs"
    LEXOMORPH_BRIDGE_APPS_DIR="$WORK/dry/apps" LEXOMORPH_BRIDGE_LAUNCHAGENTS_DIR="$WORK/dry/agents" \
        LEXOMORPH_BRIDGE_LOGS_DIR="$WORK/dry/logs" "$BIN" --dry-run >"$WORK/dry.log" 2>&1 \
        || { tail -20 "$WORK/dry.log"; fail "bridge --dry-run failed"; }
    [[ -x "$WORK/dry/apps/Lexomorph.app/Contents/MacOS/Lexomorph" ]] || fail "dry-run did not install Lexomorph.app into the temp dir"
    [[ -f "$WORK/dry/agents/com.local.lexomorph.agent.plist.dryrun" ]] || fail "dry-run did not write the agent plist"
    plutil -lint "$WORK/dry/agents/com.local.lexomorph.agent.plist.dryrun" >/dev/null || fail "agent plist is invalid"
    # Second run: idempotent.
    LEXOMORPH_BRIDGE_APPS_DIR="$WORK/dry/apps" LEXOMORPH_BRIDGE_LAUNCHAGENTS_DIR="$WORK/dry/agents" \
        LEXOMORPH_BRIDGE_LOGS_DIR="$WORK/dry/logs" "$BIN" --dry-run >"$WORK/dry2.log" 2>&1 || fail "second dry-run failed"
    grep -q "already installed" "$WORK/dry2.log" || { cat "$WORK/dry2.log"; fail "second dry-run is not idempotent"; }
    ok "bridge --dry-run into temp dirs (install + idempotent re-run)"
fi
printf 'check-bridge: ALL CHECKS PASSED\n'
