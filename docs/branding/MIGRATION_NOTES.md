# Lexomorph 1.0: identifier rename and data migration

**[Читать по-русски](MIGRATION_NOTES.ru.md)**

Owner decision (it replaces the earlier "do not change identifiers"): the SuperDictate / Parakey names are replaced
everywhere on macOS, identifiers included, and on Windows. The version is 1.0.0. This document describes what was
renamed, how data moves over, how to roll back, and what is still open for the release.

## 1. What was renamed

### macOS

| Was | Is now |
|---|---|
| `/Applications/SuperDictate.app`, executable `SuperDictate` | `/Applications/Lexomorph.app`, `Lexomorph` |
| bundle ID and UserDefaults domain `com.local.superdictate` | `com.local.lexomorph` |
| LaunchAgent `com.local.superdictate.agent` | `com.local.lexomorph.agent` (`~/Library/LaunchAgents/com.local.lexomorph.agent.plist`) |
| `~/Library/Application Support/SuperDictate` | `~/Library/Application Support/Lexomorph` |
| `~/Library/Logs/SuperDictate*` | `~/Library/Logs/Lexomorph-*` |
| Keychain `com.local.superdictate.vocab-sync` | `com.local.lexomorph.vocab-sync` |
| UTI `com.local.superdictate.corrections`, extension `.superdictate-corrections` | `com.local.lexomorph.corrections`, `.lexomorph-corrections` (old files still import: the old type is declared as importable) |
| Helpers `SuperDictateLLMHost`, `SuperDictateOnnxHost` | `LexomorphLLMHost`, `LexomorphOnnxHost` |
| SwiftPM target and directory `Parakey` | `Lexomorph` (`swift/Sources/Lexomorph`) |
| Icon `icon/Parakey.icns`, `parakey-menubar*.png` | `icon/Lexomorph.icns`, `lexomorph-menubar*.png` |
| Release asset `SuperDictate.zip` with `SuperDictate.app` | `Lexomorph.zip` with `Lexomorph.app` |
| Environment variables `SUPERDICTATE_*` (macOS scripts, Swift) | `LEXOMORPH_*` |

### Windows

| Was | Is now |
|---|---|
| `%LOCALAPPDATA%\SuperDictate` | `%LOCALAPPDATA%\Lexomorph` |
| `SuperDictate.exe`, `SuperDictateOnnxHost.exe`, `SuperDictateOvHost.exe` and the LLM host | `Lexomorph.exe`, `LexomorphOnnxHost.exe`, `LexomorphOvHost.exe`, `lexomorph-llm-host.exe` |
| Installer `SuperDictate-X.Y.Z-setup.exe` (old AppId) | `Lexomorph-Setup-X.Y.Z.exe` (new AppId) |
| Autostart value `SuperDictate` | `Lexomorph` |
| `SUPERDICTATE_*` environment variables | `LEXOMORPH_*` (the old ones are still read as a fallback for one release) |
| DPAPI entropy `com.local.superdictate.vocab-sync` | `com.lexomorph.vocab-sync` (the old one is still accepted when reading; the token is re-protected under the new one) |

### Deliberately not renamed

Owner-managed infrastructure or code shared with Windows: the repository `shohart/SuperDictate-Next` and every link to
it, the sync domain `superdictate.bykovlegal.ru`, the `server/` directory, the Python package `superdictate` in
`windows/`, the CMake target `SuperDictateOnnxHost` in `native/asr-runtime` (it is staged into the bundle as
`LexomorphOnnxHost`), the C++ file names `superdictate_*` in `swift/Sources/{llama_cpp_host,silero_vad}`, the
environment variable `SUPERDICTATE_VULKAN_SHADER_DIR` read by the native LLM host, the Parakey (Richard Courtman) and
shlgd credits, history (CHANGELOG, specifications, plans) and the upstream Homebrew cask tokens. The owner renames the
repository and the sync domain later; GitHub redirects the old repository addresses.

## 2. Migration on the first launch

### macOS

