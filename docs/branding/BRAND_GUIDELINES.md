# Lexomorph: brand guidelines

**[Читать по-русски](BRAND_GUIDELINES.ru.md)**

An extract of `BRAND_SPEC_RU.md` (the brand delivery, version 1.0 of 10 November 2026), corrected for what the
repository actually contains. If this file or any marketing text disagrees with the code, the code is right; see
`REBRAND_AUDIT.md` (a historical document, written before the rename).

## 1. Identity

| | |
|---|---|
| Name | **Lexomorph** (lexicon + morph) |
| Former name | SuperDictate Next (before that SuperDictate-Intel). In user-facing text: "Lexomorph (formerly SuperDictate Next)" |
| Primary tagline | **Speak freely. Write precisely.** |
| Second tagline | Your speech. Your words. Your style. |
| One-line description | A personal adaptive writing engine that turns speech into text shaped by your vocabulary, corrections and preferred writing style. |
| GitHub About | Personal adaptive writing engine: dictation, correction, and style-aware text transformation. |
| Transition message | Lexomorph (formerly SuperDictate Next). Same project, a broader vision: from speech recognition to adaptive, personal writing. |

Language of the product and its marketing: English. English is also the base language of all documentation; the
Russian files (`*.ru.md`) are adapted translations with the same facts. This does not limit recognition or interface
languages (the app has RU and EN; the interface follows the system language by default).

Since 0.10.0 the product name is in the identifiers too (bundle, data paths, release assets). What is still named
SuperDictate (the repository, the sync server domain, the Python package, C++ names) and why is described in
`MIGRATION_NOTES.md`.

## 2. Tone and editorial rules

Precise, calm, technical. Plain English without promotional exaggeration. Benefits are described through verifiable
scenarios.

Unproven absolutes are forbidden: "100% privacy", "100% local", "zero hallucinations", "flawless transcription",
"learns instantly", "works entirely offline" (the first model download needs the network), "no account" without the
caveat about optional sync, "logs avoid transcript text" (there is `DictationTrace.jsonl`).

Good: "Keep preferred terminology consistent across dictations.", "Review and manage what the app remembers.",
"Choose local models or a remote endpoint of your own."
Bad: "The AI reads your mind.", "Never makes mistakes.", "Learns your style automatically." (learning from edits only
covers short word and phrase edits, by heuristics, with undo).

Personalization rule: describe the implemented mechanism (replacement dictionary, learning from edits, ASR hints,
rewrite modes). Nothing is fine-tuned on user data, and it must not be written that way. "Nothing is trained on your
device or on your data" is true; "the product has no fine-tuned models" is false (correction uses a LoRA adapter that
the project trained in advance).

Do not call the product a "dictaphone", an "AI magic service" or "voice notes". Use: adaptive dictation, personal
language adaptation, context-aware rewriting (only for rewrite modes; application context is not used),
local-first writing workflow, correction-driven personalization.

Features that do not exist (adaptation to the voice, adaptive routing, Lexomorph Studio, Lexomorph SDK, mobile
clients, syncing settings) are not claimed. Unreleased things are marked "unreleased" or "planned".

## 3. Names of areas

Only the name **Lexomorph** is approved. "Lexomorph Core", "Lexicon", "Rules" and "Sync" from the specification are
marked as proposals; until the owner approves them, the README does not use them as feature names. Do not create empty
packages for the sake of names. Studio and SDK are for the future only.

## 4. Visual system

Style: calm technical minimalism. Deep dark surfaces, precise typography, one graphic story (a signal turning into
orderly lines of text), a light grid, restrained glow.

Avoid: cliche microphones, brains made of lines, colored 3D balls, overloaded neon, empty waveform graphics, fake
interface screenshots passed off as real.

### Palette

| Token | HEX | Use |
|---|---|---|
| background.dark | `#0B1020` | main dark background |
| surface.dark | `#11182B` | panels |
| surface.secondary | `#17253C` | secondary blocks |
| text.primary | `#F3F6FC` | headings and main text |
| text.secondary | `#AAB6D3` | explanations |
| accent.blue | `#5DA9FF` | main accent |
| accent.cyan | `#5EE7D8` | process and positive accents |
| accent.violet | `#8C7CFF` | transitions and graphics |
| background.light | `#F7F9FC` | light version |
| text.light | `#0F172A` | text on a light background |
| divider | `#26324A` | dividers |

In text areas WCAG contrast takes priority; color must not be the only carrier of meaning.

### Typography

