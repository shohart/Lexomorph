# Lexomorph for Windows (formerly SuperDictate)

**[Читать по-русски](README.ru.md)**

Dictation on a hotkey: press, speak, and the text appears in the focused
field. Speech is recognized on your computer and audio is never sent anywhere.
The network is used only for model downloads, update checks and what you turn
on yourself (an external LLM endpoint, account sync); the full list is in
[Network and privacy](#network-and-privacy).

This is the Windows version of [Lexomorph](../README.md) (formerly SuperDictate
Next): the same recognition models, the same settings, the same
post-processing prompts. The code is separate (Python + PySide6 instead of
Swift + AppKit), but behavior and setting names are shared so that the same
thing means the same on both platforms.

Since 0.10.0 the app is called Lexomorph in every identifier: data folder
`%LOCALAPPDATA%\Lexomorph`, `Lexomorph.exe`, helpers `LexomorphOnnxHost.exe`
and `LexomorphOvHost.exe`, autostart value `Lexomorph`, environment variables
`LEXOMORPH_*` (the old `SUPERDICTATE_*` are still read as a fallback for one
more release). Still named SuperDictate: the Python package `superdictate`
(an internal name), the sync server address `superdictate.bykovlegal.ru` and
the repository `shohart/SuperDictate-Next` (the owner renames those; GitHub
redirects the old addresses).

**Moving from SuperDictate.** The installer `Lexomorph-Setup-X.Y.Z.exe` removes
an installed SuperDictate (program, shortcuts, autostart entry) but not its
data. On the first launch Lexomorph copies `%LOCALAPPDATA%\SuperDictate` to
`%LOCALAPPDATA%\Lexomorph`: settings as they are, history, vocabulary, the sync
token (re-protected under the new DPAPI entropy) and models (large model files
as hard links when the file system allows it). The original is not deleted; it
is the rollback path. Later launches copy nothing; if the copy was interrupted,
it resumes on the next launch. Older folders (`Dictation`, `D1CT`) are handled
the same way, newest name first. The interface language defaults to the system
language (Russian locale: Russian, otherwise English); a saved choice is kept.

Provenance and what this is based on: [PROVENANCE.md](PROVENANCE.md). The
chain of authorship: [NOTICE.md](NOTICE.md).

> **Status.** Ready-made installers are published on the
> [Releases page](https://github.com/shohart/SuperDictate-Next/releases) under
> `win-vX.Y.Z` tags (the newest published one is `win-v0.9.7`, still under the
> old SuperDictate name). `Lexomorph-Setup-0.10.0.exe` has been built and
> checked on the build machine but is not published yet. The installer is not
> Authenticode-signed, so SmartScreen may warn about an unknown publisher.
> Some macOS features are not ported yet; see
> [What is not there yet](#what-is-not-there-yet).

## What already works

**Speech recognition.** The same engine and models as the macOS version since
0.7.0: the native host `LexomorphOnnxHost` (C++ core from
[`native/asr-runtime`](../native/asr-runtime), ONNX Runtime 1.23.2) in a
separate process, CPU only. Models are downloaded from the shared pinned
catalog with a SHA-256 check:

| model | languages | size |
|---|---|---|
| Parakeet Ultra 0.6B, int8 (default) | 25, including Russian | ~600 MB |
| GigaAM v3 e2e RNN-T, int8 | Russian only: punctuation, case, yo, digits | ~220 MB |

The graphics card is left to the language model: Parakeet does not gain from
it, while post-processing gets several times faster.

**Intel NPU.** On laptops with Intel Core Ultra ("Intel AI Boost"), Settings >
Advanced > "Where to recognize" gains an "NPU" entry. The same two profiles run
there as OpenVINO builds in a second host, `LexomorphOvHost.exe`
(`superdictate/openvino_host.py`, the same IPC v1). Models are installed to
`Models\openvino\` from their own pinned catalog
(`assets/openvino-models.json`):

| profile | NPU model | size |
|---|---|---|
| Parakeet | [Parakeet TDT 0.6B v3, OpenVINO](https://huggingface.co/VoiceScribe/voicescribe-parakeet) | ~1.2 GB |
| GigaAM | [GigaAM v3, encoder calibrated for the NPU](https://huggingface.co/VoiceScribe/voicescribe-gigaam-npu) + the decoder from [voicescribe-gigaam](https://huggingface.co/VoiceScribe/voicescribe-gigaam) | ~220 MB |

On the first launch the model is compiled for the NPU: about 20 s for Parakeet,
4 to 10 minutes for GigaAM. Compilation runs in the background. If it does not
finish within 15 s, the encoder starts on the CPU (the same weights, the same
text) and moves to the NPU between dictations once compilation is done
(`EncoderSlot` in `openvino_asr.py`). The result is cached in
`Models\openvino\compiled`, and later loads take 1 to 3 s. Compilation uses
OpenVINO's built-in NPU compiler, not the driver one: the driver compiler
(32.0.100.3159) does not accept GigaAM's hybrid encoder. If the NPU does not
come up, recognition stays on the CPU. Headless check:
`python main.py --benchmark-transcribe gigaam_v3_onnx --npu file.wav`.

**Post-processing with a local language model**, the same as on the Mac, with
the same weights and prompts:

* **Correction** fixes recognition errors, case and punctuation and, above all,
  restores the Latin spelling of English terms: "задеплоил в кубернетис через
  докер компоуз" becomes "задеплоил в Kubernetes через Docker Compose". The
  default is Qwen3.5-0.8B with a fine-tuned adapter; the same models as on
  macOS are available (4B models, YandexGPT 8B). The result passes a guard: if
  the model dropped the first word or invented a term, the uncorrected text is
  used.
* **Rewrite** has three modes: Polish (remove repeats and clutter, keep the
  style), Structured task (expand into a structured brief) and Official
  (business register). The models are those of rewrite on macOS (YandexGPT 8B,
  Qwen3.5-9B, Gemma 4 E4B, 3 to 4B models).

  **Custom modes.** In Settings > Post-processing > Rewrite the list of modes
  is extended with your own: a name (up to 40 characters), a color, an
  instruction for the model and its own hotkey that switches to the mode (and
  turns rewrite on if it was off); the toast shows the mode color. The number
  is not limited. Deleting the selected mode returns to Polish. Modes (without
  hotkeys and without the active selection) sync through the account with
  macOS and other PCs (`superdictate/rewrite_styles.py`).

Both stages run locally on the built-in llama.cpp host (the same as on macOS),
on the CPU or on the graphics card (Vulkan: NVIDIA, AMD, Intel Arc), or through
an OpenAI-compatible API. The app does not take the GPU on faith: on the first
start of a model on the GPU it must repeat a short phrase word for word, and if
garbage or NaN comes back, that model runs on the CPU for the rest of the
session (with a notice in the capsule).

The two stages are independent, can run together, and **never lose text on any
failure**: model not downloaded, host did not start, timeout, and what came in
is returned.

**Replacement dictionary**, on SQLite, with automatic learning as on macOS: for
45 seconds after insertion the app watches the field through UI Automation
(`superdictate/edit_watch.py`). Fix one to three words in place ("инглиш" ->
"English") and change nothing for 4 seconds, and the rule is saved. During
those 4 seconds a pill "инглиш -> English" hangs over the field, as on macOS:
Enter saves at once, Esc or a click cancels (the pair is struck through).
Deletions, case-only edits, edits outside the inserted text and password
fields are not learned. Import and export use the **same versioned format** as
the macOS sync file, so the dictionary moves between platforms without
conversion. Punctuation-only edits, word forms of ordinary words ("Запомню" ->
"Запомни") and rewritten phrases are not offered at all
(`superdictate/vocabulary_hygiene.py`, the same rules as on macOS); the "Clean
up vocabulary..." button shows what would be deleted and fixed among what is
already learned and applies it after confirmation.

**ASR hints.** Terms from the dictionary (Latin letters, digits, acronyms, and
those ticked in the "ASR hint" column) are passed to the recognition model
itself (hotwords, `superdictate/asr_hotwords.py`), which then spells them
correctly more often. Enabled in the dictionary settings, strength "Normal" or
"Stronger". CPU recognition only; the NPU path ignores them.

**Account sync** (e-mail and password; the first sign-in creates the account)
between Windows and macOS: `superdictate/vocabulary_sync.py`. The token is
stored encrypted with DPAPI in `VocabularySync.token`; the password is not
stored. The same pass syncs your custom rewrite modes and dictation
statistics: this device's row (day, device) goes up as absolute values, other
devices' rows are kept separately in `UsageSync.json`, and the statistics
window shows the total across the account's devices.

**Long dictation** is cut at pauses, not by the clock: a short dictation with
a normal breath between phrases goes through in one piece, and only a really
long one starts to be cut. Neighboring pieces overlap, the handover point is
chosen by Silero VAD at the quietest spot, and a word heard twice at the seam
is dropped (`superdictate/transcription.py`, a port of `transcribeSegmented`).

**Instant start (optional).** Normally the microphone is opened only for the
recording, and opening the stream takes noticeable time, so the first words can
be clipped. Settings > Dictation > Capture > "Instant start - keep microphone
ready" (`instant_start_mode`, default Off): "1 minute after a dictation" keeps
the stream open for a minute after the last dictation, "Always" keeps it open
while the app runs. Recording then starts at once, and the first words are not
lost thanks to a short ring buffer. The price: while the stream is open,
Windows shows the microphone-in-use indicator. Nothing is sent anywhere, only
the last ~0.4 s is held in memory, and nothing is written to disk.

**Start and stop cues** (0.10.0) are played from preloaded buffers. The stop
cue goes out before the slow stream close and resampling and is not recorded.
The start cue goes out before the stream opens only when the last real open was
fast (average under 60 ms) or the stream is already warm (Instant start);
otherwise it waits for capture, so hearing it means it is safe to speak. See
[Recording latency bench](#recording-latency-bench) to measure it.

**The capsule** shows level bars or a dictation timer (it appears after ten
seconds so that short phrases do not turn into a stopwatch), with configurable
colors and size.

**The rest:** auto-stop on silence, numbers as digits, filler-word removal,
dictation history, autostart, muting sound while recording.

## What is not there yet

The port continues, and this is the honest list of what the Windows version
does not have:

| | |
|---|---|
| HUD color "Contrast" | pointless while the capsule is always dark; see below |

**About "Contrast".** On macOS this color adapts to the capsule background:
dark on light, white on dark. Here the capsule is always dark (`CAPSULE_FILL` is
a constant), so "Contrast" would always resolve to the white that is already in
the list. It only makes sense to port it together with a light capsule theme,
which is separate work, not a settings port.

**About filler words.** An early edition of this file claimed a flat list
instead of curated presets. That was wrong: there are **38** presets here
against 27 on macOS, a four-column checklist and a field for your own words.
Only storage differs: macOS keeps stable keys (`ru_tipa`), here it is a list of
enabled words; unifying them for settings portability is worthwhile, but
functionally everything is there.

## Hotkeys

| Action | Keys |
|---|---|
| Dictation | right **Ctrl** |
| Finish the other way (insert + Enter) | **Alt** + right **Ctrl**, during recording |
| Cancel recording | **Esc** |
| History | **Shift** + right **Ctrl** |
| Correction on/off | **Ctrl + Alt + C** |
| Rewrite on/off | **Ctrl + Alt + R** |
| Next rewrite mode | **Ctrl + Alt + S** |

The second chord works as on macOS. Pressed during recording, it finishes the
dictation with the opposite action: if the main chord only inserts the text,
the second inserts it and presses Enter, and the other way round. Handy for
sending an instruction to an agent or a chat message at once. It can be turned
off.

The last three chords differ from the macOS version, where they are on F13 to
F15: PC keyboards almost never have those keys. Alt+Shift and Ctrl+Shift are
deliberately left free: they switch the keyboard layout. Everything can be
rebound in Settings > Shortcuts.

## Installation

Download `Lexomorph-Setup-X.Y.Z.exe` from the newest `win-v*` entry on the
[Releases page](https://github.com/shohart/SuperDictate-Next/releases) and run
it. Windows releases are never marked "Latest", so the "latest" link leads to
the macOS release. The install is per user and needs no administrator rights;
the minimum is Windows 10 version 1809 (build 17763), 64-bit. The installer is
in English and Russian (by the system language), and autostart is a checkbox.
It is not Authenticode-signed.

The 0.10.0 installer installs a new application (a new AppId): it closes and
removes an installed SuperDictate (program, shortcuts, autostart entry) and
leaves its data alone. When uninstalling, Lexomorph asks whether to delete the
data folder and the old SuperDictate folder (the backup the migration copied
from). Bugs fixed in this installer: the uninstall data question used to
point at `Dictation` instead of the real data folder, and the autostart value
was written and then deleted by a `deletevalue` entry of the same name.

Updating: the app checks for new `win-v*` releases (**on by default**, turn it
off in Settings > Advanced) and shows a notification. It downloads and runs
nothing by itself: the release page opens in the browser and you run the new
installer yourself.

## Network and privacy

Speech recognition, history and the dictionary work locally. What can leave the
computer (the full list is in [PRIVACY.md](../PRIVACY.md)):

* model downloads (huggingface.co, pinned revisions, SHA-256 checked; Silero
  VAD after the speech model loads; local LLMs when you press download);
* the update check (api.github.com): on by default, can be turned off;
* an external OpenAI-compatible endpoint for correction or rewrite, **only if
  you choose it**: the dictated text and the instruction (no audio) go there,
  with your API key. The key is stored in `Settings.json` **as plain text**;
* account sync (off by default, `superdictate.bykovlegal.ru`): replacement
  rules, ASR terms, your custom modes and per-day statistics. The token is kept
  DPAPI-encrypted (`VocabularySync.token`); the password is not stored.

There is no analytics or telemetry.

## Running from source

You need Python 3.11 (the dependencies are pinned to it), CMake and Visual
Studio 2022 / Build Tools with C++.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\tools\build-onnx-host.ps1        # recognition host -> onnx-asr\
python main.py
```

Silero VAD is built into `engines\` by a separate script (`build.ps1` calls it
too); without `engines\silero-vad.dll` the seams of long dictation are chosen
by signal energy:

```powershell
.\tools\build-engines.ps1        # silero-vad.dll -> engines\
```

Local correction and rewrite go through the same host as on macOS
(`lexomorph-llm-host.exe`, vendored llama.cpp with CPU and Vulkan). `build.ps1`
builds it through `tools\build-engines.ps1 -ExperimentalLlmHost -Vulkan`, which
needs the Vulkan SDK. The host keeps a snapshot of the shared beginning of the
correction prompt (system prompt and examples, ~276 of ~295 tokens) and
computes only the phrase itself. The model is loaded and warmed up in the
background once the app is ready. The VoiceScribe weights live in
`%LOCALAPPDATA%\Lexomorph\Models\llm\` and are downloaded from the settings;
CPU or GPU is chosen there too.

Measurements on a Core Ultra 5 225H (Arc 130T, driver 32.0.101.6554), on the
65-phrase corpus `benchmark/corpus/correction.jsonl`:

| backend | median / p90 per phrase | quality |
|---|---|---|
| **CPU, our host, 8 threads** | **0.25 / 0.34 s** | 63/65 answers as the reference |
| **Vulkan, our host** | **0.44 / 0.52 s** | EM 0.646 |
| CPU, `llama-server` (up to 0.8.3.1) | 0.32 / 0.43 s | EM 0.646, reference |
| Vulkan, `llama-server` | 0.50 / 0.58 s | same as CPU |
| Vulkan by default | 0.40 s | **empty and garbage answers** |
| SYCL | does not start on this driver | - |
| llama.cpp + OpenVINO | Qwen3.5 not supported (graph error) | - |

Two host settings are mandatory, and `llm/host.py` (`host_command`) sets them
itself:

* **Cooperative matrix shaders are off.** On this Intel driver they break
  batched prompt processing; without them Vulkan is both correct and faster.
* **Threads: physical cores minus two, at most 8.** On all 14 cores of the
  225H (E- and LP-cores included) the thread pool waits for the slowest thread
  at every barrier. Once other programs take the CPU, correction stretches to
  minutes.

`tools\fetch-llama.ps1` (the official `llama-server`) remains as a fallback
host: the app takes it if the build has no host of its own.

Correction and rewrite can also be pointed at an external OpenAI-compatible API
(LM Studio, Ollama, a cloud): the address, key and model are set in the
settings.

Windows releases are tagged `win-vX.Y.Z` and are never marked "Latest" (so that
Mac clients do not see them). How to build and publish a release:
[`docs/RELEASING.md`](../docs/RELEASING.md).

### Building the installer

```powershell
.\build.ps1                          # self-tests, speech host, Silero VAD, LLM host, PyInstaller
ISCC.exe installer\Lexomorph.iss     # -> dist\Lexomorph-Setup-X.Y.Z.exe
```

`build.ps1` produces `dist\Lexomorph\Lexomorph.exe`. The version lives in
`superdictate/version.py` and `AppVersion` in `installer\Lexomorph.iss`.

### Self-test

Without a microphone or a model:

```powershell
python main.py --self-test
```

Recognition with the real host, headless (16 kHz mono WAV):

```powershell
python main.py --benchmark-transcribe parakeet_ultra_onnx recording.wav
python main.py --benchmark-transcribe gigaam_v3_onnx recording.wav
```

### Recording latency bench

Measures what you feel between pressing the record hotkey and hearing the start
cue or having the microphone open, and the same for stop. No window, hook or
model is needed:

```powershell
python main.py --bench-record-latency 20             # 20 runs on the real microphone
python main.py --bench-record-latency 20 --warm      # with "Instant start: Always"
python main.py --bench-record-latency 20 --fake-mic  # a fake microphone with a set delay
```

It drives the real `Recorder` and `Sounds` in the order the app uses and prints
the time from the key press to the start cue and to an open microphone (and the
same for stop). The path from the real keystroke to the Qt thread and the
audible device latency cannot be seen from a script; the report says so. Extra
flags: `--open-ms` and `--close-ms` (for `--fake-mic`), `--legacy-order` (the
old order, for comparison), and an optional device name as the second argument.

## Environment variables

The primary prefix is `LEXOMORPH_`; the pre-0.10 `SUPERDICTATE_` is read as a
fallback (for one more release) when the new variable is not set.

| Variable | What it does |
|---|---|
| `LEXOMORPH_HOME` | data folder instead of `%LOCALAPPDATA%\Lexomorph` |
| `LEXOMORPH_ASR_THREADS` | number of recognition threads (1..32) |
| `SUPERDICTATE_VULKAN_SHADER_DIR` | Vulkan shader folder for the LLM host; the app sets it itself, and the native host reads this name, which was not renamed |

## Data

Everything lives in `%LOCALAPPDATA%\Lexomorph\`:

| | |
|---|---|
| `Settings.json` | settings (including API keys as plain text) |
| `History.json` | dictation history |
| `corrections.sqlite` | replacement dictionary |
| `VocabularySync.token` | sync token (DPAPI) |
| `Usage.json`, `UsageSync.json` | this PC's statistics; device id and other devices' rows |
| `Models\` | model weights (`Models\onnx\<model_id>\` is recognition) |
| `Logs\` | logs |

Earlier folders (`SuperDictate`, and before it `Dictation` and `D1CT`) are
copied here on the first launch, so nothing has to be downloaded again (details
at the top of this file). The original stays as the rollback path.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