Code: `swift/Sources/Lexomorph/Migration.swift`. It runs in both the agent and the Panel (`main.swift`) before the
delegate is created (and so before `Settings.shared`), under the file lock
`~/Library/Application Support/.lexomorph-migration.lock` (waits up to 20 s; if it cannot get the lock the app starts
without migrating, the migration repeats next time, no marker is written). It runs only in the production bundle
`com.local.lexomorph` (test bundles and a bare `swift build` do not migrate).

1. **UserDefaults:** every key of the domain `com.local.superdictate` is copied into `com.local.lexomorph` if the new
   domain does not have that key yet (existing keys are not overwritten). `active_run_marker` (the state of the old
   process) is not copied. Absolute paths inside the old data folder are rewritten to the new one. A saved interface
   language is carried over.
2. **Data folder:** every item of `Application Support/SuperDictate` is cloned into `Application Support/Lexomorph`
   with `clonefile(2)` (APFS: models of several gigabytes do not take space twice), to a temporary `.migrating-*` name
   and then renamed atomically; without an APFS clone an ordinary copy is made. Items that already exist in the new
   folder are not overwritten (sqlite `-wal/-shm/-journal` files are not attached to a foreign database).
   `AgentStatus*.json`, `*.pid` and `*.lock` (process state) are not carried over.
3. **Keychain:** only in the agent, on a background thread, after step 1. The token is read under the old service and
   the e-mail comes from the migrated settings; the token is written under the new service. If the new one already
   exists, it is left alone. The attempt is made exactly once: a failure or a refusal in the access dialog is final
   (no retries and no dialog on every launch); the user just signs in to sync again. The Keychain dialog does not block
   startup (the main thread does not wait for it).
4. **Marker:** `Application Support/Lexomorph/.migrated-from-superdictate.json` records the app version, the date, what
   was copied and skipped, the Keychain result and whether the notice was shown. If the marker exists, nothing is done.
5. **One-time window** on the first launch after a migration (only if old data was found): why the name and the package
   changed, that macOS permissions must be granted again, that the data was carried over, and that the old data was
   left untouched. The window does not open any Privacy pane.

macOS permissions (Microphone, Accessibility, Input Monitoring) cannot move over: a new bundle ID is a new app to the
system. The owner accepted this. `tccutil reset` is never called.

### Windows

Code: `windows/superdictate/paths.py` (`migrate_legacy_data`, called once from `main()`; `ensure_directories` and the
self-tests never migrate).

- The first launch copies `%LOCALAPPDATA%\SuperDictate` to `%LOCALAPPDATA%\Lexomorph` (older names `Dictation` and
  `D1CT` are handled the same way, newest first): settings, history, vocabulary, sync token and models; large model
  files as hard links when the file system allows. `Logs`, `OutputMuted.flag` and temporary files are not copied.
- The original is not deleted: it is the rollback path.
- A marker `.migrated-from-superdictate.json` with `status` `complete` or `incomplete` ends the migration or lets it
  resume on the next launch. A folder that already has its own `Settings.json` and no marker belongs to someone who
  started fresh, and old data is not pushed into it.
- The sync token is re-protected with the new DPAPI entropy. A failure never blocks the start.
- The installer `Lexomorph-Setup-X.Y.Z.exe` installs a new application (a new AppId) and, before installing, closes and
  removes an installed SuperDictate (program, shortcuts, autostart entry); its data stays. On uninstall it asks whether
  to delete the data folder and the old SuperDictate folder.

## 3. Installing, and the old installation

- **macOS:** `scripts/install-local.sh` and `install.sh` install `/Applications/Lexomorph.app` atomically and use the
  agent `com.local.lexomorph.agent`. If they find `/Applications/SuperDictate.app` or the agent
  `com.local.superdictate.agent`, they unload the old agent, end its process and remove the old bundle and the old
  plist only after the new one was installed successfully and before the new agent starts (so two agents do not fight
  over the hotkey). The data, defaults and Keychain of the old app are not touched.
- **Signature:** the identity is not changed and no new certificates are created. `install-local.sh` compares the
  signer and the team (Authority/TeamIdentifier) with the old installation, not the designated requirement (that
  contains the bundle ID and changes).
- **Uninstall:** `uninstall.sh` removes Lexomorph; with `--legacy` it also removes a previous SuperDictate
  installation (data is kept).

## 4. Rollback

