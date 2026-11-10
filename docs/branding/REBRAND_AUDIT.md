# REBRAND_AUDIT — SuperDictate Next -> Lexomorph (Фаза 0, только аудит)

Ветка `feat/lexomorph-rebrand` (база `feat/sync-modes-stats`, версия приложения 0.9.7, build 70).
Код и ассеты не менялись. Ничего не собиралось и не запускалось: рабочая машина Linux, macOS/Windows-сборки и
self-тесты в этой фазе не выполнялись. Всё ниже получено чтением кода (`file:line`) и `grep`.

Источники бренда: `/mnt/theVault/repos/Lexomorph/Lexomorph/` (`agent/*`, `docs/*`, `github/*`, `Lexomorph_Brand_Assets/`).
Принцип из задачи: репозиторий главнее маркетинговых текстов; compatibility-sensitive не переименовывать молча.

## 0. Главные выводы

1. **Старых брендов три, а не два.** Кроме `SuperDictate` / `SuperDictate Next` в пользовательских строках macOS живёт
   `Parakey` (≈97 видимых литералов: подсказка иконки меню, «Parakey is up to date», «Parakey v… is available»,
   ошибки, диалоги синхронизации, shell-скрипт обновления). Это public-facing, его надо переименовывать вместе с
   остальным. Но `Parakey` также = имя SwiftPM-таргета/модуля, имя иконки (`Parakey.icns`, `CFBundleIconFile`), токен brew,
   и кредит «based on Parakey by Richard Courtman» — всё это остаётся.
2. **Имя в самой macOS изменить нельзя полностью**: бандл `/Applications/SuperDictate.app`, исполняемый файл
   `SuperDictate`, bundle id `com.local.superdictate` и подпись фиксированы AGENTS.md. Finder/Activity Monitor/списки TCC
   (Конфиденциальность) будут показывать «SuperDictate». Уже сейчас `CFBundleDisplayName = "SuperDictate Next"`, а код
   (`ParakeyApp.swift:4483,4603,4605`) велит искать в системных списках переключатель «SuperDictate» — т.е. имя в TCC берётся
   из файла бандла, а не из DisplayName. Эти три строки менять **нельзя**. Опция (гипотеза, проверять на Mac):
   `InfoPlist.strings` + `LSHasLocalizedDisplayName`.
3. **README и PRIVACY.md сейчас вводят в заблуждение** и должны быть исправлены раньше, чем на них повесят бренд
   «local-first»: бейдж «100% local», «No cloud, no account», «network only for model and updates», «Windows not
   supported», «signed ad-hoc» (CHANGELOG: подпись «PolterType Dev»), PRIVACY.md «parakeet.cpp», «logs avoid transcript text»
   при наличии `DictationTrace.jsonl` и истории с текстом (локально). Реально есть удалённые маршруты: опциональный
   sync-сервер, пользовательские OpenAI-совместимые endpoint'ы (получают диктуемый текст), загрузки с huggingface.co и
   GitHub. Ключи API хранятся открытым текстом (macOS UserDefaults, Windows `Settings.json`).
4. **Часть брендовых карточек не соответствует коду** (см. §7): «adapts to your voice» (адаптации под голос нет),
   карточка Cross-Device Sync с телефоном и «settings» (мобильного клиента нет; настройки не синхронизируются),
   «Local-First Privacy: Your data stays with you» без оговорок. Вся графика растровая; `assets/svg/*`, на которые ссылается
   IMPLEMENTATION_TASK, в поставке нет.
5. **Совместимость обновлений зависит от имён, которые нельзя менять первым релизом**: `SuperDictate.zip`
   (`UpdateCheck.swift:312,343`, `install.sh`, `update.json`-флоу), `SuperDictate.app` внутри (`UpdateCheck.swift:364,392`),
   теги `mac-v*`/`win-v*`, путь `/shohart/SuperDictate-Next/releases/tag/` (`UpdateCheck.swift:84,199`).
6. **Найденные попутно баги** (не часть ребрендинга, но затрагивают Windows-поток C): §4.8.

## 1. Метод и границы

Подсчёт: `git ls-files` минус вендоренный upstream (`swift/Sources/llama_cpp_host/upstream`, `silero_vad/upstream*`,
`third_party`, `models/`, `fixtures/`, `benchmark/`, `*.onnx`). Паттерны пересекаются (одна строка может попасть в несколько
строк таблицы), суммировать нельзя. `SDN` — **0 вхождений**. Не проверялось: поведение на реальных macOS/Windows,
тесты, внешние сервисы (доступность имени `lexomorph`, редиректы GitHub), содержимое LLM-каталога моделей вне
CHANGELOG.

## 2. Текущая реализация

### 2.1 Платформы, сборка, подпись, релизы, обновления

| Область | Факты |
|---|---|
| macOS | Swift/AppKit, SwiftPM пакет `swift/Package.swift` (продукты `Parakey`, `SuperDictateLLMHost`; C++-таргеты `silero_vad`, `llama_cpp_host`), macOS 14+, Apple Silicon и Intel. LaunchAgent `com.local.superdictate.agent` (приложение работает как фоновый агент + окно Control Panel). |
| Сборка macOS | `scripts/build-app.sh` собирает `SuperDictate.app` во временный каталог, копирует `swift/Info.plist`, `icon/Parakey.icns`, `swift/Resources/parakey-menubar*.png`, хелперы `Contents/Helpers/SuperDictateOnnxHost`, `SuperDictateLLMHost`, ONNX Runtime, подписывает. `scripts/install-local.sh` — единственная локальная установка (атомарная замена, проверка designated requirement, рестарт только агента). `scripts/build-test-app.sh` собирает тестовые бандлы `SuperDictate-<label>.app` (id `com.local.superdictate.<label>`) — по AGENTS.md запускать их нельзя. |
| Подпись | Локально Apple Development (`install-local.sh`); релизы подписаны «PolterType Dev» (docs/RELEASING.md, CHANGELOG), не нотаризованы. Идентификатор подписи не менять (AGENTS.md). |
| Windows | Python + PySide6 (`windows/`), PyInstaller `windows/SuperDictate.spec` (one-folder, `SuperDictate.exe`, `SuperDictateOvHost.exe`), `windows/build.ps1`, Inno Setup `windows/installer/SuperDictate.iss` -> `SuperDictate-X.Y.Z-setup.exe`, per-user, без админа. Данные в `%LOCALAPPDATA%\SuperDictate`. |
| Релизы | Один репозиторий `shohart/SuperDictate-Next` (локальный `origin` ещё указывает на старое имя `SuperDictate-Intel` — редирект-цепочка). macOS: тег `mac-vX.Y.Z`, ассет `SuperDictate.zip`, GitHub "latest". Windows: `win-vX.Y.Z`, `SuperDictate-X.Y.Z-setup.exe`, никогда не "latest". Порядок — `docs/RELEASING.md`, обязателен `scripts/verify-release.sh`. |
| Обновление macOS | `UpdateCheck.swift`: список релизов GitHub API (`Constants.swift:44`), берёт newest `mac-v*`/`v*`, скачивает `…/releases/download/<tag>/SuperDictate.zip` (`UpdateCheck.swift:312`), сверяет SHA-256 с `update.json` из `main` (`Constants.swift:48`), проверяет bundle id, версию, подпись, имя `SuperDictate.app` и бинарь `SuperDictate` (`:364-392`), заменяет бандл, перезапускает. `update.json` = `{version, sha256}`; `scripts/check.sh` требует равенства версии/суммы с `Info.plist` и `install.sh`. Автопроверка в фоне: **macOS по умолчанию выключена** (`Settings.swift:758-760`), **Windows по умолчанию включена** (`settings.py:295`) — расхождение. |
| Обновление Windows | `windows/superdictate/updater.py`: тот же GitHub API, берёт newest `win-v*`, ассет по regex `\.(exe|msi|zip)$`; **ничего не скачивает и не запускает**, открывает страницу релиза. Т.е. имя `.exe` можно менять. |
| CI | `.github/workflows/build.yml` (macos-15: `scripts/check.sh`, ONNX-core тесты, `swift run … Parakey --self-test all`, сборка бандла, проверка путей `SuperDictate.app/Contents/MacOS/SuperDictate`, `Helpers/SuperDictateOnnxHost`, прогон `install.sh`/`uninstall.sh`); `release-smoke.yml` (Intel-раннер, ставит из `raw.githubusercontent.com/shohart/SuperDictate-Next/main/install.sh`, проверяет id, helper-ы). Windows в CI нет. |
| Установщики macOS | `install.sh` (пины `RELEASE_TAG`, `RELEASE_SHA256`, `SOURCE_COMMIT`; env `SUPERDICTATE_*`), `uninstall.sh`. |