Recommended: Inter for the interface and documentation; Sora SemiBold or Inter SemiBold for large pieces; fallbacks
IBM Plex Sans or Manrope. Do not add font files to the repository or release packages without checking the
distribution license. In SVGs, when they appear, use a system fallback.

### The mark

Concept: a "morphing L". A wave stroke turns into a strict orthogonal letter L. The final icon in the delivery is a
square "LM" monogram. Requirements: square, safe margins of at least 12%, no tiny microtypography, legible at 24 to
32 px and checked at 16 px, working in one color and on both light and dark themes. System rounding for macOS and
Windows is applied by the platform; do not bake it into the base master.

The app icon (`icon/Lexomorph.icns`, `windows/assets/Lexomorph.ico`) and the macOS menu-bar template glyph
(`swift/Resources/lexomorph-menubar*.png`) are wired into both builds. Residual points that were not re-checked on a
real Dock and tray are listed in `MANUAL_OWNER_ACTIONS.md`.

## 5. Assets in the repository

Directory `docs/assets/branding/`; details and checksums in `docs/assets/branding/MANIFEST.md`.

| What | File |
|---|---|
| README header | `readme/readme-hero-1280x640.png` (alternative: `readme-hero-alternate-1280x640.png`) |
| GitHub social preview | `social/lexomorph-social-1280x640.png`; 1.91:1 variant `social/lexomorph-social-1200x630.png` |
| App icon | `icons/final-LM/lexomorph-icon-1024.png`, `lexomorph.icns`, `lexomorph.ico`, `lexomorph.iconset/` |
| Avatar | `icons/final-LM/lexomorph-avatar-512.png` (and 256, 1024) |
| Earlier icon variants | `icons/previous-versions/` |
| Feature cards | `features/*.png` (six, with `*.ru.png` Russian versions), grid `feature-grid-1536x1024.png` |
| Originals | `source-originals/` (eight unmodified PNGs) |

**There are no SVG masters.** All artwork is raster and generated. The files `assets/svg/*` and `assets/png/*` that
`ASSET_GUIDE.md` and `IMPLEMENTATION_TASK_EN.md` refer to are not in the delivery, so item 12 of the specification
(SVG and PNG in the repository) is only half met: PNG exists, SVG does not. There are also no separate
`app_icon_light`, `mark_transparent`, `wordmark_darkbg`, `mode_*`, `pipeline_diagram`, `release_card_template` or
`contact_sheet` files. The pipeline diagram in the README is drawn as text from the code, not taken from the brand.
If editable sources are needed, they have to be commissioned or drawn separately; a raster cannot honestly be called a
"master".

### Feature cards

The six cards were recreated in the branch `feat/brand-cards` with text checked against the code and are shown in the
README gallery: Adaptive Dictation, Personal Vocabulary, Correction Learning, Style Modes, Cross-Device Sync,
Local-First Privacy. Rules for card text (a card that breaks them must not be published):

- No adaptation to the user's voice: the only "adaptation" of recognition is ASR term hints from the vocabulary.
- No syncing of "settings": synced are the replacement dictionary, ASR terms, custom writing modes (name, color,
  instruction) and per-day usage counters, through an account the user signs in to. No phone or mobile client.
- No unqualified "your data stays with you": audio always stays on the device, but text goes to a custom LLM endpoint
  if the user picks one, and to the sync server if the user signs in.
- Learning from edits is heuristic, limited to short edits, and can be undone and turned off. Style modes need an LLM
  (local or your endpoint) and are off by default.

The hero contains three badges: Local-first, Adaptive ASR, Style-aware rewriting. "Adaptive ASR" is noticeably
stronger than what exists (term hints to the decoder); the text inside the image cannot be edited without the source.
This is recorded in `MANUAL_OWNER_ACTIONS.md`.

## 6. Usage rules

- Do not distort proportions. For a README at 100% width use the 1280 x 640 PNG.
- GitHub social preview: 1280 x 640 (GitHub recommends 1280 x 640, minimum 640 x 320); check the cropping.
- Do not publish private dictionaries, dictations, logs or keys in the README or in images.
- A real application screenshot: without personal data; until one exists, the README carries a marked placeholder.
- The license, NOTICE and credits (Parakey, Richard Courtman; SuperDictate, shlgd) are kept. A rename does not
  cancel authorship.
- The name `Lexomorph` has not been checked for availability (domains, trademarks, GitHub, brew, PyPI); the
  specification does not confirm legal clearance.
- The phrase "formerly SuperDictate Next" is used for one or two releases, or until the migration notes are published.
