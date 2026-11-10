# Lexomorph: actions for the owner

**[Читать по-русски](MANUAL_OWNER_ACTIONS.ru.md)**

These are irreversible, depend on external services or need a human decision; the agents did not do them. Details and
line numbers (as of before the rename) are in `REBRAND_AUDIT.md`. Identifiers are now Lexomorph; see
`MIGRATION_NOTES.md` for what changed and for the transition release.

## Done, no action needed

- The app icon and the macOS menu-bar glyph are wired into both builds (`icon/Lexomorph.icns`,
  `windows/assets/Lexomorph.ico`, `swift/Resources/lexomorph-menubar*.png`). Only the residual checks in section 6
  remain.
- Windows installer bugs **fixed** (`windows/installer/Lexomorph.iss`): the uninstall question about the data folder
  pointed at `{localappdata}\Dictation` instead of the real data folder, and the autostart value was created and then
  deleted by a `deletevalue` entry of the same name. Now the uninstall question names the real folders, and the only
  entry touching the value `Lexomorph` is the one that writes it (the deletions are for the old names only). The
  0.9.x uninstaller still has the `Dictation` bug; the new installer works around it when it removes an installed
  SuperDictate (it moves a `Dictation` folder aside for the duration). Per the CHANGELOG, the script compiles with
  Inno Setup on the Windows build PC; the installer itself was **not run** (see section 4).