### 2.2 Конвейер диктовки (реализовано)

Захват аудио -> VAD/пауза-сегментация с перекрытием и дедупликацией швов (Silero VAD, ggml) -> ASR в отдельном процессе
`SuperDictateOnnxHost` (ONNX Runtime 1.23.2, CPU) -> правила: пользовательские замены (corrections), фильтр слов-паразитов,
ITN русских чисел -> (опц.) LLM-коррекция -> (опц.) рерайт по выбранному режиму -> (опц.) восстановление пунктуации
(последний этап, по CHANGELOG 0.9.0) -> вставка в активное поле. Подсказки ASR (hotwords) действуют **внутри декодера**,
т.е. до текстовых этапов. Порядок согласован с `RecordingLifecycle.swift` и CHANGELOG; точную последовательность вызовов в
каждом режиме перед публикацией диаграммы надо сверить (reference-диаграмма бренда это отмечает сама).

### 2.3 Бэкенды

| Этап | Варианты | Где исполняется | По умолчанию |
|---|---|---|---|
| ASR | Parakeet Ultra 0.6B int8 (`nemo_tdt`, 25 языков), GigaAM v3 e2e RNN-T int8 (русский); Windows дополнительно NPU через OpenVINO (`SuperDictateOvHost`) | локально, CPU (NPU на Windows) | Parakeet Ultra |
| Пунктуация | Horizon-Labs punctuation-restoration Small/Base (ONNX) | локально, CPU | выкл. (`Settings.swift:1205`) |
| LLM-коррекция | локальный `SuperDictateLLMHost` (llama.cpp, CPU/Vulkan, loopback HTTP) **или** OpenAI-совместимый endpoint пользователя | локально, либо **внешний сервер** | режим `off` (`Settings.swift:1132`, `settings.py:322`); бэкенд по умолчанию `bundledLocal` |
| Рерайт | те же два варианта, настройки независимы | то же | выкл. (`rewrite_enabled` = false) |
| Защита | `LLMCorrectionGuardrail`: правка слова сверяется с оригиналом, имена из словаря не меняются (CHANGELOG 0.9.7) | локально | вкл. при коррекции |

Режимы рерайта: встроенные `polish`, `structured_task` («Structured task»), `official` (`ConfigModels.swift:786-804`) +
пользовательские `c-<uuid>` (имя, цвет, инструкция, хоткей; `ConfigModels.swift:809`). Отдельного режима Raw/Clean/Formal
нет: «Clean» бренда ~ этап коррекции (off/correction), «Polish» = `polish`, «Formal» = `official`, «Custom» = custom.
Raw-значения (`polish`, `structured_task`, `official`) хранятся в настройках — не менять; переименовывать можно только
`displayName`.

### 2.4 Персонализация: что реально есть

| Механизм | Что это | Статус |
|---|---|---|
| Словарь замен (corrections) | SQLite `~/Library/Application Support/SuperDictate/corrections.sqlite` (`Settings.swift:171`); добавление/правка/удаление вручную, JSON-импорт/экспорт, файловая синхронизация между Mac | существует |
| Автообучение по правкам | Замечает ручную правку короткого слова/фразы (≤3 слов) сразу после вставки, сохраняет правило, показывает тост с отменой (Esc). Правила отбраковки: падежные окончания, смена смысла, чистая пунктуация/регистр. **Эвристики, не обучение весов.** Включено по умолчанию (`Settings.swift:897-901`), отключаемо | существует |
| «Почистить словарь» | План удаления/слияния выученных записей с превью | существует |
| ASR hotwords | Термины из словаря/списка подсказываются декодерам TDT и RNN-T (токенизация SentencePiece/BPE). По умолчанию вкл. (`Settings.swift:905-907`) | существует |
| Пользовательские режимы рерайта | инструкции для LLM | существует |
| Дообучение ASR/LLM, адаптация под голос, адаптивный роутинг, «learns style automatically» | — | **не существует** |

### 2.5 Синхронизация

| Что | Механизм | Статус |
|---|---|---|
| Corrections между Mac | один JSON-файл в папке, выбранной пользователем (iCloud/Dropbox/Syncthing); без аккаунта | существует (macOS) |
| Словарь + ASR-термины между macOS и Windows | аккаунт e-mail+пароль на сервере владельца `https://superdictate.bykovlegal.ru` (`Constants.swift:132`, `settings.py:360`; код сервера `server/vocab-sync`, FastAPI+SQLite); **по умолчанию выкл.** (`Settings.swift:930-931`); токен в Keychain (`com.local.superdictate.vocab-sync`) / DPAPI | выпущено: 0.9.3 (словарь), 0.9.5 (термины) |
| Пользовательские режимы (имя, цвет, инструкция) и статистика по дням/устройствам | тот же сервер и endpoint (`docs/specs/modes-and-usage-sync-spec.md`) | **не выпущено**: только ветка `feat/sync-modes-stats`, «релиза нет» |
| Настройки, хоткеи, активный режим | не синхронизируются (хоткеи и выбранный режим намеренно локальны) | не существует |
| Мобильные устройства | нет клиентов | не существует |

### 2.6 Таблица приватности (для README, факты по коду)