Old data is not modified or deleted: `~/Library/Application Support/SuperDictate`, the domain `com.local.superdictate`,
the Keychain item `com.local.superdictate.vocab-sync`; on Windows the folder `%LOCALAPPDATA%\SuperDictate`.

- **macOS:** run `uninstall.sh`, then install the previous release (0.9.x); it uses its own data again.
- **Windows:** uninstall Lexomorph, install the previous `SuperDictate-0.9.x-setup.exe`; it uses `%LOCALAPPDATA%\SuperDictate`.

Edits made in Lexomorph after the migration do not flow back into the old data. To repeat the migration from scratch:
delete `~/Library/Application Support/Lexomorph` (or only the marker) and the domain `com.local.lexomorph` by hand on
macOS, or `%LOCALAPPDATA%\Lexomorph` on Windows. This is an explicit user action; the code does not do it.

## 5. How 0.9.x clients move over

- **macOS 0.9.x cannot update itself into Lexomorph.** The in-app updater checks the bundle ID, the name
  `SuperDictate.app` and the asset `SuperDictate.zip` (`UpdateCheck.swift` in 0.9.x). A release that carries only
  `Lexomorph.zip` fails that check (the download URL for `SuperDictate.zip` does not exist for the new tag). Users
  move over with `install.sh`.
- **Windows 0.9.x** only opens the release page and does not install anything itself; it accepts any `.exe`, `.msi` or
  `.zip` asset of the newest `win-v*` release, so `Lexomorph-Setup-1.0.0.exe` is offered normally and the user runs
  it. The installer removes the old SuperDictate and the first launch copies the data.

### Transition release (implemented as the bridge app; requirements kept for reference)

Implemented: `mac-v1.0.0` also publishes `SuperDictate.zip`, a bridge app under the old names that shows this explanation and installs Lexomorph (design: `docs/specs/transition-release-spec.md`, source: `bridge/`). The text below is the original requirement list.

Because 0.9.x macOS clients can never update into Lexomorph, a **transition release under the old names** is needed
before (or together with) 1.0.0. It must be built and published the old way: bundle `SuperDictate.app`, bundle ID
`com.local.superdictate`, the same signing identity, asset `SuperDictate.zip`, a `mac-v0.9.x` tag, `update.json` on
`main` with that version, so that the existing in-app updater accepts it. What it has to do:

1. Explain the rename: the app is now Lexomorph; the product, the app file and the package changed, and so did the
   signature identity of the package (the bundle ID), so macOS will ask for Microphone, Accessibility and Input
   Monitoring again; settings, vocabulary and models are carried over, and the old data is kept.
2. Lead the user to the installation of Lexomorph: show the one-line installer command or a link to the Releases page
   and the README (`install.sh`), instead of offering an in-app update to a release the old updater cannot install.
3. Teach the old update check to recognize a release of the Lexomorph era (for example a tag at or above `mac-v1.0.0`
   or a release without `SuperDictate.zip`) and show the explanation instead of attempting the update, so that 0.9.x
   users never see a failed download once 1.0.0 is published.
4. Optionally the same message on Windows (the 0.9.x Windows update notice is only a link to the release page, so the
   release notes of `win-v1.0.0` can carry the explanation instead).

The transition release must be out and given time to spread before `mac-v1.0.0` is published as the "latest" macOS
release; clients older than the transition release should be able to update into it with the old updater.

## 6. Risks and limits

- `install.sh` and `update.json` hold **placeholders** (SHA-256 of all zeros, source commit of all zeros, version 1.0.0)
  until the release procedure in `docs/RELEASING.md` fills them in; until then the installer fails on the checksum.
  Do not merge the rename into `main` before the release is published: the one-line installer in the README reads
  `install.sh` from `main`, and `update.json` on `main` is what the in-app updaters compare against.
- The first launch of Lexomorph while the old agent is still running: data is copied "on the fly" (if the installation
  did not go through the scripts). The scripts unload the old agent beforehand.
- A Keychain dialog may appear when the old token is read (the ACL is bound to the old package's signature).
- The published `SuperDictate.zip` is Intel-only (x86_64); the installer rejects other architectures, so Apple
  Silicon users build from source. Decide whether the 1.0.0 ZIP should be universal.
