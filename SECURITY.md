# 🔒 Security

**[Читать по-русски](SECURITY.ru.md)**

## Reporting a vulnerability

Please report a suspected vulnerability privately through GitHub's
**Security > Report a vulnerability** page for this repository. Do not include
private transcript text, audio, credentials, or full diagnostic logs in a
public issue.

## How Lexomorph is hardened

**Network use.** Audio is recognized on your device and is never sent
anywhere. The app talks to the network only for: downloading models (pinned
revisions, SHA-256 checked), checking for updates, and what you turn on
yourself: an LLM endpoint of your own (it receives the dictated text and the
instruction prompt, not audio) and account sync (replacement rules, ASR terms,
custom modes and usage counters). Nothing in the code is analytics or
telemetry. The full table is in [PRIVACY.md](PRIVACY.md).

- **Update check.** On macOS it runs when you open the panel, plus a background
  check that is **off by default**. On Windows the automatic check is **on by
  default** and can be turned off in Settings > Advanced. Either way it only
  requests the release list from GitHub; the Windows app opens the release page
  and never downloads or runs anything by itself.
- **Accounts.** No account is needed to use the app. An account exists only for
  the optional sync, which is off until you sign in. How the sync server
  (operated by the project owner) stores credentials and data at rest has not
  been documented or audited here.

**Secrets storage.**

- The **API key** of a custom LLM endpoint is stored **as plain text**: in the
  settings (macOS UserDefaults) or in `Settings.json` (Windows). Treat anyone
  who can read your user profile as able to read the key, and use a key you can
  rotate.
- The **sync token** is stored in the macOS Keychain (service
  `com.local.lexomorph.vocab-sync`) or, on Windows, encrypted with DPAPI for the
  current user in `VocabularySync.token`. The password is not stored.
- History and `DictationTrace.jsonl` contain the dictated text and are not
  encrypted; they stay on your computer.

**macOS release builds** are signed with a developer certificate ("PolterType
Dev") and are **not notarized by Apple**. A ZIP downloaded through a browser
can therefore trigger a Gatekeeper warning. The default installer downloads a
version-pinned release bundle and verifies its SHA-256, version, bundle
identifier, architecture, code signature, and required microphone
entitlements. It does not disable Gatekeeper with `xattr`. Local builds made
with `scripts/build-app.sh` are signed ad-hoc unless you pass `SIGN_IDENTITY`;
`scripts/install-local.sh` uses the local Apple Development identity when
available. Users who require a locally built binary can run the source-build
installer documented in [README.md](README.md).

**The Windows installer** (`Lexomorph-Setup-X.Y.Z.exe`) is **not
Authenticode-signed**, so SmartScreen may warn about an unknown publisher.
Download it only from this repository's Releases page. It installs per user and
needs no administrator rights.