| Данные / сеть | Куда | Когда | Что передаётся | Креды |
|---|---|---|---|---|
| Аудио | никуда | никогда (ASR локален) | — | — |
| Модели ASR/пунктуации | huggingface.co (закреплённые ревизии, SHA-256) | первый запуск / по кнопке | запрос файла | нет |
| Silero VAD | huggingface.co `ggml-org/whisper-vad` | автоматически после загрузки модели | запрос файла | нет |
| Локальные LLM-модели | по CHANGELOG — те же закреплённые файлы; адаптер LoRA качается с `github.com/shohart/SuperDictate-Next/raw/feat/llm-postproc-gec/…` (`ModelDownload.swift:149`) | по кнопке | запрос файла | нет |
| Проверка обновлений | `api.github.com`, `raw.githubusercontent.com` | macOS: выкл. по умолчанию; Windows: вкл. | запрос релизов | нет |
| LLM-коррекция/рерайт через endpoint | URL пользователя (по умолчанию в UI подсказка OpenRouter) | **opt-in**, только если выбран `customEndpoint` | диктуемый текст (+ промпт); аудио нет | API-ключ в **открытом виде**: macOS UserDefaults (`Settings.swift:1151-1160`), Windows `Settings.json`; системный прокси включён по умолчанию, локальные адреса напрямую |
| Синхронизация словаря | сервер владельца | **opt-in** | правила замены (source/replacement/origin/asr_hint), ASR-термины, (не выпущено) инструкции режимов и счётчики по дням | e-mail+пароль; токен в Keychain/DPAPI |
| Транскрипты | локально: история в настройках, `DictationTrace.jsonl` (2000–4000 диктовок: вывод ASR, после правил, итог), crash-recovery аудио | всегда | остаётся на устройстве | — |
| Аналитика/телеметрия | нет в коде | — | — | — |

Вывод для текстов: допустимо «аудио обрабатывается локально; удалённые маршруты — только по выбору пользователя»; недопустимо
«100% local», «works entirely offline» (первая загрузка моделей требует сети), «no account» без оговорки про opt-in sync,
«logs avoid transcript text».

### 2.7 Иконки и ассеты сейчас

**macOS.** `icon/Parakey.icns` (1.4 МБ, источник — `icon/generate-appicon.swift`, CoreGraphics, комментарий «SuperDictate Next …
Parakey.icns»), `icon/parakey-512.png`; `swift/Info.plist` `CFBundleIconFile = Parakey`; `build-app.sh`/`build-test-app.sh`
копируют в `Contents/Resources/Parakey.icns`; `ParakeyApp.swift:6448` берёт `NSImage(named: "Parakey")` для About. Иконка меню:
`swift/Resources/parakey-menubar.png` (22x22) и `@2x` (44x44), грузится как `NSImage(named: "parakey-menubar")` с
`isTemplate = true` (`ParakeyApp.swift:1292-1294`), тонируется для состояний записи/ошибки — **нужен монохромный альфа-глиф**.
**Windows.** `windows/assets/SuperDictate.png` 1024x1024 (полный кадр) — единственный мастер: `windows/tools/make_icon.py`
**пересобирает `.ico` из PNG при каждом `build.ps1`**, поэтому подмена одного `.ico` будет затёрта. PNG же напрямую
используется треем (`ui/tray.py:39`, масштабируется, поверх рисуется цветная точка состояния в углу) и окном
(`main.py:80`). `SuperDictate.spec` берёт `assets/SuperDictate.png` как data и `assets/SuperDictate.ico` как иконку exe;
`SuperDictate.iss` — `SetupIconFile=..\assets\SuperDictate.ico`.

**Поставка бренда** (`Lexomorph_Brand_Assets/`): `icons/final-LM/` — `lexomorph.icns` (16–1024 + @2x, типы icp4…ic14),
`lexomorph.ico` (7 размеров 16–256), PNG 16…1024, `lexomorph.iconset/`, аватары; `readme/` (hero 1280x640 + alternate),
`social/` (1280x640 и 1200x630), `features/` (6 карточек ≈460x345 + сетка 1536x1024), `source-originals/`. Замечания:
- SVG-мастеров нет (`README.md` пакета: «No editable vector/SVG master exists»); ASSET_GUIDE и IMPLEMENTATION_TASK описывают
  несуществующие `assets/svg|png`. Размеры карточек 458–471 px, а не 1200x675.
- Иконка `lexomorph-icon-1024.png`: закруглённый квадрат занимает bbox (17,31,1007,1004) — ~97% холста; по шаблону Apple
  корпус macOS-иконки ≈ 824/1024 с полями. В Dock будет выглядеть крупнее соседей. Решение дизайнера/владельца.
- Монохромного глифа для строки меню нет; для 16 px трея Windows цветная плита с градиентом и точкой состояния —
  читаемость проверить.
- Шрифт (Inter/Sora) в репозиторий не вносить без проверки лицензии.

### 2.8 Где живут строки UI

| Платформа | Механизм | Где |
|---|---|---|
| macOS | Нет каталога строк. `Localization.swift` — только `localizedText(ru, en, language:)`; в коде везде двуязычные литералы `t("рус", "eng")` (RU/EN переключатель) и **отдельные английские литералы без перевода** (ParakeyApp.swift: alerts, меню, Setup-окно) | `ControlPanel.swift`, `ParakeyApp.swift`, `HUDViews.swift`, `UpdateCheck.swift`, `Hotkeys.swift`, `ModelRegistry.swift`, `ModelDownload.swift`, `Permissions.swift`, `CorrectionsTransfer.swift`, `VocabularyManagerWindow.swift`, `ConfigModels.swift` |
| macOS plist | `swift/Info.plist`: `CFBundleDisplayName`, `CFBundleName`, `NSMicrophoneUsageDescription`, `NSAppleEventsUsageDescription`, `NSHumanReadableCopyright`, `CFBundleTypeName`, `UTTypeDescription` | — |
| Windows | `windows/superdictate/i18n.py`: словарь ключ -> (ru, en); имя = ключ `app_name` (`i18n.py:15`), используется в заголовке окна (`ui/panel.py:110`), подсказке трея (`ui/tray.py:129`), уведомлении (`ui/updates.py:75`), QMessageBox (`ui/settings_window.py:1025`); plus `main.py:77` `setApplicationName`, `i18n.py:595-597` | Windows везде пишет просто «SuperDictate» (без «Next») |
| Windows installer | `SuperDictate.iss`: `[CustomMessages]` ru/en, `AppName`, `AppPublisher` | — |

Самотесты закрепляют бренд-строки (`SelfTest.swift:6455-6499` — shell-скрипт обновления «Parakey v…», «SuperDictate Next v9.8.7 is
installed.», `:1077` «Parakey could not save that hotkey…», `:716` имя файла диагностики; Windows `selftest.py`): при
смене видимых строк тесты менять **в том же коммите**.

### 2.9 Что показывает README сейчас

