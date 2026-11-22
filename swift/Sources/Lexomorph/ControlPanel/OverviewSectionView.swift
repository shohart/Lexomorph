// Lexomorph — Tab 1: Overview ("Главная") — Service, Instant Quick Modes,
// Account & Broader Sync, and Mini-Stats / Quick Access.

import AppKit
import Foundation

extension LexomorphControlPanelApp {

    func buildOverviewSection(draft: ControlPanelSettingsDraft) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        stack.addArrangedSubview(sectionHeader(
            title: t("Главная", "Overview"),
            subtitle: t("Состояние службы, быстрое переключение режимов и синхронизация аккаунта.",
                        "Service status, quick mode switching, and account sync.")
        ))

        // 1. Service status & conditional alerts (missing permissions, available update)
        stack.addArrangedSubview(overviewServiceCard())

        // 2. Instant Quick Modes card (Correction, Rewrite + Style picker, Punctuation)
        stack.addArrangedSubview(overviewQuickModesCard(draft: draft))

        // 3. Account & Cloud Sync card (vocabulary, hotwords, rewrite styles, prompts, usage)
        stack.addArrangedSubview(overviewAccountSyncCard())

        // 4. Compact stats & dictionary quick access
        stack.addArrangedSubview(overviewStatsAndVocabularyCard())

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    // MARK: - 1. Service Card