- SECURITY.md and windows/README.md no longer contradict the code (account, "ad-hoc", "no builds", "nothing leaves
  the computer"); both have Russian versions.
- Brand documents are English-first with Russian adaptations next to them (`*.ru.md`).

## 1. Release order (the critical path)

1. **Transition release under the old names** (macOS `mac-v0.9.x`): explains the rename and leads to the Lexomorph
   installation, because 0.9.x clients cannot update into Lexomorph from inside the app. **Not implemented in the code
   yet; it is yours to build and publish.** Requirements are in `MIGRATION_NOTES.md`, section 5.
2. Let the transition release spread.
3. Publish 0.10.0 following `docs/RELEASING.md`: macOS `mac-v0.10.0` with `Lexomorph.zip`, Windows `win-v0.10.0` with
   `Lexomorph-Setup-0.10.0.exe` (never "latest"). Self-tests and the mandatory `scripts/verify-release.sh`.
4. Fill in the pins: `install.sh` (`RELEASE_SHA256`, `SOURCE_COMMIT`) and `update.json` currently hold placeholders
   (all zeros). **Do not merge `release/0.10.0` into `main` before the release is published.** `scripts/check.sh`
   checks that the version and SHA agree with `Info.plist`.
5. Run `gh workflow run "release smoke"` and wait for it to pass.
6. Release notes: "Lexomorph (formerly SuperDictate Next)"; permissions must be granted again on macOS; settings and
   data are carried over; the old data is left as a rollback.

## 2. Name, trademark, domains

- The name `Lexomorph` has not been checked for availability: trademarks, domains, GitHub, Homebrew, PyPI, app stores.
  The brand specification does not confirm legal clearance. Check before a public release.
- Approve the public wording: the README privacy table and the list of "exists / planned" features.
- Decide whether to rename the displayed mode names (`Polish`, `Structured task`, `Official` to Clean, Polish, Formal)
  and whether to introduce a Raw mode. Do not change the internal values (`polish`, `structured_task`, `official`).

## 3. Repository and sync domain rename (the owner does it; only after the transition release)

The repository `shohart/SuperDictate-Next` and the domain `superdictate.bykovlegal.ru` are deliberately kept in the
code and the documentation. Order:

1. Ship a macOS client that accepts both URL prefixes (`/shohart/SuperDictate-Next/` and the future one) in
   `UpdateCheck.sanitizedReleaseURL`, and wait until clients have updated.
2. Rename the repository (if the name is free). Do not create a new repository under the old name. Do not delete the
   branch `feat/llm-postproc-gec` (the correction adapter is downloaded from it).
3. Check the redirects with `curl -IL` for: the releases API list, raw `update.json`, raw `install.sh` and
   `uninstall.sh`, `releases/download/<tag>/Lexomorph.zip`, `raw/feat/llm-postproc-gec/...`.
4. Update the local `origin` (it may still point at `SuperDictate-Intel`),
   `.github/ISSUE_TEMPLATE/config.yml`, badges and links in the READMEs, the install commands in the READMEs, the
   strings in `scripts/check.sh` (otherwise CI fails), `release-smoke.yml`, `docs/RELEASING.md`, the URLs in the Swift
   and Windows update code, Pages and integrations if any.
5. For the sync domain: keep the old one or add a new one; clients are hard-wired to the old one, so both need to work
   (an alias). Confirm the privacy wording for the server: how passwords and tokens are stored and whether data is
   encrypted at rest has not been checked in the code or the specification.

## 4. Signing and checks on real machines

- Confirm that the release is signed with the same "PolterType Dev" certificate. If it is not, the designated
  requirement changes and everyone loses the macOS permissions (they are re-requested anyway because of the new
  bundle ID, but it must not happen a second time). Releases are not notarized.
- Any change to `Info.plist` changes the ZIP: a new checksum in `install.sh` and `update.json`, and the mandatory
  `scripts/verify-release.sh`.
- Run `Lexomorph-Setup-0.10.0.exe` on a clean Windows machine and on one with SuperDictate installed (removal of the
  old app, autostart, data copy, uninstall questions). So far it has only been built and compiled. There is no Windows
  CI.
- The Windows installer is not Authenticode-signed (SmartScreen warns). Decide whether to buy a certificate.
- Run the macOS migration on a machine that has real SuperDictate data (the migration self-test groups
  `legacy-migration` and `interface-language-default` use temporary data only).
- The published `SuperDictate.zip` is Intel-only (x86_64); Apple Silicon builds from source. Decide whether the 0.10.0
  ZIP should be universal.

## 5. GitHub: social preview, About, topics

- Upload `docs/assets/branding/social/lexomorph-social-1280x640.png` by hand: Settings, General, Social preview. For
  platforms with a 1.91:1 format use `lexomorph-social-1200x630.png`. Check the cropping.
- About: `Personal adaptive writing engine: dictation, correction, and style-aware text transformation.`
  Website/subtitle: `Speak freely. Write precisely.`
- Topics confirmed by the code: `dictation`, `speech-to-text`, `asr`, `macos`, `windows`, `local-ai`, `llm`, `onnx`.
  `text-normalization`, `personal-dictionary`, `writing-assistant` are acceptable with a caveat (the replacement
  dictionary exists; "writing assistant" is marketing wording).

## 6. Assets

- The brand delivery is raster only; **there are no SVG masters**. If editable sources of the logo, hero and cards are
  needed, they have to be made separately.
- Check the icon by eye: the rounded square used to take about 97% of the canvas (the Apple macOS template uses a body
  of about 824/1024 with margins), so in the Dock it may look larger than its neighbors; and the macOS menu-bar glyph
  should be a single-color alpha glyph. Legibility at 16 px, including with the colored status dot in the Windows
  tray, on light and dark taskbars, was not verified.
- The hero still carries the badge "Adaptive ASR" and a phrase about learning your writing style, both stronger than
  reality (the app has term hints to the decoder and replacement rules). The text inside the image cannot be edited
  without a source.
- The six feature cards (English and `*.ru.png`) are in the tree and shown in the README galleries. Their text was
  written to match the code; re-check it against the code, especially after any change to sync, modes or privacy behavior. The old
  cards were 458 to 471 px, not the 1200 x 675 the brand documents state; the new ones are 1200 x 675.
- Do not include fonts (Inter, Sora) in the repository without checking the license.
- Decide whether to keep `docs/assets/branding/source-originals/` (about 12 MB) in the repository or move it to a
  release.

## 7. Open bugs found during the audit (not fixed)

All of them are outside the rebrand. Not re-verified after the rename unless stated.

1. **Different defaults of the automatic update check:** macOS off (`Settings.swift`, `checkForUpdates`), Windows on
   (`settings.py`, `check_for_updates`). Both are documented as they are; decide whether to align them.
2. **API keys are stored as plain text:** macOS UserDefaults, Windows `Settings.json`. Documented in PRIVACY.md and
   SECURITY.md; moving them to the Keychain and DPAPI would remove the caveat.
3. **`scripts/check.sh` line about `shlgd/SuperDictate`:** the negation `! grep -q ...` under `set -e` does not stop
   the script, although the README must link to `shlgd/SuperDictate` as a credit. Fix it together with the decision
   of what exactly to forbid.
4. **`UpdateCheck.sanitizedReleaseURL`** accepts only one repository prefix (see section 3, step 1).
5. **The LoRA adapter link** points at the branch `feat/llm-postproc-gec` (`ModelDownload.swift`).
6. **`NOTICE.md`** carries a one-line note about the rename; check that the wording is acceptable. Credits are kept.
7. **PR template:** the network checkbox was refined; check that the wording suits you.
8. **The macOS installer (`install.sh`) prints Russian messages.** English is the documentation base; the installer
   text is code, which the documentation stream did not touch.
