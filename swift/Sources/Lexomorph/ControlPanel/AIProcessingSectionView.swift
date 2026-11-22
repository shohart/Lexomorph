// Lexomorph — Tab 4: AI Processing ("AI-обработка") with 4 focused
// subsections (Correction | Rewrite | Punctuation | Shortcuts & GPU),
// collapsible prompt editors, and custom rewrite style editor window.

import AppKit
import Foundation

extension LexomorphControlPanelApp {

    func buildAIProcessingSection(draft: ControlPanelSettingsDraft) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        stack.addArrangedSubview(sectionHeader(
            title: t("AI-обработка", "AI Processing"),
            subtitle: t("Настройка моделей коррекции, рерайта, пунктуации, промптов и ускорения GPU.",
                        "Configure correction, rewrite, punctuation models, system prompts, and GPU acceleration.")
        ))

        let subSelector = NSSegmentedControl(
            labels: AISubsection.allCases.map { localizedAISubsectionTitle($0) },
            trackingMode: .selectOne,
            target: self,
            action: #selector(selectAISubsection(_:))
        )
        subSelector.selectedSegment = selectedAISubsection.rawValue
        subSelector.segmentStyle = .texturedRounded
        subSelector.controlSize = .regular
        stack.addArrangedSubview(subSelector)

        switch selectedAISubsection {
        case .correction:
            stack.addArrangedSubview(buildAICorrectionSubsection(draft: draft))
        case .rewrite:
            stack.addArrangedSubview(buildAIRewriteSubsection(draft: draft))
        case .punctuation:
            stack.addArrangedSubview(buildAIPunctuationSubsection(draft: draft))
        case .shortcutsAndHardware:
            stack.addArrangedSubview(buildAIShortcutsAndHardwareSubsection(draft: draft))
        }

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    // MARK: - Subsection 1: Correction

    private func buildAICorrectionSubsection(draft: ControlPanelSettingsDraft) -> NSView {
        let isOn = draft.textPostprocessingMode == .correction
        var rows: [NSView] = [
            toggleRow(
                title: t("Исправлять ошибки распознавания", "Correct recognition errors"),
                detail: t("Орфография, пунктуация, регистр и написание иностранных терминов без изменения стиля.",
                          "Spelling, punctuation, casing, and foreign terms without changing style."),
                isOn: isOn,
                action: #selector(toggleLLMCorrectionMode(_:))
            ),
        ]

        if isOn {
            let hw = HardwareCapabilities.shared.current()
            let localStatus = hw.localLLMStatus(language: language)
            let modelCompat = hw.modelCompatibility(for: draft.correctionModel, language: language)

            rows.append(popupRow(
                title: t("Модель коррекции", "Correction model"),
                detail: t("VoiceScribe — мгновенная (0,19 с), Qwen3.5-4B — точнейшая из малых. Подробности — «?».",
                          "VoiceScribe — instant (0.19 s), Qwen3.5-4B — most accurate small model. Details — '?'."),
                selectedValue: draft.correctionModel.rawValue,
                options: BundledLLMModel.correctionModels.map { model in
                    let minRAM = HardwareProfile.minimumRAMGB(for: model)
                    let baseName = model == .voiceScribe
                        ? t("\(model.displayName) — рекомендуется", "\(model.displayName) — recommended")
                        : model.displayName
                    if hw.physicalMemoryGB < minRAM {
                        return ("\(baseName) (\(t("нужно ≥ \(minRAM) ГБ ОЗУ", "needs ≥ \(minRAM) GB RAM")))", model.rawValue)
                    }
                    return (baseName, model.rawValue)
                },
                action: #selector(selectCorrectionBundledModel(_:)),
                showsHelp: true
            ))

            rows.append(popupRow(
                title: t("Движок", "Engine"),
                detail: t("Встроенная модель работает локально. Свой сервер — любой OpenAI-совместимый эндпоинт.",
                          "Built-in runs locally. Custom server is any OpenAI-compatible endpoint."),
                selectedValue: draft.llmEngineBackend.rawValue,
                options: [
                    (localStatus.isAvailable
                        ? t("Встроенная (локально)", "Built-in (local)")
                        : t("Встроенная (недоступно на этом Mac)", "Built-in (unavailable on this Mac)"),
                     LLMEngineBackend.bundledLocal.rawValue),
                    (t("Свой сервер", "Custom server"), LLMEngineBackend.customEndpoint.rawValue),
                ],
                action: #selector(selectLLMEngineBackend(_:))
            ))

            switch draft.llmEngineBackend {
            case .bundledLocal:
                if case .unsupported(let reason) = modelCompat {
                    rows.append(compatibilityBanner(
                        symbol: "exclamationmark.triangle.fill",
                        color: .systemOrange,
                        title: t("Оборудование не соответствует требованиям модели",
                                 "Hardware does not meet model requirements"),
                        detail: reason
                    ))
                } else if case .cpuOnlyWarning(let reason) = modelCompat {
                    rows.append(compatibilityBanner(
                        symbol: "info.circle.fill",
                        color: .systemBlue,
                        title: t("Работа без ускорения GPU (на CPU)", "Running without GPU acceleration (CPU)"),
                        detail: reason
                    ))
                }
                rows.append(llmBundledModelStatusRow(model: draft.correctionModel, supported: modelCompat.isSupported))
            case .customEndpoint:
                rows.append(llmCustomEndpointRows(draft))
            }

            rows.append(correctionPromptRow(draft))
        }

        return settingsCard(
            title: t("Коррекция текста (GEC)", "Text Correction (GEC)"),
            symbol: "text.badge.checkmark",
            rows: rows
        )
    }

