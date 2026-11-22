// Lexomorph — reusable macOS Control Panel UI components and localization helpers.

import AppKit
import Foundation

extension LexomorphControlPanelApp {

    func t(_ russian: String, _ english: String) -> String {
        localizedText(russian, english, language: language)
    }

    // MARK: - Section & Card Containers

    func sectionHeader(title: String, subtitle: String? = nil, trailing: NSView? = nil) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 12

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(title, size: 19, weight: .semibold))
        if let subtitle, !subtitle.isEmpty {
            let sub = panelLabel(subtitle, size: 12, color: .secondaryLabelColor)
            sub.preferredMaxLayoutWidth = 460
            text.addArrangedSubview(sub)
        }

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        if let trailing {
            row.addArrangedSubview(trailing)
        }
        return row
    }

    /// Rounded macOS Settings-style card grouping related rows with subtle
    /// hairline dividers between items.
    func settingsCard(title: String? = nil,
                      symbol: String? = nil,
                      symbolColor: NSColor = .secondaryLabelColor,
                      accessory: NSView? = nil,
                      rows: [NSView]) -> NSView {
        let card = compactCard(cornerRadius: 10)
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        stack.translatesAutoresizingMaskIntoConstraints = false

        if let title {
            let header = NSStackView()
            header.orientation = .horizontal
            header.alignment = .centerY
            header.spacing = 7
            if let symbol {
                header.addArrangedSubview(panelSymbol(symbol, color: symbolColor, description: nil, pointSize: 13))
            }
            header.addArrangedSubview(panelLabel(title, size: 12.5, weight: .semibold, color: .secondaryLabelColor))
            header.addArrangedSubview(NSView())
            if let accessory {
                header.addArrangedSubview(accessory)
            }
            stack.addArrangedSubview(header)
            stack.addArrangedSubview(cardDivider())
        }

        for (index, rowView) in rows.enumerated() {
            if index > 0 {
                stack.addArrangedSubview(cardDivider())
            }
            stack.addArrangedSubview(rowView)
        }

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }

        pin(stack, inside: card, horizontal: 15, vertical: 13)
        return card
    }

    func cardDivider() -> NSView {
        let line = NSView()
        line.wantsLayer = true
        line.layer?.backgroundColor = NSColor.separatorColor.withAlphaComponent(0.32).cgColor
        line.translatesAutoresizingMaskIntoConstraints = false
        line.heightAnchor.constraint(equalToConstant: 1).isActive = true
        return line
    }

    func compactCard(cornerRadius: CGFloat = 9) -> NSView {
        let card = NSView()
        card.wantsLayer = true
        card.layer?.cornerRadius = cornerRadius
        card.layer?.backgroundColor = NSColor.controlBackgroundColor.withAlphaComponent(0.72).cgColor
        card.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.38).cgColor
        card.layer?.borderWidth = 1
        card.setContentHuggingPriority(.required, for: .vertical)
        card.setContentCompressionResistancePriority(.required, for: .vertical)
        return card
    }

    // MARK: - Standard Setting Rows

    func toggleRow(title: String,
                   detail: String? = nil,
                   isOn: Bool,
                   enabled: Bool = true,
                   action: Selector,
                   toolTip: String? = nil,
                   hint: String? = nil,
                   leadingBadge: NSView? = nil,
                   trailingAction: NSView? = nil) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10

        if let leadingBadge {
            row.addArrangedSubview(leadingBadge)
        }

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2

        let titleRow = NSStackView()
        titleRow.orientation = .horizontal
        titleRow.alignment = .centerY
        titleRow.spacing = 5
        titleRow.addArrangedSubview(panelLabel(title, size: 13, weight: .semibold,
                                               color: enabled ? .labelColor : .secondaryLabelColor))
        if let hint {
            titleRow.addArrangedSubview(hintIcon(toolTip: hint))
        }
        text.addArrangedSubview(titleRow)

        if let detail, !detail.isEmpty {
            let detailLabel = panelLabel(detail, size: 11.5, color: .secondaryLabelColor)
            detailLabel.preferredMaxLayoutWidth = 370
            text.addArrangedSubview(detailLabel)
        }

        let toggle = NSSwitch()
        toggle.target = self
        toggle.action = action
        toggle.state = isOn ? .on : .off
        toggle.isEnabled = enabled
        toggle.toolTip = toolTip ?? detail
        toggle.setContentHuggingPriority(.required, for: .horizontal)

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        if let trailingAction {
            row.addArrangedSubview(trailingAction)
        }
        row.addArrangedSubview(toggle)
        return row
    }

    func popupRow(title: String,
                  detail: String? = nil,
                  selectedValue: String,
                  options: [(title: String, value: String)],
                  action: Selector,
                  enabled: Bool = true,
                  toolTip: String? = nil,
                  hint: String? = nil,
                  showsHelp: Bool = false) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 12

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2

        let titleRow = NSStackView()
        titleRow.orientation = .horizontal
        titleRow.alignment = .centerY
        titleRow.spacing = 5
        titleRow.addArrangedSubview(panelLabel(title, size: 13, weight: .semibold,
                                               color: enabled ? .labelColor : .secondaryLabelColor))
        if let hint {
            titleRow.addArrangedSubview(hintIcon(toolTip: hint))
        }
        text.addArrangedSubview(titleRow)

        if let detail, !detail.isEmpty {
            let detailLabel = panelLabel(detail, size: 11.5, color: .secondaryLabelColor)
            detailLabel.preferredMaxLayoutWidth = 330
            text.addArrangedSubview(detailLabel)
        }

        let popup = NSPopUpButton()
        popup.target = self
        popup.action = action
        popup.isEnabled = enabled
        popup.toolTip = toolTip
        for option in options {
            popup.addItem(withTitle: option.title)
            popup.lastItem?.representedObject = option.value
        }
        if let item = popup.itemArray.first(where: { $0.representedObject as? String == selectedValue }) {
            popup.select(item)
        }
        popup.setContentHuggingPriority(.required, for: .horizontal)

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(popup)
        if showsHelp {
            row.addArrangedSubview(benchmarkHelpButton())
        }
        return row
    }

    func hotkeyRow(title: String,
                   detail: String? = nil,
                   shortcut: HotkeyChoice,
                   kind: ControlPanelShortcutKind,
                   toolTip: String) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 12

        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(title, size: 13, weight: .semibold))
        if let detail, !detail.isEmpty {
            let sub = panelLabel(detail, size: 11.5, color: .secondaryLabelColor)
            sub.preferredMaxLayoutWidth = 310
            text.addArrangedSubview(sub)
        }

        row.addArrangedSubview(text)
        row.addArrangedSubview(NSView())
        let button = panelButton(localizedHotkeyName(shortcut, language: language),
                                 action: #selector(recordDictationShortcutClicked(_:)),
                                 enabled: serviceOperation == nil,
                                 toolTip: toolTip)
        button.tag = kind.rawValue
        button.controlSize = .regular
        button.setContentHuggingPriority(.required, for: .horizontal)
        button.widthAnchor.constraint(equalToConstant: 184).isActive = true
        row.addArrangedSubview(button)
        return row
    }

    func disclosureToggleButton(title: String, expanded: Bool, action: Selector) -> NSButton {
        let chevron = expanded ? "▾" : "▸"
        let button = NSButton(title: "\(chevron) \(title)", target: self, action: action)
        button.bezelStyle = .inline
        button.isBordered = false
        button.font = .systemFont(ofSize: 12, weight: .medium)
        button.contentTintColor = .controlAccentColor
        button.setContentHuggingPriority(.required, for: .horizontal)
        return button
    }

    func linkButton(_ title: String, action: Selector, tag: Int = 0, toolTip: String? = nil) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .inline
        button.isBordered = false
        button.font = .systemFont(ofSize: 11.5, weight: .medium)
        button.contentTintColor = .controlAccentColor
        button.tag = tag
        button.toolTip = toolTip
        button.setContentHuggingPriority(.required, for: .horizontal)
        return button
    }

    func hintIcon(toolTip: String) -> NSView {
        let view = panelSymbol("info.circle", color: .tertiaryLabelColor, description: nil, pointSize: 12)
        view.toolTip = toolTip
        return view
    }

    func chipBadge(text: String, symbol: String? = nil, color: NSColor = .secondaryLabelColor) -> NSView {
        let container = NSView()
        container.wantsLayer = true
        container.layer?.cornerRadius = 6
        container.layer?.backgroundColor = color.withAlphaComponent(0.11).cgColor

        let stack = NSStackView()
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 4
        stack.translatesAutoresizingMaskIntoConstraints = false
        if let symbol {
            stack.addArrangedSubview(panelSymbol(symbol, color: color, description: nil, pointSize: 10.5))
        }
        let label = panelLabel(text, size: 11, weight: .medium, color: color)
        label.setContentHuggingPriority(.required, for: .horizontal)
        stack.addArrangedSubview(label)

        pin(stack, inside: container, horizontal: 7, vertical: 3)
        container.setContentHuggingPriority(.required, for: .horizontal)
        return container
    }

    /// Tinted compatibility / warning notice banner placed inline beneath
    /// hardware-gated settings so the user clearly understands why a feature is
    /// unavailable or limited on their machine.
    func compatibilityBanner(symbol: String,
                             color: NSColor,
                             title: String,
                             detail: String) -> NSView {
        let container = NSView()
        container.wantsLayer = true
        container.layer?.cornerRadius = 8
        container.layer?.backgroundColor = color.withAlphaComponent(0.09).cgColor
        container.layer?.borderColor = color.withAlphaComponent(0.28).cgColor
        container.layer?.borderWidth = 1
        container.setContentHuggingPriority(.required, for: .vertical)
        container.setContentCompressionResistancePriority(.required, for: .vertical)

        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .top
        row.spacing = 9
        row.translatesAutoresizingMaskIntoConstraints = false

        let icon = panelSymbol(symbol, color: color, description: nil, pointSize: 13.5)
        let text = NSStackView()
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 2
        text.addArrangedSubview(panelLabel(title, size: 12, weight: .semibold, color: .labelColor))
        let detailLabel = panelLabel(detail, size: 11.5, color: .secondaryLabelColor)
        detailLabel.preferredMaxLayoutWidth = 440
        text.addArrangedSubview(detailLabel)

        row.addArrangedSubview(icon)
        row.addArrangedSubview(text)
        pin(row, inside: container, horizontal: 11, vertical: 9)
        return container
    }

    func colorDotImage(hex: String) -> NSImage {
        let size = NSSize(width: 12, height: 12)
        let image = NSImage(size: size, flipped: false) { _ in
            let rect = NSRect(x: 2, y: 2, width: 8, height: 8)
            StateToastController.color(forColorHex: hex).setFill()
            NSBezierPath(ovalIn: rect).fill()
            return true
        }
        image.isTemplate = false
        return image
    }

    func statusDot(color: NSColor, size: CGFloat = 8) -> NSView {
        let dot = NSView()
        dot.wantsLayer = true
        dot.layer?.cornerRadius = size / 2
        dot.layer?.backgroundColor = color.cgColor
        dot.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            dot.widthAnchor.constraint(equalToConstant: size),
            dot.heightAnchor.constraint(equalToConstant: size),
        ])
        return dot
    }

    // MARK: - Basic Primitives

    func panelLabel(_ text: String,
                    size: CGFloat,
                    weight: NSFont.Weight = .regular,
                    color: NSColor = .labelColor) -> NSTextField {
        let label = NSTextField(labelWithString: text)
        label.font = .systemFont(ofSize: size, weight: weight)
        label.textColor = color
        label.lineBreakMode = .byWordWrapping
        label.maximumNumberOfLines = 0
        return label
    }

    func panelButton(_ title: String,
                     action: Selector,
                     enabled: Bool = true,
                     toolTip: String? = nil) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        button.controlSize = .regular
        button.isEnabled = enabled
        button.toolTip = toolTip
        button.setContentHuggingPriority(.required, for: .horizontal)
        return button
    }

    func compactIconButton(symbol: String,
                           accessibilityTitle: String,
                           toolTip: String,
                           action: Selector,
                           enabled: Bool = true) -> NSButton {
        let button = NSButton(image: NSImage(systemSymbolName: symbol,
                                             accessibilityDescription: accessibilityTitle) ?? NSImage(),
                              target: self,
                              action: action)
        button.bezelStyle = .texturedRounded
        button.controlSize = .small
        button.isEnabled = enabled
        button.toolTip = toolTip
        button.setAccessibilityLabel(accessibilityTitle)
        button.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            button.widthAnchor.constraint(equalToConstant: 28),
            button.heightAnchor.constraint(equalToConstant: 24),
        ])
        return button
    }

    func panelSymbol(_ name: String,
                     color: NSColor,
                     description: String?,
                     pointSize: CGFloat) -> NSImageView {
        let image = NSImage(systemSymbolName: name, accessibilityDescription: description) ?? NSImage()
        let view = NSImageView(image: image)
        view.contentTintColor = color
        view.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: pointSize, weight: .medium)
        view.setContentHuggingPriority(.required, for: .horizontal)
        return view
    }

    func pin(_ view: NSView,
             inside container: NSView,
             horizontal: CGFloat,
             vertical: CGFloat) {
        container.addSubview(view)
        NSLayoutConstraint.activate([
            view.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: horizontal),
            view.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -horizontal),
            view.topAnchor.constraint(equalTo: container.topAnchor, constant: vertical),
            view.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -vertical),
        ])
    }

    func separator() -> NSBox {
        let box = NSBox()
        box.boxType = .separator
        return box
    }

    func benchmarkHelpButton() -> NSButton {
        let button = NSButton(title: "?", target: self, action: #selector(showBenchmarkHelp(_:)))
        button.bezelStyle = .circular
        button.controlSize = .small
        button.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        button.toolTip = t("Результаты замеров моделей (бенчмарк).",
                           "Model benchmark results.")
        button.setContentHuggingPriority(.required, for: .horizontal)
        return button
    }

    // MARK: - Localization Helpers

    func localizedSectionTitle(_ section: ControlPanelSection) -> String {
        switch section {
        case .overview: return t("Главная", "Overview")
        case .statistics: return t("Статистика", "Statistics")
        case .dictation: return t("Диктовка", "Dictation")
        case .text: return t("Текст и словарь", "Text & Vocabulary")
        case .ai: return t("AI-обработка", "AI Processing")
        case .audio: return t("Аудио", "Audio")
        case .appearance: return t("Индикатор", "Indicator")
        case .system: return t("Система", "System")
        }
    }

    func localizedAISubsectionTitle(_ sub: AISubsection) -> String {
        switch sub {
        case .correction: return t("Коррекция", "Correction")
        case .rewrite: return t("Рерайт", "Rewrite")
        case .punctuation: return t("Пунктуация", "Punctuation")
        case .shortcutsAndHardware: return t("Хоткеи и сеть", "Shortcuts & GPU")
        }
    }

    func localizedDictationLanguageName(_ lang: DictationLanguage) -> String {
        if language == .russian {
            switch lang {
            case .auto: return "Автоопределение"
            case .russian: return "Русский"
            case .english: return "Английский"
            case .spanish: return "Испанский"
            case .french: return "Французский"
            case .german: return "Немецкий"
            case .italian: return "Итальянский"
            case .portuguese: return "Португальский"
            case .romanian: return "Румынский"
            case .polish: return "Польский"
            case .czech: return "Чешский"
            case .slovak: return "Словацкий"
            case .slovenian: return "Словенский"
            case .croatian: return "Хорватский"
            case .bosnian: return "Боснийский"
            case .ukrainian: return "Украинский"
            case .belarusian: return "Белорусский"
            case .bulgarian: return "Болгарский"
            case .serbian: return "Сербский"
            }
        }
        return DICTATION_LANGUAGE_DISPLAY[lang] ?? lang.rawValue
    }

    func localizedRewriteStyleLongName(_ style: RewriteStyle) -> String {
        switch style {
        case .polish: return t("Причесать текст", "Polish text")
        case .structuredTask: return t("Структурировать в задачу", "Structure into a task")
        case .official: return t("Официальный стиль", "Official style")
        }
    }

    func localizedRewriteStyleShortName(_ style: RewriteStyle) -> String {
        switch style {
        case .polish: return t("Причесать", "Polish")
        case .structuredTask: return t("Задача", "Task")
        case .official: return t("Официальный", "Official")
        }
    }

    func localizedCompletionBehavior(_ behavior: DictationCompletionBehavior) -> String {
        switch behavior {
        case .insert: return t("Вставить", "Insert")
        case .insertAndEnter: return t("Вставить + Enter", "Insert + Enter")
        }
    }

    func localizedTriggerModeShort(_ mode: TriggerMode) -> String {
        switch mode {
        case .hold: return t("Удерживать", "Hold")
        case .toggle: return t("Нажать", "Toggle")
        }
    }

    func permissionTitle(_ permission: Permission) -> String {
        switch permission {
        case .microphone: return t("Микрофон", "Microphone")
        case .accessibility: return t("Универсальный доступ", "Accessibility")
        case .inputMonitoring: return t("Мониторинг ввода", "Input Monitoring")
        }
    }

    func permissionDetail(_ permission: Permission) -> String {
        switch permission {
        case .microphone:
            return t("Запись голоса только во время активной диктовки.",
                     "Lets the service hear your voice while dictation is active.")
        case .accessibility:
            return t("Поиск активного поля и вставка готового текста.",
                     "Lets the service find the active field and insert text.")
        case .inputMonitoring:
            return t("Глобальное распознавание выбранного сочетания клавиш.",
                     "Lets the service detect your shortcut globally.")
        }
    }

    func localizedColorName(_ color: RecordingHUDAccentColor) -> String {
        guard language == .russian else { return color.displayName }
        switch color {
        case .red: return "Красный"
        case .orange: return "Оранжевый"
        case .pink: return "Розовый"
        case .purple: return "Фиолетовый"
        case .blue: return "Синий"
        case .cyan: return "Голубой"
        case .green: return "Зелёный"
        case .white: return "Белый"
        case .contrast: return "Контрастный"
        }
    }

    func localizedBackgroundName(_ style: RecordingHUDBackgroundStyle) -> String {
        guard language == .russian else { return style.displayName }
        switch style {
        case .system: return "Как в системе"
        case .dark: return "Тёмный"
        case .light: return "Светлый"
        }
    }

    func localizedHUDSizeName(_ size: RecordingHUDSize) -> String {
        guard language == .russian else { return size.displayName }
        switch size {
        case .compact: return "Компактная"
        case .standard: return "Обычная"
        case .large: return "Крупная"
        }
    }

    func localizedDisplayModeName(_ mode: RecordingHUDDisplayMode) -> String {
        guard language == .russian else { return mode.displayName }
        switch mode {
        case .levelBars: return "Полоски уровня"
        case .timerOutline: return "Таймер"
        }
    }

    func displayStatus(_ raw: String) -> String {
        switch raw {
        case "ready", "recording", "transcribing": return t("Работает", "Running")
        case "starting": return t("Запускается", "Starting")
        case "needs_permissions": return t("Нужен доступ", "Needs Access")
        case "error": return t("Ошибка", "Error")
        case "stopping": return t("Останавливается", "Stopping")
        case "stopped": return t("Остановлена", "Stopped")
        default: return raw.capitalized
        }
    }

    func colorForStatus(_ raw: String) -> NSColor {
        switch raw {
        case "ready", "recording", "transcribing": return .systemGreen
        case "starting", "needs_permissions", "stopping": return .systemOrange
        case "error", "stopped": return .systemRed
        default: return .secondaryLabelColor
        }
    }

    func localizedServiceDetail(_ state: AgentRuntimeState) -> String {
        switch state.status {
        case "ready", "recording", "transcribing":
            return t("Фоновая служба готова к диктовке.",
                     "The background service is ready for dictation.")
        case "starting":
            if state.detail.hasPrefix("Downloading speech model") {
                if let percentRange = state.detail.range(of: "\\d+%", options: .regularExpression) {
                    let percent = state.detail[percentRange]
                    return t("Скачиваю языковую модель… \(percent)", "Downloading speech model… \(percent)")
                }
                return t("Скачиваю языковую модель…", "Downloading speech model…")
            } else if state.detail.hasPrefix("Checking speech model") {
                return t("Проверяю список файлов модели…", "Checking speech model files…")
            } else if state.detail.hasPrefix("Preparing speech model") {
                return t("Подготавливаю модель…", "Preparing speech model…")
            } else if state.detail.hasPrefix("Loading cached speech model") {
                return t("Загружаю модель из кэша…", "Loading cached speech model…")
            } else if state.detail.hasPrefix("Loading speech model") {
                return t("Загружаю языковую модель…", "Loading speech model…")
            }
            return t("Запускаю службу диктовки…", "Starting dictation service…")
        case "needs_permissions":
            return t("Выдайте недостающие разрешения ниже.", "Grant the missing permissions below.")
        case "stopped":
            return t("Фоновая служба остановлена.", "The background service is stopped.")
        case "error":
            return t("Служба сообщила об ошибке: \(state.detail)", "Service error: \(state.detail)")
        default:
            return state.detail
        }
    }

    func operationTitle(_ operation: ControlPanelServiceOperation) -> String {
        switch operation {
        case .starting: return t("Запускаю службу диктовки", "Starting dictation service")
        case .restarting: return t("Перезапускаю фоновую службу", "Restarting background service")
        case .stopping: return t("Останавливаю фоновую службу", "Stopping background service")
        case .applyingSettings: return t("Применяю настройки и перезапускаю службу",
                                         "Applying settings and restarting service")
        }
    }

    func operationDetail(_ operation: ControlPanelServiceOperation) -> String {
        switch operation {
        case .starting:
            return t("Подключаю глобальный хоткей и локальную модель. Обычно 1–3 секунды.",
                     "Enabling the global shortcut and local model. Usually 1–3 seconds.")
        case .restarting, .applyingSettings:
            return t("Диктовка временно недоступна, пока новый воркер запускается.",
                     "Dictation is briefly unavailable while the new worker starts.")
        case .stopping:
            return t("Хоткей перестанет работать, но настройки и история сохранятся.",
                     "The shortcut will stop; settings and history remain saved.")
        }
    }

    func servicePresentation(running: Bool,
                             state: AgentRuntimeState?) -> (status: String, detail: String, color: NSColor) {
        if let operation = serviceOperation {
            return (operationTitle(operation), operationDetail(operation), .systemBlue)
        }
        if running, let state {
            if ["ready", "recording", "transcribing"].contains(state.status) {
                return (t("Работает", "Running"),
                        t("Фоновая служба готова к диктовке.", "The background service is ready for dictation."),
                        .systemGreen)
            }
            return (displayStatus(state.status), localizedServiceDetail(state), colorForStatus(state.status))
        }
        if running {
            return (t("Запускается", "Starting"),
                    t("Фоновый процесс запущен и готовит модель.", "The background process is preparing the model."),
                    .systemOrange)
        }
        return (settings.agentEnabled ? t("Остановлена", "Stopped") : t("Выключена", "Off"),
                t("Хоткей не работает, пока служба не запущена.",
                  "The shortcut is unavailable until the service starts."),
                settings.agentEnabled ? .systemRed : .secondaryLabelColor)
    }

    func privacyInfoView() -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        let icon = panelSymbol("lock.shield.fill", color: .secondaryLabelColor, description: nil, pointSize: 13)
        row.addArrangedSubview(icon)
        let label = panelLabel(
            t("Аудио и распознавание остаются на Mac. При входе в аккаунт синхронизируются только словарь, термины, режимы, промпты и статистика.",
              "Audio and transcription stay on this Mac. Signing in syncs only your vocabulary, terms, modes, prompts, and usage statistics."),
            size: 11.5,
            color: .secondaryLabelColor
        )
        label.preferredMaxLayoutWidth = 480
        row.addArrangedSubview(label)
        return row
    }
}
