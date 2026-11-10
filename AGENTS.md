# Lexomorph Development Invariants

## One Installed Application

- The only runnable installed bundle is `/Applications/Lexomorph.app`.
- Always use bundle identifier `com.local.lexomorph`.
- The background agent is the LaunchAgent `com.local.lexomorph.agent`
  (`~/Library/LaunchAgents/com.local.lexomorph.agent.plist`).
- Local installation must atomically replace that bundle and restart only
  `com.local.lexomorph.agent`.
- Never launch a copied, test, smoke, or temporary `.app` bundle. Exercise
  diagnostics through the command-line self-tests instead.
- The stable signing identity is "Aleksei Bykov" (a self-signed local
  code-signing certificate). It must NOT change between installations without
  the owner's decision: a different signer changes the designated requirement
  and macOS resets every granted permission. The one switch from
  "PolterType Dev" was made once, at the move to Lexomorph 1.0.0. Do not
  create new certificates; the scripts pick the identity by its hash.
- Never call `tccutil reset` automatically. Permission removal is an explicit
  user action.
- Never open more than one macOS privacy pane for a permission request.

## Local Installation

Run `scripts/install-local.sh`. It builds into a temporary directory, signs
with the stable local identity when available, replaces the single installed
bundle, and restarts the background agent without opening another app window.
When a pre-1.0 `/Applications/SuperDictate.app` is found, it is retired only
after the new bundle is installed (see below).

## Self-tests

- Run self-tests in separate groups (`--self-test <group>`), not `all`, on a
  machine where the production agent is installed: a self-test can unload the
  real LaunchAgent. Check `launchctl list | grep -i -E 'lexomorph|superdictate'`
  before and after.
- Tests use temporary directories and isolated `UserDefaults` suites. Never
  write to the real `com.local.lexomorph` defaults domain or touch the real
  Application Support folder from a test.
- The migration groups are `legacy-migration` and `interface-language-default`.

## Names

- Product: Lexomorph. Executable `Lexomorph`; helpers `LexomorphLLMHost` and
  `LexomorphOnnxHost`; SwiftPM target and directory `Lexomorph`; icon
  `Lexomorph.icns`; release asset `Lexomorph.zip` containing `Lexomorph.app`.
- Data: `~/Library/Application Support/Lexomorph`, logs
  `~/Library/Logs/Lexomorph-*`, defaults domain `com.local.lexomorph`, Keychain
  service `com.local.lexomorph.vocab-sync`.
- Deliberately not renamed (owner-managed infrastructure): the repository
  `shohart/SuperDictate-Next`, the sync server domain
  `superdictate.bykovlegal.ru`, `server/`, `windows/`, the native C++
  `SuperDictateOnnxHost` CMake target (staged into the bundle as
  `LexomorphOnnxHost`) and the C++ bridge file names. Credits to Parakey
  (Richard Courtman) and shlgd are history and stay in NOTICE/About/README.
- The interface language defaults to the system language (Russian system ->
  `ru`, otherwise `en`); a language saved by the user always wins.

## Historical: pre-1.0 identifiers

Before 1.0.0 the app was SuperDictate (Next). These identifiers exist only
for migration (`swift/Sources/Lexomorph/Migration.swift`, `LegacyIdentifiers`)
and for retiring the old installation in the install/uninstall scripts:

| Legacy | Replaced by |
| --- | --- |
| `/Applications/SuperDictate.app`, executable `SuperDictate` | `/Applications/Lexomorph.app`, `Lexomorph` |
| `com.local.superdictate` (bundle id, defaults domain) | `com.local.lexomorph` |
| `com.local.superdictate.agent` | `com.local.lexomorph.agent` |
| `~/Library/Application Support/SuperDictate` | `~/Library/Application Support/Lexomorph` |
| Keychain `com.local.superdictate.vocab-sync` | `com.local.lexomorph.vocab-sync` |
| `.superdictate-corrections` files | `.lexomorph-corrections` (old files still import) |

First launch of the new app migrates, idempotently and without deleting
anything (details and rollback: `docs/branding/MIGRATION_NOTES.md`):
defaults keys copied only if absent, the data folder cloned (APFS
`clonefile`), the sync token copied by the agent in the background (one
attempt), a marker `.migrated-from-superdictate.json` in the new data folder.
The legacy data, defaults and Keychain item are never modified or removed.

The new bundle id is a new app for macOS: privacy permissions (Microphone,
Accessibility, Input Monitoring) must be granted again. This was accepted by
the owner and the first-run notice says so. Never "fix" it with `tccutil`.