    // MARK: - Subsection 2: Rewrite

    private func buildAIRewriteSubsection(draft: ControlPanelSettingsDraft) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        let isOn = draft.rewriteEnabled
        var mainRows: [NSView] = [
            toggleRow(
                title: t("Рерайт текста", "Text rewriting"),
                detail: t("Переписывает текст в выбранном стиле. Независим от коррекции и может работать вместе с ней.",
                          "Rewrites text in the chosen style. Independent from correction and can run after it."),
                isOn: isOn,
                action: #selector(toggleRewriteMode(_:))
            ),
        ]

        if isOn {
            let hw = HardwareCapabilities.shared.current()
            let localStatus = hw.localLLMStatus(language: language)
            let modelCompat = hw.modelCompatibility(for: draft.rewriteBundledModel, language: language)

            mainRows.append(popupRow(
                title: t("Активный стиль рерайта", "Active rewrite style"),
                detail: t("Встроенные и пользовательские режимы переработки текста.",
                          "Built-in and custom text rewriting styles."),
                selectedValue: draft.rewriteStyleID,
                options: RewriteStyle.allCases.map { (localizedRewriteStyleLongName($0), $0.rawValue) }
                    + draft.customRewriteStyles.map { ($0.name, $0.id) },
                action: #selector(selectRewriteStyle(_:))
            ))

            mainRows.append(popupRow(
                title: t("Модель рерайта", "Rewrite model"),
                detail: t("YandexGPT 5 Lite — лучший по замерам сохранения фактов. Подробности — «?».",
                          "YandexGPT 5 Lite — benchmark winner for fact preservation. Details — '?'."),
                selectedValue: draft.rewriteBundledModel.rawValue,
                options: BundledLLMModel.rewriteModels.map { model in
                    let minRAM = HardwareProfile.minimumRAMGB(for: model)
                    let suffix: String
                    if model == .yandexGPT {
                        suffix = t(" — рекомендуется", " — recommended")
                    } else if model == .lfm25 {
                        suffix = t(" — экспериментальная", " — experimental")
                    } else {
                        suffix = ""
                    }
                    let base = "\(model.displayName)\(suffix)"
                    if hw.physicalMemoryGB < minRAM {
                        return ("\(base) (\(t("нужно ≥ \(minRAM) ГБ ОЗУ", "needs ≥ \(minRAM) GB RAM")))", model.rawValue)
                    }
                    return (base, model.rawValue)
                },
                action: #selector(selectRewriteBundledModel(_:)),
                showsHelp: true
            ))

            mainRows.append(popupRow(
                title: t("Движок рерайта", "Rewrite engine"),
                detail: t("Независим от коррекции: локальная модель или свой OpenAI-совместимый сервер.",
                          "Independent from correction: local model or custom OpenAI-compatible server."),
                selectedValue: draft.rewriteEngineBackend.rawValue,
                options: [
                    (localStatus.isAvailable
                        ? t("Встроенная (локально)", "Built-in (local)")
                        : t("Встроенная (недоступно на этом Mac)", "Built-in (unavailable on this Mac)"),
                     LLMEngineBackend.bundledLocal.rawValue),
                    (t("Свой сервер", "Custom server"), LLMEngineBackend.customEndpoint.rawValue),
                ],
                action: #selector(selectRewriteEngineBackend(_:))
            ))

            switch draft.rewriteEngineBackend {
            case .bundledLocal:
                if case .unsupported(let reason) = modelCompat {
                    mainRows.append(compatibilityBanner(
                        symbol: "exclamationmark.triangle.fill",
                        color: .systemOrange,
                        title: t("Оборудование не соответствует требованиям модели",
                                 "Hardware does not meet model requirements"),
                        detail: reason
                    ))
                } else if case .cpuOnlyWarning(let reason) = modelCompat {
                    mainRows.append(compatibilityBanner(
                        symbol: "info.circle.fill",
                        color: .systemBlue,
                        title: t("Работа без ускорения GPU (на CPU)", "Running without GPU acceleration (CPU)"),
                        detail: reason
                    ))
                }
                mainRows.append(llmBundledModelStatusRow(model: draft.rewriteBundledModel, supported: modelCompat.isSupported))
            case .customEndpoint:
                mainRows.append(rewriteCustomEndpointRows(draft))
            }

            mainRows.append(rewritePromptRow(draft))
        }

        stack.addArrangedSubview(settingsCard(
            title: t("Рерайт текста", "Text Rewriting"),
            symbol: "wand.and.stars",
            rows: mainRows
        ))

