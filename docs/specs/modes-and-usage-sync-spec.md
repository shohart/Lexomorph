# Спецификация: синхронизация режимов рерайта и статистики диктовок

**Ветка:** `feat/sync-modes-stats` (от `origin/main`, 0.9.7). **Релиза нет**, только коммиты.
**Основание:** запрос пользователя 2026-11-10.

## 1. Цели

1. Пользовательские режимы рерайта (имя, цвет, инструкция; без лимита на разумное число — серверный потолок 500)
   создаются на любой платформе и синхронизируются через аккаунт между macOS и Windows.
2. Статистика диктовок едина по всем устройствам аккаунта.
3. Пользователь без аккаунта и старые клиенты/серверы не ломаются (поля опциональны, как у `hotwords`).

## 2. Что уже есть
- macOS: `CustomRewriteStyle` (id `c-<uuid>`, name, colorHex, instruction, hotkey), UI «Свои режимы» (с 0.8.0).
- Windows: `rewrite_custom_styles_v1` / `rewrite_custom_style_id_v1` в settings, поддержка в пайплайне.
  Нужно проверить наличие UI создания/редактирования; если нет — добавить (имя, цвет, инструкция, хоткей).
- Статистика: macOS `DailyDictationUsage` (day, dictationCount, characterCount, audioSeconds, asrSeconds);
  Windows `UsageStats`/`DailyUsage` (day, dictations, audio_seconds, characters, words).
- Sync: `server/vocab-sync` (FastAPI+SQLite), `POST/GET /v1/vocabulary`, общий `revision`, LWW по `updated_at`
  (ISO-8601 TEXT), tombstones, коллекции `changes`/`hotwords`.

## 3. Контракт API (аддитивный, тот же эндпоинт и тот же revision)

Push (`POST /v1/vocabulary`) получает два новых необязательных массива, pull/push-ответ — два новых массива
(по умолчанию `[]`). Клиент определяет, что сервер старый, по отсутствию поля в ответе (как у `hotwords`,
`serverStoresHotwords`) и тогда повторяет отправку позже.

### 3.1 `styles`
```json
{"id":"c-6f1c…","name":"Деловой","color":"#FF8800","instruction":"…","deleted":false,"updated_at":"2026-11-10T12:00:00Z"}
```
- Ключ — `id` (строка `c-` + UUID, ≤ 64). `name` 1…40 симв., `color` `#RRGGBB`, `instruction` ≤ 4000.
  Для `deleted=true` name/instruction могут быть пустыми.
- LWW по `updated_at`; при равенстве побеждает сервер. Потолок живых строк 500 (`VOCAB_SYNC_MAX_STYLES`).
- Таблица `style_entries(account_id, id, name, color, instruction, deleted, updated_at, revision)`.
- **Хоткеи НЕ синхронизируются** (коды клавиш зависят от платформы) — это локальная настройка устройства.
  **Выбранный активный режим тоже локален.** Решение автора спеки, чтобы смена режима на одном ПК не меняла другой.
- Удаление активного режима на устройстве -> фолбэк на `polish` (уже реализовано на macOS; на Windows — проверить).
- Принятые стили не пишутся в `events`.

### 3.2 `usage`
```json
{"day":"2026-11-10","device":"<uuid>","dictations":12,"characters":3400,"words":510,
 "audio_seconds":210.5,"asr_seconds":14.2,"updated_at":"2026-11-10T12:00:00Z"}
```
- Строка = (день, устройство). **Каждое устройство пишет только собственные строки, абсолютными значениями за
  день** (не дельтами): повторная отправка идемпотентна, двойного счёта нет, конфликтов нет.
  Ключ `(account_id, day, device)`, LWW по `updated_at` (ошибка/откат часов не страшна).
- `device` — случайный UUID, создаётся при первой синхронизации и хранится локально; ≤ 64 симв.
  `day` — `YYYY-MM-DD` в локальном часовом поясе устройства. Скрытые от платформы поля (`words` на macOS,
  `asr_seconds` на Windows) = 0/null, на чтении суммируются как 0.
- Потолок: 400 дней на устройство (клиент шлёт только последние 400); сервер хранит всё, не удаляет.
- Таблица `usage_days(account_id, day, device, dictations, characters, words, audio_seconds, asr_seconds,
  updated_at, revision)`; `revision` растёт при каждом принятом изменении, pull отдаёт строки с `revision > since`.
- Клиент: единая статистика = сумма по всем устройствам (своя строка берётся из локального счётчика, а не из
  эха сервера). Для `words` на macOS, где нет собственного счётчика, показывать только если ненулевое.
  Историю до включения синхронизации не теряем: локальные дни при первой отправке превращаются в строки устройства.

## 4. Клиенты
- **Sync-цикл** не меняется: триггеры, backoff, курсор/revision общие. Добавляются приём/отправка `styles` и `usage`
  в `VocabularySyncEngine` (Swift) и `vocabulary_sync.py` (Windows).
- Применение удалённых стилей не должно вызывать `onLocalChange` (чтобы не зациклить синхронизацию) — как
  `applyRemoteHotwords`. Локальное создание/правка/удаление стиля помечает `updated_at`, tombstone хранится локально.
- Вход в синхронизацию уже есть в UI словаря; отдельных настроек не добавляем. Текст согласия на сервере
  (events) не меняется: стили и статистика в `events` не попадают.

## 5. Тесты и сборка
- Сервер: pytest — LWW для стилей, tombstone, потолок, idempotent usage, мульти-устройство, обратная совместимость
  (старый клиент без полей), `since`.
- macOS: self-tests (стили-roundtrip, merge удалённых, usage-merge/суммирование, wire-совместимость), `swift build`
  (debug и release) на Intel Mac, `--self-test` из командной строки. **Не запускать скопированные .app** (AGENTS.md).
- Windows: `selftest` Python на Windows-машине, сборка `windows/build.ps1`.
- Релиз не делается; версия и CHANGELOG не меняются (кроме раздела Unreleased, если он есть).