`README.md`/`README.ru.md` (≈400 строк каждый): заголовок «SuperDictate Next», слоган про Intel Mac, бейджи («100% local»),
история форка (upstream shlgd/SuperDictate, Parakey), таблица отличий, one-line install (`raw.githubusercontent.com/shohart/SuperDictate-Next/main/install.sh`),
обновление, хоткеи, настройки, сборка из исходников, бенчмарк ASR (WER/RTF на Xeon), ограничения, приватность, лицензия.
Устарело/неверно: «Windows … not supported yet» (есть `windows/` и релизы `win-v*`; `windows/README.md` тоже говорит «Готовых
сборок нет» и «Ничего не уходит в сеть»), «public build signed ad-hoc», «100% local», «no account», раздел Limitations
«Intel only zip» требует сверки, нет упоминаний LLM-коррекции/рерайта/пунктуации/sync/Windows. `scripts/check.sh:39-40`
**требует** точную строку `raw.githubusercontent.com/shohart/SuperDictate-Next/main/install.sh` в обоих README — CI упадёт, если
её заменить. Строка `! grep -q 'shohart/SuperDictate-Intel\|shlgd/SuperDictate' README.md README.ru.md` (`check.sh:38`) на деле
ничего не проверяет (отрицание под `set -e` не прерывает скрипт), хотя README содержит ссылку на `shlgd/SuperDictate`.

## 3. Таблица touchpoints и классификация

Классы: **P** public-facing (менять безопасно), **C** compatibility-sensitive (не менять без миграции и согласия владельца),
**B** build identifier (менять только осознанно), **H** historical (оставить). Числа — вхождения/файлы по §1.

| # | Группа | Примеры (file:line) | ≈ вхожд. / файлов | Класс | Решение |
|---|---|---|---|---|---|
| 1 | Отображаемое имя «SuperDictate Next» в UI/plist | `Info.plist:6,11,31,43,47,49,58` (DisplayName, TypeName, CFBundleName, usage descriptions, Copyright, UTTypeDescription); `ControlPanel.swift:400,432,457,976,985,1186,1274,1285,1955,4961`; `ParakeyApp.swift:3862,3895,4078,4135,4227,4401,4464,6429`; `HUDViews.swift:935-1054`; `Hotkeys.swift:195`; `UpdateCheck.swift:73,250,271,676-686` | 85 / 19 (из них UI ≈ 55) | P | -> «Lexomorph» |
| 2 | Отображаемое «SuperDictate» (без Next) в macOS UI | `UpdateCheck.swift:79`; `ControlPanel.swift:1174-1175,1411,2233-2234`; `ParakeyApp.swift:4542`; `main.swift:59` (usage CLI) | ≈ 15 | P (кроме 4603/4605/4483 — C) | -> «Lexomorph», кроме указаний на пункт в TCC |
| 3 | «Parakey» в видимых строках macOS | `ParakeyApp.swift:1301,1304,1322,3897,3919,5424-6051,6569,6661,6728,6877-6943`; `ModelRegistry.swift:50-56`; `ModelDownload.swift:197,395,598,755,885,896`; `Permissions.swift:188,285`; `CorrectionsTransfer.swift:32,46,212`; `VocabularyManagerWindow.swift:436,447,473`; `Hotkeys.swift:60`; `ConfigModels.swift:408`; shell обновления `UpdateCheck.swift:580-660` | 97 литералов / 21 | P | -> «Lexomorph» |
| 4 | Имя `Parakey` как идентификатор | SwiftPM таргет/продукт (`Package.swift:16,21,92`), каталог `swift/Sources/Parakey`, `swift run … Parakey` (CI, README, PR-шаблон, CONTRIBUTING), `NSError(domain: "Parakey")`, `DispatchQueue(label:"Parakey…")`, `ParakeySelfTest`/`ParakeyApp`, `HOMEBREW_CASK_INSTALLED_TOKEN = "parakey"` (`Constants.swift:56`), `CFBundleIconFile=Parakey`, `icon/Parakey.icns`, `parakey-menubar*.png`, `Parakey-<uuid>` временные каталоги (`ParakeyApp.swift:651,5459` — **C**: код ищет префикс) | 516 всего / 85 (в т.ч. планы) | B/C | не менять в этой итерации |
| 5 | Кредит «based on Parakey by Richard Courtman», ссылки на shlgd/SuperDictate | `NOTICE.md`, `LICENSE`, `Info.plist:47` (copyright), README «Origin», `windows/NOTICE.md`, `windows/PROVENANCE.md`, `windows/superdictate/version.py:11-14`, `__init__.py:3-4` | 12 / 8 | H (юридически обязательно) | сохранить; в copyright писать «Lexomorph (formerly SuperDictate Next), based on Parakey…» |
| 6 | Репозиторий/URL `shohart/SuperDictate-Next` | `Constants.swift:44-49`; `UpdateCheck.swift:84,199,312`; `ParakeyApp.swift:6442,6762,6784`; `ModelDownload.swift:149`; `install.sh`; `scripts/check.sh:39-40`; `.github/workflows/release-smoke.yml:28,44,82`; `.github/ISSUE_TEMPLATE/config.yml:4`; `windows/superdictate/updater.py:32-33`; `windows/installer/SuperDictate.iss:14`; docs/RELEASING.md; README*, CHANGELOG | 52 / 15 (50 — полные URL) | C до переименования репозитория | менять только вместе с владельцем (§8), поэтапно |
| 7 | Путь бандла `/Applications/SuperDictate.app`, `Contents/MacOS/SuperDictate`, имя `.app` | `Constants.swift:57`; `Logger.swift:209,372`; `UpdateCheck.swift:364,391-392,750,777`; `ParakeyApp.swift:4234-4236`; `install.sh`, `uninstall.sh`, `scripts/*`, CI, `verify-release.sh` | 95 `.app` / 28; 28 `MacOS/SuperDictate` / 15 | C (AGENTS.md) | не менять |
| 8 | bundle id `com.local.superdictate`, LaunchAgent `…agent`, UTI `…corrections`, notification names, suite names самотестов, Keychain `…vocab-sync`, DPAPI entropy (`vocabulary_sync.py:55`), Windows `BUNDLE_ID` (`paths.py:23`) | `Info.plist:18,27,60`, `Constants.swift:58-76,131-133` | 86 / 27 | C (AGENTS.md) | не менять |
| 9 | Тип файла корректировок: расширение `.superdictate-corrections`, MIME `application/vnd.superdictate.corrections+json` | `Info.plist:64-66` | 2 | C (ассоциации файлов у пользователей) | менять только `CFBundleTypeName`/`UTTypeDescription` |
| 10 | Хранилище данных macOS: `Application Support/SuperDictate` (+`Models`, `onnx`), `Library/Logs/SuperDictate*.log`, `SuperDictate-update.log`, `AgentStatus*.json`, `ControlPanel*.pid`, UserDefaults домен = bundle id | `Constants.swift:77-91` (`APP_SUPPORT_DIR_NAME`), `Logger.swift:33`, `ModelDownload.swift:637` | 30 / 14; 16 / 12 | C | не менять; в README писать как «путь сохранён» |
| 11 | Процессы/хелперы: `SuperDictateOnnxHost`, `SuperDictateLLMHost`, `SuperDictateOvHost`, `superdictate-llm-host.exe`, `pkill -x SuperDictate`, `pkill -f …/MacOS/SuperDictate --agent`, имена в `Package.swift`, `CMakeLists`, CI-проверки | `OnnxAsrEngine.swift:176`, `LLMHostProcess.swift:205`, `install.sh`, `uninstall.sh`, `UpdateCheck.swift:777` | 170 / 59 | B/C | не менять |
| 12 | Swift-типы `SuperDictate*` (`SuperDictateAgentService`, `…ControlPanelApp`, `…UpdateInstaller`…) | `Logger.swift:104,197`, `ControlPanel.swift:236`, `UpdateCheck.swift:206-441` | 74 / 12 | B | не менять (внутреннее, «не переименовывать ради эстетики») |
| 13 | env `SUPERDICTATE_*` (`_REPOSITORY`, `_RELEASE_URL`, `_APP_PATH`, `_BUILD_FROM_SOURCE`, `_ASR_THREADS`, `_ONNX_HOST`, `_HOME`…) | `install.sh`, CI, `scripts/*`, `windows/*` | 111 / 25 | C (скрипты и CI пользователей) | не менять |
| 14 | Релизные артефакты: `SuperDictate.zip`, `SuperDictate-X.Y.Z-setup.exe`, теги `mac-v*`/`win-v*` | `UpdateCheck.swift:312,343`, `install.sh`, `docs/RELEASING.md`, `SuperDictate.iss:45` | 31 / 11; 16 / 4 | `.zip`: C; `.exe`: допустимо менять (regex `.exe`), но отложить | см. §5 |
| 15 | Windows exe/spec/ico/png: `SuperDictate.exe`, `SuperDictate.spec`, `SuperDictate.iss`, `assets/SuperDictate.{png,ico}`, `build.ps1`, каталог установки `{autopf}\SuperDictate`, Run-значение `SuperDictate` (`system.py:384,389`), AUMID `local.SuperDictate` (`system.py:540`, `.iss:17`), mutex `Global\SuperDictate.SingleInstance` (`paths.py:59`), сообщение `SuperDictate.ShowControlPanel` (`system.py:536`), `AppId` GUID, taskkill по `SuperDictate.exe`, `%LOCALAPPDATA%\SuperDictate`, лог `SuperDictate.log` | 22 / 10 + см. выше | C | не менять; только отображаемые имена |
| 16 | Python-пакет `superdictate`, имена логгеров, `windows/main.py` | `windows/superdictate/**` | 289 / 78 | B | не менять |
| 17 | User-Agent'ы: `SuperDictate-Windows/<v>`, `SuperDictate/<v> (Windows)` (`updater.py:90`, `vocabulary_sync.py:274`, `onnx_models.py:347`, `vad.py:87`, `llm/download.py:144`) | — | 5 | P (низкий риск) | можно менять; но серверные логи владельца могут фильтровать |
| 18 | Домен sync-сервера `superdictate.bykovlegal.ru` | `Constants.swift:132`, `settings.py:360`, `selftest_vocab.py:1141`, `server/vocab-sync/*`, спека, CHANGELOG | 8 / 7 | C (зашит как URL по умолчанию во всех клиентах; на нём аккаунты) | не менять без нового домена + оставить старый как алиас |
| 19 | Тексты «хранится на сервере SuperDictate» | `ControlPanel.swift:2233-2234`; `i18n.py:595-597` | 2 | P | -> «Lexomorph sync server» (честнее: «на сервере синхронизации»), без смены URL |
| 20 | Windows UI: `app_name` и производные | `i18n.py:15`, `panel.py:110`, `tray.py:129`, `updates.py:75`, `settings_window.py:1025`, `main.py:64,77` | 8 | P (`main.py:77` `setApplicationName` — осторожно, §4.6) | -> «Lexomorph» |
| 21 | Windows installer, видимое: `AppPublisher "SuperDictate Next"`, `[CustomMessages]`, имя в «Приложения и возможности» (из `AppName`), ярлыки `{group}\{#AppName}`, `.lnk` | `SuperDictate.iss:10,12,21-29,94-97,104,Messages 64-70` | 18 / 1 | P/C смешано (§4.5) | развести отображаемое имя и идентификаторы |
| 22 | Документы: README*, PRIVACY, SECURITY, CONTRIBUTING, `.github/*` шаблоны, `windows/README.md` | см. §2.9 | ≈ 200 / 15 | P | поток A |
| 23 | CHANGELOG, `docs/specs/*`, `docs/superpowers/*`, `docs/capability/*` | CHANGELOG 45 строк; specs 35; plans/specs 77 | ≈ 160 / 25 | H | оставить; в CHANGELOG добавить запись «formerly SuperDictate Next» |
| 24 | Native ASR runtime: `sd_asr_*` API, `SD_ASR_*`, `SuperDictateOnnxHost` | `native/asr-runtime/**` | ≈ 450 / 40 | B | не менять |
| 25 | Заголовки-комментарии `// SuperDictate — extracted from…`, `Parakey — push-to-talk…` | `Logger.swift:1`, `ControlPanel.swift:1`, `Constants.swift:1`… | ≈ 40 | H | не трогать |