        // Custom modes card is ALWAYS accessible even while rewrite is off
        let addBtn = panelButton(
            t("＋ Новый режим", "＋ New mode"),
            action: #selector(addCustomRewriteStyleClicked(_:)),
            toolTip: t("Создать свой режим рерайта: имя, цвет, инструкция, хоткей.",
                       "Create a custom rewrite mode: name, color, instruction, hotkey.")
        )
        addBtn.controlSize = .small
        stack.addArrangedSubview(settingsCard(
            title: t("Свои режимы рерайта", "Custom Rewrite Modes"),
            symbol: "swatchpalette",
            accessory: addBtn,
            rows: [customRewriteStylesBlock(draft)]
        ))

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    // MARK: - Subsection 3: Punctuation

    private func buildAIPunctuationSubsection(draft: ControlPanelSettingsDraft) -> NSView {
        let hw = HardwareCapabilities.shared.current()
        let punctStatus = hw.punctuationStatus(language: language)
        let toggleEnabled = punctStatus.isAvailable || draft.punctuationRestorationEnabled

        var rows: [NSView] = [
            toggleRow(
                title: t("Восстановление пунктуации", "Punctuation restoration"),
                detail: t("Последний этап после коррекции и рерайта: расставляет запятые, точки, «?», двоеточия и тире. Работает локально на CPU.",
                          "Final stage after correction and rewrite: places commas, periods, '?', colons, and dashes. Runs locally on CPU."),
                isOn: draft.punctuationRestorationEnabled,
                enabled: toggleEnabled,
                action: #selector(togglePunctuationRestoration(_:))
            ),
        ]

        if case .unavailable(let reason) = punctStatus {
            rows.append(compatibilityBanner(
                symbol: "exclamationmark.triangle.fill",
                color: .systemOrange,
                title: t("Недостаточно ресурсов для локальной пунктуации",
                         "Insufficient hardware for local punctuation"),
                detail: reason
            ))
        }

        if draft.punctuationRestorationEnabled {
            rows.append(popupRow(
                title: t("Модель пунктуации", "Punctuation model"),
                detail: t("Base точнее (~60 мс, 1,5 ГБ), Small быстрее (~25 мс, 0,7 ГБ).",
                          "Base is more accurate (~60 ms, 1.5 GB), Small is faster (~25 ms, 0.7 GB)."),
                selectedValue: draft.punctuationModel.rawValue,
                options: PunctuationModel.allCases.map { model in
                    (model.displayName + (model == .base ? t(" — рекомендуется", " — recommended") : ""), model.rawValue)
                },
                action: #selector(selectPunctuationModel(_:))
            ))
            rows.append(punctuationModelStatusRow(model: draft.punctuationModel))
        }

        return settingsCard(
            title: t("Восстановление пунктуации", "Punctuation Restoration"),
            symbol: "textformat.abc.dottedunderline",
            rows: rows
        )
    }

    // MARK: - Subsection 4: Shortcuts, GPU & Network

    private func buildAIShortcutsAndHardwareSubsection(draft: ControlPanelSettingsDraft) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        let hotkeysCard = settingsCard(
            title: t("Глобальные хоткеи режимов", "Global Mode Shortcuts"),
            symbol: "keyboard",
            rows: [
                hotkeyRow(
                    title: t("Переключить коррекцию", "Toggle correction"),
                    detail: t("Включить или выключить коррекцию без открытия окна.",
                              "Toggle correction on or off without opening this window."),
                    shortcut: draft.correctionHotkey,
                    kind: .correction,
                    toolTip: t("Сочетание для переключения коррекции.", "Shortcut to toggle correction.")
                ),
                hotkeyRow(
                    title: t("Переключить рерайт", "Toggle rewrite"),
                    detail: t("Включить или выключить рерайт без открытия окна.",
                              "Toggle rewrite on or off without opening this window."),
                    shortcut: draft.rewriteToggleHotkey,
                    kind: .rewriteToggle,
                    toolTip: t("Сочетание для переключения рерайта.", "Shortcut to toggle rewrite.")
                ),
                hotkeyRow(
                    title: t("Следующий стиль рерайта", "Cycle rewrite style"),
                    detail: t("Переключает режимы рерайта по кругу; если рерайт выключен — включает его.",
                              "Cycles rewrite styles; enables rewrite first if off."),
                    shortcut: draft.rewriteStyleHotkey,
                    kind: .rewriteStyle,
                    toolTip: t("Сочетание для переключения стиля рерайта.", "Shortcut to cycle rewrite style.")
                ),
            ]
        )

        let hw = HardwareCapabilities.shared.current()
        let gpuStatus = hw.vulkanGPUStatus(language: language)
        let vulkanAvailable = gpuStatus.isAvailable

        var hardwareRows: [NSView] = [
            toggleRow(
                title: t("LLM на GPU (Vulkan)", "LLM on GPU (Vulkan)"),
                detail: vulkanAvailable
                    ? t("Ускоряет локальные модели коррекции и рерайта на видеокарте (\(gpuStatus.message)). Распознавание речи всегда идёт на CPU.",
                        "Runs local correction and rewrite models on GPU (\(gpuStatus.message)). Speech recognition always uses CPU.")
                    : t("Недоступно на текущем оборудовании. Локальные модели работают на CPU.",
                        "Unavailable on this hardware. Local models run on CPU."),
                isOn: vulkanAvailable && draft.llmUseGPU,
                enabled: vulkanAvailable,
                action: #selector(toggleLLMUseGPUSetting(_:))
            ),
        ]

