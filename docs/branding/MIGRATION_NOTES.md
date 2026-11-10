# Lexomorph 0.10: переименование идентификаторов macOS и миграция

Решение владельца (отменяет прежнее «идентификаторы не менять»): имя SuperDictate / Parakey заменено везде в macOS-части,
включая идентификаторы. Версия 0.10.0. Этот документ описывает, что переименовано, как данные переезжают и как откатиться.

## 1. Что переименовано

| Было | Стало |
|---|---|
| `/Applications/SuperDictate.app`, исполняемый файл `SuperDictate` | `/Applications/Lexomorph.app`, `Lexomorph` |
| bundle id и домен UserDefaults `com.local.superdictate` | `com.local.lexomorph` |
| LaunchAgent `com.local.superdictate.agent` | `com.local.lexomorph.agent` (`~/Library/LaunchAgents/com.local.lexomorph.agent.plist`) |
| `~/Library/Application Support/SuperDictate` | `~/Library/Application Support/Lexomorph` |
| `~/Library/Logs/SuperDictate*` | `~/Library/Logs/Lexomorph-*` |
| Keychain `com.local.superdictate.vocab-sync` | `com.local.lexomorph.vocab-sync` |
| UTI `com.local.superdictate.corrections`, расширение `.superdictate-corrections` | `com.local.lexomorph.corrections`, `.lexomorph-corrections` (старые файлы продолжают импортироваться: объявлен импортируемый тип) |
| Хелперы `SuperDictateLLMHost`, `SuperDictateOnnxHost` | `LexomorphLLMHost`, `LexomorphOnnxHost` |
| SwiftPM-таргет и каталог `Parakey` | `Lexomorph` (`swift/Sources/Lexomorph`) |
| Иконка `icon/Parakey.icns`, `parakey-menubar*.png` | `icon/Lexomorph.icns`, `lexomorph-menubar*.png` |
| Релизный ассет `SuperDictate.zip` с `SuperDictate.app` | `Lexomorph.zip` с `Lexomorph.app` |
| Переменные окружения `SUPERDICTATE_*` (macOS-скрипты, Swift) | `LEXOMORPH_*` |

Намеренно не менялись (инфраструктура владельца или общий код с Windows): репозиторий `shohart/SuperDictate-Next` и все
ссылки на него, домен синхронизации `superdictate.bykovlegal.ru`, каталог `server/`, весь `windows/`, имя CMake-таргета
`SuperDictateOnnxHost` в `native/asr-runtime` (в бандл он кладётся под именем `LexomorphOnnxHost`), имена C++-файлов
`superdictate_*` в `swift/Sources/{llama_cpp_host,silero_vad}`, бренд-кредиты Parakey (Richard Courtman) и shlgd, история
(CHANGELOG, спецификации, планы), токены upstream-кэска Homebrew.

## 2. Миграция при первом запуске

Код: `swift/Sources/Lexomorph/Migration.swift`. Запускается и в агенте, и в Панели (`main.swift`) до создания делегата
(и значит до `Settings.shared`), под файловым локом `~/Library/Application Support/.lexomorph-migration.lock`
(ожидание до 20 с; не дождались: запуск идёт без миграции, повторится в следующий раз, маркера нет).
Запускается только в production-бандле `com.local.lexomorph` (тестовые бандлы и `swift build` без бандла не мигрируют).

1. UserDefaults: все ключи домена `com.local.superdictate` копируются в `com.local.lexomorph`, если такого ключа в новом
   домене ещё нет (существующие не перезаписываются). Не копируется `active_run_marker` (состояние старого процесса).
   Абсолютные пути внутри старой папки данных переписываются на новую. Сохранённый язык интерфейса переносится.