## 4. Риски совместимости

1. **Обновление существующих клиентов.** Клиенты 0.9.7 ждут ассет `SuperDictate.zip` с `SuperDictate.app` внутри и верят
   `update.json` из `main` старого пути. Переименование ассета/бандла ломает самообновление всех установленных macOS-копий.
   Следствие: первый «Lexomorph»-релиз выпускается тем же именем ассета и тем же бандлом.
2. **Переименование репозитория.** GitHub редиректит web/API/raw со старого имени (нужно проверить `curl -IL` на каждый из
   URL: API releases, raw `update.json`, raw `install.sh`, `releases/download/…`, `raw/feat/llm-postproc-gec/…`), редирект
   исчезает, если старое имя будет занято новым репозиторием. `UpdateCheck.sanitizedReleaseURL` (`UpdateCheck.swift:189-203`)
   принимает `html_url` только с путём `/shohart/SuperDictate-Next/releases/tag/<tag>`; после переименования API вернёт
   новый путь, и ссылка на заметки **молча подменится страницей `releases/latest`** (сама проверка обновления не
   ломается, но деградирует). Нужен клиент, принимающий оба префикса, выпущенный **до** переименования. Аналогично
   Windows `updater.py` использует пути только как URL запросов (деградации нет). Ссылка LoRA ведёт на ветку
   `feat/llm-postproc-gec`: ветку нельзя удалять, пока живут клиенты с этой ссылкой (или перенести артефакт в релиз).
3. **Подпись/TCC.** Смена `CFBundleDisplayName`, иконки и строк не меняет identifier и designated requirement;
   `install-local.sh` это проверяет. Смена bundle id, `CFBundleExecutable` или сертификата сбросит разрешения —
   запрещено AGENTS.md. Кэш иконок macOS может показывать старую иконку до обновления LaunchServices; решается
   штатно после установки (не запуском копий бандла).
4. **Тип файла корректировок и пользовательские данные**: расширение/UTI/MIME, `corrections.sqlite`, `UserDefaults`,
   ключи `*_v1` — не трогать. Отдельной миграции данных ребрендинг не требует; `MIGRATION_NOTES.md` будет описывать
   «оставлено намеренно».
