# SuperDictate vocabulary sync

Small FastAPI + SQLite service that syncs the replacement dictionary between
a user's macOS and Windows installs. See the module docstring in `app.py`
for the account and sync model.

- API: `POST /v1/auth` (sign in; the first sign-in with a new e-mail creates
  the account), `DELETE /v1/auth`, `GET /v1/vocabulary?since=N`,
  `POST /v1/vocabulary`, `GET /healthz`.
- Besides `changes`/`hotwords`, the same payload carries optional `styles`
  (custom rewrite modes, tombstones, cap `VOCAB_SYNC_MAX_STYLES`=500) and
  `prompts` (edited full system prompts of the built-in styles `polish`,
  `structured_task`, `official`; 1..16000 chars verbatim, tombstone = reset
  to default, LWW, max 3 rows per account) and
  `usage` (per-device per-day dictation statistics, absolute values, LWW).
  They share the account revision, are `[]` for old clients, and are never
  written to `events`.
- Every accepted correction change is appended to the `events` table (training data;
  the apps tell the user before sign-in).
- Deployed on octopusreborn at `/home/shohart/services/superdictate-sync`
  (`docker compose up -d --build`), published on `10.77.77.2:8095` only;
  Caddy vhost `superdictate.bykovlegal.ru` in
  `/home/shohart/nc-project/caddyfile.conf`.
- Backup: the single file `data/vocab-sync.sqlite` (WAL; use
  `sqlite3 data/vocab-sync.sqlite ".backup out.sqlite"`).
- Tests: `python -m pytest test_app.py` (needs fastapi, httpx, pytest).
