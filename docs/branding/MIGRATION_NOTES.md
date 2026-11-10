# Lexomorph: заметки о миграции (что намеренно осталось под старым именем)

Lexomorph это новое название SuperDictate Next. Меняется только то, что видит пользователь: название, тексты, иконки,
документация. Всё, от чего зависят установленные копии, обновления, подпись и данные, остаётся прежним. Здесь список
того, что осталось, и причины. Данные пользователя не переносятся и не конвертируются: миграция данных не требуется.

Статус: документ описывает намерения и состояние на момент ветки `feat/lexomorph-rebrand`. Что именно сделано в
macOS-коде и в Windows-коде другими потоками, документ не утверждает; проверяйте по истории ветки. Версия
приложения этой веткой не меняется (последний релиз 0.9.7), релиза с новым именем пока нет.

## 1. Что осталось `SuperDictate` и почему

Классы по `REBRAND_AUDIT.md`: C совместимость, B внутренний идентификатор, H история и кредиты.

| Что | Значение | Класс | Почему не меняется |
|---|---|---|---|
| Бандл macOS | `/Applications/SuperDictate.app`, исполняемый файл `Contents/MacOS/SuperDictate` | C | Зафиксирован `AGENTS.md`. Самообновление и установщик ищут именно это имя. |
| Bundle ID | `com.local.superdictate` | C | Смена сбрасывает разрешения macOS (микрофон, Accessibility, Input Monitoring), ключи UserDefaults и Keychain. Запрещено `AGENTS.md`. |
| Подпись | существующий сертификат (локально Apple Development, релизы «PolterType Dev») | C | Смена меняет designated requirement и сбрасывает разрешения у всех. Запрещено `AGENTS.md`. |
| LaunchAgent | `com.local.superdictate.agent`, `~/Library/LaunchAgents/com.local.superdictate.agent.plist` | C | `AGENTS.md`; `install-local.sh` перезапускает только эту метку. |
| Данные macOS | `~/Library/Application Support/SuperDictate` (включая `Models`, `onnx`, `corrections.sqlite`), `~/Library/Logs/SuperDictate*`, домен UserDefaults = bundle ID | C | Любое изменение пути требует обратимой миграции данных пользователя. |
| Keychain | сервис `com.local.superdictate.vocab-sync` | C | Токен синхронизации уже лежит под этим именем. |
| Тип файла корректировок | расширение `.superdictate-corrections`, UTI `com.local.superdictate.corrections`, MIME `application/vnd.superdictate.corrections+json` | C | У пользователей есть сохранённые файлы и ассоциации. Меняется только видимое описание типа. |
| Релизные файлы | `SuperDictate.zip` (внутри `SuperDictate.app`), `SuperDictate-X.Y.Z-setup.exe`, теги `mac-vX.Y.Z` и `win-vX.Y.Z` | C | Клиенты 0.9.7 ждут именно такой ассет и такую структуру (см. раздел 2). |
| `update.json` | `{version, sha256}` на ветке `main` | C | Клиенты 0.9.7 сверяют с ним контрольную сумму. |
| Репозиторий | `shohart/SuperDictate-Next`, ссылки в клиентах, `install.sh`, `uninstall.sh`, CI, `.github/ISSUE_TEMPLATE/config.yml` | C | См. раздел 3. `scripts/check.sh` требует точную строку `raw.githubusercontent.com/shohart/SuperDictate-Next/main/install.sh` в обоих README. |
| Домен синхронизации | `superdictate.bykovlegal.ru` | C | Зашит по умолчанию во всех клиентах, на нём аккаунты. Новый домен возможен только с оставленным старым как алиасом. |
| Процессы и хелперы | `SuperDictateOnnxHost`, `SuperDictateLLMHost`, `SuperDictateOvHost`, `pkill -x SuperDictate` | B/C | Установщик, CI и проверки релиза ищут по именам. |
| Переменные окружения | `SUPERDICTATE_*` | C | Скрипты пользователей и CI. |
| Windows | `SuperDictate.exe`, каталог установки, `AppId`, AppUserModelID, mutex, значение автозапуска, `%LOCALAPPDATA%\SuperDictate`, лог `SuperDictate.log` | C | Смена оставила бы второй автозапуск и вторую копию. Допустимо менять только отображаемые имена (заголовок, трей, ярлыки, имя в «Приложения и возможности»), и только вместе с разделением отображаемого имени и каталога в установщике. |
| Код | таргет и каталог SwiftPM `Parakey`, `swift run ... Parakey`, Swift-типы `SuperDictate*`, Python-пакет `superdictate`, нативный API `sd_asr_*` | B | Внутреннее; не переименовывать ради эстетики. |
| Иконка-файл | `icon/Parakey.icns` (до решения потока macOS) | B | Имя файла иконки не входит в designated requirement; решение принимает поток macOS. |
| Кредиты и история | Parakey (Richard Courtman), SuperDictate (shlgd), `NOTICE.md`, `LICENSE`, старые записи CHANGELOG, спецификации | H | Юридически обязательно или исторически. |