5. **Inno Setup.** `AppName` задаёт `DefaultDirName`, `DefaultGroupName`, имена `.lnk`, **значение автозапуска** и имя в
   «Приложения и возможности». При `UsePreviousAppDir=no` смена `AppName` положит новую версию в другой каталог
   (`{autopf}\Lexomorph`) и оставит старый. Нужны отдельные `#define AppDisplayName` и неизменный `AppDirName`; если
   ярлык переименовывается — `[InstallDelete]` для старых `.lnk`. `AppId` GUID, `AppExeName`, Run-значение
   (`system.py:384`), AUMID, mutex менять нельзя. Run-значение в `.iss:104` строится из `{#AppName}`, а приложение
   пишет «SuperDictate» (`system.py:384`) — при смене `AppName` получатся два автозапуска.
6. **Qt `setApplicationName("SuperDictate")`** (`main.py:77`) может влиять на пути `QStandardPaths`/`QSettings`; в коде
   они не используются (поиск по `windows/` пуст), но меняйте вместе с проверкой самотестов Windows.
7. **CI и проверки в скриптах** завязаны на старые пути (`check.sh:38-42`, `build.yml`, `release-smoke.yml`,
   `verify-release.sh`). Любая правка README, затрагивающая install-URL, требует правки `check.sh` в том же коммите.
8. **Найденные попутно дефекты (вне ребрендинга, зафиксировать отдельно):**
   - `SuperDictate.iss:187` при удалении спрашивает про `{localappdata}\Dictation`, а данные лежат в `…\SuperDictate`
     (`paths.py:22`) — диалог «удалить настройки и модель» не удалит реальные данные.
   - `[Registry]` (`.iss:103-113`): сначала создаётся Run-значение `SuperDictate`, ниже идёт `deletevalue` для того же
     имени — вероятно, значение стирается сразу после создания, и автозапуск восстанавливается только когда приложение
     переписывает его при сохранении настроек (`system.py:482`). Проверить на Windows.
   - `README.md` Windows «not supported»; `windows/README.md` «Готовых сборок нет»; `PRIVACY.md` «parakeet.cpp», «logs avoid
     transcript text».
   - Расхождение значений по умолчанию автопроверки обновлений macOS/Windows (см. §2.1).
   - Сырые ключи API в открытом виде (macOS plist, Windows JSON).
9. **Самотесты** закрепляют бренд-строки (§2.8). Разрыв между строкой в коде и ожиданием в тесте даст красный CI.
10. **Новый релиз.** Любое изменение `Info.plist` меняет содержимое zip -> новый номер версии, новая SHA-256 в `install.sh` и
    `update.json`, обязательный `scripts/verify-release.sh` (`docs/RELEASING.md`). Номер версии — решение владельца
    (0.9.8 или 0.10.0); в ребрендинг-ветке версия не повышается.
11. **Бренд-активы и честность.** Карточки и hero содержат утверждения, которых нет в продукте (§7); публикация без правки —
    нарушение собственного «no fabricated claims».
12. **Имя `Lexomorph` не проверено на занятость** (домены, товарные знаки, GitHub, brew, App Store, PyPI) — архив это явно не
    подтверждает.

## 5. План изменений

Порядок: A (документы и ассеты, не влияет на бинарники) -> B/C (в отдельных ветках/коммитах) -> релиз. Для B и C: один коммит на тему,
тесты меняются вместе со строками. «Строки» ниже — по состоянию `feat/lexomorph-rebrand` на момент аудита.

### Поток A: README, docs, assets, brand-документы

1. **Ассеты** -> `docs/assets/branding/`: `readme/readme-hero-1280x640.png`, `social/lexomorph-social-1280x640.png` и
   `-1200x630.png`, `features/*.png` (только карточки, которые прошли §7), `icons/final-LM/lexomorph-icon-1024.png` и
   `lexomorph-avatar-512.png`; `source-originals/` положить рядом (12 МБ — решить, держать ли в репозитории или в релизе).
   Прописать в `docs/assets/branding/README.md` происхождение (сгенерировано, SVG-мастеров нет) и проверить размеры.
2. **`README.md`**: заменить шапку (hero, «Lexomorph», «Speak freely. Write precisely.», плашка «formerly SuperDictate Next»),
   удалить бейдж «100% local», переписать вводный абзац и «Why», добавить таблицы: возможности (только §2.4 «существует»),
   конвейер (§2.2), бэкенды и приватность (§2.3, §2.6), синхронизация (§2.5: что выпущено, что нет), режимы (§2.3), платформы
   (macOS 14+, Windows 10 1809+ — `MinVersion=10.0.17763`, `.iss`), установка/обновление/troubleshooting из реальных скриптов.
   **Не менять** строку `curl … shohart/SuperDictate-Next/main/install.sh` (она закреплена `check.sh:39`), команды
   `swift run … Parakey`, пути `/Applications/SuperDictate.app`, `~/Library/…/SuperDictate`, LaunchAgent — объяснить в
   разделе «Совместимость: внутренние имена сохранены». Сохранить раздел Origin/License (Parakey, shlgd), историю
   «SuperDictate-Intel -> SuperDictate Next -> Lexomorph».
3. **`README.ru.md`**: то же, зеркально.
4. **`PRIVACY.md`**: переписать по §2.6 (убрать «parakeet.cpp», «logs avoid transcript text», добавить sync, endpoint, trace).
   **`SECURITY.md`, `CONTRIBUTING.md`** (`CONTRIBUTING.md:12`, «Apple Silicon» и т.п.), `.github/ISSUE_TEMPLATE/*`
   (`bug_report.md:25,32`, `feature_request.md:3`), `.github/PULL_REQUEST_TEMPLATE.md` (чекбокс «no new network calls» уточнить):
   отображаемое имя -> Lexomorph, пути оставить. `config.yml:4` URL не трогать до переименования.
5. **`windows/README.md`**: заголовок и вводка; убрать «Ничего не уходит в сеть» и «Готовых сборок нет»; `windows/PROVENANCE.md`,
   `windows/NOTICE.md` — только дописать.
6. **`CHANGELOG.md`**: шапка «Lexomorph (formerly SuperDictate Next)»; новая запись `## Unreleased` про смену имени;
   старые записи не переписывать. `NOTICE.md`: добавить строку про переименование, кредиты сохранить.
7. **Новые документы** (по IMPLEMENTATION_TASK): `docs/branding/MIGRATION_NOTES.md` (таблица «что намеренно осталось
   `SuperDictate`» = §3 классы C/B), `BRAND_GUIDELINES.md` (палитра/тон из `BRAND_SPEC_RU.md`), `MANUAL_OWNER_ACTIONS.md` (= §8).
8. **`scripts/check.sh`**: ничего не удалять; при необходимости добавить проверки существования новых ассетов. Починить
   `check.sh:38` (no-op) — отдельным коммитом, с учётом, что README ссылается на `shlgd/SuperDictate`.
9. GitHub metadata (about/topics) — только документировать (§8). Topics: `dictation, speech-to-text, asr, macos, windows,
   local-ai, llm, onnx` подтверждены кодом; `text-normalization`, `personal-dictionary`, `writing-assistant` допустимы, но
   с оговоркой (словарь замен существует, «writing assistant» — маркетинговое).

