# Lexomorph account sync

Small FastAPI + SQLite service that syncs a user's Lexomorph state between
their macOS and Windows installs. See the module docstring in `app.py` for the
account and sync model.

- API: `POST /v1/auth` (sign in; the first sign-in with a new e-mail creates
  the account), `DELETE /v1/auth`, `GET /v1/vocabulary?since=N`,
  `POST /v1/vocabulary`, `GET /healthz`.
- Collections sharing the single account `revision` (all optional in requests,
  default `[]` in responses for full backward compatibility):
  - `changes` / `entries`: replacement dictionary + tombstones (also appended
    to `events` for speech model improvement).
  - `hotwords`: custom ASR hotwords, tombstones, cap `VOCAB_SYNC_MAX_HOTWORD_ENTRIES`=5000.
  - `styles`: custom rewrite modes, tombstones, cap `VOCAB_SYNC_MAX_STYLES`=500.
  - `prompts`: edited full system prompts of built-in rewrite styles
    (`polish`, `structured_task`, `official`; 1..16000 chars verbatim, tombstone = reset).
  - `system_prompts`: edited full system prompts of non-rewrite stages
    (`correction`; 1..16000 chars verbatim, tombstone = reset).
  - `fillers`: filler word preset toggles and custom filler words, tombstones,
    cap `VOCAB_SYNC_MAX_FILLER_ENTRIES`=1000.
  - `prefs`: cross-platform text & vocabulary preferences (`remove_filler_words`,
    `normalize_numbers`, `remove_final_period`, `paste_suffix`, `dictation_language`,
    `auto_learn_vocabulary`, `asr_hotwords_enabled`, `asr_hotwords_strength`,
    `interface_language`), independent LWW per key.
  - `usage`: per-device per-day dictation statistics, absolute values, LWW.
- Only `entries` changes are written to `events`; all other collections never
  enter `events`.
- `GET /healthz` returns `{"ok": true, "capabilities": [...]}` so clients and
  operators can verify the deployed schema/collection set.
- Deployed on `octopusreborn` at `/home/shohart/services/superdictate-sync`
  (`docker compose up -d --build`), published on `10.77.77.2:8095` only;
  Caddy vhost `superdictate.bykovlegal.ru` in
  `/home/shohart/nc-project/caddyfile.conf`.
- Backup: the single file `data/vocab-sync.sqlite` (WAL; use
  `sqlite3 data/vocab-sync.sqlite ".backup out.sqlite"`).
- Tests: `python -m pytest test_app.py` (needs fastapi, httpx, pytest).