Что видит пользователь и что не изменить совсем: Finder, Activity Monitor и списки «Конфиденциальность» в macOS берут
имя из файла бандла, поэтому там по-прежнему «SuperDictate». Документация об этом предупреждает.

## 2. Как обновляются клиенты 0.9.7

macOS (код `UpdateCheck.swift`):

1. Клиент запрашивает список релизов GitHub API репозитория `shohart/SuperDictate-Next` и берёт самый новый
   опубликованный `mac-v*` (или старый `v*`), пропуская Windows-теги, черновики и пре-релизы.
2. Скачивает `.../releases/download/<тег>/SuperDictate.zip`, сверяет SHA-256 с `update.json` на `main`
   (по старому пути репозитория), проверяет bundle ID, версию, подпись и то, что внутри лежат `SuperDictate.app` и
   исполняемый файл `SuperDictate`; затем заменяет бандл и перезапускает.
3. Установленные копии 0.9.7 без кнопки `Update` и новые пользователи обновляются повторным запуском
   `install.sh` (он заменяет только `/Applications/SuperDictate.app`).
4. Автопроверка по умолчанию выключена; проверка при открытии панели есть всегда.

Поэтому первый релиз с именем Lexomorph обязан выйти с тем же именем ассета (`SuperDictate.zip`), тем же бандлом, тем
же bundle ID и той же подписью, с новой версией, новой суммой в `install.sh` и `update.json` и обязательным прогоном
`scripts/verify-release.sh` (порядок в `docs/RELEASING.md`).

Windows (код `windows/superdictate/updater.py`): клиент читает тот же список релизов, берёт самый новый `win-v*`,
ищет ассет по шаблону `.exe`, `.msi` или `.zip`, **ничего не скачивает и не запускает** и открывает страницу релиза.
Пользователь запускает новый `setup.exe` сам. Имя `.exe` технически можно менять, но в первом релизе его
оставляют, чтобы не ломать `docs/RELEASING.md` и привычные ссылки.

Данные пользователя при любом обновлении остаются на месте, потому что пути и идентификаторы не меняются.

## 3. Переименование репозитория

Репозиторий сейчас называется `shohart/SuperDictate-Next`; локальный `origin` разработчика ещё указывает на старое имя
`SuperDictate-Intel` (работает через редирект GitHub). Переименование откладывается:

- GitHub перенаправляет web, API и raw со старого имени, но редирект исчезает, если старое имя займёт другой
  репозиторий.
- Клиент 0.9.7 принимает ссылку на заметки релиза только с путём `/shohart/SuperDictate-Next/releases/tag/<тег>`.
  После переименования API вернёт новый путь, и ссылка тихо подменится страницей `releases/latest`. Сама проверка
  обновления продолжит работать, но деградирует. Нужен клиент, который принимает оба префикса, выпущенный до
  переименования.
- Адаптер LoRA качается с ветки `feat/llm-postproc-gec` этого репозитория; ветку нельзя удалять, пока живы клиенты
  с этой ссылкой.

Порядок действий см. `MANUAL_OWNER_ACTIONS.md`.

## 4. Что менялось в документах

README, README.ru, PRIVACY, CONTRIBUTING, шаблоны `.github/` (только текст, без путей и ссылок на репозиторий),
CHANGELOG (раздел `Unreleased`), ассеты и документы бренда в `docs/assets/branding` и `docs/branding`. В README
сохранены строки установки и удаления с адресом `shohart/SuperDictate-Next`, команда `swift run ... Parakey`,
все пути и метки.

## 5. Фраза «formerly SuperDictate Next»

Использовать в README, описаниях релизов и окне «О программе» один-два релиза или пока не опубликованы заметки о
миграции. История SuperDictate Next сохранена: старые записи CHANGELOG не переписываются.
