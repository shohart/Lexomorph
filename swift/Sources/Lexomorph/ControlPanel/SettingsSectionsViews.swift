// Lexomorph — Settings section views: Dictation, Text & Vocabulary,
// Audio, Appearance (Indicator), and System.

import AppKit
import Foundation
import ServiceManagement

extension LexomorphControlPanelApp {

    // MARK: - Tab 2: Dictation

    func buildDictationSection(draft: ControlPanelSettingsDraft) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        stack.addArrangedSubview(sectionHeader(
            title: t("Диктовка", "Dictation"),
            subtitle: t("Модель распознавания речи, язык и сочетания клавиш.",
                        "Speech recognition engine, language hint, and keyboard shortcuts.")
        ))

        let recognitionCard = settingsCard(
            title: t("Распознавание речи", "Speech Recognition"),
            symbol: "waveform",
            rows: [
                popupRow(
                    title: t("Движок распознавания", "Speech engine"),
                    detail: t("ONNX Runtime, CPU. Parakeet Ultra — многоязычная; GigaAM v3 — точнее на русском.",
                              "ONNX Runtime, CPU only. Parakeet Ultra is multilingual; GigaAM v3 is more accurate in Russian."),
                    selectedValue: draft.speechModelProfile.rawValue,
                    options: SpeechModelProfile.allCases.map { ($0.displayName, $0.rawValue) },
                    action: #selector(selectSpeechModelProfile(_:)),
                    toolTip: t("Выбор модели распознавания речи (требует перезапуска службы).",
                               "Choose the speech recognition model (requires service restart).")
                ),
                popupRow(
                    title: t("Подсказка языка", "Language hint"),
                    detail: t("Автоопределение подходит для большинства задач; выбор языка помогает пост-обработке.",
                              "Auto-detect works for most dictation; picking a language guides post-processing."),
                    selectedValue: draft.dictationLanguage.rawValue,
                    options: DictationLanguage.allCases.map { (localizedDictationLanguageName($0), $0.rawValue) },
                    action: #selector(selectDictationLanguageDraft(_:)),
                    toolTip: t("Применяется мгновенно.", "Applies immediately.")
                ),
            ]
        )

        let controlsCard = settingsCard(
            title: t("Управление и хоткеи", "Controls & Shortcuts"),
            symbol: "keyboard",
            rows: [
                hotkeyRow(
                    title: t("Хоткей диктовки", "Dictation shortcut"),
                    detail: t("Начать и завершить запись голоса.", "Start and finish voice recording."),
                    shortcut: draft.dictationHotkey,
                    kind: .dictation,
                    toolTip: t("Нажмите, чтобы записать новое сочетание клавиш.", "Click to record a new shortcut.")
                ),
                popupRow(
                    title: t("Режим активации", "Trigger mode"),
                    detail: t("Удерживать клавишу во время речи или нажимать для старта и остановки.",
                              "Hold the shortcut while speaking, or press once to start and again to stop."),
                    selectedValue: draft.triggerMode.rawValue,
                    options: [
                        (t("Удерживать", "Press and hold"), TriggerMode.hold.rawValue),
                        (t("Нажать для старта и остановки", "Press to toggle"), TriggerMode.toggle.rawValue),
                    ],
                    action: #selector(selectTriggerModeDraft(_:)),
                    toolTip: t("Применяется мгновенно.", "Applies immediately.")
                ),
                primaryCompletionBehaviorRow(draft),
                alternateCompletionRow(draft),
                popupRow(
                    title: t("Задержка Enter", "Enter delay"),
                    detail: t("Пауза между вставкой текста и нажатием Enter.",
                              "Pause between inserting text and pressing Enter."),
                    selectedValue: String(draft.enterDelayMilliseconds),
                    options: Self.enterDelayOptions,
                    action: #selector(selectEnterDelay(_:)),
                    toolTip: t("Некоторым приложениям (Electron, VM) нужна пауза после вставки.",
                               "Some apps (Electron, VMs) need a brief pause after paste.")
                ),
                hotkeyRow(
                    title: t("История диктовок", "History overlay"),
                    detail: t("Открыть или закрыть оверлей последних транскрипций.",
                              "Toggle the recent transcriptions overlay."),
                    shortcut: draft.historyHotkey,
                    kind: .history,
                    toolTip: t("Сочетание для открытия окна истории.", "Shortcut for toggling history.")
                ),
            ]
        )

