#!/bin/bash
# Builds the SuperDictate -> Lexomorph transition bridge (see bridge/README.md).
#
#   scripts/build-bridge.sh <path/to/Lexomorph.zip> <version> [output-dir]
#
# Output (default dist/bridge): SuperDictate.app (kept), SuperDictate.zip, SuperDictate.zip.sha256.
# Environment:
#   SIGN_IDENTITY       signing identity name or SHA-1 hash (default "Aleksei Bykov"; "-" = ad-hoc, tests only).
#                       It MUST be the identity that signed Lexomorph.zip: the bridge compares Authority at runtime.
#   SIGN_VIA_ASUSER=1   sign through `sudo launchctl asuser $(id -u) codesign` (needed over bare SSH, the private
#                       key requires the GUI session); the sudo password is read from SUDO_PASSWORD.
#   BRIDGE_ARCHS        space separated, default "x86_64 arm64" (universal bridge).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEXOMORPH_ZIP="${1:-}"
VERSION="${2:-}"
OUT_DIR="${3:-$ROOT_DIR/dist/bridge}"
SIGN_IDENTITY="${SIGN_IDENTITY:-Aleksei Bykov}"
BRIDGE_ARCHS="${BRIDGE_ARCHS:-x86_64 arm64}"

fail() { printf 'build-bridge: %s\n' "$*" >&2; exit 1; }
say() { printf 'build-bridge: %s\n' "$*"; }

[[ -n "$LEXOMORPH_ZIP" && -n "$VERSION" ]] || fail "usage: build-bridge.sh <Lexomorph.zip> <version> [output-dir]"
[[ -f "$LEXOMORPH_ZIP" ]] || fail "no such file: $LEXOMORPH_ZIP"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "version must look like 1.0.0"
[[ "$(/usr/bin/uname -s)" == "Darwin" ]] || fail "macOS is required."
command -v swiftc >/dev/null || fail "swiftc is missing (xcode-select --install)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/lexomorph-bridge-build.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
APP="$WORK/SuperDictate.app"

say "Compiling the bridge ($BRIDGE_ARCHS)..."
slices=()
for arch in $BRIDGE_ARCHS; do
    swiftc -O -warnings-as-errors -target "$arch-apple-macos14.0" -o "$WORK/bridge-$arch" "$ROOT_DIR/bridge/main.swift"
    slices+=("$WORK/bridge-$arch")
done
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
if (( ${#slices[@]} == 1 )); then
    cp "${slices[0]}" "$APP/Contents/MacOS/SuperDictate"
else
    lipo -create "${slices[@]}" -output "$APP/Contents/MacOS/SuperDictate"
fi
chmod 755 "$APP/Contents/MacOS/SuperDictate"

sed "s/@VERSION@/$VERSION/g" "$ROOT_DIR/bridge/Info.plist.template" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist" >/dev/null
cp "$ROOT_DIR/bridge/lexomorph.icns" "$APP/Contents/Resources/lexomorph.icns"
cp "$LEXOMORPH_ZIP" "$APP/Contents/Resources/Lexomorph.zip"

# The embedded app must have the version this bridge announces.
probe="$WORK/probe"
mkdir "$probe"
ditto -x -k "$LEXOMORPH_ZIP" "$probe"
[[ "$(plutil -extract CFBundleShortVersionString raw -o - "$probe/Lexomorph.app/Contents/Info.plist")" == "$VERSION" ]] \
    || fail "Lexomorph.zip does not contain version $VERSION"
[[ "$(plutil -extract CFBundleIdentifier raw -o - "$probe/Lexomorph.app/Contents/Info.plist")" == "com.local.lexomorph" ]] \
    || fail "Lexomorph.zip does not contain com.local.lexomorph"
rm -rf "$probe"

[[ -z "$(find "$APP" -type l)" ]] || fail "the bridge bundle must not contain symbolic links"

say "Signing with identity: $SIGN_IDENTITY"
sign_args=(--force --deep --sign "$SIGN_IDENTITY" --options runtime
           --entitlements "$ROOT_DIR/entitlements.plist")
if [[ "$SIGN_IDENTITY" == "-" ]]; then sign_args+=(--timestamp=none); fi
if [[ "${SIGN_VIA_ASUSER:-0}" == "1" ]]; then
    [[ -n "${SUDO_PASSWORD:-}" ]] || fail "SIGN_VIA_ASUSER=1 needs SUDO_PASSWORD"
    printf '%s\n' "$SUDO_PASSWORD" | sudo -S launchctl asuser "$(id -u)" /usr/bin/codesign "${sign_args[@]}" "$APP"
else
    codesign "${sign_args[@]}" "$APP"
fi
codesign --verify --deep --strict "$APP"

say "Running the bridge self-test (command line)..."
"$APP/Contents/MacOS/SuperDictate" --self-test >"$WORK/selftest.log" 2>&1 || { tail -30 "$WORK/selftest.log"; fail "self-test failed"; }
tail -1 "$WORK/selftest.log"

mkdir -p "$OUT_DIR"
rm -rf "$OUT_DIR/SuperDictate.app" "$OUT_DIR/SuperDictate.zip" "$OUT_DIR/SuperDictate.zip.sha256"
mv "$APP" "$OUT_DIR/SuperDictate.app"
( cd "$OUT_DIR" && ditto -c -k --keepParent SuperDictate.app SuperDictate.zip \
    && shasum -a 256 SuperDictate.zip > SuperDictate.zip.sha256 )
say "Built $OUT_DIR/SuperDictate.zip"
cat "$OUT_DIR/SuperDictate.zip.sha256"
