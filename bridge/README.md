# SuperDictate -> Lexomorph transition bridge

Spec: `docs/specs/transition-release-spec.md`. The 0.9.x in-app updater only accepts a `SuperDictate.app`
(bundle id `com.local.superdictate`, version == release version, executable `Contents/MacOS/SuperDictate`,
no symlinks, valid `codesign --deep --strict`, SHA-256 from `update.json`). The bridge is exactly such an app.
It carries the real `Lexomorph.zip` and, on the user's consent, installs it.

## Files

- `main.swift` - the whole bridge (AppKit dialog + pure logic + `--self-test`); no dependency on the main app.
- `Info.plist.template` - `@VERSION@` is replaced by `scripts/build-bridge.sh`.
- `lexomorph.icns` - copy of `icon/Lexomorph.icns` (keep in sync).

## Behaviour

Launch (by `open`, by the old LaunchAgent at login, or by hand) shows ONE dialog, English or Russian by system
language: **Install Lexomorph** / **Not now**. "Not now" exits 0 and changes nothing (the old agent asks again at the
next login). If Lexomorph of the same version is already installed and valid, the dialog offers **Finish cleanup**
instead (idempotent re-run).

Install: extract the embedded zip (`ditto`) into a private dir under `/Applications` -> verify bundle id
`com.local.lexomorph`, version == bridge version, executable, `codesign --verify --deep --strict`, and that the
leaf **Authority/Team equals the bridge's own** (no hard-coded identity; an unsigned bridge refuses) -> stage and
replace `/Applications/Lexomorph.app` atomically with a backup. Then a detached helper (its own launchd job
`com.local.lexomorph.bridge-finish`, so it survives the old agent being booted out) does: boot out
`com.local.superdictate.agent` and remove its plist, write `com.local.lexomorph.agent.plist` (same keys as
`install-local.sh`), `bootstrap` + `kickstart`, require a **stable running agent pid**, and only then removes
`/Applications/SuperDictate.app` (after checking its bundle id) and the backup. Any failure: restore the previous
Lexomorph, restore the old agent plist, keep the bridge, show an `osascript` message. User data, `defaults`,
Keychain and `tccutil` are never touched. Failures always exit 0 so launchd does not respawn the bridge.

## Test modes (no side effects on the real system)

- `--print-plan` - print paths and steps.
- `--dry-run` - non-interactive; honours `LEXOMORPH_BRIDGE_APPS_DIR`, `LEXOMORPH_BRIDGE_LAUNCHAGENTS_DIR`,
  optional `LEXOMORPH_BRIDGE_LOGS_DIR`, `LEXOMORPH_BRIDGE_ZIP`, `LEXOMORPH_BRIDGE_VERSION` (ignored without
  `--dry-run`). Extracts, verifies and installs into the temp dir, writes `<agent>.plist.dryrun` and the helper
  script there; never calls `launchctl`/`open`, never removes anything real.
- `--self-test` - unit tests of language choice, plist content, signer parsing, rollback on bad signature / wrong
  bundle id / version / authority, idempotency, no writes outside the given dirs, and the helper script run against
  a fake `launchctl` (success and rollback paths). Needs macOS (`ditto`, `bash`).

## Release process (per macOS release that old clients may still see)

1. Build and sign `Lexomorph.zip` as usual (see `docs/RELEASING.md`). The bridge must be signed by the SAME identity.
2. `SIGN_IDENTITY="Aleksei Bykov" scripts/build-bridge.sh /path/Lexomorph.zip 1.0.0 out/`
   (over bare SSH: `SIGN_VIA_ASUSER=1 SUDO_PASSWORD=...`). Produces `out/SuperDictate.zip` + `.sha256`, runs the
   self-test.
3. `scripts/check-bridge.sh out/SuperDictate.zip 1.0.0 <sha256 of SuperDictate.zip> /path/Lexomorph.zip`
   repeats the 0.9.7 client checks and the bridge dry-run.
4. Publish `SuperDictate.zip` and `Lexomorph.zip` as assets of `mac-v1.0.0`. `update.json` on `main`:
   `{"version":"1.0.0","sha256":"<SuperDictate.zip>","lexomorph_sha256":"<Lexomorph.zip>"}`. Old clients read
   `sha256` (bridge), new clients read `lexomorph_sha256` first.
5. Keep publishing a bridge with every release until the owner decides old clients are gone.
