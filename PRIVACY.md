# 🔒 Privacy

**[Читать по-русски](PRIVACY.ru.md)**

Lexomorph (formerly SuperDictate Next) is built around local speech
recognition. This page lists what stays on your device and what can leave it.
The sync server address still carries the old name on purpose;
see [docs/branding/MIGRATION_NOTES.md](docs/branding/MIGRATION_NOTES.md).

## 💾 Data that stays on your device

- **Audio is recognized locally.** Microphone audio is never sent to a
  transcription service. Recognition runs in a helper process on your CPU (on
  Windows with a supported Intel NPU, optionally on the NPU).
- **Transcripts are stored locally, in readable form.** The dictation history
  and settings are kept in `~/Library/Application Support/Lexomorph` (macOS)
  or `%LOCALAPPDATA%\Lexomorph` (Windows). The history contains the dictated
  text.
- **`DictationTrace.jsonl`.** Since 0.9.7 a local file records, for the last
  2000 to 4000 dictations, what recognition wrote, the text after the rules,
  and the final text. It stays on your computer. Delete it if you do not want it.
- **Replacement dictionary and ASR terms** are stored locally
  (`corrections.sqlite` on macOS).
- **Diagnostic logs** are in `~/Library/Logs/Lexomorph-*` (macOS). They are
  not guaranteed to be free of transcript text; do not paste logs publicly
  without reading them.
- **Interrupted recordings.** If the app crashes, the unfinished audio is kept
  for recovery and removed after it is handled.
- **API keys are stored as plain text.** If you configure your own LLM
  endpoint, its API key is written unencrypted to the settings (macOS
  UserDefaults, Windows `Settings.json`). Do not reuse a key you cannot rotate.
  The sync token is stored in the macOS Keychain or protected with Windows DPAPI.
- There is no analytics or telemetry code.

## 🌐 What can leave your device

| What | Where to | When | What is sent |
|---|---|---|---|
| Speech and punctuation models | huggingface.co (pinned revisions, SHA-256 checked) | first run or when you choose another model | a file request |
| Silero VAD file | huggingface.co | automatically after the speech model loads | a file request |
| Local LLM models and the correction adapter | pinned model catalog; the adapter from this project's GitHub repository | when you press download | a file request |
| Update check | api.github.com, raw.githubusercontent.com | macOS: when you open the panel, plus a background check if you enable it (off by default). Windows: automatic by default | a request for the release list |
| Installer | github.com, raw.githubusercontent.com | when you run `install.sh` | downloads the release and checks it |
| LLM correction or rewrite on your own endpoint | the URL you enter | only if you select the custom endpoint (off by default) | **the dictated text and the instruction prompt** (no audio), with your API key |
| Account sync | the server operated by the project owner at `superdictate.bykovlegal.ru` (code in `server/vocab-sync`) | only after you sign in (off by default) | replacement rules (source text, replacement, origin, ASR-hint flag) and ASR terms; since 1.0.0 also your custom mode names, colors and instructions and per-day usage counters; your e-mail and password to sign in |

Whatever you dictate and send through a custom endpoint is handled under that
provider's terms, not under this page. Sync content is stored on the sync
server; how that server stores credentials and data at rest has not been
documented or audited here.

Folder-based sync of the replacement dictionary between Macs writes one JSON
file to a folder you choose; whatever syncs that folder (iCloud, Dropbox,
Syncthing) sees it.

## 🔐 macOS permissions

- **Microphone** records speech while dictation is active.
- **Accessibility** inserts the resulting text into the focused field.
- **Input Monitoring** observes the configured global hotkey.

In macOS Privacy settings the app is listed as **Lexomorph**. Because the bundle identifier changed in 1.0.0, macOS treats it as a new app and asks for these permissions again.