    private func overviewServiceCard() -> NSView {
        let running = LexomorphAgentService.isAgentRunning()
        let state = AgentRuntimeStateStore.read()
        let presentation = servicePresentation(running: running, state: state)
        let missingPermissions = Permission.allCases.filter { !Permissions.isGranted($0) }

        var rows: [NSView] = []

        // Main status row
        let topRow = NSStackView()
        topRow.orientation = .horizontal
        topRow.alignment = .centerY
        topRow.spacing = 12

        let icon = panelSymbol(running ? "waveform.circle.fill" : "waveform.circle",
                               color: presentation.color,
                               description: t("Состояние службы", "Service status"),
                               pointSize: 24)

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2

        let titleLine = NSStackView()
        titleLine.orientation = .horizontal
        titleLine.alignment = .centerY
        titleLine.spacing = 8
        titleLine.addArrangedSubview(panelLabel(presentation.status, size: 14, weight: .semibold))
        if missingPermissions.isEmpty {
            titleLine.addArrangedSubview(chipBadge(
                text: t("Доступы выданы", "Permissions OK"),
                symbol: "checkmark.shield.fill",
                color: .systemGreen
            ))
        }
        text.addArrangedSubview(titleLine)

        let hk = localizedHotkeyName(settings.configuredHotkey, language: language)
        let triggerShort = localizedTriggerModeShort(settings.triggerMode)
        let engine = settings.speechModelProfile.shortName
        let detail = panelLabel(
            "\(presentation.detail)\n\(hk) (\(triggerShort)) · \(engine)",
            size: 11.5,
            color: .secondaryLabelColor
        )
        detail.preferredMaxLayoutWidth = 340
        text.addArrangedSubview(detail)

        if running, state?.status == "starting" {
            let progressBar = NSProgressIndicator()
            progressBar.style = .bar
            progressBar.controlSize = .small
            if let fraction = state?.downloadProgressFraction {
                progressBar.isIndeterminate = false
                progressBar.minValue = 0
                progressBar.maxValue = 1
                progressBar.doubleValue = fraction
            } else {
                progressBar.isIndeterminate = true
                progressBar.startAnimation(nil)
            }
            progressBar.translatesAutoresizingMaskIntoConstraints = false
            progressBar.heightAnchor.constraint(equalToConstant: 6).isActive = true
            text.addArrangedSubview(progressBar)
            progressBar.widthAnchor.constraint(equalTo: text.widthAnchor).isActive = true
        }

        let actions = NSStackView()
        actions.orientation = .horizontal
        actions.alignment = .centerY
        actions.spacing = 6
        let enabled = serviceOperation == nil
        if running {
            actions.addArrangedSubview(compactIconButton(
                symbol: "arrow.clockwise",
                accessibilityTitle: t("Перезапустить службу", "Restart Service"),
                toolTip: t("Перезапустить фоновую службу", "Restart background service"),
                action: #selector(restartAgentClicked(_:)),
                enabled: enabled
            ))
            actions.addArrangedSubview(compactIconButton(
                symbol: "stop.fill",
                accessibilityTitle: t("Остановить службу", "Stop Service"),
                toolTip: t("Остановить диктовку до ручного запуска", "Stop dictation until manually started"),
                action: #selector(stopAgentClicked(_:)),
                enabled: enabled
            ))
        } else {
            actions.addArrangedSubview(compactIconButton(
                symbol: "play.fill",
                accessibilityTitle: t("Запустить службу", "Start Service"),
                toolTip: t("Запустить фоновую службу диктовки", "Start background dictation service"),
                action: #selector(startAgentClicked(_:)),
                enabled: enabled
            ))
        }

        topRow.addArrangedSubview(icon)
        topRow.addArrangedSubview(text)
        topRow.addArrangedSubview(NSView())
        topRow.addArrangedSubview(actions)
        rows.append(topRow)

        // Conditional missing-permissions strip (hidden when all 3 are granted!)
        if !missingPermissions.isEmpty {
            let permBox = NSStackView()
            permBox.orientation = .vertical
            permBox.alignment = .leading
            permBox.spacing = 6

            let permHeader = NSStackView()
            permHeader.orientation = .horizontal
            permHeader.alignment = .centerY
            permHeader.spacing = 6
            permHeader.addArrangedSubview(panelSymbol("exclamationmark.shield.fill",
                                                      color: .systemOrange,
                                                      description: nil,
                                                      pointSize: 13))
            permHeader.addArrangedSubview(panelLabel(
                t("Нужны разрешения macOS (\(missingPermissions.count))",
                  "macOS permissions required (\(missingPermissions.count))"),
                size: 12,
                weight: .semibold,
                color: .systemOrange
            ))
            permBox.addArrangedSubview(permHeader)

            for permission in missingPermissions {
                let permRow = NSStackView()
                permRow.orientation = .horizontal
                permRow.alignment = .centerY
                permRow.spacing = 8
                let label = panelLabel(permissionTitle(permission), size: 12, weight: .medium)
                label.toolTip = permissionDetail(permission)
                let buttonTitle = (permissionClickCount[permission] ?? 0) >= 1
                    ? t("Открыть настройки", "Open Settings")
                    : t("Разрешить", "Grant")
                let button = panelButton(buttonTitle,
                                         action: #selector(grantPermissionClicked(_:)),
                                         enabled: serviceOperation == nil,
                                         toolTip: permissionDetail(permission))
                button.controlSize = .small
                button.tag = Permission.allCases.firstIndex(of: permission) ?? -1
                permRow.addArrangedSubview(label)
                permRow.addArrangedSubview(NSView())
                permRow.addArrangedSubview(button)
                permBox.addArrangedSubview(permRow)
                permRow.widthAnchor.constraint(equalTo: permBox.widthAnchor).isActive = true
            }
            rows.append(permBox)
        }

        // Conditional update banner (shown only when an update is available or installing)
        if case .available(let release) = updateState {
            let updateRow = NSStackView()
            updateRow.orientation = .horizontal
            updateRow.alignment = .centerY
            updateRow.spacing = 8
            updateRow.addArrangedSubview(panelSymbol("arrow.down.circle.fill",
                                                     color: .systemBlue,
                                                     description: nil,
                                                     pointSize: 15))
            updateRow.addArrangedSubview(panelLabel(
                t("Доступно обновление Lexomorph v\(release.version)",
                  "Lexomorph v\(release.version) is available"),
                size: 12,
                weight: .medium
            ))
            updateRow.addArrangedSubview(NSView())
            let updateBtn = panelButton(t("Обновить", "Update"),
                                        action: #selector(updateButtonClicked(_:)),
                                        enabled: serviceOperation == nil)
            updateBtn.controlSize = .small
            updateRow.addArrangedSubview(updateBtn)
            rows.append(updateRow)
        } else if case .preparing(let version, let phase) = updateState {
            let updateRow = NSStackView()
            updateRow.orientation = .horizontal
            updateRow.alignment = .centerY
            updateRow.spacing = 8
            updateRow.addArrangedSubview(panelSymbol("arrow.down.circle",
                                                     color: .systemBlue,
                                                     description: nil,
                                                     pointSize: 15))
            updateRow.addArrangedSubview(panelLabel(
                t("Обновляю до v\(version): \(phase)", "Updating to v\(version): \(phase)"),
                size: 12,
                color: .secondaryLabelColor
            ))
            rows.append(updateRow)
        }

        let jumpToDictation = linkButton(
            t("Диктовка →", "Dictation →"),
            action: #selector(jumpToSectionClicked(_:)),
            tag: ControlPanelSection.dictation.rawValue,
            toolTip: t("Открыть настройки диктовки и хоткеев", "Open dictation and hotkey settings")
        )
        return settingsCard(
            title: t("Служба диктовки", "Dictation Service"),
            symbol: "bolt.circle",
            accessory: jumpToDictation,
            rows: rows
        )
    }