### Поток B: macOS

Бандл, id, исполняемый файл, подпись, LaunchAgent, Application Support — **не трогаются**. Меняется только то, что видит
пользователь.

1. `swift/Info.plist`: `CFBundleDisplayName` (:6) и `CFBundleName` (:31) -> `Lexomorph`; `NSAppleEventsUsageDescription` (:43),
   `NSMicrophoneUsageDescription` (:49) -> «Lexomorph …» (текст про «locally on your Mac» оставить верным: аудио локально);
   `NSHumanReadableCopyright` (:47) -> «Lexomorph (formerly SuperDictate Next), based on Parakey. MIT licensed.»;
   `CFBundleTypeName` (:11) и `UTTypeDescription` (:58) -> «Lexomorph Corrections»; `CFBundleIconFile` — см. п.2.
   Не менять `CFBundleExecutable`, `CFBundleIdentifier`, UTI, расширение, MIME. `scripts/check.sh` делает `plutil -lint`.
2. **Иконка.** Положить `lexomorph.icns` как `icon/Lexomorph.icns` и `CFBundleIconFile=Lexomorph`
   (+ `build-app.sh:` копирование и `build-test-app.sh:75`; `ParakeyApp.swift:6448` `NSImage(named: "Lexomorph")`); либо проще и
   безопаснее: перезаписать содержимое `icon/Parakey.icns` и оставить имена. Выбрать (рекомендация: переименовать на
   `Lexomorph.icns` — имя файла иконки не входит в designated requirement). `icon/generate-appicon.swift` и
   `icon/parakey-512.png` пометить устаревшими/удалить после согласования. Проверить `iconutil`/`sips` и вид в Dock на Mac
   (см. замечание о полях, §2.7).
3. **Иконка меню** `swift/Resources/parakey-menubar{,@2x}.png` — нужен монохромный template-глиф «LM» 22/44 px (в поставке нет —
   владелец/дизайнер, §8). Имена файлов и `NSImage(named: "parakey-menubar")` (`ParakeyApp.swift:1292`) можно оставить; текстовый
   фолбэк и tooltip `"Parakey"` (`:1301,1304,1322`) -> `Lexomorph`.
4. **Строки (литералы):**
   - `ControlPanel.swift`: 400, 432, 457, 976, 985, 1174-1175, 1186-1187, 1274, 1285-1286, 1411, 1955-1956, 2233-2234, 4961-4962.
   - `ParakeyApp.swift`: 3862-3863, 3895-3897, 3919 (имя файла диагностики `Parakey Diagnostics.txt` — **проверить `SelfTest.swift:716-717`**),
     4078, 4135, 4227, 4401, 4464-4465, 4542, 4808, 5424, 5487-5515, 5571, 5592, 5886, 6003, 6024, 6051, 6429, 6441
     («Open source, based on Parakey by Richard Courtman» — **оставить кредит**, но заменить префикс),
     6569, 6661, 6728, 6877-6943. Не менять 4483, 4603, 4605 (указание на имя в TCC), 4234-4236 (пути).
   - `HUDViews.swift`: 935, 945-946, 950-951, 1049-1054 (окно прогресса обновления).
   - `Hotkeys.swift:60,195`; `UpdateCheck.swift:73,79,250,271,676-686` и shell-шаблон `:580-660` (сообщения `Parakey …` ->
     `Lexomorph …`; **имена функций и `parakey-update-*.sh` оставить**); `ModelRegistry.swift:50-56`;
     `ModelDownload.swift:197,395,598,755,885,896`; `Permissions.swift:188,285`; `CorrectionsTransfer.swift:32,46,212`;
     `VocabularyManagerWindow.swift:436,447,473`; `ConfigModels.swift:408`; `main.swift:59` и `DiagnosticCommands.swift:56,123,198,499,562`
     (usage-строки CLI называют исполняемый файл — оставить `SuperDictate`, это реальное имя бинаря).
   - Добавить в About («About …», `ParakeyApp.swift:6429-6448`): «Formerly SuperDictate Next».
5. **Самотесты**, закрепляющие строки: `SelfTest.swift:716-717, 1077, 6455-6465, 6499` обновить в том же коммите; остальные
   (`ParakeySelfTest`, `Parakey.app` в `:6806`, домены `com.local.superdictate.selftest.*`) не трогать.
6. **Install/CI:** `install.sh`, `uninstall.sh`, `scripts/*` — только отображаемые сообщения (`say`/`printf 'SuperDictate: …'`
   -> «Lexomorph: …»), без путей/переменных; `check.sh:47` сообщение. Пути и env — не менять. Установщик говорит по-русски:
   сохранить язык.
7. **Приватность в UI:** убрать/уточнить «audio is not uploaded»-подобные фразы только если они неверны (по коду аудио не
   покидает устройство — верно).
8. **Обновление приёма URL** (`UpdateCheck.swift:84,199`): принять оба префикса `/shohart/SuperDictate-Next/` и будущий
   `/shohart/lexomorph/` — **отдельный релиз до переименования репозитория**.
9. **Релиз**: новая версия, `install.sh` pin + `update.json`, ассет остаётся `SuperDictate.zip`, `verify-release.sh`.
10. **Проверка** (вне этой фазы): `scripts/check.sh`, `swift run -c debug --package-path swift Parakey --self-test all`,
    `scripts/install-local.sh` (единственный способ запуска; после — проверить, что `com.local.superdictate.agent`
    жив, в соответствии с памятью о риске self-test).

### Поток C: Windows

Не менять: `AppExeName`, каталог установки, `AppId`, AUMID, mutex, Run-значение, `%LOCALAPPDATA%\SuperDictate`, имена хелперов и пакета.

1. `windows/superdictate/i18n.py:15` `app_name` -> «Lexomorph» (ru/en) — одним ключом меняются заголовок окна
   (`panel.py:110`), tooltip трея (`tray.py:129`), уведомление (`updates.py:75`), QMessageBox (`settings_window.py:1025`);
   `i18n.py:595-597` («на сервере SuperDictate» -> «на сервере синхронизации Lexomorph»).
2. `main.py:64` (лог) и `:77` `setApplicationName` — по желанию; `version.py:11-14` `UPSTREAM_BASE`: добавить «Lexomorph (formerly
   SuperDictate Next)» (текст кредитов оставить).
3. **Иконка:** заменить `windows/assets/SuperDictate.png` содержимым `lexomorph-icon-1024.png` (файл оставить под старым именем,
   чтобы не менять `spec`, `tray.py:39`, `make_icon.py:SOURCE`, `build.ps1`), `windows/assets/SuperDictate.ico` — содержимым
   `lexomorph.ico` (будет перегенерирован `make_icon.py` из PNG, поэтому PNG главный). Проверить читаемость LM на 16 px и
   точку состояния (`tray.py:36-60`), в том числе в светлой/тёмной панели задач. Если переименовывать файлы в
   `Lexomorph.png/.ico`, править `SuperDictate.spec` (:44,126,139,148), `make_icon.py`, `.iss` (`SetupIconFile`), `tray.py:39`.
