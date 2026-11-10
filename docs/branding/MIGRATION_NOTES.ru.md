# Lexomorph 1.0: переименование идентификаторов и миграция данных

**[Read this in English](MIGRATION_NOTES.md)** (основной вариант; этот файл — его русская адаптация).

Решение владельца (оно отменяет прежнее «идентификаторы не менять»): имена SuperDictate и Parakey заменены везде в
macOS-части, включая идентификаторы, а также в Windows-версии. Версия — 1.0.0. Здесь описано, что переименовано, как
переезжают данные, как откатиться и что ещё не сделано для релиза.

## 1. Что переименовано

### macOS

| Было | Стало |
|---|---|
| `/Applications/SuperDictate.app`, исполняемый файл `SuperDictate` | `/Applications/Lexomorph.app`, `Lexomorph` |
| bundle ID и домен UserDefaults `com.local.superdictate` | `com.local.lexomorph` |
| LaunchAgent `com.local.superdictate.agent` | `com.local.lexomorph.agent` (`~/Library/LaunchAgents/com.local.lexomorph.agent.plist`) |
| `~/Library/Application Support/SuperDictate` | `~/Library/Application Support/Lexomorph` |
| `~/Library/Logs/SuperDictate*` | `~/Library/Logs/Lexomorph-*` |
| Keychain `com.local.superdictate.vocab-sync` | `com.local.lexomorph.vocab-sync` |
| UTI `com.local.superdictate.corrections`, расширение `.superdictate-corrections` | `com.local.lexomorph.corrections`, `.lexomorph-corrections` (старые файлы по-прежнему импортируются: старый тип объявлен как импортируемый) |
| Хелперы `SuperDictateLLMHost`, `SuperDictateOnnxHost` | `LexomorphLLMHost`, `LexomorphOnnxHost` |
| Таргет SwiftPM и каталог `Parakey` | `Lexomorph` (`swift/Sources/Lexomorph`) |
| Иконка `icon/Parakey.icns`, `parakey-menubar*.png` | `icon/Lexomorph.icns`, `lexomorph-menubar*.png` |
| Релизный ассет `SuperDictate.zip` с `SuperDictate.app` | `Lexomorph.zip` с `Lexomorph.app` |
| Переменные окружения `SUPERDICTATE_*` (скрипты macOS, Swift) | `LEXOMORPH_*` |

### Windows

| Было | Стало |
|---|---|
| `%LOCALAPPDATA%\SuperDictate` | `%LOCALAPPDATA%\Lexomorph` |
| `SuperDictate.exe`, `SuperDictateOnnxHost.exe`, `SuperDictateOvHost.exe` и хост LLM | `Lexomorph.exe`, `LexomorphOnnxHost.exe`, `LexomorphOvHost.exe`, `lexomorph-llm-host.exe` |
| Установщик `SuperDictate-X.Y.Z-setup.exe` (старый AppId) | `Lexomorph-Setup-X.Y.Z.exe` (новый AppId) |
| Значение автозапуска `SuperDictate` | `Lexomorph` |
| Переменные `SUPERDICTATE_*` | `LEXOMORPH_*` (старые читаются как запасные ещё один релиз) |
| Энтропия DPAPI `com.local.superdictate.vocab-sync` | `com.lexomorph.vocab-sync` (старая ещё принимается при чтении; токен перезащищается новой) |

### Намеренно не переименовано

Инфраструктура владельца или код, общий с Windows: репозиторий `shohart/SuperDictate-Next` и все ссылки на него, домен
синхронизации `superdictate.bykovlegal.ru`, каталог `server/`, Python-пакет `superdictate` в `windows/`, CMake-таргет
`SuperDictateOnnxHost` в `native/asr-runtime` (в бандл он кладётся как `LexomorphOnnxHost`), имена C++-файлов
`superdictate_*` в `swift/Sources/{llama_cpp_host,silero_vad}`, переменная `SUPERDICTATE_VULKAN_SHADER_DIR`, которую
читает нативный хост LLM, кредиты Parakey (Richard Courtman) и shlgd, история (CHANGELOG, спецификации, планы) и токены
upstream-кэска Homebrew. Репозиторий и домен синхронизации владелец переименует позже; GitHub перенаправляет старые
адреса репозитория.

## 2. Миграция при первом запуске

### macOS

Код: `swift/Sources/Lexomorph/Migration.swift`. Запускается и в агенте, и в Панели (`main.swift`) до создания делегата
(а значит, до `Settings.shared`), под файловой блокировкой `~/Library/Application Support/.lexomorph-migration.lock`
(ожидание до 20 с; не дождались — приложение стартует без миграции, она повторится в следующий раз, маркер не
пишется). Работает только в production-бандле `com.local.lexomorph` (тестовые бандлы и голый `swift build` не
мигрируют).

