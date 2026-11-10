# Transition release: SuperDictate Next 0.9.x -> Lexomorph 1.0.0

**Status:** design, 2026-11-10. Implemented by the "bridge" tasks below.

## 1. Constraints from the old clients (read from `origin/main`, 0.9.7)

**macOS (`UpdateCheck.swift`)** updates in place, user-initiated (auto-check is off by default):
1. lists GitHub releases, picks the newest published `mac-vX.Y.Z` (tag version = V);
2. fetches `update.json` from `main` and requires `version == V`;
3. downloads `.../releases/download/mac-vV/SuperDictate.zip`, requires `sha256` from `update.json`;
4. extracts, requires `SuperDictate.app` with `CFBundleIdentifier == com.local.superdictate`,
   `CFBundleShortVersionString == V`, executable `Contents/MacOS/SuperDictate`, **no symlinks**,
   and `codesign --verify --deep --strict` passing;
5. a helper script boots out `com.local.superdictate.agent`, swaps `/Applications/SuperDictate.app`,
   verifies, and `open`s it.

So a single release `mac-v1.0.0` must contain **`SuperDictate.zip`** (the *bridge*) and `Lexomorph.zip`
(the real app), and `update.json` must stay valid for the old client (`version`, `sha256` of the bridge zip).

**Windows (`updater.py`)** never downloads or runs anything: it opens the release page for a newer
`win-vX.Y.Z` that has a `.exe`/`.msi`/`.zip` asset. `Lexomorph-Setup-1.0.0.exe` already satisfies it, and the
new installer removes the old SuperDictate install and keeps its data. Windows needs release notes only.

## 2. macOS bridge app (`SuperDictate.app`, version = release version)

- Bundle id `com.local.superdictate`, executable `SuperDictate`, same signing identity as always,
  `CFBundleDisplayName` "SuperDictate Next -> Lexomorph", **no symlinks**, contains
  `Contents/Resources/Lexomorph.zip` (the real signed app, `ditto`-zipped, so no symlink problem).
- On launch (from `open`, from the old LaunchAgent at login, or by hand) it shows ONE native dialog,
  English by default, Russian on a Russian system: why the name, bundle and signature change; that settings,
  vocabulary, history and models are carried over by Lexomorph on its first launch (originals are kept);
  that macOS privacy permissions must be granted again; buttons **Install Lexomorph** / **Not now**.
  "Not now" quits without changing anything (the old LaunchAgent keeps asking at next login).
- **Install**: (1) `ditto -x -k` the embedded zip into a private temp dir; (2) verify bundle id
  `com.local.lexomorph`, version, `codesign --verify --deep --strict`, and that the authority matches the
  bridge's own authority; (3) stage next to `/Applications` and replace `/Applications/Lexomorph.app`
  atomically (keep a backup, roll back on failure); (4) stop and remove the old agent
  (`launchctl bootout gui/<uid>/com.local.superdictate.agent`, delete its plist); (5) start Lexomorph the way
  `install-local.sh`/`install.sh` do (registers `com.local.lexomorph.agent`); (6) only after Lexomorph's agent is
  running, remove `/Applications/SuperDictate.app` via a detached helper (the bridge cannot delete itself while
  running). Never touch user data, `defaults`, Keychain, or `tccutil`.
- Failure at any step: roll back to the previous state, show the reason, keep the bridge in place.
- Test hooks: `--dry-run` (everything except launchctl/open/removal, into a temp prefix given by
  `LEXOMORPH_BRIDGE_APPS_DIR`), exercised by a check script and by unit tests of the pure logic.
- Source lives in `bridge/` (a small SwiftPM or single-file `swiftc` target, no dependency on the main app),
  built by `scripts/build-bridge.sh` from a given `Lexomorph.zip`.

## 3. Manifest and release layout

- `update.json` stays decodable by old clients: `version`, `sha256` (= `SuperDictate.zip`, the bridge), plus
  `lexomorph_sha256` (= `Lexomorph.zip`) for new clients. New clients read `lexomorph_sha256` first and fall
  back to `sha256`.
- Each macOS release that old clients may still see must also publish a `SuperDictate.zip` bridge whose version
  equals the release version, until the owner decides old clients are gone. `docs/RELEASING.md` documents it.
- Release notes (EN/RU) for `mac-v1.0.0` and `win-v1.0.0` explain the rename, the changed package and
  signature, the permissions re-grant, data migration and the rollback path.

## 4. Non-goals / not done here

Publishing, tagging, editing `main`'s `update.json`/`install.sh` pins, DNS/repo rename, notarization.