2. Папка данных: каждый элемент `Application Support/SuperDictate` клонируется в `Application Support/Lexomorph`
   системным `clonefile(2)` (APFS: модели на гигабайты не занимают место второй раз), во временное имя
   `.migrating-*` и затем атомарным переименованием; без APFS-клона используется обычное копирование. Уже существующие
   в новой папке элементы не затираются (sqlite-файлы `-wal/-shm/-journal` не присоединяются к чужой базе).
   Не переносятся `AgentStatus*.json`, `*.pid`, `*.lock` (состояние процессов).
3. Keychain: только в агенте, в фоновом потоке, после шага 1. Читается токен по старому service и e-mail из
   перенесённых настроек и записывается под новый service; если новый уже есть, он не трогается. Попытка делается
   ровно один раз: сбой или отказ в диалоге доступа считается окончательным (повторов и диалога на каждый запуск нет),
   пользователю достаточно войти в синхронизацию снова. Диалог Keychain не блокирует старт (главный поток его не ждёт).
4. Маркер `Application Support/Lexomorph/.migrated-from-superdictate.json`: версия приложения, дата, что скопировано и
   пропущено, итог Keychain, флаг показанного уведомления. Есть маркер: ничего не делается.
5. Одноразовое окно при первом запуске после миграции (только если старые данные были найдены): почему название и пакет
   изменились, что разрешения macOS нужно выдать заново, что данные перенесены, что старые данные остались нетронутыми.
   Окно не открывает ни одной панели «Конфиденциальность».

Разрешения macOS (микрофон, универсальный доступ, мониторинг ввода) переехать не могут: новый bundle id для системы новое
приложение. Это принято владельцем. `tccutil reset` не вызывается нигде.

## 3. Установка и старая установка

- `scripts/install-local.sh`, `install.sh`: ставят `/Applications/Lexomorph.app` атомарно, пишут/используют агент
  `com.local.lexomorph.agent`. Найдя `/Applications/SuperDictate.app` или агент `com.local.superdictate.agent`, выгружают
  старый агент, завершают его процесс и удаляют старый бандл и старый plist ТОЛЬКО после успешной установки нового и до
  запуска нового агента (чтобы два агента не боролись за горячую клавишу). Данные, Defaults и Keychain старого не трогаются.
- Подпись: идентичность не меняется и новые сертификаты не создаются. `install-local.sh` сравнивает подписанта и команду
  (Authority/TeamIdentifier) со старой установкой, а не designated requirement (он содержит bundle id и меняется).
- `uninstall.sh` удаляет Lexomorph; с флагом `--legacy` ещё и прежнюю установку SuperDictate (данные остаются).

## 4. Откат

Старые данные не изменяются и не удаляются: `~/Library/Application Support/SuperDictate`, домен `com.local.superdictate`,
Keychain `com.local.superdictate.vocab-sync`. Для отката: `uninstall.sh`, установить прежний релиз (0.9.x, он снова
использует свои данные). Правки, сделанные в Lexomorph после миграции, в старые данные не возвращаются. Чтобы повторить
миграцию с нуля: удалить `~/Library/Application Support/Lexomorph` (или только маркер) и домен `com.local.lexomorph`
вручную (это явное действие пользователя; код его не выполняет).

## 5. Риски и ограничения

- Клиенты 0.9.x не обновятся «изнутри» до Lexomorph: они проверяют bundle id, имя `SuperDictate.app` и ассет
  `SuperDictate.zip`. Переход делается установщиком (`install.sh`). Это нужно учесть при выпуске.
- `install.sh` и `update.json` содержат заглушки (SHA-256 из нулей, версия 0.10.0): `docs/RELEASING.md` заменяет их
  реальными значениями при выпуске; до этого установщик закрыт по контрольной сумме. Не вливать в `main` до релиза.
- Первый запуск Lexomorph при ещё работающем старом агенте: данные копируются «на лету» (если установка шла
  не через скрипты). Скрипты выгружают старый агент заранее.
- Диалог Keychain при чтении старого токена возможен (ACL привязан к подписи старого пакета).