1. **UserDefaults:** все ключи домена `com.local.superdictate` копируются в `com.local.lexomorph`, если такого ключа в
   новом домене ещё нет (существующие не перезаписываются). `active_run_marker` (состояние старого процесса) не
   копируется. Абсолютные пути внутри старой папки данных переписываются на новую. Сохранённый язык интерфейса
   переносится.
2. **Папка данных:** каждый элемент `Application Support/SuperDictate` клонируется в `Application Support/Lexomorph`
   вызовом `clonefile(2)` (APFS: модели в несколько гигабайт не занимают место дважды) во временное имя `.migrating-*`,
   затем атомарно переименовывается; без APFS-клона делается обычное копирование. Уже существующие в новой папке
   элементы не затираются (файлы sqlite `-wal/-shm/-journal` не приклеиваются к чужой базе). `AgentStatus*.json`,
   `*.pid` и `*.lock` (состояние процессов) не переносятся.
3. **Keychain:** только в агенте, в фоновом потоке, после шага 1. Токен читается по старому service, e-mail берётся из
   перенесённых настроек, токен записывается под новый service; если новый уже есть, его не трогают. Попытка делается
   ровно один раз: сбой или отказ в диалоге доступа окончательны (без повторов и без диалога при каждом запуске);
   пользователю остаётся просто снова войти в синхронизацию. Диалог Keychain не блокирует запуск (главный поток его не
   ждёт).
4. **Маркер:** `Application Support/Lexomorph/.migrated-from-superdictate.json` хранит версию приложения, дату, что
   скопировано и пропущено, итог по Keychain и признак показанного уведомления. Есть маркер — ничего не делается.
5. **Одноразовое окно** при первом запуске после миграции (только если старые данные найдены): почему изменились
   название и пакет, что разрешения macOS нужно выдать заново, что данные перенесены и что старые остались
   нетронутыми. Окно не открывает ни одну панель «Конфиденциальность».

Разрешения macOS (микрофон, универсальный доступ, мониторинг ввода) переехать не могут: для системы новый bundle ID —
новое приложение. Владелец с этим согласился. `tccutil reset` не вызывается нигде.

### Windows

Код: `windows/superdictate/paths.py` (`migrate_legacy_data`, вызывается один раз из `main()`; `ensure_directories` и
самотесты никогда не мигрируют).

- Первый запуск копирует `%LOCALAPPDATA%\SuperDictate` в `%LOCALAPPDATA%\Lexomorph` (более старые имена `Dictation` и
  `D1CT` обрабатываются так же, сначала самое новое): настройки, историю, словарь, токен синхронизации и модели;
  крупные файлы моделей — жёсткими ссылками, если файловая система позволяет. `Logs`, `OutputMuted.flag` и временные
  файлы не копируются.
- Оригинал не удаляется: это путь отката.
- Маркер `.migrated-from-superdictate.json` со `status` `complete` или `incomplete` завершает миграцию либо даёт ей
  продолжиться со следующего запуска. Каталог, где уже есть собственный `Settings.json` и нет маркера, принадлежит
  тому, кто начал с чистого листа; старые данные в него не подсовываются.
- Токен синхронизации перезащищается новой энтропией DPAPI. Сбой никогда не мешает запуску.
- Установщик `Lexomorph-Setup-X.Y.Z.exe` ставит новое приложение (новый AppId) и перед установкой закрывает и удаляет
  установленный SuperDictate (программу, ярлыки, автозапуск); данные остаются. При удалении он спрашивает, удалять ли
  каталог данных и прежний каталог SuperDictate.

## 3. Установка и старая установка

- **macOS:** `scripts/install-local.sh` и `install.sh` атомарно ставят `/Applications/Lexomorph.app` и используют агент
  `com.local.lexomorph.agent`. Найдя `/Applications/SuperDictate.app` или агент `com.local.superdictate.agent`, они
  выгружают старый агент, завершают его процесс и удаляют старый бандл и старый plist только после успешной установки
  нового и до запуска нового агента (чтобы два агента не боролись за горячую клавишу). Данные, defaults и Keychain
  старого приложения не трогаются.
- **Подпись:** идентичность не меняется, новые сертификаты не создаются. `install-local.sh` сравнивает подписанта и
  команду (Authority/TeamIdentifier) со старой установкой, а не designated requirement (в нём есть bundle ID, и он
  меняется).
- **Удаление:** `uninstall.sh` удаляет Lexomorph; с флагом `--legacy` ещё и прежнюю установку SuperDictate (данные
  остаются).

## 4. Откат

Старые данные не изменяются и не удаляются: `~/Library/Application Support/SuperDictate`, домен
`com.local.superdictate`, элемент Keychain `com.local.superdictate.vocab-sync`; в Windows — папка
`%LOCALAPPDATA%\SuperDictate`.