    // MARK: - 2. Quick Modes Card (Instant Live Toggles!)

    private func overviewQuickModesCard(draft: ControlPanelSettingsDraft) -> NSView {
        let correctionOn = settings.textPostprocessingMode == .correction
        let rewriteOn = settings.rewriteEnabled
        let punctuationOn = settings.punctuationRestorationEnabled

        let correctionModelLabel: String = settings.llmEngineBackend == .bundledLocal
            ? settings.correctionBundledModel.displayName
            : (settings.llmCustomModelName.isEmpty ? t("Свой сервер", "Custom server") : settings.llmCustomModelName)
        let correctionShortcut = localizedHotkeyName(settings.configuredCorrectionHotkey, language: language)

        let correctionRow = toggleRow(
            title: t("Коррекция текста", "Text Correction"),
            detail: "\(correctionModelLabel) · \(t("хоткей", "hotkey")): \(correctionShortcut)",
            isOn: correctionOn,
            action: #selector(quickToggleCorrectionClicked(_:)),
            toolTip: t("Мгновенно включить или выключить коррекцию текста (без перезапуска).",
                       "Instantly toggle text correction (no restart needed)."),
            leadingBadge: panelSymbol("text.badge.checkmark",
                                      color: correctionOn ? .controlAccentColor : .secondaryLabelColor,
                                      description: nil,
                                      pointSize: 15)
        )

        let rewriteModelLabel: String = settings.rewriteEngineBackend == .bundledLocal
            ? settings.rewriteBundledModel.displayName
            : (settings.rewriteCustomModelName.isEmpty ? t("Свой сервер", "Custom server") : settings.rewriteCustomModelName)
        let rewriteShortcut = localizedHotkeyName(settings.configuredRewriteToggleHotkey, language: language)

        let rewriteRow = toggleRow(
            title: t("Рерайт текста", "Text Rewrite"),
            detail: "\(rewriteModelLabel) · \(t("хоткей", "hotkey")): \(rewriteShortcut)",
            isOn: rewriteOn,
            action: #selector(quickToggleRewriteClicked(_:)),
            toolTip: t("Мгновенно включить или выключить рерайт текста (без перезапуска).",
                       "Instantly toggle text rewrite (no restart needed)."),
            leadingBadge: panelSymbol("wand.and.stars",
                                      color: rewriteOn ? .controlAccentColor : .secondaryLabelColor,
                                      description: nil,
                                      pointSize: 15)
        )

        var rows: [NSView] = [correctionRow, rewriteRow]

        // Rewrite style picker row (shown cleanly right under Rewrite toggle when enabled)
        if rewriteOn {
            let styleRow = NSStackView()
            styleRow.orientation = .horizontal
            styleRow.alignment = .centerY
            styleRow.spacing = 10

            let indentIcon = panelSymbol("slider.horizontal.3",
                                         color: .secondaryLabelColor,
                                         description: nil,
                                         pointSize: 13)
            let styleLabel = panelLabel(t("Стиль рерайта", "Rewrite style"), size: 12.5, weight: .medium)

            let popup = NSPopUpButton()
            popup.target = self
            popup.action = #selector(quickSelectRewriteStyle(_:))
            popup.toolTip = t("Активный стиль рерайта — применяется мгновенно.",
                              "Active rewrite style — applies immediately.")

            let activeID = settings.rewriteStyleID
            for style in RewriteStyle.allCases {
                popup.addItem(withTitle: localizedRewriteStyleLongName(style))
                popup.lastItem?.representedObject = style.rawValue
            }
            let customStyles = settings.customRewriteStyles
            if !customStyles.isEmpty {
                popup.menu?.addItem(.separator())
                for custom in customStyles {
                    popup.addItem(withTitle: custom.name)
                    popup.lastItem?.representedObject = custom.id
                    popup.lastItem?.image = colorDotImage(hex: custom.colorHex)
                }
            }
            if let selectedItem = popup.itemArray.first(where: { ($0.representedObject as? String) == activeID }) {
                popup.select(selectedItem)
            }
            popup.setContentHuggingPriority(.required, for: .horizontal)

            let manageBtn = linkButton(
                t("Режимы…", "Modes…"),
                action: #selector(jumpToAIRewriteClicked(_:)),
                toolTip: t("Настроить встроенные и свои режимы рерайта",
                           "Configure built-in and custom rewrite modes")
            )

            styleRow.addArrangedSubview(indentIcon)
            styleRow.addArrangedSubview(styleLabel)
            styleRow.addArrangedSubview(NSView())
            styleRow.addArrangedSubview(manageBtn)
            styleRow.addArrangedSubview(popup)
            rows.append(styleRow)
        }

        let punctInstalled = punctuationModelInstalled(settings.punctuationModel)
        let punctDetail = punctInstalled
            ? t("Модель \(settings.punctuationModel.displayName) · готова",
                "\(settings.punctuationModel.displayName) model · ready")
            : t("Модель \(settings.punctuationModel.displayName) не скачана",
                "\(settings.punctuationModel.displayName) model not downloaded")
        let punctTrailing: NSView? = punctInstalled ? nil : linkButton(
            t("Скачать →", "Download →"),
            action: #selector(jumpToAIPunctuationClicked(_:))
        )
        let punctRow = toggleRow(
            title: t("Восстановление пунктуации", "Punctuation Restoration"),
            detail: punctDetail,
            isOn: punctuationOn,
            action: #selector(quickTogglePunctuationClicked(_:)),
            toolTip: t("Мгновенно включить или выключить модель расстановки пунктуации.",
                       "Instantly toggle punctuation restoration."),
            leadingBadge: panelSymbol("textformat.abc.dottedunderline",
                                      color: punctuationOn ? .controlAccentColor : .secondaryLabelColor,
                                      description: nil,
                                      pointSize: 15),
            trailingAction: punctTrailing
        )
        rows.append(punctRow)

        let aiLink = linkButton(
            t("Настроить AI →", "Configure AI →"),
            action: #selector(jumpToSectionClicked(_:)),
            tag: ControlPanelSection.ai.rawValue,
            toolTip: t("Открыть подробные настройки моделей, промптов и серверов",
                       "Open detailed model, prompt, and server settings")
        )
        return settingsCard(
            title: t("Быстрое переключение режимов", "Quick Modes"),
            symbol: "sparkles",
            accessory: aiLink,
            rows: rows
        )
    }