4. `windows/installer/SuperDictate.iss`: `#define AppDisplayName "Lexomorph"`; `AppName={#AppDisplayName}` только если
   ввести `AppDirName "SuperDictate"` и использовать его в `DefaultDirName`, `DefaultGroupName` (или явный `UsePreviousAppDir`),
   Run-значении (`ValueName`), `[Icons]` при необходимости переименования ярлыков (`[InstallDelete]` для старых
   `{group}\SuperDictate.lnk`/`{autodesktop}`), `AppPublisher` (:12) -> «Lexomorph (formerly SuperDictate Next)»,
   `[CustomMessages]` (:64-70), `UninstallDisplayName`. `OutputBaseFilename` оставить `SuperDictate-…-setup` в
   первом релизе (Windows-updater допускает любой `.exe`, но Intel/mac-часть и docs/RELEASING.md ссылаются на имя). Попутные
   исправления §4.8 (путь `Dictation`, порядок Run) — отдельными коммитами и только с проверкой на Windows.
5. `windows/SuperDictate.spec` (название коллекции, `name=`) — не менять; docstring можно обновить.
6. `windows/README.md`, `docs/RELEASING.md` (таблица с именами артефактов — описать «имена артефактов сохранены»).
7. **Самотесты Windows** (`selftest.py`): строки с `SuperDictate` в проверках интерфейса — обновить вместе с i18n; `python main.py --self-test`
   на Windows (в этой фазе не выполнялся).
8. Не собирать установщик на Linux: проверка на Windows (build.ps1) обязательна.

## 6. Что оставить `SuperDictate` намеренно (для MIGRATION_NOTES.md)

Bundle id, `SuperDictate.app`, `Contents/MacOS/SuperDictate`, LaunchAgent, Application Support/Logs, UserDefaults, Keychain service,
UTI/расширение/MIME, `SuperDictate.zip`, теги релизов, `update.json`, `SuperDictate*Host`, env `SUPERDICTATE_*`, Windows exe/каталог/
AppId/AUMID/Run/mutex/`%LOCALAPPDATA%`, Python-пакет, домен sync-сервера, SwiftPM-таргет `Parakey`, иконка-файл (до решения),
история и спецификации, кредиты Parakey/shlgd.

## 7. Бренд-материалы против кода (existing / partial / planned / unsupported)

| Заявление бренда | Статус | Комментарий |
|---|---|---|
| Dictation, ASR на выбор (Parakeet Ultra, GigaAM v3; NPU на Windows) | existing | |
| Adaptive ASR / «adapts to your voice and domain» | partial/unsupported | есть hotwords-подсказки терминов из словаря (domain-терминология); адаптации под голос нет |
| Personal vocabulary | existing | словарь замен + ASR-термины |
| Correction learning, «learns from your edits and applies automatically» | existing, с оговорками | автообучение включено по умолчанию, правила эвристические, правка короткая, с отменой; не «ML» |
| Style modes: polish/structured/official/custom | existing | требует LLM (локально или endpoint), по умолчанию выкл. |
| Formal / Clean / Raw (термины бренда) | partial | соответствуют `official`/коррекции/выкл.; переименование display-имён — решение владельца |
| Local-first | partial | аудио локально; текст уходит наружу только при выборе endpoint; нужна сеть для скачивания моделей |
| «Your data stays with you» | partial | см. sync/endpoint |
| Cross-Device Sync «vocabulary, settings, and style» | partial | словарь/термины (выпущено); стили и статистика — не выпущено; настройки — нет; иконка телефона — нет мобильного клиента |
| Cross-platform macOS+Windows | existing | Windows: релизы `win-v*`, без CI |
| Context-aware (приложение/контекст) , adaptive routing, fine-tuning, Lexomorph Studio/SDK, Lexomorph Sync | planned/unsupported | в README не заявлять; «Lexomorph Sync» — допустимо как название функции только при согласии |
| Теги hero «Local-first / Adaptive ASR / Style-aware rewriting» | partial | см. выше |

Рекомендация: использовать hero и social preview (без утверждений о данных); карточки «Adaptive Dictation», «Cross-Device Sync»,
«Local-First Privacy» не публиковать без правки текста; остальные три карточки допустимы с подписью-оговоркой. Диаграмму
pipeline из пакета в поставке нет (только в тексте) — рисовать по §2.2.

## 8. Действия владельца (вручную)

1. **Имя:** проверить занятость `Lexomorph` (GitHub, домены, товарные знаки, brew, PyPI); решение о публичном использовании.
2. **Переименование репозитория** `shohart/SuperDictate-Next` -> `shohart/lexomorph` — **только после** релиза клиента,
   принимающего оба префикса URL (§5 B.8). Проверить редиректы `curl -IL` для API releases, raw `update.json`, raw
   `install.sh`/`uninstall.sh`, `releases/download/…/SuperDictate.zip`, `raw/feat/llm-postproc-gec/…`. Не создавать
   репозиторий со старым именем. Не удалять ветку `feat/llm-postproc-gec`. Затем обновить `origin` локально (сейчас
   `SuperDictate-Intel`), `.github/*`, badge URL, README install-команду и `scripts/check.sh:39-40`, release-smoke, GitHub Pages
   (если есть), интеграции.
3. **Social preview:** загрузить `lexomorph-social-1280x640.png` вручную (Settings -> General -> Social preview; есть
   `1200x630` вариант); проверить обрезку; **About** и topics вручную (`github/GITHUB_METADATA.md`, с учётом §5 A.9).
4. **Подпись/релиз:** подтвердить, что сертификат «PolterType Dev» тот же (designated requirement не меняется — иначе сброс
   TCC у всех пользователей), выбрать версию, выпустить `mac-v…` с `SuperDictate.zip` и `win-v…` (имя `.exe` решить), в
   описании «Lexomorph (formerly SuperDictate Next)» и «имена файлов и путей сохранены намеренно».
5. **Монохромный глиф меню** и ревизия иконки (поля 824/1024, читаемость 16 px); SVG-мастера логотипа/hero, если нужны
   редактируемые исходники; лицензия шрифтов; решение, хранить ли `source-originals/` (12 МБ) в репозитории.
6. **Sync-сервер:** оставить домен `superdictate.bykovlegal.ru` или завести новый (клиенты зашиты на старый; нужен алиас
   на обоих); подтвердить формулировки приватности (хранение паролей/токенов, шифрование на диске — в коде/спеке не
   проверялось).
7. **Публичные утверждения:** утвердить таблицу §2.6 и список «существует/планируется» §7; решить, переименовывать ли display-имена
   режимов (`Polish`/`Structured task`/`Official` -> Clean/Polish/Formal) и вводить ли Raw.
8. **Исправить попутные дефекты** (§4.8): PRIVACY, Windows-деинсталляция, автозапуск, дефолт автопроверки, ключи API.
9. **Миграция** данных не требуется (идентификаторы сохранены); решение о будущей смене идентификаторов (если вообще) — отдельный
   проект с обратимой миграцией, проверкой на обеих ОС и согласием владельца.