        stack.addArrangedSubview(recognitionCard)
        stack.addArrangedSubview(controlsCard)

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    private func primaryCompletionBehaviorRow(_ draft: ControlPanelSettingsDraft) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 12

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(t("Повторное нажатие", "Press again"), size: 13, weight: .semibold))
        text.addArrangedSubview(panelLabel(
            t("Что сделать после вставки распознанного текста.",
              "What to do after inserting the transcribed text."),
            size: 11.5,
            color: .secondaryLabelColor
        ))

        let control = NSSegmentedControl(
            labels: [t("Вставить", "Insert"), t("Вставить + Enter", "Insert + Enter")],
            trackingMode: .selectOne,
            target: self,
            action: #selector(selectPrimaryCompletionBehavior(_:))
        )
        control.selectedSegment = draft.primaryCompletionBehavior == .insert ? 0 : 1
        control.isEnabled = serviceOperation == nil
        control.toolTip = t("Действие при завершении диктовки (применяется мгновенно).",
                            "Action when finishing dictation (applies immediately).")
        control.setContentHuggingPriority(.required, for: .horizontal)

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(control)
        return row
    }

    private func alternateCompletionRow(_ draft: ControlPanelSettingsDraft) -> NSView {
        let behavior = draft.primaryCompletionBehavior.opposite
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(
            behavior == .insert
                ? t("Завершить без Enter", "Finish without Enter")
                : t("Завершить + Enter", "Finish + Enter"),
            size: 13,
            weight: .semibold
        ))
        text.addArrangedSubview(panelLabel(
            t("Дополнительный хоткей работает только во время записи.",
              "Alternative shortcut active only while recording."),
            size: 11.5,
            color: .secondaryLabelColor
        ))

        let toggle = NSSwitch()
        toggle.target = self
        toggle.action = #selector(toggleAlternateCompletion(_:))
        toggle.state = draft.alternateCompletionEnabled ? .on : .off
        toggle.isEnabled = serviceOperation == nil
        toggle.setContentHuggingPriority(.required, for: .horizontal)

        let button = panelButton(
            localizedHotkeyName(draft.alternateCompletionHotkey, language: language),
            action: #selector(recordDictationShortcutClicked(_:)),
            enabled: draft.alternateCompletionEnabled && serviceOperation == nil,
            toolTip: t("Изменить дополнительный хоткей завершения.", "Change alternative finish shortcut.")
        )
        button.tag = ControlPanelShortcutKind.alternateCompletion.rawValue
        button.widthAnchor.constraint(equalToConstant: 164).isActive = true

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(toggle)
        row.addArrangedSubview(button)
        return row
    }

    // MARK: - Tab 3: Text & Vocabulary

    func buildTextSection(draft: ControlPanelSettingsDraft) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        stack.addArrangedSubview(sectionHeader(
            title: t("Текст и словарь", "Text & Vocabulary"),
            subtitle: t("Правила форматирования, очистка слов-паразитов, словарь и история.",
                        "Formatting rules, filler-word cleanup, personal vocabulary, and history.")
        ))

        let formattingCard = settingsCard(
            title: t("Форматирование текста", "Text Formatting"),
            symbol: "textformat",
            rows: [
                popupRow(
                    title: t("После вставки", "After pasting"),
                    detail: t("Что добавлять в конце вставленного текста.", "What to append at the end of pasted text."),
                    selectedValue: draft.pasteSuffix.rawValue,
                    options: [
                        (t("Добавить пробел", "Append space"), PasteSuffix.appendSpace.rawValue),
                        (t("Ничего не добавлять", "No suffix"), PasteSuffix.none.rawValue),
                        (t("Перенос строки", "Append newline"), PasteSuffix.appendNewline.rawValue),
                    ],
                    action: #selector(selectPasteSuffixDraft(_:))
                ),
                toggleRow(
                    title: t("Числа цифрами", "Numbers as digits"),
                    detail: t("Записывать продиктованные числа цифрами (25) вместо слов. Только для русского языка.",
                              "Write dictated numbers as digits (25) instead of words. Russian only."),
                    isOn: draft.normalizeNumbersToDigits,
                    action: #selector(toggleNormalizeNumbers(_:))
                ),
                toggleRow(
                    title: t("Убирать финальную точку", "Remove final period"),
                    detail: t("Удалять точку в конце продиктованного текста (многоточия сохраняются).",
                              "Drop the trailing period from dictated text (ellipses are kept)."),
                    isOn: draft.removeFinalPeriod,
                    action: #selector(toggleRemoveFinalPeriodSetting(_:))
                ),
                fillerWordsBlock(draft),
            ]
        )

        let vocabCount = settings.vocabularyStore.all().count
        let hotwordsCount = settings.vocabularyStore.hotwordPhrases().count
        var vocabRows: [NSView] = [
            vocabularyOpenRow(vocabCount: vocabCount, hotwordsCount: hotwordsCount),
            toggleRow(
                title: t("Автоматически учить словарь по вашим правкам",
                         "Automatically learn vocabulary from edits"),
                detail: t("Запоминает регулярные исправления, которые вы вносите сразу после вставки.",
                          "Remembers corrections you make right after dictation is inserted."),
                isOn: draft.autoLearnVocabularyEnabled,
                action: #selector(toggleAutoLearnVocabularySetting(_:))
            ),
            toggleRow(
                title: t("Подсказывать распознаванию термины из словаря",
                         "Bias recognition toward vocabulary terms"),
                detail: t("Улучшает распознавание имён, аббревиатур и латиницы из словаря.",
                          "Helps the speech model recognize names, acronyms, and Latin terms from your vocabulary."),
                isOn: draft.asrHotwordsEnabled,
                action: #selector(toggleAsrHotwordsSetting(_:)),
                hint: t("Выученные обычные слова не подсказываются; отдельные записи можно включить в окне словаря, колонка «Подсказка ASR».",
                        "Ordinary learned words are not boosted; toggle individual entries in the vocabulary window under 'ASR hint'.")
            ),
        ]
        if draft.asrHotwordsEnabled {
            vocabRows.append(popupRow(
                title: t("Сила подсказки", "Hint strength"),
                detail: t("«Сильнее» чаще исправляет редкие термины, но может заменять похожие обычные слова.",
                          "'Strong' catches more terms but may replace similar ordinary words."),
                selectedValue: draft.asrHotwordsStrength.rawValue,
                options: AsrHotwordsStrength.allCases.map { strength in
                    switch strength {
                    case .normal: return (t("Обычно", "Normal"), strength.rawValue)
                    case .strong: return (t("Сильнее", "Strong"), strength.rawValue)
                    }
                },
                action: #selector(selectAsrHotwordsStrength(_:))
            ))
        }

        let vocabCard = settingsCard(
            title: t("Словарь и обучение", "Vocabulary & Learning"),
            symbol: "book.closed",
            rows: vocabRows
        )

        let historyCard = settingsCard(
            title: t("История в строке меню", "Menu Bar History"),
            symbol: "clock.arrow.circlepath",
            rows: [
                popupRow(
                    title: t("Недавние диктовки", "Recent transcripts"),
                    detail: t("Сколько последних транскрипций показывать в меню строки состояния.",
                              "How many recent transcripts to display in the menu bar dropdown."),
                    selectedValue: draft.recentTranscriptLimit.rawValue,
                    options: RecentTranscriptLimit.allCases.map { limit in
                        switch limit {
                        case .off: return (t("Выкл", "Off"), limit.rawValue)
                        case .last1: return (t("Последняя 1", "Last 1"), limit.rawValue)
                        case .last5: return (t("Последние 5", "Last 5"), limit.rawValue)
                        case .last10: return (t("Последние 10", "Last 10"), limit.rawValue)
                        }
                    },
                    action: #selector(selectRecentTranscriptLimitDraft(_:))
                ),
            ]
        )

        stack.addArrangedSubview(formattingCard)
        stack.addArrangedSubview(vocabCard)
        stack.addArrangedSubview(historyCard)

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    private func vocabularyOpenRow(vocabCount: Int, hotwordsCount: Int) -> NSView {
        let audit = VocabularyHygiene.extendedAudit(for: settings.vocabularyStore.all())
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(t("Исправления и ASR-термины", "Corrections & ASR terms"),
                                           size: 13, weight: .semibold))
        let countSummary = t("Записей в словаре: \(vocabCount) · ASR-терминов: \(hotwordsCount)",
                             "Vocabulary entries: \(vocabCount) · ASR hotwords: \(hotwordsCount)")
        let extraSummary: String
        if audit.definiteCount > 0 {
            extraSummary = t(" · найдено ошибок: \(audit.definiteCount)", " · issues found: \(audit.definiteCount)")
        } else if audit.reviewCount > 0 {
            extraSummary = t(" · на проверку: \(audit.reviewCount)", " · to review: \(audit.reviewCount)")
        } else {
            extraSummary = ""
        }
        text.addArrangedSubview(panelLabel(
            countSummary + extraSummary,
            size: 11.5,
            color: audit.definiteCount > 0 ? .systemOrange : .secondaryLabelColor
        ))

        let cleanupTitle = audit.items.isEmpty
            ? t("Очистить словарь…", "Clean Up…")
            : t("Очистить словарь (\(audit.items.count))…", "Clean Up (\(audit.items.count))…")
        let cleanupBtn = panelButton(
            cleanupTitle,
            action: #selector(cleanVocabularyClicked),
            toolTip: t("Проверить словарь на мусорные, ошибочные и подозрительные сохранения с выбором перед удалением.",
                       "Scan the vocabulary for junk, broken, or suspicious entries with a review checklist before deleting.")
        )

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(cleanupBtn)
        row.addArrangedSubview(panelButton(
            t("Открыть словарь…", "Open Vocabulary…"),
            action: #selector(openVocabularyManager),
            toolTip: t("Открыть окно управления словарём (добавить, изменить, удалить, импорт/экспорт).",
                       "Open the vocabulary manager (add, edit, delete, import/export).")
        ))
        return row
    }

    private func fillerWordsBlock(_ draft: ControlPanelSettingsDraft) -> NSView {
        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .leading
        container.spacing = 8

        let activeCount = draft.enabledFillerPresetKeys.count
            + draft.customFillerWords.filter { !draft.disabledCustomFillerWords.contains($0) }.count

        let header = toggleRow(
            title: t("Удалять слова-паразиты", "Remove filler words"),
            detail: t("Убирает слова-хезитации и разговорные паразиты (активно: \(activeCount)).",
                      "Removes hesitation sounds and verbal tics (active: \(activeCount))."),
            isOn: draft.removeFillerWords,
            action: #selector(toggleRemoveFillerWordsSetting(_:)),
            trailingAction: draft.removeFillerWords ? disclosureToggleButton(
                title: fillerListExpanded ? t("Скрыть список", "Hide list") : t("Список слов", "Word list"),
                expanded: fillerListExpanded,
                action: #selector(toggleFillerListDisclosure(_:))
            ) : nil
        )
        container.addArrangedSubview(header)
        header.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true

        if draft.removeFillerWords && fillerListExpanded {
            let fillerColumnCount = 4
            var columnStacks: [NSStackView] = []
            for _ in 0..<fillerColumnCount {
                let column = NSStackView()
                column.orientation = .vertical
                column.alignment = .leading
                column.spacing = 4
                columnStacks.append(column)
            }

            func addCell(_ cell: NSView, at index: Int) {
                let column = columnStacks[index % fillerColumnCount]
                column.addArrangedSubview(cell)
                cell.widthAnchor.constraint(equalTo: column.widthAnchor).isActive = true
            }

            var cellIndex = 0
            for preset in FillerWordRemover.presets {
                let box = NSButton(checkboxWithTitle: preset.displayText, target: self, action: #selector(toggleFillerPreset(_:)))
                box.state = draft.enabledFillerPresetKeys.contains(preset.key) ? .on : .off
                box.identifier = NSUserInterfaceItemIdentifier(preset.key)
                box.lineBreakMode = .byTruncatingTail
                box.toolTip = preset.displayText
                addCell(box, at: cellIndex)
                cellIndex += 1
            }
            for word in draft.customFillerWords {
                let cell = NSStackView()
                cell.orientation = .horizontal
                cell.alignment = .centerY
                cell.spacing = 4
                let box = NSButton(checkboxWithTitle: word, target: self, action: #selector(toggleCustomFillerWord(_:)))
                box.state = draft.disabledCustomFillerWords.contains(word) ? .off : .on
                box.identifier = NSUserInterfaceItemIdentifier(word)
                box.lineBreakMode = .byTruncatingTail
                box.toolTip = word
                box.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
                cell.addArrangedSubview(box)
                cell.addArrangedSubview(NSView())
                let remove = NSButton(title: "×", target: self, action: #selector(removeCustomFillerWord(_:)))
                remove.identifier = NSUserInterfaceItemIdentifier(word)
                remove.bezelStyle = .inline
                remove.toolTip = t("Убрать слово из списка", "Remove this word from the list")
                remove.setContentHuggingPriority(.required, for: .horizontal)
                cell.addArrangedSubview(remove)
                addCell(cell, at: cellIndex)
                cellIndex += 1
            }

            let columnsRow = NSStackView(views: columnStacks)
            columnsRow.orientation = .horizontal
            columnsRow.alignment = .top
            columnsRow.spacing = 10
            columnsRow.distribution = .fillEqually
            columnsRow.translatesAutoresizingMaskIntoConstraints = false

            let scroll = NSScrollView()
            scroll.documentView = columnsRow
            scroll.hasVerticalScroller = true
            scroll.drawsBackground = false
            scroll.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([
                columnsRow.leadingAnchor.constraint(equalTo: scroll.contentView.leadingAnchor),
                columnsRow.trailingAnchor.constraint(equalTo: scroll.contentView.trailingAnchor),
                columnsRow.topAnchor.constraint(equalTo: scroll.contentView.topAnchor),
                scroll.heightAnchor.constraint(equalToConstant: 165),
            ])
            container.addArrangedSubview(scroll)

            let customField = NSTextField()
            customField.placeholderString = t("Добавить своё слово или фразу и нажать Enter",
                                              "Add a custom word or phrase and press Enter")
            customField.target = self
            customField.action = #selector(addCustomFillerWord(_:))
            container.addArrangedSubview(customField)

            NSLayoutConstraint.activate([
                scroll.widthAnchor.constraint(equalTo: container.widthAnchor),
                customField.widthAnchor.constraint(equalTo: container.widthAnchor),
            ])
        }

        return container
    }

    // MARK: - Tab 5: Audio

    func buildAudioSection(draft: ControlPanelSettingsDraft) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        stack.addArrangedSubview(sectionHeader(
            title: t("Аудио", "Audio"),
            subtitle: t("Микрофон, автоостановка при тишине и звуковые сигналы.",
                        "Microphone input, silence auto-stop, and audio feedback.")
        ))

        var inputRows: [NSView] = [
            microphoneSettingsRow(draft),
            toggleRow(
                title: t("Останавливать запись при тишине", "Stop automatically after silence"),
                detail: t("Диктовка завершится сама после указанной паузы.",
                          "Dictation ends automatically after the configured silence duration."),
                isOn: draft.autoStopOnSilenceEnabled,
                action: #selector(toggleAutoStopOnSilence(_:))
            ),
        ]
        if draft.autoStopOnSilenceEnabled {
            inputRows.append(popupRow(
                title: t("Длительность тишины", "Silence duration"),
                detail: t("Сколько секунд тишины ждать перед остановкой.",
                          "Seconds of silence to wait before stopping."),
                selectedValue: String(draft.autoStopSilenceSeconds),
                options: silenceDurationOptions,
                action: #selector(selectAutoStopSilenceSeconds(_:))
            ))
        }

        let inputCard = settingsCard(
            title: t("Микрофон и запись", "Input & Recording"),
            symbol: "mic",
            rows: inputRows
        )

        let soundCard = settingsCard(
            title: t("Звуки", "Sound"),
            symbol: "speaker.wave.2",
            rows: [
                toggleRow(
                    title: t("Заглушать системный звук во время записи", "Mute system audio while recording"),
                    detail: t("Временно приглушает воспроизведение, пока микрофон слушает.",
                              "Temporarily mutes playback while the microphone is listening."),
                    isOn: draft.muteWhileRecording,
                    action: #selector(toggleMuteWhileRecordingSetting(_:))
                ),
                toggleRow(
                    title: t("Звуки обратной связи", "Play feedback sounds"),
                    detail: t("Короткие сигналы при старте, завершении и переключении режимов.",
                              "Subtle cues on start, completion, and mode toggles."),
                    isOn: draft.playFeedbackSounds,
                    action: #selector(togglePlayFeedbackSoundsSetting(_:))
                ),
            ]
        )

        stack.addArrangedSubview(inputCard)
        stack.addArrangedSubview(soundCard)

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    private func microphoneSettingsRow(_ draft: ControlPanelSettingsDraft) -> NSView {
        let devices = availableAudioInputDevices()
        let preference = draft.inputDevicePreference.trimmingCharacters(in: .whitespacesAndNewlines)
        let selectedDevice = audioInputDevice(matching: preference, in: devices)
        let unavailable = !preference.isEmpty && selectedDevice == nil

        let detailText: String
        if unavailable {
            detailText = t("Устройство недоступно — временно используется системный микрофон.",
                           "Device unavailable; falling back to system microphone temporarily.")
        } else if let selectedDevice {
            detailText = t("Выбран: \(selectedDevice.name).", "Selected: \(selectedDevice.name).")
        } else {
            detailText = t("Следовать выбору входа в настройках macOS.",
                           "Follow the input selected in macOS settings.")
        }

        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 12

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(t("Микрофон", "Microphone"), size: 13, weight: .semibold))
        let detail = panelLabel(detailText, size: 11.5, color: .secondaryLabelColor)
        detail.preferredMaxLayoutWidth = 310
        text.addArrangedSubview(detail)

        let popup = NSPopUpButton()
        popup.target = self
        popup.action = #selector(selectInputDeviceDraft(_:))
        popup.addItem(withTitle: t("Системный по умолчанию", "System default"))
        popup.lastItem?.representedObject = ""
        if unavailable {
            popup.addItem(withTitle: t("Недоступен: \(preference)", "Unavailable: \(preference)"))
            popup.lastItem?.representedObject = preference
            popup.lastItem?.isEnabled = false
        }
        if !devices.isEmpty {
            popup.menu?.addItem(.separator())
        }
        for device in devices {
            popup.addItem(withTitle: device.name)
            popup.lastItem?.representedObject = device.uid
            popup.lastItem?.toolTip = device.uid
        }
        let selectedValue = selectedDevice?.uid ?? (unavailable ? preference : "")
        if let item = popup.itemArray.first(where: { ($0.representedObject as? String) == selectedValue }) {
            popup.select(item)
        }
        popup.setContentHuggingPriority(.required, for: .horizontal)

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(popup)
        return row
    }

    // MARK: - Tab 6: Appearance (Indicator)

    func buildAppearanceSection(draft: ControlPanelSettingsDraft) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        stack.addArrangedSubview(sectionHeader(
            title: t("Индикатор", "Indicator"),
            subtitle: t("Внешний вид плавающей капсулы записи, транскрибации и AI-обработки. Все изменения применяются сразу.",
                        "Appearance of the floating recording, transcribing, and AI-processing capsule. Changes apply immediately.")
        ))

        let enabled = draft.showRecordingWaveform

        let capsuleCard = settingsCard(
            title: t("Плавающая капсула", "Floating Capsule"),
            symbol: "capsule",
            rows: [
                toggleRow(
                    title: t("Показывать плавающий индикатор", "Show floating recording indicator"),
                    detail: t("Капсула с волной и статусом рядом с активным полем ввода.",
                              "Floating capsule with audio wave and status near the text field."),
                    isOn: draft.showRecordingWaveform,
                    action: #selector(toggleShowRecordingWaveformSetting(_:))
                ),
                popupRow(
                    title: t("Размер капсулы", "Capsule size"),
                    selectedValue: draft.hudSize.rawValue,
                    options: RecordingHUDSize.allCases.map { (localizedHUDSizeName($0), $0.rawValue) },
                    action: #selector(selectRecordingHUDSize(_:)),
                    enabled: enabled
                ),
                popupRow(
                    title: t("Вид во время записи", "Recording display"),
                    detail: t("Полоски уровня громкости или таймер длительности после 10 секунд.",
                              "Volume level bars or elapsed-time timer after 10 seconds."),
                    selectedValue: draft.hudDisplayMode.rawValue,
                    options: RecordingHUDDisplayMode.allCases.map { (localizedDisplayModeName($0), $0.rawValue) },
                    action: #selector(selectRecordingHUDDisplayMode(_:)),
                    enabled: enabled
                ),
                popupRow(
                    title: t("Фон капсулы", "Capsule background"),
                    selectedValue: draft.backgroundStyle.rawValue,
                    options: RecordingHUDBackgroundStyle.allCases.map { (localizedBackgroundName($0), $0.rawValue) },
                    action: #selector(selectRecordingHUDBackgroundStyle(_:)),
                    enabled: enabled
                ),
            ]
        )

        let colorsCard = settingsCard(
            title: t("Цвета состояний", "State Colors"),
            symbol: "paintpalette",
            rows: [
                popupRow(
                    title: t("Цвет записи", "Recording color"),
                    detail: t("Цвет аудиоволн, пока микрофон слушает.", "Color while the microphone is listening."),
                    selectedValue: draft.recordingColor.rawValue,
                    options: RecordingHUDAccentColor.allCases.map { (localizedColorName($0), $0.rawValue) },
                    action: #selector(selectRecordingHUDRecordingColor(_:)),
                    enabled: enabled
                ),
                popupRow(
                    title: t("Цвет транскрибации", "Transcribing color"),
                    detail: t("Цвет анимации во время распознавания речи.", "Color while speech is transcribed."),
                    selectedValue: draft.transcribingColor.rawValue,
                    options: RecordingHUDAccentColor.allCases.map { (localizedColorName($0), $0.rawValue) },
                    action: #selector(selectRecordingHUDTranscribingColor(_:)),
                    enabled: enabled
                ),
                popupRow(
                    title: t("Цвет AI-улучшения", "AI polish color"),
                    detail: t("Конечный цвет градиента волны при коррекции и рерайте.",
                              "Gradient end color during AI correction and rewrite."),
                    selectedValue: draft.correctingColor.rawValue,
                    options: RecordingHUDAccentColor.allCases.map { (localizedColorName($0), $0.rawValue) },
                    action: #selector(selectRecordingHUDCorrectingColor(_:)),
                    enabled: enabled
                ),
            ]
        )

        stack.addArrangedSubview(capsuleCard)
        stack.addArrangedSubview(colorsCard)

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    // MARK: - Tab 7: System

    func buildSystemSection(draft: ControlPanelSettingsDraft) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        stack.addArrangedSubview(sectionHeader(
            title: t("Система", "System"),
            subtitle: t("Автозапуск, обновления, разрешения macOS и диагностика.",
                        "Launch at login, updates, macOS permissions, and diagnostics.")
        ))

        let startupAndUpdatesCard = settingsCard(
            title: t("Запуск и обновления", "Startup & Updates"),
            symbol: "arrow.triangle.2.circlepath",
            rows: [
                launchAtLoginRow(),
                toggleRow(
                    title: t("Автоматически проверять обновления", "Automatically check for updates"),
                    detail: t("Периодически проверять GitHub Releases и уведомлять в меню.",
                              "Periodically check GitHub Releases and notify in the menu."),
                    isOn: draft.checkForUpdates,
                    action: #selector(toggleCheckForUpdatesSetting(_:))
                ),
                systemUpdateStatusRow(),
            ]
        )

        let permissionsCard = systemPermissionsCard()
        let hardwareCard = systemHardwareCard()

        let maintenanceCard = settingsCard(
            title: t("Диагностика и обслуживание", "Diagnostics & Maintenance"),
            symbol: "wrench.and.screwdriver",
            rows: [
                maintenanceRow(),
            ]
        )

        stack.addArrangedSubview(startupAndUpdatesCard)
        stack.addArrangedSubview(hardwareCard)
        stack.addArrangedSubview(permissionsCard)
        stack.addArrangedSubview(maintenanceCard)
        stack.addArrangedSubview(privacyInfoView())

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    private func launchAtLoginRow() -> NSView {
        let status = SMAppService.mainApp.status
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(t("Запускать при входе в систему", "Launch at Login"),
                                           size: 13, weight: .semibold))
        text.addArrangedSubview(panelLabel(
            status == .requiresApproval
                ? t("Требует подтверждения в Системных настройках → Элементы входа.",
                    "Requires approval in System Settings → Login Items.")
                : t("Автоматически запускать фоновую службу при входе в macOS.",
                    "Start the background service automatically when you log in."),
            size: 11.5,
            color: status == .requiresApproval ? .systemOrange : .secondaryLabelColor
        ))

        let toggle = NSSwitch()
        toggle.target = self
        toggle.action = #selector(toggleLaunchAtLoginSetting(_:))
        switch status {
        case .enabled: toggle.state = .on
        case .requiresApproval: toggle.state = .mixed
        default: toggle.state = .off
        }
        toggle.setContentHuggingPriority(.required, for: .horizontal)

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(toggle)
        return row
    }

    private func systemUpdateStatusRow() -> NSView {
        let presentation = compactUpdatePresentation()
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10

        row.addArrangedSubview(panelSymbol(presentation.symbol,
                                           color: presentation.color,
                                           description: nil,
                                           pointSize: 16))
        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(presentation.title, size: 13, weight: .semibold))
        let detail = panelLabel(presentation.detail, size: 11.5, color: .secondaryLabelColor)
        detail.preferredMaxLayoutWidth = 330
        text.addArrangedSubview(detail)

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        if let buttonTitle = presentation.buttonTitle, let action = presentation.action {
            let button = panelButton(buttonTitle,
                                     action: action,
                                     enabled: presentation.buttonEnabled,
                                     toolTip: presentation.buttonToolTip)
            row.addArrangedSubview(button)
        }
        return row
    }

    private func systemPermissionsCard() -> NSView {
        let missingCount = Permission.allCases.filter { !Permissions.isGranted($0) }.count
        var rows: [NSView] = []

        for (index, permission) in Permission.allCases.enumerated() {
            let granted = Permissions.isGranted(permission)
            let row = NSStackView()
            row.orientation = .horizontal
            row.alignment = .centerY
            row.spacing = 10

            row.addArrangedSubview(panelSymbol(
                granted ? "checkmark.circle.fill" : "exclamationmark.triangle.fill",
                color: granted ? .systemGreen : .systemOrange,
                description: nil,
                pointSize: 14
            ))

            let text = NSStackView()
            text.orientation = .vertical
            text.alignment = .leading
            text.spacing = 1
            text.addArrangedSubview(panelLabel(permissionTitle(permission), size: 12.5, weight: .semibold))
            text.addArrangedSubview(panelLabel(permissionDetail(permission), size: 11, color: .secondaryLabelColor))

            row.addArrangedSubview(text)
            row.addArrangedSubview(NSView())

            if granted {
                row.addArrangedSubview(panelLabel(t("Выдано", "Granted"),
                                                  size: 11.5, weight: .medium, color: .systemGreen))
            } else {
                let title = (permissionClickCount[permission] ?? 0) >= 1
                    ? t("Открыть настройки", "Open Settings")
                    : t("Разрешить", "Grant")
                let btn = panelButton(title,
                                      action: #selector(grantPermissionClicked(_:)),
                                      enabled: serviceOperation == nil)
                btn.controlSize = .small
                btn.tag = index
                row.addArrangedSubview(btn)
            }
            rows.append(row)
        }

        let resetBtn = panelButton(
            t("Сбросить разрешения", "Reset Permissions"),
            action: #selector(resetPermissionsClicked(_:)),
            enabled: serviceOperation == nil,
            toolTip: t("Отозвать все разрешения macOS у Lexomorph и запросить их заново.",
                       "Revoke all macOS permissions from Lexomorph and prompt again.")
        )
        resetBtn.controlSize = .small

        return settingsCard(
            title: missingCount == 0
                ? t("Разрешения macOS · все выданы", "macOS Permissions · all granted")
                : t("Разрешения macOS · не хватает: \(missingCount)", "macOS Permissions · missing: \(missingCount)"),
            symbol: missingCount == 0 ? "checkmark.shield.fill" : "exclamationmark.shield.fill",
            symbolColor: missingCount == 0 ? .systemGreen : .systemOrange,
            accessory: resetBtn,
            rows: rows
        )
    }

    private func systemHardwareCard() -> NSView {
        let hw = HardwareCapabilities.shared.current()
        let gpuStatus = hw.vulkanGPUStatus(language: language)
        let localLLMStatus = hw.localLLMStatus(language: language)
        let punctStatus = hw.punctuationStatus(language: language)

        func hwRow(title: String, detail: String, ok: Bool, badgeText: String) -> NSView {
            let row = NSStackView()
            row.orientation = .horizontal
            row.alignment = .centerY
            row.spacing = 10

            let text = NSStackView()
            text.orientation = .vertical
            text.alignment = .leading
            text.spacing = 1
            text.addArrangedSubview(panelLabel(title, size: 12.5, weight: .semibold))
            let sub = panelLabel(detail, size: 11, color: .secondaryLabelColor)
            sub.preferredMaxLayoutWidth = 340
            text.addArrangedSubview(sub)

            row.addArrangedSubview(text)
            row.addArrangedSubview(NSView())
            row.addArrangedSubview(chipBadge(
                text: badgeText,
                symbol: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill",
                color: ok ? .systemGreen : .systemOrange
            ))
            return row
        }

        var rows: [NSView] = [
            hwRow(
                title: t("Процессор и память", "CPU & Memory"),
                detail: "\(hw.cpuModel) · \(hw.cpuCores) \(t("ядер", "cores")) · \(hw.physicalMemoryGB) \(t("ГБ ОЗУ", "GB RAM"))",
                ok: true,
                badgeText: hw.architecture
            ),
            hwRow(
                title: t("Ускорение LLM на GPU (Vulkan)", "LLM GPU Acceleration (Vulkan)"),
                detail: gpuStatus.message,
                ok: gpuStatus.isAvailable,
                badgeText: gpuStatus.isAvailable ? t("Доступно", "Available") : t("Только CPU", "CPU only")
            ),
            hwRow(
                title: t("Локальные AI-модели и пунктуация", "Local AI Models & Punctuation"),
                detail: localLLMStatus.isAvailable
                    ? (hw.physicalMemoryGB >= 12
                        ? t("Доступны все локальные модели (включая 8B/9B для рерайта) и пунктуация.",
                            "All local models (including 8B/9B rewrite models) and punctuation are supported.")
                        : t("Доступны лёгкие модели коррекции и пунктуация; для крупных 8B/9B требуется ≥ 12 ГБ ОЗУ.",
                            "Light correction models and punctuation are supported; large 8B/9B models require ≥ 12 GB RAM."))
                    : localLLMStatus.message,
                ok: localLLMStatus.isAvailable && punctStatus.isAvailable,
                badgeText: localLLMStatus.isAvailable ? t("Совместимо", "Compatible") : t("Ограничено", "Limited")
            ),
        ]

        if !hw.vulkanGPUAvailable || !hw.localLLMAvailable {
            rows.append(compatibilityBanner(
                symbol: "info.circle.fill",
                color: .systemOrange,
                title: t("Часть локальных AI-функций ограничена оборудованием",
                         "Some local AI features are limited by hardware"),
                detail: t("Распознавание речи ONNX всегда работает локально на CPU. Для ускорения коррекции и рерайта на компьютерах без Vulkan GPU можно подключить внешний OpenAI-совместимый сервер в разделе «AI-обработка».",
                          "ONNX speech recognition always runs locally on CPU. On Macs without a Vulkan GPU, you can also use an external OpenAI-compatible server under 'AI Processing'.")
            ))
        }

        return settingsCard(
            title: t("Оборудование и совместимость", "Hardware & Compatibility"),
            symbol: "cpu",
            rows: rows
        )
    }

    private func maintenanceRow() -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(t("Журнал и кэш модели", "Log & model cache"),
                                           size: 13, weight: .semibold))
        text.addArrangedSubview(panelLabel(
            t("Локальный журнал работы или переустановка кэша речевой модели.",
              "Local diagnostic log or fresh speech model cache download."),
            size: 11.5,
            color: .secondaryLabelColor
        ))

        let openLogButton = panelButton(
            t("Открыть лог", "Open Log"),
            action: #selector(openDiagnosticLogClicked(_:)),
            toolTip: t("Открыть файл журнала Lexomorph.", "Open the Lexomorph log file.")
        )
        let resetCacheButton = panelButton(
            t("Сбросить кэш…", "Reset Cache…"),
            action: #selector(resetSpeechModelCacheFromSettingsClicked(_:)),
            enabled: serviceOperation == nil,
            toolTip: t("Удалить кэш речевой модели и скачать заново при перезапуске службы.",
                       "Delete the speech model cache and download a fresh copy on restart.")
        )

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(openLogButton)
        row.addArrangedSubview(resetCacheButton)
        return row
    }
}