- **macOS:** выполнить `uninstall.sh` и установить прежний релиз (0.9.x); он снова работает со своими данными.
- **Windows:** удалить Lexomorph и установить прежний `SuperDictate-0.9.x-setup.exe`; он использует
  `%LOCALAPPDATA%\SuperDictate`.

Правки, сделанные в Lexomorph после миграции, в старые данные не возвращаются. Чтобы повторить миграцию с нуля,
вручную удалите `~/Library/Application Support/Lexomorph` (или только маркер) и домен `com.local.lexomorph` на macOS
либо `%LOCALAPPDATA%\Lexomorph` на Windows. Это явное действие пользователя; код его не выполняет.

## 5. Как переходят клиенты 0.9.x

- **macOS 0.9.x не может обновиться «изнутри» до Lexomorph.** Встроенное обновление проверяет bundle ID, имя
  `SuperDictate.app` и ассет `SuperDictate.zip` (`UpdateCheck.swift` в 0.9.x). Релиз, в котором есть только
  `Lexomorph.zip`, эту проверку не проходит (адреса скачивания `SuperDictate.zip` для нового тега не существует).
  Переход делается установщиком `install.sh`.
- **Windows 0.9.x** лишь открывает страницу релиза и сам ничего не ставит; он принимает любой ассет `.exe`, `.msi` или
  `.zip` последнего релиза `win-v*`, поэтому `Lexomorph-Setup-1.0.0.exe` предлагается как обычно, а пользователь
  запускает его сам. Установщик удалит старый SuperDictate, а первый запуск скопирует данные.

### Переходный релиз (реализован как приложение-мост; требования оставлены для справки)

Реализовано: `mac-v1.0.0` публикует ещё и `SuperDictate.zip` — мост под старыми именами, который показывает это объяснение и ставит Lexomorph (проект: `docs/specs/transition-release-spec.md`, исходники: `bridge/`). Ниже — исходный список требований.

Раз клиенты macOS 0.9.x никогда не обновятся до Lexomorph, нужен **переходный релиз под старыми именами** до выпуска
1.0.0 (или вместе с ним). Его нужно собрать и опубликовать по-старому: бандл `SuperDictate.app`, bundle ID
`com.local.superdictate`, та же подпись, ассет `SuperDictate.zip`, тег `mac-v0.9.x`, `update.json` в `main` с этой
версией, чтобы существующее встроенное обновление его приняло. Что он должен сделать:

1. Объяснить переименование: приложение теперь называется Lexomorph; изменились название, файл приложения и пакет, а с
   ними идентичность пакета для системы (bundle ID), поэтому macOS снова запросит микрофон, универсальный доступ и
   мониторинг ввода; настройки, словарь и модели переносятся, старые данные сохраняются.
2. Привести пользователя к установке Lexomorph: показать однострочную команду установщика или ссылку на страницу
   релизов и README (`install.sh`) вместо предложения обновиться «изнутри» до релиза, который старое обновление
   поставить не умеет.
3. Научить старую проверку обновлений распознавать релиз эпохи Lexomorph (например, тег `mac-v1.0.0` и выше или релиз
   без `SuperDictate.zip`) и показывать это объяснение вместо попытки обновиться, чтобы пользователи 0.9.x не видели
   неудачной загрузки после публикации 1.0.0.
4. По желанию то же сообщение для Windows (уведомление об обновлении в Windows 0.9.x — просто ссылка на страницу релиза,
   так что объяснение можно вынести в описание релиза `win-v1.0.0`).

Переходный релиз должен выйти и некоторое время распространяться до того, как `mac-v1.0.0` станет «последним» релизом
macOS; клиенты старше переходного релиза должны суметь обновиться до него старым механизмом.

## 6. Риски и ограничения

- В `install.sh` и `update.json` стоят **заглушки** (SHA-256 из нулей, исходный коммит из нулей, версия 1.0.0), пока
  процедура из `docs/RELEASING.md` не подставит настоящие значения; до этого установщик не проходит проверку
  контрольной суммы. Не вливайте переименование в `main` до публикации релиза: однострочный установщик из README читает
  `install.sh` из `main`, а `update.json` в `main` — то, с чем сверяются встроенные обновления.
- Первый запуск Lexomorph при ещё работающем старом агенте: данные копируются «на лету» (если установка шла не через
  скрипты). Скрипты заранее выгружают старый агент.
- При чтении старого токена возможен диалог Keychain (ACL привязан к подписи старого пакета).
- Опубликованный `SuperDictate.zip` собран только под Intel (x86_64); установщик отклоняет другие архитектуры, поэтому
  пользователям Apple Silicon нужна сборка из исходников. Нужно решить, делать ли ZIP для 1.0.0 универсальным.
