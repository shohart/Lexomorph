# 🤝 Участие в разработке

**[Read this in English](CONTRIBUTING.md)** (основной вариант; этот файл — его русская адаптация).

Issue и pull request в Lexomorph (ранее SuperDictate Next) приветствуются. Держите
изменения сфокусированными, оставляйте звук на устройстве, описывайте любое новое
сетевое взаимодействие в таблице конфиденциальности README и в PRIVACY.md, тестируйте
на macOS 14 и новее (Apple Silicon или Intel), а изменения для Windows — на Windows 10
1809 и новее. С версии 1.0.0 идентификаторы на обеих платформах (bundle ID
`com.local.lexomorph`, `Lexomorph.app`, `%LOCALAPPDATA%\Lexomorph`, пути данных) носят
новое имя; репозиторий теперь `shohart/Lexomorph` (раньше `shohart/SuperDictate-Next`, со
переадресацией); адрес сервера синхронизации и
несколько внутренних имён (Python-пакет `superdictate`, имена файлов C++) намеренно
сохраняют старое; перед любым переименованием см.
[docs/branding/MIGRATION_NOTES.md](docs/branding/MIGRATION_NOTES.md). Документация
пишется сначала на английском; русские файлы (`*.ru.md`) — адаптированные переводы с
теми же фактами, поэтому при изменении пользовательских текстов обновляйте оба варианта.
Правила сообщества см. в [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## ✅ Перед pull request

```bash
./scripts/check.sh
swift run -c debug --package-path swift Lexomorph --self-test all
./scripts/build-app.sh ./dist/Lexomorph.app
```

Для изменений Windows, из `windows\`: `python main.py --self-test`.

## 🚢 Выпуск релиза

Версия релиза в `swift/Info.plist` и `install.sh` должна совпадать. Ресурсы релиза
неизменяемы: публикуйте новую версию, а не заменяйте существующий ZIP, затем обновите
закреплённый SHA-256 в `install.sh`.