        if case .unavailable(let reason) = gpuStatus {
            hardwareRows.append(compatibilityBanner(
                symbol: "exclamationmark.triangle.fill",
                color: .systemOrange,
                title: t("GPU-ускорение Vulkan недоступно на этом Mac",
                         "Vulkan GPU acceleration is unavailable on this Mac"),
                detail: reason
            ))
        }

        hardwareRows.append(toggleRow(
            title: t("Использовать системный прокси", "Use system proxy"),
            detail: t("Для интернет-адресов пользовательских серверов. Локальные адреса (127.0.0.1, LAN, *.local) всегда идут напрямую.",
                      "For internet URLs of custom endpoints. Local addresses (127.0.0.1, LAN, *.local) always bypass proxy."),
            isOn: draft.llmUseSystemProxy,
            action: #selector(toggleLLMUseSystemProxy(_:))
        ))

        let hardwareCard = settingsCard(
            title: t("Оборудование и сеть", "Hardware & Network"),
            symbol: "cpu",
            rows: hardwareRows
        )

        stack.addArrangedSubview(hotkeysCard)
        stack.addArrangedSubview(hardwareCard)

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    // MARK: - Model Status, Custom Endpoints & Collapsible Prompt Editors

    private func llmBundledModelStatusRow(model: BundledLLMModel, supported: Bool = true) -> NSView {
        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .leading
        container.spacing = 8

        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 12

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(model.displayName, size: 12.5, weight: .semibold))

        let sizeLabel = formattedByteCount(UInt64(bundledLLMModelDownloadSize(model)))
        let modelReady = bundledLLMModelExists(model)
        let readyText = t("Готова (\(model.benchmarkSummary))", "Ready (\(model.benchmarkSummary))")
        let missingText = t("Не скачана (\(sizeLabel)) · \(model.benchmarkSummary)",
                            "Not downloaded (\(sizeLabel)) · \(model.benchmarkSummary)")

        let statusText: String
        let statusColor: NSColor
        let downloadInFlight = llmModelDownloadTask != nil && llmModelDownloadModel == model
        let liveProgress = downloadInFlight ? llmModelDownloadProgress : nil
        if downloadInFlight, case .downloading = llmModelDownloadState {
            if let liveProgress, liveProgress.total > 0 {
                let fraction = Double(liveProgress.received) / Double(liveProgress.total)
                statusText = t("Скачивание… \(Int(fraction * 100))% (\(formattedByteCount(UInt64(liveProgress.received))) из \(formattedByteCount(UInt64(liveProgress.total))))",
                               "Downloading… \(Int(fraction * 100))% (\(formattedByteCount(UInt64(liveProgress.received))) of \(formattedByteCount(UInt64(liveProgress.total))))")
            } else {
                statusText = t("Скачивание…", "Downloading…")
            }
            statusColor = .systemBlue
        } else if downloadInFlight, case .failed(let message) = llmModelDownloadState {
            statusText = message
            statusColor = .systemRed
        } else {
            statusText = modelReady ? readyText : missingText
            statusColor = modelReady ? .systemGreen : .secondaryLabelColor
        }
        let statusLabel = panelLabel(statusText, size: 11.5, color: statusColor)
        text.addArrangedSubview(statusLabel)
        if downloadInFlight {
            llmDownloadStatusLabel = statusLabel
        }

        let button: NSButton
        if downloadInFlight, case .downloading = llmModelDownloadState {
            button = panelButton(t("Отменить", "Cancel"), action: #selector(cancelLLMModelDownload(_:)))
        } else {
            button = panelButton(
                modelReady ? t("Скачать заново", "Re-download") : t("Скачать", "Download"),
                action: #selector(startBundledModelDownloadClicked(_:)),
                enabled: supported
            )
            button.tag = BundledLLMModel.allCases.firstIndex(of: model) ?? 0
        }
        button.controlSize = .small

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(button)
        container.addArrangedSubview(row)
        row.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true

        if downloadInFlight, case .downloading = llmModelDownloadState {
            let progressBar = NSProgressIndicator()
            progressBar.style = .bar
            progressBar.controlSize = .small
            if let liveProgress, liveProgress.total > 0 {
                progressBar.isIndeterminate = false
                progressBar.minValue = 0
                progressBar.maxValue = 1
                progressBar.doubleValue = Double(liveProgress.received) / Double(liveProgress.total)
            } else {
                progressBar.isIndeterminate = true
                progressBar.startAnimation(nil)
            }
            progressBar.translatesAutoresizingMaskIntoConstraints = false
            progressBar.heightAnchor.constraint(equalToConstant: 6).isActive = true
            container.addArrangedSubview(progressBar)
            progressBar.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true
            llmDownloadProgressBar = progressBar
        }

        return container
    }