    // MARK: - 3. Account & Cloud Sync Card (First Tab!)

    private func overviewAccountSyncCard() -> NSView {
        let signedIn = vocabularySync.isSignedIn
        var rows: [NSView] = []

        if signedIn {
            let accountRow = NSStackView()
            accountRow.orientation = .horizontal
            accountRow.alignment = .centerY
            accountRow.spacing = 10

            let avatar = panelSymbol("person.crop.circle.fill",
                                     color: .controlAccentColor,
                                     description: nil,
                                     pointSize: 22)

            let info = NSStackView()
            info.orientation = .vertical
            info.alignment = .leading
            info.spacing = 2
            info.addArrangedSubview(panelLabel(settings.vocabularySyncEmail, size: 13, weight: .semibold))

            let statusLabel = panelLabel("", size: 11.5, color: .secondaryLabelColor)
            statusLabel.preferredMaxLayoutWidth = 310
            info.addArrangedSubview(statusLabel)
            vocabularySyncStatusLabel = statusLabel
            updateVocabularySyncStatusLabel()

            let syncNowBtn = panelButton(
                t("Синхронизировать", "Sync Now"),
                action: #selector(vocabularySyncNowClicked),
                enabled: !vocabularySyncBusy,
                toolTip: t("Отправить локальные изменения и получить обновления с других устройств.",
                           "Push local changes and pull updates from your other devices.")
            )
            syncNowBtn.controlSize = .small

            let signOutBtn = panelButton(
                t("Выйти", "Sign Out"),
                action: #selector(vocabularySyncSignOutClicked),
                enabled: !vocabularySyncBusy,
                toolTip: t("Остановить синхронизацию на этом Mac. Локальные данные сохранятся.",
                           "Stop syncing on this Mac. Local data stays intact.")
            )
            signOutBtn.controlSize = .small

            accountRow.addArrangedSubview(avatar)
            accountRow.addArrangedSubview(info)
            accountRow.addArrangedSubview(NSView())
            if vocabularySyncBusy {
                let spinner = NSProgressIndicator()
                spinner.style = .spinning
                spinner.controlSize = .small
                spinner.startAnimation(nil)
                accountRow.addArrangedSubview(spinner)
            }
            accountRow.addArrangedSubview(syncNowBtn)
            accountRow.addArrangedSubview(signOutBtn)
            rows.append(accountRow)

            // Scope chips showing EVERYTHING synced across devices
            let vocabCount = settings.vocabularyStore.all().count
            let hotwordsCount = settings.vocabularyStore.hotwordPhrases().count
            let stylesCount = settings.customRewriteStyles.count
            let chipsRow = NSStackView()
            chipsRow.orientation = .horizontal
            chipsRow.alignment = .centerY
            chipsRow.spacing = 6
            chipsRow.addArrangedSubview(chipBadge(
                text: t("Словарь: \(vocabCount)", "Vocabulary: \(vocabCount)"),
                symbol: "book.closed",
                color: .systemGreen
            ))
            chipsRow.addArrangedSubview(chipBadge(
                text: t("Термины: \(hotwordsCount)", "Terms: \(hotwordsCount)"),
                symbol: "tag",
                color: .systemGreen
            ))
            chipsRow.addArrangedSubview(chipBadge(
                text: t("Режимы: \(stylesCount) + промпты", "Modes: \(stylesCount) + prompts"),
                symbol: "wand.and.stars",
                color: .systemGreen
            ))
            chipsRow.addArrangedSubview(chipBadge(
                text: t("Правила и паразиты", "Text & fillers"),
                symbol: "slider.horizontal.3",
                color: .systemGreen
            ))
            chipsRow.addArrangedSubview(chipBadge(
                text: t("Статистика", "Stats"),
                symbol: "chart.bar",
                color: .systemGreen
            ))
            chipsRow.addArrangedSubview(NSView())
            rows.append(chipsRow)
        } else {
            vocabularySyncStatusLabel = nil
            let signInBlock = NSStackView()
            signInBlock.orientation = .vertical
            signInBlock.alignment = .leading
            signInBlock.spacing = 8

            if settings.vocabularySyncEnabled,
               settings.vocabularySyncLastError == VocabularySyncFailure.unauthorized.rawValue {
                signInBlock.addArrangedSubview(panelLabel(
                    t("Сессия истекла — войдите снова.", "Session expired — please sign in again."),
                    size: 12,
                    weight: .medium,
                    color: .systemOrange
                ))
            }

            let intro = panelLabel(
                t("Войдите, чтобы синхронизировать словарь, ASR-термины, режимы рерайта, системные промпты, слова-паразиты, правила текста и статистику между Mac и Windows. Если аккаунта ещё нет, он создастся автоматически.",
                  "Sign in to sync your vocabulary, ASR terms, custom rewrite modes, system prompts, filler words, text rules, and usage statistics across Mac and Windows. If you don't have an account yet, one is created automatically."),
                size: 11.5,
                color: .secondaryLabelColor
            )
            intro.preferredMaxLayoutWidth = 490
            signInBlock.addArrangedSubview(intro)

            let fieldsRow = NSStackView()
            fieldsRow.orientation = .horizontal
            fieldsRow.alignment = .centerY
            fieldsRow.spacing = 8

            let emailField = NSTextField()
            emailField.stringValue = vocabularySyncEmailInput ?? settings.vocabularySyncEmail
            emailField.placeholderString = "name@example.com"
            emailField.tag = Self.vocabularySyncEmailFieldTag
            emailField.delegate = self
            emailField.target = self
            emailField.action = #selector(vocabularySyncSignInClicked)
            emailField.isEnabled = !vocabularySyncBusy
            emailField.setAccessibilityLabel(t("Эл. почта аккаунта", "Account e-mail"))

            let passwordField = NSSecureTextField()
            passwordField.stringValue = vocabularySyncPasswordInput
            passwordField.placeholderString = t("Пароль (от 8 символов)", "Password (8+ chars)")
            passwordField.tag = Self.vocabularySyncPasswordFieldTag
            passwordField.delegate = self
            passwordField.target = self
            passwordField.action = #selector(vocabularySyncSignInClicked)
            passwordField.isEnabled = !vocabularySyncBusy
            passwordField.setAccessibilityLabel(t("Пароль аккаунта", "Account password"))

            let signInButton = panelButton(
                t("Войти", "Sign In"),
                action: #selector(vocabularySyncSignInClicked),
                enabled: !vocabularySyncBusy,
                toolTip: t("Войти или создать аккаунт синхронизации Lexomorph.",
                           "Sign in to or create a Lexomorph sync account.")
            )

            fieldsRow.addArrangedSubview(emailField)
            fieldsRow.addArrangedSubview(passwordField)
            fieldsRow.addArrangedSubview(signInButton)
            if vocabularySyncBusy {
                let spinner = NSProgressIndicator()
                spinner.style = .spinning
                spinner.controlSize = .small
                spinner.startAnimation(nil)
                fieldsRow.addArrangedSubview(spinner)
            }
            emailField.widthAnchor.constraint(greaterThanOrEqualToConstant: 185).isActive = true
            passwordField.widthAnchor.constraint(greaterThanOrEqualToConstant: 155).isActive = true
            signInBlock.addArrangedSubview(fieldsRow)
            fieldsRow.widthAnchor.constraint(equalTo: signInBlock.widthAnchor).isActive = true

            let privacyNote = panelLabel(
                t("Аудиозаписи, история диктовок, хоткеи и API-ключи никогда не отправляются на сервер.",
                  "Audio recordings, dictation history, hotkeys, and API keys are never uploaded."),
                size: 11,
                color: .tertiaryLabelColor
            )
            privacyNote.preferredMaxLayoutWidth = 490
            signInBlock.addArrangedSubview(privacyNote)

            rows.append(signInBlock)
        }

        if let message = vocabularySyncMessage {
            let errorLabel = panelLabel(message, size: 11.5, color: .systemRed)
            errorLabel.preferredMaxLayoutWidth = 490
            rows.append(errorLabel)
        }

        let badge: NSView? = signedIn
            ? chipBadge(text: t("Активна", "Active"), symbol: "checkmark.circle.fill", color: .systemGreen)
            : nil

        return settingsCard(
            title: t("Аккаунт и синхронизация", "Account & Sync"),
            symbol: "icloud",
            symbolColor: signedIn ? .systemGreen : .secondaryLabelColor,
            accessory: badge,
            rows: rows
        )
    }