    private func punctuationModelStatusRow(model: PunctuationModel) -> NSView {
        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .leading
        container.spacing = 8

        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 12

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel("Horizon Labs punctuation-restoration \(model.displayName)",
                                           size: 12.5, weight: .semibold))
        let inFlight = punctuationDownloadTask != nil && punctuationDownloadModel == model
        let ready = punctuationModelInstalled(model)
        let statusText: String
        let statusColor: NSColor
        if inFlight {
            statusText = t("Скачивание… \(Int((punctuationDownloadFraction ?? 0) * 100))%",
                           "Downloading… \(Int((punctuationDownloadFraction ?? 0) * 100))%")
            statusColor = .systemBlue
        } else if let error = punctuationDownloadError, punctuationDownloadModel == model {
            statusText = error
            statusColor = .systemRed
        } else if ready {
            statusText = t("Готова · Apache-2.0", "Ready · Apache-2.0")
            statusColor = .systemGreen
        } else {
            statusText = t("Не скачана (\(formattedByteCount(UInt64(model.downloadBytes)))). Пока модели нет, этот этап пропускается.",
                           "Not downloaded (\(formattedByteCount(UInt64(model.downloadBytes)))). Skipped until downloaded.")
            statusColor = .secondaryLabelColor
        }
        let statusLabel = panelLabel(statusText, size: 11.5, color: statusColor)
        statusLabel.preferredMaxLayoutWidth = 370
        text.addArrangedSubview(statusLabel)
        if inFlight { punctuationDownloadStatusLabel = statusLabel }

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        if inFlight {
            let btn = panelButton(t("Отменить", "Cancel"), action: #selector(cancelPunctuationModelDownload(_:)))
            btn.controlSize = .small
            row.addArrangedSubview(btn)
        } else if !ready {
            let btn = panelButton(t("Скачать", "Download"), action: #selector(startPunctuationModelDownload(_:)))
            btn.controlSize = .small
            row.addArrangedSubview(btn)
        }
        container.addArrangedSubview(row)
        row.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true

        if inFlight {
            let bar = NSProgressIndicator()
            bar.style = .bar
            bar.controlSize = .small
            bar.isIndeterminate = false
            bar.minValue = 0
            bar.maxValue = 1
            bar.doubleValue = punctuationDownloadFraction ?? 0
            bar.translatesAutoresizingMaskIntoConstraints = false
            bar.heightAnchor.constraint(equalToConstant: 6).isActive = true
            container.addArrangedSubview(bar)
            bar.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true
            punctuationDownloadProgressBar = bar
        }
        return container
    }

    private func endpointFieldRow(title: String, placeholder: String, value: String, tag: Int, secure: Bool) -> NSView {
        let row = NSStackView()
        row.orientation = .vertical
        row.alignment = .leading
        row.spacing = 3
        row.addArrangedSubview(panelLabel(title, size: 11.5, weight: .medium, color: .secondaryLabelColor))

        let field: NSTextField = secure ? NSSecureTextField() : NSTextField()
        field.placeholderString = placeholder
        field.stringValue = value
        field.tag = tag
        field.delegate = self
        field.translatesAutoresizingMaskIntoConstraints = false
        row.addArrangedSubview(field)
        field.widthAnchor.constraint(equalTo: row.widthAnchor).isActive = true
        return row
    }

    private func llmCustomEndpointRows(_ draft: ControlPanelSettingsDraft) -> NSView {
        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .leading
        container.spacing = 8
        container.addArrangedSubview(endpointFieldRow(
            title: t("Базовый URL (OpenAI-совместимый)", "Base URL (OpenAI-compatible)"),
            placeholder: "http://127.0.0.1:8080",
            value: draft.llmCustomBaseURL,
            tag: Self.llmCustomBaseURLFieldTag,
            secure: false
        ))
        container.addArrangedSubview(endpointFieldRow(
            title: t("API-ключ (необязательно)", "API key (optional)"),
            placeholder: "",
            value: draft.llmCustomAPIKey,
            tag: Self.llmCustomAPIKeyFieldTag,
            secure: true
        ))
        container.addArrangedSubview(endpointFieldRow(
            title: t("Имя модели", "Model name"),
            placeholder: "gpt-4o-mini",
            value: draft.llmCustomModelName,
            tag: Self.llmCustomModelNameFieldTag,
            secure: false
        ))
        for child in container.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true
        }
        return container
    }

    private func rewriteCustomEndpointRows(_ draft: ControlPanelSettingsDraft) -> NSView {
        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .leading
        container.spacing = 8
        container.addArrangedSubview(endpointFieldRow(
            title: t("Базовый URL рерайта (OpenAI-совместимый)", "Rewrite base URL (OpenAI-compatible)"),
            placeholder: "http://127.0.0.1:8080",
            value: draft.rewriteCustomBaseURL,
            tag: Self.rewriteCustomBaseURLFieldTag,
            secure: false
        ))
        container.addArrangedSubview(endpointFieldRow(
            title: t("API-ключ (необязательно)", "API key (optional)"),
            placeholder: "",
            value: draft.rewriteCustomAPIKey,
            tag: Self.rewriteCustomAPIKeyFieldTag,
            secure: true
        ))
        container.addArrangedSubview(endpointFieldRow(
            title: t("Имя модели рерайта", "Rewrite model name"),
            placeholder: "gpt-4o-mini",
            value: draft.rewriteCustomModelName,
            tag: Self.rewriteCustomModelNameFieldTag,
            secure: false
        ))
        for child in container.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true
        }
        return container
    }

    private func correctionPromptRow(_ draft: ControlPanelSettingsDraft) -> NSView {
        let model = draft.correctionModel
        let locked = !model.allowsCustomSystemPrompt
        let isDefault = draft.correctionSystemPrompt == defaultCorrectionSystemPrompt(for: model)

        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .leading
        container.spacing = 6

        let header = NSStackView()
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 8

        let title = t("Системный промпт коррекции", "Correction system prompt")
        if locked {
            header.addArrangedSubview(panelLabel(title, size: 12.5, weight: .semibold, color: .secondaryLabelColor))
            header.addArrangedSubview(NSView())
            header.addArrangedSubview(panelLabel(t("Обязательный для модели", "Locked by model"),
                                                 size: 11, color: .tertiaryLabelColor))
        } else {
            header.addArrangedSubview(disclosureToggleButton(
                title: isDefault ? title : "\(title) · \(t("изменён", "custom"))",
                expanded: correctionPromptExpanded,
                action: #selector(toggleCorrectionPromptDisclosure(_:))
            ))
            header.addArrangedSubview(NSView())
            if correctionPromptExpanded {
                let reset = panelButton(
                    t("Вернуть стандартный", "Reset to default"),
                    action: #selector(resetCorrectionPromptClicked(_:)),
                    enabled: !isDefault
                )
                reset.controlSize = .small
                header.addArrangedSubview(reset)
            }
        }
        container.addArrangedSubview(header)
        header.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true

        if !locked && correctionPromptExpanded {
            let field = promptEditorField(
                text: draft.correctionSystemPrompt,
                identifier: Self.correctionSystemPromptEditorID,
                editable: true
            )
            container.addArrangedSubview(field)
            field.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true

            let noteLabel = panelLabel(
                t("После правки нажмите «Сохранить» внизу окна.", "Click Save at the bottom after editing."),
                size: 11,
                color: .secondaryLabelColor
            )
            container.addArrangedSubview(noteLabel)
        }
        return container
    }

    private func rewritePromptRow(_ draft: ControlPanelSettingsDraft) -> NSView {
        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .leading
        container.spacing = 6

        let header = NSStackView()
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 8

        let title = t("Системные промпты рерайта", "Rewrite system prompts")
        header.addArrangedSubview(disclosureToggleButton(
            title: title,
            expanded: rewritePromptExpanded,
            action: #selector(toggleRewritePromptDisclosure(_:))
        ))
        header.addArrangedSubview(NSView())

        if rewritePromptExpanded {
            let styleSwitcher = NSPopUpButton()
            styleSwitcher.controlSize = .small
            let allEditorStyles: [(id: String, name: String)] =
                RewriteStyle.allCases.map { ($0.rawValue, localizedRewriteStyleShortName($0)) }
                + draft.customRewriteStyles.map { ($0.id, $0.name) }
            for styleEntry in allEditorStyles {
                styleSwitcher.addItem(withTitle: styleEntry.name)
                styleSwitcher.lastItem?.representedObject = styleEntry.id
            }
            let editorIndex = allEditorStyles.firstIndex(where: { $0.id == rewritePromptEditorStyleID }) ?? 0
            if editorIndex < styleSwitcher.numberOfItems {
                styleSwitcher.selectItem(at: editorIndex)
            }
            styleSwitcher.target = self
            styleSwitcher.action = #selector(selectRewritePromptStyle(_:))
            styleSwitcher.setContentHuggingPriority(.required, for: .horizontal)
            header.addArrangedSubview(styleSwitcher)

            let editingStyleID = rewritePromptEditorStyleID
            let currentText = draft.rewriteSystemPrompts[editingStyleID]
                ?? defaultRewriteSystemPrompt(forStyleID: editingStyleID, draft: draft)
            let isDefault = currentText == defaultRewriteSystemPrompt(forStyleID: editingStyleID, draft: draft)
            let reset = panelButton(
                t("Стандартный", "Reset"),
                action: #selector(resetRewritePromptClicked(_:)),
                enabled: !isDefault
            )
            reset.controlSize = .small
            header.addArrangedSubview(reset)
        }
        container.addArrangedSubview(header)
        header.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true

        if rewritePromptExpanded {
            let editingStyleID = rewritePromptEditorStyleID
            let currentText = draft.rewriteSystemPrompts[editingStyleID]
                ?? defaultRewriteSystemPrompt(forStyleID: editingStyleID, draft: draft)
            let field = promptEditorField(
                text: currentText,
                identifier: Self.rewriteSystemPromptEditorID,
                editable: true
            )
            container.addArrangedSubview(field)
            field.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true

            let noteLabel = panelLabel(
                t("Промпты встроенных и своих режимов синхронизируются с аккаунтом. После правки нажмите «Сохранить» внизу.",
                  "Built-in and custom style prompts sync with your account. Click Save at the bottom after editing."),
                size: 11,
                color: .secondaryLabelColor
            )
            noteLabel.preferredMaxLayoutWidth = 460
            container.addArrangedSubview(noteLabel)
        }
        return container
    }

    private func promptEditorField(text: String, identifier: NSUserInterfaceItemIdentifier, editable: Bool) -> NSScrollView {
        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.autohidesScrollers = true
        scrollView.borderType = .bezelBorder
        let textView = NSTextView()
        textView.isRichText = false
        textView.font = NSFont.systemFont(ofSize: 12)
        textView.textColor = .labelColor
        textView.isEditable = editable
        textView.isSelectable = true
        textView.delegate = editable ? self : nil
        textView.identifier = identifier
        textView.string = text
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.textContainer?.widthTracksTextView = true
        textView.autoresizingMask = [.width]
        scrollView.documentView = textView
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.heightAnchor.constraint(equalToConstant: 108).isActive = true
        return scrollView
    }

    // MARK: - Custom Rewrite Styles List & Editor Window

    private func customRewriteStylesBlock(_ draft: ControlPanelSettingsDraft) -> NSView {
        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .leading
        container.spacing = 8

        if draft.customRewriteStyles.isEmpty {
            let empty = panelLabel(
                t("Своих режимов пока нет — нажмите «＋ Новый режим», чтобы задать инструкцию, цвет и хоткей.",
                  "No custom modes yet — click '＋ New mode' to add an instruction, color, and shortcut."),
                size: 11.5,
                color: .secondaryLabelColor
            )
            empty.preferredMaxLayoutWidth = 460
            container.addArrangedSubview(empty)
            return container
        }

        for (index, custom) in draft.customRewriteStyles.enumerated() {
            let row = NSStackView()
            row.orientation = .horizontal
            row.alignment = .centerY
            row.spacing = 8

            let swatch = statusDot(color: StateToastController.color(forColorHex: custom.colorHex), size: 11)
            row.addArrangedSubview(swatch)
            row.addArrangedSubview(panelLabel(custom.name, size: 12.5, weight: .medium))

            let hotkeyButton = panelButton(
                custom.hotkeyKeycode == 0
                    ? t("Без хоткея", "No shortcut")
                    : localizedHotkeyName(hotkeyChoice(forKeycode: CGKeyCode(custom.hotkeyKeycode),
                                                       modifiers: CGEventFlags(rawValue: custom.hotkeyModifiers)),
                                          language: language),
                action: #selector(customStyleHotkeyClicked(_:)),
                enabled: serviceOperation == nil
            )
            hotkeyButton.controlSize = .small
            hotkeyButton.tag = index
            row.addArrangedSubview(hotkeyButton)
            row.addArrangedSubview(NSView())

            let editButton = panelButton(t("Изменить", "Edit"), action: #selector(editCustomRewriteStyleClicked(_:)))
            editButton.controlSize = .small
            editButton.tag = index
            row.addArrangedSubview(editButton)

            let deleteButton = panelButton(t("Удалить", "Delete"), action: #selector(deleteCustomRewriteStyleClicked(_:)))
            deleteButton.controlSize = .small
            deleteButton.tag = index
            row.addArrangedSubview(deleteButton)

            container.addArrangedSubview(row)
            row.widthAnchor.constraint(equalTo: container.widthAnchor).isActive = true
        }
        return container
    }

    func presentCustomStyleEditor(_ draft: ControlPanelSettingsDraft, existing: CustomRewriteStyle?) {
        NSApp.activate(ignoringOtherApps: true)
        customStyleEditorWindow?.orderOut(nil)
        customStyleEditorWindow = nil

        customStyleEditorExisting = existing
        customStyleEditorColor = existing?.colorHex ?? Self.customStylePalette[0]
        customStyleEditorHotkey = existing.flatMap { custom in
            guard custom.hotkeyKeycode != 0 else { return nil }
            return hotkeyChoice(forKeycode: CGKeyCode(custom.hotkeyKeycode),
                                modifiers: CGEventFlags(rawValue: custom.hotkeyModifiers))
        }

        let nameField = NSTextField(string: existing?.name ?? "")
        nameField.placeholderString = t("Например: Задача для ассистента", "e.g. Task for my assistant")
        nameField.translatesAutoresizingMaskIntoConstraints = false

        let instruction = NSTextView()
        instruction.isRichText = false
        instruction.font = NSFont.systemFont(ofSize: 12)
        instruction.string = existing?.instruction ?? ""
        instruction.isEditable = true
        instruction.isVerticallyResizable = true
        instruction.textContainer?.widthTracksTextView = true
        instruction.autoresizingMask = [.width]
        let instructionScroll = NSScrollView()
        instructionScroll.hasVerticalScroller = true
        instructionScroll.borderType = .bezelBorder
        instructionScroll.documentView = instruction
        instructionScroll.translatesAutoresizingMaskIntoConstraints = false

        let swatchRow = NSStackView()
        swatchRow.orientation = .horizontal
        swatchRow.spacing = 6
        var swatchButtons: [NSButton] = []
        for (index, hex) in Self.customStylePalette.enumerated() {
            let swatch = NSButton(title: "", target: nil, action: nil)
            swatch.wantsLayer = true
            swatch.layer?.backgroundColor = NSColor(hexString: hex).cgColor
            swatch.layer?.cornerRadius = 6
            swatch.isBordered = false
            swatch.title = ""
            swatch.tag = index
            swatch.translatesAutoresizingMaskIntoConstraints = false
            swatch.widthAnchor.constraint(equalToConstant: 26).isActive = true
            swatch.heightAnchor.constraint(equalToConstant: 26).isActive = true
            swatchRow.addArrangedSubview(swatch)
            swatchButtons.append(swatch)
        }
        customStyleSwatchButtons = swatchButtons
        refreshCustomStyleSwatchSelection()

        let swatchAction = SwatchAction(handler: { [weak self] index in
            guard let self, Self.customStylePalette.indices.contains(index) else { return }
            self.customStyleEditorColor = Self.customStylePalette[index]
            self.refreshCustomStyleSwatchSelection()
        })
        for swatch in swatchButtons {
            swatch.target = swatchAction
            swatch.action = #selector(SwatchAction.swatchClicked(_:))
            objc_setAssociatedObject(swatch, &SwatchAction.associationKey, swatchAction, .OBJC_ASSOCIATION_RETAIN)
        }

        let hotkeyTitle = customStyleEditorHotkey.map { localizedHotkeyName($0, language: language) }
            ?? t("Не назначен", "Not assigned")
        let hotkeyButton = panelButton(hotkeyTitle, action: #selector(customStyleEditorHotkeyClicked(_:)))
        customStyleEditorHotkeyButton = hotkeyButton

        let content = NSStackView()
        content.orientation = .vertical
        content.alignment = .leading
        content.spacing = 8
        content.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 14, right: 16)
        content.addArrangedSubview(panelLabel(t("Имя режима", "Mode name"), size: 12, weight: .medium, color: .secondaryLabelColor))
        content.addArrangedSubview(nameField)
        content.addArrangedSubview(panelLabel(t("Инструкция для модели (что делать с текстом)", "Model instruction (what to do with the text)"), size: 12, weight: .medium, color: .secondaryLabelColor))
        content.addArrangedSubview(instructionScroll)
        content.addArrangedSubview(panelLabel(t("Цвет уведомления", "Notification color"), size: 12, weight: .medium, color: .secondaryLabelColor))
        content.addArrangedSubview(swatchRow)
        content.addArrangedSubview(panelLabel(t("Хоткей активации режима", "Mode activation hotkey"), size: 12, weight: .medium, color: .secondaryLabelColor))
        content.addArrangedSubview(hotkeyButton)

        let buttonRow = NSStackView()
        buttonRow.orientation = .horizontal
        buttonRow.spacing = 10
        let cancelButton = panelButton(t("Отмена", "Cancel"), action: #selector(customStyleEditorCancelClicked(_:)))
        let saveButton = panelButton(t("Сохранить режим", "Save mode"), action: #selector(customStyleEditorSaveClicked(_:)))
        buttonRow.addArrangedSubview(NSView())
        buttonRow.addArrangedSubview(cancelButton)
        buttonRow.addArrangedSubview(saveButton)
        content.addArrangedSubview(buttonRow)

        let editorWindow = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 410, height: 420),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        editorWindow.title = existing == nil
            ? t("Новый режим рерайта", "New rewrite mode")
            : t("Изменить режим рерайта", "Edit rewrite mode")
        editorWindow.isReleasedWhenClosed = false
        editorWindow.contentView = content

        NSLayoutConstraint.activate([
            nameField.widthAnchor.constraint(equalTo: content.widthAnchor, constant: -32),
            instructionScroll.widthAnchor.constraint(equalTo: content.widthAnchor, constant: -32),
            instructionScroll.heightAnchor.constraint(equalToConstant: 92),
            swatchRow.widthAnchor.constraint(equalTo: content.widthAnchor, constant: -32),
            buttonRow.widthAnchor.constraint(equalTo: content.widthAnchor, constant: -32),
        ])

        customStyleEditorNameField = nameField
        customStyleEditorInstructionView = instruction
        customStyleEditorWindow = editorWindow

        if let mainFrame = window?.frame {
            let x = mainFrame.midX - editorWindow.frame.width / 2
            let y = mainFrame.midY - editorWindow.frame.height / 2
            editorWindow.setFrameOrigin(NSPoint(x: x, y: y))
        } else {
            editorWindow.center()
        }
        editorWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        editorWindow.makeFirstResponder(nameField)
    }

    func refreshCustomStyleSwatchSelection() {
        for (index, button) in customStyleSwatchButtons.enumerated() {
            let selected = Self.customStylePalette.indices.contains(index)
                && Self.customStylePalette[index] == customStyleEditorColor
            button.layer?.borderWidth = selected ? 2.5 : 0
            button.layer?.borderColor = NSColor.white.cgColor
        }
    }

    func closeCustomStyleEditor() {
        customStyleEditorWindow?.orderOut(nil)
        customStyleEditorWindow = nil
        customStyleEditorNameField = nil
        customStyleEditorInstructionView = nil
        customStyleEditorHotkeyButton = nil
        customStyleEditorHotkey = nil
        customStyleSwatchButtons = []
    }
}