    // MARK: - 4. Compact Stats & Vocabulary Strip

    private func overviewStatsAndVocabularyCard() -> NSView {
        settings.refreshFromDisk()
        let allUsage = settings.combinedDailyDictationUsage
        let calendar = Calendar.current
        let now = Date()
        let todayStart = calendar.startOfDay(for: now)
        let todayKey = dictationUsageDayKey(for: todayStart, calendar: calendar)
        let byDay = Dictionary(uniqueKeysWithValues: allUsage.map { ($0.day, $0) })
        let todayUsage = byDay[todayKey] ?? DailyDictationUsage(day: todayKey)
        var weekTotalDictations = 0
        var weekTotalChars = 0
        for offset in 0..<7 {
            if let date = calendar.date(byAdding: .day, value: -offset, to: todayStart),
               let usage = byDay[dictationUsageDayKey(for: date, calendar: calendar)] {
                weekTotalDictations += usage.dictationCount
                weekTotalChars += usage.characterCount
            }
        }

        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 12

        let icon = panelSymbol("chart.bar.doc.horizontal", color: .secondaryLabelColor, description: nil, pointSize: 16)
        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        let todayDictsStr = formattedUsageInteger(todayUsage.dictationCount, language: language)
        let todayCharsStr = formattedUsageInteger(todayUsage.characterCount, language: language)
        let weekDictsStr = formattedUsageInteger(weekTotalDictations, language: language)
        let weekCharsStr = formattedUsageInteger(weekTotalChars, language: language)
        text.addArrangedSubview(panelLabel(
            t("Сегодня: \(todayDictsStr) дикт. · \(todayCharsStr) симв.",
              "Today: \(todayDictsStr) dictations · \(todayCharsStr) chars"),
            size: 12.5,
            weight: .semibold
        ))
        text.addArrangedSubview(panelLabel(
            t("За 7 дней: \(weekDictsStr) дикт. · \(weekCharsStr) симв." + (vocabularySync.isSignedIn ? " (все устройства)" : ""),
              "Last 7 days: \(weekDictsStr) dictations · \(weekCharsStr) chars" + (vocabularySync.isSignedIn ? " (all devices)" : "")),
            size: 11.5,
            color: .secondaryLabelColor
        ))

        let statsLink = linkButton(
            t("Подробная статистика →", "Full Statistics →"),
            action: #selector(jumpToSectionClicked(_:)),
            tag: ControlPanelSection.statistics.rawValue,
            toolTip: t("Открыть графики и тепловую карту активности", "Open charts and activity heatmap")
        )

        let vocabBtn = panelButton(
            t("Открыть словарь…", "Open Vocabulary…"),
            action: #selector(openVocabularyManager),
            toolTip: t("Управление словарём замен и ASR-терминами.", "Manage text replacements and ASR hotwords.")
        )
        vocabBtn.controlSize = .small

        row.addArrangedSubview(icon)
        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(statsLink)
        row.addArrangedSubview(vocabBtn)

        return settingsCard(rows: [row])
    }
}
